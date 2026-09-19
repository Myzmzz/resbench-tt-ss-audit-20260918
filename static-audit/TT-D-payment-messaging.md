以下是 train-ticket 支付、取消改签与消息链路的排查结果。全程只读：没有改任何文件，没有访问集群或网络。

**口径**
- 源码以上游 313886e9 为准。线上 ts-payment-service 1.0.2、ts-order-service 1.0.1、ts-order-other-service 1.0.2 三个镜像，在 static-manifests.yaml:3224、live-export.yaml:4315 等处只有 tag 不同，找不到改动原因的注释。凡涉及这三个服务的结论都注明「以上游为准」，实际差异见 R10。
- 默认负载只跑「下单→查询→取消未支付订单」：profiles.yaml:22-27；generator:382 的 foodType=0；负载里没有支付步骤。支付、改签、餐食消息链路都要自定义负载才能激活。
- 全仓没有 `@Scheduled`，唯一的后台线程是 wait-order 的 PollThread。本范围服务全部单副本，所以「多副本重复执行、单例保证」这一类不适用。

## 资金与消息流程表

| 流程 | 发起方 | 通道 | 接收方 | 确认 / 一致性方式 |
|---|---|---|---|---|
| 站内支付 | InsidePaymentController.java:31-35 → InsidePaymentServiceImpl.java:46-139 | 取订单 :59-65；余额不足时 POST ts-payment-service :108-114；GET /order/status/{id}/1 :330-358 | PaymentServiceImpl.java:33-46；OrderServiceImpl.java:315-327 | 无事务、无补偿。站外分支先记账后改单（:119-121）；余额分支先改单后记账（:128-130）；setOrderStatus 的返回值被忽略 |
| 取消退款 | 网关 GET /cancel/{orderId}/{loginId} → CancelController.java:40-51 → CancelServiceImpl.java:46-141 | 取订单 :308-320；PUT 整单改为 4 :238-252；GET drawback :278-292；GET user :294-306 | OrderServiceImpl.java:440-468（整单覆盖）；InsidePaymentServiceImpl.java:245-257（插入 inside_money 的 D 类行） | 先改单后退款；退款失败只记日志（:89-92）；任何异常都被包装成 status=1（CancelController.java:48-50） |
| 改签 | RebookController.java:31-42 → RebookServiceImpl.java:48-143 / :146-182 | 退差价 drawback :454-466 或补差价 difference :435-452，然后 updateOrder :184-236（同类 PUT :340-357；跨类 POST 删除 :359-378 再新建 :319-338） | InsidePaymentServiceImpl.java:245-257 / :260-317 | 先动钱后改单，无回滚；跨类时 delete/create 的返回值被忽略（:231-234） |
| 取票/检票 | ExecuteServiceImpl.java:89-133 / :41-86 | GET /order/status :136-161，鉴权头被置空（:44、:138），该接口本身 permitAll | OrderServiceImpl.java:315-327 | 先读后写，非原子 |
| 餐食配送消息（唯一在用的 MQ 链路） | FoodServiceImpl.java:131 落库 → :143（批量 :101-108）→ RabbitSend.java:21 | 默认交换机，队列 food_delivery（两端 Queues.java:10-14 都声明 durable） | ts-delivery-service RabbitReceive.java:35-55 → delivery 表 | 生产端无 confirm/returns（yml:22-24 只配了 host/port），发送异常被吞（:142-146）；消费端 AUTO ack（yml:16-18），落库异常被吞（:49-54） |
| 邮件通知消息 | PreserveServiceImpl.java:288-291（调用处 :261 已注释）；PreserveOtherServiceImpl.java:260 已注释；NotificationController.java:33-35 自测接口 | 队列 email（notification Queues.java:10-14） | notification RabbitReceive.java:51-91（先发邮件 :79，后落库 :90） | AUTO ack，异常即重新入队；没有业务生产者 |
| 候补轮询 | WaitListOrderServiceImpl.java:52-64 → :162-171 每单 new 一个 PollThread | POST ts-preserve-service（PollThread.java:74-82） | — | 仅内存线程、无恢复；实际首轮即退出，见后文「排查过但不成立」 |
| 凭证 | voucher server.py:14-44 | urllib 调 order / order-other :46-66（走 K8s DNS，不经 Nacos） | voucher 表 | 先查后插，无唯一键 |

## 候选缺陷（按严重度排序）

### TT-D1 取消接口把任何异常包装成 status=1「成功」，压测成功率看不到取消链路的故障
- 机制族 / 失效模式：fallback_degradation；主 D3（兜底被触发了，但返回「成功」这个动作本身造成错误），次 D4（状态码写错）。
- 位置：ts-cancel-service 入口的 catch 块。受波及的调用边：cancel→order（PUT）、cancel→inside-payment（drawback）、cancel→user。
- 成立条件：
  - E1 成立：异常被映射为成功。CancelController.java:45-51 `catch (Exception e)` 后返回 `ok(new Response<>(1,"error",null))`，HTTP 200。
  - E2 成立：下游异常都会抛到这里。CancelServiceImpl.java 的 :245-249、:269-273、:284-288、:299-304、:313-318 全是 `restTemplate.exchange`，没有 try。
  - E3 成立：负载以 status==1 判成功。generator:285-289；cleanup-order 在 :430-438。
  - E4 成立：取消在默认负载里。profiles.yaml:22-27 中 order 流占 30%，cleanupCreatedOrders: true。
  - E5 存疑：只有快速失败会被掩盖。拒连、无可用实例这类快速异常会被掩盖；下游挂住超过 10 s 时，负载端先超时（generator:585），这种反而可见。
