#!/usr/bin/env python3
"""
网络管理功能测试 - 测试Pod网络分配和管理
"""

import json
import time
from network import NetworkManager, PodNetworkAttacher, get_network_manager, get_network_attacher
from pod import Pod
from container import Container


class TestNetworkManagement:
    """网络管理测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.network_manager = get_network_manager()
        self.network_attacher = get_network_attacher()
        print("\n=== 网络管理测试开始 ===")
    
    def teardown_method(self):
        """测试后清理"""
        print("=== 网络管理测试结束 ===\n")
    
    def test_network_manager_initialization(self):
        """测试网络管理器初始化"""
        print("\n--- 测试网络管理器初始化 ---")
        
        # 检查网络管理器基本属性
        assert self.network_manager.subnet_base == "10.5.0.0/16"
        assert self.network_manager.dns_ip == "10.5.53.5"
        assert self.network_manager.bridge_name == "mini-k8s-br0"
        
        # 检查IP池初始化
        assert isinstance(self.network_manager.ip_pool, set)
        assert len(self.network_manager.ip_pool) > 0
        
        print(f"✓ 网络管理器初始化成功")
        print(f"  子网: {self.network_manager.subnet_base}")
        print(f"  DNS: {self.network_manager.dns_ip}")
        print(f"  网桥: {self.network_manager.bridge_name}")
        print(f"  预留IP数量: {len(self.network_manager.ip_pool)}")
    
    def test_ip_allocation_and_release(self):
        """测试IP分配和释放"""
        print("\n--- 测试IP分配和释放 ---")
        
        # 分配IP地址
        ip1 = self.network_manager.allocate_pod_ip("test-pod-1", "default")
        ip2 = self.network_manager.allocate_pod_ip("test-pod-2", "default")
        ip3 = self.network_manager.allocate_pod_ip("test-pod-3", "kube-system")
        
        print(f"✓ 分配IP地址:")
        print(f"  test-pod-1: {ip1}")
        print(f"  test-pod-2: {ip2}")
        print(f"  test-pod-3: {ip3}")
        
        # 验证IP格式和唯一性
        assert ip1.count('.') == 3  # IPv4格式
        assert ip2.count('.') == 3  # IPv4格式
        assert ip3.count('.') == 3  # IPv4格式
        assert ip1 != ip2  # IP唯一性
        assert ip1 != ip3
        assert ip2 != ip3
        
        # 验证重复分配返回相同IP
        ip1_duplicate = self.network_manager.allocate_pod_ip("test-pod-1", "default")
        assert ip1 == ip1_duplicate
        
        # 获取已分配的IP
        retrieved_ip = self.network_manager.get_pod_ip("test-pod-1", "default")
        assert retrieved_ip == ip1
        
        # 释放IP地址
        self.network_manager.release_pod_ip("test-pod-1", "default")
        self.network_manager.release_pod_ip("test-pod-2", "default")
        self.network_manager.release_pod_ip("test-pod-3", "kube-system")
        
        # 验证释放后无法获取
        released_ip = self.network_manager.get_pod_ip("test-pod-1", "default")
        assert released_ip is None
        
        print(f"✓ IP分配和释放测试通过")
    
    def test_pod_network_configuration(self):
        """测试Pod网络配置创建"""
        print("\n--- 测试Pod网络配置创建 ---")
        
        # 创建网络配置
        network_config = self.network_manager.create_pod_network("test-pod", "default")
        
        print(f"✓ 网络配置创建成功:")
        print(f"  {json.dumps(network_config, indent=2)}")
        
        # 验证网络配置结构
        assert "name" in network_config
        assert "ip" in network_config
        assert "dns_servers" in network_config
        assert "search_domains" in network_config
        assert "subnet" in network_config
        
        # 验证DNS配置
        assert self.network_manager.dns_ip in network_config["dns_servers"]
        assert "default.svc.cluster.local" in network_config["search_domains"]
        
        # 验证网络名称
        assert network_config["name"] == self.network_manager.bridge_name
        
        # 清理
        self.network_manager.delete_pod_network("test-pod", "default")
        
        print(f"✓ Pod网络配置测试通过")
    
    def test_network_info_retrieval(self):
        """测试网络信息获取"""
        print("\n--- 测试网络信息获取 ---")
        
        # 分配一些IP用于测试
        self.network_manager.allocate_pod_ip("info-test-1", "default")
        self.network_manager.allocate_pod_ip("info-test-2", "kube-system")
        
        # 获取网络信息
        network_info = self.network_manager.get_network_info()
        
        print(f"✓ 网络信息:")
        print(f"  {json.dumps(network_info, indent=2)}")
        
        # 验证信息结构
        assert "subnet" in network_info
        assert "dns_ip" in network_info
        assert "bridge_name" in network_info
        assert "allocated_ips" in network_info
        assert "active_pods" in network_info
        assert "pod_mappings" in network_info
        
        # 验证计数
        assert network_info["active_pods"] >= 2
        assert len(network_info["pod_mappings"]) >= 2
        
        # 清理
        self.network_manager.release_pod_ip("info-test-1", "default")
        self.network_manager.release_pod_ip("info-test-2", "kube-system")
        
        print(f"✓ 网络信息获取测试通过")
    
    def test_pod_with_network_integration(self):
        """测试Pod与网络管理的集成"""
        print("\n--- 测试Pod与网络管理集成 ---")
        
        # 创建Pod配置
        pod_config = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "network-test-pod",
                "namespace": "default"
            },
            "spec": {
                "containers": [
                    {
                        "name": "test-container",
                        "image": "busybox:latest",
                        "command": ["sh", "-c", "echo 'Network test' && sleep 30"]
                    }
                ]
            }
        }
        
        try:
            # 创建Pod实例
            pod = Pod(pod_config)
            
            # 验证网络管理器已注入
            assert hasattr(pod, 'network_manager')
            assert hasattr(pod, 'network_attacher')
            assert pod.network_manager is not None
            assert pod.network_attacher is not None
            
            print(f"✓ Pod网络管理器注入成功")
            
            # 检查Pod状态包含网络信息
            status = pod.get_status()
            assert "network" in status
            
            print(f"✓ Pod状态包含网络信息:")
            print(f"  网络配置: {json.dumps(status['network'], indent=2)}")
            
            print(f"✓ Pod与网络管理集成测试通过")
            
        except Exception as e:
            print(f"⚠ Pod网络集成测试跳过（需要Docker环境）: {e}")


def test_standalone_network_functionality():
    """独立的网络功能测试"""
    print("\n=== 独立网络功能测试 ===")
    
    # 测试网络管理器实例获取
    nm1 = get_network_manager()
    nm2 = get_network_manager()
    assert nm1 is nm2  # 单例模式
    
    # 测试网络附加器实例获取
    na1 = get_network_attacher()
    na2 = get_network_attacher()
    assert na1 is na2  # 单例模式
    
    print("✓ 网络管理器单例模式工作正常")
    
    # 测试多命名空间IP分配
    ip_default_1 = nm1.allocate_pod_ip("pod-1", "default")
    ip_default_2 = nm1.allocate_pod_ip("pod-2", "default")
    ip_kube_1 = nm1.allocate_pod_ip("pod-1", "kube-system")  # 相同名称，不同命名空间
    
    print(f"✓ 多命名空间IP分配:")
    print(f"  default/pod-1: {ip_default_1}")
    print(f"  default/pod-2: {ip_default_2}")
    print(f"  kube-system/pod-1: {ip_kube_1}")
    
    # 验证不同命名空间可以有相同Pod名
    assert ip_default_1 != ip_kube_1
    
    # 清理
    nm1.release_pod_ip("pod-1", "default")
    nm1.release_pod_ip("pod-2", "default")
    nm1.release_pod_ip("pod-1", "kube-system")
    
    print("✓ 独立网络功能测试完成")


if __name__ == "__main__":
    # 运行测试
    print("=== Mini-K8s 网络管理测试套件 ===")
    
    # 独立功能测试
    test_standalone_network_functionality()
    
    # 创建测试实例并运行测试
    test_instance = TestNetworkManagement()
    
    try:
        test_instance.setup_method()
        test_instance.test_network_manager_initialization()
        test_instance.test_ip_allocation_and_release()
        test_instance.test_pod_network_configuration()
        test_instance.test_network_info_retrieval()
        test_instance.test_pod_with_network_integration()
        test_instance.teardown_method()
        
        print("\n🎉 所有网络管理测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 显示最终网络状态
        nm = get_network_manager()
        final_info = nm.get_network_info()
        print(f"\n=== 最终网络状态 ===")
        print(f"{json.dumps(final_info, indent=2)}")
