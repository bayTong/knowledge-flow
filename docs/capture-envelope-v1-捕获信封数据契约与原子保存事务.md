# Capture Envelope v1：捕获信封数据契约与原子保存事务

> 状态：Approved Design；四个公开文本操作、C5V 与 C6A–C6C 恢复/迁移均已完成<br>
> 整理日期：2026-09-01<br>
> 确认日期：2026-09-01<br>
> 补充确认日期：2026-09-02<br>
> C3-0 补充确认日期：2026-09-08<br>
> C3 编码前收口日期：2026-09-09<br>
> C3A/C3B 完成日期：2026-09-10<br>
> C3C 完成日期：2026-09-11<br>
> C3V 完成日期：2026-09-11<br>
> 原子 Event 补充确认日期：2026-09-08<br>
> C4-0 读取契约完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> C4V 完成与远端同步日期：2026-09-14（提交 `1e38f2f` 已 push 至 `origin/main`）<br>
> C5-0 追加写入契约收口日期：2026-09-14（独立提交 `ea530ad`；2026-09-16 已 push 至 `origin/main`）<br>
> 最小 Windows CI 首次通过日期：2026-09-16（提交 `c4d2c7b`；远端运行 `35075692046`）<br>
> C5A/C5B/C5V 完成日期：2026-09-17（提交 `63a3250`、`ab2a613`、`a9913e2`；2026-09-18 已 push 至 `origin/main`）<br>
> C6A 业务事务崩溃恢复日期：2026-09-17（独立提交 `84ee1d7`；2026-09-18 已 push 至 `origin/main`）<br>
> C6B 派生状态重建日期：2026-09-17（独立提交 `f686941`；2026-09-18 已 push 至 `origin/main`）<br>
> C6C Store 迁移日期：2026-09-18（独立提交 `ea8f84e`；已 push 至 `origin/main`）<br>
> C6 远端门禁通过日期：2026-09-18（截至 `ea8f84e`；Windows CI 运行 `35319645501` 首次通过）<br>
> 适用范围：MVP-0 的文本捕获，以及未来 URL、文件 Payload 必须保持的身份与事务语义<br>
> 边界：本文定义完整数据和事务契约；四个公开操作及 C6A–C6C 已实现，C7A/C7B 已完成受限 CLI 协议、四操作分派与安装入口，C7V、C8 及本文其余远期能力尚未完成

## 0. 结论先行

Capture Envelope v1 采用以下实现决策：

1. **本地文件式 Capture Store 是捕获审计锚点。**
2. **GBrain 是异步未审核镜像、检索与派生处理层，不是唯一原件。**
3. 用户确认“保存成功”的必要条件，是本地不可变版本已经完成原子提交和哈希回读校验；不等待 GBrain、Git、embedding 或任何模型调用。
4. 每次主动保存产生独立 Capture Event；相同内容不能因为哈希相同而静默吞掉用户的第二次保存。
5. 同一 Capture Item 的修改通过新增版本表达，不允许覆盖旧版本。
6. 所有路由、策展和批准都绑定 `capture_id + version + envelope_sha256`，并保留全部 Payload 哈希；不能只绑定某个会变化的 GBrain 页面。

该决策来自对 GBrain `0.46.28.0` 源码快照的只读核对。原生 `capture` 能提供低摩擦文本摄入、数据库写入和搜索，但不能同时满足精确原件、独立事件身份、完整不可变版本、历史导出恢复、可靠重试和后台语义隔离六项要求。

## 1. 与其他文档的关系

本文细化以下文档中的捕获部分：

- [设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)
- [需求与治理基线](requirements-and-governance-baseline-需求与治理基线.md)
- [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md)
- [SOP-000A：临时知识库骨架初始化](sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md)

边界如下：

- 本文只回答“如何可靠保存一次捕获，以及如何证明保存的是哪一版”。
- 捕获属于哪个 KB、是否新建 KB，由捕获与路由规范处理。
- 长文如何生成策展地图，由 SOP-001 处理。
- 获批知识如何写入可信 wiki，由后续 SOP-002 约束。
- 本文不决定每个 KB 的 Git 拓扑，也不建立 KB 领域、标签、关系或 SCHEMA。

## 2. 设计目标

Capture Envelope v1 必须同时做到：

- 入口低摩擦：不知道 KB 归属也能立即保存。
- 原件可证明：保存内容可按字节或明确的渠道保真等级核验。
- 请求可重试：客户端超时或进程崩溃后，不会因重试产生不可控重复项。
- 主动重复不丢失：用户两次主动保存相同内容，可以保留两个不同事件。
- 修改不覆盖：旧版本永久保留，批准仍绑定原版本。
- 状态可恢复：索引、状态投影和 GBrain 镜像损坏时，可以从不可变记录重建。
- 热路径零模型：模型不可用不影响保存。
- 语义隔离：摘要、标签、关系、路由和提升结果不能写回原件。

## 3. 非目标

v1 不解决：

- 自动判断 KB 归属。
- 自动新建 KB。
- 自动把捕获提升为可信知识。
- 跨设备实时同步。
- 端到端加密和密钥托管。
- 大文件对象存储的最终选型。
- 物理 Payload 去重和垃圾回收。
- 通过 Capture Store 替代 Git、备份系统或业务状态机。

这些能力以后可以增加，但不得改变 v1 的身份、不可变版本和成功判定语义。

## 4. 核心对象模型

### 4.1 Capture Event

Capture Event 表示一次用户或入口发起的保存动作。

- 使用稳定 `event_id` 标识。
- 同一请求因网络超时而重试时，应返回同一个 Event。
- 用户再次主动点击“保存”或再次发送“记一下”时，即使内容完全相同，也可以产生新的 Event。
- Event 记录渠道、请求时间、幂等证据和授权证据。

### 4.2 Capture Item

Capture Item 是后续可被编辑、路由、归档或提升的逻辑对象。

- 使用稳定 `capture_id` 标识。
- 首次保存创建 Item 和版本 1。
- 对已有 Item 的显式编辑追加版本 2、3……
- 普通的新保存请求不得仅凭内容相同自动判断为“编辑已有 Item”。

MVP 默认一个创建 Event 对应一个新 Item。以后若需要“多个入口事件指向同一 Item”，必须通过显式合并提案完成，不能由哈希自动决定。

### 4.3 Capture Version

Capture Version 是某个 Capture Item 在一个时间点的不可变原始版本。

版本由以下三元组唯一确定：

```text
capture_id + version + envelope_sha256
```

其中：

- `version` 从 1 开始单调递增。
- 版本目录一旦原子提交，不得原地修改。
- 版本目录存在不单独证明版本已逻辑提交：版本 1 还必须有唯一匹配的 `capture.created`，版本 N>1 还必须有唯一匹配的 `capture.version-appended`；读取只承认由这些 Event 证明的连续前缀。
- 任何正文、附件、用户标题或用户意图的修改都产生新版本。
- 纯粹的 GBrain 同步状态、路由状态和备份状态变化不产生 Payload 新版本，而是追加状态事件。

### 4.4 Payload

Payload 是用户要求保存的原始对象。一个版本可以包含一个主 Payload 和零个或多个附件 Payload。

每个 Payload 使用完整 SHA256 作为内容身份：

```text
payload_id = sha256:<64位小写十六进制>
```

相同 Payload 可以在未来共享物理存储，但逻辑 Event、Item 和 Version 仍然分别保留。

一个版本还必须计算 `payload_set_sha256`，用于回答“这一版的整组输入是否相同”。它与单个 Payload 哈希不是一回事：主文本相同但附件不同，Payload Set 哈希也必须不同。规范输入字节见第 8.6 节。

### 4.5 Immutable Envelope

Immutable Envelope 是版本目录内的不可变机器清单，建议文件名为 `envelope.yaml`。

它记录：

- Item、Event 和 Version 身份。
- 原始 Payload 清单及哈希。
- 捕获时间和渠道来源。
- 用户明确表达的意图及授权证据。
- 前一版本引用。
- 需要异步执行的投递请求。

它不记录会持续变化的当前状态，例如 GBrain page ID、重试次数和当前路由结果。

### 4.6 State Projection

State Projection 是 Item 根目录下便于 UI 和脚本快速读取的当前状态投影，建议文件名为 `capture.yaml`。

它可以更新，但不是审计真源。投影损坏或丢失时，必须能从不可变版本与事件重建。

### 4.7 State Event

State Event 是状态变化的追加式记录，建议一个事件一个文件，不修改旧事件。

典型事件包括：

- `capture.created`
- `capture.version-appended`
- `gbrain.sync-requested`
- `gbrain.sync-succeeded`
- `gbrain.sync-failed`
- `route.proposed`
- `route.approved`
- `route.materialized`
- `capture.archived`

路由提案和 Route Record 仍由捕获与路由规范定义；Capture Event 只记录它们的引用，不复制全部语义内容。

