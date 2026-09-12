# MVP-0 本地文本捕获操作契约

> 状态：Approved Design；C0–C3 与 C4-0 已完成，`capture_text` 已实现并通过本阶段验收，读取与追加操作仍未实现<br>
> 确认日期：2026-09-02<br>
> C3-0 补充确认日期：2026-09-08<br>
> C3 编码前收口日期：2026-09-09<br>
> C3A/C3B 完成日期：2026-09-10<br>
> C3C 完成日期：2026-09-11<br>
> C3V 完成日期：2026-09-11<br>
> C4-0 读取契约完成日期：2026-09-13（独立本地提交；未 push）<br>
> 适用范围：单机、单用户、纯文本捕获<br>
> 边界：本文定义调用方可见的完整操作；C3 只实现并验收了 `capture_text`，其余三个公开操作尚未完成，也未创建生产目录

## 0. 结论先行

MVP-0 只需要四个机械操作：

| 操作 | 用户含义 | 是否调用 LLM | 是否要求 KB | 是否写 GBrain |
|---|---|---:|---:|---:|
| `capture_text` | 保存一条新文本 | 否 | 否 | 否 |
| `get_capture` | 读取一条捕获的指定版本 | 否 | 否 | 否 |
| `list_captures` | 列出捕获箱中的记录 | 否 | 否 | 否 |
| `append_capture_version` | 给原捕获追加一个完整新版本 | 否 | 否 | 否 |

四个名称是内部操作名，不要求直接显示给用户。界面可以分别显示为“保存”“查看”“捕获箱”“保存为新版本”。

本文不定义路由、SOP-000A、SOP-001、GBrain 镜像、可信写入或删除。它们都不是本地文本捕获成功的前置条件。

## 1. 与其他规范的关系

- [设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)决定 MVP 边界和功能门禁。
- [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md)继续负责身份、Envelope、哈希、不可变版本、幂等和原子事务，是底层权威。
- [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md)冻结 `capture_text` 编码前六项补充边界，已于 2026-09-08 获批并同步进本文。
- [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md)负责 MVP-1 以后如何选择 KB 和处理方式。
- 本文只把底层事务收敛为四个调用方可以理解和测试的操作。

发生冲突时，本文不能放宽上层治理红线；底层字段和事务细节以 Capture Envelope v1 为准。

## 2. `capture-root` 方案

### 2.1 定义

`capture-root` 是一个本地运行配置项。程序真正访问存储前，必须把配置来源解析为 Capture Store 的规范化绝对根目录。它是存储位置，不是业务对象，也不是 Global Intake。

```text
Capture Store  = 本地捕获存储机制
capture-root   = 该机制在本机文件系统中的根路径
Capture Item   = 根路径下的一条捕获原料
Global Intake  = list_captures(routing_status="unassigned") 的逻辑视图
```

### 2.2 当前机器的推荐值

```text
E:\KnowledgeFlowData\capture-store
```

推荐理由：

- 与 `C:\Users\94233\knowledge-flow` 源代码仓库分离，避免原料被误提交为项目代码。
- 与 `E:\KnowledgeBase` 等领域知识库分离，捕获时无需先决定 KB。
- E 盘当前可用，并适合作为用户控制的本地数据位置。
- 将来可以对整个 `E:\KnowledgeFlowData` 单独制定备份、加密和迁移策略。

该路径已确认为当前机器的部署配置，但当前仍不存在，本轮不创建。程序实现必须读取机器本地配置，不得把该绝对路径硬编码进通用代码。

配置示意如下，配置文件位置仍留到实现拆解时确定：

```yaml
capture:
  root: 'E:\KnowledgeFlowData\capture-store'
  inline_text_threshold_bytes: 4194304
  max_text_version_bytes: 67108864
```

### 2.3 路径硬约束

1. 路径来源可以是机器本地配置、明确启动参数或平台数据目录选择器；通用源码不得写死某台机器的盘符和用户名。
2. 在任何存储访问前，解析结果必须是规范化绝对路径。普通相对路径不得按当前工作目录解释；平台数据目录选择器必须先解析成绝对路径。
3. 不得位于 KnowledgeFlow 源码仓库、任一 KB、GBrain 数据目录或系统临时目录中。
4. `.staging/` 与 `items/` 必须在同一文件系统，保证原子 rename 的语义成立。
5. 所有目标路径必须在规范化后验证仍位于 `capture-root` 内，拒绝 `..`、符号链接或 Windows reparse point 越界。
6. 配置文件不存在时返回 `config_not_found`；配置存在但语法、schema 或必填字段不合法时返回 `config_invalid`。两种情况都不得偷偷回退到当前目录、用户桌面或临时目录。
7. 根目录不存在、未初始化或不可写时不得报告保存成功。
8. Git、云盘和远端备份可以异步增加，但不能参与 `capture_text` 的成功判定。

### 2.4 一次性初始化边界

首次确认路径后，需要由安装流程或设置页机械创建 Capture Store 的基础目录并验证读写、flush 和同盘原子 rename。这是一次性部署动作，不是第五个日常捕获操作，也不调用 LLM、GBrain 或 SOP。

