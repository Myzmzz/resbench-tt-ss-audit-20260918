# 缺陷模板库 v1

这是一座**与具体系统无关**的韧性缺陷模板库，给"面向韧性测试智能体的基准构建系统"做输入。每条模板是一条能在陌生微服务系统上逐条核对的规则，分四块：

| 块 | 回答什么 | 关键字段 |
|---|---|---|
| **规则** `rule` | 应该怎样、凭什么 | `statement`、`sources[]`（doc_id + 原文 + 章节）、`defaults[]` |
| **定位** `locate` | 到哪找、查什么 | `applies_when[]`、`roles`、`instantiations[]`、`checks[]` |
| **实验** `experiment` | 用什么故障、多大多久 | `actions[]`、`parameter_relation`（boundary / hold / recovery_window） |
| **判定** `verdict` | 看什么、算不算、怎么修 | `expected_behavior`、`signals[]`、`alternative_explanations[]`、`mitigation` |

下游流水线按 `locate` 在目标系统上核对出候选脆弱点，按 `experiment` 选故障并算参数，按 `verdict` 编断言、执行并裁决，最后派生测试题。所以 `templates.yaml` 是给机器读的，字段含义固定；`templates.md` 是它的人读版本，由脚本生成。

## 目录

```
defect-template-library/
  README.md                 本文件
  stack.md                  技术栈层次与组件、每个组件对应的 doc_id、收与不收的口径
  documents.yaml            文档登记：doc_id、标题、组件、版本、url、retrieved_at、sha256、许可说明
  docs-cache/<doc_id>.txt   引用核对副本（开放许可来源存全文，厂商版权来源只存被引段落）
  templates.yaml            模板（四块）
  templates.md              由 render_templates.py 生成的卡片版
  advisories.yaml           本版不生成场景的规则（概率型 / 累积型 / 滞后型 / 组合型 / 时机型 / 状态型）
  checkers/semgrep/*.yaml   检查项引用的 Semgrep 规则
  stats.md                  由 stats.py 生成的统计
  validate.py               校验脚本
  render_templates.py       templates.yaml -> templates.md
  stats.py                  生成 stats.md
  fetch_docs.py             按 sources.tsv 取回文档正文（全文落在 docs-cache/.full/，不入库）
  build_cache.py            按许可口径生成入库副本与 documents.yaml
  sources.tsv               抓取输入
  fetch-log.json            抓取结果原始记录
  CHANGES.md                每次提交做了什么、新增机制组的理由
  OPEN-QUESTIONS.md         需要出题人拍板的问题
```

## 怎么校验

```bash
python3 validate.py
```

它检查：schema 合法；每条模板至少 1 条 source 且 quote 在 `docs-cache/<doc_id>.txt` 里原样存在（忽略空白差异）；所有 doc_id 可解析且登记了版本、取回日期、sha256，且 sha256 与文件实际内容一致；每条模板至少 1 条「必要」检查项；`checker` / `kind` / `type` / `source` / `defect_class` / `parameter_kind` 的取值在枚举内；阈值型模板有 `parameter_relation` 且每个 symbol 有 `source`；`defaults` 都有 `doc_id`；`checks` 引用的 Semgrep 规则文件存在且 `semgrep --validate` 通过；模板与 advisory 里不出现目标系统名及其服务名；`stats.md` 与 YAML 一致。

## 怎么重新生成

```bash
python3 fetch_docs.py            # 取回 sources.tsv 里还没缓存的文档（全文写入 docs-cache/.full/）
python3 fetch_docs.py --reparse  # 不联网，用本地原始副本重新生成正文
python3 build_cache.py           # 按许可口径生成 docs-cache/*.txt 与 documents.yaml
python3 stats.py                 # 生成 stats.md
python3 render_templates.py      # 生成 templates.md
python3 validate.py              # 全部校验
```

改了 `templates.yaml` 之后要按 `build_cache.py` → `stats.py` → `render_templates.py` → `validate.py` 的顺序跑一遍：厂商版权来源的引用核对副本是按当前引用重建的，不重建会缺段。

## 引用与"逐字"的含义

正文归一化会做四件事，引用逐字比对的是归一化之后的文本：

1. HTML 源码里的换行按 HTML 语义并成空白，一个段落落在一行；`<pre>` 块内的换行保留。
2. `h1`–`h6` 标题前加 `[[Hn]]` 标记，用来填 `location` 字段；引用正文不会碰到这个标记。
3. 表格单元格用 ` | ` 分隔、一行一 `<tr>`，便于整行引用参数默认值表。
4. `.md` / `.adoc` / `.txt` / `.rst` 与 `raw.githubusercontent.com` 上的文件按纯文本处理，保留原换行。

## 检查项的五种判定方式

