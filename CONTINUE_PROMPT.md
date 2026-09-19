你接手一项进行中的工作：对 train-ticket 和 sock-shop 两个微服务系统做韧性缺陷审计，覆盖源码、K8s 配置和运行时数据。目标是把已有的 108 条静态候选和运行时证据合并成一份去重、分级、可复核的终稿。全程用中文回复。

第一步：克隆私有仓库 https://github.com/Myzmzz/resbench-tt-ss-audit-20260918 ，完整阅读 HANDOFF.md，再动手。它记录了进度、已确认和已否定的结论、终稿规格、源码版本和约束。已完成的部分不要重做。HANDOFF.md 第 3 节里已核实的结论不要推翻，除非你拿到新的反证并写明。

然后按 HANDOFF.md 第 6 节的顺序续做：
1. 用与 _work/extract/TT-A.jsonl 相同的字段，把 static-audit/ 里的 TT-B（17 条）、TT-D（14 条）、TT-E（21 条）、SS（23 条）提取成 _work/extract/<组>.jsonl，并校验条数。
2. 根据 runtime-evidence/TT-rebuilt-image-provenance/partial/ 写该目录的 README.md：说明 6 个重打版本或被改过的服务到底改了什么。其中单独一节写 ts-travel-service 订阅了上游源码里没有的 ts-traceenv-test。
3. 按 HANDOFF.md 第 4 节的规格写 FINAL-DEFECTS.md 和 final-defects.json，包括：
   - 去重合并；
   - 每条标证据等级（R/C/S/X/M）；
   - 最值得关注的 10 条；
   - 注入实验设计，按"一次注入能同时验证哪几条"分组；
   - 附录。

需要读源码时，按 HANDOFF.md 第 5 节克隆对应版本：
- FudanSELab/train-ticket@313886e9；
- microservices-demo 各组件的对应 release；
- Myzmzz/resiliencebenchmark 分支 codex/stage2-d0-integration@d7afd49。

约束：
- 每条结论都要能追溯到证据文件或"源码路径:行号"。查不到就写"未核实"，拿不准就往低一档定级。
- 优雅退出类不算韧性缺陷（"恢复后回不来"除外）。安全问题、观测缺口、压测平台问题放附录。
- 故障注入只写设计、不执行。对被测系统的任何改动都要先问我。
- 不输出、不提交任何凭据。
- 如果能访问实验集群，只做只读操作，且只碰 train-ticket、sock-shop、observability、jaeger 这四个命名空间（共享集群）。
- 同时运行的子智能体不超过 3 个。

完成后提交并推送到同一仓库，提交信息写清为什么这样改。然后给我一份不超过 40 行的中文摘要，包括：
- 条目总数和各等级计数；
- 最值得关注的 10 条标题；
- 主要的合并与否定；
- 你认为证据最薄弱的 5 处。
