#!/usr/bin/env python3
"""按来源许可口径生成入库的 docs-cache/<doc_id>.txt，并生成 documents.yaml。

口径（README 与 documents.yaml 的 license 字段记录同一套判断）：
  permissive —— 来源明确采用开放许可（CC BY / Apache-2.0 / MIT / BSD / PostgreSQL License 等），
                入库全文正文副本，便于任何人复核引用。
  restricted —— 来源为厂商版权文档或未标注许可，不作全文再分发；入库的只有本库实际引用到的
                段落及其所在小节标题（摘录），足以逐字复核，不等于再分发整页。

全文始终保留在本地 docs-cache/.full/（.gitignore 排除），改口径后可随时重建。
用法：python3 build_cache.py
"""
import hashlib
import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "docs-cache")
FULL = os.path.join(CACHE, ".full")

# 主机 -> (许可档位, 许可说明)。判断用的是原始网址；web.archive.org 快照按其中嵌套的原始网址判。
LICENSE_MAP = [
    ("kubernetes.io", "permissive", "CC BY 4.0（Kubernetes 官方文档）"),
    ("kubernetes.github.io", "permissive", "Apache-2.0（ingress-nginx 项目文档）"),
    ("envoyproxy.io", "permissive", "Apache-2.0 / CC BY 4.0（Envoy 项目文档）"),
    ("istio.io", "permissive", "Apache-2.0 / CC BY 4.0（Istio 项目文档）"),
    ("grpc.io", "permissive", "CC BY 4.0（gRPC 项目文档）"),
    ("raw.githubusercontent.com", "permissive", "随所属仓库的开源许可（见 url 指向的仓库）"),
    ("pkg.go.dev", "permissive", "随所属模块的开源许可（标准库为 BSD-3-Clause）"),
    ("docs.spring.io", "permissive", "Apache-2.0（Spring 项目文档）"),
    ("apache.org", "permissive", "Apache-2.0（Apache 软件基金会项目文档）"),
    ("nacos.io", "permissive", "Apache-2.0（Nacos 项目文档）"),
    ("rabbitmq.com", "permissive", "Apache-2.0 / MPL-2.0（RabbitMQ 项目文档）"),
    ("postgresql.org", "permissive", "PostgreSQL License"),
    ("nodejs.org", "permissive", "MIT（Node.js 文档）"),
    ("redis.github.io", "permissive", "MIT（Lettuce 项目文档）"),
    ("docs.rs", "permissive", "随 crate 许可（reqwest 为 MIT OR Apache-2.0）"),
    ("docs.ruby-lang.org", "permissive", "Ruby License / BSD-2-Clause（Ruby 文档）"),
    ("docs.guzzlephp.org", "permissive", "MIT（Guzzle 项目文档）"),
    ("polaris.docs.fairwinds.com", "permissive", "Apache-2.0（Polaris 项目文档）"),
    ("resilience4j.readme.io", "permissive", "Apache-2.0（Resilience4j 项目文档）"),
    ("pollydocs.org", "permissive", "BSD-3-Clause（Polly 项目文档）"),
    ("requests.readthedocs.io", "permissive", "Apache-2.0（Requests 项目文档）"),
    ("python-httpx.org", "permissive", "BSD-3-Clause（HTTPX 项目文档）"),
    ("learn.microsoft.com", "restricted", "© Microsoft，文档未授权再分发"),
    ("docs.oracle.com", "restricted", "© Oracle，文档未授权再分发"),
    ("aws.amazon.com", "restricted", "© Amazon，文档未授权再分发"),
    ("sre.google", "restricted", "© Google / O'Reilly，可在线免费阅读，未授权再分发"),
    ("mongodb.com", "restricted", "© MongoDB，文档未授权再分发"),
    ("principlesofchaos.org", "restricted", "页面未标注许可，按不可再分发处理"),
]
HEADER = (
    "# {doc_id} —— 引用核对副本（摘录）\n"
    "# 来源：{url}\n"
    "# 许可：{license}。本文件不是全文副本，只保留本库实际逐字引用到的段落及其所在小节标题，\n"
    "#      供 validate.py 逐字复核。需要全文请按上面的网址到原站点阅读。\n"
    "# ----------------------------------------------------------------------\n")