State Event 不是运行日志。Event 具有稳定 schema 和 `event_id`，属于 Capture Store 的业务事实，用于审计和重建投影；运行日志只用于排障和运维，可以轮转或清理，不能参与身份、幂等或状态恢复。日志可以记录安全的 `event_id` 与错误码来关联 Event，但不得替代 Event，也不得记录正文、原始幂等键、凭据或敏感绝对路径。

### 4.8 Delivery Request 与 Outbox

Delivery Request 表示本地捕获成功后需要异步执行的机械投递，例如镜像到 GBrain。

投递请求随不可变版本一起提交，因此即使独立 outbox 索引丢失，也能通过扫描版本目录恢复待执行任务。

`outbox/` 只是加速调度的可重建投影，不是唯一任务真源。

## 5. 身份规范

### 5.1 ID 格式

v1 固定使用 UUIDv7，并增加类型前缀：

```text
capture_id: cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421
event_id:   evt_01991a7e-7b21-72ae-9ef5-4f45249ad332
store_id:   store_01991a7e-7b22-77df-a46b-b4af9597a0a1
job_id:     job_01991a7e-7b23-7eba-b6e4-0f4d5eb03862
```

约束：

- UUID 部分使用 48 位 Unix 毫秒时间、固定 version `7` 位和 RFC variant `10` 位；其余 74 位来自操作系统安全随机源。
- UUID 部分使用小写、带连字符的标准文本形式；完整 ID 分别使用 `cap_`、`evt_`、`store_`、`job_` 前缀。
- 一经分配不得重用。
- 同一毫秒内只要求唯一，不要求严格单调；不得增加跨进程共享计数器来制造绝对排序。
- 观察到的毫秒值严格增加时，UUID 时间部分应随之增加；但 ID 仍不能替代 `received_at`、`captured_at` 或事件时间。
- 系统时钟回拨时，不钳制时间、不伪造未来时间，也不维护持久化“最后时钟”；使用当次观察到的毫秒值和新的安全随机位生成合法、唯一的 UUIDv7。审计顺序以显式时间和版本/事件关系为准。
- ID 不从标题、正文、文件名或模型输出推导。
- 固定时钟和固定随机位只允许作为测试注入，不能从配置或生产入口开启。

### 5.2 版本号

- 新 Item 的首个版本固定为 `1`。
- 新版本只能是当前最大版本加一。
- 追加版本必须提供 `expected_current_version` 或等价的前一版本哈希。
- 当前版本不匹配时返回 `version_conflict`，不得覆盖或自动合并。
- v1 目录只表达 `000001..999999`；因此公开追加请求的 `expected_current_version` 只接受整数 `1..999998`，`bool` 无效。当前已为 `999999` 时返回 `invalid_input`，不分配越界版本。

### 5.3 幂等键

入口可提供 `idempotency_key`。C3 使用无歧义、带域前缀的规则：

```text
scope = <channel.type>:<channel.instance_id>:<operation>
key_sha256 = sha256("knowledgeflow.idempotency-key.v1\n" + utf8(idempotency_key))
idempotency_identity = (scope, key_sha256)
```

规则：

- `channel.type` 和 `channel.instance_id` 必须分别为 1–64 个小写 ASCII 字母、数字、点、下划线或连字符，不允许冒号、斜杠、反斜杠、空白或换行；`operation` 来自固定枚举，因此 scope 分段无歧义。
- `capture_text` 可以省略 `idempotency_key`；`append_capture_version` 必须提供。提供时必须是非空字符串，UTF-8 编码不超过 512 bytes。
- 同一作用域、同一幂等身份且请求指纹相同，必须验证最终不可变 Envelope、Payload 与 Event 后，返回原 `event_id + capture_id + version` 以及相同的 Payload/Envelope 哈希字段。
- 同一幂等键若对应不同请求指纹，即使 Payload 字节相同但明确用户意图不同，也返回 `idempotency_conflict`，不能静默采用任一请求。
- 原始幂等键默认不落盘，只保存哈希；外部消息 ID 如需审计，单独存放在来源字段中。
- 只有 `capture_text` 在入口不提供幂等键时，才把每次请求按新的主动保存处理；追加不允许进入这个分支。
- 内容哈希不是幂等键，不能单独用来吞掉 Capture Event。

成功回执中的 `warnings` 是当前派生状态，不属于幂等身份。幂等命中时只读检查 `capture.yaml`：投影有效则返回空警告，投影缺失、损坏或不一致则返回 `projection_needs_rebuild`；C3 不在该路径自动重建投影。不可变原件验证失败时必须返回完整性错误，不能仅凭幂等字段返回成功。

`idempotency.key_sha256` 是按上述带域前缀规则生成的单向键摘要，目的只是避免落盘原始幂等键。幂等身份由 `scope + key_sha256` 二元组表达；它不描述 Payload、整包输入、请求内容或 Envelope，因此不计入第 8.6 节的四类核心哈希。

## 6. 原件保真等级

“保存原文”必须说明保真的边界，不能笼统声称所有渠道都能恢复网络层原始字节。

### 6.1 `byte-exact`

适用于文件、音频、图片、PDF 和入口直接提供的字节流。

- 原样复制字节。
- 不改编码、换行、文件头、压缩方式或元数据块。
- SHA256 对原始字节计算。

### 6.2 `channel-exact`

适用于入口已经解码成字符串的文本消息，或经严格 UTF-8 增量校验的二进制文本流。

- 字符串精确保留渠道 API 交付给 KnowledgeFlow 的字符序列；字节流精确保留通过严格 UTF-8 校验的输入字节。
- 以 UTF-8、无 BOM 的方式写入 Payload 文件。
- 输入开头的 UTF-8 BOM 或字符串 `U+FEFF` 拒绝，不静默删除。
- 不做 Unicode 规范化、trim、换行转换或自动补标题。
- 不能声称恢复渠道在解码前的网络字节。

### 6.3 `canonical-snapshot`

适用于会话片段等必须结构化保存的对象。

- 使用规定的确定性序列化格式保存消息顺序、角色、消息 ID 和原文。
- 原平台导出文件若可取得，应另外作为 `byte-exact` 附件保存。
- 规范化结构是捕获快照，不伪装成平台原始数据库或网络报文。

### 6.4 `reference-only`

适用于只保存 URL、外部对象 ID 或暂时无法复制的大文件。

- 只证明“在该时间保存了这个引用”。
- 不证明引用目标内容以后不会变化。
- URL 抓取内容必须作为新的 Snapshot Payload 或派生结果保存，不能覆盖 URL 原串。
- MVP 中，普通本地文件不能仅存路径并报告为耐久成功；必须复制字节，或明确返回不支持。

## 7. 推荐物理布局

本文使用 `<capture-root>` 表示配置确定的 Capture Store 根目录。它应位于独立的全局捕获数据区，而不是任一领域 KB；Global Intake 只是查询视图，不是这里的物理目录。当前机器的路径建议见 [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)，Git 拓扑仍可后置决定。

```text
<capture-root>/
├── items/
│   └── YYYY/
│       └── MM/
│           └── <capture-id>/
│               ├── capture.yaml
│               ├── versions/
│               │   ├── 000001/
│               │   │   ├── envelope.yaml
│               │   │   └── payloads/
│               │   │       ├── primary.txt
│               │   │       └── attachment-001.bin
│               │   └── 000002/
│               │       ├── envelope.yaml
│               │       └── payloads/
│               └── events/
│                   ├── <event-id>.yaml
│                   └── <event-id>.yaml
├── outbox/
│   ├── pending/
│   ├── running/
│   ├── failed/
│   └── completed/
├── indexes/
│   └── idempotency/
├── .staging/
└── journal/
```

说明：

- `versions/000001/` 整个目录不可变。
- `capture.yaml` 是当前状态投影，使用临时文件加原子替换更新。
- `events/` 只追加，不改旧文件。
- `outbox/` 和 `indexes/` 均可重建，不能成为唯一审计记录。
- `.staging/` 只能位于与 `items/` 相同的文件系统，以便使用原子 rename。
- `capture.yaml`、`envelope.yaml`、`events/` 等机器契约名称是“英文名-中文名”文件命名规则的明确例外。

## 8. Immutable Envelope v1 字段

### 8.1 示例

```yaml
schema: "knowledgeflow.capture-envelope"
schema_version: 1

capture_id: "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
event_id: "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332"
version: 1
previous_version: null

received_at: "2026-09-01T02:10:12.123Z"
captured_at: "2026-09-01T02:10:12.456Z"

actor:
  type: "user"
  actor_id: "local-user"

channel:
  type: "app"
  instance_id: "local-desktop"
  external_ref: null
  source_created_at: null

idempotency:
  scope: "app:local-desktop:capture_text"
  key_sha256: "sha256:<64位小写十六进制>"
  request_fingerprint_sha256: "sha256:<本次不可变请求指纹>"

payloads:
  - payload_id: "sha256:<64位小写十六进制>"
    ordinal: 0
    role: "primary"
    kind: "text"
    path: "payloads/primary.txt"
    original_name: null
    media_type: "text/plain; charset=utf-8"
    encoding: "utf-8"
    fidelity: "channel-exact"
    byte_size: 42
    sha256: "sha256:<64位小写十六进制>"

payload_set_sha256: "sha256:<整组 Payload 规范化摘要>"

user_intent:
  target_kb_id: null
  processing_mode: null
  requested_new_kb_name: null
  evidence:
    event_id: "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332"
    payload_id: "sha256:<64位小写十六进制>"

delivery_requests: []

envelope_serialization:
  encoding: "utf-8"
  line_endings: "lf"
  bom: false
  key_order: "schema-defined"

envelope_sha256: "sha256:<除本字段外的规范化 envelope.yaml 字节哈希>"
```

