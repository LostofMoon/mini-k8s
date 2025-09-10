#!/usr/bin/env python3
"""
Mini-K8s KubeProxy实现
参考old版本设计，负责Service网络代理和iptables规则管理
"""

import json
import time
import random
import string
import logging
import platform
import shutil
import subprocess
from typing import Dict, List, Optional, Any
from confluent_kafka import Consumer, KafkaError
from config import Config


class KubeProxy:
    """KubeProxy - Service代理类，负责管理iptables规则和NAT转换"""
    
    def __init__(self, node_name: str = None, kafka_bootstrap_servers: str = None):
        self.node_name = node_name
        self.kafka_bootstrap_servers = kafka_bootstrap_servers or Config.KAFKA_BOOTSTRAP_SERVERS
        
        # Kubernetes iptables链名称
        self.nat_chain = "KUBE-SERVICES"
        self.mark_chain = "KUBE-MARK-MASQ"
        self.postrouting_chain = "KUBE-POSTROUTING"
        self.service_chain_prefix = "KUBE-SVC-"
        self.endpoint_chain_prefix = "KUBE-SEP-"
        
        # Service 和 Endpoint 链映射
        self.service_chains = {}  # service_name -> chain_name
        self.endpoint_chains = {}  # service_name -> [endpoint_chain_names]
        self.services = {}  # service_name -> service_info (用于模拟模式)
        
        # 线程控制
        self.running = False
        self.message_thread = None
        
        # 检查运行环境
        self.is_macos = platform.system() == "Darwin"
        self.is_windows = platform.system() == "Windows"
        self.is_linux = platform.system() == "Linux"
        self.iptables_available = self.is_linux and shutil.which('iptables') is not None
        
        if self.is_macos:
            print(f"[WARNING]Running on macOS, iptables functions will be simulated")
        elif self.is_windows:
            print(f"[WARNING]Running on Windows, iptables functions will be simulated")
        elif not self.iptables_available:
            print(f"[WARNING]iptables command not available, network proxy will be simulated")
        else:
            print(f"[INFO]Linux system detected, setting up real iptables chains")
            self.setup_base_chains()
        
        # 初始化Kafka消费者（可选）
        self.kafka_consumer = None
        if node_name:
            self._init_kafka_consumer()
    
    def _init_kafka_consumer(self):
        """初始化Kafka消费者"""
        if Consumer is None:
            print("[WARNING]confluent_kafka not available, Kafka consumer disabled")
            self.kafka_consumer = None
            return
            
        try:
            kafka_config = {
                'bootstrap.servers': self.kafka_bootstrap_servers,
                'group.id': f'kubeproxy-{self.node_name}',
                'auto.offset.reset': 'latest',
                'enable.auto.commit': True
            }
            self.kafka_consumer = Consumer(kafka_config)
            self.kafka_consumer.subscribe(['service-proxy-rules'])
            print(f"[INFO]KubeProxy {self.node_name} connected to Kafka for Service rules")
        except Exception as e:
            print(f"[ERROR]Failed to connect to Kafka: {e}")
            self.kafka_consumer = None
    
    def setup_base_chains(self):
        """设置基础iptables链（按照Kubernetes标准）"""
        if not self.iptables_available:
            print("[INFO]Skipping iptables setup on non-Linux system")
            return
            
        try:
            # 创建基础链（如果不存在）
            self._run_iptables(["-t", "nat", "-N", self.mark_chain], ignore_errors=True)
            self._run_iptables(["-t", "nat", "-N", self.postrouting_chain], ignore_errors=True)
            self._run_iptables(["-t", "nat", "-N", self.nat_chain], ignore_errors=True)
            
            print("[INFO]Base iptables chains setup completed")
        except Exception as e:
            print(f"[ERROR]Failed to setup base iptables chains: {e}")
    
    def create_service_rules(self, service_name: str, cluster_ip: str, port: int, 
                           protocol: str, endpoints: List[str], node_port: Optional[int] = None):
        """为Service创建iptables规则"""
        if not self.iptables_available:
            print(f"[INFO]Simulating iptables rules for Service {service_name} (ClusterIP: {cluster_ip}:{port})")
            # 在模拟模式下，仍然记录Service信息以供测试
            self.services[f"{service_name}"] = {
                'cluster_ip': cluster_ip,
                'port': port,
                'protocol': protocol,
                'endpoints': endpoints,
                'node_port': node_port
            }
            return
            
        try:
            # 清理可能存在的旧规则
            self.delete_service_rules(service_name, cluster_ip, port, protocol, node_port)
            
            if not endpoints:
                print(f"[WARNING]No endpoints available for Service {service_name}")
                return
            
            print(f"[INFO]Creating iptables rules for Service {service_name}, endpoints: {endpoints}")
            
            # 生成Service链名
            service_chain = f"{self.service_chain_prefix}{service_name.upper().replace('-', '_')}"
            
            # 创建Service专用链
            self._run_iptables(["-t", "nat", "-N", service_chain], ignore_errors=True)
            
            # 为每个端点创建链
            endpoint_chains = []
            for i, endpoint in enumerate(endpoints):
                ep_hash = self._generate_chain_hash()
                endpoint_chain = f"{self.endpoint_chain_prefix}{ep_hash}"
                
                self._run_iptables(["-t", "nat", "-N", endpoint_chain], ignore_errors=True)
                
                # 解析端点地址
                if ':' in endpoint:
                    ep_ip, ep_port = endpoint.split(':')
                else:
                    ep_ip, ep_port = endpoint, port
                
                # 添加DNAT规则到端点
                self._run_iptables([
                    "-t", "nat", "-A", endpoint_chain,
                    "-p", protocol.lower(),
                    "-j", "DNAT", "--to-destination", f"{ep_ip}:{ep_port}"
                ])
                
                endpoint_chains.append(endpoint_chain)
            
            # 在Service链中添加负载均衡规则
            self._setup_load_balancing(service_chain, endpoint_chains, protocol)
            
            # 添加主链规则
            self._run_iptables([
                "-t", "nat", "-A", self.nat_chain,
                "-d", f"{cluster_ip}/32",
                "-p", protocol.lower(),
                "-m", protocol.lower(), "--dport", str(port),
                "-j", service_chain
            ])
            
            # 更新映射
            self.service_chains[service_name] = service_chain
            self.endpoint_chains[service_name] = endpoint_chains
            
            print(f"[INFO]Created iptables rules for Service {service_name}, endpoints: {len(endpoints)}")
            
        except Exception as e:
            print(f"[ERROR]Failed to create iptables rules for Service {service_name}: {e}")
    
    def delete_service_rules(self, service_name: str, cluster_ip: str, port: int, 
                           protocol: str, node_port: Optional[int] = None):
        """删除Service的iptables规则"""
        if not self.iptables_available:
            print(f"[INFO]Simulating deletion of iptables rules for Service {service_name}")
            # 在模拟模式下，从记录中删除Service信息
            if service_name in self.services:
                del self.services[service_name]
            return
            
        try:
            service_chain = f"{self.service_chain_prefix}{service_name.upper().replace('-', '_')}"
            
            # 删除主链中的规则
            self._run_iptables([
                "-t", "nat", "-D", self.nat_chain,
                "-d", f"{cluster_ip}/32",
                "-p", protocol.lower(),
                "-m", protocol.lower(), "--dport", str(port),
                "-j", service_chain
            ], ignore_errors=True)
            
            # 清理Service和Endpoint链
            self._cleanup_service_chains(service_name)
            
            print(f"[INFO]Deleted all iptables rules for Service {service_name}")
            
        except Exception as e:
            print(f"[ERROR]Failed to delete iptables rules for Service {service_name}: {e}")
    
    def update_service_endpoints(self, service_name: str, cluster_ip: str, port: int,
                               protocol: str, endpoints: List[str], node_port: Optional[int] = None):
        """更新Service的端点"""
        if not self.iptables_available:
            print(f"[INFO]Simulating endpoint update for Service {service_name}: {endpoints}")
            # 在模拟模式下，更新Service记录
            if service_name in self.services:
                self.services[service_name]['endpoints'] = endpoints
            return
        
        try:
            # 简单实现：删除并重建
            print(f"[INFO]Updating endpoints for Service {service_name}: {endpoints}")
            self.create_service_rules(service_name, cluster_ip, port, protocol, endpoints, node_port)
            
        except Exception as e:
            print(f"[ERROR]Failed to update endpoints for Service {service_name}: {e}")
    
    def get_service_stats(self, service_name: str) -> Dict[str, Any]:
        """获取Service的iptables统计信息"""
        if not self.iptables_available:
            return {
                "service_name": service_name,
                "iptables_support": False,
                "simulated": True,
                "service_info": self.services.get(service_name, {}),
                "message": "iptables not available on this system"
            }
        
        return {
            "service_name": service_name,
            "service_chain": self.service_chains.get(service_name),
            "endpoint_chains": len(self.endpoint_chains.get(service_name, [])),
            "iptables_support": True
        }
    
    def _run_iptables(self, args: List[str], ignore_errors: bool = False):
        """执行iptables命令"""
        if not self.iptables_available:
            print(f"[SIMULATE]iptables {' '.join(args)}")
            return
            
        try:
            cmd = ["iptables"] + args
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            if not ignore_errors:
                print(f"[ERROR]iptables command failed: {' '.join(args)}, error: {e}")
        except Exception as e:
            print(f"[ERROR]Failed to run iptables: {e}")
    
    def _generate_chain_hash(self) -> str:
        """生成随机链哈希"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    
    def _cleanup_service_chains(self, service_name: str):
        """清理Service相关的所有链"""
        # 清理Service链
        if service_name in self.service_chains:
            service_chain = self.service_chains[service_name]
            self._run_iptables(["-t", "nat", "-F", service_chain], ignore_errors=True)
            self._run_iptables(["-t", "nat", "-X", service_chain], ignore_errors=True)
            del self.service_chains[service_name]
        
        # 清理Endpoint链
        if service_name in self.endpoint_chains:
            for endpoint_chain in self.endpoint_chains[service_name]:
                self._run_iptables(["-t", "nat", "-F", endpoint_chain], ignore_errors=True)
                self._run_iptables(["-t", "nat", "-X", endpoint_chain], ignore_errors=True)
            del self.endpoint_chains[service_name]
    
    def _setup_load_balancing(self, service_chain: str, endpoint_chains: List[str], protocol: str):
        """在Service链中设置负载均衡规则"""
        endpoint_count = len(endpoint_chains)
        
        if endpoint_count == 0:
            return
        
        if endpoint_count == 1:
            # 单端点，直接跳转
            self._run_iptables([
                "-t", "nat", "-A", service_chain,
                "-j", endpoint_chains[0]
            ])
        else:
            # 多端点，使用统计模块实现负载均衡
            for i, endpoint_chain in enumerate(endpoint_chains):
                probability = 1.0 / (endpoint_count - i)
                prob_str = f"{probability:.10f}"
                
                if i == endpoint_count - 1:
                    # 最后一个端点，无条件跳转
                    self._run_iptables([
                        "-t", "nat", "-A", service_chain,
                        "-j", endpoint_chain
                    ])
                else:
                    # 使用概率跳转
                    self._run_iptables([
                        "-t", "nat", "-A", service_chain,
                        "-m", "statistic", "--mode", "random", "--probability", prob_str,
                        "-j", endpoint_chain
                    ])
        
        print(f"[INFO]Load balancing setup completed for {endpoint_count} endpoints")

    def cleanup_chains(self):
        """清理所有 iptables 链"""
        if not self.iptables_available:
            print("[INFO]Simulating cleanup of iptables chains")
            # 在模拟模式下，清理记录的Service信息
            self.services.clear()
            self.service_chains.clear()
            self.endpoint_chains.clear()
            return
            
        try:
            print("[INFO]Cleaning up all KubeProxy iptables chains")
            
            # 清理所有Service链
            for service_name in list(self.service_chains.keys()):
                self._cleanup_service_chains(service_name)
            
            # 清理基础链（谨慎操作，因为可能被其他组件使用）
            # 这里只清空链，不删除链本身
            for chain in [self.nat_chain, self.mark_chain, self.postrouting_chain]:
                self._run_iptables(["-t", "nat", "-F", chain], ignore_errors=True)
            
            print("[INFO]KubeProxy chains cleanup completed")
            
        except Exception as e:
            print(f"[ERROR]Failed to cleanup chains: {e}")

    def start(self):
        """启动KubeProxy服务"""
        print(f"[INFO]KubeProxy {self.node_name} started")
        
        # 设置基础iptables链
        self.setup_base_chains()
        
        # 如果有Kafka消费者，启动消息监听线程
        if self.kafka_consumer:
            self.running = True
            import threading
            self.message_thread = threading.Thread(target=self._handle_kafka_messages, daemon=True)
            self.message_thread.start()
            print(f"[INFO]KubeProxy {self.node_name} ready to receive Service rules")
        
        return True
    
    def _handle_kafka_messages(self):
        """处理Kafka消息的主循环"""
        print(f"[INFO]KubeProxy {self.node_name} starting message handler")
        
        while self.running and self.kafka_consumer:
            try:
                msg = self.kafka_consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                    
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        print(f"[ERROR]Kafka message error: {msg.error()}")
                    continue
                
                # 解析Service规则消息
                try:
                    import json
                    rule_data = json.loads(msg.value().decode('utf-8'))
                    self._process_service_rule(rule_data)
                except Exception as e:
                    print(f"[ERROR]Failed to process Service rule message: {e}")
                    
            except Exception as e:
                print(f"[ERROR]KubeProxy message handler error: {e}")
                
        print(f"[INFO]KubeProxy {self.node_name} message handler stopped")
    
    def _process_service_rule(self, rule_data: dict):
        """处理单个Service规则"""
        try:
            action = rule_data.get('action', 'CREATE')
            service_info = rule_data.get('service', {})
            
            service_name = f"{service_info.get('namespace', 'default')}/{service_info.get('name', 'unknown')}"
            cluster_ip = service_info.get('cluster_ip')
            ports = service_info.get('ports', [])
            endpoints = service_info.get('endpoints', [])
            
            print(f"[INFO]Processing Service rule: {action} {service_name}")
            
            if action == 'DELETE':
                # 删除Service规则
                for port_info in ports:
                    port = port_info.get('port')
                    protocol = port_info.get('protocol', 'TCP')
                    node_port = port_info.get('node_port')
                    
                    self.delete_service_rules(service_name, cluster_ip, port, protocol, node_port)
                    
            else:  # CREATE or UPDATE
                # 创建或更新Service规则
                for port_info in ports:
                    port = port_info.get('port')
                    protocol = port_info.get('protocol', 'TCP')
                    node_port = port_info.get('node_port')
                    target_port = port_info.get('target_port', port)
                    
                    # 构建端点列表 - 处理对象格式的端点数据
                    endpoint_list = []
                    for endpoint in endpoints:
                        if isinstance(endpoint, dict):
                            # 如果端点是对象格式 {'ip': '10.5.0.11', 'port': 80, 'protocol': 'TCP'}
                            endpoint_ip = endpoint.get('ip')
                            endpoint_port = endpoint.get('port')
                            # 使用target_port而不是端点中的port
                            endpoint_list.append(f"{endpoint_ip}:{target_port}")
                        else:
                            # 如果端点是字符串格式 "10.5.0.11:8080"
                            endpoint_list.append(endpoint)
                    
                    self.create_service_rules(
                        service_name, cluster_ip, port, protocol, 
                        endpoint_list, node_port
                    )
                    
            print(f"[SUCCESS]Service rule processed: {service_name}")
            
        except Exception as e:
            print(f"[ERROR]Failed to process Service rule: {e}")
    
    def stop(self):
        """停止KubeProxy服务"""
        print(f"[INFO]Stopping KubeProxy {self.node_name}")
        
        # 停止消息处理线程
        self.running = False
        if self.message_thread and self.message_thread.is_alive():
            self.message_thread.join(timeout=2.0)
            print(f"[INFO]KubeProxy {self.node_name} message thread stopped")
        
        # 关闭Kafka消费者
        if self.kafka_consumer:
            try:
                self.kafka_consumer.close()
                print(f"[INFO]KubeProxy {self.node_name} Kafka consumer closed")
            except Exception as e:
                print(f"[WARNING]Error closing Kafka consumer: {e}")
        
        # 清理iptables规则（如果可用）
        if self.iptables_available:
            try:
                self.cleanup_chains()
                print(f"[INFO]KubeProxy {self.node_name} iptables rules cleaned up")
            except Exception as e:
                print(f"[WARNING]Error cleaning up iptables rules: {e}")
        
        print(f"[INFO]KubeProxy {self.node_name} stopped")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='KubeProxy - Node网络代理组件')
    parser.add_argument('--node-name', required=True, help='Node名称')
    parser.add_argument('--test', action='store_true', help='运行KubeProxy测试')
    
    args = parser.parse_args()
    
    if args.test:
        # 测试KubeProxy
        print(f"[INFO]Testing KubeProxy on Node: {args.node_name}")
        proxy = KubeProxy(args.node_name)
        
        # 模拟创建Service规则
        print("\n=== Testing Service Rule Creation ===")
        proxy.create_service_rules(
            service_name="test-service",
            cluster_ip="10.96.1.1",
            port=80,
            protocol="TCP",
            endpoints=["192.168.1.10:8080", "192.168.1.11:8080"]
        )
        
        # 获取统计信息
        print("\n=== Service Statistics ===")
        stats = proxy.get_service_stats("test-service")
        print(f"Service stats: {json.dumps(stats, indent=2)}")
        
        # 测试端点更新
        print("\n=== Testing Endpoint Update ===")
        proxy.update_service_endpoints(
            service_name="test-service",
            cluster_ip="10.96.1.1",
            port=80,
            protocol="TCP",
            endpoints=["192.168.1.12:8080", "192.168.1.13:8080", "192.168.1.14:8080"]
        )
        
        # 清理规则
        print("\n=== Cleaning Up ===")
        proxy.delete_service_rules(
            service_name="test-service",
            cluster_ip="10.96.1.1",
            port=80,
            protocol="TCP"
        )
        
        print("\n=== KubeProxy Test Complete ===")
        
    else:
        print("[INFO]KubeProxy initialized for production use")
        print("Add --test flag to run tests")
