# train-ticket / sock-shop 韧性缺陷审计 · 交接说明（2026-09-19）

原始需求（用户 2026-09-18）：详细核对 train-ticket、sock-shop 的源码、K8s 配置、运行时数据，详尽排查其韧性缺陷；可以先在新/旧环境上部署。
本仓库是审计的全部可上传材料。续做者请先读完本文件再动手。

---

## 1. 口径与约束（用户定的，必须遵守）

- 回复一律用中文；标识符保持原文。
- 可信第一：每条结论都要能追溯到证据文件或"源码路径:行号 / 清单文件+字段"。查不到就写"未核实"，拿不准就往低一档定级。
- **优雅退出**（graceful_shutdown 族：SIGTERM、preStop、在途请求排空）**不算韧性缺陷**，放进排除清单；例外是"故障恢复后回不来"，这类要保留。
- 纯安全问题（泄露、越权、注入）、观测缺口、压测平台自身的问题，都放附录，不计入韧性缺陷。
- **故障注入只写设计、不执行**；执行前必须征得用户同意。被测系统的任何改动（改配置、重启、删 Pod）也要先征得同意。
- 不输出、不提交任何凭据。manifests/ 已按键名（pass/secret/token/key/credential）打码，没有导出 Secret 对象。
- 实验集群（腾讯云新环境）是**共享集群**，只能动自己的命名空间：train-ticket、sock-shop、observability、jaeger。
- 子智能体并发不要超过 3 个：上次同时开 8 个撞了账号额度上限（HTTP 429），任务全部中断。

## 2. 进度