### 8.2 必填字段

Envelope 顶层采用“字段存在，但值可以按 schema 为 `null`”的方式消除不同实现的省略差异。第 8.1 节展示的全部顶层字段均必须存在；其中 `previous_version` 和 `idempotency` 可以为 `null`，`delivery_requests` 在 MVP-0 固定为空数组。

以下核心字段或嵌套值缺失时，版本不得提交：

- `schema`
- `schema_version`
- `capture_id`
- `event_id`
- `version`
- `previous_version`
- `received_at`
- `captured_at`
- `actor`
- `channel`
- `idempotency`
- 至少一个 `payloads[]`
- 每个 Payload 的 `payload_id + ordinal + role + kind + path + original_name + media_type + encoding + fidelity + byte_size + sha256`
- `payload_set_sha256`
- `user_intent`
- `delivery_requests`
- `envelope_serialization`
- `envelope_sha256`

`user_intent` 必须存在，但其值可以全部为 `null`，从而明确表达“用户没有指定”，而不是“字段遗漏”。

不存在幂等键时，`idempotency` 为 `null`；存在时，`scope + key_sha256 + request_fingerprint_sha256` 均必须存在。请求指纹的精确字段和字节规则见第 8.6 节。

### 8.3 时间语义

- `received_at`：KnowledgeFlow 开始接收请求的服务端 UTC 时间。
- `captured_at`：服务端在生成最终 Envelope、准备提交该版本时固定的 UTC 记录时间。
- `capture.created.occurred_at`：在创建 Event 写入 staging、最终 flush 与原子 rename 前固定，表示本次创建事件的逻辑发生时间；Event 只有随整个 Item rename 成功后才成为正式可见事实。它不宣称是底层文件系统完成 rename 的精确物理时刻。
- 渠道提供的消息时间另存为 `channel.source_created_at`，不得冒充本地捕获时间。
- 核心生成的机器时间固定为带 `Z`、毫秒精度的 UTC：`YYYY-MM-DDTHH:MM:SS.mmmZ`；UI 可以按用户时区展示。
- `channel.source_created_at` 可以为 `null`；非空时必须已经符合上述规范 UTC 格式，C3 不猜测时区或静默改写时间。
- MVP-0 是单用户本地模式，核心固定写入 `actor.type: user` 与 `actor_id: local-user`；普通请求不能覆盖可信 actor。多用户或远程身份必须通过后续独立可信身份上下文设计。
- `channel.external_ref` 可以为 `null`；非空时 UTF-8 编码不超过 2048 bytes，只作为来源证据并参与 Request Fingerprint，不参与路径生成。

### 8.4 用户意图边界

`user_intent` 只能记录用户明确表达的内容：

- 用户明确说出已有 KB，才写 `target_kb_id`。
- 用户明确要求深度整理，才写 `processing_mode: deep-curation`。该值只表示用户允许进入较深语义处理，不承诺固定的 SOP、完整策展地图或语义零遗漏；实际处理策略属于后续可重建的派生决定，当前 Profile 工作名称、默认映射和路由规则仍为 Draft，必须经对应门禁批准。
- 用户明确要求创建一个给定名称的新 KB，才写 `requested_new_kb_name`。
- 模型猜测、历史习惯和相似度结果不得写进 `user_intent`。
- 模型建议必须进入 Route Proposal，并引用该版本哈希。

### 8.5 Envelope 规范化与哈希

为避免同一份数据因 YAML 发射器、换行或字段顺序变化产生不同结果，Envelope 必须通过第 8.7 节的受限 YAML codec 规范化。`envelope_sha256` 的精确计算步骤见第 8.6 节。

第 8.1 节示例为了阅读留有空行，不是 golden fixture，也不是可以直接参与哈希的规范字节。

### 8.6 四类核心 SHA256

前文曾把这一组误称为“三类哈希”；按实际用途和字段应为**四类核心哈希**。可以把它们理解为从里到外的四枚防篡改封条：

| 层级 | 字段 | 它回答的问题 | 不负责什么 |
|---|---|---|---|
| 单个原件 | `payloads[].sha256` / `payload_id` | 这一份正文或附件的精确字节变了吗？ | 不代表附件集合、用户意图或整个版本 |
| 整包输入 | `payload_set_sha256` | 这一版收到的正文与全部附件组合变了吗？ | 不代表来源、操作或用户意图 |
| 一次请求 | `request_fingerprint_sha256` | 同一幂等键重试的是否真是同一个请求？ | 不作为 Capture ID，也不用于内容去重 |
| 完整版本记录 | `envelope_sha256` | 这个不可变版本的身份、来源、意图和 Payload 清单变了吗？ | 不证明由谁批准，也不是数字签名 |

四类输出都使用 `sha256:<64 位小写十六进制>`。SHA256 在这里用于完整性和确定性身份比较，不用于加密正文、判断语义相似或证明操作者身份。

#### A. Payload SHA256

对实际保存的每个 Payload 的**精确字节序列**直接计算 SHA256；不先统一换行、Unicode、编码或空白：

```text
payload_sha256 = "sha256:" + lower_hex(SHA256(exact_stored_bytes))
payload_id = payload_sha256
```

写入 staging 后必须从 staging 文件流式回读并重新计算；不能信任调用方声明，也不能只使用写入前的候选哈希。

#### B. Payload Set SHA256

1. 按 `ordinal` 升序排列所有 Payload，且 `ordinal` 必须唯一。
2. 每项只保留以下字段，并按此固定键顺序生成 JSON 对象：`ordinal`、`role`、`kind`、`media_type`、`byte_size`、`sha256`。
3. 生成一个 JSON 数组。JSON 使用 UTF-8、无 BOM、无缩进和多余空白、无尾随换行；字符串中的非 ASCII 字符直接使用 UTF-8，只转义 JSON 语法必须转义的字符。
4. 对下面两段字节直接连接后的结果计算 SHA256：

```text
UTF8("knowledgeflow.payload-set.v1\n")
+ compact_json_bytes
```

固定前缀用于区分哈希用途，避免相同字节在不同对象类型中被误当成同一种身份。

#### C. Request Fingerprint SHA256

MVP-0 两个写操作先构造以下固定键顺序的 JSON 对象；所有可选值都必须显式写为 `null`，不能因调用语言不同而省略：

```json
{"operation":"capture_text","payload_set_sha256":"sha256:...","channel":{"type":"app","instance_id":"local-desktop","external_ref":null,"source_created_at":null},"payload_metadata":[{"ordinal":0,"original_name":null}],"user_intent":{"target_kb_id":null,"processing_mode":null,"requested_new_kb_name":null},"capture_id":null,"expected_current_version":null}
```

```json
{"operation":"append_capture_version","payload_set_sha256":"sha256:...","channel":{"type":"app","instance_id":"local-desktop","external_ref":null,"source_created_at":null},"payload_metadata":[{"ordinal":0,"original_name":null}],"user_intent":{"target_kb_id":null,"processing_mode":null,"requested_new_kb_name":null},"capture_id":"cap_...","expected_current_version":1}
```

- `operation` 只能是 `capture_text` 或 `append_capture_version`。
- `payload_metadata` 按 `ordinal` 升序；文本入口的 `original_name` 固定为 `null`。
- `capture_text` 的 `capture_id` 与 `expected_current_version` 固定为 `null`。
- `append_capture_version` 必须填入调用方提交的 `capture_id` 与 `expected_current_version`。
- 不包含原始幂等键、新分配的 ID、服务端时间、Store 路径、模型输出或任何随后产生的状态。

JSON 字节规则与 Payload Set 相同。计算输入为：

```text
UTF8("knowledgeflow.request-fingerprint.v1\n")
+ compact_json_bytes
```

因此，同一幂等键配合同一请求会命中原 Item/Version/Event 和相同核心哈希；正文、附件、来源元数据、明确用户意图或追加基线任一变化都会形成不同指纹并返回 `idempotency_conflict`。回执警告仍按命中时的当前投影事实生成。

#### D. Envelope SHA256

1. 构造完整 Envelope。
2. 删除顶层 `envelope_sha256` 字段本身，而不是把值改成空字符串或 `null`。
3. 按第 8.7 节规则发射规范 YAML 字节。
4. 直接对这份规范 YAML 字节计算 SHA256，不增加领域前缀。
5. 将结果写回 `envelope_sha256`，再次按相同规则发射最终 `envelope.yaml`。

验证时执行相反过程：先通过语法门禁和 schema 校验，再移除该字段、重新规范发射并比较哈希；最终文件本身也必须符合规范发射格式。

