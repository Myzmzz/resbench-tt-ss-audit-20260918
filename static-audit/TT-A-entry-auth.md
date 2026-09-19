## train-ticket 入口与认证链路：韧性缺陷候选清单（只读静态排查）

**路径缩写**（下文都按此简写）
- `B` = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark`
- `SRC` = `B/benchmark-sources/train-ticket-upstream`
- `MAN` = `B/multisystem-audit-20260918/manifests/train-ticket`
- `D0` = `B/resiliencebenchmark-stage2-d0-integration`
- 「修复记录」= `D0/environment/repairs/train-ticket-nacos-workload-qualification-20260822.yaml`
- 「档案」= `D0/environment/applications/train-ticket.yaml`
- 「负载」= `D0/environment/workloads/train-ticket/image/train_ticket_workload_generator.py`

**「javap 核实」的含义**：本机 `~/.m2` 里有与根 pom 解析结果版本一致的 jar/pom（Boot 2.3.12、SCG 2.2.9、SCA 2.2.7、nacos-client 2.0.3、Ribbon 2.3.0、spring-cloud-netflix-ribbon 2.2.9、spring-retry 1.2.5、httpclient 4.5.13、Netty 4.1.65）。我把它们反编译，直接确认了默认值。

**三个前提**
1. **当前 SLO 路径**：压测负载在集群内直连 `http://ts-gateway-service.train-ticket.svc.cluster.local:18888`（`D0/…/train-ticket/runtime-fixture.example.yaml:2`）。每次请求新建连接，连接超时 3 s、响应超时 10 s，不重试（负载:142、:168–169、:584–585）。登录不带验证码（负载:302–309），每个 order 流程都重新登录（:346–347）。
   - 在路径上：gateway、auth（登录约占 40% 流程）、contacts、user（被 preserve/cancel 同步调用）。
   - 不在路径上：ts-ui-dashboard、ischaos-tls-gateway、验证码服务。
2. **镜像来源未证实**：修复记录:66 写明"部署镜像尚未证明出自锁定的源码 commit"。所有代码级结论都要先做核对清单第 2 项。
3. **副本数与任务描述相反**：两份导出和修复记录:27 都是 gateway 3、order 2，任务描述写的是 gateway(2)、order(3)。以新环境实测为准。

**主会话三条运行时事实的根因归属**
- 事实 1（Nacos 副本分歧、死地址被标成健康）→ TT-A1（网关侧四方面根因）+ TT-A2。
- 事实 2（Nacos 全挂时服务启动即退、反复 CrashLoopBackOff）→ TT-A3。
- 事实 3（网关 `restartedAt` 注解）→ 作为 TT-A1、TT-A2 的证据引用。

---

### TT-A1 网关遇到死实例时，不主动探活、不被动剔除、不换实例重试，只能等 Ribbon 每 30 s 重读一次 Nacos（08-22 事故的网关侧根因）
- **机制族 / 失效模式**：replica_disruption（摘除/故障转移）+ circuit_isolation（被动剔除）。主 D2：Ribbon 的被动熔断存在，但网关路径不给它输入。次 D4：30 s 轮询加 DummyPing，不适合入口。另有 D1 成分：入口没有重试。
- **位置**：ts-gateway-service 全部 39 条 `lb://` 路由（本组关心 auth、auth-user、contacts、user、verification-code）。链路是 SCG `LoadBalancerClientFilter` → Ribbon `ZoneAwareLoadBalancer` → `NacosServerList`。
- **成立条件**
  - **E1 负载均衡**——成立。
    - `SRC/ts-gateway-service/src/main/resources/application.yml:16–209` 的 39 条路由全是 `uri: lb://…`。
    - 根 `pom.xml:70–72` 把 nacos-discovery 2.2.7 加进所有模块；它的 pom（`~/.m2/…/spring-cloud-starter-alibaba-nacos-discovery-2.2.7.RELEASE.pom:150–155`）以 compile 引入 spring-cloud-starter-netflix-ribbon 2.2.9。
    - javap：SCG 2.2.9 的 `GatewayLoadBalancerClientAutoConfiguration` 以 `@ConditionalOnClass(RibbonAutoConfiguration)` 注册 `LoadBalancerClientFilter`。
  - **E2 实例缓存刷新**——成立。javap `PollingServerListUpdater`：首次延迟 1000 ms，之后每 `30000` ms 一次。网关 yml 里没有任何 ribbon/loadbalancer 键。
  - **E3 失败实例剔除**——成立。
    - javap `RibbonClientConfiguration` 的默认值是 `DummyPing`、`ZoneAvoidanceRule`；`NacosRibbonClientConfiguration` 只覆盖 `ribbonServerList`。
    - javap `LoadBalancerClientFilter` 只调 `LoadBalancerClient.choose(String)`，不经 `execute`，也不记 `ServerStats`，所以 `AvailabilityPredicate` 永远不会跳闸。
    - 对照：服务间 `@LoadBalanced RestTemplate` 经 `RibbonLoadBalancerClient.execute` 会记录失败。这一点按库设计推断，未反编译。
  - **E4 重试与切换实例**——成立。
    - yml 里没有 `filters`、`default-filters`、`httpclient`。
    - javap `HttpClientProperties.connectTimeout=null`，落到 Netty `DEFAULT_CONNECT_TIMEOUT=30000`，比负载的 10 s 还长。
  - **E5 已实际发生**——成立。
    - 修复记录:8–22：网关和服务选中了"stale Nacos replicas still marked healthy"的不存在 IP，例如 order 10.0.2.124:12031、preserve 10.0.2.194:14568。
    - 修复记录:27：滚动重启 3 个网关，"so every Ribbon cache starts from the repaired registry"。
    - `MAN/deployments.json` ts-gateway-service 的 `.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"]="2026-08-22T01:48:16+08:00"`；档案:143–144。
- **触发设想**
  - (a) 对 ts-auth-service 两副本之一做 pod-kill（grace 0，避开优雅退出口径）。Nacos 随 gRPC 断连摘除实例后，网关还要再等 0–30 s。
    - 期间约一半登录打到死 IP。按每秒约 0.4 次登录估算，一次注入约 6 个流程失败，约占 5 min 窗口流程数的 2%。
    - 死 IP 如果被丢包，这些请求会各挂满 10 s。
  - (b) 单副本的 ts-contacts-service 被 kill。新 Pod 已 Ready 并已注册后，网关可能还要再等 ≤30 s 才会用它。
  - (c) 复现 08-22：只要网关所连的 Nacos 副本把旧 IP 标成健康，每次轮询都会把它读回来，失败会无限期持续。
    - 例如 3 个登记里有 1 个死实例，约 1/3 的 preserve 会失败，占全部流程约 10%，超过 5%。
