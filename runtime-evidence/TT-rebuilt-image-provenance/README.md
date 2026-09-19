# train-ticket 部署镜像与上游源码的比对

**问题**：集群里跑的 train-ticket 镜像，和审计所依据的上游源码（FudanSELab/train-ticket @ 313886e9）是不是同一份代码？
哪些服务被改过、改了什么、是不是植入了故障？

**为什么要问**：静态审计的全部代码级结论都建立在上游源码上。如果部署镜像与上游不一致，
那些结论对被测系统就不成立。交接文档里「结论依赖这 6 个服务源码的条目，一律标『运行镜像与上游源码不一致，待镜像比对』」
说的就是这件事。

---

## 1. 方法

比对脚本是同目录的 `diff_images.py`（只读，匿名 pull 令牌只在内存里，不落盘）。它做四件事：

1. **解析镜像**：tag → OCI image index → linux/amd64 manifest（跳过 buildx 证明条目）→ 拉取镜像配置与 SLSA provenance。
2. **比对层与 jar**：按层摘要找出公共前缀，只下载其上的层；把应用 fat jar 逐条目比对（CRC32 + 大小），
   分类成 classes / resources / 依赖 jar / Spring Boot loader / META-INF，并对字节有变化的依赖 jar（如 ts-common）再下钻一层。
3. **反编译比对**：对每个有变化的 class 跑 `javap -c -p -constants -l`，**剥掉常量池索引**（常量池顺序属于构建噪声），
   按成员切分，输出与字节码偏移无关、且带源码行号标注的指令级差异。
4. **与上游源码对拍**（`--upstream-compile`）：用本机 javac 8 编译上游的 ts-common 和该服务，
   classpath 直接用镜像自带的 `BOOT-INF/lib`，再把镜像里每个 class 与编译产物逐个比对。

判定口径，三档：

| 结果 | 含义 |
|---|---|
| **byte-identical** | 镜像里的 class 与上游源码的编译产物逐字节相同 → 确定出自这份源码 |
| **normalised-identical** | 规范化（剥常量池索引、`ldc_w`→`ldc` 等）后相同 → 语义相同，差异只是编译环境 |
| **different** | 规范化后仍不同 → 确有代码差异 |

`only-image` 表示镜像里有而上游编译产物里没有的 class。对于匿名内部类（`Xxx$1`、`Xxx$4`），
这通常意味着**新增了 lambda 或匿名类**，是最值得追查的信号。

**本轮的执行范围**：交接时 `partial/` 里已有两份结果——`summary.txt`（6 个服务的 tag 间比对 + 与上游对拍）和
`summary-deployed-scan.txt`（`deployments.json` 里全部 46 个 ts-* 镜像与上游对拍）。
本轮尝试重跑以取得成员级的 javap 差异，但 Harbor 到本机的实测带宽只有约 34 KB/s（手工 curl 峰值 270 KB/s），
12 个 fat jar 层合计约 860 MB，估算需 6 小时以上，遂中止。
**因此本文的「改了哪些类」是已核实的，「具体改成了什么」除单独说明的部分外均为未核实。**
需要时在带宽较好的环境重跑：`python3 diff_images.py --skip-inventory --upstream-compile --pair <repo>:<old>:<new>`。

---

## 2. 总览：46 个部署镜像

| 分类 | 数量 | 说明 |
|---|---|---|
| 与上游编译结果完全一致 | 23 | 41 个 Java 服务中的 23 个，`byte-identical` 全中且资源无差异 |
| 有 class 差异 | 16 | 见第 3 节 |
| 只有资源或 Dockerfile 差异 | 2 | ts-gateway-service、ts-wait-order-service |
| 非 Java 组件 | 5 | ts-avatar、ts-news、ts-ticket-office、ts-ui-dashboard、ts-voucher |

**与上游完全一致的 23 个**（这些服务的静态结论可以直接采信）：
ts-admin-basic-info、ts-admin-route、ts-admin-travel、ts-assurance、ts-auth、ts-basic、ts-config、
ts-consign、ts-contacts、ts-delivery、ts-execute、ts-food-delivery、ts-food、ts-inside-payment、
ts-notification、ts-price、ts-route-plan、ts-route、ts-seat、ts-security、ts-train-food、
ts-travel-plan、ts-verification-code（均为 1.0.0）。

