#!/usr/bin/env python3
"""
测试Container类和重构后的Pod类
"""

import yaml
import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from container import Container
from pod import Pod


def test_container_creation():
    """测试Container类的创建和基本操作"""
    print("=" * 60)
    print("测试Container类")
    print("=" * 60)
    
    # 容器配置
    container_config = {
        "name": "test-container",
        "image": "nginx:latest",
        "command": ["nginx", "-g", "daemon off;"],
        "ports": [
            {"containerPort": 80, "protocol": "TCP"}
        ],
        "env": [
            {"name": "ENV_VAR", "value": "test_value"}
        ]
    }
    
    # 创建Container对象
    container = Container(container_config, pod_name="test-pod", namespace="default")
    
    print(f"容器名称: {container.name}")
    print(f"容器镜像: {container.image}")
    print(f"容器完整名称: {container.container_name}")
    print(f"初始状态: {container.status}")
    
    # 测试Docker参数构建
    docker_args = container.build_docker_args()
    print(f"Docker参数: {docker_args}")
    
    # 获取容器信息
    info = container.get_info()
    print("容器信息:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    
    print()


def test_pod_with_containers():
    """测试使用Container对象的Pod类"""
    print("=" * 60)
    print("测试Pod类（使用Container对象）")
    print("=" * 60)
    
    # Pod配置
    pod_config = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "test-pod",
            "namespace": "default",
            "labels": {
                "app": "test"
            }
        },
        "spec": {
            "containers": [
                {
                    "name": "nginx-container",
                    "image": "nginx:latest",
                    "ports": [
                        {"containerPort": 80, "protocol": "TCP"}
                    ],
                    "env": [
                        {"name": "NGINX_PORT", "value": "80"}
                    ]
                },
                {
                    "name": "sidecar-container",
                    "image": "busybox:latest",
                    "command": ["sh", "-c"],
                    "args": ["while true; do echo 'Sidecar running'; sleep 30; done"]
                }
            ],
            "volumes": [
                {
                    "name": "test-volume",
                    "hostPath": {
                        "path": "/tmp/test-data",
                        "type": "DirectoryOrCreate"
                    }
                }
            ]
        }
    }
    
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
    
    print()


def test_yaml_pod_loading():
    """测试从YAML文件加载Pod配置"""
    print("=" * 60)
    print("测试从YAML文件加载Pod")
    print("=" * 60)
    
    # 检查测试文件是否存在
    test_yaml_path = "./testFile/pod-1.yaml"
    if not os.path.exists(test_yaml_path):
        print(f"测试文件 {test_yaml_path} 不存在，跳过YAML测试")
        return
    
    try:
        # 加载YAML文件
        with open(test_yaml_path, 'r', encoding='utf-8') as f:
            pod_config = yaml.safe_load(f)
        
        print(f"从文件加载配置: {test_yaml_path}")
        
        # 创建Pod对象
        pod = Pod(pod_config)
        
        print(f"Pod名称: {pod.name}")
        print(f"Pod命名空间: {pod.namespace}")
        print(f"容器数量: {len(pod.containers)}")
        
        print("\n容器详情:")
        for i, container in enumerate(pod.containers, 1):
            print(f"  容器{i}: {container.name} ({container.image})")
            if container.command:
                print(f"    命令: {container.command}")
            if container.args:
                print(f"    参数: {container.args}")
            if container.ports:
                print(f"    端口: {container.ports}")
    
    except Exception as e:
        print(f"加载YAML文件时出错: {e}")
    
    print()


if __name__ == "__main__":
    print("Container类和Pod类重构测试")
    print("=" * 60)
    
    try:
        # 测试Container类
        test_container_creation()
        
        # 测试Pod类
        test_pod_with_containers()
        
        # 测试YAML加载
        test_yaml_pod_loading()
        
        print("=" * 60)
        print("所有测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
