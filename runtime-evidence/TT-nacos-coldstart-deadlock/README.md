# 本目录结论已更正（2026-09-18）

目录名沿用最初的错误假设"冷启动死锁"，**该结论作废**，请不要引用。

| 文件 | 当时的解读 | 更正后的解读 |
|---|---|---|
| before-fix.txt | 按序创建 + 钩子 → nacos-0 永不就绪 | 现象属实（8848 拒绝、钩子不返回），但原因是 Nacos 进程启动失败 |
| after-parallel.txt | 同时创建后仍不就绪 → 未就绪不发布 DNS 构成第二层死锁 | 现象属实，原因仍是启动失败；DNS 不发布是真实配置，但不是这次起不来的原因 |
| root-cause-no-datasource.txt | —— | **真正原因**：`IllegalStateException: No DataSource set`，外部存储模式下配置库无表 |

**真实缺陷（TT-RT-04）**：Nacos 集群默认使用外部 MySQL（nacosdb），而建表脚本不在任何部署产物里（上游 chart README 要求使用者自行初始化）。nacosdb 数据丢失（例如 PV 被删、换集群重建、恢复时漏了这一步）后，Nacos 起不来，进而全部业务服务因注册失败而 CrashLoopBackOff（TT-RT-03）。

**附带确认的两点**：
1. postStart 钩子（循环 PUT 开关、无超时）在 Nacos 起不来时会让容器永远停在 PodInitializing，既拿不到日志，也无法正常删除（需强制删除）——这是可诊断性与恢复操作上的缺陷。
2. 原配置（OrderedReady + 钩子 + publishNotReadyAddresses=false）在有表结构时能否正常起来，见本文件末尾的验证记录。
- 原配置（OrderedReady + postStart + publishNotReadyAddresses=false）在补表后正常起来：nacos-0 → nacos-1 → nacos-2 依次就绪（2026-09-18T08:57:23Z 观察），"冷启动死锁"不成立。