- 触发设想：默认负载约 0.3 次取消/秒，10 分钟约 180 次。对 ts-inside-payment-service 做 pod-kill 或端口拒连（单副本），或对 order-service 的 PUT /order 注入 abort。注入期间 cleanup-order 成功率仍接近 100%。
- 机制专属信号：
  - 响应体是 `{"status":1,"msg":"error","data":null}`；正常成功时 msg 是 "Success."，G/D 订单的 data 是 "test not null"（:92）。
  - cancel 日志里有只打印异常消息的 ERROR 行（:49）。
  - Jaeger 里根 span 返回 200，但子 span 标记 error。
  - 与 T-02 的区别：T-02 是客户端先看到失败、后端后落地；这里客户端直接看到「成功」。
- 业务影响：
  - PUT 失败时，订单仍是 0（未支付），接口却报成功。
  - drawback 失败时，订单已是 4（已取消），退款缺失。
  - SLO 对「注入在取消链路下游」的故障失明，直接影响评测的可观测性。
- 运行时要核对：R1、R2、R3。
- 置信度：高。E1–E4 都有直接静态证据；E5 只影响能看见的比例。

### TT-D2 取消是「先改为已取消、再退款」，退款失败只记日志仍报成功，没有补偿也没有对账（回应主会话事实 3）
- 机制族 / 失效模式：idempotency_compensation；主 D1（按手册 §10「扣款后订单中止、无补偿」口径），次 D2（失败不回传给调用方，状态守卫还挡住了补救性重试）。
- 位置：ts-cancel-service → ts-order-service（PUT）→ ts-inside-payment-service（drawback）。
- 成立条件：
  - E1 成立：先改单。:57 → :238-252 PUT 状态 4，然后才在 :63-64 退款；order-other 分支是 :115 → :120-121。
  - E2 成立：退款失败不回传。:89-92 与 :122-127 只记 LOGGER.error，仍返回 status 1；退款抛异常时由 TT-D1 包装成成功。
  - E3 成立：重试无法补救。守卫只放行状态 0/1/3（:52-53、:109-110），订单已是 4 时返回 "Order Status Cancel Not Permitted"（:98-100）。
  - E4 成立：无补偿、无对账。全仓没有定时任务；inside_money 表只有 id、userId、money、type 四列（inside 的 Money.java:19-41），没有 orderId，无法按订单对账。
  - E5 条件成立：要已付订单才会丢钱。未支付订单的退款额是 "0.00"（:201-203），默认负载下只会少一条 0 元记录；已付订单按 80% 退（:228-233）。
- 对事实 3 的判断：会出现金额与订单状态不一致，代码里没有任何补偿、重试、outbox 或对账。中途失败有三种终态：
  - ① PUT 失败或抛异常：订单仍是 0 或 1，接口却报成功，表现就是「遗留未取消订单」。
  - ② PUT 成功，drawback 返回 0：订单为 4，没有退款行，接口报成功。
  - ③ PUT 成功，drawback 抛异常：结果同 ②。
  - 那 9 个遗留单可能来自 ①，也可能是负载在下单与取消之间就中断了：query-order 失败时 generator:425 附近直接 return，不会走到 :430 的取消；重置步骤 scale-load-generator-zero 也可能杀掉进行中的流。静态区分不了，要用 R5 按单号查。
- 触发设想：自定义 preserve→pay→cancel 流。取消进行中对 inside-payment 注入 abort 或 pod-kill，或让 inside-payment 到 tsdb-mysql:3306 丢包。
- 机制专属信号：订单状态为 4、inside_payment 里有该订单的支付记录，但 inside_money 中 D 类金额合计少于 Σ0.8×price；cancel 日志有 "[cancelOrder][Draw Back Money Failed]"（:90/:125）。
- 业务影响：取消退款丢失，用户看到的是成功。
- 运行时要核对：R3、R4、R5。
- 置信度：高（机制）；9 个遗留单的成因：低，需 R5。

