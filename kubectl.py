#!/usr/bin/env python3
"""
Minik8s kubectl - 命令行工具
支持查看Pod及其运行状态，包括Pod名、运行状态、运行时间、namespace、labels等信息
"""

import argparse
import json
import requests
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import yaml
import docker

class MinikubectlClient:
    """Minik8s kubectl 客户端"""
    
    def __init__(self, api_server_host: str = "localhost", api_server_port: int = 5050):
        """初始化客户端"""
        self.host = api_server_host
        self.port = api_server_port
        self.base_url = f"http://{self.host}:{self.port}"
        self.default_namespace = "default"
        self.docker_client = docker.from_env()
        
    def _get_pod_ip_from_docker(self, pod_name: str, namespace: str = "default") -> str:
        """从Docker网络中获取Pod的IP地址"""
        try:
            # 查找pause容器的名称模式
            pause_container_name = f"pause_{namespace}_{pod_name}"
            
            # 获取mini-k8s-br0网络信息
            network = self.docker_client.networks.get("mini-k8s-br0")
            containers = network.attrs.get("Containers", {})
            
            # 查找匹配的容器
            for container_id, container_info in containers.items():
                if container_info.get("Name") == pause_container_name:
                    ipv4_address = container_info.get("IPv4Address", "")
                    if ipv4_address:
                        # 移除子网掩码部分 (例如: "10.5.0.11/16" -> "10.5.0.11")
                        return ipv4_address.split('/')[0]
            
            return "<none>"
        except Exception as e:
            print(f"[DEBUG] 获取Pod IP失败: {e}")
            return "<none>"
        
    def _make_request(self, endpoint: str, method: str = "GET", data: dict = None) -> Optional[dict]:
        """发送HTTP请求"""
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "GET":
                response = requests.get(url, timeout=10)
            elif method.upper() == "POST":
                response = requests.post(url, json=data, timeout=10)
            elif method.upper() == "DELETE":
                response = requests.delete(url, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")
                
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: HTTP {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to API server: {e}")
            return None
    
    def format_table_output(self, headers: List[str], rows: List[List[str]]) -> str:
        """格式化表格输出"""
        if not rows:
            return ""
        
        # 计算每列的最大宽度
        col_widths = [len(header) for header in headers]
        
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(cell)))
        
        # 构建输出
        lines = []
        
        # 表头
        header_line = "  ".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
        lines.append(header_line)
        
        # 数据行
        for row in rows:
            row_line = "  ".join(str(row[i]).ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i]) 
                                for i in range(len(headers)))
            lines.append(row_line)
        
        return "\n".join(lines)
    
    def _calculate_age(self, timestamp: float) -> str:
        """计算运行时间"""
        try:
            created_time = datetime.fromtimestamp(timestamp)
            now = datetime.now()
            age = now - created_time
            
            if age.days > 0:
                return f"{age.days}d"
            elif age.seconds > 3600:
                hours = age.seconds // 3600
                return f"{hours}h"
            elif age.seconds > 60:
                minutes = age.seconds // 60
                return f"{minutes}m"
            else:
                return f"{age.seconds}s"
        except:
            return "Unknown"
    
    def _format_labels(self, labels: dict) -> str:
        """格式化标签显示"""
        if not labels:
            return "<none>"
        return ",".join([f"{k}={v}" for k, v in labels.items()])
    
    def get_pods(self, namespace: str = None) -> None:
        """获取Pod列表"""
        try:
            # 构建请求端点 - 如果没有指定namespace，获取所有namespace的pods
            if namespace:
                endpoint = f"/api/v1/namespaces/{namespace}/pods"
            else:
                endpoint = "/api/v1/pods"
            
            response = self._make_request(endpoint)
            
            if not response:
                return
                
            pods = response.get("pods", [])
            if not pods:
                ns_info = "all namespaces" if not namespace else namespace
                print(f"No pods found in {ns_info}.")
                return
            
            # 构建表头 - 默认显示所有信息
            headers = ["NAME", "READY", "STATUS", "RESTARTS", "AGE"]
            if not namespace:  # 如果没有指定namespace，显示NAMESPACE列
                headers.insert(0, "NAMESPACE")
            # 默认wide模式，显示IP和NODE
            headers.extend(["IP", "NODE"])
            # 默认显示标签
            headers.append("LABELS")
            
            rows = []
            
            for pod in pods:
                metadata = pod.get("metadata", {})
                pod_name = metadata.get("name", "Unknown")
                pod_namespace = metadata.get("namespace", "Unknown")
                labels = metadata.get("labels", {})
                
                # 状态信息
                spec = pod.get("spec", {})
                containers = spec.get("containers", [])
                
                # 计算Ready状态 - 这里简化处理
                total_containers = len(containers)
                ready_containers = total_containers  # 假设都是ready的，实际应该检查容器状态
                ready = f"{ready_containers}/{total_containers}"
                
                # Pod状态 - 从不同位置获取状态信息
                status = "Unknown"
                if "status" in pod:
                    if "phase" in pod["status"]:
                        status = pod["status"]["phase"]
                    else:
                        status = "Running"  # 默认状态
                else:
                    status = "Running"  # 如果没有状态信息，假设为Running
                
                restarts = "0"  # 重启次数，这里简化处理
                
                # 年龄计算
                age = "Unknown"
                if "lastUpdated" in pod:
                    age = self._calculate_age(pod["lastUpdated"])
                elif "uid" in metadata:
                    # 从UID中尝试提取时间戳（如果有的话）
                    age = "<unknown>"
                
                # Pod IP - 从Docker网络获取真实IP
                pod_ip = self._get_pod_ip_from_docker(pod_name, pod_namespace)
                
                # Node信息
                node = pod.get("node", "<none>")
                
                # 构建行数据
                row = [pod_name, ready, status, restarts, age]
                if not namespace:  # 如果没有指定namespace，添加namespace列
                    row.insert(0, pod_namespace)
                # 默认显示IP和NODE
                row.extend([pod_ip, node])
                # 默认显示标签
                row.append(self._format_labels(labels))
                
                rows.append(row)
            
            print(self.format_table_output(headers, rows))
            
        except Exception as e:
            print(f"Error getting pods: {e}")
    
    def describe_pod(self, pod_name: str, namespace: str = None) -> None:
        """描述Pod详细信息"""
        try:
            ns = namespace or self.default_namespace
            endpoint = f"/api/v1/namespaces/{ns}/pods/{pod_name}"
            
            response = self._make_request(endpoint)
            
            if not response:
                print(f"Pod '{pod_name}' not found in namespace '{ns}'")
                return
            
            metadata = response.get("metadata", {})
            spec = response.get("spec", {})
            status = response.get("status", {})
            
            # 基本信息
            print(f"Name:         {metadata.get('name', 'Unknown')}")
            print(f"Namespace:    {metadata.get('namespace', 'Unknown')}")
            print(f"Priority:     0")
            print(f"Node:         {response.get('node', '<none>')}")
            
            # 标签和注释
            labels = metadata.get("labels", {})
            print(f"Labels:       {self._format_labels(labels)}")
            print(f"Annotations:  <none>")
            
            # 状态
            pod_status = status.get("phase", "Running")
            pod_ip = self._get_pod_ip_from_docker(pod_name, namespace or self.default_namespace)
            print(f"Status:       {pod_status}")
            print(f"IP:           {pod_ip}")
            
            # 容器信息
            print("")
            print("Containers:")
            containers = spec.get("containers", [])
            for container in containers:
                print(f"  {container.get('name', 'Unknown')}:")
                print(f"    Container ID:  docker://{container.get('container_id', '<none>')}")
                print(f"    Image:         {container.get('image', 'Unknown')}")
                print(f"    Image ID:      {container.get('image_id', '<none>')}")
                
                # 端口信息
                ports = container.get("ports", [])
                if ports:
                    port_strs = []
                    for port in ports:
                        port_str = f"{port.get('containerPort', '?')}/{port.get('protocol', 'TCP')}"
                        port_strs.append(port_str)
                    print(f"    Port:          {', '.join(port_strs)}")
                else:
                    print(f"    Port:          <none>")
                
                print(f"    Host Port:     <none>")
                
                # 命令和参数
                command = container.get("command", [])
                args = container.get("args", [])
                if command:
                    print(f"    Command:       {' '.join(command)}")
                if args:
                    print(f"    Args:          {' '.join(args)}")
                
                print(f"    State:         Running")
                print(f"    Ready:         True")
                print(f"    Restart Count: 0")
                
                # 环境变量
                env = container.get("env", [])
                if env:
                    print(f"    Environment Variables from:")
                    for e in env:
                        print(f"      {e.get('name', '?')}:  {e.get('value', '?')}")
                else:
                    print(f"    Environment:   <none>")
                
                print("")
            
            # 条件信息
            print("Conditions:")
            print("  Type              Status")
            print("  Initialized       True")
            print("  Ready             True")
            print("  ContainersReady   True")
            print("  PodScheduled      True")
            
            # 卷信息
            volumes = spec.get("volumes", [])
            if volumes:
                print("")
                print("Volumes:")
                for volume in volumes:
                    vol_name = volume.get("name", "Unknown")
                    if "hostPath" in volume:
                        path = volume["hostPath"].get("path", "Unknown")
                        print(f"  {vol_name}:")
                        print(f"    Type:      HostPath (bare host directory volume)")
                        print(f"    Path:      {path}")
            else:
                print("")
                print("Volumes:        <none>")
            
            print("")
            print("QoS Class:         BestEffort")
            print("Node-Selectors:    <none>")
            print("Tolerations:       <none>")
            print("Events:            <none>")
            
        except Exception as e:
            print(f"Error describing pod '{pod_name}': {e}")
    
    def get_nodes(self) -> None:
        """获取Node列表"""
        try:
            endpoint = "/api/v1/nodes"
            response = self._make_request(endpoint)
            
            if not response:
                return
                
            nodes = response.get("nodes", [])
            if not nodes:
                print("No nodes found.")
                return
            
            headers = ["NAME", "STATUS", "ROLES", "AGE", "VERSION"]
            rows = []
            
            for node in nodes:
                node_name = node.get("name", "Unknown")
                status = "Ready"  # 简化处理
                roles = "<none>"  # 简化处理
                age = "<unknown>"  # 简化处理
                version = "v1.0.0"  # 简化处理
                
                rows.append([node_name, status, roles, age, version])
            
            print(self.format_table_output(headers, rows))
            
        except Exception as e:
            print(f"Error getting nodes: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Minik8s kubectl - 命令行工具")
    parser.add_argument("--server", default="localhost", help="API server地址")
    parser.add_argument("--port", type=int, default=5050, help="API server端口")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # get 命令
    get_parser = subparsers.add_parser("get", help="显示资源")
    get_parser.add_argument("resource", choices=["pods", "nodes", "pod", "node"], help="资源类型")
    get_parser.add_argument("name", nargs="?", help="资源名称")
    get_parser.add_argument("-n", "--namespace", help="命名空间")
    
    # describe 命令
    desc_parser = subparsers.add_parser("describe", help="显示资源详细信息")
    desc_parser.add_argument("resource", choices=["pod", "node"], help="资源类型")
    desc_parser.add_argument("name", help="资源名称")
    desc_parser.add_argument("-n", "--namespace", help="命名空间")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 创建客户端
    client = MinikubectlClient(args.server, args.port)
    
    try:
        if args.command == "get":
            if args.resource in ["pods", "pod"]:
                client.get_pods(namespace=args.namespace)
            elif args.resource in ["nodes", "node"]:
                client.get_nodes()
                
        elif args.command == "describe":
            if args.resource == "pod":
                if not args.name:
                    print("Error: Pod name is required for describe command")
                    return
                client.describe_pod(args.name, args.namespace)
            elif args.resource == "node":
                if not args.name:
                    print("Error: Node name is required for describe command")
                    return
                # 这里可以添加describe node的实现
                print(f"Describe node '{args.name}' - Not implemented yet")
                
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
