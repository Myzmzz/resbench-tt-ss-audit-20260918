"""Render a short-lived reader Pod that mounts a workload results PVC and prints a summary.

Usage: python3 read_results.py <namespace> <pvc> <file-in-pvc> > pod.yaml
The Pod runs the pinned python-base image, summarizes a JMeter-style JTL (or prints a JSON file),
and never prints request bodies or credentials (JTL rows carry only label/status/elapsed).
"""
import json
import sys

PYTHON_BASE_IMAGE = ("1.94.151.57:85/train-ticket/python-base:3.12.5-slim-bookworm-eac7a234d332"
                     "@sha256:eac7a234d33269f362593c31d2ff1db7b116fbd794929f1f6015f5ea812ff254")

SUMMARIZER = r'''
import csv, json, sys, statistics, collections
path = sys.argv[1]
if path.endswith(".json"):
    print(open(path).read()[:6000]); sys.exit()
rows = list(csv.DictReader(open(path)))
print("rows", len(rows), "fields", list(rows[0].keys()) if rows else [])
if not rows: sys.exit()
t0 = int(rows[0]["timeStamp"])
def pct(v, q):
    v = sorted(v); return v[max(0, -(-len(v) * q // 100) - 1)]
by = collections.defaultdict(list)
for r in rows: by[r["label"]].append(r)
print("label | n | fail | p50 | p95 | max | first5_elapsed")
for lab, rs in sorted(by.items()):
    el = [int(r["elapsed"]) for r in rs]
    fails = sum(1 for r in rs if r["success"].lower() != "true")
    print(f"{lab} | {len(rs)} | {fails} | {pct(el,50)} | {pct(el,95)} | {max(el)} | {[int(r['elapsed']) for r in rs[:5]]}")
codes = collections.Counter((r["label"], r["responseCode"]) for r in rows if r["success"].lower() != "true")
print("failures by (label, code):", dict(codes.most_common(15)))
print("timeline (10s buckets): bucket_start_s n p95 max fails")
buckets = collections.defaultdict(list)
for r in rows: buckets[(int(r["timeStamp"]) - t0) // 10000].append(r)
for b in sorted(buckets):
    el = [int(r["elapsed"]) for r in buckets[b]]
    print(b * 10, len(el), pct(el, 95), max(el), sum(1 for r in buckets[b] if r["success"].lower() != "true"))
slow = sorted(rows, key=lambda r: -int(r["elapsed"]))[:12]
print("slowest:", [(r["label"], int(r["elapsed"]), r["responseCode"], (int(r["timeStamp"]) - t0) // 1000) for r in slow])
'''


def render(namespace: str, pvc: str, file_in_pvc: str) -> dict:
    """Return a Pod manifest that mounts the PVC read-only and runs the summarizer once."""
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": f"resbench-audit-read-{pvc}"[:63], "namespace": namespace,
                     "labels": {"resiliencebenchmark.io/owner": "resbench-audit-20260918"}},
        "spec": {
            "restartPolicy": "Never",
            "containers": [{
                "name": "reader", "image": PYTHON_BASE_IMAGE,
                "command": ["python3", "-c", SUMMARIZER, f"/results/{file_in_pvc}"],
                "volumeMounts": [{"name": "results", "mountPath": "/results", "readOnly": True}],
                "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}},
            }],
            "volumes": [{"name": "results", "persistentVolumeClaim": {"claimName": pvc, "readOnly": True}}],
        },
    }


if __name__ == "__main__":
    print(json.dumps(render(sys.argv[1], sys.argv[2], sys.argv[3])))
