"""Print report lines in a line range, skipping signal/runtime-check blocks, truncating long lines."""
import sys
path, start, end, width = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
lines = open(path, encoding="utf-8").read().splitlines()
skip = False
for no in range(start, min(end, len(lines)) + 1):
    line = lines[no - 1]
    if line.startswith("- "):
        skip = any(k in line[:16] for k in ("机制专属信号", "运行时要核对"))
    if skip or not line.strip():
        continue
    print(f"{no}:{line[:width]}")
