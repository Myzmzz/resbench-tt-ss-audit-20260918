# -*- coding: utf-8 -*-
"""终稿的公共部分：机制族顺序、头部、Top10、注入设计、附录、原编号补充去向。"""

# CODEBOOK 的机制族，外加消息投递语义（wave2 建议的 delivery_ack，本轮仍按原报告写法保留）
FAMILY_ORDER = [
    "deadline_timeout", "retry_backoff", "circuit_isolation", "fallback_degradation",
    "idempotency_compensation", "delivery_semantics", "replica_disruption", "health_probe",
    "load_shedding_admission", "resource_limit", "other",
]

HEADER_MD = """# train-ticket 与 sock-shop 韧性缺陷审计终稿

本文件由 `_work/consolidation/gen.py` 从 `data_tt.py` / `data_ss.py` / `data_misc.py` 渲染，
Markdown 与 `final-defects.json` 出自同一份数据，不会漂移。

**输入**：`static-audit/` 的 6 组共 108 条静态候选（结构化形式在 `_work/extract/*.jsonl`）、
`runtime-evidence/` 的本轮运行时证据、`manifests/` 的部署清单、`DEVIATIONS.md` 的 14 项部署偏差。

**证据等级**

| 级 | 含义 |
|---|---|
| R | 本轮运行时已复现 |
| C | 运行对象或配置里已核实缺陷确实存在，但后果没有实跑出来 |
| S | 只有源码 / 清单的静态推断 |
| X | 已否定（写明被什么否定） |
| M | 被本轮部署偏差掩盖（写明偏差号） |

**口径**（沿用交接约定）

- 优雅退出族（SIGTERM、preStop、在途请求排空）不算韧性缺陷，例外是"故障恢复后回不来"。
- 纯安全问题、观测缺口、压测平台自身问题都在附录，不计入韧性缺陷条目。
- 每条的证据位置都能落到文件或"源码路径:行号"；查不到的写"未核实"，拿不准的往低一档定级。
- 故障注入只写设计，本轮没有执行。
"""

TOP10_INTRO_MD = """## 1.3 最值得关注的 10 条

排序依据：先看是否已复现（R > C > S），再看影响面（全站 / 关键链路 / 单一功能），
最后看触发概率（默认负载就会撞上 > 需要注入 > 需要自定义负载）。

紧随其后的是 TT-27（order 接收队列停止排空、不自愈）：旧环境真实发生过、需要人工重启，机制链完整，但本轮基线下 CLOSE_WAIT 与连接池排队三个现象全为 0，因此它是最值得优先做注入验证的一条（见注入设计 G4）。
"""

# 原编号里不作为终稿条目、但需要交代去向的（运行时编号、已撤回的判断）
ORIGINAL_ID_NOTES = {
    "TT-RT-05": "TT-33（ticket-office 空闲连接崩溃）",
    "N-01（OTel 同步导出）": "附录 D（观测缺口）——负控制，未成立",
    "T-03（重试放大）": "附录 A（排除清单）——TT 侧无实例，SS 侧仅 SS-14 的潜在 D3",
}

