sock-shop 的只读排查做完了。共列出 23 条候选缺陷，其中 14 条是 D2–D6；主会话补充的 5 条运行时事实都已在相关条目里引用并补上代码或配置层面的根因。全程没有修改任何文件，也没有访问集群。凡是只能靠库默认行为、镜像内实际版本或运行时状态才能确认的，都标成"存疑"，并写明要查什么。

**5 条补充事实放在哪里：**
- **修复记录**：session-db 快照失败的配置层根因写进 SS-09 的 E6；这次修补把"写不进"换成了"重启即清空"，后果就是 SS-01。Mongo 驱动协议问题见 SS-17，共享购物车超支付限额的代码根因见 SS-22。
- **重名注册回 500**：危害评估见 SS-14，与唯一索引的连锁问题见 SS-10；安全问题放在文末附注。
- **user 启动每约 6 秒重试、探针延迟 180/300 秒**：根因与探针判定是否反映依赖状态，见 SS-04。
- **ZIPKIN**：N-01 不成立，详见负控制第 2 条。
- **下单时取地址/卡**：客户没有地址或卡时不会崩（返回 `[]`，前端守卫生效，orders 以 406 拒单）；真正会崩的是"有地址/卡但属性查询失败"那一支，见 SS-03 的 E2、E3。

**路径缩写**（B=`/Users/mymz/work/国家重点研发/韧性测试工具 benchmark`）：
- FE=`B/benchmark-sources/materialized/sock-shop-front-end-0.3.12`
- CAT=`B/benchmark-sources/materialized/sock-shop-catalogue-0.3.5`
- PAY=`B/benchmark-sources/materialized/sock-shop-payment-0.4.3`
- USR=`B/benchmark-sources/materialized/sock-shop-user-0.4.7`
- ORDJ=`B/benchmark-sources/materialized/sock-shop-orders-0.4.7/src/main/java/works/weave/socks/orders`
- CARTJ=`B/benchmark-sources/materialized/sock-shop-carts-0.4.8/src/main/java/works/weave/socks/cart`
- SHPJ=`B/benchmark-sources/materialized/sock-shop-shipping-0.4.8/src/main/java/works/weave/socks/shipping`
- QMJ=`B/benchmark-sources/materialized/sock-shop-queue-master-0.3.1/src/main/java/works/weave/socks/queuemaster`
- DEP=`B/multisystem-audit-20260918/manifests/sock-shop/deployments.json`
- LOC=`B/resiliencebenchmark-stage2-d0-integration/environment/workloads/sock-shop/locustfile.py`
- REP=`B/resiliencebenchmark-stage2-d0-integration/environment/repairs/sock-shop-workload-dependency-compatibility-20260822.yaml`
- PROF=`B/resiliencebenchmark-stage2-d0-integration/environment/applications/sock-shop.yaml`

**压测量级基准**：5 个闭环用户，每人每秒 1 个流程（`LOC:32`），合计约 5 流程/秒。其中 `POST /cart` 约 1.5 次/秒（加购 15%，加上结账前那次加购 15%），`POST /orders` 约 0.75 次/秒。

---

### SS-01 session-db 一旦重建，仍持 `logged_in` cookie 的会话会被当成 customerId=undefined：购物车串单，结账让 front-end 进入崩溃循环，故障消失后也不恢复
- **机制族 / 失效模式**：fallback_degradation（会话丢失后的降级）＋ replica_disruption（会话无持久化）；primary D2——登录态校验只看 cookie，没覆盖"服务端会话已丢、cookie 仍有效"这个边界；secondary D5——无持久化、崩溃重启退避、客户端残留状态三者叠加，形成一种自己维持下去的失效。
- **位置**：front-end ↔ session-db；front-end → carts（`/carts/undefined/…`）；front-end → user（`/customers/undefined`）。
- **成立条件**：
  - E1 成立：session-db 关闭了全部持久化，也没有卷。`DEP session-db.containers[0].args=[redis-server,--save,"",--appendonly,no]`，volumes 为空。这个参数是旧环境修复时加的（主会话已查实，`REP:21-28`），所以 session-db 一重启，全部会话就清空。
  - E2 成立：登录态只看 cookie。`FE/helpers/index.js:86-104` 在有 `logged_in` 时直接返回 `req.session.customerId`；`FE/api/orders/index.js:50-56` 同样只查 cookie。cookie 有效期 1 小时（`FE/api/user/index.js:305-306`）。
  - E3 成立：旧 sid 在存储里查不到时，express-session 会生成新会话（`saveUninitialized:true`，`FE/config.js:15-21`，库行为），此时 customerId 为 undefined，拼出的地址是 `carts/undefined/items`（`FE/api/cart/index.js:14-16,26-29,73,84`）。carts 遇到不存在的 customerId 会现场建车（`CARTJ/cart/CartResource.java:24,30-32`），于是所有失效会话共用一辆 "undefined" 购物车，看车/加购仍回 200/201。
  - E4 成立：结账时去 `user/customers/undefined` 取客户（`FE/api/orders/index.js:60`），user 对非法 ID 回 500 JSON（`USR/db/mongodb/mongodb.go:215-217`，`USR/api/transport.go:102-115`）。前端的 500 守卫失效（见 SS-03 E1），第 67 行 `jsonBody._links.customer.href` 在 request 回调里抛 TypeError；front-end 没有 `uncaughtException` 处理，Node 进程直接退出。
  - E5 成立：压测只在 `on_start` 登录一次（`LOC:34-54`），之后从不重新登录。
- **触发设想**：删 session-db Pod；或它作为 BestEffort 被 OOM 杀掉、被驱逐。session-db 恢复后，约 1–2 秒内的第一次结账就会让 front-end 崩溃。front-end 重启后有 30 秒就绪延迟（`DEP front-end.readinessProbe.initialDelaySeconds=30`），一就绪又会在 1–2 秒内被结账打崩，重启退避按 10→20→40…→300 秒递增。只有 cookie 到期（登录后 3600 秒）或压测重启才会结束，在 10–20 分钟的试验窗口里不会自己恢复。
- **机制专属信号**：front-end `lastState.terminated.exitCode=1`（不是 OOMKilled），报错栈为 `TypeError: Cannot read property 'customer' of undefined`，指向 `api/orders/index.js:67`；user 日志出现 `/customers/undefined` 和 `Invalid Id Hex`；carts-db 里出现 `customerId:"undefined"` 的购物车。据此可与 SS-02（栈在 cart/index.js:79）、SS-03（custId 是合法 ObjectId）区分。
- **业务影响**：全站中断（浏览随进程一起挂），且恢复后回不来；多用户场景下购物车串单。违反 success-rate 和 throughput-ratio 两项 SLO。
- **运行时要核对**：session-db 重启前后的 `DBSIZE` 及 `CONFIG GET save/appendonly`；front-end 的 restartCount、lastState 和关键字 `'customer' of undefined`；user 日志中的 `customers/undefined`；carts-db 执行 `db.cart.count({customerId:"undefined"})`；压测 `/orders [checkout]` 是否一直失败到试验结束。
- **置信度**：高。每一环都有代码或配置证据，只剩 express-session 的实际版本待核（该行为在 1.x 中一致）。

