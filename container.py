import docker
import os
from uuid import uuid1
import platform

from config import Config


class Container:
    def __init__(self, container_config, pod_name=None, namespace="default"):
        """
        初始化容器对象
        
        Args:
            container_config: 容器的配置字典
            pod_name: 所属Pod名称
            namespace: 命名空间
        """
        # 基本信息
        self.id = str(uuid1())
        self.name = container_config.get("name")
        self.image = container_config.get("image")
        self.pod_name = pod_name
        self.namespace = namespace
        
        # 容器配置
        self.command = container_config.get("command", [])
        self.args = container_config.get("args", [])
        self.ports = container_config.get("ports", [])
        self.env = container_config.get("env", [])
        self.volume_mounts = container_config.get("volumeMounts", [])
        self.resources = container_config.get("resources", {})
        
        # 运行时状态
        self.status = "Created"  # Created, Running, Stopped, Failed
        self.docker_container = None
        self.docker_client = None
        self.container_name = self._generate_container_name()
        
        # 初始化Docker客户端
        self._init_docker_client()
        
    def _generate_container_name(self):
        """生成容器名称"""
        if self.pod_name:
            return f"{self.namespace}_{self.pod_name}_{self.name}"
        else:
            return f"{self.namespace}_{self.name}_{self.id[:8]}"
    
    def _init_docker_client(self):
        """初始化Docker客户端"""
        try:
            self.docker_client = docker.from_env()
            # 测试连接
            self.docker_client.ping()
            print(f"[INFO]Docker client initialized successfully for container {self.container_name}")
        except Exception as e:
            print(f"[WARNING]Docker not available for container {self.container_name}: {e}")
            self.docker_client = None
    
    def build_docker_args(self, volumes=None, network_mode=None):
        """
        构建Docker容器运行参数
        
        Args:
            volumes: 卷挂载配置字典
            network_mode: 网络模式
        """
        args = {
            "image": self.image,
            "name": self.container_name,
            "detach": True,
            "remove": False
        }
        
        # 命令和参数
        if self.command:
            if self.args:
                # 如果有command和args，组合它们
                full_command = self.command + self.args
                args["command"] = full_command
            else:
                args["command"] = self.command
        elif self.args:
            # 只有args，使用默认entrypoint
            args["command"] = self.args
        
        # 环境变量
        if self.env:
            env_dict = {}
            for env_var in self.env:
                if isinstance(env_var, dict):
                    name = env_var.get("name")
                    value = env_var.get("value", "")
                    if name:
                        env_dict[name] = value
            if env_dict:
                args["environment"] = env_dict
        
        # 端口映射 - 只在非共享网络模式下使用
        if self.ports and not network_mode:
            ports = {}
            for port_config in self.ports:
                container_port = port_config.get("containerPort")
                host_port = port_config.get("hostPort")
                protocol = port_config.get("protocol", "TCP").lower()
                
                if container_port:
                    port_key = f"{container_port}/{protocol}"
                    if host_port:
                        ports[port_key] = host_port
                    else:
                        ports[port_key] = None
            
            if ports:
                args["ports"] = ports
        
        # 卷挂载
        if self.volume_mounts and volumes:
            volume_binds = {}
            for volume_mount in self.volume_mounts:
                volume_name = volume_mount.get("name")
                mount_path = volume_mount.get("mountPath")
                read_only = volume_mount.get("readOnly", False)
                
                if volume_name in volumes and mount_path:
                    host_path = volumes[volume_name]
                    # 确保宿主机目录存在
                    os.makedirs(host_path, exist_ok=True)
                    
                    bind_config = {"bind": mount_path, "mode": "ro" if read_only else "rw"}
                    volume_binds[host_path] = bind_config
            
            if volume_binds:
                args["volumes"] = volume_binds
        
        # 网络模式
        if network_mode:
            args["network_mode"] = network_mode
        
        return args
    
    def create(self, volumes=None, network_mode=None):
        """
        创建容器
        
        Args:
            volumes: 卷挂载配置字典
            network_mode: 网络模式
        """
        if not self.docker_client:
            print(f"[ERROR]Docker client not available for {self.container_name}")
            self.status = "Failed"
            return False
        
        try:
            # 检查容器是否已存在，如果存在则删除重建
            existing = self.docker_client.containers.list(
                all=True, 
                filters={"name": self.container_name}
            )
            for container in existing:
                print(f"[INFO]Removing existing container: {self.container_name}")
                container.remove(force=True)
            
            # 构建Docker运行参数
            docker_args = self.build_docker_args(volumes, network_mode)
            
            print(f"[INFO]Creating container: {self.container_name}")
            print(f"[DEBUG]Docker args: {docker_args}")
            
            self.docker_container = self.docker_client.containers.run(**docker_args)
            self.status = "Running"
            
            print(f"[INFO]Container {self.container_name} created successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to create container {self.container_name}: {e}")
            self.status = "Failed"
            import traceback
            traceback.print_exc()
            return False
    
    def execute_command(self, command):
        """在容器中执行命令"""
        if not self.docker_container:
            print(f"[ERROR]No Docker container to execute command in {self.container_name}")
            return None, None
        
        try:
            exec_result = self.docker_container.exec_run(command)
            return exec_result.exit_code, exec_result.output.decode('utf-8')
        except Exception as e:
            print(f"[ERROR]Failed to execute command in {self.container_name}: {e}")
            return -1, str(e)
    
    def start(self):
        """启动容器"""
        if not self.docker_container:
            print(f"[ERROR]No Docker container to start for {self.container_name}")
            return False
        
        try:
            if self.docker_container.status != "running":
                self.docker_container.start()
                self.status = "Running"
                print(f"[INFO]Container {self.container_name} started")
            return True
        except Exception as e:
            print(f"[ERROR]Failed to start container {self.container_name}: {e}")
            self.status = "Failed"
            return False
    
    def stop(self):
        """停止容器"""
        if not self.docker_container:
            print(f"[ERROR]No Docker container to stop for {self.container_name}")
            return False
        
        try:
            if self.docker_container.status == "running":
                self.docker_container.stop()
                self.status = "Stopped"
                print(f"[INFO]Container {self.container_name} stopped")
            return True
        except Exception as e:
            print(f"[ERROR]Failed to stop container {self.container_name}: {e}")
            return False
    
    def delete(self):
        """删除容器"""
        if not self.docker_container:
            print(f"[ERROR]No Docker container to delete for {self.container_name}")
            return False
        
        try:
            # 先停止容器
            if self.docker_container.status == "running":
                self.docker_container.stop()
            
            # 删除容器
            self.docker_container.remove(force=True)
            self.status = "Deleted"
            print(f"[INFO]Container {self.container_name} deleted successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to delete container {self.container_name}: {e}")
            return False
    
    def get_status(self):
        """获取容器状态"""
        if not self.docker_container:
            return self.status
        
        try:
            self.docker_container.reload()
            docker_status = self.docker_container.status
            
            # 映射Docker状态到我们的状态
            status_mapping = {
                "running": "Running",
                "exited": "Stopped",
                "created": "Created",
                "restarting": "Running",
                "removing": "Deleting",
                "paused": "Paused",
                "dead": "Failed"
            }
            
            self.status = status_mapping.get(docker_status, "Unknown")
            return self.status
            
        except Exception as e:
            print(f"[ERROR]Failed to get container status for {self.container_name}: {e}")
            return "Unknown"
    
    def get_logs(self, tail=100):
        """获取容器日志"""
        if not self.docker_container:
            return f"[ERROR]No Docker container for {self.container_name}"
        
        try:
            logs = self.docker_container.logs(tail=tail).decode('utf-8')
            return logs
        except Exception as e:
            return f"[ERROR]Failed to get logs for {self.container_name}: {e}"
    
    def get_info(self):
        """获取容器详细信息"""
        info = {
            "id": self.id,
            "name": self.name,
            "container_name": self.container_name,
            "image": self.image,
            "pod_name": self.pod_name,
            "namespace": self.namespace,
            "status": self.get_status(),
            "command": self.command,
            "args": self.args,
            "ports": self.ports,
            "env": self.env,
            "volume_mounts": self.volume_mounts,
            "resources": self.resources
        }
        
        if self.docker_container:
            try:
                self.docker_container.reload()
                info["docker_id"] = self.docker_container.id
                info["docker_status"] = self.docker_container.status
            except:
                pass
        
        return info
    
    def __str__(self):
        return f"Container(name={self.name}, image={self.image}, status={self.status})"
    
    def __repr__(self):
        return self.__str__()
