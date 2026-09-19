以下是 train-ticket 基础设施与部署配置层面的排查报告。全程只读：没有改任何项目文件，没有运行 kubectl，也没有访问集群或网络。中间结果只写进了会话临时目录。

## 结论先行

- **三条运行时缺陷的根因都在配置或框架层，可以回溯到具体文件和字节码。**
  - **TT-RT-01**：Chart 的 `allowEmptyRootPassword: true` 让 xenon 用免密 root 经 TCP `localhost:3306` 探活。K8s 探针却走 Unix socket，所以出现“探针全绿，但集群没有主库”。
  - **TT-RT-02**：41 个 Java 服务启动都要挂载一个 NFS 目录，里面放着 OTel 探针 jar。这个 NFS 在集群外，和 Harbor 是同一台主机。
  - **TT-RT-03**：Nacos 客户端框架默认 `failFast=true`，客户端连不上就报 STARTING 并抛异常。另外 `nacos-headless` 没开 `publishNotReadyAddresses`，Nacos 只要“没 Ready”，域名就解析不到。
- **旧环境是否同样成立**：
  - TT-RT-01 在旧环境是潜伏状态：配置相同，但 Pod 里没有启用 IPv6，所以没有触发。
  - TT-RT-02 在旧环境是潜伏单点：依赖一直存在，只是那台主机一直可达。
  - TT-RT-03 在旧环境完全成立，属于代码和配置层问题，与环境无关。
  - 新环境里 TT-RT-01 被偏差 #5 掩盖，TT-RT-02 被偏差 #7 掩盖，都已经无法复现。
- **按要求重点找了 D2–D6 类缺陷，主要新发现有四条：**
  1. K8s 的 readiness 与 Nacos 实例健康是两套互不相通的判定。服务之间的流量只认 Nacos，而且所有服务都没有 liveness（TT-E04）。
  2. 40 个服务的 RestTemplate 实际用的是 Apache HttpClient 的系统默认配置，我用 javap 反汇编核实过。三种超时全都没有，连接池每个目标只有 5 条、整个服务只有 10 条，借不到连接时无限等待（TT-E05）。
  3. 数据库切主后，Hikari 池里指向旧主的连接仍能通过校验，写入失败最长会持续约 30 分钟（TT-E07）。
  4. 旧环境 Nacos 注册表分歧的根因：成员列表用的是 DNS 名，不是写死的 Pod IP；但这些域名只在 Pod Ready 时存在，Ready 又不等于 Distro 数据就绪，Nacos 还没有持久化（TT-E08）。
- **ts-order-service 接收队列不排空的问题**：从配置层推断，是“请求线程里存在无界等待 + 调用方放弃后服务端不中止 + 没有 liveness”三者组合造成的。这条链能同时解释三个现象，但具体卡在哪里需要线程栈确认（TT-E06）。
- **5 个另行构建的镜像来源不明。** 只有 `ts-order-service:1.0.1` 在上游的部署样例里出现过。

路径缩写（均为绝对路径）：
- `B` = `/Users/mymz/work/国家重点研发/韧性测试工具 benchmark`
- `MF` = `B/multisystem-audit-20260918/manifests/train-ticket`
- `RE` = `B/multisystem-audit-20260918/runtime-evidence`
- `UP` = `B/benchmark-sources/train-ticket-upstream`
- `CH` = `UP/deployment/kubernetes-manifests/quickstart-k8s/charts`
- `D0` = `B/resiliencebenchmark-stage2-d0-integration/environment`
- `M2` = `/Users/mymz/.m2/repository`。这是本机 Maven 缓存里与 pom 解析出的版本一致的 jar，我用 javap 反汇编核对过；镜像里实际打包的 jar 仍需按 R10 确认。

---

## 一、部署配置总表

| 工作负载 | 副本 | 探针 | requests / limits | JVM 与堆 | 存储 | 异常点 |
|---|---|---|---|---|---|---|
| 其余 32 个 Java ts-*（下面几行之外） | 1 | 只有 readiness，TCP 探容器端口，d60/p10/t5/f3；没有 liveness 和 startup | 10m/100Mi；1500m/1500Mi | JTO=`-XX:+UnlockDiagnosticVMOptions -XX:+DebugNonSafepoints -javaagent:/opt/opentelemetry-javaagent/opentelemetry-javaagent.jar`；堆由镜像 CMD 决定，为 `-Xmx200m` | NFS `1.94.151.57:/data/share` 挂到 `/opt/opentelemetry-javaagent`（新环境按偏差 #7 改为 emptyDir 加初始化容器） | 请求值与实际用量严重不符；没有反亲和；nodeAffinity 写的是 `NotIn tcse-v100-01`，在新环境无效 |
| ts-gateway-service | 3 | 同上 | 同上 | `-Xmx1024m` | 同上 | 入口，NodePort 18888 |
| ts-order-service / ts-auth-service / ts-preserve-service | 2 | 同上 | 同上 | `-Xmx200m` | 同上 | order 用的是 1.0.1 自建镜像；两个副本没有分散 |
| delivery / food / notification / preserve-other / wait-order | 1 | 同上 | 同上 | 同上 | 同上 | 前 4 个多一个 env `rabbitmq_host=rabbitmq` |
| avatar / news / ticket-office / voucher | 1 | 同上 | 同上 | 非 Java，没有 OTel | 无 | — |
| ts-ui-dashboard | 3 | 同上 | 同上 | openresty | 无 | NodePort 8080 |
| rabbitmq | 1 | readiness TCP 5672，d30；没有 liveness | 100m/200Mi；没有 limits | — | **无卷** | 单点，消息不持久化 |
| nacos（StatefulSet 2.0.1） | 3，OrderedReady | readiness TCP 8848，d60/t5；没有 liveness；postStart 用 `until curl …doubleWriteEnabled=false&debug=true` 循环 | 500m/1Gi；没有 limits | 用镜像默认值，没设 JVM_XMX；是否为 1g 待核 | **无卷**，数据只在内存和容器层 | initmysql 容器无限等待 `nacosdb-mysql-leader:3306`；没有反亲和 |
| tsdb-mysql / nacosdb-mysql（StatefulSet） | 3，OrderedReady | mysql 容器：liveness `mysqladmin ping -uroot` t5，readiness `mysql -uroot -e "SELECT 1"` **t1**，两者都走 Unix socket。xenon 容器：liveness `pgrep xenon`，readiness `xenoncli xenon ping` t1 | mysql 100m/256Mi；500m/1Gi。xenon 50m/128Mi；100m/256Mi。slowlog 未设 | — | data 卷 1Gi：旧环境 `nfs-client`，新环境 `openebs-hostpath`（偏差 #1） | `max_connections=65535`；主从由 role 标签区分，标签由脚本调 API 打上；没有反亲和 |
| ischaos-tls-gateway | 1 | 无 | 无 | — | — | 他人植入的故障组件，按偏差 #3 排除 |