- 目标不存在时，只有经过用户明确选择的路径才能创建。
- 目标是非空但无法识别的既有目录时必须拒绝接管，不能混写。
- 初始化只建立存储骨架，不创建 Capture Item，不选择 KB，也不生成演示内容。
- 四个日常操作只在初始化成功后开放；否则返回 `capture_store_not_initialized`。

### 2.5 可移植性与迁移

项目可移植性来自“通用代码 + 每机配置 + 与根目录无关的数据格式”，而不是要求所有机器共用同一条路径。

- `E:\KnowledgeFlowData\capture-store` 只存在于当前机器的本地部署配置中。
- Envelope 内只记录 `payloads/primary.txt` 等版本目录内相对路径，不记录 `E:\...` 前缀。
- Payload 和 Envelope 哈希不包含当前机器的 `capture-root`，因此合法搬迁不会改变原件身份。
- 机器本地路径配置不应提交为仓库中的跨机器共享默认值。

迁移流程固定为：

1. 暂停所有写操作并记录当前状态。
2. 完整复制 Capture Store 到新位置，不在复制过程中继续捕获。
3. 在新位置扫描并验证所有 Envelope 和 Payload 哈希。
4. 将新机器或新磁盘的本地配置改为新的绝对解析结果。
5. 重建可派生的状态投影、幂等索引和 outbox，再恢复写入。

迁移前旧目录保持只读保留，直到新位置验收通过；不得用移动后无法回退的方式替代复制—校验—切换。

## 3. 四个操作的共同约定

### 3.1 文本保真

- 核心操作接受 Python `str` 或提供 `read(size)` 的二进制 UTF-8 流；两者共享同一个有界分块写入器和保存事务。
- `str` 按 UTF-8 分块编码；字节流执行严格 UTF-8 增量校验，不要求 seek 或重复读取。
- 以 UTF-8、无 BOM 写入 `payloads/primary.txt`；开头的 UTF-8 BOM 字节或字符串 `U+FEFF` 拒绝，不静默删除。
- 不做 `trim`、Unicode 规范化、换行转换、错字修正、摘要或自动标题。
- 空字符串拒绝；只包含空格或换行的非空字符串仍允许保存，因为系统不判断内容价值。
- 4 MiB 是内联传输阈值，不是存储上限。
- 不超过 4 MiB 时允许走内联路径；超过 4 MiB 时，同一个 `capture_text` 操作必须走有界分块 staging。阈值只改变内部传输方式，不改变 Item、Payload、哈希或回执身份。
- MVP-0 单文本版本的默认安全上限是 64 MiB UTF-8 字节，可由机器本地配置调整。
- 超过配置安全上限时返回 `text_too_large`；不得截断、摘要、自动拆成多个 Capture Item 或虚报成功。
- 大文本仍保存为一个完整的 `payloads/primary.txt`。流式实现必须保持 UTF-8 字节顺序，以一次读取写入本事务 staging，并以 staging 和最终路径回读的完整字节计算哈希。

本文中的 MiB 使用二进制定义：`1 MiB = 1,048,576 bytes`。配置必须满足 `0 < inline_text_threshold_bytes <= max_text_version_bytes`；修改上限只影响后续请求，不改变既有版本。

处理分层如下：

| UTF-8 字节数 | 处理方式 |
|---:|---|
| `0` | `invalid_input` |
| `1` 至 `4 MiB` | 内联进入同盘 staging |
| `> 4 MiB` 且 `<= 64 MiB` | 流式写入同盘 staging，仍是同一个 Capture Item 和 Payload |
| `> 64 MiB` | 默认拒绝提交并保留调用方原输入；允许调整本地安全上限，或以后转入大文本文件捕获 |

调用方只有收到 `saved: true` 后才能清空编辑缓冲、删除临时来源或确认外部消息已经被本地耐久接管。

### 3.2 身份和版本

- `capture_id`、`event_id` 由服务端生成，调用方不能指定。
- 新 Capture Item 的版本固定为 `1`。
- 追加版本只能从当前版本 `N` 变成 `N + 1`。
- 任何操作都不得原地修改已经提交的版本目录。
- 所有写入成功回执必须携带 `capture_id + version + envelope_sha256`。

### 3.3 渠道和用户意图

写操作需要内部渠道信息：

```yaml
channel:
  type: "app"
  instance_id: "local-desktop"
  external_ref: null
  source_created_at: null
```

界面入口可以自动填入自身渠道信息，不要求用户手工输入。

MVP-0 的可信操作者不由普通请求传入，核心固定为 `actor.type: user`、`actor_id: local-user`。`channel.type` 和 `channel.instance_id` 分别限制为 1–64 个小写 ASCII token 字符；`source_created_at` 非空时必须是带 `Z`、毫秒精度的规范 UTC，`external_ref` 非空时最多 2048 UTF-8 bytes。

`user_intent` 只记录用户在这次请求中明确表达的目标 KB、处理方式或新 KB 名称。MVP-0 只保存这份证据，不执行路由，也不运行 SOP。

### 3.4 幂等