TOP10 = [
    dict(rank=1, id="TT-06", why="服务起齐就必然发生，不需要任何注入：需求 270 条连接而实际上限只有 214，最后启动的几个服务直接崩溃重启。"
                                 "而且它是个「配置谎言」——configmap 写的是 65535，运维照着配置看不出问题。偏差 #13 的临时 SET GLOBAL 不持久，MySQL 一重启就回到 214。"),
    dict(rank=2, id="TT-01", why="影响面是全系统，且本轮实测 37 个 Pod 同时 CrashLoopBackOff、最慢的服务 764 秒才回来。"
                                 "任何涉及重启的运维动作（包括基准自己的 restart-application-deployments 重置流程）都会撞上它。"),
    dict(rank=3, id="SS-01", why="默认负载下 100% 持续发生（15 分钟 432/433 条失败），而 checkout 成功率 100%、队列积压为 0——"
                                 "从任何业务指标都看不出来。对一个韧性基准来说，这种「注入了故障也测不出来」的灰色故障最危险。"),
    dict(rank=4, id="TT-13", why="已复现的数据一致性缺陷：客户端判失败、服务端已落库，留下没人回收的幽灵订单。"
                                 "冷启动首请求 9.7–10 s 正好卡在客户端 10 s 超时线上，第一次基线就因此中止。"),
    dict(rank=5, id="TT-11", why="全审计跨组重复最多的一条（入口、查询、下单、基础设施四组各记一次），影响 40 个服务的全部服务间调用。"
                                 "每进程只有 10 条连接且借不到无限等，单个慢依赖能跨业务链路污染；清除故障后还要约 120 秒才恢复，超过常用的 60 秒恢复判据。"),
    dict(rank=6, id="TT-02", write_hint="", why="故障会一直持续到 Nacos 自己改判为止，而不是一个探测周期——K8s 的 readiness 对服务间流量完全无效。"
                                 "旧环境已经因此出过事故（08-22），配置层根因至今未改。"),
    dict(rank=7, id="TT-15", why="把依赖故障翻译成「成功」，直接损害基准的可观测性：注入了故障但 SLO 看不见。"
                                 "取消链路把任何异常包成 status=1，搜索链路把 basic 故障变成 200+空列表，两处都会让评测得出错误结论。"),
    dict(rank=8, id="SS-13", why="默认负载（仅 5 个用户）就让 carts 节流 33%、orders 节流 24%，而平均用量只有约 0.06 核——"
                                 "limit 是按平均值配的，完全没留突发余量。空闲时节流为 0 的对照组使因果非常清楚。"),
    dict(rank=9, id="TT-30", why="影响面最大的结构性问题：41 个服务单副本、没有 PDB、没有反亲和，而新环境只有 2 个节点且 TT 全被固定在 vm-0-10。"
                                 "排空一个节点就能让下单链路和数据库仲裁组同时失去多数派。"),
    dict(rank=10, id="TT-41", why="本轮反编译部署镜像才发现的：主查询入口 POST /trips/left 的第一行，"
                                  "就同步调用一个上游源码里不存在、Nacos 里也没有实例的 ts-traceenv-test，"
                                  "而且默认走无超时的共享连接池。它把 TT-02（陈旧实例）和 TT-11（无超时+10 条连接）"
                                  "串成了一条现成的放大链路，入口正好在 SLO 路径上。"
                                  "静态审计看的是上游源码，不可能发现它。"),
]

