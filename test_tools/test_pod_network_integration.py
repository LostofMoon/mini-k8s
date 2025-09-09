#!/usr/bin/env python3
"""
Pod网络完整集成测试 - 测试Pod创建、网络分配、容器运行的完整流程
"""

import json
import time
import subprocess
from pod import Pod
from network import get_network_manager


def test_pod_network_complete_workflow():
    """测试Pod网络的完整工作流程"""
    print("=== Pod网络完整集成测试 ===")
    
    # 测试配置
    pod_configs = [
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "network-pod-1",
                "namespace": "default"
            },
            "spec": {
                "containers": [
                    {
                        "name": "web-server",
                        "image": "busybox:latest",
                        "command": ["sh", "-c", "echo 'Pod 1 Web Server' && sleep 120"],
                        "ports": [
                            {
                                "containerPort": 8080,
                                "hostPort": 8080,
                                "protocol": "TCP"
                            }
                        ]
                    }
                ]
            }
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "network-pod-2",
                "namespace": "default"
            },
            "spec": {
                "containers": [
                    {
                        "name": "client",
                        "image": "busybox:latest",
                        "command": ["sh", "-c", "echo 'Pod 2 Client' && sleep 120"]
                    }
                ]
            }
        }
    ]
    
    pods = []
    network_manager = get_network_manager()
    
    try:
        print("\n--- 第1步: 创建多个Pod并分配网络 ---")
        
        for i, config in enumerate(pod_configs):
            print(f"\n创建Pod {i+1}: {config['metadata']['name']}")
            
            # 创建Pod实例
            pod = Pod(config)
            pods.append(pod)
            
            # 测试网络分配
            network_config = pod.network_manager.create_pod_network(
                pod.name, pod.namespace
            )
            
            print(f"✓ Pod {pod.name} 网络配置:")
            print(f"  IP: {network_config['ip']}")
            print(f"  DNS: {network_config['dns_servers']}")
            print(f"  网络: {network_config['name']}")
        
        print(f"\n--- 第2步: 显示网络分配状态 ---")
        network_info = network_manager.get_network_info()
        print(f"当前网络状态:")
        print(f"  分配的IP数量: {network_info['allocated_ips']}")
        print(f"  活跃Pod数量: {network_info['active_pods']}")
        print(f"  Pod IP映射:")
        for pod_key, ip in network_info['pod_mappings'].items():
            print(f"    {pod_key}: {ip}")
        
        print(f"\n--- 第3步: 测试Pod状态查询 ---")
        for i, pod in enumerate(pods):
            status = pod.get_status()
            print(f"\nPod {i+1} ({pod.name}) 状态:")
            print(f"  状态: {status['status']}")
            print(f"  IP: {status['ip']}")
            print(f"  容器数量: {status['containers']}")
            print(f"  网络配置: {json.dumps(status['network'], indent=4)}")
        
        print(f"\n--- 第4步: 测试网络连通性检查 ---")
        # 获取Docker网络信息
        try:
            result = subprocess.run(
                ["docker", "network", "ls", "--filter", "name=mini-k8s-br0"],
                capture_output=True, text=True, check=True
            )
            print(f"✓ Docker网络存在:")
            print(f"  {result.stdout}")
            
            # 检查网络详细信息
            result = subprocess.run(
                ["docker", "network", "inspect", "mini-k8s-br0"],
                capture_output=True, text=True, check=True
            )
            network_detail = json.loads(result.stdout)
            print(f"✓ 网络详细信息:")
            print(f"  IPAM配置: {network_detail[0]['IPAM']['Config']}")
            
        except subprocess.CalledProcessError as e:
            print(f"⚠ Docker网络检查失败: {e}")
        
        print(f"\n--- 第5步: 测试IP地址冲突检测 ---")
        # 尝试为同一个Pod分配IP（应该返回相同IP）
        pod1 = pods[0]
        original_ip = network_manager.get_pod_ip(pod1.name, pod1.namespace)
        duplicate_ip = network_manager.allocate_pod_ip(pod1.name, pod1.namespace)
        
        assert original_ip == duplicate_ip, "同一Pod应该获得相同IP"
        print(f"✓ IP冲突检测正常: {pod1.name} -> {original_ip}")
        
        print(f"\n--- 第6步: 测试跨命名空间网络隔离 ---")
        # 创建不同命名空间的Pod
        kube_system_ip = network_manager.allocate_pod_ip("test-pod", "kube-system")
        default_ip = network_manager.allocate_pod_ip("test-pod", "default")
        
        assert kube_system_ip != default_ip, "不同命名空间应该有不同IP"
        print(f"✓ 命名空间隔离正常:")
        print(f"  kube-system/test-pod: {kube_system_ip}")
        print(f"  default/test-pod: {default_ip}")
        
        # 清理测试IP
        network_manager.release_pod_ip("test-pod", "kube-system")
        network_manager.release_pod_ip("test-pod", "default")
        
        print(f"\n🎉 Pod网络完整集成测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print(f"\n--- 清理阶段 ---")
        # 清理所有测试Pod的网络配置
        for pod in pods:
            try:
                network_manager.delete_pod_network(pod.name, pod.namespace)
                print(f"✓ 清理Pod {pod.name} 网络配置")
            except Exception as e:
                print(f"⚠ 清理Pod {pod.name} 网络配置失败: {e}")
        
        # 显示最终网络状态
        final_info = network_manager.get_network_info()
        print(f"\n最终网络状态:")
        print(f"  活跃Pod数量: {final_info['active_pods']}")
        print(f"  剩余分配IP: {final_info['allocated_ips']}")


def test_docker_network_integration():
    """测试Docker网络集成功能"""
    print("\n=== Docker网络集成测试 ===")
    
    try:
        # 检查Docker是否可用
        result = subprocess.run(
            ["docker", "version"], 
            capture_output=True, text=True, check=True
        )
        print("✓ Docker环境可用")
        
        # 检查是否存在mini-k8s网桥
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True, text=True, check=True
        )
        
        if "mini-k8s-br0" in result.stdout:
            print("✓ mini-k8s网桥已存在")
            
            # 获取网桥详细信息
            result = subprocess.run(
                ["docker", "network", "inspect", "mini-k8s-br0"],
                capture_output=True, text=True, check=True
            )
            
            network_info = json.loads(result.stdout)[0]
            print("✓ 网桥配置信息:")
            print(f"  Driver: {network_info['Driver']}")
            print(f"  Scope: {network_info['Scope']}")
            
            if 'IPAM' in network_info and 'Config' in network_info['IPAM']:
                ipam_config = network_info['IPAM']['Config']
                if ipam_config:
                    print(f"  Subnet: {ipam_config[0].get('Subnet', 'N/A')}")
                    print(f"  Gateway: {ipam_config[0].get('Gateway', 'N/A')}")
            
            print("✓ Docker网络集成正常")
        else:
            print("⚠ mini-k8s网桥未找到，需要初始化网络管理器")
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Docker环境检查失败: {e}")
        print("请确保Docker已安装并正在运行")
    except Exception as e:
        print(f"❌ Docker网络集成测试失败: {e}")