### SS-02 catalogue 不可达时，加购回调先执行 `JSON.parse(undefined)` 再判错，导致整个 front-end 进程崩溃；叠加 catalogue 180 秒就绪延迟和重启退避，一次 catalogue 重启会放大成 3–7 分钟的全站中断
- **机制族 / 失效模式**：circuit_isolation（进程级故障隔离）＋ fallback_degradation；primary D4——错误传递的写法本身错了；secondary D5——与就绪延迟、重启退避叠加。
- **位置**：front-end → catalogue（`POST /cart` 和 `POST /cart/update` 都要先查价格）。
- **成立条件**：
  - E1 成立：`FE/api/cart/index.js:77-80` 和 `:125-128` 都写成 `callback(error, JSON.parse(body))`。请求出错时 body 为 undefined，JSON.parse 在把 error 交出去之前就抛异常；异常发生在 request 库的回调里，不经过 Express 的错误处理，进程直接退出。
  - E2 成立（对照）：同一代码库的 `/catalogue/images*` 挂了 error 监听（`FE/api/catalogue/index.js:12-14`），加购路径却没有。
  - E3 成立：catalogue 重启后就绪延迟 180 秒（`DEP catalogue.readinessProbe.initialDelaySeconds=180`），单副本，所以 Service 约 180 秒没有端点；front-end 自身就绪延迟 30 秒。
  - E4 存疑：Service 没有端点时，连接是立即被拒（kube-proxy iptables 模式）还是被丢包挂起（部分 IPVS/eBPF 实现）？前者立刻崩，后者约 127 秒后超时再崩。DNS 解析失败（ENOTFOUND）同样会触发。
- **触发设想**：删 catalogue Pod，或对 front-end 注入 DNS 故障。`POST /cart` 约 1.5 次/秒，front-end 每次就绪后不到 1 秒就会崩。按退避 10/20/40/80 秒加 30 秒就绪延迟推算，catalogue 在约 180 秒恢复后，front-end 要到约 190–430 秒之间才回来（取决于退避相位）。
- **机制专属信号**：`SyntaxError: Unexpected token u`，栈指向 `api/cart/index.js:79`；catalogue 的 endpoints 为空；front-end 出现事件 `Back-off restarting failed container`。
- **业务影响**：本应只有加购失败，实际浏览、看车、登录、结账全部中断；违反 success-rate、p95、throughput。
- **运行时要核对**：删 catalogue Pod，记录 catalogue 的 Ready 时刻、front-end 每次崩溃的时间戳、全站恢复时刻；确认 kube-proxy 模式；front-end 内执行 `node -v`。
- **置信度**：高。代码行为确定，影响量级取决于 E4。

### SS-03 结账路径的错误守卫写错或漏了："user 回 500 JSON"和"有地址/卡但属性查询失败时回 200 却缺 `_links`"两种情况，都会让 front-end 在回调里崩溃（含第 5 点的判定）
- **机制族 / 失效模式**：fallback_degradation；primary D4——守卫实现错误；secondary D2——守卫没覆盖"返回 200 但数据残缺"的情况。
- **位置**：front-end `POST /orders` → user（customers/{id}、addresses、cards）；front-end `GET /orders` 和 `GET /orders/*` → orders。
- **成立条件**：
  - E1 成立：`FE/api/orders/index.js:61` 的 `body.status_code === 500` 判断的是还没解析的字符串，永远为 false。user 除鉴权外的所有错误都回 500 JSON（`USR/api/transport.go:102-115`），于是第 66–67 行 `jsonBody._links.customer.href` 抛 TypeError。对照：`FE/api/user/index.js:75-76,98-99` 是先 parse 再判，写法正确。
  - E2 成立（第 5 点：没有地址/卡时不会崩）：`AddUserIDs` 和 `GetUserAttributes` 都保证切片非 nil（`USR/db/mongodb/mongodb.go:68-84,242-286`），序列化结果是 `"address":[]`。第 90、105 行的 `!=null` 守卫会短路，`order.address/card` 保持 null，orders 以 406 拒单（`ORDJ/controllers/OrdersController.java:56-57`）。
  - E3 成立（第 5 点真正会崩的分支）：`db.GetUserAttributes` 只在成功时给地址/卡补 `_links`（`USR/db/db.go:107-119`），端点却忽略它的错误、照常回 200（`USR/api/endpoints.go:101-107`），返回的是 `[{"id":…,"_links":null}]`。前端第 91、106 行 `._links.self.href` 因此抛 `Cannot read property 'self' of null`。响应是 200，所以 `status_code !== 500` 守卫拦不住。
  - E4 成立：`GET /orders` 在 orders 回错误 JSON 时，第 31 行 `JSON.parse(body)._embedded.customerOrders` 抛异常；`GET /orders/*` 用 `request.get(url).pipe(res)`，没挂 error 监听（第 45 行），orders 不可达就崩。
  - E5 成立：会话存储断开时 `req.session` 不存在，登录/注册回调里 `req.session.customerId = …`（`FE/api/user/index.js:270,205`）会抛异常。
- **触发设想**：
  - user-db 不可达（命中 E1）：user 在被探针摘除前的约 6–9 秒内仍接流量，GetUser 等满 mgo 的 5 秒超时后回 500，结账（0.75 次/秒）随即把 front-end 打崩。
  - user-db 有 30–50% 丢包，或刚重启、连接池里还有死 socket（命中 E3）：会出现"第一个查询成功、第二个查询失败"的组合。
- **机制专属信号**：报错栈指向 `:67`（E1）或 `:91`/`:106`（E3）；user 日志出现 `no reachable servers`、`i/o timeout` 或 `EOF`；addresses 接口的 200 响应体里出现 `"_links":null`。
- **业务影响**：一次 user-db 抖动就打掉整个 front-end 进程，全站中断。
- **运行时要核对**：对 user-db 分别做 kill、6 秒延迟、40% 丢包，看 front-end 日志关键字和 restartCount；抓取 addresses/cards 的响应体。
- **置信度**：高。E3 的触发窗口需要实测。

### SS-04 catalogue、user 的存活/就绪探针在处理函数里同步探测远程数据库：数据库中断约 9 秒就触发重启，重启后又被初始化循环和 180 秒就绪延迟拖成至少 3 分钟不可用（含第 3 点）
- **机制族 / 失效模式**：health_probe（liveness＋readiness＋app_healthcheck）；primary D6——正是 codebook 的边界案例"liveness handler 同步请求远程数据库"；secondary D4（探针超时 1 秒对驱动超时 5 秒；用固定 180 秒延迟代替 startupProbe）和 D5。
- **位置**：kubelet → user `/health` → user-db；kubelet → catalogue `/health` → catalogue-db。
- **成立条件**：
  - E1 成立：user 的 `/health` 同步调用 `db.Ping()`（`USR/api/service.go:136-152` → `mongodb.go:461-465`）。会话由 `DialWithTimeout(…,5s)` 建立（`mongodb.go:42`），找不到可达服务器时要等满 5 秒；探针配置为 `timeoutSeconds=1, periodSeconds=3, failureThreshold=3`（`DEP user`，路径 `/health`）。结果是 user-db 不可达约 6–9 秒，user 就会被摘除并重启。
  - E2 成立：两个服务的 `/health` 都恒回 HTTP 200，依赖状态只写在响应体里（`USR/api/transport.go:196`，`CAT/transport.go:179-187`）。也就是说，探针实际判断的是"1 秒内有没有返回"。
  - E3 成立：catalogue 的 `Health()` 同步 Ping（`CAT/service.go:163-179`），DSN 里没有任何超时参数（`CAT/cmd/cataloguesvc/main.go:46`）。数据库快速拒绝连接时，Ping 立刻返回，体里写 "err"，HTTP 仍是 200，探针恒绿；数据库慢或被黑洞时，Ping 阻塞、探针超时、catalogue 被杀。同一个端点对两类故障给出相反的结论。
  - E4 成立（第 3 点的根因）：`USR/main.go:99-110` 的 `for !dbconn { db.Init() }` 里没有 sleep，每一轮被 `DialWithTimeout` 的 5 秒卡住，所以日志大约每 6 秒一条 `no reachable servers`。HTTP 监听要等循环结束才启动（`main.go:154-157`）；探针延迟 180/300 秒，且没有 startupProbe。因此 user 重启后，即使数据库早已恢复，也要至少 180 秒才就绪；数据库停机超过约 309 秒时，liveness 会再杀一次并进入退避。
  - 探针判定汇总：payment 的 `/health` 不查任何依赖（`PAY/service.go:62-67`）；front-end 的探针打的是静态页（见 SS-05 E4）；四个 Java 服务没有探针（见 SS-18）。
