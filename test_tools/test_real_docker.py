#!/usr/bin/env python3
"""
测试真实Docker模式下的Container类和Pod类
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from container import Container
from pod import Pod


def test_container_real_docker():
    """测试Container类的真实Docker模式"""
    print("=" * 60)
    print("测试Container类（真实Docker模式）")
    print("=" * 60)
    
    # 容器配置
    container_config = {
        "name": "test-nginx",
        "image": "nginx:alpine",
        "ports": [
            {"containerPort": 80, "protocol": "TCP"}
        ],
        "env": [
            {"name": "NGINX_PORT", "value": "80"}
        ]
    }
    
    try:
        # 创建Container对象
        container = Container(container_config, pod_name="test-pod", namespace="default")
        
        print(f"容器名称: {container.name}")
        print(f"容器镜像: {container.image}")
        print(f"容器完整名称: {container.container_name}")
        print(f"初始状态: {container.status}")
        
        # 测试Docker参数构建
        docker_args = container.build_docker_args()
        print(f"Docker参数: {docker_args}")
        
        # 尝试创建容器
        print("\n尝试创建容器...")
        success = container.create()
        print(f"创建结果: {'成功' if success else '失败'}")
        
        if success:
            # 获取容器状态
            status = container.get_status()
            print(f"容器状态: {status}")
            
            # 获取容器信息
            info = container.get_info()
            print("容器信息:")
            for key, value in info.items():
                if key not in ['env', 'volume_mounts']:  # 跳过冗长的信息
                    print(f"  {key}: {value}")
            
            # 清理容器
            print("\n清理容器...")
            container.delete()
        
        print()
        
    except Exception as e:
        print(f"测试Container时出错: {e}")
        import traceback
        traceback.print_exc()


def test_pod_real_docker():
    """测试Pod类的真实Docker模式"""
    print("=" * 60)
    print("测试Pod类（真实Docker模式）")
    print("=" * 60)
    
    # Pod配置
    pod_config = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "test-pod-real",
            "namespace": "default",
            "labels": {
                "app": "test"
            }
        },
        "spec": {
            "containers": [
                {
                    "name": "nginx-container",
                    "image": "nginx:alpine",
                    "ports": [
                        {"containerPort": 80, "protocol": "TCP"}
                    ],
                    "env": [
                        {"name": "NGINX_PORT", "value": "80"}
                    ]
                }
            ]
        }
    }
    
    try:
        # 创建Pod对象
        pod = Pod(pod_config)
        
        print(f"Pod名称: {pod.name}")
        print(f"Pod命名空间: {pod.namespace}")
        print(f"容器数量: {len(pod.containers)}")
        
        print("\n容器详情:")
        for i, container in enumerate(pod.containers, 1):
            print(f"  容器{i}: {container.name} ({container.image})")
            print(f"    状态: {container.status}")
            print(f"    完整名称: {container.container_name}")
        
        # 尝试创建Pod容器（不向API Server注册）
        print("\n尝试创建Pod容器...")
        success = pod._create_docker_containers()
        print(f"创建结果: {'成功' if success else '失败'}")
        
        if success:
            # 获取Pod状态
            pod_status = pod.get_status()
            print(f"\nPod状态信息:")
            for key, value in pod_status.items():
                if key == "container_statuses":
                    print(f"  {key}:")
                    for status in value:
                        print(f"    - {status['name']}: {status['status']}")
                else:
                    print(f"  {key}: {value}")
            
            # 清理Pod
            print("\n清理Pod...")
            pod._delete_docker_containers()
        
        print()
        
    except Exception as e:
        print(f"测试Pod时出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("真实Docker模式测试")
    print("=" * 60)
    
    try:
        # 测试Container类
        test_container_real_docker()
        
        # 测试Pod类
        test_pod_real_docker()
        
        print("=" * 60)
        print("所有测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
