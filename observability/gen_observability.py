"""生成新环境（腾讯云）上的观测栈清单：OTel Collector + Jaeger + Prometheus + kube-state-metrics。

以旧环境 observability 命名空间的实际配置为底（old-export/），只做这些改动：
- Jaeger 加开 Zipkin 9411（sock-shop 用 zipkin 上报；旧环境从未开，sock-shop 调用链一直是断的）
- OTel Collector 去掉 coroot 导出（新环境没有 coroot）
- Prometheus 换成 Harbor 里的 v2.52.0，去掉 3.x 才有的 OTLP 接收参数与 otlp 配置段、去掉 node-exporter 任务
- 共享集群上只采集本次审计的三个命名空间，不抓别人的 Pod
用法：python3 gen_observability.py > new-env-observability.yaml
"""
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).parent
HARBOR = "1.94.151.57:85/train-ticket"
OWNED = ["train-ticket", "sock-shop", "observability"]
LABELS = {"resiliencebenchmark.io/owner": "resbench-audit-20260918"}


def meta(name, ns=None, extra=None):
    m = {"name": name, "labels": dict(LABELS, **(extra or {}))}
    if ns:
        m["namespace"] = ns
    return m


def deployment(name, image, *, command=None, args=None, env=None, ports=(), resources=None, volumes=None, mounts=None,
               sa=None, fs_group=None, strategy="RollingUpdate"):
    container = {"name": name, "image": image, "ports": [{"containerPort": p} for p in ports],
                 "resources": resources or {}}
    if command:
        container["command"] = command
    if args:
        container["args"] = args
    if env:
        container["env"] = [{"name": k, "value": v} for k, v in env.items()]
    if mounts:
        container["volumeMounts"] = mounts
    pod = {"containers": [container]}
    if volumes:
        pod["volumes"] = volumes
    if sa:
        pod["serviceAccountName"] = sa
    if fs_group is not None:
        pod["securityContext"] = {"fsGroup": fs_group}
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta(name, "observability"),
            "spec": {"replicas": 1, "strategy": {"type": strategy},
                     "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": dict(LABELS, app=name)}, "spec": pod}}}


def service(name, ns, selector_app, ports):
    return {"apiVersion": "v1", "kind": "Service", "metadata": meta(name, ns),
            "spec": {"selector": {"app": selector_app},
                     "ports": [{"name": n, "port": p, "targetPort": p} for n, p in ports]}}


def pvc(name, size):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": meta(name, "observability"),
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "openebs-hostpath",
                     "resources": {"requests": {"storage": size}}}}


def rbac(name, rules):
    full = f"resbench-audit-{name}"
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": meta(name, "observability")},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole", "metadata": meta(full), "rules": rules},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding", "metadata": meta(full),
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": full},
         "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": "observability"}]},
    ]


def prometheus_config():
    cfg = yaml.safe_load((HERE / "old-export/prometheus.yml").read_text())
    cfg.pop("otlp", None)
    jobs = []
    for job in cfg["scrape_configs"]:
        if job["job_name"] == "node-exporter":
            continue
        if job["job_name"] == "kubernetes-cadvisor":
            job["metric_relabel_configs"] = [{"source_labels": ["namespace"], "action": "keep",
                                              "regex": "(" + "|".join(OWNED) + "|)"}]
        if job["job_name"] == "kubernetes-pods-annotated":
            job["kubernetes_sd_configs"] = [{"role": "pod", "namespaces": {"names": OWNED}}]
        jobs.append(job)
    # Audit-only addition (not in the old env): sock-shop annotates its Services, not its Pods, with
    # prometheus.io/scrape, so the pod-annotation job above never finds it and its request metrics were
    # never collected in either environment. Scrape Service endpoints in sock-shop only.
    jobs.append({
        "job_name": "sock-shop-service-endpoints",
        "kubernetes_sd_configs": [{"role": "endpoints", "namespaces": {"names": ["sock-shop"]}}],
        "relabel_configs": [
            {"source_labels": ["__meta_kubernetes_service_annotation_prometheus_io_scrape"],
             "action": "keep", "regex": "true"},
            {"source_labels": ["__address__", "__meta_kubernetes_service_annotation_prometheus_io_port"],
             "action": "replace", "regex": r"([^:]+)(?::\d+)?;(\d+)", "replacement": "$1:$2",
             "target_label": "__address__"},
            {"source_labels": ["__meta_kubernetes_namespace"], "target_label": "namespace"},
            {"source_labels": ["__meta_kubernetes_service_name"], "target_label": "service"},
            {"source_labels": ["__meta_kubernetes_pod_name"], "target_label": "pod"},
        ],
    })
    cfg["scrape_configs"] = jobs
    return yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)


