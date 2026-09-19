"""For each static-audit entry, list citation-like tokens and which image-changed services it names."""
import json, re
from pathlib import Path
ROOT = Path("/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/multisystem-audit-20260918/static-audit")
entries = json.load(open("entries.json"))
CITE = re.compile(r"`([^`]{3,140}?:[0-9][0-9,\-–]*)`|([A-Za-z0-9_./\-]+\.(?:java|yml|yaml|json|js|go|py|sh|xml|conf|properties|md|sql|txt)(?::[0-9][0-9,\-–]*)?)")
CHANGED = ["ts-order-service", "ts-order-other-service", "ts-payment-service",
           "ts-consign-price-service", "ts-station-food-service", "ts-travel-service"]
out = {}
for x in entries:
    lines = (ROOT / x["file"]).read_text(encoding="utf-8").splitlines()[x["line"]-1:x["end"]]
    text = "\n".join(lines)
    cites = []
    for m in CITE.finditer(text):
        c = m.group(1) or m.group(2)
        if c not in cites:
            cites.append(c)
    svc = [s for s in CHANGED if re.search(re.escape(s) + r"(?![-a-z])", text)]
    # short names used in reports (order, order-other, payment, travel ...)
    out[x["id"]] = {"cites": cites[:8], "n": len(cites), "changed": svc, "chars": len(text)}
json.dump(out, open("cites.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
for k, v in out.items():
    print(k, v["chars"], v["changed"], "|", "; ".join(v["cites"][:5])[:260])
