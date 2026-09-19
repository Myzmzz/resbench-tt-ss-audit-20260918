你接手一项进行中的工作：对 train-ticket（TT）和 sock-shop（SS）两个微服务系统做韧性缺陷审计，覆盖源码、K8s 配置和运行时数据。目标是把已有的 108 条静态候选和运行时证据合并成一份去重、分级、可复核的终稿。全程用中文回复。

【先读】
克隆私有仓库 https://github.com/Myzmzz/resbench-tt-ss-audit-20260918 ，完整阅读 HANDOFF.md。里面有进度、已确认和已否定的结论、终稿规格、源码版本、集群接入方式（第 5.1 节）和续做步骤。
- 已完成的部分不要重做。
- 第 3 节里已核实的结论不要推翻，除非你拿到新的反证并写明。

【集群环境】共两套 K8s 集群。kubeconfig 不在仓库里，由我单独提供。

新环境（腾讯云，主实验环境）：
- 接入：API 地址 https://62.234.93.223:6443；kubeconfig 放在 ~/.kube/resbench-new-config（context 名 kubernetes-admin@kubernetes）。
- 节点：2 个。vm-0-13-ubuntu 是控制面，vm-0-10-ubuntu 是工作节点。k8s 1.31，运行时 cri-dockerd + Docker 29，cgroup v2，存储类 openebs-hostpath。
- 部署状态：两个系统都已全部部署并就绪。
  - TT：47 个服务、Nacos 3 副本，以及 tsdb、nacosdb 两套 MySQL。
  - SS：14 个组件。
- 观测栈：我们自己在 observability 命名空间里搭的，包括 prometheus:9090、jaeger-query:16686、otel-collector、kube-state-metrics。
- 这是共享集群。你只能碰 train-ticket、sock-shop、observability、jaeger 这四个命名空间；observe、social-network、sregym、chaos-mesh 等是别人的。

旧环境（tcse-v100）：
- 接入：API 地址 https://122.112.193.220:6443；kubeconfig 放在 ~/.kube/coroot-config。这个文件没有 current-context，每条命令都必须加 --context=kubernetes-admin@kubernetes，否则会静默连到别的集群。
- 节点：3 个，tcse-v100-01 到 03，每台 8 核 64G，k8s 1.28。
- 部署状态：TT（51 个对象）和 SS（14 个对象）都处于待机，副本全部为 0，原副本数记在注解 resiliencebenchmark.io/standby-replicas 里。本审计用的部署清单就是从这里导出的。
- 这套集群同时跑着 Stage-2 评测平台、otel-demo-01 到 05 的副本和 BladeAI。
- observability 命名空间里有 prometheus、jaeger-query、otel-collector、loki。

镜像仓库：Harbor，地址 http://1.94.151.57:85，train-ticket 和 sock-shop 两个项目是公开的。

【查询要点】
- 只用 kubectl 访问，不要用口令登录主机。
- Prometheus 和 Jaeger 走 API Server 服务代理，不需要端口转发。例如：kubectl get --raw "/api/v1/namespaces/observability/services/prometheus:9090/proxy/api/v1/query?query=…"。
- 新环境的 cAdvisor 只有 Pod 级数据，PromQL 要按 pod 聚合。
- 查 MySQL：先找 role=leader 的 Pod（目前是 tsdb-mysql-2 和 nacosdb-mysql-0），再 kubectl exec 进去，执行 mysql -uroot -h127.0.0.1。只做 SELECT 和 SHOW。
- 新环境 tsdb 的 max_connections=400 是临时调的。MySQL 一旦重启或切主，就会回到 214。
- 压测命令、镜像 digest、读取结果的方法，都在 HANDOFF.md 第 5.1 节。

【权限】
- 可以直接做：只读查询，包括 get、describe、logs，exec 里的只读命令，以及 Prometheus 和 Jaeger 查询。
- 必须先问我：压测、部署、扩缩容、重启、改配置、清理资源、故障注入，以及旧环境上的任何写操作。
- 这一轮故障注入只写设计，不执行。

【续做】按 HANDOFF.md 第 6 节的顺序：
1. 用 _work/extract/TT-A.jsonl 的字段，把 static-audit/ 里的 TT-B（17 条）、TT-D（14 条）、TT-E（21 条）、SS（23 条）提取成 _work/extract/<组>.jsonl，并校验条数。
2. 根据 runtime-evidence/TT-rebuilt-image-provenance/partial/ 写该目录的 README.md，说明 6 个被重打或被改过的服务到底改了什么。其中单独一节写 ts-travel-service 订阅了上游源码里没有的 ts-traceenv-test。需要时可以从 Harbor 重新拉镜像层来比对。
3. 用集群补只读核对：
   - 看 ticket-office 是否在 2026-09-19 08:29 UTC 前后再次崩溃（restartCount 应从 2 变 3，ts.office 表应从 4 行变 5 行）；
   - 把 S 级里只需只读查询就能核实的条目升为 C 级。
4. 按 HANDOFF.md 第 4 节的规格写 FINAL-DEFECTS.md 和 final-defects.json，包括：
   - 去重合并；
   - 每条标证据等级（R/C/S/X/M）；
   - 最值得关注的 10 条；
   - 注入实验设计，按"一次注入能同时验证哪几条"分组；
   - 附录。

需要读源码时，按 HANDOFF.md 第 5 节克隆对应版本：FudanSELab/train-ticket@313886e9、microservices-demo 各组件的对应 release、Myzmzz/resiliencebenchmark 分支 codex/stage2-d0-integration@d7afd49。

【约束】
- 每条结论都要能追溯到证据文件或"源码路径:行号"。查不到就写"未核实"，拿不准就往低一档定级。
- 优雅退出类不算韧性缺陷（"恢复后回不来"除外）。安全问题、观测缺口、压测平台问题放附录。
- 不输出、不提交任何凭据，包括 kubeconfig 的内容。
- 同时运行的子智能体不超过 3 个。

【交付】
完成后提交并推送到同一仓库，提交信息写清为什么这样改。然后给我一份不超过 40 行的中文摘要，包括：
- 条目总数和各等级计数；
- 最值得关注的 10 条标题；
- 主要的合并与否定；
- 证据最薄弱的 5 处。
