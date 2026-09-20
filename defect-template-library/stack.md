# stack.md —— 技术栈层次、组件与文档对应

本库的规则依据只来自两类材料：**组件官方文档**，以及**公认准则**（云厂商可靠性框架与设计模式目录、Google SRE 书、AWS Builders' Library、Kubernetes 生态检查工具的规则清单、Principles of Chaos Engineering）。事故报告与博客不作为规则依据，只可能出现在模板的 `evidence_incidents` 里作佐证。

模板本身与具体系统无关；与组件有关的内容只出现在 `locate.instantiations`（这条规则在该组件里落在哪个配置键或代码写法上）。下表的 `doc_id` 与 `documents.yaml`、`docs-cache/<doc_id>.txt` 一一对应。

## 覆盖范围与取舍

- **收**：机制有显式的、能从配置或代码读到的参数（阈值型），或动作离散且预期行为能用现有信号写成断言（离散动作）。
- **转 advisory**：参数关系属于概率型、累积型、滞后型、组合型、时机型、状态型的规则，登记在 `advisories.yaml`，本版不生成场景。
- **不收**：优雅终止族（SIGTERM、preStop、在途请求排空）、安全（认证授权、泄露、注入）、可观测性配置（采样率、日志级别）、跨区域灾备与备份恢复、纯性能调优。**例外**：「故障恢复后回不来」保留在本库内。

## 版本口径

每个组件取当前稳定版文档；文档站自报的版本记在 `documents.yaml` 的 `version` 字段，取不到则记 `unversioned`，不臆造版本号。取回日期记在 `retrieved_at`。同一组件不同大版本语义不同时分开登记 doc_id（本版暂无此情况）。

## 文档副本的许可口径

`documents.yaml` 的 `redistribution` 字段分两档：

- `permissive`（74 份）：来源明确采用开放许可（CC BY、Apache-2.0、MIT、BSD、PostgreSQL License 等），`docs-cache/<doc_id>.txt` 存**全文正文**，任何人都能直接复核引用。
- `restricted`（24 份）：厂商版权文档或未标注许可（Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB、Principles of Chaos Engineering），不作全文再分发；`docs-cache/<doc_id>.txt` 只存**本库实际逐字引用到的段落及其所在小节标题**，足以逐字复核，需要全文请按登记的网址到原站点阅读。

两档的 `sha256` 都是对入库那份文件算的，`validate.py` 按它核对引用；`source_sha256` 是抓回的完整正文的摘要，用来判断原站点是否已改版。全文副本保留在本地 `docs-cache/.full/`，由 `.gitignore` 排除。

## 层次与组件

