"""
Kafka工具类，提供Kafka生产者、消费者和管理客户端的封装
"""
import json
import logging
import threading
from typing import Dict, List, Optional, Callable, Any
from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from pkg.config.kafkaConfig import KafkaConfig

logger = logging.getLogger(__name__)

class KafkaProducerWrapper:
    """Kafka生产者封装类"""
    
    def __init__(self, config: Dict = None):
        """
        初始化Kafka生产者
        
        Args:
            config: 自定义配置，如果为None则使用默认配置
        """
        self.config = config or KafkaConfig.get_producer_config()
        self.producer = Producer(self.config)
        self._lock = threading.Lock()
    
    def produce(self, topic: str, value: Any, key: str = None, callback: Callable = None) -> bool:
        """
        发送消息到指定主题
        
        Args:
            topic: 主题名称
            value: 消息值，支持字典、字符串等类型
            key: 消息键（可选）
            callback: 发送完成后的回调函数（可选）
            
        Returns:
            bool: 发送是否成功
        """
        try:
            # 如果value是字典，转换为JSON字符串
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            
            # 确保value是bytes类型
            if isinstance(value, str):
                value = value.encode('utf-8')
            
            # 确保key是bytes类型（如果提供了key）
            if key and isinstance(key, str):
                key = key.encode('utf-8')
            
            with self._lock:
                self.producer.produce(
                    topic=topic,
                    value=value,
                    key=key,
                    callback=callback or self._default_delivery_callback
                )
                self.producer.poll(0)  # 非阻塞轮询
            
            logger.debug(f"Message sent to topic '{topic}' with key '{key}'")
            return True
            
        except KafkaException as e:
            logger.error(f"Failed to send message to topic '{topic}': {e}")
            return False
    
    def _default_delivery_callback(self, err, msg):
        """默认的消息发送回调"""
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")
    
    def flush(self, timeout: float = None):
        """
        刷新生产者缓冲区，等待所有消息发送完成
        
        Args:
            timeout: 超时时间（秒），None表示无限等待
        """
        with self._lock:
            self.producer.flush(timeout)
    
    def close(self):
        """关闭生产者"""
        self.flush()
        # confluent_kafka的Producer没有close方法，但flush可以确保所有消息发送完成


class KafkaConsumerWrapper:
    """Kafka消费者封装类"""
    
    def __init__(self, topics: List[str], group_id: str, node_id: str = None, config: Dict = None):
        """
        初始化Kafka消费者
        
        Args:
            topics: 要订阅的主题列表
            group_id: 消费者组ID
            node_id: 节点ID（可选）
            config: 自定义配置，如果为None则使用默认配置
        """
        self.topics = topics
        self.group_id = group_id
        self.node_id = node_id
        self.config = config or KafkaConfig.get_consumer_config(group_id, node_id)
        self.consumer = Consumer(self.config)
        self.running = False
        self._lock = threading.Lock()
        
        # 订阅主题
        self.consumer.subscribe(self.topics)
        logger.info(f"Kafka consumer subscribed to topics: {self.topics}")
    
    def poll(self, timeout: float = 1.0) -> Optional[Dict]:
        """
        轮询消息
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            Dict: 消息内容，包含topic、key、value、partition、offset等信息
            None: 没有消息或发生错误
        """
        try:
            msg = self.consumer.poll(timeout)
            
            if msg is None:
                return None
            
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug(f"End of partition reached {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")
                else:
                    logger.error(f"Consumer error: {msg.error()}")
                return None
            
            # 解析消息
            value = msg.value()
            if value:
                try:
                    # 尝试解码为字符串
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    
                    # 尝试解析为JSON
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        # 如果不是JSON格式，保持原字符串
                        pass
                        
                except UnicodeDecodeError:
                    logger.warning(f"Failed to decode message value from topic {msg.topic()}")
                    value = msg.value()  # 保持原始bytes
            
            key = msg.key()
            if key and isinstance(key, bytes):
                try:
                    key = key.decode('utf-8')
                except UnicodeDecodeError:
                    pass  # 保持原始bytes
            
            return {
                'topic': msg.topic(),
                'partition': msg.partition(),
                'offset': msg.offset(),
                'key': key,
                'value': value,
                'timestamp': msg.timestamp()
            }
            
        except KafkaException as e:
            logger.error(f"Error while polling messages: {e}")
            return None
    
    def commit(self, message: Dict = None):
        """
        提交偏移量
        
        Args:
            message: 特定消息（可选），如果提供则只提交该消息的偏移量
        """
        try:
            if message:
                # 提交特定消息的偏移量
                # 这需要构造TopicPartition对象，实现较复杂
                # 暂时使用同步提交所有已消费的偏移量
                self.consumer.commit()
            else:
                self.consumer.commit()
            logger.debug("Offset committed successfully")
        except KafkaException as e:
            logger.error(f"Failed to commit offset: {e}")
    
    def start_consuming(self, message_handler: Callable[[Dict], None], error_handler: Callable[[Exception], None] = None):
        """
        启动消费循环
        
        Args:
            message_handler: 消息处理函数，接收消息字典作为参数
            error_handler: 错误处理函数（可选）
        """
        self.running = True
        
        def consume_loop():
            logger.info(f"Starting consumer loop for topics: {self.topics}")
            while self.running:
                try:
                    message = self.poll(timeout=1.0)
                    if message:
                        message_handler(message)
                        # 处理完消息后提交偏移量
                        if self.config.get('enable.auto.commit', True) is False:
                            self.commit()
                            
                except Exception as e:
                    logger.error(f"Error in consumer loop: {e}")
                    if error_handler:
                        error_handler(e)
                    else:
                        # 默认错误处理：短暂休眠后继续
                        import time
                        time.sleep(1)
        
        # 在新线程中运行消费循环
        consumer_thread = threading.Thread(target=consume_loop, daemon=True)
        consumer_thread.start()
        return consumer_thread
    
    def stop_consuming(self):
        """停止消费"""
        self.running = False
        logger.info("Consumer stop requested")
    
    def close(self):
        """关闭消费者"""
        self.stop_consuming()
        with self._lock:
            self.consumer.close()
        logger.info("Kafka consumer closed")


