from flask import Flask, request
import platform
import docker

from config import Config
from etcd import Etcd

class ApiServer:
    def __init__(self):
        print("[INFO]ApiServer Init...")
        self.etcd = Etcd(host = Config.HOST, port =  Config.ETCD_PORT)
        self.app = Flask(__name__)

        # if platform.system() == "Windows":
        #     self.docker = docker.DockerClient(
        #         base_url="npipe:////./pipe/docker_engine",
        #         version="1.25",
        #         timeout=5
        #     )
        # else:
        #     self.docker = docker.DockerClient(
        #         base_url="unix://var/run/docker.sock",
        #         version="1.25",
        #         timeout=5
        #     )

        self.etcd.reset()

        self.bind()

    def bind(self):
        print("[INFO]ApiServer Bind...")
        self.app.route("/", methods=["GET"])(self.index)

        self.app.route(Config.NODE_SPEC_URL_F, methods=["POST"])(self.add_node)

    def index(self):
        return "ApiServer Demo"

    # 注册一个新结点
    def add_node(self, node_name: str):
        print(f"[INFO]Add Node: {node_name} && json: {request.json}")
        node_data_json = request.json
        # new_node_config = NodeConfig(node_json)

        # self.etcd.put(Config.NODE_SPEC_KEY.format(node_name = node_name), node_data_json)

        # # 如果Node存在且状态为ONLINE
        # node = self.etcd.get(self.etcd_config.NODE_SPEC_KEY.format(name=node_name))
        # if node is not None:
        #     if node.status == NODE_STATUS.OFFLINE:
        #         print(f'[INFO]Node {node_name} reconnect.')
        #     else:
        #         print(f'[ERROR] Node {node_name} already exists and is still online.')
        #         return json.dumps({'error': 'Node name duplicated'}), 403

        # try:
        #     # 创建Pod主题（用于kubelet）
        #     pod_topic = self.kafka_config.POD_TOPIC.format(name=node_name)
        #     # 创建ServiceProxy主题（用于ServiceProxy）
        #     serviceproxy_topic = self.kafka_config.SERVICE_PROXY_TOPIC.format(name=node_name)
            
        #     # 批量创建主题
        #     topics_to_create = [
        #         NewTopic(pod_topic, num_partitions=1, replication_factor=1),
        #         NewTopic(serviceproxy_topic, num_partitions=1, replication_factor=1)
        #     ]
            
        #     fs = self.kafka.create_topics(topics_to_create)
        #     for topic, f in fs.items():
        #         f.result()
        #         print(f"[INFO]Topic '{topic}' created successfully.")
            
        #     # 发送心跳消息到Pod主题
        #     self.kafka_producer.produce(
        #         pod_topic, key="HEARTBEAT", value=json.dumps({}).encode("utf-8")
        #     )
        # except KafkaException as e:
        #     if not e.args[0].code() == 36:  # 忽略"主题已存在"的错误
        #         raise

        # # 创建成功，向etcd写入实际状态
        # new_node_config.kafka_server = self.kafka_config.BOOTSTRAP_SERVER
        # new_node_config.topic = pod_topic
        # new_node_config.status = NODE_STATUS.ONLINE
        # new_node_config.heartbeat_time = time()
        # self.etcd.put(self.etcd_config.NODE_SPEC_KEY.format(name=node_name), new_node_config)

        # return {
        #     "kafka_server": self.kafka_config.BOOTSTRAP_SERVER,
        #     "kafka_topic": pod_topic,
        #     # "serviceproxy_topic": serviceproxy_topic,
        # }
        return {
            "message": f"Node {node_name} added successfully."
        }

    def run(self):
        print('[INFO] ApiServer Run...')
        # Thread(target = self.node_health).start()
        # Thread(target = self.serverless_scale).start()
        self.app.run(host = Config.HOST, port = Config.SERVER_PORT, threaded = True)

if __name__ == "__main__":
    api_server = ApiServer()
    api_server.run()