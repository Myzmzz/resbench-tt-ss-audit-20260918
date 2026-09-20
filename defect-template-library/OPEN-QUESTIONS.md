# OPEN-QUESTIONS.md —— 需要出题人拍板的问题

按提出时间排列，已定的会标注结论。

## Q1 Principles of Chaos Engineering 算不算"公认准则"

`principlesofchaos.org` 是一页宣言式的文字，没有标注许可，也没有版本。它被广泛引用，但和 Google SRE 书、云厂商可靠性框架不是一个量级的材料。当前处理：登记进 `documents.yaml`，许可按不可再分发处理；**暂不作为任何模板的唯一依据**。要不要允许它单独支撑一条规则，需要拍板。

## Q2 Wayback 快照能不能算"官方文档"

AWS Builders' Library 的 5 篇正文只能从 `web.archive.org` 的快照取到（原站点已改成前端渲染）。当前处理：照常引用，来源仍记为 © Amazon，并在 `documents.yaml` 里保留快照网址。若认为快照不算官方文档，这 5 篇支撑的模板需要另找依据或降级为 advisory。

## Q3 厂商版权文档只入库摘录是否可接受

24 份来源（Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB 等）没有再分发授权，`docs-cache/` 里只存本库引用到的段落。好处是可复核且不整页再分发，代价是这些文件不能拿来做"从文档反查还能抽出哪些规则"。若要求全文可复核，需要出题人确认再分发口径。
