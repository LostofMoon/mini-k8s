#!/usr/bin/env python3
"""
简化的IP分配冲突测试
直接测试NetworkManager的IP分配功能
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from network import NetworkManager

def test_ip_allocation():
    """测试IP分配功能"""
    print("=" * 50)
    print("IP分配冲突修复验证测试")
    print("=" * 50)
    
    # 创建网络管理器实例
    network_mgr = NetworkManager()
    
    print("\n[阶段1] 连续分配多个IP地址")
    print("-" * 30)
    
    # 测试连续分配IP
    test_pods = ["test-pod-1", "test-pod-2", "test-pod-3", "test-pod-4", "test-pod-5"]
    allocated_ips = []
    
    for pod_name in test_pods:
        try:
            ip = network_mgr.allocate_pod_ip(pod_name)
            allocated_ips.append(ip)
            print(f"Pod {pod_name}: {ip}")
        except Exception as e:
            print(f"❌ 为Pod {pod_name} 分配IP失败: {e}")
            return False
    
    print(f"\n已分配IP: {allocated_ips}")
    
    print("\n[阶段2] 检查IP唯一性")
    print("-" * 30)
    
    # 检查IP唯一性
    unique_ips = set(allocated_ips)
    if len(unique_ips) == len(allocated_ips):
        print("✅ 所有IP都是唯一的")
        print(f"分配了 {len(allocated_ips)} 个唯一IP地址")
    else:
        print("❌ 检测到IP冲突！")
        duplicates = [ip for ip in allocated_ips if allocated_ips.count(ip) > 1]
        print(f"重复的IP: {set(duplicates)}")
        return False
    
    print("\n[阶段3] 测试IP释放和重新分配")
    print("-" * 30)
    
    # 释放第一个Pod的IP
    first_pod = test_pods[0]
    first_ip = allocated_ips[0]
    network_mgr.release_pod_ip(first_pod)
    print(f"释放Pod {first_pod} 的IP: {first_ip}")
    
    # 为新Pod分配IP，应该复用刚释放的IP
    new_pod = "test-pod-new"
    new_ip = network_mgr.allocate_pod_ip(new_pod)
    print(f"新Pod {new_pod}: {new_ip}")
    
    if new_ip == first_ip:
        print("✅ IP复用成功")
    else:
        print(f"ℹ️ 分配了新IP（这也是正常的）: {new_ip}")
    
    print("\n[阶段4] 查看网络管理器状态")
    print("-" * 30)
    
    print(f"IP池大小: {len(network_mgr.ip_pool)}")
    print(f"Pod-IP映射数量: {len(network_mgr.pod_ip_mapping)}")
    print("当前Pod-IP映射:")
    for pod_key, ip in network_mgr.pod_ip_mapping.items():
        print(f"  {pod_key}: {ip}")
    
    print("\n✅ IP分配冲突修复验证成功！")
    return True

def test_network_manager_singleton():
    """测试NetworkManager单例模式"""
    print("\n[阶段5] 测试NetworkManager单例模式")
    print("-" * 30)
    
    # 创建多个NetworkManager实例
    mgr1 = NetworkManager()
    mgr2 = NetworkManager()
    
    if mgr1 is mgr2:
        print("✅ NetworkManager单例模式工作正常")
    else:
        print("❌ NetworkManager单例模式失效！")
        return False
    
    # 在一个实例中分配IP
    ip1 = mgr1.allocate_pod_ip("singleton-test-1")
    print(f"实例1分配IP: singleton-test-1 -> {ip1}")
    
    # 在另一个实例中查看
    ip2 = mgr2.get_pod_ip("singleton-test-1") 
    print(f"实例2查看IP: singleton-test-1 -> {ip2}")
    
    if ip1 == ip2:
        print("✅ 单例状态共享正常")
    else:
        print("❌ 单例状态共享失败！")
        return False
    
    return True

def main():
    """主测试函数"""
    try:
        if not test_ip_allocation():
            return
            
        if not test_network_manager_singleton():
            return
            
        print("\n" + "=" * 50)
        print("🎉 所有测试通过！IP分配冲突问题已修复！")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ 测试过程中出现异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