### 8.7 受限 YAML codec：语法门禁、schema 校验与确定性发射

PyYAML 只负责扫描和解析 YAML 基础结构，不能把它的默认行为当成 KnowledgeFlow 契约。受限 codec 分为两个连续关卡：

1. **语法门禁**回答“这是不是允许进入系统的安全 YAML 子集”。只允许单个 YAML 文档、mapping、sequence，以及 string、integer、boolean、null 四种标量；mapping 的 key 必须是字符串。拒绝 float、时间对象、binary、重复 key、anchor、alias、显式 tag、merge key `<<`、多文档和非字符串 key。
2. **schema 校验**回答“这是不是当前文件类型所要求的正确数据”。它按 `schema + schema_version` 检查必填/可选字段、嵌套结构、字段类型、枚举、是否允许 `null`、数组顺序约束和未知字段。MVP 对未知字段和未知 schema 版本一律拒绝；未来扩展必须提升版本并提供明确迁移。

两者不能互相替代。例如，`version: "one"` 是安全 YAML，能通过语法门禁，但不符合 Envelope 对整数版本号的 schema；带 anchor 的文档即使展开后字段看起来正确，也在 schema 校验前被语法门禁拒绝。

规范发射固定为：

- UTF-8、无 BOM、LF 换行、2 空格缩进、block style。
- key 按各 schema 声明的顺序输出；schema key 使用固定的普通字符串形式。
- 所有字符串值使用双引号；`null`、`true`、`false` 使用小写；整数使用无前导 `+` 和无多余前导零的十进制。
- 不输出注释、anchor、alias、tag、YAML 文档起止标记或空行。
- 文件结尾恰好一个 LF。

UUID、ISO-8601 时间和 `sha256:...` 均按普通字符串处理，不能让 YAML 隐式转换为其他类型。读取需要参与完整性判断的机器文件时，除数据通过两个关卡外，还必须与重新发射的规范字节一致。

Envelope v1 顶层键顺序固定为：`schema`、`schema_version`、`capture_id`、`event_id`、`version`、`previous_version`、`received_at`、`captured_at`、`actor`、`channel`、`idempotency`、`payloads`、`payload_set_sha256`、`user_intent`、`delivery_requests`、`envelope_serialization`、`envelope_sha256`。各嵌套 mapping 的键顺序固定为第 8.1 节展示顺序；没有值时按 schema 写 `null` 或空数组，不能删键改变规范字节。

## 9. State Projection v1

### 9.1 示例

```yaml
schema: "knowledgeflow.capture-state"
schema_version: 1

capture_id: "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
current_version: 1
current_envelope_sha256: "sha256:<hash>"

durability:
  status: "durable"
  verified_at: "2026-09-01T02:10:12.456Z"

routing:
  status: "unassigned"
  target_kb_ids: []

trust:
  status: "unreviewed-capture"

gbrain:
  sync_status: "not-requested"
  source_id: null
  page_slug: null
  mirrored_version: null
  mirrored_envelope_sha256: null

backup:
  git_status: "uncommitted"
  commit: null
  remote_status: "not-requested"

updated_at: "2026-09-01T02:10:12.456Z"
```

### 9.2 投影规则

- 投影只反映当前状态，不作为批准或审计依据。
- 每次更新使用“写临时文件—flush—原子替换”。
- 投影中的版本和哈希必须能在不可变版本目录中找到。
- 投影与事件不一致时，以不可变版本和追加事件为准，投影标记 `needs-rebuild` 后重建。
- `current_version` 与 `current_envelope_sha256` 只能指向最高连续已提交版本；不得因为发现更高版本目录而提前推进。C5A 把同一 `capture-state` v1 的 `current_version` 从初始专用值 `1` 向后兼容地泛化为整数 `1..999999`，不提升 schema version、不改变现有版本 1 golden 字节。
- 对 C5 新写的追加投影，`updated_at` 取当前版本唯一匹配版本建立 Event 的 `occurred_at`；`durability.verified_at` 取该版本/Event 最终回读通过后、写投影前的独立规范 UTC 样本，两者不要求相等，且不得把较晚的投影验证时间伪装成业务 Event 时间。现有 C3 初始投影继续使用兼容分支：`current_version == 1` 时要求两个字段相等，其既有 golden 字节不变，即使该时间晚于创建 Event。
- C5A 将 `validate/dump/load_capture_state` 的 Event 交叉验证参数设计为向后兼容的可选关键字：版本 1 调用不新增必填参数并保持原校验；`current_version > 1` 时必须同时提供当前追加 Event 和前一 Envelope，复用严格 Event 引用校验，并要求 `updated_at == current_event.occurred_at`。不得简单删除旧相等校验后让任意投影时间通过。C4 返回值仍从不可变 Event 内存重建，不信任投影时间。
- GBrain page ID、Git commit 和错误次数等异步信息只能进入投影或事件，不能回写旧 Envelope。
- C3 初始投影固定使用第 9.1 节的完整字段和值域：`durable`、`unassigned`、`unreviewed-capture`、`not-requested` 与 `uncommitted`；此时不执行路由、GBrain 或 Git。
- `capture.yaml` 使用受限 YAML、严格 `knowledgeflow.capture-state` v1 schema 和 schema-defined 字段顺序。缺失或损坏只产生重建需求，不代表不可变原件丢失。

### 9.3 `capture.created` State Event v1

C3 冻结创建事件；C4-0 仍保持其字节和字段不变：

```yaml
schema: "knowledgeflow.capture-event"
schema_version: 1
event_id: "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332"
event_type: "capture.created"
capture_id: "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
version: 1
envelope_sha256: "sha256:<64位小写十六进制>"
occurred_at: "2026-09-08T00:00:00.000Z"
actor:
  type: "user"
  actor_id: "local-user"
```

固定规则：

- 路径是所属 Item 下的 `events/<event-id>.yaml`，一个 Event 一个文件，只追加、不覆盖。
- 使用受限 YAML、严格 `knowledgeflow.capture-event` v1 schema、上述字段顺序和规范发射。
- `event_id`、actor 必须与 Envelope 一致；`capture_id + version + envelope_sha256` 必须指向同一 staging Item 内已经回读验证通过的版本。
- `occurred_at` 在最终 flush 与 rename 前写入；Event 与版本一起提交。Event 写入、schema 或交叉引用失败时不得提交 Item，不能在提交后再猜测原始时间。
- 同一事件文件重试时，规范字节完全一致才视为幂等；内容不同则报告完整性或身份冲突，不能覆盖。
- Event 是持久业务历史；运行日志可以引用其 `event_id`，但不能替代、重建或删除 Event。

### 9.4 `capture.version-appended` State Event v1

C4-0 为读取侧和未来 C5 冻结最小追加事件；C5-0 继续冻结 writer 的复用边界，但不在契约批实现 writer：

```yaml
schema: "knowledgeflow.capture-event"
schema_version: 1
event_id: "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332"
event_type: "capture.version-appended"
capture_id: "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
version: 2
previous_version: 1
previous_envelope_sha256: "sha256:<版本 1 Envelope 哈希>"
envelope_sha256: "sha256:<版本 2 Envelope 哈希>"
occurred_at: "2026-09-13T00:00:00.000Z"
actor:
  type: "user"
  actor_id: "local-user"
```

固定规则：

- 使用同一 `knowledgeflow.capture-event` v1 schema；`event_type` 决定严格字段集合和 schema-defined 键序，创建事件不得混入追加字段，追加事件不得省略上述字段。
- `version` 必须是 `2..999999`，`previous_version` 必须严格等于 `version - 1`；两者都是整数，boolean 无效。
- `event_id` 与新 Envelope 一致；`capture_id`、actor、`version`、`previous_version` 必须分别与新 Envelope 的对应字段一致。
- `previous_envelope_sha256` 必须等于前一已提交版本 Envelope 的自哈希；`envelope_sha256` 必须等于新版本 Envelope 的自哈希。这样 Event 同时封住版本链两端，而 Envelope v1 的 `previous_version` 继续只保存整数 N-1，不增加未定义字段。
- 每个版本恰好一个版本建立 Event。同一 Item 中重复、孤立或交叉引用矛盾的创建/追加 Event 均是完整性失败，不按“最新文件获胜”。
- 追加 Event 必须以目标不存在的无覆盖提交进入 `events/<event-id>.yaml`；它的最终提交是版本 N>1 的逻辑提交点。Event 进入最终路径之前，即使版本目录已经存在，也不得被读取、投影或列表视为新版本。
- 读取遇到不支持的 Event schema/schema version 返回 `unsupported_store_version`；已知 schema 的非法字段、非规范字节或引用矛盾返回 `integrity_check_failed`。
- C5 writer 必须调用同一严格 schema、规范发射和 `dump/load_capture_event` 引用校验能力，不得复制或放宽一套只写不读的 Event schema。首次新写时 Event 与新 Envelope 在事务 staging 内预封存；若同 key 重试接管一个完全可证明的唯一 N+1 尾部，可以从该不可变 Envelope 的 `event_id`、actor、版本和前后哈希重建 Event，并在本次真正逻辑提交前采样新的规范 `occurred_at`。未提交 staging Event 的时间不构成持久事实。

