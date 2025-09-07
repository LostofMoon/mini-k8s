import json
import subprocess
import ipaddress
import time
import os
import socket
from typing import Dict, List, Optional, Tuple
import docker
from config import Config


class NetworkManager:
    """Pod网络管理器，负责IP分配和网络配置 (单例模式)"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(NetworkManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 如果已经初始化过，直接返回
        if NetworkManager._initialized:
            return
            
        self.subnet_base = "10.5.0.0/16"  # Pod网络子网
        self.bridge_name = "mini-k8s-br0"  # 网桥名称
        self.ip_pool = set()  # 已分配的IP地址池
        self.pod_ip_mapping = {}  # Pod名称到IP的映射
        self.network_cache = {}  # 网络信息缓存
        
        # 初始化网络基础设施
        self._init_network_infrastructure()
        
        # 标记为已初始化
        NetworkManager._initialized = True
        
    def _init_network_infrastructure(self):
        """初始化网络基础设施，创建网桥和网络配置"""
        try:
            # 检查是否已存在网桥
            if not self._bridge_exists():
                self._create_bridge()
            
            # 初始化IP池
            self._initialize_ip_pool()
            
            print(f"[INFO] 网络管理器初始化完成 - 子网: {self.subnet_base}")
            
        except Exception as e:
            print(f"[ERROR] 网络基础设施初始化失败: {e}")
            
    def _bridge_exists(self) -> bool:
        """检查网桥是否存在"""
        try:
            # 使用docker network命令检查网络
            result = subprocess.run(
                ["docker", "network", "ls", "--format", "{{.Name}}"],
                capture_output=True, text=True, check=True
            )
            return self.bridge_name in result.stdout
        except subprocess.CalledProcessError:
            return False
            
    def _create_bridge(self):
        """创建Docker网桥网络"""
        try:
            # 创建自定义网络，类似于CNI的功能
            cmd = [
                "docker", "network", "create",
                "--driver", "bridge",
                "--subnet", self.subnet_base,
                "--opt", "com.docker.network.bridge.name=" + self.bridge_name,
                self.bridge_name
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"[INFO] 创建网桥网络成功: {self.bridge_name}")
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] 创建网桥失败: {e.stderr}")
            raise
            
    def _initialize_ip_pool(self):
        """初始化IP地址池"""
        try:
            # 解析子网，预留部分IP地址
            network = ipaddress.IPv4Network(self.subnet_base)
            
            # 预留前10个和后10个IP地址
            reserved_ips = set()
            for i, ip in enumerate(network.hosts()):
                if i < 10 or i >= network.num_addresses - 12:  # 预留前10个和后10个
                    reserved_ips.add(str(ip))
                    
            # 检查Docker网络中已分配的IP，避免冲突
            try:
                import subprocess
                result = subprocess.run([
                    "docker", "network", "inspect", self.bridge_name,
                    "--format", "{{range .Containers}}{{.IPv4Address}}{{end}}"
                ], capture_output=True, text=True, check=False)
                
                if result.returncode == 0 and result.stdout.strip():
                    # 解析已使用的IP地址
                    used_ips_raw = result.stdout.strip().split()
                    for ip_with_mask in used_ips_raw:
                        if "/" in ip_with_mask:
                            used_ip = ip_with_mask.split("/")[0]
                            reserved_ips.add(used_ip)
                            print(f"[INFO] 发现已使用的IP: {used_ip}")
                            
            except Exception as e:
                print(f"[WARNING] 检查已使用IP时出错: {e}")
                    
            self.ip_pool = reserved_ips
            print(f"[INFO] IP池初始化完成，预留{len(self.ip_pool)}个地址")
            
        except Exception as e:
            print(f"[ERROR] IP池初始化失败: {e}")
            
    def allocate_pod_ip(self, pod_name: str, namespace: str = "default") -> str:
        """为Pod分配IP地址"""
        try:
            # 检查是否已为此Pod分配IP
            pod_key = f"{namespace}/{pod_name}"
            if pod_key in self.pod_ip_mapping:
                return self.pod_ip_mapping[pod_key]
            
            # 刷新IP池状态，检查Docker网络中的实际使用情况
            self._refresh_ip_pool_state()
            
            # 分配新IP
            network = ipaddress.IPv4Network(self.subnet_base)
            for ip in network.hosts():
                ip_str = str(ip)
                if ip_str not in self.ip_pool:
                    # 双重检查：确认IP未被Docker容器使用
                    if not self._is_ip_in_use(ip_str):
                        self.ip_pool.add(ip_str)
                        self.pod_ip_mapping[pod_key] = ip_str
                        print(f"[INFO] 为Pod {pod_key} 分配IP: {ip_str}")
                        return ip_str
                    else:
                        # IP正在使用中，添加到已用池
                        self.ip_pool.add(ip_str)
                    
            raise Exception("没有可用的IP地址")
            
        except Exception as e:
            print(f"[ERROR] IP分配失败: {e}")
            raise
            
    def _refresh_ip_pool_state(self):
        """刷新IP池状态，与Docker网络实际情况同步"""
        try:
            import subprocess
            result = subprocess.run([
                "docker", "network", "inspect", self.bridge_name,
                "--format", "{{range .Containers}}{{.IPv4Address}}\n{{end}}"
            ], capture_output=True, text=True, check=False)
            
            if result.returncode == 0 and result.stdout.strip():
                used_ips = set()
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and "/" in line:
                        used_ip = line.split("/")[0]
                        if used_ip:  # 确保IP不为空
                            used_ips.add(used_ip)
                
                # 更新IP池状态
                self.ip_pool.update(used_ips)
                print(f"[DEBUG] 刷新IP池状态，当前已用IP: {used_ips}")
                        
        except Exception as e:
            print(f"[WARNING] 刷新IP池状态时出错: {e}")
            
    def _is_ip_in_use(self, ip_str):
        """检查IP地址是否正在被Docker容器使用"""
        try:
            import subprocess
            result = subprocess.run([
                "docker", "network", "inspect", self.bridge_name,
                "--format", "{{range .Containers}}{{.IPv4Address}}{{end}}"
            ], capture_output=True, text=True, check=False)
            
            if result.returncode == 0 and result.stdout.strip():
                for ip_with_mask in result.stdout.strip().split():
                    if "/" in ip_with_mask:
                        used_ip = ip_with_mask.split("/")[0]
                        if used_ip == ip_str:
                            return True
            return False
            
        except Exception as e:
            print(f"[WARNING] 检查IP使用状态时出错: {e}")
            return False
            
    def release_pod_ip(self, pod_name: str, namespace: str = "default"):
        """释放Pod的IP地址"""
        try:
            pod_key = f"{namespace}/{pod_name}"
            if pod_key in self.pod_ip_mapping:
                ip = self.pod_ip_mapping[pod_key]
                self.ip_pool.discard(ip)
                del self.pod_ip_mapping[pod_key]
                print(f"[INFO] 释放Pod {pod_key} 的IP: {ip}")
                
        except Exception as e:
            print(f"[ERROR] IP释放失败: {e}")
            
    def get_pod_ip(self, pod_name: str, namespace: str = "default") -> Optional[str]:
        """获取Pod的IP地址"""
        pod_key = f"{namespace}/{pod_name}"
        return self.pod_ip_mapping.get(pod_key)
        
    def create_pod_network(self, pod_name: str, namespace: str = "default") -> Dict:
        """为Pod创建网络配置"""
        try:
            # 分配IP地址
            pod_ip = self.allocate_pod_ip(pod_name, namespace)
            
            # 创建网络配置
            network_config = {
                "name": self.bridge_name,
                "ip": pod_ip,
                "subnet": self.subnet_base
            }
            
            # 缓存网络配置
            pod_key = f"{namespace}/{pod_name}"
            self.network_cache[pod_key] = network_config
            
            return network_config
            
        except Exception as e:
            print(f"[ERROR] 创建Pod网络配置失败: {e}")
            raise
            
    def delete_pod_network(self, pod_name: str, namespace: str = "default"):
        """删除Pod的网络配置"""
        try:
            pod_key = f"{namespace}/{pod_name}"
            
            # 释放IP地址
            self.release_pod_ip(pod_name, namespace)
            
            # 清除缓存
            if pod_key in self.network_cache:
                del self.network_cache[pod_key]
                
            print(f"[INFO] 删除Pod {pod_key} 网络配置完成")
            
        except Exception as e:
            print(f"[ERROR] 删除Pod网络配置失败: {e}")
            
    def get_network_info(self) -> Dict:
        """获取网络管理器状态信息"""
        return {
            "subnet": self.subnet_base,
            "bridge_name": self.bridge_name,
            "allocated_ips": len(self.ip_pool),
            "active_pods": len(self.pod_ip_mapping),
            "pod_mappings": dict(self.pod_ip_mapping)
        }


class PodNetworkAttacher:
    """Pod网络附加器，负责将容器连接到Pod网络"""
    
    def __init__(self, network_manager: NetworkManager):
        self.network_manager = network_manager
        self.docker_client = docker.from_env()
        
    def attach_container_to_pod_network(self, container_id: str, pod_name: str, 
                                      namespace: str = "default") -> bool:
        """将容器连接到Pod网络"""
        try:
            # 获取网络配置
            pod_key = f"{namespace}/{pod_name}"
            network_config = self.network_manager.network_cache.get(pod_key)
            
            if not network_config:
                print(f"[WARNING] 未找到Pod {pod_key} 的网络配置")
                return False
                
            network_name = network_config["name"]
            target_ip = network_config["ip"]
            
            # 连接容器到网络
            network = self.docker_client.networks.get(network_name)
            container = self.docker_client.containers.get(container_id)
            
            # 检查容器是否已连接到目标网络
            container.reload()
            current_networks = container.attrs['NetworkSettings']['Networks']
            
            if network_name not in current_networks:
                # 连接到网络并指定IP
                network.connect(container, ipv4_address=target_ip)
                print(f"[INFO] 容器 {container_id[:12]} 已连接到网络 {network_name}, IP: {target_ip}")
            else:
                # 检查IP是否正确
                current_ip = current_networks[network_name].get('IPAddress')
                if current_ip != target_ip:
                    # 断开重连以获得正确IP
                    network.disconnect(container)
                    network.connect(container, ipv4_address=target_ip)
                    print(f"[INFO] 容器 {container_id[:12]} 重新连接到网络 {network_name}, IP: {target_ip}")
                else:
                    print(f"[INFO] 容器 {container_id[:12]} 已正确连接到网络 {network_name}, IP: {current_ip}")
                
            return True
            
        except Exception as e:
            print(f"[ERROR] 容器网络连接失败: {e}")
            return False
            
    def detach_container_from_pod_network(self, container_id: str, pod_name: str, 
                                        namespace: str = "default") -> bool:
        """从Pod网络断开容器"""
        try:
            network_config = self.network_manager.network_cache.get(f"{namespace}/{pod_name}")
            if not network_config:
                return True  # 已经断开或未连接
                
            network_name = network_config["name"]
            network = self.docker_client.networks.get(network_name)
            container = self.docker_client.containers.get(container_id)
            
            network.disconnect(container)
            print(f"[INFO] 容器 {container_id[:12]} 已从网络 {network_name} 断开")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] 容器网络断开失败: {e}")
            return False


# 全局网络管理器实例
_global_network_manager = None
_global_network_attacher = None

def get_network_manager() -> NetworkManager:
    """获取全局网络管理器实例"""
    global _global_network_manager
    if _global_network_manager is None:
        _global_network_manager = NetworkManager()
    return _global_network_manager

def get_network_attacher() -> PodNetworkAttacher:
    """获取全局网络附加器实例"""
    global _global_network_attacher
    if _global_network_attacher is None:
        _global_network_attacher = PodNetworkAttacher(get_network_manager())
    return _global_network_attacher


if __name__ == "__main__":
    # 测试网络管理功能
    print("=== Mini-K8s 网络管理器测试 ===")
    
    # 初始化网络管理器
    nm = get_network_manager()
    
    # 测试IP分配
    print("\n--- IP分配测试 ---")
    ip1 = nm.allocate_pod_ip("test-pod-1", "default")
    ip2 = nm.allocate_pod_ip("test-pod-2", "default")
    print(f"Pod1 IP: {ip1}")
    print(f"Pod2 IP: {ip2}")
    
    # 测试网络配置创建
    print("\n--- 网络配置测试 ---")
    config1 = nm.create_pod_network("test-pod-1", "default")
    print(f"网络配置: {json.dumps(config1, indent=2)}")
    
    # 显示网络状态
    print("\n--- 网络状态 ---")
    info = nm.get_network_info()
    print(f"网络信息: {json.dumps(info, indent=2)}")
    
    # 清理测试
    print("\n--- 清理测试 ---")
    nm.delete_pod_network("test-pod-1", "default")
    nm.delete_pod_network("test-pod-2", "default")
    
    info = nm.get_network_info()
    print(f"清理后网络信息: {json.dumps(info, indent=2)}")
