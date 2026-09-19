"""Extract compact per-entry fields from the six static audit reports (read-only)."""
import json, re, sys
from pathlib import Path

ROOT = Path("/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/multisystem-audit-20260918/static-audit")
FILES = ["TT-A-entry-auth.md", "TT-B-search-path.md", "TT-C-order-path.md",
         "TT-D-payment-messaging.md", "TT-E-infra-k8s.md", "SS-sock-shop.md"]
HEAD = re.compile(r"^###\s+(TT-[A-E]\d+|SS-\d+)(.*)$")
FIELD = re.compile(r"^- (?:\*\*)?([^*：:]{1,24}?)(?:\*\*)?[：:](?:\*\*)?\s*(.*)$")
KEYS = {"机制族 / 失效模式": "family", "位置": "loc", "业务影响": "impact", "置信度": "conf",
        "触发设想": "trigger", "触发设想与量级": "trigger", "旧环境": "oldenv"}

entries = []
for name in FILES:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    cur = None
    for i, line in enumerate(lines, 1):
        m = HEAD.match(line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "file": name, "line": i, "f": {}}
            entries.append(cur)
            continue
        if line.startswith("## ") and cur:
            cur["end"] = i - 1
            cur = None
            continue
        if cur is None:
            continue
        cur["end"] = i
        fm = FIELD.match(line)
        if fm:
            key = fm.group(1).strip().rstrip("：:")
            if key in KEYS:
                cur["_k"] = KEYS[key]
                cur["f"].setdefault(KEYS[key], "")
                cur["f"][KEYS[key]] += fm.group(2).strip()
                continue
            cur["_k"] = None
        elif line.startswith("  ") and cur.get("_k"):
            cur["f"][cur["_k"]] += " / " + line.strip().lstrip("- ")

json.dump(entries, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(len(entries), "entries")
