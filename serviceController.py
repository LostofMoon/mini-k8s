#!/usr/bin/env python3
"""
Mini-K8s ServiceController实现
负责Service生命周期管理、端点发现和规则分发
"""

import json
import time
import threading
from typing import Dict, List, Optional
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic

from config import Config
from service import Service
from etcd import Etcd

class ServiceController:
    """
    ServiceController负责:
    1. 监听Service对象的创建、更新、删除
    2. 管理Service端点发现
    3. 通过Kafka分发Service规则到各个KubeProxy
    4. 维护Service状态同步
    """
    
    def __init__(self):
        self.etcd = Etcd()
        self.services: Dict[str, Service] = {}  # namespace/name -> Service
        self.running = False
        
        # Kafka配置
        self.kafka_config = {
            'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'service-controller'
        }
        
        self.producer = Producer(self.kafka_config)
        
        # Consumer配置 - 监听Service变化
        consumer_config = {
            'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': 'service-controller',
            'auto.offset.reset': 'latest'
        }
        self.consumer = Consumer(consumer_config)
        
        self._init_kafka_topics()
        
        print(f"[INFO]ServiceController初始化完成")
    
    def _init_kafka_topics(self):
        """初始化Kafka主题"""
        try:
            admin_client = AdminClient(self.kafka_config)
            
            topics_to_create = [
                NewTopic(Config.SERVICE_EVENTS_TOPIC, num_partitions=1, replication_factor=1),
                NewTopic('service-proxy-rules', num_partitions=1, replication_factor=1)
            ]
            
            # 创建主题（忽略已存在的错误）
            fs = admin_client.create_topics(topics_to_create)
            for topic, f in fs.items():
                try:
                    f.result()
                    print(f"[INFO]创建Kafka主题: {topic}")
                except Exception as e:
                    if "already exists" not in str(e):
                        print(f"[WARNING]创建主题 {topic} 失败: {e}")
                        
        except Exception as e:
            print(f"[ERROR]初始化Kafka主题失败: {e}")
    
    def start(self):
        """启动ServiceController"""
        print("[INFO]启动ServiceController...")
        self.running = True
        
        # 从etcd加载现有Service
        self._load_existing_services()
        
        # 启动监听线程
        service_listener = threading.Thread(target=self._service_event_listener, daemon=True)
        endpoint_sync = threading.Thread(target=self._endpoint_sync_loop, daemon=True)
        
        service_listener.start()
        endpoint_sync.start()
        
        print("[INFO]ServiceController已启动")
        
        # 主循环
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INFO]收到停止信号...")
            self.stop()
    
    def stop(self):
        """停止ServiceController"""
        print("[INFO]停止ServiceController...")
        self.running = False
        
        if hasattr(self, 'consumer'):
            self.consumer.close()
        if hasattr(self, 'producer'):
            self.producer.flush()
    
    def _load_existing_services(self):
        """从etcd加载现有Service"""
        try:
            services_data = self.etcd.get_prefix(Config.GLOBAL_SERVICES_KEY)
            
            for service_data in services_data:
                try:
                    # 如果service_data是字符串，则解析；如果已经是dict，直接使用
                    if isinstance(service_data, str):
                        service_config = json.loads(service_data)
                    else:
                        service_config = service_data
                        
                    service = Service(service_config)
                    service_key = f"{service.namespace}/{service.name}"
                    self.services[service_key] = service
                    
                    print(f"[INFO]加载现有Service: {service_key}")
                    
                    # 同步端点
                    self._sync_service_endpoints(service)
                    
                    # 分发规则到KubeProxy
                    self._distribute_service_rules(service, 'CREATE')
                    
                except Exception as e:
                    print(f"[ERROR]加载Service失败: {e}")
                    
        except Exception as e:
            print(f"[WARNING]加载现有Service失败: {e}")
    
    def _service_event_listener(self):
        """监听Service事件"""
        self.consumer.subscribe([Config.SERVICE_EVENTS_TOPIC])
        
        print("[INFO]ServiceController开始监听Service事件...")
        
        while self.running:
            try:
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                    
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        print(f"[ERROR]Kafka消费错误: {msg.error()}")
                    continue
                
                # 处理Service事件
                self._handle_service_event(msg)
                
            except Exception as e:
                print(f"[ERROR]处理Service事件失败: {e}")
                time.sleep(1)
    
    def _handle_service_event(self, msg):
        """处理Service事件"""
        try:
            event = json.loads(msg.value().decode('utf-8'))
            event_type = event.get('type')  # CREATE, UPDATE, DELETE
            service_data = event.get('service')
            
            print(f"[INFO]收到Service事件: {event_type}")
            
            if event_type == 'CREATE':
                self._handle_service_create(service_data)
            elif event_type == 'UPDATE':
                self._handle_service_update(service_data)
            elif event_type == 'DELETE':
                self._handle_service_delete(service_data)
                
        except Exception as e:
            print(f"[ERROR]处理Service事件失败: {e}")
    
    def _handle_service_create(self, service_data):
        """处理Service创建"""
        try:
            service = Service(service_data)
            service_key = f"{service.namespace}/{service.name}"
            
            # 添加到本地缓存
            self.services[service_key] = service
            
            # 同步端点
            self._sync_service_endpoints(service)
            
            # 分发规则
            self._distribute_service_rules(service, 'CREATE')
            
            print(f"[INFO]Service创建完成: {service_key}")
            
        except Exception as e:
            print(f"[ERROR]处理Service创建失败: {e}")
    
    def _handle_service_update(self, service_data):
        """处理Service更新"""
        try:
            service = Service(service_data)
            service_key = f"{service.namespace}/{service.name}"
            
            if service_key in self.services:
                # 更新本地缓存
                self.services[service_key] = service
                
                # 重新同步端点
                self._sync_service_endpoints(service)
                
                # 分发更新规则
                self._distribute_service_rules(service, 'UPDATE')
                
                print(f"[INFO]Service更新完成: {service_key}")
            else:
                # 如果本地没有，当作创建处理
                self._handle_service_create(service_data)
                
        except Exception as e:
            print(f"[ERROR]处理Service更新失败: {e}")
    
    def _handle_service_delete(self, service_data):
        """处理Service删除"""
        try:
            service_key = f"{service_data['metadata']['namespace']}/{service_data['metadata']['name']}"
            
            if service_key in self.services:
                service = self.services[service_key]
                
                # 分发删除规则
                self._distribute_service_rules(service, 'DELETE')
                
                # 从本地缓存移除
                del self.services[service_key]
                
                print(f"[INFO]Service删除完成: {service_key}")
            
        except Exception as e:
            print(f"[ERROR]处理Service删除失败: {e}")
    
    def _endpoint_sync_loop(self):
        """端点同步循环"""
        print("[INFO]启动端点同步循环...")
        
        while self.running:
            try:
                # 为每个Service同步端点
                for service_key, service in self.services.items():
                    self._sync_service_endpoints(service)
                
                # 每5秒同步一次
                time.sleep(5)
                
            except Exception as e:
                print(f"[ERROR]端点同步失败: {e}")
                time.sleep(5)
    
    def _sync_service_endpoints(self, service: Service):
        """同步Service端点"""
        try:
            # 从etcd获取所有Pod
            pods_data = self.etcd.get_prefix(Config.GLOBAL_PODS_KEY)
            matching_pods = []
            
            for pod_data in pods_data:
                try:
                    # 如果pod_data是字符串，则解析；如果已经是dict，直接使用
                    if isinstance(pod_data, str):
                        pod_dict = json.loads(pod_data)
                    else:
                        pod_dict = pod_data
                    
                    # 检查Pod是否匹配Service选择器
                    if self._pod_matches_selector(pod_dict, service.selector):
                        # 检查Pod是否在运行状态
                        if pod_dict.get('status') == 'RUNNING':
                            matching_pods.append(pod_dict)
                            
                except Exception as e:
                    print(f"[WARNING]解析Pod数据失败: {e}")
            
            # 更新Service端点
            old_endpoints_count = len(service.endpoints)
            service.update_endpoints(matching_pods)
            new_endpoints_count = len(service.endpoints)
            
            # 如果端点有变化，分发更新规则
            if old_endpoints_count != new_endpoints_count:
                print(f"[INFO]Service {service.namespace}/{service.name} 端点更新: {old_endpoints_count} -> {new_endpoints_count}")
                self._distribute_service_rules(service, 'UPDATE')
            
        except Exception as e:
            print(f"[ERROR]同步Service端点失败: {e}")
    
    def _pod_matches_selector(self, pod_data: dict, selector: dict) -> bool:
        """检查Pod是否匹配Service选择器"""
        try:
            pod_labels = pod_data.get('metadata', {}).get('labels', {})
            
            # 检查所有选择器标签是否匹配
            for key, value in selector.items():
                if pod_labels.get(key) != value:
                    return False
            
            return True
            
        except Exception:
            return False
    
    def _distribute_service_rules(self, service: Service, action: str):
        """分发Service规则到所有KubeProxy"""
        try:
            # 构建Service规则消息
            rule_message = {
                'action': action,  # CREATE, UPDATE, DELETE
                'timestamp': time.time(),
                'service': {
                    'name': service.name,
                    'namespace': service.namespace,
                    'cluster_ip': service.cluster_ip,
                    'service_type': service.service_type,
                    'ports': service.ports,
                    'endpoints': service.endpoints
                }
            }
            
            # 发送到所有节点的KubeProxy
            topic = 'service-proxy-rules'
            message_json = json.dumps(rule_message)
            
            self.producer.produce(
                topic,
                key=f"{service.namespace}/{service.name}",
                value=message_json,
                callback=self._delivery_callback
            )
            
            self.producer.poll(0)  # 触发回调
            
            print(f"[INFO]分发Service规则: {action} {service.namespace}/{service.name}")
            
        except Exception as e:
            print(f"[ERROR]分发Service规则失败: {e}")
    
    def _delivery_callback(self, err, msg):
        """Kafka消息发送回调"""
        if err:
            print(f"[ERROR]Service规则分发失败: {err}")
        else:
            print(f"[DEBUG]Service规则分发成功: {msg.topic()}")
    
    def get_service_stats(self) -> dict:
        """获取ServiceController统计信息"""
        return {
            'total_services': len(self.services),
            'services': {
                service_key: {
                    'cluster_ip': service.cluster_ip,
                    'type': service.service_type,
                    'endpoints_count': len(service.endpoints),
                    'ports': len(service.ports)
                }
                for service_key, service in self.services.items()
            },
            'running': self.running
        }


def main():
    """ServiceController主程序"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Mini-K8s ServiceController')
    parser.add_argument('--daemon', action='store_true', help='以守护进程模式运行')
    parser.add_argument('--test', action='store_true', help='运行测试模式')
    parser.add_argument('--stats', action='store_true', help='显示统计信息')
    
    args = parser.parse_args()
    
    if args.test:
        # 测试模式
        print("=== ServiceController 测试模式 ===")
        controller = ServiceController()
        
        # 显示统计信息
        stats = controller.get_service_stats()
        print("统计信息:")
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        
    elif args.stats:
        # 只显示统计信息（需要连接到运行中的ServiceController）
        print("显示统计信息功能需要实现...")
        
    elif args.daemon:
        # 守护进程模式
        print("启动ServiceController守护进程...")
        controller = ServiceController()
        controller.start()
        
    else:
        print("ServiceController使用方法:")
        print("  --daemon    启动守护进程")
        print("  --test      运行测试模式")
        print("  --stats     显示统计信息")


if __name__ == "__main__":
    main()