def classify(url):
    u = url
    if "web.archive.org" in u and "/https://" in u:
        u = "https://" + u.split("/https://", 1)[1]
    host = re.sub(r"^https?://", "", u).split("/")[0].lower()
    for key, tier, note in LICENSE_MAP:
        if host == key or host.endswith("." + key) or key in host:
            return tier, note
    return "restricted", "许可未能确认，按不可再分发处理"


def collect_quotes():
    """从 templates.yaml / advisories.yaml 里收集 doc_id -> 引用原文集合。"""
    q = {}
    for fn, key in (("templates.yaml", "templates"), ("advisories.yaml", "advisories")):
        path = os.path.join(ROOT, fn)
        if not os.path.exists(path):
            continue
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for item in (data.get(key) or []):
            for src in ((item.get("rule") or {}).get("sources") or []):
                if src.get("doc_id") and src.get("quote"):
                    q.setdefault(src["doc_id"], []).append(src["quote"])
    return q


def excerpt(full_text, quotes):
    """为每条引用取出所在行及最近的上方小节标题，按原文顺序去重拼接。"""
    lines = full_text.split("\n")
    keep = set()
    missing = []
    for quote in quotes:
        qlines = [x for x in quote.split("\n") if x.strip()]
        first = qlines[0].strip()
        hit = None
        for i, ln in enumerate(lines):
            if first and first in ln:
                hit = i
                break
        if hit is None:
            missing.append(quote)
            continue
        for j in range(hit, min(hit + len(qlines), len(lines))):
            keep.add(j)
        for j in range(hit - 1, -1, -1):          # 最近的上方标题
            if lines[j].startswith("[[H"):
                keep.add(j)
                break
    out, prev = [], None
    for i in sorted(keep):
        if prev is not None and i > prev + 1:
            out.append("...")
        out.append(lines[i])
        prev = i
    return "\n".join(out), missing


def main():
    log = json.load(open(os.path.join(ROOT, "fetch-log.json"), encoding="utf-8"))
    quotes = collect_quotes()
    docs, missing_all = [], []
    for doc_id in sorted(log):
        v = log[doc_id]
        if v.get("status") != "ok":
            docs.append(dict(doc_id=doc_id, url=v.get("url", ""), fetch_status="failed",
                             error=v.get("error", "")))
            continue
        tier, note = classify(v["url"])
        full = open(os.path.join(FULL, doc_id + ".txt"), encoding="utf-8").read()
        if tier == "permissive":
            body = full
            kind = "full"
        else:
            body, miss = excerpt(full, quotes.get(doc_id, []))
            missing_all += [(doc_id, m) for m in miss]
            if not body.strip():
                body = "（本次提交尚无引用落在该文档上）"
            body = HEADER.format(doc_id=doc_id, url=v["url"], license=note) + body + "\n"
            kind = "excerpt"
        open(os.path.join(CACHE, doc_id + ".txt"), "w", encoding="utf-8").write(body)
        docs.append(dict(
            doc_id=doc_id, title=v["title"], component=v["component"], layer=v["layer"],
            version=v.get("version", "unversioned"), url=v["url"],
            retrieved_at=v["retrieved_at"],
            sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            source_sha256=v.get("source_sha256", ""),
            license=note, redistribution=tier, local_copy="docs-cache/%s.txt" % doc_id,
            local_copy_kind=kind))
    header = ("# 文档登记表。由 build_cache.py 依据 sources.tsv 与 fetch-log.json 生成，请勿手改。\n"
              "# redistribution=permissive 的文档入库全文；restricted 的只入库被引用到的段落（摘录），\n"
              "# 两种情况下 sha256 都是对 local_copy 指向的文件计算的，validate.py 按它核对引用。\n"
              "# source_sha256 是抓回的完整正文的摘要，用于判断原站点是否已改版。\n")
    with open(os.path.join(ROOT, "documents.yaml"), "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump({"documents": docs}, f, allow_unicode=True, sort_keys=False, width=200)
    n_full = sum(1 for d in docs if d.get("local_copy_kind") == "full")
    print("documents.yaml：%d 份（全文 %d，摘录 %d）" % (len(docs), n_full, len(docs) - n_full))
    if missing_all:
        print("以下引用在全文副本里找不到，摘录未能生成：")
        for d, m in missing_all:
            print("  %s: %s" % (d, m.replace("\n", " ")[:90]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
