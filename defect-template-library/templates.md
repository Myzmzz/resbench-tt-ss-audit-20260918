<!-- 由 render_templates.py 生成，请勿手改；改了 templates.yaml 后重新运行 -->

# templates.md —— 缺陷模板卡片

共 49 条模板、6 条 advisory。每张卡片四块：**规则**（应该怎样、凭什么）、**定位**（到哪找、查什么）、**实验**（用什么故障、多大多久）、**判定**（看什么、算不算、怎么修）。

## 目录

- **`circuit_isolation`**：[T-CIRCUIT-01](#t-circuit-01)、[T-CIRCUIT-02](#t-circuit-02)、[T-CIRCUIT-03](#t-circuit-03)、[T-CIRCUIT-04](#t-circuit-04)、[T-CIRCUIT-05](#t-circuit-05)
- **`connection_lifecycle`**：[T-CONN-01](#t-conn-01)、[T-CONN-02](#t-conn-02)、[T-CONN-03](#t-conn-03)
- **`deadline_timeout`**：[T-DEADLINE-01](#t-deadline-01)、[T-DEADLINE-02](#t-deadline-02)、[T-DEADLINE-03](#t-deadline-03)、[T-DEADLINE-04](#t-deadline-04)、[T-DEADLINE-05](#t-deadline-05)
- **`delivery_semantics`**：[T-DELIVERY-01](#t-delivery-01)、[T-DELIVERY-02](#t-delivery-02)、[T-DELIVERY-03](#t-delivery-03)、[T-DELIVERY-04](#t-delivery-04)
- **`fallback_degradation`**：[T-FALLBACK-01](#t-fallback-01)、[T-FALLBACK-02](#t-fallback-02)、[T-FALLBACK-03](#t-fallback-03)
- **`health_probe`**：[T-PROBE-01](#t-probe-01)、[T-PROBE-02](#t-probe-02)、[T-PROBE-03](#t-probe-03)、[T-PROBE-04](#t-probe-04)、[T-PROBE-05](#t-probe-05)
- **`idempotency_compensation`**：[T-IDEM-01](#t-idem-01)、[T-IDEM-02](#t-idem-02)、[T-IDEM-03](#t-idem-03)
- **`load_shedding_admission`**：[T-SHED-01](#t-shed-01)、[T-SHED-02](#t-shed-02)、[T-SHED-03](#t-shed-03)、[T-SHED-04](#t-shed-04)
- **`replica_disruption`**：[T-REPLICA-01](#t-replica-01)、[T-REPLICA-02](#t-replica-02)、[T-REPLICA-03](#t-replica-03)、[T-REPLICA-04](#t-replica-04)、[T-REPLICA-05](#t-replica-05)
- **`resource_limit`**：[T-RESOURCE-01](#t-resource-01)、[T-RESOURCE-02](#t-resource-02)、[T-RESOURCE-03](#t-resource-03)、[T-RESOURCE-04](#t-resource-04)
- **`retry_backoff`**：[T-RETRY-01](#t-retry-01)、[T-RETRY-02](#t-retry-02)、[T-RETRY-03](#t-retry-03)、[T-RETRY-04](#t-retry-04)、[T-RETRY-05](#t-retry-05)
- **`service_discovery`**：[T-DISCOVERY-01](#t-discovery-01)、[T-DISCOVERY-02](#t-discovery-02)、[T-DISCOVERY-03](#t-discovery-03)


---

## 机制组 `circuit_isolation`


### T-CIRCUIT-01　熔断只看错误率，不看慢调用

> 机制 `circuit breaker`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖只是变慢、一直返回成功，熔断全程闭合，调用方的线程池被慢调用占满直至自身不可用。

#### 一 规则

熔断的判据除了失败率还应包含慢调用比例；只看错误率时，一个「只慢不错」的依赖永远不会让熔断跳闸。

依据：

- `resilience4j-circuitbreaker`（Resilience4j，CircuitBreaker > Failure rate and slow call rate thresholds）— CircuitBreaker
  > The CircuitBreaker also changes from CLOSED to OPEN when the percentage of slow calls is equal or greater than a configurable threshold. For example when more than 50% of the recorded calls took longer than 5 seconds. This helps to reduce the load on an external system before it is actually unresponsive.
- `resilience4j-circuitbreaker`（Resilience4j，CircuitBreaker > Failure rate and slow call rate thresholds）— CircuitBreaker
  > The failure rate and slow call rate can only be calculated, if a minimum number of calls were recorded.

#### 二 定位

适用范围：

- 对某个同步依赖启用了熔断
- 该依赖存在「变慢但仍返回成功」的失效方式（绝大多数同步依赖都有）

角色：脆弱点在 **该依赖的熔断配置**；故障加在 **该依赖**；异常显现在 **调用方的线程池或连接池占用，以及它的上游**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | 是否配了 slowCallRateThreshold 与 slowCallDurationThreshold | `resilience4j.circuitbreaker 配置` |
| Polly | 断路器只按 ShouldHandle 的结果计数，慢调用需靠外层 Timeout 策略转成失败 | `源码` |
| Envoy | 无原生慢调用判据，靠 per_try_timeout 把慢转成错误后再由 outlier detection 剔除 | `route.retry_policy.per_try_timeout 与 cluster.outlier_detection` |
| gobreaker | ReadyToTrip 回调默认只数连续失败，慢调用需自行计入 | `源码` |
| Microsoft.Extensions.Http.Resilience | 标准弹性处理器把超时段落放在断路器之前，慢调用先被转成失败再计入断路器 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 熔断配置里没有慢调用判据（阈值时长或比例缺失） | resilience4j.circuitbreaker.instances.*.[slowCallRateThreshold, slowCallDurationThreshold] |
| C2 | 必要 | `codegraph` | 该调用没有短于慢调用容忍度的超时（否则慢会被超时转成失败） | 起点为被熔断包裹的调用点，向内查 2 跳内底层客户端是否设置了读超时 |
| C3 | 反证 | `llm` | 外层已有超时策略把慢调用转成失败，失败率判据能够覆盖 | 被熔断包裹的调用是否有一个小于慢调用容忍时长的超时？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | 熔断的最小请求数与统计窗口（决定触发所需的注入时长） | resilience4j.circuitbreaker.instances.*.[minimumNumberOfCalls, slidingWindowSize] |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢但仍成功 | 连续幅值 | `injection_site` | 网络延迟，保持下游正常返回 200，只把耗时抬高 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `S` | 慢调用时长阈值，未配置时视为无穷 | manifest|default |
| `rs` | 慢调用比例阈值 | manifest|default |
| `b` | 该调用的基线耗时 | measured |
| `M` | 最小请求数 | manifest|default |
| `q` | 该路径的 QPS | measured |

- 触发边界：`d* = S - b`
- 最坏情况倍数：`1`
- 保持时长：`M / q + 慢调用统计窗口`
- 恢复观察窗：`2 * (M / q)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：依赖只慢不错时，熔断在慢调用比例越过阈值后跳闸，调用方的线程占用回落。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 熔断器状态是否发生 CLOSED 到 OPEN 的变迁 | `metrics` |
| 慢调用比例指标随注入幅值的变化 | `metrics` |
| 调用方线程池活跃线程数与队列长度 | `metrics` |
| 上游对该服务的耗时 p99 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 调用本身有短超时，慢被转成了失败，熔断其实是按失败率跳的
- QPS 太低，统计窗内攒不满最小请求数

怎么修：给熔断加慢调用判据，或用短于容忍度的超时把慢转成失败（改动层面：**config**）


### T-CIRCUIT-02　熔断打开后不能自动恢复

> 机制 `circuit breaker half-open`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：依赖早已恢复，调用方仍在熔断，必须重启实例才恢复调用——故障范围被自己的保护机制延长。

#### 一 规则

熔断打开后应在等待时长到期时自动进入半开并放行少量探测调用，依赖恢复即自行闭合，不需要人工干预。

依据：

- `azure-pattern-circuit-breaker`（Azure Architecture Center，Circuit Breaker pattern > Half-Open）— Circuit Breaker pattern
  > Half-Open: A limited number of requests from the application are allowed to pass through and invoke the operation. If these requests are successful, the circuit breaker assumes that the fault that caused the failure is fixed, and the circuit breaker switches to the Closed state.
- `azure-pattern-circuit-breaker`（Azure Architecture Center，Circuit Breaker pattern > Half-Open）— Circuit Breaker pattern
  > The Half-Open state helps prevent a recovering service from suddenly being flooded with requests.
- `resilience4j-circuitbreaker`（Resilience4j，CircuitBreaker > Failure rate and slow call rate thresholds）— CircuitBreaker
  > After a wait time duration has elapsed, the CircuitBreaker state changes from OPEN to HALF_OPEN and permits a configurable number of calls to see if the backend is still unavailable or has become available again.

#### 二 定位

适用范围：

- 对某个依赖启用了熔断或被动实例剔除

角色：脆弱点在 **熔断器的等待时长与半开探测配置**；故障加在 **该依赖**；异常显现在 **该服务对该依赖的调用量**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | waitDurationInOpenState、permittedNumberOfCallsInHalfOpenState、automaticTransitionFromOpenToHalfOpenEnabled | `resilience4j.circuitbreaker 配置` |
| Polly | BreakDuration 到期后进入半开 | `源码` |
| Envoy | outlier detection 的 base_ejection_time 到期后自动解除剔除 | `cluster.outlier_detection.base_ejection_time` |
| gobreaker | Settings.Timeout 决定 open 停留多久，Settings.MaxRequests 决定半开放行多少 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 熔断器被设成需要人工复位（FORCED_OPEN、等待时长缺失或设成极大值） | resilience4j.circuitbreaker.instances.*.[waitDurationInOpenState, permittedNumberOfCallsInHalfOpenState] |
| C2 | 反证 | `llm` | 存在外部的自动复位路径（定时任务、控制面下发规则） | 是否存在会在依赖恢复后自动复位该熔断器的代码或配置？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 附注 | `manifest` | 等待时长的取值（决定恢复观察窗口要开多长） | waitDurationInOpenState 或 base_ejection_time 的取值 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖不可达 | 离散·有时长 | `injection_site` | 先让依赖不可达足够长，确保熔断打开 | — |
| 依赖恢复 | 离散·无可比参数 | `injection_site` | 撤销注入，观察调用量是否自行回到基线 | — |

#### 四 判定

预期行为：依赖恢复后，在数倍等待时长之内调用量自行回到基线，无需重启实例或人工操作。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 熔断器状态变迁事件的时间线（OPEN → HALF_OPEN → CLOSED） | `metrics` |
| 依赖恢复时刻到调用量恢复时刻的间隔 | `metrics` |
| 半开期间放行的探测调用数 | `metrics` |
| 恢复期内被熔断拒绝的请求数是否归零 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 调用量恢复是因为实例被重启，而不是熔断自行闭合（需检查重启计数）
- 上游流量本身在此期间下降

怎么修：配置 open 等待时长与半开探测数，让熔断自动复位（改动层面：**config**）


### T-CIRCUIT-03　调不同依赖共用同一个资源池

> 机制 `bulkhead`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：只注入依赖 A 的延迟，与 A 完全无关的依赖 B 的调用也开始超时——故障跨依赖传播。

#### 一 规则

调用不同依赖所用的线程、连接与信号量应当彼此隔离，一个依赖变慢不能把共用池占光。

依据：

- `azure-pattern-bulkhead`（Azure Architecture Center，Bulkhead pattern > Solution）— Bulkhead pattern
  > A consumer can also partition resources to ensure that resources used to call one service don't affect the resources used to call another service. For example, a consumer that calls multiple services might be assigned a connection pool for each service. If a service begins to fail, it only affects the connection pool assigned for that service.
- `azure-pattern-bulkhead`（Azure Architecture Center，Bulkhead pattern > Context and problem）— Bulkhead pattern
  > When the consumer sends a request to a misconfigured or unresponsive service, the resources that the client's request uses might remain unavailable for an extended period. As requests to the service continue, those resources might be exhausted.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `maxConcurrentCalls` | 25 | 并发 | `resilience4j-bulkhead` |

#### 二 定位

适用范围：

- 一个进程同步调用两个及以上外部依赖

角色：脆弱点在 **该服务的线程池 / 连接池 / 信号量配置**；故障加在 **其中一个依赖**；异常显现在 **与被注入依赖无关的另一条业务路径**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | 是否每个依赖一个 Bulkhead 实例（SemaphoreBulkhead 或 FixedThreadPoolBulkhead） | `resilience4j.bulkhead 配置` |
| Istio | DestinationRule 的 connectionPool 是按 host 配置的，天然每上游一组配额 | `spec.trafficPolicy.connectionPool` |
| Envoy | circuit_breakers 阈值按 cluster 生效 | `cluster.circuit_breakers` |
| HikariCP | 每个数据源一个独立池，不要多库共用一个池 | `spring.datasource.*.hikari.maximumPoolSize` |
| Go net/http | 每个下游一个 http.Client / Transport，分别限 MaxConnsPerHost | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 多个依赖的出站调用走同一个线程池、连接池或同一个 http.Client | 起点为各出站客户端实例的构造点，查它们是否共享同一个池对象或执行器（0 跳，看构造与注入关系） |
| C2 | 必要 | `manifest` | 该共用池没有按依赖维度的并发上限 | 线程池与连接池的上限配置，以及是否存在按依赖划分的 bulkhead 配置 |
| C3 | 反证 | `manifest` | 各依赖已经各有独立的池或 bulkhead | resilience4j.bulkhead.instances 的键集合与依赖集合是否一一对应 |
| C4 | 附注 | `runtime` | 共用池的容量与各路径的基线并发（决定占满所需的注入幅值） | 无注入时各路径的并发数与池使用率 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 单个依赖变慢 | 连续幅值 | `injection_site` | 只对其中一个依赖注入网络延迟，另一条路径不动 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `P` | 共用池的容量 | manifest|default |
| `qa` | 被注入依赖那条路径的 QPS | measured |
| `ba` | 该路径的基线耗时 | measured |
| `qb` | 另一条路径的 QPS | measured |
| `bb` | 另一条路径的基线耗时 | measured |

- 触发边界：`d* = (P - qa * ba - qb * bb) / qa`
- 最坏情况倍数：`1`
- 保持时长：`2 * (P / qa)`
- 恢复观察窗：`2 * (P / qa)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：只有被注入的那条路径受影响，与它无关的另一条路径的成功率与耗时保持不变。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 未被注入的那条路径的成功率与 p99 | `metrics` |
| 共用池的使用率与等待队列长度 | `metrics` |
| 未被注入路径上出现的「获取连接超时」或「线程池拒绝」错误 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 两条路径其实共享同一个下游，影响是真实依赖关系而非池耦合
- 注入同时抬高了整机 CPU，影响是资源争抢而非池耦合

怎么修：每依赖独立资源池，并给每个池设并发上限（改动层面：**config**）


### T-CIRCUIT-04　到上游的并发上限沿用框架默认或被设成不限

> 机制 `concurrency limit`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：上游变慢后在途请求无限堆积，调用方的内存与线程被吃光，最后被 OOM 杀掉或整体无响应。

#### 一 规则

对每个上游的并发、连接与挂起请求数都应有上限，且取值要出自本进程的容量，而不是沿用框架默认或调成最大值。

依据：

- `envoy-circuit-breaking`（Envoy，Circuit breaking > Overview）— Circuit breaking
  > Circuit breakers are enabled by default and have modest default values, e.g. 1024 connections per cluster. To disable circuit breakers, set the thresholds to the highest allowed values.
- `resilience4j-bulkhead`（Resilience4j，Bulkhead > Create and configure a Bulkhead）— Bulkhead
  > maxConcurrentCalls | 25 | Max amount of parallel executions allowed by the bulkhead

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `envoy_max_connections` | 1024 | 连接 | `envoy-circuit-breaking` |
| `maxConcurrentCalls` | 25 | 并发 | `resilience4j-bulkhead` |

#### 二 定位

适用范围：

- 存在到某个上游的并发调用

角色：脆弱点在 **该上游对应的并发 / 连接 / 挂起请求上限配置**；故障加在 **该上游**；异常显现在 **该服务自身的内存与线程占用**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Envoy | cluster circuit_breakers 的 max_connections / max_pending_requests / max_requests / max_retries | `cluster.circuit_breakers.thresholds` |
| Istio | connectionPool.tcp.maxConnections 与 http.http1MaxPendingRequests / http2MaxRequests | `spec.trafficPolicy.connectionPool` |
| Resilience4j | Bulkhead.maxConcurrentCalls 与 maxWaitDuration | `resilience4j.bulkhead 配置` |
| Go net/http | Transport 的 MaxConnsPerHost；不设即无上限 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 并发或连接上限未显式设置，或被设成框架允许的最大值 | spec.trafficPolicy.connectionPool 与 cluster.circuit_breakers.thresholds[*].[max_connections, max_pending_requests, max_requests] |
| C2 | 必要 | `semgrep` | 代码侧的 HTTP / DB 客户端没有设每主机连接上限 | checkers/semgrep/go-http-client-no-timeout.yaml（同一处构造点同时看 MaxConnsPerHost）；其余语言交 llm |
| C3 | 反证 | `manifest` | 上游侧已有按调用方维度的限流，能替代调用方的并发上限 | 上游的限流规则是否按调用方维度配置 |
| C4 | 附注 | `manifest` | 该服务的线程数与内存限额（判断上限取值是否与容量相称） | spec.template.spec.containers[*].resources.limits 与线程池配置 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 上游变慢 | 连续幅值 | `injection_site` | 网络延迟，把在途请求数推高 | — |
| 入站流量抬升 | 连续幅值 | `manifest_site` | 提高该路径的入站 QPS，与延迟叠加逼近上限 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `C` | 到该上游的并发上限，未设时视为无穷 | manifest|default |
| `q` | 该路径的入站 QPS | measured |
| `b` | 该调用的基线耗时 | measured |
| `L` | 该容器的内存限额 | manifest |

- 触发边界：`d* = C / q - b`
- 最坏情况倍数：`1`
- 保持时长：`3 * (C / q)`
- 恢复观察窗：`2 * (C / q)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：上游变慢后在途请求数被压在上限处，超出的请求立即失败而不是无限堆积。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 到该上游的在途请求数是否停在某个值 | `metrics` |
| 并发上限溢出计数器（upstream_rq_pending_overflow 一类） | `metrics` |
| 该容器的内存用量与线程数是否随注入持续增长 | `metrics` |
| 是否出现 OOMKilled | `status` |

同一现象的其他解释（实验必须能排除）：

- 上限其实由上游的限流决定，不是调用方自己压住的
- 入站流量本身有限，还没到能撞上限的水位

怎么修：按本进程容量推导每上游并发上限，溢出即快速失败（改动层面：**config**）


### T-CIRCUIT-05　剔除比例上限与副本数不相容

> 机制 `outlier detection`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：副本少时一个坏实例摘不掉，错误率稳定卡在 1/n 不降；比例放大到 100% 后，全局性故障又会把整个上游摘空，本来还能处理部分请求的实例也拿不到流量。

#### 一 规则

一次最多能剔除的实例比例必须与副本数相容：既要保证单个坏实例摘得掉，也要保证全局性故障不会把整个上游摘空。

依据：

- `envoy-outlier-detection`（Envoy，Outlier detection > Ejection algorithm）— Outlier detection
  > It checks to make sure the number of ejected hosts is below the allowed threshold (specified via the outlier_detection.max_ejection_percent setting). If the number of ejected hosts is above the threshold, the host is not ejected.
- `istio-destinationrule`（Istio，DestinationRule > OutlierDetection > maxEjectionPercent）— DestinationRule reference (connectionPool, outlierDetection)
  > Maximum % of hosts in the load balancing pool for the upstream service that can be ejected. Defaults to 10%.
- `envoy-outlier-detection`（Envoy，Outlier detection > Ejection algorithm）— Outlier detection
  > An ejected host will automatically be brought back into service after the ejection time has been satisfied.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `maxEjectionPercent` | 10% | 比例 | `istio-destinationrule` |

#### 二 定位

适用范围：

- 上游服务有多个实例
- 启用了被动异常实例剔除

角色：脆弱点在 **该上游的 outlierDetection 配置与它的副本数**；故障加在 **该上游的一个实例（单实例故障）或全部实例（全局故障）**；异常显现在 **调用方看到的错误率与可用后端数**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Envoy | outlier_detection 的 consecutive_5xx、interval、base_ejection_time、max_ejection_percent | `cluster.outlier_detection` |
| Istio | outlierDetection 的 consecutive5xxErrors、baseEjectionTime、maxEjectionPercent、minHealthPercent | `spec.trafficPolicy.outlierDetection` |
| ingress-nginx | upstream 的被动失败计数与失败窗口 | `nginx.ingress.kubernetes.io/* 注解` |
| Spring Cloud LoadBalancer | 是否启用了基于健康检查的实例过滤，决定坏实例能否被客户端负载均衡摘掉 | `spring.cloud.loadbalancer.* 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 上游副本数 × maxEjectionPercent 小于 1，单个坏实例其实摘不掉 | spec.trafficPolicy.outlierDetection.maxEjectionPercent 与对应 Deployment 的 spec.replicas |
| C2 | 反证 | `manifest` | maxEjectionPercent 被设成 100%，单实例摘得掉，但此时应改看「全体被摘空」这一面 | spec.trafficPolicy.outlierDetection.maxEjectionPercent 的取值 |
| C3 | 附注 | `manifest` | minHealthPercent 的取值（决定全体不健康时是否还会继续剔除） | spec.trafficPolicy.outlierDetection.minHealthPercent |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 单实例持续返回错误 | 离散·有数量 | `injection_site` | 只让上游的一个实例返回 5xx，观察它是否被摘掉 | — |
| 全部实例同时变坏 | 离散·有时长 | `injection_site` | 让上游全部实例同时返回 5xx，观察是否出现「无可用后端」 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `n` | 上游副本数 | manifest |
| `P` | maxEjectionPercent | manifest|default |
| `k` | 触发剔除所需的连续错误数 | manifest|default |
| `I` | 检测间隔 | manifest|default |
| `E` | 基础剔除时长 | manifest|default |

- 触发边界：`d* = 1（注入一个坏实例即可；判定看 floor(n * P) 是否 ≥ 1）`
- 最坏情况倍数：`n`
- 保持时长：`k * I + E`
- 恢复观察窗：`2 * E`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：单个坏实例在若干次失败后被摘掉、剔除期满自动回来；全部实例同时变坏时仍保留可路由的后端。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 按上游实例分组的入站 QPS，坏实例是否归零 | `metrics` |
| 剔除与恢复事件的时间线 | `metrics` |
| 全体变坏时是否出现 no healthy upstream 类错误 | `logs` |
| 调用方错误率是否稳定在 1/n 附近（说明坏实例没被摘掉） | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 坏实例同时被就绪探针摘出了 EndpointSlice，剔除其实由探针完成
- 负载均衡算法本身把流量挪走了（如最少请求数）

怎么修：让 maxEjectionPercent × 副本数 ≥ 1，并配 minHealthPercent 防止摘空（改动层面：**config**）


---

## 机制组 `connection_lifecycle`


### T-CONN-01　长连接没有保活探测，死连接要等到请求超时才暴露

> 机制 `connection keepalive`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：对端消失后请求全部卡满整个超时才失败；或者低峰期过后第一批请求成片失败，重试一次又好了。

#### 一 规则

长连接应当有周期性的保活探测，使对端静默消失时连接能被及时判死并重建，而不是等到下一次请求超时才发现。

依据：

- `grpc-keepalive`（gRPC，Keepalive > Overview）— Keepalive
  > HTTP/2 PING-based keepalives are a way to keep an HTTP/2 connection alive even when there is no data being transferred. This is done by periodically sending a PING frame to the other end of the connection.
- `grpc-keepalive`（gRPC，Keepalive > Background）— Keepalive
  > TCP keepalive is a well-known method of maintaining connections and detecting broken connections.

#### 二 定位

适用范围：

- 该服务与下游之间使用长连接（HTTP/2、gRPC、数据库连接池、Redis 连接）
- 中间可能存在会静默丢弃连接的设备（云负载均衡、NAT 网关、防火墙）

角色：脆弱点在 **该客户端的保活参数**；故障加在 **该服务与下游之间的网络路径**；异常显现在 **该服务对下游调用的失败检测耗时**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | keepalive_time 与 keepalive_timeout 是否设置 | `源码（channel 参数）` |
| HikariCP | keepaliveTime 是否设置，用于对空闲连接做保活探测 | `spring.datasource.hikari.keepaliveTime` |
| Lettuce | 是否保留了默认的 PING 握手与自动重连 | `源码（ClientOptions）` |
| Node.js | http.Agent 的 keepAlive 与 keepAliveMsecs | `源码` |
| Envoy | 上游连接的 idle_timeout 与 HTTP/2 connection keepalive | `cluster 的 typed_extension_protocol_options` |
| StackExchange.Redis | AbortOnConnectFail 与 ConnectTimeout 决定连接不可用时是放弃还是后台重连 | `源码（ConfigurationOptions）` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 客户端没有启用保活探测（相关参数缺失或被显式关闭） | 客户端的 keepalive 相关配置项取值 |
| C2 | 必要 | `codegraph` | 该连接确实是长连接而非每次新建 | 起点为该客户端的构造点，检查它是否被复用（单例或池化）而不是每次调用新建 |
| C3 | 反证 | `manifest` | 请求超时已经足够短，靠它发现死连接的代价可以接受 | 该调用的请求超时值 |
| C4 | 附注 | `llm` | 中间设备的空闲断连时间（决定保活间隔的上界） | 该服务到下游之间是否经过会在空闲若干时间后断开连接的设备？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 对端静默消失 | 离散·有时长 | `injection_site` | 单向丢弃该服务到下游的报文，制造既不回包也不发 RST 的黑洞 | — |
| 空闲后首次调用 | 离散·无可比参数 | `injection_site` | 让连接空闲超过中间设备的断连时间，再发起一次调用 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `K` | 保活探测间隔，未启用时视为无穷 | manifest|default |
| `Kt` | 保活探测的等待上限 | manifest|default |
| `T` | 该调用的请求超时 | manifest|code|default |
| `N` | 中间设备的空闲断连时间 | measured|assumed_worst |

- 触发边界：`d* = N（空闲超过它即触发静默断连）；故障检测耗时应为 K + Kt 而不是 T`
- 最坏情况倍数：`1`
- 保持时长：`2 * max(K + Kt, T)`
- 恢复观察窗：`2 * (K + Kt)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：对端静默消失后，连接在保活探测的时间量级内被判死并重建，而不是让请求一直挂到超时。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 故障注入后首个失败请求的耗时（接近 K + Kt 还是接近 T） | `traces` |
| 连接重建计数 | `metrics` |
| 低峰期后首次调用的失败率 | `metrics` |
| 是否出现 GOAWAY 或 too_many_pings 类日志 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 请求超时本就很短，看不出保活与否的差别
- 客户端每次调用新建连接，本就不受保活影响

怎么修：启用保活探测，间隔短于中间设备的空闲断连时间（改动层面：**config**）


### T-CONN-02　池中连接的寿命长于对端允许的连接时限

> 机制 `connection max lifetime`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：低峰期过后第一批请求成片报连接重置，重试一次就好——每条坏连接换来一次失败，看起来像随机抖动。

#### 一 规则

池中连接的最长寿命必须短于对端（数据库、代理、网络设备）施加的连接时限，否则池里会留下已被对端单方面关闭的连接。

依据：

- `hikaricp`（HikariCP，HikariCP README > Essentials > maxLifetime）— HikariCP configuration
  > **We strongly recommend
  > setting this value, and it should be several seconds shorter than any database or infrastructure imposed
  > connection time limit.**
- `envoy-timeouts`（Envoy，Envoy timeouts > Connection timeouts）— FAQ: Envoy timeouts
  > The TCP proxy idle_timeout is the amount of time that the TCP proxy will allow a connection to exist with no upstream or downstream activity.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `hikari_maxLifetime` | 1800000 | ms | `hikaricp` |

#### 二 定位

适用范围：

- 该服务用连接池访问有连接时限或空闲断连策略的对端

角色：脆弱点在 **连接池的 maxLifetime / idleTimeout 配置**；故障加在 **该服务与对端之间的网络路径，或对端自身**；异常显现在 **该服务对该对端调用的失败率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| HikariCP | maxLifetime 需短于数据库的 wait_timeout 或云负载均衡的空闲断连时间 | `spring.datasource.hikari.maxLifetime` |
| go-redis | ConnMaxLifetime 与 ConnMaxIdleTime | `源码` |
| Go database/sql | SetConnMaxLifetime 与 SetConnMaxIdleTime | `源码` |
| Lettuce | 连接被对端关闭后是否会自动重连（autoReconnect） | `源码（ClientOptions）` |
| ioredis | connectTimeout 与 maxRetriesPerRequest 决定连接失效后的行为 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 没有设置连接最长寿命（缺失或设为 0，含义是无上限） | spring.datasource.hikari.maxLifetime 与源码里的 SetConnMaxLifetime 调用 |
| C2 | 必要 | `manifest` | 取用连接前没有可用性校验（没有 keepalive、没有 validation query、没有 PING 握手） | 连接池的连接校验相关配置项 |
| C3 | 反证 | `llm` | 客户端设置的寿命已经明显短于对端时限 | 该连接池的最长寿命是否小于对端施加的连接时限？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `runtime` | 对端的连接时限实测值 | 让连接空闲不同时长后取用，观察从多长的空闲开始出现连接重置 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 连接空闲超过对端时限 | 离散·有时长 | `injection_site` | 停止该路径的流量，空闲超过对端时限后再恢复流量 | — |
| 对端单方面关闭连接 | 离散·无可比参数 | `injection_site` | 在对端侧断开已建立的连接，不通知客户端 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `L` | 池的连接最长寿命，未设视为无穷 | manifest|code|default |
| `D` | 对端施加的连接时限 | measured|assumed_worst |
| `t` | 实际空闲时长 | measured |
| `N` | 池中连接数 | manifest|measured |

- 触发边界：`d* = D（空闲超过对端时限即触发；L > D 时池中连接必然命中已断连接）`
- 最坏情况倍数：`N`
- 保持时长：`D + 60`
- 恢复观察窗：`2 * D`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：恢复流量后首批请求正常返回，池能在取用前识别并替换掉已失效的连接。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 恢复流量后首批请求的失败率 | `metrics` |
| connection reset / broken pipe 类错误计数 | `logs` |
| 失败次数与池中连接数的关系（每条坏连接一次） | `metrics` |
| 池的连接回收与新建计数 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 对端确实在这段时间内不可用，失败与连接寿命无关
- 客户端有重试，掩盖了首次失败

怎么修：让池中连接寿命短于对端时限，并开启取用前的连接校验（改动层面：**config**）


### T-CONN-03　客户端保活参数与服务端允许的下限冲突

> 机制 `keepalive negotiation`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：空闲期间连接被服务端反复断开重建，日志里成片的 too_many_pings，业务请求在重建窗口内成批失败。

#### 一 规则

客户端的保活间隔必须落在服务端愿意接受的范围内，否则服务端会主动断开这些连接，保活反而变成故障源。

依据：

- `grpc-keepalive`（gRPC，Keepalive > How configuring keepalive affects a call）— Keepalive
  > It’s not required for service owners to support keepalive. Client authors must coordinate with service owners for whether a particular client-side setting is acceptable.

#### 二 定位

适用范围：

- 客户端启用了连接保活
- 服务端对保活频率有策略限制

角色：脆弱点在 **客户端的保活间隔与服务端的保活策略**；故障加在 **该服务与下游之间的连接**；异常显现在 **该服务对下游调用的失败率与连接重建频率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | 客户端 keepalive_time 是否小于服务端允许的最小间隔；触发时服务端回 GOAWAY 且 debug data 为 too_many_pings | `源码（客户端 channel 参数与服务端 keepalive enforcement 策略）` |
| Envoy | 作为客户端时的 HTTP/2 keepalive 设置与上游服务端策略的匹配 | `cluster 的 typed_extension_protocol_options` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 客户端保活间隔小于服务端声明的最小允许间隔 | 客户端 keepalive_time 与服务端 keepalive enforcement 的最小间隔配置 |
| C2 | 必要 | `manifest` | 客户端在没有在途请求时也发送保活（服务端策略对这种情况通常更严） | 客户端的 keepalive_without_calls 类参数取值 |
| C3 | 反证 | `llm` | 服务端没有启用保活频率限制 | 下游服务端是否配置了对客户端保活频率的限制？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 连接长时间空闲 | 离散·有时长 | `injection_site` | 让该路径长时间无请求，使客户端只发保活而不发业务请求 | — |
| 依赖变慢 | 连续幅值 | `injection_site` | 注入延迟延长在途时间，改变保活与业务请求的交错节奏 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `K` | 客户端保活间隔 | manifest|code|default |
| `Ks` | 服务端允许的最小保活间隔 | manifest|assumed_worst |
| `t_idle` | 连接的空闲时长 | measured |

- 触发边界：`d* = t_idle（空闲越久越容易只发保活）；K < Ks 时服务端会断开连接`
- 最坏情况倍数：`1`
- 保持时长：`4 * K`
- 恢复观察窗：`4 * K`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：空闲期间连接保持可用，不出现被服务端主动断开后又重建的循环。

看哪些信号：

| 信号 | 来源 |
|---|---|
| GOAWAY 事件计数与其 debug data 内容 | `logs` |
| 连接重建频率是否与保活间隔成比例 | `metrics` |
| 空闲期后首个请求的失败率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 连接重建来自服务端的滚动更新，而不是保活策略
- 中间设备断连（与 T-CONN-01 同源，需要用日志里的 GOAWAY 区分）

怎么修：与服务端对齐保活间隔，或关闭无在途请求时的保活（改动层面：**config**）


---

## 机制组 `deadline_timeout`


### T-DEADLINE-01　同步出站调用没有显式截止时间

> 机制 `request deadline`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：下游变慢后调用方的等待时长随注入幅值一路上涨、不在任何值处截断，线程与连接被长期占住。

#### 一 规则

每一个同步出站调用都必须显式设置截止时间；多数客户端的缺省行为是不设超时，等待可以无限长。

依据：

- `grpc-deadlines`（gRPC，Deadlines > Deadlines on the Client）— Deadlines
  > By default, gRPC does not set a deadline which means it is possible for a client to end up waiting for a response effectively forever. To avoid this you should always explicitly set a realistic deadline in your clients.
- `python-requests-advanced`（Python requests，Advanced Usage > Timeouts）— Advanced Usage (timeouts)
  > By default, requests do not time out unless a timeout value is set explicitly. Without a timeout, your code may hang for minutes or more.
- `php-guzzle`（Guzzle，Request Options > timeout）— Guzzle request options
  > Float describing the total timeout of the request in seconds. Use 0 to wait indefinitely (the default behavior).

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `envoy_route_timeout` | 15 | s | `envoy-timeouts` |
| `httpx_default_timeout` | 5 | s | `python-httpx-timeouts` |
| `guzzle_timeout` | 0 | s（0 表示不超时） | `php-guzzle` |
| `reqwest_timeout` | no timeout | — | `rust-reqwest` |

#### 二 定位

适用范围：

- 服务存在同步出站调用（HTTP / gRPC / 数据库 / 缓存）
- 该调用位于对外接口的请求处理路径上

角色：脆弱点在 **发起出站调用的客户端构造处与调用点**；故障加在 **被调用的下游服务或中间件**；异常显现在 **该服务自身，以及它的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | 调用点是否用 context.WithTimeout / CallOptions.withDeadlineAfter 设了 deadline | `源码` |
| Go net/http | http.Client.Timeout 是否设置，或请求是否带 deadline 的 context | `源码` |
| Python requests | requests 调用是否传了 timeout= | `源码` |
| Guzzle | 客户端或请求是否给了 timeout / connect_timeout 选项 | `源码` |
| reqwest | ClientBuilder 是否调用 timeout / connect_timeout | `源码` |
| .NET HttpClient | HttpClient.Timeout 是否被显式设置，或调用是否传 CancellationToken | `源码` |
| Envoy | 路由是否显式配置 timeout；未配置时落在 15 秒默认值上 | `route.timeout` |
| Istio | VirtualService 的 http.timeout 是否配置；默认不启用 | `spec.http[*].timeout` |
| Python httpx | 是否显式给了 Timeout(connect / read / write / pool)，还是靠 5 秒默认值 | `源码` |
| axios | 请求或实例是否设置了 timeout（缺省为 0，含义是不超时） | `源码` |
| undici | headersTimeout / bodyTimeout / connectTimeout 是否显式设置 | `源码` |
| Ruby Net::HTTP | open_timeout 与 read_timeout 是否显式设置 | `源码` |
| Spring Cloud OpenFeign | Request.Options 的 connectTimeout 与 readTimeout | `源码或 feign.client.config.* 配置` |
| MongoDB driver | 连接串的 connectTimeoutMS / socketTimeoutMS / serverSelectionTimeoutMS | `连接串` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 出站客户端构造处或调用点没有设置超时，也没有传带 deadline 的 context | checkers/semgrep/go-http-client-no-timeout.yaml、checkers/semgrep/python-requests-no-timeout.yaml、checkers/semgrep/php-guzzle-no-timeout.yaml、checkers/semgrep/rust-reqwest-no-timeout.yaml、checkers/semgrep/java-resttemplate-no-timeout.yaml、checkers/semgrep/node-axios-no-timeout.yaml、checkers/semgrep/dotnet-httpclient-no-timeout.yaml |
| C2 | 必要 | `codegraph` | 该调用确实在对外接口的请求路径上（不是启动期一次性调用或后台任务） | 起点为对外 HTTP/gRPC 路由的处理函数符号，沿调用边查 5 跳内是否到达 C1 命中的调用点 |
| C3 | 反证 | `manifest` | 网关或网格层已对这条路径设了更短的超时，实际等待被外层截断 | 与该服务对应的 VirtualService.spec.http[*].timeout 或 Envoy route.timeout |
| C4 | 附注 | `runtime` | 该调用的基线耗时（决定注入幅值的起点） | 无注入时该出站调用的 p99 耗时 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，限定到该服务与下游的 Pod 对与端口 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 丢弃该服务到下游的报文，制造既不回包也不拒绝的黑洞 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `T` | 该调用点实际生效的超时（含外层网关超时） | manifest|code|default |
| `b` | 该出站调用的基线耗时 p99 | measured |
| `U` | 上游对本服务的超时 | manifest|requirement|assumed_worst |
| `n` | 一次入站请求对该下游的串行调用次数 | measured|assumed_worst |

- 触发边界：`d* = T - b`
- 最坏情况倍数：`n`
- 保持时长：`max(T, U) + b`
- 恢复观察窗：`2 * (max(T, U) + b)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：下游变慢时调用方在自己的超时处截断并返回错误，占用的线程与连接随即释放。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 出站调用 span 的时长分布是否在某个值处截断 | `traces` |
| 出站调用的超时类错误码（DEADLINE_EXCEEDED / 504 / read timeout）计数 | `metrics` |
| 注入期间该服务的在途请求数与线程占用 | `metrics` |
| 上游对本服务的错误率与耗时 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 外层网关或网格的超时先于应用超时生效（需用反证项区分）
- 连接池耗尽导致请求在获取连接处失败，而不是在调用处超时
- 下游自己返回了错误，调用方并未真正等待

怎么修：在每个同步调用点显式设置连接超时与请求超时（改动层面：**code**）


### T-DEADLINE-02　出站截止时间不由入站剩余预算派生

> 机制 `deadline propagation`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：入口已经返回超时，链路深处仍在为这次请求继续调用和计算，过载时这部分是纯浪费的容量。

#### 一 规则

服务再去调别人时应当沿用入站请求的截止时间，而不是自己另发明一个；否则上游早已放弃，下游还在为这次请求干活。

依据：

- `sre-cascading-failures`（Google SRE，Latency and Deadlines > Deadline propagation）— SRE Book ch.22 Addressing Cascading Failures
  > Rather than inventing a deadline when sending RPCs to backends, servers should employ deadline propagation.
- `sre-cascading-failures`（Google SRE，Latency and Deadlines > Missing deadlines）— SRE Book ch.22 Addressing Cascading Failures
  > A common theme in many cascading outages is that servers spend resources handling requests that will exceed their deadlines on the client.
- `grpc-deadlines`（gRPC，Deadlines > Deadline Propagation）— Deadlines
  > Your server might need to call another server to produce a response. In these cases where your server also acts as a client you would want to honor the deadline set by the original client.

#### 二 定位

适用范围：

- 服务既接收同步请求又发起同步出站调用（调用链深度 ≥ 2）

角色：脆弱点在 **该服务的请求处理路径与出站调用点**；故障加在 **调用链上更深一层的服务或中间件**；异常显现在 **调用链的入口服务**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | Java 与 Go 默认继承入站 deadline；跨线程池提交任务或新建 context 时会丢 | `源码` |
| Go context | 出站调用用的 context 是否派生自 r.Context()，而不是 context.Background() | `源码` |
| Spring Boot | WebClient / RestClient 的 responseTimeout 是写死常量还是按剩余预算推导 | `源码与 spring.http.client.* 配置` |
| Istio | 网格只管本跳超时，不做跨跳预算传递，需要应用自己传 | `spec.http[*].timeout` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 请求处理路径上出现了与入站 context 无关的新建 context 或写死的超时常量 | checkers/semgrep/go-context-background-in-handler.yaml；Java / .NET 侧交 llm 复核 |
| C2 | 必要 | `codegraph` | 该服务确有更深一层的同步出站调用 | 起点为该服务的入站路由处理函数，沿调用边查 5 跳内是否到达出站客户端 |
| C3 | 反证 | `llm` | 出站超时的取值已经小于入站超时，即使不是派生出来的，实际也不会超出预算 | 该出站调用的超时值是否小于本服务对外承诺的响应时间上限？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | 入口对本服务的超时值（决定边界公式里的 B） | 入口网关或上游服务对该服务的 route timeout |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 链路末端变慢 | 连续幅值 | `injection_site` | 在调用链最深一跳注入网络延迟 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `B` | 入口对本服务的截止时间 | manifest|requirement |
| `e` | 本服务在发出该出站调用前已消耗的时间 | measured |
| `T` | 本服务给该出站调用设的超时 | manifest|code|default |
| `b` | 该出站调用的基线耗时 | measured |

- 触发边界：`d* = B - e - b`
- 最坏情况倍数：`1`
- 保持时长：`T + e`
- 恢复观察窗：`2 * (T + e)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：入口的截止时间一到，链路上各跳同时停止为这次请求工作。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 入口 span 已结束后，下游 span 仍在继续的时长 | `traces` |
| 入口返回超时错误的时刻与下游调用结束时刻之差 | `traces` |
| 入口超时之后下游仍产生的请求日志 | `logs` |
| 下游在入口放弃后的 CPU 与线程占用 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 链路中存在异步分支，本就不受入口截止时间约束
- 追踪采样导致 span 缺失，看起来像没有结束

怎么修：出站超时由入站剩余预算推导，全链路传递同一绝对截止时间（改动层面：**code**）


### T-DEADLINE-03　入口放弃后在途工作没有被取消

> 机制 `cancellation propagation`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：客户端早已超时离开，后台仍有成比例的孤儿请求在跑，过载时这些请求把线程池与下游容量占满，形成只出不进的空转。

#### 一 规则

调用方放弃之后，取消信号应当跨服务边界一路传到调用树底部，使各层停止为这次请求继续工作。

依据：

- `grpc-cancellation`（gRPC，Cancellation > 概述）— Cancellation
  > When an RPC is cancelled, the server should stop any ongoing computation and end its side of the stream. Often, servers are also clients to upstream servers, so that cancellation operation should ideally propagate to all ongoing computation in the system that was initiated due to the original client RPC call.
- `grpc-deadlines`（gRPC，Deadlines > Deadlines on the Server）— Deadlines
  > Please note that the server application is responsible for stopping any activity it has spawned to service the RPC. If your application is running a long-running process you should periodically check if the RPC that initiated it has been cancelled and if so, stop the processing.
- `go-context`（Go context，context package > Overview）— context package
  > A Context may be canceled to indicate that work done on its behalf should stop. A Context with a deadline is canceled after the deadline passes. When a Context is canceled, all Contexts derived from it are also canceled.
- `sre-cascading-failures`（Google SRE，Latency and Deadlines > Cancellation propagation）— SRE Book ch.22 Addressing Cascading Failures
  > Propagating cancellations reduces unneeded or doomed work by advising servers in an RPC call stack that their efforts are no longer necessary.

#### 二 定位

适用范围：

- 服务在一次入站请求内发起同步出站调用，或把工作提交到线程池、协程、异步任务
- 入口存在会导致客户端提前放弃的机制（超时、用户断开、对冲请求取消落选副本）

角色：脆弱点在 **该服务的请求处理路径与其向下的出站调用、任务提交点**；故障加在 **调用链更深一层的服务或中间件**；异常显现在 **调用链上被放弃请求仍在占用资源的各跳**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | 客户端 cancel 会向服务端发 CANCELLED；服务端须把同一 context 继续传给自己的出站调用 | `源码` |
| Go context | 处理函数把 r.Context() 一路传下去；中途换成 context.Background() 即断链 | `源码` |
| Node.js | AbortController 的 signal 是否传给下游 fetch / undici 请求 | `源码` |
| .NET HttpClient | CancellationToken 是否沿调用链传递，而不是每层新建 | `源码` |
| Spring Boot | 提交到 ExecutorService 或 @Async 的任务不会自动带上入站请求的取消信号 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 请求处理路径上存在断开取消链的写法（新建根 context、丢弃 CancellationToken、提交到不带取消的线程池） | checkers/semgrep/go-context-background-in-handler.yaml；Java / .NET / Node 侧交 llm 复核 |
| C2 | 必要 | `codegraph` | 断链之后确有耗时的下游调用或计算（否则取消与否看不出差别） | 起点为 C1 命中的断链位置，沿调用边查 4 跳内是否到达出站客户端或显式的长循环 |
| C3 | 反证 | `llm` | 下游调用自身的超时已经短于入口超时，即使取消不传播，工作也会很快自行结束 | 该断链之后的出站调用是否设置了小于入口超时的超时值？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `llm` | 吞掉取消异常的写法（catch CancelledError / InterruptedException 后继续执行） | 该处理路径是否在捕获取消类异常后继续执行后续步骤？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 客户端提前放弃 | 离散·无可比参数 | `manifest_site` | 在入口注入一个短于链路耗时的超时，或在压测客户端侧主动断开连接 | — |
| 链路末端变慢 | 连续幅值 | `injection_site` | 在最深一跳注入网络延迟，把链路耗时推过入口超时，从而稳定触发放弃 | — |

#### 四 判定

预期行为：入口放弃后的一个探针周期内，链路各跳都停止为这次请求工作，在途调用数回落到基线。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 入口返回错误之后，下游仍在进行的 span 数量与持续时长 | `traces` |
| 下游收到的取消信号计数（gRPC CANCELLED、客户端断开计数） | `metrics` |
| 入口放弃后下游的 CPU 占用与在途请求数是否回落 | `metrics` |
| 入口放弃后下游仍产生的业务日志 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 下游调用自身超时很短，工作本就会很快结束（需用反证项区分）
- 链路中存在设计上就该继续的异步分支（如落库后的事件投递）
- 追踪采样缺失，误判为「仍在进行」

怎么修：全链路传递取消信号，并在阻塞点与长循环里响应它（改动层面：**code**）


### T-DEADLINE-04　重试串的总耗时超出这条请求的截止时间

> 机制 `retry within deadline`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：上游的等待时长膨胀到「尝试次数 × 单次超时」，远超它自己声明的预算，而下游在同一次用户请求里被打了好几遍。

#### 一 规则

整串重试连同退避等待必须装进这次请求的总截止时间里，单次尝试的超时应由总预算推导，而不是与重试次数各自独立设定。

依据：

- `grpc-retry-grfc`（gRPC，gRFC A6 Client Retries > Hedging Policy）— gRFC A6: client retries
  > As with retries, gRPC call deadlines apply to the entire chain of hedged requests. Once a deadline has passed, the operation fails regardless of in-flight RPCS, and regardless of the hedging configuration.
- `istio-virtualservice`（Istio，VirtualService > HTTPRetry > attempts）— VirtualService reference (HTTPRetry, timeout)
  > When request timeout of the HTTP route or per_try_timeout is configured, the actual number of retries attempted also depends on the specified request timeout and per_try_timeout values.
- `envoy-route-retry`（Envoy，route_components.proto > RetryPolicy > num_retries）— HTTP route components (timeout, retry_policy)
  > (UInt32Value) Specifies the allowed number of retries. This parameter is optional and defaults to 1.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `envoy_num_retries` | 1 | 次 | `envoy-route-retry` |
| `envoy_route_timeout` | 15 | s | `envoy-timeouts` |

#### 二 定位

适用范围：

- 同一条出站路径上同时配置了重试与超时

角色：脆弱点在 **该路径的重试配置与超时配置**；故障加在 **被调用的下游服务**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Envoy | per_try_timeout 与 route.timeout 的关系；per_try_timeout × (1 + num_retries) 不应超过 route.timeout | `route.retry_policy 与 route.timeout` |
| Istio | HTTPRetry.perTryTimeout 与 http.timeout 的组合 | `spec.http[*].retries 与 spec.http[*].timeout` |
| gRPC | deadline 覆盖整串重试，maxAttempts 到不了就先 DEADLINE_EXCEEDED | `service config 的 retryPolicy` |
| Resilience4j | Retry 的 maxAttempts 与 intervalFunction 叠加后的总时长，对比 TimeLimiter 的 timeoutDuration | `resilience4j.retry 与 resilience4j.timelimiter 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | (1 + 最大重试次数) × 单次超时 + 累计退避 大于该路径的总截止时间 | spec.http[*].[timeout, retries.attempts, retries.perTryTimeout] |
| C2 | 必要 | `llm` | 该框架的 timeout 是单次语义而非整串语义（决定上式是否成立） | 该客户端或代理的 timeout 参数作用于单次尝试还是整串重试？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `manifest` | 外层已有一个更短的总截止时间，会先于重试串结束把请求截断 | 入口网关对该路径的 timeout 值 |
| C4 | 附注 | `manifest` | 退避序列的累计时长（无抖动时可由配置算出） | 重试配置里的 initialBackoff、backoffMultiplier、maxBackoff |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，幅值取到刚好超过单次超时，稳定触发每一次重试 | — |
| 依赖返回可重试错误 | 离散·有时长 | `injection_site` | 让下游在一段时间内稳定返回 503 之类的可重试状态码 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `D` | 该路径的总截止时间 | manifest|requirement |
| `t` | 单次尝试的超时 | manifest|default |
| `n` | 最大尝试次数（含首次） | manifest|default |
| `b` | 累计退避时长 | manifest|measured |
| `r` | 该调用的基线耗时 | measured |

- 触发边界：`d* = t - r`
- 最坏情况倍数：`n`
- 保持时长：`min(D, n * t + b)`
- 恢复观察窗：`2 * min(D, n * t + b)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：下游持续变慢时，上游的等待在总截止时间处截断，而不是累加到「次数 × 单次超时」。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 上游端到端耗时 p99 是否停在 D 附近还是停在 n × t 附近 | `traces` |
| 下游在一次入站请求内收到的尝试次数 | `traces` |
| 上游看到的错误码类型（总超时 还是 重试耗尽） | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 重试因为不可重试错误而提前终止，没有跑满次数
- 下游熔断打开导致尝试被本地拒绝，耗时反而变短

怎么修：用总截止时间约束整串重试，单次超时由总预算与次数推导（改动层面：**config**）


### T-DEADLINE-05　超时包装器之外底层 I/O 没有自己的超时

> 机制 `timeout enforcement`　缺陷类别 **实现错误型**　参数类型 **阈值型**

**违反后的运行时表现**：超时错误照常返回，线程池和连接池却持续被慢调用占着，最终整体不可用——负载看似被削掉，资源其实没有释放。

#### 一 规则

在阻塞调用外面套一层超时只让调用方不再等待，底层 I/O 必须另有自己的超时，否则工作线程在超时返回后仍被占着。

依据：

- `grpc-deadlines`（gRPC，Deadlines > Deadlines on the Server）— Deadlines
  > Please note that the server application is responsible for stopping any activity it has spawned to service the RPC.
- `resilience4j-timelimiter`（Resilience4j，TimeLimiter > Create and configure TimeLimiter）— TimeLimiter
  > whether cancel should be called on the running future
- `go-context`（Go context，context package > Overview）— context package
  > Failing to call the CancelFunc leaks the child and its children until the parent is canceled.

#### 二 定位

适用范围：

- 出站调用被容错库的超时或时间限制器包裹
- 被包裹的是阻塞式客户端调用（JDBC、阻塞 HTTP 客户端、同步 Redis 命令）

角色：脆弱点在 **超时装饰器与被包裹的底层客户端配置**；故障加在 **被调用的下游服务或中间件**；异常显现在 **该服务自身的线程池与连接池占用**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | TimeLimiter 的 cancelRunningFuture 是否开启；底层 HTTP / JDBC 客户端是否各自设了超时 | `resilience4j.timelimiter 配置与客户端构造代码` |
| Polly | Timeout 策略靠 CancellationToken 生效，被包裹的委托必须把 token 传到最底层 | `源码` |
| Go context | context 超时只关闭 Done 通道，底层调用必须使用 ctx 感知的 API | `源码` |
| HikariCP | 池的 connectionTimeout 只管取连接，查询本身要靠驱动的 socketTimeout | `spring.datasource.hikari.* 与 JDBC URL 参数` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 被包裹的底层客户端没有各自的连接超时与读写超时 | checkers/semgrep/go-sql-open-dsn-no-timeout.yaml、checkers/semgrep/java-resttemplate-no-timeout.yaml、checkers/semgrep/dotnet-httpclient-no-timeout.yaml |
| C2 | 必要 | `codegraph` | 外层确实存在一个超时装饰器（否则问题退化为 T-DEADLINE-01） | 起点为该出站调用点，向上查 3 跳内是否被 TimeLimiter / Polly Timeout / context.WithTimeout 包裹 |
| C3 | 反证 | `llm` | 被包裹的任务响应中断或取消（把 token / context 传到了最底层） | 被超时装饰器包裹的代码是否把取消信号传递给了底层 I/O 调用？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | 该服务的工作线程数或连接池大小（决定占满所需的并发量） | 线程池与连接池的上限配置 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，幅值取到明显大于外层超时 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `Tw` | 外层超时装饰器的超时值 | manifest|code |
| `Ti` | 底层 I/O 自己的超时，未设时视为无穷 | manifest|code|default |
| `b` | 该调用的基线耗时 | measured |
| `N` | 工作线程数或连接池上限 | manifest|default |
| `q` | 该路径的入站 QPS | measured |

- 触发边界：`d* = Tw - b`
- 最坏情况倍数：`1`
- 保持时长：`min(Ti, d) + Tw`
- 恢复观察窗：`2 * min(Ti, d)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：超时触发后，被占用的线程与连接在同一时间量级内释放，在途数回落。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 超时错误计数上升的同时，在途请求数与线程占用是否同步回落 | `metrics` |
| 超时返回之后仍保持 ESTABLISHED 的下游连接数 | `metrics` |
| 连接池等待队列长度与获取连接超时计数 | `metrics` |
| 超时返回后仍然出现的下游响应日志 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 线程占用上升来自入站请求堆积，而不是超时后未释放
- 连接池本身过小，问题出在获取连接而不是 I/O 未中断

怎么修：包装层超时之外，底层客户端也要设连接与读写超时，并把取消信号传到最底层（改动层面：**code**）


---

## 机制组 `delivery_semantics`


### T-DELIVERY-01　生产端的确认级别不足以保证已确认的写不丢

> 机制 `producer acknowledgement`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：主副本一挂，生产端已经收到成功确认的消息在切主后读不到了，而各项配置单独看都「合法」。

#### 一 规则

生产端的写确认必须要求复制到法定数量的副本，确认级别、最小同步副本数与副本因子三者要配套，否则「已确认」的消息在切主后仍可能丢失。

依据：

- `kafka-producer-config`（Kafka，Producer configs > acks）— Producer configs
  > acks=all This means the leader will wait for the full set of in-sync replicas to acknowledge the record. This guarantees that the record will not be lost as long as at least one in-sync replica remains alive.
- `kafka-topic-config`（Kafka，Topic configs > min.insync.replicas）— Topic configs
  > When a producer sets acks to "all" (or "-1"), this configuration specifies the minimum number of replicas that must acknowledge a write for the write to be considered successful.
- `rabbitmq-reliability`（RabbitMQ，Reliability Guide > Durability）— Reliability Guide
  > It's therefore critically important that durable queues (or replicated queue types covered below) are used for important data, and messages are published as persistent by publishers.

#### 二 定位

适用范围：

- 该服务向消息中间件生产不可丢失的消息

角色：脆弱点在 **生产端的确认配置与该主题的副本参数**；故障加在 **消息中间件的一个 broker 或分区主副本**；异常显现在 **消费端收到的消息序列**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kafka | producer 的 acks、topic 的 min.insync.replicas 与 replication.factor 三者的组合 | `producer 配置与 topic 配置` |
| RabbitMQ | 是否开启 publisher confirms，队列是否为 durable 或 quorum 类型 | `源码与队列声明参数` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 确认级别不要求全部同步副本（Kafka 的 acks 非 all，或 RabbitMQ 未开 publisher confirms） | producer 配置里的 acks 取值，以及队列声明时的 confirm 设置 |
| C2 | 必要 | `manifest` | min.insync.replicas 等于 1，或等于 replication.factor（前者不保证，后者一挂就不可写） | topic 配置的 min.insync.replicas 与 replication.factor |
| C3 | 反证 | `llm` | 该消息本就允许丢失（指标上报、可重算的派生数据） | 这条消息丢失是否会造成业务上不可接受的后果？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | unclean leader election 的开关状态（决定落后副本能否被选为主） | topic 配置的 unclean.leader.election.enable |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 分区主副本实例终止 | 离散·有数量 | `injection_site` | 在持续生产的同时删除承载该分区主副本的 broker 实例 | — |
| 副本之间网络分区 | 离散·有时长 | `injection_site` | 切断主副本与部分从副本之间的网络，制造同步副本集收缩 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `R` | 副本因子 | manifest |
| `M` | min.insync.replicas | manifest|default |
| `k` | 同时失效的副本数 | measured |
| `Q` | 法定数量 = floor(R/2)+1 | manifest |

- 触发边界：`d* = k；当 k > R - M 时写入应被拒绝，当 M = 1 且 k >= 1 时已确认的写可能丢失`
- 最坏情况倍数：`1`
- 保持时长：`120`
- 恢复观察窗：`300`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：少数副本失效时写入仍成功且已确认的消息不丢；失去法定数量时写入被明确拒绝，而不是静默接受后丢失。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 生产端收到成功确认的消息数与消费端最终读到的消息数之差 | `logs` |
| 生产端是否收到 NotEnoughReplicas 一类的明确错误 | `logs` |
| 注入期间同步副本集的大小变化 | `metrics` |
| 切主事件的时刻与新主的日志末端位置 | `events` |

同一现象的其他解释（实验必须能排除）：

- 消息丢失发生在消费侧（提交了位移却没处理完），而不是生产侧
- 生产端自己在超时后放弃了重发

怎么修：副本因子取奇数、min.insync.replicas 留一个副本余量、生产端要求全部同步副本确认（改动层面：**config**）


### T-DELIVERY-02　消费端在业务处理完成之前就确认了消息

> 机制 `consumer acknowledgement`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：消费者一重启，正在处理的那批消息就永远消失了，业务数据缺了一段却没有任何错误记录。

#### 一 规则

消费确认应当在业务处理成功之后发出；在处理完成前确认（自动确认或先提交位移）意味着消费者一旦中断，这些消息就再也不会被投递。

依据：

- `rabbitmq-confirms`（RabbitMQ，Consumer Acknowledgements and Publisher Confirms > Manual and automatic acknowledgement modes）— Consumer Acknowledgements and Publisher Confirms
  > In automatic acknowledgement mode, a message is considered to be successfully delivered immediately after it is sent. This mode trades off higher throughput (as long as the consumers can keep up) for reduced safety of delivery and consumer processing.
- `kafka-consumer-config`（Kafka，Consumer configs > enable.auto.commit）— Consumer configs
  > If true the consumer's offset will be periodically committed in the background.

#### 二 定位

适用范围：

- 该服务从消息中间件消费消息并产生业务副作用

角色：脆弱点在 **消费端的确认模式与确认时机**；故障加在 **该消费者实例**；异常显现在 **业务数据与消息积压**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| RabbitMQ | 消费时是否使用了自动确认模式（autoAck / no_ack） | `源码（basicConsume 的 autoAck 参数）` |
| Kafka | enable.auto.commit 是否为 true；手动提交是否在业务处理之后 | `consumer 配置与源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 使用了自动确认模式，或位移在业务处理之前提交 | consumer 配置的 enable.auto.commit，以及 RabbitMQ 消费注册时的 autoAck 参数 |
| C2 | 必要 | `codegraph` | 消费逻辑确实产生了外部副作用（落库、调下游），中断会造成真实损失 | 起点为消息处理函数，沿调用边查 4 跳内是否到达存储写入或出站调用 |
| C3 | 反证 | `llm` | 业务本身允许丢失这类消息（纯指标、可重算） | 这条消息未被处理是否会造成业务上不可接受的后果？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | 自动提交的间隔（决定丢失窗口的大小） | consumer 配置的 auto.commit.interval.ms |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 消费者实例终止 | 离散·有数量 | `injection_site` | 在消费者处理消息的过程中删除它的 Pod | — |
| 业务写入依赖不可达 | 离散·有时长 | `injection_site` | 让消费逻辑要写的存储不可达，使处理必然失败 | — |

#### 四 判定

预期行为：消费者中断或处理失败时，未处理完的消息会被重新投递，业务副作用最终仍然发生。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 投递出去的消息数与最终产生业务副作用的条数之差 | `logs` |
| 消费者重启后是否重新收到未处理完的消息 | `logs` |
| 消费位移的提交时刻与业务写入时刻的先后 | `traces` |
| 队列积压深度在注入前后的变化 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 消息确实被处理了，只是业务写入被后续逻辑回滚
- 生产端本就没有发出这些消息

怎么修：改用手动确认，在业务处理成功之后再确认或提交位移（改动层面：**code**）


### T-DELIVERY-03　消费失败无限重投，没有死信出口

> 机制 `dead letter`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：一条毒消息被无限重投，占满消费者并把正常消息饿死，队列积压持续上涨而死信目的地始终是空的。

#### 一 规则

反复处理失败的消息应当在有限次数后转入死信目的地，而不是无限重投堵住队列。

依据：

- `rabbitmq-dlx`（RabbitMQ，Dead Letter Exchanges > 概述）— Dead Letter Exchanges
  > Messages from a queue can be "dead-lettered", which means these messages are republished to an exchange when any of the following four events occur.
- `rabbitmq-confirms`（RabbitMQ，Consumer Acknowledgements and Publisher Confirms > Prefetch）— Consumer Acknowledgements and Publisher Confirms
  > Automatic acknowledgement mode or manual acknowledgement mode with unlimited prefetch should be used with care. Consumers that consume a lot of messages without acknowledging will lead to memory consumption growth on the node they are connected to.

#### 二 定位

适用范围：

- 消费侧存在失败后重投的路径

角色：脆弱点在 **队列或订阅的死信配置与最大重投次数**；故障加在 **队列中的一条会稳定处理失败的消息**；异常显现在 **该队列的积压深度与消费吞吐**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| RabbitMQ | 队列参数 x-dead-letter-exchange 与 x-dead-letter-routing-key；靠 reject 且 requeue=false 触发 | `队列声明参数` |
| Kafka | 无原生死信，需消费端自行在重试上限后投递到死信主题 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 队列没有配置死信目的地，或消费端没有最大重投次数 | 队列声明参数里的 x-dead-letter-exchange 与消费端的重试上限配置 |
| C2 | 必要 | `llm` | 消费失败走的是无限重投路径（requeue=true 或位移不前进） | 消费处理失败时，这条消息是否会被无限次重新投递？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `llm` | 重投计数随消息持久化，能够可靠地达到上限 | 重投次数是记录在消息属性里，还是只存在消费者进程内存中？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `manifest` | 消费者的并发度与预取数（决定一条毒消息能占住多少处理能力） | 消费端的并发消费者数与 prefetch 设置 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 注入一条必然处理失败的消息 | 离散·有数量 | `injection_site` | 向该队列投递一条消费端一定会抛异常的消息 | — |
| 消费者反复重启 | 离散·有数量 | `injection_site` | 在重投过程中反复删除消费者 Pod，检验重投计数是否被重置 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `k` | 最大重投次数，无上限时视为无穷 | manifest|code|default |
| `c` | 消费者并发度 | manifest|default |
| `p` | 单次处理耗时 | measured |
| `R` | 观察期内消费者重启次数 | measured |

- 触发边界：`d* = 1（一条毒消息即可触发）；判定看重投次数是否收敛到 k`
- 最坏情况倍数：`c`
- 保持时长：`k * p * 2`
- 恢复观察窗：`k * p * 2`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：毒消息在有限次重投后进入死信目的地，正常消息的处理不受影响。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 该消息的累计重投次数是否收敛 | `metrics` |
| 死信队列或死信主题是否收到它 | `logs` |
| 队列积压深度与正常消息的处理延迟 | `metrics` |
| 消费者重启后重投计数是否被清零 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 消息被人工从队列里清掉了
- 消费端把异常吞掉并直接确认，看起来像「没有无限重投」，实为丢消息

怎么修：配置死信目的地与最大重投次数，且重投计数随消息持久化（改动层面：**config**）


### T-DELIVERY-04　承载重要数据的队列或消息没有持久化

> 机制 `durability`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：中间件实例一重建，队列里积压的消息全部消失，生产端却已经把它们当成投递成功了。

#### 一 规则

承载不可丢失数据的队列与消息必须声明为持久的，否则中间件实例重启即丢。

依据：

- `rabbitmq-reliability`（RabbitMQ，Reliability Guide > Durability）— Reliability Guide
  > With some messaging protocols supported by RabbitMQ, applications control durability of queues and messages. It's therefore critically important that durable queues (or replicated queue types covered below) are used for important data, and messages are published as persistent by publishers.

#### 二 定位

适用范围：

- 该队列承载的消息丢失会造成业务损失

角色：脆弱点在 **队列与消息的持久化声明**；故障加在 **承载该队列的中间件实例**；异常显现在 **消费端收到的消息序列**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| RabbitMQ | 队列声明为 durable，消息投递时标记为 persistent；或改用 quorum 队列 | `源码（queueDeclare 的 durable 参数与消息属性）` |
| Kafka | 主题日志落在持久卷上，且副本因子大于 1 | `broker 的 log.dirs 与 topic 的 replication.factor` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `llm` | 队列声明为非持久，或消息未标记为持久 | 该队列声明时 durable 是否为 true，消息投递时是否标记为持久？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C2 | 必要 | `manifest` | 中间件的数据目录挂在临时存储上（容器层或 emptyDir） | 中间件工作负载的 spec.template.spec.volumes 与 volumeMounts |
| C3 | 反证 | `llm` | 该队列承载的是可重算或可丢弃的数据 | 该队列里的消息丢失是否会造成业务上不可接受的后果？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 中间件实例终止 | 离散·有数量 | `injection_site` | 在队列中有未消费消息时删除中间件实例的 Pod | — |

#### 四 判定

预期行为：中间件实例重建后，此前未消费的消息仍在队列里，消费端能继续处理。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 实例重建前后队列中未消费消息数的差 | `metrics` |
| 生产端已确认但消费端从未收到的消息条数 | `logs` |
| 中间件数据目录对应的卷类型 | `status` |

同一现象的其他解释（实验必须能排除）：

- 消息在注入前已被消费完，本就没有待丢的数据
- 生产端在实例重启期间自行重发，掩盖了丢失

怎么修：队列与消息都声明持久化，数据目录挂持久卷，重要数据用复制型队列（改动层面：**config**）


---

## 机制组 `fallback_degradation`


### T-FALLBACK-01　非关键依赖失败导致整个响应失败

> 机制 `graceful degradation`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：一个可有可无的依赖挂掉，整个接口返回 5xx，用户看到的是整页失败而不是少了一个模块。

#### 一 规则

非关键依赖失败时应当只裁剪掉它负责的那部分结果，而不是让整个响应失败。

依据：

- `sre-cascading-failures`（Google SRE，Preventing Server Overload > Load Shedding and Graceful Degradation）— SRE Book ch.22 Addressing Cascading Failures
  > Graceful degradation takes the concept of load shedding one step further by reducing the amount of work that needs to be performed. In some applications, it’s possible to significantly decrease the amount of work or time needed by decreasing the quality of responses.
- `aws-war-reliability`（AWS Well-Architected，Reliability Pillar > 优雅降级最佳实践）— Reliability Pillar: graceful degradation
  > Implement graceful degradation to transform applicable hard dependencies into soft dependencies

#### 二 定位

适用范围：

- 一次响应聚合了两个及以上依赖的结果
- 其中至少一个依赖在业务上是可缺省的

角色：脆弱点在 **聚合响应的处理函数及其异常处理**；故障加在 **该非关键依赖**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | 非关键依赖是否被单独装饰并给了 fallback，而不是让异常冒泡 | `源码` |
| Spring Boot | 聚合接口对非关键字段的异常是否单独捕获并返回部分结果 | `源码` |
| Envoy | 是否对非关键上游单独设更短超时与更激进的熔断 | `route.timeout 与 cluster.outlier_detection` |
| Polly | Fallback 策略是否只包住非关键调用 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 非关键依赖的调用没有被单独捕获，异常直接冒泡到整体失败 | 起点为聚合接口的处理函数，沿调用边找到各依赖调用点，检查每个调用点是否处在独立的异常处理块内 |
| C2 | 必要 | `llm` | 代码或配置里存在关键与非关键依赖的显式区分（没有这个区分就无从判断哪些该裁剪） | 该聚合接口是否对不同依赖做了关键性区分（独立装饰、独立捕获或注解标注）？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `llm` | 该依赖在业务上是关键的，失败时整体失败是正确行为 | 缺少该依赖的结果时，这个接口的响应是否仍对调用方有用？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 非关键依赖不可达 | 离散·有时长 | `injection_site` | 只让这一个依赖不可达，其余依赖保持正常 | — |
| 非关键依赖变慢 | 连续幅值 | `injection_site` | 只对该依赖注入延迟，检查是否把整体响应拖到超时 | — |

#### 四 判定

预期行为：非关键依赖完全不可用时，接口整体成功率基本不变，只是响应里少了对应字段。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入期间该接口的整体成功率 | `metrics` |
| 响应体中对应字段缺失或为默认值的比例 | `logs` |
| 该接口的 p99 延迟是否随非关键依赖的延迟同步上升 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 该依赖其实是关键依赖，整体失败是预期行为
- 上游有缓存，掩盖了后端的失败

怎么修：区分关键与非关键依赖，非关键失败只裁剪对应结果（改动层面：**code**）


### T-FALLBACK-02　缓存兜底只在一个方向上成立

> 机制 `cache fallback`　缺陷类别 **组合型**　参数类型 **离散动作**

**违反后的运行时表现**：缓存一挂源被全量流量瞬间打死；或者源一挂，明明缓存里还有数据却直接返回错误——两个方向只要有一个不成立，缓存就不是韧性手段而是新的单点。

#### 一 规则

把缓存当作韧性手段时，源不可用要能返回过期值，缓存不可用要能穿透到源；同时源的容量还得扛得住缓存全空。

依据：

- `azure-pattern-cache-aside`（Azure Architecture Center，Cache-Aside pattern > Reliability）— Cache-Aside pattern
  > Caching replicates data. In limited ways, it can preserve the availability of frequently accessed data if the origin data store becomes temporarily unavailable.
- `sre-cascading-failures`（Google SRE，Slow Startup and Cold Caching）— SRE Book ch.22 Addressing Cascading Failures
  > It’s important to note the distinction between a latency cache versus a capacity cache: when a latency cache is employed, the service can sustain its expected load with an empty cache, but a service using a capacity cache cannot sustain its expected load under an empty cache.

#### 二 定位

适用范围：

- 该服务在读路径上使用了缓存

角色：脆弱点在 **读路径上的缓存访问与回源逻辑**；故障加在 **缓存实例，或缓存背后的源存储**；异常显现在 **该服务的上游调用方，以及源存储的入站 QPS**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| go-redis | 缓存命令报错时是否穿透到源，还是把错误直接抛给调用方 | `源码` |
| Jedis | 同上；另看池耗尽时的异常是否被当成业务失败 | `源码` |
| Spring Boot | 源不可用时是否返回缓存中的过期值（stale-while-revalidate 语义） | `源码` |
| Lettuce | 命令超时后的重连行为是否让读路径整体失败 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 缓存访问异常没有被捕获成「未命中」，而是直接失败 | 起点为缓存客户端调用点，向上查 2 跳内是否存在把缓存异常转成未命中的处理分支 |
| C2 | 必要 | `llm` | 源不可用时没有返回过期值的路径（只有命中或回源两种结果） | 源存储不可用时，该读路径是否会返回缓存里已过期的数据？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `manifest` | 源侧配置了准入控制或限流，缓存全空时源不会被瞬间打垮 | 源存储前的限流配置或连接数上限 |
| C4 | 附注 | `runtime` | 缓存命中率与源容量（判断这是延迟型缓存还是容量型缓存） | 稳态缓存命中率，以及源在缓存全空时需要承担的 QPS |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 缓存不可达 | 离散·有时长 | `injection_site` | 让缓存实例不可达，观察读路径是失败还是穿透 | — |
| 源不可达 | 离散·有时长 | `injection_site` | 让源存储不可达，观察是否还能返回缓存里的值 | — |

#### 四 判定

预期行为：两个方向分别注入时，读路径都还能工作：源挂了返回过期值，缓存挂了穿透到源且源扛得住。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 两种注入下该读接口的成功率 | `metrics` |
| 缓存不可用期间源存储的入站 QPS 相对基线的倍数 | `metrics` |
| 源不可用期间返回结果的新鲜度标记或版本 | `logs` |
| 源存储在穿透期间的错误率与延迟 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 缓存命中率本就很低，穿透带来的放大不明显
- 上游重试掩盖了首次失败

怎么修：明确缓存是延迟型还是容量型，支持返回过期值并按空缓存备容量（改动层面：**code**）


### T-FALLBACK-03　回退路径自己也依赖会一起失败的对象

> 机制 `fallback path`　缺陷类别 **实现错误型**　参数类型 **离散动作**

**违反后的运行时表现**：真出故障时回退路径自己也炸了，或者慢到把上游一起拖垮——平时不走的分支，等到要用的时候才发现不能用。

#### 一 规则

回退路径不应依赖与主路径同时失效的对象；平时不走的回退分支很容易成为只在故障时才暴露的隐患。

依据：

- `aws-builders-avoiding-fallback`（AWS Builders Library，Avoiding fallback in distributed systems > Single-machine fallback）— Avoiding fallback in distributed systems
  > Not only might the fallback strategy make the problem worse, this will likely occur as a latent bug. It is easy to develop fallback strategies that rarely trigger in production.
- `aws-builders-avoiding-fallback`（AWS Builders Library，Avoiding fallback in distributed systems > How Amazon avoids fallback）— Avoiding fallback in distributed systems
  > Instead, we favor code paths that are exercised in production continuously rather than rarely.
- `sre-cascading-failures`（Google SRE，Preventing Server Overload > Load Shedding and Graceful Degradation）— SRE Book ch.22 Addressing Cascading Failures
  > Remember that the code path you never use is the code path that (often) doesn’t work.
- `chaos-principles`（Principles of Chaos Engineering，Principles of Chaos Engineering > 开篇）— Principles of Chaos Engineering
  > Systemic weaknesses could take the form of: improper fallback settings when a service is unavailable; retry storms from improperly tuned timeouts; outages when a downstream dependency receives too much traffic; cascading failures when a single point of failure crashes; etc.

#### 二 定位

适用范围：

- 该服务对某个依赖配置了回退分支（fallback 方法、降级返回、备用数据源）

角色：脆弱点在 **回退分支的实现**；故障加在 **主路径依赖，以及回退分支自己依赖的对象**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Resilience4j | CircuitBreaker / Retry 的 fallback 方法内部是否又发起远程调用 | `源码` |
| Polly | Fallback 策略的委托内部是否又访问了可能同时失效的资源 | `源码` |
| Spring Boot | 降级分支是否读同一个数据库或同一个缓存 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 回退分支内部发起了远程调用或访问了外部资源 | 起点为 fallback 方法符号，沿调用边查 3 跳内是否到达任一出站客户端 |
| C2 | 必要 | `llm` | 回退分支访问的对象与主路径失败的原因相关（同一实例、同一网络路径、同一存储） | 回退分支访问的外部对象是否与主路径依赖同一个实例或同一条网络路径？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `codegraph` | 回退分支只返回本地常量、本地缓存或静态默认值 | 起点为 fallback 方法符号，查 3 跳内是否完全没有出站调用 |
| C4 | 附注 | `runtime` | 回退分支在稳态下是否有执行记录（长期为零说明它从未被验证过） | 稳态下 fallback 分支的执行计数 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 主路径依赖不可达 | 离散·有时长 | `injection_site` | 让主依赖不可达，稳定触发回退分支 | — |
| 主依赖与回退依赖同时不可达 | 离散·有时长 | `injection_site` | 若两者共用同一实例或同一网络路径，一次注入即可同时命中 | — |

#### 四 判定

预期行为：触发回退后，回退分支能成功返回，且耗时与主路径同量级。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 回退分支的执行计数与其中的失败计数 | `metrics` |
| 触发回退后该接口的端到端耗时 | `traces` |
| 回退分支产生的出站调用数 | `traces` |
| 触发回退后上游看到的错误率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 回退失败是因为它依赖的对象恰好也在维护，属偶发
- 回退分支根本没被触发（熔断未打开），观察到的失败来自主路径

怎么修：回退只用本地可得的数据；做不到就去掉回退、加固主路径（改动层面：**code**）


---

## 机制组 `health_probe`


### T-PROBE-01　存活探针的判定耦合进程外依赖

> 机制 `liveness probe`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖变慢十几秒，进程健康的容器被重启，随后被就绪探针初始延迟拖成分钟级不可用。

#### 一 规则

存活探针的判定不应依赖进程外的对象；依赖是否可用由就绪探针检查。

依据：

- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Types of probe > Liveness probe）— Liveness, Readiness, and Startup Probes
  > When your app has a strict dependency on back-end services, you can implement both a liveness and a readiness probe. The liveness probe passes when the app itself is healthy, but the readiness probe additionally checks that each required back-end service is available.
- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Liveness probe）— Liveness, Readiness, and Startup Probes
  > If a container fails its liveness probe more times than the configured tolerance, the kubelet restarts that container.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `timeoutSeconds` | 1 | s | `k8s-probes-concept` |
| `periodSeconds` | 10 | s | `k8s-probes-concept` |
| `failureThreshold` | 3 | 次 | `k8s-probes-concept` |

#### 二 定位

适用范围：

- 容器声明了 livenessProbe（httpGet / exec / grpc / tcpSocket 任一）
- 该容器所属服务在依赖图上有出边指向进程外对象（数据库、缓存、消息中间件、其他服务）

角色：脆弱点在 **该服务的探针配置与探针端点的处理函数**；故障加在 **该服务的进程外依赖**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | livenessProbe.httpGet.path 指向的端点、exec 指向的脚本、grpc 指向的健康服务 | `spec.template.spec.containers[*].livenessProbe` |
| Spring Boot Actuator | liveness 分组包含的 HealthIndicator；默认只含 livenessState，把数据库等指示器加进去即耦合 | `management.endpoint.health.group.liveness.include` |
| Go net/http | 与探针路径对应的处理函数（HandleFunc 或路由库注册）里是否发起出站调用 | `源码` |
| ASP.NET Core | MapHealthChecks 的 Predicate 或 tags 过滤是否把依赖检查放进了存活端点 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 探针端点的处理函数同步访问进程外对象（数据库 ping、HTTP/gRPC 调用、缓存命令） | 起点为 livenessProbe 路径对应的处理函数符号，沿调用边查 3 跳内是否到达出站客户端（sql/http/grpc/redis 客户端） |
| C2 | 必要 | `semgrep` | 该访问没有短于 timeoutSeconds 的等待上限 | checkers/semgrep/go-sql-open-dsn-no-timeout.yaml、checkers/semgrep/go-http-client-no-timeout.yaml、checkers/semgrep/python-requests-no-timeout.yaml、checkers/semgrep/java-health-indicator-external-call.yaml、checkers/semgrep/dotnet-healthcheck-external-call.yaml；命中不确定时交 llm 复核是否被带超时的中间件包裹 |
| C3 | 反证 | `manifest` | 存活探针指向的是只查进程自身状态的端点（Spring 的 livenessState、独立的 /livez） | spec.template.spec.containers[*].livenessProbe.httpGet.path |
| C4 | 附注 | `runtime` | 依赖失败时该端点的返回状态是否变化（决定「依赖不可达」这个动作能否触发） | 注入依赖不可达后观察探针端点返回码是否由 2xx 变为非 2xx |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，限定到该服务与依赖的 Pod 对与端口 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 丢弃该服务到依赖的报文，或让依赖端口拒绝连接 | C4 成立 |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `T` | timeoutSeconds | manifest|default |
| `P` | periodSeconds | manifest|default |
| `F` | failureThreshold | manifest|default |
| `b` | 探针处理函数的基线耗时 | measured |
| `n` | 一次探针调用对依赖的往返次数 | measured|assumed_worst |

- 触发边界：`d* = T - b`
- 最坏情况倍数：`n`
- 保持时长：`(F + 1) * P + T`
- 恢复观察窗：`readinessProbe.initialDelaySeconds + hold`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：依赖变慢时实例可被就绪探针摘出流量，但进程自身健康的容器不被重启。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入窗内连续 ≥ F 次探针失败事件 | `events` |
| 容器重启计数 +1，且 Killing 事件消息为 failed liveness probe | `events` |
| 终止原因非 OOMKilled；无 Pod 删除或驱逐事件 | `status` |
| 同期容器资源用量在限额之内 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 内存溢出被 OOMKilled
- 人工删除或节点驱逐
- 只被就绪探针摘流而未重启

怎么修：存活探针只查进程自身；依赖检查移到就绪探针（改动层面：**config**）

佐证（只作优先级参考，不是规则依据）：
- [etcd-io/etcd#13340](https://github.com/etcd-io/etcd/issues/13340)


### T-PROBE-02　接收流量的容器没有就绪探针

> 机制 `readiness probe`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：实例还没准备好或已经不能服务，却一直留在 Endpoints 里，持续吃掉一份流量并向上游返回错误。

#### 一 规则

会被路由到的容器必须声明就绪信号，使暂时不能服务的实例被摘出流量而不是被杀掉。

依据：

- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Types of probe > Readiness probe）— Liveness, Readiness, and Startup Probes
  > Readiness probes determine when a container is ready to accept traffic. This is useful when waiting for an application to perform time-consuming initial tasks, such as establishing network connections, loading files, and warming caches.
- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Types of probe > Readiness probe）— Liveness, Readiness, and Startup Probes
  > If the readiness probe returns a failed state, the EndpointSlice controller removes the Pod's IP address from the EndpointSlices of all Services that match the Pod.
- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability 检查表）— Polaris Checks: Reliability
  > readinessProbeMissing | warning | Fails when a readiness probe is not configured for a pod.

#### 二 定位

适用范围：

- 容器所属工作负载被某个 Service 的 selector 选中
- 该容器对外提供同步接口（有 containerPort 且被 Service 引用）

角色：脆弱点在 **该容器的探针配置**；故障加在 **该服务自身或它的进程外依赖**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | 容器是否声明 readinessProbe | `spec.template.spec.containers[*].readinessProbe` |
| Spring Boot Actuator | 是否暴露 /actuator/health/readiness 并被探针引用 | `management.endpoint.health.group.readiness.include` |
| ASP.NET Core | 是否用 tags 区分出一个只给就绪用的端点 | `源码（MapHealthChecks 的 Predicate）` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 被 Service 选中的容器没有声明 readinessProbe | spec.template.spec.containers[?readinessProbe==null].name |
| C2 | 反证 | `manifest` | 该工作负载不接收同步流量（无 Service 选中，或只跑批处理） | spec.template.metadata.labels 与集群内各 Service 的 spec.selector 是否有交集 |
| C3 | 附注 | `llm` | 应用是否有能反映「暂时不能服务」的内部状态（否则就算加了探针也恒返回就绪） | 该服务是否存在依赖不可用时仍返回 200 的健康端点？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖不可达 | 离散·有时长 | `injection_site` | 丢弃该服务到依赖的报文 | — |
| 实例重启 | 离散·有数量 | `defect_site` | 删除该服务的一个 Pod，观察新实例在未就绪期间是否已被打流量 | — |

#### 四 判定

预期行为：实例在不能服务的窗口内被摘出 EndpointSlice，上游看到的错误率不随之上升。

看哪些信号：

| 信号 | 来源 |
|---|---|
| EndpointSlice 中该 Pod 地址在故障窗内被移除 | `status` |
| 上游对该服务的 5xx 或连接失败计数 | `metrics` |
| 新实例启动期间被路由到的请求数 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 上游自身已有熔断或异常实例剔除，掩盖了未摘流的影响
- Service 使用了 headless 模式，路由不经 EndpointSlice

怎么修：为接流量的容器声明就绪探针，判据覆盖依赖不可用与预热未完成（改动层面：**config**）


### T-PROBE-03　慢启动容器没有用启动探针兜住

> 机制 `startup probe`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖一变慢，新实例就在启动完成前被存活探针杀掉，反复 CrashLoopBackOff，副本数越滚越少。

#### 一 规则

初始化明显长于稳态响应时间的容器必须用启动探针覆盖最坏启动时长，而不是把存活探针的容忍度放宽。

依据：

- `k8s-probes-task`（Kubernetes，Configure Liveness, Readiness and Startup Probes > Protect slow starting containers with startup probes）— Configure Liveness, Readiness and Startup Probes
  > The solution is to set up a startup probe with the same command, HTTP or TCP check, with a failureThreshold * periodSeconds long enough to cover the worst case startup time.
- `k8s-probes-task`（Kubernetes，Configure Liveness, Readiness and Startup Probes > Protect slow starting containers with startup probes）— Configure Liveness, Readiness and Startup Probes
  > Once the startup probe has succeeded once, the liveness probe takes over to provide a fast response to container deadlocks. If the startup probe never succeeds, the container is killed after 300s and subject to the pod's restartPolicy.
- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Types of probe > Startup probe）— Liveness, Readiness, and Startup Probes
  > If a startup probe is configured, Kubernetes does not execute liveness or readiness probes until the startup probe succeeds, allowing the application time to finish its initialization.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `periodSeconds` | 10 | s | `k8s-probes-concept` |
| `failureThreshold` | 3 | 次 | `k8s-probes-concept` |

#### 二 定位

适用范围：

- 容器声明了 livenessProbe
- 容器没有声明 startupProbe
- 该容器在启动路径上需要连接进程外依赖或做预热（建连接池、载缓存、JIT 预热）

角色：脆弱点在 **该容器的 startupProbe 与 livenessProbe 配置**；故障加在 **该服务在启动路径上依赖的进程外对象**；异常显现在 **该服务自身的就绪副本数**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | startupProbe 的 failureThreshold × periodSeconds 是否覆盖最坏启动时长 | `spec.template.spec.containers[*].startupProbe` |
| Spring Boot Actuator | 启动期 readiness 未就绪；若无 startupProbe，liveness 会在启动完成前开始计数 | `management.endpoint.health.group.readiness.include` |
| JVM | 类加载与 JIT 预热让首次启动明显慢于稳态，是这条规则的典型触发场景 | `容器启动参数` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 容器有 livenessProbe 但没有 startupProbe | spec.template.spec.containers[?livenessProbe!=null && startupProbe==null].name |
| C2 | 必要 | `codegraph` | 启动路径上存在对进程外依赖的同步等待（依赖变慢会把启动时长推高） | 起点为 main / ApplicationRunner / init 容器入口符号，沿调用边查 4 跳内是否到达出站客户端的建连或校验调用 |
| C3 | 反证 | `manifest` | livenessProbe 的 initialDelaySeconds 已经大于最坏启动时长 | spec.template.spec.containers[*].livenessProbe.initialDelaySeconds |
| C4 | 附注 | `runtime` | 最坏启动时长的实测值（决定注入幅值） | 冷启动（缓存空、依赖正常）下从容器启动到首次就绪的耗时 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 启动期依赖变慢 | 连续幅值 | `injection_site` | 先注入延迟，再删除该服务的一个 Pod，使新实例在启动路径上撞上慢依赖 | — |
| 实例重启 | 离散·有数量 | `defect_site` | 删除 Pod 触发重建 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `S` | 冷启动下的最坏启动时长 | measured |
| `I` | livenessProbe.initialDelaySeconds | manifest|default |
| `P` | livenessProbe.periodSeconds | manifest|default |
| `F` | livenessProbe.failureThreshold | manifest|default |
| `k` | 启动路径上对该依赖的串行等待次数 | measured|assumed_worst |

- 触发边界：`d* = (I + F * P - S) / k`
- 最坏情况倍数：`k`
- 保持时长：`I + (F + 1) * P`
- 恢复观察窗：`2 * (I + (F + 1) * P)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：启动变慢只推迟就绪时间，容器不会在启动完成前被存活探针杀掉。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 容器重启计数在注入窗内增加，Killing 事件消息为 failed liveness probe | `events` |
| Pod 进入 CrashLoopBackOff | `status` |
| 该工作负载的就绪副本数在注入窗内跌到 0 | `status` |

同一现象的其他解释（实验必须能排除）：

- 镜像拉取失败或配置错误导致的启动失败
- 节点资源不足导致容器被驱逐
- 应用自身在依赖不可用时主动退出（与探针无关）

怎么修：增加 startupProbe，failureThreshold × periodSeconds 覆盖最坏启动时长（改动层面：**config**）


### T-PROBE-04　存活探针与就绪探针用同一个判据

> 机制 `liveness probe`　缺陷类别 **实现错误型**　参数类型 **离散动作**

**违反后的运行时表现**：依赖抖一下本该只摘流，结果容器被重启，重启又带来冷启动，恢复反而更慢。

#### 一 规则

存活与就绪不应使用同一个判据，否则凡是该摘流量的情形都会顺带触发重启。

依据：

- `kube-score-checks`（kube-score，kube-score checks 列表）— kube-score checks list
  > | pod-probes-identical | Pod | Makes sure that readiness and liveness probes are not identical | default |
- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Types of probe > Liveness probe）— Liveness, Readiness, and Startup Probes
  > Liveness probes do not wait for readiness probes to succeed.

#### 二 定位

适用范围：

- 容器同时声明了 livenessProbe 与 readinessProbe

角色：脆弱点在 **该容器的两个探针配置及其指向的端点**；故障加在 **该服务的进程外依赖**；异常显现在 **该服务自身的就绪副本数与上游错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | 两个探针的 httpGet.path / exec.command / tcpSocket.port 是否完全相同 | `spec.template.spec.containers[*].livenessProbe 与 .readinessProbe` |
| Spring Boot Actuator | 两个探针是否都指向 /actuator/health（而不是分别指向 liveness 与 readiness 分组） | `management.endpoint.health.group` |
| ASP.NET Core | 两个端点是否用同一个 Predicate，没有靠 tags 区分 | `源码（MapHealthChecks）` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 两个探针的判定目标完全相同（同一路径、同一命令或同一端口） | spec.template.spec.containers[*].[livenessProbe.httpGet.path, readinessProbe.httpGet.path] |
| C2 | 反证 | `codegraph` | 虽然路径相同，但该端点只反映进程自身状态，不触达任何进程外依赖 | 起点为该路径对应的处理函数符号，沿调用边查 3 跳内是否到达出站客户端；未到达则本模板不适用 |
| C3 | 附注 | `manifest` | 两个探针的 failureThreshold × periodSeconds 差多少（差得越小，摘流与重启越容易同时发生） | spec.template.spec.containers[*].[livenessProbe.failureThreshold, livenessProbe.periodSeconds, readinessProbe.failureThreshold, readinessProbe.periodSeconds] |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，幅值取到足以让探针端点超时 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 丢弃该服务到依赖的报文 | — |

#### 四 判定

预期行为：依赖短暂不可用只导致摘流，容器不被重启；恢复后实例自行回到就绪。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 同一注入窗内同时出现「摘出 EndpointSlice」与「容器重启」 | `events` |
| 容器重启计数 +1，Killing 事件消息为 failed liveness probe | `events` |
| 依赖恢复后该实例重新就绪所花的时间 | `status` |

同一现象的其他解释（实验必须能排除）：

- 存活探针本就耦合了依赖（与 T-PROBE-01 同源，需要用反证项区分）
- 应用在依赖不可用时自行退出

怎么修：存活与就绪指向不同端点，存活只查进程自身（改动层面：**config**）


### T-PROBE-05　探针超时小于探针端点本身的基线耗时

> 机制 `probe timeout`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖只抖动几百毫秒，探针就连续超时，实例被摘流甚至被重启，而业务请求其实还在正常返回。

#### 一 规则

探针的超时必须大于该探针端点在正常状态下的耗时，并留出依赖抖动的余量，否则探针会在系统正常时就开始失败。

依据：

- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Configure probes > timeoutSeconds）— Liveness, Readiness, and Startup Probes
  > Number of seconds after which the probe times out. Defaults to 1 second. Minimum value is 1.
- `k8s-probes-concept`（Kubernetes，Liveness, Readiness, and Startup Probes > Configure probes > failureThreshold）— Liveness, Readiness, and Startup Probes
  > After a probe fails failureThreshold times in a row, Kubernetes considers that the overall check has failed: the container is not ready/healthy/live.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `timeoutSeconds` | 1 | s | `k8s-probes-concept` |
| `periodSeconds` | 10 | s | `k8s-probes-concept` |
| `failureThreshold` | 3 | 次 | `k8s-probes-concept` |

#### 二 定位

适用范围：

- 容器声明了任一探针
- 该探针端点的处理函数做了不止「返回常量」的工作（读本地状态、聚合多个健康指示器、访问依赖）

角色：脆弱点在 **该容器的探针 timeoutSeconds 与探针端点的处理函数**；故障加在 **该服务所在容器（CPU 压力）或它的进程外依赖（延迟）**；异常显现在 **该服务自身的就绪副本数与重启计数**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | timeoutSeconds 未显式设置即为 1 秒，对聚合型健康端点常常不够 | `spec.template.spec.containers[*].*Probe.timeoutSeconds` |
| Spring Boot Actuator | /actuator/health 聚合全部 HealthIndicator，耗时随指示器数量增长 | `management.endpoint.health.group.*.include` |
| ASP.NET Core | MapHealthChecks 默认跑全部已注册的健康检查 | `源码（MapHealthChecks 的 Predicate）` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 探针未显式设置 timeoutSeconds（落在 1 秒默认值上），或设置值接近端点基线耗时 | spec.template.spec.containers[*].[livenessProbe.timeoutSeconds, readinessProbe.timeoutSeconds, startupProbe.timeoutSeconds] |
| C2 | 必要 | `codegraph` | 探针端点做的不只是返回常量 | 起点为探针路径对应的处理函数符号，沿调用边查 2 跳内是否存在 I/O 或聚合调用 |
| C3 | 反证 | `llm` | 探针端点是静态返回（例如直接写死 200），基线耗时与依赖无关 | 该探针端点的处理函数是否只返回常量、不做任何 I/O？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `runtime` | 探针端点的基线耗时实测值 | 无注入时连续采样探针端点的响应耗时，取 p99 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 网络延迟，限定到该服务与依赖的 Pod 对与端口 | — |
| CPU 压力 | 连续幅值 | `injection_site` | 在该容器内占用 CPU，抬高探针端点的处理耗时 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `T` | timeoutSeconds | manifest|default |
| `b` | 探针端点的基线耗时 p99 | measured |
| `P` | periodSeconds | manifest|default |
| `F` | failureThreshold | manifest|default |
| `n` | 一次探针调用触达依赖的次数 | measured|assumed_worst |

- 触发边界：`d* = (T - b) / n`
- 最坏情况倍数：`n`
- 保持时长：`(F + 1) * P + T`
- 恢复观察窗：`(F + 1) * P + T`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：依赖或 CPU 出现小幅抖动时探针仍能在超时内完成，实例不被摘流也不被重启。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 探针失败事件出现时，注入幅值远小于该服务的业务超时 | `events` |
| 就绪副本数下降或容器重启计数增加 | `status` |
| 探针端点响应耗时越过 timeoutSeconds 的时刻 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 探针端点本身耦合了依赖（T-PROBE-01），而非超时值过紧
- 容器被 CPU 限额节流（需要同时看 throttling 指标）

怎么修：按探针端点的基线耗时设置 timeoutSeconds 并留余量；同时收敛端点自身的工作量（改动层面：**config**）


---

## 机制组 `idempotency_compensation`


### T-IDEM-01　会被重试的写操作没有幂等键

> 机制 `idempotency key`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：一次超时重试造成重复扣款或重复下单，账面上多出一笔谁也说不清来源的记录。

#### 一 规则

带副作用且可能被重试的操作必须靠调用方提供的请求标识做幂等，使重复请求能被识别为同一次意图。

依据：

- `aws-builders-idempotency`（AWS Builders Library，Making retries safe with idempotent APIs > Reducing client complexity with idempotent API design）— Making retries safe with idempotent APIs
  > At Amazon, our preferred approach is to incorporate a unique caller-provided client request identifier into our API contract. Requests from the same caller with the same client request identifier can be considered duplicate requests and can be dealt with accordingly.
- `azure-pattern-retry`（Azure Architecture Center，Retry pattern > Issues and considerations）— Retry pattern
  > Consider whether the operation is idempotent. If so, it's inherently safe to retry. Otherwise, retries could cause the operation to be executed more than once, with unintended side effects.

#### 二 定位

适用范围：

- 该接口带写副作用（落库、扣减、下单、发消息）
- 该接口所在路径上存在自动重试（客户端 SDK、网格、网关任一层）

角色：脆弱点在 **该写接口的实现与它的入参契约**；故障加在 **该服务自身（制造响应丢失）或它与调用方之间的网络**；异常显现在 **该服务写入的存储**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Spring Boot | 写接口是否接受 Idempotency-Key 之类的请求头，并据此去重 | `源码` |
| gRPC | 被放进 retryableStatusCodes 的方法是否具备幂等语义 | `service config 与源码` |
| Kafka | 生产端 enable.idempotence 只解决 broker 侧重复写，业务侧仍需自己的幂等键 | `producer 配置` |
| Envoy | retry_on 是否对带副作用的路由开启（对这类路由重试即要求幂等） | `route.retry_policy.retry_on` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 该写接口没有接受调用方提供的幂等标识，也没有基于业务主键的去重 | 起点为该写接口的处理函数，沿调用边查 4 跳内是否存在对幂等表或唯一约束的查询与写入 |
| C2 | 必要 | `manifest` | 该路径上确实存在自动重试 | 该路由的 retry_policy / retries.attempts，以及客户端 SDK 的重试配置 |
| C3 | 反证 | `llm` | 该操作天然幂等（纯覆盖写、按主键的 upsert、只读） | 该操作重复执行两次的结果是否与执行一次相同？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `llm` | 存储侧是否有唯一约束能兜住重复写 | 该写入涉及的表是否存在能阻止重复插入的唯一约束？回答 成立 / 不成立 / 无法判定 + 文件:行 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 响应在返回途中丢失 | 离散·有数量 | `injection_site` | 在该服务返回响应的方向上丢包或注入超过调用方超时的延迟，迫使调用方重试 | — |
| 依赖变慢触发重试 | 连续幅值 | `injection_site` | 注入延迟使调用方超时并重试，而服务端其实已经处理成功 | — |

#### 四 判定

预期行为：同一次业务意图被重复提交时，副作用只发生一次，重复请求得到语义等价的响应。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入窗内业务记录的新增条数与客户端发起的业务次数之比 | `logs` |
| 幂等表或唯一约束的命中与冲突计数 | `metrics` |
| 重复请求得到的响应是否与首次语义等价 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 存储的唯一约束挡住了重复，接口本身其实没有做幂等（需用附注项区分）
- 客户端其实没有重试，重复来自用户操作

怎么修：调用方生成幂等键，服务端据此识别重复请求（改动层面：**code**）


### T-IDEM-02　幂等标识的记录与业务副作用不在同一个原子操作里

> 机制 `idempotency key atomicity`　缺陷类别 **实现错误型**　参数类型 **离散动作**

**违反后的运行时表现**：中断之后留下一个「幂等标识已记录、业务却没做成」的请求，重试被判为重复直接返回成功，这笔业务永远补不回来。

#### 一 规则

记录幂等标识与产生业务副作用必须是同一个原子操作，否则会出现「标识记下了但业务没做」或「业务做了但标识没记」两种残缺状态。

依据：

- `aws-builders-idempotency`（AWS Builders Library，Making retries safe with idempotent APIs > Reducing client complexity with idempotent API design）— Making retries safe with idempotent APIs
  > An important consideration is that the process that combines recording the idempotent token and all mutating operations related to servicing the request must meet the properties for an atomic, consistent, isolated, and durable (ACID) operation.

#### 二 定位

适用范围：

- 该写接口已经实现了基于幂等标识的去重

角色：脆弱点在 **幂等标识的写入位置与业务写入位置之间的事务边界**；故障加在 **该服务的实例（在两次写入之间终止进程）**；异常显现在 **该服务写入的存储**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Spring Boot | 幂等表的插入与业务写是否在同一个 @Transactional 边界内 | `源码` |
| go-redis | 用 Redis SETNX 记标识、用数据库写业务，两者天然不在同一事务里 | `源码` |
| HikariCP | 若两次写入取了不同连接，就不在同一本地事务内 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 幂等标识与业务数据写在不同的存储，或不在同一个事务边界内 | 起点为该写接口的处理函数，比较幂等标识写入点与业务写入点是否处在同一事务作用域内（2 跳内） |
| C2 | 反证 | `llm` | 两者在同一本地事务内提交 | 幂等标识的插入与业务数据的写入是否在同一个数据库事务中提交？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 附注 | `runtime` | 两次写入之间的时间窗（决定注入终止的时机精度） | 从幂等标识写入到业务写入提交之间的耗时 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 处理中途实例终止 | 离散·有数量 | `injection_site` | 在请求处理过程中删除该服务的 Pod，反复多次以覆盖两次写入之间的时间窗 | — |
| 存储短暂不可达 | 离散·有时长 | `injection_site` | 让业务数据所在的存储短暂不可达，而幂等标识所在的存储仍然可写 | — |

#### 四 判定

预期行为：无论在哪个时刻中断，最终只会出现「都做了」或「都没做」两种状态，重试能够收敛。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 幂等标识存在但对应业务记录缺失的条数 | `logs` |
| 业务记录存在但幂等标识缺失，导致重复写入的条数 | `logs` |
| 中断后重试是否被幂等标识误判为「已处理」而直接返回成功 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 存储本身有补偿任务在后台修复，掩盖了瞬时的不一致
- 注入的终止时机没有落在两次写入之间，未能触发

怎么修：幂等标识与业务副作用同事务提交；跨存储时改用发件箱或补偿（改动层面：**code**）


### T-IDEM-03　跨服务的多步写操作没有补偿动作

> 机制 `compensating transaction`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：第三步失败后，前两步的扣减没有退回，留下一笔各服务数据对不上的脏记录。

#### 一 规则

跨越多个服务或多个存储的写操作，每个已完成且可撤销的步骤都要有对应的补偿动作，且补偿本身必须幂等。

依据：

- `azure-pattern-compensating`（Azure Architecture Center，Compensating Transaction pattern > Solution）— Compensating Transaction pattern
  > Implement a compensating transaction that undoes the effects of completed steps in the original operation.
- `azure-pattern-compensating`（Azure Architecture Center，Compensating Transaction pattern > Solution）— Compensating Transaction pattern
  > You can use a workflow to implement an eventually consistent operation that requires compensation. As the original operation runs, the system records information about each step and how to undo it. If the operation fails, the workflow rewinds through the completed steps and reverses each step.

#### 二 定位

适用范围：

- 一次业务操作跨越两个及以上服务或存储的写入
- 这些写入无法放进单一本地事务

角色：脆弱点在 **该业务流程的编排代码与各步骤的补偿实现**；故障加在 **流程中间某一步所依赖的服务或存储**；异常显现在 **各服务各自的业务数据**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Spring Boot | 每个流程步骤是否有对应的补偿方法，补偿方法是否幂等 | `源码` |
| Kafka | 以事件驱动编排时，每步的事件与补偿事件是否都能被重放且幂等 | `源码` |
| RabbitMQ | 补偿消息的投递是否可靠（持久化、确认、死信） | `源码与队列参数` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 存在已完成的步骤没有对应的撤销实现 | 起点为流程编排函数，枚举各步骤调用点，检查每个步骤是否存在配对的撤销调用 |
| C2 | 必要 | `llm` | 流程中途失败时没有触发撤销的代码路径 | 该流程在中间步骤失败时，是否会调用前序步骤的撤销动作？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `llm` | 所有写入其实都落在同一个存储且在同一本地事务内 | 该流程的全部写入是否在同一个数据库事务中提交？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `codegraph` | 流程的步骤数与各步骤的顺序（决定要逐个注入几次） | 起点为流程编排函数，列出按顺序调用的各写入步骤 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 中间步骤所依赖的服务不可达 | 离散·有时长 | `injection_site` | 依次让第 2 步、第 3 步…… 所依赖的服务不可达，每次只断一个 | — |
| 编排实例中途终止 | 离散·有数量 | `injection_site` | 在流程执行中途删除编排服务的 Pod | — |

#### 四 判定

预期行为：任一中间步骤失败后，前序步骤的副作用被撤销干净，系统不留中间态记录。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 各服务业务记录的一致性核对结果 | `logs` |
| 补偿动作的执行计数 | `metrics` |
| 残留在中间态的记录条数 | `logs` |
| 补偿被重复执行时是否产生二次副作用 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 后台对账任务已经修复了不一致，观察窗太长看不出问题
- 注入点选在了不可撤销的步骤之后（越过了不可回头点）

怎么修：为每个可撤销步骤定义幂等的补偿动作，并明确不可回头点（改动层面：**code**）


---

## 机制组 `load_shedding_admission`


### T-SHED-01　服务端没有准入控制，过载时全体一起变慢

> 机制 `admission control`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：压力上去后吞吐不是持平而是塌陷，所有请求一起超时，服务从「部分可用」直接掉成「完全不可用」。

#### 一 规则

服务端应当在自己饱和之前主动拒掉多余请求，让被接受的请求仍在延迟目标内完成，而不是照单全收后集体变慢。

依据：

- `aws-builders-load-shedding`（AWS Builders Library，Using load shedding to avoid overload > 概述）— Using load shedding to avoid overload
  > When a server approaches overload, it should start rejecting excess requests so that it can focus on the requests it decides to let in. The goal of load shedding is to keep latency low for the requests that the server decides to accept so that the service replies before the client times out.
- `sre-cascading-failures`（Google SRE，Preventing Server Overload > Load Shedding and Graceful Degradation）— SRE Book ch.22 Addressing Cascading Failures
  > One straightforward way to shed load is to do per-task throttling based on CPU, memory, or queue length; limiting queue length as discussed in Queue Management is a form of this strategy.
- `azure-pattern-throttling`（Azure Architecture Center，Throttling pattern > Issues and considerations）— Throttling pattern
  > Shed load proactively, not at the edge of collapse. A throttle that only rejects after a component saturates causes latency to spike before callers see any back-pressure.

#### 二 定位

适用范围：

- 服务对外暴露同步接口
- 入站流量不完全受本服务控制（来自网关、外部调用方或异步消费）

角色：脆弱点在 **该服务的限流 / 并发上限 / 过载保护配置**；故障加在 **该服务自身（抬升入站流量或制造资源压力）**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Envoy | 本地或全局 rate limit filter；overload manager 按内存与在途请求数减载 | `http_filters 的 local_ratelimit / ratelimit 与 overload_manager` |
| ingress-nginx | limit-rps、limit-connections 注解 | `nginx.ingress.kubernetes.io/limit-rps` |
| Polly | RateLimiter 或 ConcurrencyLimiter 策略 | `源码` |
| Spring Boot | 服务端线程池上限与队列上限共同决定准入 | `server.tomcat.threads.max 与 server.tomcat.accept-count` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 该服务入口既没有限流规则，也没有并发上限 | 该服务对应的 Ingress / VirtualService / EnvoyFilter 上的限流配置，以及服务端线程池上限 |
| C2 | 必要 | `semgrep` | 服务端的工作队列是无界的，请求会一直堆积而不是被拒绝 | checkers/semgrep/java-unbounded-work-queue.yaml、checkers/semgrep/go-unbounded-channel-worker.yaml |
| C3 | 反证 | `manifest` | 上游或网关侧已经有针对该服务的限流，实际准入由外层完成 | 入口网关上与该服务路由匹配的限流注解或规则 |
| C4 | 附注 | `runtime` | 该服务的容量拐点（吞吐随并发上升到不再增长的位置） | 阶梯加压下吞吐与延迟随并发的变化曲线 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 入站流量抬升 | 连续幅值 | `injection_site` | 阶梯提高该服务入口的 QPS，越过容量拐点 | — |
| CPU 压力 | 连续幅值 | `injection_site` | 在该容器内占用 CPU，等效降低容量，使较低的 QPS 也能越过拐点 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `C` | 该服务的容量（拐点处的 QPS） | measured |
| `q` | 注入的入站 QPS | measured |
| `L` | 上游对本服务的延迟目标或超时 | requirement|manifest |
| `N` | 服务端工作线程数 | manifest|default |

- 触发边界：`d* = C（把 QPS 抬到容量以上即触发）`
- 最坏情况倍数：`1`
- 保持时长：`3 * L`
- 恢复观察窗：`3 * L`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：入站流量越过容量后出现拒绝，被接受请求的延迟仍在目标内，吞吐持平而不是塌陷。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 吞吐随入站 QPS 的曲线是否持平（而非先升后塌） | `metrics` |
| 被接受请求的 p99 延迟是否仍在 L 以内 | `metrics` |
| 拒绝计数与拒绝率 | `metrics` |
| 上游侧看到的超时比例 | `traces` |

同一现象的其他解释（实验必须能排除）：

- 吞吐塌陷来自下游依赖被打满，而不是本服务缺准入控制
- 压测客户端自身成为瓶颈

怎么修：按压测得到的容量设准入阈值，过载时快速拒绝而不是排队（改动层面：**config**）


### T-SHED-02　请求队列无界或相对线程池过长

> 机制 `bounded queue`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：过载时内存被排队请求吃光，或所有请求都排到上游超时之后才被处理，有效吞吐降到接近零。

#### 一 规则

服务端的请求队列必须有界；流量平稳的服务队列长度还应显著小于线程池规模，宁可早拒绝也不要让请求排到超时。

依据：

- `sre-cascading-failures`（Google SRE，Preventing Server Overload > Queue Management）— SRE Book ch.22 Addressing Cascading Failures
  > For a system with fairly steady traffic over time, it is usually better to have small queue lengths relative to the thread pool size (e.g., 50% or less), which results in the server rejecting requests early when it can’t sustain the rate of incoming requests.
- `sre-cascading-failures`（Google SRE，Preventing Server Overload > Queue Management）— SRE Book ch.22 Addressing Cascading Failures
  > Queued requests consume memory and increase latency.

#### 二 定位

适用范围：

- 服务端在工作线程前面有请求队列（线程池队列、accept 队列、消息拉取缓冲）

角色：脆弱点在 **该服务的队列长度与线程池规模配置**；故障加在 **该服务自身（抬升入站流量）或它的下游依赖（拉长单请求耗时）**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Spring Boot | server.tomcat.threads.max 与 server.tomcat.accept-count 的比值 | `application 配置` |
| Envoy | max_pending_requests 即队列上限，溢出立即拒绝 | `cluster.circuit_breakers.thresholds[*].max_pending_requests` |
| ingress-nginx | worker_connections 与 backlog 决定内核层排队深度 | `ConfigMap 的 worker-connections` |
| Go net/http | 每请求一协程且无并发上限，等价于无界队列 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 队列无界（无参 LinkedBlockingQueue、每请求起协程且无信号量、未设 max_pending_requests） | checkers/semgrep/java-unbounded-work-queue.yaml、checkers/semgrep/go-unbounded-channel-worker.yaml |
| C2 | 必要 | `manifest` | 清单侧也没有给出队列上限 | cluster.circuit_breakers.thresholds[*].max_pending_requests 与 server.tomcat.accept-count |
| C3 | 反证 | `manifest` | 队列虽有界但长度远大于线程池规模，属于同一问题的程度差异，应记录实际比值而非直接判违反 | 队列长度与线程数的比值 |
| C4 | 附注 | `runtime` | 单请求的平均处理时长（用于把队列长度换算成排队时长） | 无注入时该接口的处理耗时均值 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 注入下游延迟，拉长单请求占用线程的时间，使队列快速堆积 | — |
| 入站流量抬升 | 连续幅值 | `injection_site` | 提高入站 QPS 直到超过线程池的处理能力 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `Q` | 队列长度，无界时视为无穷 | manifest|code|default |
| `N` | 工作线程数 | manifest|default |
| `p` | 单请求处理时长 | measured |
| `U` | 上游对本服务的超时 | manifest|requirement |
| `q` | 入站 QPS | measured |

- 触发边界：`d* = (N * U / p - N) * p（注入延迟使 (Q/N) * (p + d) 超过 U 即触发）`
- 最坏情况倍数：`1`
- 保持时长：`(Q / N) * p + U`
- 恢复观察窗：`2 * ((Q / N) * p + U)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：过载时新请求在队列上限处被立即拒绝，被接受请求的排队时长不超过上游还愿意等待的时间。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 队列深度随时间的变化是否收敛到上限 | `metrics` |
| 排队时长分布与上游超时的关系 | `traces` |
| 拒绝计数是否随过载出现 | `metrics` |
| 容器内存用量是否随队列堆积持续上涨 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 内存上涨来自业务对象缓存，而不是排队请求
- 拒绝来自上游网关而不是本服务

怎么修：有界队列加明确的拒绝策略，队列长度按上游预算反推（改动层面：**config**）


### T-SHED-03　过载拒绝没有用可识别的状态码，下游过载信号被吞掉

> 机制 `backpressure signalling`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：上游无从得知下游在过载，继续加压甚至重试，过载沿调用链反向放大。

#### 一 规则

过载拒绝必须用调用方能识别的状态表示，并且下游返回的过载信号要如实向上传递，不能被统一改写成通用错误或被静默重试掩盖。

依据：

- `azure-pattern-throttling`（Azure Architecture Center，Throttling pattern > Issues and considerations）— Throttling pattern
  > Propagate overload signals from your dependencies instead of absorbing them. A service that throttles its callers must also honor the throttling responses that it receives from its own downstream dependencies. If your service hides a downstream 429 or 503 response by retrying silently or by returning a generic HTTP 500 (Internal Server Error) response, callers can't slow down, retries amplify, and the overload cascades back upstream.
- `azure-pattern-throttling`（Azure Architecture Center，Throttling pattern > Issues and considerations）— Throttling pattern
  > Include a Retry-After HTTP header so that the client can pick a retry strategy.

#### 二 定位

适用范围：

- 该服务有限流，或它的下游可能返回过载类响应

角色：脆弱点在 **该服务的限流响应配置与异常映射层**；故障加在 **该服务的下游依赖**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Envoy | 限流拒绝返回的状态码与响应头 | `local_ratelimit 的 status 与 response_headers_to_add` |
| Spring Boot | 全局异常处理器是否把下游 429 / 503 统一改写成 500 | `源码（@ControllerAdvice）` |
| gRPC | RESOURCE_EXHAUSTED 与 UNAVAILABLE 的区分，以及是否被放进可重试状态码 | `源码与 service config` |
| ingress-nginx | 限流拒绝的返回码注解 | `nginx.ingress.kubernetes.io/limit-*` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `llm` | 异常映射层把下游的过载状态统一改写成了通用错误 | 该服务的全局异常处理是否把下游 429 / 503 映射成了 500 或统一错误码？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C2 | 必要 | `manifest` | 本服务自己的限流拒绝没有用可识别的状态码 | 限流过滤器配置里的拒绝状态码取值 |
| C3 | 反证 | `runtime` | 过载状态被如实透传，且带了 Retry-After 或等价信息 | 注入下游过载后，观察本服务向上返回的状态码与响应头 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 下游返回过载状态 | 离散·有时长 | `injection_site` | 让下游在一段时间内稳定返回 429 或 503 | — |
| 入站流量抬升 | 连续幅值 | `defect_site` | 把本服务的入站 QPS 抬过它自己的限流阈值，检查它拒绝时用的状态码 | — |

#### 四 判定

预期行为：下游的过载状态被如实传到上游，上游能据此退避；本服务自己的限流拒绝也用可识别的状态码。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 本服务出站收到的状态码分布 | `metrics` |
| 本服务入站返回的状态码分布 | `metrics` |
| 上游在注入期间的重试率变化 | `metrics` |
| 响应头中是否带 Retry-After | `logs` |

同一现象的其他解释（实验必须能排除）：

- 下游本身没有返回过载状态，而是直接超时（信号源头就没有）
- 上游不看状态码，只按超时判断，透传与否都不影响其行为

怎么修：用专门的过载状态码并把它一路透传上去（改动层面：**code**）


### T-SHED-04　排到超时的请求出队后仍被处理

> 机制 `queue admission by deadline`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：过载期间服务端满负荷运转，有效吞吐却接近零——处理的全是上游早已放弃的请求。

#### 一 规则

请求出队开始处理前应当先看它是否已经超出调用方还愿意等待的时间，过期的直接丢弃，而不是照先进先出处理完。

依据：

- `sre-cascading-failures`（Google SRE，Latency and Deadlines > Missing deadlines）— SRE Book ch.22 Addressing Cascading Failures
  > If handling a request is performed over multiple stages (e.g., there are a few callbacks and RPC calls), the server should check the deadline left at each stage before attempting to perform any more work on the request.
- `aws-builders-load-shedding`（AWS Builders Library，Using load shedding to avoid overload > Watching the clock）— Using load shedding to avoid overload
  > In some extreme overload scenarios, huge volumes of requests can queue up in Transmission Control Protocol (TCP) buffers, so by the time the server reads the requests from its buffers, the client has already timed out.

#### 二 定位

适用范围：

- 服务端存在排队（线程池队列、消息拉取、内核 accept 队列）
- 调用方对该接口设置了超时

角色：脆弱点在 **该服务的出队处理入口**；故障加在 **该服务自身（抬升入站流量制造排队）或它的下游（拉长处理时长）**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | 服务端出队后是否检查 context 是否已取消或已过期 | `源码` |
| Spring Boot | 队列里是否记录了入队时刻，处理前是否比对上游超时 | `源码` |
| Envoy | route timeout 与 max_pending_requests 配合，超时的挂起请求被取消 | `route.timeout 与 cluster.circuit_breakers` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `codegraph` | 出队处没有「已过期就丢弃」的判断 | 起点为工作线程的任务取出点，沿调用边查 2 跳内是否存在对 context 取消状态或入队时间戳的检查 |
| C2 | 必要 | `llm` | 队列里没有携带入队时刻或截止时间，想判也判不了 | 入队的任务对象是否携带入队时刻或截止时间字段？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `manifest` | 队列极短（相对线程池不足以排出超过上游超时的等待），过期请求本就很少 | 队列长度与线程数的比值，以及单请求处理时长 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 入站流量抬升 | 连续幅值 | `injection_site` | 把 QPS 抬到超过处理能力，让队列稳定堆满 | — |
| 依赖变慢 | 连续幅值 | `injection_site` | 注入下游延迟，拉长单请求处理时长，加速排队 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `U` | 上游对本服务的超时 | manifest|requirement |
| `Q` | 队列长度 | manifest|code|default |
| `N` | 工作线程数 | manifest|default |
| `p` | 单请求处理时长 | measured |
| `q` | 入站 QPS | measured |

- 触发边界：`d* = (U * N / Q) - p（排队时长 (Q/N)*(p+d) 越过 U 即触发）`
- 最坏情况倍数：`1`
- 保持时长：`2 * (Q / N) * p`
- 恢复观察窗：`2 * (Q / N) * p`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：过载时服务端把已过期的排队请求直接丢弃，有效吞吐（上游还愿意接收的那部分）保持非零。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 有效吞吐（上游未超时的成功响应数）是否随过载降到零 | `metrics` |
| 服务端 CPU 使用率与有效吞吐的背离程度 | `metrics` |
| 上游已超时但服务端仍完成的请求比例 | `traces` |
| 出队即丢弃的计数 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 有效吞吐为零是因为服务端确实处理不过来，而不是在处理过期请求
- 上游超时设得过短，任何排队都会过期

怎么修：出队即校验截止时间，或改用 LIFO / CoDel 之类的排队策略（改动层面：**code**）


---

## 机制组 `replica_disruption`


### T-REPLICA-01　需要持续可用的工作负载只有一个副本

> 机制 `replica count`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：杀掉唯一的实例即 100% 不可用，恢复时间等于镜像拉取加冷启动的全过程。

#### 一 规则

需要在丢掉一个实例后继续提供服务的工作负载，副本数不能是 1。

依据：

- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability 检查表）— Polaris Checks: Reliability
  > deploymentMissingReplicas | warning | Fails when there is only one replica for a deployment.
- `kube-score-checks`（kube-score，kube-score checks 列表）— kube-score checks list
  > | deployment-replicas | Deployment | Makes sure that Deployment has multiple replicas. The --min-replicas-deployment flag can be used to specify the required minimum. Default is 2. | default |

#### 二 定位

适用范围：

- 该工作负载被某个 Service 选中并承担同步流量
- 该工作负载不是单例语义（不是需要全局唯一实例的组件）

角色：脆弱点在 **该工作负载的副本数声明**；故障加在 **该工作负载的实例**；异常显现在 **该服务的上游调用方或入口**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | Deployment / StatefulSet 的 spec.replicas；被 HPA 管的看 minReplicas | `spec.replicas` |
| Polaris | deploymentMissingReplicas 检查 | `Polaris 配置` |
| kube-score | deployment-replicas 检查 | `kube-score 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | spec.replicas 等于 1（被 HPA 管的看 minReplicas 等于 1） | spec.replicas |
| C2 | 反证 | `llm` | 该工作负载是单例语义组件（领导者选举、单写入者），多副本反而不正确 | 该工作负载是否依赖「同一时刻只有一个实例在运行」的语义？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 附注 | `manifest` | 该工作负载是否被 Service 选中（不接流量时影响面不同） | spec.template.metadata.labels 与集群内各 Service 的 spec.selector 的交集 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 实例终止 | 离散·有数量 | `injection_site` | 删除该工作负载的一个 Pod | — |

#### 四 判定

预期行为：杀掉一个实例后服务仍可用，上游错误率只有短暂抖动。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 杀实例期间上游对该服务的错误率 | `metrics` |
| 就绪副本数在注入窗内是否跌到 0 | `status` |
| 从实例被删到新实例就绪的时长 | `events` |

同一现象的其他解释（实验必须能排除）：

- 上游有重试或缓存兜底，掩盖了短暂的完全不可用
- 该服务本就无人调用

怎么修：多副本部署，副本数按「丢一个仍够用」反推（改动层面：**config**）


### T-REPLICA-02　多副本工作负载没有中断预算

> 机制 `pod disruption budget`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：节点维护时整组副本被一次性驱逐，服务出现完全中断，而各个副本自身都「健康」。

#### 一 规则

多副本工作负载应当有中断预算，限制主动中断同时带走的副本数。

依据：

- `k8s-disruptions`（Kubernetes，Disruptions > Pod disruption budgets）— Disruptions
  > As an application owner, you can create a PodDisruptionBudget (PDB) for each application. A PDB limits the number of Pods of a replicated application that are down simultaneously from voluntary disruptions.
- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability 检查表）— Polaris Checks: Reliability
  > missingPodDisruptionBudget | warning | Fails when PDB is missing.
- `kube-score-checks`（kube-score，kube-score checks 列表）— kube-score checks list
  > | deployment-has-poddisruptionbudget | Deployment | Makes sure that all Deployments are targeted by a PDB | default |

#### 二 定位

适用范围：

- 该工作负载副本数大于 1
- 集群会发生节点维护、缩容或重调度这类主动中断

角色：脆弱点在 **该工作负载与集群内 PDB 的匹配关系**；故障加在 **承载该工作负载的节点**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | 是否存在 selector 能匹配到该工作负载的 PDB，且指定了 minAvailable 或 maxUnavailable | `policy/v1 PodDisruptionBudget` |
| Polaris | missingPodDisruptionBudget 检查 | `Polaris 配置` |
| kube-score | deployment-has-poddisruptionbudget 与 poddisruptionbudget-has-policy | `kube-score 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 没有任何 PDB 的 selector 能匹配到该工作负载的 Pod 标签 | 集群内 PodDisruptionBudget[*].spec.selector 与该工作负载 spec.template.metadata.labels 的交集 |
| C2 | 必要 | `manifest` | 即便存在 PDB，也没有指定 minAvailable 或 maxUnavailable | PodDisruptionBudget[*].spec.[minAvailable, maxUnavailable] |
| C3 | 反证 | `manifest` | 该工作负载只有一个副本，PDB 无法同时满足「不中断」与「可维护」，应改用 T-REPLICA-01 | spec.replicas |
| C4 | 附注 | `manifest` | PDB 的 unhealthyPodEvictionPolicy 取值（影响不健康 Pod 能否被驱逐） | PodDisruptionBudget[*].spec.unhealthyPodEvictionPolicy |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 节点排空 | 离散·有数量 | `injection_site` | 对承载该工作负载多数副本的节点调用 Eviction API 逐出 Pod | — |
| 实例终止 | 离散·有数量 | `injection_site` | 同时删除多个副本，模拟一次带走多个实例的主动中断 | — |

#### 四 判定

预期行为：主动中断期间可用副本数始终不低于预算，服务不出现完全中断。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 驱逐期间就绪副本数的最低值 | `status` |
| Eviction API 被拒绝的次数（说明 PDB 在起作用） | `events` |
| 驱逐窗内上游看到的错误率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 调度器恰好把副本分散在多个节点上，单节点排空本就不会全带走
- 驱逐工具直接删除 Pod 而没有走 Eviction API，PDB 本就不生效

怎么修：为每个多副本工作负载配 PDB，并核对 selector 确实匹配（改动层面：**config**）


### T-REPLICA-03　中断预算与副本数或扩缩下限不相容

> 机制 `pod disruption budget`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：节点维护永远排不掉 Pod，集群升级卡死；在故障演练里表现为「驱逐类注入完全无效」。

#### 一 规则

中断预算必须留出至少驱逐一个副本的余地，且与自动扩缩的副本下限相容，否则主动中断会被永久阻塞。

依据：

- `k8s-disruptions`（Kubernetes，Disruptions > How disruption budgets work）— Disruptions
  > A PDB specifies the number of replicas that an application can tolerate having, relative to how many it is intended to have. For example, a Deployment which has a .spec.replicas: 5 is supposed to have 5 pods at any given time. If its PDB allows for there to be 4 at a time, then the Eviction API will allow voluntary disruption of one (but not two) pods at a time.
- `k8s-pdb-task`（Kubernetes，Specifying a Disruption Budget > Unhealthy Pod eviction policy）— Specifying a Disruption Budget for your Application
  > PodDisruptionBudget guarding an application ensures that .status.currentHealthy number of pods does not fall below the number specified in .status.desiredHealthy by disallowing eviction of healthy pods.
- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability 检查表）— Polaris Checks: Reliability
  > pdbMinAvailableGreaterThanHPAMinReplicas | warning | Fails when PDB minAvailable is greater than HPA minReplicas

#### 二 定位

适用范围：

- 该工作负载已配置 PDB

角色：脆弱点在 **PDB 的 minAvailable / maxUnavailable 与副本数、HPA 下限三者的关系**；故障加在 **承载该工作负载的节点**；异常显现在 **集群的节点维护流程与该服务的可用性**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | minAvailable 必须小于副本数；maxUnavailable 必须大于 0 | `PodDisruptionBudget.spec` |
| Polaris | pdbMinAvailableGreaterThanHPAMinReplicas 交叉检查 | `Polaris 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | minAvailable 大于等于副本数，或 maxUnavailable 等于 0 | PodDisruptionBudget[*].spec.[minAvailable, maxUnavailable] 与被选中工作负载的 spec.replicas |
| C2 | 必要 | `manifest` | PDB.minAvailable 大于 HPA.minReplicas（缩容到下限后驱逐被永久阻塞） | PodDisruptionBudget[*].spec.minAvailable 与 HorizontalPodAutoscaler[*].spec.minReplicas |
| C3 | 反证 | `manifest` | PDB 用的是百分比且在任何副本数下都留有余地 | PodDisruptionBudget[*].spec.minAvailable 的百分比取值与副本数区间 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 节点排空 | 离散·有数量 | `injection_site` | 对承载该工作负载的节点调用 Eviction API，观察是否始终被拒绝 | — |
| 缩容到下限 | 离散·有数量 | `defect_site` | 把副本数降到 HPA 的 minReplicas，再尝试驱逐 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `n` | 当前副本数 | manifest |
| `m` | PDB 的 minAvailable | manifest |
| `u` | PDB 的 maxUnavailable | manifest |
| `h` | HPA 的 minReplicas | manifest |

- 触发边界：`违反条件为 m >= n 或 u == 0 或 m > h；注入幅值为尝试驱逐的副本数 1`
- 最坏情况倍数：`1`
- 保持时长：`300（一次节点排空的常规观察窗，单位秒）`
- 恢复观察窗：`300`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：驱逐请求在合理时间内被允许若干个，节点排空能够完成。

看哪些信号：

| 信号 | 来源 |
|---|---|
| Eviction API 返回 429 被拒的次数与持续时长 | `events` |
| 节点处于 cordon 状态但 Pod 数不下降的时长 | `status` |
| 排空操作的总耗时 | `events` |

同一现象的其他解释（实验必须能排除）：

- 驱逐被拒是因为当前确实有副本不健康，预算本身没问题
- 集群没有足够节点容纳被驱逐的 Pod，卡在调度而不是 PDB

怎么修：让 PDB 的下限与副本数、HPA 下限三者相容（改动层面：**config**）


### T-REPLICA-04　多副本没有跨故障域打散

> 机制 `topology spread`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：所有副本落在同一节点或同一可用区，该域一失效服务整体不可用，而副本数看起来是「够的」。

#### 一 规则

同一工作负载的多个副本应当跨故障域打散；调度器默认按装箱放置，不保证副本分散。

依据：

- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability > Background > Topology Spread Constraints）— Polaris Checks: Reliability
  > By default, the Kubernetes scheduler uses a bin-packing algorithm to fit as many pods as possible into a cluster. The scheduler prefers a more evenly distributed general node load to app replicas precisely spread across nodes. Therefore, by default, multi-replica is not guaranteed to be spread across multiple availability zones.
- `k8s-topology-spread`（Kubernetes，Pod Topology Spread Constraints > Spread constraint definition）— Pod Topology Spread Constraints
  > maxSkew describes the degree to which Pods may be unevenly distributed. You must specify this field and the number must be greater than zero.
- `polaris-checks-reliability`（Polaris，Polaris Checks > Reliability 检查表）— Polaris Checks: Reliability
  > topologySpreadConstraint | warning | Fails when there is no topology spread constraint on the pod

#### 二 定位

适用范围：

- 该工作负载副本数大于 1
- 集群有多个节点（若有多可用区则按可用区判）

角色：脆弱点在 **该工作负载的 topologySpreadConstraints 与 podAntiAffinity 配置**；故障加在 **承载该工作负载多数副本的节点或可用区**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | topologySpreadConstraints 的 maxSkew、topologyKey、whenUnsatisfiable，或 podAntiAffinity | `spec.template.spec.[topologySpreadConstraints, affinity.podAntiAffinity]` |
| Polaris | topologySpreadConstraint 检查 | `Polaris 配置` |
| kube-score | deployment-has-host-podantiaffinity 与 pod-topology-spread-constraints | `kube-score 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 既没有 topologySpreadConstraints 也没有 podAntiAffinity | spec.template.spec.[topologySpreadConstraints, affinity.podAntiAffinity] |
| C2 | 反证 | `manifest` | 虽然没配约束，但集群只有一个节点，打散无从谈起 | 集群节点数与可用区标签的取值集合 |
| C3 | 附注 | `manifest` | whenUnsatisfiable 是 DoNotSchedule 还是 ScheduleAnyway（后者只是尽力而为） | spec.template.spec.topologySpreadConstraints[*].whenUnsatisfiable |
| C4 | 附注 | `runtime` | 实际的副本落点分布 | 各节点与各可用区上该工作负载的 Pod 数 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 整节点实例终止 | 离散·有数量 | `injection_site` | 删除落在同一节点上的该工作负载全部 Pod | — |
| 节点不可达 | 离散·有时长 | `injection_site` | 切断该节点的网络，模拟整节点失效 | — |

#### 四 判定

预期行为：单个节点或可用区失效后仍有足够副本在服务，上游错误率只有短暂抖动。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 每节点与每可用区的副本分布 | `status` |
| 整节点失效后剩余的就绪副本数 | `status` |
| 注入期间上游对该服务的错误率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 调度器恰好把副本放散了，并非配置保证
- 上游有缓存或兜底，掩盖了后端全灭

怎么修：按节点与可用区两级配置拓扑分散约束（改动层面：**config**）


### T-REPLICA-05　滚动更新参数允许一次带走过多副本

> 机制 `rolling update`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：更新过程中容量最低的那一刻撑不住当前流量，出现一段错误率台阶，看起来像「一发布就抖」。

#### 一 规则

滚动更新时允许同时不可用的副本数必须与该服务的容量需求相容，剩下的副本要能独立承担当前流量。

依据：

- `k8s-deployment`（Kubernetes，Deployments > Rolling Update Deployment > Max Unavailable）— Deployments (rolling update parameters)
  > .spec.strategy.rollingUpdate.maxUnavailable is an optional field that specifies the maximum number of Pods that can be unavailable during the update process.
- `k8s-deployment`（Kubernetes，Deployments > Rolling Update Deployment > Max Surge）— Deployments (rolling update parameters)
  > .spec.strategy.rollingUpdate.maxSurge is an optional field that specifies the maximum number of Pods that can be created over the desired number of Pods.

#### 二 定位

适用范围：

- 该工作负载是 Deployment 且策略为 RollingUpdate
- 该工作负载承担同步流量

角色：脆弱点在 **该工作负载的 rollingUpdate 参数与副本数**；故障加在 **该工作负载的实例**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | maxUnavailable 与 maxSurge 的取值，以及它们相对 replicas 的比例 | `spec.strategy.rollingUpdate` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | maxUnavailable 换算成绝对值后占副本数的比例过高，剩余副本不足以承担当前流量 | spec.strategy.rollingUpdate.maxUnavailable 与 spec.replicas |
| C2 | 必要 | `manifest` | maxSurge 为 0，更新期间没有额外容量补位 | spec.strategy.rollingUpdate.maxSurge |
| C3 | 反证 | `manifest` | 该工作负载不接同步流量，短暂容量下降没有可观测影响 | spec.template.metadata.labels 与各 Service 的 spec.selector 的交集 |
| C4 | 附注 | `runtime` | 单副本容量与当前 QPS（决定剩余副本够不够） | 稳态下单副本承担的 QPS 与该服务的总 QPS |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 同时终止 maxUnavailable 个副本 | 离散·有数量 | `injection_site` | 一次删除与 maxUnavailable 等量的 Pod，等效于滚动更新中容量最低的那一刻 | — |
| 入站流量抬升 | 连续幅值 | `manifest_site` | 在副本减少的同时维持或抬高流量，逼出容量缺口 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `n` | 副本数 | manifest |
| `u` | maxUnavailable 换算后的绝对副本数 | manifest|default |
| `s` | maxSurge 换算后的绝对副本数 | manifest|default |
| `C1` | 单副本容量 | measured |
| `q` | 该服务当前 QPS | measured |

- 触发边界：`d* = u（同时带走的副本数；当 (n - u + s) * C1 < q 时出现容量缺口）`
- 最坏情况倍数：`1`
- 保持时长：`120`
- 恢复观察窗：`240`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：容量最低的那一刻剩余副本仍能承担当前流量，上游错误率与延迟不出现明显台阶。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入窗内就绪副本数的最低值 | `status` |
| 同期上游的错误率与 p99 延迟 | `metrics` |
| 剩余副本的 CPU 使用率是否触到限额 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 错误来自新实例冷启动而非容量不足
- 上游本身在同期流量下降，掩盖了缺口

怎么修：按「剩余副本仍够用」反推 maxUnavailable，必要时提高 maxSurge（改动层面：**config**）


---

## 机制组 `resource_limit`


### T-RESOURCE-01　容器没有声明资源请求与限额

> 机制 `resource requests and limits`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：节点资源一紧张，这个服务先被驱逐或反复 OOMKilled，而同节点上不重要的负载活得好好的。

#### 一 规则

每个容器都应声明资源请求与限额；调度按请求决定放在哪台节点，内核按限额约束实际用量。

依据：

- `k8s-resources`（Kubernetes，Resource Management for Pods and Containers > 概述）— Resource Management for Pods and Containers
  > When you specify the resource request for containers in a Pod, the kube-scheduler uses this information to decide which node to place the Pod on. When you specify a resource limit for a container, the kubelet enforces those limits so that the running container is not allowed to use more of that resource than the limit you set.
- `k8s-resources`（Kubernetes，Resource Management for Pods and Containers > Memory requests and limits）— Resource Management for Pods and Containers
  > If a container exceeds its memory request and the node that it runs on becomes short of memory overall, it is likely that the Pod the container belongs to will be evicted.
- `kube-score-checks`（kube-score，kube-score checks 列表）— kube-score checks list
  > | container-resources | Pod | Makes sure that all pods have resource limits and requests set. The --ignore-container-cpu-limit flag can be used to disable the requirement of having a CPU limit | default |

#### 二 定位

适用范围：

- 该工作负载与其他负载共享节点

角色：脆弱点在 **该容器的 resources 字段**；故障加在 **承载该容器的节点（制造资源压力）**；异常显现在 **该服务自身的重启计数与上游错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | resources.requests 与 resources.limits 的 cpu、memory、ephemeral-storage | `spec.template.spec.containers[*].resources` |
| kube-score | container-resources 与 container-ephemeral-storage-request-and-limit | `kube-score 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 容器没有设置 requests 或 limits（任一缺失） | spec.template.spec.containers[*].resources.[requests, limits] |
| C2 | 反证 | `manifest` | 集群有 LimitRange 会为该命名空间补上默认值 | 该命名空间下 LimitRange[*].spec.limits |
| C3 | 附注 | `runtime` | 该容器的实测稳态用量（判断 requests 取值是否离谱） | 稳态下该容器的 CPU 与内存用量 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 节点内存压力 | 连续幅值 | `injection_site` | 在该节点上占用内存，逼近节点可分配量 | — |
| 同节点 CPU 争抢 | 连续幅值 | `injection_site` | 在同节点起占 CPU 的负载 | — |

#### 四 判定

预期行为：节点出现资源压力时，该服务按其声明的请求量获得保障，不被优先驱逐也不被 OOM 杀。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 该容器是否出现 OOMKilled | `status` |
| 驱逐事件及被驱逐 Pod 的 QoS 等级 | `events` |
| CPU 节流时间占比 | `metrics` |
| 注入期间该服务的错误率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 驱逐来自节点维护而非资源压力
- OOM 来自应用自身的内存泄漏，与限额声明无关

怎么修：按实测用量设置 requests 与 limits（改动层面：**config**）


### T-RESOURCE-02　运行时堆上限与容器内存限额脱钩

> 机制 `runtime heap vs container limit`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：容器被内核 OOMKilled，而运行时日志里没有任何内存不足的迹象，重启后周期性复发。

#### 一 规则

运行时的堆上限应当由容器内存限额推导并为堆外留出余量，否则容器会在运行时自认为内存还够的时候被内核杀掉。

依据：

- `jvm-launcher`（JVM，java command > Advanced Runtime Options）— java command (UseContainerSupport, MaxRAMPercentage)
  > The maximum amount of available memory to the JVM process is the minimum of the machine's physical memory and any constraints set by the environment (e.g. container).
- `jvm-launcher`（JVM，java command > Advanced Runtime Options > -XX:-UseContainerSupport）— java command (UseContainerSupport, MaxRAMPercentage)
  > Linux only: The VM now provides automatic container detection support, which allows the VM to determine the amount of memory and number of processors that are available to a Java process running in docker containers.
- `k8s-resources`（Kubernetes，Resource Management for Pods and Containers > Resource units）— Resource Management for Pods and Containers
  > memory limits are enforced by the kernel with out of memory (OOM) kills. When a container uses more than its memory limit, the kernel may terminate it.

#### 二 定位

适用范围：

- 容器内跑的是自带堆或内存池的运行时（JVM、Node.js、.NET 等）
- 容器声明了内存限额

角色：脆弱点在 **运行时的堆参数与容器内存限额**；故障加在 **该容器（制造内存压力或抬高业务内存占用）**；异常显现在 **该服务自身的重启计数与上游错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| JVM | 是否用 -XX:MaxRAMPercentage 之类按比例取值；是否显式关掉了 UseContainerSupport | `容器启动参数 JAVA_OPTS / JAVA_TOOL_OPTIONS` |
| Node.js | --max-old-space-size 是否按容器限额设置 | `容器启动参数` |
| Kubernetes | resources.limits.memory 是内核 OOM 的判据；以内存为介质的 emptyDir 也计入 | `spec.template.spec.containers[*].resources.limits.memory` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 堆上限写死为绝对值或完全未设，没有与容器内存限额挂钩 | spec.template.spec.containers[*].[env, args] 中的堆参数，与 resources.limits.memory 比对 |
| C2 | 必要 | `manifest` | 显式关闭了容器感知（-XX:-UseContainerSupport 或等价设置） | 容器启动参数里是否出现 -XX:-UseContainerSupport |
| C3 | 反证 | `runtime` | 堆上限加上实测堆外占用之和明显小于内存限额，余量充足 | 稳态下进程 RSS 与堆占用之差，对比内存限额 |
| C4 | 附注 | `runtime` | 实测堆外占用（元空间、线程栈、直接内存、本地库） | RSS 减去堆内占用 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 容器内存压力 | 连续幅值 | `injection_site` | 在容器内占用内存，把 RSS 推向限额 | — |
| 业务内存占用抬升 | 连续幅值 | `manifest_site` | 抬高并发或请求体大小，抬高堆外与堆内占用 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `L` | 容器内存限额 | manifest |
| `H` | 运行时堆上限 | manifest|default |
| `O` | 实测堆外占用 | measured |
| `R` | 稳态 RSS | measured |

- 触发边界：`d* = L - R（再占这么多内存就会触到限额）`
- 最坏情况倍数：`1`
- 保持时长：`120`
- 恢复观察窗：`300`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：内存压力上来时，运行时先抛出自己的内存不足错误（可观测、可降级），而不是被内核直接杀掉。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 容器是否被 OOMKilled | `status` |
| 运行时是否记录了内存不足异常 | `logs` |
| RSS 与内存限额的比值随注入的变化 | `metrics` |
| GC 频率与停顿时长（JVM） | `metrics` |

同一现象的其他解释（实验必须能排除）：

- OOM 来自以内存为介质的 emptyDir 占用而非进程堆
- 节点整体内存压力导致的驱逐，而不是容器超限

怎么修：按容器限额推导堆上限并为堆外留余量（改动层面：**config**）


### T-RESOURCE-03　连接池没有上限，或取连接不设等待上限

> 机制 `connection pool limits`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：数据库一变慢，应用线程全部卡在「等连接」上，连不碰数据库的接口也一起无响应。

#### 一 规则

连接池必须有连接数上限，且从池中获取连接的等待本身要有超时，否则依赖变慢会让调用方的线程全部阻塞在取连接上。

依据：

- `go-database-sql`（Go database/sql，database/sql > DB.SetMaxOpenConns）— database/sql package
  > If n <= 0, then there is no limit on the number of open connections. The default is 0 (unlimited).
- `hikaricp`（HikariCP，HikariCP README > Essentials > connectionTimeout）— HikariCP configuration
  > This property controls the maximum number of milliseconds that a client (that's you) will wait
  > for a connection from the pool. If this time is exceeded without a connection becoming
  > available, a SQLException will be thrown. Lowest acceptable connection timeout is 250 ms.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `hikari_connectionTimeout` | 30000 | ms | `hikaricp` |
| `go_maxOpenConns` | 0 | 连接（0 表示不限） | `go-database-sql` |

#### 二 定位

适用范围：

- 该服务通过连接池访问数据库、缓存或下游服务

角色：脆弱点在 **该连接池的上限与获取超时配置**；故障加在 **池后面的数据库、缓存或服务**；异常显现在 **该服务自身的线程占用与上游错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| HikariCP | maximumPoolSize 与 connectionTimeout（默认 30 秒，通常远大于上游预算） | `spring.datasource.hikari.*` |
| Go database/sql | SetMaxOpenConns 默认不限；获取等待要靠传入 context 的 deadline | `源码` |
| go-redis | PoolSize 与 PoolTimeout | `源码` |
| Jedis | JedisPoolConfig 的 maxTotal 与 maxWaitMillis | `源码` |
| Lettuce | 连接共享模型下靠命令超时兜底，需确认是否配了 timeout | `源码` |
| PostgreSQL | 连接串的 connect_timeout 与会话级 statement_timeout | `连接串与会话参数` |
| go-sql-driver/mysql | DSN 的 timeout / readTimeout / writeTimeout，三者缺省都不设上限 | `DSN` |
| StackExchange.Redis | ConnectTimeout 与 SyncTimeout | `源码（ConfigurationOptions）` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 池没有设连接数上限（或设成不限） | checkers/semgrep/go-sql-open-dsn-no-timeout.yaml（同一处构造点同时看 SetMaxOpenConns）；Java 侧交 manifest 读 maximumPoolSize |
| C2 | 必要 | `manifest` | 获取连接的等待没有超时，或超时值大于上游对本服务的超时 | spring.datasource.hikari.connectionTimeout 与上游对本服务的超时值 |
| C3 | 反证 | `llm` | 调用点传入了带 deadline 的 context，获取等待受它约束 | 该数据库或缓存调用是否通过带 deadline 的 context 发起？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C4 | 附注 | `runtime` | 池大小与该路径的并发量（决定占满所需的注入幅值） | 稳态下池的活跃连接数与该路径 QPS |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖变慢 | 连续幅值 | `injection_site` | 对数据库或缓存注入网络延迟，拉长每条连接的占用时长 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 让依赖端口拒绝连接，观察建连是否也无限等 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `N` | 池的连接数上限，不设时视为无穷 | manifest|code|default |
| `W` | 获取连接的等待上限 | manifest|default |
| `q` | 该路径的 QPS | measured |
| `b` | 单次数据库调用的基线耗时 | measured |
| `U` | 上游对本服务的超时 | manifest|requirement |

- 触发边界：`d* = N / q - b`
- 最坏情况倍数：`1`
- 保持时长：`W + U`
- 恢复观察窗：`2 * (W + U)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：依赖变慢把池占满后，新请求在获取超时处快速失败，服务的线程不会全部阻塞在取连接上。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 池的活跃连接数与等待队列长度 | `metrics` |
| 获取连接超时类错误计数 | `metrics` |
| 应用线程池的活跃线程数 | `metrics` |
| 该服务对所有接口（包括不走数据库的）的错误率 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 下游数据库自身拒绝新连接，问题在服务端而非池配置
- 线程阻塞来自锁竞争而不是取连接

怎么修：给池设连接数上限与获取等待上限，并把等待计入上游预算（改动层面：**config**）


### T-RESOURCE-04　关键负载的 QoS 等级使其先被驱逐

> 机制 `QoS class`　缺陷类别 **需求相对型**　参数类型 **离散动作**

**违反后的运行时表现**：节点内存一紧张，关键服务先被驱逐，批处理任务反而留在节点上继续跑。

#### 一 规则

需要在节点资源压力下活下来的负载，其 requests 与 limits 的写法应当落在最后才被驱逐的那一档上。

依据：

- `k8s-qos`（Kubernetes，Pod Quality of Service Classes > 概述）— Pod Quality of Service Classes
  > When a Node runs out of resources, Kubernetes will first evict BestEffort Pods running on that Node, followed by Burstable and finally Guaranteed Pods.
- `k8s-qos`（Kubernetes，Pod Quality of Service Classes > Guaranteed）— Pod Quality of Service Classes
  > Pods that are Guaranteed have the strictest resource limits and are least likely to face eviction.

#### 二 定位

适用范围：

- 节点上混布了不同重要性的负载
- 节点可能出现内存或磁盘压力

角色：脆弱点在 **该容器的 requests 与 limits 写法所决定的 QoS 等级**；故障加在 **承载该容器的节点**；异常显现在 **该服务的上游调用方**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Kubernetes | requests 等于 limits 且两者都设为 Guaranteed；只设 requests 为 Burstable；都不设为 BestEffort | `spec.template.spec.containers[*].resources` |
| kube-score | container-resource-requests-equal-limits（可选检查，用于要求 Guaranteed） | `kube-score 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 该工作负载落在 BestEffort 或 Burstable 档，而同节点存在更高档的非关键负载 | spec.template.spec.containers[*].resources 推导出的 QoS 等级，与同节点其他工作负载比较 |
| C2 | 反证 | `llm` | 该负载本就是可牺牲的批处理类工作 | 该工作负载是否属于可被随时驱逐的离线或批处理任务？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 附注 | `manifest` | 该节点上各工作负载的 QoS 等级分布 | 该节点上所有 Pod 的 status.qosClass |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 节点内存压力 | 连续幅值 | `injection_site` | 在该节点上逐步占用内存，触发 kubelet 的节点压力驱逐 | — |

#### 四 判定

预期行为：节点资源压力下先驱逐低档负载，关键服务保持在位。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 驱逐事件的顺序与被驱逐 Pod 的 qosClass | `events` |
| 关键服务的就绪副本数是否下降 | `status` |
| 节点的 MemoryPressure 状态变化时刻 | `status` |

同一现象的其他解释（实验必须能排除）：

- 驱逐顺序还受 Pod 优先级影响，需同时看 priorityClassName
- 被驱逐的是超出 requests 最多的 Pod，而不是 QoS 最低的

怎么修：关键负载写成 Guaranteed，非关键负载压到低档（改动层面：**config**）


---

## 机制组 `retry_backoff`


### T-RETRY-01　重试没有指数退避与随机抖动

> 机制 `retry backoff`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖失败期间与刚恢复时，下游 QPS 出现周期性同步尖峰，把刚缓过来的依赖再次打垮。

#### 一 规则

自动重试必须按指数退避安排，并在退避时长上加随机抖动，不能以固定间隔或零间隔连发。

依据：

- `sre-cascading-failures`（Google SRE，Retries > When issuing automatic retries）— SRE Book ch.22 Addressing Cascading Failures
  > Always use randomized exponential backoff when scheduling retries.
- `aws-builders-timeouts`（AWS Builders Library，Timeouts, retries and backoff with jitter > Jitter）— Timeouts, retries and backoff with jitter
  > When failures are caused by overload or contention, backing off often doesn't help as much as it seems like it should. This is because of correlation. If all the failed calls back off to the same time, they cause contention or overload again when they are retried. Our solution is jitter.
- `grpc-retry`（gRPC，Retry > Exponential backoff）— Retry
  > Jitter of plus or minus 20% is applied to the backoff delay to avoid hammering servers at the same time from a large number of clients.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `grpc_jitter` | ±20% | — | `grpc-retry` |

#### 二 定位

适用范围：

- 该出站路径上配置或实现了自动重试

角色：脆弱点在 **重试策略的配置或手写重试循环**；故障加在 **被重试的下游服务或中间件**；异常显现在 **下游服务的入站 QPS 与错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | service config 的 retryPolicy.initialBackoff / backoffMultiplier / maxBackoff | `service config` |
| Envoy | retry_policy.retry_back_off 的 base_interval 与 max_interval | `route.retry_policy` |
| Resilience4j | RetryConfig.intervalFunction 是否用了 ofExponentialRandomBackoff | `resilience4j.retry 配置或源码` |
| Polly | RetryStrategyOptions 的 BackoffType 与 UseJitter | `源码` |
| go-retryablehttp | RetryWaitMin / RetryWaitMax 与自定义 Backoff 函数 | `源码` |
| Spring Boot | @Retryable 是否带 @Backoff，是否用了 ExponentialRandomBackOffPolicy | `源码` |
| Microsoft.Extensions.Http.Resilience | AddStandardResilienceHandler 自带的重试段落是否被改成了无退避 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 重试策略没有指数退避（倍数缺失或等于 1），或退避没有抖动 | checkers/semgrep/java-spring-retry-no-backoff.yaml、checkers/semgrep/go-retry-loop-no-backoff.yaml；配置型框架交 manifest 读 retry_policy |
| C2 | 必要 | `codegraph` | 该重试作用在跨进程调用上（进程内重试不构成对下游的放大） | 起点为重试装饰器或重试循环，沿调用边查 3 跳内是否到达出站客户端 |
| C3 | 反证 | `manifest` | 该客户端库自带抖动且未被关闭（例如 gRPC 的 ±20%） | service config 的 retryPolicy 字段，或代理侧 retry_back_off 配置 |
| C4 | 附注 | `runtime` | 调用该下游的客户端实例数（抖动缺失时同步尖峰的高度与它成正比） | 注入期间同时在重试的客户端副本数 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖返回可重试错误 | 离散·有时长 | `injection_site` | 让下游在一段时间内稳定返回可重试状态码，制造全体客户端同时进入重试 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 中断该服务到下游的连接，恢复时观察重试是否成簇到达 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `i0` | 初始退避时长 | manifest|code|default |
| `m` | 退避倍数 | manifest|code|default |
| `n` | 最大尝试次数 | manifest|code|default |
| `N` | 同时重试的客户端副本数 | measured |
| `q` | 该路径的基线 QPS | measured |

- 触发边界：`d* = 0（只要下游持续返回可重试错误即可触发；本模板不靠幅值而靠持续时长）`
- 最坏情况倍数：`n`
- 保持时长：`i0 * (m ** n - 1) / (m - 1) + n * q`
- 恢复观察窗：`2 * i0 * (m ** n - 1) / (m - 1)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：依赖失败期间与恢复瞬间，下游入站 QPS 平滑上升，不出现周期性的同步尖峰。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 下游入站请求到达时刻的直方图是否成簇 | `metrics` |
| 重试间隔的实测分布是否呈指数增长且带离散 | `traces` |
| 依赖恢复瞬间下游 QPS 相对基线的峰值倍数 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 尖峰来自上游流量本身的波动，而不是重试
- 客户端副本数很少，成簇不明显

怎么修：指数退避加随机抖动，并设退避上限（改动层面：**config**）


### T-RETRY-02　重试次数没有上限

> 机制 `retry attempts`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖不可用期间下游入站 QPS 持续攀升而不是稳定在有限倍数，依赖恢复后又被积压的重试再次打垮。

#### 一 规则

每个请求的重试次数必须有上限，不能无限重试。

依据：

- `sre-cascading-failures`（Google SRE，Retries > When issuing automatic retries）— SRE Book ch.22 Addressing Cascading Failures
  > Limit retries per request. Don’t retry a given request indefinitely.
- `aws-builders-timeouts`（AWS Builders Library，Timeouts, retries and backoff with jitter > Backoff）— Timeouts, retries and backoff with jitter
  > In almost all cases, our solution is to limit the number of times that the client retries, and handle the resulting failure earlier in the service-oriented architecture.
- `istio-virtualservice`（Istio，VirtualService > HTTPRetry > attempts）— VirtualService reference (HTTPRetry, timeout)
  > Number of retries to be allowed for a given request.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `envoy_num_retries` | 1 | 次 | `envoy-route-retry` |

#### 二 定位

适用范围：

- 该出站路径上配置或实现了自动重试

角色：脆弱点在 **重试策略的次数上限配置或手写重试循环的退出条件**；故障加在 **被重试的下游服务或中间件**；异常显现在 **下游服务的入站 QPS**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | retryPolicy.maxAttempts（含首次） | `service config` |
| Envoy | retry_policy.num_retries，未配置时为 1 | `route.retry_policy.num_retries` |
| Istio | HTTPRetry.attempts；总请求数为 1 + attempts | `spec.http[*].retries.attempts` |
| Resilience4j | RetryConfig.maxAttempts | `resilience4j.retry 配置` |
| go-retryablehttp | Client.RetryMax | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `semgrep` | 重试配置里没有最大尝试次数，或手写重试循环的退出条件只依赖成功 | checkers/semgrep/go-retry-loop-no-backoff.yaml（同一处循环同时判次数上限）；配置型框架交 manifest |
| C2 | 必要 | `codegraph` | 该重试作用在跨进程调用上 | 起点为重试装饰器或重试循环，沿调用边查 3 跳内是否到达出站客户端 |
| C3 | 反证 | `manifest` | 外层有总截止时间，会在次数跑满前把整串重试截断 | 该路径的 route timeout 或调用点的 deadline |
| C4 | 附注 | `manifest` | 单次尝试的超时（与次数一起决定放大倍数的时间分布） | perTryTimeout 或客户端超时值 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖持续失败 | 离散·有时长 | `injection_site` | 让下游在整个注入窗内稳定返回可重试错误 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 让下游端口拒绝连接 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `n` | 最大尝试次数（含首次），无上限时视为无穷 | manifest|code|default |
| `A` | 放大倍数 = 下游入站请求数 / 上游入站请求数 | measured |
| `D` | 该路径的总截止时间 | manifest|requirement |
| `t` | 单次尝试的超时 | manifest|default |

- 触发边界：`d* = 0（下游持续失败即可触发）`
- 最坏情况倍数：`n`
- 保持时长：`min(D, n * t)`
- 恢复观察窗：`2 * min(D, n * t)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：下游持续不可用时，单个入站请求引发的出站尝试次数收敛到配置的上限。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 每个入站请求对应的出站尝试次数 | `traces` |
| 下游入站 QPS 与上游入站 QPS 的比值是否稳定 | `metrics` |
| 注入持续期间放大倍数是否随时间继续增长 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 放大来自调用链上多层各自重试（T-RETRY-03），而不是单层无上限
- 客户端在连接失败时自行重连，计入了尝试次数

怎么修：给每个请求设最大尝试次数，超出即向上报错（改动层面：**config**）


### T-RETRY-03　同一条调用链上多层都配了重试

> 机制 `retry layering`　缺陷类别 **组合型**　参数类型 **阈值型**

**违反后的运行时表现**：一次用户操作在最底层变成几十次请求，本已过载的依赖被重试彻底锁死，且各层看自己的配置都「合规」。

#### 一 规则

一条调用链上只应有一层做重试；每层都重试时，最底层承受的尝试次数是各层次数的乘积。

依据：

- `sre-cascading-failures`（Google SRE，Retries > When issuing automatic retries）— SRE Book ch.22 Addressing Cascading Failures
  > In particular, avoid amplifying retries by issuing retries at multiple levels: a single request at the highest layer may produce a number of attempts as large as the product of the number of attempts at each layer to the lowest layer.
- `azure-pattern-retry`（Azure Architecture Center，Retry pattern > Issues and considerations）— Retry pattern
  > Implement retry logic only where the full context of a failing operation is understood. For example, if a task that contains a retry policy invokes another task that also contains a retry policy, this extra layer of retries can add long delays to the processing.

#### 二 定位

适用范围：

- 一条调用链上存在两个及以上可配置重试的位置（网关 / 网格 / 客户端 SDK / 业务代码）

角色：脆弱点在 **该调用链上所有启用了重试的层**；故障加在 **调用链最底层的服务或中间件**；异常显现在 **最底层服务的入站 QPS**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Istio | 网格默认给 HTTP 路由带重试，应用层若也重试即成两层 | `spec.http[*].retries` |
| Envoy | route retry_policy 与应用内 SDK 重试叠加 | `route.retry_policy` |
| Spring Boot | RestClient / WebClient 重试、Spring Retry 注解与网格重试三层叠加 | `源码与网格配置` |
| Resilience4j | Retry 装饰器与底层 HTTP 客户端自带重试叠加 | `resilience4j.retry 配置与客户端构造代码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 同一条调用路径上启用了重试的层数大于 1 | 对该路径逐层取 spec.http[*].retries.attempts、route.retry_policy.num_retries，与代码侧重试点计数相加 |
| C2 | 必要 | `codegraph` | 代码侧确实存在一层重试（仅靠清单判不出应用内重试） | 起点为该服务的出站客户端调用点，向上查 3 跳内是否被重试装饰器或重试循环包裹 |
| C3 | 反证 | `manifest` | 内层被显式配置为不重试（attempts = 0 或 RetryMax = 0） | 内层的 retries.attempts 或 num_retries 取值 |
| C4 | 附注 | `manifest` | 各层的次数取值（用于算乘积） | 逐层的最大尝试次数 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 最底层依赖持续失败 | 离散·有时长 | `injection_site` | 让最底层服务在注入窗内稳定返回可重试错误 | — |
| 最底层依赖变慢 | 连续幅值 | `injection_site` | 注入延迟使每层的单次超时都被触发 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `k` | 该调用链上启用重试的层数 | manifest|code |
| `n_i` | 第 i 层的最大尝试次数 | manifest|code|default |
| `A` | 最底层实测放大倍数 | measured |
| `t_min` | 各层中最短的单次超时 | manifest|default |

- 触发边界：`d* = t_min（注入延迟超过最短的单次超时即可逐层触发重试）`
- 最坏情况倍数：`各层 n_i 的乘积`
- 保持时长：`k * t_min`
- 恢复观察窗：`2 * k * t_min`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：最底层依赖失败时，它收到的尝试次数与单层配置同量级，而不是各层次数的乘积。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 一次入口请求在最底层产生的请求计数 | `traces` |
| 最底层入站 QPS 与入口 QPS 的比值 | `metrics` |
| 各层的重试计数指标是否同时上升 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 单层次数配得很高，放大来自一层而非多层（用 C4 的逐层取值区分）
- 客户端连接重建被计成了业务重试

怎么修：只在最了解上下文的一层重试，其余层显式关掉（改动层面：**config**）


### T-RETRY-04　对不可重试的错误也重试

> 机制 `retryable condition`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：一个必然失败的请求被反复重试到用尽预算，既拖慢自己的响应，又把下游的处理能力耗在注定失败的请求上。

#### 一 规则

只有瞬时的、可重试的失败才应重试；永久错误与参数错误重试多少次都不会成功，只会白白消耗预算并压住下游。

依据：

- `sre-cascading-failures`（Google SRE，Retries > When issuing automatic retries）— SRE Book ch.22 Addressing Cascading Failures
  > Use clear response codes and consider how different failure modes should be handled. For example, separate retriable and nonretriable error conditions. Don’t retry permanent errors or malformed requests in a client, because neither will ever succeed.
- `azure-transient-faults`（Azure Architecture Center，Transient fault handling > Retry strategy guidelines）— Transient fault handling
  > Retry tasks only when the faults are transient, which the nature of the error typically indicates, and when the operation might succeed when retried. For HTTP-based services, status code 429 (Too Many Requests) and 5xx server errors are typical retry candidates. Most 4xx client errors, like 400, 401, 403, and 404, indicate problems that a retry doesn't resolve.

#### 二 定位

适用范围：

- 该出站路径上配置或实现了自动重试

角色：脆弱点在 **重试策略的可重试条件（状态码白名单或异常类型）**；故障加在 **被调用的下游服务**；异常显现在 **下游服务的入站 QPS 与该服务的响应耗时**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | retryPolicy.retryableStatusCodes 是否是白名单，是否混入了 INVALID_ARGUMENT | `service config` |
| Envoy | retry_on 的取值是否只含 5xx / gateway-error / reset / connect-failure | `route.retry_policy.retry_on` |
| Istio | HTTPRetry.retryOn | `spec.http[*].retries.retryOn` |
| Resilience4j | RetryConfig.retryExceptions / ignoreExceptions 是否按异常类型区分 | `resilience4j.retry 配置` |
| Polly | ShouldHandle 谓词是否按状态码与异常类型筛选 | `源码` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 可重试条件是「捕获所有异常就重试」，或白名单里混入了 4xx / 参数错误 / 鉴权失败 | spec.http[*].retries.retryOn 与 service config 的 retryableStatusCodes |
| C2 | 必要 | `llm` | 代码侧的重试没有按错误类型分支（catch (Exception) 后直接重试） | 该重试实现是否对所有异常一视同仁地重试？回答 成立 / 不成立 / 无法判定 + 文件:行 |
| C3 | 反证 | `manifest` | 重试条件是显式白名单且只含瞬时错误 | 重试条件配置的完整取值 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖返回确定性错误 | 离散·有时长 | `injection_site` | 让下游稳定返回 400 / INVALID_ARGUMENT 这类重试不会成功的响应 | — |
| 依赖返回可重试错误 | 离散·有时长 | `injection_site` | 作为对照组，让下游返回 503，确认重试机制本身在工作 | — |

#### 四 判定

预期行为：面对确定性错误时不发生重试，请求快速失败；面对可重试错误时才重试。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入确定性错误时下游收到的重复请求数是否仍为 1 | `traces` |
| 按状态码分组的重试计数 | `metrics` |
| 两组注入下该服务的响应耗时差异 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 下游把参数错误错误地映射成了 5xx，重试方其实没配错
- 客户端连接层面的重连被计成业务重试

怎么修：用白名单区分可重试与不可重试错误（改动层面：**config**）


### T-RETRY-05　没有重试预算，重试量不随失败率收敛

> 机制 `retry budget`　缺陷类别 **规范明示型**　参数类型 **阈值型**

**违反后的运行时表现**：依赖大面积失败时重试流量把它彻底压死，恢复之后又被积压的重试洪峰再打挂一次。

#### 一 规则

除了单请求的次数上限，进程整体还应有一个重试总量预算；预算耗尽时直接失败，不再重试。

依据：

- `sre-cascading-failures`（Google SRE，Retries > When issuing automatic retries）— SRE Book ch.22 Addressing Cascading Failures
  > Consider having a server-wide retry budget. For example, only allow 60 retries per minute in a process, and if the retry budget is exceeded, don’t retry; just fail the request.
- `grpc-retry`（gRPC，Retry > Retry throttling）— Retry
  > For each server, the gRPC client tracks a token_count (initially set to maxTokens). Failed RPCs decrement the count by 1, successful RPCs increment it by tokenRatio. If the token_count falls below half of maxTokens, retries are paused until the count recovers.
- `grpc-retry-grfc`（gRPC，gRFC A6 Client Retries > Throttling Retry Attempts and Hedged RPCs）— gRFC A6: client retries
  > gRPC prevents server overload due to retries and hedged RPCs by disabling these policies when the client’s ratio of failures to successes passes a certain threshold.

#### 二 定位

适用范围：

- 客户端对某个下游开启了自动重试

角色：脆弱点在 **该客户端的重试节流或预算配置**；故障加在 **被重试的下游服务**；异常显现在 **下游服务的入站 QPS 构成（首发 与 重试 的比例）**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| gRPC | service config 的 retryThrottling（maxTokens / tokenRatio），按 server name 统计 | `service config` |
| Envoy | cluster circuit_breakers.max_retries 限制并发重试数，是预算的一种近似 | `cluster.circuit_breakers` |
| Resilience4j | 无原生重试预算；需要用 RateLimiter 或熔断限制整体重试量 | `resilience4j 配置` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 没有配置重试节流或预算（缺失，或被设成等同于不限） | service config 的 retryThrottling 字段与 cluster.circuit_breakers.max_retries |
| C2 | 必要 | `manifest` | 该路径上确实启用了重试（否则预算无意义） | 该路径的重试配置是否存在且 attempts > 0 |
| C3 | 反证 | `manifest` | 下游侧已有针对该调用方的限流，能替代客户端预算的作用 | 下游的限流规则是否按调用方维度配置 |
| C4 | 附注 | `runtime` | 该依赖的正常错误率基线（预算阈值是否留有余量要靠它判断） | 无注入时该依赖的错误率 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 依赖大比例失败 | 连续幅值 | `injection_site` | 按比例让下游返回可重试错误，比例从低到高扫 | — |
| 依赖不可达 | 离散·有时长 | `injection_site` | 让下游完全不可达，观察重试占比是否被压住 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `f` | 注入的下游失败比例 | measured |
| `n` | 单请求最大尝试次数 | manifest|default |
| `r` | 预算允许的重试占比，无预算时视为无穷 | manifest|default |
| `A` | 实测放大倍数 | measured |

- 触发边界：`d* = 失败比例扫到使 A 超过 1 + r 的那个 f`
- 最坏情况倍数：`n`
- 保持时长：`60（按 SRE 给的「每分钟若干次」量级取一个完整统计窗）`
- 恢复观察窗：`120`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：下游失败率升高时，重试流量占比被压在预算之内，放大倍数收敛而不是趋近于次数上限。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 重试请求数占该客户端出站总请求数的比例 | `metrics` |
| 因预算耗尽而被本地丢弃的重试计数 | `metrics` |
| 下游入站 QPS 随注入失败率的变化曲线 | `metrics` |

同一现象的其他解释（实验必须能排除）：

- 熔断先于预算打开，重试量下降来自熔断而非预算
- 上游流量本身在故障期间下降

怎么修：按失败与成功的比例节流重试，预算耗尽即直接失败（改动层面：**config**）


---

## 机制组 `service_discovery`


### T-DISCOVERY-01　注册中心不可用时客户端解析不到地址

> 机制 `registry client local cache`　缺陷类别 **需求相对型**　参数类型 **离散动作**

**违反后的运行时表现**：注册中心一挂，正在跑的实例还撑得住，一旦有实例重启就再也起不来——故障范围随重启逐步扩大。

#### 一 规则

注册中心不可用时，客户端应当能用本地缓存继续解析服务地址；这条要求在实例冷启动那一刻同样成立。

依据：

- `nacos-java-failover`（Nacos，Java SDK 容灾 > 使用场景）— Java SDK 容灾
  > 在Nacos运行期间，突然出现接口不可用或者数据异常，我们可以快速的开启容灾，让客户端使用容灾数据，减小服务受影响的窗口，等Nacos服务端恢复后再关闭容灾；
- `nacos-java-properties`（Nacos，Java SDK 配置项 > 注册中心）— Java SDK 配置项
  > namingLoadCacheAtStart | NAMING_LOAD_CACHE_AT_START | 注册中心NamingService在启动时读取本地磁盘缓存来初始化数据 | boolean | false

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `namingLoadCacheAtStart` | false | 布尔 | `nacos-java-properties` |

#### 二 定位

适用范围：

- 该服务通过注册中心解析下游地址（而不是固定域名或 Kubernetes Service）

角色：脆弱点在 **该服务的注册中心客户端配置（本地缓存与启动时读盘）**；故障加在 **注册中心**；异常显现在 **该服务对下游的调用成功率，以及它自身的启动过程**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Nacos | 是否开启本地容灾；namingLoadCacheAtStart 默认 false，冷启动时不读磁盘缓存 | `nacos 客户端 properties` |
| Eureka | 客户端本地注册表缓存与增量拉取；注册中心不可用时沿用最后一次拉到的列表 | `eureka.client.* 配置` |
| Consul | 通过本地 agent 访问可缓解 server 不可用，需确认应用连的是 agent 还是 server | `客户端连接地址配置` |
| Spring Cloud LoadBalancer | 服务实例列表的本地缓存与其 ttl | `spring.cloud.loadbalancer.cache.*` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 客户端没有开启本地缓存或容灾，或缓存只在内存里、进程重启即丢 | 注册中心客户端配置里的本地缓存与容灾开关取值 |
| C2 | 必要 | `manifest` | 冷启动路径不允许从本地缓存初始化（例如 namingLoadCacheAtStart 落在 false 默认值上） | 客户端配置里的启动时读盘开关 |
| C3 | 反证 | `codegraph` | 该服务其实不经注册中心解析地址（用的是集群内 Service 名或固定域名） | 起点为该服务的出站客户端构造点，检查地址来源是注册中心 API 还是静态配置 |
| C4 | 附注 | `runtime` | 本地缓存文件是否真实存在并被读取 | 观察客户端缓存目录下是否有服务列表文件，以及重启时是否被加载 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 注册中心不可达 | 离散·有时长 | `injection_site` | 切断该服务到注册中心的网络，保持下游服务本身正常 | — |
| 注册中心不可达期间重启实例 | 离散·有数量 | `defect_site` | 在注册中心仍不可达时删除该服务的一个 Pod，检验新实例能否起来并解析到地址 | — |

#### 四 判定

预期行为：注册中心不可用期间，已在运行的实例继续正常调用；期间重启的实例也能从本地缓存拿到地址并进入就绪。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注册中心不可达期间该服务对下游的调用成功率 | `metrics` |
| 期间重启的实例能否进入就绪 | `status` |
| 解析失败类错误（服务列表为空、找不到实例）的计数 | `logs` |
| 客户端本地缓存文件的读取记录 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 下游地址其实由 Kubernetes Service 解析，注册中心只用于元数据
- 调用方有长连接复用，注入窗内没有触发新的地址解析

怎么修：开启客户端本地缓存并落盘，允许冷启动时从缓存初始化（改动层面：**config**）


### T-DISCOVERY-02　实例已经不可用但仍被解析到

> 机制 `instance eviction delay`　缺陷类别 **需求相对型**　参数类型 **阈值型**

**违反后的运行时表现**：实例已经死了，调用方还在往它身上打流量，错误率稳定在 1/n 附近持续好几十秒才回落。

#### 一 规则

实例失效到它从解析结果中消失之间有一段延迟，这段延迟由心跳间隔、容忍次数与客户端缓存 ttl 叠加而成，必须与调用方能承受的失败比例相称。

依据：

- `eureka-client`（Eureka，Spring Cloud Netflix > Service Discovery: Eureka Clients）— Spring Cloud Netflix: Eureka client and server
  > Eureka receives heartbeat messages from each instance belonging to a service. If the heartbeat fails over a configurable timetable, the instance is normally removed from the registry.
- `eureka-client`（Eureka，Spring Cloud Netflix > Why Is It so Slow to Register a Service?）— Spring Cloud Netflix: Eureka client and server
  > Being an instance also involves a periodic heartbeat to the registry (through the client’s serviceUrl) with a default duration of 30 seconds. A service is not available for discovery by clients until the instance, the server, and the client all have the same metadata in their local cache (so it could take 3 heartbeats).
- `consul-health-checks`（Consul，Define health checks > Types of checks）— Define health checks
  > Time-to-live (TTL) checks are passive checks that await updates from the service. If the check does not receive a status update before the specified duration, the health check enters a criticalstate.

文档给出的默认值：

| 符号 | 值 | 单位 | 出处 |
|---|---|---|---|
| `leaseRenewalIntervalInSeconds` | 30 | s | `eureka-client` |

#### 二 定位

适用范围：

- 下游地址通过注册中心解析
- 调用方侧还有一层服务实例列表缓存

角色：脆弱点在 **心跳间隔、剔除容忍次数与客户端缓存 ttl 三者的组合**；故障加在 **下游服务的一个实例**；异常显现在 **调用方看到的错误率**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Eureka | eureka.instance.leaseRenewalIntervalInSeconds（默认 30 秒）与服务端剔除周期，再加客户端缓存 | `eureka.instance.* 与 eureka.client.* 配置` |
| Nacos | 临时实例靠心跳维持，持久实例靠服务端主动健康检查；两类的剔除时机不同 | `nacos 客户端与集群健康检查配置` |
| Consul | TTL 检查在超过指定时长没收到更新时进入 critical，此后不再被发现 | `服务注册时的 check 定义` |
| Spring Cloud LoadBalancer | 实例列表缓存的 ttl，会叠加在注册中心的剔除延迟之上 | `spring.cloud.loadbalancer.cache.ttl` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 心跳间隔与容忍次数沿用默认值，没有按调用方的容忍度调过 | 注册中心客户端的心跳间隔与服务端的剔除阈值配置 |
| C2 | 必要 | `manifest` | 调用方侧还有一层实例列表缓存，其 ttl 叠加在剔除延迟之上 | spring.cloud.loadbalancer.cache.ttl 或等价的客户端缓存配置 |
| C3 | 反证 | `manifest` | 调用方有异常实例剔除或熔断，能在注册中心之前把坏实例摘掉 | 该调用路径上的 outlierDetection 或熔断配置 |
| C4 | 附注 | `manifest` | 调用方对该下游的重试配置（决定单次解析到坏实例是否会被掩盖） | 该路径的重试次数与可重试条件 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 单实例强制终止 | 离散·有数量 | `injection_site` | 直接删除下游的一个 Pod，不给它主动注销的机会 | — |
| 单实例网络隔离 | 离散·有时长 | `injection_site` | 切断该实例与注册中心之间的网络，但保留它与调用方之间的网络 | — |

参数关系：

| 符号 | 含义 | 取值来源 |
|---|---|---|
| `H` | 心跳间隔 | manifest|default |
| `k` | 剔除前容忍的心跳丢失次数 | manifest|default |
| `C` | 客户端实例列表缓存的 ttl | manifest|default |
| `n` | 下游实例数 | manifest|measured |
| `q` | 调用方对该下游的 QPS | measured |

- 触发边界：`d* = 1（终止一个实例即可触发）；总剔除延迟 T_evict = H * k + C`
- 最坏情况倍数：`1`
- 保持时长：`2 * (H * k + C)`
- 恢复观察窗：`2 * (H * k + C)`

余量与安全系数由下游流水线统一取，模板不写。

#### 四 判定

预期行为：实例失效后在可接受的时间内从解析结果中消失，期间落到它身上的失败请求数在预算之内。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 从实例终止到服务列表中不再出现它的时长 | `logs` |
| 该时间窗内打到已死实例的请求数 | `traces` |
| 调用方错误率的峰值与持续时长 | `metrics` |
| 客户端实例列表刷新的时刻 | `logs` |

同一现象的其他解释（实验必须能排除）：

- 调用方的熔断或异常剔除先起作用，掩盖了注册中心的剔除延迟
- 长连接复用使调用方在缓存过期前不会重新解析

怎么修：按可接受的失败比例反推心跳间隔与缓存 ttl，并用客户端侧的异常剔除兜住这段延迟（改动层面：**config**）


### T-DISCOVERY-03　注册状态不反映应用的真实健康

> 机制 `registry health propagation`　缺陷类别 **规范明示型**　参数类型 **离散动作**

**违反后的运行时表现**：实例的业务功能已经完全不可用，注册中心里它还是 UP，上游持续把流量发过去，错误率稳定在 1/n 不降。

#### 一 规则

注册中心里的实例状态应当反映应用自身的健康判断；只靠心跳判活时，进程活着但业务不可用的实例仍会被当成可用实例发出去。

依据：

- `eureka-client`（Eureka，Spring Cloud Netflix > Status Page and Health Indicator）— Spring Cloud Netflix: Eureka client and server
  > By default, Eureka uses the client heartbeat to determine if a client is up. Unless specified otherwise, the Discovery Client does not propagate the current health check status of the application, per the Spring Boot Actuator. Consequently, after successful registration, Eureka always announces that the application is in 'UP' state.
- `nacos-java-properties`（Nacos，Java SDK 配置项 > 通用 GRPC 配置）— Java SDK 配置项
  > nacos.remote.client.grpc.health.retry | 该Nacos Java SDK的GRPC连接的健康检查重试次数，达到这个次数健康检查失败的连接会被客户端强制关闭，进行重连 | 任意int值 | 3

#### 二 定位

适用范围：

- 该服务把自己注册到注册中心，且下游调用方按注册结果选实例

角色：脆弱点在 **该服务的注册客户端健康上报配置**；故障加在 **该服务的进程外依赖（让业务不可用但进程存活）**；异常显现在 **调用该服务的上游**。

落点：

| 组件 | 怎么落 | 配置键或代码 |
|---|---|---|
| Eureka | 是否启用了把 Actuator 健康状态上报给注册中心的开关；不启用时注册后恒为 UP | `eureka.client.healthcheck.enabled` |
| Nacos | 临时实例靠心跳与连接生命周期判活，业务不可用不会自动反映到实例健康上 | `nacos 客户端注册参数` |
| Consul | 注册时是否定义了能反映业务健康的 check，而不是只有 TTL 或端口探测 | `服务注册时的 check 定义` |
| Spring Boot Actuator | readiness 分组的判据是否被接到注册中心的健康上报上 | `management.endpoint.health.group.readiness.include` |

检查项：

| id | 类型 | 判定方式 | 要查什么 | 查询 |
|---|---|---|---|---|
| C1 | 必要 | `manifest` | 注册客户端没有启用应用健康状态上报，实例状态只由心跳或端口连通性决定 | eureka.client.healthcheck.enabled 与等价的注册中心健康上报开关 |
| C2 | 必要 | `codegraph` | 该服务确有「进程活着但业务不可用」的状态（例如关键依赖不可用时无法服务） | 起点为该服务的对外接口处理函数，沿调用边查 4 跳内是否存在无法降级的关键依赖调用 |
| C3 | 反证 | `codegraph` | 上游不按注册结果选实例，而是走 Kubernetes Service 与就绪探针 | 起点为上游的出站客户端构造点，检查地址来源是注册中心还是集群内 Service |
| C4 | 附注 | `manifest` | 该服务的就绪探针判据是否已覆盖这类状态（两条路径可能不一致） | spec.template.spec.containers[*].readinessProbe 与健康分组配置 |

#### 三 实验

| 动作 | 类型 | 作用对象 | 注入手法 | 触发条件 |
|---|---|---|---|---|
| 关键依赖不可达 | 离散·有时长 | `injection_site` | 让该服务的关键依赖不可用，使它能应答 HTTP 但处理不了业务 | — |
| 关键依赖变慢 | 连续幅值 | `injection_site` | 注入延迟使业务处理超时，但进程与端口仍然正常 | — |

#### 四 判定

预期行为：应用进入不可服务状态后，注册中心里的实例状态随之变为不可用，上游不再把流量发给它。

看哪些信号：

| 信号 | 来源 |
|---|---|
| 注入期间注册中心里该实例的状态 | `status` |
| 上游在注入期间仍打到该实例的请求数 | `traces` |
| 上游对该服务的错误率 | `metrics` |
| 该实例就绪探针状态与注册状态是否一致 | `status` |

同一现象的其他解释（实验必须能排除）：

- 上游其实走 Kubernetes Service，就绪探针已经把它摘了
- 上游有异常实例剔除，掩盖了注册状态没变的影响

怎么修：把应用的就绪判据接到注册中心的健康上报上（改动层面：**config**）


---

## advisory（本版不生成场景）


### A-RETRY-01　重试放大把过载推成自持

> 机制组 `retry_backoff`　参数类型 **概率型**

当下游因过载开始拒绝时，重试带来的额外流量会把下游推得更满，进而产生更多拒绝，形成自持的正反馈。

- `sre-cascading-failures`（Google SRE，Retries）
  > The volume of retries grows: 100 QPS of retries in the first second leads to 200 QPS, then to 300 QPS, and so on. Fewer and fewer requests are able to succeed on their first attempt, so less useful work is being performed as a fraction of requests to the backend.
- `sre-cascading-failures`（Google SRE，Retries）
  > If the backend spends a significant amount of resources processing requests that will ultimately fail due to overload, then the retries themselves may be keeping the backend in an overloaded mode.

- **本版为什么不支持**：是否进入正反馈取决于下游容量、当前负载水位与拒绝成本的比值，同一份配置在不同负载下结论相反，写不出与配置参数挂钩的判定边界。
- **要支持它还缺什么**：需要下游的容量曲线（吞吐随并发的拐点）、拒绝一个请求相对处理一个请求的成本比，以及注入时的实际负载水位；具备这三项后可退化为一条以负载水位为自变量的阈值规则。

### A-RETRY-02　重试与熔断的相互作用

> 机制组 `retry_backoff`　参数类型 **状态型**

重试逻辑应当识别熔断器给出的拒绝，并在熔断指示故障不是瞬时的时候停止重试。

- `azure-pattern-circuit-breaker`（Azure Architecture Center，Circuit Breaker pattern > Comparison to the Retry pattern）
  > An application can combine these two patterns by using the Retry pattern to invoke an operation through a circuit breaker. However, the retry logic should be sensitive to any exceptions that the circuit breaker returns and stop retry attempts if the circuit breaker indicates that a fault isn't transient.

- **本版为什么不支持**：判定要看熔断器当时处于哪个状态、以及重试是否把「熔断拒绝」计入了失败，属状态相关；同样的配置在闭合态与打开态下的正确行为不同，无法只凭静态配置判出违反。
- **要支持它还缺什么**：需要能在运行时读取熔断器状态机的当前状态与状态变迁时刻，并能把每次重试决策与当时的状态对齐。

### A-SHED-01　过载解除后系统回不到正常态（亚稳态）

> 机制组 `load_shedding_admission`　参数类型 **滞后型**

触发过载的条件消失之后，系统可能仍停在低吞吐的过载态，需要显著降低负载或切断流量才能恢复。

- `sre-cascading-failures`（Google SRE，Retries）
  > Even if the rate of calls to MakeRequest decreases to pre-meltdown levels (9,000 QPS, for example), depending on how much returning a failure costs the backend, the problem might not go away.
- `sre-cascading-failures`（Google SRE，Retries）
  > If either of these conditions is true, in order to dig out of this outage, you must dramatically reduce or eliminate the load on the frontends until the retries stop and the backends stabilize.

- **本版为什么不支持**：判定要看「撤销注入之后系统是否自行回到基线」，而进入与退出的负载阈值不同（滞后），退出阈值取决于队列里积压了多少、重试预算恢复得多快，无法从配置参数算出一个边界。
- **要支持它还缺什么**：需要在撤销注入后持续观测足够长的窗口，并能比较进入过载与退出过载两个方向的负载阈值；还需要能测出积压深度随时间的衰减速率。

### A-SHED-02　客户端自适应节流

> 机制组 `load_shedding_admission`　参数类型 **状态型**

后端开始拒绝时，客户端应当按后端的接受率自适应地降低发出量，而不是把拒绝的开销全留给后端。

- `sre-handling-overload`（Google SRE，Client-Side Throttling > Client request rejection probability）
  > As the rate at which the application attempts requests to the client grows (relative to the rate at which the backend accepts them), we want to increase the probability of dropping new requests.
- `sre-handling-overload`（Google SRE，Client-Side Throttling > Client request rejection probability）
  > We've found adaptive throttling to work well in practice, leading to stable rates of requests overall.

- **本版为什么不支持**：是否违反取决于客户端本地统计的「请求数 / 接受数」滑动状态，而这个状态既不在配置里也不在代码常量里；同一份代码在不同后端拒绝率下表现不同，静态查不出，运行时也需要客户端自报该状态才能判。
- **要支持它还缺什么**：需要客户端暴露自适应节流的内部状态（请求数、接受数、本地丢弃数）作为指标，或在实验中能按已知比例控制后端的拒绝率并观测客户端发出量的响应曲线。

### A-CONN-01　连接或资源泄漏导致的缓慢耗尽

> 机制组 `connection_lifecycle`　参数类型 **累积型**

派生出的 context、连接与游标若没有在所有控制流路径上释放，会随请求量累积，直到资源耗尽。

- `go-context`（Go context，context package > Overview）
  > Failing to call the CancelFunc leaks the child and its children until the parent is canceled. The go vet tool checks that CancelFuncs are used on all control-flow paths.

- **本版为什么不支持**：是否出问题取决于泄漏速率与总量的乘积随时间的累积，同一处泄漏在低流量下几个月都不发作、在高流量下几分钟就耗尽；注入一次故障看不出结论，需要长时间基线对比。
- **要支持它还缺什么**：需要在恒定负载下长时间观测资源占用的斜率（连接数、协程数、文件描述符随时间的增长），并能把斜率归因到具体的代码路径。

### A-IDEM-01　副作用与确认之间的时序窗口

> 机制组 `idempotency_compensation`　参数类型 **时机型**

业务副作用与对外确认之间存在一个时间窗，在这个窗口内中断会造成「做了但没记」或「记了但没做」。

- `aws-builders-idempotency`（AWS Builders Library，Making retries safe with idempotent APIs > Reducing client complexity with idempotent API design）
  > An important consideration is that the process that combines recording the idempotent token and all mutating operations related to servicing the request must meet the properties for an atomic, consistent, isolated, and durable (ACID) operation.

- **本版为什么不支持**：触发与否取决于中断恰好落在哪个毫秒级窗口内，是时机相关而非幅值相关；现有的实例终止原语无法把中断精确对齐到那个窗口，反复注入也只是概率命中。
- **要支持它还缺什么**：需要能在指定代码点暂停或终止进程的注入能力（故障点注入），或能在测试环境里对该窗口加锁放大，才能把它变成可稳定复现的场景。
