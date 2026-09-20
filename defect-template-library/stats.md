<!-- 由 stats.py 生成，请勿手改；改了 YAML 后重新运行 python3 stats.py -->

# stats.md —— 缺陷模板库统计

## 1 文档

### 1.1 组件文档（按层与组件）

| 层 | 组件 | 文档数 | 全文入库 | 仅摘录入库 |
|---|---|---|---|---|
| 健康端点 | ASP.NET Core | 1 | 0 | 1 |
| 健康端点 | Spring Boot Actuator | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | .NET HttpClient | 2 | 0 | 2 |
| RPC 与 HTTP 客户端 | Go context | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Go net/http | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Guzzle | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Python httpx | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Python requests | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Ruby Net::HTTP | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Spring Boot | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | Spring Cloud OpenFeign | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | axios | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | gRPC | 5 | 5 | 0 |
| RPC 与 HTTP 客户端 | reqwest | 1 | 1 | 0 |
| RPC 与 HTTP 客户端 | undici | 1 | 1 | 0 |
| 服务发现 | Consul | 1 | 0 | 1 |
| 服务发现 | Eureka | 1 | 1 | 0 |
| 服务发现 | Nacos | 3 | 3 | 0 |
| 服务发现 | Spring Cloud LoadBalancer | 1 | 1 | 0 |
| 容错库 | Microsoft.Extensions.Http.Resilience | 1 | 0 | 1 |
| 容错库 | Polly | 3 | 3 | 0 |
| 容错库 | Resilience4j | 5 | 5 | 0 |
| 容错库 | go-retryablehttp | 1 | 1 | 0 |
| 容错库 | gobreaker | 1 | 1 | 0 |
| 入口与代理 | Envoy | 5 | 5 | 0 |
| 入口与代理 | Istio | 3 | 3 | 0 |
| 入口与代理 | ingress-nginx | 1 | 1 | 0 |
| 数据库客户端与连接池 | Go database/sql | 1 | 1 | 0 |
| 数据库客户端与连接池 | HikariCP | 1 | 1 | 0 |
| 数据库客户端与连接池 | MongoDB driver | 1 | 0 | 1 |
| 数据库客户端与连接池 | PostgreSQL | 2 | 2 | 0 |
| 数据库客户端与连接池 | go-sql-driver/mysql | 1 | 1 | 0 |
| 缓存客户端 | Jedis | 1 | 1 | 0 |
| 缓存客户端 | Lettuce | 1 | 1 | 0 |
| 缓存客户端 | StackExchange.Redis | 1 | 1 | 0 |
| 缓存客户端 | go-redis | 1 | 1 | 0 |
| 缓存客户端 | ioredis | 1 | 1 | 0 |
| 缓存客户端 | redis-py | 1 | 1 | 0 |
| 语言运行时 | JVM | 1 | 0 | 1 |
| 语言运行时 | Node.js | 1 | 1 | 0 |
| 容器编排 | Kubernetes | 13 | 13 | 0 |
| 消息 | Kafka | 3 | 3 | 0 |
| 消息 | RabbitMQ | 4 | 4 | 0 |
| **小计** | | **80** | | |

### 1.2 通用准则文档

| 来源 | 文档数 | 全文入库 | 仅摘录入库 |
|---|---|---|---|
| AWS Builders Library | 5 | 0 | 5 |
| AWS Well-Architected | 1 | 0 | 1 |
| Azure Architecture Center | 9 | 0 | 9 |
| Google SRE | 2 | 0 | 2 |
| Polaris | 1 | 1 | 0 |
| Principles of Chaos Engineering | 1 | 0 | 1 |
| kube-score | 1 | 1 | 0 |
| **小计** | **20** | | |

文档合计 **100** 份，其中全文入库 75 份、仅摘录入库 25 份。

## 2 模板与 advisory

| 项 | 数 |
|---|---|
| 模板 | 49 |
| advisory | 6 |
| 引用条目（模板 + advisory 的 sources） | 127 |
| 被引用到的文档 | 55 |
| 检查项 | 181 |

### 2.1 每个机制组的模板数与 advisory 数

| 机制组 | 模板数 | advisory 数 | 是否达到 3 条 |
|---|---|---|---|
| `circuit_isolation` | 5 | 0 | 是 |
| `connection_lifecycle` | 3 | 1 | 是 |
| `deadline_timeout` | 5 | 0 | 是 |
| `delivery_semantics` | 4 | 0 | 是 |
| `fallback_degradation` | 3 | 0 | 是 |
| `health_probe` | 5 | 0 | 是 |
| `idempotency_compensation` | 3 | 1 | 是 |
| `load_shedding_admission` | 4 | 2 | 是 |
| `replica_disruption` | 5 | 0 | 是 |
| `resource_limit` | 4 | 0 | 是 |
| `retry_backoff` | 5 | 2 | 是 |
| `service_discovery` | 3 | 0 | 是 |

