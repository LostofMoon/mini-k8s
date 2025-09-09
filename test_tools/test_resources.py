"""
Mini-K8s 资源类综合测试
测试Node和Pod的基本功能
"""
import yaml
import os

from node import Node
from pod import Pod
from config import Config

def test_node_and_pod():
    """测试Node和Pod的基本功能"""
    print("=== Mini-K8s 资源类综合测试 ===")
    
    # 测试Node
    print("\n1. 测试Node...")
    node_yaml_path = "testFile/node-1.yaml"
    
    if os.path.exists(node_yaml_path):
        with open(node_yaml_path, 'r', encoding='utf-8') as f:
            node_data = yaml.safe_load(f)
        
        node = Node(node_data)
        print(f"   ✅ Node创建成功: {node.name}")
        print(f"   - ID: {node.id}")
        print(f"   - 子网: {node.subnet_ip}")
        print(f"   - API服务器: {node.apiserver}")
    else:
        print("   ❌ Node配置文件不存在")
    
    # 测试Pod
    print("\n2. 测试Pod...")
    pod_yaml_path = "testFile/pod-1.yaml"
    
    if os.path.exists(pod_yaml_path):
        with open(pod_yaml_path, 'r', encoding='utf-8') as f:
            pod_data = yaml.safe_load(f)
        
        pod = Pod(pod_data)
        print(f"   ✅ Pod创建成功: {pod.namespace}/{pod.name}")
        print(f"   - ID: {pod.id}")
        print(f"   - 容器数: {len(pod.containers)}")
        print(f"   - 状态: {pod.status}")
        
        # 测试生命周期
        success = pod.create()
        if success:
            print(f"   ✅ Pod启动成功: {pod.status}")
        else:
            print(f"   ❌ Pod启动失败")
    else:
        print("   ❌ Pod配置文件不存在")
    
    # 测试Config
    print("\n3. 测试Config...")
    print(f"   - 服务器地址: {Config.SERVER_URI}")
    print(f"   - ETCD端口: {Config.ETCD_PORT}")
    print(f"   - Pod状态常量: {Config.POD_STATUS_CREATING} -> {Config.POD_STATUS_RUNNING}")
    print(f"   - Node API: {Config.NODE_SPEC_URL}")
    print(f"   - Pod API: {Config.POD_SPEC_URL}")
    
    print("\n=== 测试完成 ===")
    print("✅ 简化的资源类结构已就绪！")
    print("\n结构总览:")
    print("- config.py    # 统一配置（包含状态常量）")
    print("- node.py      # Node资源类（合并配置和逻辑）")
    print("- pod.py       # Pod资源类（合并配置和逻辑）")
    print("- etcd.py      # ETCD客户端")

if __name__ == "__main__":
    test_node_and_pod()