其余配置核对结果：
- **Deployment 策略**：全部是 RollingUpdate 25%/25%，终止宽限期 30 秒，没有 preStop。
- **Service**：共 56 个。ts-* 都是 ClusterIP，只有 gateway、ui 和 nacos 是 NodePort。导出时去掉了 clusterIP，所以 Service 是否 headless 以 Chart 为准：`nacos-headless` 是 headless 但没有 `publishNotReadyAddresses`；`tsdb-mysql` 和 `nacosdb-mysql` 是 headless，并设了 `publishNotReadyAddresses: true`。
- **没有的对象**：各份导出和各个 Chart 里都没有 PDB、HPA、NetworkPolicy、LimitRange。
- **启动命令**：ts-* 都没有覆盖 command。
- **探针端口**：41 个 Java 服务的 readiness 端口与 `server.port` 逐一比对，全部一致。

---

## 二、候选缺陷（按严重度排序，共 21 条）

### TT-E01（即 TT-RT-01）xenon 探活依赖“localhost=IPv4 + 免密 root”，K8s 探针走 Unix socket，两者判定分叉，出现“全绿但无主”
- **机制族 / 失效模式**：健康探针；故障转移 / D6（高可用依赖环境假设）+ D2（K8s 探针覆盖不到高可用的判定路径）
- **位置**：tsdb-mysql 和 nacosdb-mysql 中 xenon 的探活配置，以及 mysql 容器的探针
- **成立条件**：
  - **E1 xenon 用免密 root 经 TCP `localhost:3306` 探活 — 成立。**
    - `CH/mysql/values.yaml:29` 设了 `allowEmptyRootPassword: true`。
    - 因此 `CH/mysql/templates/statefulset.yaml:195-196` 不给 xenon 注入 `MYSQL_ROOT_PASSWORD`。`MF/statefulsets.json` 里 xenon 的 env 只有 REPL_PASSWORD、POD_HOSTNAME、HOST、LEADER_*_CMD 和 *_SysVars。
    - xenon.json 由镜像入口脚本生成，Chart 和 ConfigMap 里都没有。
    - 运行日志 `RE/TT-xenon-ipv6-localhost/before-fix.txt:27-28` 是 `mysql[localhost:3306]… (using password: NO)… downslimits:3`。
  - **E2 库里只有 `root@127.0.0.1` 和 `root@localhost`，没有 `root@'::1'` — 成立**（before-fix.txt:21-22、40-41）。
    - ConfigMap 只有 node.cnf、server-id.cnf、create-peers.sh 和 leader-start/stop.sh，没有任何账号定义（`MF/configmaps.json`）。
    - 账号是镜像的 `/docker-entrypoint.sh` 在初始化数据目录时生成的。具体生成逻辑存疑，需要看 R12。
  - **E3 mysqld 监听 IPv6，且把 ::1 当作单独的主机匹配 — 现象成立，机制存疑。**
    - node.cnf 没有设 `bind-address`，默认值 `*` 在 IPv6 可用时会监听 `::`。
    - 报错里的主机是 `'root'@'::1'` 而不是 localhost，据此推断镜像的 my.cnf 开了 `skip_name_resolve`。
  - **E4 Pod 启用了 IPv6，localhost 同时映射到 ::1 — 新环境成立，旧环境不成立。**
    - 新环境：before-fix.txt:15-16 有 `::1 localhost`，且 `disable_ipv6=0`。
    - 旧环境用同样的镜像和账号却能选出主库，说明那里 ::1 不可用，xenon 回退到了 127.0.0.1。
  - **E5 失败发生在认证阶段，拨号不会回退到 IPv4 — 成立（推断）。** 1045 是服务端返回的，说明连接已经建立。按 RFC 6724 排序，::1 排在前面。
  - **E6 K8s 探针走的不是同一条路径 — 成立。**
    - mysql 容器的探针不带 `-h`，走 socket 以 root@localhost 登录（`CH/mysql/templates/statefulset.yaml:144,161`）。xenon 的 readiness 只检查进程。
    - 结果是 6 个 Pod 全部 3/3 Ready、全部 follower，而 leader Service 显示 `<none>`（before-fix.txt:3-12）。
- **触发设想**：让 Pod 启用 IPv6 回环的任何环境变化，比如容器运行时、CNI 或内核升级。xenon 约 1 秒探活一次，连续 3 次失败就判死（before-fix.txt:27-32），所以约 3 秒后永久无法选主。主会话实测补上 `root@'::1'` 后 10 秒内选出主库。
- **机制专属信号**：
  - xenon 日志里 `ping.error[Error 1045 … '::1']` 持续出现，`downs` 计数一直递增。
  - K8s 层 Ready 全绿，leader 的 Endpoints 为空，所有 Pod 的 role 标签都是 follower。
  - 与 TT-E10 的区别：这里 `xenoncli cluster status` 本身就没有 LEADER；TT-E10 是 xenon 有主，但标签和 Endpoints 不对。
- **业务影响**：
  - nacosdb 无主时，Nacos 的 initmysql 永久等待，Nacos 起不来，接着就是 TT-E02 的全体 CrashLoop。
  - tsdb 无主时，27 个用库服务（其中 25 个 Java）全部失败。三条关键路径全断。
- **旧环境**：配置缺陷同样存在，但触发条件 E4 不成立，属于潜伏。新环境已被偏差 #5 掩盖。
- **运行时要核对**：
  - R11：xenon.json 的 admin、host、ping 相关字段；日志里的 `mysql.dead`。
  - R12：`SELECT user,host FROM mysql.user WHERE user='root'`；`SELECT @@skip_name_resolve,@@bind_address`；`cat /proc/sys/net/ipv6/conf/all/disable_ipv6`；`getent ahosts localhost`；`grep -n "127.0.0.1\|::1\|CREATE USER" /docker-entrypoint.sh`。
  - R17：旧环境做同样的检查。
- **置信度**：高。已在运行时复现；账号来源和 skip_name_resolve 两个细节存疑。

### TT-E02（即 TT-RT-03）业务服务启动强依赖“Nacos 已 Ready”，注册失败就退出，随后的指数退避让恢复滞后数分钟
- **机制族 / 失效模式**：降级回退；恢复 / D6 + N-04
- **位置**：41 个 Java 服务的 Nacos 注册；configmap `nacos` 里的 `NACOS_ADDRS`；`nacos-headless` Service
- **成立条件**：
  - **E1 所有 Java 模块启动时都会自动注册 — 成立。** 根 pom `UP/pom.xml:68-73` 给所有模块引入了 nacos-discovery 2.2.7；`UP/ts-order-service/src/main/resources/application.yml:9`。
  - **E2 注册失败会中止启动 — 成立。**
    - `M2/com/alibaba/cloud/spring-cloud-starter-alibaba-nacos-discovery/2.2.7.RELEASE/*.jar` 的 javap 结果：`NacosDiscoveryProperties` 构造函数里 `failFast=true`、`namingLoadCacheAtStart="false"`。
    - `NacosServiceRegistry.register` 在 `isFailFast()` 为真时调用 `ReflectionUtils.rethrowRuntimeException`。
    - 业务的 yml 都没有覆盖这个开关。
  - **E3 客户端连不上时直接报错 — 成立。**
    - `M2/com/alibaba/nacos/nacos-client/2.0.3` 里 `RpcClient` 的 `RETRY_TIMES=3`，报错字符串是 `"Client not connected,current status:"`。
    - 2.0.3 这个版本来自 `…/spring-cloud-alibaba-dependencies-2.2.7.RELEASE.pom:46`。
  - **E4 “Nacos 不可用”的范围比“Nacos 挂了”大 — 成立。**
    - `NACOS_ADDRS` 是三个 Pod 的 headless 域名（`CH/nacos/templates/configmap.yaml:7`）。
    - `nacos-headless` 没有 `publishNotReadyAddresses`（`CH/nacos/templates/service.yaml:1-24`）。
    - Nacos 的 readiness 在启动 60 秒后才开始探测。
    - 运行时证据：`RE/TT-startup-hard-dependency-on-nacos/crashloop.txt:12` 起连续出现 `UnknownHostException: nacos-0/1/2.nacos-headless…`。
  - **E5 没有启动编排，也没有容忍逻辑 — 成立。** 旧环境的 ts-* 没有 initContainers，也没有 startupProbe（`MF/deployments.json`）。
  - **E6 退避会放大恢复时间 — 成立。** crashloop.txt:2-9 显示 37 个 Pod 处于 CrashLoopBackOff，重启次数多为 15–16。kubelet 的退避上限是 300 秒。
  - **E7 还有同类的数据库启动依赖 — 成立。**
    - 21 个服务有 CommandLineRunner 写库，且不捕获异常（例如 `UP/ts-order-service/src/main/java/order/init/InitData.java:28,45`）。
    - 它在 Tomcat 监听端口和 Nacos 注册之后才运行，所以实例会先注册、再退出，造成注册抖动。
