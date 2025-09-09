import requests
import json
import time
from threading import Thread

from config import Config
from pod import Pod
from confluent_kafka import Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic


class Kubelet:
    def __init__(self, node_name, kafka_bootstrap_servers):
        # 节点名称
        self.node_name = node_name

        # kafka
        self.admin_client = AdminClient({
            'bootstrap.servers': kafka_bootstrap_servers
        })
        self.kafka_config = {
            'bootstrap.servers': kafka_bootstrap_servers,
            'group.id': f'kubelet-{self.node_name}',
            'auto.offset.reset': 'earliest',  # 从最早的消息开始读取
            'enable.auto.commit': True
        }
        self.topic = Config.KUBELET_TOPIC.format(node_name=self.node_name)
        self._create_kafka_topic()
        self.consumer = Consumer(self.kafka_config)
        self.consumer.subscribe([self.topic])
        
        print(f"[INFO]Subscribed to Kafka topic: {self.topic}")
        
        # Pod缓存 - 存储当前节点上的所有Pod
        self.pods_cache = {}  # {namespace/name: Pod}

        # 运行状态
        self.running = False
        
        print(f"[INFO]Kubelet initialized for node {self.node_name}, Kafka: {kafka_bootstrap_servers}")
        
    def _create_kafka_topic(self):
        try:
            # 检查主题是否已存在
            metadata = self.admin_client.list_topics(timeout=10)
            if self.topic in metadata.topics:
                print(f"[DEBUG]Kafka topic {self.topic} already exists")
                return True
            
            # 创建主题
            new_topic = NewTopic(self.topic, num_partitions=1, replication_factor=1)
            futures = self.admin_client.create_topics([new_topic])
            
            # 等待创建完成
            for topic_name, future in futures.items():
                try:
                    future.result()  # 等待创建完成
                    print(f"[INFO]Kafka topic {topic_name} created successfully")
                    return True
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"[DEBUG]Kafka topic {topic_name} already exists")
                        return True
                    else:
                        print(f"[ERROR]Failed to create Kafka topic {topic_name}: {e}")
                        return False
            
        except Exception as e:
            print(f"[ERROR]Failed to create Kafka topic: {e}")
            return False
        
    def start(self):
        """启动Kubelet"""
        self.running = True
        print(f"[INFO]Starting Kubelet on node {self.node_name}")
        
        # TODO: 暂时没有实现监听心跳保证pods都是正常状态
        # 启动监控循环
        # monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        # monitor_thread.start()
        
        # 启动Kafka监听线程
        kafka_thread = Thread(target=self._kafka_listener, daemon=True)
        kafka_thread.start()
        
        print(f"[INFO]Kubelet started successfully")
        
    def stop(self):
        """停止Kubelet"""
        self.running = False
        print(f"[INFO]Kubelet stopped")

     # 更新etcd中pods状态
    
    def _report_pod_status(self, pod):
        try:
            # 构建状态更新URL
            url = f"{Config.SERVER_URI}/api/v1/namespaces/{pod.namespace}/pods/{pod.name}/status"
            
            status_data = {
                "status": pod.status,
                "ip": pod.subnet_ip,
                "node": self.node_name,
                # TODO: 目前容器就一个
                "containers": 1,
                "phase": pod.status
            }
            
            response = requests.put(url, json=status_data, timeout=5)
            
            if response.status_code == 200:
                print(f"[Info]Pod {pod.namespace}/{pod.name} status reported: {pod.status}")
            else:
                print(f"[Error]Failed to report Pod status: {response.status_code}")
                
        except Exception as e:
            print(f"[ERROR]Failed to report Pod status to ApiServer: {e}")
    
    def _kafka_listener(self):
        """
        Kafka监听循环 - 监听调度器分配的Pod任务
        """
        print(f"[INFO]Starting Kafka listener for node {self.node_name}")
         
        try:
            while self.running:
                msg = self.consumer.poll(timeout=1.0)
                
                # 添加调试日志
                if msg is None:
                    print(f"[DEBUG]Kafka poll timeout for topic {self.topic}")
                    continue
                    
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        print(f"[ERROR]Kafka error: {msg.error()}")
                        continue
                
                try:
                    # 解析消息
                    message_data = json.loads(msg.value().decode('utf-8'))
                    action = message_data.get("action")
                    
                    print(f"[INFO]Received Kafka message: {action}")
                    
                    if action == "create_pod":
                        pod_data = message_data.get("pod_data")
                        if pod_data:
                            self.create_pod(pod_data)
                        else:
                            print("[ERROR]Pod data missing in Kafka message")
                    elif action == "delete_pod":
                        pod_info = message_data.get("pod_info")
                        if pod_info:
                            self.delete_pod(pod_info)
                        else:
                            print("[ERROR]Pod info missing in delete Kafka message")
                    else:
                        print(f"[WARN]Unknown action in Kafka message: {action}")
                        
                except json.JSONDecodeError as e:
                    print(f"[ERROR]Failed to parse Kafka message: {e}")
                except Exception as e:
                    print(f"[ERROR]Error processing Kafka message: {e}")
                    
        except Exception as e:
            print(f"[ERROR]Kafka listener error: {e}")
        finally:
            self.consumer.close()
            print(f"[INFO]Kafka listener stopped for node {self.node_name}")
    
    def create_pod(self, pod_data):
        """
        Args:
            pod_data: Pod数据字典
            
        Returns:
            bool: 创建是否成功
        """
        try:
            pod_ns = pod_data.get("metadata", {}).get("namespace", "default")
            pod_name = pod_data.get("metadata", {}).get("name")
            pod_key = f"{pod_ns}/{pod_name}"
            
            print(f"[INFO]Processing Pod creation from Kafka: {pod_key}")
            
            # 检查是否已存在
            if pod_key in self.pods_cache:
                print(f"[WARNING]Pod {pod_key} already exists on this node")
                return False
            
            # 创建Pod实例，设置节点信息，创建容器
            pod = Pod(pod_data)
            pod.node_name = self.node_name
            success = pod.create_containers()
            if success:
                # 添加到缓存，并向ApiServer报告状态
                self.pods_cache[pod_key] = pod
                self._report_pod_status(pod)
                print(f"[INFO]Pod {pod_key} created successfully on node {self.node_name} via Kafka")
                return True
            else:
                print(f"[ERROR]Failed to create Pod {pod_key} via Kafka")
                return False
                
        except Exception as e:
            print(f"[ERROR]Failed to process Pod creation from Kafka: {e}")
            return False
    
    def delete_pod(self, pod_info):
        """
        Args:
            pod_info: Pod删除信息字典，包含namespace和name
            
        Returns:
            bool: 删除是否成功
        """
        try:
            pod_namespace = pod_info.get("namespace", "default")
            pod_name = pod_info.get("name")
            pod_key = f"{pod_namespace}/{pod_name}"
                   
            print(f"[INFO]Processing Pod deletion from Kafka: {pod_key}")
            
            # 检查Pod是否存在
            if pod_key not in self.pods_cache:
                print(f"[WARNING]Pod {pod_key} not found on this node, ignoring delete request")
                return False
            
            # 删除Pod
            pod = self.pods_cache[pod_key]
            success = pod.delete()
            if success:
                del self.pods_cache[pod_key]
                # TODO:是不是需要在这里删除etcd
                print(f"[INFO]Pod {pod_key} deleted successfully on node {self.node_name} via Kafka")
                return True
            else:
                print(f"[ERROR]Failed to delete Pod {pod_key} via Kafka")
                return False

        except Exception as e:
            print(f"[ERROR]Failed to process Pod deletion from Kafka: {e}")
            return False