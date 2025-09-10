## ApiServer
conda activate k8s; python apiServer.py

## Scheduler
<!-- conda activate k8s; python scheduler.py --apiserver localhost --interval 3 -->
conda activate k8s; python scheduler.py --apiserver localhost --interval 3 --kafka localhost:9092

## 注册3个Nodes
conda activate k8s
python node.py --config testFile\node-1.yaml
python node.py --config testFile\node-2.yaml
python node.py --config testFile\node-3.yaml

## 直接用PODs在当前注册3个Pods
python pod.py --config testFile/pod-1.yaml --action create
python pod.py --config testFile/pod-2.yaml --action create
python pod.py --config testFile/pod-3.yaml --action create

conda activate k8s; python submit_pod.py --config testFile/pod-1.yaml --wait
conda activate k8s; python submit_pod.py --config testFile/pod-2.yaml --wait

### NEW（删除是有一定延迟）
python kubectl.py get pods
python kubectl.py apply -f testFile/pod-1.yaml
python kubectl.py apply -f testFile/pod-2.yaml
python kubectl.py apply -f testFile/pod-3.yaml
python kubectl.py apply -f testFile/pod-4.yaml
python kubectl.py delete pod pod4 

### 0. 检查API Server状态
curl http://localhost:5050/api/v1/nodes
curl http://localhost:5050/api/v1/pods

### 1. 确认Pod分布在不同节点
Invoke-WebRequest -Uri "http://localhost:5050/api/v1/pods" -Method GET | Select-Object -ExpandProperty Content | ConvertFrom-Json | Select-Object -ExpandProperty pods | Select-Object @{Name="Name";Expression={$_.metadata.name}}, @{Name="Namespace";Expression={$_.metadata.namespace}}, @{Name="Node";Expression={$_.node}}, @{Name="UID";Expression={$_.metadata.uid}}

### 2. 检查网络配置
docker network inspect mini-k8s-br0

### 3. 验证跨节点通信（pod1在node-01，pod2在node-02）
docker exec default_pod1_pod1-container1 ping -c 3 10.5.0.12
docker exec default_pod1_pod1-container1 ping -c 3 10.5.0.13
docker exec default_pod2_pod2-container1 ping -c 3 10.5.0.11

### 4. 检查路由表
docker exec default_pod1_pod1-container1 ip addr show
docker exec default_pod2_pod2-container1 ip addr show
docker exec default_pod3_pod3-container1 ip addr show

## kafuka
### 0. 关闭原先的消息队列
docker compose -f docker-compose-kafka.yml down
### 1. 启动消息队列
docker compose -f docker-compose-kafka.yml up -d
### 2. 看有什么topic
docker exec mini-k8s-kafka-1 kafka-topics.sh --list --bootstrap-server localhost:9092

conda activate k8s; python service.py --action manager --sync-interval 5