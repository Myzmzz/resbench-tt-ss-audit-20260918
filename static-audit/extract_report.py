"""从子任务的 JSONL 记录里提取最后一条助手文本（最终报告），原样存档。"""
import json, sys
last = None
for line in open(sys.argv[1], encoding="utf-8"):
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    msg = rec.get("message") or {}
    if rec.get("type") == "assistant" and isinstance(msg.get("content"), list):
        texts = [c.get("text", "") for c in msg["content"] if c.get("type") == "text"]
        if any(t.strip() for t in texts):
            last = "\n".join(texts)
if not last:
    sys.exit("未找到最终报告")
open(sys.argv[2], "w", encoding="utf-8").write(last)
print(f"{sys.argv[2].rsplit('/',1)[-1]}: {len(last)} 字符，候选 {last.count(sys.argv[3])} 条")
