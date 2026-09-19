# train-ticket 下单链路韧性缺陷排查（只读静态分析）

这次没有改任何项目文件，也没有访问集群或网络。唯一写过的是临时目录里一份用来 diff 的副本。

- **镜像版本：** ts-order-service（1.0.1）、ts-order-other-service（1.0.2）、ts-consign-price-service（1.0.1）、ts-station-food-service（1.0.1）的结论都**以上游源码 313886e9 为准，线上镜像可能有差异**。两份清单都没有改动原因的注释：static-manifests.yaml 第 3127、3028、1999、4087 行，live-export.yaml 第 4218、4119、3090、5178 行。修复记录第 66 行也写明，镜像还没证实出自锁定的源码。
- **副本数和任务描述对不上：** 两份导出里 ts-order-service 都是 **2 副本**（deployments.json 的 `spec.replicas=2`；live-export.yaml:4165；档案第 137 行写的是 "0/2→2/2"），ts-gateway-service 是 **3 副本**。以运行时为准，见核对清单 A1。
- **主会话 4 条事实的落点：** 事实 1 → TT-C4、TT-C3；事实 2 → TT-C8；事实 3 → TT-C11；事实 4 → TT-C1（排在最前）。
- **没有细看的部分：** contacts、basic（及其下游 station/train/route/price）、delivery、inside-payment 的内部实现，以及 1.0.x 镜像的实际内容。station-food、train-food 只在餐食查询路径上，不在下单写路径上。

**路径约定**（文中引用都按下面展开为绝对路径）

- `U` = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/benchmark-sources/train-ticket-upstream`
- `M` = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/multisystem-audit-20260918`
- `E` = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/resiliencebenchmark-stage2-d0-integration/environment`
- `R` = `/Users/mymz/.m2/repository`，本机 Maven 缓存。版本与上游 pom 锁定的一致：Boot 2.3.12、Hoxton.SR12、SCA 2.2.7，见 U/pom.xml:14、72、160。

| 简称 | 绝对路径 |
|---|---|
| Preserve / PreserveApp / PreserveCtl | U/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java，U/…/preserve/PreserveApplication.java，U/…/preserve/controller/PreserveController.java |
| PreserveOther | U/ts-preserve-other-service/src/main/java/preserveOther/service/PreserveOtherServiceImpl.java |
| Seat | U/ts-seat-service/src/main/java/seat/service/SeatServiceImpl.java |
| OrderSvc / OrderEnt / OrderRepo / OrderCtl / OrderYml | U/ts-order-service/src/main/java/order/{service/OrderServiceImpl.java, entity/Order.java, repository/OrderRepository.java, controller/OrderController.java}，U/ts-order-service/src/main/resources/application.yml |
| OtherSvc / OtherEnt | U/ts-order-other-service/src/main/java/other/{service/OrderOtherServiceImpl.java, entity/Order.java} |
| Security / SecInit | U/ts-security-service/src/main/java/security/{service/SecurityServiceImpl.java, init/InitData.java} |
| Assurance* | U/ts-assurance-service/src/main/java/assurance/{controller/AssuranceController.java, service/AssuranceServiceImpl.java, entity/Assurance.java, repository/AssuranceRepository.java} |
| Food* / FoodYml | U/ts-food-service/src/main/java/foodsearch/{service/FoodServiceImpl.java, mq/RabbitSend.java}，U/ts-food-service/src/main/resources/application.yml |
| Consign / Cancel / Travel / UserSvc | U/ts-consign-service/…/consign/service/ConsignServiceImpl.java，U/ts-cancel-service/…/cancel/service/CancelServiceImpl.java，U/ts-travel-service/…/travel/service/TravelServiceImpl.java，U/ts-user-service/…/user/service/impl/UserServiceImpl.java |
| OTI / TrainInit | U/ts-common/src/main/java/edu/fudan/common/entity/OrderTicketsInfo.java，U/ts-train-service/src/main/java/train/init/InitData.java |
| GwYml / GwCfg | U/ts-gateway-service/src/main/resources/application.yml，U/ts-gateway-service/src/main/java/gateway/GatewayConfiguration.java |
| Dockerfile | U/<服务名>/Dockerfile |
| deploy/sts/svc/cm.json、DEV | M/manifests/train-ticket/{deployments,statefulsets,services,configmaps}.json，M/DEVIATIONS.md |
| Profile / Repair | E/applications/train-ticket.yaml，E/repairs/train-ticket-nacos-workload-qualification-20260822.yaml |
| WL / WLP | E/workloads/train-ticket/image/train_ticket_workload_generator.py，E/workloads/train-ticket/profiles.yaml |

---

## 下单请求步骤表（ts-preserve-service，G/D 车次）

| 步 | 调用谁 | 有无副作用 | 失败时前面的副作用怎么办 | 证据 |
|---|---|---|---|---|
| 0 | 网关用 `lb://` 经 Nacos+Ribbon 选一个 preserve 实例 | 无 | — | GwYml:131-134 |
| 1 | GET security `/securityConfigs/{acct}`。security 内部再**同步**调 order `/order/security/..` 和 order-other `/orderOther/security/..`，两边都全量加载账户订单 | 无 | 前面没有写入。status=0 时返回 0；抛异常则返回 500 | Preserve:52-56、345-357；Security:108-158 |
| 2 | GET contacts `/contacts/{id}` | 无 | 同上 | Preserve:62-66、376-389 |
| 3 | POST travel `/trip_detail`。travel 内部调 basic，再调 2 次 seat `/left_tickets`，每次 seat 都 POST order `/order/tickets`，另调 config | 无 | 同上。余票校验写错了，见 TT-C15 | Preserve:78-98、360-373；Travel:296-320、426-432 |
| 4a | POST basic `/basic/travel`（内部再调 station/train/route/price） | 无 | 同上 | Preserve:127-138 |
| 4b | POST seat `/seats`，seat 内部 POST order `/order/tickets` | **无**：只算出一个座位号，不做任何预留 | 同上 | Preserve:147-166、266-286；Seat:41-116 |
| 4c | POST order `/order` | **写订单**（orders 表，状态 NOTPAID）。座位号跟着订单落库，这是唯一的"占座" | status=0 时没有残留。抛异常或超时就返回 500，但如果服务端已经提交，就留下一笔**客户端不知道的订单** | Preserve:170-174、391-404；OrderSvc:87-99 |
| 5 | （assurance≠0）**GET** assurance `/assurances/{type}/{orderId}` | **写保险**（用 GET 做写入） | status≠1 只改提示语，订单保留。抛异常返回 500，订单保留，没有回滚 | Preserve:179-190、316-327 |
| 6 | （foodType≠0）POST food `/orders`。food 内部写 food_order，再同步投递 RabbitMQ | **写餐食并发出配送消息** | 同上。MQ 失败被吞掉 | Preserve:193-215；FoodServiceImpl:114-150 |
| 7 | （填了收货人）POST consign `/consigns`，consign 内部 GET consign-price | **写托运** | status≠1 时提示语改为 "Consign Fail."。抛异常返回 500，之前的订单、保险、餐食都保留 | Preserve:218-241；Consign:46-79 |
| 8 | GET user `/users/id/{acct}` | 无。结果只用来拼通知，而发通知的代码已注释 | 抛异常，或 data=null 导致 NPE（Preserve:250），都返回 500，前面所有副作用都保留 | Preserve:245-261、301-314 |
| 9 | 返回 `Response(1,"Success.", cor.getMsg())` | — | **响应里没有订单号** | Preserve:177、263 |

