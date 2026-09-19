"""Assemble FINAL-DEFECTS.md and final-defects.json from the curated entry data.

The entry data lives in data_tt.py / data_ss.py / data_misc.py (plain Python literals) so that the
Markdown and the JSON are rendered from one source and cannot drift apart.
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path

from data_misc import (APPENDIX_MD, FAMILY_ORDER, HEADER_MD, INJECTION_MD, ORIGINAL_ID_NOTES,
                       TOP10, TOP10_INTRO_MD)
from data_ss import SS_ENTRIES
from data_tt import TT_ENTRIES

OUT_DIR = Path(__file__).resolve().parents[2]   # 仓库根目录
LEVELS = ["R", "C", "S", "X", "M"]
LEVEL_TEXT = {
    "R": "R（本轮运行时已复现）",
    "C": "C（运行对象/配置已核实存在，后果未实跑）",
    "S": "S（仅源码/清单静态推断）",
    "X": "X（已否定）",
    "M": "M（被本轮部署偏差掩盖）",
}
TT_FLOWS = ["搜索", "下单", "取消", "支付", "改签", "登录", "注册", "查单", "查联系人", "餐食配送",
            "管理后台", "UI入口", "其他", "全部"]
SS_FLOWS = ["浏览", "加购", "购物车", "结账", "登录", "注册", "发货", "全站"]
REQUIRED = ["id", "system", "title", "family", "dmode", "flows", "trigger", "consequence", "level",
            "evidence", "original_ids", "notes"]


def validate(entries: list[dict]) -> None:
    """Fail loudly on missing fields, unknown levels/flows/families or duplicate ids."""
    seen = set()
    for entry in entries:
        missing = [key for key in REQUIRED + ["families"] if key not in entry]
        assert not missing, (entry.get("id"), missing)
        assert entry["id"] not in seen, entry["id"]
        seen.add(entry["id"])
        assert entry["level"] in LEVELS, (entry["id"], entry["level"])
        allowed = TT_FLOWS if entry["system"] == "train-ticket" else SS_FLOWS
        for flow in entry["flows"]:
            assert flow in allowed, (entry["id"], flow)
        for fam in entry["families"]:
            assert fam in FAMILY_ORDER, (entry["id"], fam)
        assert entry["evidence"], entry["id"]


def render_entry(entry: dict) -> str:
    """Render one final entry in the fixed 8-line layout."""
    lines = [
        f"### {entry['id']}〔{entry['level']}〕{entry['title']}",
        f"- **机制族 / 失效模式**：{' + '.join(entry['family'])}；{entry['dmode']}",
        f"- **业务链路**：{'、'.join(entry['flows'])}",
        f"- **触发条件**：{entry['trigger']}",
        f"- **后果**：{entry['consequence']}",
        f"- **证据等级**：{LEVEL_TEXT[entry['level']]}。{entry.get('level_why', '')}".rstrip("。") + "。",
        f"- **证据位置**：{'；'.join(entry['evidence'])}",
        f"- **原编号 / 备注**：原编号 {'、'.join(entry['original_ids'])}。{entry['notes']}",
    ]
    return "\n".join(lines)


def level_table(entries: list[dict]) -> str:
    """System x evidence-level counts."""
    rows = ["| 系统 | R | C | S | X | M | 合计 |", "|---|---|---|---|---|---|---|"]
    total = Counter()
    for system, label in (("train-ticket", "train-ticket（TT）"), ("sock-shop", "sock-shop（SS）")):
        counts = Counter(e["level"] for e in entries if e["system"] == system)
        total.update(counts)
        rows.append(f"| {label} | " + " | ".join(str(counts[l]) for l in LEVELS)
                    + f" | {sum(counts.values())} |")
    rows.append("| 合计 | " + " | ".join(str(total[l]) for l in LEVELS) + f" | {sum(total.values())} |")
    return "\n".join(rows)


def flow_family_table(entries: list[dict]) -> str:
    """Business flow x mechanism family counts (an entry can land in several cells)."""
    fams = [f for f in FAMILY_ORDER if any(f in e["families"] for e in entries)]
    short = {f: f.replace("_", "_<wbr>") for f in fams}
    header = "| 系统 | 业务链路 | " + " | ".join(short[f] for f in fams) + " | 条目数 |"
    rows = [header, "|" + "---|" * (len(fams) + 3)]
    for system, flows in (("TT", TT_FLOWS), ("SS", SS_FLOWS)):
        sys_name = "train-ticket" if system == "TT" else "sock-shop"
        for flow in flows:
            subset = [e for e in entries if e["system"] == sys_name and flow in e["flows"]
                      and e["level"] != "X"]
            if not subset:
                continue
            counts = Counter(f for e in subset for f in e["families"])
            rows.append(f"| {system} | {flow} | " + " | ".join(str(counts[f]) if counts[f] else "·"
                                                             for f in fams) + f" | {len(subset)} |")
    return "\n".join(rows)


def top10_block(entries: list[dict]) -> str:
    """Render the ranked top-10 list, pulling title/level from the entry data itself."""
    by_id = {e["id"]: e for e in entries}
    lines = []
    for item in TOP10:
        entry = by_id[item["id"]]
        lines.append(f"**{item['rank']}. {entry['id']}〔{entry['level']}〕{entry['title']}**")
        lines.append("")
        lines.append(f"{item['why']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def mapping_table(entries: list[dict]) -> str:
    """Original id -> final id(s), including the runtime-only TT-RT ids."""
    mapping: "OrderedDict[str, list[str]]" = OrderedDict()
    for entry in entries:
        for raw in entry["original_ids"]:
            key = raw.split("（")[0].strip()
            mapping.setdefault(key, [])
            part = raw[len(key):]
            mapping[key].append(entry["id"] + part)
    for key, target in ORIGINAL_ID_NOTES.items():
        mapping.setdefault(key, []).append(target)

    def sort_key(item: str) -> tuple:
        """TT-A…TT-E, then SS, then the free-form notes (TT-RT-*, withdrawn judgements) last."""
        if item.startswith("TT-") and len(item.split("-")) > 1 and item.split("-")[1][:1].isalpha():
            prefix = "1" + item.split("-")[1][:1]
        elif item.startswith("SS-"):
            prefix = "2"
        else:
            prefix = "3"
        digits = "".join(ch for ch in item if ch.isdigit()) or "0"
        return (prefix, int(digits), item)

    rows = ["| 原编号 | 终稿去向 |", "|---|---|"]
    for key in sorted(mapping, key=sort_key):
        rows.append(f"| {key} | {'；'.join(mapping[key])} |")
    return "\n".join(rows), mapping


def main() -> None:
    entries = TT_ENTRIES + SS_ENTRIES
    validate(entries)
    table_map, mapping = mapping_table(entries)

    parts = [HEADER_MD.strip(), "",
             "## 1. 汇总", "",
             f"终稿共 **{len(entries)}** 条（TT {len(TT_ENTRIES)} 条、SS {len(SS_ENTRIES)} 条；其中 X 级 "
             f"{sum(e['level'] == 'X' for e in entries)} 条是已否定的原候选，保留在正文里便于追溯）。", "",
             "### 1.1 系统 × 证据等级", "", level_table(entries), "",
             "### 1.2 业务链路 × 机制族（不含 X 级；一条可同时计入多个链路和多个机制族，所以格子之和大于条目数）", "",
             flow_family_table(entries), "",
             TOP10_INTRO_MD.strip(), "", top10_block(entries), "",
             "## 2. train-ticket 条目", ""]
    parts += [render_entry(e) + "\n" for e in TT_ENTRIES]
    parts += ["## 3. sock-shop 条目", ""]
    parts += [render_entry(e) + "\n" for e in SS_ENTRIES]
    parts += [INJECTION_MD.strip(), "", APPENDIX_MD.strip(), "",
              "### 附录 F　原编号 → 终稿编号对照表", "",
              "108 条静态候选、5 条运行时编号（TT-RT-01～05）和偏差日志里已撤回的判断，逐条列出去向。"
              "括号里的“部分”表示该原条目被拆到多条终稿里。", "", table_map, ""]
    md = "\n".join(parts)
    (OUT_DIR / "FINAL-DEFECTS.md").write_text(md, encoding="utf-8")

    doc = {
        "title": "train-ticket 与 sock-shop 韧性缺陷审计终稿",
        "date": "2026-09-18",
        "levels": LEVEL_TEXT,
        "entries": [{key: e[key] for key in REQUIRED} for e in entries],
        "top10": TOP10,
        "original_id_map": mapping,
    }
    (OUT_DIR / "final-defects.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    print("entries", len(entries), Counter((e["system"], e["level"]) for e in entries))
    print("mapped original ids", len(mapping))


if __name__ == "__main__":
    main()