- **触发设想**：Nacos 三个副本同时未 Ready 时，任意业务 Pod 发生启动或重启。
  - Nacos 未 Ready 的场景：全量重启、nacosdb 无主、或 TT-E12 的有序启动卡住。
  - 业务 Pod 重启的场景：OOM、驱逐、或平台重置流程执行 `restart-application-deployments`（`D0/applications/train-ticket.yaml:106`）。
  - Nacos 恢复后，每个服务平均还要再等约 2.5 分钟，最坏约 5 分钟，再加上 JVM 启动时间，才会重新注册。
- **机制专属信号**：
  - 日志出现 `Client not connected,current status:STARTING`、`UnknownHostException: nacos-N.nacos-headless`、`register failed`。
  - Pod 的 lastState exitCode 不是 137（说明不是 OOM）。
  - 与 TT-E03 的区别：TT-E03 的 Pod 卡在 FailedMount，JVM 根本没启动。
- **业务影响**：Nacos 恢复后数分钟内三条关键路径仍不可用。已经在运行的 Pod 不受影响（见 N6、N7）。
- **旧环境**：同样成立，代码与配置和环境无关。新环境里让 Nacos 不可用的诱因是 TT-E01 和一个 cri-dockerd 环境问题（`RE/ENV-pod-status-stuck-after-start/nacos-0.txt`），但缺陷本身在代码和配置层。
- **运行时要核对**：R3、R10、R14，以及各 Pod 的 restartCount 和 lastState.exitCode。
- **置信度**：高。

### TT-E03（即 TT-RT-02）41 个 Java 服务的每次启动都依赖集群外主机 1.94.151.57 的 NFS，这台主机同时是 Harbor
- **机制族 / 失效模式**：依赖；重新调度 / D6
- **位置**：`volumes[opentelemetry-javaagent].nfs` 与 `JAVA_TOOL_OPTIONS` 里的 `-javaagent`
- **成立条件**：
  - **E1 用的是 in-tree NFS 卷 — 成立。** `MF/deployments.json` 有 41 个；团队 08-23 的旧环境快照 `D0/kubernetes/train-ticket/live-export.yaml` 里也是 41 处。
    - 上游只提供了 SkyWalking 变体，做法是用初始化容器从镜像复制 agent（`UP/deployment/kubernetes-manifests/quickstart-k8s/yamls/sw_deploy.yaml.sample:20-25`）。
    - 所以 NFS 方案是旧集群运维自己加的，没有找到说明文档。
  - **E2 JVM 必须加载这个 jar 才能启动 — 成立。** 41 个 env 里都有 `-javaagent:/opt/opentelemetry-javaagent/opentelemetry-javaagent.jar`。
  - **E3 挂载要求节点装有 NFS 客户端且主机可达 — 成立。** 新环境 46 个 Pod（41 个 Deployment 的全部副本）卡在 ContainerCreating，报 `mount -t nfs … bad option … /sbin/mount.<type> helper`（`RE/TT-nfs-javaagent-startup-dependency/before-fix.txt:2,9-12`）。
  - **E4 同一台主机还是镜像仓库 `1.94.151.57:85` — 成立。** `IfNotPresent` 只能在已缓存镜像的节点上缓解拉镜像依赖，而 NFS 挂载每次启动都需要。
  - **E5 运行中 NFS 故障的影响 — 存疑，需要演练。** 硬挂载下，按需加载 agent 类的线程可能阻塞，删除 Pod 时卸载也可能卡住。
- **触发设想**：这台主机或其 NFS 服务不可用之后，任何重启或重新调度都无法完成，恢复时间等于主机恢复时间。
- **机制专属信号**：FailedMount，没有任何容器日志。
- **业务影响**：与 TT-E09 叠加时，一次节点排空就能让大量单副本服务长期下线。
- **旧环境**：依赖同样存在，是潜伏单点。新环境已被偏差 #7 掩盖，而且 agent 换成了 otel-demo 2.2.0 自带的版本。
- **运行时要核对**：
  - 新环境：`unzip -p /opt/opentelemetry-javaagent/opentelemetry-javaagent.jar META-INF/MANIFEST.MF | grep -i version`。
  - R17：旧环境 PV 与节点 NFS 客户端的情况。
- **置信度**：高。

### TT-E04 两套健康判定互不相通：readiness 只管 K8s Service 端点，服务间流量走 Nacos 加 Ribbon，并且所有服务都没有 liveness
- **机制族 / 失效模式**：健康探针；摘除 / D2（包含模板 T-05 与 T-07 的实例）
- **位置**：46 个 ts-* 的探针；40 个服务的 `@LoadBalanced RestTemplate`
- **成立条件**：
  - **E1 只有 TCP readiness，没有 liveness — 成立**（`MF/deployments.json` 共 46 个）。
  - **E2 服务间调用按服务名走客户端负载均衡，不经过 K8s Service — 成立。**
    - `UP/ts-preserve-service/src/main/java/preserve/service/PreserveServiceImpl.java:44-45` 直接拼 `"http://"+serviceName`。
    - `UP/ts-order-service/src/main/java/order/OrderApplication.java:29-33`。
    - 共 40 个服务是这种写法。
  - **E3 Nacos 实例存活只看 gRPC 长连接 — 成立（框架语义）。** 实例是 ephemeral 的（javap 确认 `ephemeral=true`），与 Tomcat 能否处理请求无关。
  - **E4 Ribbon 列表每 30 秒刷新一次 — 成立。** `M2/com/netflix/ribbon/ribbon-loadbalancer/2.3.0` 里 `PollingServerListUpdater` 是 30000 毫秒；业务 yml 没有 ribbon 配置。挂起或返回 5xx 的实例不会被剔除——这个细节存疑。
  - **E5 历史事件印证 — 成立。** order 曾是“0/2 Ready”，最后仍要人工滚动重启（`D0/applications/train-ticket.yaml:137-138`）。
