#!/usr/bin/env python3
"""把 templates.yaml 渲染成 templates.md：每条模板一张四块卡片（规则 / 定位 / 实验 / 判定）。

用法：python3 render_templates.py
"""
import os
from collections import defaultdict

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(name, key):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return []
    return (yaml.safe_load(open(p, encoding="utf-8")) or {}).get(key, []) or []


def esc(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


def main():
    templates = load("templates.yaml", "templates")
    advisories = load("advisories.yaml", "advisories")
    docs = {d["doc_id"]: d for d in load("documents.yaml", "documents")}
    L = []
    A = L.append
    A("<!-- 由 render_templates.py 生成，请勿手改；改了 templates.yaml 后重新运行 -->\n")
    A("# templates.md —— 缺陷模板卡片\n")
    A("共 %d 条模板、%d 条 advisory。每张卡片四块：**规则**（应该怎样、凭什么）、"
      "**定位**（到哪找、查什么）、**实验**（用什么故障、多大多久）、**判定**（看什么、算不算、怎么修）。\n"
      % (len(templates), len(advisories)))

    by_group = defaultdict(list)
    for t in templates:
        by_group[t["mechanism_group"]].append(t)
    A("## 目录\n")
    for g in sorted(by_group):
        A("- **`%s`**：%s" % (g, "、".join("[%s](#%s)" % (t["template_id"], t["template_id"].lower())
                                          for t in by_group[g])))
    A("")

    for g in sorted(by_group):
        A("\n---\n\n## 机制组 `%s`\n" % g)
        for t in by_group[g]:
            A("\n### %s　%s\n" % (t["template_id"], t["name"]))
            A("> 机制 `%s`　缺陷类别 **%s**　参数类型 **%s**\n"
              % (t["mechanism"], t["defect_class"], t["parameter_kind"]))
            A("**违反后的运行时表现**：%s\n" % t["violation_manifestation"])

            rule = t.get("rule") or {}
            A("#### 一 规则\n")
            A("%s\n" % rule.get("statement", ""))
            A("依据：\n")
            for src in rule.get("sources") or []:
                d = docs.get(src["doc_id"], {})
                A("- `%s`（%s，%s）— %s" % (src["doc_id"], d.get("component", "?"),
                                            src.get("location", ""), d.get("title", "")))
                for line in str(src["quote"]).split("\n"):
                    A("  > %s" % line)
            if rule.get("defaults"):
                A("\n文档给出的默认值：\n")
                A("| 符号 | 值 | 单位 | 出处 |")
                A("|---|---|---|---|")
                for d0 in rule["defaults"]:
                    A("| `%s` | %s | %s | `%s` |" % (d0.get("symbol"), esc(d0.get("value")),
                                                     esc(d0.get("unit", "")), d0.get("doc_id")))

            loc = t.get("locate") or {}
            A("\n#### 二 定位\n")
            A("适用范围：\n")
            for x in loc.get("applies_when") or []:
                A("- %s" % x)
            r = loc.get("roles") or {}
            A("\n角色：脆弱点在 **%s**；故障加在 **%s**；异常显现在 **%s**。\n"
              % (r.get("defect_site"), r.get("injection_site"), r.get("manifest_site")))
            A("落点：\n")
            A("| 组件 | 怎么落 | 配置键或代码 |")
            A("|---|---|---|")
            for inst in loc.get("instantiations") or []:
                A("| %s | %s | `%s` |" % (esc(inst["component"]), esc(inst["how"]),
                                          esc(inst["config_or_code"])))
            A("\n检查项：\n")
            A("| id | 类型 | 判定方式 | 要查什么 | 查询 |")
            A("|---|---|---|---|---|")
            for c in loc.get("checks") or []:
                A("| %s | %s | `%s` | %s | %s |" % (c["id"], c["kind"], c["checker"],
                                                    esc(c["statement"]), esc(c["query"])))

            exp = t.get("experiment") or {}
            A("\n#### 三 实验\n")
            A("| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |")
            A("|---|---|---|---|---|")
            for a in exp.get("actions") or []:
                A("| %s | %s | `%s` | %s | %s |" % (esc(a["action"]), a["type"], a["target_role"],
                                                    esc(a.get("primitive_hint", "")),
                                                    esc(a.get("only_if", "—"))))
            pr = exp.get("parameter_relation") or {}
            if pr:
                A("\n参数关系：\n")
                A("| 符号 | 含义 | 取值来源 |")
                A("|---|---|---|")
                for sym in pr.get("symbols") or []:
                    A("| `%s` | %s | %s |" % (sym["symbol"], esc(sym["meaning"]), sym["source"]))
                A("")
                A("- 触发边界：`%s`" % esc(pr.get("boundary", "")))
                A("- 最坏情况倍数：`%s`" % esc(pr.get("worst_case_multiplier", "")))
                A("- 保持时长：`%s`" % esc(pr.get("hold", "")))
                A("- 恢复观察窗：`%s`" % esc(pr.get("recovery_window", "")))
                A("\n余量与安全系数由下游流水线统一取，模板不写。")

            v = t.get("verdict") or {}
            A("\n#### 四 判定\n")
            A("预期行为：%s\n" % v.get("expected_behavior", ""))
            A("看哪些信号：\n")
            A("| 信号 | 来源 |")
            A("|---|---|")
            for sg in v.get("signals") or []:
                A("| %s | `%s` |" % (esc(sg["signal"]), sg["source"]))
            A("\n同一现象的其他解释（实验必须能排除）：\n")
            for x in v.get("alternative_explanations") or []:
                A("- %s" % x)
            m = v.get("mitigation") or {}
            A("\n怎么修：%s（改动层面：**%s**）" % (m.get("family"), m.get("level")))
            if t.get("evidence_incidents"):
                A("\n佐证（只作优先级参考，不是规则依据）：")
                for e in t["evidence_incidents"]:
                    A("- [%s](%s)" % (e.get("ref"), e.get("url")))
            A("")

    A("\n---\n\n## advisory（本版不生成场景）\n")
    for a in advisories:
        A("\n### %s　%s\n" % (a["advisory_id"], a["name"]))
        A("> 机制组 `%s`　参数类型 **%s**\n" % (a["mechanism_group"], a["parameter_kind"]))
        A("%s\n" % (a.get("rule") or {}).get("statement", ""))
        for src in (a.get("rule") or {}).get("sources") or []:
            d = docs.get(src["doc_id"], {})
            A("- `%s`（%s，%s）" % (src["doc_id"], d.get("component", "?"), src.get("location", "")))
            for line in str(src["quote"]).split("\n"):
                A("  > %s" % line)
        A("\n- **本版为什么不支持**：%s" % a.get("why_not_supported"))
        A("- **要支持它还缺什么**：%s" % a.get("what_is_needed"))

    open(os.path.join(ROOT, "templates.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("templates.md 已生成：%d 条模板、%d 条 advisory" % (len(templates), len(advisories)))


if __name__ == "__main__":
    main()