| 部分 | 状态 | 位置 |
|---|---|---|
| 新环境部署 | 完成。train-ticket 47 个服务、sock-shop 14 个组件全部就绪（09-19 00:42 UTC 复查仍全部可用） | DEVIATIONS.md（14 项偏差） |
| 静态排查 | 完成。6 组共 108 条候选 | static-audit/*.md，索引 INDEX.md |
| 10 分钟基线 | 完成。TT 第 2 次：1500 个请求 0 失败，search p95 139ms，下单 p95 333ms。SS：1955 个请求 0 失败，p95 130ms | runtime-evidence/TT-baseline-r2.txt、SS-baseline/ |
| 运行时证据 | 大部分完成（见第 3 节） | runtime-evidence/ |
| 结构化提取 | **部分完成**：TT-A（18 条）、TT-C（15 条）已完成；TT-B（17）、TT-D（14）、TT-E（21）、SS（23）未做 | _work/extract/ |
| 汇总中间件 | 部分完成：entries.json（108 条的标题/文件/行号）、cites.json（每条引用）、notes-runtime.md、gen.py（渲染器，要求 data_tt.py / data_ss.py / data_misc.py，这三个数据文件没写出来） | _work/consolidation/ |
| 镜像来源比对 | **部分完成**：脚本和比对摘要已有，README 未写。4.7G 镜像层留在原机器，没有上传 | runtime-evidence/TT-rebuilt-image-provenance/（diff_images.py、partial/） |
| 终稿 FINAL-DEFECTS.md / final-defects.json | **未开始** | — |
| 注入实验设计 | **未开始**（只写设计） | — |

## 3. 已确认的结论

### 3.1 运行时已复现（证据等级 R）

**train-ticket**

1. **数据库连接放不下。** 25 个用 tsdb 的服务，每实例 Hikari 池 10，合计 270；稳态实际 276、峰值 286。默认 max_connections 只有 214：Docker 29 容器的 nofile=1024，MySQL 自动压低了上限。结果是服务起齐后，最后启动的几个会 Too many connections 崩溃重启。
   - 证据：TT-db-connection-exhaustion/、RES-resource-pool-metrics/
   - 偏差 #13 把上限临时调到 400，不持久：MySQL 一重启或切主就回到 214。09-19 00:42 复查仍是 400，tsdb-mysql-2 已运行约 17.9 h。
2. **Nacos 不可用 → 业务服务 fail-fast，崩溃循环。** Nacos 恢复后，最慢的服务在 T0+764 s 才回来（与第 1 条叠加，不能单独归因）。证据：TT-startup-hard-dependency-on-nacos/。
3. **全新部署起不来的三处**（打偏差之前已实测复现，证据目录里有修复前记录；终稿记 R，备注写"已被偏差 #x 掩盖"）：
   - Nacos 外部库没建表（#12，真因证据 TT-nacos-coldstart-deadlock/root-cause-no-datasource.txt）；
   - xenon 用 IPv6 ::1 做健康检查被拒，选不出主（#5，TT-xenon-ipv6-localhost/）；
   - 业务 Pod 启动依赖 NFS 上的 javaagent（#7，TT-nfs-javaagent-startup-dependency/）。
4. **冷启动首请求约 9.7–10 s**，撞上压测客户端 10 s 超时，第一次基线因此中止。证据：TT-baseline-abort-first-run.txt。
5. **幽灵订单**（TT-C5 / TT-A7）：客户端 10 s 超时判失败，服务端却已写单，留下一笔未支付、没人清理的订单。证据：TT-ghost-order-after-client-timeout/README.txt。
6. **ticket-office 每空闲 8 小时崩一次**（TT-B17 升为 R，并补上触发条件）：
   - 机制：进程只有一条 MySQL 连接，空闲满 wait_timeout=28800 s 被服务端断开；驱动报 PROTOCOL_CONNECTION_LOST，代码没有 'error' 监听，进程退出。
   - 副作用：每次重启都再插一行种子数据，已累计 4 行。
   - **可证伪预测**：下一次崩溃约在 2026-09-19 08:29 UTC。
   - 证据：TT-ticket-office-idle-connection-crash/README.txt
7. **配置事实**（TT-tsdb-runtime-config/、TT-network-and-health/、RES-resource-pool-metrics/）：
   - 数据库：业务库 32 张表 MyISAM、3 张 InnoDB；半同步超时 1e18 且 wait_no_slave=ON；expire_logs_days=0（binlog 永不清理）。
   - 健康检查：/actuator/health 返回 403，探针只能看 TCP。
   - 网络：连不存在的 IP 约 127 s 才失败（tcp_syn_retries=6）。
   - 资源：内存 request 100Mi，实际工作集 630–850Mi；CPU request 10m、limit 1.5。节流只出现在 JVM 启动期，稳态没有任何 Pod 节流超过 1%（steady-state-0916-0931.txt）。
8. **扇出**：一次搜索是 12 次 HTTP + 19 次 DB，一次下单是 28 次 HTTP + 30 次 DB（TT-call-graph-baseline/fanout.txt）。

**sock-shop**

1. **queue-master 发货全部失败却照常确认。** 15 分钟内收到 433 条、失败 432 条（容器里没有 docker socket）；队列积压 0；shipping-task 队列 durable=false（SS-queue-master-swallowed-failures/）。
2. **CPU limit 按平均值配、没留突发余量。** 5 个用户时 carts 节流 33%、orders 24%，而平均用量只有约 0.06 核；空闲时节流为 0。与 GET /cart P99 600ms 同时出现（RES-resource-pool-metrics/ss-throttle-load-vs-idle.txt）。
3. **有状态组件缺保护。** 全部 BestEffort、没有持久卷、没有 PDB；Redis 8.10.1 没开持久化（save "" 且 appendonly no）；Java 服务是 8u111，front-end 是 Node 4.8.0（SS-runtime-config/）。
4. **购物车明细只增不删。** carts-db 里 cart 0 条、item 580 条（结账只删购物车、不删明细）。

### 3.2 基线下没复现（**不能判否**，归为"需加压/注入验证"）

- MyISAM 表锁等待为 0；order/gateway 没有 CLOSE_WAIT；Hikari 没有排队。
- 另查过 voucher-service：每个请求新建连接，不受空闲回收影响（阴性对照）。

### 3.3 已否定（X）或已更正

- "Nacos 冷启动死锁"不成立。真因是外部库缺建表；偏差 #9–#11 已撤回。
- "train-ticket 的 java:8-jre 不感知容器限额"不成立：实际是 Temurin 8u482。
- TT-A14（登录依赖验证码服务）只在 UI 带验证码时成立，基准负载不触发（Jaeger 显示登录只有网关→auth 一跳）。
- 本集群 cAdvisor 只有 Pod 级 cgroup，没有 container 标签。按容器查会得到"无节流"的错误结论，要按 pod 聚合。

### 3.4 附录类发现（不计入韧性缺陷）

**镜像来源 / 供应链**
- ts-order 1.0.1、consign-price 1.0.1、station-food 1.0.1、order-other 1.0.2、payment 1.0.2 都被重打过版本。
- 运行中的 ts-travel-service:1.0.0 向 Nacos 订阅了上游源码里没有的 `ts-traceenv-test`；Harbor 上 1.0.0 标签在 2026-03 被反复重推。
- 全部 Deployment 用可变标签；基础镜像 `FROM node` / `FROM python:3` 没固定版本，ticket-office 实际跑 Node v25.8.1。
- **结论依赖这 6 个服务源码的条目，一律标"运行镜像与上游源码不一致，待镜像比对"。**

**观测缺口**
- SS 的 4 个 Java 服务 zipkin 关闭；queue-master 的 /metrics 不是 Prometheus 格式；rabbitmq 没有 exporter。
- 旧 Prometheus 抓不到 SS，已加偏差 #14。
- TT 有 6 个组件没有链路：rabbitmq、avatar、news、ticket-office、ui-dashboard、voucher。

**压测平台问题**
- TT 压测器的中止判断没有预热期，冷启动时必然中止。
- locust 容器 nofile 只有 1024。

**安全旁注**
- SS front-end 会暴露全部地址和卡片、在日志里记录密码和卡号；重复注册返回 500。

## 4. 终稿规格（FINAL-DEFECTS.md + final-defects.json）

1. **去重合并**：同一根因合并成一条，例如 TT-A8 与 TT-B01、TT-A3 与 TT-RT-03、TT-A11 与 TT-E 组的资源条目、多组重复出现的"无 PDB/单副本"。最终编号 TT-01…、SS-01…，每条写"原编号：…"。
2. **每条 5–8 行**：
   - 标题：一句话说清什么条件下出什么事；
   - 机制族 / 失效模式：沿用静态报告的 family 名和 D1–D6，不要另造；
   - 影响的业务链路；
   - 触发条件；
   - 后果；
   - 证据等级；
   - 证据位置；
   - 备注：被哪条偏差掩盖、有条件成立、待镜像比对等。
3. **证据等级**：
   - R = 本轮运行时复现；
   - C = 运行对象里已核实缺陷存在，但后果没有实跑；
   - S = 只有源码/清单静态推断；
   - X = 已否定（写明被什么否定）；
   - M = 被本轮部署偏差掩盖（写偏差号）。
4. **汇总与重点**：按系统 × 等级计数；列出"最值得关注的 10 条"，按影响面、触发概率、是否已复现排序，并写明理由。时间紧可以省掉"链路 × 机制族"交叉表。
5. **注入实验设计**（只写不做）：把 S/C 级、能靠注入激活的条目，按"同一个注入能同时验证哪几条"分组。每组写目标对象、故障类型、时长、负载 profile、要观察的信号、判定标准。
6. **附录**：排除清单、安全、观测缺口、平台问题、镜像来源。

_work/extract/*.jsonl 的字段：id, claim, family, dmode, flows, default_load, default_load_why, trigger, consequence, key_evidence, (fanout_numbers), code_services, weak_conditions, runtime_checks, report_conf, overlaps。

## 5. 源码与环境

静态报告里的路径前缀对应关系：
- `TT源码/`、`U/` = FudanSELab/train-ticket @ 313886e9（2022-11-01）
- `D0/`、`E/` = Myzmzz/resiliencebenchmark 分支 codex/stage2-d0-integration @ d7afd49（含压测器 environment/workloads/…、repairs/…）
- `清单/`、`M/` = 本仓库 manifests/（旧环境导出、已打码）
- `~/.m2/...` = 原机器上的 Maven 缓存，新环境可能没有；需要时按 pom 版本拉取

| 组件 | 仓库 | 版本（审计所用） |
|---|---|---|
| sock-shop carts / catalogue / front-end / orders | github.com/microservices-demo/* | 0.4.8 / 0.3.5 / 0.3.12 / 0.4.7 |
| sock-shop payment / queue-master / shipping / user | 同上 | 0.4.3 / 0.3.1 / 0.4.8 / 0.4.7 |
| sock-shop 部署清单 | microservices-demo/microservices-demo | 9dff06f |

实验环境：
- 新环境是腾讯云 2 节点共享集群（vm-0-10 worker、vm-0-13 控制面，k8s 1.31，cri-dockerd + Docker 29，cgroup v2）。kubeconfig 只在原机器上，**没有上传**。
- 我方在集群上的资源仍在：命名空间 train-ticket、sock-shop、observability、jaeger；ClusterRole/Binding resbench-audit-prometheus、resbench-audit-kube-state-metrics。是否清理由用户决定。
- 镜像仓库 Harbor：http://1.94.151.57:85，项目 train-ticket、sock-shop 公开。registry v2 要先匿名取令牌：`/service/token?service=harbor-registry&scope=repository:<项目>/<仓库>:pull`；标签指向 OCI index，要先选 linux/amd64 的 manifest。
- 查询技巧：Prometheus 和 Jaeger 可以走 API Server 服务代理 `kubectl get --raw /api/v1/namespaces/observability/services/<svc>:<port>/proxy/...`；cAdvisor 数据要按 pod 聚合。

## 6. 续做步骤（建议顺序）

1. 按 _work/extract/TT-A.jsonl 的字段，把 TT-B、TT-D、TT-E、SS 提取成 _work/extract/<组>.jsonl，并校验条数（17 / 14 / 21 / 23）。
2. 根据 partial/ 的比对结果写 runtime-evidence/TT-rebuilt-image-provenance/README.md：6 个服务相对 1.0.0 和上游改了什么、判定（植入故障 / 功能改动 / 无差异 / 无法判定），单独一节写 ts-traceenv-test。Harbor 可达且确有必要时，才重跑 diff_images.py（全量约 4.7G）。
3. 按第 4 节规格合并，写 FINAL-DEFECTS.md 和 final-defects.json。可以沿用 _work/consolidation/gen.py 的"一份数据同时渲染 MD 和 JSON"做法，也可以重写。
4. 写注入实验设计（只写设计）。
5. 可选（需集群访问，只读）：
   - 核对 ticket-office 是否在 09-19 08:29 UTC 左右再次崩溃（restartCount 应从 2 变 3，ts.office 应为 5 行）；
   - 复查 tsdb 的 max_connections 是否仍为 400。

## 7. 续做 prompt

见仓库根目录 CONTINUE_PROMPT.md（与交付给用户的那段相同）。
