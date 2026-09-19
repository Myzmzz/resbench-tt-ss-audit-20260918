# train-ticket 与 sock-shop 韧性缺陷审计终稿

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

## 1. 汇总

终稿共 **58** 条（TT 44 条、SS 14 条）：108 条静态候选合并成 57 条，另有 1 条（TT-41）是本轮镜像比对新发现的、不在静态候选内。其中 X 级 3 条是已否定的原候选，保留在正文里便于追溯。

### 1.1 系统 × 证据等级

| 系统 | R | C | S | X | M | 合计 |
|---|---|---|---|---|---|---|
| train-ticket（TT） | 6 | 18 | 17 | 3 | 0 | 44 |
| sock-shop（SS） | 3 | 7 | 4 | 0 | 0 | 14 |
| 合计 | 9 | 25 | 21 | 3 | 0 | 58 |

### 1.2 业务链路 × 机制族（不含 X 级；一条可同时计入多个链路和多个机制族，所以格子之和大于条目数）

| 系统 | 业务链路 | deadline_<wbr>timeout | retry_<wbr>backoff | circuit_<wbr>isolation | fallback_<wbr>degradation | idempotency_<wbr>compensation | delivery_<wbr>semantics | replica_<wbr>disruption | health_<wbr>probe | load_<wbr>shedding_<wbr>admission | resource_<wbr>limit | other | 条目数 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TT | 搜索 | 3 | · | 1 | 3 | · | · | · | 1 | 2 | 3 | 5 | 9 |
| TT | 下单 | 1 | 1 | · | 3 | 3 | 1 | · | 1 | 2 | 2 | 3 | 9 |
| TT | 取消 | · | 1 | · | 2 | 3 | · | · | · | 1 | 1 | · | 6 |
| TT | 支付 | · | 1 | · | · | 2 | · | · | · | · | · | · | 2 |
| TT | 改签 | · | 1 | · | · | 2 | · | · | · | · | · | · | 2 |
| TT | 登录 | 1 | · | · | 1 | · | · | · | · | 2 | 1 | 1 | 4 |
| TT | 注册 | · | · | · | · | 1 | · | · | · | · | · | · | 1 |
| TT | 查单 | · | · | · | · | · | · | · | 1 | 2 | 3 | 1 | 3 |
| TT | 餐食配送 | · | · | · | 1 | · | 1 | 1 | 1 | · | 1 | · | 2 |
| TT | 管理后台 | · | · | · | · | · | · | · | · | 1 | 1 | · | 1 |
| TT | UI入口 | · | · | · | · | · | · | · | 2 | 1 | · | 1 | 2 |
| TT | 其他 | 1 | · | 1 | 1 | · | · | 1 | 1 | 1 | 1 | 1 | 4 |
| TT | 全部 | 6 | 1 | 2 | · | · | · | 9 | 5 | 2 | 4 | 2 | 18 |
| SS | 浏览 | · | · | 1 | 1 | · | · | 1 | 1 | · | · | · | 3 |
| SS | 加购 | · | · | 2 | 1 | 1 | · | · | · | · | 2 | · | 4 |
| SS | 购物车 | 1 | · | 1 | 1 | 1 | · | 1 | · | · | 2 | · | 4 |
| SS | 结账 | 1 | · | 1 | 4 | 2 | 1 | 2 | 1 | · | 2 | · | 8 |
| SS | 登录 | 1 | 1 | 1 | 1 | 1 | · | 2 | 1 | · | · | · | 4 |
| SS | 注册 | · | 1 | · | · | 1 | · | · | · | · | · | · | 1 |
| SS | 发货 | · | · | · | 1 | · | 1 | · | · | · | · | · | 1 |
| SS | 全站 | 1 | 1 | 2 | 2 | · | · | 2 | 2 | · | 1 | · | 7 |

## 1.3 最值得关注的 10 条

排序依据：先看是否已复现（R > C > S），再看影响面（全站 / 关键链路 / 单一功能），
最后看触发概率（默认负载就会撞上 > 需要注入 > 需要自定义负载）。

紧随其后的是 TT-27（order 接收队列停止排空、不自愈）：旧环境真实发生过、需要人工重启，机制链完整，但本轮基线下 CLOSE_WAIT 与连接池排队三个现象全为 0，因此它是最值得优先做注入验证的一条（见注入设计 G4）。

**1. TT-06〔R〕tsdb 实际连接上限只有 214 而稳态需求 270：configmap 写的 65535 被 open_files_limit=1024 压掉了两个数量级**

服务起齐就必然发生，不需要任何注入：需求 270 条连接而实际上限只有 214，最后启动的几个服务直接崩溃重启。而且它是个「配置谎言」——configmap 写的是 65535，运维照着配置看不出问题。偏差 #13 的临时 SET GLOBAL 不持久，MySQL 一重启就回到 214。

**2. TT-01〔R〕Nacos 不可用时业务服务注册即 fail-fast 退出，CrashLoopBackOff 把恢复从秒级拖到 12 分钟**

影响面是全系统，且本轮实测 37 个 Pod 同时 CrashLoopBackOff、最慢的服务 764 秒才回来。任何涉及重启的运维动作（包括基准自己的 restart-application-deployments 重置流程）都会撞上它。

**3. SS-01〔R〕发货链路两端都静默失败：shipping 吞掉发布异常仍回 201，queue-master 的发货必然失败却照常确认消息**

默认负载下 100% 持续发生（15 分钟 432/433 条失败），而 checkout 成功率 100%、队列积压为 0——从任何业务指标都看不出来。对一个韧性基准来说，这种「注入了故障也测不出来」的灰色故障最危险。

**4. TT-13〔R〕入口没有截止时间、取消不传播：客户端 10 s 放弃后服务端照样跑完整条链并写库，留下没人清理的幽灵订单**

已复现的数据一致性缺陷：客户端判失败、服务端已落库，留下没人回收的幽灵订单。冷启动首请求 9.7–10 s 正好卡在客户端 10 s 超时线上，第一次基线就因此中止。

**5. TT-11〔C〕40 个服务的 RestTemplate 是 Apache HttpClient 系统默认：三种超时全无，每目标 5 条、整进程 10 条连接，借不到就无限等**

全审计跨组重复最多的一条（入口、查询、下单、基础设施四组各记一次），影响 40 个服务的全部服务间调用。每进程只有 10 条连接且借不到无限等，单个慢依赖能跨业务链路污染；清除故障后还要约 120 秒才恢复，超过常用的 60 秒恢复判据。

**6. TT-02〔C〕服务发现的「健康」只表示 gRPC 连接还活着：Ribbon 不探活、不剔除、不重试，K8s 就绪被完全绕开**

故障会一直持续到 Nacos 自己改判为止，而不是一个探测周期——K8s 的 readiness 对服务间流量完全无效。旧环境已经因此出过事故（08-22），配置层根因至今未改。

**7. TT-15〔C〕依赖失败被翻译成「成功」：travel 把 basic 故障变成 200+空列表，cancel 把任何异常包成 status=1，SLO 对故障失明**

把依赖故障翻译成「成功」，直接损害基准的可观测性：注入了故障但 SLO 看不见。取消链路把任何异常包成 status=1，搜索链路把 basic 故障变成 200+空列表，两处都会让评测得出错误结论。

**8. SS-13〔R〕CPU limit 按平均用量配、没留突发余量：5 个用户就让 carts 节流 33%、orders 24%，而平均用量只有约 0.06 核**

默认负载（仅 5 个用户）就让 carts 节流 33%、orders 节流 24%，而平均用量只有约 0.06 核——limit 是按平均值配的，完全没留突发余量。空闲时节流为 0 的对照组使因果非常清楚。

**9. TT-30〔C〕没有 PDB、41 个服务单副本、多副本服务和三成员仲裁组都没有反亲和，本地盘还把 MySQL 钉在节点上**

影响面最大的结构性问题：41 个服务单副本、没有 PDB、没有反亲和，而新环境只有 2 个节点且 TT 全被固定在 vm-0-10。排空一个节点就能让下单链路和数据库仲裁组同时失去多数派。

**10. TT-41〔C〕部署镜像在主查询路径第一行植入了对 ts-traceenv-test 的同步调用，默认走无超时的共享连接池**

本轮反编译部署镜像才发现的：主查询入口 POST /trips/left 的第一行，就同步调用一个上游源码里不存在、Nacos 里也没有实例的 ts-traceenv-test，而且默认走无超时的共享连接池。它把 TT-02（陈旧实例）和 TT-11（无超时+10 条连接）串成了一条现成的放大链路，入口正好在 SLO 路径上。静态审计看的是上游源码，不可能发现它。

## 2. train-ticket 条目

### TT-01〔R〕Nacos 不可用时业务服务注册即 fail-fast 退出，CrashLoopBackOff 把恢复从秒级拖到 12 分钟
- **机制族 / 失效模式**：replica_disruption（重启恢复） + retry_backoff；主 D6（启动硬依赖）；次 D5（与 kubelet 退避叠加）、D3
- **业务链路**：全部
- **触发条件**：Nacos 三副本同时未 Ready 的窗口里，任一业务 Pod 因 OOM、驱逐、节点重调度或平台重置流程 restart-application-deployments 而启动或重启。nacos-discovery 2.2.7 的 failFast 默认为 true，注册失败直接抛出导致上下文启动失败、进程退出。
- **后果**：本轮实测：Nacos 0/3 时 37 个 Pod 进入 CrashLoopBackOff，主要重启 14–17 次。Nacos 恢复（T0=08:57:44Z）后就绪中位数是 T0−97 s，但最慢的 auth、assurance 要到 T0+764 s 才回来，44 个 Pod 重启 ≥5 次。没有 startupProbe，kubelet 退避从 10 s 翻倍到 300 s 封顶，再叠加 JVM 启动和 60 s 就绪初始延迟。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现，有 crashloop.txt 与 recovery-lag.txt 两份采集。恢复时长与 TT-06 的连接上限叠加，不能单独归因于本条。
- **证据位置**：证据/TT-startup-hard-dependency-on-nacos/crashloop.txt（08:23Z，Nacos 0/3，37 Pod CrashLoopBackOff，UnknownHostException nacos-N.nacos-headless）；证据/TT-startup-hard-dependency-on-nacos/recovery-lag.txt（T0=08:57:44Z，就绪中位 −97 s、最慢 +764 s）；TT源码/pom.xml:68-73（所有模块引入 nacos-discovery 2.2.7）；~/.m2/repository/com/alibaba/cloud/spring-cloud-starter-alibaba-nacos-discovery/2.2.7.RELEASE（javap：failFast=true；NacosServiceRegistry.register 调 rethrowRuntimeException）；清单/train-ticket/deployments.json（initContainers 为 0，无 startupProbe，readiness 初始延迟 60 s）
- **原编号 / 备注**：原编号 TT-A3、TT-B06、TT-E02、TT-D13（部分）、TT-RT-03。四组各从自己的链路记了同一个根因，合并为一条。TT-D13 是支付/消息组的「共性问题打包条目」，按根因拆开：启动依赖并入本条，无超时并入 TT-11，单副本无 PDB 并入 TT-29，无 liveness 并入 TT-38。voucher 不经 Nacos（server.py:47-48），是本条的天然阴性对照。

### TT-02〔C〕服务发现的「健康」只表示 gRPC 连接还活着：Ribbon 不探活、不剔除、不重试，K8s 就绪被完全绕开
- **机制族 / 失效模式**：health_probe（负载均衡层健康判定） + replica_disruption（摘除/故障转移） + circuit_isolation（被动剔除）；主 D2（摘除与故障转移失效）；次 D4、D6
- **业务链路**：全部
- **触发条件**：实例进程活着但已无法服务（线程耗尽、堆内 OOM、卡死），或实例被杀而 Nacos 仍把旧 IP 标为健康。网关和服务间调用都只认 Nacos 的实例列表，K8s 的 readiness 只影响 Service 端点，摘不掉 Nacos 流量。
- **后果**：失败会持续到 Nacos 自己改判为止，而不是一个探测周期。Ribbon 服务器列表每 30 s 才刷新一次，默认 DummyPing 不主动探活；网关走 LoadBalancerClientFilter 只调 choose()，不经 execute，永远不记 ServerStats，AvailabilityPredicate 不会跳闸。查询链路 6+6N 次扇出会把单实例故障放大：order 两副本时约一半请求受影响。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。库默认值已用 javap 逐条反编译核实，清单里的探针配置也已核实。本轮新环境没有再现陈旧注册（nacos-vs-pods.txt 显示陈旧 0、登记未就绪 0），旧环境 08-22 事故复现过，因此定 C 而不是 R。
- **证据位置**：TT源码/ts-gateway-service/src/main/resources/application.yml:16–209（39 条路由全是 uri: lb://…）；~/.m2/…/ribbon（javap：PollingServerListUpdater 首次 1000 ms、之后 30000 ms；RibbonClientConfiguration 默认 DummyPing + ZoneAvoidanceRule；LoadBalancerClientFilter 只调 choose(String)）；清单/train-ticket/deployments.json（readiness 仅 tcpSocket，无 liveness）；证据/TT-network-and-health/nacos-vs-pods.txt（本轮：陈旧 0、登记未就绪 0；文件头时间戳未展开）；D0/environment/repairs/train-ticket-nacos-workload-qualification-20260822.yaml:8–22、:27（旧环境陈旧注册与人工修复记录）
- **原编号 / 备注**：原编号 TT-A1、TT-A4、TT-B03、TT-B04、TT-C4、TT-E04。六条讲的是同一件事在不同链路上的投影：A1 是网关侧四方面根因，A4 是绕开 K8s 就绪，B03 是扇出放大，B04 是探针与路由脱节，C4 是 order 陈旧实例，E04 是两套健康判定互不相通。合并后保留 B03 的扇出放大系数。失败率随扇出放大的具体数值依赖死 IP 是快速拒连还是丢 SYN（后者每次约 127 s），两种情况差一个量级，属未核实。