- **触发设想**：让 order 的一个副本线程耗尽。K8s 大约 30–45 秒后把它标为 NotReady，但 Ribbon 仍会把约一半请求发给它。调用方没有超时，于是一起挂住。因为没有 liveness，它永远不会自动重启。
- **机制专属信号**：Pod 显示 NotReady，但 Nacos 的 `/nacos/v1/ns/instance/list?serviceName=ts-order-service&healthyOnly=false` 里这个 IP 仍是 `healthy=true`。
- **业务影响**：preserve 和 query-order 路径的 p95 与成功率同时恶化，而且不会自愈。
- **旧环境**：同样成立。
- **运行时要核对**：R13、R9。
- **置信度**：高（配置和框架层确定；影响有多大需要演练）。

### TT-E05 40 个服务的 RestTemplate 实际是 Apache HttpClient 的系统默认：没有任何超时，每个目标 5 条连接，全服务合计 10 条，借不到连接时无限等待
- **机制族 / 失效模式**：超时；熔断与隔离 / D1 + D4（共享的小连接池加无限排队）+ D5（一个下游挂住，会拖死对其他健康下游的调用）
- **位置**：各服务的 `RestTemplateBuilder.build()`。ts-common 里没有公共 HTTP 配置，只有实体、工具类、JWT 和 Swagger。
- **成立条件**：
  - **E1 classpath 上有 Apache HttpClient — 成立。** nacos-discovery 的 pom（`…2.2.7.RELEASE.pom:151-155`）依赖 netflix-ribbon，netflix-ribbon 再依赖 ribbon-httpclient，后者依赖 httpclient。
  - **E2 Boot 2.3.12 优先选 HttpComponents — 成立。** 用 javap 核对了 `ClientHttpRequestFactorySupplier`；另外 spring-web 5.2.15 的 `HttpComponentsClientHttpRequestFactory()` 内部调用的是 `HttpClients.createSystem()`。
  - **E3 连接池大小 — 成立。** httpclient 4.5.13 的 `HttpClientBuilder.build` 字节码：`http.maxConnections` 默认为 `"5"`，然后执行 `setDefaultMaxPerRoute(5)` 和 `setMaxTotal(10)`。
  - **E4 全仓没有设过任何超时 — 成立。** 用 rg 搜 `setConnectTimeout` 和 `setReadTimeout`，结果为 0。所以：
    - 连接超时交给内核：报文被静默丢弃时，SYN 重传约 127 秒。
    - 读超时无限。
    - 借连接无限等待。
  - **E5 所有下游共用同一个 RestTemplate Bean — 成立。** `PreserveServiceImpl.java:32-33` 注入同一个实例，对 11 个不同的下游发调用。
  - **E6 重试范围很窄 — 成立。**
    - `UP/pom.xml:83` 引入了 integration starter，而 `spring-integration-core-5.3.8.RELEASE.pom:81-85` 依赖 spring-retry。
    - spring-retry 在 classpath 上，于是生效的是 `RetryLoadBalancerInterceptor`：不带重试的那个拦截器配置标了 `@ConditionalOnMissingClass(RetryTemplate)`，已用 javap 核对。
    - Ribbon 默认值是 `MaxAutoRetries=0`、`MaxAutoRetriesNextServer=1`。结果是只有 GET 在连接异常时会多试一次。
- **触发设想**：
  1. 让 ts-seat-service 延迟 60 秒，preserve 到 seat 的 5 条连接挂住。
  2. 再让 ts-security-service 也延迟，preserve 的总连接池 10 条耗尽。
  3. 此后 preserve 对 ts-contacts-service 等健康下游的调用也会无限排队，Tomcat 的 200 个线程逐步耗尽。
- **机制专属信号**：线程栈停在 `AbstractConnPool.getPoolEntryBlocking`（借连接）或 `socketRead0`（读）。数据库池耗尽的特征是 `HikariPool.getConnection`，30 秒后报错，可以据此区分。
- **业务影响**：search 和 preserve 的长尾延迟没有上限。任何一个下游变慢，p95 ≤2500ms 的 SLO 就会违约。
- **旧环境**：同样成立。
- **运行时要核对**：R10（重点是 5 个自建镜像）、R9、R14。
- **置信度**：高。

### TT-E06 ts-order-service“接收队列不排空、FD 与 CLOSE_WAIT 堆积”的配置层根因推断
- **机制族 / 失效模式**：超时；取消传播 / D5（模板 T-02 的实例）
- **成立条件**：
  - **E1 Tomcat 用的全是默认值 — 成立。** 200 个工作线程、maxConnections 8192、acceptCount 100。`application.yml:1-3` 只设了端口，全仓没有 `server.tomcat.*`。
  - **E2 请求线程里存在无界等待 — 成立。**
    - JDBC URL 只有 `useSSL=false`（application.yml:13）。Connector/J 8.0.25 的 connect 和 socket 超时默认都是 0，即不超时（驱动内置说明）。
    - 但在上游源码里，order 唯一的出站调用已经被注释掉了（`UP/ts-order-service/src/main/java/order/service/OrderServiceImpl.java:200`，方法定义在 :208-220）。
    - 所以对 order 来说，阻塞更可能发生在数据库一侧。这一点存疑，因为 1.0.1 镜像的源码未知。
  - **E3 OSIV 默认开启 — 配置成立，影响存疑。** yml 没有设 `open-in-view`，请求内拿到的数据库连接会一直持有到请求结束，而池只有 10 条。
  - **E4 慢查询放大 — 存疑，交给查询链路组核对。** 实体 `Order.java:20` 只有 `@Table(name="orders")`，没有索引；`findByAccountId` 和 `findByTravelDateAndTrainNumber` 会随订单累积变成全表扫描。
  - **E5 调用方放弃后服务端线程不中止，套接字进入 CLOSE_WAIT — 成立（机制）。**
  - **E6 没有 liveness，NotReady 也不影响 Nacos 路由 — 成立**（见 TT-E04）。
- **推断链**：
  1. 某个无界等待占满 200 个线程。
  2. 调用方超时后关闭连接，服务端这边的连接变成 CLOSE_WAIT，FD 持续增长。
  3. 连接数到 8192 后，acceptor 停止 accept，内核 backlog（100）被填满。
  4. TCP 探针开始失败，Pod 显示 0/2 Ready。
  5. 没有 liveness，只能人工重启。
  这条链能同时解释三个现象。
- **触发设想**：订单表增长到一定规模后稳态加压；或者 tsdb 切主、网络闪断时，在途查询卡在半开连接上。
- **机制专属信号**：
  - `ss -ltn` 看到端口 12031 的 Recv-Q 达到 101；`ss -tan state close-wait` 计数持续增长。
  - 线程栈多数停在 `com.mysql.cj … socketRead0` 或 `HikariPool.getConnection`。
  - GC 和 CPU 都正常，据此与 TT-E11、TT-E17 区分。
- **业务影响**：query-order、preserve 和 search 三条路径都受影响。
- **旧环境**：事件本身发生在旧环境（08-21），残余风险也有记录（train-ticket.yaml:138）。
- **运行时要核对**：R9、R12（`orders` 表的行数与索引）、R15。
- **置信度**：中。

