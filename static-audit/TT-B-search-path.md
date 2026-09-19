# train-ticket 查询车次链路韧性排查（只读静态审计）

共找到 17 条候选缺陷，12 条属于 D2–D6。协调方补充的三条运行时事实已分别写进 TT-B06（Nacos 不可用）、TT-B03（Nacos 陈旧副本与扇出放大）、TT-B13（主库切换），并补上了代码和配置层面的根因。

- **过程**：没有改任何文件，没有访问集群或网络。
- **库行为怎么核实的**：依据上游 pom 解析出库版本，用本机 `~/.m2` 里同版本 jar 做 `javap` 反汇编核实，下文标记为「lib」。
- **最大的前提**：部署镜像里的 jar 是否就是这些版本，需要运行时确认（清单第 1 条）。

**路径简写**
- S = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/benchmark-sources/train-ticket-upstream`。Java 文件都在 `S/<服务>/src/main/java/` 下，正文只写"类名:行号"。
- M = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/multisystem-audit-20260918/manifests/train-ticket`
- P = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/resiliencebenchmark-stage2-d0-integration/environment/applications/train-ticket.yaml`
- W = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/resiliencebenchmark-stage2-d0-integration/environment/workloads/train-ticket`

## 查询链路调用图（运行时 trace 核对的基准）

入口是负载的 `POST /api/v1/travelservice/trips/left`（`W/image/train_ticket_workload_generator.py:319-330`）。负载客户端的连接超时 3s、响应超时 10s（同文件 `:584-585`）。

| # | 调用边 | 接口 | 每次查询调用几次 | 串行/并行 | 超时 | 错误处理 | 证据 |
|---|---|---|---|---|---|---|---|
| 1 | 网关→travel | `lb://ts-travel-service`，走 Nacos + Ribbon | 1 | – | 无（yml 里没有任何 timeout 键） | – | `S/ts-gateway-service/src/main/resources/application.yml:196-199` |
| 2 | travel→travel 库 | `findAll`，取全部 T 个车次 | 1 | 串 | JDBC 无 | 直接抛出 | `TravelServiceImpl.java:214` |
| – | 短路 | 出发日早于今天：直接返回空列表，不产生任何下游调用 | – | – | – | – | `:325-328` |
| 3 | travel→basic | `POST /basic/travels`，一次批量带上全部 T 个车次 | 1 | 串 | 无 | 没有 try；basic 返回 status 0 或反序列化失败，都变成"成功+空列表" | `:345-365` |
| 3a | basic→station | `POST /stations/idlist` | 1 | 串 | 无 | status 0 → 返回 null | `BasicServiceImpl.java:184, :341-356` |
| 3b | basic→train | `POST /trains/byNames` | 1 | 串 | 无 | 同上 | `:209, :372-387` |
| 3c | basic→route | `POST /routes/byIds/`；route 端再执行 1+2R 条 SQL（懒加载） | 1 | 串 | 无 | 同上 | `:232, :403-421`；`RouteRepository.java:31-32`；`Route.java:28-34` |
| 3d | basic→price | `POST /prices/byRouteIdsAndTrainTypes` | 1 | 串 | 无 | 没有 try；结果为 null 时在 `:286` 抛 NPE | `:272, :457-483` |
| 4 | travel→seat | `POST /seats/left_tickets`，一等、二等各 1 次 | **2N** | 串，在 for 循环里 | 无 | 没有 try，任何一次失败整个查询 500 | `TravelServiceImpl.java:367-375, :426-430, :550-557` |
| 4a | seat→order（G/D 车次）或 order-other（其余） | `POST /order/tickets` | **2N** | 串 | 无 | 没有 try | `SeatServiceImpl.java:138-168` |
| 4a' | order→order 库 | 按 (日期, 车次) 查询，无索引、不过滤订单状态 | 2N | – | JDBC 无 | – | `OrderServiceImpl.java:54-71`；`Order.java:19-55` |
| 4b | seat→config | `GET /configs/DirectTicketAllocationProportion` | **2N** | 串 | 无 | 没有 try；配置缺失时抛 NPE | `SeatServiceImpl.java:190, :205-219` |

**调用次数**
- 网关以下共 **5+6N** 次 HTTP 调用，算上网关这一跳是 6+6N 次。
- 只有这一种重试：Ribbon 对 GET 请求在连接异常后换"下一台"再试 1 次（第 4b 条是 GET，lib 核实）；POST 从不重试。
- N 是"线路先经过起点再经过终点"的车次数，过滤逻辑在 `BasicServiceImpl.java:242-264`。按种子数据：
  - Shang Hai→Su Zhou：N=1，只有 D1345（route `InitData.java:89-92`，travel `InitData.java:69-77`）。共 11 个客户端 span、19 条 SQL（15+4N，R=5）。
  - nanjing→shanghai：N=3，共 23 个客户端 span。

