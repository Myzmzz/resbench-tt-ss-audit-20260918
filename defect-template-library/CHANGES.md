# CHANGES.md —— 每次提交做了什么

## 提交 1：技术栈与文档范围

- `stack.md`：按 11 层列出要覆盖的组件与对应 `doc_id`；写明本版收什么、什么转 advisory、什么不收。
- `documents.yaml`：98 份文档的登记（doc_id、标题、组件、层、版本、网址、取回日期、sha256、许可说明），由 `build_cache.py` 生成。
- `docs-cache/<doc_id>.txt`：引用核对副本。
- 工具：`fetch_docs.py`（抓取与正文归一化）、`build_cache.py`（按许可口径生成入库副本与 `documents.yaml`）、`sources.tsv`（抓取输入）、`fetch-log.json`（抓取结果原始记录）。任务书的目录清单没有点名这两个脚本，但"引用必须能在本地副本里原样找到"要求抓取、归一化、核对是一条可重跑的链路，所以把它们一并入库。

### 本次需要说明的口径

1. **文档副本分两档入库。** 任务书要求 `docs-cache/` 存正文副本供引用核对，同时又要求在交付说明里点出"哪些引用来自不可再分发的来源"。两者合起来的做法是：开放许可的来源（74 份）入库全文；厂商版权文档或未标注许可的来源（24 份：Microsoft Learn、Oracle、AWS、Google SRE 书、MongoDB、Principles of Chaos Engineering）只入库本库实际引用到的段落及其所在小节标题。两档都能逐字复核，后者不构成整页再分发。全文保留在本地 `docs-cache/.full/`（`.gitignore` 排除），改口径后 `build_cache.py` 可随时重建。
2. **正文归一化规则**（影响"逐字"的含义，`README.md` 与 `fetch_docs.py` 头部有同样说明）：HTML 源码里的换行按 HTML 语义并成空白，一个段落落在一行；`<pre>` 块内换行保留；`h1`–`h6` 前加 `[[Hn]]` 标记供 `location` 定位；表格单元格用 ` | ` 分隔、一行一 `<tr>`，便于整行引用参数默认值表；`.md`/`.adoc`/`.txt`/`.rst` 与 `raw.githubusercontent.com` 的文件按纯文本处理，保留原换行。
3. **AWS Builders' Library 走 Wayback 快照。** `aws.amazon.com/builders-library/*` 现已跳转到前端渲染的站点，脚本取不到正文，5 篇取自 `web.archive.org` 的 2024 快照；许可判断按快照里嵌套的原始网址做，仍记为 © Amazon、不可再分发。
4. **机制组 slug 对齐审计终稿。** 取 `final-defects.json` 的 `family` 词表，只读词表本身，不从审计结论里抽规则。

## 提交 2–11：按机制组逐组提交模板

| 提交 | 机制组 | 模板 | advisory |
|---|---|---|---|
| 2 | `health_probe` | 5 | 0 |
| 3 | `deadline_timeout` | 5 | 0 |
| 4 | `retry_backoff` | 5 | 2 |
| 5 | `circuit_isolation` | 5 | 0 |
| 6 | `load_shedding_admission` | 4 | 2 |
| 7 | `replica_disruption` | 5 | 0 |
| 8 | `resource_limit` | 4 | 0 |
| 9 | `fallback_degradation` | 3 | 0 |
| 10 | `idempotency_compensation` | 3 | 0 |
| 11 | `delivery_semantics` | 4 | 0 |

每次提交前都跑了 `validate.py`，零错误才提交。

## 提交 12：新增机制组 connection_lifecycle、工具与文档

### 新增机制组 `connection_lifecycle`（3 条模板、1 条 advisory）

**理由。** 读文档时反复遇到一类机制，它既不属于「超时」也不属于「熔断隔离」，更不是资源限额：**长连接自身的生命周期管理**——保活探测、连接最长寿命、与对端保活策略的协商。它的特征是故障只在「连接空闲了很久」或「对端静默消失」时才显现，与请求级的超时、重试、熔断都是正交的：请求超时管的是单次调用等多久，连接保活管的是这条连接还活着没有；熔断管的是要不要继续调，连接寿命管的是手里这条连接还能不能用。把它塞进 `deadline_timeout` 会让那一组的参数关系失去一致性（一个以请求为单位，一个以连接为单位），塞进 `resource_limit` 又和「配额与限额」不是一回事。

支撑它的文档是 gRPC 的独立 Keepalive 页、HikariCP 的 `maxLifetime` 说明、Envoy 的连接空闲超时、Lettuce 的 ClientOptions。三条模板分别覆盖「没有保活探测」「连接寿命长于对端时限」「客户端保活间隔与服务端策略冲突」。

对应到本仓库审计终稿 `final-defects.json` 的 `family` 词表，这一组落在 `other（…）` 下，没有现成 slug 可对齐；沿用任务书的命名习惯取了 `connection_lifecycle`。

### 另外补充的 advisory

- `A-CONN-01` 连接或资源泄漏（累积型）
- `A-IDEM-01` 副作用与确认之间的时序窗口（时机型）

加上前面几组的 4 条，共 6 条 advisory，覆盖了任务书点名的概率型（`A-RETRY-01`）、累积型（`A-CONN-01`）、滞后型（`A-SHED-01`）三个例子，另有状态型 2 条、时机型 1 条。

