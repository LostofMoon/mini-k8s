import requests
import os
import time
from uuid import uuid1

from config import Config

class Node:
    def __init__(self, arg):
        self.id = str(uuid1())

        metadata = arg.get("metadata")
        self.name = metadata.get("name")
        
        # 尝试获取apiserver配置，如果没有则使用默认值
        api_server_config = metadata.get("api-server")
        if api_server_config and isinstance(api_server_config, dict):
            self.apiserver = api_server_config.get("ip", "localhost")
        else:
            self.apiserver = "localhost"

        spec = arg.get("spec")
        self.subnet_ip = spec.get("podCIDR")
        self.taints = spec.get("taints")

        # Kafka配置 - 直接使用配置文件中的默认值
        self.kafka_bootstrap_servers = Config.KAFKA_BOOTSTRAP_SERVERS

        self.json = arg

        # 运行时状态
        
        self.kubelet = None

        # TODO: 组件引用（暂时为None，后续完善时再启用）
        self.service_proxy = None
        
    def kubelet_config_args(self):
        """返回kubelet配置参数"""
        return {
            "subnet_ip": self.subnet_ip,
            "apiserver": self.apiserver,
            "node_id": self.id,
            "kafka_bootstrap_servers": self.kafka_bootstrap_servers
        }

    def run(self):
        """启动节点并注册到ApiServer"""
        print(f"[INFO]Starting Node: {self.name}")
        
        # 注册到 API Server
        path = Config.NODE_SPEC_URL.format(node_name=self.name)
        url = f"{Config.SERVER_URI}{path}"
        session = requests.Session()
        register_response = session.post(url, json=self.json)

        if register_response.status_code == 200:
            print(f"[INFO]Node {self.name} successfully registered to ApiServer")
        elif register_response.status_code == 409:
            print(f"[WARNING]Node {self.name} already exists in ApiServer - continuing with existing registration")
        else:
            print(f"[ERROR]Cannot register to ApiServer with code {register_response.status_code}: {register_response.text}")
            return
        
        # 启动组件
        self._start_kubelet()
        
        # TODO: 后续实现
        # self._start_service_proxy()
        
        print(f"[INFO]Node {self.name} is running")
    
    def _start_kubelet(self):
        """启动Kubelet组件"""
        try:
            from kubelet import Kubelet
            
            # 构建Kubelet配置，创建并启动Kubelet
            kubelet_config = {
                "node_id": self.name,
                "apiserver": self.apiserver,
                "subnet_ip": self.subnet_ip,
                "kafka_bootstrap_servers": self.kafka_bootstrap_servers
            }
            self.kubelet = Kubelet(kubelet_config)
            self.kubelet.start()
            
            print(f"[INFO]Kubelet started on node {self.name}")
            
        except Exception as e:
            print(f"[ERROR]Failed to start Kubelet: {e}")
            self.kubelet = None
    
    def stop(self):
        """停止节点及其组件"""
        print(f"[INFO]Stopping Node: {self.name}")
        
        # 停止Kubelet
        if self.kubelet:
            try:
                self.kubelet.stop()
                print(f"[INFO]Kubelet stopped on node {self.name}")
            except Exception as e:
                print(f"[ERROR]Failed to stop Kubelet: {e}")
        
        # 停止Service Proxy (TODO: 后续实现)
        # if self.service_proxy:
        #     self.service_proxy.stop()
        
        print(f"[INFO]Node {self.name} stopped")

if __name__ == "__main__":
    print("[INFO]Starting Node...")

    # 解析命令行参数
    import yaml
    import argparse
    parser = argparse.ArgumentParser(description="Start Mini-K8s Node.")
    parser.add_argument("--config", type=str, default="./testFile/node-1.yaml", help="YAML config file for the node")
    args = parser.parse_args()

    # 读取配置文件
    config_file = args.config
    if not os.path.exists(config_file):
        print(f"[ERROR]Config file not found: {config_file}")
        exit(1)
        
    print(f"[INFO]Using config file: {config_file}")
    
    try:
        with open(config_file, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except Exception as e:
        print(f"[ERROR]Failed to read config file: {e}")
        exit(1)
    
    # print(data)

    # 创建并启动节点
    node = Node(data)
    print(f"[INFO]Node created: {node.name}")
    node.run()
    
    # 保持运行状态
    try:
        print(f"[INFO]Node {node.name} is running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[INFO]Shutting down Node {node.name}...")
        node.stop()
        print(f"[INFO]Node {node.name} stopped successfully")