### TT-E07 数据库切主不覆盖已建立的连接：旧主变成只读后，池里的连接仍能通过校验，写入最长失败约 30 分钟
- **机制族 / 失效模式**：故障转移 / D2 + D4
- **成立条件**：
  - **E1 所有服务都连 `tsdb-mysql-leader` — 上游成立，环境存疑。** 上游 `UP/hack/deploy/utils.sh:66` 就是这么配的，Service 按 `role=leader` 选择（`CH/mysql/templates/service.yaml:29,53`）。新旧环境的 secret 已脱敏，需要按 R7 核对。
  - **E2 连接池参数全是默认 — 成立。** 全仓没有 hikari 配置。Hikari 3.4.5 的默认值是：池 10、连接超时 30 秒、校验超时 5 秒、最大生命周期 30 分钟（javap 核对）。
  - **E3 只读报错的连接不会被驱逐 — 成立。** Hikari 只在 SQLState 以 08 开头，或属于 0A000、57P01–03、01002、JZ0C0/1、500150、2399 时驱逐连接（`ProxyConnection` 的静态表）。MySQL 只读错误 1290 的状态码是 HY000，不在表里。
  - **E4 kube-proxy 不会中断已建立的连接 — 存疑。**
  - **E5 xenon 降主时是否踢掉用户会话 — 存疑。**
  - **E6 旧主消失时，在途查询只能靠内核重传超时 — 成立。**
- **触发设想**：做一次切主演练。27 个 Pod 各 10 条连接，约 270 条连接留在旧主上，按 30 分钟的生命周期逐步轮换掉。
- **机制专属信号**：Endpoints 已经指向新主，但业务日志仍持续出现 `--read-only option`，旧主的 processlist 里仍有 ts 用户的会话。
- **业务影响**：preserve 和 cancel 的写入失败，最长约 30 分钟。
- **旧环境**：同样成立。
- **运行时要核对**：R7、R11、R12、R14、R16。
- **置信度**：中。

### TT-E08 旧环境 Nacos 三副本注册表分歧、把已不存在的 Pod IP 标为健康：Nacos 集群配置层的根因
- **机制族 / 失效模式**：服务发现；摘除 / D4 + D5
- **成立条件**：
  - **E1 成员列表写死了 Pod 地址？— 不成立。**
    - `NACOS_SERVERS` 是三个 FQDN，`PREFER_HOST_MODE=hostname`（`CH/nacos/templates/statefulset.yaml:35-40`）。
    - 但成员数固定写成了 3。
  - **E2 成员域名只在 Pod Ready 时存在 — 成立。**
    - `nacos-headless` 没有 `publishNotReadyAddresses`，而 MySQL Chart 设了（`CH/mysql/templates/service.yaml:19-20`）。
    - 客户端解析失败已在运行时观察到。
    - 对等节点之间的 Distro 同步和校验是否也因此失败，存疑。
  - **E3 Ready 不等于 Distro 数据就绪 — 成立。** readiness 只探 TCP 8848。团队修复记录里明确写了要“等 Distro 快照初始化，而不是只看 K8s readiness”（`D0/repairs/train-ticket-nacos-workload-qualification-20260822.yaml:25`）。
  - **E4 Nacos 没有持久卷 — 成立**（`MF/statefulsets.json`）。这也解释了为什么逐个重启就能清掉陈旧实例：重启后的节点会从对端重建数据（修复记录:24、26）。
  - **E5 实例存活与清理的机制 — 框架层成立，服务端清理缺陷存疑。**
    - 客户端 2.0.3 的实例存活绑定在 gRPC 连接上，不看心跳。`heartBeatInterval` 和 `ipDeleteTimeout` 没有设置，而且只对 1.x 的 HTTP 心跳生效。
    - 其他副本要靠删除同步，或者靠校验续约加过期来清理实例。
    - 删除同步如果因 E2 失败，而 2.0.1 的过期清理又没起作用，陈旧实例就会一直保留。本机没有服务端 jar，这一点无法离线核实。
  - **E6 postStart 用 `debug=true` 关掉双写 — 配置成立，是否会被 Raft 持久化的开关覆盖存疑。**
    - 这样改只作用于本节点内存，不持久化（live-export.yaml:1283-1289）。
    - 上游 Chart 没有这个钩子，部署说明里也没有记录原因。
  - **E7 客户端侧放大 — 成立。** Ribbon 有 30 秒缓存；连接不存在的 IP 时没有连接超时，每次约 127 秒；团队当时还需要重启网关（修复记录:27）。
  - **E8 客户端的空推送保护是关的 — 存疑。** SCA 2.2.7 没有暴露这个属性，客户端默认 false。
- **触发设想**：在某个 Nacos 副本未 Ready 的窗口里，业务 Pod 重建并换了 IP。旧环境实际出现的陈旧实例是：order `10.0.2.124:12031`、preserve `10.0.2.194:14568`、gateway `10.0.2.1` 和 `10.0.2.93:18888`（修复记录:10-22）。
- **机制专属信号**：三个节点的 instance/list 结果不一致；Nacos 日志里有 `UnknownHostException: nacos-N.nacos-headless`，或 DISTRO 同步、校验失败的记录。
- **业务影响**：一部分调用打到不存在的 IP 并挂住约 2 分钟；入口流量也可能被转给陈旧的网关实例。
- **旧环境**：事件发生在旧环境。新环境按偏差 #8 全部部署在单节点上，跨节点触发变少，但 E2 和 E3 的机制仍在。副本一致性仍未做成自动闸门（train-ticket.yaml:130-132）。
- **运行时要核对**：R13、R3。
- **置信度**：中。

### TT-E09 没有 PDB，46 个 ts-* 里 41 个单副本，多副本服务和三成员仲裁组都没有反亲和，本地盘还把 MySQL 钉在节点上
- **机制族 / 失效模式**：副本与中断预算 / D1 + D2（模板 T-06 的实例）
- **成立条件**：
  - E1 没有 PDB — 成立。
  - E2 46 个 ts-* 里 41 个单副本，rabbitmq 也是单副本 — 成立。
  - E3 没有 podAntiAffinity 或拓扑分散；三个 StatefulSet 的 affinity 都是 null — 成立。
  - E4 新环境的数据卷是 openebs-hostpath，Pod 被钉在原节点 — 成立。
  - E5 实际放置 — 存疑。需要看 R2，确认是否有 2 个 tsdb 成员或 2 个 order 副本落在同一节点。
- **触发设想**：排空一个承载 2 个 tsdb 成员的节点。xenon 失去多数派，所有写入中断；被驱逐的成员因为本地盘只能等原节点回来。
- **机制专属信号**：没有 LEADER；MySQL Pod 处于 Pending，事件为 volume node affinity conflict。
- **业务影响**：27 个用库服务的写入全部中断，直到被驱逐的成员所在的原节点恢复；单副本服务每次排空都要等重建和 JVM 启动。
- **旧环境**：配置相同，旧环境有 2 个可调度节点。新环境被偏差 #8 全部固定到 vm-0-10-ubuntu，这类结论在新环境不代表旧环境。
- **运行时要核对**：R1、R2、R4。
- **置信度**：配置层高，实际放置待核。