**同构链路与其他入口**
- travel2 结构完全相同：`Travel2Controller.java:105-117` → travel2 的 `TravelServiceImpl.java:239-294, :448-472`；K/Z/T 车次的 seat 调 order-other。
- 单车次详情 `trip_detail`（下单和 route-plan 会调）：basic 走 `/basic/travel`，共 station GET×2、train、route、price 各 1 次 GET（`BasicServiceImpl.java:49-98`），再加 2 次 seat。
- route-plan / travel-plan 的放大链见 TT-B16。

---

### TT-B01 隐性连接池舱壁配错：每个目标 5 条、每个进程共 10 条连接，拿连接无限等待
- **机制族 / 失效模式**：circuit_isolation / 主 D4，次 D5（与"无超时、无取消"叠加）。模板 T-04 实例。
- **位置**：travel（→basic、seat）、seat（→order、config）、basic（→4 个下游）各自的 RestTemplate。
- **成立条件**
  - E1 成立：RestTemplate 只做了 `builder.build()`（`TravelApplication.java:30-34`，其余服务同）。类路径上有 Apache HttpClient（nacos-discovery 2.2.7 → ribbon 2.2.9 → ribbon-httpclient 2.3.0 传递引入），Boot 2.3.12 因此选用 `HttpComponentsClientHttpRequestFactory`。它的默认构造调用 `HttpClients.createSystem()`，`http.maxConnections` 默认 "5"，于是每个路由 5 条、总共 10 条（lib）。
  - E2 成立：连接、读、租约（从池里拿连接）三类超时都没设，拿不到连接的线程会一直等。
  - E3 成立：同一个池同时承载查询和下单两条业务。下单路径是 preserve→travel `/trip_detail`（`PreserveServiceImpl.java:366`）和 preserve→seat 分座（`SeatServiceImpl.java:40-116`）。
  - E4 成立：全仓只有网关用了 Sentinel，服务里没有熔断、舱壁或限流。Tomcat 为 200 线程（lib）。
  - E5 存疑：部署 jar 里是否真的有 httpclient 和 spring-retry，进程是否设了 `-Dhttp.maxConnections`。
- **触发设想**
  - 对 seat 注入挂起型故障（100% 丢包或 pod pause）。默认负载并发 1，客户端 10s 超时后放弃，但服务端请求继续占着连接：大约每 10s 多一个。约 50s 后 travel→seat 这个路由的 5 个槽位占满；再加上 travel→basic 的 5 条，全进程 10 条用尽，连新 seat IP 都拿不到连接。
  - 小延迟需要 2N·d ≳ 50s 才能占满，所以单纯加延迟很难触发。
  - 清除故障后，被卡住的连接要等下一次 TCP 重传（重传间隔上限 120s），因此恢复最多滞后约 120s，超过 T-07 模板"清理后 60s 恢复"的反驳线。
- **机制专属信号**：travel 线程栈大量停在 `AbstractConnPool.getPoolEntryBlocking`（区别于 TT-B02 的 `socketRead0`）；travel→seat 客户端 span 远长于 seat 服务端 span；下单的 `/trip_detail` 同时变慢，说明是跨路径污染。
- **业务影响**：search-trips 与 preserve-order 同时违反 p95≤2500ms 和成功率≥0.95（P:67-78）。
- **运行时要核对**：清单 1、2、9。
- **置信度**：中高。库行为已逐条核实；部署 jar 内容和实际重传间隔待测。

### TT-B02 全链路没有截止时间；看得见的 Ribbon 5s/2s 超时对这条路径不生效
- **机制族 / 失效模式**：deadline_timeout / 主 D1，次 D4。T-01 实例。
- **位置**：9 条 HTTP 边和 7 个数据库。
- **成立条件**
  - E1 成立：HTTP 客户端没有任何超时（同 TT-B01 的 E1、E2）。
  - E2 成立：Ribbon 默认值里有 ReadTimeout=5000、ConnectTimeout=2000（lib），但只作用于 Ribbon 自带的客户端，不作用于 RestTemplate 的 request factory。这是一个"以为有超时"的陷阱。
  - E3 成立：JDBC URL 里没有 connectTimeout / socketTimeout（例如 travel 的 `application.yml:13`），11 个服务的 yml 里都搜不到 hikari 配置。
  - E4 成立：网关 yml 没有 timeout 键；UI 的 nginx 只写了 `proxy_pass`（`S/ts-ui-dashboard/nginx.conf:40-41`），走默认 60s。整条链路唯一的截止是负载客户端的 10s。
- **触发设想**
  - SLO 越界的最小延迟 d* ≈ (2500 − 280) / (k·n_rtt)，基线 p95 取 280ms（P:142）。
  - seat、order、config 这三条边 n_rtt=2N，N=1 时 d* ≈ 1.1s/k；basic 的 4 个下游 n_rtt=1，d* ≈ 2.2s/k。
  - 超过客户端截止的点：d ≈ 10s/n_rtt。没有库常量，所以不存在内层饱和点。
- **机制专属信号**：入口延迟增量约等于 n_rtt·d，随 d 线性增长、没有上限；全程看不到 504 或 SocketTimeoutException。
- **业务影响**：查询只会慢失败，不会快速失败。
- **运行时要核对**：清单 3、10。
- **置信度**：高。

