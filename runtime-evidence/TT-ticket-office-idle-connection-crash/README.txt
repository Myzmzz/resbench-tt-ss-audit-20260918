# ts-ticket-office-service：库连接空闲 8 小时被服务端断开 → 进程崩溃重启（周期性），每次重启再插一行种子数据
# 新环境，只读采集于 2026-09-19 00:4x UTC；夜间无任何压测（该服务也不在压测路径上）

## 1. 重启历史（kubectl get pod -o json）
Pod ts-ticket-office-service-7df8d4c647-rpp6d  created 2026-09-18T08:23:33Z  restartCount=2
上一个容器实例：startedAt 2026-09-18T16:29:16Z → finishedAt 2026-09-19T00:29:17Z（Error, exit 1）
  => 该实例恰好存活 8h00m01s，期间没有请求；第一个实例在 ~16:29 崩溃（第二实例于 16:29:16 起）。
  其它 train-ticket / sock-shop / observability 容器在 09-18 09:30 之后均无重启。

## 2. 崩溃日志（kubectl logs --previous，末尾）
Emitted 'error' event on Connection instance at:
    at Connection._handleProtocolError (/app/node_modules/mysql/lib/Connection.js:423:8)
    ...
  fatal: true,
  code: 'PROTOCOL_CONNECTION_LOST'
Node.js v25.8.1
  => mysql 驱动在连接被对端关闭时发出 'error' 事件；没有监听器 → 未捕获异常 → 进程退出。

## 3. 数据库侧（tsdb 主库 tsdb-mysql-2，information_schema.processlist，只读）
@@wait_timeout = 28800, @@interactive_timeout = 28800（nacosdb-mysql-0 同为 28800）
来自该 Pod IP 的会话只有 1 个：id 28950, db=ts, command=Sleep, time=875 s（00:44 UTC，即重启后一直空闲）
  => 全进程只有一条连接；空闲满 28800 s 服务端即断开，与 8h00m01s 的存活时长吻合。

## 4. 源码（上游 313886e9，ts-ticket-office-service/bin/db.js）
:10-15  require('mysql').createConnection({...})   —— 单连接、非连接池、无 on('error')、无重连、无心跳
:23-24  查询回调里 if (err) throw err
:30     启动时无条件 insertEntry(...) 插入种子数据
Dockerfile:1  FROM node（未固定版本）→ 2026-03 重建的镜像实际运行 Node.js v25.8.1

## 5. 副作用：种子数据随重启累积（SELECT ... FROM ts.office，只读）
rows_total=4, distinct_offices=1（'Jinqiao Road ticket sales outlets' × 4）
  => 每次进程启动插一行；按每 8 h 崩一次的节奏，表每天多 3 行重复数据，售票点列表返回重复项。

## 6. 可证伪的预测
若期间无请求、无人重启：下一次崩溃约在 2026-09-19 08:29 UTC（00:29:17 + 28800 s）。
同理，任何让这条连接断开的事件（MySQL 切主、tsdb Pod 重启、网络闪断、KILL 该会话）都会立即让进程崩溃，
恢复依赖 kubelet 重启 + CrashLoopBackOff 退避。

## 归属
静态报告 TT-B17 已指出 E1/E2/E3（单连接、throw err、重复种子），本文件把它升级为运行时已复现（R），
并补充了触发条件"空闲 8 小时"（静态报告未提）。业务影响：售票点页面，不在压测 SLO 路径上。