> **对交接结论的一处修正**：交接文档把范围写成「6 个被重打或被改过的服务」，指的是 5 个非 1.0.0 标签的服务
> 加上被反复重推的 ts-travel-service:1.0.0。但按 `deployments.json` 全量扫描，**标签仍是 1.0.0 的服务里也有 11 个与上游不一致**，
> 其中 ts-preserve-service:1.0.0 的差异比任何一个改过标签的服务都大。
> 「标签没变 = 代码没变」在这个仓库里不成立。

---

## 3. 逐个服务：改了哪些类

按差异类数从多到少。「真差异」指规范化后仍不同的 class 数。

### 3.1 标签仍是 1.0.0 但代码与上游不一致（11 个）

| 服务 | byte-identical | 真差异 | 差异的 class | 备注 |
|---|---|---|---|---|
| **ts-preserve-service:1.0.0** | 6/16 | **10** | PreserveController、PreserveServiceImpl 及 `$1`–`$8` | 镜像多出 `PreserveServiceImpl$8`；application.yml 也不同。**含 ts-traceenv-test** |
| **ts-travel-service:1.0.0** | 9/18 | 5 | TravelApplication、TravelController、TravelServiceImpl 及 `$4`、`$5` | 镜像多出 `$4`、`$5`；application.yml 也不同。**含 ts-traceenv-test**，详见第 4 节 |
| **ts-preserve-other-service:1.0.0** | 6/17 | 3 | PreserveOtherController、PreserveOtherServiceImpl 及 `$9` | 镜像多出 `$9`。**含 ts-traceenv-test** |
| **ts-train-service:1.0.0** | 7/10 | 3 | TrainController、TrainServiceImpl 及 `$1` | 镜像多出 `$1`。**含 ts-traceenv-test** |
| ts-admin-user-service:1.0.0 | 8/10 | 2 | UserDto、UserDto$UserDtoBuilder | 只涉及 DTO，疑似 Lombok 版本差异 |
| ts-user-service:1.0.0 | 0/16 | 2 | UserRepository、UserServiceImpl | **16 个 class 全部字节不同，但 14 个规范化后相同**——整个服务是用不同编译器编的，真正改过的只有 2 个 |
| ts-admin-order-service:1.0.0 | 7/8 | 1 | AdminOrderServiceImpl | |
| ts-cancel-service:1.0.0 | 8/12 | 1 | CancelServiceImpl | application.yml 也不同 |
| ts-rebook-service:1.0.0 | 6/10 | 1 | RebookServiceImpl | application.yml 也不同 |
| ts-station-service:1.0.0 | 8/9 | 1 | StationServiceImpl | |
| ts-travel2-service:1.0.0 | 11/16 | 1 | travel2/TravelServiceImpl | application.yml 也不同 |

### 3.2 改过标签的服务（5 个）

| 服务 | byte-identical | 真差异 | 差异的 class | 相对 1.0.0 的语义变化 |
|---|---|---|---|---|
| **ts-consign-price-service:1.0.1** | 5/9 | 4 | ConsignPrice、InitData、ConsignPriceConfigRepository、ConsignPriceServiceImpl | 1.0.0→1.0.1 改了 InitData、Repository、ServiceImpl 三个类 |
| **ts-payment-service:1.0.2** | 8/12 | 4 | PaymentController、PaymentRepository、PaymentServiceImpl 及 `$1` | 1.0.0→1.0.1 只改 ServiceImpl；1.0.1→1.0.2 又改了 Repository。**含 ts-traceenv-test** |
| **ts-order-service:1.0.1** | 9/13 | 3 | OrderController、OrderServiceImpl 及 `$2` | 1.0.0→1.0.1 改了 OrderServiceImpl。**含 ts-traceenv-test** |
| **ts-order-other-service:1.0.2** | 9/12 | 2 | other/InitData、OrderOtherServiceImpl | 1.0.0→1.0.1 改 InitData；1.0.1→1.0.2 改 OrderOtherServiceImpl |
| **ts-station-food-service:1.0.1** | 7/9 | 2 | food/InitData、StationFoodRepository | **1.0.0 与上游 9/9 完全一致**，改动都发生在 1.0.1 |