**preserve-other 与上面同构，差异如下：**
- 第 3 步走 travel2，第 4c 步写 order-other 的 `orders_other` 表。
- seat 对非 G/D 车次查 order-other（Seat:68-81）。
- 对应行号：PreserveOther:52、62、79、94、131、154/163、173、185、206、231、244、262、396。

**两套订单库的分流（回应事实 1）**
- 写到哪个库，完全由客户端选哪个下单接口决定，服务端不检查车次类型。发错接口会在第 3 步报 "Trip not found"，不会写单（Travel:299-304）。
- 系统内部读写是一致的：seat 按车次前缀选库，安检和取消两个库都查（Security:111-114、Cancel:46-104）。
- 只有外部调用方只查其中一个库时，才会"查不到刚下的单"。压测当初就是这种情况（Repair:29）。
- 现在压测只调 `/preserve`，搜索 `trips/left` 也只会返回 travel 服务的 G/D 车次，所以只查 order 是对的。profiles.yaml 里写的 `alternatePath` 在生成器中没有实现。

**遗留订单谁来回收（回应事实 2）**
- 写单（4c）之前的任何失败都不留痕。
- 4c 之后的失败，或客户端超时，会留下 NOTPAID 订单，附带可能已写入的保险、餐食、托运记录。
- 系统里**没有任何自动回收**；取消操作也不回收附属记录、不释放座位。详见 TT-C8。

---

## 候选缺陷（按严重度排序）

### TT-C1 ts-order-service 接收队列停止排空、句柄与 CLOSE_WAIT 堆积：每次请求的工作量随数据无上限增长，叠加表级锁、全链路无上限等待、没有自愈（根因推断）
- **机制族 / 失效模式：** 准入与过载保护（主）+ 超时 + 资源配额与 OOM + 健康探针（liveness）。**D5 为主**，次要为 D1（没有分页、没有 JDBC 超时、没有 liveness）和 D4（堆上限、存储引擎配错）。对应模板 T-05、T-07、T-08。
- **位置：** ts-order-service 两个副本。调用方是 seat（`/order/tickets`）、security（`/order/security`）、preserve（POST `/order`）、网关（`/order/refresh`）、cancel（PUT `/order`）。下游是 tsdb-mysql 主库的 `orders` 表。
- **成立条件：**
  - **E1 现象（成立，事实 4 已查实）：** 见 Profile:137-138。两个副本同时变成 0/2，说明是共因，不像单个 Pod 的随机泄漏。
  - **E2 工作量随数据线性增长、没有上限（成立）：**
    - `findByAccountId` 一次取出账户的全部订单：下单（OrderSvc:89）、查单（:128）、安检（:385）都用它。
    - `findByTravelDateAndTrainNumber` 取出某日某车次的全部订单，而且不按状态过滤（OrderSvc:54-66）。
    - 两个查询都没有分页（OrderRepo:24、26），实体上也没有任何二级索引（OrderEnt:19-22），所以都是全表扫描。
    - 取消只改状态、不删行（OrderSvc:223-245）。
    - 压测固定用一个账户、一个日期、总选第一个车次（WL:333-337、372-378），PVC 又跨轮保留（Profile:109-110）。所以同一账户、同一（日期，车次）的行数跨轮只增不减。
  - **E3 扇入放大（成立）：**
    - 一次下单要打 order 5 次：安检 1 次（Security:111）、行程详情里 seat 查余票 2 次（Travel:426-429 → Seat:143-149）、分座 1 次（Seat:59-65）、写单 1 次（Preserve:395-401）。其中 4 次是全表扫描。
    - 一次搜索对返回的每个车次各打 2 次 `/order/tickets`。设 T 为该站点对的车次数，就是 2T 次。
    - 按基线混合流量（WLP:17-24），order 总请求率约为 λ≈1.8T+2.4 次/秒。
  - **E4 表级锁（存疑，静态证据很强）：**
    - 所有带 JPA 的服务都配 `MySQL5Dialect` + `ddl-auto: update`（OrderYml:19、22）。
    - 本机 R/org/hibernate/hibernate-core/5.4.32.Final 的字节码显示：`MySQLDialect.getDefaultMySQLStorageEngine()` 返回 `MyISAMStorageEngine.INSTANCE`，MySQL5Dialect 没有覆盖它，到 MySQL55Dialect 才改成 InnoDB。上游也没有预先建表的 DDL。
    - 旁证：压测把 `data[-1]` 当成"最新订单"（WL:442-449），而查询没有 ORDER BY；烟测 60/60 次取消全部成功（Repair:41-58）。只有按插入顺序返回（MyISAM 堆表）时这才能稳定成立；如果是 InnoDB，会按随机 UUID 主键排序。
    - MyISAM 下 UPDATE（取消订单）要拿整表写锁；排队中的写锁会挡住后面所有的读，形成锁队列。
  - **E5 等待没有上限（成立）：**
    - JDBC URL 只有 `useSSL=false`（OrderYml:13），Connector/J 的 connectTimeout 和 socketTimeout 都是 0，即无限等待。
    - 没有 Hikari 配置，所以连接池是 10，取连接最多等 30s。
    - 没有 server.tomcat 配置，所以是 200 个线程、acceptCount 100、maxConnections 8192，执行队列无界。
    - 上游调用方全部没有超时（见 TT-C6）。
  - **E6 堆太小（按上游 Dockerfile 成立；1.0.1 存疑）：**
    - Dockerfile:6 写死 `-Xmx200m`；JAVA_TOOL_OPTIONS 里只有 agent，没有堆设置；容器 limit 是 1500Mi。
    - O(N) 的实体列表、JSON，以及日志里提前拼接的 `leftTicketInfo.toString()`（OrderSvc:65）都要挤在这 200MB 里。
  - **E7 不会自愈（成立）：**
    - 没有 livenessProbe，readiness 只是 tcpSocket:12031（deploy.json）。
    - Pod 即使 NotReady，Nacos 仍然把流量送进来（见 TT-C4）。
    - 重启不会让数据变少，所以问题会复发。Profile:138 的 residualRisk 也是这么写的。
  - **E8 1.0.1 镜像和上游的差异（存疑）：** 见 Repair:66。
