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
        metadata = pod_json.get("metadata", {})
        self.name = metadata.get("name")
        self.namespace = metadata.get("namespace", "default")
        self.labels = metadata.get("labels", {})
        self.id = str(uuid1())
        
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
        self.docker_containers = []  # 实际的Docker容器列表
        
        # 网络管理
        self.network_manager = get_network_manager()
        self.network_attacher = get_network_attacher()
        
        # Docker客户端初始化
        self.docker_client = None
        self._init_docker_client()
        
        # 保存原始配置
        self.json = pod_json
        
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
    
    def create(self):
        """
        创建Pod - 对应ApiServer的POST /api/v1/namespaces/<namespace>/pods/<name>
        发送Pod配置到ApiServer进行创建，同时创建真实的Docker容器
        """
        print(f"[INFO]Creating Pod {self.namespace}:{self.name} via ApiServer")
        
        try:
            # 1. 首先向ApiServer注册Pod
            url = f"{self.base_url}{Config.POD_SPEC_URL.format(namespace=self.namespace, name=self.name)}"
            
            # 准备Pod规格数据
            pod_spec = self.json.copy()
            if "metadata" not in pod_spec:
                pod_spec["metadata"] = {}
            pod_spec["metadata"]["uid"] = self.id
            
            # 发送POST请求到ApiServer
            response = requests.post(url, json=pod_spec, timeout=10)
            
            if response.status_code not in [200, 201]:
                if response.status_code == 409:
                    print(f"[WARNING]Pod {self.namespace}:{self.name} already exists in ApiServer")
                else:
                    print(f"[ERROR]Failed to register Pod to ApiServer: {response.status_code} - {response.text}")
                    return False
            
            print(f"[INFO]Pod {self.namespace}:{self.name} registered to ApiServer successfully")
            
            # 2. 创建真实的Docker容器
            if not self._create_docker_containers():
                print(f"[ERROR]Failed to create Docker containers for Pod")
                return False
            
            self.status = Config.POD_STATUS_RUNNING
            print(f"[INFO]Pod {self.namespace}:{self.name} created successfully")
            return True
                
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR]Cannot connect to ApiServer at {self.base_url}: {e}")
            return False
        except Exception as e:
            print(f"[ERROR]Failed to create Pod: {e}")
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
                
                # 收集所有需要映射的端口
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
                
                # 创建pause容器参数，先使用默认网络
                pause_args = {
                    "image": "busybox:latest",
                    "name": pause_name,
                    "command": ["sh", "-c", "echo '[INFO]Pod network init' && sleep 3600"],
                    "detach": True,
                    "remove": False
                    # 不指定network，让Docker使用默认网络，然后手动连接
                }
                
                # 只在有端口需要映射时添加ports参数
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
                    
                    # 设置容器的DNS解析
                    self.network_manager.setup_dns_resolution(
                        container.docker_container.id, self.name, self.namespace
                    )
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
    
    
    def _get_pod_ip(self, pause_container):
        """获取Pod的IP地址"""
        try:
            pause_container.reload()
            
            # 从容器网络配置获取IP
            container_info = self.docker_client.api.inspect_container(pause_container.id)
            ip_address = container_info['NetworkSettings']['IPAddress']
            
            # 如果默认网络没有IP，尝试从其他网络获取
            if not ip_address:
                networks = container_info['NetworkSettings']['Networks']
                for network_name, network_config in networks.items():
                    if network_config.get('IPAddress'):
                        ip_address = network_config['IPAddress']
                        break
            
            return ip_address or "10.244.1.100"  # fallback IP
            
        except Exception as e:
            print(f"[WARNING]Failed to get Pod IP: {e}")
            return "10.244.1.100"  # fallback IP
    
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
            
            # 另外，通过名称清理可能遗留的容器
            self._cleanup_containers_by_name()
            
            print(f"[INFO]All containers and network config deleted for Pod {self.namespace}:{self.name}")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to delete Docker containers: {e}")
            return False
    
    def _cleanup_containers_by_name(self):
        """通过名称清理可能遗留的容器"""
        try:
            # 清理pause容器
            pause_name = f"pause_{self.namespace}_{self.name}"
            pause_containers = self.docker_client.containers.list(
                all=True, 
                filters={"name": pause_name}
            )
            for container in pause_containers:
                container.remove(force=True)
                print(f"[INFO]Cleaned up pause container: {pause_name}")
            
            # 清理业务容器
            for container in self.containers:
                business_containers = self.docker_client.containers.list(
                    all=True, 
                    filters={"name": container.container_name}
                )
                for docker_container in business_containers:
                    docker_container.remove(force=True)
                    print(f"[INFO]Cleaned up business container: {container.container_name}")
                    
        except Exception as e:
            print(f"[WARNING]Failed to cleanup containers by name: {e}")
    
    def start(self):
        """启动Pod中的所有容器"""
        if not self.docker_client:
            print(f"[ERROR]Docker client not available for Pod {self.namespace}:{self.name}")
            return False
        
        try:
            print(f"[INFO]Starting Pod {self.namespace}:{self.name}")
            
            # 启动所有业务容器
            for container in self.containers:
                container.start()
            
            # 启动pause容器和其他直接Docker容器
            for docker_container in self.docker_containers:
                if docker_container.status != "running":
                    docker_container.start()
                    print(f"[INFO]Started container: {docker_container.name}")
            
            self.status = Config.POD_STATUS_RUNNING
            print(f"[INFO]Pod {self.namespace}:{self.name} started successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to start Pod: {e}")
            return False
    
    def stop(self):
        """停止Pod中的所有容器"""
        if not self.docker_client:
            print(f"[ERROR]Docker client not available for Pod {self.namespace}:{self.name}")
            return False
        
        try:
            print(f"[INFO]Stopping Pod {self.namespace}:{self.name}")
            
            # 停止所有业务容器
            for container in self.containers:
                container.stop()
            
            # 停止pause容器和其他直接Docker容器
            for docker_container in self.docker_containers:
                if docker_container.status == "running":
                    docker_container.stop()
                    print(f"[INFO]Stopped container: {docker_container.name}")
            
            self.status = Config.POD_STATUS_STOPPED
            print(f"[INFO]Pod {self.namespace}:{self.name} stopped successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to stop Pod: {e}")
            return False
    
    def get_status(self):
        """获取Pod状态信息，包含网络配置"""
        # 刷新容器状态
        if self.docker_client and (self.docker_containers or self.containers):
            self._refresh_status()
        
        # 获取网络信息
        network_info = {}
        if hasattr(self, 'network_manager'):
            pod_ip = self.network_manager.get_pod_ip(self.name, self.namespace)
            network_info = {
                "allocated_ip": pod_ip,
                "subnet_ip": self.subnet_ip,
                "dns_servers": ["10.5.53.5"],  # CoreDNS IP
                "network_mode": "Pod"
            }
        
        return {
            "name": f"{self.namespace}:{self.name}",
            "status": self.status,
            "ip": self.subnet_ip,
            "node": self.node_name,
            "containers": len(self.containers),
            "docker_containers": len(self.docker_containers) if self.docker_containers else 0,
            "container_statuses": [container.get_info() for container in self.containers],
            "network": network_info
        }
    
    def _refresh_status(self):
        """刷新Pod状态（基于容器状态）"""
        try:
            running_count = 0
            stopped_count = 0
            failed_count = 0
            total_containers = 0
            
            # 检查业务容器状态
            for container in self.containers:
                container_status = container.get_status()
                total_containers += 1
                
                if container_status == "Running":
                    running_count += 1
                elif container_status == "Stopped":
                    stopped_count += 1
                elif container_status in ["Failed", "Unknown"]:
                    failed_count += 1
            
            # 检查直接Docker容器状态（如pause容器）
            if self.docker_client and self.docker_containers:
                for docker_container in self.docker_containers:
                    try:
                        docker_container.reload()
                        status = docker_container.status
                        total_containers += 1
                        
                        if status == "running":
                            running_count += 1
                        elif status == "exited":
                            exit_code = docker_container.attrs.get("State", {}).get("ExitCode", 0)
                            if exit_code == 0:
                                stopped_count += 1
                            else:
                                failed_count += 1
                        else:
                            # creating, restarting, etc.
                            pass
                    except Exception as e:
                        print(f"[WARNING]Failed to check Docker container status: {e}")
            
            # 根据容器状态更新Pod状态
            if total_containers == 0:
                self.status = Config.POD_STATUS_CREATING
            elif running_count == total_containers:
                self.status = Config.POD_STATUS_RUNNING
            elif stopped_count == total_containers:
                self.status = Config.POD_STATUS_STOPPED
            elif failed_count > 0:
                self.status = Config.POD_STATUS_FAILED
            else:
                self.status = Config.POD_STATUS_CREATING
                
        except Exception as e:
            print(f"[WARNING]Failed to refresh Pod status: {e}")
        
        return self.status


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
                       choices=["create", "get", "delete", "start", "stop", "status"],
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
                
        elif args.action == "start":
            print(f"\n[INFO]Starting Pod containers...")
            success = pod.start()
            if success:
                print("[INFO]Pod started successfully")
                print(f"[INFO]Pod Status: {pod.get_status()}")
            else:
                print("[ERROR]Pod start failed")
                
        elif args.action == "stop":
            print(f"\n[INFO]Stopping Pod containers...")
            success = pod.stop()
            if success:
                print("[INFO]Pod stopped successfully")
                print(f"[INFO]Pod Status: {pod.get_status()}")
            else:
                print("[ERROR]Pod stop failed")
                
        elif args.action == "status":
            print(f"\n[INFO]Getting Pod status...")
            status = pod.get_status()
            print(f"[INFO]Pod Status: {json.dumps(status, indent=2, ensure_ascii=False)}")

    except Exception as e:
        print(f"\n[ERROR]Test failed: {e}")
        exit(1)
    
    print("[INFO]Pod API test finished.")