### TT-B03 服务间路由的健康判断完全来自 Nacos：陈旧副本把死 IP 标成健康后，失败率随扇出放大（运行时事实 2）
- **机制族 / 失效模式**：health_probe（负载均衡层健康判定）/ 主 D6，次 D5。
- **位置**：所有 `http://<服务名>` 调用（`TravelServiceImpl.java:51-53` 等）和网关的 `lb://` 路由。
- **成立条件**
  - E1 成立：地址列表只来自 Nacos。`NacosServerList` 调 `selectInstances(…, healthy=true)`；Ribbon 用 DummyPing（不主动探活），按规则轮询，服务器列表每 30s 刷新一次（lib）。
  - E2 成立：Nacos 2.0.1 三副本，没有持久卷（`M/statefulsets.json`）。nacos-client 2.0.3 的 gRPC 连接只挂在其中一个副本上，调用方看到的实例列表来自这个副本。
  - E3 成立（运行时已查实）：陈旧副本把不存在的 Pod IP 标为健康。P:144 也记录过 order、preserve、网关的陈旧注册；P:132、P:151 说明副本一致性还没有成为门禁。
  - E4 成立：没有连接超时。如果死 IP 直接丢 SYN，每次连接会挂约 127s（Linux 默认值，待测）。
  - E5 部分成立：Ribbon 有服务器级跳闸：连续 3 次连接类异常后跳过该地址 10s，之后每次失败翻倍、上限 30s；只有成功才清零，所以死 IP 永远不会清零（lib：`ServerStats`、`RibbonLoadBalancedRetryPolicy`）。
- **按代码数出来的调用次数**
  - 一次查询：网关→travel 1、travel→basic 1、basic→4 个下游各 1、seat 2N、order 2N、config 2N（GET，有重试）。
  - 合计 6+6N 次，经过 4 个调用方进程、9 个目标服务。
  - 公式：单次调用挑中死地址的概率 q=死/(活+死)。POST 不重试时，P(查询失败) = 1 − Π(1−q_e)^{n_e}。同一进程连续调用时轮询是严格交替的，实际值不低于公式值。

| 陈旧情形 | 查询失败率（N=1） | 查询失败率（N=3） |
|---|---|---|
| 只有 seat 陈旧（1 活 1 死） | 75% | 98.4% |
| 只有 order 陈旧（2 活 1 死） | 55.6% | 91.2% |
| basic、station、train、route、price、travel 中任一个陈旧 | 50% | 50% |
| 只有 config 陈旧 | 死 IP 快速失败时约 0%（重试落到活实例）；丢 SYN 时 75% 超过 10s | 丢 SYN 时 98.4% 超过 10s |
| 全部服务都保留滚动重启前的旧 IP（P:144 的形态） | 成功率只有 (1/2)^{6+4N} ≈ 0.1%，即失败约 99.9% | 更高 |

  - 调用方侧还有一层放大：4 个调用方进程各自随机连到 3 个副本之一时，至少有一个连在陈旧副本上的概率是 1 − (2/3)^4 ≈ 80%。
  - 跳闸之后的稳态分两种情况：
    - 死 IP 能快速失败时：每个"调用方进程 + 死地址"组合约每 30s 失败 1 次。默认每 30s 约 18 次查询，所以一个组合就造成约 5.6% 的查询失败，已经超过 5% 的错误率 SLO；9 个组合约 50%。
    - 死 IP 丢 SYN 时：失败要约 127s 才记账，而跳闸窗口最多 30s，所以约 80% 的时间不在跳闸期。挂起的连接很快占满该路由的 5 个槽位。basic 只要 4 个下游里有 2 个陈旧，就会占满全进程 10 条连接，查询 100% 失败（与 TT-B01 叠加）。
- **触发设想**：让一个 Nacos 副本保留旧实例（旧环境已自然出现过）。强度由死条目数与活实例数之比决定。
- **机制专属信号**：报错里的 IP 不在 `kubectl get pod -o wide` 的结果里；失败集中在连着陈旧副本的调用方进程；3 个 Nacos 副本对同一服务返回的实例集合不同。与 TT-B04 的区别：这里地址已经不存在，TT-B04 是实例还在但不能服务。
- **业务影响**：查询成功率随扇出迅速坍塌，下单链路也同样经过 seat 和 order。
- **运行时要核对**：清单 5、6、7、18。
- **置信度**：机制成立为高；数值为中，取决于死 IP 是快速失败还是丢 SYN。

### TT-B04 K8s 探针与真实路由脱节：readiness 摘不掉 Nacos 流量，TCP 探针测错对象，没有 liveness
- **机制族 / 失效模式**：health_probe（readiness 与 liveness）/ 主 D2，次 D4、D1。对应 T-05、T-07。
- **位置**：查询链路上全部 Java Deployment。
- **成立条件**
  - E1 成立：只有 tcpSocket 类型的 readiness（initialDelay 60 / period 10 / timeout 5 / failure 3），没有 liveness 和 startup 探针（`M/deployments.json`，14 个服务配置相同）。
  - E2 成立：服务间调用走 Nacos，不走 K8s Service（见 TT-B03 E1）。NotReady 只会把 Pod 从 K8s Endpoints 摘掉；Nacos 2.x 下实例是否存活由 gRPC 连接维持，与 Tomcat 线程能不能干活无关。
  - E3 成立：TCP 探针只有在 Tomcat 连接数达到 8192 且 backlog 100 也满了才会失败（lib）；200 个工作线程全部阻塞时它照样通过。
  - E4 成立：旧环境出现过 order 的 accept 队列停止排空、0/2 Ready，最后靠人工滚动重启才恢复（P:137-138）。
  - E5 存疑：pom 里有 actuator（`pom.xml:90-91`），但安全配置对非业务路径要求认证（travel 的 `SecurityConfig.java:75-78`），所以健康端点大概率返回 401/403，探针用不了。