- **根因推断（按可能性从高到低）：**
  - **H1 数据库一侧：锁排队导致连接池耗尽（最可能）。**
    1. 按 E2、E3，`orders` 表的全表扫描每秒约 10 次，每次耗时随行数增长；MyISAM 的写锁排队把读也堵住；tsdb 主库的 CPU limit 只有 500m（sts.json），进一步放大。
    2. 单次查询耗时超过约 20/λ 秒（2 副本 × 池 10）时，Hikari 连接池饱和。
    3. Tomcat 线程在 getConnection 上各等 30s。λ×30 约 330，接近两个副本合计的 400 个线程，多出的请求进入无界队列。
    4. 此时有些连接会主动断开：一是网关代理的查单请求（压测 10s 超时后网关断开上游，约 0.3 次/秒），二是 kubelet 的 TCP 探针（每 Pod 每 10s 一次）。它们不停地建连再关闭，Tomcat 已接受但没线程处理的连接就变成 CLOSE_WAIT，句柄数随之上涨。
    5. 停摆持续数小时后，连接数逼近 maxConnections 8192，Acceptor 停止 accept，backlog（100）被填满，TCP 探针失败，两个副本同时 0/2。
    6. 只要有一次切主或丢包让 SQL 的 socket 半开，由于没有 socketTimeout，这 10 个连接会被永久占住（见 TT-C9），数据库恢复了服务也回不来，只能重启。旧集群上有过他人植入的故障组件和混沌实验（DEV 第 3 行），这类注入足以留下这种永久占用的连接。
  - **H2 堆耗尽（次之）：**
    - 200MB 堆要承接 O(N) 列表乘以并发请求数，会造成 GC 抖动或 OOME。
    - Tomcat 9 的 Acceptor/Poller 捕获 Throwable 后，遇到 VirtualMachineError 会重新抛出，线程随之终止。
    - 结果是端口还在监听，但永远不再 accept，症状和 H1 相同，也只能靠重启恢复。
  - **H3 取决于 1.0.1 镜像：**
    - 上游在 refresh 路径里把 `queryForStationId` 注释掉了（OrderSvc:200），这个方法的出站调用没有超时（OrderSvc:208-220）。
    - 如果 1.0.1 恢复了这类出站调用，或做了别的改动，线程会挂在出站调用上。
  - **H4（可能性低）：** nacos-client 2.0.3 在 Nacos 副本分歧期间反复重连，遗留连接。只有当 CLOSE_WAIT 的远端端口是 9848 时才需要考虑。
  - **判别方法：**
    - 看 CLOSE_WAIT 在哪一侧：本地端口 12031 是入站（H1/H2）；远端端口 3306 是数据库，9848 是 Nacos，4318 是 OTel。
    - Hikari 的 pending 大于 0，且线程堆在 getConnection 上，指向 H1。
    - 日志里有 OutOfMemoryError，且线程栈里没有 `http-nio-12031-Acceptor`，指向 H2。
    - order 的 trace 里出现 order 发起的出站 CLIENT span，指向 H3。
- **触发设想：**
  - (a) 老化：预置或累计该账户、该（日期，车次）的订单到 10^4～10^5 行，跑 10 分钟基线，观察 `/order/tickets` 和 `/order/security` 的 p95 是否随行数上升。
  - (b) 在 (a) 的基础上，对 tsdb 主库注入 CPU 压力或 200ms 网络延迟，使单次查询耗时 ≥ 20/λ 秒。
  - (c) 撤除注入后 5 分钟内仍不恢复，就是 T-07（故障后不自愈）的信号。
- **机制专属信号：**
  - CLOSE_WAIT 集中在本地 12031；LISTEN 那一行的 rx_queue 接近 100；ListenOverflows 在增长。
  - Hikari 的 pending 持续大于 0。
  - PROCESSLIST 里有大量针对 `orders` 表的 `Waiting for table level lock`。
  - p95 与 `COUNT(*)` 正相关。
  - 和 TT-C4 的区别：这里是两个副本同时变差；TT-C4 是单个实例坏了而流量没摘掉。
- **业务影响：** 下单（写单、分座、安检都经过 order）、查单，以及搜索（seat 查余票也经过 order）一起超时或失败，违反 p95≤2500ms 和错误率≤5%（Profile:66-82），只能人工重启。
- **运行时要核对：** A1、B1-B6、C1-C4、D1、D3、D8、F7、G1。
- **置信度：** 中。机制链的静态证据是完整的，但 H1/H2/H3 要靠运行时判别，存储引擎是不是 MyISAM 也要一条 SQL 确认。

### TT-C2 写订单之后的 4 个后置调用只把"业务失败"当软失败，一旦出现传输异常或 5xx，就把已经写入的订单变成 500，而且没有补偿
- **机制族 / 失效模式：** 降级回退 + 补偿。**D2 为主**（降级只覆盖了 status≠1 这种情况），次要为 D1（没有补偿）。对应模板 T-09。
- **位置：** preserve 和 preserve-other，调用 assurance、food、consign（再调 consign-price）、user。
- **成立条件：**
  - **E1 先写单（成立）：** 第 170-175 行写单，第 179-258 行才是后置调用（PreserveOther 从 173 行起结构相同）。
  - **E2 软失败只覆盖 status≠1（成立）：** 只在 Preserve:184-189、207-212、233-238 检查返回体里的 status。RestTemplate 遇到 4xx、5xx 或 IO 错误会直接抛异常，而调用处没有 try/catch（Preserve:316-327、406-418、420-431）。
  - **E3 非关键调用能打断整个请求（成立）：** 第 8 步查用户的结果只用来拼通知，而发通知的代码已注释（Preserve:260-261）。user 服务返回 status=0 时 data 为 null（UserSvc:123-130），第 250 行会 NPE。
  - **E4 没有统一异常处理（成立）：** preserve 和 ts-common 里都搜不到 @ControllerAdvice 或 @ExceptionHandler，PreserveCtl:31-37 同步返回，所以落到默认的 500。
  - **E5 没有补偿（成立）：** 异常路径上不取消订单，也不删已经写入的保险和餐食。
  - **E6 依赖都是单副本（成立）：** assurance、food、consign、consign-price、user 在 deploy.json 里都是 replicas=1。
  - **E7 默认压测只覆盖第 8 步（成立）：** 压测请求体里 assurance="0"、foodType=0、收货人为空（WL:381-390）。
- **触发设想：** 对 ts-user-service 做 pod-kill（重启窗口不少于 readiness 的 60s），或对 12342 端口丢包、返回 5xx。按 0.3 笔下单/秒算，每分钟约 18 笔订单已落库却返回 500。
- **机制专属信号：**
  - 同一条 trace 里，`POST /api/v1/orderservice/order` 子 span 成功，之后的 user/assurance/food/consign 子 span 报错，根 span 返回 500。
  - preserve 日志里，"[Step 4][Do Order][Do Order Complete]" 后面紧跟异常栈。
  - 故障窗口内新增的 NOTPAID 行数约等于 500 的次数。
  - 和 TT-C5 的区别：这里请求很快就返回 500，不是客户端超时。
- **业务影响：** 下单显示失败，但订单、座位（以及保险、餐食、托运）其实都已生效。用户重试就会重复下单（见 TT-C3）。
- **运行时要核对：** F1、F2、D4、D6。
- **置信度：** 高。

### TT-C3 重复提交必然重复下单：没有幂等键，order 的去重比较写错了永远不会命中，订单号被服务端重新生成，下单响应也不带订单号
- **机制族 / 失效模式：** 幂等与去重。**D4 为主**（去重逻辑存在但写错了），次要为 D1（没有幂等键）。
- **位置：** preserve 到 order；preserve-other 到 order-other 相同。
- **成立条件：**
  - **E1 请求里没有幂等键（成立）：** OTI:19-54 的字段中没有类似 requestId 的字段。
  - **E2 订单号被生成两次（成立）：** Preserve:105-106 随机生成一次，OrderSvc:94 又覆盖成新的 UUID（OtherSvc:98 同样如此）。
  - **E3 去重形同虚设（成立）：**
    - OrderSvc:89-92 用 `contains` 判重，依赖 Order 的 equals。
    - OrderEnt:101 把本单的 boughtDate 和对方的 **travelDate** 比较，结果恒为 false。OtherEnt:96 有同样的错误。
    - 而且 boughtDate 每次都取当前时间（Preserve:115），座位号又是随机的（Seat:95），所以即使修好 equals 也匹配不上。
  - **E4 数据库没有业务唯一约束（成立）：** 见 OrderEnt:19-22。
  - **E5 客户端没法对账（成立）：**
    - 下单成功响应的 data 字段不是订单号（Preserve:177）。
    - 客户端只能按账户列出全部订单（没有 ORDER BY，见 OrderRepo:24），而且必须查对库，见上面"两套订单库的分流"。
    - 压测靠 `data[-1]` 认最新订单，这依赖存储的物理顺序（见 TT-C7）。
  - **E6 平台层不会重放（不成立）：** 网关没有 filters 或 Retry（GwYml:116-134）；压测失败后直接返回、不重试（WL:402-403）。所以重复只可能来自调用方重试。