| 层 | 组件 | doc_id | 文档 |
|---|---|---|---|
| **容器编排** | Kubernetes | `k8s-probes-concept` | Liveness, Readiness, and Startup Probes |
|  |  | `k8s-probes-task` | Configure Liveness, Readiness and Startup Probes |
|  |  | `k8s-pod-lifecycle` | Pod Lifecycle |
|  |  | `k8s-resources` | Resource Management for Pods and Containers |
|  |  | `k8s-qos` | Pod Quality of Service Classes |
|  |  | `k8s-disruptions` | Disruptions |
|  |  | `k8s-pdb-task` | Specifying a Disruption Budget for your Application |
|  |  | `k8s-hpa` | Horizontal Pod Autoscaling |
|  |  | `k8s-topology-spread` | Pod Topology Spread Constraints |
|  |  | `k8s-affinity` | Assigning Pods to Nodes |
|  |  | `k8s-eviction` | Node-pressure Eviction |
|  |  | `k8s-deployment` | Deployments (rolling update parameters) |
|  |  | `k8s-config-best-practices` | Configuration Best Practices |
| **入口与代理** | Envoy | `envoy-timeouts` | FAQ: Envoy timeouts |
|  |  | `envoy-route-retry` | HTTP route components (timeout, retry_policy) |
|  |  | `envoy-circuit-breaking` | Circuit breaking |
|  |  | `envoy-outlier-detection` | Outlier detection |
|  |  | `envoy-health-checking` | Health checking |
|  | Istio | `istio-virtualservice` | VirtualService reference (HTTPRetry, timeout) |
|  |  | `istio-destinationrule` | DestinationRule reference (connectionPool, outlierDetection) |
|  |  | `istio-request-timeouts` | Request Timeouts |
|  | ingress-nginx | `ingress-nginx-annotations` | NGINX Ingress annotations |
| **RPC 与 HTTP 客户端** | gRPC | `grpc-deadlines` | Deadlines |
|  |  | `grpc-cancellation` | Cancellation |
|  |  | `grpc-keepalive` | Keepalive |
|  |  | `grpc-retry` | Retry |
|  |  | `grpc-retry-grfc` | gRFC A6: client retries |
|  | Go context | `go-context` | context package |
|  | Go net/http | `go-net-http` | net/http package |
|  | Spring Boot | `spring-rest-clients` | REST Clients |
|  | Spring Cloud OpenFeign | `spring-cloud-openfeign` | Spring Cloud OpenFeign reference |
|  | undici | `node-undici` | undici Dispatcher / Client API |
|  | axios | `axios` | axios request config |
|  | .NET HttpClient | `dotnet-httpclient-guidelines` | HttpClient guidelines for .NET |
|  |  | `dotnet-httpclient-factory` | IHttpClientFactory with .NET |
|  | Python requests | `python-requests-advanced` | Advanced Usage (timeouts) |
|  | Python httpx | `python-httpx-timeouts` | Timeouts |
|  | reqwest | `rust-reqwest` | reqwest ClientBuilder |
|  | Ruby Net::HTTP | `ruby-net-http` | Net::HTTP |
|  | Guzzle | `php-guzzle` | Guzzle request options |
| **容错库** | Resilience4j | `resilience4j-retry` | Retry |
|  |  | `resilience4j-circuitbreaker` | CircuitBreaker |
|  |  | `resilience4j-bulkhead` | Bulkhead |
|  |  | `resilience4j-timelimiter` | TimeLimiter |
|  |  | `resilience4j-ratelimiter` | RateLimiter |
|  | Polly | `polly-retry` | Retry resilience strategy |
|  |  | `polly-circuit-breaker` | Circuit breaker resilience strategy |
|  |  | `polly-timeout` | Timeout resilience strategy |
|  | Microsoft.Extensions.Http.Resilience | `dotnet-http-resilience` | Build resilient HTTP apps |
|  | gobreaker | `gobreaker` | sony/gobreaker package |
|  | go-retryablehttp | `go-retryablehttp` | hashicorp/go-retryablehttp package |
| **健康端点** | Spring Boot Actuator | `spring-boot-actuator` | Actuator endpoints (health groups, Kubernetes probes) |
|  | ASP.NET Core | `aspnet-health-checks` | Health checks in ASP.NET Core |
| **服务发现** | Nacos | `nacos-java-properties` | Java SDK 配置项 |
|  |  | `nacos-java-failover` | Java SDK 容灾 |
|  |  | `nacos-instance-lifecycle` | 实例生命周期 |
|  | Spring Cloud LoadBalancer | `spring-cloud-loadbalancer` | Spring Cloud Commons: LoadBalancer |
| **数据库客户端与连接池** | Go database/sql | `go-database-sql` | database/sql package |
|  | go-sql-driver/mysql | `go-sql-driver-mysql` | DSN parameters |
|  | HikariCP | `hikaricp` | HikariCP configuration |
|  | PostgreSQL | `postgres-libpq-connect` | libpq connection parameters (connect_timeout) |
|  |  | `postgres-runtime-client` | Client connection defaults (statement_timeout) |
|  | MongoDB driver | `mongodb-connection-options` | Connection String Options |
| **缓存客户端** | Jedis | `jedis` | Jedis README (pool, timeouts) |
|  | Lettuce | `lettuce` | Lettuce Client Options (timeout, auto-reconnect) |
|  | go-redis | `go-redis` | go-redis v9 Options |
|  | ioredis | `ioredis` | ioredis README |
|  | redis-py | `redis-py` | redis-py connection examples |
|  | StackExchange.Redis | `stackexchange-redis` | Configuration options |
| **消息** | RabbitMQ | `rabbitmq-reliability` | Reliability Guide |
|  |  | `rabbitmq-confirms` | Consumer Acknowledgements and Publisher Confirms |
|  |  | `rabbitmq-prefetch` | Consumer Prefetch |
|  |  | `rabbitmq-dlx` | Dead Letter Exchanges |
|  | Kafka | `kafka-producer-config` | Producer configs |
|  |  | `kafka-consumer-config` | Consumer configs |
|  |  | `kafka-topic-config` | Topic configs |
| **语言运行时** | JVM | `jvm-launcher` | java command (UseContainerSupport, MaxRAMPercentage) |
|  | Node.js | `node-http` | HTTP (agent, keepAlive, timeouts) |
| **通用准则** | Google SRE | `sre-handling-overload` | SRE Book ch.21 Handling Overload |
|  |  | `sre-cascading-failures` | SRE Book ch.22 Addressing Cascading Failures |
|  | AWS Builders Library | `aws-builders-timeouts` | Timeouts, retries and backoff with jitter |
|  |  | `aws-builders-idempotency` | Making retries safe with idempotent APIs |
|  |  | `aws-builders-avoiding-fallback` | Avoiding fallback in distributed systems |
|  |  | `aws-builders-load-shedding` | Using load shedding to avoid overload |
|  |  | `aws-builders-health-checks` | Implementing health checks |
|  | AWS Well-Architected | `aws-war-reliability` | Reliability Pillar: graceful degradation |
|  | Azure Architecture Center | `azure-pattern-retry` | Retry pattern |
|  |  | `azure-pattern-circuit-breaker` | Circuit Breaker pattern |
|  |  | `azure-pattern-bulkhead` | Bulkhead pattern |
|  |  | `azure-pattern-throttling` | Throttling pattern |
|  |  | `azure-pattern-health-endpoint` | Health Endpoint Monitoring pattern |
|  |  | `azure-pattern-queue-leveling` | Queue-Based Load Leveling pattern |
|  |  | `azure-pattern-compensating` | Compensating Transaction pattern |
|  |  | `azure-pattern-cache-aside` | Cache-Aside pattern |
|  |  | `azure-transient-faults` | Transient fault handling |
|  | Polaris | `polaris-checks-reliability` | Polaris Checks: Reliability |
|  | kube-score | `kube-score-checks` | kube-score checks list |
|  | Principles of Chaos Engineering | `chaos-principles` | Principles of Chaos Engineering |

## 机制组

slug 与本仓库审计终稿 `final-defects.json` 的 `family` 词表保持一致，便于交叉引用：

| slug | 覆盖的机制 |
|---|---|
| `deadline_timeout` | 超时、截止时间、取消传播 |
| `retry_backoff` | 重试次数、退避与抖动、重试预算 |
| `circuit_isolation` | 熔断、隔离舱、并发上限、outlier detection |
| `load_shedding_admission` | 限流、过载保护、队列上限、背压 |
| `health_probe` | 存活 / 就绪 / 启动探针、健康分组 |
| `replica_disruption` | 副本数、PDB、反亲和与拓扑分布、滚动更新参数 |
| `resource_limit` | 请求与限额、堆与限额的关系、连接池与线程池上限 |
| `fallback_degradation` | 降级、回退、默认值、缓存兜底 |
| `idempotency_compensation` | 幂等键、补偿、副作用顺序 |
| `delivery_semantics` | 消息确认、持久化、重投、死信、消费幂等 |

读文档时遇到不属于以上任何一组的机制，会新建一组并在 `CHANGES.md` 写明理由；`final-defects.json` 里这类机制归在 `other（…）` 下。