- **触发设想**：user-db 黑洞 30 秒，或注入让 Ping 超过 1 秒的延迟；catalogue-db 延迟 ≥1 秒。只要故障持续 ≥9 秒，user 就会重启，登录和结账中断约 9＋180≈190 秒——10 秒的数据库抖动变成约 3 分钟中断。catalogue 同理，还会经 SS-02 放大成全站中断。
- **机制专属信号**：事件 `Liveness probe failed: … Client.Timeout exceeded`；restartCount 增加；恢复时刻约等于"重启时刻＋180 秒"，而不是数据库恢复时刻。删 catalogue-db Pod（快速失败）时，catalogue 反而保持 Ready，体里显示 `catalogue-db: err`。
- **业务影响**：登录、结账（user）；浏览、加购（catalogue）；恢复滞后至少 3 分钟。
- **运行时要核对**：user Pod 的探针事件；给 user-db 注入 2 秒延迟 60 秒，记录 user 的 Ready 恢复时刻；user-db 不可达时 `curl -w '%{time_total}' http://user/health` 应约为 5 秒。
- **置信度**：高。

### SS-05 session-db 挂起（连接没断）时，除静态文件外的全站请求都会挂住；会话降级只在"连接断开"时才生效，而 front-end 的探针打的是静态页，始终为绿
- **机制族 / 失效模式**：fallback_degradation ＋ health_probe(readiness)；primary D2；secondary D4——探针检查的不是真实服务路径。
- **位置**：front-end 的全部 API 路由 → session-db。
- **成立条件**：
  - E1 成立：会话中间件挂在所有 API 路由之前（`FE/server.js:22-29` 早于 `:48-51`），连不需要会话的浏览请求也要读写会话；`saveUninitialized:true`（`FE/config.js:15-21`）要求新会话在响应结束前写入存储。
  - E2 存疑：express-session 1.14.2（`FE/yarn.lock:367-368`）只在存储发出"断开"事件时跳过会话；连接还在但命令没回应时，回调一直不返回。connect-redis/redis 不在 yarn.lock 里（`FE/package.json:31` 为 `^3.2.0`），node_redis 默认没有命令超时。
  - E3 成立：Node 4（`FE/Dockerfile:1`）默认 120 秒后销毁客户端连接，但挂着的 redis 命令不会被中止。
  - E4 成立：探针路径 `/` 由 `express.static` 在会话中间件之前直接返回（`FE/server.js:21`），所以挂起期间 Pod 一直 Ready，也不会被重启。
- **触发设想**：对 session-db 注入 100% 丢包或黑洞，或暂停 redis-server 进程。所有非静态请求挂满 120 秒，5 个用户全部卡住，throughput 接近 0，而 `GET /` 一直返回 200。
- **机制专属信号**：`GET /` 正常、`GET /catalogue` 挂起；front-end 不崩溃也不重启；故障解除后自行恢复，没有数据丢失（这点区别于 SS-01）。
- **业务影响**：全站，包括本不需要会话的浏览；违反 p95 和 throughput。
- **运行时要核对**：front-end 镜像里 `node_modules/{express-session,connect-redis,redis,request}/package.json` 的版本；挂起期间 `curl -m 5 front-end/catalogue` 超时而 `curl front-end/` 正常。
- **置信度**：中。E2 依赖库版本。

### SS-06 启动只需不到一秒的 Go 服务配了 180 秒固定就绪延迟、又没有 startupProbe：payment、catalogue、user 任何一次重启，都意味着该服务至少 3 分钟完全不可用
- **机制族 / 失效模式**：health_probe(readiness)；D4。
- **位置**：payment、catalogue、user 的 readinessProbe。
- **成立条件**：
  - E1 成立：`DEP payment/catalogue/user` 的 readiness initialDelaySeconds=180、liveness=300，没有 startupProbe；这是照搬上游的（`B/benchmark-sources/sock-shop-deployment/deploy/kubernetes/complete-demo.yaml:183,494,810`）。
  - E2 成立：payment 和 catalogue 启动时不做阻塞等待（`PAY/cmd/paymentsvc/main.go:66-71`；`CAT/cmd/cataloguesvc/main.go:105-109` 连不上数据库也只记日志），不到一秒就能服务。
  - E3 成立：全部单副本。
- **触发设想**：删 payment Pod 后，orders 调 payment 连接被拒，结账 500 持续至少 180 秒，约 0.75×180≈135 次失败。catalogue 同理，还会触发 SS-02。
- **机制专属信号**：Pod 已 Running、进程日志已出现 `transport=HTTP port=80`，但 endpoints 为空；Ready 时刻减去容器启动时刻约 180 秒。和 SS-04 的区别是：没有数据库故障，也没有 liveness 失败。
- **业务影响**：结账、浏览/加购、登录。
- **运行时要核对**：`containerStatuses[0].state.running.startedAt` 与 Ready 条件时间之差；orders 日志中的 `Connection refused`。
- **置信度**：高。

### SS-07 RabbitMQ 不可用时，shipping 吞掉发布异常仍回 201；既没有发布确认，队列也不持久，Broker 还没有卷——订单显示成功，发货消息却静默丢失（N-02 实例）
- **机制族 / 失效模式**：fallback_degradation ＋ idempotency_compensation；primary D3——"照单全收"这个降级动作本身造成了丢失；secondary D1。
- **位置**：orders → shipping → rabbitmq → queue-master。
- **成立条件**：
  - E1 成立：`SHPJ/controllers/ShippingController.java:42-48` 捕获所有异常，打印 "Accepting anyway" 后照常返回（201）。
  - E2 成立：shipping 和 queue-master 源码里都没有 publisher confirm、mandatory、return 回调或死信配置（grep 为空）；队列以 `new Queue(queueName,false)` 声明，非持久（`SHPJ/configuration/RabbitMqConfiguration.java:52`，`QMJ/configuration/RabbitMqConfiguration.java:54`，`QMJ/configuration/ShippingConsumerConfiguration.java:30`）。
  - E3 成立：rabbitmq 没有卷、没有探针、没有资源限额。
  - E4 成立：orders 拿到 201 就落库并回成功（`ORDJ/controllers/OrdersController.java:100-120`）。