- `capture_text` 允许省略 `idempotency_key`；省略意味着每次调用都是新的主动保存。
- 官方界面和 API 适配器应为每次用户保存动作生成稳定的 `idempotency_key`，以便处理超时重试。
- `append_capture_version` 必须提供新的 `idempotency_key`，避免“提交成功但回执丢失”时重复追加版本。
- 同一作用域、同一 key、相同请求指纹返回同一 Item/Version/Event 及相同核心哈希；同一 key、不同指纹返回 `idempotency_conflict`。
- 幂等命中仍须验证最终不可变 Envelope、Payload 和 Event；成功回执的 `warnings` 按命中时的当前投影事实生成。`capture.yaml` 缺失、损坏或不一致时返回 `projection_needs_rebuild`，C3 不在该路径静默重建投影。
- 内容哈希不是幂等键；相同内容可以被用户主动保存为两个不同 Capture Item。
- 提供的 key 必须非空且不超过 512 UTF-8 bytes；原始 key 不落盘。规范 `scope`、带域前缀的 `key_sha256` 及二元组身份规则以 Capture Envelope v1 第 5.3 节为准。
- C3 在 Store 级写锁内扫描不可变 Envelope，不引入新的幂等索引磁盘格式；索引只作为后续可重建的性能优化。

### 3.5 统一失败结构

操作失败时返回结构化错误，不用自然语言猜测状态。调用方以稳定的公共 `error.code` 决定交互；`cause_code` 字段固定存在，在有更底层机械原因时填写，否则为 `null`，不能替代公共错误码：

```yaml
ok: false
commit_state: "not-committed"
error:
  code: "integrity_check_failed"
  cause_code: "payload_hash_mismatch"
  message: "stored data failed integrity verification"
  retryable: false
  details: {}
```

两个写操作必须返回 `commit_state`：

| 值 | 含义 | 调用方动作 |
|---|---|---|
| `not-committed` | 可以证明不可变版本没有进入最终路径 | 保留原输入；修复原因后可用同一幂等键重试 |
| `committed` | 可以证明不可变版本已进入最终路径并通过回读校验 | 视为保存成功；后续故障只作为警告或状态处理 |
| `unknown` | rename 附近发生异常，当前进程无法证明最终目录是否已提交 | 不生成新幂等键；保留原输入，并用同一幂等键重试或查询 |

`capture_text` 和 `append_capture_version` 的成功回执固定为 `ok: true + saved: true + commit_state: committed`。写操作失败时为 `ok: false`，并返回 `not-committed` 或 `unknown`；不能在状态未知时谎报 `saved: false`。读取操作不发生提交，因此省略 `commit_state`。

不可变版本提交以后发生投影、索引或异步任务故障时，必须返回成功加警告，不能把已保存原件改报为失败：

```yaml
ok: true
saved: true
commit_state: "committed"
warnings:
  - code: "projection_needs_rebuild"
    message: "capture state projection needs rebuild"
    details: {}
```

`retryable: true` 表示修复原因后可以安全重试；写操作必须使用**同一幂等键**，读取操作重放同一请求。它不保证立刻重试一定成功。错误和警告不得包含 Payload 正文、预览、原始幂等键、凭据或敏感本机路径。

### 3.6 已提交版本与读取可见性

读取只能观察由不可变版本目录和版本建立 Event 共同证明的**连续已提交版本前缀**；`capture.yaml`、目录修改时间和“最高目录名”都不是提交证明。

1. 版本 1 可见，当且仅当最终 Item 中存在规范 `versions/000001/`，且存在唯一、规范、交叉引用完全匹配的 `capture.created` Event。创建事务以完整 Item rename 为原子单位，因此已经定位到 `<capture-id>/` 却无法证明版本 1 时属于 `integrity_check_failed`，不得当成空 Item 或自动清理。
2. 对 `N > 1`，版本 N 可见，当且仅当 `versions/<六位版本号>/` 已在最终 Item 中存在，且 `events/` 中存在唯一、规范的 `capture.version-appended` Event，同时绑定版本 N、前一版本 N-1、前后两个 Envelope 哈希和相同 `capture_id`。该 Event 的最终无覆盖提交是追加事务的逻辑提交点。
3. 已提交版本必须恰好构成 `1..N` 的连续链。每个版本目录名只能是 `000001` 至 `999999` 的六位 ASCII 十进制数；Python `bool` 等不得冒充整数版本。Item 的 `YYYY/MM` 分片必须与版本 1 `received_at` 一致，同一 Store 中不得存在两个相同 `capture_id`。
4. 在有效前缀 `1..N` 后，至多允许一个普通、非 reparse、仍位于 Item 内的 `versions/<N+1>/` 目录没有任何版本建立 Event。无论其内部文件是否写全，它都只视为追加事务残留：读取 latest 和列表继续使用 N，并返回 `incomplete_version_ignored`；显式读取 N+1 返回 `version_not_found`。C4 只读路径不得删除、补 Event 或修复该目录。
5. Event 已存在但对应版本目录、Envelope、Payload 或交叉引用缺失/损坏，孤立或重复的版本建立 Event，版本缺口，两个以上未提交尾部目录，或未提交尾部之后又出现更高版本/Event，均返回 `integrity_check_failed`，不得回退到较旧版本伪装成功。
6. 已知 schema 的非法内容、非规范机器字节和交叉引用矛盾属于 `integrity_check_failed`；Store Manifest 或机器文件使用本实现不支持的 schema/schema version 时返回 `unsupported_store_version`。投影从不改变上述判定。

