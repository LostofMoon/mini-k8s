#!/usr/bin/env python3
"""
Mini-K8s Service实现
提供服务发现、负载均衡和网络代理功能
支持ClusterIP和NodePort类型
"""

import yaml
import json
import uuid
import time
import subprocess
import random
import ipaddress
import requests
from typing import Dict, List, Optional, Any, Tuple
from config import Config

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
        
        for port_info in self.ports:
            service_port = port_info["port"]
            protocol = port_info["protocol"].lower()
            
            # 获取这个端口对应的所有端点
            port_endpoints = [ep for ep in self.endpoints if ep[1] == port_info["target_port"]]
            
            if not port_endpoints:
                continue
            
            # ClusterIP规则 - 使用iptables实现负载均衡
            for i, endpoint in enumerate(port_endpoints):
                # 使用iptables的random模块实现负载均衡
                probability = f"1/{len(port_endpoints) - i}" if i < len(port_endpoints) - 1 else "1"
                
                # OUTPUT链规则（本机访问ClusterIP）
                output_rule = [
                    "iptables", "-t", "nat", "-A", "OUTPUT",
                    "-d", f"{self.cluster_ip}/32",
                    "-p", protocol,
                    "--dport", str(service_port),
                    "-m", "statistic",
                    "--mode", "random",
                    "--probability", probability,
                    "-j", "DNAT",
                    "--to-destination", f"{endpoint[0]}:{endpoint[1]}"
                ]
                
                # PREROUTING链规则（其他机器访问ClusterIP）
                prerouting_rule = [
                    "iptables", "-t", "nat", "-A", "PREROUTING",
                    "-d", f"{self.cluster_ip}/32",
                    "-p", protocol,
                    "--dport", str(service_port),
                    "-m", "statistic",
                    "--mode", "random",
                    "--probability", probability,
                    "-j", "DNAT",
                    "--to-destination", f"{endpoint[0]}:{endpoint[1]}"
                ]
                
                try:
                    subprocess.run(output_rule, check=True, capture_output=True)
                    subprocess.run(prerouting_rule, check=True, capture_output=True)
                    self.iptables_rules.extend([output_rule, prerouting_rule])
                    print(f"[DEBUG]Added ClusterIP rule for {endpoint[0]}:{endpoint[1]}")
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR]Failed to add ClusterIP rule: {e}")
            
            # NodePort规则
            if self.service_type == "NodePort" and port_info["node_port"]:
                self._setup_nodeport_rules(port_info, port_endpoints)
    
    def _setup_nodeport_rules(self, port_info: Dict, endpoints: List[Tuple[str, int]]):
        """设置NodePort iptables规则"""
        node_port = port_info["node_port"]
        protocol = port_info["protocol"].lower()
        
        for i, endpoint in enumerate(endpoints):
            probability = f"1/{len(endpoints) - i}" if i < len(endpoints) - 1 else "1"
            
            rule = [
                "iptables", "-t", "nat", "-A", "PREROUTING",
                "-p", protocol,
                "--dport", str(node_port),
                "-m", "statistic",
                "--mode", "random",
                "--probability", probability,
                "-j", "DNAT",
                "--to-destination", f"{endpoint[0]}:{endpoint[1]}"
            ]
            
            try:
                subprocess.run(rule, check=True, capture_output=True)
                self.iptables_rules.append(rule)
                print(f"[DEBUG]Added NodePort rule {node_port} -> {endpoint[0]}:{endpoint[1]}")
            except subprocess.CalledProcessError as e:
                print(f"[ERROR]Failed to add NodePort rule: {e}")
    
    def _cleanup_iptables_rules(self):
        """清理iptables规则"""
        for rule in self.iptables_rules:
            # 将-A改为-D来删除规则
            delete_rule = rule.copy()
            if "-A" in delete_rule:
                delete_rule[delete_rule.index("-A")] = "-D"
                try:
                    subprocess.run(delete_rule, check=False, capture_output=True)
                except Exception:
                    pass  # 忽略删除失败的情况
        
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
    
    parser = argparse.ArgumentParser(description='Service管理工具')
    parser.add_argument('--config', type=str, required=True, help='Service配置文件')
    parser.add_argument('--action', choices=['create', 'delete'], required=True, help='操作类型')
    
    args = parser.parse_args()
    
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