## 10. 创建捕获的原子事务

### 10.1 输入

最小输入：

- 一个或多个 Payload 字节/字符串；C3 文本允许 Python `str` 或提供 `read(size)` 的二进制 UTF-8 流，两者共享同一个有界分块写入器。
- 渠道信息。
- 可选 `idempotency_key`。
- 可选、但必须来自用户明确表达的 `user_intent`。

以下内容不是热路径前置条件：

- KB 领域判断。
- 模型标题、摘要或标签。
- GBrain 可用性。
- Git commit 或 push。
- embedding。

### 10.2 C3 创建事务步骤

```text
T0 校验机械元数据，建立本事务独占 staging
  -> T1 单次流式写入正文，严格校验 UTF-8、大小并计算候选哈希
  -> T2 生成 Payload Set 与 Request Fingerprint
  -> T3 获取 Store 级 Windows 内核写锁
  -> T4 扫描不可变 Envelope，执行幂等命中或冲突判断
  -> T5 分配 capture_id/event_id，构造包含创建 Event 的完整 staging Item
  -> T6 写入并封存 Envelope 与 capture.created，flush、回读和复算哈希/引用
  -> T7 将完整 Item 原子 rename 到最终 <capture-id> 目录并回读版本与 Event
  -> T8 原子写 capture.yaml；投影失败只产生 repair warning
  -> T9 释放内核锁，返回结构化回执
```

#### T0–T2：机械校验、单次 staging 与请求指纹

- staging 必须由本事务建立所有权标记，并与 `items/` 位于同一文件系统。
- `str` 按 UTF-8 分块编码；二进制流按严格 UTF-8 增量校验，不要求 seek 或重复读取。
- 空文本、BOM、非法 UTF-8 和超过配置安全上限分别按操作契约拒绝；只含空白的非空文本允许保存。
- 写入过程中同步计算候选 Payload 哈希；Request Fingerprint 形成后才能进行幂等判断。最终成功仍必须依据 staging 与最终文件的磁盘回读结果，不能只信任入口或候选哈希。
- 允许机械检查类型、大小、路径与编码；禁止判断内容价值、自动改标题、修正文风、清洗观点或因模型分类失败而拒绝捕获。

#### T3：Store 级写锁

- 固定锁文件为 `<capture-root>/journal/capture-write.lock`，复用 C2 已验证的 Windows 内核排他锁。
- 默认最多等待 10 秒；超时返回可重试的 `capture_store_unavailable + commit_state: not-committed`。
- 锁文件可以长期存在，文件存在不表示当前持锁。进程退出或崩溃后由操作系统释放内核锁；不得按文件年龄、PID 或存在性删除所谓陈旧锁。
- C3 先采用一个 Store 级写锁并持有到提交后投影 T8 尝试结束；细粒度锁和并行优化留到后续批次。

#### T4：幂等查询

- C3 在写锁内扫描不可变 Envelope；不创建新的幂等索引磁盘格式。
- 同一幂等身份和请求指纹命中已提交版本时，从最终路径验证 Envelope、Payload 与创建 Event，随后只读检查 `capture.yaml`，安全清理本事务拥有的未提交 staging，并返回原稳定身份/哈希字段及当前投影警告；不得在 C3 幂等命中路径静默重建投影。
- 同一幂等身份但请求指纹不同，返回 `idempotency_conflict`；不得覆盖或产生第二个 Item。
- 没有幂等键时，每次调用都是新的主动保存。

#### T5–T6：身份、Envelope、Event 与提交前验证

- 幂等未命中后分配 UUIDv7 `event_id` 和 `capture_id`；目录分片年月来自服务端 `received_at`。
- 在 staging 中构造完整 Item shell：版本下的 `envelope.yaml`、`payloads/primary.txt`，以及 Item 下的 `events/<event-id>.yaml`。
- 记录实际 `byte_size` 与哈希，生成规范 Envelope；MVP-0 的 `delivery_requests` 固定为空。
- 在最终提交前生成规范 UTC `occurred_at`，写入第 9.3 节的 `capture.created`；其 `event_id`、actor 和版本三元组必须与 Envelope 严格一致。
- flush Payload、Envelope 与 Event，并从 staging 磁盘重新读取，复算大小、全部哈希和交叉引用；任一不一致不得进入提交。

#### T7：原子提交完整新 Item

- `items/YYYY/MM/` 可以机械创建；年月目录不是 Capture Item，只有最终 `<capture-id>/` 表示可见 Item。
- 使用同盘、目标不得已存在的原子 rename，把完整 staging `item/` 移动到 `items/YYYY/MM/<capture-id>/`，不提前在最终区域创建 `<capture-id>/versions/` 半成品。
- 新分配 ID 的最终 `<capture-id>` 已存在时不得覆盖、采用或冒认为本请求；可以证明 staging 未提交时返回可重试 `atomic_commit_failed + commit_state: not-committed`。
- rename 后 `versions/000001/` 与已提交 Event 均不可变；在平台允许时 flush 最终父目录元数据，并从最终路径回读 Envelope、Payload 与 Event。
- 只有可以证明最终版本和匹配的创建 Event 同时存在且通过校验时才进入 `committed`；rename 前失败为 `not-committed`，rename 附近无法判断时为 `unknown`。

#### T8：状态投影

- 最终版本和创建 Event 回读成功后，原子写入第 9.1 节的 `capture.yaml`。
- 投影失败时，已提交版本与 Event 可以重建它；返回成功加 `projection_needs_rebuild` 警告，不修改或撤销版本/Event。
- C3 没有 Delivery Request，不生成 outbox job；未来 outbox 仍是从 Envelope 可重建的提交后投影。

#### T9：释放与回执

只有 T7 成功且最终版本、Envelope、Payload 与创建 Event 回读校验通过，才能返回 `saved: true`。实现只能清理由本事务明确拥有且尚未提交的 staging，不能按模糊名称或文件年龄删除其他进程的目录。

调用方可见的 C3 成功回执固定为：

```yaml
ok: true
saved: true
commit_state: "committed"
capture_id: "cap_..."
event_id: "evt_..."
version: 1
primary_payload_sha256: "sha256:..."
payload_set_sha256: "sha256:..."
envelope_sha256: "sha256:..."
durability: "durable"
routing_status: "unassigned"
trust_status: "unreviewed-capture"
gbrain_sync_status: "not-requested"
warnings: []
```

该形状以 MVP-0 操作契约第 4.3 节为公共接口权威，不增加固定为 `1` 的冗余 `payload_count`。幂等重试保持身份、版本和哈希字段不变；`warnings` 按重试时的当前投影事实生成。回执不得等待模型、GBrain、Git commit、push 或 embedding。

## 11. 追加新版本的原子事务

调用方必须提供：

- `capture_id`
- `expected_current_version`
- 新 Payload
- 必填的 `idempotency_key`
- 可省略并归一化为全 `null` 的 `user_intent`

MVP-0 的 C5 复用现有 Store 级 Windows 内核写锁，不提前引入细粒度 Item 锁、数据库或持久幂等索引。正文先在锁外有界写入本事务 staging，回读形成 Payload Set、Request Fingerprint 和幂等身份；进入不可变扫描后持锁，直到 Event 提交后的最终回读与投影更新尝试结束。

追加 staging 不复用 C3 的完整 `item/versions/000001` 候选，而使用可直接提交单一版本目录与单一 Event 的固定树：

```text
.staging/<transaction-id>/
├── active.lock
├── transaction.yaml
├── version/
│   ├── envelope.yaml
│   └── payloads/primary.txt
└── events/<event-id>.yaml
```

内部事务 marker 继续使用 `knowledgeflow.capture-transaction` v1 的四字段规范形状；C5A 只增加 `operation: "append_capture_version"`，不改变已有 `capture_text` marker 字节。C6A 在事务根创建后先创建并持续持有空 `active.lock` 的 Windows 内核字节锁，再写 marker 与内容；租约只证明事务进程仍存活，文件存在本身不等于锁仍被持有。清理按 marker operation 选择互不混用的固定允许树，并校验事务根/marker/lease 与每个对象身份、普通对象类型、非 reparse 与 root 包含关系。提交导致 `version/` 或 Event 文件缺失是允许的部分树；未知额外对象或身份变化必须拒绝清理。清理只触及已证明归属的 staging，先删内容，再释放并删除租约，marker 最后删除，不能枚举、采用或删除最终 Item 尾部。

逻辑提交顺序固定为：