`ts-station-food-service` 这一行值得单独说：它的 **1.0.0 是干净的**，所以「改标签」确实对应着「改代码」，
而不是单纯重打包。这与 3.1 节里那些「标签没变但代码变了」的服务正好相反，说明这个仓库里标签与代码的对应关系不可靠。

### 3.3 只有资源或构建差异（2 个）

- **ts-gateway-service:1.0.0**：2 个 class 全部 byte-identical，但 **application.yml 与上游不同**，
  且 jar 里能 grep 到 `traceenv`。网关的路由表就写在 application.yml 里，所以这个差异很可能就是一条指向
  `ts-traceenv-test` 的路由——见第 4 节。
- **ts-wait-order-service:1.0.0**：13/13 class 全部 byte-identical，但 **Dockerfile 的 EXPOSE 从 15678 改成了 17525**，
  application.yml 也不同。端口改动会影响探针与 Service 的对应关系，值得在部署清单里核对一次。

### 3.4 非 Java 组件（5 个）

| 服务 | 结果 |
|---|---|
| ts-ticket-office-service:1.0.0 | 1701 个源文件全部一致。但基础镜像是 `FROM node` 不固定版本，实际跑的是 **Node v25.8.1** |
| ts-voucher-service:1.0.0 | 2 个源文件一致（requirements.txt 没锁版本，实际库版本未核实） |
| ts-news-service:1.0.0 | 1 个源文件一致 |
| ts-ui-dashboard:1.0.0 | 135 个源文件中 **3 个 js 不同**：admin_user.js、client_collect.js、client_ticket_book.js |
| ts-avatar-service:1.0.0 | Dockerfile 与 requirements.txt 都不同：上游是 4 条独立 `RUN apt`，镜像里合并成一条带 fallback 的命令，pip 也加了 `--upgrade pip` |

---

## 4. ts-traceenv-test：上游源码里不存在的服务

这是本次比对最值得注意的发现。

### 4.1 范围：不是一个服务，是七个

交接文档记的是「运行中的 ts-travel-service:1.0.0 向 Nacos 订阅了上游源码里没有的 ts-traceenv-test」。
按 `--grep` 的全量扫描结果，**部署中的 46 个镜像里有 7 个的 jar 含 `ts-traceenv-test` 字符串**：

| 服务 | 命中的 class | 同时含 `traceenv` 的 class |
|---|---|---|
| ts-travel-service:1.0.0 | travel/service/TravelServiceImpl | TravelController、TravelServiceImpl |
| ts-order-service:1.0.1 | order/service/OrderServiceImpl | OrderController、OrderServiceImpl |
| ts-payment-service:1.0.2 | com/trainticket/service/PaymentServiceImpl | PaymentController、PaymentServiceImpl |
| ts-preserve-service:1.0.0 | preserve/service/PreserveServiceImpl | PreserveController、PreserveServiceImpl |
| ts-preserve-other-service:1.0.0 | preserveOther/service/PreserveOtherServiceImpl | PreserveOtherController、PreserveOtherServiceImpl |
| ts-train-service:1.0.0 | train/service/TrainServiceImpl | TrainController、TrainServiceImpl |
| ts-gateway-service:1.0.0 | （在 application.yml 里，不在 class 里） | 1 处 |

七个服务的模式高度一致：**都是 Controller + ServiceImpl 两个类同时被改，而且改动都伴随新增匿名内部类**
（TravelServiceImpl`$4`/`$5`、OrderServiceImpl`$2`、PaymentServiceImpl`$1`、PreserveServiceImpl`$8`、
PreserveOtherServiceImpl`$9`、TrainServiceImpl`$1`）。这些匿名内部类在上游编译产物里都不存在，
是典型的「新增了一段带回调或 lambda 的代码」的特征。

`ts-traceenv-test` 这个名字在上游 313886e9 的全仓里搜不到，也不在任何部署清单里——
**Nacos 里不会有这个服务的实例**，所以这些订阅在运行时必然得到空列表。

### 4.2 ts-travel-service 里到底植入了什么（已反编译核实）

