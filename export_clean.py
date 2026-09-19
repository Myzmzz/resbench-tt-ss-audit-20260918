"""从旧集群导出某命名空间的工作负载定义，清掉集群相关字段，恢复待机前的副本数。

用法: python3 export_clean.py <kind-json-file> <输出-apply.json> <输出-redacted.json> <storage-class>
- apply 版：原样保留配置值，只供 kubectl apply（放在 0700 的临时目录，不进项目目录）
- redacted 版：凡键名含 pass/secret/token/key/credential 的值一律替换成 <REDACTED>，供分析与留档
"""
import json
import re
import sys

SENSITIVE = re.compile(r"pass|secret|token|credential|private|apikey|api_key", re.I)
DROP_META = ("uid", "resourceVersion", "creationTimestamp", "managedFields", "generation",
             "selfLink", "ownerReferences", "finalizers")
DROP_ANN = ("kubectl.kubernetes.io/last-applied-configuration", "deployment.kubernetes.io/revision",
            "pv.kubernetes.io/bind-completed", "pv.kubernetes.io/bound-by-controller",
            "volume.beta.kubernetes.io/storage-provisioner", "volume.kubernetes.io/storage-provisioner",
            "volume.kubernetes.io/selected-node")


def clean(obj: dict, storage_class: str) -> dict:
    meta = obj.get("metadata", {})
    for k in DROP_META:
        meta.pop(k, None)
    ann = meta.get("annotations") or {}
    standby = ann.pop("resiliencebenchmark.io/standby-replicas", None)
    ann.pop("resiliencebenchmark.io/standby-selected-system", None)
    for k in DROP_ANN:
        ann.pop(k, None)
    ann["resiliencebenchmark.io/copied-from"] = "old-cluster tcse-v100 (2026-09-18)"
    meta["annotations"] = ann
    obj.pop("status", None)
    kind = obj.get("kind")
    spec = obj.get("spec", {})
    if kind in ("Deployment", "StatefulSet") and standby is not None and str(standby).isdigit():
        spec["replicas"] = int(standby)
    if kind == "StatefulSet":
        for t in spec.get("volumeClaimTemplates", []):
            t.get("metadata", {}).pop("creationTimestamp", None)
            t.pop("status", None)
            t.setdefault("spec", {})["storageClassName"] = storage_class
    if kind == "Service":
        for k in ("clusterIP", "clusterIPs", "externalIPs", "healthCheckNodePort"):
            spec.pop(k, None)
        for p in spec.get("ports", []):
            p.pop("nodePort", None)          # 避免与共享集群里已占用的 NodePort 冲突
    if kind == "PersistentVolumeClaim":
        spec.pop("volumeName", None)
        spec["storageClassName"] = storage_class
    return obj


def redact(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, str) and SENSITIVE.search(k):
                out[k] = "<REDACTED>"
            elif k == "env" and isinstance(v, list):
                out[k] = [dict(e, value="<REDACTED>") if SENSITIVE.search(e.get("name", "")) and "value" in e else redact(e) for e in v]
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        # ConfigMap 里内嵌的 application.yml / properties 文本：逐行脱敏 password 类键
        return re.sub(r"(?im)^(\s*[\w.\-]*(?:pass|secret|token|credential)[\w.\-]*\s*[:=]\s*).+$", r"\1<REDACTED>", value)
    return value


src, out_apply, out_red, sc = sys.argv[1:5]
data = json.load(open(src, encoding="utf-8"))
items = [clean(o, sc) for o in data.get("items", [])
         if not (o.get("kind") == "ConfigMap" and o["metadata"]["name"] == "kube-root-ca.crt")]
json.dump({"apiVersion": "v1", "kind": "List", "items": items}, open(out_apply, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"apiVersion": "v1", "kind": "List", "items": redact(items)}, open(out_red, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{src.rsplit('/',1)[-1]}: {len(items)} 个对象")
