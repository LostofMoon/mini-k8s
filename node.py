import requests
import os
import time
from uuid import uuid1

from config import Config
from kubelet import Kubelet

class Node:
    def __init__(self, arg):
        self.json = arg
        self.kafka_bootstrap_servers = Config.KAFKA_BOOTSTRAP_SERVERS

        self.id = str(uuid1())
        metadata = arg.get("metadata")
        self.name = metadata.get("name")
        spec = arg.get("spec", {})
        status = arg.get("status", {})

        # 运行时状态
        self.kubelet = None
        self.service_proxy = None # TODO: 组件引用（暂时为None，后续完善时再启用）
        
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
        
        # 创建并启动Kubelet
        try:
            self.kubelet = Kubelet(self.name, self.kafka_bootstrap_servers)
            self.kubelet.start()
            print(f"[INFO]Kubelet started on node {self.name}")
        except Exception as e:
            print(f"[ERROR]Failed to start Kubelet: {e}")
            self.kubelet = None
        
        # TODO: 后续实现
        # self._start_service_proxy()
        
        print(f"[INFO]Node {self.name} is running")
    
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