本轮把 ts-travel-service:1.0.0 的 fat jar 层单独拉了下来
（`sha256:cee94c3e…`，73,585,634 字节，摘要与 manifest 一致），反编译了 `TravelServiceImpl.class`。
镜像里多出来一个上游**完全不存在**的私有方法（上游 `TravelServiceImpl.java` 里 `callTraceenvTest` 出现 0 次）：

```java
private void callTraceenvTest(HttpHeaders headers) {
    String url = System.getenv("TRACEENV_TEST_URL");
    if (url != null && !url.isEmpty()) {
        // 分支 A：自建 RestTemplate，连接超时 3000ms、读超时 3000ms
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(3000);
        f.setReadTimeout(3000);
        new RestTemplate(f).exchange(url + "/api/v1/traceenvtest/test", GET, entity, <$4>);
    } else {
        // 分支 B：走 Nacos 解析服务名，复用 this.restTemplate
        String url = getServiceUrl("ts-traceenv-test");
        this.restTemplate.exchange(url + "/api/v1/traceenvtest/test", GET, entity, <$5>);
    }
}   // 整个方法体被 catch (Exception) 包住（异常表：0–177 → 180, java/lang/Exception）
```

`TravelServiceImpl$4` 和 `$5` 就是这两个分支各自的 `ParameterizedTypeReference` 匿名内部类——
这解释了第 3 节里「镜像多出 `$4`、`$5`」的现象。

**调用点在主查询路径的第一行**。字节码显示它被两个方法在 offset 2（即方法体开头）调用：

| 调用方 | 对应入口 | 是否在压测路径上 |
|---|---|---|
| `queryByBatch(TripInfo, HttpHeaders)` | `POST /api/v1/travelservice/trips/left`（TravelController.java:113 → :123） | **是**，这是基准负载的主查询入口 |
| `create(TravelInfo, HttpHeaders)` | 创建车次 | 否 |

**部署时走的是分支 B**。`manifests/train-ticket/deployments.json` 里**没有任何服务**设置
`TRACEENV_TEST_URL`（ts-travel-service 的 env 只有 NODE_IP、6 个 OTEL_* 和 JAVA_TOOL_OPTIONS）。
所以实际执行的是：用**共享的 `@LoadBalanced` RestTemplate**（就是终稿 TT-11 说的那个
`builder.build()`——三种超时全无、每目标 5 条连接、整进程 10 条）
去调用一个**在 Nacos 里没有任何实例**的服务名。

### 4.3 性质判定

| 判定 | 结论 |
|---|---|
| 是否与上游一致 | **否**，已反编译核实：上游没有这个方法 |
| 是不是插桩残留 | **是**，方法名、URL 路径 `/api/v1/traceenvtest/test`、以及「有环境变量就用带超时的客户端」这套写法，都符合链路追踪实验代码的特征 |
| 是不是刻意植入的韧性故障 | **未核实**。没有 `Thread.sleep`、没有死循环，不像刻意的故障注入；但分支 B 复用无超时连接池这一点，效果上确实构成一个真实的故障放大器 |
| 是否影响审计结论 | **是**，见 4.4；并已据此在终稿新增一条 TT-41 |

**风险在于分支 B 与既有缺陷的叠加**：

- 正常情况下 Nacos 里没有 `ts-traceenv-test`，Ribbon 抛 `No instances available`，被 `catch (Exception)` 吞掉，
  快速失败，对延迟影响很小——这也是它在基线里没被发现的原因（本轮 search p95 只有 139 ms）。
- 但一旦 Nacos 返回了任何一个地址（终稿 TT-02 记录的「陈旧副本把死 IP 标成健康」正是这种情况），
  这个调用就会用**没有超时**的连接去打死 IP。按 `tcp_syn_retries=6`，单次连接最长挂约 127 秒，
  而且占用整进程仅有的 10 条连接之一（终稿 TT-11）。
- 它位于主查询路径的**第一行**，在任何业务逻辑之前执行。

换句话说，这段插桩代码把 TT-02 和 TT-11 串成了一条现成的放大链路，且入口就在 SLO 路径上。

### 4.4 对审计结论的影响

