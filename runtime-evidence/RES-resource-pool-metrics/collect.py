"""Collect resource-vs-runtime and connection-pool evidence from the audit Prometheus (read-only).

Queries go through the Kubernetes API server service proxy, so no port-forward is needed.
Usage: python3 collect.py <kubeconfig>  (prints a plain-text report to stdout)
"""
import json
import re
import subprocess
import sys
import urllib.parse
from collections import defaultdict

KUBECONFIG = sys.argv[1]
PROXY = "/api/v1/namespaces/observability/services/prometheus:9090/proxy/api/v1/query?query="


def query(promql: str) -> list[dict]:
    """Run an instant PromQL query and return the result vector."""
    raw = subprocess.run(["kubectl", f"--kubeconfig={KUBECONFIG}", "get", "--raw", PROXY + urllib.parse.quote(promql)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(raw)["data"]["result"]


def pod_owner(pod: str) -> str:
    """Map `ts-foo-service-7c8bf7df4f-65kjp` to `ts-foo-service`; StatefulSet pods keep their ordinal name."""
    parts = pod.split("-")
    if len(parts) > 2 and re.fullmatch(r"[a-z0-9]{5}", parts[-1]) and re.fullmatch(r"[a-z0-9]{6,10}", parts[-2]):
        return "-".join(parts[:-2])
    return pod


def mib(value: float) -> str:
    return f"{value / 1048576:.0f}Mi"


def main() -> None:
    # 1. JVM heap ceiling (sum of heap pools per instance) vs container memory limit/request, train-ticket.
    heap = defaultdict(float)
    for r in query('sum by (exported_job, exported_instance) (train_ticket_jvm_memory_limit_bytes{jvm_memory_type="heap"})'):
        heap[r["metric"]["exported_job"]] = max(heap[r["metric"]["exported_job"]], float(r["value"][1]))
    heap_used = defaultdict(float)
    for r in query('max by (exported_job) (max_over_time(sum by (exported_job, exported_instance) (train_ticket_jvm_memory_used_bytes{jvm_memory_type="heap"})[15m:30s]))'):
        heap_used[r["metric"]["exported_job"]] = float(r["value"][1])
    limits, requests, wss = {}, {}, defaultdict(float)
    for r in query('max by (container) (kube_pod_container_resource_limits{namespace="train-ticket",resource="memory"})'):
        limits[r["metric"]["container"]] = float(r["value"][1])
    for r in query('max by (container) (kube_pod_container_resource_requests{namespace="train-ticket",resource="memory"})'):
        requests[r["metric"]["container"]] = float(r["value"][1])
    # cAdvisor on this cluster (cgroup v2 + cri-dockerd) only reports pod-level cgroups (no `container` label),
    # so aggregate by pod and map the pod back to its Deployment by stripping the ReplicaSet/pod hash suffixes.
    for r in query('max by (pod) (max_over_time(container_memory_working_set_bytes{namespace="train-ticket",pod!=""}[15m]))'):
        owner = pod_owner(r["metric"]["pod"])
        wss[owner] = max(wss[owner], float(r["value"][1]))
    print("## train-ticket：JVM 堆上限 vs 容器内存限额（堆上限取自 OTel jvm.memory.limit 的 heap 池之和）")
    print("service | heap_max | heap_used_max(15m) | mem_request | mem_limit | wss_max(15m) | heap/limit")
    for svc in sorted(heap):
        lim = limits.get(svc)
        print(f"{svc} | {mib(heap[svc])} | {mib(heap_used.get(svc, 0))} | {mib(requests[svc]) if svc in requests else '-'} | "
              f"{mib(lim) if lim else 'none'} | {mib(wss.get(svc, 0))} | {heap[svc] / lim:.2f}" if lim else
              f"{svc} | {mib(heap[svc])} | {mib(heap_used.get(svc, 0))} | {mib(requests[svc]) if svc in requests else '-'} | none | {mib(wss.get(svc, 0))} | -")

    # 2. Hikari pool maxima per service x live instances, vs the tsdb max_connections.
    print("\n## train-ticket：Hikari 连接池上限（OTel db.client.connections.max）")
    per_service = defaultdict(list)
    for r in query("train_ticket_db_client_connections_max"):
        per_service[r["metric"]["exported_job"]].append(float(r["value"][1]))
    total = 0.0
    for svc, values in sorted(per_service.items()):
        total += sum(values)
        print(f"{svc} | instances={len(values)} | max_per_instance={values[0]:.0f} | subtotal={sum(values):.0f}")
    print(f"TOTAL pool max across reporting instances = {total:.0f}（注：collector 导出端的过期窗口内可能含已退出实例）")
    pending = query("max by (exported_job) (max_over_time(train_ticket_db_client_connections_pending_requests[15m]))")
    busy = [(r["metric"]["exported_job"], r["value"][1]) for r in pending if float(r["value"][1]) > 0]
    print(f"15 分钟内出现过排队等连接的服务：{busy or '无'}")
    wait = query('histogram_quantile(0.99, sum by (le, exported_job) (rate(train_ticket_db_client_connections_wait_time_milliseconds_bucket[15m])))')
    top = sorted(((r["metric"]["exported_job"], float(r["value"][1])) for r in wait if r["value"][1] not in ("NaN",)), key=lambda x: -x[1])[:8]
    print(f"取连接等待 p99（ms，15m）前 8：{[(s, round(v, 1)) for s, v in top]}")

    # 3. CPU throttling ratio (last 15m) for both namespaces.
    print("\n## CPU 节流比例（15m，Pod 级 cgroup，throttled_periods / periods，只列 >1% 的 Pod）")
    for ns in ("train-ticket", "sock-shop"):
        rows = query(f'sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{{namespace="{ns}",pod!=""}}[15m])) / '
                     f'sum by (pod) (rate(container_cpu_cfs_periods_total{{namespace="{ns}",pod!=""}}[15m]))')
        measured = [r for r in rows if r["value"][1] != "NaN"]
        hot = sorted(((pod_owner(r["metric"]["pod"]), float(r["value"][1])) for r in measured if float(r["value"][1]) > 0.01), key=lambda x: -x[1])
        print(f"{ns}: 有节流数据的 Pod {len(measured)} 个；>1%：{[(c, f'{v:.0%}') for c, v in hot] or '无'}")
    print("\n## sock-shop：内存工作集峰值 vs 限额（15m，Pod 级）")
    ss_limits = {r["metric"]["container"]: float(r["value"][1]) for r in query('max by (container) (kube_pod_container_resource_limits{namespace="sock-shop",resource="memory"})')}
    for r in sorted(query('max by (pod) (max_over_time(container_memory_working_set_bytes{namespace="sock-shop",pod!=""}[15m]))'), key=lambda r: r["metric"]["pod"]):
        owner = pod_owner(r["metric"]["pod"])
        lim = ss_limits.get(owner)
        print(f"{owner} | wss_max={mib(float(r['value'][1]))} | limit={mib(lim) if lim else 'none'}" + (f" | {float(r['value'][1]) / lim:.0%}" if lim else ""))
    cpu_limits = query('count by (namespace) (kube_pod_container_resource_limits{namespace=~"train-ticket|sock-shop",resource="cpu"})')
    print("设置了 CPU limit 的容器数：", {r["metric"]["namespace"]: r["value"][1] for r in cpu_limits})


if __name__ == "__main__":
    main()