- **触发设想：** 用 TT-C2 或 TT-C5 的注入制造模糊失败，再让调用方（自定义压测，或模拟用户）重试一次。每次模糊失败多出一笔重复单。
- **机制专属信号：** 同一账户、车次、日期、证件、座位等级、起止站，状态为 0 或 1、下单时间只差几秒的订单出现多笔。和 TT-C15 的区别：TT-C15 是不同的下单意图抢到了同一个座位号。
- **业务影响：** 产生重复订单，可能重复扣款，座位被浪费。
- **运行时要核对：** D5、G1。
- **置信度：** 高。

### TT-C4 摘除和实际路由脱节：readiness 只管 K8s Endpoints，而服务之间和网关都经 Nacos+Ribbon 选实例；陈旧或卡死的实例会持续收到流量，而且因为没有超时，Ribbon 按失败剔除的机制永远等不到信号
- **机制族 / 失效模式：** 健康探针（readiness）+ 摘除。**D2 为主**，次要为 D6（摘除依赖 Nacos 副本之间的一致性）和 D5（按失败剔除 × 没有超时）。对应模板 T-05、N-04。
- **位置：** 所有东西向调用：preserve、seat、security、cancel、网关调用 order、preserve 等。
- **成立条件：**
  - **E1 调用走 Nacos+Ribbon（成立）：**
    - 所有服务都用 `@LoadBalanced` 的 RestTemplate（PreserveApp:30-34，16 个服务写法相同），URL 是 `"http://"+服务名`（Preserve:44-45）。
    - SCA 2.2.7 依赖 ribbon 2.2.9 和 nacos-client 2.0.3，见 R/com/alibaba/cloud/spring-cloud-starter-alibaba-nacos-discovery/2.2.7.RELEASE/…pom:127-130、150-155。
    - 网关路由用 `lb://`（GwYml:117、132）。
  - **E2 readiness 管不到这条路径（成立）：** 只有 tcpSocket 类型的 readiness（deploy.json），它只影响 K8s Endpoints。nacos-client 2.x 的实例是否存活绑定在 gRPC 连接上；JVM 还活着、只是 Tomcat 卡死时，连接还在，实例就不会被摘掉。
  - **E3 Nacos 把不存在的 Pod IP 标成健康（成立，事实 1 已查实）：** 见 Repair:8-22，order 10.0.2.124:12031、preserve 10.0.2.194:14568。Nacos 是 2.0.1 版本、3 副本（sts.json）。
  - **E4 Ribbon 靠连接失败才剔除（默认值下成立）：**
    - 没有任何 ribbon.* 配置，所以用默认的轮询；连续 3 次连接类失败才跳过该实例，最长跳过 30s；服务列表每 30s 刷新一次。
    - 一个实例如果"接受 TCP 连接但不回包"，在没有超时的情况下不会产生任何失败，所以永远不会被跳过。
    - 如果 IP 已经不存在（黑洞），建连没有 connect timeout，要等约 127s（Linux 默认 SYN 重试时间）才失败。
  - **E5 要靠人工修复（成立）：** 当时是先滚动重启 Nacos，再重启网关来重建 Ribbon 缓存（Repair:24-27）。
  - **E6 扇出放大（推算）：** 一次下单经 3 个调用方打 order 5 次。k 个实例里有 1 个坏，至少命中一次的概率约为 1-(1-1/k)^5：k=3（2 个正常 + 1 个陈旧）时约 87%；k=2（1 个卡死）时约 97%。
- **触发设想：** 只对一个 order Pod 的入站 12031 丢包（保留它到 9848 的出站，这样 Nacos 连接不断），或者对它做 JVM 方法延迟注入。30s 后它会变成 NotReady，然后观察 5 分钟内 Nacos 是否仍把它列为健康，以及下单成功率是否按 E6 的比例下降。
- **机制专属信号：** Nacos 各副本的实例列表里，NotReady 或已不存在的 IP 仍然 healthy=true；调用方发往该 IP 的 CLIENT span 挂起，或报 `connect timed out` / `No route to host`；其他实例的服务端 span 正常。
- **业务影响：** 下单和搜索成功率骤降，延迟拉长，要靠人工修复。
- **运行时要核对：** A1、E1-E3、F3。
- **置信度：** 高。

### TT-C5 上游已经放弃了，preserve 仍然把整条链跑完并写单（取消不传播）；恢复时积压的"僵尸请求"会集中落库
- **机制族 / 失效模式：** 取消传播。**D2 为主**（对应编码手册里的边界案例），次要为 D5（和没有超时、排队叠加）。对应模板 T-02。
- **位置：** 压测（10s 超时）到网关，再到 preserve，再到下游各服务。
- **成立条件：**
  - **E1 上游有时限（成立）：** 压测的建连超时 3s、响应超时 10s（WL:584-585）。
  - **E2 网关本身没有响应超时（成立）：** GwYml 里没有 httpclient 超时配置。客户端断开后网关会不会取消上游请求，是存疑的，要运行时确认。
  - **E3 preserve 感知不到取消（成立）：** 它是同步的 Servlet（PreserveCtl:31-37）；Preserve:48-264 的各步之间既不检查时限或取消，也不把时限传给下游。
  - **E4 写单前有 7 次以上同步调用，全都没有超时（成立）：** 延迟都累积在第 170 行写单之前。
- **触发设想：** 对 seat 或 basic 注入 3-5s 的延迟（第 3 步和第 4b 步合计要经过 seat 3 次），让 preserve 的总耗时超过 10s。撤除注入时，排在连接池和线程上的请求会一起完成写单。
- **机制专属信号：**
  - 网关的 span 在 10s 左右结束或被取消，而 preserve 的服务端 span 结束得更晚，并且包含成功的 `POST /order` 子 span。
  - preserve 写响应时出现 `ClientAbortException` 或 `Broken pipe`。
  - 订单的下单时间晚于压测记录的超时时刻。
- **业务影响：** 产生幽灵订单；用户一重试就重复下单；恢复期出现写入尖峰，叠加 TT-C1。
- **运行时要核对：** F4、D4。
- **置信度：** 高（E2 存疑）。

### TT-C6 所有出站调用都没有超时，而且（推断）共用一个很小的连接池：单个慢依赖可以钉死 preserve 的全部出站能力，对端消失后连接被永久占住
- **机制族 / 失效模式：** 超时（主）+ 熔断与隔离。**D1 为主**，次要为 D5（小连接池 × 取连接无限等待）。对应模板 T-01、T-04、T-07。
- **位置：** preserve 的 RestTemplate；范围内其他服务的写法相同。
- **成立条件：**
  - **E1 没有超时（成立）：**
    - 16 个服务都是 `builder.build()`（例如 PreserveApp:32-34）。
    - 全仓（网关除外）搜不到 timeout、ribbon、hystrix、resilience4j 的配置。
    - Ribbon 自带的 ReadTimeout 默认值对普通 RestTemplate 不起作用。
  - **E2 连接池大小（存疑）：**
    - ribbon-httpclient 2.3.0 以 runtime 范围带入了 Apache HttpClient（R/com/netflix/ribbon/ribbon-httpclient/2.3.0/…pom:26-31）。
    - 这种情况下 Boot 的 RestTemplateBuilder 会自动选 HttpComponents 请求工厂，底层走 `HttpClients.createSystem()`：每个目标地址最多 5 个连接、总共 10 个；连接、读取、取连接都不限时；SO_KEEPALIVE 关闭。
    - 如果实际用的是 JDK 的 HttpURLConnection，就没有连接池上限，但同样没有超时。
  - **E3 共用且无隔离（成立）：** 一个 RestTemplate 负责所有步骤（Preserve:32-33），没有舱壁也没有熔断。
