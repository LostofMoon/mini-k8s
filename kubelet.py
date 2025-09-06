import json
import logging
import sys
import os
from time import sleep
from confluent_kafka import Consumer, KafkaError
from threading import Thread

from pkg.apiObject.pod import Pod, STATUS
from pkg.config.podConfig import PodConfig
from pkg.apiServer.apiClient import ApiClient

class Kubelet:
    """
    kubelet可以细分为Cri、PLEG等组件，分别用于容器管理和容器状态监控等。
    我认为这样细分会增加阅读难度，所以我将这些组件的功能全部实现在同一个循环中
    """

    def __init__(self, config, uri_config):
        self.config = config
        self.uri_config = uri_config
        self.api_client = ApiClient(self.uri_config.HOST, self.uri_config.PORT)
        self.pods_cache = []
        self.pods_status = []
        # 三个状态：apiserver存储的状态，kubelet存储的状态，Pod本身的状态。
        # 可以保证：如果http请求正常送达，则前两者保持一致。在kubelet每一轮loop后短时间内后两者一致

        self.consumer = Consumer(config.consumer_config())
        self.consumer.subscribe([config.topic])

        print(f"[INFO]Subscribe kafka({config.kafka_server}) topic {config.topic}")

    def apply(self, pod_config_list):
        self.pods_cache = [Pod(pod_config) for pod_config in pod_config_list]
        self.pods_status = [STATUS.CREATING] * len(self.pods_cache)

    def run(self):
        while True:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                print(f'错误: {msg.error()}')
                continue

            self.update_pod(
                msg.key().decode("utf-8"),
                json.loads(msg.value().decode("utf-8")),
            )

            self.consumer.commit(asynchronous = False)


    def update_pod(self, type, data):
        print(f"[INFO]Kubelet {type} pod with data: {data}")


if __name__ == "__main__":
    print("[INFO]Testing kubelet.")
    import yaml
    from pkg.apiObject.pod import Pod
    from pkg.config.kubeletConfig import KubeletConfig
    from pkg.config.globalConfig import GlobalConfig
    import os

    kubelet_config = KubeletConfig()
    kubelet = Kubelet(kubelet_config)
    global_config = GlobalConfig()
    test_yaml = os.path.join(global_config.TEST_FILE_PATH, "pod-3.yaml")

    with open(test_yaml, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    print(f"data = {data}")
    podConfig = PodConfig(data)
    # pod = Pod(podConfig)
    # kubelet.pods_cache.append(pod)

    print("[INFO]start kubelet(infinite retry)")
    kubelet.run()