### TT-03〔C〕Nacos 三副本注册表分歧的配置层根因：成员列表用 DNS 名、没有持久卷、headless 不发布未就绪地址
- **机制族 / 失效模式**：replica_disruption（服务发现）；主 D6；次 D4、D5
- **业务链路**：全部
- **触发条件**：某个 Nacos 副本未 Ready 的窗口里业务 Pod 换 IP 重建。成员域名只在 Pod Ready 时才解析得到，而 Ready 又不等于 Distro 数据就绪；nacos-headless 没开 publishNotReadyAddresses。
- **后果**：三副本注册表出现分歧：调用方看到的实例列表取决于它的 gRPC 连接恰好挂在哪个副本上。旧环境曾出现已不存在的 Pod IP 被标为健康，需要人工修复。没有持久卷意味着重建即丢注册数据。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。配置已在清单里核实（statefulsets.json、services.json、configmaps.json）。旧环境有事故与修复记录，本轮新环境未再现。
- **证据位置**：清单/train-ticket/statefulsets.json（Nacos 2.0.1 三副本，无持久卷）；清单/train-ticket/services.json（nacos-headless 未设 publishNotReadyAddresses）；清单/train-ticket/configmaps.json（成员列表用 DNS 名而非固定 Pod IP）；D0/environment/repairs/train-ticket-nacos-workload-qualification-20260822.yaml:8–22（旧环境三副本分歧的处置记录）
- **原编号 / 备注**：原编号 TT-A2、TT-E08。A2 从网关视角描述后果（错误路由、空列表 503），E08 给出 Nacos 集群配置层的根因，合并为一条。与 TT-02 的分工：本条是「注册表为什么会错」，TT-02 是「注册表错了为什么没人纠正」。

### TT-04〔R〕41 个 Java 服务每次启动都要挂载集群外主机 1.94.151.57 的 NFS 取 javaagent，这台主机同时是 Harbor
- **机制族 / 失效模式**：replica_disruption（重启恢复）；D6（启动硬依赖集群外单点）
- **业务链路**：全部
- **触发条件**：NFS 主机不可达，或节点上没有 mount.nfs。所有业务 Pod 的重建都会卡住。
- **后果**：本轮实测：46 个 Pod 停在 ContainerCreating，FailedMount 事件 13 次 / 10 分钟，报 `mount -t nfs 1.94.151.57:/data/share` bad option（节点没有 mount.nfs）。这台主机同时承载 Harbor，一旦它出问题，拉镜像和挂 agent 会同时失败，故障域完全重叠。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现，有 before-fix.txt。已被偏差 #7 掩盖（agent 换成镜像内置的 otel-demo 2.2.0），现在无法再复现。
- **证据位置**：证据/TT-nfs-javaagent-startup-dependency/before-fix.txt（07:06Z，46 Pod ContainerCreating，FailedMount×13/10m）；清单/train-ticket/deployments.json（41 个 Java Deployment 挂载 NFS 卷 1.94.151.57:/data/share，-javaagent 指向该目录）；DEVIATIONS.md 偏差 #7
- **原编号 / 备注**：原编号 TT-E03、TT-RT-02。旧环境是潜伏单点：依赖一直存在，只是那台主机一直可达。终稿记 R 并注明已被偏差 #7 掩盖。

### TT-05〔R〕xenon 用「localhost=IPv4 + 免密 root」探活，K8s 探针走 Unix socket，两套判定分叉出「探针全绿但没有主库」
- **机制族 / 失效模式**：health_probe + replica_disruption（故障转移）；主 D6；次 D2（选不出主 = 故障转移失效）
- **业务链路**：全部
- **触发条件**：Pod 里启用了 IPv6 回环时，localhost 解析到 ::1，而 mysql.user 里只有 root@127.0.0.1 和 root@localhost，root@'::1' 被拒（1045）。xenon 因此判定本地 mysqld 已死。
- **后果**：本轮实测：两个 leader Service 都没有端点，6 个 MySQL 全是 follower，xenon ping 失败计数 downs:720（downslimits:3），而 K8s 探针走 Unix socket 一路绿灯。数据库集群永久选不出主，所有写入不可用，但从 K8s 看一切正常。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现（before-fix.txt），补 root@'::1' 后 10 秒内选出主。已被偏差 #5 掩盖。
- **证据位置**：证据/TT-xenon-ipv6-localhost/before-fix.txt（06:51Z，两个 leader Service 无端点、6 个 MySQL 全 follower、root@'::1' 1045、downs:720）；TT源码/deployment/kubernetes-manifests/quickstart-k8s/charts/（Chart 的 allowEmptyRootPassword: true，xenon 经 TCP localhost:3306 免密探活）；清单/train-ticket/statefulsets.json（K8s 探针走 Unix socket）；DEVIATIONS.md 偏差 #5
- **原编号 / 备注**：原编号 TT-E01、TT-RT-01。旧环境是潜伏状态：配置相同，但 Pod 里没启用 IPv6，所以没触发。这是「两套健康判定各自为政」在数据库层的实例，与 TT-02（服务发现层）、TT-38（应用层）同构。

### TT-06〔R〕tsdb 实际连接上限只有 214 而稳态需求 270：configmap 写的 65535 被 open_files_limit=1024 压掉了两个数量级
- **机制族 / 失效模式**：resource_limit + load_shedding_admission；主 D4（配置值与生效值不符）；次 D5、D1
- **业务链路**：全部
- **触发条件**：服务起齐即触发，不需要注入。25 个服务共 27 个实例，每实例 Hikari 池 10，合计需求 270；MySQL 因 open_files_limit=1024 把 max_connections 从配置的 65535 自动压低到 214。
- **后果**：本轮实测：稳态 Threads_connected 276、Max_used_connections 286、Connection_errors_max_connections 127；最后启动的几个服务（assurance、order-other、security 等）直接 Too many connections 崩溃重启。这是一个「配置谎言」——运维看 configmap 会以为有 65535 个连接可用。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现，有 crashloop-too-many-connections.txt 与 processlist-by-pod.txt 两份采集。偏差 #13 把上限临时 SET GLOBAL 到 400，不持久：MySQL 一重启或切主就回到 214。
- **证据位置**：证据/TT-db-connection-exhaustion/crashloop-too-many-connections.txt（09:04Z，assurance/order-other/security 等 Too many connections）；证据/TT-db-connection-exhaustion/processlist-by-pod.txt（09:04Z，业务连接 213，Threads_connected 215 / max 214）；证据/TT-tsdb-runtime-config/tsdb-leader.txt（08:59Z，@@max_connections=214、@@open_files_limit=1024）；清单/train-ticket/configmaps.json（tsdb-mysql / node.cnf 写的是 max_connections=65535）；证据/RES-resource-pool-metrics/during-baseline-0918.txt（25 服务 27 实例 × 池 10 = 270）
- **原编号 / 备注**：原编号 TT-E18、TT-A12（部分）、TT-RT-04。**更正静态结论**：TT-E18 担心的是「max_connections=65535 远超 1Gi 内存能承受的量」，方向反了——配置值根本没生效，实际瓶颈是 214 太小。原条目里「1 秒超时的 exec 就绪探针在 500m 限额下可能把主库误判」的部分未核实，单独留在 TT-08 的备注里。

### TT-07〔C〕数据库切主不覆盖已经建立的连接：旧主变只读后连接仍能通过校验，失联时则半开挂死
- **机制族 / 失效模式**：replica_disruption（故障转移） + deadline_timeout；主 D2；次 D4、D5
- **业务链路**：全部
- **触发条件**：xenon 切主。旧主还活着时变成只读；旧主失联时连接进入半开状态。
- **后果**：旧主活着：池里的连接仍能通过 Hikari 校验（只读错误 1290 不在驱逐表里），写入持续报只读错误，直到连接因 maxLifetime 到期才轮换，约 270 条连接逐步换完最长约 30 分钟。旧主失联：JDBC 没有 socketTimeout，在用的连接半开挂死。只指向主库的 Service 在切换窗口里还可能短暂没有后端。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。Hikari 与 JDBC 的默认行为已核实，连接数与 Secret 指向（27 个 Secret 指 tsdb-mysql-leader）已在运行时核实。切主过程本身没有实跑，30 分钟是按 maxLifetime 推算的。
- **证据位置**：TT源码/ts-order-service/src/main/resources/application.yml:13 等 11 个服务的 yml（JDBC URL 无 connectTimeout / socketTimeout，也没有任何 hikari 配置）；证据/TT-tsdb-runtime-config/tsdb-leader.txt（27 个 Secret 的 HOST 都是 tsdb-mysql-leader）；清单/train-ticket/services.json（leader Service 按标签选主，切换窗口内可能无后端）；清单/train-ticket/configmaps.json（xenon 半同步与切主配置）
- **原编号 / 备注**：原编号 TT-C9、TT-E07、TT-B13。C9 从下单链路、E07 从基础设施、B13 从查询链路记同一件事，合并。「已有连接粘在旧主」这一点在三份报告里都是推断，没有实跑切主，因此不升 R。

### TT-08〔S〕切主通告靠 curl 改 Pod 标签且不判返回码，xenon 判死阈值又过于灵敏，可能误切主并留下陈旧 leader 标签
- **机制族 / 失效模式**：replica_disruption（故障转移） + health_probe；主 D4；次 D6、D3
- **业务链路**：全部
- **触发条件**：切主时 API Server 抖动，或 leader 被 kill -9；以及负载尖峰下 xenon 在 100m CPU 限额里约 1 秒一次探活、连续 3 次失败即判死。
- **后果**：leader-start/stop.sh 用 curl 改标签，不检查返回状态、没有超时和重试，异常失主会留下陈旧的 leader 标签，Service 指向一个已经不是主的成员。判死过灵敏则可能因为 CPU 争用误切主，进而带出 TT-07 的只读写失败。
- **证据等级**：S（仅源码/清单静态推断）。脚本与阈值都在 configmap 里核实过，但误切主和陈旧标签都没有实跑复现。
- **证据位置**：清单/train-ticket/configmaps.json（leader-start.sh / leader-stop.sh 用 curl 改标签，无返回码判断、无超时重试）；清单/train-ticket/configmaps.json（xenon 探活间隔约 1 s、连续 3 次失败判死）；清单/train-ticket/statefulsets.json（xenon 容器 limit 100m/256Mi）
- **原编号 / 备注**：原编号 TT-E10、TT-E19。E10 是通告机制、E19 是判死阈值，两者是同一条故障链的上下游（误判 → 切主 → 通告失败），合并。另：TT-E18 里「1 秒超时的 exec 就绪探针在 500m 限额下可能把主库误判为不可用」未核实，记在这里备查。

### TT-09〔C〕半同步复制超时设成 1e18 且 wait_no_slave=ON，binlog 又永不过期：写入要么全局悬挂，要么把 1Gi 卷写满
- **机制族 / 失效模式**：deadline_timeout + resource_limit；D3（保护动作本身造成故障）
- **业务链路**：全部
- **触发条件**：从库都不能 ACK（网络分区、从库全挂）时主库提交挂起；或长时间运行后 binlog 占满数据卷。
- **后果**：半同步 timeout=1e18 相当于无限等待，wait_no_slave=ON 表示没有从库也继续等：主库提交一直挂着，叠加客户端没有超时（TT-11、TT-12），形成全局悬挂而不是快速失败。expire_logs_days=0 表示 binlog 永不清理，xenon 也不清理，1Gi 数据卷写满后 MySQL 写入挂起而非报错。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。配置值是 kubectl exec 进主库实测得到的（tsdb-leader.txt），不是清单推断，因此定 C；两种后果都没有实跑。
- **证据位置**：证据/TT-tsdb-runtime-config/tsdb-leader.txt（08:59Z，semi-sync timeout=1e18、wait_no_slave=ON、wait_point=AFTER_SYNC、wait_for_slave_count=1、expire_logs_days=0）；清单/train-ticket/persistentvolumeclaims.json（数据卷 1Gi）
- **原编号 / 备注**：原编号 TT-E20、TT-E21。两条都是「数据库写入悬挂」的不同触发路径，合并。E20 报告里只写了 D3、没写机制族名，这里按后果补成 deadline_timeout + resource_limit。

### TT-10〔C〕业务库 32 张表实际是 MyISAM：表级锁、崩溃后表损坏不自修复、写入不参与两阶段提交
- **机制族 / 失效模式**：other；主 D4；次 D6
- **业务链路**：下单、搜索、查单
- **触发条件**：并发写同一张表时表级锁争用；进程崩溃或断电后表损坏。
- **后果**：MyISAM 只有表级锁，写并发被串行化；myisam_recover_options=OFF 表示崩溃后不自动修复；MyISAM 不支持事务，写入不参与两阶段提交，半同步复制对它没有意义。实体用 MySQL5Dialect 经 Hibernate ddl-auto 建表，默认落到 MyISAM，而 default_storage_engine 明明是 InnoDB。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实 32 张 MyISAM、3 张 InnoDB（office/station/voucher）。但基线下 Table_locks_waited=0，锁争用后果没有复现——这属于 3.2 节「基线下没复现，不能判否」。
- **证据位置**：证据/TT-tsdb-runtime-config/tsdb-leader.txt（08:59Z，32 张 MyISAM、3 张 InnoDB、default_storage_engine=InnoDB、myisam_recover_options=OFF）；证据/TT-tsdb-runtime-config/myisam-locks-during-baseline.txt（09:24Z，Table_locks_immediate 13454、waited 0）；TT源码/ts-order-service/src/main/resources/application.yml:13（MySQL5Dialect + ddl-auto）
- **原编号 / 备注**：原编号 TT-C7。静态报告写的是「很可能被建成 MyISAM」，运行时已把它坐实，因此从 S 升到 C。锁争用要靠注入加压验证，见注入实验 G4。

