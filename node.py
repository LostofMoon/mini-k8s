import requests
import sys
import os
import yaml
from uuid import uuid1

from config import Config

class Node:
    def __init__(self, arg):
        self.id = str(uuid1())

        metadata = arg.get("metadata")
        self.name = metadata.get("name")
        self.apiserver = metadata.get("api-server").get("ip")

        spec = arg.get("spec")
        self.subnet_ip = spec.get("podCIDR")
        self.taints = spec.get("taints")
        
        self.json = arg

        # 运行时状态
        self.kafka_server = None
        self.kafka_topic = None
        
        # 组件引用（暂时为None，后续完善时再启用）
        self.kubelet = None
        self.service_proxy = None
        
    def kubelet_config_args(self):
        """返回kubelet配置参数"""
        return {
            "subnet_ip": self.subnet_ip,
            "apiserver": self.apiserver,
            "node_id": self.id,
        }

    def run(self):
        """启动节点并注册到ApiServer"""
        print(f"[INFO]Starting Node: {self.name}")
        
        # 注册到 API Server
        path = Config.NODE_SPEC_URL.format(node_name=self.name)
        url = f"{Config.SERVER_URI}{path}"

        session = requests.Session()
        register_response = session.post(url, json=self.json)

        if register_response.status_code != 200:
            print(f"[ERROR]Cannot register to ApiServer with code {register_response.status_code}")
            return
            
        # 获取ApiServer返回的配置信息
        res_json = register_response.json()
        self.kafka_server = res_json.get("kafka_server")
        self.kafka_topic = res_json.get("kafka_topic")
        
        print(f"[INFO]Node {self.name} successfully registered to ApiServer")
        
        # TODO: 启动组件（后续完善）
        # self._start_kubelet(res_json)
        # self._start_service_proxy()
        
        print(f"[INFO]Node {self.name} is running")

if __name__ == "__main__":
    print("[INFO]Starting Node...")

    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="Start Mini-K8s Node.")
    parser.add_argument("--node-config", type=str, default="./testFile/node-1.yaml", help="YAML config file for the node")
    args = parser.parse_args()

    # 读取配置文件
    config_file = args.node_config
    if not os.path.exists(config_file):
        print(f"[ERROR]Config file not found: {config_file}")
        sys.exit(1)
        
    print(f"[INFO]Using config file: {config_file}")
    
    try:
        with open(config_file, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except Exception as e:
        print(f"[ERROR]Failed to read config file: {e}")
        sys.exit(1)
    
    # print(data)

    # 创建并启动节点
    node = Node(data)
    print(f"[INFO]Node created: {node.name}")
    node.run()