- **新增终稿条目 TT-41**，记录这段插桩代码本身。它不在 108 条静态候选里——静态审计依据的是上游源码，
  而上游根本没有这段代码，这正说明「只审源码不看镜像」会漏掉什么。
- **直接受影响的终稿条目**：`TT-21`（改签删单用 POST 打 @DeleteMapping，依赖 ts-order-service:1.0.1 的 OrderController）、
  `TT-22`（支付去重逻辑，依赖 ts-payment-service:1.0.2 的 PaymentServiceImpl 和 PaymentRepository）。
  这两条的关键 class 恰好都在「被改过」的清单里，因此终稿里都标注了「以上游为准，部署镜像上未核实」。
- **需要留意的条目**：凡是结论落在 preserve、preserve-other、travel、train、order、payment 这六个服务的
  ServiceImpl 上的，都要考虑运行的代码可能与上游不同。涉及 TT-11、TT-13、TT-16、TT-18、TT-19、TT-24。
- **另外五个含 traceenv 的服务尚未反编译**（order、payment、preserve、preserve-other、train）。
  它们的改动模式与 travel 一致（Controller + ServiceImpl 同时改、新增匿名内部类），
  **推测是同一套插桩，但未核实**。

### 4.5 怎么接着查

1. 另外五个服务重复本轮做法即可（每个约 70 MB）：取 amd64 manifest → 下最大的那个层 → 解包 → `javap -p -c`：
   ```
   TOK=$(curl -s "http://1.94.151.57:85/service/token?service=harbor-registry&scope=repository:train-ticket/<repo>:pull" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
   curl -H "Authorization: Bearer $TOK" "http://1.94.151.57:85/v2/train-ticket/<repo>/blobs/<layer digest>" -o layer.tar.gz
   ```
2. 更省事的办法是直接从运行中的 Pod 取（不走 Harbor）：`kubectl cp <pod>:/app/<service>.jar ./`。
3. 网关那一处最容易查，一条命令即可：
   `kubectl exec deploy/ts-gateway-service -- cat /app/BOOT-INF/classes/application.yml | grep -A3 traceenv`
   （注意 travel 的 `application.yml` 里**没有** traceenv，引用只在 class 里；网关恰好相反。）
4. 要成员级的完整字节码差异，在带宽较好的环境跑：
   `python3 diff_images.py --skip-inventory --upstream-compile --grep ts-traceenv-test --pair ts-travel-service:1.0.1:1.0.0`

---

## 5. 附带发现

- **1.0.0 标签被反复重推**。ts-travel-service 的 1.0.0 在 Harbor 上至少对应过 8 个不同的 manifest 摘要
  （见 `partial/summary.txt` 里以 `sha256:` 开头的那些比对行），其中两个摘要之间是 `identical layers`——
  同一份内容被重推了多次。全部 Deployment 都用可变标签，没有一个用摘要固定。
- **依赖 jar 也有变化**。每一对 tag 比对里都有 `libs: 1` 的变化，下钻到 `ts-common-0.1.0.jar` 后
  class 无变化（`nested jar class changes: []`），说明变的是 jar 的打包元数据而非代码。
- **运行时配置无差异**。所有比对的 `runtime config diffs` 都是空的，即镜像配置里的
  env、entrypoint、工作目录没有被改过——改动都在应用代码和 application.yml 里。
- **ts-avatar-service 的构建被改过**，把 4 条 `apt` 合并成一条带 fallback 的命令。这是构建修复的痕迹，
  与韧性无关，但说明这批镜像确实经过二次构建。

---

## 6. 结论

1. **46 个部署镜像里，23 个与上游源码完全一致**，这些服务的静态审计结论可以直接采信。
2. **18 个 Java 服务与上游不一致**，其中 11 个的标签仍然是 1.0.0——标签不能用来判断代码是否改过。
3. **7 个服务引用了上游不存在的 `ts-traceenv-test`**，改动模式高度一致（Controller + ServiceImpl 同时改，
   并新增匿名内部类）。这个服务在 Nacos 里没有实例，订阅必然得到空列表。
4. **改动的具体内容未核实**：本轮未能取得成员级的字节码差异，因此无法判断是插桩残留还是植入的故障。
   终稿中所有依赖这 6 个服务源码的条目都已标注「以上游为准，部署镜像上未核实」。