### TT-11〔C〕40 个服务的 RestTemplate 是 Apache HttpClient 系统默认：三种超时全无，每目标 5 条、整进程 10 条连接，借不到就无限等
- **机制族 / 失效模式**：deadline_timeout + circuit_isolation；主 D1（无截止时间）；次 D4（舱壁配错）、D5
- **业务链路**：全部
- **触发条件**：任一下游变慢或黑洞。对 seat 注入挂起型故障（100% 丢包或 pod pause），默认负载并发 1、客户端 10 s 放弃但服务端连接继续占着，约每 10 s 多占一条，约 50 s 占满 travel→seat 的 5 个槽位，再加 travel→basic 的 5 条，全进程 10 条用尽。
- **后果**：同一个池同时承载查询和下单两条业务，所以单个慢依赖能跨路径污染：travel→seat 挂住时，下单的 /trip_detail 一起变慢。健康下游也要排队，Tomcat 200 线程逐步耗尽。清除故障后还要等 TCP 重传（上限约 120 s）才恢复，超过「清理后 60 s 恢复」的反驳线。线程栈特征是大量停在 AbstractConnPool.getPoolEntryBlocking。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。库默认值已用 javap 在字节码层面核实（http.maxConnections 默认 "5"、setDefaultMaxPerRoute(5)、setMaxTotal(10)），源码里 RestTemplate 只做 builder.build() 也已核实。但部署 jar 里是否真有 httpclient、进程是否设了 -Dhttp.maxConnections 未核实（需 R10），后果也没有实跑。
- **证据位置**：TT源码/ts-travel-service/src/main/java/travel/TravelApplication.java:30-34（RestTemplate 只做 builder.build()，其余服务同）；~/.m2/repository/org/apache/httpcomponents/httpclient/4.5.13（javap：HttpClients.createSystem() → http.maxConnections 默认 5、maxTotal 10）；~/.m2/repository/com/alibaba/cloud/spring-cloud-starter-alibaba-nacos-discovery/2.2.7.RELEASE.pom:151-155（经 netflix-ribbon → ribbon-httpclient 传递引入 httpclient）；TT源码/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java:32-33（同一个 RestTemplate Bean 打 11 个下游）；证据/RES-resource-pool-metrics/during-baseline-0918.txt（15 分钟内无排队等连接——基线下未触发）
- **原编号 / 备注**：原编号 TT-A8、TT-B01、TT-C6、TT-E05、TT-D13（部分）、TT-E14（部分）。这是全审计中跨组重复最多的一条：入口组、查询组、下单组、基础设施组各记了一次。E05 的证据最硬（字节码级），B01 的触发时序最具体（约 50 s 占满），C6 的阴性对照最清楚（撤注入后不释放）。合并后以 E05 为主干。网关侧的同一问题（39 条 lb:// 路由无超时、连接池不设上限）并入本条，Sentinel 限流部分留在 TT-30。

### TT-12〔C〕JDBC 连接串没有 connectTimeout / socketTimeout：数据库丢包或挂起时查询无限挂起，连服务都启动不了
- **机制族 / 失效模式**：deadline_timeout；主 D1；次 D6
- **业务链路**：全部
- **触发条件**：共用的 MySQL 主节点丢包、主从切换或不可用。
- **后果**：查询挂起而不是快速失败，连接池被占满；服务启动时也要连库，数据库不可用时连启动都起不来。与 TT-09 的半同步无限等待叠加后，写入会全局悬挂。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。11 个服务的 yml 都已核实没有超时参数，也没有任何 hikari 配置。挂起后果没有实跑。
- **证据位置**：TT源码/ts-travel-service/src/main/resources/application.yml:13（JDBC URL 无 connectTimeout / socketTimeout；11 个服务的 yml 都搜不到 hikari 配置）；证据/TT-network-and-health/probe.txt（09:01Z，tcp_syn_retries=6 tcp_retries2=15，连不存在的 IP 约 127 s 才失败）
- **原编号 / 备注**：原编号 TT-A12、TT-B02（部分）。A12 是认证与用户数据访问侧，B02 的 E3 是查询链路侧，同一配置缺失。TT-06 的连接上限问题从 A12 拆出，单独成条。

### TT-13〔R〕入口没有截止时间、取消不传播：客户端 10 s 放弃后服务端照样跑完整条链并写库，留下没人清理的幽灵订单
- **机制族 / 失效模式**：deadline_timeout + other（取消传播）；主 D2（取消不传播）；次 D1
- **业务链路**：下单、搜索
- **触发条件**：下游延迟超过压测客户端的 10 s 响应超时。网关没有响应超时配置，取消只传播到网关为止，后端和下游继续执行。
- **后果**：本轮已复现：客户端按超时判为失败，服务端却已经把订单写进库，留下一笔未支付、没人回收的订单（幽灵订单）。冷启动首请求 9.7–10 s 正好撞上这条线，第一次基线因此中止。恢复时积压的「僵尸请求」还会集中落库。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现，有 TT-ghost-order-after-client-timeout/README.txt 与 TT-baseline-abort-first-run.txt 两份证据。
- **证据位置**：证据/TT-ghost-order-after-client-timeout/README.txt（客户端超时判失败、服务端已写单）；证据/TT-baseline-abort-first-run.txt（preserve 首请求 10011 ms 码 000 失败；search 首请求 9712 ms）；D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py:584-585（连接超时 3 s、响应超时 10 s，不重试）；TT源码/ts-gateway-service/src/main/resources/application.yml（没有任何 timeout 键）；TT源码/ts-ui-dashboard/nginx.conf:40-41（只写 proxy_pass，走默认 60 s）
- **原编号 / 备注**：原编号 TT-A7、TT-B05、TT-C5。三组各记一次：A7 是网关侧、B05 是查询链路白耗容量、C5 是下单侧写单。合并后按后果最重的下单侧定级 R。清理缺失的部分（NOTPAID 单没人回收）在 TT-18。

### TT-14〔C〕一次查询 5+6N 次调用全部串行且有 N+1 查询，注入的延迟被放大约 2N 倍，而 N 随车次数据增长
- **机制族 / 失效模式**：other（扇出放大） + deadline_timeout；主 D1；次 D2
- **业务链路**：搜索
- **触发条件**：给 seat、order 或 config 任一跳注入延迟 d。seat、order、config 这三条边的往返次数是 2N，N=1 时越过 p95≤2500 ms 只需 d≈1.1 s。
- **后果**：入口延迟增量约等于 n_rtt·d，随 d 线性增长且没有上限，全程看不到 504 或 SocketTimeoutException——只会慢失败，不会快速失败。route-plan / travel-plan 还会在此之上再串行放大，一个车次失败拖垮整个规划。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。扇出次数已用 Jaeger 在运行时核实：一次搜索 12 次 HTTP + 19 次 DB，一次下单 28 次 HTTP + 30 次 DB，与静态推算的 5+6N（N=1 时 11 个客户端 span）吻合。延迟放大本身没有实跑注入。
- **证据位置**：证据/TT-call-graph-baseline/fanout.txt（搜索 HTTP 中位 12、DB 19；下单 HTTP 28、DB 30）；TT源码/ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java:367-375、:426-430、:550-557（seat 一等/二等各 1 次，共 2N，在 for 循环里串行）；TT源码/ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java:232、:403-421（route 端 1+2R 条 SQL 懒加载）；TT源码/ts-seat-service/src/main/java/seat/service/SeatServiceImpl.java:190、:205-219（config 每次远程读，2N 次）
- **原编号 / 备注**：原编号 TT-B11、TT-B16。B11 是主查询链路、B16 是 route-plan/travel-plan 的二次放大，合并。B08 的 config 无缓存是本条 2N 里的一项成因，单独成条（TT-17）因为它还有 NPE 的独立后果。

### TT-15〔C〕依赖失败被翻译成「成功」：travel 把 basic 故障变成 200+空列表，cancel 把任何异常包成 status=1，SLO 对故障失明
- **机制族 / 失效模式**：fallback_degradation；主 D3（兜底动作本身造成错误）；次 D4（状态码写错）
- **业务链路**：搜索、取消
- **触发条件**：basic 返回 status 0 或反序列化失败（搜索侧）；取消链路下游快速失败如拒连、无可用实例（取消侧）。
- **后果**：搜索侧：travel 把依赖故障翻译成 HTTP 200 加空列表，按状态码算的 SLO 把它算成成功，用户看到的是「没有车次」。取消侧：入口 catch 把任何异常包装成 {"status":1,"msg":"error"} 并回 200，注入期间 cleanup-order 成功率仍接近 100%。两者合起来使评测对整类故障失明，直接损害基准的可观测性。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。代码路径已核实。取消侧只掩盖快速失败——下游挂住超过 10 s 时负载端先超时，反而可见，这一半属未核实。
- **证据位置**：TT源码/ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java:345-365（没有 try；basic 返回 status 0 或反序列化失败都变成「成功+空列表」）；TT源码/ts-cancel-service/src/main/java/cancel/controller/CancelController.java:45-51（catch Exception 后 ok(Response(1,"error",null))，已核对上游源码逐行确认）；TT源码/ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java:245-249 等 5 处 restTemplate.exchange 均无 try；D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py:285-289（负载以 status==1 判成功）
- **原编号 / 备注**：原编号 TT-B14、TT-D1。两条是同一反模式在两条链路上的实例：把依赖故障映射成成功响应。合并后作为「灰色故障」的代表条目。这条对基准平台本身危害最大——注入了故障但 SLO 看不见。

### TT-16〔S〕降级只兜「逻辑失败」不兜传输异常，非关键依赖被同步串在关键路径上
- **机制族 / 失效模式**：fallback_degradation；主 D1（缺降级）；次 D2（回退不覆盖传输异常）
- **业务链路**：下单、取消、搜索、登录
- **触发条件**：非关键依赖（price、user、verification-code、order-other、inside-payment）出现传输异常或 5xx，而不是返回 status 0。
- **后果**：price 故障让查询 100% 失败（降级只兜住「缺配置」、兜不住「调用失败」，try 外面抛 NPE）；user 故障把已经提交的下单或取消报成失败；order-other 单副本不可用时安检第 1 步无降级，G/D 下单 100% 失败；取消路径对 0 元退款也同步调 inside-payment、对已注释掉的通知仍同步查 user。seat 的 2N 次调用里任一失败整个查询就 500——按车次隔离的写法只存在于没人调用的 left_parallel 路径。
- **证据等级**：S（仅源码/清单静态推断）。全部是源码层推断，没有实跑注入。TT-A14（登录依赖验证码）已被运行时部分否定：Jaeger 显示基准负载的登录只有网关→auth 一跳，只在 UI 带验证码时才成立。
- **证据位置**：TT源码/ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java:272、:457-483、:286（price 结果为 null 时抛 NPE）；TT源码/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java（副作用之后才查 user，结果被丢弃且无降级）；TT源码/ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java:367-375（seat 逐车次循环没有 try；left_parallel 才有隔离写法）；TT源码/ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java:201-203、:63-64（0 元也调 drawback）、:70-73（G/D 分支查 user）、:86-87（发邮件已注释）；TT源码/ts-security-service/src/main/java/security/service/SecurityServiceImpl.java（安检第 1 步调 order-other，无降级）
- **原编号 / 备注**：原编号 TT-A5、TT-A14、TT-B09、TT-B10、TT-C10、TT-D6。六条的共同模式是「有降级代码但覆盖面不对」。A14 保留在本条内但标注已被运行时部分否定（见 TT-X3）。C10 的安检阈值默认无限大（安检只剩成本不产生拦截）也并入本条备注。

### TT-17〔S〕seat→config：一个常量配置每次都远程读取，每次查询读 2N 次，没有缓存也没有默认值，配置缺失直接 NPE
- **机制族 / 失效模式**：fallback_degradation + other（扇出放大）；主 D1；次 D6
- **业务链路**：搜索、下单
- **触发条件**：config 服务或它的库不可用，或配置项缺失。
- **后果**：DirectTicketAllocationProportion 是个常量，却每次分座都远程读一次，一次查询读 2N 次。没有缓存也没有默认值，配置缺失时在 SeatServiceImpl 直接抛 NPE，余票查询和下单的 trip_detail 一起全挂。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实，但 config 故障没有实跑。
- **证据位置**：TT源码/ts-seat-service/src/main/java/seat/service/SeatServiceImpl.java:190、:205-219（GET /configs/DirectTicketAllocationProportion，没有 try，配置缺失抛 NPE）
- **原编号 / 备注**：原编号 TT-B08。静态报告给 B08 的 E1 区间是 :205-215 而 E2 说 NPE 在 :217，落在区间外，疑似笔误；这里按 :205-219（调用图表格的写法）记录，实际行号待核。

