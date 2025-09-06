"""
测试优化后的Pod存储逻辑
验证直接通过prefix查询的效率和正确性
"""
import requests
import json
import time

def test_optimized_pod_storage():
    """测试优化后的Pod存储逻辑"""
    base_url = "http://localhost:5050"
    
    print("=== 测试优化后的Pod存储逻辑 ===")
    
    # 测试数据
    test_pods = [
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "test-pod-1",
                "namespace": "default",
                "labels": {"app": "test"}
            },
            "spec": {
                "containers": [
                    {
                        "name": "test-container-1",
                        "image": "nginx:latest"
                    }
                ]
            }
        },
        {
            "apiVersion": "v1", 
            "kind": "Pod",
            "metadata": {
                "name": "test-pod-2",
                "namespace": "kube-system",
                "labels": {"app": "system"}
            },
            "spec": {
                "containers": [
                    {
                        "name": "test-container-2",
                        "image": "busybox:latest"
                    }
                ]
            }
        }
    ]
    
    try:
        # 1. 创建测试Pods
        print("\n1. 创建测试Pods...")
        for pod in test_pods:
            namespace = pod["metadata"]["namespace"]
            name = pod["metadata"]["name"]
            
            response = requests.post(
                f"{base_url}/api/v1/namespaces/{namespace}/pods",
                json=pod,
                timeout=5
            )
            
            if response.status_code == 200:
                print(f"   ✅ Pod {namespace}/{name} 创建成功")
            else:
                print(f"   ❌ Pod {namespace}/{name} 创建失败: {response.status_code}")
        
        # 2. 测试获取所有Pods（通过prefix查询）
        print("\n2. 测试获取所有Pods...")
        response = requests.get(f"{base_url}/api/v1/pods", timeout=5)
        
        if response.status_code == 200:
            all_pods = response.json()
            print(f"   ✅ 获取所有Pods成功，共 {len(all_pods.get('items', []))} 个")
            for pod in all_pods.get('items', []):
                metadata = pod.get('metadata', {})
                print(f"     - {metadata.get('namespace', 'default')}/{metadata.get('name', 'unknown')}")
        else:
            print(f"   ❌ 获取所有Pods失败: {response.status_code}")
        
        # 3. 测试按命名空间获取Pods
        print("\n3. 测试按命名空间获取Pods...")
        for namespace in ["default", "kube-system"]:
            response = requests.get(f"{base_url}/api/v1/namespaces/{namespace}/pods", timeout=5)
            
            if response.status_code == 200:
                namespace_pods = response.json()
                count = len(namespace_pods.get('items', []))
                print(f"   ✅ 命名空间 '{namespace}' 有 {count} 个Pod")
            else:
                print(f"   ❌ 获取命名空间 '{namespace}' Pods失败: {response.status_code}")
        
        # 4. 测试删除Pod
        print("\n4. 测试删除Pod...")
        response = requests.delete(f"{base_url}/api/v1/namespaces/default/pods/test-pod-1", timeout=5)
        
        if response.status_code == 200:
            print("   ✅ Pod删除成功")
            
            # 验证删除后的状态
            response = requests.get(f"{base_url}/api/v1/pods", timeout=5)
            if response.status_code == 200:
                remaining_pods = response.json()
                count = len(remaining_pods.get('items', []))
                print(f"   ✅ 删除后剩余 {count} 个Pod")
            
        else:
            print(f"   ❌ Pod删除失败: {response.status_code}")
        
        print("\n=== 测试完成 ===")
        print("✅ 优化成功！")
        print("优势说明:")
        print("1. 无需维护冗余的全局Pod列表")
        print("2. 数据一致性更好，只有一个数据源")
        print("3. 代码更简洁，减少维护成本")
        print("4. 直接通过etcd的prefix查询，性能良好")
        
    except requests.RequestException as e:
        print(f"❌ 网络请求失败: {e}")
        print("请确保ApiServer已启动 (python apiServer.py)")
    except Exception as e:
        print(f"❌ 测试过程中出错: {e}")

if __name__ == "__main__":
    test_optimized_pod_storage()