这里的“忽略”只隔离唯一、无 Event 的 N+1 尾部残留；它不是一般性的损坏容忍策略。正式恢复、隔离或删除残留属于 C6。

## 4. `capture_text`

### 4.1 目的

创建一个新的 Capture Item 和版本 `1`，完成本地可靠保存后立即返回回执。

### 4.2 请求

```yaml
text: "想到知识策展悖论可能还涉及整理成本与未来收益的不对称。"
channel:
  type: "app"
  instance_id: "local-desktop"
  external_ref: null
  source_created_at: null
idempotency_key: "save-0199..."   # 可选，但官方客户端应提供
user_intent:
  target_kb_id: null
  processing_mode: null
  requested_new_kb_name: null
```

以上展示 `str` 内联形态。二进制流形态使用相同的渠道、幂等和 `user_intent` 元数据，但正文通过受控 `read(size)` 流提供，不嵌入 YAML/JSON，也不要求流可回退；两种形态不能在同一请求中同时提供。

字段规则：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `text` 或二进制 UTF-8 流 | 二选一 | 非空文本；严格 UTF-8、无 BOM；按落盘字节计算且不超过配置安全上限，超过内联阈值时分块写 staging |
| `channel.type` | 是 | 由入口适配器填写，不从正文推断；1–64 个规范 token 字符 |
| `channel.instance_id` | 是 | 标识具体入口实例；1–64 个规范 token 字符 |
| `channel.external_ref` | 否 | 外部消息 ID 等来源引用；非空时最多 2048 UTF-8 bytes |
| `channel.source_created_at` | 否 | 渠道给出的原消息规范 UTC 时间；省略时为 `null`，不能冒充本地捕获时间 |
| `idempotency_key` | 否 | 官方客户端应生成；提供时非空且最多 512 UTF-8 bytes；核心允许主动重复保存 |
| `user_intent` | 否 | 省略等价于三个意图字段均为 `null`；非空值只能记录用户明确表达 |

调用方不能传入 `capture_id`、版本号、服务端时间、actor、哈希、模型标题、摘要、标签或可信状态。

为保证低摩擦输入和稳定幂等，调用边界先做唯一的机械规范化：省略 `channel.external_ref` 或 `channel.source_created_at` 时补为 `null`；省略整个 `user_intent` 时补成三个字段均为 `null` 的对象。省略形式与显式 `null` 形式生成同一 Request Fingerprint。最终 Envelope 仍必须写出完整 `channel`、`user_intent` 和 `user_intent.evidence`，不能把“调用输入可省略”误解成“Envelope 字段可省略”。

### 4.3 成功回执

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

`ok: true` 要求完整新 Item 已原子提交到最终 `<capture-id>/`，其中不可变版本 1 和匹配的 `capture.created` Event 均已从最终路径回读校验成功。创建 Event 失败发生在提交前，不得报告成功；只有提交后的 `capture.yaml` 投影失败产生 repair warning。回执不等待模型、KB、Git、GBrain 或备份。

同 key、同请求的重试必须返回相同的 `capture_id`、`event_id`、`version` 和三个 SHA256 字段。`warnings` 不是不可变回执身份：它按重试时观察到的 `capture.yaml` 状态生成；C3 不因幂等重试自动重建投影。

### 4.4 明确不做

- 不选择或创建 KB。
- 不自动生成标题、摘要、标签、实体或关系。
- 不运行 SOP-000A、SOP-001 或 SOP-002。
- 不直接写 `raw/`、`wiki/` 或 GBrain。
- 不因“内容太短、重复、不重要”而拒绝保存。
- 不把大文本自动拆成多个 Capture Item，也不通过摘要规避安全上限。

## 5. `get_capture`

### 5.1 目的

按 `capture_id` 读取最新版本或一个明确历史版本，先完整校验不可变版本链和目标 Payload，再把正文写入调用方拥有的二进制 sink。

### 5.2 请求

请求由结构化元数据和一个带 `write(bytes)` 的调用方二进制 `body_sink` 组成；sink 不序列化进 JSON/YAML。读取最新版本：

```yaml
capture_id: "cap_..."
version: null
```

读取明确历史版本：

```yaml
capture_id: "cap_..."
version: 1
```

字段规则：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `capture_id` | 是 | 必须是规范 `cap_` UUIDv7；不得参与未校验路径拼接 |
| `version` | 否 | `null` 表示最高已提交版本；非空时是 `1..999999` 的整数，`bool` 无效 |
| `body_sink` | 是 | 调用方拥有、带 `write(bytes) -> int` 的二进制输出；一次请求使用一个初始为空或可安全丢弃的 sink |

### 5.3 成功返回