### TT-18〔S〕下单后置调用失败无补偿、取消只改状态不回收：已落库订单回 500，附属记录和座位都没人回收
- **机制族 / 失效模式**：idempotency_compensation；主 D2；次 D1
- **业务链路**：下单、取消
- **触发条件**：写单之后的 4 个后置调用遇到传输异常或 5xx（代码只把 status≠1 当软失败）；或下单中途失败、压测异常退出。
- **后果**：订单已经写进库，接口却返回 500 且没有补偿，调用方重试会再下一单。取消时只把订单状态改掉，不回收保险、餐食、托运，也不释放座位；下单中途失败留下的 NOTPAID 订单没有任何自动回收机制（全仓没有 @Scheduled）。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实，但没有实跑注入。旧环境留下的 9 个遗留单成因静态区分不了（可能是本条，也可能是负载在下单与取消之间中断），需要按单号查 Jaeger/Loki。
- **证据位置**：TT源码/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java:207-212（只处理 status≠1，不处理异常）；TT源码/ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java:57→:238-252（只改订单状态）；TT源码/ts-order-service/src/main/java/order/service/OrderServiceImpl.java:302-311（订单只增不删）
- **原编号 / 备注**：原编号 TT-C2、TT-C8。C2 是后置调用失败、C8 是补偿覆盖不全，同属「写了一半没人收尾」，合并。座位不释放这一点与 TT-35 的超卖是同一段代码的两面。

### TT-19〔S〕全链路没有幂等键：重复提交必然重复下单，跨服务「先读后写」的守卫在慢写时会重复退款、重复扣款
- **机制族 / 失效模式**：idempotency_compensation + retry_backoff；主 D4（守卫非原子、写端无版本号）；次 D3、D5
- **业务链路**：下单、取消、支付、改签
- **触发条件**：调用方在模糊失败后重复提交；或对 order 的 PUT 注入 ≥10 s 延迟，客户端超时后重发。order-service 写端无条件覆盖，没有乐观锁，守卫全部基于旧读。
- **后果**：下单侧：去重比较写错了永远不会命中，订单号还被服务端重新生成，必然多出一笔重复订单。资金侧：两个请求都读到「已支付」就退两次款；execute 与 cancel 并发时已检票的订单会被改为 4 并退 80%；cancel 的整单 PUT 还会回滚并发改签刚写入的车次和座位。买保险是带副作用的 GET 且 Ribbon 会对 GET 自动重试一次。
- **证据等级**：S（仅源码/清单静态推断）。写端与守卫的代码路径已核实。但重复请求的来源未核实：默认负载并发 1 且不重试，网关也没有 Retry 过滤器，需要真实用户重复点击或自定义客户端。Ribbon 是否真带自动重试取决于 spring-retry 是否传递进 classpath，未核实。
- **证据位置**：TT源码/ts-order-service/src/main/java/order/service/OrderServiceImpl.java:315-327（直接改状态）、:440-468（整单覆盖，无乐观锁）；TT源码/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java（无幂等键，去重比较恒不命中）；TT源码/ts-inside-payment-service/src/main/java/inside_payment/controller/InsidePaymentController.java:62-66（退款接口是 GET）；D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py:584-585（负载不重试，可作阴性对照）
- **原编号 / 备注**：原编号 TT-C3、TT-C13、TT-D5、TT-D12。C3（下单去重写错）、C13（保险 GET 被重试）、D5（守卫非原子）、D12（退款 GET 被重试）是同一根因——没有幂等键 + 非幂等操作用 GET 暴露。D12 报告自评低置信，合并后整条按最弱环节定 S。

### TT-20〔S〕取消是「先改成已取消、再退款」，退款失败只记日志仍报成功，没有补偿也没法对账
- **机制族 / 失效模式**：idempotency_compensation；主 D1（扣款后中止、无补偿）；次 D2
- **业务链路**：取消
- **触发条件**：取消进行中对 inside-payment 注入 abort 或 pod-kill，或让它到 tsdb-mysql:3306 丢包。
- **后果**：三种终态都对用户报成功：①PUT 失败→订单仍未取消；②③PUT 成功但退款返回 0 或抛异常→订单已取消而没有退款行。守卫只放行状态 0/1/3，订单已是 4 时重试会被拒，无法补救。inside_money 表只有 id/userId/money/type 四列、没有 orderId，根本没法按订单对账。
- **证据等级**：S（仅源码/清单静态推断）。代码路径已核实。默认负载取消的是未支付订单，退款额为 0.00，只少一条 0 元记录；要丢真金白银需自定义 preserve→pay→cancel 流，没有实跑。
- **证据位置**：TT源码/ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java:57→:238-252（先 PUT 状态 4）→:63-64（后退款）；TT源码/ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java:89-92、:122-127（退款失败只 LOGGER.error 仍返回 status 1）；TT源码/ts-inside-payment-service/src/main/java/inside_payment/entity/Money.java:19-41（inside_money 无 orderId 列）
- **原编号 / 备注**：原编号 TT-D2。与 TT-15 的关系：本条的失败之所以对外不可见，正是因为被 TT-15 的 status=1 包装掩盖，两条在同一次注入里会同时出现。

### TT-21〔S〕改签先动钱后改单且失败不回滚，「只能改一次」的守卫最后才落地；跨类改签用 POST 打 @DeleteMapping 必然 405
- **机制族 / 失效模式**：idempotency_compensation；主 D1；次 D2
- **业务链路**：改签
- **触发条件**：确定性触发：把 G/D 车次改签成更便宜的 Z/K/T 车次，每调一次退一次差价而订单不变。故障触发：同类改签时让 route 返回 status 0（触发 NPE），或对 seat / order 的 PUT 注入 abort。
- **后果**：钱已经动过而订单没改，守卫要求状态为 1、状态 3 只在成功路径写入，所以失败后订单仍是 1，可以反复改签、反复退差价，错误提示还在引导用户重试。跨类改签删单用 POST 打 @DeleteMapping，405 抛异常时钱已经动过；即使删除成功，delete/create 的返回值被忽略直接报 Success，删除成功但新建失败时订单就丢了。补差价还不校验余额（BigDecimal.add 结果被丢弃）。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实。跨类改签的 405 依赖 1.0.1/1.0.2 镜像没改过删除接口映射——镜像比对显示 order/controller/OrderController.class 相对上游确有差异，因此这一条在部署镜像上未核实。
- **证据位置**：TT源码/ts-rebook-service/src/main/java/rebook/service/RebookServiceImpl.java:127→:131、:176→:177（先动钱后改单）；TT源码/ts-rebook-service/src/main/java/rebook/service/RebookServiceImpl.java:53、:69-71、:191、:222（守卫要求状态 1，状态 3 只在成功路径写入）；TT源码/ts-rebook-service/src/main/java/rebook/service/RebookServiceImpl.java:371-375（POST 删单）对 TT源码/ts-order-service/src/main/java/order/controller/OrderController.java:142（@DeleteMapping）；证据/TT-rebuilt-image-provenance/partial/summary-deployed-scan.txt（ts-order-service:1.0.1 的 OrderController.class 与上游编译结果不同）
- **原编号 / 备注**：原编号 TT-D3。本条是全审计中唯一「确定性可触发、不需要注入」的资金缺陷（跨类改签只要调用就退钱不改单），但默认负载没有改签步骤，需要自定义负载。

### TT-22〔S〕支付部分失败后重试，被 payment 的订单号去重以「失败」拒绝：订单永远付不了而用户已被记账
- **机制族 / 失效模式**：idempotency_compensation；主 D3（去重被触发却用失败回应合法重试）；次 D4、D5、D1
- **业务链路**：支付
- **触发条件**：自定义支付负载并制造余额不足；pay 期间对 order 的 GET /order/status 注入 abort，然后客户端重试 pay。
- **后果**：站外分支顺序是扣款→本地记账→改单，改单抛异常时前两步已落地而订单仍未支付。重试能通过入口守卫，但 payment 查到已有记录就返回 0 并提示「order not found」（与事实相反），此后每次都失败，钱扣了、订单永远付不了。orderId 没有唯一约束，并发插两行后单值查询会抛异常，该订单此后永久 500。余额分支则先改单后记账，本地库故障时订单已支付却没有扣款记录。
- **证据等级**：S（仅源码/清单静态推断）。上游源码路径已核实，但线上 payment 是 1.0.2，镜像比对显示 PaymentServiceImpl.class 与 PaymentRepository.class 相对上游都有差异，pay 逻辑可能已被改过——结论以上游为准，部署镜像上未核实。
- **证据位置**：TT源码/ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java:110-114→:119-120→:121（扣款、记账、改单三步）；TT源码/ts-payment-service/src/main/java/com/trainticket/service/PaymentServiceImpl.java:35、:43-44（查得到就返回 0 并提示 order not found）；TT源码/ts-payment-service/src/main/java/com/trainticket/entity/Payment.java:29-30（orderId 无唯一约束）；证据/TT-rebuilt-image-provenance/partial/summary-deployed-scan.txt（ts-payment-service:1.0.2 的 PaymentServiceImpl/PaymentRepository/PaymentController 与上游编译结果不同）
- **原编号 / 备注**：原编号 TT-D4。这是「待镜像比对」影响最大的一条：结论直接建立在 PaymentServiceImpl.pay 的实现上，而这个类恰好是 1.0.2 改过的类之一。见附录 E。

### TT-23〔S〕注册是跨库双写且没有补偿，用户名也没有唯一约束：一次部分失败加一次重试，该用户就永久登录不了
- **机制族 / 失效模式**：idempotency_compensation；主 D1
- **业务链路**：注册
- **触发条件**：注册时远程建 auth 用户成功但后续失败并重试；或空库上两个 auth 副本同时启动初始化。
- **后果**：同名用户重复，该用户此后永久登录不了。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实，未实跑。
- **证据位置**：TT源码/ts-auth-service/src/main/java/auth/service/impl/UserServiceImpl.java:52-65（跨库双写无补偿）；TT源码/ts-auth-service/src/main/java/auth/entity/User.java:32-33、UserRepository.java:20（用户名无唯一约束）；TT源码/ts-auth-service/src/main/java/auth/init/InitUser.java:29-49（两副本同时初始化）
- **原编号 / 备注**：原编号 TT-A15。与 SS-10（user 唯一索引只在启动时建一次）是跨系统的同构缺陷。

### TT-24〔S〕餐食配送消息：生产端落库后才发布、异常被吞、无 confirm/outbox，消费端 AUTO ack 吞掉落库异常，消息静默丢失
- **机制族 / 失效模式**：delivery_semantics；主 D1（N-02：生产者无确认）；次 D2（失败不回传）、D5
- **业务链路**：餐食配送、下单
- **触发条件**：把负载改成带餐（默认 foodType=0，preserve 直接跳过这一步）。然后 pod-delete rabbitmq，或让 delivery 到 tsdb-mysql:3306 不通。
- **后果**：生产端：发送异常只记日志仍报成功，订餐成功但配送记录静默缺失；同步发布还会让带餐下单卡约 60 s（amqp 建连超时）。消费端：落库异常被 catch 住后正常返回，AUTO ack 照常确认，消息不会重投也没有死信队列，队列 messages_ready 始终为 0——从队列指标完全看不出丢了消息。两端都没有去重。
- **证据等级**：S（仅源码/清单静态推断）。源码与 yml 已核实（两端都没有 listener / publisher confirm 配置）。默认负载不带餐，本轮没有激活这条链路。
- **证据位置**：TT源码/ts-food-service/src/main/java/foodsearch/service/FoodServiceImpl.java:131（落库）、:142-146（发送异常只记日志）、:148（仍报成功）；TT源码/ts-food-service/src/main/resources/application.yml:22-24（只有 host/port，Boot 2.3 默认不开 publisher confirm/returns）；TT源码/ts-delivery-service/src/main/java/delivery/mq/RabbitReceive.java:49-54（catch 后正常返回）；TT源码/ts-delivery-service/src/main/resources/application.yml:16-18（无 listener 配置，默认 AUTO ack）；D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py:382（foodType=0）
- **原编号 / 备注**：原编号 TT-D8、TT-D9、TT-C14。D8 生产端、D9 消费端、C14 同步投递卡 60 s，是同一条消息链路的三段，合并。rabbitmq 本身的单点问题在 TT-25。sock-shop 的 SS-07 是同构缺陷（shipping 吞掉发布异常仍回 201）。

### TT-25〔C〕rabbitmq 单实例、没有持久卷、没有内存上限、只有 TCP readiness 且无 liveness：重建即丢光在途消息
- **机制族 / 失效模式**：replica_disruption + resource_limit + health_probe；主 D1（T-10、T-06 实例）；次 D4
- **业务链路**：餐食配送
- **触发条件**：pod-delete rabbitmq（带餐负载下）。
- **后果**：队列按 durable 声明、消息默认持久化，但都落在容器可写层，没有卷等于形同虚设：重建后 messages=0。已预取到消费者（默认 prefetch 250）未处理完的消息本应由 broker 重投，但 broker 已经换了，于是丢失。优雅删除时消费者在 broker 就绪后 ≤5 s 恢复；节点失联这类半开连接要等 60 s 心跳约两个周期（约 120 s）。没有 memory limit 时高水位按节点内存算，流控几乎不会先于节点驱逐触发。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。清单配置已核实（无 volumes、replicas=1、无 PDB、无 memory limit、readiness 仅 tcpSocket 5672、无 liveness）。重建丢消息没有实跑，因为默认负载不带餐。
- **证据位置**：清单/train-ticket/deployments.json（rabbitmq 无 volumes、replicas=1、requests 100m/200Mi 无 limit、readiness 仅 tcpSocket 5672、无 liveness）；TT源码/ts-food-service/src/main/resources/application.yml:22-24 等（各服务都没有 listener 配置，取 Spring AMQP 2.2 默认值）
- **原编号 / 备注**：原编号 TT-D10、TT-E15。D10 从消息链路、E15 从基础设施记同一对象，合并。「消费方能自动重连」（容器每 5 s 无限重试）是有效保护，可作 N-04 / T-07 的阴性对照。

