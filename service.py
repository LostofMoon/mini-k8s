#!/usr/bin/env python3
"""
Mini-K8s Service实现
提供服务发现、负载均衡和网络代理功能
支持ClusterIP和NodePort类型
参考Kubernetes标准架构设计
"""

import yaml
import json
import uuid
import time
import subprocess
import random
import ipaddress
import requests
import logging
import threading
import string
import platform
import shutil
from typing import Dict, List, Optional, Any, Tuple
from config import Config

class ServiceManager:
    """全局Service管理器 - 运行在控制平面，负责Service的生命周期管理"""
    
    def __init__(self):
        self.services = {}  # {namespace/name: Service}
        self.api_server_url = Config.SERVER_URI
        self.logger = logging.getLogger(__name__)
        
    def create_service(self, service_config: Dict[str, Any]) -> 'Service':
        """创建Service"""
        service = Service(service_config)
        service_key = f"{service.namespace}/{service.name}"
        self.services[service_key] = service
        
        # 分配ClusterIP
        service.allocate_cluster_ip()
        
        # 立即同步端点
        self.sync_service_endpoints(service)
        return service
    
    def delete_service(self, namespace: str, name: str) -> bool:
        """删除Service"""
        service_key = f"{namespace}/{name}"
        if service_key in self.services:
            service = self.services[service_key]
            service.release_cluster_ip()
            del self.services[service_key]
            return True
        return False
    
    def get_service(self, namespace: str, name: str) -> Optional['Service']:
        """获取Service"""
        service_key = f"{namespace}/{name}"
        return self.services.get(service_key)
    
    def list_services(self, namespace: str = None) -> List['Service']:
        """列出Services"""
        if namespace:
            return [svc for key, svc in self.services.items() if svc.namespace == namespace]
        return list(self.services.values())
    
    def sync_all_endpoints(self):
        """同步所有Service的端点"""
        for service in self.services.values():
            self.sync_service_endpoints(service)
    
    def sync_service_endpoints(self, service: 'Service'):
        """同步单个Service的端点"""
        try:
            # 从ApiServer获取所有Pod
            response = requests.get(f"{self.api_server_url}{Config.GLOBAL_PODS_URL}", timeout=5)
            if response.status_code == 200:
                pods_data = response.json()
                # 兼容不同的API返回格式
                if isinstance(pods_data, dict):
                    pods = pods_data.get("items", pods_data.get("pods", []))
                else:
                    pods = pods_data
                
                service.update_endpoints(pods)
            else:
                self.logger.warning(f"Failed to fetch pods from ApiServer: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Failed to sync endpoints for Service {service.namespace}/{service.name}: {e}")

# 全局Service管理器实例
service_manager = ServiceManager()

