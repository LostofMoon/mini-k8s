#!/usr/bin/env python3
"""
实际Pod创建与网络管理集成测试
"""

import json
import time
from pod import Pod


def test_real_pod_creation_with_network():
    """测试真实Pod创建并验证网络功能"""
    print("=== 真实Pod创建与网络管理集成测试 ===")
    
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
                    "name": "test-server",
                    "image": "busybox:latest",
                    "command": ["sh", "-c", "echo 'Pod网络测试服务器启动' && echo 'IP: '$(hostname -i) && sleep 60"],
                    "ports": [
                        {
                            "containerPort": 8080,
                            "protocol": "TCP"
                        }
                    ]
                }
            ]
        }
    }
    
    pod = None
    
    try:
        print("\n--- 第1步: 创建Pod实例 ---")
        pod = Pod(pod_config)
        print(f"✓ Pod实例创建成功: {pod.name}")
        print(f"  命名空间: {pod.namespace}")
        print(f"  容器数量: {len(pod.containers)}")
        
        # 检查网络管理器是否正确注入
        assert hasattr(pod, 'network_manager'), "Pod应该有network_manager"
        assert hasattr(pod, 'network_attacher'), "Pod应该有network_attacher"
        print(f"✓ 网络管理器已正确注入")
        
        print(f"\n--- 第2步: 检查网络预分配 ---")
        # 在Pod创建前检查网络状态
        initial_status = pod.get_status()
        print(f"初始状态: {initial_status['status']}")
        print(f"网络配置: {json.dumps(initial_status['network'], indent=2)}")
        
        print(f"\n--- 第3步: 创建实际Pod（跳过API Server） ---")
        # 只创建Docker容器，不调用API Server
        print("创建Docker容器...")
        if pod._create_docker_containers():
            print(f"✓ Docker容器创建成功")
            
            # 检查Pod IP分配
            if pod.subnet_ip:
                print(f"✓ Pod IP已分配: {pod.subnet_ip}")
            else:
                print(f"⚠ Pod IP未分配")
            
            # 显示容器状态
            for i, container in enumerate(pod.containers):
                info = container.get_info()
                print(f"  容器 {i+1}: {info['name']} -> {info['status']}")
            
        else:
            print(f"❌ Docker容器创建失败")
            return
        
        print(f"\n--- 第4步: 验证网络配置 ---")
        # 获取更新后的状态
        updated_status = pod.get_status()
        print(f"Pod状态: {updated_status['status']}")
        print(f"Pod IP: {updated_status['ip']}")
        print(f"容器数量: {updated_status['containers']}")
        print(f"Docker容器数量: {updated_status['docker_containers']}")
        
        # 显示网络配置详情
        network_config = updated_status['network']
        print(f"网络配置详情:")
        print(f"  分配IP: {network_config.get('allocated_ip')}")
        print(f"  实际IP: {network_config.get('subnet_ip')}")
        print(f"  DNS服务器: {network_config.get('dns_servers')}")
        print(f"  网络模式: {network_config.get('network_mode')}")
        
        print(f"\n--- 第5步: 验证Docker容器网络 ---")
        # 检查实际的Docker容器
        if pod.docker_containers:
            print(f"Docker容器数量: {len(pod.docker_containers)}")
            
            for i, docker_container in enumerate(pod.docker_containers):
                try:
                    docker_container.reload()
                    container_info = docker_container.attrs
                    
                    print(f"  容器 {i+1}: {docker_container.name}")
                    print(f"    状态: {docker_container.status}")
                    
                    # 获取网络信息
                    networks = container_info.get('NetworkSettings', {}).get('Networks', {})
                    for network_name, network_info in networks.items():
                        ip = network_info.get('IPAddress', 'N/A')
                        print(f"    网络 {network_name}: {ip}")
                        
                except Exception as e:
                    print(f"    ⚠ 获取容器 {docker_container.name} 信息失败: {e}")
        
        print(f"\n--- 第6步: 验证网络管理器状态 ---")
        network_info = pod.network_manager.get_network_info()
        print(f"网络管理器状态:")
        print(f"  活跃Pod数: {network_info['active_pods']}")
        print(f"  分配IP数: {network_info['allocated_ips']}")
        print(f"  当前Pod映射: {network_info['pod_mappings']}")
        
        print(f"\n🎉 真实Pod创建与网络集成测试成功！")
        
        # 让Pod运行一会儿
        print(f"\n--- 第7步: 监控Pod运行状态 ---")
        for i in range(3):
            time.sleep(2)
            status = pod.get_status()
            print(f"  第{i+1}次检查 - 状态: {status['status']}, IP: {status['ip']}")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print(f"\n--- 清理阶段 ---")
        if pod:
            try:
                # 删除Docker容器和网络配置
                pod._delete_docker_containers()
                print(f"✓ Pod清理完成")
                
                # 验证清理结果
                final_info = pod.network_manager.get_network_info()
                print(f"清理后网络状态:")
                print(f"  活跃Pod数: {final_info['active_pods']}")
                print(f"  剩余分配IP: {final_info['allocated_ips']}")
                
            except Exception as e:
                print(f"⚠ 清理过程出现问题: {e}")


if __name__ == "__main__":
    test_real_pod_creation_with_network()