### TT-26〔C〕订单表只增不减：余票查询与管理查询的成本随运行时长单调上升，各 episode 的基线不可比
- **机制族 / 失效模式**：resource_limit + load_shedding_admission；主 D1；次 D5
- **业务链路**：搜索、查单、取消、管理后台
- **触发条件**：长时间跑默认负载即可，不需要注入。取消只改状态不删订单（约 1,080 单/小时），重置时 PVC 受保护，数据跨 episode 保留。
- **后果**：余票计算按 (日期, 车次) 查订单表且不过滤订单状态、没有索引，一次搜索要打 order 2N 次全表扫描，成本随历史订单线性增长。inside_money 每次取消追加一行，而退款的「账户存在」检查每次全量加载该用户全部记录（对 List 做 != null 判断，恒真）。admin-order 无分页地全量拉两张订单表。结果是取消与搜索的 p95 随运行时长漂移，基准的各 episode 之间不可比——这是对评测有效性的直接损害。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实数据只增（基线期间 orders 92 行、inside_money 89 行且持续增长），PVC 保护配置已核实。老化到 GC 抖动或 OOM 的程度没有实跑。
- **证据位置**：TT源码/ts-order-service/src/main/java/order/service/OrderServiceImpl.java:54-71、:302-311（按日期车次查、无索引不过滤状态；findAll 无分页）；TT源码/ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java:246、:247-251（每次取消 +1 行；存在性检查全量加载且恒真）；D0/environment/applications/train-ticket.yaml:109-110（重置时 PVC 受保护）；证据/TT-tsdb-runtime-config/myisam-locks-during-baseline.txt（09:24Z，orders 92 行、inside_money 89 行）
- **原编号 / 备注**：原编号 TT-B12、TT-D7、TT-D14。三条都是「数据只增导致的老化」，合并。order 接收队列停止排空是这条的极端后果，因为触发条件和现象都不同，单列为 TT-27。

### TT-27〔C〕order 接收队列停止排空、CLOSE_WAIT 与句柄堆积且不自愈，只能人工重启
- **机制族 / 失效模式**：load_shedding_admission + health_probe + resource_limit；主 D5（多因素组合）；次 D1、D4
- **业务链路**：下单、查单、搜索
- **触发条件**：订单累计到 10^4–10^5 行后跑基线，再对 tsdb 主库注入 CPU 压力或 200 ms 延迟。机制是「请求线程里的无界等待 + 调用方放弃后服务端不中止 + 没有 liveness」三者组合。
- **后果**：两个副本同时 0/2，下单、查单、搜索一起超时失败，TCP 探针失败后 Pod 被摘除但没有 liveness 不会重启，只能人工干预。这条能同时解释 CLOSE_WAIT 堆积、句柄耗尽和队列不排空三个现象。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。旧环境发生过（08-21），配置层根因已核实。本轮基线下没有复现：close-wait-during-baseline.txt 显示 order×2、gateway×1 的 CLOSE_WAIT 都是 0，Hikari 也没有排队——属于 3.2 节「基线下没复现，不能判否」。具体卡在哪里需要线程栈确认。
- **证据位置**：证据/TT-network-and-health/close-wait-during-baseline.txt（09:24Z，order×2、gateway×1 CLOSE_WAIT=0）；证据/RES-resource-pool-metrics/during-baseline-0918.txt（15 分钟内无排队等连接）；TT源码/ts-order-service/src/main/java/order/repository/OrderRepository.java:24、26（全表扫描）；清单/train-ticket/deployments.json（readiness tcpSocket:12031，无 livenessProbe）
- **原编号 / 备注**：原编号 TT-C1、TT-E06。C1 从下单链路、E06 从配置层记同一现象，合并。这是「S 级里最值得做注入验证」的一条：机制链完整，但基线下三个现象全部为 0。

### TT-28〔C〕JVM 堆固定 200MB 而容器上限 1500Mi：堆内 OOM 对 K8s 不可见，进程不退出又没有 liveness，服务僵死不重启
- **机制族 / 失效模式**：resource_limit + health_probe；主 D4（配额与运行时参数错配）；次 D1、D2
- **业务链路**：全部
- **触发条件**：大响应、全量订单查询或入口压测把堆压到 -Xmx200m 上限。
- **后果**：容器 1500Mi 的配额轮不到 OOMKill，堆内 OOM 后进程和端口都还在，TCP 探针照样通过，僵尸实例继续接流量。Dockerfile 没有 -XX:+ExitOnOutOfMemoryError。网关是 -Xmx1024m 加默认直接内存，可能超出容器上限。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实堆上限：ts-* 为 192–196Mi、网关 999Mi，而 request 100Mi、limit 1500Mi，实际工作集 465–859Mi。堆内 OOM 后果没有实跑。
- **证据位置**：证据/RES-resource-pool-metrics/during-baseline-0918.txt（ts-* 堆上限 192–196Mi、网关 999Mi；req 100Mi、lim 1500Mi；wss 465–848Mi）；证据/RES-resource-pool-metrics/steady-state-0916-0931.txt（09:16–09:31，wss 490–859Mi）；TT源码/ts-order-service/Dockerfile:6（-Xmx200m，无 ExitOnOutOfMemoryError）；清单/train-ticket/deployments.json（无 livenessProbe）
- **原编号 / 备注**：原编号 TT-B15、TT-C12、TT-E11、TT-E17。四组各记一次。E17 的「java:8-jre 不感知容器」部分已被运行时否定（实际是 Temurin 8u482，见 TT-X2），本条只保留堆与容器配额错配的部分。CPU 节流部分并入 TT-29。

### TT-29〔C〕资源请求严重失真（CPU 10m / 内存 100Mi）：稳态不节流，但全量重启时 41 个 JVM 同时冷启动形成恢复风暴
- **机制族 / 失效模式**：resource_limit；主 D5（恢复期资源争用）；次 D4
- **业务链路**：全部
- **触发条件**：节点故障重新调度，或平台重置流程 restart-application-deployments 触发全量重启。
- **后果**：request 只有 10m/100Mi 而实际工作集 465–859Mi，调度器按失真的请求值堆放 Pod。41 个 JVM 加 javaagent 同时冷启动时 CPU 争用剧烈，冷启动首请求约 9.7–10 s，正好撞上压测客户端 10 s 超时（见 TT-13）。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。**部分更正静态结论**：运行时实测稳态下没有任何 TT Pod 节流超过 1%，节流只出现在 JVM 启动期（travel 26%、assurance 22%、auth 22% 的窗口含 09:07–09:10 重启期）。所以「稳态被节流」不成立，成立的是「恢复期风暴」。
- **证据位置**：证据/RES-resource-pool-metrics/steady-state-0916-0931.txt（09:16–09:31，TT 无 Pod 节流 >1%）；证据/RES-resource-pool-metrics/during-baseline-0918.txt（节流 >1% 的窗口含 09:07–09:10 重启期：travel 26%、assurance 22%、auth 22%）；证据/TT-baseline-abort-first-run.txt（冷启动首请求 9712–10011 ms）；清单/train-ticket/deployments.json（ts-* request 10m/100Mi、limit 1.5 核/1500Mi）
- **原编号 / 备注**：原编号 TT-A11、TT-E13。A11 关注网关的 request/堆错配，E13 关注恢复风暴。运行时数据把「稳态节流」这一半否定了，合并后只保留恢复期这一半，这是本轮对静态结论的一处重要收窄。

### TT-30〔C〕没有 PDB、41 个服务单副本、多副本服务和三成员仲裁组都没有反亲和，本地盘还把 MySQL 钉在节点上
- **机制族 / 失效模式**：replica_disruption；主 D1（T-06 实例）；次 D2、D6
- **业务链路**：全部
- **触发条件**：排空一个节点，或 kill 任一单副本服务。新环境只有 2 个节点，TT 的 Deployment 又都被固定在 vm-0-10（偏差 #8）。
- **后果**：下单关键路径上有 6 个单副本依赖，任一重启就中断下单且不能自愈。排空承载 2 个 tsdb 成员的节点时，xenon 失去多数派，写入全断，而本地盘让被驱逐的成员只能等原节点回来。三个 MySQL 副本的数据卷在旧环境还都落在同一个 NFS 供给器上，副本不是独立故障域。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实：两个命名空间都没有 PDB；副本数已从旧环境注解逐个核实（gateway 3、ui-dashboard 3、auth/order/preserve 各 2，其余 43 个为 1）。节点排空没有实跑。
- **证据位置**：证据/SS-runtime-config/versions-and-config.txt（08:59Z，两个命名空间都无 PDB）；旧环境 Deployment 注解 resiliencebenchmark.io/standby-replicas（本轮只读核实：gateway 3、ui-dashboard 3、auth 2、order 2、preserve 2，其余 43 个为 1）；清单/train-ticket/deployments.json（无反亲和）；清单/train-ticket/statefulsets.json（三成员仲裁组无反亲和；旧环境三个 MySQL 数据卷同一 NFS 供给器）；DEVIATIONS.md 偏差 #8（新环境 TT 的 Deployment 与 nacos 固定在 vm-0-10）
- **原编号 / 备注**：原编号 TT-A13、TT-B07、TT-C11、TT-E09、TT-E16、TT-D13（部分）。**更正静态结论**：TT-B07 说「查询链路上 9 个服务都是单副本」，但 order 实际是 2 副本（已用旧环境注解核实）；任务描述里的「gateway 2、order 3」也与实际相反。E16（数据卷同一 NFS 供给器）只在旧环境成立，新环境用 openebs-hostpath，已被偏差 #1 改变。

### TT-31〔S〕网关唯一的准入保护 Sentinel 只覆盖 39 条路由中的 1 条，登录每次都做 BCrypt 却完全不限流
- **机制族 / 失效模式**：load_shedding_admission；主 D2；次 D4
- **业务链路**：登录、全部
- **触发条件**：登录流量激增或节点 CPU 受压。
- **后果**：BCrypt 是故意设计成慢的，每次登录都算一遍而没有任何限流，登录时延在 CPU 争用时飙升并拖累整个入口。Sentinel 只给一条管理路由限了流，对 SLO 路径没有保护。
- **证据等级**：S（仅源码/清单静态推断）。路由配置与 BCrypt 调用已核实，未实跑加压。
- **证据位置**：TT源码/ts-gateway-service/src/main/resources/application.yml:16–209（39 条路由，Sentinel 只覆盖 1 条）；TT源码/ts-auth-service/src/main/java/auth/service/impl/TokenServiceImpl.java:65-79（每次登录做 BCrypt）；证据/TT-call-graph-baseline/fanout.txt（登录 HTTP 1 跳、DB 3 次）
- **原编号 / 备注**：原编号 TT-A10、TT-E14（部分）。E14 的无超时部分并入 TT-11，限流部分在这里。

### TT-32〔S〕验证码的匿名接口每次都新建 HttpSession（保留 30 min），堆只有 200m 又没有限流
- **机制族 / 失效模式**：load_shedding_admission + resource_limit；主 D1
- **业务链路**：登录、其他
- **触发条件**：对无限流的匿名验证码接口持续 50 QPS 请求 30 分钟。
- **后果**：按 30 分钟会话保留期估算累积约 9 万个会话，200m 堆出现 Full GC 直至 OOM。
- **证据等级**：S（仅源码/清单静态推断）。接口与会话行为已核实，9 万这个量级是估算，未实跑。
- **证据位置**：TT源码/ts-verification-code-service/src/main/java/verifycode/controller/VerifyCodeController.java:37-38、:55（匿名接口每次新建 HttpSession）；TT源码/ts-verification-code-service/Dockerfile:6（-Xmx200m）
- **原编号 / 备注**：原编号 TT-A18。不在 SLO 路径上（基准负载的登录不带验证码），属于「可被外部流量打爆的旁路」。

### TT-33〔R〕ticket-office 每空闲 8 小时崩一次：单条 MySQL 连接被 wait_timeout 断开、代码没有 error 监听，进程直接退出
- **机制族 / 失效模式**：fallback_degradation + replica_disruption（重启恢复）；主 D3；次 D4
- **业务链路**：其他
- **触发条件**：进程空闲满 wait_timeout=28800 s（8 小时）。驱动报 PROTOCOL_CONNECTION_LOST，回调里 throw err 打崩整个进程，靠 CrashLoopBackOff 恢复。
- **后果**：本轮已复现并计数：每次重启都会再插一行种子数据，已累计 4 行。服务本身不在 SLO 路径上，但「每次重启重复插种子数据」会污染数据集，而且这是一个可预测的周期性崩溃。
- **证据等级**：R（本轮运行时已复现）。本轮新环境复现，机制与触发条件都已查清，并给出可证伪预测：下一次崩溃约在 2026-09-19 08:29 UTC（restartCount 应从 2 变 3，ts.office 表应从 4 行变 5 行）。**本轮未能验证该预测**——见附录 E 的未核实清单。
- **证据位置**：证据/TT-ticket-office-idle-connection-crash/README.txt（机制、触发条件、已累计 4 行种子数据、可证伪预测）；证据/TT-tsdb-runtime-config/tsdb-leader.txt（office 表是 3 张 InnoDB 之一）
- **原编号 / 备注**：原编号 TT-B17。静态报告只写到「一条 SQL 出错就打崩进程」，运行时补上了真正的触发条件（空闲 8 小时的 wait_timeout）并升为 R。ticket-office 跑的是 Node v25.8.1（Dockerfile 用 `FROM node` 不固定版本），与上游预期版本相差很远，见附录 E。

