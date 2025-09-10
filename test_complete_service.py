#!/usr/bin/env python3
"""
完整的 Service 端点和网络代理测试
"""

import json
from etcd import Etcd
from config import Config

def test_real_service_endpoints():
    """测试实际的Service端点发现"""
    print("=== 实际 Service 端点发现测试 ===")
    
    etcd = Etcd()
    
    # 获取Service和Pod数据
    services_data = etcd.get_prefix(Config.GLOBAL_SERVICES_KEY)
    pods_data = etcd.get_prefix(Config.GLOBAL_PODS_KEY)
    
    print(f"\n📊 找到 {len(services_data)} 个 Service，{len(pods_data)} 个 Pod")
    
    for service in services_data:
        if isinstance(service, dict):
            service_name = service.get('metadata', {}).get('name', 'Unknown')
            service_namespace = service.get('metadata', {}).get('namespace', 'default')
            service_type = service.get('spec', {}).get('type', 'ClusterIP')
            cluster_ip = service.get('spec', {}).get('clusterIP', 'N/A')
            selector = service.get('spec', {}).get('selector', {})
            ports = service.get('spec', {}).get('ports', [])
            
            print(f"\n🔍 Service: {service_namespace}/{service_name}")
            print(f"   类型: {service_type}")
            print(f"   ClusterIP: {cluster_ip}")
            print(f"   Selector: {selector}")
            print(f"   端口配置: {ports}")
            
            # 查找匹配的Pod端点
            matching_endpoints = []
            
            for pod in pods_data:
                if isinstance(pod, dict):
                    pod_labels = pod.get('metadata', {}).get('labels', {})
                    pod_name = pod.get('metadata', {}).get('name', 'Unknown')
                    pod_namespace = pod.get('metadata', {}).get('namespace', 'default')
                    pod_ip = pod.get('ip', 'N/A')  # 直接获取ip字段
                    pod_status = pod.get('status', 'Unknown')
                    pod_node = pod.get('node', 'Unknown')
                    
                    # 检查命名空间和标签匹配
                    if (pod_namespace == service_namespace and 
                        pod_status == 'RUNNING' and
                        all(pod_labels.get(k) == v for k, v in selector.items())):
                        
                        matching_endpoints.append({
                            'name': pod_name,
                            'ip': pod_ip,
                            'node': pod_node
                        })
                        
                        print(f"   ✅ 端点: {pod_name}")
                        print(f"      IP: {pod_ip}")
                        print(f"      节点: {pod_node}")
                        print(f"      标签: {pod_labels}")
            
            print(f"   📊 总计: {len(matching_endpoints)} 个有效端点")
            
            # 生成网络代理规则
            if matching_endpoints and ports:
                print(f"\n🔄 应生成的代理规则:")
                for port in ports:
                    port_num = port.get('port')
                    target_port = port.get('target_port', port_num)
                    protocol = port.get('protocol', 'TCP')
                    
                    print(f"   规则: {cluster_ip}:{port_num} -> {protocol}")
                    for endpoint in matching_endpoints:
                        print(f"     └─ {endpoint['ip']}:{target_port}")
                    
                    if service_type == 'NodePort':
                        node_port = port.get('node_port')
                        if node_port:
                            print(f"   NodePort规则: *:{node_port} -> {protocol}")
                            for endpoint in matching_endpoints:
                                print(f"     └─ {endpoint['ip']}:{target_port}")

def test_kubeproxy_rules():
    """测试KubeProxy规则分发"""
    print(f"\n=== KubeProxy 规则分发测试 ===")
    
    etcd = Etcd()
    
    # 检查是否有KubeProxy规则存储
    try:
        proxy_rules = etcd.get_prefix("/service-proxy-rules/")
        
        if proxy_rules:
            print(f"📋 发现 {len(proxy_rules)} 个代理规则:")
            for i, rule in enumerate(proxy_rules, 1):
                print(f"   规则 {i}: {rule}")
        else:
            print("⚠️  未发现任何代理规则")
            print("   这可能是因为:")
            print("   1. ServiceController 还未处理Service事件")
            print("   2. KubeProxy 还未接收到规则")
            print("   3. 规则存储位置不同")
    except Exception as e:
        print(f"❌ 查看代理规则失败: {e}")

def test_network_connectivity():
    """测试网络连通性建议"""
    print(f"\n=== 网络连通性测试建议 ===")
    
    print("💡 手动测试建议:")
    print("1. ClusterIP Service 测试:")
    print("   # 在集群内某个Pod中执行:")
    print("   curl 10.96.71.85:80")
    print("   # 应该转发到 pod1(10.5.0.12:9090) 或 pod2(10.5.0.11:9090)")
    
    print("\n2. NodePort Service 测试:")
    print("   # 集群内访问:")
    print("   curl 10.96.29.79:80")
    print("   # 外部访问 (如果NodePort是30080):")
    print("   curl <NodeIP>:30080")
    print("   # 应该转发到 pod1(10.5.0.12:8080) 或 pod2(10.5.0.11:8080)")
    
    print("\n3. 直接Pod访问测试:")
    print("   curl 10.5.0.12:8080  # 直接访问pod1")
    print("   curl 10.5.0.11:8080  # 直接访问pod2")
    
    print("\n🔧 KubeProxy 状态检查:")
    print("   检查Node进程日志，确认KubeProxy已启动")
    print("   检查iptables规则是否已生成 (在Linux环境)")

if __name__ == "__main__":
    test_real_service_endpoints()
    test_kubeproxy_rules()
    test_network_connectivity()