- **触发设想：** 对 ts-user-service（第 8 步，非关键）做黑洞注入。每笔下单都会先写单、再挂在第 8 步。发往 user 的 5 个连接被钉死之后，新请求在取连接上无限等待；Tomcat 的 200 个线程耗尽后，preserve 整体不可用。撤除注入后，如果对端从没发 RST，这些连接不会释放，只能重启。
- **机制专属信号：**
  - 线程栈里大量停在 `AbstractConnPool.getPoolEntryBlocking` 或 `socketRead0`。
  - preserve 的 CLIENT span 的 instrumentation scope 可以判断底层用的是哪种 HTTP 客户端。
  - 撤除注入后 preserve 仍然不恢复。
  - 和 TT-C1 的区别：这里 order 服务端是正常的。
- **业务影响：** 一个非关键依赖就能拖垮整个下单入口；和 TT-C2、TT-C5 叠加会产生幽灵单。
- **运行时要核对：** G1、F5、B6（在 preserve Pod 上做）。
- **置信度：** 中。没有超时这一点是高置信，连接池大小存疑。

### TT-C7 业务表很可能被 Hibernate 建成了 MyISAM：表级锁；崩溃后表损坏不会自动修复；写入不参与两阶段提交
- **机制族 / 失效模式：** 故障转移与持久性。**D4 为主**（方言的默认值选错了存储引擎），次要为 D6（恢复依赖人工 REPAIR）。
- **位置：** tsdb-mysql 库 `ts` 里的 orders、orders_other、assurance、food_order、consign_record、security_config 等表。
- **成立条件：**
  - **E1 方言导致 MyISAM（字节码层面成立，是否实际生效存疑）：**
    - 依据见 TT-C1 的 E4。
    - 范围内所有带 JPA 的服务（order、order-other、security、assurance、food、station-food、train-food、consign、consign-price，以及 contacts、user、travel）都是 MySQL5Dialect + update。
    - cm.json 里 node.cnf 的 `default_storage_engine=InnoDB` 不会覆盖显式写出的 `engine=MyISAM`；chart 里也没有 disabled_storage_engines。
  - **E2 旁证（成立）：** `data[-1]` 取最新订单总是对的，见 TT-C1 的 E4。
  - **E3 崩溃后不会自愈（存疑）：** MySQL 5.7 的 `myisam_recover_options` 默认是 OFF；mysql 容器 limit 只有 1Gi（sts.json），有被 OOMKill 的可能。
  - **E4 切主时新旧主不一致（存疑）：** 旧主上可能留下新主没有的写入，导致切主后"刚下的单查不到"或"多出订单"。
  - **E5 存储是节点本地盘（成立）：** 见 DEV 第 1 行。这一点属于基础设施组。
- **触发设想：** 在下单压测期间 kill -9 主库的 mysqld，然后执行 `CHECK TABLE`；或者触发 xenon 切主，比较新旧主的行数。
- **机制专属信号：** Engine=MyISAM；出现 145 或 1194 "marked as crashed" 错误；`Table_locks_waited` 在增长；切主前后行数不一致。
- **业务影响：** MySQL 崩溃后下单、查单持续失败，订单丢失或多出；它同时也是 TT-C1 里锁争用的来源。
- **运行时要核对：** D1、D2、D8。
- **置信度：** 中。静态证据强，一条 SQL 就能定案。

### TT-C8 补偿覆盖不全、没人回收：取消只改订单状态，不回收保险、餐食、托运，也不释放座位；下单中途失败或压测异常退出留下的 NOTPAID 订单没有任何自动回收
- **机制族 / 失效模式：** 补偿。**D2 为主**（有补偿但覆盖不全），次要为 D1（没有定时回收）。
- **位置：** cancel、order（已售座位的统计口径）、preserve 的失败路径。
- **成立条件：**
  - **E1 取消只碰订单相关服务（成立）：** Cancel 里调用的服务地址只出现在第 147、244、268、283、298、312、326 行，都是 order、order-other、inside-payment、user、notification，没有 assurance、food、consign。
  - **E2 座位不释放（成立）：** `getSoldTickets` 不按状态过滤（OrderSvc:54-66）。
  - **E3 没有定时回收（成立）：** 全仓没有 @Scheduled 或 @EnableScheduling。
  - **E4 半成品订单确实会产生（成立）：**
    - 写单之后失败会留下订单，见 TT-C2、TT-C5。
    - 压测只在下单成功后才清理，而且只取消 `data[-1]` 那一笔（WL:402-438）。
  - **E5 已经发生过（成立，事实 2 已查实）：** Repair:59-62 找到 9 笔遗留订单，靠补做取消才清掉。
  - **E6 餐食配送消息已发出、不会撤回（成立）：** 见 FoodServiceImpl:134-146。
- **触发设想：** 在下单和清理之间杀掉压测 Pod，或用 TT-C2、TT-C5 的注入制造失败；一轮结束后统计遗留的订单和孤儿附属记录。
- **机制专属信号：** 本轮新增的 status=0 订单没有被清理；附属记录指向 status=4 的订单或根本不存在的订单。和 TT-C3 的区别：遗留单不一定成对出现。
- **业务影响：** 订单列表被污染；数据无限增长，进一步加重 TT-C1；跨轮的基线被污染。
- **运行时要核对：** D3、D6、H1。
- **置信度：** 高。

### TT-C9 主从切换后连接池还粘在旧主上：旧主活着时，写入会报只读错误，直到连接寿命到期；旧主失联时，在用的连接因为没有 socketTimeout 而半开挂死
- **机制族 / 失效模式：** 故障转移。**D2 为主**（切主没有传递到已有连接），次要为 D1（没有 socketTimeout）。对应模板 T-07。
- **位置：** order 以及所有写 tsdb 的服务，连到 tsdb-mysql-leader。
- **成立条件：**
  - **E1 经 leader Service 连库（成立）：** 上游部署脚本把库地址统一设为 `tsdb-mysql-leader`（U/hack/deploy/utils.sh:66）；svc.json 里的选择器是 role=leader；DEV 第 5 行写到"leader Service 无后端 → 业务全部连不上"，可以佐证。
  - **E2 切主就是改 Pod 标签（成立）：** 见 cm.json 里 tsdb-mysql 的 leader-start.sh 和 leader-stop.sh。已建立的 TCP 连接不会跟着 Endpoints 迁移；kube-proxy 模式存疑。
  - **E3 连接池不感知切主（默认值下成立）：** maxLifetime 是 30 分钟，连接检查只用 isValid，而只读库也能通过这个检查。
  - **E4 半开挂死（成立）：** OrderYml:13 没有 socketTimeout，只能等操作系统默认 keepalive（约 2 小时 11 分）才能发现。
  - **E5 旧主是否被设为只读（存疑）：** 取决于 xenon 的行为。
- **触发设想：** 在压测期间让主库发生 xenon 切主，但不删 Pod。只读错误最多持续 30 分钟，半开挂死约 2 小时。
- **机制专属信号：** 日志出现 "--read-only option"（错误码 1290），而新建的连接正常；或者线程停在 `socketRead0`，并且有到旧主 IP 的 ESTABLISHED 连接。
- **业务影响：** 切主本应在秒级完成，下单却持续失败几十分钟甚至几小时。
- **运行时要核对：** D7、B6。
- **置信度：** 中。