1. 在写锁内扫描全部唯一规范 Item、已提交版本/Envelope/版本建立 Event，以及每个 Item 至多一个无 Event 的 N+1 尾部；已提交结构、规范字节、引用或受支持版本任一无法可靠判断时失败关闭。尾部允许尚未写全，其已知缺失/部分机器字节本身不污染已提交链。普通扫描不全量重哈希 Store 中每份历史正文；对幂等命中的版本、可接管尾部以及目标 Item 当前基线必须完成其全部 Payload attestation。
2. 先按 `scope + key_sha256` 解析幂等：同身份、同指纹的已提交版本经最终验证后返回原稳定回执，即使目标 Item 当前已超过请求中的 expected；同身份、不同指纹返回 `idempotency_conflict`。唯一尾部只有规范、可读、自哈希有效且绑定其 Item/版本的 Envelope 才贡献未提交身份；同身份同指纹只命中尾部时记录候选并继续目标/CAS/完整采用证明，绝不直接返回成功。已知缺失/部分/非规范尾部不保留全 Store key，I/O 导致身份事实不可判断则在写最终对象前返回 `capture_store_unavailable + not-committed`。该顺序必须先于目标查找和 CAS。
3. 幂等未命中后定位唯一 `capture_id`，验证 Event 证明的连续已提交前缀，并以该前缀的 N 比较 `expected_current_version`；投影、最高目录名和目录时间不能代替该判定。
4. 若目标存在唯一无 Event 的 N+1 尾部，只有其普通目录身份、完整 Payload/Envelope、前一版本绑定、幂等身份和请求指纹都与本请求完全一致时才采用；仅在步骤 2 读取到身份不等于完成采用证明。采用时保留既有 N+1、`event_id` 和 Envelope，丢弃本次未提交版本候选并直接进入 Event 预封存。其他目标尾部不采用、不覆盖、不删除，返回 `atomic_commit_failed + not-committed`，通用隔离留给 C6。
5. 无可采用尾部时分配新 `event_id`，令新版本为 N+1。新 Envelope 的 `previous_version` 只写整数 N；第 9.4 节 Event 写入 `previous_version: N`、前一 Envelope 哈希和新 Envelope 哈希。
6. 在 staging 中写完整新版本和规范追加 Event；flush 并回读验证全部新 Payload、Payload Set、Envelope 自哈希、Event schema 及前后版本交叉引用。
7. 以目标不存在的同盘原子 rename 提交 `versions/<N+1>/`，并在平台允许时 flush `versions/`。此刻只是不可变候选，尚未对读者可见。
8. 再以目标不存在的原子提交把 Event 放入 `events/<event-id>.yaml`，并在平台允许时 flush `events/`。这是唯一逻辑提交点；不能先更新 `capture.yaml`，也不能把版本目录 rename 当作成功回执边界。
9. 从最终路径回读版本、前一版本和 Event。只有连续链、全部新版本哈希及交叉引用都通过，才能返回 `saved: true + commit_state: committed`。
10. 最后原子更新投影到 N+1。该步失败只返回 `projection_needs_rebuild` 警告，不撤销已经提交的 Event/Version；只有显式启用异步投递目标时才登记对应新版本请求，MVP-0 不请求 GBrain 镜像。

锁内公共错误优先级为“不可变结构/版本支持 → 幂等命中或冲突 → `capture_not_found` → `version_conflict` → 版本/Event 目标与写入证据”。请求模型的机械错误和正文 staging/超限发生在此之前；因此正文超限可以先于锁内查找返回。已经取得确定损坏证据时必须使用 `integrity_check_failed`，不能退化成普通冲突或未知 I/O。

故障与读取责任固定为：

- 版本目录提交前失败：`not-committed`，没有新可见版本。
- 版本目录已经提交但 Event 可以证明未提交：仍为 `not-committed`；留下的唯一 N+1 目录是未完成事务残留。C4 latest/list 忽略它并警告，显式读取 N+1 返回 `version_not_found`；C4 不删除或补全它。
- 版本 rename 自身的结果即使无法判断，只要 Event 最终目标在逻辑提交尝试前仍被证明不存在，公共提交状态仍为 `not-committed`；不得把“可能留下不可见尾部”误报为逻辑提交未知。
- Event rename 抛错后，若 staging 候选仍存在且目标不存在，则为 `not-committed`；若候选已不存在且最终 Event、前后版本与全部新 Payload 完全匹配，则提交事实为 `committed`，继续最终回读；其余无法形成唯一结论的现场返回 `unknown`。不得生成新幂等键。
- Event 最终目标在首次尝试前已存在且没有先前同请求幂等证明时，不覆盖、不冒认；可证明本请求尚未逻辑提交时返回 `atomic_commit_failed + not-committed`。
- Event 已提交但最终回读无法证明内容有效：不能报告成功；确定的规范字节、引用或哈希损坏返回 `integrity_check_failed + unknown`，I/O 使事实不可证明则返回 `atomic_commit_failed + unknown`。读取侧看到 Event/Version 矛盾时一律 fail-closed。
- Event 和版本最终回读有效而投影失败：提交已成立，返回成功加 `projection_needs_rebuild`。
- 同 key 重试若发现可证明一致的唯一未提交 N+1 尾部，复用其版本、Event ID 和 Envelope 续封 Event；发现已提交匹配版本则返回原稳定回执。其他残留不自动处理。
- C6A 已在后续写操作取得 Store 锁后扫描固定 `.staging/` 的直接子项；只清理规范 UUIDv7 根、匹配的规范 marker、既有普通非 reparse lease 可无等待取得、身份复核不变且固定树完全通过的已放弃事务。活跃、旧式、未知、额外对象、reparse、身份变化或 I/O 不可证明的树均保持原字节。
- C6A 不发明物理 quarantine schema：完全匹配同一请求的唯一 N+1 尾部沿用 C5 窄续封；其他尾部继续由 Event 真源逻辑隔离并失败关闭。投影与空派生目录重建现已由 C6B 闭合。
- C6B 提供与四个日常文本操作分离的显式管理操作。它先在 Store 写锁内完整验证所有已提交 Item/Version/Event/Envelope 及全部 Payload 实际哈希，再原子替换缺失、已知损坏或落后的 `capture.yaml`；有效投影保持原字节。任一不可变损坏都会在派生写入前失败，唯一无 Event 的 N+1 尾部与未知 staging 均不触碰。
- C6B 不新增幂等索引文件或 outbox job schema。`indexes/idempotency/` 只是空的预留派生目录，key 映射仍由不可变 Envelope 扫描校验；Envelope v1 固定 `delivery_requests: []`，所以 outbox 重建只恢复四个空 bucket。未知 projection 版本或未知派生条目原样保留并失败关闭。
- C6C 提供另一个显式管理操作 `migration.migrate_capture_store`，要求配置、源根、目标根与预期 Store ID 同时绑定。它在初始化锁和源/目标 Store 锁下先完整验证源，再有界复制稳定树；只接受空目标或已有文件字节数/哈希与源完全匹配的兼容子集。
- C6C 不复制源 `.staging/` 内容或锁文件状态，但保留稳定 Item 里的未提交尾部字节及其逻辑不可见性。目标字节快照和语义均完整通过后才以同目录临时配置 + `os.replace` 切换；源在任何结果下均不自动删除。
- 迁移切换前已读到旧根的 `capture_text`/`append_capture_version` 会在获得旧 Store 锁后重读配置；绑定已变时以 `capture_store_unavailable + not-committed` 失败并只清理自有 staging，不能在切换后回写源。已完整复制的兼容部分目标可续传；单文件中途写入的部分目标不自动覆盖，按目标冲突失败关闭。

约束：

- 不提供 `capture_id` 的“相同内容保存”是新 Item，不是新版本。
- 不允许对旧版本做 in-place patch。
- 可以在 UI 中显示 diff，但版本文件保存完整 Payload，避免恢复依赖补丁链。
- 已批准旧版本时，新版本不会继承批准；旧批准继续只绑定旧哈希。
- C5 新增独立的追加成功结果类型，不放宽 C3 `capture_text` 已冻结的精确回执字段。

## 12. 崩溃与重试语义

| 故障点 | 结果 | 恢复方式 |
|---|---|---|
| staging 写入前崩溃 | 没有捕获成功 | 操作系统释放事务 `active.lock` 租约；后续写操作只按 C6A 所有权规则清理可证明放弃的 staging |
| staging 写入中崩溃 | 只有不完整临时目录 | 后续写操作取得 Store 锁后保守扫描；只清理租约可取得且固定树完整通过的已放弃事务，不返回成功 |
| 回读校验失败 | 不提交 | 保留诊断后重试 |
| rename 前崩溃 | 最终版本不存在 | 同幂等键重试 |
| rename 后、回执前崩溃 | 已耐久，但调用方不知道 | 同幂等键找到并验证原 Event/Version，返回相同身份与哈希字段；警告按当前投影事实生成 |
| 追加版本目录 rename 后、Event 前崩溃 | 只有不可见 N+1 残留 | C4 继续读取 N 并警告；完全匹配同 key 重试续封，其他尾部保持逻辑隔离，读取操作不自行修复 |
| 追加 Event rename 附近崩溃 | 逻辑提交状态未知 | 返回/保持 `unknown`；同幂等键按最终 Event 与版本事实探测，不盲目追加 |
| 投影更新失败 | 原件已耐久 | 当前调用及同 key 重试返回 `projection_needs_rebuild`；正式重建留到恢复批次 |
| Store 迁移复制未完成 | 配置仍指向源 | 完整且匹配的部分目标可重试续传；损坏/部分文件失败关闭，不自动覆盖 |
| 配置原子切换后、回执前崩溃 | 配置已指向完整目标 | 同迁移请求重放重新验证源/目标并返回已完成；不删除源、不重复切换 |
| outbox 索引失败 | 原件已耐久，尚未镜像 | 从 Envelope 的 Delivery Request 重建任务 |
| GBrain 写入失败 | 原件已耐久 | 标记 failed，按同一投递幂等键重试 |
| GBrain 成功但本地未记成功 | 远端状态不确定 | 按明确 slug、版本和哈希探测后 reconcile，不盲目新建 |
| Git commit/push 失败 | 本地原件仍耐久，但备份未完成 | 保持 uncommitted/failed 并批量重试 |