- **触发设想**：让 order 的一个副本挂住但不退出，或者让 seat 的 200 个线程全部阻塞（见 TT-B01）。
- **机制专属信号**：Endpoints 已经摘掉该 Pod，Nacos 里它仍然 `healthy=true`，调用方的 span 继续打到这个 IP，restartCount 不变，日志里也没有 OOM（这一点区别于 TT-B15）。
- **业务影响**：order 两副本时约 50% 的余票查询会挂住，而且不会自愈。
- **运行时要核对**：清单 11、15。
- **置信度**：高。

### TT-B05 入口放弃后下游继续干活（取消不传播）
- **机制族 / 失效模式**：cancellation / D2。T-02 实例。
- **位置**：网关与 travel 的边界，以及 travel 内部 2N 次串行 seat 调用。
- **成立条件**
  - E1 成立：截止时间只在边缘：负载客户端 10s，UI 经 nginx 是默认 60s。
  - E2 成立：travel 是阻塞式 servlet，`queryByBatch` 全程不检查取消（`TravelServiceImpl.java:203-217, :322-377`）。
  - E3 成立：下游调用把入站请求头丢掉了（`HttpEntity(infos, null)`，`:345` 和 `:550`），截止时间传不下去。
  - E4 存疑：网关在客户端断开后会不会关闭到 travel 的连接。
- **触发设想**：给 seat 注入 6–10s 延迟。客户端 10s 就放弃，服务端还会继续做完最多 6N 次下游调用。
- **机制专属信号**：入口 span 已经结束，之后同一条 trace 里还有新的 seat、order、config span 开始；order 侧 CLOSE_WAIT 连接数增长（P:138 提到过）。
- **业务影响**：过载时白白消耗容量，放大 TT-B01 的排队。
- **运行时要核对**：清单 10。
- **置信度**：中高。

### TT-B06 Nacos 不可用时服务启动即退出，进入 CrashLoopBackOff；Nacos 恢复后要等退避计时器（运行时事实 1）
- **机制族 / 失效模式**：retry_backoff / D5（启动快速失败 × kubelet 指数退避）。T-07 / N-04 形态。
- **位置**：所有 ts-* Java 服务的启动阶段。
- **成立条件**
  - E1 成立（运行时已查实）：启动时报 `NacosException: Client not connected, current status: STARTING` 后退出。
  - E2 成立（配置根因）：yml 里只配了 server-addr（travel 的 `application.yml:5-9`），没有配置 fail-fast。`NacosDiscoveryProperties.failFast` 默认为 true；`NacosServiceRegistry.register` 捕获异常后，如果 `isFailFast()` 为真就重新抛出（lib，SCA 2.2.7 反汇编），导致应用上下文启动失败。
  - E3 成立（部署根因）：没有 initContainer 或 startupProbe 等待 Nacos（`M/deployments.json` 中 initContainers 为 0）。kubelet 的退避从 10s 开始翻倍，300s 封顶。
  - E4 成立：已经在运行的进程靠本地缓存继续路由，不受影响；受害的是 Nacos 故障期间被重启的 Pod。环境 reset 流程里有 `restart-application-deployments`（P:103-108），如果 reset 时 Nacos 没就绪，48 个服务会一起进入退避。
- **触发设想与量级**：Nacos 宕机超过约 5 分钟，期间有 Pod 被重启。若查询路径上的 10 个服务（网关 + 9 个）都在退避中，每个服务在 Nacos 恢复后的下一次重启时刻约在 [0, 300s] 内均匀分布，整条路径要等最慢的那个，期望约 300×10/11 ≈ 273s，再加 JVM 启动时间。扇出越多，恢复越慢。
- **机制专属信号**：lastState 为非 0 退出，日志里是上面那条 NacosException，restartCount 按约 5 分钟一次递增。与 TT-B07 的区别：这里 Pod 根本起不来。
- **业务影响**：Nacos 恢复后几分钟内查询全部 5xx，违反"清理后 60s 恢复"线。
- **运行时要核对**：清单 12。
- **置信度**：高。