class KafkaAdminWrapper:
    """Kafka管理客户端封装类"""
    
    def __init__(self, config: Dict = None):
        """
        初始化Kafka管理客户端
        
        Args:
            config: 自定义配置，如果为None则使用默认配置
        """
        self.config = config or KafkaConfig.get_admin_config()
        self.admin_client = AdminClient(self.config)
    
    def create_topics(self, topic_names: List[str], num_partitions: int = None, replication_factor: int = None) -> Dict[str, bool]:
        """
        创建主题
        
        Args:
            topic_names: 主题名称列表
            num_partitions: 分区数（可选，默认使用配置值）
            replication_factor: 副本数（可选，默认使用配置值）
            
        Returns:
            Dict[str, bool]: 主题名称到创建结果的映射
        """
        topic_config = KafkaConfig.get_topic_config()
        num_partitions = num_partitions or topic_config["num_partitions"]
        replication_factor = replication_factor or topic_config["replication_factor"]
        
        # 构建NewTopic对象列表
        new_topics = [
            NewTopic(topic, num_partitions=num_partitions, replication_factor=replication_factor)
            for topic in topic_names
        ]
        
        # 创建主题
        fs = self.admin_client.create_topics(new_topics)
        results = {}
        
        for topic, future in fs.items():
            try:
                future.result()  # 等待操作完成
                logger.info(f"Topic '{topic}' created successfully")
                results[topic] = True
            except KafkaException as e:
                if e.args[0].code() == 36:  # 主题已存在错误
                    logger.info(f"Topic '{topic}' already exists")
                    results[topic] = True
                else:
                    logger.error(f"Failed to create topic '{topic}': {e}")
                    results[topic] = False
        
        return results
    
    def delete_topics(self, topic_names: List[str], timeout: float = 30.0) -> Dict[str, bool]:
        """
        删除主题
        
        Args:
            topic_names: 要删除的主题名称列表
            timeout: 超时时间（秒）
            
        Returns:
            Dict[str, bool]: 主题名称到删除结果的映射
        """
        fs = self.admin_client.delete_topics(topic_names, operation_timeout=timeout)
        results = {}
        
        for topic, future in fs.items():
            try:
                future.result()  # 等待操作完成
                logger.info(f"Topic '{topic}' deleted successfully")
                results[topic] = True
            except KafkaException as e:
                logger.error(f"Failed to delete topic '{topic}': {e}")
                results[topic] = False
        
        return results
    
    def list_topics(self, timeout: float = 10.0) -> Optional[Dict]:
        """
        列出所有主题
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            Dict: 主题信息，如果失败则返回None
        """
        try:
            cluster_metadata = self.admin_client.list_topics(timeout=timeout)
            topics_info = {}
            
            for topic_name, topic_metadata in cluster_metadata.topics.items():
                topics_info[topic_name] = {
                    'partitions': len(topic_metadata.partitions),
                    'error': str(topic_metadata.error) if topic_metadata.error else None
                }
            
            return topics_info
            
        except KafkaException as e:
            logger.error(f"Failed to list topics: {e}")
            return None


# 全局实例（单例模式）
_producer_instance = None
_admin_instance = None

def get_kafka_producer() -> KafkaProducerWrapper:
    """获取全局Kafka生产者实例（单例）"""
    global _producer_instance
    if _producer_instance is None:
        _producer_instance = KafkaProducerWrapper()
    return _producer_instance

def get_kafka_admin() -> KafkaAdminWrapper:
    """获取全局Kafka管理客户端实例（单例）"""
    global _admin_instance
    if _admin_instance is None:
        _admin_instance = KafkaAdminWrapper()
    return _admin_instance

def create_kafka_consumer(topics: List[str], group_id: str, node_id: str = None, config: Dict = None) -> KafkaConsumerWrapper:
    """
    创建Kafka消费者实例
    
    Args:
        topics: 要订阅的主题列表
        group_id: 消费者组ID
        node_id: 节点ID（可选）
        config: 自定义配置（可选）
        
    Returns:
        KafkaConsumerWrapper: 消费者实例
    """
    return KafkaConsumerWrapper(topics, group_id, node_id, config)