- **触发设想**：删 rabbitmq Pod。新容器开始监听 5672 之前（没有 readiness，端点已加入），shipping 连接被拒，异常被吞，回 201。按 Broker 重启 5–15 秒、0.75 单/秒估算，约 4–11 单没有发货，队列里还没消费的消息全部丢失。若是黑洞：shipping 的连接超时是 5 秒（`SHPJ/configuration/RabbitMqConfiguration.java:27`），正好等于 orders 的等待时间，常见结果是 orders 先回 500，shipping 随后仍回 201。
- **机制专属信号**：shipping 日志 `Accepting anyway`；orders-db 新增订单数多于 `shipping-task` 的发布数。
- **业务影响**：已付款未发货（正确性问题），现有四项 SLO 都看不到。
- **运行时要核对**：删 rabbitmq Pod 期间下单，对账订单增量与发布计数；确认 rabbitmq 实际版本。
- **置信度**：高。

### SS-08 orders 的 5 秒超时只放弃等待、不取消调用，底层 RestTemplate 也没有连接/读超时：下游慢于 5 秒时，失败的订单照样发货；下游挂起时，线程随故障时长线性堆积
- **机制族 / 失效模式**：cancellation；primary D2——codebook 边界案例"调用方有超时，但下游不接收取消"；secondary D1。
- **位置**：orders → user / carts / payment / shipping（`@Async` 配合 `Future.get`）。
- **成立条件**：
  - E1 成立：`http.timeout` 默认为 5（`OrdersController.java:46-47`），各阶段用 `Future.get(timeout)` 等待（`:76-112`）；超时只抛异常（`:121-122`），没有调用 `cancel(true)`。
  - E2 成立：`new RestTemplate()` 使用默认工厂（`ORDJ/config/RestProxyTemplate.java:24`），JAVA_OPTS 里也没有 `sun.net.client.default*Timeout`。
  - E3 成立：开了 `@EnableAsync`（`ORDJ/OrderApplication.java:8`），工程里却没有 TaskExecutor bean，于是用 Spring 默认的 SimpleAsyncTaskExecutor——每次调用新建一个线程，没有上限；每单 6 次异步调用（`ORDJ/services/AsyncGetService.java:54-92`）。
  - E4 成立：执行顺序是付款 → 发货 → 落库（`:85-117`）。
- **触发设想**：
  - 对 shipping 注入 6–10 秒延迟：orders 在 5 秒时回 500，但发货请求仍在后台完成并入队，每分钟约 30–45 个"失败订单的发货"。
  - 对 payment 或 shipping 注入黑洞：每单泄漏 1 个永久阻塞的线程，10 分钟约 300–450 个。user 黑洞不算在内——它会先卡在 front-end，请求到不了 orders。
- **机制专属信号**：orders 日志 `Unable to create order due to timeout`，同一时刻 shipping 有 `Adding shipment to queue`；`SimpleAsyncTaskExecutor-N` 线程数持续增长，栈停在 `socketRead0`。
- **业务影响**：幽灵发货；orders 的线程与原生内存增长（接 SS-19）。
- **运行时要核对**：shipping 延迟实验中对账；orders 容器 `/proc/1/status` 里 Threads 的变化曲线。
- **置信度**：高。

### SS-09 有状态组件都没有持久卷，且都是 BestEffort；压测账号的地址和卡是运行期绑定的，user-db 一重建，结账就可能永久失败（引用修复记录，补 session-db 快照失败的配置层根因）
- **机制族 / 失效模式**：replica_disruption（T-10）＋ resource_limit；primary D1，secondary D2——资源治理只覆盖了无状态层。session-db 的历史形态为 D3。
- **位置**：carts-db、orders-db、user-db、catalogue-db、session-db、rabbitmq。
- **成立条件**：
  - E1 成立：唯一的 PVC 是压测结果卷（`B/multisystem-audit-20260918/manifests/sock-shop/persistentvolumeclaims.json`）。各库数据都落在镜像声明的匿名卷里，容器或 Pod 一重建就回到镜像初始状态：user-db 的种子数据是构建时烤进 `/data/db-users` 的（`USR/docker/user-db/Dockerfile:4-17`），catalogue-db 靠初始化脚本（`CAT/docker/catalogue-db/Dockerfile:7`）。
  - E2 成立：这六个组件的 `resources={}`，都是 BestEffort，节点压力下最先被驱逐、OOM 时最先被杀；也没有 ephemeral-storage 限额。
  - E3 成立（主会话已查实）：压测账号的地址和卡是在 Redis 恢复后重新绑定的（`REP:37-38,51-52`），数据就在 user-db 的匿名卷里。
  - E4 存疑：压测账号是种子账号（Eve_Berger/user/user1，`_id` 固定）还是运行期注册的？
    - 若是种子账号：重建后回到种子里的地址和卡，结账可以继续。
    - 若是运行期注册：账号直接消失。已登录的会话取 `/customers/<id>` 得到 500，走进 SS-03 E1 的崩溃循环；下一次压测启动时登录 401，整轮结账失败。
  - E5 成立：地址/卡丢失本身不会让 front-end 崩溃，而是 orders 回 406。
  - E6（session-db，主会话已查实的历史故障，这里补根因）：旧环境里快照写盘失败后，会话写不进去（`REP:8-10`）。这是 Redis 默认 `stop-writes-on-bgsave-error yes`——快照失败就拒绝所有写入，属于 D3。配置层可能的根因（存疑）：`DEP session-db.securityContext` 设置了 `readOnlyRootFilesystem:true`、drop all、只加回 CHOWN/SETGID/SETUID，又没有给 `/data` 挂任何卷，完全依赖镜像的 VOLUME 声明；上游用的是浮动标签 `redis:alpine`（complete-demo.yaml:657），现在已是新版 Redis、默认开快照。具体可能是：(a) 运行时没给镜像 VOLUME 建可写挂载（报 EROFS）；(b) `/data` 属主不对，又缺 DAC_OVERRIDE（报 EACCES）；(c) fork 失败。现在的修补（`REP:21-28`）让 D3 不再触发，但把问题换成了"重启即清空"（D1），后果就是 SS-01。
- **触发设想**：删 user-db Pod；节点内存压力导致数据库被先驱逐（再叠加 SS-01）；如果有人按上游清单去掉 session-db 的参数，写入量到默认快照阈值后就会报 MISCONF，登录全部失败。
- **机制专属信号**：user-db 重建后压测账号的文档不存在，或 addresses/cards 变回种子值；orders 406 `Invalid order request`；Pod 的 qosClass=BestEffort。session-db 的旧形态会在日志里出现 `Failed opening the temp RDB file`，或 `Can't save in background: fork`，客户端报 `MISCONF`。
- **业务影响**：结账可能在故障解除后持续失败；购物车、订单、会话、队列都会随重建丢失。
- **运行时要核对**：
  - secret `sock-shop-workload-user` 的 username（只读这一个键）是否为种子账号。
  - `crictl inspect` 查看 `/data/db`、`/data/db-users`、`/var/lib/mysql`、`/var/lib/rabbitmq` 和 redis `/data` 的挂载来源。
  - 在隔离命名空间用同一镜像、同一 securityContext、不带 `--save ""` 启动 redis，执行 BGSAVE 后读日志 errno，并执行 `id; ls -ld /data; mount | grep ' /data '`。