### TT-B07 单副本 Pod 重建后，调用方的 30s 地址缓存、无连接超时和 GET 重试叠加，恢复晚于 Pod Ready
- **机制族 / 失效模式**：replica_disruption / D5。对应 T-06、T-07。
- **成立条件**
  - E1 成立：查询链路上 9 个服务都是单副本（replicas=1），没有 PDB 或 HPA（团队导出的清单里没有这两类资源）。
  - E2 成立：Ribbon 地址列表 30s 才刷新一次（lib）。
  - E3 成立：没有连接超时。旧 IP 如果丢 SYN，每次连接挂约 127s，还占着连接池槽位（见 TT-B01）。
  - E4 成立：GET 请求会换"下一台"再试 1 次（lib）；单实例时下一台还是同一个陈旧 IP，挂起时间翻倍。
  - E5 存疑：CPU request 只有 10m、堆 `-Xmx200m`、OTel agent 要从 NFS（1.94.151.57）挂载，这些决定了 Pod 重建本身要多久。
- **触发设想**：删除 ts-seat-service 的 Pod。
- **机制专属信号**：新 Pod 已 Ready 并且已在 Nacos 注册，travel 仍然报旧 IP 的连接错误或 `No instances available`，这段滞后不超过 30s（旧 IP 快速失败时）或约 127s（丢 SYN 时）。
- **业务影响**：每次单副本中断，查询不可用时间 = 重建时间 + 最多 30s（最坏再加 127s×2）。
- **运行时要核对**：清单 7、8。
- **置信度**：中高。

### TT-B08 seat→config：一个常量配置每次都远程读取，每次查询读 2N 次，没有缓存也没有默认值
- **机制族 / 失效模式**：fallback_degradation / 主 D1，次 D6。T-09 实例。
- **成立条件**
  - E1 成立：每次 `left_tickets` 都 GET 一次该配置（`SeatServiceImpl.java:190, :205-215`），而它的值是常量 0.5（config 的 `InitData.java:22-23`）。
  - E2 成立：配置缺失时 `getData().toString()` 直接 NPE（`:217`），没有 try，也没有默认值。
  - E3 成立：这一行配置只在 config 服务启动时写入（`InitData.java:18-26`）。表被清空以后，只要 config 进程不重启，查询就一直 500，属于"恢复后回不来"的形态。
- **触发设想**：config 服务 pod-fail，或者它的数据库不可用。
- **机制专属信号**：seat 日志出现 NPE 或 `ResourceAccessException(ts-config-service)`；由于 GET 会被 Ribbon 重试一次，config 的 span 数翻倍。
- **业务影响**：一个非关键常量拖垮全部余票查询，下单的 `trip_detail` 也一起失败。
- **运行时要核对**：清单 13。
- **置信度**：高。

### TT-B09 basic→price：默认价格只兜住"缺配置"，兜不住"调用失败"
- **机制族 / 失效模式**：fallback_degradation / D2。T-09 实例。
- **成立条件**
  - E1 成立：降级是有的：缺配置时用 0.75/1.0（`BasicServiceImpl.java:284-290`），距离计算出错时用 95/120（`:293-306`）。
  - E2 成立：调用本身没有 try（`:461-465`）。
  - E3 成立：如果价格结果为 null（反序列化失败，`:476-478`），在 try 外面的 `:286` 会抛 NPE。
- **触发设想**：price 服务 pod-fail 或网络丢包。
- **机制专属信号**：station、train、route 的 span 都正常，只有 price 失败，而整个查询 500。
- **业务影响**：非关键的价格服务故障导致查询 100% 失败。
- **置信度**：高。

### TT-B10 按车次隔离失败的写法只存在于没人调用的 left_parallel 路径；线上的 /trips/left 要么全成功要么全失败
- **机制族 / 失效模式**：fallback_degradation / D2。
- **成立条件**
  - E1 成立：`queryInParallel` 对每个车次单独捕获异常（`TravelServiceImpl.java:277-286`）。
  - E2 成立：`/trips/left` 的逐车次循环没有 try（`:367-375`）。
  - E3 成立：UI 和负载只用 `/trips/left`（`W/profiles.yaml:57`，UI 里从没引用 left_parallel）。
  - E4 附带问题：left_parallel 自己用的是全局固定 20 线程池、无界队列，`future.get()` 也没有超时（`:49, :272, :279`），而且经网关可以访问到。
- **量级**：单次 seat 调用失败率为 p 时，查询失败率 = 1 − (1−p)^{2N}。
- **机制专属信号**：一条 trace 里只有一个 seat span 报错，整个查询却 500。
- **置信度**：高。

### TT-B11 扇出 5+6N 次全部串行，还有 N+1 查询：注入的延迟被放大 2N 倍，而 N 随数据增长
- **机制族 / 失效模式**：deadline_timeout（放大系数 n_rtt）/ D1。
- **成立条件**
  - E1 成立：调用图第 4、4a、4b 条都在循环里串行执行。
  - E2 成立：basic 收到的是全部 T 个车次（`:332-341`）；route 端对每条线路还要额外执行 2 条 SQL，共 1+2R 条（`Route.java:28-34`，集合是懒加载）。
  - E3 成立：N=1 时 11 次 HTTP、19 条 SQL；N=3 时 23 次 HTTP、27 条 SQL。管理员新增车次后线性增长。