### TT-D3 改签先动钱后改单、失败不回滚；「只能改一次」的守卫最后才落地，部分失败后可以反复退差价；跨类改签必然失败
- 机制族 / 失效模式：idempotency_compensation；主 D1，次 D2。
- 位置：ts-rebook-service → ts-inside-payment-service → order / order-other。
- 成立条件：
  - E1 成立：先动钱。退差价是 RebookServiceImpl.java:127 退款 → :131 改单；补差价是 :176 扣款 → :177 改单。
  - E2 成立：改单阶段有多个失败点，且都不回滚。route 查询返回 status 0 时得到 null（:426-428），在 :199 触发 NPE；:204-216 调 seat；:222-228 PUT 失败只返回 "Can't update Order!"。
  - E3 成立：守卫不覆盖部分失败。守卫要求状态为 1（:53），状态 3 会被拒（:69-71），但状态 3 只在成功路径写入（:191 + :222）。失败后订单仍是 1，可以再改签、再退一次差价；错误提示还在引导用户重试（:129 "please try again!"、:180）。
  - E4 成立（以上游为准）：跨类改签确定性失败。删除订单用的是 POST（:371-375），而 order-service 的删除接口是 @DeleteMapping（OrderController.java:142，order-other 在 :139），结果是 405 → 抛异常，此时钱已经动过。即使删除成功，:231-234 也忽略 delete/create 的返回值直接报 "Success"，删除成功但新建失败时订单就丢了。
  - E5 成立（功能缺陷，会放大本条）：补差价不校验余额。InsidePaymentServiceImpl.java:278/:280/:285 的 `BigDecimal.add` 结果被丢弃，永远走站内扣款分支（:313-314），也没有去重。
- 触发设想：自定义 preserve→pay→rebook 流。
  - 确定性触发：把 G/D 车次改签成更便宜的 Z/K/T 车次，每调用一次就退一次差价，订单不变。
  - 故障触发：同类改签时让 route 返回 status 0，或对 seat / order 的 PUT 注入 abort。
- 机制专属信号：inside_money 中 D 类行数随改签次数增长，而订单状态仍为 1、车次不变；rebook 日志出现 405 或 NPE 栈。与 TT-D2 的区别：TT-D2 是少退，这里是多退、多扣。
- 业务影响：多退差价、重复补差价、订单丢失。
- 运行时要核对：R3、R6、R10。
- 置信度：高。E4 依赖 1.0.1/1.0.2 镜像没有改过删除接口。

### TT-D4 支付部分失败后，重试被 ts-payment-service 的订单号去重以「失败」拒绝，订单永远付不了而用户已被记账；余额分支先改为已支付、后记账
- 机制族 / 失效模式：idempotency_compensation；主 D3（去重被触发了，却用「失败」回应合法重试），次 D4（先查后插、没有唯一约束）、D5（与 inside-payment 的非原子多步组合）、D1（无补偿）。
- 位置：inside-payment → payment（POST /payment）→ order（GET status）。以上游为准，线上 payment 是 1.0.2。
- 成立条件：
  - E1 成立：站外分支顺序是 :110-114 扣款 → :119-120 本地记账 → :121 改单；改单抛异常时，前两步已落地，订单仍是 0。
  - E2 成立：重试能通过入口守卫，:70 只检查订单是否未支付。
  - E3 成立：去重以失败回应。PaymentServiceImpl.java:35 只在查不到时才记账，否则 :43-44 返回 0 并提示 "order not found"（与事实相反）；inside-payment 在 :123-125 跟着返回失败，从此每次都失败。
  - E4 成立：去重本身有竞态。Payment.java:29-30 的 orderId 没有唯一约束；并发插入两行后，PaymentRepository.java:16 的单值查询会抛 IncorrectResultSizeDataAccessException，该订单此后永久 500。
  - E5 成立：余额分支 :128 先改单、:129-130 后记账，本地库故障时订单已支付却没有扣款记录。:121/:128 还忽略了改单的返回值。
  - E6 成立（功能缺陷）：站外支付也计入站内支出，:87-90 汇总了全部 Payment 行。
- 触发设想：自定义支付负载，并让余额不足。初始只有 4d2a46c7… 账户的 10000（inside-payment 的 InitData）。pay 期间对 order 的 GET /order/status 注入 abort，然后客户端重试 pay。
- 机制专属信号：payment 表有该订单、inside_payment 有 type='O' 的行，但订单状态仍为 0；payment 日志有 "[pay][Pay Failed][Order not found with order id]"（:43）。
- 业务影响：钱已扣、订单未支付、且无法再支付；E5 导致运营方损失。
- 运行时要核对：R4、R9、R10。
- 置信度：中。路径需要余额不足加自定义负载，1.0.2 也可能改过。

### TT-D5 资金与状态守卫全都是「跨服务先读后写」，order-service 无条件覆盖：慢写加重复请求时会重复退款、重复扣款，已检票的票也能被退
- 机制族 / 失效模式：idempotency_compensation；主 D4（守卫非原子，写端既没有版本号也不校验状态机），次 D5（与「无超时 + 客户端放弃后重试」组合）。
- 位置：cancel / rebook / pay / execute → ts-order-service。
- 成立条件：
  - E1 成立（以 1.0.1 上游为准）：写端无条件。OrderServiceImpl.java:315-327 直接改状态；:440-468 用调用方传来的整单覆盖；没有乐观锁。
  - E2 成立：守卫基于旧读。cancel 是 :48→:52→:57；pay 是 :59-70→:121/:128；rebook 是 :50-53→:124-131；execute 是 :93-104。
  - E3 成立：慢写窗口可以被拉长。RestTemplate 都用 `builder.build()`，没有超时；负载端 10 s 就放弃（generator:585），服务端还在继续执行（T-02）。
  - E4 存疑：重复请求从哪来。默认负载并发为 1 且不重试；网关没有 Retry 过滤器。需要真实用户重复点击、自定义的并发或重试客户端，或者 TT-D12 的自动重试。
