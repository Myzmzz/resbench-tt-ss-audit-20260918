# CHANGES.md —— 每次提交做了什么

## 提交 1：技术栈与文档范围

- `stack.md`：按 11 层列出要覆盖的组件与对应 `doc_id`；写明本版收什么、什么转 advisory、什么不收。
- `documents.yaml`：98 份文档的登记（doc_id、标题、组件、层、版本、网址、取回日期、sha256、许可说明），由 `build_cache.py` 生成。
- `docs-cache/<doc_id>.txt`：引用核对副本。
- 工具：`fetch_docs.py`（抓取与正文归一化）、`build_cache.py`（按许可口径生成入库副本与 `documents.yaml`）、`sources.tsv`（抓取输入）、`fetch-log.json`（抓取结果原始记录）。任务书的目录清单没有点名这两个脚本，但"引用必须能在本地副本里原样找到"要求抓取、归一化、核对是一条可重跑的链路，所以把它们一并入库。

### 本次需要说明的口径

1. **文档副本分两档入库。** 任务书要求 `docs-cache/` 存正文副本供引用核对，同时又要求在交付说明里点出"哪些引用来自不可再分发的来源"。两者合起来的做法是：开放许可的来源（74 份）入库全文；厂商版权文档或未标注许可的来源（24 份：Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB、Principles of Chaos Engineering）只入库本库实际引用到的段落及其所在小节标题。两档都能逐字复核，后者不构成整页再分发。全文保留在本地 `docs-cache/.full/`（`.gitignore` 排除），改口径后 `build_cache.py` 可随时重建。
2. **正文归一化规则**（影响"逐字"的含义，`README.md` 与 `fetch_docs.py` 头部有同样说明）：HTML 源码里的换行按 HTML 语义并成空白，一个段落落在一行；`<pre>` 块内换行保留；`h1`–`h6` 前加 `[[Hn]]` 标记供 `location` 定位；表格单元格用 ` | ` 分隔、一行一 `<tr>`，便于整行引用参数默认值表；`.md`/`.adoc`/`.txt`/`.rst` 与 `raw.githubusercontent.com` 的文件按纯文本处理，保留原换行。
3. **AWS Builders' Library 走 Wayback 快照。** `aws.amazon.com/builders-library/*` 现已跳转到前端渲染的站点，脚本取不到正文，5 篇取自 `web.archive.org` 的 2024 快照；许可判断按快照里嵌套的原始网址做，仍记为 © Amazon、不可再分发。
4. **机制组 slug 对齐审计终稿。** 取 `final-defects.json` 的 `family` 词表，只读词表本身，不从审计结论里抽规则。