- **机制专属信号**
  - 失败目标 IP 已不在任何 Pod 或 Endpoints 中。
  - 网关日志出现 `AnnotatedConnectException … Connection refused: /<旧IP>`、`No route to host`，或 CLIENT span 超时。
  - 网关容器 `/root/logs/nacos/naming.log` 已出现 `removed ips` 之后，失败仍持续（≤30 s）。
  - 和 TT-A4 的区别：这里目标 Pod 已经不存在。
- **业务影响**：登录、下单前查联系人、下单（preserve）。违反错误率 ≤5%、p95 ≤2500 ms（档案:66–78）。
- **运行时要核对**
  1. 网关 jar 内容（核对清单 2）。
  2. 网关日志 `DynamicServerListLoadBalancer for client ts-auth-service initialized … current list of Servers=`，和 Pod IP 对比。这一行同时能证实网关用的是 Ribbon。
  3. 按 (a) 注入后，取三个时间点：`naming.log` 的 `removed ips` 时间 T1；网关日志里最后一次打到旧 IP 的时间 T2；Jaeger 中 ts-gateway-service CLIENT span 目标（`net.peer.name` 或 `server.address`）最后一次是旧 IP 的时间。T2−T1 应 ≤30 s。
- **置信度**：高。库版本与默认值已反编译核实，而且已经发生过。

### TT-A2 路由是否正确，取决于网关恰好连上的那个 Nacos 副本；副本分歧、空推送、Distro 未就绪都会直接变成错误路由
- **机制族 / 失效模式**：replica_disruption（服务发现）。主 D6。次 D5（Distro 不一致叠加"每个网关只连一个 Nacos 节点"）、D4（空推送保护关闭）。
- **位置**：ts-gateway-service，以及 auth/user/contacts 的出站调用 → Nacos 2.0.1 集群。
- **成立条件**
  - **E1 只信 Nacos 的健康标记**——成立。javap `NacosServerList` 调 `selectInstances(serviceId, group, true)`，不与 K8s Endpoints 交叉核对（网关代码全文里没有 Endpoints 访问）。
  - **E2 每个网关只经一个节点订阅**——成立（设计层面）。`MAN/configmaps.json` `nacos.data.NACOS_ADDRS` 列了 3 个 headless FQDN，网关 yml:13 只配了这一项。实际连哪个节点：存疑。
  - **E3 空推送无保护**——成立。
    - javap nacos-client 2.0.3 `ServiceInfoHolder.isPushEmptyProtect` 默认 false；SCA 2.2.7 `NacosDiscoveryProperties` 没有对应字段。
    - 空列表会让 Ribbon 选不到实例，进而触发 `NotFoundException("Unable to find instance for …")`，返回 503（javap 已核实）。
  - **E4 Nacos 的 K8s 就绪 ≠ 数据就绪**——成立。
    - `MAN/statefulsets.json` nacos 只有 `readinessProbe.tcpSocket 8848`，没有 liveness。
    - 修复记录:25 写明"Wait for Nacos Distro snapshot initialization, not Kubernetes readiness alone"。
    - `MAN/services.json` `nacos-headless.publishNotReadyAddresses=false`。
  - **E5 分歧已发生**——成立。修复记录:8–9、:24–27；档案:151 把"自动核对 Nacos 副本一致性"列为待办。
  - **E6 Nacos 修好后网关能否不重启自愈**——存疑。nacos-client 2.0.3 有 `NamingGrpcRedoService`（3000 ms，javap 已核实），重连后会重做订阅。按设计网关应在 ≤30 s 内收敛，08-22 的网关重启可能只是预防性操作。
- **触发设想**
  - (a) 隔离一个 Nacos Pod，期间 kill 一个 auth 或 contacts Pod。解除后逐副本比对实例列表。只有连到坏节点的那个网关副本出错；负载每请求随机落到 3 个网关之一，所以约 1/3 请求受影响（估算）。
  - (b) Nacos 滚动重启时，网关连到尚未加载完快照的节点，可能收到空列表，对应服务 503 最长持续到下一次 30 s 轮询。
- **机制专属信号**
  - 错误按网关 Pod 分簇。
  - 三个 Nacos 副本对同一服务返回的实例不一致；或者网关报 `Unable to find instance for`，而 K8s Endpoints 并不为空。
- **业务影响**：所有经网关的流程。
- **运行时要核对**：核对清单 7–11、13。另外，旧登记的网关 IP 是 10.0.2.1（修复记录:18–19），要确认它是否是节点网桥地址；如果是，说明还有"登记 IP 选错"的问题。
- **置信度**：高（已发生，默认值已核实）。E6 为低。

### TT-A3 注册 fail-fast 把"Nacos 不可用"放大成"服务起不来"，再叠加 CrashLoopBackOff 拖慢恢复；网关自己也要注册
- **机制族 / 失效模式**：replica_disruption（重启恢复），对应 N-04。主 D3：fail-fast 被触发后退出进程，这个动作本身造成宕机，还绕过了客户端自带的补注册。次 D5（叠加 kubelet 指数退避）、D6（启动依赖 Nacos）。
- **位置**：gateway、auth、user、contacts、verification-code 的启动路径。其他业务服务同理。
- **成立条件**
  - **E1 只有 discovery、没有 config/bootstrap，fail-fast 未显式设置**——成立。
    - resources 下都只有 application.yml/yaml：网关 :10–13；auth application.yaml:3–7；user :4–8；contacts :4–8；verification :4–8。
    - 所有 pom 都没有 nacos-config 依赖。
  - **E2 SCA 2.2.7 默认 fail-fast 且会抛出**——成立。javap `NacosDiscoveryProperties` 中 `failFast=true`；`NacosServiceRegistry.register` 在 `isFailFast()` 时调用 `ReflectionUtils.rethrowRuntimeException`（日志 "nacos registry, {} register failed...{},"）。
  - **E3 报错来源**——成立。javap nacos-client 2.0.3 `RpcClient` 含 "Client not connected,current status:"，也含 "Fail to connect to server on start up … retry times left"，和主会话实测的报错一致。
  - **E4 本可自动补注册**——成立。javap `NamingGrpcClientProxy.registerService` 先 `cacheInstanceForRedo` 再 `doRegisterService`，重做任务每 3000 ms 跑一次。
    - 如果 fail-fast=false，服务会带着"待重做"的注册正常起来，Nacos 恢复后约 3 s 自动登记。
    - 默认 fail-fast=true 时进程直接退出，只能等 kubelet 重启。
  - **E5 没有 liveness/startup 探针**——成立（`MAN/deployments.json` 上述 5 个 Deployment），恢复完全依赖重启退避。
  - **E6 网关注册自己毫无收益**——成立。代码里没有任何按 Nacos 查找网关的调用方；只有部署清单引用 `ts-gateway-service`。负载、nginx、TLS 网关都用 K8s Service 名。网关却同样受 E2 约束，入口会因 Nacos 故障而无法重启。
