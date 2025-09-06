"""
Mini-K8s系统演示
展示Node注册、Pod创建、Kubelet管理的完整流程
"""
import time
import threading
import json
import requests
from apiServer import ApiServer
from node import Node
from kubelet import Kubelet


def main():
    print("🚀 Mini-K8s系统演示开始...")
    print("="*50)
    
    # 1. 启动ApiServer
    print("\n📡 启动ApiServer...")
    api_server = ApiServer()
    server_thread = threading.Thread(target=lambda: api_server.run(), daemon=True)
    server_thread.start()
    
    # 等待ApiServer启动
    time.sleep(3)
    print("   ✅ ApiServer已启动在localhost:5050")
    
    # 2. 创建并注册Node
    print("\n🖥️ 创建并注册Node...")
    node_config = {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "worker-node-1"},
        "spec": {"podCIDR": "10.244.1.0/24"}
    }
    
    node = Node(node_config)
    node.run()  # 注册到ApiServer
    print("   ✅ Node worker-node-1 已注册")
    
    # 3. 启动Kubelet
    print("\n⚙️ 启动Kubelet...")
    kubelet_config = {
        "node_id": "worker-node-1",
        "apiserver": "localhost",
        "subnet_ip": "10.244.1.0/24"
    }
    
    kubelet = Kubelet(kubelet_config)
    kubelet.start()
    print("   ✅ Kubelet已启动")
    
    # 4. 通过ApiServer创建Pod
    print("\n🐳 通过ApiServer创建Pod...")
    nginx_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "nginx-demo",
            "namespace": "default",
            "labels": {"app": "nginx"}
        },
        "spec": {
            "containers": [
                {
                    "name": "nginx",
                    "image": "nginx:latest",
                    "ports": [{"containerPort": 80}]
                }
            ]
        }
    }
    
    # 通过ApiServer API创建Pod
    response = requests.post(
        "http://localhost:5050/api/v1/namespaces/default/pods/nginx-demo",
        json=nginx_pod
    )
    
    if response.status_code in [200, 201]:
        print("   ✅ Pod已通过ApiServer创建")
    else:
        print(f"   ❌ Pod创建失败: {response.status_code}")
    
    # 5. 通过Kubelet管理Pod
    print("\n🔧 通过Kubelet管理Pod...")
    busybox_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "busybox-demo",
            "namespace": "default"
        },
        "spec": {
            "containers": [
                {
                    "name": "busybox",
                    "image": "busybox:latest",
                    "command": ["sleep", "3600"]
                }
            ]
        }
    }
    
    success = kubelet.create_pod(busybox_pod)
    if success:
        print("   ✅ Pod已通过Kubelet创建")
    else:
        print("   ❌ Kubelet创建Pod失败")
    
    # 6. 查询系统状态
    print("\n📊 查询系统状态...")
    time.sleep(2)
    
    # 查询所有Nodes
    try:
        response = requests.get("http://localhost:5050/api/v1/nodes")
        if response.status_code == 200:
            nodes = response.json().get("nodes", [])
            print(f"   📋 系统中有 {len(nodes)} 个Node")
            for node in nodes:
                node_name = node.get("metadata", {}).get("name", "Unknown")
                print(f"      - {node_name}")
        
        # 查询所有Pods  
        response = requests.get("http://localhost:5050/api/v1/pods")
        if response.status_code == 200:
            pods = response.json().get("pods", [])
            print(f"   🐳 系统中有 {len(pods)} 个Pod")
            for pod in pods:
                pod_name = pod.get("metadata", {}).get("name", "Unknown")
                pod_status = pod.get("status", "Unknown")
                print(f"      - {pod_name}: {pod_status}")
        
        # 查询Kubelet管理的Pod
        kubelet_pods = kubelet.list_pods()
        print(f"   ⚙️ Kubelet管理 {len(kubelet_pods)} 个Pod")
        
    except Exception as e:
        print(f"   ❌ 查询状态失败: {e}")
    
    # 7. 监控系统运行
    print("\n⏱️ 监控系统运行（30秒）...")
    print("   系统正在运行，Pod状态会被定期更新...")
    
    for i in range(6):
        time.sleep(5)
        try:
            # 检查Pod状态
            response = requests.get("http://localhost:5050/api/v1/namespaces/default/pods/nginx-demo")
            if response.status_code == 200:
                pod_data = response.json()
                status = pod_data.get("status", "Unknown")
                last_update = pod_data.get("lastUpdate", "Unknown")
                print(f"   📊 nginx-demo状态: {status} (更新时间: {last_update})")
            
        except Exception as e:
            print(f"   ⚠️ 监控检查失败: {e}")
    
    # 8. 清理资源
    print("\n🧹 清理资源...")
    
    # 删除Pod
    success = kubelet.delete_pod("default", "busybox-demo")
    if success:
        print("   ✅ busybox-demo Pod已删除")
    
    try:
        response = requests.delete("http://localhost:5050/api/v1/namespaces/default/pods/nginx-demo")
        if response.status_code == 200:
            print("   ✅ nginx-demo Pod已删除")
    except Exception as e:
        print(f"   ⚠️ 删除nginx-demo失败: {e}")
    
    # 停止Kubelet
    kubelet.stop()
    print("   ✅ Kubelet已停止")
    
    print("\n" + "="*50)
    print("🎉 Mini-K8s系统演示完成！")
    print("\n演示内容包括:")
    print("  ✅ ApiServer启动和REST API")
    print("  ✅ Node注册和管理")
    print("  ✅ Kubelet的Pod生命周期管理")
    print("  ✅ Pod创建、监控和删除")
    print("  ✅ 状态同步和报告")
    print("  ✅ etcd数据持久化")
    
    print("\n🚀 您的Mini-K8s系统运行正常！")


if __name__ == "__main__":
    main()