def collector_config():
    cfg = yaml.safe_load((HERE / "old-export/otel-collector.yaml").read_text())
    cfg["exporters"].pop("otlphttp/coroot", None)
    for pipeline in cfg["service"]["pipelines"].values():
        pipeline["exporters"] = [e for e in pipeline.get("exporters", []) if e != "otlphttp/coroot"] or ["debug"]
    return yaml.safe_dump(cfg, sort_keys=False)


docs = [
    {"apiVersion": "v1", "kind": "Namespace", "metadata": meta("observability")},
    {"apiVersion": "v1", "kind": "Namespace", "metadata": meta("jaeger")},
    # sock-shop 写死上报到 zipkin.jaeger.svc.cluster.local:9411，用 DNS 别名指到 Jaeger，不改 sock-shop 配置
    {"apiVersion": "v1", "kind": "Service", "metadata": meta("zipkin", "jaeger"),
     "spec": {"type": "ExternalName", "externalName": "jaeger-query.observability.svc.cluster.local",
              "ports": [{"name": "zipkin", "port": 9411}]}},
    pvc("jaeger-badger", "20Gi"),
    deployment("jaeger", f"{HARBOR}/jaeger-all-in-one:1.57", command=["/go/bin/all-in-one-linux"], strategy="Recreate", fs_group=10001,
               env={"COLLECTOR_OTLP_ENABLED": "true", "COLLECTOR_ZIPKIN_HOST_PORT": ":9411",
                    "SPAN_STORAGE_TYPE": "badger", "BADGER_EPHEMERAL": "false",
                    "BADGER_DIRECTORY_KEY": "/badger/key", "BADGER_DIRECTORY_VALUE": "/badger/data",
                    "BADGER_SPAN_STORE_TTL": "24h", "BADGER_MAINTENANCE_INTERVAL": "5m"},
               ports=(16686, 4317, 4318, 14268, 9411),
               resources={"requests": {"cpu": "250m", "memory": "1Gi"}, "limits": {"cpu": "2", "memory": "8Gi"}},
               volumes=[{"name": "badger", "persistentVolumeClaim": {"claimName": "jaeger-badger"}}],
               mounts=[{"name": "badger", "mountPath": "/badger"}]),
    service("jaeger-query", "observability", "jaeger",
            [("query", 16686), ("otlp-grpc", 4317), ("otlp-http", 4318), ("thrift-http", 14268), ("zipkin", 9411)]),
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("otel-collector-config", "observability"),
     "data": {"config.yaml": collector_config()}},
    deployment("otel-collector", f"{HARBOR}/otel-collector-contrib:0.102.1", command=["/otelcol-contrib"], args=["--config=/conf/config.yaml"],
               ports=(4317, 4318, 8889, 13133),
               resources={"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
               volumes=[{"name": "conf", "configMap": {"name": "otel-collector-config"}}],
               mounts=[{"name": "conf", "mountPath": "/conf"}]),
    service("otel-collector", "observability", "otel-collector",
            [("otlp-grpc", 4317), ("otlp-http", 4318), ("prom", 8889), ("health", 13133)]),
    *rbac("prometheus", json.loads((HERE / "old-export/observability-prometheus.rules.json").read_text())),
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("prometheus-config", "observability"),
     "data": {"prometheus.yml": prometheus_config()}},
    pvc("prometheus-data", "20Gi"),
    deployment("prometheus", f"{HARBOR}/prometheus:v2.52.0", command=["/bin/prometheus"], sa="prometheus", strategy="Recreate", fs_group=65534,
               args=["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus",
                     "--storage.tsdb.retention.time=7d", "--web.enable-lifecycle"],
               ports=(9090,),
               resources={"requests": {"cpu": "250m", "memory": "1Gi"}, "limits": {"cpu": "2", "memory": "4Gi"}},
               volumes=[{"name": "conf", "configMap": {"name": "prometheus-config"}},
                        {"name": "data", "persistentVolumeClaim": {"claimName": "prometheus-data"}}],
               mounts=[{"name": "conf", "mountPath": "/etc/prometheus"}, {"name": "data", "mountPath": "/prometheus"}]),
    service("prometheus", "observability", "prometheus", [("web", 9090)]),
    *rbac("kube-state-metrics", json.loads((HERE / "old-export/observability-kube-state-metrics.rules.json").read_text())),
    deployment("kube-state-metrics", f"{HARBOR}/kube-state-metrics:v2.12.0", command=["/kube-state-metrics"], sa="kube-state-metrics",
               args=["--namespaces=" + ",".join(OWNED)], ports=(8080, 8081),
               resources={"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "512Mi"}}),
    service("kube-state-metrics", "observability", "kube-state-metrics", [("metrics", 8080)]),
]
sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True))
