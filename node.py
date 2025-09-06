import requests
import sys
import os
import pickle
import signal
from threading import Thread
from time import sleep

from config import Config

from pkg.kubelet.kubelet import Kubelet
from pkg.config.kubeletConfig import KubeletConfig

from pkg.proxy.kubeproxy import KubeProxy


class STATUS:
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class Node:
    def __init__(self, arg):
        metadata = arg.get("metadata")
        self.name = metadata.get("name")
        self.apiserver = metadata.get("ip")

        spec = arg.get("spec")
        self.subnet_ip = spec.get("podCIDR")
        self.taints = spec.get("taints")
        self.json = arg

        self.status = None
        self.heartbeat_time = None
        self.kafka_server = None
        self.kafka_topic = None
        self.service_proxy = None

    def run(self):
        # 注册到 API Server
        path = Config.NODE_SPEC_URL.format(node_name=self.name)
        url = f"{Config.SERVER_URI}{path}"

        session = requests.Session()
        register_response = session.post(url, json=self.json)

        if register_response.status_code != 200:
            print(f"[ERROR]Cannot register to ApiServer with code {register_response.status_code}")
            return
    
        self.status = STATUS.ONLINE
        res_json = register_response.json()

        # 启动 Kubelet
        kubelet_config = KubeletConfig(**self.kubelet_config_args(), **res_json)
        self.kubelet = Kubelet(kubelet_config, self.uri_config)
        print(f"[INFO]Successfully register to ApiServer.")

        # # 创建ServiceProxy实例
        # self.service_proxy = KubeProxy(
        #     node_name=self.config.name,
        #     kafka_config=KafkaConfig
        # )
        # # 启动ServiceProxy守护进程
        # self.service_proxy.start_daemon()
        # print(f"[INFO]ServiceProxy已在节点 {self.config.name} 上启动")

        # Pod
        # 从apiServer索要持久化的Pod状态信息，并运行kubelet
        uri = self.uri_config.PREFIX + self.uri_config.NODE_ALL_PODS_URL.format(name = self.config.name)
        register_response = requests.get(uri)
        if register_response.status_code != 200:
            print(f"[ERROR]Cannot fetch Pod status from apiServer")
            return
        res = pickle.loads(register_response.content)
        self.kubelet.apply(res)
        Thread(target=self.kubelet.run).start()

        # 设置信号处理器，确保优雅关闭
        try:
            import threading
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, self._signal_handler)
                signal.signal(signal.SIGTERM, self._signal_handler)
                print("[INFO]信号处理器已设置")
            else:
                print("[INFO]非主线程环境，跳过信号处理器设置")
        except Exception as e:
            print(f"[WARNING]设置信号处理器失败: {e}")

        # 定期发送心跳
        while True:
            sleep(2)
            uri = self.uri_config.PREFIX + self.uri_config.NODE_SPEC_URL.format(name=self.name)
            register_response = requests.put(uri, json=self.json)

if __name__ == "__main__":
    print("[INFO]Starting Node with integrated ServiceProxy.")
    
    # 记录日志文件路径
    log_file = os.environ.get('NODE_LOG_FILE')
    if log_file:
        print(f"[INFO]Node logs will be written to: {log_file}")
        
    import yaml
    from pkg.config.globalConfig import GlobalConfig
    import argparse

    global_config = GlobalConfig()

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Start Node with integrated ServiceProxy.")
    parser.add_argument("--node-config", type=str, default="./testFile/node-1.yaml", help="YAML config file for the node")
    args = parser.parse_args()

    file_yaml = args.node_config
    test_yaml = os.path.join(global_config.PROJECT_ROOT, file_yaml)
    print(
        f"[INFO]使用{file_yaml}作为测试配置，节点将自动启动ServiceProxy"
    )
    print(f"[INFO]请求地址: {test_yaml}")
    with open(test_yaml, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        
    node = Node(data)
    node.run()
