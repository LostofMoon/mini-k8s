#!/usr/bin/env python3
"""
Pod间网络通信测试 - 验证Pod之间是否能够相互通信
"""

import time
import json
import subprocess
from pod import Pod
from network import get_network_manager


def test_pod_to_pod_communication():
    """测试Pod之间的网络通信"""
    print("=== Pod间网络通信测试 ===")
    
    # 创建服务端Pod配置
    server_pod_config = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "comm-server-pod",
            "namespace": "default"
        },
        "spec": {
            "containers": [
                {
                    "name": "http-server",
                    "image": "busybox:latest",
                    "command": [
                        "sh", "-c", 
                        "echo 'HTTP服务器启动中...' && "
                        "echo 'Pod IP: '$(hostname -i) && "
                        "while true; do "
                        "  echo -e 'HTTP/1.1 200 OK\\r\\nContent-Length: 13\\r\\n\\r\\nHello from Pod' | nc -l -p 8080; "
                        "done"
                    ],
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
    
    # 创建客户端Pod配置
    client_pod_config = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "comm-client-pod",
            "namespace": "default"
        },
        "spec": {
            "containers": [
                {
                    "name": "http-client",
                    "image": "busybox:latest",
                    "command": [
                        "sh", "-c",
                        "echo 'HTTP客户端启动中...' && "
                        "echo 'Pod IP: '$(hostname -i) && "
                        "sleep 120"  # 保持运行以便测试
                    ]
                }
            ]
        }
    }
    
    server_pod = None
    client_pod = None
    network_manager = get_network_manager()
    
    try:
        print("\n--- 第1步: 创建服务端Pod ---")
        server_pod = Pod(server_pod_config)
        
        if server_pod._create_docker_containers():
            server_status = server_pod.get_status()
            server_ip = server_status['ip']
            print(f"✓ 服务端Pod创建成功")
            print(f"  名称: {server_pod.name}")
            print(f"  IP: {server_ip}")
            print(f"  状态: {server_status['status']}")
        else:
            print("❌ 服务端Pod创建失败")
            return
        
        print("\n--- 第2步: 创建客户端Pod ---")
        client_pod = Pod(client_pod_config)
        
        if client_pod._create_docker_containers():
            client_status = client_pod.get_status()
            client_ip = client_status['ip']
            print(f"✓ 客户端Pod创建成功")
            print(f"  名称: {client_pod.name}")
            print(f"  IP: {client_ip}")
            print(f"  状态: {client_status['status']}")
        else:
            print("❌ 客户端Pod创建失败")
            return
        
        print("\n--- 第3步: 验证网络分配 ---")
        network_info = network_manager.get_network_info()
        print(f"当前网络状态:")
        print(f"  活跃Pod数: {network_info['active_pods']}")
        print(f"  Pod IP映射:")
        for pod_key, ip in network_info['pod_mappings'].items():
            print(f"    {pod_key}: {ip}")
        
        # 等待容器完全启动
        print(f"\n--- 第4步: 等待服务启动 ---")
        print("等待Pod完全启动...")
        time.sleep(5)
        
        print("\n--- 第5步: 测试网络连通性 ---")
        
        # 方法1: 通过Docker网络检查连通性
        print("方法1: Docker网络连通性检查")
        try:
            # 检查两个Pod是否在同一网络
            result = subprocess.run([
                "docker", "network", "inspect", "mini-k8s-br0", 
                "--format", "{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{end}}"
            ], capture_output=True, text=True, check=True)
            
            print(f"网络中的容器:")
            print(f"  {result.stdout}")
            
        except subprocess.CalledProcessError as e:
            print(f"⚠ Docker网络检查失败: {e}")
        
        # 方法2: 从客户端Pod ping服务端Pod
        print(f"\n方法2: Ping连通性测试")
        try:
            # 获取客户端容器
            client_container = None
            for container in client_pod.containers:
                if container.docker_container:
                    client_container = container.docker_container
                    break
            
            if client_container:
                # 执行ping命令
                exec_result = client_container.exec_run(
                    f"ping -c 3 {server_ip}",
                    stdout=True,
                    stderr=True
                )
                
                print(f"Ping结果 (退出码: {exec_result.exit_code}):")
                print(f"输出: {exec_result.output.decode('utf-8')}")
                
                if exec_result.exit_code == 0:
                    print(f"✓ Ping测试成功 - Pod间网络连通")
                else:
                    print(f"❌ Ping测试失败 - Pod间网络不通")
            else:
                print(f"⚠ 未找到客户端容器")
                
        except Exception as e:
            print(f"❌ Ping测试出错: {e}")
        
        # 方法3: HTTP连接测试
        print(f"\n方法3: HTTP连接测试")
        try:
            if client_container:
                # 使用wget测试HTTP连接
                exec_result = client_container.exec_run(
                    f"wget -T 5 -O - http://{server_ip}:8080",
                    stdout=True,
                    stderr=True
                )
                
                print(f"HTTP测试结果 (退出码: {exec_result.exit_code}):")
                print(f"输出: {exec_result.output.decode('utf-8')}")
                
                if exec_result.exit_code == 0:
                    print(f"✓ HTTP测试成功 - Pod间应用层通信正常")
                else:
                    print(f"❌ HTTP测试失败 - Pod间应用层通信异常")
            else:
                print(f"⚠ 未找到客户端容器进行HTTP测试")
                
        except Exception as e:
            print(f"❌ HTTP测试出错: {e}")
        
        # 方法4: 网络路由检查
        print(f"\n方法4: 网络路由检查")
        try:
            if client_container:
                # 检查路由表
                exec_result = client_container.exec_run(
                    "route -n",
                    stdout=True,
                    stderr=True
                )
                
                print(f"客户端路由表:")
                print(f"{exec_result.output.decode('utf-8')}")
                
                # 检查网络接口
                exec_result = client_container.exec_run(
                    "ifconfig",
                    stdout=True,
                    stderr=True
                )
                
                print(f"客户端网络接口:")
                print(f"{exec_result.output.decode('utf-8')}")
                
        except Exception as e:
            print(f"⚠ 路由检查出错: {e}")
        
        # 方法5: 检查iptables规则（如果有权限）
        print(f"\n方法5: 主机网络检查")
        try:
            # 检查主机的Docker网络
            result = subprocess.run([
                "docker", "exec", client_container.id, "nslookup", server_ip
            ], capture_output=True, text=True)
            
            print(f"DNS解析测试:")
            print(f"退出码: {result.returncode}")
            print(f"输出: {result.stdout}")
            if result.stderr:
                print(f"错误: {result.stderr}")
                
        except Exception as e:
            print(f"⚠ DNS解析测试出错: {e}")
        
    except Exception as e:
        print(f"\n❌ 网络通信测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print(f"\n--- 清理阶段 ---")
        
        # 清理Pod
        if server_pod:
            try:
                server_pod._delete_docker_containers()
                print(f"✓ 服务端Pod清理完成")
            except Exception as e:
                print(f"⚠ 服务端Pod清理失败: {e}")
        
        if client_pod:
            try:
                client_pod._delete_docker_containers()
                print(f"✓ 客户端Pod清理完成")
            except Exception as e:
                print(f"⚠ 客户端Pod清理失败: {e}")
        
        # 显示最终网络状态
        try:
            final_info = network_manager.get_network_info()
            print(f"\n最终网络状态:")
            print(f"  活跃Pod数: {final_info['active_pods']}")
            print(f"  剩余分配IP: {final_info['allocated_ips']}")
        except Exception as e:
            print(f"⚠ 获取最终网络状态失败: {e}")


def test_network_isolation():
    """测试网络隔离功能"""
    print("\n=== 网络隔离测试 ===")
    
    network_manager = get_network_manager()
    
    # 测试不同命名空间的网络隔离
    print("--- 测试跨命名空间网络隔离 ---")
    
    try:
        # 在不同命名空间分配IP
        default_ip1 = network_manager.allocate_pod_ip("test-pod", "default")
        default_ip2 = network_manager.allocate_pod_ip("test-pod2", "default")
        kube_system_ip = network_manager.allocate_pod_ip("test-pod", "kube-system")
        
        print(f"IP分配结果:")
        print(f"  default/test-pod: {default_ip1}")
        print(f"  default/test-pod2: {default_ip2}")
        print(f"  kube-system/test-pod: {kube_system_ip}")
        
        # 验证IP不同
        assert default_ip1 != default_ip2, "同命名空间不同Pod应有不同IP"
        assert default_ip1 != kube_system_ip, "不同命名空间相同Pod名应有不同IP"
        
        print(f"✓ 网络隔离正常 - 不同命名空间分配不同IP")
        
        # 清理
        network_manager.release_pod_ip("test-pod", "default")
        network_manager.release_pod_ip("test-pod2", "default")
        network_manager.release_pod_ip("test-pod", "kube-system")
        
    except Exception as e:
        print(f"❌ 网络隔离测试失败: {e}")


if __name__ == "__main__":
    print("=== Mini-K8s Pod间网络通信测试套件 ===")
    
    # 运行网络通信测试
    test_pod_to_pod_communication()
    
    # 运行网络隔离测试
    test_network_isolation()
    
    print("\n=== 测试总结 ===")
    print("Pod间网络通信测试完成")
    print("检查上述输出判断网络连通性是否正常")
