"""
Mini-K8s Scheduler
简化版调度器，定期扫描未绑定节点的Pod并分配到可用Node
使用轮转调度算法确保负载均衡
"""
import time
import requests
from config import Config

class Scheduler:
    def __init__(self, apiserver_host="localhost", interval=5):
        self.apiserver_host = apiserver_host
        self.base_url = f"http://{apiserver_host}:5050"
        self.interval = interval  # 调度周期（秒）
        print(f"[INFO]Scheduler initialized, ApiServer: {self.base_url}")

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
                        else:
                            print(f"[WARN]分配失败: {resp.status_code} {resp.text}")
                    except Exception as e:
                        print(f"[ERROR]调度Pod失败: {e}")
            time.sleep(self.interval)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mini-K8s Scheduler")
    parser.add_argument("--apiserver", type=str, default="localhost", help="ApiServer地址")
    parser.add_argument("--interval", type=int, default=5, help="调度周期(秒)")
    args = parser.parse_args()
    
    scheduler = Scheduler(apiserver_host=args.apiserver, interval=args.interval)
    scheduler.schedule()
