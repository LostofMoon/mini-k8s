#!/usr/bin/env python3
"""
测试Pod etcd注册功能的完整脚本
"""
import subprocess
import time
import requests
import json


def run_pod_command(config_file, action, wait_time=0):
    """运行Pod命令"""
    cmd = ["python", "pod.py", "--config", config_file, "--action", action]
    if wait_time > 0:
        cmd.extend(["--wait", str(wait_time)])
    
    print(f"[INFO]Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    print(f"[INFO]Return code: {result.returncode}")
    if result.stdout:
        print(f"[INFO]Output: {result.stdout}")
    if result.stderr:
        print(f"[INFO]Error: {result.stderr}")
    return result.returncode == 0


def get_pods_from_apiserver():
    """从ApiServer获取Pod列表"""
    try:
        response = requests.get("http://localhost:5050/api/v1/pods", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get("pods", [])
        else:
            print(f"[ERROR]Failed to get pods: {response.status_code}")
            return []
    except Exception as e:
        print(f"[ERROR]Failed to get pods: {e}")
        return []


def print_pod_status():
    """打印所有Pod状态"""
    pods = get_pods_from_apiserver()
    print(f"\n[INFO]Current Pod Status ({len(pods)} pods):")
    print("-" * 60)
    print(f"{'Name':<12} {'Namespace':<10} {'Node':<10} {'Status':<10}")
    print("-" * 60)
    
    for pod in pods:
        name = pod.get("metadata", {}).get("name", "N/A")
        namespace = pod.get("metadata", {}).get("namespace", "N/A")
        node = pod.get("node", "N/A")
        status = pod.get("status", {}).get("phase", "N/A")
        print(f"{name:<12} {namespace:<10} {node:<10} {status:<10}")
    
    print("-" * 60)
    return pods


def test_pod_lifecycle():
    """测试Pod完整生命周期"""
    print("=" * 80)
    print("Pod etcd 注册功能测试")
    print("=" * 80)
    
    # 测试配置文件列表
    pod_configs = [
        "./testFile/pod-1.yaml",
        "./testFile/pod-2.yaml", 
        "./testFile/pod-3.yaml"
    ]
    
    print("\n[INFO]Phase 1: 初始状态检查")
    initial_pods = print_pod_status()
    
    print(f"\n[INFO]Phase 2: 注册 {len(pod_configs)} 个Pod")
    for i, config in enumerate(pod_configs):
        print(f"\n[INFO]注册Pod {i+1}: {config}")
        success = run_pod_command(config, "register")
        if success:
            print(f"[INFO]Pod {i+1} 注册成功")
        else:
            print(f"[ERROR]Pod {i+1} 注册失败")
        time.sleep(1)  # 等待1秒
    
    print("\n[INFO]Phase 3: 注册后状态检查")
    after_register_pods = print_pod_status()
    
    print(f"\n[INFO]Phase 4: 测试Pod运行（使用 pod-base.yaml）")
    # 使用一个简单的配置文件测试run动作
    base_config = "./testFile/pod-base.yaml"
    print(f"[INFO]运行Pod: {base_config}")
    success = run_pod_command(base_config, "run", wait_time=3)
    if success:
        print("[INFO]Pod run 测试成功")
    else:
        print("[ERROR]Pod run 测试失败")
    
    print("\n[INFO]Phase 5: 最终状态检查")
    final_pods = print_pod_status()
    
    # 统计结果
    print(f"\n[INFO]测试总结:")
    print(f"初始Pod数量: {len(initial_pods)}")
    print(f"注册后Pod数量: {len(after_register_pods)}")  
    print(f"最终Pod数量: {len(final_pods)}")
    
    # 检查调度分布
    if final_pods:
        node_distribution = {}
        for pod in final_pods:
            node = pod.get("node", "Unscheduled")
            node_distribution[node] = node_distribution.get(node, 0) + 1
        
        print(f"[INFO]节点分布:")
        for node, count in node_distribution.items():
            print(f"  {node}: {count} pods")
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    try:
        test_pod_lifecycle()
    except KeyboardInterrupt:
        print("\n[INFO]测试被用户中断")
    except Exception as e:
        print(f"\n[ERROR]测试失败: {e}")