- **触发设想**：让 Nacos 全部不可用，同时删除一个 auth Pod，或滚动重启网关。
  - 实测约 76 min 内重启 16 次，约 4.75 min 一次，符合 kubelet 退避封顶 300 s 加上 JVM 启动时间。
  - Nacos 恢复后，该 Pod 最坏还要等：≤300 s 退避 + 启动 + 就绪 initialDelay 60 s + Ribbon ≤30 s。
- **机制专属信号**
  - 日志 `register failed` + `Client not connected,current status: STARTING`，随后 Spring 上下文关闭，`restartCount` 递增。
  - Nacos 恢复时刻和服务恢复时刻之间有数分钟空档。
  - 和 TT-A12 的区别看异常栈：这里是 `NacosException`，那边是 `CommunicationsException`。
- **业务影响**：auth 掉线 = 登录全部失败；网关掉副本 = 入口容量下降；恢复时间指标会系统性偏大。
- **运行时要核对**：核对清单 4、14。
- **置信度**：高。

### TT-A4 网关按 Nacos 选实例，完全绕开 K8s 就绪；Nacos 的"健康"只表示 gRPC 连接还活着
- **机制族 / 失效模式**：health_probe（readiness + lb_healthcheck）。主 D2：就绪探针存在，但覆盖不到网关→服务这条路径。次 D4：用连接存活来判断健康，判错了对象。
- **位置**：网关 → auth/user/contacts/verification。服务间调用同样如此：auth `AuthApplication.java:21–25`、user `UserApplication.java:28–32`、preserve/cancel `*Application.java:30–34` 都是 `@LoadBalanced`。
- **成立条件**
  - **E1 网关不经 Endpoints**——成立（见 TT-A1 E1）。整个集群里只有"负载 → 网关"这一跳受 K8s 就绪控制。
  - **E2 Nacos 2.x 临时实例随 gRPC 连接存亡**——成立（Nacos 2.x 设计）。实际摘除时限存疑。
  - **E3 类似事件**——部分成立。档案:137–138 记录 ts-order-service 因 accept 队列不再排空而 0/2 Ready。静态推断此时网关仍会按 Nacos 继续转发；当时是否真的继续转发，存疑。
- **触发设想**：让 contacts 进程和 Nacos 连接都活着、但无法服务，例如注入 JVM 方法延迟 ≥10 s，或占满 Tomcat 默认 200 线程。每个请求挂到负载的 10 s 超时。
- **机制专属信号**：Endpoints 里该 IP 已进入 `notReadyAddresses`，或 K8s 仍判 Ready；Nacos 显示 `healthy=true`；网关 CLIENT span 仍指向该 IP 并超时。和 TT-A1 的区别：目标 Pod 还存在。
- **业务影响**：查联系人、登录、下单第 8 步。p95 和错误率都会恶化。
- **运行时要核对**：核对清单 15；另查 Nacos 服务端日志里该连接被注销的时间。
- **置信度**：结构判断为高，量级为中。

### TT-A5 user-service 出故障，会把已经提交的下单或取消报成失败：查用户信息被放在副作用之后，结果还被丢弃，且没有降级
- **机制族 / 失效模式**：fallback_degradation + idempotency_compensation。主 D1（CODEBOOK 边界案例"扣款后订单中止、无补偿 → D1"）。与下单组交叉：调用方属下单链路，注入点 ts-user-service 属本组。
- **位置**：preserve、cancel → `GET /api/v1/userservice/users/id/{id}`。
- **成立条件**
  - **E1 调用发生在下单之后**——成立。`SRC/ts-preserve-service/…/PreserveServiceImpl.java:170` 调 `createOrder`，:245 才调 `getAccount`（第 8 步）。
  - **E2 结果只用于一封不会发送的通知**——成立。:247–258 组装 NotifyInfo，:261 的 `// sendEmail(...)` 已被注释。
  - **E3 无降级**——成立。:301–314 没有 try/catch，直接 `result.getData()`；:250 用 `getUser.getEmail()`，查不到用户时会 NPE。
  - **E4 取消路径结构相同**——成立。`SRC/ts-cancel-service/…/CancelServiceImpl.java:57` 取消、:64 退款；:70–73 查不到用户就返回失败；:87 通知同样被注释。
  - **E5 user 单副本**——成立（`MAN/deployments.json`）。
- **触发设想**：对 ts-user-service 做 pod-kill，或注入 5xx/延迟。
  - 基线里 30% 的流程是 order，它们都会在订单已落库后得到 5xx。
  - 负载的 cleanup 取消同样依赖 user-service，订单可能既没报成功、也没被取消。
- **机制专属信号**：同一 trace 中 order 的 span 成功、user 的 span 失败；preserve 日志先有 `Do Order Complete`，最终却返回 500。
- **业务影响**：下单、取消。违反错误率 SLO，还会产生孤儿订单和"已取消却报失败"的正确性问题。
- **运行时要核对**：核对清单 24。
- **置信度**：高。

