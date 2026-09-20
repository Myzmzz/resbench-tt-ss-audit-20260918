#!/usr/bin/env python3
"""生成 stats.md。加 --stdout 则只打印不落盘（validate.py 用它比对 stats.md 是否最新）。

统计内容对应任务书第 10 节：文档数（按组件与通用准则分列）、模板数、advisory 数、
机制组 × 动作类型分布、检查项按判定方式的占比、组件 × 模板的落点覆盖矩阵。
"""
import os
import sys
from collections import Counter, defaultdict

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
GUIDELINE_LAYER = "通用准则"


def load(name, key):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return []
    return (yaml.safe_load(open(p, encoding="utf-8")) or {}).get(key, []) or []


def main():
    docs = load("documents.yaml", "documents")
    templates = load("templates.yaml", "templates")
    advisories = load("advisories.yaml", "advisories")
    L = []
    A = L.append

    A("<!-- 由 stats.py 生成，请勿手改；改了 YAML 后重新运行 python3 stats.py -->\n")
    A("# stats.md —— 缺陷模板库统计\n")

    # 1 文档
    A("## 1 文档\n")
    by_layer = defaultdict(list)
    for d in docs:
        by_layer[d.get("layer", "?")].append(d)
    A("### 1.1 组件文档（按层与组件）\n")
    A("| 层 | 组件 | 文档数 | 全文入库 | 仅摘录入库 |")
    A("|---|---|---|---|---|")
    total_comp = 0
    for layer in [x for x in by_layer if x != GUIDELINE_LAYER]:
        per_comp = defaultdict(list)
        for d in by_layer[layer]:
            per_comp[d["component"]].append(d)
        for comp in sorted(per_comp):
            ds = per_comp[comp]
            full = sum(1 for x in ds if x.get("local_copy_kind") == "full")
            A("| %s | %s | %d | %d | %d |" % (layer, comp, len(ds), full, len(ds) - full))
            total_comp += len(ds)
    A("| **小计** | | **%d** | | |" % total_comp)

    A("\n### 1.2 通用准则文档\n")
    A("| 来源 | 文档数 | 全文入库 | 仅摘录入库 |")
    A("|---|---|---|---|")
    per_comp = defaultdict(list)
    for d in by_layer.get(GUIDELINE_LAYER, []):
        per_comp[d["component"]].append(d)
    total_g = 0
    for comp in sorted(per_comp):
        ds = per_comp[comp]
        full = sum(1 for x in ds if x.get("local_copy_kind") == "full")
        A("| %s | %d | %d | %d |" % (comp, len(ds), full, len(ds) - full))
        total_g += len(ds)
    A("| **小计** | **%d** | | |" % total_g)
    A("\n文档合计 **%d** 份，其中全文入库 %d 份、仅摘录入库 %d 份。" % (
        len(docs), sum(1 for d in docs if d.get("local_copy_kind") == "full"),
        sum(1 for d in docs if d.get("local_copy_kind") == "excerpt")))

    # 2 模板与 advisory
    A("\n## 2 模板与 advisory\n")
    A("| 项 | 数 |")
    A("|---|---|")
    A("| 模板 | %d |" % len(templates))
    A("| advisory | %d |" % len(advisories))
    A("| 引用条目（模板 + advisory 的 sources） | %d |" % (
        sum(len((t.get("rule") or {}).get("sources") or []) for t in templates)
        + sum(len((a.get("rule") or {}).get("sources") or []) for a in advisories)))
    A("| 被引用到的文档 | %d |" % len({
        s["doc_id"] for t in templates for s in (t.get("rule") or {}).get("sources") or []}
        | {s["doc_id"] for a in advisories for s in (a.get("rule") or {}).get("sources") or []}))
    A("| 检查项 | %d |" % sum(len((t.get("locate") or {}).get("checks") or []) for t in templates))

    A("\n### 2.1 每个机制组的模板数与 advisory 数\n")
    A("| 机制组 | 模板数 | advisory 数 | 是否达到 3 条 |")
    A("|---|---|---|---|")
    gt = Counter(t["mechanism_group"] for t in templates)
    ga = Counter(a["mechanism_group"] for a in advisories)
    for g in sorted(set(gt) | set(ga)):
        A("| `%s` | %d | %d | %s |" % (g, gt.get(g, 0), ga.get(g, 0),
                                       "是" if gt.get(g, 0) >= 3 else "**否**"))

    A("\n### 2.2 缺陷类别分布\n")
    A("| 缺陷类别 | 模板数 |")
    A("|---|---|")
    for k, v in sorted(Counter(t["defect_class"] for t in templates).items()):
        A("| %s | %d |" % (k, v))

    A("\n### 2.3 advisory 的参数类型分布\n")
    A("| 参数类型 | advisory 数 |")
    A("|---|---|")
    for k, v in sorted(Counter(a["parameter_kind"] for a in advisories).items()):
        A("| %s | %d |" % (k, v))

    # 3 机制组 × 动作类型
    A("\n## 3 机制组 × 动作类型分布\n")
    types = ["连续幅值", "离散·有数量", "离散·有时长", "离散·无可比参数"]
    cell = defaultdict(Counter)
    for t in templates:
        for a in (t.get("experiment") or {}).get("actions") or []:
            cell[t["mechanism_group"]][a["type"]] += 1
    A("| 机制组 | " + " | ".join(types) + " | 合计 |")
    A("|---" * (len(types) + 2) + "|")
    tot = Counter()
    for g in sorted(cell):
        row = [str(cell[g][x]) for x in types]
        s = sum(cell[g][x] for x in types)
        for x in types:
            tot[x] += cell[g][x]
        A("| `%s` | %s | %d |" % (g, " | ".join(row), s))
    A("| **合计** | %s | **%d** |" % (" | ".join(str(tot[x]) for x in types), sum(tot.values())))

    # 4 检查项判定方式
    A("\n## 4 检查项按判定方式的占比\n")
    ck = Counter()
    ck_kind = defaultdict(Counter)
    for t in templates:
        for c in (t.get("locate") or {}).get("checks") or []:
            ck[c["checker"]] += 1
            ck_kind[c["checker"]][c["kind"]] += 1
    n = sum(ck.values()) or 1
    A("| 判定方式 | 检查项数 | 占比 | 其中「必要」 |")
    A("|---|---|---|---|")
    for k in ["manifest", "semgrep", "codegraph", "llm", "runtime"]:
        A("| %s | %d | %.1f%% | %d |" % (k, ck[k], 100.0 * ck[k] / n, ck_kind[k]["必要"]))
    A("| **合计** | **%d** | 100.0%% | **%d** |" % (n, sum(v["必要"] for v in ck_kind.values())))
    auto = ck["manifest"] + ck["semgrep"] + ck["codegraph"]
    A("\n可由工具直接判定（manifest + semgrep + codegraph）的检查项占 **%.1f%%**；"
      "其余 %.1f%% 需要 llm 复核或运行时观察。" % (100.0 * auto / n, 100.0 * (n - auto) / n))

    # 5 组件 × 模板落点覆盖矩阵
    A("\n## 5 组件 × 模板的落点覆盖矩阵\n")
    A("列出每个组件被哪些模板的 `locate.instantiations` 命中。\n")
    comp_map = defaultdict(list)
    for t in templates:
        for inst in (t.get("locate") or {}).get("instantiations") or []:
            comp_map[inst["component"]].append(t["template_id"])
    A("| 组件 | 落点数 | 模板 |")
    A("|---|---|---|")
    for comp in sorted(comp_map, key=lambda c: (-len(comp_map[c]), c)):
        ids = comp_map[comp]
        A("| %s | %d | %s |" % (comp, len(ids), "、".join(sorted(set(ids)))))
    doc_comps = {d["component"] for d in docs if d.get("layer") != GUIDELINE_LAYER}
    uncovered = sorted(doc_comps - set(comp_map))
    A("\n已登记文档但尚无模板落点的组件（%d 个）：%s" % (
        len(uncovered), "、".join(uncovered) if uncovered else "无"))

    out = "\n".join(L) + "\n"
    if "--stdout" in sys.argv:
        sys.stdout.write(out)
    else:
        open(os.path.join(ROOT, "stats.md"), "w", encoding="utf-8").write(out)
        print("stats.md 已生成：%d 条模板、%d 条 advisory、%d 份文档" % (
            len(templates), len(advisories), len(docs)))


if __name__ == "__main__":
    main()