### 工具与文档

- `stats.py` / `stats.md`：文档数（按组件与通用准则分列）、模板数、advisory 数、机制组 × 动作类型分布、检查项按判定方式的占比、组件 × 模板落点覆盖矩阵。
- `render_templates.py` / `templates.md`：四块卡片版，供论文引用。
- `README.md`：库的组织、怎么校验、怎么重新生成，末尾是交付说明。
- `validate.py` 追加了两项：`semgrep --validate` 对 `checkers/semgrep/` 的语法校验；`stats.md` 与 YAML 的一致性比对（调用 `stats.py --stdout` 后比对）。

### 本次需要说明的口径

1. **Semgrep 已校验。** 本机原先没有 semgrep，`pip install semgrep` 装上 1.99.0 后，`semgrep --validate --config checkers/semgrep/` 对 15 条规则报 0 配置错误。该命令已接进 `validate.py`，本机若缺 semgrep 会降级为警告而不是错误。
2. **探针默认值的出处与任务书示例不同。** 任务书给的 `T-PROBE-01` 示例把 `timeoutSeconds` / `periodSeconds` / `failureThreshold` 的默认值记在 `k8s-probes-task` 上；当前的 Kubernetes 文档把这三个默认值写在概念页 `k8s-probes-concept` 的 Configure probes 小节，任务页里没有。按"默认值只记录文档明确给出的并注明出处"的要求，改记为 `k8s-probes-concept`；示例里的两段引用原文则与当前文档逐字一致，未作改动。
3. **两个组件已登记文档但没有模板落点。** `Nacos` 属于服务注册与发现，是一个还没建的机制组（见 `OPEN-QUESTIONS.md` 的 Q4）；`redis-py` 的 README 是上手介绍而非配置参考，取不到可引用的超时与重连参数，需要另找文档页。
4. **有 48 份文档只登记未引用。** `documents.yaml` 是本版划定的阅读范围而不是引用清单，差额可从 `stats.md` 第 2 节读出，`README.md` 里有说明。

## 提交 13：按 2026-09-20 的六条拍板结论收口

出题人一次性答复了 `OPEN-QUESTIONS.md` 的 Q1–Q6，本次提交把六条结论全部落实。

### 新增机制组 `service_discovery`（3 条模板）

**理由（Q4 的落实）。** 服务注册与发现自成一类：它管的是"调用方怎么知道该往哪儿发"，与超时（等多久）、熔断（要不要继续调）、健康探针（本实例能不能服务）都不重叠。它的三类故障也各不相同——注册中心自身不可用、实例失效到被剔除之间的延迟、注册状态与应用真实健康脱节。v1 初版没建组是因为当时只凑得出 2 条规则；这次补抓了 Consul 的健康检查页与 Spring Cloud Netflix（Eureka）的客户端文档，拿到了三段可用的原文：

- Eureka 的心跳判活与剔除（`If the heartbeat fails over a configurable timetable, the instance is normally removed from the registry.`）
- Eureka 默认不上报应用健康状态（`the Discovery Client does not propagate the current health check status of the application`），注册后恒为 UP
- Consul 的 TTL 检查在超时未更新时进入 critical
- Nacos 的 `namingLoadCacheAtStart` 默认 `false`，冷启动不读本地磁盘缓存

三条模板分别覆盖这三类故障。对应到本仓库审计终稿 `final-defects.json` 的 `family` 词表，这一组同样落在 `other（…）` 下，没有现成 slug，沿用任务书命名习惯取 `service_discovery`。

文档清单同时增加 `consul-health-checks` 与 `eureka-client` 两份，共 100 份。

### 其余五条结论的落实

| 问题 | 结论 | 改了什么 |
|---|---|---|
| Q1 Principles of Chaos Engineering 算不算公认准则 | 算 | `chaos-principles` 可作规则依据；`T-FALLBACK-03` 引用了它点名的系统性弱点清单；`README.md` 写明本库 `verdict` 块与动作分类沿用它的实验方法。它讲的是实验方法而非组件机制，因此没有为它单独写模板 |
| Q2 Wayback 快照算不算官方文档 | 算 | `build_cache.py` 为快照来源生成 `retrieved_via: web-archive-snapshot`、`snapshot_of`、`snapshot_note` 三个字段，落进 `documents.yaml`，共 5 份 |
| Q3 厂商版权文档只入库摘录是否可接受 | 可以 | 维持现状，不改口径 |
| Q5 `T-REPLICA-05` 是否越界 | 不越界 | 模板保留原样 |
| Q6 `redis-py` 换哪份文档 | 先不管 | 保留在阅读范围里，不造落点；`stats.md` 继续把它列为无落点组件 |

### 本次需要说明的口径

1. **`location` 字段里带冒号的值全部加了引号。** `Spring Cloud Netflix > Service Discovery: Eureka Clients` 这类值在 YAML 里会被当成映射，加引号后解析正常；顺手对 `how` / `query` / `statement` 等字段做了同样处理。
2. **`chaos-principles` 的引用是唯一一处"准则讲方法、却支撑了具体规则"的地方。** 用的是它开篇列举系统性弱点的那句，其中 `improper fallback settings when a service is unavailable` 与 `T-FALLBACK-03` 的规则陈述直接对应，不是拿方法论硬套机制。
