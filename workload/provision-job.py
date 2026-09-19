"""渲染建号 Job：python:3.12 基础镜像 + ConfigMap 挂载脚本，口令只经 secretKeyRef 注入。"""
import json, sys
system, base_url, secret = sys.argv[1:4]
script = open(sys.argv[4]).read()
name = f"resbench-audit-provision-{system}"
labels = {"resiliencebenchmark.io/owner": "resbench-audit-20260918", "app": name}
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "labels": labels},
      "data": {"provision_users.py": script}}
env = [{"name": "SYSTEM", "value": system}, {"name": "BASE_URL", "value": base_url},
       {"name": "USER_SVC", "value": "http://user.sock-shop.svc.cluster.local:80"}]
if system == "train-ticket":
    env = [e for e in env if e["name"] != "USER_SVC"]
for var, key in (("WL_USERNAME", "username"), ("WL_PASSWORD", "password")):
    env.append({"name": var, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}})
job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "labels": labels},
       "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 86400, "template": {"metadata": {"labels": labels}, "spec": {
           "restartPolicy": "Never",
           "containers": [{"name": "provision",
                           "image": "1.94.151.57:85/train-ticket/python-base:3.12.5-slim-bookworm-eac7a234d332@sha256:eac7a234d33269f362593c31d2ff1db7b116fbd794929f1f6015f5ea812ff254",
                           "command": ["python3", "/work/provision_users.py"], "env": env,
                           "volumeMounts": [{"name": "work", "mountPath": "/work"}]}],
           "volumes": [{"name": "work", "configMap": {"name": name}}]}}}}
print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [cm, job]}))