- 触发设想：对 order-service 的 PUT /order 注入 ≥10 s 延迟，客户端超时后重发取消（已付订单）。两个请求都读到已支付，于是两次退款；pay 同理。execute 与 cancel 并发时，已检票（2）的订单会被改为 4 并退 80%。
- 机制专属信号：同一订单号在 Jaeger 里有两条带 drawback 子 span 的 cancel trace；inside_payment 中同一订单有两行 type='P'。
- 业务影响：重复退款或扣款；cancel 的整单 PUT 还会回滚并发改签刚写入的车次和座位。
- 运行时要核对：R3、R4、R12。
- 置信度：中。机制确定，触发取决于重复请求来源。

### TT-D6 取消路径上挂着非关键依赖：0 元退款也同步调 inside-payment，已注释掉的通知仍同步查 user-service，order-other 回退只认逻辑失败
- 机制族 / 失效模式：fallback_degradation；主 D1（T-09 实例，与模板口径一致），次 D2（回退不覆盖传输异常）。
- 位置：ts-cancel-service → inside-payment / user / order。
- 成立条件：
  - E1 成立：0 元也退款。:201-203 返回 "0.00"，:63-64 无条件调 drawback。
  - E2 成立：通知早已禁用，但依赖还在。:70-73 查 user（只在 G/D 分支），:86-87 的发邮件已注释。user-service 返回 0 时，订单其实已取消、已退款，接口却返回 0 "Cann't find userinfo"。
  - E3 成立：回退只认逻辑失败。:48 抛异常时不会走 :104 的 order-other 查询，所以 Z/K/T 订单的取消也依赖 order-service。
  - E4 成立：默认负载会走到。
- 触发设想：
  - 对 ts-user-service 注入延迟 d，取消 p95 会增加约 d；SLO 上限 2500 ms，d≈2.3 s 越线。
  - 让 user-service 返回 status 0，会产生「假失败」。
  - 异常类注入会被 TT-D1 掩盖。
- 机制专属信号：cancel trace 的时延随 user 子 span 变化，但订单已是 4，inside_money 也已新增 0.00 行。
- 业务影响：取消路径的时延和可用性被两个非必需依赖拖累。
- 运行时要核对：R1、R3。
- 置信度：高。

### TT-D7 每次取消都往 inside_money 追加一行，而 drawBack 的「账户存在」检查每次全量加载该用户全部记录：随压测单调老化
- 机制族 / 失效模式：resource_limit；主 D4（存在性检查实现成全量加载，而且永远为真），次 D5（与 -Xmx200m、仅 TCP 就绪、TT-D1 掩盖三者组合）。
- 位置：ts-inside-payment-service 的 drawBack 与 pay；tsdb-mysql。
- 成立条件：
  - E1 成立：每次取消 +1 行，见 :247-251。默认负载约 1,080 行/小时，全部落在同一 userId 上。
  - E2 成立：检查 O(n) 且恒真。:246 的 `!= null` 判断作用于 List（AddMoneyRepository.java:20），List 永不为 null；pay 同理（:81-97）。
  - E3 存疑：可能没有 user_id 索引。实体只有主键，且 ddl-auto: update（application.yml:17-22）。
  - E4 成立：数据跨 episode 保留。重置时 PVC 受保护（train-ticket.yaml:109-110）。
  - E5 成立（以上游 Dockerfile 为准）：堆 OOM 不可见。Dockerfile 用 -Xmx200m、没有 ExitOnOutOfMemoryError；清单里只有 TCP readiness（18673），没有 liveness。堆 OOM 后进程和端口都还在，而 drawback 的失败又被 TT-D1 掩盖。
- 触发设想：长时间默认负载即可，不需要注入。粗估 10 万行时，每次请求要载入约 50–100 MB，在 200 MB 堆上会出现 GC 抖动甚至 OOM（估算值，以 R7 实测为准）。
- 机制专属信号：drawback span 的时延随 inside_money 行数线性增长，与是否注入无关。
- 业务影响：取消 p95 随运行时长漂移，各 episode 的基线不可比。
- 运行时要核对：R7、R11。
- 置信度：中。机制确定，严重程度取决于实际行数。

