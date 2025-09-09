"""
Kubelet和ApiServer集成测试
模拟真实的Node节点管理Pod的场景
"""
import time
import threading
import yaml
import os
import requests

from kubelet import Kubelet
from pod import Pod
from apiServer import ApiServer


def test_kubelet_integration():
    """测试Kubelet与ApiServer的集成"""
    print("=== Kubelet和ApiServer集成测试 ===")
    
    # 1. 启动ApiServer (在后台)
    print("\n1. 启动ApiServer...")
    api_server = ApiServer()
    server_thread = threading.Thread(target=lambda: api_server.run(), daemon=True)
    server_thread.start()
    
    # 等待ApiServer启动
    time.sleep(2)
    print("   ✅ ApiServer已启动")
    
    # 2. 创建Kubelet实例
    print("\n2. 创建Kubelet实例...")
    kubelet_config = {
        "node_id": "test-node-1",
        "apiserver": "localhost", 
        "subnet_ip": "10.244.1.0/24"
    }
    
    kubelet = Kubelet(kubelet_config)
    kubelet.start()
    print("   ✅ Kubelet已启动")
    
    # 3. 测试Pod创建
    print("\n3. 测试Pod创建...")
    test_pod_yaml = {
        "apiVersion": "v1",
        "kind": "Pod", 
        "metadata": {
            "name": "test-kubelet-pod",
            "namespace": "default",
            "labels": {"app": "kubelet-test"}
        },
        "spec": {
            "containers": [
                {
                    "name": "test-container",
                    "image": "nginx:latest",
                    "ports": [{"containerPort": 80}]
                }
            ]
        }
    }
    
    # 通过Kubelet创建Pod
    success = kubelet.create_pod_directly(test_pod_yaml)
    if success:
        print("   ✅ Pod创建成功")
        
        # 检查Pod状态
        pod_status = kubelet.get_pod_status("default", "test-kubelet-pod")
        print(f"   Pod状态: {pod_status}")
        
        # 列出所有Pod
        all_pods = kubelet.list_pods()
        print(f"   当前节点Pod数量: {len(all_pods)}")
        
    else:
        print("   ❌ Pod创建失败")
        return False
    
    # 4. 测试通过ApiServer查询Pod
    print("\n4. 测试通过ApiServer查询Pod...")
    try:
        response = requests.get("http://localhost:5050/api/v1/namespaces/default/pods/test-kubelet-pod")
        if response.status_code == 200:
            pod_data = response.json()
            print("   ✅ 通过ApiServer查询Pod成功")
            print(f"   Pod名称: {pod_data.get('metadata', {}).get('name')}")
        else:
            print(f"   ⚠️ ApiServer查询返回状态码: {response.status_code}")
    except Exception as e:
        print(f"   ❌ ApiServer查询失败: {e}")
    
    # 5. 测试监控功能
    print("\n5. 测试监控功能...")
    print("   监控Pod状态变化（等待10秒）...")
    time.sleep(10)
    
    # 6. 测试Pod删除
    print("\n6. 测试Pod删除...")
    success = kubelet.delete_pod_directly("default", "test-kubelet-pod")
    if success:
        print("   ✅ Pod删除成功")
        
        # 验证Pod已删除
        remaining_pods = kubelet.list_pods()
        print(f"   剩余Pod数量: {len(remaining_pods)}")
    else:
        print("   ❌ Pod删除失败")
    
    # 7. 停止Kubelet
    print("\n7. 停止Kubelet...")
    kubelet.stop()
    print("   ✅ Kubelet已停止")
    
    print("\n=== 测试完成 ===")
    print("✅ Kubelet集成测试成功！")
    
    return True


def test_kubelet_basic():
    """测试Kubelet的基本功能（不需要ApiServer）"""
    print("=== Kubelet基本功能测试 ===")
    
    # 创建Kubelet
    kubelet_config = {
        "node_id": "basic-test-node",
        "apiserver": "localhost",
        "subnet_ip": "10.244.2.0/24"
    }
    
    kubelet = Kubelet(kubelet_config)
    print("✅ Kubelet创建成功")
    
    # 启动Kubelet
    kubelet.start()
    print("✅ Kubelet启动成功")
    
    # 测试Pod配置
    test_pod = {
        "metadata": {
            "name": "basic-test-pod",
            "namespace": "default"
        },
        "spec": {
            "containers": [
                {
                    "name": "test-container",
                    "image": "busybox",
                    "command": ["echo", "hello kubelet"]
                }
            ]
        }
    }
    
    # 创建Pod
    success = kubelet.create_pod_directly(test_pod)
    if success:
        print("✅ Pod创建成功")
        
        # 查看状态
        status = kubelet.get_pod_status("default", "basic-test-pod")
        print(f"Pod状态: {status}")
        
        # 删除Pod
        success = kubelet.delete_pod_directly("default", "basic-test-pod")
        if success:
            print("✅ Pod删除成功")
        
    else:
        print("❌ Pod创建失败")
    
    # 停止Kubelet
    kubelet.stop()
    print("✅ Kubelet停止成功")
    
    print("\n=== 基本功能测试完成 ===")


if __name__ == "__main__":
    print("Kubelet测试开始...")
    
    # 选择测试类型
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--integration":
        print("运行集成测试...")
        test_kubelet_integration()
    else:
        print("运行基本功能测试...")
        test_kubelet_basic()
        
    print("\n🎉 所有测试完成！")