- **置信度**：E1–E3、E5 为高；E4 决定严重度；E6 的根因待实测。

### SS-10 user 的用户名唯一索引只在服务启动时建一次：user-db 重建后，去重保护会悄悄消失；一旦出现重名，下次 user 重启会卡在一个不退避、还泄漏会话的初始化死循环里，永远起不来
- **机制族 / 失效模式**：idempotency_compensation ＋ retry_backoff；primary D2；secondary D5——无退避重试加会话泄漏，形成对 user-db 的连接风暴。
- **位置**：user ↔ user-db（注册、登录、启动）。
- **成立条件**：
  - E1 成立：唯一索引只在 `Init → EnsureIndexes` 里创建（`USR/db/mongodb/mongodb.go:46,447-459`），而 `Init` 只在启动循环里调用（`USR/main.go:99-110`）。
  - E2 成立：种子脚本里没有任何索引（在 `USR/docker/user-db/scripts/` 下 grep `index|unique` 结果为空）；user-db 重建后没有索引，运行中的 user 也不会补建。
  - E3 成立：注册时用新 ObjectId 执行 `UpsertId`（`mongodb.go:109-127`），没有索引时重名注册会成功；登录按用户名 `.One()` 随便取一条（`mongodb.go:201-209`），后注册的那个账号会一直 401。
  - E4 成立：存在重名时，`EnsureIndex` 会失败（MongoDB 3.0 起 dropDups 被忽略），循环没有 sleep、立即重试。而 `Init` 在失败前已经把 `m.Session` 换成了新拨号的会话（`mongodb.go:42`），失败时不关闭，于是每一轮都泄漏一个会话和它的连接。HTTP 监听永远不启动，309 秒后被 liveness 杀掉，重启后重复同样的过程。
  - E5 成立（与第 2 点的关联）：重名注册回的是 500 而不是 409（`USR/api/transport.go:102-115`）。更麻烦的是，`CreateUser` 在客户已写入、只有地址/卡写失败时也返回错误（`mongodb.go:129-132`），前端一律回 500（`FE/api/user/index.js:209-210,231-236`）。客户端看到 500 的注册，可能其实已经成功；再重试，有索引时得到重名 500，没有索引时就造出一个重复账户（即 E3）。
- **触发设想**：删 user-db Pod；在此期间有同名注册两次（前端重复提交、脚本重试，或被测智能体重试）；之后 user 任意一次重启（liveness、OOM、滚动更新）即触发。
- **机制专属信号**：user 日志高频刷 `E11000 duplicate key … username_1`；user-db 的 `connections.current` 陡增；user 永远不 Ready。与 SS-04 的启动循环区别在于：那边大约每 6 秒一条 `no reachable servers`。
- **业务影响**：登录和结账永久中断，同时拖垮 user-db。
- **运行时要核对**：user-db 重建前后执行 `db.customers.getIndexes()`；在隔离环境复现"重建 user-db → 同名注册两次 → 重启 user"。
- **置信度**：中。代码链完整，但需要"重名注册"这个前置条件，当前压测不做注册。

### SS-11 下单流程是"付款 → 发货 → 写 orders-db"，既没有补偿也没有幂等键：orders-db 不可用或挂起时，已经付款、已经发货，却没有订单
- **机制族 / 失效模式**：idempotency_compensation；primary D1——codebook 规定"扣款后订单中止、无补偿"记为 D1；secondary D2。
- **位置**：orders → orders-db。
- **成立条件**：
  - E1 成立：save 发生在付款和发货之后（`OrdersController.java:85-117`），失败只会转成 500（`:121-125`），不撤销付款也不撤回发货；请求体里没有幂等键（`FE/api/orders/index.js:70-75`）。
  - E2 成立：Mongo 只设了 `serverSelectionTimeout(10000)`（`ORDJ/config/MongoConfiguration.java:17`），连接串没有其它参数（`B/benchmark-sources/materialized/sock-shop-orders-0.4.7/src/main/resources/application.properties:2`）。
- **触发设想**：删 orders-db Pod，每单在 save 处等满 10 秒后回 500，此前付款和发货都已完成；若是黑洞，save 会无限阻塞。用户重试就会重复发货。
- **机制专属信号**：orders 日志 `Timed out after 10000 ms while waiting for a server`，同一时刻 shipping 在入队。与 SS-08 的区别是：付款和发货调用都在 5 秒内成功了。
- **业务影响**：结账一致性。
- **运行时要核对**：删 orders-db Pod 期间对账；确认 jar 内 Mongo 驱动版本。
- **置信度**：高。

### SS-12 catalogue 熔断器的参数和错误分类都有问题：客户端连续请求 6 次不存在的商品，就会让所有人 30 秒内无法加购；数据库故障被报成 404；慢故障不计入失败
- **机制族 / 失效模式**：circuit_isolation；primary D4，secondary D2。
- **位置**：catalogue 服务端的 gobreaker。
- **成立条件**：
  - E1 成立：只设置了 Name 和 `Timeout:30s`（`CAT/transport.go:38-91`）。
  - E2 存疑：vendor 中 gobreaker 的版本为 809bcd5（`CAT/vendor/manifest`，源码没落地）。按文档，默认规则是连续失败超过 5 次跳闸、半开状态只放行 1 个请求，需要核对该版本。
  - E3 成立：Get 端点把错误交给熔断器（`CAT/endpoints.go:54-59`），而 `Get()` 把所有数据库错误（包括正常的"查无此行"）都变成 ErrNotFound（`CAT/service.go:147-155`），最后映射为 404（`CAT/transport.go:96-101`）。于是客户端请求不存在的商品也会被计为失败，而数据库故障被报成"不存在"。
  - E4 成立：DSN 没有超时（`CAT/cmd/cataloguesvc/main.go:46`），数据库慢或挂起时调用不返回，也就不计失败——熔断对慢故障无效。
  - E5 成立：熔断打开时返回 500。浏览请求被 front-end 改写成 200（见 SS-13）；加购则因为 item 为空被 carts 校验拒绝，返回 500（`FE/api/cart/index.js:77-105`，`CARTJ/configuration/ValidationConfiguration.java:12`，`CARTJ/entities/Item.java:13-14`）。
- **触发设想**：连续 6 次 `GET /catalogue/<不存在的id>` 后，约 30 秒内商品详情、加购、结账全部失败。catalogue-db 重启时熔断会打开，数据库恢复后最多还要再失败 30 秒。
- **机制专属信号**：响应体为 `"circuit breaker is open"`，而 `/health` 显示 `catalogue-db: OK`。
- **业务影响**：加购和结账；外部可以低成本触发。
- **运行时要核对**：发 6 次非法 ID 后立即请求合法 ID，看是否 500 并持续约 30 秒。
- **置信度**：中。

### SS-13 front-end 把下游错误改写成 200：压测中占一半的浏览流量，对 catalogue 侧故障"看不见"
- **机制族 / 失效模式**：fallback_degradation；D4。
- **位置**：front-end 的 `/catalogue*`、`/tags`、`/customers*`、`/cards*`、`/addresses`。
- **成立条件**：
  - E1 成立：`simpleHttpRequest` 不看上游状态码，一律回 200（`FE/helpers/index.js:32-34,78-83`）；这几个路由都用它（`FE/api/catalogue/index.js:17-23`，`FE/api/user/index.js:7-22`）。
  - E2 成立：压测的浏览请求只看状态码，不校验内容（`LOC:120-123`）；SLO 以压测汇总为准（`PROF:73-89`）。