### TT-D8 餐食配送消息的生产端：落库后才发布，发布异常被吞，没有 confirm / outbox，而且在请求线程里同步发布
- 机制族 / 失效模式：投递语义，暂归 idempotency_compensation（若 wave2 建议的 delivery_ack 族被采纳，则归该族）；主 D1（N-02 实例：生产者无确认），次 D2（失败不回传）、D5（同步发布 × 默认建连超时 × preserve 的餐食降级只看 status）。
- 位置：ts-food-service → rabbitmq → delivery；上游是 preserve 的第 6 步。
- 成立条件：
  - E1 成立：:131 落库，:142-146 发送异常只记日志，:148 仍报成功。
  - E2 成立：没有确认。yml:22-24 只有 host/port，Spring Boot 2.3 默认不开 publisher confirm/returns；RabbitSend.java:21 用 convertAndSend 直接发。
  - E3 成立：preserve 调 food 没有超时（PreserveServiceImpl.java:406-417），降级只处理 status≠1（:207-212），不处理异常和慢。
  - E4 存疑（库默认值）：amqp-client 建连超时 60 s，CachingConnectionFactory 串行建连；rabbitmq 没有端点时是立即拒连还是挂住，取决于 kube-proxy 模式（R20）。
  - E5 默认负载不触发：foodType 为 0（generator:382），preserve 跳过这一步（:213-215）。
- 触发设想：负载改成带餐。
  - pod-delete rabbitmq：新 Pod 就绪前的配送消息全部丢失，下单仍然成功。
  - 对 rabbitmq 做 ≥120 s 的 100% 丢包：旧连接里缓冲的消息在心跳判死时丢失，此后每次重连阻塞约 60 s。短时丢包因 TCP 重传不会丢，只能作负控制。
- 机制专属信号：food_order 的增量大于 delivery 的增量；food 日志有 "send delivery info to mq error"（:106/:145）；preserve 耗时出现约 60 s 的台阶。
- 业务影响：订餐成功但配送记录静默缺失；带餐下单变慢。
- 运行时要核对：R13、R15、R16、R20。
- 置信度：中高。

### TT-D9 配送消费端吞掉落库异常，AUTO ack 照常确认，消息静默丢失；也没有去重
- 机制族 / 失效模式：投递语义；主 D2（失败没有传到确认机制），次 D1（无死信、无去重）。
- 位置：ts-delivery-service → delivery 库。
- 成立条件：
  - E1 成立：RabbitReceive.java:49-54 catch 住异常后正常返回。
  - E2 成立：yml:16-18 没有 listener 配置，默认 AUTO ack，方法正常返回即确认。
  - E3 成立：无去重。:45-47 缺 id 时生成随机 UUID，orderId 也没有唯一约束。
- 触发设想：带餐负载下，让 delivery 到 tsdb-mysql:3306 不通（或 tsdb 切主期间），期间的消息全部被确认后丢弃，恢复后也不会补。
- 机制专属信号：delivery 日志有 "Save delivery object into database failed"（:53），队列 messages_ready 始终为 0。与 TT-D8 的区别：food 没有发送错误日志，消息确实到过 broker。
- 业务影响：配送记录丢失。
- 运行时要核对：R13、R15、R16。
- 置信度：高。

### TT-D10 rabbitmq 单实例（主会话已查实）：没有卷，没有内存 limit，只有 TCP readiness，没有 liveness；以及事实 2 的判断
- 机制族 / 失效模式：replica_disruption / resource_limit / health_probe(readiness)；主 D1（T-10、T-06 实例），次 D4（内存高水位的计算基线错了）。
- 位置：rabbitmq Deployment，以及所有 AMQP 客户端。
- 成立条件：
  - E1 成立：deployments.json 的 rabbitmq 没有 volumes。队列按 durable 声明、消息默认持久化，但都落在容器可写层，形同虚设。
  - E2 成立：replicas=1，没有 PDB。
  - E3 成立：只有 requests 100m/200Mi，没有 limit。高水位按检测到的内存计算，没有 cgroup limit 时就按节点内存算，流控几乎不会先于节点驱逐触发（这一点存疑，见 R14）。
  - E4 成立：readiness 只探 tcpSocket 5672，没有 liveness，broker 告警阻塞发布时端口照样通。
- 事实 2 的判断（依据代码 + Spring AMQP 2.2 默认值，各服务 yml 都没有 listener 配置）：
  - 消费方能自动重连：能。容器每 5 s 无限重试；Service 名 rabbitmq 的 ClusterIP 不变；Boot 自动配置的 RabbitAdmin 会在新连接建立时重新声明 Queue bean，所以不会因队列缺失而停掉容器。优雅删除 Pod 的场景下，预期在 broker 就绪后 ≤5 s 恢复。
  - 例外是半开连接：broker 没发 FIN 就消失时（节点失联、网络黑洞），要等 60 s 心跳约两个周期（约 120 s）才会重连。
  - 未确认的消息会丢：
    - ① broker 侧的就绪和未确认消息随重建一起消失，因为没有卷。
    - ② 已经预取到消费者（默认 prefetch 250）、还没处理完的消息，本应由 broker 重投，但 broker 已经换了，于是丢失。
    - ③ delivery 本来就在落库失败时确认掉消息（TT-D9）；生产端在重建窗口里的发送失败也被吞掉（TT-D8）。
  - notification 没有业务生产者，所以重建对邮件链路没有可观测影响。