INJECTION_MD = """## 4. 注入实验设计（只写设计，本轮未执行）

分组原则：一次注入尽量同时验证多条候选，并且每组都配一个预期「不受影响」的阴性对照，用来区分
「机制成立」和「整个系统都垮了」。执行前需要用户同意，并遵守只动 train-ticket / sock-shop /
observability / jaeger 四个命名空间的约定。

**通用前置**：负载用 baseline profile；每组注入前先跑 5 分钟稳态取基线；TT 压测器没有预热期，
服务刚重启时首请求约 10 s 会触发中止，要等几分钟再开始（见附录 D）。

### G1　Nacos 三副本全停 5 分钟后恢复
- **对象 / 故障**：nacos StatefulSet 缩到 0，保持 5 分钟，再恢复到 3。
- **负载**：baseline，全程不停。
- **同时验证**：TT-01（注册 fail-fast 导致 CrashLoop；观察 restartCount 与退避台阶 10/20/40…300 s）、
  TT-02（恢复后实例列表陈旧多久）、TT-03（三副本注册表是否分歧）、TT-40（StatefulSet 有序启动是否互相挡住）。
- **信号**：业务 Pod 的 lastState.terminated 时间与 Nacos 恢复时间之差；异常栈抛出点是否为 NacosServiceRegistry.register；
  Ready 时间差是否呈退避台阶。
- **判定**：若恢复滞后 > 300 s 且呈台阶状，TT-01 成立。
- **阴性对照**：ts-voucher-service 不经 Nacos（server.py:47-48），应当全程正常。

### G2　对 ts-seat-service 注入挂起型故障 60 s 后清除
- **对象 / 故障**：seat 全部副本 100% 丢包（或 pod pause）60 s，然后完全清除。
- **负载**：baseline（搜索 + 下单混合）。
- **同时验证**：TT-11（每目标 5 条、每进程 10 条连接被占满；线程栈停在 AbstractConnPool.getPoolEntryBlocking；
  清除后是否还要约 120 s 才恢复）、TT-14（延迟放大约 2N 倍）、TT-13（客户端放弃后服务端是否继续跑完）、
  TT-34（Pod 是否始终 Ready）。
- **信号**：travel→seat 客户端 span 远长于 seat 服务端 span；下单的 /trip_detail 是否同时变慢（跨路径污染的关键证据）。
- **判定**：清除故障后恢复时间 > 60 s 即证伪「清理后 60 s 恢复」这条常用判据，TT-11 成立。
- **阴性对照**：不经 seat 的登录链路（gateway→auth 一跳）应当不受影响。

### G3　对 ts-order-service 的 PUT /order 注入 10 s 延迟，并在客户端超时后重发取消
- **对象 / 故障**：order 的 PUT 路由延迟 10 s；用自定义客户端在 10 s 超时后重发同一笔取消（已支付订单）。
- **同时验证**：TT-19（是否重复退款：同一订单出现两条 drawback 子 span、inside_payment 同订单两行 type='P'）、
  TT-13（超时后服务端是否仍落库）、TT-15（响应是否为 status=1「成功」）、TT-20（订单状态与退款是否不一致）。
- **信号**：`SELECT type,COUNT(*),SUM(money) FROM inside_money WHERE user_id=…` 测试前后做差，与 Σ0.8×price 比较。
- **判定**：出现两条退款记录即 TT-19 成立；订单为 4 而无退款行即 TT-20 成立。
- **阴性对照**：默认负载并发 1 且不重试，同时段的自然流量不应产生重复。

### G4　订单表灌到 10^4–10^5 行后，对 tsdb 主库注入 CPU 压力或 200 ms 延迟
- **对象 / 故障**：先长跑负载或直接灌数据，再对 tsdb-mysql leader 注入 CPU 压力；持续 15 分钟后清除。
- **同时验证**：TT-27（order 接收队列是否停止排空、CLOSE_WAIT 是否堆积、清除后能否自愈）、
  TT-26（搜索与取消的 p95 是否随行数单调上升）、TT-10（Table_locks_waited 是否从 0 起来）、TT-12（查询是否无限挂起而非快速失败）。
- **信号**：order 两副本的 CLOSE_WAIT 数、fd 数、线程栈；Hikari 等待连接的线程数。
- **判定**：清除注入后若两副本仍不恢复、需要人工重启，TT-27 成立（这是本轮 S→R 最值得争取的一条）。
- **阴性对照**：注入前的基线已测得 CLOSE_WAIT=0、Table_locks_waited=0、无连接排队。

### G5　触发 xenon 切主
- **对象 / 故障**：kill -9 当前 leader 的 mysqld（或对 leader 注入网络分区）。
- **同时验证**：TT-07（池里指向旧主的连接是否仍通过校验、写入报只读错误持续多久）、
  TT-08（leader 标签是否留下陈旧值、curl 是否静默失败）、TT-09（半同步是否导致提交挂起）。
- **信号**：应用日志里的只读错误（1290）持续时长；leader Service 的端点变化时刻；`SHOW SLAVE STATUS`。
- **判定**：只读错误持续时间接近 maxLifetime（约 30 分钟）即 TT-07 成立。
- **注意**：切主会让 max_connections 从偏差 #13 的 400 回落到 214，TT-06 会同时复现——这两条要分开归因。

### G6　带餐负载下 pod-delete rabbitmq
- **前置**：把负载的 foodType 改为非 0（默认是 0，餐食链路不激活）。
- **同时验证**：TT-24（生产端发送失败被吞、消费端 AUTO ack 丢消息）、TT-25（重建后 messages 是否归零）。
- **信号**：food_order 与 delivery 两张表的增量差；food 日志 `send delivery info to mq error`；
  delivery 日志 `Save delivery object into database failed`。
- **判定**：两表增量不等且下单全部成功，即两条都成立。
- **阴性对照**：消费者应在 broker 就绪后 ≤5 s 自动重连（这是有效保护，用来区分「重连失败」和「消息丢失」）。

### G7　排空一个节点 / kill 单副本服务
- **对象 / 故障**：`kubectl drain` vm-0-10（TT 全部 Deployment 和 nacos 都固定在这台，偏差 #8），或单独 kill 一个单副本服务。
- **同时验证**：TT-30（没有 PDB 时中断多久）、TT-02（摘除滞后多久）、TT-04（若偏差 #7 回退，还要验 NFS 依赖）。
- **判定**：下单链路中断时长 > Pod 重建时间，即摘除滞后成立。
- **风险提示**：这是共享集群，drain 会影响别人的命名空间——**执行前必须单独征得用户同意**，或改用「kill 单副本」的弱化版本。

### G8　sock-shop：重启 catalogue
- **同时验证**：SS-02（front-end 是否整个进程崩溃）、SS-05（180 s 就绪延迟是否把一次重启放大成 3–7 分钟全站中断）、
  SS-11（熔断器是否跳闸、跳闸后多久恢复）。
- **信号**：front-end 容器的 restartCount；全站 5xx 持续时长。
- **判定**：全站中断 ≫ catalogue 自身重启时间，即放大成立。

### G9　sock-shop：删除 session-db
- **同时验证**：SS-03（会话丢失后是否出现 customerId=undefined 的串单、结账是否崩、故障消失后能否恢复）、
  SS-14（重连退避是否无上限）、SS-04（front-end 探针是否始终为绿）。
- **判定**：session-db 恢复后若 front-end 仍不能正常结账，即「恢复后回不来」成立（属于要保留的例外情形）。

### G10　sock-shop：对 carts 注入延迟
- **同时验证**：SS-06（登录是否被非关键依赖拖住）、SS-13（节流是否进一步恶化）、SS-10（错误是否被改写成 200）。
- **阴性对照**：登录对 carts 的**快速失败**有有效降级，所以必须注入「变慢」而不是「拒连」，否则测不出来。
"""

