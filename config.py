class Config:
    # Etcd Config
    # HOST = "10.119.15.182"  # server
    HOST = 'localhost'

    ETCD_PORT = "2379"
    SERVER_PORT = "5050"
    SERVER_URI = f"http://{HOST}:{SERVER_PORT}"

#---------------------------------------------------------------------------------------
    # KAFKA_SERVER = "10.119.15.182:9092"  # server
    # KAFKA_SERVER = "10.180.196.84:9092" # zys
    
    # Kafka Configuration
    KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    
    # Kafka Topics - Kubelet通信主题
    KUBELET_TOPIC = "kubelet-{node_id}"
    
    # 生成特定节点的Kubelet topic
    @classmethod
    def get_kubelet_topic(cls, node_id):
        return cls.KUBELET_TOPIC.format(node_id=node_id)

#---------------------------------------------------------------------------------------

    # ETCD KEY
    NODES_KEY = "/nodes/"
    NODE_SPEC_KEY = "/nodes/{node_name}"
    GLOBAL_PODS_KEY = "/pods/"
    POD_SPEC_KEY = "/pods/{namespace}/{pod_name}"

#---------------------------------------------------------------------------------------

    # NODES Routes
    NODE_SPEC_URL_F = "/api/v1/nodes/<node_name>"
    NODE_SPEC_URL = "/api/v1/nodes/{node_name}"
    NODE_URL_F = "/api/v1/nodes"
    NODE_URL = "/api/v1/nodes"

    # PODS Routes
    POD_SPEC_URL_F = "/api/v1/namespaces/<namespace>/pods/<name>"
    POD_SPEC_URL = "/api/v1/namespaces/{namespace}/pods/{name}"
    PODS_URL_F = "/api/v1/namespaces/<namespace>/pods"
    PODS_URL = "/api/v1/namespaces/{namespace}/pods"
    GLOBAL_PODS_URL_F = "/api/v1/pods"
    GLOBAL_PODS_URL = "/api/v1/pods"
    
    # PODS 状态更新 Routes
    POD_STATUS_URL_F = "/api/v1/namespaces/<namespace>/pods/<pod_name>/status"
    POD_STATUS_URL = "/api/v1/namespaces/{namespace}/pods/{pod_name}/status"



    # -------------------- 资源主题定义 --------------------
    # 与Node的kubelet组件交互
    POD_TOPIC = "api.v1.nodes.{name}"
    # 与scheduler交互
    SCHEDULER_TOPIC = "api.v1.scheduler"
    # 与dns服务器交互
    DNS_TOPIC = "api.v1.dns"
    # service controller与kubeproxy交互
    SERVICE_PROXY_TOPIC = "serviceproxy.{name}"

    # -------------------- Pod状态定义 --------------------
    POD_STATUS_CREATING = "CREATING"
    POD_STATUS_RUNNING = "RUNNING"
    POD_STATUS_STOPPED = "STOPPED"
    POD_STATUS_KILLED = "KILLED"
    POD_STATUS_FAILED = "FAILED"

    # 清除列表
    RESET_PREFIX = [NODES_KEY, GLOBAL_PODS_KEY]
    # RESET_PREFIX = [NODES_KEY, GLOBAL_PODS_KEY, GLOBAL_REPLICA_SETS_KEY, GLOBAL_HPA_KEY, GLOBAL_DNS_KEY, GLOBAL_SERVICES_KEY, GLOBAL_FUNCTION_KEY, GLOBAL_WORKFLOW_KEY]