### 2.2 缺陷类别分布

| 缺陷类别 | 模板数 |
|---|---|
| 实现错误型 | 4 |
| 组合型 | 7 |
| 规范明示型 | 24 |
| 需求相对型 | 14 |

### 2.3 advisory 的参数类型分布

| 参数类型 | advisory 数 |
|---|---|
| 时机型 | 1 |
| 概率型 | 1 |
| 滞后型 | 1 |
| 状态型 | 2 |
| 累积型 | 1 |

## 3 机制组 × 动作类型分布

| 机制组 | 连续幅值 | 离散·有数量 | 离散·有时长 | 离散·无可比参数 | 合计 |
|---|---|---|---|---|---|
| `circuit_isolation` | 4 | 1 | 2 | 1 | 8 |
| `connection_lifecycle` | 1 | 0 | 3 | 2 | 6 |
| `deadline_timeout` | 5 | 0 | 2 | 1 | 8 |
| `delivery_semantics` | 0 | 5 | 2 | 0 | 7 |
| `fallback_degradation` | 1 | 0 | 5 | 0 | 6 |
| `health_probe` | 5 | 2 | 3 | 0 | 10 |
| `idempotency_compensation` | 1 | 3 | 2 | 0 | 6 |
| `load_shedding_admission` | 7 | 0 | 1 | 0 | 8 |
| `replica_disruption` | 1 | 7 | 1 | 0 | 9 |
| `resource_limit` | 6 | 0 | 1 | 0 | 7 |
| `retry_backoff` | 2 | 0 | 8 | 0 | 10 |
| `service_discovery` | 1 | 2 | 3 | 0 | 6 |
| **合计** | 34 | 20 | 33 | 4 | **91** |

## 4 检查项按判定方式的占比

| 判定方式 | 检查项数 | 占比 | 其中「必要」 |
|---|---|---|---|
| manifest | 89 | 49.2% | 46 |
| semgrep | 11 | 6.1% | 11 |
| codegraph | 27 | 14.9% | 22 |
| llm | 33 | 18.2% | 10 |
| runtime | 21 | 11.6% | 0 |
| **合计** | **181** | 100.0% | **89** |

可由工具直接判定（manifest + semgrep + codegraph）的检查项占 **70.2%**；其余 29.8% 需要 llm 复核或运行时观察。

## 5 组件 × 模板的落点覆盖矩阵

列出每个组件被哪些模板的 `locate.instantiations` 命中。

