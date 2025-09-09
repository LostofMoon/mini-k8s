#!/usr/bin/env python3
"""
Mini-K8s Pod提交脚本
实现标准的Kubernetes Pod创建流程：
用户提交Pod YAML → ApiServer → 调度器分配节点 → Kubelet接收任务 → 创建Pod
"""

import requests
import yaml
import json
import time
import argparse
import os
from datetime import datetime

class PodSubmitter:
    """Pod提交器 - 模拟kubectl apply"""
    
    def __init__(self, apiserver_host="localhost", apiserver_port=5050):
        self.apiserver_host = apiserver_host
        self.apiserver_port = apiserver_port
        self.base_url = f"http://{self.apiserver_host}:{self.apiserver_port}"
        
    def submit_pod(self, pod_yaml_file):
        """
        提交Pod到ApiServer
        
        Args:
            pod_yaml_file: Pod YAML配置文件路径
            
        Returns:
            bool: 提交是否成功
        """
        try:
            # 1. 读取Pod YAML配置
            print(f"[INFO]Reading Pod configuration from: {pod_yaml_file}")
            with open(pod_yaml_file, 'r', encoding='utf-8') as f:
                pod_config = yaml.safe_load(f)
            
            # 2. 提取Pod基本信息
            metadata = pod_config.get("metadata", {})
            pod_name = metadata.get("name")
            namespace = metadata.get("namespace", "default")
            
            print(f"[INFO]Submitting Pod: {namespace}/{pod_name}")
            
            # 3. 提交到ApiServer
            url = f"{self.base_url}/api/v1/namespaces/{namespace}/pods/{pod_name}"
            
            # 准备提交数据（不包含节点信息，让调度器分配）
            submit_data = {
                "apiVersion": pod_config.get("apiVersion", "v1"),
                "kind": "Pod",
                "metadata": metadata,
                "spec": pod_config.get("spec", {}),
                "status": "PENDING"  # 初始状态为PENDING，等待调度
            }
            
            # 发送POST请求
            response = requests.post(url, json=submit_data, timeout=10)
            
            if response.status_code in [200, 201]:
                print(f"[SUCCESS]Pod {namespace}/{pod_name} submitted to ApiServer successfully")
                print(f"[INFO]Pod is now PENDING, waiting for scheduler assignment...")
                return True
            elif response.status_code == 409:
                print(f"[WARNING]Pod {namespace}/{pod_name} already exists")
                return True
            else:
                print(f"[ERROR]Failed to submit Pod: HTTP {response.status_code}")
                print(f"[ERROR]Response: {response.text}")
                return False
                
        except FileNotFoundError:
            print(f"[ERROR]Pod configuration file not found: {pod_yaml_file}")
            return False
        except yaml.YAMLError as e:
            print(f"[ERROR]Invalid YAML format: {e}")
            return False
        except requests.exceptions.ConnectionError:
            print(f"[ERROR]Cannot connect to ApiServer at {self.base_url}")
            print(f"[ERROR]Please ensure ApiServer is running on {self.apiserver_host}:{self.apiserver_port}")
            return False
        except Exception as e:
            print(f"[ERROR]Failed to submit Pod: {e}")
            return False
    
    def wait_for_pod_scheduled(self, namespace, pod_name, timeout=60):
        """
        等待Pod被调度到节点
        
        Args:
            namespace: Pod命名空间
            pod_name: Pod名称
            timeout: 超时时间（秒）
            
        Returns:
            dict: Pod信息，如果超时则返回None
        """
        print(f"[INFO]Waiting for Pod {namespace}/{pod_name} to be scheduled...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 查询Pod状态
                url = f"{self.base_url}/api/v1/namespaces/{namespace}/pods/{pod_name}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    pod_data = response.json()
                    node = pod_data.get("node")
                    status = pod_data.get("status", "UNKNOWN")
                    
                    if node:
                        print(f"[SUCCESS]Pod {namespace}/{pod_name} scheduled to node: {node}")
                        print(f"[INFO]Pod status: {status}")
                        return pod_data
                    else:
                        print(f"[INFO]Pod {namespace}/{pod_name} still pending... (status: {status})")
                
                time.sleep(2)
                
            except Exception as e:
                print(f"[WARNING]Error checking Pod status: {e}")
                time.sleep(2)
        
        print(f"[ERROR]Timeout waiting for Pod {namespace}/{pod_name} to be scheduled")
        return None
    
    def wait_for_pod_running(self, namespace, pod_name, timeout=120):
        """
        等待Pod运行
        
        Args:
            namespace: Pod命名空间  
            pod_name: Pod名称
            timeout: 超时时间（秒）
            
        Returns:
            dict: Pod信息，如果超时则返回None
        """
        print(f"[INFO]Waiting for Pod {namespace}/{pod_name} to be running...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 通过kubectl查询Pod状态
                from subprocess import run, PIPE
                result = run(['python', 'kubectl.py', 'get', 'pods'], 
                           capture_output=True, text=True, cwd=os.getcwd())
                
                if result.returncode == 0:
                    # 解析输出查找我们的Pod
                    lines = result.stdout.strip().split('\n')
                    for line in lines[1:]:  # 跳过表头
                        parts = line.split()
                        if len(parts) >= 6:
                            if parts[0] == namespace and parts[1] == pod_name:
                                status = parts[3]
                                ip = parts[6] if len(parts) > 6 else "N/A"
                                node = parts[7] if len(parts) > 7 else "N/A"
                                
                                print(f"[INFO]Pod {namespace}/{pod_name} - Status: {status}, IP: {ip}, Node: {node}")
                                
                                if status == "Running":
                                    print(f"[SUCCESS]Pod {namespace}/{pod_name} is now running!")
                                    return {
                                        "namespace": namespace,
                                        "name": pod_name,
                                        "status": status,
                                        "ip": ip,
                                        "node": node
                                    }
                
                time.sleep(3)
                
            except Exception as e:
                print(f"[WARNING]Error checking Pod running status: {e}")
                time.sleep(3)
        
        print(f"[ERROR]Timeout waiting for Pod {namespace}/{pod_name} to be running")
        return None
    
    def delete_pod(self, namespace, pod_name):
        """
        删除Pod
        
        Args:
            namespace: Pod命名空间
            pod_name: Pod名称
            
        Returns:
            bool: 删除是否成功
        """
        try:
            print(f"[INFO]Deleting Pod {namespace}/{pod_name}...")
            
            url = f"{self.base_url}/api/v1/namespaces/{namespace}/pods/{pod_name}"
            response = requests.delete(url, timeout=10)
            
            if response.status_code == 200:
                print(f"[SUCCESS]Pod {namespace}/{pod_name} deleted successfully")
                return True
            elif response.status_code == 404:
                print(f"[WARNING]Pod {namespace}/{pod_name} not found")
                return True
            else:
                print(f"[ERROR]Failed to delete Pod: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            print(f"[ERROR]Failed to delete Pod: {e}")
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Mini-K8s Pod Submitter")
    parser.add_argument("--config", type=str, required=True, help="Pod YAML配置文件")
    parser.add_argument("--apiserver", type=str, default="localhost", help="ApiServer地址")
    parser.add_argument("--port", type=int, default=5050, help="ApiServer端口")
    parser.add_argument("--action", choices=["submit", "delete"], default="submit", help="操作类型")
    parser.add_argument("--wait", action="store_true", help="等待Pod运行")
    parser.add_argument("--timeout", type=int, default=120, help="等待超时时间（秒）")
    
    args = parser.parse_args()
    
    # 检查配置文件
    if not os.path.exists(args.config):
        print(f"[ERROR]Configuration file not found: {args.config}")
        return 1
    
    # 创建Pod提交器
    submitter = PodSubmitter(args.apiserver, args.port)
    
    if args.action == "submit":
        # 提交Pod
        print(f"\n{'='*60}")
        print(f"Pod提交流程开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        success = submitter.submit_pod(args.config)
        if not success:
            return 1
        
        if args.wait:
            # 读取Pod配置获取名称
            with open(args.config, 'r', encoding='utf-8') as f:
                pod_config = yaml.safe_load(f)
            
            metadata = pod_config.get("metadata", {})
            pod_name = metadata.get("name")
            namespace = metadata.get("namespace", "default")
            
            # 等待调度
            print(f"\n{'='*60}")
            print("等待调度器分配节点...")
            print(f"{'='*60}")
            
            pod_info = submitter.wait_for_pod_scheduled(namespace, pod_name, timeout=60)
            if not pod_info:
                print("[ERROR]Pod调度失败")
                return 1
            
            # 等待运行
            print(f"\n{'='*60}")
            print("等待Kubelet创建Pod...")
            print(f"{'='*60}")
            
            running_info = submitter.wait_for_pod_running(namespace, pod_name, timeout=args.timeout)
            if running_info:
                print(f"\n{'='*60}")
                print("Pod创建成功!")
                print(f"{'='*60}")
                print(f"Pod名称: {running_info['namespace']}/{running_info['name']}")
                print(f"运行状态: {running_info['status']}")
                print(f"Pod IP: {running_info['ip']}")
                print(f"运行节点: {running_info['node']}")
                print(f"创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print("[ERROR]Pod创建失败或超时")
                return 1
                
    elif args.action == "delete":
        # 删除Pod
        with open(args.config, 'r', encoding='utf-8') as f:
            pod_config = yaml.safe_load(f)
        
        metadata = pod_config.get("metadata", {})
        pod_name = metadata.get("name")
        namespace = metadata.get("namespace", "default")
        
        success = submitter.delete_pod(namespace, pod_name)
        if not success:
            return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
