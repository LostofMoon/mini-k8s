#!/usr/bin/env python3
"""
实际多Pod创建和通信测试
使用真实的Pod YAML配置测试完整的Pod生命周期
"""

import sys
import os
import time
import requests
import subprocess
import json

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pod import Pod
from network import NetworkManager

def load_pod_config(config_file):
    """加载Pod配置文件"""
    import yaml
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] 加载配置文件失败 {config_file}: {e}")
        return None

def cleanup_existing_pods():
    """清理现有的测试Pod"""
    print("[INFO] 清理现有Pod...")
    
    test_pods = ["pod-1", "pod-2", "pod-3"]
    for pod_name in test_pods:
        try:
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
                print(f"[INFO] 清理Pod {pod_name}")
        except Exception as e:
            print(f"[WARNING] 清理Pod {pod_name} 时出错: {e}")

def wait_for_pod_ready(pod, timeout=60):
    """等待Pod就绪"""
    print(f"[INFO] 等待Pod {pod.name} 就绪...")
    
    for i in range(timeout):
        try:
            status = pod.get_status()
            if status == "Running":
                time.sleep(3)  # 等待服务启动
                return True
        except Exception:
            pass
        time.sleep(1)
        if i % 10 == 0:
            print(f"[INFO] 等待Pod {pod.name}... ({i}s)")
    
    print(f"[ERROR] Pod {pod.name} 启动超时")
    return False

def test_pod_communication(pods_info):
    """测试Pod间通信"""
    print("\n[INFO] 测试Pod间网络通信...")
    
    success_count = 0
    total_tests = 0
    
    for i, (pod_name, pod_ip) in enumerate(pods_info):
        port = 8001 + i
        try:
            response = requests.get(f"http://{pod_ip}:{port}/health", timeout=5)
            if response.status_code == 200:
                print(f"✅ {pod_name} 健康检查成功 ({pod_ip}:{port})")
                success_count += 1
            else:
                print(f"❌ {pod_name} 健康检查失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {pod_name} 连接失败: {e}")
        total_tests += 1
    
    # 测试跨Pod通信
    if len(pods_info) >= 2:
        try:
            pod1_ip = pods_info[0][1]
            pod2_ip = pods_info[1][1]
            
            # 使用curl测试Pod间通信
            result = subprocess.run([
                "docker", "exec", f"pod-1-app-container",
                "curl", "-s", f"http://{pod2_ip}:8002/health"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"✅ Pod1->Pod2 通信成功")
                success_count += 1
            else:
                print(f"❌ Pod1->Pod2 通信失败")
        except Exception as e:
            print(f"❌ Pod间通信测试失败: {e}")
        total_tests += 1
    
    return success_count, total_tests

def main():
    """主测试函数"""
    print("=" * 60)
    print("多Pod创建和通信完整测试")
    print("=" * 60)
    
    # 清理环境
    cleanup_existing_pods()
    
    # 创建网络管理器
    network_mgr = NetworkManager()
    
    pods = []
    pods_info = []
    
    try:
        print("\n[阶段1] 创建并启动多个Pod")
        print("-" * 40)
        
        # 配置文件列表
        pod_configs = [
            "testFile/pod-1.yaml",
            "testFile/pod-2.yaml", 
            "testFile/pod-3.yaml"
        ]
        
        for i, config_file in enumerate(pod_configs, 1):
            print(f"\n[INFO] 创建Pod {i}: {config_file}")
            
            # 检查配置文件是否存在
            if not os.path.exists(config_file):
                print(f"[WARNING] 配置文件不存在: {config_file}, 跳过")
                continue
            
            # 加载配置
            pod_config = load_pod_config(config_file)
            if not pod_config:
                continue
            
            # 创建Pod
            pod = Pod(pod_config)
            pods.append(pod)
            
            try:
                # 创建Pod
                pod.create()
                print(f"[SUCCESS] Pod {pod.name} 创建成功")
                
                # 启动Pod
                pod.start()
                print(f"[SUCCESS] Pod {pod.name} 启动成功")
                
                # 获取IP
                pod_ip = network_mgr.get_pod_ip(pod.name)
                pods_info.append((pod.name, pod_ip))
                print(f"[INFO] Pod {pod.name} IP: {pod_ip}")
                
            except Exception as e:
                print(f"[ERROR] Pod {pod.name} 创建/启动失败: {e}")
                continue
        
        if not pods:
            print("[ERROR] 没有成功创建任何Pod")
            return
        
        print("\n[阶段2] 等待Pod就绪")
        print("-" * 40)
        
        ready_count = 0
        for pod in pods:
            if wait_for_pod_ready(pod):
                ready_count += 1
        
        print(f"[INFO] {ready_count}/{len(pods)} 个Pod就绪")
        
        print("\n[阶段3] 验证IP分配唯一性")
        print("-" * 40)
        
        assigned_ips = [info[1] for info in pods_info]
        unique_ips = set(assigned_ips)
        
        if len(unique_ips) == len(assigned_ips):
            print("✅ 所有Pod都获得了唯一的IP地址")
            for pod_name, pod_ip in pods_info:
                print(f"  {pod_name}: {pod_ip}")
        else:
            print("❌ 检测到IP冲突！")
            duplicates = [ip for ip in assigned_ips if assigned_ips.count(ip) > 1]
            print(f"重复的IP: {set(duplicates)}")
        
        print("\n[阶段4] 测试Pod通信")
        print("-" * 40)
        
        if ready_count > 0:
            success, total = test_pod_communication(pods_info)
            print(f"通信测试结果: {success}/{total} 成功")
        
        print("\n[阶段5] 查看Docker网络状态")
        print("-" * 40)
        
        result = subprocess.run([
            "docker", "network", "inspect", "mini-k8s-br0",
            "--format", "{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{\"\\n\"}}{{end}}"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Docker网络中的容器:")
            print(result.stdout.strip() if result.stdout.strip() else "  (无容器)")
        
        print("\n✅ 多Pod创建和通信测试完成！")
        
    except KeyboardInterrupt:
        print("\n[INFO] 测试被用户中断")
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
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
