#!/usr/bin/env python3
"""
简化的Kubelet Kafka测试
"""

import json
import time
from confluent_kafka import Consumer, KafkaError

def test_kubelet_kafka():
    """测试Kubelet的Kafka接收"""
    
    # Kafka配置 - 使用和实际Kubelet相同的配置
    kafka_config = {
        'bootstrap.servers': 'localhost:9092',
        'group.id': 'kubelet-node-01',  # 使用实际的group id
        'auto.offset.reset': 'earliest',  # 修复后的配置
        'enable.auto.commit': True
    }
    
    consumer = Consumer(kafka_config)
    topic = "kubelet-node-01"
    consumer.subscribe([topic])
    
    print(f"[INFO]Kubelet Kafka test - Subscribed to topic: {topic}")
    print(f"[INFO]Waiting for messages...")
    
    try:
        timeout_count = 0
        while timeout_count < 30:  # 等待更长时间
            msg = consumer.poll(timeout=1.0)
            
            if msg is None:
                timeout_count += 1
                if timeout_count % 10 == 0:  # 每10秒输出一次
                    print(f"[DEBUG]Waiting for messages... ({timeout_count}/30)")
                continue
                
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    print("[INFO]Reached end of partition")
                    continue
                else:
                    print(f"[ERROR]Kafka error: {msg.error()}")
                    continue
            
            # 收到消息 - 模拟Kubelet处理
            try:
                message_data = json.loads(msg.value().decode('utf-8'))
                action = message_data.get("action")
                
                print(f"[SUCCESS]Received Kafka message: {action}")
                print(f"[INFO]Message content: {message_data}")
                
                if action == "create_pod":
                    pod_data = message_data.get("pod_data")
                    if pod_data:
                        pod_name = pod_data.get("metadata", {}).get("name", "unknown")
                        print(f"[INFO]Would create Pod: {pod_name}")
                        # 这里应该调用 create_pod(pod_data)
                    else:
                        print("[ERROR]Pod data missing in Kafka message")
                else:
                    print(f"[WARN]Unknown action in Kafka message: {action}")
                        
                timeout_count = 0  # 重置超时计数
                
            except json.JSONDecodeError as e:
                print(f"[ERROR]Failed to parse message: {e}")
                
    except KeyboardInterrupt:
        print("[INFO]Interrupted by user")
    finally:
        consumer.close()

if __name__ == "__main__":
    test_kubelet_kafka()