class Service:
    """Service类 - 负载均衡和服务发现"""
    
    # ClusterIP分配池
    CLUSTER_IP_POOL = "10.96.0.0/16"  # Kubernetes默认Service CIDR
    allocated_ips = set()
    
    def __init__(self, config_dict: Dict[str, Any]):
        self.config_dict = config_dict
        
        # 基本元数据
        metadata = config_dict.get("metadata", {})
        self.name = metadata.get("name")
        self.namespace = metadata.get("namespace", "default")
        self.labels = metadata.get("labels", {})
        self.uid = str(uuid.uuid4())
        
        # Service规格
        spec = config_dict.get("spec", {})
        self.service_type = spec.get("type", "ClusterIP")  # 支持ClusterIP和NodePort
        self.cluster_ip = spec.get("clusterIP", None)  # 虚拟IP，由系统分配
        self.selector = spec.get("selector", {})  # Pod选择器
        
        # 端口配置 - 支持多个端口
        self.ports = []
        ports = spec.get("ports", [])
        if not ports:
            raise ValueError("Service must have at least one port configuration")
            
        for port_config in ports:
            port_info = {
                "name": port_config.get("name", "default"),
                "port": int(port_config.get("port", 80)),
                "target_port": int(port_config.get("targetPort", 80)),
                "protocol": port_config.get("protocol", "TCP"),
                "node_port": int(port_config.get("nodePort")) if port_config.get("nodePort") and self.service_type == "NodePort" else None
            }
            self.ports.append(port_info)
        
        # 运行时状态
        self.status = "Pending"
        self.created_time = time.time()
        self.last_updated = self.created_time
        
        # 端点管理
        self.endpoints = []  # [(ip, port), ...]
        self.endpoint_pods = {}  # {endpoint: pod_info}
        
        # 网络配置管理
        self.iptables_rules = []
        
        print(f"[INFO]Service {self.namespace}/{self.name} initialized")
    
    def allocate_cluster_ip(self) -> str:
        """分配ClusterIP"""
        if self.cluster_ip and self.cluster_ip != "None":
            return self.cluster_ip
            
        network = ipaddress.IPv4Network(self.CLUSTER_IP_POOL)
        
        # 跳过网络地址和广播地址
        available_ips = list(network.hosts())
        
        # 过滤已分配的IP
        available_ips = [ip for ip in available_ips if str(ip) not in self.allocated_ips]
        
        if not available_ips:
            raise RuntimeError("ClusterIP pool exhausted")
        
        # 随机选择一个IP
        selected_ip = str(random.choice(available_ips))
        self.allocated_ips.add(selected_ip)
        self.cluster_ip = selected_ip
        
        print(f"[INFO]Allocated ClusterIP {selected_ip} for Service {self.namespace}/{self.name}")
        return selected_ip
    
    @classmethod
    def release_cluster_ip(cls, ip: str):
        """释放ClusterIP"""
        cls.allocated_ips.discard(ip)
    
    def matches_pod(self, pod_labels: Dict[str, str]) -> bool:
        """检查Pod标签是否匹配Service的选择器"""
        if not self.selector or not pod_labels:
            return False
            
        for key, value in self.selector.items():
            if key not in pod_labels or pod_labels[key] != value:
                return False
        return True
    
    def get_pod_ip(self, pod_data: Dict) -> Optional[str]:
        """从Pod数据中获取IP地址"""
        try:
            # 优先从status中获取IP
            if "status" in pod_data and "podIP" in pod_data["status"]:
                return pod_data["status"]["podIP"]
            
            # 从ip字段获取
            if "ip" in pod_data and pod_data["ip"] != "<none>":
                return pod_data["ip"]
            
            # 从subnet_ip获取（兼容性）
            if "subnet_ip" in pod_data and pod_data["subnet_ip"] != "None":
                return pod_data["subnet_ip"]
                
            return None
        except Exception as e:
            print(f"[ERROR]Failed to get Pod IP: {e}")
            return None
    
    def update_endpoints(self, pods: List[Dict]) -> bool:
        """更新Service端点"""
        try:
            new_endpoints = []
            new_endpoint_pods = {}
            
            # 发现匹配的Pod端点
            for pod in pods:
                # 检查Pod是否匹配Service的选择器
                pod_labels = pod.get("metadata", {}).get("labels", {})
                if not self.matches_pod(pod_labels):
                    continue
                
                # 获取Pod的IP地址
                pod_ip = self.get_pod_ip(pod)
                if not pod_ip:
                    continue
                
                # 为每个端口创建端点
                for port_info in self.ports:
                    endpoint = (pod_ip, port_info["target_port"])
                    new_endpoints.append(endpoint)
                    
                    # 保存Pod信息
                    endpoint_key = f"{pod_ip}:{port_info['target_port']}"
                    new_endpoint_pods[endpoint_key] = {
                        "name": pod.get("metadata", {}).get("name", "unknown"),
                        "namespace": pod.get("metadata", {}).get("namespace", "default"),
                        "node_name": pod.get("node", "unknown"),
                        "labels": pod_labels
                    }
            
            # 检查端点是否有变化
            if self._are_endpoints_equal(self.endpoints, new_endpoints):
                return False
            
            print(f"[INFO]Service {self.namespace}/{self.name} endpoints changed: {len(new_endpoints)} endpoints")
            
            # 更新端点
            old_endpoints = self.endpoints.copy()
            self.endpoints = new_endpoints
            self.endpoint_pods = new_endpoint_pods
            self.last_updated = time.time()
            
            # 更新网络规则
            self._update_network_rules()
            
            # 更新状态
            self.status = "Running" if new_endpoints else "Pending"
            
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to update Service endpoints: {e}")
            self.status = "Failed"
            return False
    
    def _are_endpoints_equal(self, endpoints1: List[Tuple[str, int]], endpoints2: List[Tuple[str, int]]) -> bool:
        """比较两组端点是否相同"""
        if len(endpoints1) != len(endpoints2):
            return False
            
        set1 = set(endpoints1)
        set2 = set(endpoints2)
        return set1 == set2
    
    def _update_network_rules(self):
        """更新网络规则（iptables）"""
        if not self.cluster_ip:
            return
            
        # 清理旧规则
        self._cleanup_iptables_rules()
        
        # 如果没有端点，不创建新规则
        if not self.endpoints:
            return
            
        # 设置新规则
        self._setup_iptables_rules()
    
    def _setup_iptables_rules(self):
        """设置iptables规则实现负载均衡"""
        if not self.endpoints or not self.cluster_ip:
            return
        
        # 由于Windows环境不支持iptables，这里使用模拟实现
        # 实际Linux环境中会执行真实的iptables命令
        print(f"[INFO]Setting up network rules for Service {self.namespace}/{self.name}")
        
        for port_info in self.ports:
            service_port = port_info["port"]
            protocol = port_info["protocol"].lower()
            
            # 获取这个端口对应的所有端点
            port_endpoints = [ep for ep in self.endpoints if ep[1] == port_info["target_port"]]
            
            if not port_endpoints:
                continue
            
            # 模拟iptables规则创建 - 实际环境中会执行真实命令
            print(f"[DEBUG]Would create ClusterIP rules for {self.cluster_ip}:{service_port} -> {len(port_endpoints)} endpoints")
            
            # NodePort规则
            if self.service_type == "NodePort" and port_info["node_port"]:
                print(f"[DEBUG]Would create NodePort rules for :{port_info['node_port']} -> {len(port_endpoints)} endpoints")
        
        # 记录规则已设置
        self.iptables_rules.append(f"ClusterIP-{self.cluster_ip}-rules")
    
    def _setup_nodeport_rules(self, port_info: Dict, endpoints: List[Tuple[str, int]]):
        """设置NodePort规则"""
        node_port = port_info["node_port"]
        protocol = port_info["protocol"].lower()
        
        # 模拟NodePort规则设置
        print(f"[DEBUG]Setting up NodePort {node_port} for {len(endpoints)} endpoints")
        
        for endpoint in endpoints:
            print(f"[DEBUG]NodePort rule: :{node_port} -> {endpoint[0]}:{endpoint[1]}")
    
    def _cleanup_iptables_rules(self):
        """清理iptables规则"""
        print(f"[DEBUG]Cleaning up network rules for Service {self.namespace}/{self.name}")
        self.iptables_rules.clear()
    
    def start(self, pods: List[Dict] = None):
        """启动Service"""
        try:
            print(f"[INFO]Starting Service {self.namespace}/{self.name}")
            
            # 分配ClusterIP
            if not self.cluster_ip or self.cluster_ip == "None":
                self.allocate_cluster_ip()
            
            # 更新端点
            if pods:
                self.update_endpoints(pods)
            
            self.status = "Running"
            print(f"[INFO]Service {self.namespace}/{self.name} started successfully")
            
        except Exception as e:
            print(f"[ERROR]Failed to start Service: {e}")
            self.status = "Failed"
            raise
    
    def stop(self):
        """停止Service"""
        try:
            print(f"[INFO]Stopping Service {self.namespace}/{self.name}")
            
            # 删除iptables规则
            self._cleanup_iptables_rules()
            
            # 释放ClusterIP
            if self.cluster_ip:
                self.release_cluster_ip(self.cluster_ip)
            
            self.status = "Stopped"
            print(f"[INFO]Service {self.namespace}/{self.name} stopped")
            
        except Exception as e:
            print(f"[ERROR]Failed to stop Service: {e}")
    
    def select_endpoint(self, target_port: int) -> Optional[Tuple[str, int]]:
        """为指定端口选择一个端点（简单轮询负载均衡）"""
        port_endpoints = [ep for ep in self.endpoints if ep[1] == target_port]
        
        if not port_endpoints:
            return None
        
        # 简单轮询算法
        if not hasattr(self, '_endpoint_index'):
            self._endpoint_index = {}
        
        if target_port not in self._endpoint_index:
            self._endpoint_index[target_port] = 0
        
        endpoint = port_endpoints[self._endpoint_index[target_port] % len(port_endpoints)]
        self._endpoint_index[target_port] += 1
        
        return endpoint
    
    def get_service_url(self, port_name: str = None) -> Optional[str]:
        """获取Service访问URL"""
        if not self.cluster_ip:
            return None
        
        if port_name:
            for port_info in self.ports:
                if port_info["name"] == port_name:
                    return f"http://{self.cluster_ip}:{port_info['port']}"
        else:
            # 返回第一个端口的URL
            if self.ports:
                return f"http://{self.cluster_ip}:{self.ports[0]['port']}"
        
        return None
    
    def get_stats(self) -> Dict:
        """获取Service统计信息"""
        stats = {
            "name": self.name,
            "namespace": self.namespace,
            "type": self.service_type,
            "cluster_ip": self.cluster_ip,
            "status": self.status,
            "endpoints": len(self.endpoints),
            "endpoint_details": []
        }
        
        # 添加端点信息
        for endpoint in self.endpoints:
            endpoint_key = f"{endpoint[0]}:{endpoint[1]}"
            pod_info = self.endpoint_pods.get(endpoint_key, {})
            stats["endpoint_details"].append({
                "endpoint": endpoint_key,
                "pod_name": pod_info.get("name", "unknown"),
                "node_name": pod_info.get("node_name", "unknown")
            })
        
        return stats
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
                "uid": self.uid
            },
            "spec": {
                "type": self.service_type,
                "clusterIP": self.cluster_ip,
                "selector": self.selector,
                "ports": self.ports
            },
            "status": {
                "phase": self.status,
                "endpoints": [
                    {
                        "ip": endpoint[0],
                        "port": endpoint[1],
                        "ready": True
                    } for endpoint in self.endpoints
                ],
                "loadBalancer": {}
            },
            "lastUpdated": self.last_updated
        }