### TT-34〔C〕健康端点被 Spring Security 挡住返回 403，探针只能看 TCP，41 个服务全都没有 liveness
- **机制族 / 失效模式**：health_probe；主 D4；次 D1
- **业务链路**：全部
- **触发条件**：端口开着但进程已无法服务（线程耗尽、堆内 OOM、死锁）。
- **后果**：唯一能反映真实状态的 /actuator/health 返回 403，探针只能探 TCP 端口，而端口在进程僵死时照样开着。没有 liveness 意味着僵死的 Pod 永远不会被重启，会一直保持 Ready 并接收流量。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实 /actuator/health 返回 403，清单里的探针配置也已核实。僵死场景没有实跑。
- **证据位置**：证据/TT-network-and-health/probe.txt（09:01Z，travel Pod：actuator/health 403；Temurin 1.8.0_482；otel agent 2.23.0）；清单/train-ticket/deployments.json（readiness 仅 tcpSocket，d60/p10/t5/f3；无 livenessProbe）；TT源码/ts-auth-service/src/main/java/auth/config/WebSecurityConfig.java:94 等（health 端点未放行）
- **原编号 / 备注**：原编号 TT-A9、TT-B04（部分）、TT-E04（部分）、TT-D13（部分）。与 TT-02 的分工：本条是 K8s 侧的探针判定失灵，TT-02 是 Nacos 侧的健康判定失灵。两者叠加的后果是「两套健康判定都看不出问题」。

### TT-35〔S〕占座没有预留也没有唯一约束，并发下单会超卖；余票校验写错；售罄时 seat 服务死循环
- **机制族 / 失效模式**：idempotency_compensation + load_shedding_admission；主 D4；次 D1
- **业务链路**：下单
- **触发条件**：需要座位数很小且并发下单同一车次。默认数据下每种车型的座位数都是 Integer.MAX_VALUE，很难触发。
- **后果**：超卖；余票校验的比较写错；售罄时 seat 服务进入死循环。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实，但默认数据下触发不了，属于「需要改数据才能激活」的条目。
- **证据位置**：TT源码/ts-seat-service/src/main/java/seat/service/SeatServiceImpl.java:40-116（分座无预留、无唯一约束）；TT源码/ts-train-service/src/main/java/train/init/InitData.java（座位数为 Integer.MAX_VALUE）
- **原编号 / 备注**：原编号 TT-C15。定级已按约束「拿不准往低一档」处理：机制确定但默认数据下不可达。

### TT-36〔S〕UI 入口 nginx 单 worker、1024 连接、默认 60 s 超时、只有 TCP 探针，上游地址还只在启动时解析一次
- **机制族 / 失效模式**：load_shedding_admission + health_probe；主 D5；次 D4
- **业务链路**：UI入口
- **触发条件**：网关变慢到接近 nginx 的 60 s 默认超时。
- **后果**：单 worker 的 1024 连接被占满，TCP 探针失败，Pod 被逐个摘除形成连锁压垮。上游地址只在启动时解析一次，网关 Pod 换 IP 后 nginx 不会重新解析。
- **证据等级**：S（仅源码/清单静态推断）。nginx.conf 已核实，未实跑。ui-dashboard 不在压测 SLO 路径上（负载直连网关）。
- **证据位置**：TT源码/ts-ui-dashboard/nginx.conf:1、:4（单 worker）、:21（1024 连接）、:40-42（proxy_pass，默认 60 s）；清单/train-ticket/deployments.json（ui-dashboard 只有 TCP 探针；副本数 3）
- **原编号 / 备注**：原编号 TT-A16。

### TT-37〔S〕ischaos-tls-gateway 证书只在启动时加载，单副本且没有任何探针，证书过期后 TLS 全失败而 Pod 不重启
- **机制族 / 失效模式**：other（证书到期） + health_probe；主 D4；次 D6
- **业务链路**：UI入口、其他
- **触发条件**：证书过期或被更换。镜像 tag 就叫 tls-cert-expire。
- **后果**：TLS 握手全部失败，而没有探针意味着 Pod 不会被重启，也不会从 Service 摘除。
- **证据等级**：S（仅源码/清单静态推断）。清单已核实，未实跑。不在 SLO 路径上。
- **证据位置**：清单/train-ticket/deployments.json（ischaos-tls-gateway 单副本、无探针、镜像 tag 为 tls-cert-expire）
- **原编号 / 备注**：原编号 TT-A17。证书到期不属于 CODEBOOK 的九个机制族，归入 other。

### TT-38〔S〕JWT 在每一跳都用本 Pod 时钟做零容差过期校验，过期异常还逃出了过滤器连 permitAll 接口也被拦
- **机制族 / 失效模式**：other（时钟假设） + deadline_timeout；主 D4；次 D6
- **业务链路**：登录、全部
- **触发条件**：某个 Pod 时钟偏移 ≥61 分钟（token 有效期 60 分钟 + 零容差）。
- **后果**：该 Pod 上所有带 token 的请求都判过期；异常逃出过滤器后，连本该 permitAll 的接口也会被拦，故障面比预期大。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实，时钟偏移没有实跑（也没有核实各节点的时钟同步状态）。
- **证据位置**：TT源码/ts-common/src/main/java/edu/fudan/common/util/JWTUtil.java:100、:101–103（零容差校验）；TT源码/ts-common/src/main/java/edu/fudan/common/security/jwt/JWTFilter.java:28（异常逃出过滤器）
- **原编号 / 备注**：原编号 TT-A6。

### TT-39〔S〕voucher 在单线程 Tornado 的 IOLoop 里做没有超时的阻塞调用，一个慢依赖冻结全部请求
- **机制族 / 失效模式**：deadline_timeout + circuit_isolation；主 D1（T-01 实例）；次 D4
- **业务链路**：其他
- **触发条件**：并发调用 /getVoucher，同时给 order-service 注入延迟 d。
- **后果**：请求耗时呈 k×d 阶梯（第 k 个请求等 k×d），CPU 接近 0，就绪探针照常通过。凭证功能不可用，不影响主链路。
- **证据等级**：S（仅源码/清单静态推断）。源码已核实，未实跑。requirements.txt 没有锁 tornado / pymysql 版本，实际版本未核实。
- **证据位置**：TT源码/ts-voucher-service/server.py:14（同步 def post）、:158-164（单 IOLoop 线程）、:64-65（urlopen 无超时）、:32/:71（每请求新建 pymysql 连接）；清单/train-ticket/deployments.json（voucher 只有 TCP readiness 16101，无 liveness）
- **原编号 / 备注**：原编号 TT-D11。voucher 走 K8s DNS 不经 Nacos（server.py:47-48），是 TT-01 的天然阴性对照：Nacos 全停时 voucher 仍能正常启动。

### TT-40〔C〕StatefulSet 按序启动叠加多处没有超时的循环：一个成员卡住就挡住其余成员重建
- **机制族 / 失效模式**：replica_disruption（重启恢复） + deadline_timeout；主 D6；次 D5
- **业务链路**：全部
- **触发条件**：nacosdb 无主时重建 Nacos。OrderedReady 策略加上三处无超时的等待循环，nacos-0 卡在 Init 就挡住 1 和 2。
- **后果**：服务发现中断被放大：本该只影响一个成员的问题变成整个集群起不来，再触发 TT-01 的全量 CrashLoop。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。清单与启动脚本已核实。本轮运行时观察到相关现象：postStart 钩子没有总超时，容器停在 PodInitializing、拿不到日志、需要强删（ENV-pod-status-stuck-after-start）。但「一个成员挡住其余」的完整链条没有实跑。
- **证据位置**：清单/train-ticket/statefulsets.json（OrderedReady，无 podManagementPolicy: Parallel）；证据/ENV-pod-status-stuck-after-start/nacos-0.txt（07:06Z，Started 但 waiting/PodInitializing；after-parallel.txt 三成员 PodInitializing，8848/9848 拒绝、7848 开）；清单/train-ticket/configmaps.json（启动脚本里三处无超时循环）
- **原编号 / 备注**：原编号 TT-E12。

### TT-X1〔X〕（已否定）Nacos 冷启动死锁
- **机制族 / 失效模式**：other；—
- **业务链路**：全部
- **触发条件**：—
- **后果**：—
- **证据等级**：X（已否定）。不成立。真因是 Nacos 的外部数据库没有建表：`Table 'nacos.config_info' doesn't exist` → `No DataSource set` → Nacos failed to start。补表后原配置在 08:57:23Z 依次就绪。偏差 #9–#11 已据此撤回。
- **证据位置**：证据/TT-nacos-coldstart-deadlock/root-cause-no-datasource.txt（08:49Z）；证据/TT-nacos-coldstart-deadlock/README.md（冷启动死锁作废的说明）；DEVIATIONS.md 偏差 #9–#11（已撤回）
- **原编号 / 备注**：原编号 偏差 #9–#11（Nacos 冷启动死锁）。保留在正文里便于追溯：这是本轮唯一一个被完整推翻并找到真因的判断。

### TT-X2〔X〕（已否定）train-ticket 的 java:8-jre 基础镜像不感知容器限额
- **机制族 / 失效模式**：resource_limit；—
- **业务链路**：全部
- **触发条件**：—
- **后果**：—
- **证据等级**：X（已否定）。不成立。运行时实测容器里是 Temurin 1.8.0_482，该版本已支持 UseContainerSupport，会按容器限额而非宿主机核数配置 GC 与线程池。
- **证据位置**：证据/TT-network-and-health/probe.txt（09:01Z，travel Pod：Temurin 1.8.0_482；otel agent 2.23.0）
- **原编号 / 备注**：原编号 TT-E17（部分）、TT-C12（部分）、TT-A11（部分）、java:8-jre 不感知容器。被否定的只是「不感知容器」这一半；堆 200MB 与容器 1500Mi 错配的另一半仍然成立，见 TT-28。

### TT-X3〔X〕（部分否定）登录同步依赖验证码服务
- **机制族 / 失效模式**：fallback_degradation；—
- **业务链路**：登录
- **触发条件**：—
- **后果**：—
- **证据等级**：X（已否定）。在基准负载下不成立。Jaeger 显示登录只有网关→auth 一跳，负载不带验证码（generator:302-309）。只有在 UI 带验证码的路径上才成立。
- **证据位置**：证据/TT-call-graph-baseline/fanout.txt（登录 HTTP 1 跳，仅 gateway→auth）；D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py:302-309（登录不带验证码）
- **原编号 / 备注**：原编号 TT-A14（部分）。代码层面的缺陷（校验恒返回 true 却被同步依赖）仍记在 TT-16 里，只是基准负载触发不到。

### TT-41〔C〕部署镜像在主查询路径第一行植入了对 ts-traceenv-test 的同步调用，默认走无超时的共享连接池
- **机制族 / 失效模式**：deadline_timeout + circuit_isolation + other（插桩残留）；主 D1（无截止时间）；次 D4（复用了错配的连接池）、D6
- **业务链路**：搜索
- **触发条件**：每一次 POST /api/v1/travelservice/trips/left 都会触发，不需要注入——callTraceenvTest 在 queryByBatch 的方法体第一行（字节码 offset 2）。风险在 Nacos 返回了任何一个 ts-traceenv-test 地址时兑现（TT-02 记录的陈旧实例正是这种情况）。
- **后果**：部署清单里没有任何服务设置 TRACEENV_TEST_URL，所以走的是 else 分支：用共享的 @LoadBalanced RestTemplate（三种超时全无、每目标 5 条、整进程 10 条，见 TT-11）去调一个 Nacos 里没有实例的服务名。正常情况下 Ribbon 抛 No instances available 被 catch 吞掉，快速失败；一旦 Nacos 给出任何地址，这个调用就会用无超时连接去打它，按 tcp_syn_retries=6 单次最长挂约 127 s，并占用整进程仅有的 10 条连接之一。等于把 TT-02 和 TT-11 串成了一条现成的放大链路，入口就在 SLO 路径的第一行。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。本轮反编译实际部署的镜像核实：拉取 ts-travel-service:1.0.0 的 fat jar 层（sha256:cee94c3e…，73,585,634 字节，摘要与 manifest 一致），javap 反编译 TravelServiceImpl.class 得到完整方法体、两个调用点和异常表；并核对上游源码确认该方法不存在、核对 deployments.json 确认环境变量未设置。后果（打到死 IP 后挂 127 s）没有实跑。
- **证据位置**：证据/TT-rebuilt-image-provenance/README.md 第 4.2 节（callTraceenvTest 的反编译结果、两个分支、异常表 0–177 → 180）；TT源码/ts-travel-service/src/main/java/travel/service/TravelServiceImpl.java（上游该文件里 callTraceenvTest 出现 0 次，确认是镜像额外植入）；TT源码/ts-travel-service/src/main/java/travel/controller/TravelController.java:113、:123（POST /trips/left → queryByBatch，即压测主查询入口）；清单/train-ticket/deployments.json（ts-travel-service 的 env 只有 NODE_IP、6 个 OTEL_* 和 JAVA_TOOL_OPTIONS，没有 TRACEENV_TEST_URL）；证据/TT-network-and-health/probe.txt（09:01Z，tcp_syn_retries=6，连不存在的 IP 约 127 s 才失败）
- **原编号 / 备注**：原编号 （本轮镜像比对新增，不在 108 条静态候选内）。静态审计依据的是上游 313886e9，而上游没有这段代码，所以 108 条里不可能有它——这条正好说明「只审源码不看部署镜像」会漏掉什么。另外 5 个含 ts-traceenv-test 的服务（order、payment、preserve、preserve-other、train）改动模式相同，推测是同一套插桩，但**未反编译核实**。基线里没被发现是因为快速失败：本轮 search p95 只有 139 ms。

## 3. sock-shop 条目

