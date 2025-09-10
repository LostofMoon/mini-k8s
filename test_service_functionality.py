#!/usr/bin/env python3
"""
Service功能验证测试脚本
"""

import requests
import json

def test_service_api():
    """测试Service API功能"""
    print("="*60)
    print("Service功能测试")
    print("="*60)
    
    base_url = "http://localhost:5050"
    
    # 1. 测试获取所有Services
    print("\n1. 测试获取所有Services:")
    try:
        response = requests.get(f"{base_url}/api/v1/services")
        if response.status_code == 200:
            data = response.json()
            services = data.get("items", [])
            print(f"✓ 找到 {len(services)} 个Services")
            for service in services:
                metadata = service.get("metadata", {})
                spec = service.get("spec", {})
                print(f"  - {metadata.get('namespace', 'default')}/{metadata.get('name')}")
                print(f"    类型: {spec.get('type', 'ClusterIP')}")
                print(f"    ClusterIP: {spec.get('clusterIP', 'None')}")
                print(f"    选择器: {spec.get('selector', {})}")
        else:
            print(f"✗ 获取Services失败: {response.status_code}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 2. 测试获取特定Service
    print("\n2. 测试获取特定Service:")
    try:
        response = requests.get(f"{base_url}/api/v1/namespaces/default/services/hello-world-nodeport")
        if response.status_code == 200:
            service = response.json()
            metadata = service.get("metadata", {})
            spec = service.get("spec", {})
            status = service.get("status", {})
            
            print(f"✓ Service详情:")
            print(f"  名称: {metadata.get('name')}")
            print(f"  命名空间: {metadata.get('namespace')}")
            print(f"  类型: {spec.get('type')}")
            print(f"  ClusterIP: {spec.get('clusterIP')}")
            print(f"  端口: {spec.get('ports')}")
            print(f"  端点: {status.get('endpoints', [])}")
        else:
            print(f"✗ 获取Service失败: {response.status_code}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 3. 测试获取所有Pods（检查端点匹配）
    print("\n3. 检查Pod-Service匹配:")
    try:
        response = requests.get(f"{base_url}/api/v1/pods")
        if response.status_code == 200:
            data = response.json()
            pods = data.get("pods", [])
            print(f"✓ 找到 {len(pods)} 个Pods")
            for pod in pods:
                metadata = pod.get("metadata", {})
                labels = metadata.get("labels", {})
                pod_ip = pod.get("ip", "None")
                print(f"  - {metadata.get('name')}: IP={pod_ip}, Labels={labels}")
        else:
            print(f"✗ 获取Pods失败: {response.status_code}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    print("\n" + "="*60)
    print("测试完成!")

if __name__ == "__main__":
    test_service_api()
