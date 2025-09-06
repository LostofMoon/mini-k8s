import docker
import platform
from uuid import uuid1

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
        
        # 简化的容器配置
        self.containers = []
        for container_json in spec.get("containers", []):
            container = {
                "name": container_json.get("name"),
                "image": container_json.get("image"),
                "command": container_json.get("command", []),
                "args": container_json.get("args", []),
                "ports": container_json.get("ports", [])
            }
            self.containers.append(container)
        
        # 简化的卷配置
        self.volumes = {}
        for volume in spec.get("volumes", []):
            volume_name = volume.get("name")
            host_path_config = volume.get("hostPath", {})
            
            if isinstance(host_path_config, str):
                host_path = host_path_config
            elif isinstance(host_path_config, dict):
                host_path = host_path_config.get("path", "/tmp")
            else:
                host_path = "/tmp"
            
            self.volumes[volume_name] = host_path
        
        # 运行时状态
        self.status = Config.POD_STATUS_CREATING
        self.node_name = None
        self.subnet_ip = None
        self.docker_containers = []
        
        # 保存原始配置
        self.json = pod_json
        
        print(f"[INFO]Pod {self.namespace}:{self.name} initialized")
    
    def create(self):
        """创建Pod（简化版本）"""
        print(f"[INFO]Creating Pod {self.namespace}:{self.name}")
        
        try:
            # 初始化Docker客户端（如果需要）
            if hasattr(self, '_docker_client'):
                pass  # 已初始化
            else:
                try:
                    if platform.system() == "Windows":
                        self._docker_client = docker.DockerClient(
                            base_url="npipe:////./pipe/docker_engine", 
                            version="auto", timeout=20
                        )
                    else:
                        self._docker_client = docker.DockerClient(
                            base_url="unix://var/run/docker.sock", 
                            version="auto", timeout=20
                        )
                except:
                    print(f"[WARNING]Docker client not available, using simulation mode")
                    self._docker_client = None
            
            # 模拟容器创建
            for container in self.containers:
                print(f"[INFO]Would create container: {container['name']} with image: {container['image']}")
                # TODO: 实际Docker容器创建逻辑
            
            self.status = Config.POD_STATUS_RUNNING
            self.subnet_ip = "10.244.1.100"  # 模拟IP分配
            print(f"[INFO]Pod {self.namespace}:{self.name} created successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to create Pod {self.namespace}:{self.name}: {e}")
            self.status = Config.POD_STATUS_FAILED
            return False
    
    def stop(self):
        """停止Pod"""
        print(f"[INFO]Stopping Pod {self.namespace}:{self.name}")
        
        try:
            # TODO: 实际停止容器逻辑
            for container in self.docker_containers:
                print(f"[INFO]Would stop container: {container}")
            
            self.status = Config.POD_STATUS_STOPPED
            print(f"[INFO]Pod {self.namespace}:{self.name} stopped")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to stop Pod: {e}")
            return False
    
    def delete(self):
        """删除Pod"""
        print(f"[INFO]Deleting Pod {self.namespace}:{self.name}")
        
        try:
            if self.status == Config.POD_STATUS_RUNNING:
                self.stop()
            
            # TODO: 实际删除容器逻辑
            self.status = Config.POD_STATUS_KILLED
            self.docker_containers = []
            print(f"[INFO]Pod {self.namespace}:{self.name} deleted")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to delete Pod: {e}")
            return False
    
    def get_status(self):
        """获取Pod状态信息"""
        return {
            "name": f"{self.namespace}:{self.name}",
            "status": self.status,
            "ip": self.subnet_ip,
            "node": self.node_name,
            "containers": len(self.containers)
        }


if __name__ == "__main__":
    print("[INFO]Testing Pod...")
    
    import yaml
    import argparse
    import os
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Test Mini-K8s Pod.")
    parser.add_argument("--pod-config", type=str, default="./testFile/pod-test.yaml", 
                       help="YAML config file for the pod")
    args = parser.parse_args()
    
    # 读取配置文件
    config_file = args.pod_config
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
        
    # 创建并测试Pod
    pod = Pod(data)
    print(f"[INFO]Pod created: {pod.namespace}/{pod.name}")
    print(f"[INFO]Containers: {len(pod.containers)}")
    
    # 测试生命周期
    pod.create()
    print(f"[INFO]Status: {pod.get_status()}")
    
    pod.stop()
    pod.delete()
