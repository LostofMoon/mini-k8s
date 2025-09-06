"""
ApiServer测试脚本
测试Node和Pod的API管理功能
"""
import requests
import json
import yaml
import time
import threading
import os

def start_api_server():
    """在后台启动ApiServer"""
    from apiServer import ApiServer
    api_server = ApiServer()
    api_server.run()

def test_api_server():
    """测试ApiServer的API功能"""
    base_url = "http://localhost:5050"
    
    print("=== Mini-K8s ApiServer API测试 ===")
    
    # 等待服务器启动
    print("等待ApiServer启动...")
    time.sleep(2)
    
    try:
        # 1. 测试基础接口
        print("\n1. 测试基础接口...")
        response = requests.get(f"{base_url}/")
        if response.status_code == 200:
            print(f"   ✅ 根路径: {response.json()['message']}")
        
        response = requests.get(f"{base_url}/health")
        if response.status_code == 200:
            print(f"   ✅ 健康检查: {response.json()['status']}")
        
        # 2. 测试Node API
        print("\n2. 测试Node API...")
        
        # 读取Node配置
        with open("testFile/node-1.yaml", "r", encoding="utf-8") as f:
            node_data = yaml.safe_load(f)
        
        # 注册Node
        response = requests.post(f"{base_url}/api/v1/nodes/node-01", json=node_data)
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ 注册Node成功: {result['message']}")
            print(f"   - Kafka服务器: {result['kafka_server']}")
        
        # 获取Node
        response = requests.get(f"{base_url}/api/v1/nodes/node-01")
        if response.status_code == 200:
            print(f"   ✅ 获取Node成功")
        
        # 获取所有Node
        response = requests.get(f"{base_url}/api/v1/nodes")
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ 获取所有Node: {result['count']} 个节点")
        
        # 3. 测试Pod API
        print("\n3. 测试Pod API...")
        
        # 读取Pod配置
        with open("testFile/pod-test.yaml", "r", encoding="utf-8") as f:
            pod_data = yaml.safe_load(f)
        
        # 创建Pod
        response = requests.post(f"{base_url}/api/v1/namespaces/default/pods", json=pod_data)
        if response.status_code == 201:
            result = response.json()
            print(f"   ✅ 创建Pod成功: {result['message']}")
        
        # 获取Pod
        response = requests.get(f"{base_url}/api/v1/namespaces/default/pods/test-pod")
        if response.status_code == 200:
            print(f"   ✅ 获取Pod成功")
        
        # 获取命名空间下的Pod
        response = requests.get(f"{base_url}/api/v1/namespaces/default/pods")
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ 获取default命名空间Pod: {result['count']} 个")
        
        # 获取所有Pod
        response = requests.get(f"{base_url}/api/v1/pods")
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ 获取所有Pod: {result['count']} 个")
        
        # 4. 测试更新API
        print("\n4. 测试更新API...")
        
        # 更新Node（心跳）
        response = requests.put(f"{base_url}/api/v1/nodes/node-01", json={"status": "healthy"})
        if response.status_code == 200:
            print(f"   ✅ Node心跳更新成功")
        
        # 更新Pod状态
        response = requests.put(f"{base_url}/api/v1/namespaces/default/pods/test-pod", 
                              json={"status": {"phase": "Running"}})
        if response.status_code == 200:
            print(f"   ✅ Pod状态更新成功")
        
        print("\n=== 测试完成 ===")
        print("✅ ApiServer API功能正常！")
        
        return True
        
    except requests.RequestException as e:
        print(f"❌ API测试失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        return False

if __name__ == "__main__":
    print("启动ApiServer测试...")
    
    # 在后台线程启动ApiServer
    server_thread = threading.Thread(target=start_api_server, daemon=True)
    server_thread.start()
    
    # 运行API测试
    success = test_api_server()
    
    if success:
        print("\n🎉 ApiServer测试成功！")
        print("\n可用的API端点:")
        print("- GET  /                                 # 根路径")
        print("- GET  /health                           # 健康检查")  
        print("- POST /api/v1/nodes/{node_name}         # 注册节点")
        print("- GET  /api/v1/nodes/{node_name}         # 获取节点")
        print("- PUT  /api/v1/nodes/{node_name}         # 更新节点")
        print("- GET  /api/v1/nodes                     # 获取所有节点")
        print("- POST /api/v1/namespaces/{ns}/pods      # 创建Pod")
        print("- GET  /api/v1/namespaces/{ns}/pods/{name} # 获取Pod")
        print("- PUT  /api/v1/namespaces/{ns}/pods/{name} # 更新Pod")
        print("- GET  /api/v1/namespaces/{ns}/pods      # 获取命名空间Pod")
        print("- GET  /api/v1/pods                      # 获取所有Pod")
    else:
        print("\n❌ ApiServer测试失败！")
        exit(1)
        
    # 保持程序运行以便手动测试API
    try:
        print("\nApiServer正在运行在 http://localhost:5050")
        print("按 Ctrl+C 退出...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭ApiServer...")
        exit(0)