- 触发设想：带餐负载下 pod-delete rabbitmq。
- 机制专属信号：重建后队列 messages=0，而重建前已有已发布、未消费的消息；消费者重连时间比 broker 就绪晚 ≤5 s（正常）或约 120 s（半开）。
- 运行时要核对：R13、R14、R15。
- 置信度：中。机制确定，但业务影响受限于默认负载不带餐。

### TT-D11 voucher：单线程 Tornado 里做没有超时的阻塞调用，一个慢依赖就冻结全部请求
- 机制族 / 失效模式：deadline_timeout / circuit_isolation；主 D1（T-01 实例），次 D4（异步框架的并发能力被阻塞调用抵消）。
- 位置：ts-voucher-service → order / order-other（K8s DNS）、MySQL。
- 成立条件：
  - E1 成立：server.py:14 是同步的 def post，跑在 :158-164 的单个 IOLoop 线程上。
  - E2 成立：:64-65 的 urlopen 没有超时；:32/:71 每个请求都新建 pymysql 连接。
  - E3 成立：只有 TCP readiness（16101），没有 liveness。
  - E4 不成立：默认负载不走这条路。
- 触发设想：并发调用 /getVoucher，同时给 order-service 注入延迟 d，第 k 个请求约等待 k×d。
- 机制专属信号：请求耗时呈 k×d 阶梯，CPU 接近 0，就绪探针照常通过。
- 业务影响：凭证功能不可用，不影响主链路。
- 运行时要核对：R17。
- 置信度：高。

### TT-D12（存疑）用 GET 暴露的非幂等退款接口，叠加 Ribbon 对 GET 的自动重试，可能重复退款
- 机制族 / 失效模式：retry_backoff；主 D3（手册边界案例「含糊超时后重试非幂等操作」）。
- 位置：cancel / rebook → inside-payment 的 GET drawback。
- 成立条件：
  - E1 成立：退款接口是 GET（InsidePaymentController.java:62-66），每调一次就插一行（:247-251）。
  - E2 存疑：客户端是否带自动重试。RestTemplate 是 @LoadBalanced；nacos-discovery 2.2.7（pom.xml:71-72）在 Hoxton（pom.xml:159-160）下带 Ribbon；如果 spring-retry 经 spring-boot-starter-integration（pom.xml:83）传递进来，Ribbon 默认会对 GET 的 IO 异常再试一次。
  - E3 存疑：没有读超时，只有连接中途被 reset 时才会触发。
- 触发设想：drawback 已提交、响应尚未返回时 kill 掉 inside-payment。
- 机制专属信号：一条 cancel trace 下出现两个 drawback 客户端 span。
- 运行时要核对：R10、R12。
- 置信度：低。

### TT-D13 本范围的共性问题（T-01/T-02/T-05/T-06 实例），以及 Nacos 启动硬依赖（事实 1 的根因）
- 机制族 / 失效模式：replica_disruption / health_probe / deadline_timeout；启动依赖部分为 D6，与 CrashLoopBackOff 退避叠加为 D5。
- 位置：本范围 15 个 Java 服务，以及 voucher。
- 成立条件：
  - E1 成立：全部单副本，没有 PDB。
  - E2 成立：没有 liveness，readiness 只探 TCP（d60/p10/t5/f3）。
  - E3 成立：RestTemplate 都用 `builder.build()`，没有超时。另有一点存疑：如果 Apache HttpClient 在 classpath，Spring Boot 会用 `HttpClients.createSystem()` 作为默认连接池，即每路由 5、总共 10 个连接，借不到连接时无限等待（见 R10）。
  - E4（事实 1 已由主会话查实，这里只补根因）：
    - 配置层：pom.xml:71-72 用 nacos-discovery 2.2.7；各服务启用 @EnableDiscoveryClient（如 CancelApplication.java:23）；yml 只配了 server-addr（如 cancel yml:4-8，来自 configmap nacos），没有 register-enabled、fail-fast 或重试相关配置。
    - 库层（存疑，未离线核对）：SCA 2.2.x 的 NacosServiceRegistry 注册失败就抛出，导致上下文启动失败、进程退出。
    - 恢复时间：没有 startupProbe，kubelet 退避从 10 s 翻倍到 300 s 封顶。Nacos 恢复后，服务要等下一次退避到期才重启，再加上 JVM 启动和 60 s 的就绪初始延迟，最坏约 6–7 分钟才回来。
    - voucher 不依赖 Nacos（server.py:47-48），不受影响。
  - E5 成立：OTel agent 从 NFS 卷 1.94.151.57:/data/share 挂载，Pod 重建依赖这台 NFS 可达（D6）。
  - E6 成立：取消路径存在 T-02。客户端 10 s 放弃，服务端继续执行，改单和退款在客户端失败后才落地。
- 触发设想：pod-kill ts-cancel-service；或让 Nacos 全停后重启任一业务 Pod。
- 机制专属信号：Pod 的 Ready 时间比 Nacos 恢复时间晚，而且差值呈 10/20/40…300 s 的退避台阶。
- 运行时要核对：R10、R18、R19。
- 置信度：配置层高；库行为中。