### TT-C10 安检把 G/D 车次的下单硬绑到 order-other（单副本、1.0.2 镜像）上，每次还要全量扫描两个库的账户订单；而阈值默认无限大，安检只剩成本和脆弱性
- **机制族 / 失效模式：** 降级回退。**D1**。对应模板 T-09。
- **成立条件：**
  - **E1 串行同步调两个订单服务（成立）：** 见 Security:111-112、130-158，没有 try/catch。返回 status=0 时会在 Security:140-141、155-156 发生 NPE。
  - **E2 第 1 步没有降级（成立）：** 见 Preserve:52-56、345-357。
  - **E3 O(N) 扫描（成立）：** 见 OrderSvc:385-402。
  - **E4 阈值（按上游初始化数据成立，线上存疑）：** SecInit:22-31 把两个阈值都设为 Integer.MAX_VALUE。
  - **E5 order-other 是单副本（成立）：** 见 deploy.json。
- **触发设想：** 对 order-other 做 pod-kill。在它恢复的 60s 以上窗口里，G/D 车次的下单 100% 在第 1 步失败（不写单，失败是干净的）。
- **机制专属信号：** order 健康，preserve 却在第 1 步失败；安检 span 下面访问 order-other 的 CLIENT span 报错。
- **业务影响：** 另一种车次的存储出故障，就让主下单路径全挂。
- **运行时要核对：** D9、F6。
- **置信度：** 高。

### TT-C11 下单关键路径上有 6 个单副本依赖，没有 PDB 也没有反亲和；恢复动作（重启、每轮重置）又依赖 Nacos 和 NFS
- **机制族 / 失效模式：** 副本与中断预算。**D1 为主**，次要为 D2（order 的两个副本可能在同一节点）和 D6（重启依赖脆弱的外部对象）。对应模板 T-06。
- **成立条件：**
  - **E1 单副本（成立）：** security、contacts、travel、basic、seat、user 都是 1 副本，order 和 preserve 各 2 副本（deploy.json）。
  - **E2 没有 PDB（存疑）：** 导出里没有 PDB 对象。
  - **E3 没有反亲和（成立）：** order 只配了 `nodeAffinity NotIn tcse-v100-01`，没有 podAntiAffinity，也没有 topologySpread。
  - **E4 Nacos 不可用就起不来（成立，事实 3 已查实）：**
    - SCA 2.2.7 的默认配置是 `spring.cloud.nacos.discovery.fail-fast=true`、`naming-load-cache-at-start=false`，见 R/…/spring-cloud-starter-alibaba-nacos-discovery-2.2.7.RELEASE.jar 里的 spring-configuration-metadata.json。
    - 同一个 jar 里，`NacosServiceRegistry.register` 注册失败时会调用 `rethrowRuntimeException`。
    - 范围内各服务的 application.yml 都没有覆盖这两个配置，所以启动时注册失败就直接退出，进入 CrashLoopBackOff。
  - **E5 OTel agent 来自 NFS 卷（成立）：** 见 deploy.json 里的 volumes[0].nfs（1.94.151.57:/data/share）。NFS 不可达时新 Pod 会卡在挂载，这一点存疑。
  - **E6 每轮重置都要重启全部应用（成立）：** 见 Profile:101-107。
  - **E7 恢复慢（成立）：** readiness 的 initialDelay 是 60s，requests.cpu 只有 10m。
- **触发设想：** 对 seat 做 pod-kill，下单会中断 60s 以上；如果同时 Nacos 全部不可用，被杀的服务就起不来。
- **机制专属信号：** 失败时间窗与 Pod 重启时间重合；日志里出现 `Client not connected, current status: STARTING`。
- **业务影响：** 任何一个单点重启都会中断下单；Nacos 或 NFS 故障期间既不能自愈，也做不了每轮重置。
- **运行时要核对：** A1-A3、E4。
- **置信度：** 高。

### TT-C12 资源配额与运行时参数错配：堆写死 200MB 而 limit 是 1500Mi，CPU 请求只有 10m，基础镜像 java:8-jre 很可能不感知容器
- **机制族 / 失效模式：** 资源配额与 OOM。**D4**。对应模板 T-08。
- **成立条件：**
  - **E1 堆太小（按上游成立，1.0.1 存疑）：** Dockerfile:6 写死 `-Xmx200m`（order、preserve、seat、consign-price、station-food 都一样），limit 是 1500Mi。
  - **E2 CPU 请求太小（成立）：** requests 10m、limits 1500m，在范围的服务全部如此。
  - **E3 不感知容器（存疑）：** Dockerfile:1 是 `FROM java:8-jre`。这个官方镜像已经废弃，多半是 8u111，早于 8u191 开始的容器支持。于是 JVM 按宿主机的核数开 GC 和 JIT 线程，而在 1.5 核的配额下，STW 停顿会被 CPU 节流拉长。
- **触发设想：** 对同一节点施加 CPU 压力，或者直接用 TT-C1 里的大数据量。
- **机制专属信号：** 堆使用贴近 200MB，而容器内存远低于 limit；CFS throttled 周期多，但 CPU 使用量低于 limit；GC 停顿时间长。
- **业务影响：** order 和 preserve 延迟抖动，放大 TT-C1。
- **运行时要核对：** B1、C2、C4。
- **置信度：** 中。

### TT-C13 买保险是一个带副作用的 GET，而 preserve 的客户端栈会自动重试 GET：模糊失败之后，要么误报"买保险失败"，要么并发写出两条保险
- **机制族 / 失效模式：** 重试与退避。**D3 为主**，次要为 D4（用 GET 做写入）。对应模板 T-03（弱实例）。
- **成立条件：**
  - **E1 用 GET 创建保险（成立）：** 见 AssuranceController:72-77、Preserve:316-327。
  - **E2 会被自动重试（存疑）：**
    - preserve 依赖 amqp，spring-amqp 2.2.18 又带入了 spring-retry，见 R/org/springframework/amqp/spring-amqp/2.2.18.RELEASE/…pom:108-112。
    - 有了 spring-retry，Hoxton 会启用 RetryLoadBalancerInterceptor：Ribbon 遇到 IO 异常时，对 GET 换一个实例重试 1 次。
    - 如果底层是 Apache HttpClient，它的默认重试器对没有 body 的请求还会再重试最多 3 次。
    - preserve-other 和 food 也依赖 amqp，情况相同。
  - **E3 去重不可靠（成立）：** 先查后插，而且没有唯一约束（AssuranceServiceImpl:54-64、Assurance:26-27）。`findByOrderId` 只返回单条（AssuranceRepository:31），一旦有两条，这笔订单的保险查询就会抛异常。
  - **E4 默认压测不买保险（成立）：** 见 WL:381。
- **触发设想：** 下单时 assurance=1，同时对 assurance 服务的响应注入 TCP RST，或在它提交后立刻 kill 掉它。
- **机制专属信号：** 一个 preserve span 下有 2 个以上 `GET /assurances/…` 的 CLIENT span；返回 "Success.But Buy Assurance Fail."，但库里已经有这条保险；同一个 order_id 有多行保险。
- **业务影响：** 用户看到错误的状态；产生重复的保险记录；后续查询报错。
- **运行时要核对：** G1、D6、F8。
- **置信度：** 低到中。