### TT-E10 切主的“通告”靠 leader-start/stop.sh 用 curl 改 Pod 标签：不检查返回状态，没有超时和重试，异常失主会留下陈旧的 leader 标签
- **机制族 / 失效模式**：故障转移 / D4 + D6
- **位置**：`CH/mysql/templates/configmap.yaml:29-38`；`MF/configmaps.json`
- **成立条件**：
  - E1 curl 没有 `-f`、`--max-time`、`--retry`。API 返回 4xx 或 5xx 时脚本仍然以 0 退出 — 成立。
  - E2 Service 只按 role 标签选择后端（service.yaml:53），模板里的标签是 `role=candidate` — 成立。
  - E3 SIGKILL、节点失联或容器原地重启时不会执行 leader-stop，旧的 `role=leader` 标签会保留 — 存疑。
  - E4 探针不检查角色和 `read_only` — 成立。
- **触发设想**：切主时 API Server 抖动；或者 leader 所在容器被 kill -9 后原地重启。结果是 Endpoints 地址数为 0 或 2。
- **机制专属信号**：`kubectl get endpoints tsdb-mysql-leader` 的地址数不等于 1，而 `xenoncli cluster status` 显示只有一个 LEADER。
- **业务影响**：地址数为 0 时与 TT-E01 一样全局中断；为 2 时约一半新连接落到只读从库，表现同 TT-E07。
- **旧环境**：同样成立。
- **运行时要核对**：R2、R3、R11。
- **置信度**：中低。

### TT-E11 JVM 内存与容器上限错配：40 个服务的堆只有 200MB 而上限是 1500Mi，堆内 OOM 对 K8s 不可见；网关 1024MB 堆加默认直接内存可能超出上限
- **机制族 / 失效模式**：资源配额 / D4（模板 T-08；相当于 N-03 的 JVM 版本）
- **成立条件**：
  - E1 堆大小来自镜像 CMD（`UP/ts-order-service/Dockerfile:1,6`、`UP/ts-gateway-service/Dockerfile:6`），K8s 没有覆盖 command — 成立。镜像是否按这些 Dockerfile 构建需要 R8 确认。
  - E2 OTel agent 与业务共用这 200MB 堆 — 机制成立，占用量存疑。
  - E3 没有设 `ExitOnOutOfMemoryError`，也没有 liveness — 成立。
  - E4 网关的直接内存默认约等于堆大小，堆与直接内存相加超出 1500Mi — 存疑。
- **触发设想**：大响应或全量订单查询（`getAllOrders` 调用 `findAll`）；入口压测。
- **机制专属信号**：日志里有 OutOfMemoryError，但 restartCount 不变。网关的 lastState 为 OOMKilled、137。
- **业务影响**：堆耗尽的僵尸实例继续接收流量；网关三个副本是同一配置，压测时可能相继被杀，导致入口中断。
- **旧环境**：同样成立。
- **运行时要核对**：R6、R8、R15。
- **置信度**：中。

### TT-E12 StatefulSet 按序启动，再加上多处没有超时的循环：一个成员卡住，就挡住其余成员的重建
- **机制族 / 失效模式**：恢复 / D6 + D5
- **成立条件**：
  - E1 `podManagementPolicy: OrderedReady`（`CH/nacos/templates/statefulset.yaml:7`，三个 StatefulSet 都是）— 成立。
  - E2 三处等待都没有超时 — 成立：initmysql 的 `until nc -z`、Nacos 的 postStart `until curl`、xenon 的 postStart `until … cluster add`。
  - E3 每个 Nacos 成员至少 60 秒才能 Ready — 成立。
  - E4 新环境 nacos-0 卡住时 nacos-1/2 缺位 — 存疑（诱因是环境问题）。
- **触发设想**：nacosdb 无主时重建全部 Nacos 成员。nacos-0 停在 Init，nacos-1/2 不会被创建。数据库恢复后，Nacos 至少还需要 3 ×（启动时间 + 60 秒）。
- **机制专属信号**：StatefulSet 事件里有 “waiting for Pod … Running and Ready”；initmysql 日志反复打印 “not yet”。
- **业务影响**：服务发现的中断时间被放大，接着触发 TT-E02。
- **旧环境**：同样成立。
- **运行时要核对**：R5、R13。
- **置信度**：中。

### TT-E13 资源请求严重失真（CPU 10m、内存 100Mi），全量重启时 41 个 JVM 加 agent 同时冷启动，形成恢复风暴
- **机制族 / 失效模式**：资源与准入 / D5
- **成立条件**：
  - E1 46 个 Pod 的请求合计 0.46 核、约 4.5Gi，而上限合计 69 核、约 67Gi — 成立。
  - E2 启动开销远大于请求值 — 机制成立，量级存疑。启动时 21 个服务写库，约 270 条数据库连接同时建立，46 个实例同时注册 Nacos。
  - E3 平台重置流程会重启全部 Deployment（train-ticket.yaml:106）— 成立。新环境还全部在单节点上。
  - E4 QoS 是 Burstable，节点内存有压力时会按“超出请求的用量”驱逐 — 成立。
- **触发设想**：节点故障后重新调度，或者平台执行重置。
- **机制专属信号**：`Started … in N seconds` 的 N 成倍增长；CFS 节流突增；Nacos 实例数缓慢爬升。
- **业务影响**：恢复时间变长，qualify 窗口失败；与 TT-E02 的退避叠加。
- **旧环境**：同样成立，但旧环境分布在 2 个节点上，程度较轻。
- **运行时要核对**：R14、R15。
- **置信度**：中。

### TT-E14 网关没有连接和响应超时、连接池不设上限，Sentinel 只给一条管理路由限了流（与入口组有重叠）
- **机制族 / 失效模式**：超时与准入 / D1 + D2
- **成立条件**：
  - E1 Spring Cloud Gateway 2.2.9 的连接池默认 ELASTIC，连接超时和响应超时都是 null（javap 核对 `HttpClientProperties`）；网关 yml 里的 39 条 `lb://` 路由都没有设置 — 成立。
  - E2 `GatewayConfiguration.java:107-118` 只对 `admin-basic-info` 设了 QPS 20 — 成立。
  - E3 网关同样受 Ribbon 30 秒缓存的影响 — 成立。
- **触发设想**：后端变慢时网关无限等待，连接数和直接内存持续增长；突发流量不会被限流。
- **机制专属信号**：没有 429 返回，也没有限流日志；网关到后端的连接数随延迟线性增长。
- **业务影响**：入口 p95 没有上限，过载时入口先垮。
- **旧环境**：同样成立。
- **运行时要核对**：R14、R15。
- **置信度**：中高。

### TT-E15 RabbitMQ 单实例，没有持久卷，没有内存上限，也没有 liveness（消息语义交给消息链路组）
- **机制族 / 失效模式**：副本、持久化、资源 / D1（模板 T-06、T-10、T-08）
- **成立条件**：
  - 单副本，没有卷 — 成立（`MF/deployments.json`；`CH/rabbitmq/values.yaml:14-20`）。
  - 只设了请求 100m/200Mi，没有 limits — 成立。
  - 只有 TCP readiness — 成立。
  - 依赖它的服务有 5 个 — 成立：delivery、food、notification、preserve、preserve-other。
  - 内存高水位的实际值 — 存疑。