### TT-D14 admin-order 无分页地全量拉取两张订单表，而订单只增不删
- 机制族 / 失效模式：load_shedding_admission；主 D1，次 D5（与 order-service 的 -Xmx200m 小堆、仅 TCP 就绪组合）。
- 位置：admin-order → order / order-other。
- 成立条件：
  - E1 成立：AdminOrderServiceImpl.java:47-53、:65-71 调用 OrderServiceImpl.java:302-311 的 findAll。
  - E2 成立：取消只改状态、不删订单，默认负载约 1,080 单/小时。
  - E3 成立：降级只处理 status≠1（:56-62、:74-80）。
  - E4 存疑：数据规模是否足以打到 OOM。
- 触发设想：长时间负载后调用 admin 的订单列表。
- 机制专属信号：只有被选中的那一个 order 副本出现 GC 暴涨。
- 业务影响：非关键的管理查询可能拖垮关键服务的副本，order-service 三副本时约 1/3 请求受影响。
- 运行时要核对：R8、R11。
- 置信度：低。

## 排查过但不成立、或业务流量触发不到

- **wait-order 轮询不成立。** PollThread.java:49 的到期判断写反了：waitUntil 是「现在 + 24 小时」（WaitListOrder.java:55-58），所以首轮就走「过期」分支退出。此外：
  - :76 调用的路径 `/api/v1/contactservice/preserve` 与 preserve 实际路径不符（PreserveController.java:18/:32）；
  - :51/:64 把 accountId 当成候补单 id 去查（WaitListOrderServiceImpl.java:116-118），状态从不更新；
  - WaitListOrderServiceImpl.java:140 的 `BeanUtils.copyProperties` 参数方向反了。
  - 线程无异常保护、只有内存态、每单一线程、捕获的 JWT 会过期，这些问题在代码里都有，但上游代码下永远不会真正开始轮询，不建议据此建场景。
- **notification 消费端的热循环触发不到。** 它先发邮件、后落库，落库异常时立即重新入队且没有退避，会造成热循环和重复邮件，这是真实代码缺陷。但 email 队列没有业务生产者：preserve、preserve-other、cancel 的发送都已注释（:261、:260、:87）。唯一的自测接口发的是字符串 "test"，在 :53-58 解析为 null 后直接丢弃，走不到落库。SMTP 调用没有超时（yml:12-25），同样没有业务调用。
- **只是安全问题，不计入韧性：** ts-payment-service 被网关直接暴露；order 的 `GET /order/status/{id}/{status}` 是 permitAll（SecurityConfig.java:80）。
- **功能缺陷，会影响场景设计：** 退款时间判断里 `new Date(year,…)` 的年份多加了 1900（CancelServiceImpl.java:216-221），所以永远按 80% 退款。

## 保护有效的点（可作负控制）

1. **坏 JSON 不会让消费端死循环。** JsonUtils.java:58-70 解析失败时返回 null，两个消费端（delivery :37-42、notification :53-58）直接返回并确认。代价是没有死信队列、静默丢弃。
2. **rabbitmq 重建后消费者会自动恢复**（库默认值，见 TT-D10），可作 N-04 / T-07 的负控制。
3. **顺序重试不会重复退款。** 取消先写入已取消（:57），之后的重试会被 :52-53 挡住。
4. **顺序重复的站外扣款会被挡。** PaymentServiceImpl.java:35（副作用见 TT-D4）。
5. **改签成功后不能再改。** RebookServiceImpl.java:69-71。
6. **餐食的逻辑失败不会导致下单失败。** PreserveServiceImpl.java:207-212。
7. **网关没有 Retry 过滤器**，入口不会复制请求。
8. **默认负载不重试、10 s 超时**（generator:584-585），所以默认负载下不会自发产生 TT-D5 的重复请求。
9. **OTel 应该是异步批量导出**（env 只设了 exporter 和 endpoint），N-01 预期不成立，由 R19 确认。
10. **Nacos 全停时 voucher 仍能正常启动。**

## 运行时核对清单汇总

**取消、退款与订单对账**
- **R1 取消掩盖：** 注入期间直接请求网关的 GET /api/v1/cancelservice/cancel/{orderId}/{userId}（带 token），看响应 msg 是否为 "error"。在 ts-cancel-service 日志里 grep `I/O error on`、`No instances available`、`Connection refused`。在 Jaeger 中筛选 ts-cancel-service 根 span 为 http 200、但有子 span 标记 error 的 trace。
- **R2 负载结果：** /results/train-ticket*.jtl 里 label=cleanup-order 的成功率，与同一时段的订单状态对照。
- **R3 订单与退款对账（只读 SQL）：**
  - `SELECT status,COUNT(*) FROM orders WHERE account_id='<负载 userId>' GROUP BY status`，orders_other 同样查一遍。
  - `SELECT type,COUNT(*),SUM(CAST(money AS DECIMAL(12,2))) FROM inside_money WHERE user_id='<userId>' GROUP BY type`。
  - 已付且已取消的订单：`SELECT SUM(CAST(o.price AS DECIMAL(12,2)))*0.8 FROM orders o JOIN <inside库>.inside_payment p ON p.order_id=o.id WHERE o.status=4`，与 D 类合计比较。
  - inside_money 没有时间列，测试前后各取一次计数再做差。
