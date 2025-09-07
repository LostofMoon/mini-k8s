conda activate k8s; python apiServer.py

conda activate k8s; python scheduler.py --apiserver localhost --interval 3

conda activate k8s
python node.py --config testFile\node-1.yaml
python node.py --config testFile\node-2.yaml
python node.py --config testFile\node-3.yaml

python pod.py --config testFile/pod-1.yaml --action create