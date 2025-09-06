import requests
import json
import time
from threading import Thread
from uuid import uuid1

from config import Config
from pod import Pod


class Kubelet:
    def __init__(self, kubelet_config):
        """
        初始化Kubelet
        
        Args:
            kubelet_config: 包含以下字段的配置字典
                - node_id: 节点ID
                - apiserver: ApiServer地址
                - subnet_ip: 子网IP
        """
        self.node_id = kubelet_config.get("node_id")
        self.apiserver_host = kubelet_config.get("apiserver", "localhost")
        self.subnet_ip = kubelet_config.get("subnet_ip")
        
        # Pod缓存 - 存储当前节点上的所有Pod
        self.pods_cache = {}  # {namespace/name: Pod}
        
        # 运行状态
        self.running = False
        
        print(f"[INFO]Kubelet initialized for node {self.node_id}")
        
    def start(self):
        """启动Kubelet"""
        self.running = True
        print(f"[INFO]Starting Kubelet on node {self.node_id}")
        
        # 启动监控循环
        monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()
        
        print(f"[INFO]Kubelet started successfully")
        
    def stop(self):
        """停止Kubelet"""
        self.running = False
        print(f"[INFO]Kubelet stopped")
        
    def create_pod(self, pod_yaml):
        """
        创建Pod
        
        Args:
            pod_yaml: Pod的YAML配置
            
        Returns:
            bool: 创建是否成功
        """
        try:
            # 创建Pod实例
            pod = Pod(pod_yaml)
            pod_key = f"{pod.namespace}/{pod.name}"
            
            # 检查是否已存在
            if pod_key in self.pods_cache:
                print(f"[WARNING]Pod {pod_key} already exists on this node")
                return False
            
            # 设置节点信息
            pod.node_name = self.node_id
            
            # 首先向ApiServer注册Pod
            pod_data = {
                "apiVersion": pod_yaml.get("apiVersion", "v1"),
                "kind": "Pod",
                "metadata": {
                    "name": pod.name,
                    "namespace": pod.namespace,
                    "labels": pod_yaml.get("metadata", {}).get("labels", {})
                },
                "spec": pod_yaml.get("spec", {}),
                "status": Config.POD_STATUS_CREATING,
                "node": self.node_id,
                "ip": "",
                "containers": len(pod_yaml.get("spec", {}).get("containers", []))
            }
            
            # 注册到ApiServer
            try:
                api_url = f"http://{self.apiserver_host}:5050/api/v1/namespaces/{pod.namespace}/pods/{pod.name}"
                response = requests.post(api_url, json=pod_data, timeout=5)
                if response.status_code not in [200, 201, 409]:  # 409表示已存在，可以忽略
                    print(f"[WARNING]Failed to register Pod to ApiServer: {response.status_code}")
            except Exception as e:
                print(f"[WARNING]Failed to register Pod to ApiServer: {e}")
            
            # 创建Pod
            success = pod.create()
            if success:
                # 添加到缓存
                self.pods_cache[pod_key] = pod
                
                # 向ApiServer报告状态
                self._report_pod_status(pod)
                
                print(f"[INFO]Pod {pod_key} created successfully on node {self.node_id}")
                return True
            else:
                print(f"[ERROR]Failed to create Pod {pod_key}")
                return False
                
        except Exception as e:
            print(f"[ERROR]Failed to create Pod: {e}")
            return False
    
    def delete_pod(self, namespace, name):
        """
        删除Pod
        
        Args:
            namespace: Pod命名空间
            name: Pod名称
            
        Returns:
            bool: 删除是否成功
        """
        pod_key = f"{namespace}/{name}"
        
        if pod_key not in self.pods_cache:
            print(f"[WARNING]Pod {pod_key} not found on this node")
            return False
            
        try:
            pod = self.pods_cache[pod_key]
            
            # 删除Pod
            success = pod.delete()
            if success:
                # 从缓存移除
                del self.pods_cache[pod_key]
                
                print(f"[INFO]Pod {pod_key} deleted successfully from node {self.node_id}")
                return True
            else:
                print(f"[ERROR]Failed to delete Pod {pod_key}")
                return False
                
        except Exception as e:
            print(f"[ERROR]Failed to delete Pod {pod_key}: {e}")
            return False
    
    def get_pod_status(self, namespace, name):
        """
        获取Pod状态
        
        Args:
            namespace: Pod命名空间
            name: Pod名称
            
        Returns:
            dict: Pod状态信息，如果不存在则返回None
        """
        pod_key = f"{namespace}/{name}"
        
        if pod_key in self.pods_cache:
            return self.pods_cache[pod_key].get_status()
        else:
            return None
    
    def list_pods(self):
        """
        列出当前节点上的所有Pod
        
        Returns:
            list: Pod状态信息列表
        """
        pods_info = []
        
        for pod_key, pod in self.pods_cache.items():
            pods_info.append(pod.get_status())
            
        return pods_info
    
    def _monitor_loop(self):
        """监控循环 - 定期检查Pod状态并上报"""
        print(f"[INFO]Starting monitor loop for node {self.node_id}")
        
        while self.running:
            try:
                # 检查所有Pod状态
                for pod_key, pod in list(self.pods_cache.items()):
                    # 简单的健康检查（实际实现可以更复杂）
                    old_status = pod.status
                    # 这里可以添加实际的容器状态检查逻辑
                    
                    # 如果状态有变化，报告给ApiServer
                    if hasattr(pod, '_last_reported_status') and pod.status != pod._last_reported_status:
                        self._report_pod_status(pod)
                        pod._last_reported_status = pod.status
                    elif not hasattr(pod, '_last_reported_status'):
                        pod._last_reported_status = pod.status
                
                # 休眠一段时间再检查
                time.sleep(10)
                
            except Exception as e:
                print(f"[ERROR]Error in monitor loop: {e}")
                time.sleep(5)
    
    def _report_pod_status(self, pod):
        """
        向ApiServer报告Pod状态
        
        Args:
            pod: Pod实例
        """
        try:
            # 构建状态更新URL
            url = f"http://{self.apiserver_host}:5050/api/v1/namespaces/{pod.namespace}/pods/{pod.name}/status"
            
            status_data = {
                "status": pod.status,
                "ip": pod.subnet_ip,
                "node": self.node_id,
                "containers": 1,
                "phase": pod.status
            }
            
            # 发送状态更新（简化实现，实际可能需要更复杂的错误处理）
            response = requests.put(url, json=status_data, timeout=5)
            
            if response.status_code == 200:
                print(f"[DEBUG]Pod {pod.namespace}/{pod.name} status reported: {pod.status}")
            else:
                print(f"[WARNING]Failed to report Pod status: {response.status_code}")
                
        except Exception as e:
            print(f"[ERROR]Failed to report Pod status to ApiServer: {e}")


