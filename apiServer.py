from flask import Flask, request, jsonify
import json
import platform
import docker
from time import time

from config import Config
from etcd import Etcd
from node import Node
from pod import Pod

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
        print("[INFO]ApiServer Bind Routes...")
        
        # 基础路由
        self.app.route("/", methods=["GET"])(self.index)
        self.app.route("/health", methods=["GET"])(self.health_check)
        
        # Node管理路由
        self.app.route(Config.NODE_SPEC_URL_F, methods=["POST"])(self.create_node)
        self.app.route(Config.NODE_SPEC_URL_F, methods=["GET"])(self.get_node)
        self.app.route(Config.NODE_SPEC_URL_F, methods=["PUT"])(self.update_node)
        self.app.route(Config.NODE_SPEC_URL_F, methods=["DELETE"])(self.delete_node)
        self.app.route(Config.NODE_URL_F, methods=["GET"])(self.get_all_nodes)

        # Pod管理路由
        self.app.route(Config.POD_SPEC_URL_F, methods=["POST"])(self.create_pod)
        self.app.route(Config.POD_SPEC_URL_F, methods=["GET"])(self.get_pod)
        self.app.route(Config.POD_SPEC_URL_F, methods=["PUT"])(self.update_pod)
        self.app.route(Config.POD_SPEC_URL_F, methods=["DELETE"])(self.delete_pod)
        self.app.route(Config.PODS_URL_F, methods=["GET"])(self.get_pods_in_namespace)
        self.app.route(Config.GLOBAL_PODS_URL_F, methods=["GET"])(self.get_all_pods)

    def index(self):
        return jsonify({
            "message": "Mini-K8s ApiServer",
            "version": "v1.0",
            "endpoints": [
                Config.NODE_URL,
                Config.PODS_URL,
                Config.GLOBAL_PODS_URL
            ]
        })
    
    def health_check(self):
        return jsonify({"status": "healthy", "timestamp": time()})

    # ==================== Node管理 ====================
    
    def create_node(self, node_name: str):
        """注册新节点"""
        print(f"[INFO]Registering Node: {node_name}")
        
        try:
            node_data = request.json
            if not node_data:
                return jsonify({"error": "No node data provided"}), 400
            
            # 检查节点是否已存在
            existing_node = self.etcd.get(Config.NODE_SPEC_KEY.format(node_name=node_name))
            if existing_node:
                return jsonify({"warning": f"Node {node_name} already exists"}), 409
            
            # 创建Node实例进行验证
            try:
                node = Node(node_data)
                if node.name != node_name:
                    return jsonify({"error": "Node name mismatch"}), 400
            except Exception as e:
                return jsonify({"error": f"Invalid node configuration: {str(e)}"}), 400
            
            # 存储到etcd
            self.etcd.put(Config.NODE_SPEC_KEY.format(node_name=node_name), node_data)
            
            print(f"[INFO]Node {node_name} registered successfully")
            
            # 返回配置信息给节点
            return jsonify({
                "message": f"Node {node_name} registered successfully",
                "kafka_server": Config.KAFKA_SERVER,
                "kafka_topic": Config.POD_TOPIC.format(name=node_name),
                "server_time": time()
            })
            
        except Exception as e:
            print(f"[ERROR]Failed to register node {node_name}: {e}")
            return jsonify({"error": str(e)}), 500
    
    def get_node(self, node_name: str):
        """获取节点信息"""
        try:
            node_data = self.etcd.get(Config.NODE_SPEC_KEY.format(node_name=node_name))
            if not node_data:
                return jsonify({"error": f"Node {node_name} not found"}), 404
            
            return jsonify(node_data)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def update_node(self, node_name: str):
        """更新节点信息（心跳）"""
        try:
            existing_node = self.etcd.get(Config.NODE_SPEC_KEY.format(node_name=node_name))
            if not existing_node:
                return jsonify({"error": f"Node {node_name} not found"}), 404
            
            # 更新心跳时间
            update_data = request.json or {}
            existing_node.update(update_data)
            existing_node["lastHeartbeat"] = time()
            
            self.etcd.put(Config.NODE_SPEC_KEY.format(node_name=node_name), existing_node)
            
            return jsonify({"message": f"Node {node_name} updated", "timestamp": time()})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def delete_node(self, node_name: str):
        """删除节点"""
        try:
            existing_node = self.etcd.get(Config.NODE_SPEC_KEY.format(node_name=node_name))
            if not existing_node:
                return jsonify({"error": f"Node {node_name} not found"}), 404
            
            # TODO: 检查节点上是否有运行的Pod
            
            self.etcd.delete(Config.NODE_SPEC_KEY.format(node_name=node_name))
            
            return jsonify({"message": f"Node {node_name} deleted"})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def get_all_nodes(self):
        """获取所有节点"""
        try:
            nodes_data = self.etcd.get_prefix(Config.NODES_KEY)
            nodes = []
            
            for node_data in nodes_data:
                if node_data:  # 过滤空数据
                    nodes.append(node_data)
            
            return jsonify({
                "nodes": nodes,
                "count": len(nodes)
            })
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ==================== Pod管理 ====================
    
    def create_pod(self, namespace: str, name: str):
        """创建Pod"""
        print(f"[INFO]Creating Pod {name} in namespace: {namespace}")
        
        try:
            pod_data = request.json
            if not pod_data:
                return jsonify({"error": "No pod data provided"}), 400
            
            # 创建Pod实例进行验证
            try:
                pod = Pod(pod_data)
                pod_name = pod.name
                
                # 验证URL中的name与配置中的name是否一致
                if pod_name != name:
                    return jsonify({"error": f"Pod name in URL ({name}) doesn't match name in config ({pod_name})"}), 400
                    
            except Exception as e:
                return jsonify({"error": f"Invalid pod configuration: {str(e)}"}), 400
            
            # 检查Pod是否已存在
            existing_pod = self.etcd.get(Config.POD_SPEC_KEY.format(namespace=namespace, name=pod_name))
            if existing_pod:
                return jsonify({"warning": f"Pod {namespace}/{pod_name} already exists"}), 409
            
            # 存储到etcd
            self.etcd.put(Config.POD_SPEC_KEY.format(namespace=namespace, name=pod_name), pod_data)
            
            print(f"[INFO]Pod {namespace}/{pod_name} created successfully")
            
            return jsonify({
                "message": f"Pod {namespace}/{pod_name} created successfully",
                "pod": {
                    "namespace": namespace,
                    "name": pod_name,
                    "status": Config.POD_STATUS_CREATING
                }
            }), 200
            
        except Exception as e:
            print(f"[ERROR]Failed to create pod: {e}")
            return jsonify({"error": str(e)}), 500
    
    def get_pod(self, namespace: str, name: str):
        """获取Pod信息"""
        try:
            pod_data = self.etcd.get(Config.POD_SPEC_KEY.format(namespace=namespace, name=name))
            if not pod_data:
                return jsonify({"error": f"Pod {namespace}/{name} not found"}), 404
            
            return jsonify(pod_data)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def update_pod(self, namespace: str, name: str):
        """更新Pod状态"""
        try:
            existing_pod = self.etcd.get(Config.POD_SPEC_KEY.format(namespace=namespace, name=name))
            if not existing_pod:
                return jsonify({"error": f"Pod {namespace}/{name} not found"}), 404
            
            update_data = request.json or {}
            existing_pod.update(update_data)
            existing_pod["lastUpdated"] = time()
            
            self.etcd.put(Config.POD_SPEC_KEY.format(namespace=namespace, name=name), existing_pod)
            
            return jsonify({"message": f"Pod {namespace}/{name} updated"})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def delete_pod(self, namespace: str, name: str):
        """删除Pod"""
        try:
            existing_pod = self.etcd.get(Config.POD_SPEC_KEY.format(namespace=namespace, name=name))
            if not existing_pod:
                return jsonify({"error": f"Pod {namespace}/{name} not found"}), 404
            
            # 从etcd删除
            self.etcd.delete(Config.POD_SPEC_KEY.format(namespace=namespace, name=name))
            
            return jsonify({"message": f"Pod {namespace}/{name} deleted"})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def get_pods_in_namespace(self, namespace: str):
        """获取命名空间下的所有Pod"""
        try:
            namespace_prefix = f"{Config.GLOBAL_PODS_KEY}{namespace}/"
            pods_data = self.etcd.get_prefix(namespace_prefix)
            pods = []
            
            for pod_data in pods_data:
                if pod_data:
                    pods.append(pod_data)
            
            return jsonify({
                "namespace": namespace,
                "pods": pods,
                "count": len(pods)
            })
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    def get_all_pods(self):
        """获取所有Pod"""
        try:
            pods_data = self.etcd.get_prefix(Config.GLOBAL_PODS_KEY)
            pods = []
            
            for pod_data in pods_data:
                if pod_data:
                    pods.append(pod_data)
            
            return jsonify({
                "pods": pods,
                "count": len(pods)
            })
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def run(self):
        print('[INFO] ApiServer Run...')
        # Thread(target = self.node_health).start()
        # Thread(target = self.serverless_scale).start()
        self.app.run(host = Config.HOST, port = Config.SERVER_PORT, threaded = True)

if __name__ == "__main__":
    api_server = ApiServer()
    api_server.run()