### SS-01〔R〕发货链路两端都静默失败：shipping 吞掉发布异常仍回 201，queue-master 的发货必然失败却照常确认消息
- **机制族 / 失效模式**：delivery_semantics + fallback_degradation；主 D1（N-02：生产者无确认）；次 D3（兜底动作本身造成错误）、D2
- **业务链路**：结账、发货
- **触发条件**：不需要注入，默认负载就持续发生。queue-master 在 K8s 里必然失败——它要用 /var/run/docker.sock 起容器，而容器里根本没有这个文件。shipping 侧则在 RabbitMQ 不可用时触发。
- **后果**：本轮实测：15 分钟收到 433 条消息、失败 432 条，而同期 checkout 225 次 0 失败——发货链路末端 100% 静默失败，从业务指标上完全看不出来。队列积压始终为 0（失败消息照样 ack），shipping-task 队列 durable=false，broker 也没有卷，没有死锁队列兜底。shipping 端则是吞掉发布异常仍回 201，订单显示成功而发货消息静默丢失。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接复现，有 baseline-0918.txt：DockerSpawner 报错 351+81=432 次，队列 messages 0 / unacked 0 / consumers 1。
- **证据位置**：证据/SS-queue-master-swallowed-failures/baseline-0918.txt（09:23Z，15 分钟收到 433、失败 432，/var/run/docker.sock 不存在；shipping-task durable=false；同期 checkout 225 次 0 失败）；SS源码/queue-master-0.3.1/src/main/java/works/weave/socks/queuemaster/（发货异常被吞、AUTO ack）；SS源码/shipping-0.4.8/src/main/java/works/weave/socks/shipping/controllers/ShippingController.java:42-48（发布异常被吞仍回 201）；清单/sock-shop/deployments.json（rabbitmq 无持久卷）
- **原编号 / 备注**：原编号 SS-07、SS-23。两条是同一条发货链路的前后两段（生产端 shipping、消费端 queue-master），合并。这是 sock-shop 唯一一条「默认负载下 100% 持续发生、却完全不影响 SLO」的缺陷，对基准而言是最典型的灰色故障样本。与 TT-24 是跨系统同构缺陷。

### SS-02〔C〕front-end 的回调没有 error 兜底、先解析后判错：一个下游错误就打崩整个 Node 进程，放大成分钟级全站中断
- **机制族 / 失效模式**：fallback_degradation + circuit_isolation；主 D4（错误处理写错）；次 D5（与就绪延迟、重启退避叠加）
- **业务链路**：加购、结账、全站
- **触发条件**：catalogue 不可达时，加购回调先执行 `JSON.parse(undefined)` 再判错；user 回 500 JSON、或有地址/卡但属性查询失败时回 200 却缺 `_links`，结账回调抛 TypeError。
- **后果**：整个 front-end 进程退出，而 front-end 是全站唯一入口。叠加 catalogue 的 180 秒就绪延迟和重启退避，一次 catalogue 重启会被放大成 3–7 分钟的全站中断。user-db 抖一下就能打崩全站。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。源码路径已核实（报错栈行号 orders:67 / cart:79 / orders:91、:106）。崩溃没有实跑。量级取决于 kube-proxy 模式：Service 没有端点时是立即被拒（iptables）还是被丢包挂起（部分 IPVS/eBPF 实现），前者立刻崩、后者约 127 秒后超时再崩——未核实。
- **证据位置**：SS源码/front-end-0.3.12/api/cart/index.js:79（JSON.parse 在判错之前）；SS源码/front-end-0.3.12/api/orders/index.js:67、:91、:106（结账回调缺 error 守卫）；清单/sock-shop/deployments.json（catalogue readiness initialDelaySeconds 180）
- **原编号 / 备注**：原编号 SS-02、SS-03。两条后果完全一样（进程退出→就绪延迟→退避→全站中断），报告自己也只能靠报错栈行号区分，合并。负控制：客户没有地址或卡时不会崩（返回 []、前端守卫短路、orders 以 406 拒单），真正会崩的是「有地址/卡但属性查询失败」那一支。

### SS-03〔C〕session-db 没有持久化而 logged_in cookie 仍有效：会话一丢，customerId 变成 undefined，购物车串单并打崩结账
- **机制族 / 失效模式**：replica_disruption + fallback_degradation；主 D2；次 D5
- **业务链路**：登录、购物车、结账
- **触发条件**：session-db（Redis）重建。Redis 8.10.1 配的是 save "" 且 appendonly no，重启即清空；而客户端仍持有 logged_in cookie。
- **后果**：旧 sid 查不到就新建会话（saveUninitialized:true），customerId 成为 undefined：所有此类用户共用同一个「undefined 购物车」，互相串单；结账时让 front-end 进入崩溃循环，故障消失后也不会自动恢复——这正是「恢复后回不来」，属于要保留的例外情形。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。Redis 持久化配置已在运行时核实（save 空、appendonly no）。串单与崩溃循环没有实跑。express-session 的实际版本待核（该行为在 1.x 中一致）。
- **证据位置**：证据/SS-runtime-config/versions-and-config.txt（08:59Z，session-db save 空、appendonly no；express-session 1.15.1、connect-redis 3.2.0、redis 2.7.1）；清单/sock-shop/deployments.json（session-db 无持久卷、BestEffort）；SS源码/front-end-0.3.12/（saveUninitialized:true）
- **原编号 / 备注**：原编号 SS-01。这一条是修复记录的直接后果：那次修补把 session-db 的「写不进」换成了「重启即清空」。与 TT-23（注册跨库双写）同属「身份数据不一致导致用户永久不可用」。

### SS-04〔C〕探针判定与真实服务能力脱节：四个 Java 服务完全没有探针、自带 /health 恒回 200，front-end 探针打的是静态页
- **机制族 / 失效模式**：health_probe；主 D1（T-05 实例）；次 D2、D4
- **业务链路**：全站
- **触发条件**：session-db 挂起（连接没断）时，除静态文件外的全站请求都会挂住，而 front-end 的探针打的是静态页，始终为绿；carts/orders/shipping/queue-master 则根本没有探针。
- **后果**：服务在启动期就被当成可用；死锁、堆耗尽、依赖挂起这些情况都不会被探测到，也不会触发重启。会话降级只在「连接断开」时才生效，挂起（连接还在）时不生效。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。清单与 /health 实现已核实。挂起场景没有实跑；express-session 在存储挂起时的行为靠库默认推断，connect-redis/redis 不在 yarn.lock 里，属未核实。
- **证据位置**：清单/sock-shop/deployments.json（carts、orders、shipping、queue-master 无任何探针）；SS源码/carts-0.4.8/src/main/java/works/weave/socks/cart/（/health 恒返回 200）；清单/sock-shop/deployments.json（front-end 探针指向静态页）
- **原编号 / 备注**：原编号 SS-18、SS-05。SS-05 的出站无超时部分并入 SS-06，探针部分在这里。与 TT-34 是跨系统同构缺陷。

### SS-05〔C〕启动不到一秒的 Go 服务配了 180 秒固定就绪延迟又没有 startupProbe，存活探针还在处理函数里同步 Ping 远程库
- **机制族 / 失效模式**：health_probe + replica_disruption（重启恢复）；主 D6；次 D4、D5
- **业务链路**：浏览、结账、登录、全站
- **触发条件**：payment、catalogue、user 任何一次重启；或它们的数据库中断约 6–9 秒（periodSeconds 3 × failureThreshold 3，按相位不同）。
- **后果**：每次重启都意味着该服务至少 3 分钟完全不可用——而实际启动只要不到一秒。探针在处理函数里同步 Ping 远程数据库，把「依赖故障」误判成「自己不健康」而自杀重启，重启后又被初始化循环和 180 秒就绪延迟拖成至少 3 分钟不可用，形成故障放大。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。清单配置已核实。重启放大链条没有实跑。同一个 /health 端点对两类故障给出相反结论：数据库快速拒连时 Ping 立刻返回、探针恒绿；数据库慢或被黑洞时才被杀。
- **证据位置**：清单/sock-shop/deployments.json（payment/catalogue/user 的 readiness initialDelaySeconds 180、liveness 300，无 startupProbe）；SS源码/catalogue-0.3.5/（/health 处理函数里同步 Ping 远程库）；SS源码/user-0.4.7/main.go:99-110（启动初始化循环）
- **原编号 / 备注**：原编号 SS-06、SS-04。标题里的时间阈值，静态报告有三种说法（约 9 秒 / 约 6–9 秒 / ≥9 秒）；按 periodSeconds×failureThreshold 推是 6–9 秒（取决于相位），这里取 6–9 秒。负控制：catalogue 启动不依赖数据库，所以这 180 秒是纯配置冗余而不是真实等待。

### SS-06〔C〕出站调用普遍没有超时：front-end 全部出站无超时，carts/orders 的 Mongo 只设了服务器选择超时
- **机制族 / 失效模式**：deadline_timeout + circuit_isolation；主 D1；次 D2、D4
- **业务链路**：全站、登录、购物车
- **触发条件**：任一下游变慢或黑洞；数据库在建连之后挂起。
- **后果**：front-end 的出站请求没有超时，Node 在 120 秒后断开客户端连接却不取消出站请求，这些请求也不进延迟直方图——故障在监控上不可见。Mongo 只配了服务器选择超时、没有读写超时，建连后库挂起时请求线程无限阻塞在 socket 读上。登录时合并购物车做了「出错就忽略」的降级却没有超时，carts 一变慢，登录就被一个非关键依赖拖住。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。源码与配置已核实（版本在 yarn.lock 与 Dockerfile 里有据）。但行为本身靠库默认推断：request 2.x 默认不超时、Node 4 的 server.timeout=120 秒、Spring Boot 1.4.4 管理的 Mongo 驱动 3.2.x 默认 socketTimeout=0——jar 内实际驱动版本未核实。
- **证据位置**：SS源码/front-end-0.3.12/（所有出站调用无 timeout 参数；yarn.lock 里 request 2.81.0）；SS源码/carts-0.4.8/src/main/java/works/weave/socks/cart/（Mongo 只设 serverSelectionTimeout）；SS源码/front-end-0.3.12/api/user/index.js:286-293（登录合并购物车的降级只处理快速失败）；证据/SS-runtime-config/versions-and-config.txt（08:59Z，Java 服务 openjdk 1.8.0_111）
- **原编号 / 备注**：原编号 SS-15、SS-16、SS-17、SS-05（部分）。SS-16 是 SS-15 在 `GET /login → carts/merge` 这一条路由上的实例，严格子集。负控制：登录对 carts 的快速失败确有有效降级，只有「变慢或挂起」才成立。与 TT-11、TT-12 是跨系统同构缺陷。

### SS-07〔S〕下单流程是「付款 → 发货 → 写 orders-db」，既没有补偿也没有幂等键；5 秒超时只放弃等待、不取消调用
- **机制族 / 失效模式**：idempotency_compensation + deadline_timeout；主 D1；次 D2
- **业务链路**：结账
- **触发条件**：orders-db 不可用或挂起；或下游慢于 5 秒。
- **后果**：钱已经付了、货已经发了，却没有订单，且没有任何补偿。5 秒超时只是放弃等待、不取消调用，底层 RestTemplate 也没有连接/读超时：下游慢于 5 秒时，被判失败的订单照样发货；下游挂起时线程随故障时长线性堆积。
- **证据等级**：S（仅源码/清单静态推断）。源码路径已核实（OrdersController.java:85-117 的三步顺序）。没有实跑注入。orders 的异步执行器无上限是 Spring 默认行为推断，未在镜像内核实。
- **证据位置**：SS源码/orders-0.4.7/src/main/java/works/weave/socks/orders/controllers/OrdersController.java:85-117（付款→发货→写库三步，无补偿无幂等键）；SS源码/orders-0.4.7/src/main/java/works/weave/socks/orders/（5 秒超时只放弃等待，不取消；SimpleAsyncTaskExecutor 无上限）
- **原编号 / 备注**：原编号 SS-08、SS-11。两条引用同一段「付款→发货→落库」代码，只是失败点不同，合并。负控制：orders 等待下游确有 5 秒上限（只是不取消）。与 TT-18、TT-19 是跨系统同构缺陷。

### SS-08〔R〕购物车明细只增不删、加购还是非原子的读-改-写，5 个虚拟用户共用一个账号的购物车
- **机制族 / 失效模式**：idempotency_compensation + resource_limit；主 D1；次 D4
- **业务链路**：加购、购物车、结账
- **触发条件**：默认负载就持续发生：结账只删购物车、不删明细；5 个闭环用户共用一个账号，加购的读-改-写交错。
- **后果**：本轮实测：carts-db 里 cart 表 0 条而 item 表 580 条——明细行永久泄漏，数据库单调增长。购物车懒创建且没有唯一约束，别人的清空和加购会交错进自己的订单，件数金额不确定，各 episode 之间不可比。
- **证据等级**：R（本轮运行时已复现）。本轮新环境直接核实（cart 0 条 / item 580 条）。「超过支付限额」这一现象在修补后已不再复现（最坏 79.99 不超限），剩下的是件数金额不确定。
- **证据位置**：证据/SS-runtime-config/versions-and-config.txt 及 carts-db 计数（cart 0 条、item 580 条）；SS源码/carts-0.4.8/src/main/java/works/weave/socks/cart/（非原子读-改-写，购物车懒创建无唯一约束）；D0/environment/workloads/sock-shop/locustfile.py:32（5 个闭环用户共用一个账号）
- **原编号 / 备注**：原编号 SS-22。负控制：carts 会拦截缺 itemId 的写入，不写脏数据。这一条与 TT-26 同属「数据只增导致 episode 不可比」，对基准有效性的损害大于对业务的损害。