- **触发设想**：catalogue 完全不可用时，成功率只会掉加购加结账那 30%；如果只是 Get 路由熔断这类局部故障，成功率可能仍在 0.95 以上。
- **机制专属信号**：catalogue 自身的 4xx/5xx 计数上升，而 front-end 同一路由全是 200。
- **业务影响**：故障检测和恢复判定被系统性低估。
- **运行时要核对**：故障期间对比 front-end 和 catalogue 按状态码统计的请求数。
- **置信度**：高。

### SS-14 整条链路的错误码分类都不准：不可重试的客户端错误回 500，数据库故障回 404，带副作用的超时也回 500（第 2 点的评估）
- **机制族 / 失效模式**：retry_backoff（可重试性信号）；primary D4，secondary 为潜在的 D3。
- **位置**：user、payment、catalogue、orders、front-end 的错误编码。
- **成立条件**：
  - E1 成立：user 除鉴权外一律回 500（`USR/api/transport.go:102-115`）；payment 对非法金额回 500（`PAY/transport.go:47-56,78-83,98-103`）；front-end 用 `err.status||500`（`FE/helpers/index.js:15-23`），写成 `next(new Error(…),400)` 的那个 400 被丢弃了（`FE/api/cart/index.js:69,114,118`）。
  - E2 成立：catalogue 把数据库故障报成 404（见 SS-12 E3）。
  - E3 成立：orders 超时回 500（`OrdersController.java:121-122`），此时付款和发货可能已经发生，与"参数错误导致的 500"无法区分。
- **评估**：应用代码目前没有任何重试，所以今天没有被放大。但有三点：
  - 现有的 catalogue 熔断器已经把客户端的 404 计为失败（见 SS-12），这就是"把不可重试错误当成故障"的现实后果。
  - 一旦加上按 5xx 重试的层（服务网格、网关、SDK，或被测智能体加的"修复"），会出现三种情况：重名注册被反复重试且必然失败；下单的模糊 500 被重放，造成重复付款授权和重复发货（codebook 中这属于 D3）；唯一索引丢失时，一次注册重试就造出重复账户（见 SS-10）。
  - SLO 错误率会把客户端错误算成服务端错误。
- **触发设想**：同名 `POST /register` 两次；`POST /paymentAuth {"amount":0}`。
- **机制专属信号**：语义上应是 4xx 的请求出现在 5xx 统计里，响应体的 error 字段为 `E11000` / `Invalid Id Hex` / `Invalid payment amount`。
- **业务影响**：错误预算、熔断决策、重试决策都会失真。
- **运行时要核对**：Pod 是否注入了 sidecar；如有，查 VirtualService/DestinationRule 的重试配置。
- **置信度**：中。分类事实是确定的，但危害需要有重试层才会发生。

### SS-15 front-end 的所有出站调用都没有超时；Node 在 120 秒后断开客户端连接，却不取消出站请求，这些请求也不进延迟直方图（T-01/T-02）
- **机制族 / 失效模式**：deadline_timeout ＋ cancellation；primary D1，secondary D2。
- **位置**：front-end → catalogue / carts / orders / user。
- **成立条件**：
  - E1 成立：`FE/api`、`FE/helpers`、`FE/server.js` 里没有任何 timeout（grep 为空）；request 2.79.0（`FE/yarn.lock:1038-1039`）默认不超时。
  - E2 成立：Node 4 的 `server.timeout` 为 120 秒，只销毁入站连接。
  - E3 成立：指标只在 `finish` 事件时记录（`FE/api/metrics/index.js:33-35`），被超时断开的请求触发的是 `close`，不会入库。
- **触发设想**：对 carts 或 orders 注入黑洞，相关请求挂满 120 秒，闭环用户全部卡住，throughput 塌陷。
- **机制专属信号**：只有依赖该下游的路由挂起，浏览正常（这点区别于 SS-05）；Prometheus 上请求量下降，却没有错误样本，也没有高延迟样本。
- **业务影响**：p95、throughput 受损，还留下可观测性盲区。
- **运行时要核对**：`curl -m 130 -w '%{time_total}'` 观察 120 秒断开；把压测失败数与 front-end 的 `request_duration_seconds_count` 对比。
- **置信度**：高。

### SS-16 登录时对 carts 合并做了"出错就忽略"的降级，却没有超时：carts 变慢或挂起时，登录被一个非关键依赖拖住
- **机制族 / 失效模式**：fallback_degradation；D2——降级只覆盖了出错，没覆盖变慢。
- **位置**：front-end `GET /login` → carts 的 `/merge`。
- **成立条件**：
  - E1 成立：合并出错时只记日志，继续登录（`FE/api/user/index.js:278-295`）。
  - E2 成立：这个请求没有超时，登录响应要等合并回调之后才写出（`:297-311`）。
- **触发设想**：给 carts 注入 30 秒延迟，登录就要约 30 秒；若是黑洞，登录挂满 120 秒。如果故障恰好覆盖压测启动时刻，压测用户会一直处于未认证状态，整轮结账失败（`LOC:42-54,129-131`）。
- **机制专属信号**：`/login` 的延迟曲线与 carts 的延迟同形；carts 快速失败时登录照常返回 200。
- **业务影响**：登录，以及依赖登录的结账。
- **运行时要核对**：carts 延迟实验中 `/login` 的延迟分布。
- **置信度**：高。

### SS-17 carts 和 orders 的 Mongo 只配了服务器选择超时，没有读写超时：数据库挂起时，请求线程会无限阻塞
- **机制族 / 失效模式**：deadline_timeout；D2。
- **位置**：carts → carts-db；orders → orders-db。
- **成立条件**：
  - E1 成立：连接串不带任何参数（`B/benchmark-sources/materialized/sock-shop-carts-0.4.8/src/main/resources/application.properties:2`，orders 同名文件第 2 行），代码只设了 `serverSelectionTimeout(10000)`（`CARTJ/configuration/MongoConfiguration.java:17`，`ORDJ/config/MongoConfiguration.java:17`）。
  - E2 存疑：Spring Boot 1.4.4 管理的驱动是 3.2.x，默认 socketTimeout=0（无限）。旧环境不得不把数据库降到 mongo 3.4.24，正是因为这一代驱动仍用 OP_QUERY（主会话已查实，`REP:11-16`）。
  - E3 成立：front-end 调用 carts 也没有超时（见 SS-15）。
- **触发设想**：连接建立之后，对 carts-db 注入黑洞，carts 的请求线程全部停在 socket 读上。
- **机制专属信号**：线程栈停在 mongo 驱动的 socket 读上，且没有 `Timed out after 10000 ms` 日志。
- **业务影响**：看车、加购、结账。
- **运行时要核对**：jar 内的驱动版本；黑洞实验时的线程栈。
- **置信度**：中。

