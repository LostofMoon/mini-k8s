#!/usr/bin/env python3
"""
直接测试Service Manager功能
"""
import sys
sys.path.append('.')

from service import ServiceManager, Service
from etcd import Etcd
import json

def test_service_manager():
    """测试Service Manager的端点发现功能"""
    print("=== 测试Service Manager ===")
    
    # 1. 初始化Service Manager
    service_manager = ServiceManager()
    
    # 2. 手动创建Service对象测试
    service_spec = {
        "metadata": {
            "name": "hello-world-service",
            "namespace": "default",
            "labels": {},
            "uid": "test-uid"
        },
        "spec": {
            "selector": {
                "app": "hello-world"
            },
            "type": "ClusterIP",
            "clusterIP": "10.96.14.53",
            "ports": [
                {
                    "port": 8090,
                    "target_port": 90,
                    "protocol": "TCP"
                }
            ]
        }
    }
    
    # 3. 创建Service对象
    service = Service(service_spec)
    print(f"✅ Service创建成功: {service.name}")
    
    # 4. 测试端点发现
    print("✅ Service创建成功，初始endpoints:", service.endpoints)
    
    # 手动更新endpoints以测试功能
    print("\n🔍 手动触发端点发现...")
    service_manager.sync_service_endpoints(service)
    
    endpoints = service.endpoints
    print(f"📍 发现的端点: {endpoints}")
    
    if endpoints:
        print("✅ 端点发现成功!")
        for endpoint in endpoints:
            print(f"   - {endpoint}")
    else:
        print("❌ 没有发现端点")
        print("🔍 让我们检查为什么没有发现端点...")
        
        # 调试：检查etcd中的Pod数据
        etcd_client = Etcd()
        try:
            pods_data = etcd_client.get_prefix("/pods/")
            print(f"🔍 etcd中的Pod数据数量: {len(pods_data) if pods_data else 0}")
            
            if pods_data:
                for i, pod_data in enumerate(pods_data):
                    print(f"🔍 Pod数据 {i}: type={type(pod_data)}, content={repr(pod_data)[:200]}...")
                    if pod_data and isinstance(pod_data, dict):
                        pod_labels = pod_data.get('metadata', {}).get('labels', {})
                        pod_name = pod_data.get('metadata', {}).get('name', f'pod-{i}')
                        print(f"🔍 检查Pod {pod_name}: labels={pod_labels}")
                        if pod_labels.get('app') == 'hello-world':
                            print(f"✅ 找到匹配的Pod: {pod_name}")
                            # 仔细检查IP字段
                            print(f"🔍 Pod数据结构: ip={pod_data.get('ip')}")
                            print(f"🔍 Pod状态: {pod_data.get('status', {})}")
                            
                            pod_ip = pod_data.get('ip') or pod_data.get('status', {}).get('podIP')
                            pod_status = pod_data.get('status')
                            if isinstance(pod_status, dict):
                                pod_phase = pod_status.get('phase', 'Unknown')
                            else:
                                pod_phase = str(pod_status)
                            print(f"   Pod IP: {pod_ip}, Status: {pod_phase}")
            else:
                print("🔍 etcd中没有找到任何Pod数据")
            
        except Exception as e:
            print(f"🔍 检查etcd数据时出错: {e}")
    
    # 5. 测试负载均衡
    if endpoints:
        print("\n=== 测试负载均衡 ===")
        for i in range(5):
            # 测试第一个端口的负载均衡
            if service.ports:
                target_port = service.ports[0]["target_port"]
                selected = service.select_endpoint(target_port)
                print(f"请求 {i+1}: 选择端点 {selected}")
            else:
                print("没有可用的端口配置")
    
    return len(endpoints) > 0

if __name__ == "__main__":
    success = test_service_manager()
    if success:
        print("\n🎉 Service Manager测试成功!")
    else:
        print("\n❌ Service Manager测试失败!")
        sys.exit(1)