### TT-A6 JWT 在每一跳都用本 Pod 时钟做零容忍过期校验；过期异常还漏过了过滤器，连 permitAll 接口也会被拦
- **机制族 / 失效模式**：不属于 CODEBOOK 的 11 个机制族（凭证有效期 / 时钟假设），最接近 deadline_timeout，按 CODEBOOK 记 candidate-other 待人工复核。主 D4：零时钟容差，并且捕获了错误的异常类型。次 D6：token 是否有效取决于各 Pod 的本地时钟。
- **位置**：ts-common 的 `JWTFilter`/`JWTUtil`（所有业务服务共用）；签发在 auth `JWTProvider`。
- **成立条件**
  - **E1 有效期与密钥**——成立。`JWTProvider.java:20` 硬编码 `secretKey="secret"`；:22 有效期 3600000 ms；`JWTUtil.java:31` 用同一密钥。
  - **E2 零容差**——成立。`JWTUtil.java:100` 用 `getExpiration().before(new Date())`；:119–121 的解析器没有设置时钟容差（jjwt 0.8.0，ts-common `pom.xml:17–18`）。
  - **E3 过期异常逃出过滤器**——成立。
    - `JWTUtil.java:101–103` 把过期异常转成 `TokenException`。
    - `TokenException.java:6` 继承 `BaseException`，`BaseException.java:6` 继承 `RuntimeException`，都不是 `JwtException`。
    - `JWTFilter.java:28` 只 `catch (JwtException)`，所以接不住。最终返回 403 还是 500，存疑。
  - **E4 permitAll 接口也受影响**——成立。过滤器对所有请求先执行（auth `WebSecurityConfig.java:96`）；user 的 `/api/v1/userservice/users/**` 是 permitAll（`SecurityConfig.java:72`），但 preserve 会转发客户端的 token（`PreserveServiceImpl.java:304`）。
  - **E5 基线不会自然过期**——成立（负载:346–347 每流程重新登录），只有时钟偏移能触发。
- **触发设想**
  - 把 contacts 或 user 的时钟调快 ≥61 min：所有带 token 的请求在该 Pod 上都判过期。
  - 把 auth 某副本的时钟调慢 ≥61 min：它签发的 token 一出生就已过期，登录显示成功，后续请求全部失败；只影响约一半登录。
  - 阈值由 :22 的 3600000 ms 推出。
- **机制专属信号**：日志 `[validateToken][getClaims][Token expired]`（:102）集中在被偏移的 Pod；登录返回 200，紧接着 403/500，且响应很快。
- **业务影响**：下单全链路。"登录成功"会误导恢复判断。
- **运行时要核对**：核对清单 19–20。
- **置信度**：代码层面为高；能否触发取决于平台是否提供时间类故障。

### TT-A7 入口没有时限，取消只传到网关为止：客户端放弃后，后端和下游仍把活干完
- **机制族 / 失效模式**：cancellation + deadline_timeout。主 D2（CODEBOOK 边界案例"gateway timeout 有，但 backend 不接收 cancellation"），次 D1（网关自身没有响应超时）。对应 T-01/T-02。
- **位置**：负载 → 网关 → auth/user/contacts（及 preserve）→ MySQL/下游。
- **成立条件**
  - **E1 网关超时配置**——成立。javap：`responseTimeout=null`，`connectTimeout=null`（落到 Netty 默认 30 s）；连接池为 ELASTIC，`maxIdleTime`/`maxLifeTime` 为 null。
  - **E2 唯一生效的时限在客户端**——成立。负载:585 是 10 s；UI 路径的 `ts-ui-dashboard/nginx.conf:40–42` 没配超时（nginx 默认 60 s）；TLS 网关同样没配。
  - **E3 后端收不到取消**——成立。后端是 Servlet 阻塞栈（根 `pom.xml:77–79` 的 starter-web），出站调用和 JDBC 都没有读超时（见 TT-A8、TT-A12）。
  - **E4 网关在客户端断开时是否取消上游**——存疑。
- **触发设想**：给 contacts 或其 MySQL 注入 15 s 延迟。负载 10 s 放弃后，后端的 Tomcat 线程继续工作；在 preserve 上则表现为"客户端判失败、订单照样落库"。
- **机制专属信号**：网关 SERVER span 在 10 s 左右结束，下游 SERVER span 更长且以 200 结束；网关日志出现 `prematurely closed` 或 `AbortedException`。
- **业务影响**：登录、查联系人、下单。
- **运行时要核对**：核对清单 10、24。
- **置信度**：高。

### TT-A8 服务间 RestTemplate 全用默认值：无读超时、无 keepalive、连接池每路由 5/总 10 且取连接无限等待；节点级故障后，调用方会被半开连接一直卡住
- **机制族 / 失效模式**：deadline_timeout + circuit_isolation + retry_backoff。按 CODEBOOK 决策顺序，主 D1（读超时不存在）。次 D5：只有和小连接池、无 keepalive 组合起来，才会出现"依赖恢复后调用方仍不自愈"，这是 T-01 没覆盖的部分。次 D4：连接池上限相当于隐式舱壁，但取连接没有超时，参数不对。
- **位置**：auth → verification-code；user → auth（POST 创建、DELETE 删除）；本组服务作为被调方：preserve/cancel → user、preserve → contacts。
- **成立条件**
  - **E1 全用 `builder.build()`**——成立。`AuthApplication.java:21–25`、`UserApplication.java:28–32`、`ContactsApplication.java:30–34`、`VerifyCodeApplication.java:22`、`PreserveApplication.java`/`CancelApplication.java:30–34`；全仓没有任何超时配置。
  - **E2 连接池**——成立。
    - ribbon-httpclient pom:27–30 引入 httpclient。
    - javap：Boot 2.3.12 优先选 `HttpComponentsClientHttpRequestFactory`；它的默认构造调用 `HttpClients.createSystem()`；`HttpClientBuilder` 读 `http.maxConnections`，默认 "5"，即每路由 5。
    - 总数 10 按 4.5.x 源码推断；三类超时默认 −1（无限）按库默认值推断。
  - **E3 重试**——成立。spring-integration-core 5.3.8 pom:82–85 以 compile 引入 spring-retry，于是启用 Ribbon 重试拦截器：GET 立即换实例重试 1 次，POST/DELETE 不重试（Ribbon 默认值，未反编译）。单副本被调方的"下一个实例"仍是同一个死地址。
  - **E4 远程调用占着数据库连接**——成立。user `UserServiceImpl.java:133` 的 `@Transactional` 方法在 :139 调 `deleteUserAuth`（:183 远程 DELETE）。
