import time
import requests
import json
from config import Config
from confluent_kafka import Producer

class Scheduler:
    def __init__(self, apiserver_host="localhost", interval=5, kafka_bootstrap_servers=None):
        self.apiserver_host = apiserver_host
        self.base_url = f"http://{apiserver_host}:5050"
        self.interval = interval  # 调度周期（秒）
        
        # 初始化Kafka Producer - 使用配置文件中的默认值
        kafka_servers = kafka_bootstrap_servers or Config.KAFKA_BOOTSTRAP_SERVERS
        self.kafka_config = {
            'bootstrap.servers': kafka_servers,
            'client.id': 'mini-k8s-scheduler'
        }
        self.producer = Producer(self.kafka_config)
        
        print(f"[INFO]Scheduler initialized, ApiServer: {self.base_url}, Kafka: {kafka_servers}")

    def get_all_nodes(self):
        url = f"{self.base_url}/api/v1/nodes"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                return [n["metadata"]["name"] for n in resp.json().get("nodes", [])]
        except Exception as e:
            print(f"[ERROR]获取Node失败: {e}")
        return []

    def get_all_pods(self):
        url = f"{self.base_url}/api/v1/pods"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                return resp.json().get("pods", [])
        except Exception as e:
            print(f"[ERROR]获取Pod失败: {e}")
        return []

    def schedule(self):
        """调度主循环"""
        print("[INFO]Scheduler started.")
        while True:
            nodes = self.get_all_nodes()
            pods = self.get_all_pods()
            if not nodes:
                print("[WARN]无可用Node，跳过本轮调度")
                time.sleep(self.interval)
                continue
                
            # 处理删除的Pod
            self._handle_pod_deletions(pods)
            
            # 过滤未绑定节点的Pod
            unscheduled = [p for p in pods if not p.get("node") or p.get("node") == ""]
            
            print(f"[INFO]发现 {len(unscheduled)} 个未调度Pod")
            
            if len(unscheduled) > 0:
                # 统计每个节点当前的Pod数量（一次性计算）
                node_pod_count = {}
                for node in nodes:
                    node_pod_count[node] = 0
                
                # 统计已调度Pod的节点分布
                for p in pods:
                    p_node = p.get("node", "")
                    if p_node and p_node in node_pod_count:
                        node_pod_count[p_node] += 1
                
                print(f"[INFO]当前节点负载: {dict(node_pod_count)}")
                
                # 基于负载的调度 - 选择Pod数量最少的节点
                for pod in unscheduled:
                    pod_ns = pod.get("metadata", {}).get("namespace", "default")
                    pod_name = pod.get("metadata", {}).get("name")
                    
                    # 选择Pod数量最少的节点
                    target_node = min(node_pod_count.keys(), key=lambda n: node_pod_count[n])
                    current_load = node_pod_count[target_node]
                    
                    print(f"[INFO]调度Pod {pod_ns}/{pod_name} -> Node {target_node} (当前负载: {current_load})")
                    
                    # 更新Pod的node字段
                    patch = {"node": target_node}
                    try:
                        url = f"{self.base_url}/api/v1/namespaces/{pod_ns}/pods/{pod_name}"
                        resp = requests.put(url, json=patch, timeout=3)
                        if resp.status_code == 200:
                            print(f"[INFO]Pod {pod_ns}/{pod_name} 成功分配到 {target_node}")
                            # 立即更新本地计数，确保下一个Pod调度时考虑到这个变化
                            node_pod_count[target_node] += 1
                            
                            # 发送Kafka消息通知Kubelet
                            self._send_pod_assignment(target_node, pod)
                            
                        else:
                            print(f"[WARN]分配失败: {resp.status_code} {resp.text}")
                    except Exception as e:
                        print(f"[ERROR]调度Pod失败: {e}")
            time.sleep(self.interval)
    
    def _handle_pod_deletions(self, pods):
        """
        处理标记为删除的Pod
        
        Args:
            pods: 所有Pod的列表
        """
        # 查找标记为删除的Pod（status为"DELETING"或有deletionTimestamp的Pod）
        pods_to_delete = []
        for pod in pods:
            # 检查删除标记
            if pod.get("status") == "DELETING":
                pods_to_delete.append(pod)
            elif pod.get("metadata", {}).get("deletionTimestamp"):
                pods_to_delete.append(pod)
        
        if pods_to_delete:
            print(f"[INFO]发现 {len(pods_to_delete)} 个待删除Pod")
            
        for pod in pods_to_delete:
            pod_ns = pod.get("metadata", {}).get("namespace", "default")
            pod_name = pod.get("metadata", {}).get("name")
            target_node = pod.get("node")
            
            if target_node:
                print(f"[INFO]发送删除消息: Pod {pod_ns}/{pod_name} -> Node {target_node}")
                self._send_pod_deletion(target_node, pod)
            else:
                print(f"[WARNING]Pod {pod_ns}/{pod_name} 未分配到节点，跳过删除通知")
    
    def _send_pod_deletion(self, target_node, pod_data):
        """
        发送Pod删除消息到Kafka
        
        Args:
            target_node: 目标节点名称
            pod_data: Pod数据字典类型
        """
        try:
            pod_ns = pod_data.get("metadata", {}).get("namespace", "default")
            pod_name = pod_data.get("metadata", {}).get("name")
            
            # 构造删除消息
            message = {
                "action": "delete_pod",
                "node": target_node,
                "pod_info": {
                    "namespace": pod_ns,
                    "name": pod_name
                },
                "timestamp": time.time()
            }
            
            # 发送到指定节点的topic
            topic = Config.KUBELET_TOPIC.format(node_name=target_node)
            message_json = json.dumps(message)
            
            self.producer.produce(topic, message_json)
            self.producer.flush()  # 确保消息被发送
            
            print(f"[INFO]Kafka删除消息已发送: Pod {pod_ns}/{pod_name} -> Topic {topic}")
            
            # 发送消息后，立即从etcd删除Pod记录
            self._remove_pod_from_etcd(pod_ns, pod_name)
            
        except Exception as e:
            print(f"[ERROR]发送Kafka删除消息失败: {e}")
    
    def _remove_pod_from_etcd(self, namespace, pod_name):
        """
        从etcd中删除Pod记录
        
        Args:
            namespace: Pod命名空间
            pod_name: Pod名称
        """
        try:
            url = f"{self.base_url}/api/v1/namespaces/{namespace}/pods/{pod_name}/remove"
            resp = requests.delete(url, timeout=3)
            if resp.status_code == 200:
                print(f"[INFO]Pod {namespace}/{pod_name} 记录已从etcd删除")
            else:
                print(f"[WARNING]删除Pod记录失败: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"[ERROR]删除Pod记录失败: {e}")
    
    def _send_pod_assignment(self, target_node, pod_data):
        """
        发送Pod分配消息到Kafka
        
        Args:
            target_node: 目标节点名称
            pod_data: Pod数据字典类型
        """
        try:
            # 构造消息
            message = {
                "action": "create_pod",
                "node": target_node,
                "pod_data": pod_data,
                "timestamp": time.time()
            }
            
            # 发送到指定节点的topic
            topic = Config.KUBELET_TOPIC.format(node_name=target_node)
            message_json = json.dumps(message)
            
            self.producer.produce(topic, message_json)
            self.producer.flush()  # 确保消息被发送
            
            pod_ns = pod_data.get("metadata", {}).get("namespace", "default")
            pod_name = pod_data.get("metadata", {}).get("name")
            print(f"[INFO]Kafka消息已发送: Pod {pod_ns}/{pod_name} -> Topic {topic}")
            
        except Exception as e:
            print(f"[ERROR]发送Kafka消息失败: {e}")
            
    def close(self):
        """关闭资源"""
        if hasattr(self, 'producer'):
            self.producer.flush()
            print("[INFO]Scheduler resources closed")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mini-K8s Scheduler")
    parser.add_argument("--apiserver", type=str, default="localhost", help="ApiServer地址")
    parser.add_argument("--interval", type=int, default=5, help="调度周期(秒)")
    parser.add_argument("--kafka", type=str, default=None, 
                       help=f"Kafka Bootstrap Servers (default: {Config.KAFKA_BOOTSTRAP_SERVERS})")
    args = parser.parse_args()
    
    scheduler = Scheduler(apiserver_host=args.apiserver, interval=args.interval, 
                         kafka_bootstrap_servers=args.kafka)
    try:
        scheduler.schedule()
    except KeyboardInterrupt:
        print("[INFO]Stopping scheduler...")
        scheduler.close()