### SS-09〔C〕有状态组件全部没有持久卷且都是 BestEffort，14 个 Deployment 全单副本、无反亲和、无 PDB
- **机制族 / 失效模式**：replica_disruption + resource_limit；主 D1（T-06、T-10 实例）；次 D2
- **业务链路**：全站
- **触发条件**：排空任一节点，或任一组件重建。
- **后果**：drain 一个节点即全站中断。所有数据库都没有卷、都是 BestEffort，内存压力下最先被驱逐；user-db 一重建，压测账号的地址和卡（运行期绑定的）就丢了，结账可能永久失败——这是「恢复后回不来」的又一实例。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。运行时已核实：两个命名空间都没有 PDB，*-db / rabbitmq / session-db 都是 BestEffort。节点排空没有实跑。导出清单不含 PDB/HPA/NetworkPolicy 这类资源，PDB 的缺失是在集群上核实的。压测账号究竟是种子账号还是运行期注册的，未核实——这一点决定严重度。
- **证据位置**：证据/SS-runtime-config/versions-and-config.txt（08:59Z，*-db / rabbitmq / session-db 为 BestEffort；两个命名空间都无 PDB）；清单/sock-shop/deployments.json（14 个 Deployment 全单副本、无反亲和、无持久卷）；D0/environment/repairs/sock-shop-workload-dependency-compatibility-20260822.yaml（地址与卡运行期绑定）
- **原编号 / 备注**：原编号 SS-09、SS-20。SS-20 的 E3 直接引用 SS-09，合并。与 TT-30 是跨系统同构缺陷。

### SS-10〔C〕整条链路的错误码分类都不准，front-end 还把下游错误改写成 200：压测中一半的浏览流量对故障完全看不见
- **机制族 / 失效模式**：fallback_degradation；主 D4；次为潜在的 D3
- **业务链路**：浏览、结账、全站
- **触发条件**：catalogue 侧任何故障；以及不可重试的客户端错误、数据库故障、带副作用的超时。
- **后果**：不可重试的客户端错误回 500，数据库故障回 404，带副作用的超时也回 500。front-end 把下游错误一律改写成 200，而浏览流量占压测的一半——对 catalogue 侧故障完全失明。错误预算、熔断决策和重试决策会一起失真。
- **证据等级**：C（运行对象/配置已核实存在，后果未实跑）。分类事实已在源码里核实。危害需要有重试层才会发生，而应用层没有任何重试（T-03 重试放大不成立）——前提是没有 sidecar，这一点未核实。
- **证据位置**：SS源码/front-end-0.3.12/（下游错误被改写成 200）；SS源码/catalogue-0.3.5/（数据库故障被报成 404）；D0/environment/workloads/sock-shop/locustfile.py（浏览流量约占一半）
- **原编号 / 备注**：原编号 SS-14、SS-13。SS-13 是 SS-14 总纲下的一个实例，合并。与 TT-15 是跨系统同构缺陷，两者都直接损害基准的可观测性。

### SS-11〔S〕catalogue 熔断器的参数和错误分类都有问题：连续 6 次请求不存在的商品就让所有人 30 秒无法加购
- **机制族 / 失效模式**：circuit_isolation；主 D4；次 D2
- **业务链路**：加购、浏览
- **触发条件**：客户端连续请求 6 次不存在的商品（正常的 404 被计成失败）。
- **后果**：熔断器跳闸后所有人 30 秒内无法加购——一个客户端的错误请求能让全体用户不可用。数据库故障被报成 404 不计入失败，慢故障也不计入失败，真正该跳闸的时候反而不跳。
- **证据等级**：S（仅源码/清单静态推断）。熔断器只设了 Timeout 这一点已核实，但 gobreaker 809bcd5 的源码没落地，「连续失败超过 5 次跳闸、半开只放行 1 个请求」是按文档默认值推断的，而整条候选的量级就建立在这个阈值上。
- **证据位置**：SS源码/front-end-0.3.12/（熔断器只设 Timeout）；SS源码/catalogue-0.3.5/（数据库故障归成 404）
- **原编号 / 备注**：原编号 SS-12。负控制：payment 的熔断器永远不会跳闸（端点恒返回 nil error）。这条是 SS 里「保护动作本身造成故障」（D3 边界）的典型。

### SS-12〔S〕user 的用户名唯一索引只在服务启动时建一次：user-db 重建后去重保护悄悄消失，一旦重名就永远起不来
- **机制族 / 失效模式**：idempotency_compensation + retry_backoff；主 D2；次 D5
- **业务链路**：注册、登录
- **触发条件**：user-db 重建后出现重名用户，然后 user 重启。当前压测不做注册，需要人或被测智能体制造重名。
- **后果**：去重保护消失后一旦出现重名，下次 user 重启会卡在一个不退避、还泄漏会话的初始化死循环里，永远起不来——「恢复后回不来」的实例。
- **证据等级**：S（仅源码/清单静态推断）。代码链完整且已核实，但需要「重名注册」这个前置条件，当前负载不触发。MongoDB 3.0 起 dropDups 被忽略这一点是库行为推断。
- **证据位置**：SS源码/user-0.4.7/main.go:99-110（唯一索引只在启动时建一次；不退避的初始化死循环，且泄漏会话）
- **原编号 / 备注**：原编号 SS-10。与 SS-05 引用同一段 main.go:99-110，但那里是「能自愈」的形态（user-db 恢复后循环能退出），这里是「永不自愈」的形态。与 TT-23 是跨系统同构缺陷。

### SS-13〔R〕CPU limit 按平均用量配、没留突发余量：5 个用户就让 carts 节流 33%、orders 24%，而平均用量只有约 0.06 核
- **机制族 / 失效模式**：resource_limit；主 D4；次 D2
- **业务链路**：购物车、加购、结账
- **触发条件**：默认负载（5 个闭环用户、约 5 流程/秒）就会触发，不需要注入。
- **后果**：本轮实测：压测期间 carts 节流 33.3%（实际用量 0.061 核，limit 300m）、orders 节流 23.9%（0.054 核，limit 500m）、shipping 9.8%、queue-master 5.1%，而空闲时全部约 0%。与 GET /cart 的 P99 600 ms 同时出现。另有静态问题：JVM 堆 128 MiB 远低于 500 Mi 限额，堆内 OOM 时不退出，对 K8s 不可见。
- **证据等级**：R（本轮运行时已复现）。节流数据本轮实测得到，压测/空闲两组对照清楚。堆内 OOM 的后果没有实跑；msd-java 基础镜像的 JDK 版本未知，Go 1.7 按宿主核数调度也是运行时默认行为推断。
- **证据位置**：证据/RES-resource-pool-metrics/ss-throttle-load-vs-idle.txt（压测 09:11–09:20：carts 33.3%、orders 23.9%、shipping 9.8%、queue-master 5.1%、front-end 1.9%；空闲 09:21–09:30 全部约 0%）；证据/SS-baseline/locust-summary.txt（09:10:26–09:20:26，5 用户，1955 请求 0 失败；GET /cart 中位 9 ms、P99 600 ms、max 701 ms）；证据/RES-resource-pool-metrics/during-baseline-0918.txt（SS 内存：carts 74%、orders 78%、queue-master 64%、shipping 69%，limit 500Mi）；清单/sock-shop/deployments.json（carts limit 300m、orders limit 500m；JVM 堆 128 MiB）
- **原编号 / 备注**：原编号 SS-19。静态报告只写了堆与限额错配（SS-19），CPU 节流是本轮运行时新发现的，合并进来并升为 R。与 TT-29 恰好相反：TT 稳态不节流，SS 在默认负载下就节流三成。

### SS-14〔S〕front-end 到 session-db 的重连退避没有上限，累计 1 小时后永久放弃
- **机制族 / 失效模式**：retry_backoff；D4（N-04 实例）
- **业务链路**：全站
- **触发条件**：session-db 断开时间较长。
- **后果**：断开越久重连越晚（退避没有最大间隔），累计 1 小时后永久放弃，期间持续返回 500 且不会自行恢复——「恢复后回不来」的实例。
- **证据等级**：S（仅源码/清单静态推断）。**证据最弱的一条**：redis 库根本不在 yarn.lock 里，「退避系数 1.7、没有最大间隔、累计 1 小时后放弃」全部是 node_redis 2.x 的文档默认值推断，库版本未核实。报告自评「低到中」。
- **证据位置**：SS源码/front-end-0.3.12/（重连配置；库版本不在 yarn.lock 中，待核）；证据/SS-runtime-config/versions-and-config.txt（08:59Z，redis(client) 2.7.1——与推断所用的 2.x 一致，但退避参数未直接核实）
- **原编号 / 备注**：原编号 SS-21。负控制：session-db 快速拒连时 front-end 有降级。本条按约束「拿不准往低一档」定 S，且在附录 E 里列为证据最弱的五处之一。

## 4. 注入实验设计（只写设计，本轮未执行）

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

## 5. 附录

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

### 附录 F　原编号 → 终稿编号对照表

108 条静态候选、5 条运行时编号（TT-RT-01～05）和偏差日志里已撤回的判断，逐条列出去向。括号里的“部分”表示该原条目被拆到多条终稿里。

| 原编号 | 终稿去向 |
|---|---|
| TT-A1 | TT-02 |
| TT-A2 | TT-03 |
| TT-A3 | TT-01 |
| TT-A4 | TT-02 |
| TT-A5 | TT-16 |
| TT-A6 | TT-38 |
| TT-A7 | TT-13 |
| TT-A8 | TT-11 |
| TT-A9 | TT-34 |
| TT-A10 | TT-31 |
| TT-A11 | TT-29；TT-X2（部分） |
| TT-A12 | TT-06（部分）；TT-12 |
| TT-A13 | TT-30 |
| TT-A14 | TT-16；TT-X3（部分） |
| TT-A15 | TT-23 |
| TT-A16 | TT-36 |
| TT-A17 | TT-37 |
| TT-A18 | TT-32 |
| TT-B01 | TT-11 |
| TT-B02 | TT-12（部分） |
| TT-B03 | TT-02 |
| TT-B04 | TT-02；TT-34（部分） |
| TT-B05 | TT-13 |
| TT-B06 | TT-01 |
| TT-B07 | TT-30 |
| TT-B08 | TT-17 |
| TT-B09 | TT-16 |
| TT-B10 | TT-16 |
| TT-B11 | TT-14 |
| TT-B12 | TT-26 |
| TT-B13 | TT-07 |
| TT-B14 | TT-15 |
| TT-B15 | TT-28 |
| TT-B16 | TT-14 |
| TT-B17 | TT-33 |
| TT-C1 | TT-27 |
| TT-C2 | TT-18 |
| TT-C3 | TT-19 |
| TT-C4 | TT-02 |
| TT-C5 | TT-13 |
| TT-C6 | TT-11 |
| TT-C7 | TT-10 |
| TT-C8 | TT-18 |
| TT-C9 | TT-07 |
| TT-C10 | TT-16 |
| TT-C11 | TT-30 |
| TT-C12 | TT-28；TT-X2（部分） |
| TT-C13 | TT-19 |
| TT-C14 | TT-24 |
| TT-C15 | TT-35 |
| TT-D1 | TT-15 |
| TT-D2 | TT-20 |
| TT-D3 | TT-21 |
| TT-D4 | TT-22 |
| TT-D5 | TT-19 |
| TT-D6 | TT-16 |
| TT-D7 | TT-26 |
| TT-D8 | TT-24 |
| TT-D9 | TT-24 |
| TT-D10 | TT-25 |
| TT-D11 | TT-39 |
| TT-D12 | TT-19 |
| TT-D13 | TT-01（部分）；TT-11（部分）；TT-30（部分）；TT-34（部分） |
| TT-D14 | TT-26 |
| TT-E01 | TT-05 |
| TT-E02 | TT-01 |
| TT-E03 | TT-04 |
| TT-E04 | TT-02；TT-34（部分） |
| TT-E05 | TT-11 |
| TT-E06 | TT-27 |
| TT-E07 | TT-07 |
| TT-E08 | TT-03 |
| TT-E09 | TT-30 |
| TT-E10 | TT-08 |
| TT-E11 | TT-28 |
| TT-E12 | TT-40 |
| TT-E13 | TT-29 |
| TT-E14 | TT-11（部分）；TT-31（部分） |
| TT-E15 | TT-25 |
| TT-E16 | TT-30 |
| TT-E17 | TT-28；TT-X2（部分） |
| TT-E18 | TT-06 |
| TT-E19 | TT-08 |
| TT-E20 | TT-09 |
| TT-E21 | TT-09 |
| TT-RT-01 | TT-05 |
| TT-RT-02 | TT-04 |
| TT-RT-03 | TT-01 |
| TT-RT-04 | TT-06 |
| TT-RT-05 | TT-33（ticket-office 空闲连接崩溃） |
| SS-01 | SS-03 |
| SS-02 | SS-02 |
| SS-03 | SS-02 |
| SS-04 | SS-05 |
| SS-05 | SS-04；SS-06（部分） |
| SS-06 | SS-05 |
| SS-07 | SS-01 |
| SS-08 | SS-07 |
| SS-09 | SS-09 |
| SS-10 | SS-12 |
| SS-11 | SS-07 |
| SS-12 | SS-11 |
| SS-13 | SS-10 |
| SS-14 | SS-10 |
| SS-15 | SS-06 |
| SS-16 | SS-06 |
| SS-17 | SS-06 |
| SS-18 | SS-04 |
| SS-19 | SS-13 |
| SS-20 | SS-09 |
| SS-21 | SS-14 |
| SS-22 | SS-08 |
| SS-23 | SS-01 |
|  | TT-41（本轮镜像比对新增，不在 108 条静态候选内） |
| N-01（OTel 同步导出） | 附录 D（观测缺口）——负控制，未成立 |
| T-03（重试放大） | 附录 A（排除清单）——TT 侧无实例，SS 侧仅 SS-14 的潜在 D3 |
| java:8-jre 不感知容器 | TT-X2 |
| 偏差 #9–#11 | TT-X1（Nacos 冷启动死锁） |