- **触发设想**：给 seat、order 或 config 加延迟 d，入口延迟约增加 2N·d。
- **机制专属信号**：seat、order、config 的 span 各 2N 个，首尾相接，没有重叠。
- **业务影响**：p95 对 N 线性敏感；这也是 TT-B03 失败概率放大的根源。
- **置信度**：高。

### TT-B12 余票计算的成本随历史订单线性增长，而负载和 reset 都让订单只增不减
- **机制族 / 失效模式**：resource_limit（数据无界增长）/ D1。
- **成立条件**
  - E1 成立：orders 表只有主键，没有 (日期, 车次) 索引（`Order.java:19-55`），查询是全表扫描。
  - E2 成立：查询不过滤订单状态和座位等级（`OrderServiceImpl.java:54-62`），已取消的订单也被当成已售，一等、二等两次调用拉的是同一个全集。
  - E3 成立：这个全集整包回传给 seat，order 端（`:65`）和 seat 端（`SeatServiceImpl.java:151`）都在 INFO 日志里整包打印。
  - E4 成立：负载的出发日期是固定值（`W/runtime-fixture.example.yaml:19`）；负载"清理"订单用的是取消，而取消只改状态（`CancelServiceImpl.java:240-247`）；reset 不清库（P:103-110）。
- **量级**：下单流量约 0.3 次/s，每个 10 分钟窗口约 180 单，全部落在同一 (日期, D1345) 上，并跨 episode 累积。
- **机制专属信号**：`/order/tickets` 的 span 时长和响应字节数随 episode 序号单调上升。
- **业务影响**：基线漂移，各 episode 之间不可比。
- **运行时要核对**：清单 14。
- **置信度**：中高。线上 order 跑的是 1.0.1 镜像，与上游代码的差异待确认。

### TT-B13 业务库切主：只指向主库的 Service 可能短暂没有后端，客户端没有读超时，已有连接还粘在旧主库上（运行时事实 3）
- **机制族 / 失效模式**：deadline_timeout / 主 D2，次 D5、D6。
- **成立条件**
  - E1 静态核实：上游 all-in-one 部署把所有服务的库主机都写成 `tsdb-mysql-leader`（`S/hack/deploy/utils.sh:61,66`、`gen-mysql-secret.sh:47-60`）。该 Service 的 selector 包含 `role=leader`（`M/services.json`）；这个标签由 xenon 在选主时调用 K8s API 打上（`M/configmaps.json` 里的 tsdb-mysql `leader-start.sh`/`leader-stop.sh`，`M/roles.json` 授予了 pods patch 权限）。Secret 的实际值没有导出，**需要运行时核对**。
  - E2 成立：JDBC 没有 failover 配置，没有读超时；连接池用 Hikari 默认值：10 个连接、取连接最多等 30s、连接最长存活 30min。
  - E3 成立：一次查询在同一个主库上执行约 15+4N 条 SQL，分布在 7 个服务里。
  - E4 存疑：kube-proxy 按连接做地址转换，已有连接会粘在旧主库的 Pod IP 上。
- **量级**（切主时 Service 没有后端的时长记为 W）

| W | 结果 |
|---|---|
| W < 10s | 查询变慢但能成功，Hikari 的 30s 等待兜住了 |
| 10s < W < 30s | 客户端 10s 已放弃，服务端之后才成功，白做（与 TT-B05 叠加） |
| W > 30s | 直接 500 |

  - 旧主库的 IP 如果静默消失，执行中的语句会一直挂到 TCP 重传放弃（约 15 分钟）。
  - 旧主库如果还活着、只是被降为从库，已有连接可能继续从它读陈旧数据，最长 30 分钟。
- **机制专属信号**：`tsdb-mysql-leader` 的 Endpoints 为空；日志里出现 Hikari 取连接 30000ms 超时；切主后旧主库的 processlist 里仍有 ts-* 服务的连接。
- **运行时要核对**：清单 16。
- **置信度**：中。

### TT-B14 依赖失败被翻译成"成功，但没有车次"（灰色故障）
- **机制族 / 失效模式**：fallback_degradation / D3。
- **成立条件**
  - E1 成立：basic 返回 status 0 或结果反序列化失败时，travel 返回 HTTP 200，内容是 `status=1` 加空列表（`TravelServiceImpl.java:353-365`）。
  - E2 成立：basic 在 station、train 或 route 查不到数据时返回 status 0（`BasicServiceImpl.java:185-189, :210-214, :233-237`），分不清是真的没车次，还是数据被清空或读到了空副本。
  - E3 存疑：按 HTTP 状态码计算的 SLO 会把这种情况算成成功。
- **机制专属信号**：返回 200 且 `data=[]`，basic 日志里有 `no travel info available`。
- **置信度**：中低。

### TT-B15 JVM 堆固定 200MB，与 1500Mi 的容器配额脱钩；堆内 OOM 后进程不退出，又没有 liveness，服务僵死不重启
- **机制族 / 失效模式**：resource_limit / 主 D2，次 D1。T-08 的变体。
- **成立条件**
  - E1 成立：各 Dockerfile 都是 `java -Xmx200m`（例如 travel `Dockerfile:6`）；JAVA_TOOL_OPTIONS 里没有 `ExitOnOutOfMemoryError`。
  - E2 成立：容器内存上限 1500Mi，所以容器级 OOMKill 重启永远轮不到，堆会先在 JVM 内部溢出。
  - E3 成立：没有 liveness 探针。
  - E4 存疑：线上镜像的实际启动参数，以及查询链路上哪个服务最先逼近 200MB。