```yaml
ok: true
body_length_bytes: 42
capture:
  capture_id: "cap_..."
  version: 1
  current_version: 2
  fidelity: "channel-exact"
  media_type: "text/plain; charset=utf-8"
  encoding: "utf-8"
  byte_size: 42
  primary_payload_sha256: "sha256:..."
  payload_set_sha256: "sha256:..."
  envelope_sha256: "sha256:..."
  captured_at: "2026-09-01T02:10:12.456Z"
  channel:
    type: "app"
    instance_id: "local-desktop"
  user_intent:
    target_kb_id: null
    processing_mode: null
    requested_new_kb_name: null
item_state:
  routing_status: "unassigned"
  trust_status: "unreviewed-capture"
integrity: "verified"
warnings: []
```

成功时，`body_sink` 恰好收到 `body_length_bytes` 个原始 UTF-8 字节；结构化结果自身不包含 `text` 或正文副本。具体适配器可以在调用完成后按自己的帧协议先发送结果头、再转发已经验证的正文。

规则：

- `version: null` 明确表示读取当前最高已提交版本，不表示“找到什么就返回什么”。
- 指定版本不存在时返回 `version_not_found`，不得悄悄退回最新版本。
- 返回正文前，按第 3.6 节验证连续版本/Event 链：链中每个版本都校验规范 Envelope、自哈希及 Event/路径/ID/版本交叉引用；对**本次请求的目标版本**，再校验其每个 Payload 的实际字节数和 SHA256 以及 `payload_set_sha256`。任一相关 Store 读取或完整性错误都必须发生在 sink 收到第一个字节之前。
- 实现以不超过 1 MiB 的块把目标主 Payload 读入 Store 外、测试或运行时拥有的磁盘验证 spool；全部验证通过后再从 spool 流式复制到 sink。正文即使达到 64 MiB 也不得整体驻留内存，spool 不属于 Capture Store，不得改变其可见性或原件。
- 每次 sink `write` 的参数不超过 1 MiB；返回值必须是 `1..len(chunk)` 的整数，短写时继续发送未消费后缀。返回 0、`None`、boolean、越界值或抛出异常都视为 sink 失败。核心不关闭、flush 或复用调用方 sink，也不把“write 已接受”宣称为 sink 自身的持久化保证。
- sink 写入失败返回可重试的 `output_write_failed`，固定消息为 `capture body output failed`，并省略 `commit_state`。此时 sink 可能已有一段**已通过 Store 完整性验证**的正文；调用方仍必须丢弃该 sink，并以新的或已清空的 sink 重试。该错误不表示 Store 损坏。
- 当前状态投影损坏时，可以从不可变版本和事件在内存中恢复读取结果，并返回 `projection_needs_rebuild` 警告；读取操作本身不静默改写存储。
- 读取历史版本时，`capture.version`、`captured_at`、`channel`、`user_intent` 和 Payload/Envelope 哈希均来自所读版本；`current_version` 和 `item_state` 表示 Item 当前已提交状态，两者不得混淆。
- `integrity: verified` 证明目标版本的 Envelope、全部 Payload 与 Payload Set，以及用于确定当前版本的 Envelope/Event 链；它不宣称顺带重哈希了其他历史版本的全部 Payload。读取另一历史版本时会对该目标版本重新完成同样证明。
- 唯一无 Event 的 N+1 尾部目录按第 3.6 节处理；latest 返回 N 并警告，显式读取 N+1 返回 `version_not_found` 且不向 sink 写字节。
- 读取操作没有提交语义，成功和失败结果都省略 `commit_state`。

## 6. `list_captures`

### 6.1 目的

按稳定顺序分页列出 Capture Item，供“捕获箱”和 Global Intake 等界面使用。

### 6.2 请求

```yaml
routing_status: "unassigned"   # 可选
created_after: null             # 可选，UTC ISO-8601
created_before: null            # 可选，UTC ISO-8601
limit: 50                       # 可选，默认 50，最大 100
cursor: null                    # 可选，服务端返回的不透明游标
```

MVP-0 不提供全文搜索、语义搜索、标签筛选、模型排序或任意字段排序。

`routing_status` 省略或为 `null` 表示不按路由状态过滤；MVP-0 非空时只接受 `unassigned`，其他值在对应状态事件和投影 schema 获批前返回 `invalid_input`。

### 6.3 成功返回

```yaml
ok: true
items:
  - capture_id: "cap_..."
    current_version: 2
    captured_at: "2026-09-01T02:10:12.456Z"
    updated_at: "2026-09-01T03:00:00.000Z"
    preview: "想到知识策展悖论可能还涉及……"
    routing_status: "unassigned"
    trust_status: "unreviewed-capture"
    envelope_sha256: "sha256:..."
next_cursor: "opaque:..."
warnings: []
```

规则：

