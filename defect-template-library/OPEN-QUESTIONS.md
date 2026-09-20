# OPEN-QUESTIONS.md —— 需要出题人拍板的问题

按提出时间排列，已定的会标注结论。

## Q1 Principles of Chaos Engineering 算不算"公认准则"

`principlesofchaos.org` 是一页宣言式的文字，没有标注许可，也没有版本。它被广泛引用，但和 Google SRE 书、云厂商可靠性框架不是一个量级的材料。当前处理：登记进 `documents.yaml`，许可按不可再分发处理；**暂不作为任何模板的唯一依据**。要不要允许它单独支撑一条规则，需要拍板。

## Q2 Wayback 快照能不能算"官方文档"

AWS Builders' Library 的 5 篇正文只能从 `web.archive.org` 的快照取到（原站点已改成前端渲染）。当前处理：照常引用，来源仍记为 © Amazon，并在 `documents.yaml` 里保留快照网址。若认为快照不算官方文档，这 5 篇支撑的模板需要另找依据或降级为 advisory。

## Q3 厂商版权文档只入库摘录是否可接受

24 份来源（Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB 等）没有再分发授权，`docs-cache/` 里只存本库引用到的段落。好处是可复核且不整页再分发，代价是这些文件不能拿来做"从文档反查还能抽出哪些规则"。若要求全文可复核，需要出题人确认再分发口径。

## Q4 服务注册与发现要不要单独建一个机制组

任务书把「服务注册的 failFast」举为可新建机制组的例子。本版已登记 Nacos 的 Java SDK 配置项与容灾文档、Spring Cloud LoadBalancer 文档，但没有为它单独建组，原因是能写成阈值型或离散动作的规则目前只凑得出两条（客户端本地容灾开关、注册失败是否阻塞启动），达不到每组 3 条的要求。可选做法：一是建组并接受它只有 2 条；二是并入 `connection_lifecycle`（但语义上并不贴切）；三是推到 v2，先补文档再建组。当前按第三种处理。

## Q5 `T-REPLICA-05` 是否越过了"不收优雅终止族"的边界

任务书把「滚动更新参数」列在 `replica_disruption` 组里，同时又把「优雅终止族（SIGTERM、preStop、在途请求排空）」列为不收。`T-REPLICA-05` 只判 `maxUnavailable` / `maxSurge` 与副本数、容量的关系，不涉及终止信号与连接排空，按这个界线是收的。若认为滚动更新整体都算发布过程、不属于故障模型内的韧性，这条应当移出。

## Q6 `redis-py` 换哪一份文档

`redis-py` 的 README 是上手介绍，没有超时与重连参数的说明，取不到可引用的原文，因此该组件目前没有模板落点。候选是 Redis 官方文档站的 Python 客户端配置页或 `redis-py` 的 API 文档，需要确认哪一份算"组件官方文档"。