### SS-18 carts、orders、shipping、queue-master 没有任何探针，它们自带的 `/health` 又恒返回 200（T-05 实例）
- **机制族 / 失效模式**：health_probe（readiness/liveness/app_healthcheck）；D1。
- **位置**：四个 Java 服务。
- **成立条件**：
  - E1 成立：`DEP` 中这四个服务都没有配置探针。
  - E2 成立：它们的 `/health` 恒返回 200（`CARTJ/controllers/HealthCheckController.java:22-35`，`ORDJ/controllers/HealthCheckController.java:22-36`，`SHPJ/controllers/ShippingController.java:51` 起，`QMJ/controllers/HealthCheckController.java:26-36`）。
  - E3 成立：滚动更新策略是 25%/25%，对 1 个副本取整后为 surge 1、unavailable 0；没有 readiness 时，新容器一启动就被当成可用，旧 Pod 立刻终止。
- **触发设想**：删 carts Pod。Spring Boot 在 300m CPU 限额下启动较慢，启动期间端点已经在 Service 里，请求会被拒；JVM 如果死锁或堆耗尽，也不会被重启。
- **机制专属信号**：Pod 已 Ready 时，日志里还没出现 `Tomcat started on port(s): 80`。
- **业务影响**：看车、加购、结账、发货。
- **运行时要核对**：Pod Ready 时刻与 `Tomcat started` 日志时刻之差，以及这段时间里 front-end 的 5xx 数量。
- **置信度**：高。

### SS-19 资源限额与运行时参数错配：JVM 堆 128 MiB 远低于 500 Mi 限额，OOM 时也不退出；orders 的异步线程没有上限；Go 1.7 按宿主机核数调度（T-08；JVM 内部 OOM 对 K8s 不可见）
- **机制族 / 失效模式**：resource_limit；primary D2，secondary D4。
- **位置**：四个 Java 服务；catalogue、payment、user。
- **成立条件**：
  - E1 成立：JAVA_OPTS 为 `-Xms64m -Xmx128m`，没有 `ExitOnOutOfMemoryError`；内存限额 500Mi。
  - E2 成立：这些服务没有 liveness（见 SS-18）。堆内 OOM 或 `unable to create new native thread` 之后 JVM 继续存活，K8s 没有任何 OOMKilled 记录。
  - E3 成立：orders 的线程没有上限（见 SS-08 E3）。
  - E4 存疑：msd-java 基础镜像的 JDK 版本未知；Go 服务用 golang:1.7 构建（`CAT/docker/catalogue/Dockerfile:1`，`PAY/docker/payment/Dockerfile:1`，`USR/docker/user/Dockerfile-release:1`），GOMAXPROCS 等于宿主核数，而 CPU 限额只有 200–300m。
- **触发设想**：对 payment 或 shipping 黑洞 10 分钟，观察 orders 的 RSS 和线程数。
- **机制专属信号**：日志出现 `OutOfMemoryError` 但 Pod 没有重启；cgroup 的 `nr_throttled` 上升。
- **业务影响**：结账；延迟尖峰。
- **运行时要核对**：`java -version`、`cat /usr/local/bin/java.sh`、`PrintFlagsFinal` 中的 `ParallelGCThreads`/`UseContainerSupport`；节点 `nproc`；各容器的 `cpu.stat`。
- **置信度**：中。

### SS-20 14 个 Deployment 全部单副本、没有反亲和，导出清单中也没有 PDB（T-06 实例）
- **机制族 / 失效模式**：replica_disruption；D1。
- **位置**：全部工作负载。
- **成立条件**：
  - E1 成立：所有 `replicas=1`，只有操作系统类型的 nodeSelector。
  - E2 存疑：导出清单不含 PDB 这类资源，需要到集群上核实。
  - E3 成立：有状态组件没有卷（见 SS-09）。
- **触发设想**：drain 一个节点（腾讯云只有 2 个节点）。Go 服务再叠加 180 秒就绪延迟，数据库数据清空，接着触发 SS-01。
- **机制专属信号**：Evicted 事件，多个服务同时 Ready=False。
- **业务影响**：全站。
- **运行时要核对**：`kubectl get pdb -n sock-shop`；`kubectl get pod -o wide` 看节点分布。
- **置信度**：高（E2 待核）。

### SS-21 front-end 到 session-db 的重连退避没有上限，累计 1 小时后永久放弃（N-04 实例，库版本待核）
- **机制族 / 失效模式**：retry_backoff；D4。
- **位置**：front-end → session-db。
- **成立条件**：
  - E1 成立：`new RedisStore({host:"session-db"})` 没有传任何重连参数（`FE/config.js:16`）。
  - E2 存疑：库不在 yarn.lock 中；node_redis 2.x 的默认行为是退避系数 1.7、没有最大间隔、累计 1 小时后放弃。
- **触发设想**：按默认值推算，下一次重试的间隔约为已断开时长的 0.7 倍。断开 60 秒后可能还要再等约 40 秒，断开 300 秒后可能还要再等约 3 分钟，断开超过 1 小时则永不重连。这期间看车、加购、结账都回 500，有人登录就会触发 SS-03 E5 的崩溃。
- **机制专属信号**：session-db 已 Ready，但 `CLIENT LIST` 里没有 front-end 的连接；请求是快速失败而不是挂起（这点区别于 SS-05）。
- **业务影响**：看车、加购、登录、结账，恢复明显滞后。
- **运行时要核对**：镜像中 `node_modules/redis/package.json` 的版本；隔离 session-db 5 分钟后恢复，测 front-end 重新连上所需时间。
- **置信度**：低到中。

### SS-22 carts 加购是非原子的"读-改-写"，购物车懒创建且没有唯一约束；5 个虚拟用户共用一个账号的购物车（这是第 1 点"超过支付限额"在代码层的根因）
- **机制族 / 失效模式**：idempotency_compensation；D1。
- **位置**：front-end → carts → carts-db；orders → payment。
- **成立条件**：
  - E1 成立：加购是先读、再新建或数量 +1、再保存（`CARTJ/controllers/ItemsController.java:46-58`）；这个 POST 不幂等。
  - E2 成立：查不到购物车就新建一个（`CARTJ/cart/CartResource.java:24-33`），并发首访时会产生多个同 customerId 的购物车。
  - E3 成立：`GET /carts/{id}/merge` 会修改数据（`CARTJ/controllers/CartsController.java:36-41`）。
  - E4 成立：5 个用户共用一个账号（`LOC:133-137`），每次结账前先清空购物车再加 1 件（`LOC:138-152`）；payment 拒绝超过 100 的金额（`PAY/cmd/paymentsvc/main.go:26`，`PAY/service.go:50-55`）。修补之后，最坏情况是 5×15+4.99=79.99，不会再超限；但别人的清空和加购会交错进自己的订单，件数和金额都不确定，甚至可能出现 0 件、只付运费的订单（`OrdersController.java:154-160` 不校验空单）。
- **触发设想**：故障恢复时积压请求同时释放；或者对加购做任何重试。
- **机制专属信号**：同一个 customerId 有多个购物车文档；订单件数与本用户的加购次数对不上。
- **业务影响**：结账正确性；测评结果的确定性。
- **运行时要核对**：对 carts 按 customerId 分组计数，找 n>1 的记录；抽样检查订单的 total 和 items。
- **置信度**：中。