- **触发设想**：user（单副本）所在节点断网或宕机，对端不会发 FIN/RST。
  - 已发出的请求永远等不到响应，连接永不归还。
  - 每个 preserve Pod 在该路由上最多卡 5 个连接；如果 contacts 同时出事，总数 10 被占满，preserve 对所有下游的调用都卡在取连接上。
  - 节点恢复后依然卡住，直到 preserve 重启。
- **机制专属信号**：被调方已恢复（直接 curl 正常），调用方仍挂起；线程栈停在 `getPoolEntryBlocking`/`leaseConnection` 和 `socketRead0`；`ss` 显示到旧 IP 的 ESTABLISHED 连接，且没有 keepalive 计时器。
- **业务影响**：下单与取消无法自愈。
- **运行时要核对**：核对清单 2、25。
- **置信度**：中高。"永久卡住"依赖对端不回 RST，需要实测。

### TT-A9 入口与认证组件的健康判定都只看 TCP 端口，没有存活探针；能反映真实状态的 health 端点又被 Spring Security 挡住
- **机制族 / 失效模式**：health_probe（readiness；liveness 缺失）。主 D4（CODEBOOK："probe 检查了错误的本地状态"），次 D1。对应 T-05。
- **位置**：gateway、auth、user、contacts、verification、ui-dashboard。
- **成立条件**
  - **E1 只有 TCP readiness**——成立。`MAN/deployments.json` 中端口依次为 18888/12340/12342/12347/15678/8080，initialDelay 60，都没有 liveness/startup。
  - **E2 TCP 通 ≠ 能服务**——成立（机制层面）。Tomcat 占满、Hikari 耗尽、网关拿到空列表时，端口照样是开着的。
  - **E3 health 端点被挡**——成立。根 `pom.xml:91` 引入了 actuator，但 auth `WebSecurityConfig.java:94`、contacts `SecurityConfig.java:74`、user `SecurityConfig.java:76` 都写了 `anyRequest().authenticated()`，httpGet 探针会拿到 401/403。
- **触发设想**：对 tsdb-mysql-leader 注入延迟，耗尽 auth 的 Hikari 连接池（10 个连接，取连接超时 30 s）。Pod 始终 Ready，也不会被重启。
- **机制专属信号**：Ready=True、`restartCount` 不变，但 SERVER span 错误率上升；日志出现 `Connection is not available, request timed out after 30000ms`。
- **业务影响**：登录、查联系人；恢复阶段没有自动重启兜底。
- **运行时要核对**：核对清单 1、16、23。
- **置信度**：高。

### TT-A10 网关唯一的准入保护（Sentinel）只覆盖 39 条路由中的 1 条；登录每次都做 BCrypt，却完全不限流
- **机制族 / 失效模式**：load_shedding_admission。主 D2，次 D4（阈值按网关实例计算，会随副本数漂移）。
- **位置**：网关 SentinelGatewayFilter → auth `/api/v1/users/login`。
- **成立条件**
  - **E1 只有一条规则**——成立。`GatewayConfiguration.java:107–119` 只给 `admin-basic-info` 设了 QPS 20（:112–116）；:77 的自定义处理器被注释。
  - **E2 规则只在进程内生效**——成立（:118）。3 个网关副本合计约 60 QPS，会随副本数变化。
  - **E3 登录成本高**——成立。auth `WebSecurityConfig.java:75` 用 `new BCryptPasswordEncoder()`（强度 10）；`TokenServiceImpl.java:84` 每次登录都校验；auth CPU request 只有 10m。
- **触发设想**：把 login 流量从 0.2 QPS（`profiles.yaml:66`）提高到 20–40 QPS，或叠加节点 CPU 压力。登录时延会超过 1500 ms（`profiles.yaml:77`），直至超过 10 s。
- **机制专属信号**：auth 的 CPU 被节流，而 DB 空闲；auth 路由从不返回 429。对照：admin-basic-info 路由在同样压力下会返回 `Blocked by Sentinel`。
- **业务影响**：登录，影响 p95 和吞吐比。
- **运行时要核对**：核对清单 10（网关日志 `only 20 requests per second can pass`）、17。
- **置信度**：代码层面为高，影响量级为中。

### TT-A11 资源配额和 JVM 运行时对不上，网关最严重：CPU request 10m、内存 request 100Mi，对应 -Xmx1024m，且基础镜像很可能不识别容器限额
- **机制族 / 失效模式**：resource_limit。主 D4，对应 T-08。
- **位置**：网关（全部流量都经过它），以及 auth/user/contacts/verification。
- **成立条件**
  - **E1 request 远低于实际用量**——成立。6 个 Deployment 都是 requests 10m/100Mi、limits 1500m/1500Mi。
  - **E2 堆上限与容器限额**——成立。网关 `Dockerfile:6` 是 `-Xmx1024m`，占限额 68%，还要加上 Netty 直接内存、元空间和 OTel agent；其他服务 `Dockerfile:6` 是 `-Xmx200m`，OTel agent 与业务共用这 200m。
  - **E3 JVM 可能不认容器 CPU 限额**——存疑。`Dockerfile:1` 都是 `FROM java:8-jre`，早于 8u191 的容器感知。若如此，事件循环和 GC 线程会按宿主机核数创建，在 1.5 核限额下被 CFS 节流，停顿被放大。
- **触发设想**
  - 节点 CPU 争用：网关只能按 10m 的份额拿 CPU，所有路由同时变慢。
  - 节点内存压力：网关实际占用远超 request，会最先被驱逐。
  - 另有冷启动：Ribbon 各路由懒加载，加上 JIT 冷启动。
- **机制专属信号**：网关 SERVER span 全面变慢，而各后端正常；`container_cpu_cfs_throttled_periods_total` 上升；Pod 事件 `Evicted`。
- **业务影响**：所有流程。
- **运行时要核对**：核对清单 3、17。
- **置信度**：中（E3 取决于实际镜像）。