- **触发设想**：删除 rabbitmq Pod 后，所有未消费的消息丢失；消费者停摆时内存无限增长。
- **机制专属信号**：重启后 `rabbitmqctl list_queues` 为空。
- **业务影响**：preserve 之后的通知和配送链路。
- **旧环境**：同样成立。
- **运行时要核对**：`rabbitmqctl status` 中的 `vm_memory_high_watermark`；R6。
- **置信度**：中。

### TT-E16（仅旧环境）三个 MySQL 副本的数据卷都在同一个 NFS 供给器上，副本不是独立的故障域
- **机制族 / 失效模式**：故障转移 / D6
- **成立条件**：
  - E1 旧环境 7 个 PVC 都是 `nfs-client`，供给器为 `cluster.local/nfs-provisioner-nfs-subdir-external-provisioner`（`D0/kubernetes/train-ticket/live-export.yaml:151-163`）— 成立。
  - E2 背后是同一台 NFS 服务器 — 存疑。
  - E3 NFS 卡顿时三个成员同时阻塞 — 存疑。
- **机制专属信号**：NFS 卡顿时三个成员的 mysqld 同时阻塞，xenon 无论选谁都不可写；按 R17 查各 PV 的 `spec.nfs.server` 是否为同一台主机。
- **业务影响**：“三副本高可用”在存储层退化成了单点。
- **新环境**：被偏差 #1 掩盖，但换成了 TT-E09 的本地盘绑定问题。
- **运行时要核对**：R17。
- **置信度**：中低。

### TT-E17 `FROM java:8-jre` 很可能不感知容器，按宿主机核数设 GC、JIT 和 Netty 的线程数，在 1.5 核限额下被节流
- **机制族 / 失效模式**：资源 / D4（模板 T-08）
- **成立条件**：
  - E1 JDK 版本低于 8u191 — 存疑。Docker Hub 的 java 镜像已停更，推断为 8u111。
  - E2 CPU 上限为 1500m — 成立。
  - E3 宿主机核数明显大于 2 — 存疑。
- **机制专属信号**：CFS 节流很高而 CPU 使用率不高；GC 停顿长；线程数异常多。
- **业务影响**：长尾延迟变差，并放大 TT-E13 的冷启动风暴。
- **旧环境**：同样成立。5 个自建镜像的基础镜像未知。
- **运行时要核对**：R8、R15、R16。
- **置信度**：中低。

### TT-E18 27 个服务共用一个 tsdb 主库；`max_connections=65535` 远超 1Gi 内存能承受的量；1 秒超时的 exec 就绪探针在 500m 限额下可能把主库误摘
- **机制族 / 失效模式**：准入；探针 / D4
- **成立条件**：
  - 所有服务共用一个库（all-in-one 模式，`UP/hack/deploy/utils.sh:59-67`）— 成立。
  - 连接风暴时 mysqld 会先被 OOMKill，而不是返回 “Too many connections” — 配置成立，临界值存疑。
  - 探针 1 秒超时导致误摘（`CH/mysql/values.yaml:56-61`）— 存疑。
- **机制专属信号**：tsdb Pod 有 Unhealthy 事件；leader 的 Endpoints 短暂为空，而 xenon 仍是 LEADER。
- **业务影响**：主库被摘期间所有新连接被拒；连接风暴时 mysqld 可能被 OOMKill，从而触发切主。
- **旧环境**：同样成立。
- **运行时要核对**：R5、R12（`thread_stack`、`innodb_buffer_pool_size`、`Max_used_connections`）。
- **置信度**：低到中。

### TT-E19 xenon 判死太灵敏（约 1 秒一次，连续 3 次失败即判死），CPU 限额又小：负载尖峰可能误切主，进而引发 TT-E07 和 TT-E10
- **机制族 / 失效模式**：故障转移 / D3
- **成立条件**：
  - 判死阈值（before-fix.txt:27-32）— 成立。
  - xenon 限额 100m、mysqld 限额 500m — 成立。
  - ping 超时和 raft 参数 — 存疑。
- **机制专属信号**：xenon 日志先出现 `mysql.dead` 然后角色切换，而 mysqld 进程从没重启过。
- **业务影响**：一次误切主会带出 TT-E07 的只读写失败和 TT-E10 的标签风险。
- **运行时要核对**：R11，以及 xenon 的 CFS 节流指标。
- **置信度**：低到中。

### TT-E20 xenon 半同步复制可能被设为无限等待：从库都不能 ACK 时，主库提交一直挂着，叠加客户端没有超时，形成全局悬挂
- **机制族 / 失效模式**：D3
- **成立条件**：
  - 半同步复制的超时设置 — 存疑。Chart 和 ConfigMap 都没有设置，由镜像决定。
  - 客户端没有超时 — 成立（见 TT-E05、TT-E07）。
- **机制专属信号**：业务线程停在提交阶段；`Rpl_semi_sync_master_status` 为 ON，但从库不回 ACK。
- **业务影响**：全局悬挂，而不是快速失败。
- **运行时要核对**：R12 的 `SHOW VARIABLES LIKE 'rpl_semi_sync%'`。
- **置信度**：低。

### TT-E21 1Gi 数据卷与 binlog 增长：MySQL 5.7 默认不过期 binlog，写满后写入挂起
- **机制族 / 失效模式**：资源 / D1
- **成立条件**：
  - 数据卷 1Gi — 成立。
  - binlog 不过期且 xenon 不清理 — 存疑。
- **机制专属信号**：磁盘写满；写入挂起而不是报错。
- **业务影响**：所有写入挂起。
- **运行时要核对**：R12 的 `SHOW BINARY LOGS`、`@@expire_logs_days`、`df -h /var/lib/mysql`。
- **置信度**：低。

---

## 三、5 个另行构建镜像的来源

- **上游样例里有没有这些标签**：上游 313886e9 的 `deploy.yaml.sample` 引用的版本是：
  - `codewisdom/ts-order-service:1.0.1`（:1015）
  - `ts-order-other-service:1.0.1`（:969）
  - `consign-price:1.0.0`（:485）
  - `payment:1.0.0`（:1061）
  - `station-food:1.0.0`（:1453）
  
  所以只有 `ts-order-service:1.0.1` 在上游出现过，Harbor 里的这份是否就是上游那份，需要比对 digest。其余四个版本上游都没有。
- **没有找到改动原因**：
  - 团队的各份清单、偏差日志和 repairs 记录里都没有记载。
  - 这 5 个服务的源码在上游目录和 materialized 副本之间逐文件一致。
  - 上游 git 历史里也搜不到这些标签。
  - 结论是**来源不明**。修复记录本身也写明镜像“尚未证明来自锁定的源码提交”（repairs yaml:66）。
- **对本报告的影响**：TT-E06 是基于上游源码推断的，1.0.1 的实际代码可能不同。需要按 R18 比对。

## 四、保护有效的点（负控制）