- **机制专属信号**：日志出现 `OutOfMemoryError`，restartCount 不变，Pod 仍然 Ready。
- **置信度**：中低。

### TT-B16 route-plan 和 travel-plan 串行放大，一个车次失败拖垮整个规划
- **机制族 / 失效模式**：deadline_timeout / 主 D1，次 D2。
- **成立条件**
  - E1 成立：各规划接口的调用构成（全部串行、无超时）：

| 接口 | 调用构成 | 证据 |
|---|---|---|
| 最便宜 / 最快 | travel 完整查询 + travel2 完整查询 + 最多 5 次 route 查询 | `RoutePlanServiceImpl.java:47-48, :83, :336-355` |
| 最少站 | 每个车次 1 次 trip_detail + 1 次 route | `:239-281` |
| travel-plan（在上述结果之上） | 每条结果再加 1 次 train + 2 次 seat | `TravelPlanServiceImpl.java:113-121` |
| 换乘 | 4 次完整查询 | `:50-85` |

  - E2 成立：trip_detail 返回 status 0 时，`:261` 直接 NPE，整个规划 500。
- **业务影响**：影响 UI 的高级查询，不在默认负载里。
- **置信度**：代码成立为高；对 SLO 的影响为低。

### TT-B17 ticket-office：一条 SQL 出错就打崩整个进程，靠 CrashLoopBackOff 恢复；每次重启还会重复插入种子数据
- **机制族 / 失效模式**：fallback_degradation（错误处理）/ 主 D3，次 D4。
- **成立条件**
  - E1 成立：全进程只有一个数据库连接，不是连接池，没有错误监听也不会重连（`bin/db.js:10-15`）。
  - E2 成立：查询回调里写的是 `if (err) throw err`（`:23-24` 等），SQL 还是字符串拼接的（`:44-45`）。
  - E3 成立：启动时无条件插入种子数据（`:30`），连不上库的错误被忽略（`:98-100`）。
  - E4 成立：读取了端口环境变量，但没有传给数据库连接（`:5, :10-15`）。
- **业务影响**：影响售票点页面，不在查询车次路径上。
- **置信度**：代码成立为高；对 SLO 的影响为低。

---

## 跨范围共性问题（只提一句）
- **入口**：网关的 Sentinel 只限流 admin-basic-info（`GatewayConfiguration.java:107-119`），最贵的查询路由没有准入控制；网关和 nginx 都没配超时。avatar 等非 Java 服务不注册 Nacos，但网关走 `lb://` 路由到 avatar（`application.yml:56-59`），这条路由大概率恒返回 503。
- **基础设施**：
  - OTel agent 从外部 NFS 挂载，所有 Pod 重建都依赖这台机器（D6）。
  - CPU request 只有 10m、内存 request 100Mi，远低于 JVM 实际占用。
  - 整个命名空间没有 PDB。
  - MySQL 的 readiness 用 `SELECT 1`，超时只有 1s，可能把唯一的主库端点摘掉。
  - DEVIATIONS 第 5 条说明，TT-RT-01 在新环境已被人为消除。
- **下单链路**：order 查已售票不过滤取消状态（这是正确性问题）；preserve 的余座检查基本不起作用（`PreserveServiceImpl.java:87-96`）。

## 保护有效的点（可作负控制）
1. **T-03 负控制**：Ribbon 只对 GET 重试 1 次，不因 5xx 重试，POST 从不重试（lib）。查询主干都是 POST，所以不存在重试放大。
2. **Nacos 不可用时，已运行的进程继续路由**：nacos-client 2.0.3 带本地缓存，重连后会重新注册（lib 类清单）。运行时待确认。
3. **Ribbon 跳闸**：对快速失败的死地址会跳过 10–30s（见 TT-B03 E5）。
4. **Hikari 的 30s 等待**：能兜住短于 10s 的切主窗口。
5. **扇出只按匹配车次计算**：basic 先过滤再扇出（`BasicServiceImpl.java:242-264`），全表车次数 T 不影响 seat 的扇出次数。
6. **G/D 与其余车次的订单源隔离**（`SeatServiceImpl.java:138-168`）：负载只查 G/D，所以对 order-other 注入故障应当是负例。
7. **站名规范化**：`TripInfo.java:37,41` 统一处理，负载里的 "Shang Hai" 能命中种子数据。
8. **业务库有持久卷**：T-10 对业务数据不成立，但注意新环境已改用节点本地盘。
9. **种子车型座位数是 `Integer.MAX_VALUE`**（train `InitData.java:33-37`）：分座的随机循环不会因为"售罄"而空转。
10. **N-01（存疑）**：span 大概率是 agent 批量异步导出的，不阻塞业务线程；需要确认 agent 版本和队列丢弃计数。