### TT-A12 认证和用户数据访问没有 socket 超时，三个服务共用一个 MySQL 主节点；数据库不可用时服务连启动都起不来
- **机制族 / 失效模式**：deadline_timeout。主 D1，次 D6。与基础设施组交叉。
- **位置**：auth、user、contacts → `*_MYSQL_HOST`。
- **成立条件**
  - **E1 JDBC URL 没有超时参数**——成立。auth yaml:11、user :12、contacts :12 只带 `useSSL=false`。驱动 8.0.25 默认 connectTimeout 和 socketTimeout 都是 0（无限，按库文档默认值）。
  - **E2 Hikari 用默认值**——成立。三个配置文件都没有 hikari 配置，HikariCP 3.4.5 默认池 10、取连接超时 30 s。
  - **E3 共用主节点**——存疑（Secret 已脱敏）。上游 `hack/deploy/utils.sh:59–66` 给所有服务都生成 `tsdb-mysql-leader`；`MAN/services.json` 里也没有各服务独立的 MySQL Service。
  - **E4 启动强依赖 DB**——成立。`ddl-auto: update` 在 auth :17、user :18、contacts :18；auth `InitUser.java:29–49` 启动时写库。
- **触发设想**
  - 对 leader 注入丢包：进行中的查询会一直挂起；10 个连接耗尽后，新请求等满 30 s 再失败；K8s 和 Nacos 都不会摘除这个实例。
  - 数据库主从切换：旧连接上的在途查询可能要等 TCP 重传放弃（约 15 min）。
  - 数据库不可用时重启服务：启动失败，进入 CrashLoopBackOff。
- **机制专属信号**：线程栈停在 `socketRead0 … com.mysql.cj`；日志有 `HikariPool … not available`；启动失败时异常是 `CommunicationsException`。
- **业务影响**：登录、查联系人、下单第 8 步。
- **运行时要核对**：核对清单 4、21、23。
- **置信度**：中。

### TT-A13 有副本却不分散：网关 3 副本、auth 2 副本没有反亲和也没有 PDB；user、contacts、verification-code 都是单副本
- **机制族 / 失效模式**：replica_disruption。多副本部分为 D2，单副本部分为 D1。对应 T-06。
- **位置**：见标题。
- **成立条件**
  - **E1 副本数**——成立（见前提 3）。
  - **E2 没有任何分散或保护配置**——成立。所有 Deployment 都没有 `podAntiAffinity`/`topologySpreadConstraints`（jq 查询结果为空）；团队 `static-manifests.yaml` 和 `live-export.yaml` 里 PDB、HPA 数量都是 0；唯一的亲和规则是 `nodeAffinity NotIn tcse-v100-01`。
  - **E3 发现机制拉长单副本的恢复**——成立（见 TT-A1、TT-A3）。
- **触发设想**
  - 网关副本如果集中在同一节点，该节点宕机时入口全断。
  - kill 单副本的 contacts：在 JVM 启动 + 就绪等待 60 s + Ribbon ≤30 s 这段时间里，下单 100% 失败。
- **机制专属信号**：失败窗口与单个 Pod 的生命周期完全重合；多个同名副本落在同一节点。
- **业务影响**：下单、登录、所有流程。
- **运行时要核对**：核对清单 1、18。
- **置信度**：清单层面为高。

### TT-A14 登录同步依赖一个"永远返回 true"的验证码服务：校验结果毫无意义，但它一出故障登录就失败
- **机制族 / 失效模式**：fallback_degradation。主 D1，对应 T-09。
- **位置**：auth → verification-code（只在请求带验证码时发生，即 UI 登录）。
- **成立条件**
  - **E1 恒返回 true**——成立。`VerifyCodeController.java:55` 是 `return true;`。
  - **E2 无降级**——成立。`TokenServiceImpl.java:65–79`（:72 对返回值拆箱）；`UserController.java:44–50` 和 `GlobalExceptionHandler.java:15–18` 只处理 `UserOperationException`，其他异常一律变成 500。
  - **E3 UI 必须带验证码**——成立。`client_login.js:38–42`。
  - **E4 压测负载不带**——成立（负载:302–309），所以当前 SLO 看不到这个问题。
- **触发设想**：kill 验证码服务，或注入延迟，同时发起带验证码的登录。延迟情况下，每个 auth Pod 只有 5 个连接的池，挂住后会连带拖慢不带验证码的登录。
- **机制专属信号**：只有带验证码的登录失败；auth 日志出现 `No instances available for ts-verification-code-service`。
- **业务影响**：UI 登录。
- **运行时要核对**：带验证码登录时，auth 的 CLIENT span 是否指向验证码服务，以及注入后的返回码分布。
- **置信度**：代码层面为高，对 benchmark 相关性低。

### TT-A15 注册是跨库双写、没有补偿，用户名也没有唯一约束：一次部分失败加一次重试，该用户就永久登录不了
- **机制族 / 失效模式**：idempotency_compensation。主 D1。
- **位置**：user register → auth `POST /api/v1/auth`；auth 启动时的 InitUser。
- **成立条件**
  - **E1 先远程写、再本地写，没有补偿**——成立。user `UserServiceImpl.java:63` 查重、:66–68 远程建 auth 用户、:70 本地保存。
  - **E2 重试会生成新 id**——成立。:49–51 每次新建 UUID；auth `UserServiceImpl.java:52–65` 不查重就保存，校验异常还被吞掉（:60–64）。
  - **E3 用户名无唯一约束**——成立。auth `User.java:32–33`；user `User.java:28`。
  - **E4 重复后登录必失败**——成立。`UserDetailsServiceImpl.java:29` 和 `TokenServiceImpl.java:90` 都调用返回单值的 `findByUsername`（auth `UserRepository.java:20`），遇到两行会抛异常。
  - **E5 InitUser 并发写入**——成立。auth 有 2 副本；`InitUser.java:40–49` 对 admin 先查后插，且 userId 随机（:43）。
- **触发设想**：在 :66 之后 kill user，客户端重试注册；或者在空库上让两个 auth 副本同时启动。
- **机制专属信号**：`auth_user` 表里同名多行；登录日志出现 `IncorrectResultSizeDataAccessException`。
- **业务影响**：注册与特定用户的登录。当前负载用预置用户，影响有限。
- **运行时要核对**：核对清单 22。
- **置信度**：代码层面为高，对 benchmark 相关性低。