### TT-C14 餐食下单在请求线程里同步投递 RabbitMQ：建连最长等 60s，没有发布确认，失败被吞掉
- **机制族 / 失效模式：** 超时。**D1 为主**，次要为 D4（没有确认，对应 N-02）。这一条和"消息链路"组有交叉，这里只写与下单相关的部分。
- **成立条件：**
  - **E1 同步投递、失败被吞（成立）：** FoodServiceImpl:131 先落库，:142-146 再同步调用 `convertAndSend`（RabbitSend:19-22），出错只记日志。
  - **E2 默认 60s 建连超时、没有确认（默认值下成立）：** FoodYml:22-24 只配了 host 和 port，没有 connection-timeout，也没有 publisher-confirm，所以客户端默认的建连超时是 60s。
  - **E3 RabbitMQ 单副本、没有卷（成立）：** 见 deploy.json。
  - **E4 这一步在写单之后，而 preserve 没有超时（成立）：** 见 TT-C6。
- **触发设想：** 对 food 到 5672 端口的流量丢包（丢包而不是拒绝），foodType≠0 的下单每笔会多出约 60s，就转成 TT-C5 或 TT-C2 里的幽灵单。
- **机制专属信号：** 日志 "send delivery info to mq error" 与请求开始相隔约 60s；food_order 里有记录，配送侧却没有对应记录。
- **业务影响：** 配送信息静默丢失；下单变慢并出现模糊失败。
- **运行时要核对：** F9。
- **置信度：** 中。默认压测覆盖不到这一步。

### TT-C15 占座没有预留也没有唯一约束，并发时会超卖；余票校验写错了；售罄时 seat 服务死循环。但默认数据下每种车型的座位数都是 Integer.MAX_VALUE，这些问题难以触发
- **机制族 / 失效模式：** 准入与过载保护 + 幂等。**D4 为主**（校验存在但写错了），次要为 D1（没有预留、没有唯一约束）。
- **成立条件：**
  - **E1 先读、再算、后写，中间没有锁（成立）：** 见 Seat:59-115 与 Preserve:170。
  - **E2 没有唯一约束（成立）：** 见 OrderEnt:19-22。
  - **E3 余票校验写错（成立）：**
    - Preserve:87-97 对一等座只在余票"恰好等于 0"时拒绝。
    - 二等座的判断写成了 `getEconomyClass()==3 && getConfortClass()==0`。
    - 余票数可能是负数（Seat:199-200）。
  - **E4 售罄时死循环（成立）：**
    - 1..total 号座位全部售出时，Seat:109-111 的循环永远不退出；而已售集合里还包括已取消的订单。
    - seat 是单副本、CPU limit 1500m，死循环还会拖垮搜索路径上的余票查询。
  - **E5 能否触发（默认数据下不成立，线上数据存疑）：**
    - TrainInit:21-22 把各车型的座位数都设为 Integer.MAX_VALUE，随机撞座概率约为 n/2^31。
    - 另外，Seat:100-107 的"复用已售座位"不检查同一座位的其他区段，买部分区段时会确定性地重复分座。这是功能缺陷；压测只买全程，所以触发不了。
- **触发设想：** 先把某个车型的座位数改小（这是一次数据变更），再以 2 个以上的并发对同一（日期，车次）下单，直到售罄。
- **机制专属信号：** 未取消的订单里，出现同一日期、车次、座位等级、座位号的重复；seat Pod 的 CPU 被打满，线程停在 isContained。
- **业务影响：** 超卖；seat 服务被占满后，搜索和下单一起挂掉。
- **运行时要核对：** D10、D11。
- **置信度：** 低。代码缺陷是确定的，但默认数据下很难触发。

**跨范围的共性问题（一句话）**
- **入口：** 网关没有响应超时；Sentinel 只对 admin-basic-info 限流（GwCfg:107-118），preserve 和 order 没有任何准入控制。
- **查询链路：** 搜索时每个车次都要经 seat 打 order 2 次（Travel:426-429），和 TT-C1 同命运。
- **支付与消息：** order 有两个用 GET 改状态的接口：`GET /order/status/{id}/{status}` 和 `/order/orderPay/{id}`（OrderCtl:90-110）。如果调用方带着 spring-retry，这两个 GET 会被自动重试。
- **基础设施：**
  - tsdb 主库只有 500m CPU、1Gi 内存，被所有服务共用。
  - Nacos 2.0.1 出现过副本分歧。
  - 新环境用的是 openebs-hostpath 本地盘（DEV 第 1 行）。
  - 对 xenon 的 `::1` 修补掩盖了缺陷 TT-RT-01（DEV 第 5 行）。

---

## 保护有效的点（可以用作负控制）

1. **写单之前的失败不留痕：** 分座是纯计算（Seat:41-116）；第 1 到 4b 步都是只读，遇到 status=0 就直接返回（Preserve:53-56、63-66、81-98、135-138）。所以在写单前注入故障，orders 表的行数不应该增加。
2. **平台层不会重放 POST：** Ribbon 默认只重试 GET；HttpClient 默认也不重试已经发出的带 body 请求；网关没有 Retry（GwYml）；压测不重试（WL:402-403）。重复下单只可能来自调用方。
3. **餐食和保险的顺序重复会被挡住：** 见 FoodServiceImpl:116-119、AssuranceServiceImpl:54-58。只对非并发的重复有效。
4. **两套订单库在系统内部是一致的：** seat 按车次前缀选库，安检和取消两个库都查；车次和接口对不上时会在第 3 步失败，不会写单（见上面步骤表后的说明）。
5. **安检阈值默认无限大（SecInit:22-31）：** 遗留订单不会触发防刷机制把账户锁死。前提是线上的值没有被改过，见 D9。
6. **遥测导出不在请求线程里（N-01 不适用，存疑）：** 用的是 OTel agent 的批量 OTLP 导出；在范围的服务没有 logback 配置，也没有同步的远程日志输出。
7. **就绪探针的端口和服务端口一致：** deploy.json 与各服务的 `server.port` 对得上，不存在探针指错端口的问题。

---

## 运行时核对清单汇总（已去重；全部为只读操作）

### A. K8s 对象
- **A1** `kubectl -n train-ticket get deploy ts-order-service ts-preserve-service ts-gateway-service -o jsonpath='{range .items[*]}{.metadata.name} {.spec.replicas} {.status.readyReplicas}{"\n"}{end}'`，确认实际副本数（导出与任务描述不一致）。
- **A2** `kubectl get pod -o wide -l app=ts-order-service`（preserve 同样）看两个副本是否在同一节点；`kubectl get pdb -n train-ticket`。
- **A3** 查新环境里 order/preserve Pod 的 `spec.volumes[].nfs.server` 取值，以及 Pod events 里有没有 NFS 挂载超时。

### B. ts-order-service Pod 内（exec 只读命令）
- **B1** 看 JVM 启动参数和运行环境：
  - `cat /proc/1/cmdline | tr '\0' ' '`，确认 Xmx 是否仍是 200m。
  - `java -version`，看是否早于 8u191。
  - `cat /sys/fs/cgroup/cpu.max 2>/dev/null || cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us`，以及 `nproc`。
- **B2** `ls /proc/1/fd | wc -l`；`grep 'open files' /proc/1/limits`。
- **B3** `cat /proc/net/tcp /proc/net/tcp6`：
  - 统计状态为 `08`（CLOSE_WAIT）的连接，按本地端口 `2EFF`（12031）和远端端口 `0CEA`（3306）、`2678`（9848）、`10DE`（4318）、`6989`（27017）分组计数。
  - 状态为 `0A`（LISTEN）、本地端口 2EFF 那一行的 rx_queue 就是 accept 队列长度，满时为 100。