## 13. GBrain 镜像契约

### 13.1 角色

GBrain 镜像用于：

- `capture` 范围检索。
- embedding。
- 用户主动请求的摘要、标签、实体、关系和路由提案。
- 承载可重建的未审核工作副本。

它不用于：

- 证明原始 Payload。
- 保存唯一版本历史。
- 决定可信 KB 归属。
- 直接写入可信 wiki。

系统不要求独立、长期存在的“镜像导出目录”。MVP POC 优先使用一个薄的确定性同步适配器，在本地保存成功后显式调用 GBrain `put_page`。只有直接投递经实证不适合长文本或 Windows 传输时，才评估临时文件传输、生成式 Markdown 视图或专用 importer。

### 13.2 映射身份

MVP 推荐：

```text
GBrain source_id: knowledgeflow-intake
GBrain page slug: inbox/knowledgeflow/<capture-slug>
投递幂等键:      <capture_id>:<version>
```

其中 `<capture-slug>` 是对本地 `capture_id` 的确定性语法映射：把不符合 GBrain slug 规则的下划线转换为连字符。例如 `cap_01991...` 映射为 `cap-01991...`。GBrain slug 只作索引地址，原始 `capture_id` 必须完整保留在 frontmatter 中。

禁止使用 GBrain 默认“日期 + hash8”slug 作为 Capture Item 身份，也不得把转换后的 slug 反向当作本地审计身份。

GBrain 页至少携带：

```yaml
knowledgeflow_capture_id: "cap_..."
knowledgeflow_version: 1
knowledgeflow_primary_payload_sha256: "sha256:..."
knowledgeflow_payload_set_sha256: "sha256:..."
knowledgeflow_envelope_sha256: "sha256:..."
knowledgeflow_trust: "unreviewed-capture"
knowledgeflow_source: "local-capture-envelope"
```

### 13.3 镜像内容

- 文本 Payload 可以作为页正文镜像。
- URL 可镜像原始 URL 和独立抓取快照的引用。
- 文件只镜像元数据、文本提取物和本地原件引用；原文件仍由 Capture Store 保管。
- GBrain 可以添加自己的 Markdown 包装，因为它不是精确原件。
- GBrain 生成的摘要、标签、关系和路由判断必须进入派生字段或 `proposals/`，不得反向写入 Payload。

### 13.4 更新方式

MVP 使用“一 Item 一镜像页，展示当前版本”：

- 新版本可更新同一 GBrain 页。
- 本地 Envelope 永久保留全部版本，因此不依赖 GBrain 页版本历史。
- GBrain 映射状态记录当前 `mirrored_version + envelope_sha256`；正文镜像还要记录主 Payload 哈希。
- 旧版本仍可通过本地 Capture Store 和路由记录访问。

若以后需要在 GBrain 内搜索历史版本，可增加每版本独立页，但不改变本地真源。

### 13.5 禁止反向覆盖

- MVP 不把 GBrain 页面作为原件编辑入口。
- 用户要修改捕获，应调用 KnowledgeFlow 的追加版本事务。
- 检测到 GBrain 页与本地镜像哈希不一致时，标记 `stale/diverged`。
- 自动任务可以从本地版本重建 GBrain 页，但不得把 GBrain 页内容覆盖回本地 Payload。
- 若未来允许从 GBrain UI 编辑，编辑内容必须作为新输入重新进入 Capture Transaction，不能原地替换旧版本。

### 13.6 语义安全前置条件

在接入 GBrain 前必须完成可执行的安全配置与验收清单，至少保证：

- 自动链接关闭或输出只进入派生层。
- 自动 timeline 写入关闭。
- 自动 facts 抽取关闭。
- auto chronicle 关闭。
- 不加载 `signal-detector`、`idea-ingest` 等自动语义写页技能。
- 不运行能够反向写规范 Markdown 的完整 Dream Cycle/autopilot。
- POC 使用专门的本地 keyless PGLite brain，或至少使用 DB-only、`federated: false` 的 `knowledgeflow-intake` source；不得把 Capture Store 目录直接配置成 GBrain 可写回的 source。
- 本地 POC 不引入 HTTP/OAuth；只有出现不可信 Agent、跨进程或远程访问时，才增加 source/slug 受限身份。
- `trusted` 查询显式排除 intake source；`federated: false` 只作为默认搜索隔离的一层，不替代查询验收。
- 同步适配器只做固定格式映射，不生成摘要、标签、实体、关系、路由和 SCHEMA 建议。

## 14. Git 与备份语义

Git 不属于捕获成功的同步前置条件，否则每次随手记都会被 commit 延迟和仓库锁阻塞。

建议：

- 本地原子提交完成即可返回 `durable`。
- Capture Store 可以按时间或数量批量 commit。
- 备份状态单独表示：`uncommitted | committed | pushed | failed`。
- 未 commit 不等于未保存，但 UI 应能提示“仅本机耐久，尚未备份”。
- Git 历史不能替代 Item/Event/Version 状态模型。
- Capture Store 的 Git 拓扑与每个 KB 是否独立 Git 分开决策。

“durable”至少保证应用进程崩溃后可恢复。对突然断电的保证依赖文件 flush、目录元数据 flush 和底层文件系统行为，必须在 Windows/Linux 实现测试中单独验证，不能只凭 rename 假设。

## 15. 安全约束

- 所有存储路径由系统 ID 和固定模板生成。
- 原始文件名只作为元数据，不直接参与目标路径拼接。
- 拒绝 `..`、绝对路径注入、设备路径和越界 symlink。
- 从本地路径捕获文件时，打开后读取实际字节；不能只记录可变化路径。
- Payload 路径必须解析在所属版本目录内。
- Envelope 解析拒绝重复 YAML key、未知危险 tag、anchor 和 alias。
- 日志不得记录完整敏感 Payload、原始幂等键或凭据。
- 哈希可用于完整性校验，不用于证明是谁创建或批准；审批身份由独立审计记录承担。
- 永久删除原件不属于普通归档，必须是显式破坏性操作。

## 16. 状态不变量

系统在任何时刻都必须满足：

1. `saved: true` 必然对应一个可读取、可解析、哈希通过的不可变版本目录。
2. 一个最终版本目录只对应一个 `capture_id + version`。
3. 同一 Item 不存在两个不同内容的相同版本号。
4. 同一幂等身份不能对应两个不同请求指纹；即使 Payload 相同，只要明确用户意图或影响 Envelope 的元数据不同，也必须冲突。
5. 相同 Payload 可以对应多个主动 Capture Event。
6. 旧版本不因新版本、路由、GBrain 同步或 Git 操作被修改。
7. 当前投影指向的版本必须真实存在；不存在时投影无效而不是原件消失。
8. GBrain 删除或损坏不能删除唯一原件。
9. 未审核捕获不能进入 `trusted` 查询范围。
10. 模型输出不能进入 Immutable Envelope 的 Payload 文件。
11. 可读版本只能构成从 1 开始的连续前缀，且每版恰有一个匹配的版本建立 Event；投影和目录名不能扩大可见范围。
12. 有效前缀后的唯一无 Event N+1 目录只是可隔离残留；Event 已存在但版本/引用不成立则是完整性失败，不能降级忽略。

## 17. 公共错误、内部原因与提交后警告

调用方可依赖的公共错误码及 `commit_state` 以[MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)第 3.5、8 节为准。底层原因不能直接冒充同级公共错误；固定映射如下：

| 底层原因或后续状态 | 公共表达 | 保存语义 |
|---|---|---|
| `payload_hash_mismatch`、`payload_set_hash_mismatch`、`envelope_hash_mismatch`、`byte_size_mismatch` | `error.code: integrity_check_failed`，具体名称放 `cause_code` | 读取操作不返回正文；写操作按现场证据返回 `not-committed` 或 `unknown` |
| `payload_read_failed`、`payload_write_failed` | 作为 `cause_code`，由发生阶段映射到稳定公共 I/O/输入错误 | 提交前发生时不得报告成功 |
| `projection_update_failed` | `ok: true`，警告 `projection_needs_rebuild` | 不可变版本已经提交，不能改报 `saved: false` |
| 唯一无 Event 的 N+1 尾部目录 | 读取成功时警告 `incomplete_version_ignored`；显式读取该版本为 `version_not_found` | 该版本没有逻辑提交，C4 不修复或删除 |
| 调用方正文 sink 写失败 | `error.code: output_write_failed`，固定消息 `capture body output failed` | Store 已通过完整验证；调用方丢弃部分 sink 输出后重试 |
| `outbox_projection_failed` | `ok: true`，警告 `outbox_needs_rebuild` | 本地原件已经提交，索引可重建 |
| `gbrain_sync_failed` | 异步状态/警告，不是捕获错误 | 不改变本地保存回执 |
| `backup_failed` | 异步状态/警告，不是捕获错误 | 不改变本地保存回执 |

