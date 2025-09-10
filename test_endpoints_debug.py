#!/usr/bin/env python3
"""
直接测试Service端点发现功能
"""
import sys
sys.path.append('.')

from service import ServiceManager, Service
from etcd import Etcd
import json

def test_service_endpoints():
    """测试Service端点发现功能"""
    print("=== 测试Service端点发现 ===")
    
    # 1. 手动创建Service对象测试
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
    
    # 2. 创建Service对象
    service = Service(service_spec)
    print(f"✅ Service创建成功: {service.name}")
    print(f"📋 Service选择器: {service.selector}")
    print(f"📋 Service端口配置: {service.ports}")
    print(f"📋 初始endpoints: {service.endpoints}")
    
    # 3. 从etcd获取Pod数据并直接测试端点更新
    print("\n🔍 获取etcd中的Pod数据...")
    
    etcd_client = Etcd()
    try:
        pods_data = etcd_client.get_prefix("/pods/")
        if pods_data:
            print(f"✅ 获取到 {len(pods_data)} 个Pod")
            
            # 检查每个Pod
            for i, pod_data in enumerate(pods_data):
                if pod_data and isinstance(pod_data, dict):
                    pod_name = pod_data.get('metadata', {}).get('name', f'pod-{i}')
                    pod_labels = pod_data.get('metadata', {}).get('labels', {})
                    pod_ip = pod_data.get('ip', 'unknown')
                    
                    print(f"📍 Pod {i}: {pod_name}")
                    print(f"   标签: {pod_labels}")
                    print(f"   IP: {pod_ip}")
                    
                    # 测试标签匹配
                    matches = service.matches_pod(pod_labels)
                    print(f"   与Service匹配: {matches}")
                    
                    if matches:
                        print("   ✅ 这个Pod应该被选中作为端点")
            
            # 4. 直接调用update_endpoints测试
            print(f"\n🔍 调用service.update_endpoints()...")
            success = service.update_endpoints(pods_data)
            print(f"📍 端点更新结果: {success}")
            
            # 5. 检查更新后的端点
            print(f"📍 更新后的端点: {service.endpoints}")
            
            if service.endpoints:
                print("✅ 端点发现成功!")
                for endpoint in service.endpoints:
                    print(f"   - {endpoint}")
                    
                # 6. 测试负载均衡
                print(f"\n🔍 测试负载均衡...")
                if service.ports:
                    target_port = service.ports[0]["target_port"]
                    for i in range(3):
                        selected = service.select_endpoint(target_port)
                        print(f"   请求 {i+1}: 选择端点 {selected}")
                        
                return True
            else:
                print("❌ 端点更新后仍然没有发现端点")
                return False
                
        else:
            print("❌ etcd中没有找到Pod数据")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_service_endpoints()
    if success:
        print("\n🎉 Service端点发现测试成功!")
    else:
        print("\n❌ Service端点发现测试失败!")
        sys.exit(1)