- 固定按 `captured_at DESC, capture_id DESC` 排序，避免同一页内顺序漂移。
- `captured_at` 固定取版本 1 Envelope；`updated_at` 取当前已提交版本所匹配版本建立 Event 的 `occurred_at`；`envelope_sha256` 取当前已提交版本。筛选只作用于版本 1 `captured_at`，`created_after` 与 `created_before` 都是严格排除边界。
- 时间过滤值非空时必须是带 `Z`、毫秒精度的规范 UTC；`created_after >= created_before` 返回 `invalid_input`。`limit` 默认 50，只接受 1–100 的整数且 `bool` 无效。
- 游标固定为 `c1.<payload-base64url-no-padding>.<checksum-lower-hex>`。payload 按固定键序编码为 `{"schema":"knowledgeflow.capture-list-cursor","schema_version":1,"store_id":"store_...","query_sha256":"sha256:...","last_captured_at":"...","last_capture_id":"cap_..."}`；checksum segment 是 `lower_hex(SHA256(UTF8("knowledgeflow.capture-list-cursor.v1\n") + payload_bytes))`。它检测误传和篡改，但不是 MAC、签名或授权边界。
- 规范查询 JSON 的固定键序和形状是 `{"routing_status":"unassigned","created_after":null,"created_before":null,"order":"captured_at-desc,capture_id-desc"}`；未提供 `routing_status` 时写 `null`。`query_sha256` 是 `"sha256:" + lower_hex(SHA256(UTF8("knowledgeflow.capture-list-query.v1\n") + canonical_query_json_bytes))`。query 不包含 `cursor` 或 `limit`，因此后续页可把 limit 改为另一个 1–100 的合法值。
- 两种 JSON 都复用 Envelope 第 8.6 节的紧凑 UTF-8 规则：无 BOM、无空白/尾随换行、非 ASCII 直接使用 UTF-8，只做 JSON 必需转义；游标 payload 再使用 RFC 4648 URL-safe Base64 并移除 `=` padding。
- 游标 schema/version、编码、checksum、`store_id`、查询指纹或最后排序键任一无效都返回 `invalid_input`；游标没有 TTL。下一页严格选择 `(captured_at, capture_id)` 小于游标末项的记录。
- `preview` 是当前主文本的前 160 个 Unicode code point，保留原始换行、空白和字符值；JSON/YAML 传输只做必要语法转义，不折叠为空格、不规范化、不调用模型。MVP-0 不承诺在 grapheme cluster 边界截断，完整原文只能通过 `get_capture` 获取。
- 列表为控制内存和 I/O，只验证目录/事件/Envelope/版本链、交叉引用、规范机器字节，以及 Payload 声明大小与普通文件实际大小；只读取解码预览所需的有界 UTF-8 前缀，不对每个大 Payload 计算完整 SHA256。因此列表不声称完成 Payload attestation，前缀之后的等长篡改可能只在 `get_capture` 被发现。
- 投影缺失、损坏或落后时，从受支持的不可变 Event 历史在内存中重建状态后再筛选和返回，不信任失配投影；每个受影响 Item 返回带 `capture_id` 的 `projection_needs_rebuild`，但不写 Store。
- 发现任何不可变结构、版本建立 Event 或引用矛盾时，整个列表返回 `integrity_check_failed`，不得返回部分 `items` 或 `next_cursor`。唯一无 Event 的 N+1 尾部残留不属于该失败：列表使用 N，并返回带 `capture_id + version` 的 `incomplete_version_ignored`。
- warning 按 `(details.capture_id 或空字符串, code, details.version 或 0)` 的 Unicode code point 升序稳定返回；仅真正 Store 级、无法归属 Item 的 warning 才能省略 `capture_id`。
- 分页只对扫描期间不变的数据集保证无重复、无遗漏；不建立跨请求快照、数据库事务或 TTL。并发创建、追加或路由变化后，调用方要获得新鲜一致视图应从空 cursor 重新开始。
- 不强制返回 `total_count`，避免每次打开捕获箱都全量扫描。
- `next_cursor` 在本页之后没有更多匹配 Item 时固定为 `null`；否则锚定本页最后一个返回 Item，而不是最后一个被过滤或扫描的目录。
- Global Intake 就是把 `routing_status` 固定为 `unassigned` 的这个操作，不产生第二份文件。
- 读取操作没有提交语义，成功和失败结果都省略 `commit_state`。

## 7. `append_capture_version`

### 7.1 目的

在保留所有旧版本的前提下，为现有 Capture Item 保存一个完整的新文本版本。

### 7.2 请求

```yaml
capture_id: "cap_..."
expected_current_version: 1
text: "补充后的完整文本，不是 diff。"
channel:
  type: "app"
  instance_id: "local-desktop"
  external_ref: null
  source_created_at: null
idempotency_key: "append-0199..."
user_intent:
  target_kb_id: null
  processing_mode: null
  requested_new_kb_name: null
```

字段规则：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `capture_id` | 是 | 必须指向已存在的 Capture Item |
| `expected_current_version` | 是 | 必须等于调用时看到的当前版本 |
| `text` | 是 | 新版本的完整文本，不接受只保存 patch |
| `channel` | 是 | 记录本次追加来源 |
| `idempotency_key` | 是 | 本次追加请求的稳定身份 |
| `user_intent` | 是 | MVP-0 可以全部为 `null`；不继承或制造批准 |

### 7.3 成功回执