- **B4** `grep -A1 TcpExt /proc/net/netstat` 间隔两次取差值，看 ListenOverflows 和 ListenDrops。
- **B5** 日志关键字：
  - `OutOfMemoryError`、`http-nio-12031-Acceptor`
  - `HikariPool-1 - Connection is not available`、`Communications link failure`
  - `marked as crashed`、`read-only option`
  - `[queryOrders][Step 1][Get Orders Number of Account][size:`（看 N 随时间的变化）
  - `[getSoldTickets][Left ticket info]`（看单行日志的长度）
- **B6（可选：SIGQUIT 只打印线程栈、不影响进程；如果团队口径不允许就跳过）** `kill -3 1` 之后看 `kubectl logs`：
  - 统计停在 `HikariPool.getConnection`、`socketRead0`（com.mysql.cj）、`getPoolEntryBlocking` 上的线程数。
  - 看 Acceptor 和 Poller 线程是否还在。
  - 在 preserve Pod 上做同样的检查。

### C. 指标（OTel agent 与 cAdvisor；指标名随 agent 版本略有不同）
- **C1** 每个 order Pod 的 `db.client.connections.usage{state=used}` 和 `db.client.connections.pending_requests`。
- **C2** 堆使用量对比 200MB、GC 停顿时间、线程数。
- **C3** `http.server.active_requests`；`/order/tickets`、`/order/security/*`、`POST /order` 的 p95 随时间和 N 的变化。
- **C4** order 和 tsdb 主库的 `container_cpu_cfs_throttled_periods_total`，以及 CPU 使用量对比 limit（主库为 500m）。

### D. tsdb 主库（只读 SQL）
表名和列名按 Spring 默认的蛇形命名推断；库名以 secret 中的 `*_MYSQL_DATABASE` 为准，上游为 `ts`。
- **D1** `SELECT TABLE_NAME, ENGINE, TABLE_ROWS, DATA_LENGTH FROM information_schema.TABLES WHERE TABLE_SCHEMA='ts';`
- **D2** 两条语句：
  - `SHOW INDEX FROM orders; SHOW INDEX FROM orders_other;`
  - 在每个 tsdb Pod 上执行：`SHOW VARIABLES WHERE Variable_name IN ('concurrent_insert','low_priority_updates','myisam_recover_options','lock_wait_timeout','read_only','super_read_only','default_storage_engine','enforce_storage_engine','disabled_storage_engines');`
- **D3** 看数据分布：
  - `SELECT status,COUNT(*) FROM orders GROUP BY status;`
  - `SELECT account_id,COUNT(*) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 5;`
  - `SELECT travel_date,train_number,COUNT(*) FROM orders GROUP BY 1,2 ORDER BY 3 DESC LIMIT 5;`
  - orders_other 做同样的查询。
- **D4** `SELECT id,bought_date,status FROM orders WHERE account_id='<压测账户>' AND bought_date BETWEEN '<t0>' AND '<t1>';`，和压测结果文件（JTL）里 preserve 失败、超时的时刻对齐。
- **D5** 查重复单：`SELECT account_id,train_number,travel_date,contacts_document_number,seat_class,from_station,to_station,COUNT(*) c,MIN(bought_date),MAX(bought_date) FROM orders WHERE status IN (0,1) GROUP BY 1,2,3,4,5,6,7 HAVING c>1;`
- **D6** 查附属记录：
  - 重复：`SELECT order_id,COUNT(*) FROM assurance GROUP BY 1 HAVING COUNT(*)>1;`
  - 孤儿：`SELECT COUNT(*) FROM assurance a LEFT JOIN orders o ON o.id=a.order_id LEFT JOIN orders_other p ON p.id=a.order_id WHERE o.id IS NULL AND p.id IS NULL;`
  - food_order、consign_record 做同样的查询；另外统计附属记录指向 status=4 订单的数量。
- **D7** 在每个 tsdb Pod 上执行 `SHOW PROCESSLIST`，看旧主上是否还残留业务服务的连接。
- **D8** 在负载下执行 `SHOW FULL PROCESSLIST`，统计 `Waiting for table level lock` 的数量；`SHOW GLOBAL STATUS LIKE 'Table_locks_%';` 间隔两次取差；再看 slowlog 容器里对 `orders` 做全表扫描的耗时。
- **D9** `SELECT * FROM security_config;`
- **D10** `SELECT id,confort_class,economy_class FROM train_type;`
- **D11** 查撞座：`SELECT travel_date,train_number,seat_class,seat_number,COUNT(*) FROM orders WHERE status IN (0,1,2) GROUP BY 1,2,3,4 HAVING COUNT(*)>1;`

### E. Nacos（只读 Open API）
- **E1** 分别对 nacos-0、nacos-1、nacos-2 执行 `curl -s 'http://<pod>:8848/nacos/v1/ns/instance/list?serviceName=<svc>'`。svc 依次取 order、order-other、preserve、seat、security、user、contacts、travel、basic、assurance、food、consign 这些服务。比较三个副本的结果是否一致，以及是否和 `kubectl get pod -o wide` 的 IP 一致。
- **E2** order Pod 处于 NotReady 期间，它的 IP 在 Nacos 里是否仍是 healthy=true。
- **E3** 看 Nacos 服务端日志里的 Distro 同步错误。
- **E4** 业务 Pod 启动日志里的 `Client not connected, current status: STARTING`；结合 G1 看 jar 里有没有覆盖 fail-fast。

### F. Trace 与日志
- **F1** 统计"根 span 为 ERROR，而 `POST /order` 子 span 为 200"的 trace，并按报错的子 span（user、assurance、food、consign）分组。
- **F2** preserve 日志里 "[Step 4][Do Order][Do Order Complete]" 之后紧跟异常栈的请求数。
- **F3** 调用方发往 order 的 CLIENT span 按对端 IP 分布，找出发往不存在或 NotReady 的 IP、以及报 `connect timed out` 或 `No route to host` 的调用。
- **F4** 找"网关 span 结束早于 preserve 服务端 span，而后者包含成功写单"的 trace；以及 preserve 日志里的 `ClientAbortException` 或 `Broken pipe`。
- **F5** 看 preserve CLIENT span 的 instrumentation scope 是 apache-httpclient 还是 http-url-connection，以此判断底层 HTTP 客户端。
- **F6** 安检 span 下访问 order-other 的 CLIENT span 是否报错。
- **F7** order 自己是否发起出站 CLIENT span（对应 H3）。
- **F8** 同一个 preserve span 下是否有重复的 `GET /assurances/…`。
- **F9** food 日志里 `send delivery info to mq error` 与请求开始的时间差。

### G. 镜像内容（kubectl cp 把 jar 拷到本地，只读分析）
- **G1** 从 preserve、order（1.0.1）、order-other（1.0.2）、consign-price（1.0.1）的 Pod 中拷出 `/app/*.jar`，然后：
  - `unzip -l` 看 BOOT-INF/lib 里有没有 httpclient-4.5.x、spring-retry、ribbon，以及 nacos-client 和 hibernate-core 的版本。
  - `unzip -p … BOOT-INF/classes/application.yml` 看 datasource 参数、hikari、server.tomcat、dialect、fail-fast 是否被改过。
  - 对 order 1.0.1 的 `OrderServiceImpl`、`Order`、`OrderRepository` 执行 `javap -c -p`，与上游对比：create 的去重、refresh 是否恢复了出站调用、查询是否加了 ORDER BY 或分页。

### H. 压测
- **H1** 确认运行时 fixture 里的 travel_date 和账户是否跨轮复用，这决定 N 的增长速度。再确认清理步骤取消的是不是本轮刚下的单：比对被取消订单的下单时间与本轮 preserve 的时刻。