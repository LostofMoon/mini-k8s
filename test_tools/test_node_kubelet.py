"""
Node + Kubelet 集成测试
测试Node类能否正确启动和管理Kubelet组件
"""
import time
import threading
import yaml
import os

from apiServer import ApiServer
from node import Node


def test_node_kubelet_integration():
    """测试Node与Kubelet的集成"""
    print("=== Node + Kubelet 集成测试 ===")
    
    # 1. 启动ApiServer
    print("\n1. 启动ApiServer...")
    api_server = ApiServer()
    server_thread = threading.Thread(target=lambda: api_server.run(), daemon=True)
    server_thread.start()
    
    # 等待ApiServer启动
    time.sleep(2)
    print("   ✅ ApiServer已启动")
    
    # 2. 创建Node配置
    print("\n2. 创建Node配置...")
    node_config = {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {
            "name": "test-worker-node",
            "api-server": {
                "ip": "localhost"
            }
        },
        "spec": {
            "podCIDR": "10.244.2.0/24",
            "taints": []
        }
    }
    
    # 3. 创建并启动Node（会自动启动Kubelet）
    print("\n3. 创建并启动Node...")
    node = Node(node_config)
    node.run()
    
    # 检查Kubelet是否启动
    if node.kubelet:
        print("   ✅ Kubelet已通过Node启动")
        print(f"   节点ID: {node.name}")
        print(f"   Kubelet节点ID: {node.kubelet.node_id}")
        print(f"   子网IP: {node.kubelet.subnet_ip}")
    else:
        print("   ❌ Kubelet启动失败")
        return False
    
    # 4. 测试Kubelet功能
    print("\n4. 测试Kubelet功能...")
    
    # 创建测试Pod配置
    test_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "node-test-pod",
            "namespace": "default"
        },
        "spec": {
            "containers": [
                {
                    "name": "test-app",
                    "image": "alpine:latest",
                    "command": ["sleep", "300"]
                }
            ]
        }
    }
    
    # 通过Node的Kubelet创建Pod
    success = node.kubelet.create_pod(test_pod)
    if success:
        print("   ✅ 通过Node的Kubelet成功创建Pod")
        
        # 检查Pod状态
        pod_status = node.kubelet.get_pod_status("default", "node-test-pod")
        print(f"   Pod状态: {pod_status}")
        
        # 列出Kubelet管理的Pod
        pods = node.kubelet.list_pods()
        print(f"   Kubelet管理的Pod数量: {len(pods)}")
    else:
        print("   ❌ 通过Node的Kubelet创建Pod失败")
    
    # 5. 测试节点运行状态
    print("\n5. 测试节点运行状态...")
    print("   等待10秒，监控Pod状态...")
    
    for i in range(2):
        time.sleep(5)
        if node.kubelet:
            pod_count = len(node.kubelet.list_pods())
            print(f"   [{i+1}/2] 当前Pod数量: {pod_count}")
    
    # 6. 清理测试
    print("\n6. 清理测试...")
    
    if node.kubelet:
        # 删除测试Pod
        success = node.kubelet.delete_pod("default", "node-test-pod")
        if success:
            print("   ✅ 测试Pod已删除")
    
    # 停止Node（会自动停止Kubelet）
    node.stop()
    print("   ✅ Node已停止")
    
    print("\n=== 测试完成 ===")
    print("✅ Node + Kubelet 集成测试成功！")
    
    return True


def test_node_config_methods():
    """测试Node的配置方法"""
    print("=== Node配置方法测试 ===")
    
    # 创建Node
    node_config = {
        "apiVersion": "v1", 
        "kind": "Node",
        "metadata": {
            "name": "config-test-node"
        },
        "spec": {
            "podCIDR": "10.244.3.0/24"
        }
    }
    
    node = Node(node_config)
    
    # 测试kubelet_config_args方法
    kubelet_config = node.kubelet_config_args()
    
    print(f"Node名称: {node.name}")
    print(f"节点ID: {node.id}")
    print(f"ApiServer: {node.apiserver}")
    print(f"子网IP: {node.subnet_ip}")
    
    print("\nKubelet配置参数:")
    for key, value in kubelet_config.items():
        print(f"  {key}: {value}")
    
    print("\n✅ Node配置方法测试完成")


if __name__ == "__main__":
    print("Node + Kubelet 集成测试开始...")
    
    # 运行配置方法测试
    test_node_config_methods()
    print("\n" + "="*50 + "\n")
    
    # 运行集成测试
    test_node_kubelet_integration()
    
    print("\n🎉 所有测试完成！")