`idempotency_conflict`、`version_conflict`、`atomic_commit_failed` 等本身就是稳定公共错误码。rename 附近发生异常且无法立即判定最终结果时，`atomic_commit_failed` 必须配合 `commit_state: unknown`；调用方保留输入并使用同一幂等键重试或查询。

公共错误和警告结构不得泄露 Payload、预览、原始幂等键、凭据或敏感本机路径。`cause_code` 只用于诊断，调用方的业务分支应依赖公共 `code`。

## 18. MVP 验收测试

### 18.1 原件与版本

- [ ] UTF-8 中文、emoji、组合字符按 channel-exact 保存，不做 NFKC。
- [ ] CRLF、LF、首尾空白和无结尾换行都能按渠道保真规则核验。
- [ ] PDF、图片和任意二进制文件按字节 SHA256 一致。
- [ ] 原输入文件在捕获后被修改，不影响已保存 Payload。
- [ ] 新版本不修改旧版本目录。
- [ ] stale `expected_current_version` 返回 `version_conflict`。

### 18.2 幂等与重复

- [ ] 相同幂等键、相同请求指纹重试返回同一 Event/Item/Version 和相同核心哈希；警告按当前投影事实生成。
- [ ] 相同幂等键、不同请求指纹返回冲突，包括“Payload 相同但明确用户意图不同”的情况。
- [ ] 不同幂等键保存相同内容产生两个 Capture Event。
- [ ] idempotency 索引删除后仍可从不可变记录恢复原映射。

### 18.3 崩溃恢复

- [ ] 在 T4 至 T10 每个阶段注入进程崩溃，均不会产生虚假成功。
- [ ] rename 后、回执前崩溃，重试返回原稳定身份/哈希字段而非新建 Item，并按当前投影事实返回警告。
- [ ] staging 残留能被安全识别，不会被当作已完成版本。
- [ ] `capture.yaml` 删除后可以重建。
- [ ] outbox 删除后可以从 Delivery Request 重建。

### 18.4 GBrain 隔离

- [ ] GBrain 完全不可用时，本地捕获仍成功并显示 `pending/failed`。
- [ ] GBrain 重试不会创建多个镜像页。
- [ ] GBrain 镜像页携带准确版本和 SHA256。
- [ ] 直接修改 GBrain 页不会覆盖本地 Payload。
- [ ] 默认 `trusted` 查询无法召回该镜像页。
- [ ] 捕获不会触发自动 facts、timeline、实体页或可信 wiki 写入。

### 18.5 热路径与权限

- [ ] 捕获成功路径没有任何 LLM 调用。
- [ ] 不指定 KB 也能保存。
- [ ] 用户明确指定 KB 时记录授权证据，但仍不直接写 wiki。
- [ ] 模型推荐结果只能进入提案。
- [ ] 路径穿越、symlink 越界和危险文件名不能逃出 Capture Store。

## 19. 成本控制

v1 推荐暂不引入新的业务数据库：

- 不可变版本目录是规范真源。
- `capture.yaml`、idempotency index 和 outbox 是可重建投影。
- 使用文件锁、staging 和原子 rename 闭合单机事务。
- Git 批量提交，不为每条灵感同步阻塞。
- GBrain 异步镜像，不参与捕获成功判定。

只有出现以下情况，再评估 SQLite/Postgres 事件索引：

- Capture Item 数量导致扫描不可接受。
- 多进程/多设备并发成为真实需求。
- 需要复杂批量查询、保留策略或队列调度。
- 文件锁和重建索引无法满足可靠性指标。

即使增加数据库，不可变 Payload 和 Envelope 的身份与哈希语义也保持不变。

## 20. 已确认与待确认

### 20.1 本轮已经确认

- GBrain 原生 capture 不作为唯一 Capture Envelope。
- MVP 使用本地文件式 Capture Store，并保留可重建的状态投影和 outbox。
- 本地不可变版本是审计锚点。
- GBrain 是异步未审核工作副本。
- 捕获成功不等待 GBrain、Git 或模型。
- Capture Event、Item、Version 和 Payload 必须分开表达。
- 状态投影不得与不可变 Envelope 混为一体。
- MVP-0 先只实现单机、单用户文本捕获。
- GBrain POC 优先使用本地 DB-only source + 薄同步适配器，不预建独立镜像导出目录或 HTTP/OAuth。
- 当前机器 `capture-root` 确认为 `E:\KnowledgeFlowData\capture-store`，由机器本地配置提供；运行时规范化结果必须是绝对路径，Envelope 内仍只记录相对 Payload 路径。
- 4 MiB 是文本内联传输阈值；4–64 MiB 使用流式 staging；64 MiB 是可配置的默认安全上限，超限不得截断、摘要或自动拆成多个 Item。
- 写操作采用 `not-committed / committed / unknown` 三态提交结果；提交后的投影故障只返回成功警告。
- 核心哈希明确分为 Payload、Payload Set、Request Fingerprint 和 Envelope 四类，并固定各自规范输入字节。
- UUIDv7 固定时间位、随机位、前缀、同毫秒唯一性和时钟回拨语义，不承诺绝对单调排序。
- YAML 采用“语法门禁 + schema 校验 + 确定性发射”三部分受限 codec。

### 20.2 实现前仍需确认

| 问题 | 当前建议 | 是否阻塞逻辑契约 |
|---|---|---|
| Capture Store 的 Git 拓扑 | 先跟随父级统一 Git，后续可迁移 | 否 |
| 非文本文件大小上限 | 文本规则已经确认；PDF、音视频和其他二进制入口仍需单独设上限 | 是，阻塞文件入口实现 |
| 大文件对象存储 | 后置；引用必须带不可变对象 hash | 否，若 MVP 限制大小 |
| 敏感内容加密 | 后续单独设计 | 否，但上线前需风险确认 |
| 自动备份频率 | 批量 commit/push，UI 展示备份状态 | 否 |
| 保留和物理删除策略 | 默认长期保留，删除必须显式 | 否 |

## 21. 下一步

本文虽已获批，仍不应立即开发完整捕获系统。当前推荐顺序：

1. C0–C2 里程碑为 85 项测试，稳定化后为 93 项；C3A/C3B 完成后为 122 项，C3C 完成后为 140 项，C3V 完成后为 144 项，R0.1/R0.2 初始化所有权加固后为 148 项，D0G 后为 156 项，R0.3D 后为 159 项，R0.3F 后为 163 项，C4A 后为 182 项，C4B 后为 197 项，C4C 后为 212 项，C4V 后为 214 项，C5A 后为 231 项，C5B 后为 250 项，C5V 后为 253 项，C6A 后为 258 项，C6B 后为 265 项，C6C 后为 274 项，C7A 后为 293 项，C7B 后当前全量 300 项测试通过。除原有 C3–C5 证据外，事务租约、16 个业务进程终止边界、REC-01–REC-03、MIG-01–MIG-05、C7A 严格帧/有界 spool/退出码与脱敏单元证据，以及 C7B 真实四操作/生产 policy/安装入口隔离证据也已建立。
2. 当前实现已包含公开 `capture_text`、C4B `get_capture`、C4C `list_captures` 和 C5B `append_capture_version`；四者均已完成各自阶段验收，C6A 业务崩溃恢复、C6B 派生状态重建和 C6C Store 迁移也已完成。C7 受限 CLI 与 C8 总验收尚未完成，因此本文整体仍不是 `Effective`。
3. [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md)已于 2026-09-08 获批，C3A/C3B 已于 2026-09-10 分别完成，C3C/C3V 与 R0.1/R0.2 已于 2026-09-11 在测试持有的 Store 中先后完成，D0-F、D0G 与 C4-0 也已闭合；后续 C4A/C4B/C4C 均另行获得逐批授权。任何这些授权都不包含生产 Store。
4. C5A `63a3250`、C5B `ab2a613`、C5V `a9913e2`、C6A `84ee1d7`、C6B `f686941` 与 C6C `ea8f84e` 已于 2026-09-18 同步至 `origin/main`，Windows CI 运行 `35319645501` 首次通过。C7-0 `dbe8329` 与 C7A `fb61358` 也已同步至 `origin/main`；C7B 已完成本地内容、验证与本批独立版本化但尚未 push，下一功能门禁为需单独授权的 C7V。上述阶段均不接 GBrain。
5. 本地链路验收后，再把第 13.6 节细化为 GBrain POC 的命令、配置和查询验收清单。
6. 最后分别设计 URL 和文件 Payload 的入口门禁。