- **N1 探针端口正确。** 41 个 Java 服务的 readiness 端口与 `server.port` 逐一一致，“探针指向错端口”不成立。
- **N2 成员地址用稳定的 DNS 名，不是 Pod IP。** 包括 `NACOS_SERVERS`、`NACOS_ADDRS`、`create-peers.sh`，并设了 `PREFER_HOST_MODE=hostname`。
- **N3 MySQL 管理 Service 设了 `publishNotReadyAddresses: true`**（`CH/mysql/templates/service.yaml:19-20`），xenon 的对等发现不受就绪状态影响。可以和 Nacos 做对照。
- **N4 连接池总和没有超过数据库上限。** 约 270 条，远小于 65535。但见 TT-E18：这个上限本身设得比内存能承受的高得多。
- **N5 N-01（同步导出遥测拖慢业务）大概率不成立。** agent 在后台线程批量导出，队列有界，满了就丢弃，清单也没有改过相关参数。但旧环境的 agent 版本未知，新环境又换了版本，需要核对。
- **N6 已运行的 Pod 在 Nacos 恢复后能自动重新注册和订阅。** jar 里有 `NamingGrpcRedoService`。
- **N7 Nacos 全挂时，已订阅的服务继续用内存里的旧列表。** 新发起的订阅和重启的 Pod 不受这层保护。
- **N8 重试放大（T-03）不成立。** 只有 GET 会在连接异常时多试一次，POST 不重试。
- **N9 mysql 和 xenon 容器的 liveness 能处理进程挂死。**
- **N10 单副本滚动更新会等新 Pod Ready 后再删旧 Pod。** 但这只对走 K8s Service 的入口流量有效，对 Nacos 路由的流量无效。

## 五、偏差造成的掩盖关系

| 偏差 | 影响的条目 |
|---|---|
| #1 数据卷改为 openebs-hostpath | 掩盖 TT-E16；引入 TT-E09 的 E4 |
| #2 去掉 clusterIP | 导出无法判断 Service 是否 headless，本报告改以 Chart 为准 |
| #5 补建 `root@'::1'` | 掩盖 TT-E01 |
| #7 探针 jar 改为 emptyDir 加初始化容器 | 掩盖 TT-E03；agent 版本变化影响 TT-E11 和 N5 |
| #8 全部固定到单节点 | 掩盖或改变 TT-E09、TT-E08；放大 TT-E13 和 TT-E17 |

cri-dockerd 的“状态卡住”是环境问题，不计入缺陷。

## 六、运行时核对清单汇总（除 R19 外均为只读）

- **R1** `kubectl -n train-ticket get pdb,hpa,networkpolicy,limitrange,resourcequota`
- **R2** `kubectl -n train-ticket get pod -o wide -L role,app`：看各成员和各副本所在的节点；每个 MySQL 集群应恰好有 1 个 `role=leader`。
- **R3** `kubectl -n train-ticket get endpoints tsdb-mysql-leader nacosdb-mysql-leader nacos-headless -o yaml`：看 leader 的地址数，以及 `notReadyAddresses`。
- **R4** 查看 PVC 与 PV：新环境看 `spec.nodeAffinity`，旧环境看 `spec.nfs.server`。
- **R5** `kubectl get events --field-selector reason=Unhealthy`，以及 StatefulSet 的 “waiting for Pod” 事件。
- **R6** 各 Pod 的 `restartCount` 和 `lastState.terminated.{reason,exitCode}`。
- **R7** 只取 secret 里的 HOST 键：`kubectl -n train-ticket get secret ts-order-mysql -o jsonpath='{.data.ORDER_MYSQL_HOST}' | base64 -d`
- **R8** 在 Java Pod 里执行：
  - `tr '\0' ' ' </proc/1/cmdline`
  - `java -version`
  - `ls /proc/1/task | wc -l`、`ls /proc/1/fd | wc -l`
  - `nproc` 与 cgroup 的 CPU 配额
- **R9** 在 order 的两个 Pod 里执行：
  - `ss -ltn 'sport = :12031'`
  - `ss -tan state close-wait | wc -l`
  - `kill -3 1` 后用 `kubectl logs` 看线程栈。这一步会发一次信号，需要主会话确认可以接受。
- **R10** `unzip -l /app/*.jar | grep -E 'BOOT-INF/lib/(httpclient|spring-retry|nacos-client|spring-cloud-starter-alibaba-nacos-discovery|spring-cloud-netflix-ribbon|HikariCP|mysql-connector)'`
- **R11** 在 xenon 容器里：
  - `cat /etc/xenon/xenon.json`，遮蔽密码后看 admin、host、ping、election、semi-sync、purge 相关的键
  - `xenoncli cluster status`、`xenoncli raft status`
  - 日志 grep `mysql.dead|ping.error|leader-start|leader-stop`
- **R12** 在每个 MySQL 成员上执行只读 SQL：
  - `SELECT user,host FROM mysql.user WHERE user='root'`
  - `SELECT @@skip_name_resolve,@@bind_address,@@read_only,@@super_read_only,@@max_connections,@@thread_stack,@@innodb_buffer_pool_size,@@expire_logs_days`
  - `SHOW VARIABLES LIKE 'rpl_semi_sync%'`
  - `SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_connected','Max_used_connections','Rpl_semi_sync_master_status')`
  - `SELECT user,host,COUNT(*) FROM information_schema.processlist GROUP BY 1,2`
  - `SHOW BINARY LOGS`
  - `orders` 表的 `COUNT(*)` 和 `SHOW INDEX`
  - shell：`df -h /var/lib/mysql`、`cat /proc/sys/net/ipv6/conf/all/disable_ipv6`、`getent ahosts localhost`、`grep -n "127.0.0.1\|::1\|CREATE USER" /docker-entrypoint.sh`
- **R13** 在 Nacos 三个成员上逐一执行 `curl -s 127.0.0.1:8848`：
  - 接口：`/nacos/v1/ns/operator/switches`、`/nacos/v1/ns/operator/metrics`、`/nacos/v1/core/cluster/nodes`、`/nacos/v1/ns/instance/list?serviceName=<ts-order/preserve/seat/gateway-service>&healthyOnly=false`。结果与 `kubectl get pod -o wide` 的 IP 比对。
  - `ps -ef | grep java`
  - `grep -nE "expired|distro|db.url" /home/nacos/conf/application.properties`
  - `naming-distro.log`、`naming-server.log`、`nacos-cluster.log`、`alipay-jraft.log` 里 grep `UnknownHost|DISTRO|verify|expire|disconnect|No DataSource`
- **R14** 业务日志 grep：`Client not connected`、`register failed`、`UnknownHostException: nacos-`、`No instances available for`、`--read-only option`、`Communications link failure`、`Connection is not available`、`OutOfMemoryError`、`Started .* in`
- **R15** Prometheus 指标：
  - `container_cpu_cfs_throttled_periods_total`
  - `container_memory_working_set_bytes` 与 `kube_pod_container_resource_requests` 对比
  - `kube_pod_container_status_restarts_total`、`kube_pod_container_status_last_terminated_reason`
  - OTel 导出的 JVM 堆与 Hikari 池使用量和等待数（指标名称随 agent 版本不同）
- **R16** 节点 CPU 核数；kube-proxy 模式；节点 sysctl `tcp_syn_retries` 和 `tcp_retries2`。
- **R17** 旧环境如果还能访问：做 R12 中 IPv6 与账号相关的项；查 PV 的 NFS server 和节点上的 NFS 客户端。
- **R18** 5 个自建镜像：与 Docker Hub 同名标签比对 digest，看镜像 history，并与 313886e9 的构建产物比对 jar。
- **R19**（演练项，不是只读，按实验计划执行）：tsdb 切主；Nacos 三成员全部 NotReady；探针 jar 缺失；节点排空；下游注入延迟。