| 组件 | 落点数 | 模板 |
|---|---|---|
| Envoy | 20 | T-CIRCUIT-01、T-CIRCUIT-02、T-CIRCUIT-03、T-CIRCUIT-04、T-CIRCUIT-05、T-CONN-01、T-CONN-03、T-DEADLINE-01、T-DEADLINE-04、T-FALLBACK-01、T-IDEM-01、T-RETRY-01、T-RETRY-02、T-RETRY-03、T-RETRY-04、T-RETRY-05、T-SHED-01、T-SHED-02、T-SHED-03、T-SHED-04 |
| Spring Boot | 14 | T-DEADLINE-02、T-DEADLINE-03、T-FALLBACK-01、T-FALLBACK-02、T-FALLBACK-03、T-IDEM-01、T-IDEM-02、T-IDEM-03、T-RETRY-01、T-RETRY-03、T-SHED-01、T-SHED-02、T-SHED-03、T-SHED-04 |
| Kubernetes | 13 | T-PROBE-01、T-PROBE-02、T-PROBE-03、T-PROBE-04、T-PROBE-05、T-REPLICA-01、T-REPLICA-02、T-REPLICA-03、T-REPLICA-04、T-REPLICA-05、T-RESOURCE-01、T-RESOURCE-02、T-RESOURCE-04 |
| Resilience4j | 13 | T-CIRCUIT-01、T-CIRCUIT-02、T-CIRCUIT-03、T-CIRCUIT-04、T-DEADLINE-04、T-DEADLINE-05、T-FALLBACK-01、T-FALLBACK-03、T-RETRY-01、T-RETRY-02、T-RETRY-03、T-RETRY-04、T-RETRY-05 |
| gRPC | 13 | T-CONN-01、T-CONN-03、T-DEADLINE-01、T-DEADLINE-02、T-DEADLINE-03、T-DEADLINE-04、T-IDEM-01、T-RETRY-01、T-RETRY-02、T-RETRY-04、T-RETRY-05、T-SHED-03、T-SHED-04 |
| Istio | 9 | T-CIRCUIT-03、T-CIRCUIT-04、T-CIRCUIT-05、T-DEADLINE-01、T-DEADLINE-02、T-DEADLINE-04、T-RETRY-02、T-RETRY-03、T-RETRY-04 |
| Polly | 8 | T-CIRCUIT-01、T-CIRCUIT-02、T-DEADLINE-05、T-FALLBACK-01、T-FALLBACK-03、T-RETRY-01、T-RETRY-04、T-SHED-01 |
| HikariCP | 6 | T-CIRCUIT-03、T-CONN-01、T-CONN-02、T-DEADLINE-05、T-IDEM-02、T-RESOURCE-03 |
| Kafka | 6 | T-DELIVERY-01、T-DELIVERY-02、T-DELIVERY-03、T-DELIVERY-04、T-IDEM-01、T-IDEM-03 |
| Spring Boot Actuator | 6 | T-DISCOVERY-03、T-PROBE-01、T-PROBE-02、T-PROBE-03、T-PROBE-04、T-PROBE-05 |
| Go net/http | 5 | T-CIRCUIT-03、T-CIRCUIT-04、T-DEADLINE-01、T-PROBE-01、T-SHED-02 |
| RabbitMQ | 5 | T-DELIVERY-01、T-DELIVERY-02、T-DELIVERY-03、T-DELIVERY-04、T-IDEM-03 |
| kube-score | 5 | T-REPLICA-01、T-REPLICA-02、T-REPLICA-04、T-RESOURCE-01、T-RESOURCE-04 |
| ASP.NET Core | 4 | T-PROBE-01、T-PROBE-02、T-PROBE-04、T-PROBE-05 |
| Lettuce | 4 | T-CONN-01、T-CONN-02、T-FALLBACK-02、T-RESOURCE-03 |
| Polaris | 4 | T-REPLICA-01、T-REPLICA-02、T-REPLICA-03、T-REPLICA-04 |
| go-redis | 4 | T-CONN-02、T-FALLBACK-02、T-IDEM-02、T-RESOURCE-03 |
| ingress-nginx | 4 | T-CIRCUIT-05、T-SHED-01、T-SHED-02、T-SHED-03 |
| Consul | 3 | T-DISCOVERY-01、T-DISCOVERY-02、T-DISCOVERY-03 |
| Eureka | 3 | T-DISCOVERY-01、T-DISCOVERY-02、T-DISCOVERY-03 |
| Go context | 3 | T-DEADLINE-02、T-DEADLINE-03、T-DEADLINE-05 |
| Nacos | 3 | T-DISCOVERY-01、T-DISCOVERY-02、T-DISCOVERY-03 |
| Node.js | 3 | T-CONN-01、T-DEADLINE-03、T-RESOURCE-02 |
| Spring Cloud LoadBalancer | 3 | T-CIRCUIT-05、T-DISCOVERY-01、T-DISCOVERY-02 |
| .NET HttpClient | 2 | T-DEADLINE-01、T-DEADLINE-03 |
| Go database/sql | 2 | T-CONN-02、T-RESOURCE-03 |
| JVM | 2 | T-PROBE-03、T-RESOURCE-02 |
| Jedis | 2 | T-FALLBACK-02、T-RESOURCE-03 |
| Microsoft.Extensions.Http.Resilience | 2 | T-CIRCUIT-01、T-RETRY-01 |
| StackExchange.Redis | 2 | T-CONN-01、T-RESOURCE-03 |
| go-retryablehttp | 2 | T-RETRY-01、T-RETRY-02 |
| gobreaker | 2 | T-CIRCUIT-01、T-CIRCUIT-02 |
| Guzzle | 1 | T-DEADLINE-01 |
| MongoDB driver | 1 | T-DEADLINE-01 |
| PostgreSQL | 1 | T-RESOURCE-03 |
| Python httpx | 1 | T-DEADLINE-01 |
| Python requests | 1 | T-DEADLINE-01 |
| Ruby Net::HTTP | 1 | T-DEADLINE-01 |
| Spring Cloud OpenFeign | 1 | T-DEADLINE-01 |
| axios | 1 | T-DEADLINE-01 |
| go-sql-driver/mysql | 1 | T-RESOURCE-03 |
| ioredis | 1 | T-CONN-02 |
| reqwest | 1 | T-DEADLINE-01 |
| undici | 1 | T-DEADLINE-01 |

已登记文档但尚无模板落点的组件（1 个）：redis-py
