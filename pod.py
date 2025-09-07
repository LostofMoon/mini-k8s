import requests
import json
from uuid import uuid1
import docker
import platform
import os

from config import Config


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
        self.containers_config = []
        for container_json in spec.get("containers", []):
            container = {
                "name": container_json.get("name"),
                "image": container_json.get("image"),
                "command": container_json.get("command", []),
                "args": container_json.get("args", []),
                "ports": container_json.get("ports", []),
                "env": container_json.get("env", []),
                "volumeMounts": container_json.get("volumeMounts", []),
                "resources": container_json.get("resources", {})
            }
            self.containers_config.append(container)
        
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
            print(f"[WARNING]Docker client connection failed: {e}")
            print(f"[INFO]Pod will run in simulation mode")
            self.docker_client = None
    
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
        """创建真实的Docker容器"""
        if not self.docker_client:
            print(f"[WARNING]Docker client not available, using simulation mode")
            return self._create_simulated_containers()
        
        try:
            # 1. 创建pause容器（用于网络共享）
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
                for container_config in self.containers_config:
                    if container_config.get("ports"):
                        for port_config in container_config["ports"]:
                            container_port = port_config.get("containerPort")
                            host_port = port_config.get("hostPort")
                            protocol = port_config.get("protocol", "TCP").lower()
                            
                            if container_port:
                                port_key = f"{container_port}/{protocol}"
                                if host_port:
                                    pause_ports[port_key] = host_port
                                # 不自动映射端口，只映射明确指定的hostPort
                
                # 创建pause容器参数
                pause_args = {
                    "image": "busybox:latest",
                    "name": pause_name,
                    "command": ["sh", "-c", "echo '[INFO]Pod network init' && sleep 3600"],
                    "detach": True,
                    "remove": False
                }
                
                # 只在有端口需要映射时添加ports参数
                if pause_ports:
                    pause_args["ports"] = pause_ports
                
                pause_container = self.docker_client.containers.run(**pause_args)
            
            self.docker_containers.append(pause_container)
            
            # 获取Pod IP地址
            self.subnet_ip = self._get_pod_ip(pause_container)
            print(f"[INFO]Pod IP address: {self.subnet_ip}")
            
            # 2. 创建业务容器
            for container_config in self.containers_config:
                container_name = f"{self.namespace}_{self.name}_{container_config['name']}"
                
                # 检查容器是否已存在，如果存在则删除重建
                existing = self.docker_client.containers.list(
                    all=True, 
                    filters={"name": container_name}
                )
                for container in existing:
                    print(f"[INFO]Removing existing container: {container_name}")
                    container.remove(force=True)
                
                # 构建Docker运行参数
                docker_args = self._build_docker_args(container_config, container_name)
                
                # 使用pause容器的网络
                docker_args["network_mode"] = f"container:{pause_name}"
                
                print(f"[INFO]Creating container: {container_name}")
                print(f"[DEBUG]Docker args: {docker_args}")
                
                container = self.docker_client.containers.run(**docker_args)
                self.docker_containers.append(container)
                
                print(f"[INFO]Container {container_name} created successfully")
            
            print(f"[INFO]All containers created for Pod {self.namespace}:{self.name}")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to create Docker containers: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _create_simulated_containers(self):
        """模拟容器创建（当Docker不可用时）"""
        print(f"[INFO]Creating simulated containers for Pod {self.namespace}:{self.name}")
        
        # 模拟pause容器
        pause_name = f"pause_{self.namespace}_{self.name}"
        print(f"[INFO]Simulated pause container: {pause_name}")
        
        # 模拟业务容器
        for container_config in self.containers_config:
            container_name = f"{self.namespace}_{self.name}_{container_config['name']}"
            print(f"[INFO]Simulated container: {container_name} ({container_config['image']})")
        
        # 分配模拟IP
        self.subnet_ip = "10.244.1.100"
        print(f"[INFO]Simulated Pod IP: {self.subnet_ip}")
        
        return True
    
    def _build_docker_args(self, container_config, container_name):
        """构建Docker容器运行参数"""
        args = {
            "image": container_config["image"],
            "name": container_name,
            "detach": True,
            "remove": False
        }
        
        # 命令和参数
        if container_config.get("command"):
            if container_config.get("args"):
                # 如果有command和args，组合它们
                full_command = container_config["command"] + container_config["args"]
                args["command"] = full_command
            else:
                args["command"] = container_config["command"]
        elif container_config.get("args"):
            # 只有args，使用默认entrypoint
            args["command"] = container_config["args"]
        
        # 环境变量
        if container_config.get("env"):
            env_dict = {}
            for env_var in container_config["env"]:
                if isinstance(env_var, dict):
                    name = env_var.get("name")
                    value = env_var.get("value", "")
                    if name:
                        env_dict[name] = value
            if env_dict:
                args["environment"] = env_dict
        
        # 端口映射 - 只在非共享网络模式下使用
        # 注意：当使用 network_mode='container:xxx' 时，不能设置端口映射
        # 端口映射应该在pause容器创建时处理
        # if container_config.get("ports"):
        #     ports = {}
        #     for port_config in container_config["ports"]:
        #         container_port = port_config.get("containerPort")
        #         host_port = port_config.get("hostPort")
        #         protocol = port_config.get("protocol", "TCP").lower()
        #         
        #         if container_port:
        #             port_key = f"{container_port}/{protocol}"
        #             if host_port:
        #                 ports[port_key] = host_port
        #             else:
        #                 ports[port_key] = None
        #     
        #     if ports:
        #         args["ports"] = ports
        
        # 卷挂载
        if container_config.get("volumeMounts") and self.volumes:
            volumes = {}
            for volume_mount in container_config["volumeMounts"]:
                volume_name = volume_mount.get("name")
                mount_path = volume_mount.get("mountPath")
                read_only = volume_mount.get("readOnly", False)
                
                if volume_name in self.volumes and mount_path:
                    host_path = self.volumes[volume_name]
                    # 确保宿主机目录存在
                    os.makedirs(host_path, exist_ok=True)
                    
                    bind_config = {"bind": mount_path, "mode": "ro" if read_only else "rw"}
                    volumes[host_path] = bind_config
            
            if volumes:
                args["volumes"] = volumes
        
        return args
    
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
        """删除真实的Docker容器"""
        if not self.docker_client:
            print(f"[INFO]Simulated containers cleanup for Pod {self.namespace}:{self.name}")
            return True
        
        try:
            # 删除所有关联的容器
            for container in self.docker_containers:
                try:
                    container_name = container.name
                    print(f"[INFO]Stopping and removing container: {container_name}")
                    
                    # 强制停止容器
                    container.kill()
                    container.remove(force=True)
                    
                    print(f"[INFO]Container {container_name} removed successfully")
                    
                except Exception as e:
                    print(f"[WARNING]Failed to remove container {container.name}: {e}")
            
            # 清空容器列表
            self.docker_containers = []
            
            # 另外，通过名称清理可能遗留的容器
            self._cleanup_containers_by_name()
            
            print(f"[INFO]All containers deleted for Pod {self.namespace}:{self.name}")
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
            for container_config in self.containers_config:
                container_name = f"{self.namespace}_{self.name}_{container_config['name']}"
                business_containers = self.docker_client.containers.list(
                    all=True, 
                    filters={"name": container_name}
                )
                for container in business_containers:
                    container.remove(force=True)
                    print(f"[INFO]Cleaned up business container: {container_name}")
                    
        except Exception as e:
            print(f"[WARNING]Failed to cleanup containers by name: {e}")
    
    def start(self):
        """启动Pod中的所有容器"""
        if not self.docker_client:
            print(f"[INFO]Simulated start for Pod {self.namespace}:{self.name}")
            self.status = Config.POD_STATUS_RUNNING
            return True
        
        try:
            print(f"[INFO]Starting Pod {self.namespace}:{self.name}")
            
            for container in self.docker_containers:
                if container.status != "running":
                    container.start()
                    print(f"[INFO]Started container: {container.name}")
            
            self.status = Config.POD_STATUS_RUNNING
            print(f"[INFO]Pod {self.namespace}:{self.name} started successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to start Pod: {e}")
            return False
    
    def stop(self):
        """停止Pod中的所有容器"""
        if not self.docker_client:
            print(f"[INFO]Simulated stop for Pod {self.namespace}:{self.name}")
            self.status = Config.POD_STATUS_STOPPED
            return True
        
        try:
            print(f"[INFO]Stopping Pod {self.namespace}:{self.name}")
            
            for container in self.docker_containers:
                if container.status == "running":
                    container.stop()
                    print(f"[INFO]Stopped container: {container.name}")
            
            self.status = Config.POD_STATUS_STOPPED
            print(f"[INFO]Pod {self.namespace}:{self.name} stopped successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to stop Pod: {e}")
            return False
    
    def get_status(self):
        """获取Pod状态信息"""
        # 刷新容器状态
        if self.docker_client and self.docker_containers:
            self._refresh_status()
        
        return {
            "name": f"{self.namespace}:{self.name}",
            "status": self.status,
            "ip": self.subnet_ip,
            "node": self.node_name,
            "containers": len(self.containers_config),
            "docker_containers": len(self.docker_containers) if self.docker_containers else 0
        }
    
    def _refresh_status(self):
        """刷新Pod状态（基于容器状态）"""
        if not self.docker_client or not self.docker_containers:
            return self.status
        
        try:
            running_count = 0
            stopped_count = 0
            failed_count = 0
            
            for container in self.docker_containers:
                container.reload()
                status = container.status
                
                if status == "running":
                    running_count += 1
                elif status == "exited":
                    exit_code = container.attrs.get("State", {}).get("ExitCode", 0)
                    if exit_code == 0:
                        stopped_count += 1
                    else:
                        failed_count += 1
                else:
                    # creating, restarting, etc.
                    pass
            
            # 根据容器状态更新Pod状态
            total_containers = len(self.docker_containers)
            if running_count == total_containers:
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