## 运行时核对清单（去重后，供主会话执行）
1. **确认进程参数与客户端依赖**
   - 看启动参数：对 travel、seat、basic 各执行 `cat /proc/1/cmdline | tr '\0' ' '`，确认 `-Xmx200m`，且没有 `http.maxConnections` 和 `ExitOnOutOfMemoryError`。
   - 看 jar 依赖：用 `kubectl cp` 把 `/app/*.jar` 拷出来，`unzip -l`，确认有 `httpclient-4.5.x`、`spring-retry-1.2.5`、`nacos-client-2.0.3`。
2. **注入期间看线程栈**：执行 `kill -3 1`，在 `kubectl logs` 里分别数停在 `getPoolEntryBlocking`（租约排队）和 `socketRead0`（读等待）的线程数。
3. **基线 trace 对账**：
   - 取 10 条查询 trace，span 数应为：basic 1；station、train、route、price 各 1；seat、order、config 各 2N（N=1 时共 11 个客户端 span）。
   - 如果 travel 下面一个 span 都没有，说明出发日被短路了（`TravelServiceImpl.java:325-328`）。
4. **实际 fixture**：确认 `travel_date` 不早于今天（按 Asia/Shanghai 时区）；在 travel 库执行 `SELECT trip_id, route_id FROM trip`，算出 N、T、R。
5. **Nacos 三副本对比**：对 nacos-0/1/2 分别执行 `curl ".../nacos/v1/ns/instance/list?serviceName=<服务>&healthyOnly=false"`，覆盖链路上 9 个服务，与 `kubectl get pod -o wide` 的 IP 对比。
6. **每个调用方连在哪个 Nacos 副本**：在网关、travel、basic、seat 的 Pod 里查看 `/proc/net/tcp`，找远端端口为 9848 的连接。
7. **死 IP 是快速失败还是丢 SYN**：
   - 在 travel Pod 里执行 `time (exec 3<>/dev/tcp/<已删 Pod 的 IP>/18898)`。
   - 在节点上查看 `sysctl net.ipv4.tcp_syn_retries net.ipv4.tcp_retries2`，并确认 kube-proxy 模式。
8. **单副本重建的恢复滞后**：删除 seat Pod，记录四个时刻：新 Pod Ready、Nacos 出现新 IP、travel 最后一次报旧 IP 错误（`refused|No route|timed out|No instances`）、查询成功率回到基线。
9. **连接池耗尽与跨路径污染**：
   - 对 seat 注入 100% 丢包 120s。
   - 观察 travel 停在 `getPoolEntryBlocking` 的线程数、客户端 span 与服务端 span 的时长差，以及下单 `/trip_detail` 的延迟。
   - 故障清除后测量多久恢复（预期最多约 120s）。
10. **取消是否传播**：给 seat 注入 6–10s 延迟，看入口 span 结束后是否还有新的下游 span 开始；查看 order Pod 里 CLOSE_WAIT 的数量（`/proc/net/tcp` 中状态为 08）。
11. **readiness 与 Nacos 的一致性**：order 一个副本挂住时，对比 `kubectl get endpoints ts-order-service` 和 Nacos 里该实例的 healthy 字段；同时看该 Pod 的 restartCount。
12. **Nacos 宕机**：
    - (a) 已运行的服务查询是否仍然成功。
    - (b) 被重启的 Pod 日志里是否有 `STARTING` 报错，退出码是多少。
    - (c) Nacos 恢复后，各服务回到 Ready 的时刻和退避间隔。
13. **非关键依赖故障**：config 不可用时，看 seat 是否报 NPE 或 `ResourceAccessException`，config 的 span 是否翻倍；price 不可用时，看查询 500 的比例。
14. **订单增长**：
    - 执行 `SHOW INDEX FROM orders`。
    - 执行 `SELECT status, COUNT(*) FROM orders WHERE train_number='D1345' AND travel_date LIKE '<日期>%' GROUP BY status`。
    - 逐个 episode 记录 `/order/tickets` 的 span 时长和响应字节数。
15. **健康端点能否被探针使用**：在 travel Pod 里执行 `curl -s -o /dev/null -w '%{http_code}' localhost:12346/actuator/health`，预期 401 或 403。
16. **业务库**：
    - 执行 `kubectl get secret ts-<svc>-mysql -o jsonpath='{.data.<SVC>_MYSQL_HOST}' | base64 -d`，覆盖 travel、route、station、train、price、config、order、order-other。
    - 切主时执行 `kubectl get endpoints tsdb-mysql-leader -w`，测出没有后端的时长 W。
    - 切主后在旧主库查 processlist，看 ts-* 服务的连接是否还在。
    - 在各副本查 `@@read_only` 和 `@@super_read_only`，并确认 Secret 里的用户是不是 root。
17. **JVM OOM**：各 Pod 执行 `kubectl logs`（含 `--previous`），搜索 `OutOfMemoryError`，对照 restartCount 和 Ready 状态。
18. **副本数**：清单 spec 里 order 是 2、网关是 3，与任务说明写的 order 3、网关 2 不一致。以线上为准，它会影响 TT-B03、TT-B04 里的 q 值。