- **R4 支付一致性：**
  - payment 库：`SELECT order_id,COUNT(*) FROM payment GROUP BY order_id HAVING COUNT(*)>1`。
  - `SELECT order_id,type,COUNT(*) FROM inside_payment GROUP BY order_id,type HAVING COUNT(*)>1`。
  - 已记账但未支付：orders 与 inside_payment 连接，条件 status=0。
  - 已支付但无记账：orders 左连接 inside_payment，条件 status IN (1,2,3,6) 且 p.id IS NULL。
- **R5 9 个遗留单的成因：** 按旧环境修复记录里的单号，在 Jaeger/Loki 查有没有对应的 cancel 请求。有、且 cancel 日志有异常 → TT-D1；没有 → 负载在 preserve 与 cancel 之间中断。同时查这些单的状态：状态为 0 说明没有资金差异。
- **R6 改签：** rebook 日志 grep `405`、`Method Not Allowed`、`NullPointerException`、`Can't update Order`；看 D 类行数随改签次数怎么变化。
- **R7 inside_money 规模与索引：** `SELECT user_id,COUNT(*) FROM inside_money GROUP BY user_id ORDER BY 2 DESC LIMIT 5`；`SHOW INDEX FROM inside_money` 和 `SHOW INDEX FROM inside_payment`；再看 drawback span 时延随时间的趋势。
- **R8 订单规模：** orders 与 orders_other 的 COUNT(*)；tsdb-mysql 的 1Gi PVC 占用（在 mysql 容器里 `du -sh /var/lib/mysql`）。
- **R9 目标账户余额：** Σinside_money − Σinside_payment，按 user_id 计算。

**镜像、依赖与 JVM**
- **R10 镜像与 classpath：**
  - 用 `kubectl cp` 取出 /app/*.jar，`unzip -l` 后 grep `spring-retry|ribbon|httpclient-4|nacos-client`（java:8-jre 镜像多半没有 unzip）。
  - 用 javap 核对 1.0.2 / 1.0.1 镜像里的 PaymentServiceImpl.pay、OrderServiceImpl.modifyOrder / updateOrder，以及删除接口映射是否与上游一致。
  - `SHOW CREATE TABLE payment`，看 order_id 有没有唯一键。
- **R11 JVM：** `cat /proc/1/cmdline`，确认有 -Xmx200m、没有 ExitOnOutOfMemoryError；在 Prometheus 里看 inside-payment 与 order-service 的 OTel JVM 内存指标（jvm_memory 或 process_runtime_jvm 前缀，取决于 agent 版本）。
- **R12 重复请求来源：** 同一订单号有几条 cancel/pay trace；同一父 span 下是否出现两个同 URL 的客户端 span。

**消息链路**
- **R13 队列与连接：** `kubectl exec deploy/rabbitmq -- rabbitmqctl list_queues name durable messages_ready messages_unacknowledged consumers`，以及 `list_consumers`、`list_connections name peer_host state`、`rabbitmqctl version`、`rabbitmq-plugins list -e`（Service 只暴露 5672）。
- **R14 资源与告警：** `rabbitmq-diagnostics status` 里的 Memory high watermark 与 Total memory；`rabbitmq-diagnostics check_local_alarms`；确认 Pod 没有 volumes、没有 memory limit。
- **R15 生产/消费端配置：** food 和 delivery 的 `env | grep -iE 'rabbit|SPRING_'`，确认没有覆盖 confirm 或 ack 的配置。日志 grep `send delivery info to mq error`、`Save delivery object into database failed`、`Consumer raised exception`、`Restarting Consumer`。
- **R16 配送对账：** 测试前后各取 food_order 与 delivery 的 COUNT(*) 做差。delivery.order_id 是 Hibernate 的 UUID 二进制列，按单号比对时需要 HEX() 转换。
- **R20 kube-proxy 模式：** 查 `kube-system/kube-proxy` 这个 configmap 的 mode，决定 rabbitmq 没有端点时是拒连还是挂住。

**其他**
- **R17 voucher：** `env | grep -E 'ORDER_SERVICE_URL|ORDER_OTHER_SERVICE_URL|VOUCHER_MYSQL'`；tornado 与 pymysql 的版本（requirements.txt 没有锁版本）。
- **R18 Nacos 启动：** 业务 Pod 的 restartCount 和 lastState.terminated 时间，与 Nacos 恢复时间对比，看是否有退避台阶；确认异常栈里抛出点是 NacosServiceRegistry.register。
- **R19 NFS 与 OTel agent：** 新环境的 Pod 事件里有没有 NFS（1.94.151.57）挂载失败；/opt/opentelemetry-javaagent 下 jar 的版本；有没有同步导出或 otel.bsp.* 相关配置。