### TT-A16 UI 入口 nginx 是单 worker、1024 连接、默认 60 s 超时，只有 TCP 探针：网关一变慢，nginx 就会饱和并被逐个摘除；上游地址只在启动时解析一次
- **机制族 / 失效模式**：load_shedding_admission + health_probe。主 D5，次 D4。
- **位置**：ts-ui-dashboard → 网关。不在压测负载路径上。
- **成立条件**
  - **E1 并发上限低**——成立。`nginx.conf:1` 单 worker、:4 `worker_connections 1024`，约 512 个代理并发；:21 的客户端 keepalive 65 s 还会占用连接。
  - **E2 超时与上游连接**——成立。:40–42 没配超时，也没有 `upstream keepalive`。
  - **E3 上游地址只解析一次**——成立。:41 写的是主机名，没配 resolver；网关 Service 如果被重建，nginx 仍连旧 IP，而且没有 liveness 探针把它重启。
  - **E4 openresty 版本**——存疑（`Dockerfile:1` 是 `trusty` tag，未固定版本）。
- **触发设想**：网关变慢到 60 s，UI 侧每个 Pod 每秒 10 个请求 → 约 600 个并发，超过 512 → nginx 停止 accept → TCP 探针失败 → Pod 被摘除 → 剩下两个 Pod 被连锁压垮。
- **机制专属信号**：error.log 出现 `worker_connections are not enough`；三个 ui Pod 依次 NotReady。
- **业务影响**：浏览器端的全部访问。
- **运行时要核对**：核对清单 6、26。
- **置信度**：中。

### TT-A17 ischaos-tls-gateway 的镜像 tag 就叫 `tls-cert-expire`，证书只在启动时加载，单副本且没有任何探针
- **机制族 / 失效模式**：不属于 CODEBOOK 机制族（证书到期），附带 health_probe。主 D4，次 D6。
- **位置**：ischaos-tls-gateway → 网关。不在压测路径上。
- **成立条件**
  - **E1 部署形态**——成立。`MAN/deployments.json` 中镜像是 `…/ischaos/frontend:v1.3.1-tls-cert-expire`，1 副本，没有探针，`resources: {}`。
  - **E2 证书加载方式**——成立。`MAN/configmaps.json` 的 `ischaos-tls-gateway-nginx` 写的是 `ssl_certificate`；nginx 不会自动重读已更新的 Secret。
  - **E3 证书是否已过期**——存疑。
  - **E4 上游地址与超时**——成立，同 TT-A16。
- **触发设想**：证书过期或被更换时 TLS 握手全部失败，但 TCP 层一切正常。
- **机制专属信号**：客户端报 `certificate has expired`，Pod 却没有重启。
- **业务影响**：经过该 TLS 入口的访问。
- **运行时要核对**：核对清单 1、27。
- **置信度**：低到中，很可能是旧实验遗留。

### TT-A18 验证码服务的匿名接口每次都新建 HttpSession（保留 30 min），堆只有 200m，也没有限流
- **机制族 / 失效模式**：load_shedding_admission + resource_limit。主 D1。
- **位置**：`GET /api/v1/verifycode/generate`。
- **成立条件**
  - **E1 每次都建会话**——成立。`VerifyCodeController.java:37–38`；`SecurityConfig.java:68` 的 STATELESS 只管 Spring Security 自己，挡不住应用建会话。
  - **E2 匿名可访问**——成立。`SecurityConfig.java:71` 是 permitAll；网关 yml:206–209 直接转发；Sentinel 没有覆盖这条路由。
  - **E3 堆小**——成立。`Dockerfile:6` 是 `-Xmx200m`。
- **触发设想**：以 50 QPS 持续请求 30 min，会累积约 9 万个会话，最终 Full GC/OOM；TCP 探针仍然通过。
- **机制专属信号**：`jvm.memory.used` 线性上涨，日志出现 `OutOfMemoryError`。
- **业务影响**：UI 登录。
- **运行时要核对**：注入期间的 JVM 内存与重启次数。
- **置信度**：中，对 benchmark 相关性低。

---

## 保护有效的点（可作负控制）
1. **入口不重试**：网关 yml 没有 Retry 过滤器，负载也只请求一次（负载:137–169），入口不存在重试放大，T-03 在入口不成立。服务间 Ribbon 重试只针对 GET、最多多试 1 次，放大上限约 2 倍。
2. **admin-basic-info 的限流有效**：`GatewayConfiguration.java:112–116`，突发时应返回 429 `Blocked by Sentinel`，可作 TT-A10 的对照组。
3. **重启 auth 不会让用户掉线**：JWT 无状态，所有服务共用固定密钥（`JWTProvider.java:20`、`JWTUtil.java:31`），auth 副本可以互换。
4. **基线下 token 不会自然过期**：负载每个流程重新登录（:346–347），token 年龄远小于 1 小时（`JWTProvider.java:22`）。
5. **联系人创建由唯一索引兜底**：`Contacts.java:21` 的唯一索引让并发重复创建只会失败、不会产生重复行（要核实库里确实有这个索引）。
6. **验证码状态丢失没有业务后果**：校验恒为 true（`VerifyCodeController.java:55`），T-10 在这个组件不成立。
7. **运行中的服务与 Nacos 断连后会自动补注册**：`NamingGrpcRedoService` 每 3000 ms 重做（javap 已核实）。只有启动期受 TT-A3 影响。
8. **已在运行的网关在 Nacos 全挂时会用最后已知列表继续转发**：本地 `ServiceInfoHolder` 缓存 + Ribbon 更新失败时保留旧列表（按库设计推断）。前提是期间没有 Pod 变动。
9. **N-01（同步遥测拖慢业务）不成立**：OTel agent 用 BatchSpanProcessor 在后台导出，环境变量里只设了 exporter 和 endpoint（需核对 agent 版本）。
10. **auth 滚动更新不会降低 K8s 层的可用副本数**：`maxUnavailable` 25% 向下取整为 0、`maxSurge` 为 1。但这只对 ClusterIP 流量有效，网关不看就绪（TT-A4），所以只算部分有效。

## 运行时核对清单汇总（已去重）

**一、先确认静态结论是否适用**
1. 6 个 Deployment 的实际配置：replicas（尤其网关是 2 还是 3）、三类探针、resources；另查 `kubectl get deploy ischaos-tls-gateway` 是否存在。
2. 各 jar 内容：
   - `unzip -p /app/<svc>-1.0.jar BOOT-INF/classes/application.y*ml`，与上游比对。
   - `unzip -l` 后 grep `nacos-client|ribbon-loadbalancer|spring-cloud-netflix-ribbon|spring-cloud-gateway-server|httpclient-4|spring-retry|jjwt|mysql-connector|HikariCP|netty-transport`。镜像里没有 unzip 时，用 `kubectl cp` 拷出来看。