```yaml
ok: true
saved: true
commit_state: "committed"
capture_id: "cap_..."
event_id: "evt_..."
previous_version: 1
version: 2
primary_payload_sha256: "sha256:..."
payload_set_sha256: "sha256:..."
envelope_sha256: "sha256:..."
durability: "durable"
routing_status: "unassigned"
trust_status: "unreviewed-capture"
gbrain_sync_status: "not-requested"
warnings: []
```

规则：

- 当前版本不是 `expected_current_version` 时返回 `version_conflict`，不覆盖、不自动合并。
- 新版本目录保存完整正文；UI 可以显示 diff，但恢复不能依赖补丁链。
- 同一幂等键重试必须返回第一次成功生成的同一版本，不能再生成下一个版本。
- 新版本不继承任何针对旧版本的批准；以后所有语义批准仍必须绑定精确版本和哈希。
- 追加版本不等于路由、归档或可信知识写入。

## 8. 错误码

| 错误码 | 适用操作 | 含义 | 重试方式 |
|---|---|---|---|
| `config_not_found` | 全部 | 配置文件不存在 | 创建或选择配置后 |
| `config_invalid` | 全部 | 配置语法、schema、字段或路径值不合法 | 修正配置后 |
| `unrecognized_existing_directory` | 全部 | 配置指向的既有目录不是可识别的 Capture Store | 检查路径，不得自动接管 |
| `unsupported_store_version` | 全部 | Manifest schema/layout 版本不受支持 | 先执行未来的显式迁移 |
| `capture_store_not_initialized` | 全部 | 配置根目录不存在，或合法 Manifest 的固定骨架不完整 | 显式初始化或修复后 |
| `capture_store_unavailable` | 全部 | 配置、根目录、锁或磁盘当前无法安全访问/写入 | 修复环境后 |
| `invalid_input` | 全部 | 字段缺失、空字符串或格式错误 | 修正请求后 |
| `text_too_large` | 两个写操作 | UTF-8 字节数超过配置安全上限 | 保留原输入；调整本地上限或改用未来大文本文件入口 |
| `capture_not_found` | 读取、追加 | `capture_id` 不存在 | 检查 ID |
| `version_not_found` | 读取 | 指定版本不存在 | 检查版本 |
| `version_conflict` | 追加 | 当前版本与预期不同 | 重新读取后由用户决定 |
| `idempotency_conflict` | 两个写操作 | 同一 key 对应不同请求 | 使用新 key 或人工检查 |
| `integrity_check_failed` | 读取、写后校验 | 哈希或字节数不一致 | 停止使用并告警 |
| `atomic_commit_failed` | 两个写操作 | staging 无法完成原子提交；由 `commit_state` 区分未提交与未知 | 保留输入并使用同一幂等键重试或查询 |
| `output_write_failed` | `get_capture` | Store 数据已完整验证，但调用方正文 sink 写入失败；固定消息 `capture body output failed` | 丢弃 sink 中任何部分输出，换新或清空 sink 后重试 |

底层 `payload_hash_mismatch`、`payload_set_hash_mismatch`、`envelope_hash_mismatch` 或 `byte_size_mismatch` 统一映射为公共 `integrity_check_failed`，具体原因放在 `cause_code`。调用方不应依赖底层原因决定是否绕过完整性门禁。

提交后的可恢复问题使用警告，不占用失败错误码：

| 警告码 | 适用操作 | 含义 |
|---|---|---|
| `projection_needs_rebuild` | 全部 | 当前状态投影缺失、损坏或提交后更新失败；不可变原件仍有效 |
| `incomplete_version_ignored` | 两个读取操作 | 唯一无版本建立 Event 的 N+1 尾部目录不可见；固定消息 `incomplete capture version was ignored` |

读取 warning 的 `details` 至少包含受影响的 `capture_id`；`incomplete_version_ignored` 还必须包含整数 `version`。警告不授权 C4 修复或清理磁盘状态。

底层 `projection_update_failed` 只作为内部原因，不作为公共失败码。不可变版本是否已提交，是判断保存成功与否的边界。

## 9. 原子性和并发不变量

1. `capture_text` 成功意味着版本 `1` 和唯一匹配的 `capture.created` Event 已在最终 Item 中提交并回读校验。
2. `append_capture_version` 成功意味着新版本目录及唯一匹配的 `capture.version-appended` Event 均已提交并回读；Event 是追加的逻辑提交点，旧版本字节完全不变。
3. `get_capture` 和 `list_captures` 不修改原件、投影、状态、路由、索引或事务残留。
4. 同一 Item 的并发追加最多一个请求能以相同 `expected_current_version` 成功。
5. 回执丢失后的同幂等重试不能创建第二个 Item 或第二个新版本；不可变身份、版本和哈希字段保持一致，警告按当前投影事实生成。
6. 投影和索引丢失不得导致不可变版本丢失，也不得改变其哈希。
7. GBrain、Git、模型或网络故障不能让本地已提交原件回滚或消失。
8. 目录存在不等于版本可见；读取结果只能来自连续、Event 证明的已提交版本链。

## 10. MVP-0 验收场景

### 10.1 正常链路

