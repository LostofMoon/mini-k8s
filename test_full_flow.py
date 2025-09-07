#!/usr/bin/env python3
"""
Mini-K8s完整集成测试脚本
测试完整的Pod创建流程：用户提交 → ApiServer → 调度器 → Kubelet → 创建Pod
"""

import subprocess
import time
import os
import signal
import sys
import threading
from datetime import datetime

class MiniK8sTestSuite:
    """Mini-K8s测试套件"""
    
    def __init__(self):
        self.processes = {}  # 存储启动的进程
        self.base_dir = os.getcwd()
        
    def start_component(self, name, command, wait_time=3):
        """
        启动组件
        
        Args:
            name: 组件名称
            command: 启动命令
            wait_time: 等待时间
        """
        print(f"[INFO]启动{name}...")
        try:
            # 在Windows上使用shell=True，在Unix上使用shell=False
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            self.processes[name] = process
            
            # 等待组件启动
            time.sleep(wait_time)
            
            # 检查进程是否还在运行
            if process.poll() is None:
                print(f"[SUCCESS]{name}启动成功 (PID: {process.pid})")
                return True
            else:
                print(f"[ERROR]{name}启动失败")
                # 读取错误输出
                try:
                    output = process.stdout.read()
                    if output:
                        print(f"[ERROR]{name}输出: {output}")
                except:
                    pass
                return False
                
        except Exception as e:
            print(f"[ERROR]启动{name}失败: {e}")
            return False
    
    def stop_all_components(self):
        """停止所有组件"""
        print("\n[INFO]停止所有组件...")
        
        for name, process in self.processes.items():
            try:
                if process.poll() is None:  # 进程还在运行
                    print(f"[INFO]停止{name}...")
                    process.terminate()
                    
                    # 等待进程结束
                    try:
                        process.wait(timeout=5)
                        print(f"[SUCCESS]{name}已停止")
                    except subprocess.TimeoutExpired:
                        print(f"[WARNING]{name}未响应，强制结束...")
                        process.kill()
                        process.wait()
                        print(f"[SUCCESS]{name}已强制结束")
                        
            except Exception as e:
                print(f"[ERROR]停止{name}失败: {e}")
    
    def wait_for_apiserver(self, timeout=30):
        """等待ApiServer就绪"""
        print("[INFO]等待ApiServer就绪...")
        
        import requests
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get("http://localhost:5050/api/v1/nodes", timeout=2)
                if response.status_code in [200, 404]:  # 404也表示ApiServer在运行
                    print("[SUCCESS]ApiServer就绪")
                    return True
            except:
                pass
            time.sleep(1)
        
        print("[ERROR]ApiServer启动超时")
        return False
    
    def run_full_test(self):
        """运行完整测试"""
        print(f"\n{'='*80}")
        print(f"Mini-K8s完整集成测试 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        
        try:
            # 1. 启动ApiServer
            if not self.start_component("ApiServer", "conda activate k8s && python apiServer.py", 5):
                return False
            
            # 等待ApiServer就绪
            if not self.wait_for_apiserver():
                return False
            
            # 2. 启动调度器
            if not self.start_component("Scheduler", "conda activate k8s && python scheduler.py --apiserver localhost --interval 3", 3):
                return False
            
            # 3. 启动节点（包含Kubelet）
            node_configs = ["testFile/node-1.yaml", "testFile/node-2.yaml", "testFile/node-3.yaml"]
            for i, config in enumerate(node_configs, 1):
                if os.path.exists(config):
                    if not self.start_component(f"Node-{i}", f"conda activate k8s && python node.py --config {config}", 3):
                        print(f"[WARNING]Node-{i}启动失败，继续测试...")
            
            # 4. 等待系统稳定
            print("\n[INFO]等待系统稳定...")
            time.sleep(5)
            
            # 5. 测试Pod提交流程
            print(f"\n{'='*60}")
            print("测试Pod创建流程")
            print(f"{'='*60}")
            
            # 测试多个Pod
            test_pods = [
                "testFile/pod-1.yaml",
                "testFile/pod-2.yaml", 
                "testFile/pod-3.yaml"
            ]
            
            success_count = 0
            for pod_config in test_pods:
                if os.path.exists(pod_config):
                    print(f"\n[TEST]测试Pod配置: {pod_config}")
                    
                    # 使用submit_pod.py提交Pod
                    cmd = f"conda activate k8s && python submit_pod.py --config {pod_config} --wait --timeout 60"
                    result = os.system(cmd)
                    
                    if result == 0:
                        success_count += 1
                        print(f"[SUCCESS]Pod {pod_config} 创建成功")
                    else:
                        print(f"[ERROR]Pod {pod_config} 创建失败")
                        
                    time.sleep(2)  # 间隔一下
                else:
                    print(f"[WARNING]Pod配置文件不存在: {pod_config}")
            
            # 6. 显示最终状态
            print(f"\n{'='*60}")
            print("最终系统状态")
            print(f"{'='*60}")
            
            print("\n[INFO]当前Pod状态:")
            os.system("conda activate k8s && python kubectl.py get pods")
            
            print(f"\n[INFO]当前Node状态:")
            try:
                import requests
                response = requests.get("http://localhost:5050/api/v1/nodes", timeout=5)
                if response.status_code == 200:
                    nodes_data = response.json()
                    nodes = nodes_data.get("nodes", [])
                    for node in nodes:
                        print(f"  - {node.get('name', 'Unknown')}")
                else:
                    print("  无法获取Node状态")
            except:
                print("  无法连接到ApiServer")
            
            print(f"\n{'='*60}")
            print(f"测试完成 - 成功创建 {success_count}/{len(test_pods)} 个Pod")
            print(f"{'='*60}")
            
            # 7. 等待用户确认清理
            print("\n[INFO]测试完成！按 Ctrl+C 或等待30秒后自动清理...")
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                print("\n[INFO]用户中断，开始清理...")
            
            return True
            
        except KeyboardInterrupt:
            print("\n[INFO]用户中断测试...")
            return False
        except Exception as e:
            print(f"\n[ERROR]测试过程中出现错误: {e}")
            return False
        finally:
            # 清理所有组件
            self.stop_all_components()


def signal_handler(sig, frame):
    """信号处理器"""
    print('\n[INFO]接收到中断信号，正在清理...')
    sys.exit(0)


if __name__ == "__main__":
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 检查必要文件
    required_files = [
        "apiServer.py",
        "scheduler.py", 
        "node.py",
        "submit_pod.py",
        "kubectl.py",
        "testFile/node-1.yaml"
    ]
    
    missing_files = [f for f in required_files if not os.path.exists(f)]
    if missing_files:
        print(f"[ERROR]缺少必要文件: {missing_files}")
        sys.exit(1)
    
    # 运行测试
    test_suite = MiniK8sTestSuite()
    try:
        success = test_suite.run_full_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"[ERROR]测试失败: {e}")
        test_suite.stop_all_components()
        sys.exit(1)