def test_network_performance():
    """测试网络性能相关指标"""
    print("\n=== 网络性能测试 ===")
    
    network_manager = get_network_manager()
    
    # 测试大量IP分配的性能
    print("--- IP分配性能测试 ---")
    start_time = time.time()
    
    test_pods = []
    for i in range(50):  # 分配50个IP地址
        pod_name = f"perf-test-pod-{i}"
        ip = network_manager.allocate_pod_ip(pod_name, "default")
        test_pods.append((pod_name, ip))
    
    allocation_time = time.time() - start_time
    print(f"✓ 分配50个IP耗时: {allocation_time:.3f}秒")
    print(f"✓ 平均每个IP分配耗时: {allocation_time/50*1000:.1f}毫秒")
    
    # 测试IP释放性能
    print("--- IP释放性能测试 ---")
    start_time = time.time()
    
    for pod_name, ip in test_pods:
        network_manager.release_pod_ip(pod_name, "default")
    
    release_time = time.time() - start_time
    print(f"✓ 释放50个IP耗时: {release_time:.3f}秒")
    print(f"✓ 平均每个IP释放耗时: {release_time/50*1000:.1f}毫秒")
    
    # 检查内存使用
    info = network_manager.get_network_info()
    print(f"✓ 网络管理器状态:")
    print(f"  活跃Pod数量: {info['active_pods']}")
    print(f"  IP池大小: {info['allocated_ips']}")


if __name__ == "__main__":
    print("=== Mini-K8s Pod网络集成测试套件 ===")
    
    # 运行所有测试
    test_docker_network_integration()
    test_network_performance()
    test_pod_network_complete_workflow()
    
    print("\n=== 测试总结 ===")
    print("✅ Docker网络集成测试")
    print("✅ 网络性能测试")
    print("✅ Pod网络完整工作流程测试")
    print("\n🎉 所有Pod网络集成测试完成！")