3. JVM（网关、auth）：
   - `java -version`
   - `java -XX:+PrintFlagsFinal -version | grep -Ei "UseContainerSupport|ActiveProcessorCount|ParallelGCThreads|MaxHeapSize"`
   - `grep Threads /proc/1/status`
4. 各 Pod 环境变量：`env | grep -i -E "nacos|mysql|hikari|datasource|ribbon"`，看有没有覆盖 fail-fast 或超时。
5. OTel agent 版本：`unzip -p /opt/opentelemetry-javaagent/opentelemetry-javaagent.jar META-INF/MANIFEST.MF`。
6. nginx：`openresty -v`，并查看实际生效的 `nginx.conf`。

**二、Nacos / Ribbon**

7. 在 nacos-0/1/2 上逐个查询：`curl -s 'localhost:8848/nacos/v1/ns/instance/list?serviceName=<svc>'`（auth、user、contacts、verification、gateway），与 `kubectl get endpoints <svc> -o yaml`（addresses/notReadyAddresses）对账。
8. 每个网关 Pod 连的是哪个 Nacos 节点：`ss -tnp | grep 9848` 或 `/proc/net/tcp`。
9. 网关容器 `/root/logs/nacos/naming.log` 里的 `current ips`、`removed ips`、`new ips`，特别注意 `current ips:(0)`。
10. 网关日志关键字：`DynamicServerListLoadBalancer for client`、`Unable to find instance for`、`Connection refused`、`No route to host`、`prematurely closed`、`AbortedException`、`only 20 requests per second can pass`。
11. 修复记录里旧登记的网关 IP 10.0.2.1，是否是节点网桥地址。
12. 实验 A：对一个 auth Pod 做 pod-kill（grace 0），测量 naming.log 的 `removed ips` 时间与网关最后一次打到旧 IP 的时间差。
13. 实验 B：只重启一个 Nacos 副本、不动网关，看旧 IP 是否在 30 s 内从网关 CLIENT span 的目标中消失，以及有没有出现 `Unable to find instance`。
14. 实验 C：Nacos 全部不可用。
    - C1：不动任何 Pod，确认网关还能继续转发（负控制）。
    - C2：再删一个 auth Pod，记录 `restartCount`、`lastState.terminated.finishedAt` 的序列和两条报错；Nacos 恢复后，记录"Nacos 恢复 → Pod Ready → 网关首次成功转发"三个时间点。
15. 实验 D：让 contacts 无法服务，但进程和 Nacos 连接都还活着。对照 Endpoints 的 notReady、Nacos 的 healthy 字段、网关 CLIENT span 的目标。

**三、健康、资源、拓扑**

16. 在各 Pod 内执行 `curl -s -o /dev/null -w '%{http_code}' localhost:<port>/actuator/health`（端口 12340/12342/12347/15678/18888），预期 auth、user、contacts 返回 401/403。
17. Prometheus：网关和 auth 的 `container_cpu_cfs_throttled_periods_total`、`container_memory_working_set_bytes`；`kubectl describe node` 看 requests 与 allocatable。
18. `kubectl get pod -l 'app in (ts-gateway-service,ts-auth-service,ts-ui-dashboard)' -o wide` 看节点分布；`kubectl get pdb,hpa -n train-ticket`。

**四、认证与时钟**

19. 各节点时钟：`chronyc tracking`，或在各 Pod 里对比 `date +%s`。
20. 用过期或伪造的 token 调 `POST /api/v1/users/login`（带 Authorization 头）和 `GET /api/v1/userservice/users/id/<id>`，记录返回码是 403 还是 500。时间类故障注入后，统计目标 Pod 日志里 `Token expired` 的次数。

**五、数据库**

21. 把 `ts-auth-mysql`、`ts-user-mysql`、`ts-contacts-mysql` 三个 Secret 里的 `*_MYSQL_HOST` 解码，看是否都指向 tsdb-mysql-leader。
22. 只读 SQL：`SHOW INDEX FROM contacts;`，以及 `SELECT user_name, COUNT(*) FROM auth_user GROUP BY user_name HAVING COUNT(*)>1;`（user 库同理）。
23. DB 故障注入期间，看日志 `HikariPool-1 - Connection is not available`、`CommunicationsException`，同时看 Pod 是否始终 Ready。

**六、调用链与挂死**

24. Jaeger 与日志：
    - 网关 SERVER span 时长与下游 SERVER span 时长对比，确认取消有没有传下去。
    - preserve 的 trace 里"order span 成功 + user span 失败"的比例。
    - preserve 日志 `Do Order Complete` 与 500 的配对数。
    - 负载用户未取消订单的数量（可对照修复记录:59–62）。
25. 故障解除后仍挂着的调用方 Pod：执行 `kill -3 1` 取线程栈，统计 `leaseConnection`、`getPoolEntryBlocking`、`socketRead0` 的数量；用 `ss -tno state established` 看到旧 IP 的连接和 keepalive 计时器。

**七、UI 与 TLS 入口**

26. `tail /usr/local/openresty/nginx/logs/error.log`，找 `worker_connections are not enough`。
27. TLS Secret 的证书到期时间：`… | base64 -d | openssl x509 -noout -enddate`。

## 跨范围提示与未覆盖部分
- **交基础设施组**：
  - 所有 Java Pod 的 OTel agent 从 NFS `1.94.151.57:/data/share` 挂载，这台主机同时也是 Harbor，Pod 重建依赖它。
  - Nacos 服务端本身：2.0.1、只有 TCP 就绪、`publishNotReadyAddresses=false`、OrderedReady。
- **交下单组复核**：preserve 和 cancel 的内部逻辑（TT-A5、TT-A8 的调用方）。
- **未反编译核实、按库设计推断的**：
  - Ribbon 重试默认值；服务间路径是否记录 `ServerStats`；Ribbon 更新失败时是否保留旧列表。
  - HttpClient 的总连接数 10 和三类超时 −1。
  - Connector/J、Hikari 的默认值（依据本地缓存中的 8.0.25 和 3.4.5）。
- **未看的范围**：ts-admin-user-service 等其他调用 user/contacts 的管理类服务。