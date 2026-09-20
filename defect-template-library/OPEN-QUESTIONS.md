# OPEN-QUESTIONS.md —— 需要出题人拍板的问题

按提出时间排列。**2026-09-20 出题人一次性答复了 Q1–Q6，结论与落实方式记在每条下面。当前没有悬而未决的问题。**

## Q1 Principles of Chaos Engineering 算不算"公认准则"

`principlesofchaos.org` 是一页宣言式的文字，没有标注许可，也没有版本号。

**结论（2026-09-20）：算。** 落实：`chaos-principles` 现在可以作为规则依据。它的正文讲的是实验方法（稳态假设、变化真实世界事件、在生产运行、自动化、控制爆炸半径），不是组件机制，因此没有为它单独写模板；实际用到它的地方有两处：一是 `T-FALLBACK-03` 引用了它点名的那句系统性弱点清单（其中就有 improper fallback settings）；二是本库 `verdict` 块的设计（稳态 + 预期行为 + 备择解释）与 `experiment.actions` 的动作分类沿用了它的实验方法，这一点写在 `README.md` 里。许可上它仍按不可再分发处理（页面未标许可），`docs-cache/chaos-principles.txt` 只存被引用的段落。

## Q2 Wayback 快照能不能算"官方文档"

AWS Builders' Library 的 5 篇正文只能从 `web.archive.org` 的快照取到（原站点已改成前端渲染，脚本取不到正文）。

**结论（2026-09-20）：算。** 落实：`documents.yaml` 为这 5 份加了 `retrieved_via: web-archive-snapshot`、`snapshot_of`（原始网址）与 `snapshot_note`，把"正文取自快照、按口径视同原站点官方文档"写在登记里，供下游流水线与复核者分辨。它们支撑的模板不需要另找依据。

## Q3 厂商版权文档只入库摘录是否可接受

25 份来源（Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB、Principles of Chaos Engineering 等）没有再分发授权，`docs-cache/` 里只存本库引用到的段落及其小节标题。

**结论（2026-09-20）：可以。** 落实：维持现状。代价是这些文件不能拿来做"从文档反查还能抽出哪些规则"，需要全文时按 `documents.yaml` 登记的 `url` 到原站点读；全文始终保留在本地 `docs-cache/.full/`（`.gitignore` 排除），换口径后 `build_cache.py` 可随时重建。

## Q4 服务注册与发现要不要单独建一个机制组

任务书把"服务注册的 failFast"举为可新建机制组的例子。v1 初版没有建组，理由是只凑得出 2 条能写成阈值型或离散动作的规则。

**结论（2026-09-20）：建。** 落实：新建机制组 `service_discovery`，补抓了 Consul 健康检查与 Spring Cloud Netflix（Eureka）两份文档后凑齐 3 条模板——`T-DISCOVERY-01`（注册中心不可用时客户端解析不到地址）、`T-DISCOVERY-02`（实例已经不可用但仍被解析到）、`T-DISCOVERY-03`（注册状态不反映应用的真实健康）。建组理由与它在 `final-defects.json` 词表里的对应关系写在 `CHANGES.md`。

## Q5 `T-REPLICA-05` 是否越过了"不收优雅终止族"的边界

任务书把"滚动更新参数"列在 `replica_disruption` 组里，同时把"优雅终止族（SIGTERM、preStop、在途请求排空）"列为不收。

**结论（2026-09-20）：不越界，保留。** 落实：`T-REPLICA-05` 维持原样。它只判 `maxUnavailable` / `maxSurge` 与副本数、容量的关系，不涉及终止信号与连接排空。

## Q6 `redis-py` 换哪一份文档

`redis-py` 的 README 是上手介绍，没有超时与重连参数的说明，取不到可引用的原文，因此该组件目前没有模板落点。

**结论（2026-09-20）：先不管。** 落实：`redis-py` 保留在 `documents.yaml` 的阅读范围里，但不强行给它造落点；`stats.md` 的落点覆盖矩阵会继续把它列为"已登记文档但尚无模板落点"。下一版若要补，候选是 Redis 官方文档站的 Python 客户端配置页或 `redis-py` 的 API 文档。
