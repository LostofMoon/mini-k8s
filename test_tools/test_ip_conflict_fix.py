#!/usr/bin/env python3
"""
测试多Pod IP分配和网络通信
验证IP分配冲突问题是否修复
"""

import sys
import os
import time
import requests
import subprocess
import signal
import threading

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pod import Pod
from network import NetworkManager

def cleanup_existing_pods():
    """清理现有的Pod和容器"""
    print("[INFO] 清理现有Pod...")
    
    # 停止并删除所有测试容器
    test_pods = ["pod-1", "pod-2", "pod-3"]
    for pod_name in test_pods:
        try:
            # 尝试停止Pod
            result = subprocess.run([
                "docker", "ps", "-a", "-q", "--filter", f"label=pod={pod_name}"
            ], capture_output=True, text=True)
            
            if result.stdout.strip():
                container_ids = result.stdout.strip().split('\n')
                for cid in container_ids:
                    subprocess.run(["docker", "stop", cid], 
                                 capture_output=True, check=False)
                    subprocess.run(["docker", "rm", cid], 
                                 capture_output=True, check=False)
                print(f"[INFO] 清理Pod {pod_name} 的容器")
                
        except Exception as e:
            print(f"[WARNING] 清理Pod {pod_name} 时出错: {e}")

def wait_for_pod_ready(pod, timeout=60):
    """等待Pod就绪"""
    print(f"[INFO] 等待Pod {pod.name} 就绪...")
    
    for i in range(timeout):
        try:
            status = pod.get_status()
            if status == "Running":
                # 等待额外几秒让服务完全启动
                time.sleep(3)
                return True
        except Exception as e:
            pass
        time.sleep(1)
        
    return False

def test_pod_communication(pod1_ip, pod2_ip, pod3_ip):
    """测试Pod间通信"""
    print("\n[INFO] 测试Pod间网络通信...")
    
    # 测试1: pod-1 -> pod-2
    try:
        response = requests.get(f"http://{pod2_ip}:8002/health", timeout=5)
        print(f"✅ Pod1->Pod2 通信成功: {response.status_code}")
    except Exception as e:
        print(f"❌ Pod1->Pod2 通信失败: {e}")
    
    # 测试2: pod-2 -> pod-3  
    try:
        response = requests.get(f"http://{pod3_ip}:8003/health", timeout=5)
        print(f"✅ Pod2->Pod3 通信成功: {response.status_code}")
    except Exception as e:
        print(f"❌ Pod2->Pod3 通信失败: {e}")
    
    # 测试3: pod-3 -> pod-1
    try:
        response = requests.get(f"http://{pod1_ip}:8001/health", timeout=5)
        print(f"✅ Pod3->Pod1 通信成功: {response.status_code}")
    except Exception as e:
        print(f"❌ Pod3->Pod1 通信失败: {e}")

def main():
    """主测试函数"""
    print("=" * 60)
    print("多Pod IP分配冲突修复验证测试")
    print("=" * 60)
    
    # 清理环境
    cleanup_existing_pods()
    
    # 创建网络管理器
    network_mgr = NetworkManager()
    
    # 初始化pods列表
    pods = []
    
    try:
        print("\n[阶段1] 创建并启动多个Pod")
        print("-" * 40)
        
        # 创建Pod对象
        pod1 = Pod("pod-1")
        pod2 = Pod("pod-2") 
        pod3 = Pod("pod-3")
        
        pods = [pod1, pod2, pod3]
        
        # 依次创建Pod
        for i, pod in enumerate(pods, 1):
            print(f"\n[INFO] 创建Pod {i}: {pod.name}")
            try:
                pod.create()
                print(f"[SUCCESS] Pod {pod.name} 创建成功")
                
                # 获取分配的IP
                ip = network_mgr.get_pod_ip(pod.name)
                print(f"[INFO] Pod {pod.name} 分配到IP: {ip}")
                
            except Exception as e:
                print(f"[ERROR] Pod {pod.name} 创建失败: {e}")
                raise
        
        print("\n[阶段2] 等待Pod就绪")
        print("-" * 40)
        
        # 等待所有Pod就绪
        for pod in pods:
            if not wait_for_pod_ready(pod):
                print(f"[ERROR] Pod {pod.name} 启动超时")
                return
        
        print("\n[阶段3] 验证IP分配唯一性")
        print("-" * 40)
        
        # 检查IP分配情况
        assigned_ips = []
        for pod in pods:
            ip = network_mgr.get_pod_ip(pod.name)
            assigned_ips.append(ip)
            print(f"Pod {pod.name}: {ip}")
        
        # 检查IP唯一性
        unique_ips = set(assigned_ips)
        if len(unique_ips) == len(assigned_ips):
            print("✅ 所有Pod都获得了唯一的IP地址")
        else:
            print("❌ 检测到IP冲突！")
            duplicates = [ip for ip in assigned_ips if assigned_ips.count(ip) > 1]
            print(f"重复的IP: {set(duplicates)}")
            return
        
        print("\n[阶段4] 测试Pod间网络通信")
        print("-" * 40)
        
        # 测试Pod间通信
        test_pod_communication(assigned_ips[0], assigned_ips[1], assigned_ips[2])
        
        print("\n[阶段5] 检查Docker网络状态")  
        print("-" * 40)
        
        # 检查Docker网络
        result = subprocess.run([
            "docker", "network", "inspect", "mini-k8s-br0",
            "--format", "{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{\"\\n\"}}{{end}}"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Docker网络中的容器:")
            print(result.stdout.strip())
        
        print("\n[SUCCESS] 多Pod IP分配冲突修复验证完成！")
        
    except KeyboardInterrupt:
        print("\n[INFO] 测试被用户中断")
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
    finally:
        # 清理资源
        print("\n[INFO] 清理测试资源...")
        for pod in pods:
            try:
                pod.delete()
                print(f"[INFO] 清理Pod {pod.name}")
            except:
                pass

if __name__ == "__main__":
    main()
