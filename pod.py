import requests
import json
from uuid import uuid1
import docker
import platform
import os

from config import Config
from container import Container
from network import get_network_manager, get_network_attacher


class Pod:
    def __init__(self, pod_json):
        """
        从YAML配置初始化Pod，支持真实Docker集成
        
        Args:
            pod_json: Pod的YAML/JSON配置
        """
        # 基本信息
        self.id = str(uuid1())
        self.json = pod_json

        metadata = pod_json.get("metadata", {})
        self.name = metadata.get("name")
        self.namespace = metadata.get("namespace", "default")
        self.labels = metadata.get("labels", {})
        
        # 规格配置
        spec = pod_json.get("spec", {})
        
        # 容器配置
        self.containers = []
        for container_json in spec.get("containers", []):
            container = Container(container_json, pod_name=self.name, namespace=self.namespace)
            self.containers.append(container)
        
        # 卷配置
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
        
        # 网络管理
        self.network_manager = get_network_manager()
        self.network_attacher = get_network_attacher()
        
        # Docker客户端初始化
        self.docker_client = None
        self._init_docker_client()
        
        # API Server 连接配置
        self.base_url = Config.SERVER_URI
        
        print(f"[INFO]Pod {self.namespace}:{self.name} initialized (ID: {self.id})")
    
    def _init_docker_client(self):
        """初始化Docker客户端"""
        try:
            if platform.system() == "Windows":
                self.docker_client = docker.DockerClient(
                    base_url="npipe:////./pipe/docker_engine", 
                    version="auto", 
                    timeout=20
                )
            else:
                self.docker_client = docker.DockerClient(
                    base_url="unix://var/run/docker.sock", 
                    version="auto", 
                    timeout=20
                )
            
            # 测试连接
            self.docker_client.ping()
            print(f"[INFO]Docker client connected successfully")
            
        except Exception as e:
            print(f"[ERROR]Docker client connection failed: {e}")
            raise Exception(f"Docker is required but not available: {e}")
    
    def create_containers(self):
        """
        仅创建Docker容器，不向ApiServer注册Pod
        这个方法专门供Kubelet使用，因为Pod已经通过调度器注册到ApiServer了
        """
        print(f"[INFO]Creating Docker containers for Pod {self.namespace}:{self.name}")
        
        try:
            # 直接创建Docker容器
            if not self._create_docker_containers():
                print(f"[ERROR]Failed to create Docker containers for Pod")
                return False
            
            self.status = Config.POD_STATUS_RUNNING
            print(f"[INFO]Pod {self.namespace}:{self.name} containers created successfully")
            return True
                
        except Exception as e:
            print(f"[ERROR]Failed to create Pod containers: {e}")
            return False
    
    def _create_docker_containers(self):
        """创建真实的Docker容器，集成网络管理"""
        if not self.docker_client:
            print(f"[ERROR]Docker client not available")
            return False
        
        try:
            # 1. 创建Pod网络配置
            print(f"[INFO]Creating network configuration for Pod {self.namespace}:{self.name}")
            network_config = self.network_manager.create_pod_network(self.name, self.namespace)
            self.subnet_ip = network_config["ip"]
            print(f"[INFO]Allocated Pod IP: {self.subnet_ip}")
            
            # 2. 创建pause容器（用于网络共享）
            pause_name = f"pause_{self.namespace}_{self.name}"
            
            # 检查pause容器是否已存在
            existing_containers = self.docker_client.containers.list(
                all=True, 
                filters={"name": pause_name}
            )
            
            if existing_containers:
                print(f"[INFO]Reusing existing pause container: {pause_name}")
                pause_container = existing_containers[0]
                if pause_container.status != "running":
                    pause_container.start()
            else:
                print(f"[INFO]Creating pause container: {pause_name}")
                
                # 收集所有容器的端口配置
                pause_ports = {}
                for container in self.containers:
                    if container.ports:
                        for port_config in container.ports:
                            container_port = port_config.get("containerPort")
                            host_port = port_config.get("hostPort")
                            protocol = port_config.get("protocol", "TCP").lower()
                            if container_port:
                                port_key = f"{container_port}/{protocol}"
                                if host_port:
                                    pause_ports[port_key] = host_port
                                else:
                                    pause_ports[port_key] = None
                
                # 创建pause容器参数
                pause_args = {
                    "image": "busybox:latest",
                    "name": pause_name,
                    "command": ["sh", "-c", "echo '[INFO]Pod network init' && sleep 3600"],
                    "detach": True,
                    "remove": False
                }
                
                # 如果有端口配置，添加到参数中
                if pause_ports:
                    pause_args["ports"] = pause_ports
                
                pause_container = self.docker_client.containers.run(**pause_args)
                
                # 将pause容器连接到Pod网络并分配指定IP
                if self.network_attacher.attach_container_to_pod_network(
                    pause_container.id, self.name, self.namespace
                ):
                    print(f"[INFO] pause容器已成功连接到Pod网络")
                else:
                    print(f"[ERROR] pause容器网络连接失败")
                    return False
            
            self.docker_containers.append(pause_container)
            
            # 3. 创建业务容器
            for container in self.containers:
                # 使用pause容器的网络
                network_mode = f"container:{pause_name}"
                
                # 创建容器，传入卷和网络模式
                if container.create(volumes=self.volumes, network_mode=network_mode):
                    self.docker_containers.append(container.docker_container)
                    print(f"[INFO]Container {container.container_name} created successfully")
                else:
                    print(f"[ERROR]Failed to create container {container.container_name}")
                    return False
            
            print(f"[INFO]All containers created for Pod {self.namespace}:{self.name}")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to create Docker containers: {e}")
            import traceback
            traceback.print_exc()
            return False

    def delete(self):
        """
        删除Pod - 对应ApiServer的DELETE /api/v1/namespaces/<namespace>/pods/<name>
        从ApiServer删除Pod，同时删除真实的Docker容器
        """
        print(f"[INFO]Deleting Pod {self.namespace}:{self.name} via ApiServer")
        
        try:
            # 1. 首先删除Docker容器
            self._delete_docker_containers()
            
            # 2. 从ApiServer删除Pod
            url = f"{self.base_url}{Config.POD_SPEC_URL.format(namespace=self.namespace, name=self.name)}"
            
            # 发送DELETE请求到ApiServer
            response = requests.delete(url, timeout=10)
            
            if response.status_code == 200:  # OK
                print(f"[INFO]Pod {self.namespace}:{self.name} deleted successfully")
                self.status = Config.POD_STATUS_KILLED
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
    
    def _delete_docker_containers(self):
        """删除真实的Docker容器，集成网络管理"""
        if not self.docker_client:
            print(f"[ERROR]Docker client not available")
            return False
        
        try:
            # 1. 从网络中断开容器连接
            for container in self.containers:
                if hasattr(container, 'docker_container') and container.docker_container:
                    self.network_attacher.detach_container_from_pod_network(
                        container.docker_container.id, self.name, self.namespace
                    )
            
            # 2. 删除所有业务容器
            for container in self.containers:
                container.delete()
            
            # 3. 删除pause容器和直接Docker容器
            for docker_container in self.docker_containers:
                try:
                    container_name = docker_container.name
                    print(f"[INFO]Stopping and removing container: {container_name}")
                    
                    # 从网络断开pause容器
                    if "pause_" in container_name:
                        self.network_attacher.detach_container_from_pod_network(
                            docker_container.id, self.name, self.namespace
                        )
                    
                    # 强制停止容器
                    docker_container.kill()
                    docker_container.remove(force=True)
                    
                    print(f"[INFO]Container {container_name} removed successfully")
                    
                except Exception as e:
                    print(f"[WARNING]Failed to remove container {docker_container.name}: {e}")
            
            # 4. 删除Pod网络配置
            self.network_manager.delete_pod_network(self.name, self.namespace)
            
            # 清空容器列表
            self.docker_containers = []
            
            print(f"[INFO]All containers and network config deleted for Pod {self.namespace}:{self.name}")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to delete Docker containers: {e}")
            return False