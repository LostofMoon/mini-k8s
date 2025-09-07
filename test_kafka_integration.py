#!/usr/bin/env python3
"""
测试Kafka集成的完整Mini-K8s Pod提交流程
"""

import subprocess
import time
import os
import signal
import sys
from threading import Thread

def start_component(cmd, name, log_file=None):
    """启动组件"""
    try:
        print(f"[INFO]Starting {name}...")
        if log_file:
            with open(log_file, "w") as f:
                process = subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT)
        else:
            process = subprocess.Popen(cmd, shell=True)
        
        time.sleep(2)  # 等待启动
        
        if process.poll() is None:
            print(f"[INFO]{name} started successfully (PID: {process.pid})")
            return process
        else:
            print(f"[ERROR]{name} failed to start")
            return None
    except Exception as e:
        print(f"[ERROR]Failed to start {name}: {e}")
        return None

def test_kafka_integration():
    """测试Kafka集成的完整流程"""
    
    processes = []
    
    try:
        print("[INFO]===== Testing Mini-K8s with Kafka Integration =====")
        
        # 1. 启动Kafka（如果还没有运行）
        print("\n[INFO]Step 1: Starting Kafka...")
        kafka_process = start_component("python start_kafka.py start", "Kafka")
        if kafka_process:
            processes.append(kafka_process)
        
        print("[INFO]Waiting for Kafka to be ready...")
        time.sleep(15)
        
        # 2. 启动ApiServer
        print("\n[INFO]Step 2: Starting ApiServer...")
        api_cmd = "conda activate k8s && python apiServer.py"
        api_process = start_component(api_cmd, "ApiServer", "logs/apiserver.log")
        if api_process:
            processes.append(api_process)
        
        time.sleep(3)
        
        # 3. 启动Scheduler（带Kafka支持）
        print("\n[INFO]Step 3: Starting Scheduler with Kafka...")
        scheduler_cmd = "conda activate k8s && python scheduler.py --apiserver localhost --interval 3 --kafka localhost:9092"
        scheduler_process = start_component(scheduler_cmd, "Scheduler", "logs/scheduler.log")
        if scheduler_process:
            processes.append(scheduler_process)
        
        time.sleep(3)
        
        # 4. 启动Node（带Kafka支持）
        print("\n[INFO]Step 4: Starting Node with Kafka...")
        node_cmd = "conda activate k8s && python node.py --config testFile/node-1.yaml --kafka localhost:9092"
        node_process = start_component(node_cmd, "Node-1", "logs/node-1.log")
        if node_process:
            processes.append(node_process)
        
        time.sleep(5)
        
        # 5. 提交Pod
        print("\n[INFO]Step 5: Submitting Pod...")
        submit_cmd = "conda activate k8s && python submit_pod.py --config testFile/pod-1.yaml --wait"
        
        print("[INFO]Running Pod submission...")
        result = subprocess.run(submit_cmd, shell=True, capture_output=True, text=True)
        
        print(f"[INFO]Pod submission result: {result.returncode}")
        if result.stdout:
            print(f"[INFO]Output: {result.stdout}")
        if result.stderr:
            print(f"[WARN]Stderr: {result.stderr}")
        
        # 6. 等待Pod创建
        print("\n[INFO]Step 6: Waiting for Pod creation...")
        time.sleep(10)
        
        # 7. 检查Pod状态
        print("\n[INFO]Step 7: Checking Pod status...")
        kubectl_cmd = "python kubectl.py get pods"
        result = subprocess.run(kubectl_cmd, shell=True, capture_output=True, text=True)
        
        print("[INFO]Pod Status:")
        print(result.stdout)
        
        # 8. 检查Docker容器
        print("\n[INFO]Step 8: Checking Docker containers...")
        docker_cmd = "docker ps --filter name=pod-1"
        result = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True)
        
        print("[INFO]Docker Containers:")
        print(result.stdout)
        
        # 9. 等待观察
        print("\n[INFO]Step 9: Monitoring for 30 seconds...")
        print("[INFO]Check logs in the logs/ directory for detailed information")
        time.sleep(30)
        
        print("\n[INFO]===== Test Complete =====")
        
    except KeyboardInterrupt:
        print("\n[INFO]Test interrupted by user")
    except Exception as e:
        print(f"\n[ERROR]Test failed: {e}")
    finally:
        # 清理进程
        print("\n[INFO]Cleaning up processes...")
        for process in processes:
            try:
                if process and process.poll() is None:
                    process.terminate()
                    time.sleep(2)
                    if process.poll() is None:
                        process.kill()
                    print(f"[INFO]Process {process.pid} terminated")
            except Exception as e:
                print(f"[WARN]Error terminating process: {e}")
        
        print("[INFO]Test cleanup complete")

if __name__ == "__main__":
    # 创建日志目录
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    test_kafka_integration()
