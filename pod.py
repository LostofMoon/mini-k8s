import requests
import json
from uuid import uuid1
import requests

from config import Config


class Pod:
    def __init__(self, pod_json):
        """
        从YAML配置初始化Pod
        
        Args:
            pod_json: Pod的YAML/JSON配置
        """
        # 基本信息
        metadata = pod_json.get("metadata", {})
        self.name = metadata.get("name")
        self.namespace = metadata.get("namespace", "default")
        self.labels = metadata.get("labels", {})
        self.id = str(uuid1())
        
        # 规格配置
        spec = pod_json.get("spec", {})
        
        # # 简化的容器配置
        # self.containers = []
        # for container_json in spec.get("containers", []):
        #     container = {
        #         "name": container_json.get("name"),
        #         "image": container_json.get("image"),
        #         "command": container_json.get("command", []),
        #         "args": container_json.get("args", []),
        #         "ports": container_json.get("ports", [])
        #     }
        #     self.containers.append(container)
        
        # # 简化的卷配置
        # self.volumes = {}
        # self.volumes_config = spec.get("volumes", [])  # 保存原始volumes配置
        # for volume in spec.get("volumes", []):
        #     volume_name = volume.get("name")
        #     host_path_config = volume.get("hostPath", {})
            
        #     if isinstance(host_path_config, str):
        #         host_path = host_path_config
        #     elif isinstance(host_path_config, dict):
        #         host_path = host_path_config.get("path", "/tmp")
        #     else:
        #         host_path = "/tmp"
            
        #     self.volumes[volume_name] = host_path
        
        # # 运行时状态
        # self.status = Config.POD_STATUS_CREATING
        # self.node_name = None
        # self.subnet_ip = None
        # # self.docker_containers = []  # 暂时注释掉Docker容器列表
        # self.simulated_containers = []  # 使用模拟的容器列表
        
        # 保存原始配置
        self.json = pod_json
        
        # API Server 连接配置
        self.base_url = Config.SERVER_URI
        
        print(f"[INFO]Pod {self.namespace}:{self.name} initialized (ID: {self.id})")
    
    def create(self):
        """
        创建Pod - 对应ApiServer的POST /api/v1/namespaces/<namespace>/pods/<name>
        发送Pod配置到ApiServer进行创建
        """
        print(f"[INFO]Creating Pod {self.namespace}:{self.name} via ApiServer")
        
        try:
            # 构造创建URL
            url = f"{self.base_url}{Config.POD_SPEC_URL.format(namespace=self.namespace, name=self.name)}"
            
            # 准备Pod规格数据
            pod_spec = self.json.copy()
            # 确保有正确的metadata
            if "metadata" not in pod_spec:
                pod_spec["metadata"] = {}
            pod_spec["metadata"]["uid"] = self.id
            
            # 发送POST请求到ApiServer
            response = requests.post(url, json=pod_spec, timeout=10)
            
            if response.status_code == 200:
                print(f"[INFO]Pod {self.namespace}:{self.name} created successfully")
                return True
            elif response.status_code == 409:  # Conflict - already exists
                print(f"[WARNING]Pod {self.namespace}:{self.name} already exists")
                return False
            else:
                print(f"[ERROR]Failed to create Pod: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR]Cannot connect to ApiServer at {self.base_url}: {e}")
            return False
        except Exception as e:
            print(f"[ERROR]Failed to create Pod: {e}")
            return False
    
    def get(self):
        """
        获取Pod信息 - 对应ApiServer的GET /api/v1/namespaces/<namespace>/pods/<name>
        从ApiServer获取Pod的完整信息
        """
        print(f"[INFO]Getting Pod {self.namespace}:{self.name} from ApiServer")
        
        try:
            # 构造获取URL
            url = f"{self.base_url}{Config.POD_SPEC_URL.format(namespace=self.namespace, name=self.name)}"
            
            # 发送GET请求到ApiServer
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:  # OK
                pod_data = response.json()
                print(f"[INFO]Pod {self.namespace}:{self.name} found")
                print(f"[INFO]Pod Status: {pod_data.get('status', {}).get('phase', 'Unknown')}")
                print(f"[INFO]Pod Node: {pod_data.get('node', 'Unscheduled')}")
                return pod_data
            elif response.status_code == 404:  # Not Found
                print(f"[WARNING]Pod {self.namespace}:{self.name} not found")
                return None
            else:
                print(f"[ERROR]Failed to get Pod: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR]Cannot connect to ApiServer at {self.base_url}: {e}")
            return None
        except Exception as e:
            print(f"[ERROR]Failed to get Pod: {e}")
            return None
    
    def delete(self):
        """
        删除Pod - 对应ApiServer的DELETE /api/v1/namespaces/<namespace>/pods/<name>
        从ApiServer删除Pod
        """
        print(f"[INFO]Deleting Pod {self.namespace}:{self.name} via ApiServer")
        
        try:
            # 构造删除URL
            url = f"{self.base_url}{Config.POD_SPEC_URL.format(namespace=self.namespace, name=self.name)}"
            
            # 发送DELETE请求到ApiServer
            response = requests.delete(url, timeout=10)
            
            if response.status_code == 200:  # OK
                print(f"[INFO]Pod {self.namespace}:{self.name} deleted successfully")
                return True
            elif response.status_code == 404:  # Not Found
                print(f"[WARNING]Pod {self.namespace}:{self.name} not found for deletion")
                return False
            else:
                print(f"[ERROR]Failed to delete Pod: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR]Cannot connect to ApiServer at {self.base_url}: {e}")
            return False
        except Exception as e:
            print(f"[ERROR]Failed to delete Pod: {e}")
            return False


if __name__ == "__main__":
    import yaml
    import argparse
    import os
    import sys
    
    print("[INFO]Starting Pod API test...")
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Test Mini-K8s Pod API operations.")
    parser.add_argument("--config", type=str, default="./testFile/pod-1.yaml", 
                       help="YAML config file for the pod")
    parser.add_argument("--action", type=str, default="create", 
                       choices=["create", "get", "delete"],
                       help="API action to perform on the pod")
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
    
    # 创建Pod实例
    try:
        pod = Pod(data)
        print(f"[INFO]Pod initialized: {pod.namespace}/{pod.name} && Pod ID: {pod.id}")
    except Exception as e:
        print(f"[ERROR]Failed to create Pod: {e}")
        exit(1)
    
    # 根据指定动作执行API操作
    try:
        if args.action == "create":
            print(f"\n[INFO]Creating Pod via API...")
            success = pod.create()
            if success:
                print("[INFO]Pod created successfully")
            else:
                print("[ERROR]Pod creation failed")
            
        elif args.action == "get":
            print(f"\n[INFO]Getting Pod info via API...")
            pod_data = pod.get()
            if pod_data:
                print(f"[INFO]Pod data retrieved successfully:")
                print(json.dumps(pod_data, indent=2, ensure_ascii=False))
            else:
                print("[ERROR]Pod not found or get failed")
            
        elif args.action == "delete":
            print(f"\n[INFO]Deleting Pod via API...")
            success = pod.delete()
            if success:
                print("[INFO]Pod deleted successfully")
            else:
                print("[ERROR]Pod deletion failed")

    except Exception as e:
        print(f"\n[ERROR]Test failed: {e}")
        exit(1)
    
    print("[INFO]Pod API test finished.")