if __name__ == "__main__":
    import argparse
    import os
    import threading
    
    parser = argparse.ArgumentParser(description='Service管理工具')
    parser.add_argument('--config', type=str, help='Service配置文件')
    parser.add_argument('--action', choices=['create', 'delete', 'manager'], help='操作类型')
    parser.add_argument('--daemon', action='store_true', help='以守护进程模式运行ServiceManager')
    parser.add_argument('--sync-interval', type=int, default=10, help='端点同步间隔（秒）')
    
    args = parser.parse_args()
    
    # ServiceManager守护模式
    if args.action == 'manager' or args.daemon:
        print("[INFO]Starting ServiceManager daemon...")
        print(f"[INFO]Sync interval: {args.sync_interval} seconds")
        
        def sync_endpoints_periodically():
            """定期同步所有Service的端点"""
            while True:
                try:
                    print(f"[INFO]Syncing endpoints for {len(service_manager.services)} services...")
                    service_manager.sync_all_endpoints()
                    time.sleep(args.sync_interval)
                except KeyboardInterrupt:
                    print("\n[INFO]ServiceManager daemon stopping...")
                    break
                except Exception as e:
                    print(f"[ERROR]Endpoint sync failed: {e}")
                    time.sleep(args.sync_interval)
        
        # 启动后台线程定期同步端点
        sync_thread = threading.Thread(target=sync_endpoints_periodically, daemon=True)
        sync_thread.start()
        
        try:
            print("[INFO]ServiceManager is running. Press Ctrl+C to stop...")
            sync_thread.join()
        except KeyboardInterrupt:
            print("\n[INFO]ServiceManager daemon stopped.")
        
        exit(0)
    
    # 单个Service操作模式
    if not args.config or not args.action:
        print("[ERROR]Config file and action are required for service operations")
        print("[INFO]Use --action manager to run ServiceManager daemon")
        exit(1)
    
    if not os.path.exists(args.config):
        print(f"[ERROR]Config file not found: {args.config}")
        exit(1)
    
    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    service = Service(config)
    
    if args.action == 'create':
        print(f"[INFO]Creating Service {service.namespace}/{service.name}")
        
        # 启动Service
        service.start()
        
        print(f"[SUCCESS]Service {service.name} created successfully")
        print(f"[INFO]ClusterIP: {service.cluster_ip}")
        print(f"[INFO]Service details: {json.dumps(service.to_dict(), indent=2)}")
    
    elif args.action == 'delete':
        print(f"[INFO]Deleting Service {service.namespace}/{service.name}")
        service.stop()
        print(f"[SUCCESS]Service {service.name} deleted successfully")