APPENDIX_MD = """## 5. 附录

### 附录 A　排除清单（按口径不计入韧性缺陷）

- **优雅退出族**（graceful_shutdown：SIGTERM 处理、preStop、在途请求排空）：按用户口径不算韧性缺陷，本轮未单列条目。
  例外是「故障恢复后回不来」，这类已保留：SS-03（session-db 恢复后仍串单）、SS-12（重名后 user 永远起不来）、
  SS-14（重连放弃后不恢复）、TT-27（清除注入后仍需人工重启）。
- **T-03（重试放大）**：TT 侧没有实例（默认负载不重试、网关没有 Retry 过滤器）；SS 侧应用层也没有任何重试，
  只有 SS-10 提到的潜在 D3。前提是没有 sidecar 代理，这一点未核实。
- **wait-order 轮询**：代码缺陷真实存在（到期判断写反、路径不符、参数方向反了），但上游代码下轮询永远不会真正开始，
  不建议据此建场景。
- **notification 消费端热循环**：机制成立（先发邮件后落库、异常立即重新入队且无退避），但 email 队列没有业务生产者，触发不到。

### 附录 B　安全旁注（不计入韧性缺陷）

- sock-shop 的 front-end 会暴露全部地址和卡片信息、在日志里记录密码和卡号；重复注册返回 500。
- train-ticket 的 ts-payment-service 被网关直接暴露；order 的 `GET /order/status/{id}/{status}` 是 permitAll。
- train-ticket 的退款、买保险等非幂等操作用 GET 暴露（韧性后果已记在 TT-19）。

### 附录 C　观测缺口（不计入韧性缺陷）

- sock-shop 的 4 个 Java 服务 zipkin 关闭；queue-master 的 /metrics 不是 Prometheus 格式；rabbitmq 没有 exporter。
- 旧环境的 Prometheus 抓不到 sock-shop，已记为偏差 #14。
- train-ticket 有 6 个组件完全没有链路数据：rabbitmq、avatar、news、ticket-office、ui-dashboard、voucher。
- 新环境的 cAdvisor 只有 Pod 级 cgroup、没有 container 标签，按容器聚合会得到「无节流」的错误结论，PromQL 必须按 pod 聚合。
- N-01（OTel 同步导出）不成立：env 只设了 exporter 和 endpoint，应为异步批量导出。

### 附录 D　压测平台自身的问题（不计入韧性缺陷）

- TT 压测器的中止判断没有预热期，服务刚重启时首请求约 10 s，必然触发中止——第一次基线就是这样中止的。
- locust 容器的 nofile 只有 1024。
- tt-fixture.yaml 的 travel_date 是 2026-09-25，过了这天会失效，需要改成未来日期。
- 负载以 `status==1` 判成功，因此看不见 TT-15 那类「异常被包装成成功」的故障。

### 附录 E　镜像来源与本轮未核实清单

镜像来源的完整比对见 `runtime-evidence/TT-rebuilt-image-provenance/README.md`。与缺陷条目直接相关的是：

- **结论依赖被改过的源码的条目**：TT-21（改签删单接口映射，依赖 ts-order-service:1.0.1 的 OrderController）、
  TT-22（支付去重逻辑，依赖 ts-payment-service:1.0.2 的 PaymentServiceImpl 与 PaymentRepository）。
  这两条的 class 恰好都在「与上游编译结果不同」的清单里，因此**以上游为准，部署镜像上未核实**。
- 全部 Deployment 用可变标签；ticket-office 的基础镜像是 `FROM node` 不固定版本，实际跑的是 Node v25.8.1。

**本轮未能核实的事项**（按约束记为「未核实」，不据此升级定级）：

1. **ticket-office 的崩溃预测未验证**。预测下一次崩溃约在 2026-09-19 08:29 UTC（restartCount 2→3、ts.office 表 4→5 行），
   需要新环境集群的只读查询，本轮未取得新环境 kubeconfig，无法验证。TT-33 仍按已复现的那一次记 R。
2. **tsdb 的 max_connections 是否仍为 400** 未复查（同上，需要新环境访问）。
3. **部署 jar 的 classpath**（是否真有 httpclient、spring-retry；进程是否设了 -Dhttp.maxConnections）未核实，
   影响 TT-11 与 TT-19 的定级。
4. **sock-shop 多个库的实际版本**未核实：redis 客户端的退避参数（SS-14）、gobreaker 的跳闸阈值（SS-11）、
   Mongo 驱动的 socketTimeout（SS-06）、spring-amqp 的重新入队行为（SS-01），都只有文档默认值作依据。
5. **kube-proxy 模式**未核实，决定 Service 无端点时是立即拒连还是挂起，影响 SS-02 的故障量级（立刻崩 vs 约 127 秒后崩）。
6. **另外 5 个含 ts-traceenv-test 的服务未反编译**（order、payment、preserve、preserve-other、train）。
   travel 一个已反编译核实（见 TT-41），其余 5 个改动模式相同，推测是同一套插桩，但未核实。

**只读查询就能升级定级的条目**（本轮已做的已标注，未做的需要新环境 kubeconfig）：

| 条目 | 现级 | 一条只读命令就能核实什么 | 本轮状态 |
|---|---|---|---|
| TT-30 | C | 各服务原副本数（旧环境 Deployment 的 `resiliencebenchmark.io/standby-replicas` 注解） | **已做**：gateway 3、ui-dashboard 3、auth/order/preserve 各 2，其余 43 个为 1。据此更正了 TT-B07 与任务描述里两处相反的说法 |
| TT-06 | R | `SELECT @@max_connections` 复查是否仍为偏差 #13 的 400 | 未做（需新环境） |
| TT-33 | R | `kubectl get pod -l app=ts-ticket-office-service -o jsonpath='{..restartCount}'` 加 `SELECT COUNT(*) FROM ts.office` | 未做（需新环境），预测 2→3 与 4→5 行待验证 |
| TT-31 | S | `kubectl exec deploy/ts-gateway-service -- cat /app/BOOT-INF/classes/application.yml`：一次确认 Sentinel 覆盖几条路由，**同时**确认有没有指向 ts-traceenv-test 的路由 | 未做（需新环境） |
| TT-35 | S | `SELECT ... FROM train_type` 看座位数是否真是 Integer.MAX_VALUE | 未做（需新环境） |
| TT-19 | S | `SHOW CREATE TABLE payment` 看 order_id 有无唯一键 | 未做（需新环境） |
| TT-24 | S | `rabbitmqctl list_queues name durable messages_ready consumers` | 未做（需新环境） |
| TT-08 | S | `kubectl exec tsdb-mysql-N -c xenon -- cat /etc/xenon/xenon.json` 确认判死阈值的生效值 | 未做（需新环境） |
| TT-39 | S | `kubectl exec deploy/ts-voucher-service -- pip list` 确认 tornado / pymysql 实际版本 | 未做（需新环境） |
| SS-09 | C | `kubectl get pdb -A` 确认 PDB 缺失 | **已做**：两个命名空间都没有 PDB |

**证据最薄弱的五处**（终稿已按「拿不准往低一档」处理）：

| # | 条目 | 薄弱点 |
|---|---|---|
| 1 | SS-14 | redis 库不在 yarn.lock 里，退避系数 1.7、1 小时放弃全部是文档默认值推断 |
| 2 | SS-11 | gobreaker 809bcd5 源码未落地，跳闸阈值纯按文档推断，而整条的量级就建立在这个阈值上 |
| 3 | TT-22 | 结论建立在 PaymentServiceImpl.pay 上，而这个类恰好是 1.0.2 改过的类之一 |
| 4 | TT-19 | 重复请求的来源未核实（默认负载不重试、网关无 Retry），Ribbon 是否真带 GET 自动重试取决于未核实的 classpath |
| 5 | TT-08 | 误切主与陈旧 leader 标签都没有实跑；xenon 判死阈值只有配置值、没有观测到误判 |

另有三处静态报告的行号或表述问题，追溯时需要重新确认（已在对应条目的 notes 里注明）：
TT-17 的 `:205-215` 与 NPE 行 `:217` 不自洽；TT-B16 表格里有几处裸行号没带类名；
TT-A 组有 8 条的 key_evidence 用了「网关 yml:13」这类裸写法，没有完整路径前缀。
"""