### SS-23 queue-master 的发货工作在 K8s 里必然失败，却被吞掉、消息照常确认；处理出异常的消息默认重新入队，也没有死信队列
- **机制族 / 失效模式**：idempotency_compensation / fallback_degradation；primary D1，secondary 为潜在的 D3。
- **位置**：rabbitmq → queue-master。
- **成立条件**：
  - E1 成立：处理消息时先 `init` 再 `spawn`（`QMJ/ShippingTaskHandler.java:15-16`）；`dc` 在拉镜像之前就被赋值了（`QMJ/DockerSpawner.java:33-35`）。结果是只有启动后的第一条消息抛异常（按默认被重新入队一次），之后的消息都在线程池里失败并被吞掉（`:38,:61-62`），消息照常被确认。
  - E2 成立：监听容器全部用默认配置（`QMJ/configuration/ShippingConsumerConfiguration.java:35-37`），源码里没有确认模式、重新入队或死信相关设置（grep 为空）。
  - E3 成立：没有挂载 docker.sock，没有探针，`/health` 恒返回 200。
- **触发设想**：稳态下就成立——发货链路末端 100% 静默失败；毒消息则需要一条每次处理都抛异常的消息。
- **机制专属信号**：日志 `Exception trying to launch/remove worker container`；队列的 redelivered 计数。
- **业务影响**：发货链路末端不可观测，这一段的故障注入没有业务层面的信号。
- **运行时要核对**：queue-master 日志；`rabbitmqctl list_queues name messages consumers`；jar 内 spring-amqp 的版本。
- **置信度**：中。

---

**附：非韧性问题（安全，只简述）**
- front-end 的 `/customers`、`/addresses`、`/cards` 直接转发 user 的全量接口，不按当前用户过滤（`FE/api/user/index.js:14-22`，主会话已查实）。
- 注册、加地址、加卡时把请求体（含口令、卡号）写进日志（`:33,54,118,188`）。
- 会话 secret 写死在代码里（`FE/config.js:10,18`）；RabbitMQ 用 guest/guest。
- orders 会按客户端给的 URL 去取地址、卡和购物车（`OrdersController.java:62-73`），存在 SSRF 风险。
- 另外，`DEP user.env` 里的 `mongo=user-db:27017` 不会被代码读取：代码读的是 `MONGO_HOST`（`mongodb.go:29`），实际值来自镜像（`Dockerfile-release:24`）。

**保护有效的点（负控制）**
1. 应用层没有任何重试，所以 T-03（重试放大）不成立；前提是没有 sidecar，需要核对。
2. N-01 不成立（第 4 点）：
   - 三个 Go 服务在导出清单里都没有 ZIPKIN 环境变量，因此用的是空追踪器，根本不上报（`CAT/cmd/cataloguesvc/main.go:47,73-74`；`USR/main.go:45,76-77`；`PAY/cmd/paymentsvc/main.go:25`）。
   - 四个 Java 服务都带 `-Dspring.zipkin.enabled=false`。shipping 的 ZIPKIN 只进了 `spring.zipkin.baseUrl`（`application.properties:4`），本身已被禁用；front-end 没有追踪库。
   - 所以"调用链一直不可用"是因为全体都没上报，而不是上报失败，也就不存在阻塞业务线程的问题。
   - 如果以后给 Go 服务打开 ZIPKIN，vendored 的 zipkin-go-opentracing 594640b（`USR/glide.lock:72-73`）在收集端会不会阻塞，需要查该版本源码（存疑）。
3. payment 的熔断器永远不会跳闸：端点恒返回 nil error（`PAY/endpoints.go:34`）。
4. 登录对 carts 快速失败有有效降级（`FE/api/user/index.js:286-293`）。
5. user → user-db 有 5 秒超时（`mongodb.go:42`），数据库挂起时业务请求不会挂住。
6. catalogue 启动不依赖数据库（`main.go:105-109`）；user-db 恢复后，user 的启动循环能自动恢复（第 3 点）。
7. orders 等待下游有 5 秒上限（但不取消，见 SS-08）。
8. 客户没有地址/卡时 front-end 不会崩；`/card`、`/address` 的守卫写法正确；`/catalogue/images*` 有 error 监听。
9. carts 会拦截缺 itemId 的写入，不写脏数据（`ValidationConfiguration.java:12`，`Item.java:13-14`）。
10. shipping 和 queue-master 连 RabbitMQ 有 5 秒连接超时；监听容器按库默认每 5 秒重连（待核）。
11. session-db 被删（快速失败）时，浏览不受影响（库行为，待核），可与 SS-05 对照。

**运行时核对清单汇总（去重后）**

A. 版本与配置（只读的 exec/get）：
1. front-end：`node -v`；`node_modules/{express-session,connect-redis,redis,request}` 的版本。
2. 四个 Java 服务：`java -version`、`cat /usr/local/bin/java.sh`、`PrintFlagsFinal`；`unzip -l app.jar | grep -E 'mongo-java-driver|spring-amqp|amqp-client|sleuth'`。
3. session-db：`INFO server/persistence`；`CONFIG GET save/appendonly/stop-writes-on-bgsave-error/dir`；`DBSIZE`；`id; ls -ld /data; mount | grep ' /data '`。
4. rabbitmq：`rabbitmqctl status`；`list_queues name durable messages consumers`。
5. 平台：节点 `nproc`；kube-proxy 模式与 CNI；用 `crictl inspect` 看各数据库目录的挂载来源。
6. 拓扑：`kubectl get pdb,hpa,networkpolicy -n sock-shop`；Pod 的节点分布、qosClass、是否有 sidecar；如有，查它的 retries/timeout。
7. 压测账号：username 是否为种子账号；该账号在 user-db 中的 addresses/cards；`db.customers.getIndexes()`。

B. 故障实验（按候选编号分组，观察项见各条"机制专属信号"）：
8. session-db：删 Pod（SS-01）；黑洞或暂停进程（SS-05）；隔离 5 分钟后恢复（SS-21）。
9. catalogue：删 catalogue Pod（SS-02、SS-06）；catalogue-db 延迟 ≥1 秒（SS-04），或删 catalogue-db Pod（SS-04 对照、SS-12、SS-13）；连续 6 次非法商品 ID（SS-12）。
10. user-db：kill、6 秒延迟、40% 丢包（SS-03、SS-04）；删 user-db 后检查账号和索引（SS-09、SS-10）；在隔离环境复现"重名＋重启"（SS-10）。
11. 删 payment Pod（SS-06）；payment/shipping 黑洞 10 分钟，看 orders 的线程和内存（SS-08、SS-19）；shipping 延迟 6–10 秒后对账（SS-08）。
12. 删 rabbitmq Pod 期间下单并对账（SS-07）；看 queue-master 日志和 redelivered 计数（SS-23）。
13. 删 orders-db Pod 期间下单并对账（SS-11）；carts-db/orders-db 建连后注入黑洞，看线程栈（SS-17）。
14. carts 注入 30 秒延迟，看 `/login`（SS-16）；carts/orders 黑洞，看 front-end 的 120 秒断开和指标缺口（SS-15）。
15. 删 carts Pod，看 Ready 与 `Tomcat started` 的时间差（SS-18）；drain 节点（只在隔离环境做，SS-20）。
16. 同名注册两次、`paymentAuth amount=0`（SS-14）；共享账号并发加购后查重复购物车（SS-22）。

**未覆盖的范围**
- vendor 目录里只有 manifest，gobreaker、zipkin-go-opentracing、go-sql-driver 的源码没有落地。
- msd-java 基础镜像，以及 front-end 镜像内依赖的实际版本，都需要运行时确认。
- 导出清单不含 PDB、HPA、NetworkPolicy 和服务网格资源。
- front-end 的浏览器端 JS 只做了定点 grep。