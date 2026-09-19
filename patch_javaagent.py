"""新环境部署偏差 #7：把 41 个服务从 NFS（1.94.151.57:/data/share）挂载 OTel Java 探针，
改为初始化容器从 otel-demo 2.2.0 ad 镜像复制 jar 到同名 emptyDir。启动参数 JAVA_TOOL_OPTIONS 不动。

原因：新环境节点没有 NFS 客户端（mount: bad option ... /sbin/mount.nfs），不能在共享集群节点上装软件。
用法: python3 patch_javaagent.py <apply 版 deployments.json>  （原地改写）
"""
import json
import sys

AGENT_IMAGE = ("1.94.151.57:85/infra/open-telemetry/demo:2.2.0-ad"
               "@sha256:bc8162f917bed059240369079284df4a2bd549a3e10ea4aece01bf83a749ddd3")
path = sys.argv[1]
doc = json.load(open(path))
patched = 0
for d in doc["items"]:
    spec = d["spec"]["template"]["spec"]
    vols = spec.get("volumes") or []
    target = next((v for v in vols if v["name"] == "opentelemetry-javaagent" and "nfs" in v), None)
    if not target:
        continue
    target.pop("nfs")
    target["emptyDir"] = {}
    inits = [c for c in (spec.get("initContainers") or []) if c["name"] != "copy-otel-javaagent"]
    inits.insert(0, {
        "name": "copy-otel-javaagent",
        "image": AGENT_IMAGE,
        "command": ["sh", "-c", "cp /usr/src/app/opentelemetry-javaagent.jar /opt/opentelemetry-javaagent/opentelemetry-javaagent.jar"],
        "volumeMounts": [{"name": "opentelemetry-javaagent", "mountPath": "/opt/opentelemetry-javaagent"}],
        "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}},
    })
    spec["initContainers"] = inits
    ann = d["metadata"].setdefault("annotations", {})
    ann["resiliencebenchmark.io/new-env-deviation"] = "javaagent-nfs-replaced-by-initcontainer-copy"
    patched += 1
json.dump(doc, open(path, "w"))
print(f"已改 {patched} 个 Deployment")