if __name__ == "__main__":
    print("[INFO]Testing Kubelet...")
    
    import yaml
    import argparse
    import os
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Test Mini-K8s Kubelet.")
    parser.add_argument("--node-id", type=str, default="node-1", 
                       help="Node ID for this kubelet")
    parser.add_argument("--apiserver", type=str, default="localhost",
                       help="ApiServer address")
    parser.add_argument("--pod-config", type=str, default="./testFile/pod-test.yaml",
                       help="Test Pod config file")
    args = parser.parse_args()
    
    # 创建Kubelet配置
    kubelet_config = {
        "node_id": args.node_id,
        "apiserver": args.apiserver,
        "subnet_ip": "10.244.1.0/24"
    }
    
    # 创建Kubelet实例
    kubelet = Kubelet(kubelet_config)
    kubelet.start()
    
    # 测试创建Pod
    if os.path.exists(args.pod_config):
        with open(args.pod_config, "r", encoding="utf-8") as f:
            pod_yaml = yaml.safe_load(f)
        
        print(f"[INFO]Testing Pod creation...")
        success = kubelet.create_pod(pod_yaml)
        
        if success:
            print(f"[INFO]Pod created, current pods: {len(kubelet.pods_cache)}")
            
            # 列出Pod
            pods = kubelet.list_pods()
            for pod_info in pods:
                print(f"[INFO]Pod: {pod_info}")
                
            # 等待一段时间观察监控
            print("[INFO]Monitoring for 30 seconds...")
            time.sleep(30)
            
            # 删除测试Pod
            pod_namespace = pod_yaml.get("metadata", {}).get("namespace", "default")
            pod_name = pod_yaml.get("metadata", {}).get("name")
            
            if pod_name:
                print(f"[INFO]Deleting test Pod {pod_namespace}/{pod_name}")
                kubelet.delete_pod(pod_namespace, pod_name)
        else:
            print("[ERROR]Failed to create test Pod")
    else:
        print(f"[ERROR]Pod config file not found: {args.pod_config}")
    
    # 停止Kubelet
    kubelet.stop()