1. `capture_text("A")` 返回 `capture_id = X, version = 1`。
2. `get_capture(X)` 返回精确文本 `A` 且完整性通过。
3. `append_capture_version(X, expected=1, text="B")` 返回版本 `2`。
4. `get_capture(X, version=1)` 仍返回 `A`。
5. `get_capture(X)` 返回 `B` 和 `current_version = 2`。
6. `list_captures(routing_status="unassigned")` 只列出一个 Item `X`，当前版本为 `2`。

### 10.2 保真

- 中文、emoji、组合字符、CRLF/LF、首尾空白和无结尾换行均按 `channel-exact` 保存。
- 只含空格或换行的非空字符串可以保存；真正空字符串返回 `invalid_input`。
- 哈希依据实际落盘 UTF-8 字节，不依据调用方声明。
- 4 MiB 边界两侧分别走内联和流式实现，但产生相同的保真、哈希和 Envelope 语义。
- 4 MiB 至 64 MiB 的流式输入保存为一个完整 Payload，不按块生成多个 Item。

### 10.3 幂等和并发

- 创建成功但回执丢失后，同 key 重试返回同一个 Item/Version/Event 和相同核心哈希；投影异常时返回警告但不静默重建。
- 追加成功但回执丢失后，同 key 重试返回同一个新版本。
- 两个并发请求都声明 `expected_current_version = 1` 时，只允许一个生成版本 `2`，另一个返回 `version_conflict`。

### 10.4 故障

- `capture-root` 未配置、不可写或磁盘空间不足时不得返回成功。
- 超过 64 MiB 默认安全上限时返回 `text_too_large`，不产生部分版本，并且调用方不得丢弃原输入。
- 在 staging、Event/Envelope 封存、flush、整个 Item rename 和提交后投影阶段分别模拟失败；Event 提交前失败不得产生可见 Item，投影失败不得把已提交原件改报为失败。
- GBrain 完全未安装时，四个操作全部正常工作。

## 11. 已确认的 MVP-0 默认值

| 项目 | 已确认结论 |
|---|---|
| 当前机器 `capture-root` | `E:\KnowledgeFlowData\capture-store` |
| 路径配置方式 | 机器本地配置读取，不硬编码；最终解析结果必须为绝对路径；未配置不回退 |
| 内联传输阈值 | 4 MiB UTF-8 字节 |
| 单版本默认安全上限 | 64 MiB UTF-8 字节，可由机器本地配置调整 |
| 4–64 MiB 文本 | 同一 `capture_text` 操作流式写入一个完整 Payload |
| 超过安全上限 | 不截断、不摘要、不自动拆 Item；保留原输入，调整上限或转未来文件入口 |
| 列表分页 | 默认 50，最大 100 |
| 列表排序 | `captured_at DESC, capture_id DESC` |
| 预览 | 当前正文前 160 个 Unicode code point，纯机械派生 |
| 预览换行/截断 | 保留原字符与换行；只做传输语法转义；按 code point 截断，不承诺 grapheme cluster 边界 |
| `get_capture` 正文 | 结构化元数据 + 调用方二进制 sink；完整验证后以不超过 1 MiB 的块公开 |
| 列表完整性 | 验证版本/Event/Envelope/结构与文件大小，仅读有界预览前缀；完整 Payload 哈希由 `get_capture` 证明 |
| 版本可见性 | 连续版本目录 + 唯一匹配版本建立 Event；追加 Event 是 N>1 的逻辑提交点 |
| 游标 | `c1` 规范 JSON keyset 游标，绑定 Store 与查询；无 TTL、无跨页快照 |
| 创建幂等键 | 核心可选，官方客户端默认生成 |
| 追加幂等键 | 必填 |
| C3 创建锁 | 固定 Store 级 Windows 内核锁；`journal/capture-write.lock` 可长期存在，不按文件存在或年龄清理 |
| C3 原子提交单位 | 新建时提交完整 `<capture-id>` Item 目录；追加版本边界留到 C5 |
| Event 与日志 | Event 是追加式业务事实并参与重建；运行日志只用于诊断，可轮转，不能替代 Event |
| 更新语义 | 只追加完整新版本，不提供覆盖和 patch 存储 |
| MVP-0 GBrain 状态 | `not-requested`，不建立 Delivery Request |

以上默认值及错误/提交状态模型已于 2026-09-02 获批，C3-0 六项补充行为于 2026-09-08 获批，成功回执、固定错误消息与幂等命中警告语义于 2026-09-09 完成编码前收口。C3A 契约能力和 C3B 写入基础已于 2026-09-10 分别完成；C3C 与 C3V 已于 2026-09-11 在测试持有的 Store 中先后实现并验收完整 `capture_text` 事务，C3V 当时全量为 144 项。R0.1/R0.2 随后完成初始化所有权加固，R0 后全量为 148 项；D0-F、D0G、C4-0 与 R0.3D 也已闭合。R0.3D 新增 3 项特征测试后当前全量 159 项通过；证据要求下一步另行授权 R0.3F，完成后才可授权 C4A。读取/追加公开操作、生产 Store、GBrain 与路由均未实现。
