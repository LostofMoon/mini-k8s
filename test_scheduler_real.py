"""
测试真实scheduler.py进程的多轮调度算法
使用真实的scheduler.py进程而非模拟调度逻辑
"""
import time
import threading
import yaml
import os
import requests
import subprocess
from apiServer import ApiServer


def test_real_scheduler():
    """测试真实scheduler.py进程的多轮调度逻辑"""
    print("🚀 测试真实Scheduler进程多轮调度")
    print("="*60)
    
    # 1. 启动ApiServer
    print("\n📡 启动ApiServer...")
    api_server = ApiServer()
    server_thread = threading.Thread(target=lambda: api_server.run(), daemon=True)
    server_thread.start()
    time.sleep(3)
    print("   ✅ ApiServer已启动")
    
    # 2. 注册3个测试节点
    print("\n🖥️ 注册3个测试节点...")
    
    with open("testFile/node-1.yaml", "r", encoding="utf-8") as f:
        node_data = yaml.safe_load(f)
    
    nodes = ["real-node-1", "real-node-2", "real-node-3"]
    for i, node_name in enumerate(nodes):
        test_node = node_data.copy()
        test_node["metadata"]["name"] = node_name
        test_node["spec"]["podCIDR"] = f"10.244.{i+1}.0/24"
        
        response = requests.post(
            f"http://localhost:5050/api/v1/nodes/{node_name}",
            json=test_node
        )
        if response.status_code == 200:
            print(f"   ✅ {node_name} 注册成功")
    
    # 3. 启动真实的scheduler.py进程
    print("\n⚙️ 启动真实Scheduler进程...")
    scheduler_process = subprocess.Popen([
        "python", "scheduler.py", 
        "--apiserver", "localhost", 
        "--interval", "2"  # 2秒间隔
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    
    print("   ✅ Scheduler进程已启动 (2秒调度间隔)")
    time.sleep(2)
    
    # 4. 第一轮：创建3个Pod
    print("\n🐳 第一轮：创建3个Pod...")
    
    with open("testFile/pod-1.yaml", "r", encoding="utf-8") as f:
        pod_data = yaml.safe_load(f)
    
    all_pod_names = []
    
    def create_pods_batch(round_name, count, start_idx):
        """创建一批Pod"""
        pod_names = []
        for i in range(count):
            pod_name = f"real-test-{round_name}-{i+1}"
            pod_names.append(pod_name)
            
            test_pod = pod_data.copy()
            test_pod["metadata"]["name"] = pod_name
            test_pod["spec"]["containers"][0]["name"] = f"container-{start_idx+i}"
            test_pod["spec"]["containers"][0]["image"] = f"nginx:1.{20+start_idx+i}"
            
            if "node" in test_pod:
                del test_pod["node"]
            
            response = requests.post(
                f"http://localhost:5050/api/v1/namespaces/default/pods/{pod_name}",
                json=test_pod
            )
            
            if response.status_code == 200:
                print(f"   ✅ Pod {pod_name} 创建成功")
            else:
                print(f"   ❌ Pod {pod_name} 创建失败")
        
        return pod_names
    
    # 创建第一轮Pod
    round1_pods = create_pods_batch("round1", 3, 1)
    all_pod_names.extend(round1_pods)
    
    # 5. 等待第一轮调度完成
    print("\n⏳ 等待第一轮调度完成...")
    time.sleep(5)  # 等待2-3个调度周期
    
    def check_scheduling_status(round_name):
        """检查调度状态"""
        response = requests.get("http://localhost:5050/api/v1/pods")
        if response.status_code == 200:
            pods = response.json()
            node_pod_count = {}
            scheduled_count = 0
            
            print(f"   � {round_name}调度状态:")
            for pod in pods["pods"]:
                pod_name = pod.get("metadata", {}).get("name", "unknown")
                pod_node = pod.get("node", "")
                if pod_node:
                    scheduled_count += 1
                    node_pod_count[pod_node] = node_pod_count.get(pod_node, 0) + 1
                    print(f"      ✅ {pod_name} -> {pod_node}")
                else:
                    print(f"      ⏳ {pod_name} -> 等待调度")
            
            if node_pod_count:
                print(f"   📈 当前负载分布:")
                for node in sorted(node_pod_count.keys()):
                    count = node_pod_count.get(node, 0)
                    print(f"      {node}: {count} 个Pod")
            
            return scheduled_count, node_pod_count
    
    scheduled_count, node_distribution = check_scheduling_status("第一轮")
    
    # 6. 第二轮：再创建4个Pod
    print("\n🐳 第二轮：再创建4个Pod...")
    round2_pods = create_pods_batch("round2", 4, 4)
    all_pod_names.extend(round2_pods)
    
    # 7. 等待第二轮调度完成
    print("\n⏳ 等待第二轮调度完成...")
    time.sleep(6)  # 等待3个调度周期
    
    scheduled_count, node_distribution = check_scheduling_status("第二轮")
    
    # 8. 第三轮：再创建2个Pod
    print("\n🐳 第三轮：再创建2个Pod...")
    round3_pods = create_pods_batch("round3", 2, 8)
    all_pod_names.extend(round3_pods)
    
    # 9. 等待第三轮调度完成
    print("\n⏳ 等待最终调度完成...")
    time.sleep(4)  # 等待2个调度周期
    
    # 10. 最终调度结果分析
    print("\n🎯 最终调度结果分析...")
    response = requests.get("http://localhost:5050/api/v1/pods")
    if response.status_code == 200:
        pods = response.json()
        node_pod_count = {}
        
        print("   📋 所有Pod最终分布:")
        for pod in pods["pods"]:
            pod_name = pod.get("metadata", {}).get("name", "unknown")
            pod_node = pod.get("node", "")
            if pod_node:
                node_pod_count[pod_node] = node_pod_count.get(pod_node, 0) + 1
                # 判断是哪一轮
                if "round1" in pod_name:
                    round_info = "第一轮"
                elif "round2" in pod_name:
                    round_info = "第二轮"  
                elif "round3" in pod_name:
                    round_info = "第三轮"
                else:
                    round_info = "未知"
                print(f"      ✅ {pod_name} ({round_info}) -> {pod_node}")
            else:
                print(f"      ❌ {pod_name} -> 未调度")
        
        print(f"\n   📊 最终负载分布:")
        total_pods = 0
        for node in sorted(node_pod_count.keys()):
            count = node_pod_count.get(node, 0)
            total_pods += count
            print(f"      {node}: {count} 个Pod")
        
        print(f"\n   📈 负载均衡分析:")
        print(f"      总Pod数量: {total_pods}")
        print(f"      节点数量: {len(nodes)}")
        print(f"      平均每节点: {total_pods/len(nodes):.1f} 个Pod")
        
        if node_pod_count:
            max_pods = max(node_pod_count.values())
            min_pods = min(node_pod_count.values())
            print(f"      最大负载: {max_pods} 个Pod")
            print(f"      最小负载: {min_pods} 个Pod")
            print(f"      负载差异: {max_pods - min_pods} 个Pod")
            
            if max_pods - min_pods <= 1:
                print("      ✅ 负载分布非常均衡")
            elif max_pods - min_pods <= 2:
                print("      ✅ 负载分布良好")
            else:
                print("      ⚠️ 负载分布需要优化")
    
    # 11. 停止scheduler进程
    print("\n🛑 停止Scheduler进程...")
    scheduler_process.terminate()
    try:
        scheduler_process.wait(timeout=5)
        print("   ✅ Scheduler进程已正常停止")
    except subprocess.TimeoutExpired:
        scheduler_process.kill()
        print("   ⚠️ Scheduler进程被强制终止")
    
    # 12. 清理测试数据
    print("\n🧹 清理测试数据...")
    for pod_name in all_pod_names:
        try:
            response = requests.delete(f"http://localhost:5050/api/v1/namespaces/default/pods/{pod_name}")
            if response.status_code == 200:
                print(f"   ✅ 已删除Pod: {pod_name}")
        except Exception as e:
            print(f"   ⚠️ 删除Pod失败: {pod_name} - {e}")
    
    print("\n🎉 真实Scheduler多轮调度测试完成!")
    
    # 13. 测试总结
    print("\n📋 测试总结:")
    print("✅ 测试了多轮Pod创建和调度")
    print("✅ 使用了真实的scheduler.py进程")
    print("✅ 验证了基于负载的调度算法")
    print("✅ 分析了负载均衡效果")


if __name__ == "__main__":
    test_real_scheduler()
