#!/usr/bin/env python3
"""
Mini-K8s Service实现
参考old版本设计，包含Service类
"""

import json
import uuid
import time
import random
import ipaddress
import requests
from typing import Dict, List, Optional, Any, Tuple
from config import Config

class Service:
    """Service核心类，负责服务发现、负载均衡和网络代理"""
    
    # ClusterIP分配池
    CLUSTER_IP_POOL = "10.96.0.0/16"  # Kubernetes默认Service CIDR
    allocated_ips = set()
    
    def __init__(self, config_dict: Dict[str, Any]):
        # 基本元数据
        metadata = config_dict.get("metadata", {})
        self.name = metadata.get("name")
        self.namespace = metadata.get("namespace", "default")
        self.labels = metadata.get("labels", {})
        self.uid = metadata.get("uid", str(uuid.uuid4()))
        
        # Service规格
        spec = config_dict.get("spec", {})
        self.service_type = spec.get("type", "ClusterIP")
        self.cluster_ip = spec.get("clusterIP", None)
        self.selector = spec.get("selector", {})
        
        # 端口配置
        self.ports = []
        ports = spec.get("ports", [])
        if not ports:
            raise ValueError("Service must have at least one port configuration")
            
        for port_config in ports:
            port_info = {
                "name": port_config.get("name", "default"),
                "port": int(port_config.get("port", 80)),
                "target_port": int(port_config.get("targetPort", port_config.get("port", 80))),
                "protocol": port_config.get("protocol", "TCP"),
                "node_port": int(port_config.get("nodePort")) if port_config.get("nodePort") and self.service_type == "NodePort" else None
            }
            self.ports.append(port_info)
        
        # 运行时状态
        self.status = "Pending"
        self.created_time = time.time()
        self.last_updated = self.created_time
        
        # 端点管理
        self.endpoints = []  # [{"ip": ip, "port": port, "protocol": protocol}, ...]
        self.endpoint_pods = {}  # {endpoint_key: pod_info}
        
        # 分配ClusterIP
        if not self.cluster_ip or self.cluster_ip == "None":
            self.cluster_ip = self._allocate_cluster_ip()
        
        print(f"[INFO]Service {self.namespace}/{self.name} initialized with ClusterIP {self.cluster_ip}")
    
    def _allocate_cluster_ip(self) -> str:
        """分配ClusterIP"""
        network = ipaddress.IPv4Network(self.CLUSTER_IP_POOL)
        available_ips = list(network.hosts())
        available_ips = [ip for ip in available_ips if str(ip) not in self.allocated_ips]
        
        if not available_ips:
            raise RuntimeError("ClusterIP pool exhausted")
        
        selected_ip = str(random.choice(available_ips))
        self.allocated_ips.add(selected_ip)
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
            # 优先从ip字段获取
            if "ip" in pod_data and pod_data["ip"] not in [None, "None", "<none>", ""]:
                return pod_data["ip"]
            
            # 从status中获取
            status = pod_data.get("status", {})
            if isinstance(status, dict) and "podIP" in status:
                return status["podIP"]
            elif isinstance(status, str):
                # 如果status是字符串，可能是直接的IP
                if status not in ["PENDING", "RUNNING", "FAILED", "SUCCEEDED"]:
                    return status
                    
            return None
        except Exception as e:
            print(f"[ERROR]Failed to get Pod IP: {e}")
            return None
    
    def update_endpoints(self, pods: List[Dict]) -> bool:
        """更新Service端点"""
        try:
            new_endpoints = []
            
            # 发现匹配的Pod端点
            for pod in pods:
                pod_labels = pod.get("metadata", {}).get("labels", {})
                if not self.matches_pod(pod_labels):
                    continue
                
                pod_ip = self.get_pod_ip(pod)
                if not pod_ip:
                    continue
                
                # 为每个端口创建端点
                for port_info in self.ports:
                    endpoint = {
                        "ip": pod_ip,
                        "port": port_info["target_port"],
                        "protocol": port_info["protocol"]
                    }
                    new_endpoints.append(endpoint)
            
            # 检查端点是否有变化
            old_endpoint_set = {(ep["ip"], ep["port"]) for ep in self.endpoints}
            new_endpoint_set = {(ep["ip"], ep["port"]) for ep in new_endpoints}
            
            if old_endpoint_set == new_endpoint_set:
                return False
            
            print(f"[INFO]Service {self.namespace}/{self.name} endpoints updated: {len(new_endpoints)} endpoints")
            self.endpoints = new_endpoints
            self.last_updated = time.time()
            self.status = "Active" if new_endpoints else "Pending"
            
            return True
            
        except Exception as e:
            print(f"[ERROR]Failed to update Service endpoints: {e}")
            self.status = "Failed"
            return False
    
    def start(self, pods: List[Dict] = None):
        """启动Service"""
        try:
            print(f"[INFO]Starting Service {self.namespace}/{self.name}")
            
            # 如果提供了pods，更新端点
            if pods:
                self.update_endpoints(pods)
            
            if not self.endpoints:
                print(f"[WARNING]Service {self.namespace}/{self.name} has no available endpoints")
                return
            
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
            
            # 释放ClusterIP
            if self.cluster_ip:
                self.release_cluster_ip(self.cluster_ip)
            
            self.status = "Stopped"
            print(f"[INFO]Service {self.namespace}/{self.name} stopped")
            
        except Exception as e:
            print(f"[ERROR]Failed to stop Service: {e}")
    
    def cleanup(self):
        """清理Service资源"""
        print(f"[INFO]Cleaning up Service {self.namespace}/{self.name}")
        
        # 释放ClusterIP
        if self.cluster_ip:
            self.release_cluster_ip(self.cluster_ip)
        
        self.status = "Terminated"
    
    def get_endpoint(self) -> Optional[Dict[str, Any]]:
        """获取下一个可用端点（简单轮询负载均衡）"""
        if not self.endpoints:
            return None
            
        # 简单轮询算法
        import random
        return random.choice(self.endpoints)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取Service统计信息"""
        return {
            "name": self.name,
            "namespace": self.namespace,
            "type": self.service_type,
            "cluster_ip": self.cluster_ip,
            "status": self.status,
            "endpoints": len(self.endpoints),
            "endpoint_details": self.endpoints,
            "ports": self.ports,
            "created_time": self.created_time,
            "last_updated": self.last_updated
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于API和存储"""
        return {
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
                "uid": self.uid,
                "creationTimestamp": self.created_time
            },
            "spec": {
                "type": self.service_type,
                "clusterIP": self.cluster_ip,
                "selector": self.selector,
                "ports": self.ports
            },
            "status": {
                "phase": self.status,
                "endpoints": self.endpoints,
                "loadBalancer": {}
            },
            "lastUpdated": self.last_updated
        }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Service测试')
    parser.add_argument('--test', action='store_true', help='运行Service测试')
    
    args = parser.parse_args()
    
    if args.test:
        # 测试Service创建
        test_config = {
            "metadata": {
                "name": "test-service",
                "namespace": "default",
                "labels": {"app": "test"}
            },
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "nginx"},
                "ports": [
                    {
                        "name": "http",
                        "port": 80,
                        "targetPort": 8080,
                        "protocol": "TCP"
                    }
                ]
            }
        }
        
        service = Service(test_config)
        print(f"Service created: {service.to_dict()}")
    else:
        print("Use --test to run Service test")