| checker | query 怎么写 | 说明 |
|---|---|---|
| `manifest` | 对渲染后 Kubernetes 清单或组件配置的 JMESPath 表达式 | 最便宜，优先用 |
| `semgrep` | `checkers/semgrep/` 下的规则文件名 | 每条规则覆盖该检查项 instantiations 涉及的语言；写不出的语言在 query 里标 llm |
| `codegraph` | 从哪个符号出发、查什么关系、几跳内 | 用于"探针端点是否触达出站客户端"这类可达性问题 |
| `llm` | 一个小到能用"成立 / 不成立 / 无法判定 + 文件:行"回答的问题 | 只用于工具判不了的三值问题 |
| `runtime` | 要在实验里看的现象 | 只出现在「附注」类检查项里，不作为静态判定依据 |

每条模板至少有一条「必要」检查项；凡是存在"另有保护"写法的地方都配了对应的「反证」项。

## 交付说明

**做了什么。** 登记并取回了 98 份文档（11 层技术栈的组件官方文档 + 通用准则），写了 46 条模板覆盖 11 个机制组（任务书给的 10 个，加上从文档里读出来的 `connection_lifecycle`），每组不少于 3 条；另有 6 条 advisory 记录本版参数类型不支持的规则。119 条引用全部逐字回查通过，`semgrep --validate` 对 15 条规则报 0 错误，`validate.py` 零错误。

**没做什么。** 一、没有读也没有绑定任何目标系统，模板里不出现系统名与服务名，`validate.py` 会拒绝这类字符串。二、没有从事故报告、博客或论文归纳规则；`evidence_incidents` 只在一条模板上出现，且只作优先级佐证。三、没有给规则预设失效模式分类，只写 `violation_manifestation`。四、按任务书口径不收的内容一律没收：优雅终止族、安全、可观测性配置、跨区域灾备与备份恢复、纯性能调优；例外的「故障恢复后回不来」保留在 `T-CIRCUIT-02`。五、参数关系属于概率型 / 累积型 / 滞后型 / 时机型 / 状态型的规则一律进了 `advisories.yaml`，本版不为它们生成场景。六、`redis-py` 与 `Nacos` 两个组件已登记文档但还没有模板落点，原因见 `stats.md` 与 `OPEN-QUESTIONS.md`。

**哪些引用来自不可再分发的来源。** 24 份文档没有再分发授权（Microsoft Learn、Oracle、AWS 文档与 Builders' Library、Google SRE 书、MongoDB 文档、Principles of Chaos Engineering），它们的 `docs-cache/<doc_id>.txt` 里**只有本库实际逐字引用到的段落及其所在小节标题**，不是全文副本，文件头部写明了来源与许可。要读全文请按 `documents.yaml` 里登记的 `url` 到原站点。涉及的标识与章节是：

| doc_id | 章节 |
|---|---|
| `sre-handling-overload` | Client-Side Throttling > Client request rejection probability |
| `sre-cascading-failures` | Preventing Server Overload（Queue Management / Load Shedding and Graceful Degradation）、Retries、Latency and Deadlines、Slow Startup and Cold Caching |
| `aws-builders-timeouts` | Timeouts / Backoff / Jitter |
| `aws-builders-idempotency` | Reducing client complexity with idempotent API design |
| `aws-builders-avoiding-fallback` | Single-machine fallback、How Amazon avoids fallback |
| `aws-builders-load-shedding` | 概述、Watching the clock |
| `aws-war-reliability` | 优雅降级最佳实践 |
| `azure-pattern-retry` / `-circuit-breaker` / `-bulkhead` / `-throttling` / `-compensating` / `-cache-aside` | 各页的 Solution 与 Issues and considerations |
| `azure-transient-faults` | Retry strategy guidelines |
| `jvm-launcher` | Advanced Runtime Options（`-XX:-UseContainerSupport` 等） |

另有 9 份不可再分发的文档已登记但本版没有产生逐字引用（`aws-builders-health-checks`、`azure-pattern-health-endpoint`、`azure-pattern-queue-leveling`、`mongodb-connection-options`、`aspnet-health-checks`、`dotnet-httpclient-guidelines`、`dotnet-httpclient-factory`、`dotnet-http-resilience`、`chaos-principles`），它们的 `docs-cache/` 文件里只有一行说明，没有正文。

其余 74 份文档采用开放许可（CC BY 4.0、Apache-2.0、MIT、BSD、PostgreSQL License 等），`docs-cache/` 里存的是全文正文副本，任何人都能直接复核引用。

**关于"登记了但没引用"。** 98 份文档里有 50 份产生了逐字引用，另外 48 份只是登记在册：`documents.yaml` 是本版划定的阅读范围，不是引用清单。一份文档没被引用，可能是它覆盖的机制已由同组更贴切的文档支撑（例如 Kubernetes 探针的默认值集中在概念页，任务页只支撑启动探针那一条），也可能是它只在 `locate.instantiations` 里作为落点出现而无需引用（例如各语言 HTTP 客户端的超时参数名）。范围与引用的差额可以从 `stats.md` 第 2 节的「被引用到的文档」一行读出。
