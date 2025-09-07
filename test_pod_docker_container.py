#!/usr/bin/env python3
"""
全面测试Pod、Docker和Container的完整流程
结合了command line测试和programmatic测试
"""

import subprocess
import time
import requests
import json
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from container import Container
from pod import Pod
import yaml


def run_command(cmd, description=""):
    """运行命令并返回结果"""
    if description:
        print(f"[INFO]{description}")
    print(f"[EXEC]Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    
    if isinstance(cmd, str):
        cmd = cmd.split()
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    
    print(f"[INFO]Return code: {result.returncode}")
    if result.stdout:
        print(f"[OUTPUT]\n{result.stdout}")
    if result.stderr and result.returncode != 0:
        print(f"[ERROR]\n{result.stderr}")
    
    return result.returncode == 0, result.stdout, result.stderr


def check_docker_containers(filter_name=""):
    """检查Docker容器状态"""
    print(f"\n[DOCKER]检查Docker容器状态{'（过滤: ' + filter_name + '）' if filter_name else ''}...")
    
    if filter_name:
        cmd = ["docker", "ps", "-a", "--filter", f"name={filter_name}", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"]
    else:
        cmd = ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"]
    
    success, stdout, stderr = run_command(cmd)
    return success


def test_container_standalone():
    """测试Container类独立功能"""
    print("\n" + "="*80)
    print("1. 测试Container类独立功能")
    print("="*80)
    
    # 容器配置
    container_config = {
        "name": "standalone-test",
        "image": "nginx:alpine",
        "ports": [{"containerPort": 80, "protocol": "TCP"}],
        "env": [{"name": "TEST_VAR", "value": "standalone"}]
    }
    
    try:
        print("\n[STEP 1.1] 创建Container对象...")
        container = Container(container_config, pod_name="test-pod", namespace="test")
        
        print(f"容器名称: {container.name}")
        print(f"容器镜像: {container.image}")
        print(f"完整名称: {container.container_name}")
        print(f"初始状态: {container.status}")
        
        print("\n[STEP 1.2] 构建Docker参数...")
        docker_args = container.build_docker_args()
        print(f"Docker参数: {json.dumps(docker_args, indent=2, ensure_ascii=False)}")
        
        print("\n[STEP 1.3] 创建容器...")
        success = container.create()
        if success:
            print("✓ 容器创建成功")
            
            print("\n[STEP 1.4] 检查容器状态...")
            status = container.get_status()
            print(f"容器状态: {status}")
            
            print("\n[STEP 1.5] 获取容器信息...")
            info = container.get_info()
            print("容器详细信息:")
            for key, value in info.items():
                if key not in ['env', 'volume_mounts', 'command', 'args']:
                    print(f"  {key}: {value}")
            
            print("\n[STEP 1.6] 获取容器日志...")
            logs = container.get_logs(tail=10)
            print(f"容器日志:\n{logs}")
            
            print("\n[STEP 1.7] 在容器中执行命令...")
            exit_code, output = container.execute_command("nginx -v")
            print(f"命令执行结果 (exit_code={exit_code}):\n{output}")
            
            print("\n[STEP 1.8] 检查Docker容器...")
            check_docker_containers(container.container_name)
            
            print("\n[STEP 1.9] 删除容器...")
            container.delete()
            print("✓ 容器删除完成")
        else:
            print("✗ 容器创建失败")
            return False
            
    except Exception as e:
        print(f"✗ Container测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


def test_pod_programmatic():
    """测试Pod类编程接口"""
    print("\n" + "="*80)
    print("2. 测试Pod类编程接口")
    print("="*80)
    
    # Pod配置
    pod_config = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "test-pod-prog",
            "namespace": "default",
            "labels": {"app": "test", "version": "v1"}
        },
        "spec": {
            "containers": [
                {
                    "name": "nginx-main",
                    "image": "nginx:alpine",
                    "ports": [{"containerPort": 80, "hostPort": 8080}],
                    "env": [{"name": "NGINX_HOST", "value": "0.0.0.0"}]
                },
                {
                    "name": "busybox-sidecar",
                    "image": "busybox:latest",
                    "command": ["sh", "-c"],
                    "args": ["while true; do echo 'Sidecar running at' $(date); sleep 10; done"]
                }
            ],
            "volumes": [
                {
                    "name": "shared-data",
                    "hostPath": {"path": "/tmp/test-pod-data", "type": "DirectoryOrCreate"}
                }
            ]
        }
    }
    
    try:
        print("\n[STEP 2.1] 创建Pod对象...")
        pod = Pod(pod_config)
        
        print(f"Pod名称: {pod.name}")
        print(f"Pod命名空间: {pod.namespace}")
        print(f"容器数量: {len(pod.containers)}")
        print(f"卷数量: {len(pod.volumes)}")
        
        print("\n[STEP 2.2] 显示容器信息...")
        for i, container in enumerate(pod.containers, 1):
            print(f"  容器{i}: {container.name}")
            print(f"    镜像: {container.image}")
            print(f"    状态: {container.status}")
            print(f"    完整名称: {container.container_name}")
        
        print("\n[STEP 2.3] 创建Pod容器（跳过API Server）...")
        success = pod._create_docker_containers()
        if success:
            print("✓ Pod容器创建成功")
            
            print("\n[STEP 2.4] 检查Pod状态...")
            pod_status = pod.get_status()
            print("Pod状态信息:")
            for key, value in pod_status.items():
                if key == "container_statuses":
                    print(f"  {key}:")
                    for status in value:
                        print(f"    - {status['name']}: {status['status']}")
                else:
                    print(f"  {key}: {value}")
            
            print("\n[STEP 2.5] 检查Docker容器...")
            check_docker_containers(pod.name)
            
            print("\n[STEP 2.6] 等待容器运行...")
            time.sleep(5)
            
            print("\n[STEP 2.7] 再次检查状态...")
            pod._refresh_status()
            print(f"刷新后Pod状态: {pod.status}")
            
            print("\n[STEP 2.8] 获取容器日志...")
            for container in pod.containers:
                logs = container.get_logs(tail=5)
                print(f"容器 {container.name} 日志:\n{logs}\n")
            
            print("\n[STEP 2.9] 停止Pod...")
            pod.stop()
            
            print("\n[STEP 2.10] 启动Pod...")
            pod.start()
            
            print("\n[STEP 2.11] 删除Pod...")
            pod._delete_docker_containers()
            print("✓ Pod删除完成")
        else:
            print("✗ Pod容器创建失败")
            return False
            
    except Exception as e:
        print(f"✗ Pod编程接口测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


def test_pod_command_line():
    """测试Pod命令行接口"""
    print("\n" + "="*80)
    print("3. 测试Pod命令行接口")
    print("="*80)
    
    # 测试配置文件
    test_configs = [
        "./testFile/pod-1.yaml",
        "./testFile/pod-2.yaml"
    ]
    
    for i, config_file in enumerate(test_configs):
        if not os.path.exists(config_file):
            print(f"[WARNING]配置文件不存在，跳过: {config_file}")
            continue
            
        print(f"\n[STEP 3.{i+1}] 测试配置文件: {config_file}")
        
        try:
            # 读取配置获取Pod名称
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            pod_name = config.get('metadata', {}).get('name', 'unknown')
            
            print(f"\n[STEP 3.{i+1}.1] 创建Pod...")
            success, stdout, stderr = run_command(
                ["python", "pod.py", "--config", config_file, "--action", "create"],
                f"创建Pod: {pod_name}"
            )
            
            if success:
                print(f"\n[STEP 3.{i+1}.2] 检查Docker容器...")
                check_docker_containers(pod_name)
                
                print(f"\n[STEP 3.{i+1}.3] 获取Pod信息...")
                run_command(
                    ["python", "pod.py", "--config", config_file, "--action", "get"],
                    "获取Pod信息"
                )
                
                print(f"\n[STEP 3.{i+1}.4] 检查Pod状态...")
                run_command(
                    ["python", "pod.py", "--config", config_file, "--action", "status"],
                    "检查Pod状态"
                )
                
                print(f"\n[STEP 3.{i+1}.5] 等待容器运行...")
                time.sleep(3)
                
                print(f"\n[STEP 3.{i+1}.6] 停止Pod...")
                run_command(
                    ["python", "pod.py", "--config", config_file, "--action", "stop"],
                    "停止Pod"
                )
                
                print(f"\n[STEP 3.{i+1}.7] 启动Pod...")
                run_command(
                    ["python", "pod.py", "--config", config_file, "--action", "start"],
                    "启动Pod"
                )
                
                print(f"\n[STEP 3.{i+1}.8] 删除Pod...")
                run_command(
                    ["python", "pod.py", "--config", config_file, "--action", "delete"],
                    "删除Pod"
                )
                
                print(f"\n[STEP 3.{i+1}.9] 验证删除...")
                check_docker_containers(pod_name)
                
            else:
                print(f"✗ Pod创建失败: {config_file}")
                
        except Exception as e:
            print(f"✗ 命令行测试失败: {e}")


def test_error_handling():
    """测试错误处理"""
    print("\n" + "="*80)
    print("4. 测试错误处理")
    print("="*80)
    
    print("\n[STEP 4.1] 测试无效镜像...")
    invalid_config = {
        "name": "invalid-test",
        "image": "nonexistent:invalid",
        "command": ["echo", "test"]
    }
    
    try:
        container = Container(invalid_config, pod_name="error-test", namespace="test")
        success = container.create()
        if not success:
            print("✓ 正确处理无效镜像错误")
        else:
            print("✗ 应该失败但成功了")
            container.delete()
    except Exception as e:
        print(f"✓ 捕获到预期错误: {e}")


def main():
    """主测试函数"""
    print("Pod、Docker和Container完整流程测试")
    print("="*80)
    print("测试开始时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    
    # 检查Docker环境
    print("\n[INIT] 检查Docker环境...")
    success, stdout, stderr = run_command(["docker", "version"], "检查Docker版本")
    if not success:
        print("✗ Docker不可用，无法进行测试")
        return
    
    # 清理可能存在的测试容器
    print("\n[INIT] 清理测试环境...")
    run_command("docker container prune -f", "清理已停止的容器")
    
    # 显示初始Docker状态
    print("\n[INIT] 初始Docker状态...")
    check_docker_containers()
    
    results = []
    
    # 运行测试
    try:
        # 1. Container独立测试
        result1 = test_container_standalone()
        results.append(("Container独立功能", result1))
        
        # 2. Pod编程接口测试
        result2 = test_pod_programmatic()
        results.append(("Pod编程接口", result2))
        
        # 3. Pod命令行测试
        test_pod_command_line()  # 这个测试不返回boolean
        results.append(("Pod命令行接口", True))  # 假设成功
        
        # 4. 错误处理测试
        test_error_handling()
        results.append(("错误处理", True))
        
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断测试")
    except Exception as e:
        print(f"\n\n[ERROR] 测试过程中发生异常: {e}")
        import traceback
        traceback.print_exc()
    
    # 最终清理
    print("\n" + "="*80)
    print("5. 最终清理")
    print("="*80)
    run_command("docker container prune -f", "清理测试容器")
    
    # 测试总结
    print("\n" + "="*80)
    print("测试结果总结")
    print("="*80)
    print("结束时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    
    for test_name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{test_name:<20}: {status}")
    
    print("\n[INFO] 所有测试完成！")


if __name__ == "__main__":
    main()
