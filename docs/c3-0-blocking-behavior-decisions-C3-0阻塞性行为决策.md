# C3-0：`capture_text` 阻塞性行为决策

> 状态：Approved Design；六项决策已人工确认，C3A–C3V 已完成，C3 `capture_text` 已通过本阶段验收，但整体不是 Effective 规范<br>
> 整理日期：2026-09-08<br>
> 确认日期：2026-09-08<br>
> 原子 Event 补充确认日期：2026-09-08<br>
> C3 编码前收口日期：2026-09-09<br>
> C3A/C3B 完成日期：2026-09-10<br>
> C3C 完成日期：2026-09-11<br>
> C3V 完成日期：2026-09-11<br>
> 适用范围：C3 第一个本地文本捕获事务<br>
> 授权边界：2026-09-08 的本次确认只批准设计；后续 C3A–C3V、R0.1/R0.2、D0-F、D0G、C4-0、R0.3D、R0.3F、C4、C5-0、C5A–C5V 与 C6A–C6C 已分别完成并同步至 `origin/main`；业务事务崩溃恢复、派生状态重建与 Store 迁移已通过定向及远端验收，但 C7、生产配置和生产 Capture Store 仍需独立授权

## 0. 结论先行

C0–C2 已经提供配置、Store 骨架、受限 YAML、Envelope、哈希、Windows 内核锁、耐久化原语以及初始化崩溃恢复。C3 不需要另设新的基础设施里程碑，但可以按本事务需要小幅扩展现有 codec、锁、durability 与 Store 内部原语；在实现 `capture_text` 前必须冻结六项会改变磁盘格式、成功边界、幂等结果或并发结果的行为：

1. 文本输入和流式处理边界。
2. 新 Capture Item 的原子提交单位。
3. `capture.created` 与 `capture.yaml` 的最小 v1 格式。
4. Capture 写锁的范围及锁文件语义。
5. 幂等身份的无歧义编码。
6. MVP-0 的操作者身份和时间格式。

本文不解决查询、追加版本、路由、策展、GBrain、Git 备份、CLI、Harness 或 UI。六项决策已于 2026-09-08 获得人工确认，作为 C3 后续实现依据；是否开始编码仍服从独立的 C3 授权门禁。

## 1. 术语澄清

### 1.1 锁

锁是操作系统维护的一段临时排他状态。一个进程持有排他锁时，另一个进程不能同时进入受保护的写入区。锁的目的不是保存知识，而是避免两个写入同时判断“可以创建”，最后生成重复或互相覆盖的结果。

### 1.2 锁文件

锁文件是供进程打开并向操作系统申请文件锁的固定落点，例如：

```text
<capture-root>/journal/capture-write.lock
```

它只是锁的载体，不是“当前是否有人持锁”的证明。文件可以长期存在；真正的持锁事实由当前进程是否仍持有操作系统文件句柄和内核锁决定。

### 1.3 过期锁或陈旧锁

如果系统仅凭“某个文件存在”判断有人持锁，进程崩溃后遗留的文件会让系统永久误判，这种遗留状态通常叫 stale lock（陈旧锁、俗称过期锁）。

本项目已经采用 Windows 内核文件锁：进程正常关闭或崩溃后，操作系统会释放锁；锁文件本身可以继续存在。因此 C3 不应按文件年龄、PID 文本或文件是否存在来删除所谓“过期锁”。强行删除锁文件可能让两个进程锁住不同文件对象，反而破坏互斥。

### 1.4 Payload、Envelope、Event 与 Projection

- `payloads/primary.txt`：用户保存的正文原件。
- `envelope.yaml`：与某个不可变版本一起封存的机器清单，记录“保存了什么、从哪里来、是哪一版、哈希是什么”。
- `events/<event-id>.yaml`：状态变化的追加记录，例如“这个 Capture 已创建”。
- `capture.yaml`：方便 UI 快速读取的当前状态摘要，可以重建，不是审计真源。

可以把 Payload 理解为包裹内容，把 Envelope 理解为和包裹一起封存的装箱单。正文损坏、文件被换掉或元数据指向了错误版本时，系统可以通过 Envelope 中的大小、哈希和身份发现不一致。Envelope 不负责保存不断变化的 GBrain 状态、路由结果或备份次数。

### 1.5 Event 与运行日志

Event 是具有稳定 schema 和业务身份的持久状态事实，例如 `capture.created`。它属于 Capture Store，需要追加保存、参与审计和投影重建，不能因日志轮转或排障结束而删除。

运行日志是程序为了排障和运维记录的诊断信息，例如“开始获取写锁”“某次 flush 失败”。它不参与 Capture 身份、幂等判断或状态重建，可以按明确的保留策略轮转和清理，而且不得包含正文、原始幂等键、凭据或敏感绝对路径。

二者可以互相引用：运行日志可以只记录 `event_id`、公共错误码和安全的关联 ID，帮助定位某个 Event 的执行过程；但日志不能替代 Event，Event 也不用于保存堆栈、性能采样等诊断噪声。

## 2. C3D-01：文本输入和流式处理

### 当前冲突

现有操作契约同时写了“入口已经解码完成的字符串”和“超过 4 MiB 改用流式 staging”。如果核心只接收一个已经完整存在内存中的字符串，“流式入口”的类型、UTF-8 校验和一次读取语义并未确定。

### 已确认

1. `capture_text` 是一个业务操作，但允许两种机械输入形态：Python `str`，或提供 `read(size)` 的二进制字节流。
2. 两种输入共享同一个有界分块写入器，最终都写成一个 `payloads/primary.txt`，不产生两个事务实现。
3. `str` 按 UTF-8 分块编码；字节流使用严格 UTF-8 增量校验。遇到非法 UTF-8 时返回 `invalid_input`，不使用替换字符继续保存。
4. 正文不做 trim、Unicode 规范化、换行转换、错字修正、摘要、标题或拆分。
5. 空正文拒绝；仅由空格或换行组成的非空正文允许保存。
6. 输入开头的 UTF-8 BOM 字节或 `U+FEFF` 拒绝，不静默删除，从而同时满足“无 BOM 落盘”和“不得悄悄改正文”。
7. `inline_text_threshold_bytes` 只决定内部内联/分块路径，不改变 Capture 身份；默认 4 MiB。
8. `max_text_version_bytes` 是硬提交上限；默认 64 MiB。读取到上限加 1 byte 即返回 `text_too_large`，不得截断或产生可见 Item。
9. 字节流不要求可回退或可重复读取。实现必须支持一次读取：先流式写入由本次事务拥有的 staging 文件并计算候选哈希，再进行幂等判定；最终成功仍以 staging 文件和最终文件的磁盘回读结果为准。

### 明确延后

- CLI 如何从 stdin 或文件描述符提供字节流。
- URL、PDF、图片和任意文件 Payload。
- 超过配置上限后的自动拆分、摘要或外部对象存储。

## 3. C3D-02：新 Item 的原子提交单位

### 当前冲突

最终布局是：

```text
items/YYYY/MM/<capture-id>/versions/000001/
```

但现有事务文字要求直接把 staging 目录原子重命名为 `versions/000001/`。新 Item 的 `<capture-id>/versions/` 尚不存在；如果为了重命名而提前创建它，就会在最终 `items/` 中暴露一个没有完整版本的半成品 Item。

### 已确认

新建 Item 时，原子提交单位是完整的 `<capture-id>` Item 目录，而不是单独的 `versions/000001`：

```text
<capture-root>/.staging/<transaction-id>/item/
├── versions/
│   └── 000001/
│       ├── envelope.yaml
│       └── payloads/
│           └── primary.txt
└── events/
    └── <event-id>.yaml

              同盘、不得覆盖的原子 rename
                              ↓

<capture-root>/items/YYYY/MM/<capture-id>/
├── versions/
│   └── 000001/
│       ├── envelope.yaml
│       └── payloads/
│           └── primary.txt
└── events/
    └── <event-id>.yaml
```

具体成功边界：

1. staging 必须由本次事务创建并记录所有权，且与 `items/` 位于同一文件系统。
2. Payload、Envelope 与 `capture.created` Event 在 staging 中写入、flush、回读并通过 schema、引用和哈希校验。
3. `items/YYYY/MM/` 年月父目录可以机械创建；年月来自服务端 `received_at`，空的年月目录不构成 Capture Item。
4. 在持有 Capture 写锁时，将完整 `item/` 以“目标不得已存在”的方式原子 rename 为最终 `<capture-id>/`。
5. rename 后从最终路径再次读取版本、Payload、Envelope 与创建 Event；只有可以证明这些最小审计原件同时存在且校验通过时，才能返回 `saved: true`。
6. rename 前失败为 `not-committed`；rename 附近无法证明结果时为 `unknown`；不得用猜测返回失败或成功。
7. `capture.created` 与不可变版本一起提交；Event 写入、校验或引用不一致发生在 rename 前时不得提交 Item。只有 `capture.yaml` 在 Item 提交后生成，投影失败时返回成功加 repair warning。
8. 以后 `append_capture_version` 只原子提交新的版本目录；该规则留到 C5 冻结，不在 C3 实现。
9. 若新分配的 `<capture-id>` 最终目录在 rename 前已经存在，不得覆盖、采用或把它冒认为本请求；由于当前 staging 尚未提交，固定返回可重试 `atomic_commit_failed + commit_state: not-committed`。

## 4. C3D-03：最小 State Event 与 State Projection v1

### 设计时冲突（已由本节冻结）

C3 设计进入本节前，完成条件虽已包含版本、Envelope、事件、投影和回执，但当时只有 `capture.yaml` 示例，没有可直接实现的 State Event schema，也没有明确哪些投影字段在 C3 固定；本节随后冻结该缺口，C3A 已实现相应 schema 契约。

### 已确认：`capture.created`

路径：

```text
items/YYYY/MM/<capture-id>/events/<event-id>.yaml
```

最小字段和固定顺序：

```yaml
schema: "knowledgeflow.capture-event"
schema_version: 1
event_id: "evt_<uuidv7>"
event_type: "capture.created"
capture_id: "cap_<uuidv7>"
version: 1
envelope_sha256: "sha256:<64位小写十六进制>"
occurred_at: "2026-09-08T00:00:00.000Z"
actor:
  type: "user"
  actor_id: "local-user"
```

约束：

- 一个事件一个文件，使用不得覆盖的创建方式；旧事件不修改。
- `event_id` 必须与版本 Envelope 中的 `event_id` 一致。
- `capture_id + version + envelope_sha256` 必须指向同一 staging Item 内已经回读验证通过的版本。
- `occurred_at` 在最终 flush 与原子 rename 前固定，表示本次创建事件的逻辑发生时间；只有整个 Item rename 成功后，该 Event 才进入正式可见状态。
- Event 写入、schema 校验或交叉引用失败时不得提交 Item；不能在提交后再凭 Envelope 猜测无法恢复的原始 `occurred_at`。
- C3 的 `event_type` 只允许 `capture.created`；其他事件类型以后分别提升 schema 能力，不提前加入空字段。

### 已确认：`capture.yaml`

C3 采用现有 `knowledgeflow.capture-state` v1 示例的完整字段，初始固定值如下：

```yaml
schema: "knowledgeflow.capture-state"
schema_version: 1
capture_id: "cap_<uuidv7>"
current_version: 1
current_envelope_sha256: "sha256:<64位小写十六进制>"
durability:
  status: "durable"
  verified_at: "2026-09-08T00:00:00.000Z"
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
updated_at: "2026-09-08T00:00:00.000Z"
```

约束：

- 使用受限 YAML codec、严格 schema 和规范化发射。
- 每次更新采用“同目录临时文件—flush—原子替换”。
- `capture.yaml` 丢失或损坏不等于原件丢失；它不得反向覆盖 Envelope 或 Payload。
- C3 不执行路由、GBrain 或 Git，只写上述初始状态。

## 5. C3D-04：Capture 写锁和锁文件

### 当前冲突

Envelope 事务旧文字要求至少按幂等身份加锁，并清理“陈旧锁”；C2 已经确认锁文件可长期存在且只能以 Windows 内核锁作为持锁真相。若 C3另做一套 PID/时间戳锁，会与 C2 的已验证语义冲突。

### 已确认

1. C3 只使用一个 Store 级写锁：

   ```text
   <capture-root>/journal/capture-write.lock
   ```

2. 复用 C2 已实现并测试的 Windows 内核排他锁和等待机制，不引入第二套锁协议。
3. 在获得完整 Payload 候选哈希后、查询幂等记录前获取锁；持有到包含创建 Event 的最终 Item 提交、回读以及投影尝试结束。
4. 默认等待上限为 10 秒。超时返回可重试的 `capture_store_unavailable`，并且 `commit_state: not-committed`。
5. 锁文件允许永久存在；进程退出或崩溃后由操作系统释放内核锁。实现不得按文件年龄、PID 或文件存在性删除它。
6. Store 级锁会串行化写入，但 MVP-0 是单机个人系统，先用简单正确的互斥换取可验证行为。每幂等键锁、每 Item 锁和并行写入优化延后。

## 6. C3D-05：幂等身份编码和查询

### 当前冲突

现有公式直接拼接 `channel_type + channel_instance + operation`，但没有分隔符约束和字段长度限制。字段中如果出现冒号或换行，不同输入可能形成同一拼接文本。

### 已确认

1. `channel.type` 和 `channel.instance_id` 必须是 1–64 个 ASCII token 字符：小写字母、数字、点、下划线或连字符；不得包含冒号、斜杠、反斜杠、空白或换行。
2. C3 的 `operation` 固定为 `capture_text`。
3. `scope` 规范字符串固定为：

   ```text
   <channel.type>:<channel.instance_id>:capture_text
   ```

4. `idempotency_key` 可以省略；提供时必须是非空字符串，UTF-8 编码不超过 512 bytes。
5. Envelope 中不保存原始 key，固定保存：

   ```text
   key_sha256 = SHA256("knowledgeflow.idempotency-key.v1\n" + UTF8(idempotency_key))
   ```

6. 幂等身份是二元组 `(scope, key_sha256)`，不再使用有歧义的裸字符串拼接公式。
7. 同一幂等身份且请求指纹相同，必须先从最终路径回读并验证不可变 Envelope、Payload 与 `capture.created` Event，然后返回原 `event_id + capture_id + version + primary_payload_sha256 + payload_set_sha256 + envelope_sha256`；任一不可变原件不能通过验证时不得返回成功。
8. `warnings` 不属于上述不可变回执身份。幂等命中时只读检查当前 `capture.yaml`：投影存在、规范且与不可变记录一致时返回空警告；投影缺失、损坏或不一致时返回 `projection_needs_rebuild`。C3 不在幂等命中路径静默重建投影，重建能力留到 C6/M0-E11。
9. 请求指纹不同则返回 `idempotency_conflict`。不提供 key 时，每次调用都是新的主动保存；相同正文允许形成多个 Capture Item。
10. C3 不冻结或写入新的幂等索引格式。在 Store 写锁内扫描不可变 Envelope 得到事实；索引仅作为以后可重建的性能优化。

### 成本取舍

扫描在 Capture 数量很大时是 O(n)，但它避免 C3 再引入一套需要崩溃恢复的磁盘索引。先证明正确性，达到实际性能瓶颈后再增加可重建索引。

## 7. C3D-06：操作者、渠道与时间

### 当前冲突

Envelope 强制要求 `actor`，但现有 `capture_text` 调用并没有可信登录身份上下文；时间字段在文档中要求 UTC，当前基础 schema 仍只检查非空字符串。

### 已确认

1. MVP-0 是单用户本地模式，C3 由核心固定写入：

   ```yaml
   actor:
     type: "user"
     actor_id: "local-user"
   ```

2. 调用者不能通过普通请求伪造 `actor`。以后引入登录或多用户身份时，必须设计单独的可信身份上下文并提升契约。
3. `received_at` 在核心开始接收操作时生成；`captured_at` 在最终 Envelope 封存前生成；`occurred_at` 在创建 Event 写入 staging、最终 flush 与原子提交前生成。Event 只有随 Item rename 成功后才成为正式事实。
4. 核心生成时间固定为 UTC、带 `Z`、毫秒精度：`YYYY-MM-DDTHH:MM:SS.mmmZ`。
5. `channel.source_created_at` 可以为 `null`；非空时必须已经是同一规范 UTC 格式，C3 不猜测时区、不把本地时间静默解释成 UTC。
6. `channel.external_ref` 可以为 `null`；非空时 UTF-8 编码不超过 2048 bytes。它只作为来源证据，并进入请求指纹，不用于目标路径。
7. `user_intent` 仍只能记录用户明确表达的值；C3 不根据正文推断 KB、处理模式或新 KB 名称。

## 8. 冻结后的建议事务顺序

六项决策确认后，C3 的最小事务顺序固定为：

```text
T0  校验机械元数据，建立本事务独占 staging
T1  单次流式写入正文，严格校验 UTF-8、大小并计算候选哈希
T2  生成 Payload Set 与 Request Fingerprint
T3  获取 Store 级 Windows 内核写锁
T4  扫描不可变 Envelope；命中时验证不可变原件并只读检查投影，返回稳定身份/哈希字段和当前警告
T5  分配 capture_id/event_id，构造包含创建 Event 的完整 staging Item
T6  写入并封存 Envelope 与 capture.created，flush、回读和复算全部哈希/引用
T7  将完整 Item 原子 rename 到最终 <capture-id> 目录，最终回读版本与 Event
T8  原子写 capture.yaml；投影失败只产生 repair warning
T9  释放内核锁，返回结构化回执
```

实现必须安全清理由本事务明确拥有且尚未提交的 staging；不得根据模糊名称、文件年龄或全局扫描删除其他进程的暂存数据。

## 9. C3 验收边界

确认本文不等于接受“只要 happy path 能写文件”。C3 至少需要验证：

- 中文、英文、emoji、LF/CRLF、首尾空白和无末尾换行逐字节往返。
- 空正文、非法 UTF-8、BOM、4 MiB/64 MiB 边界行为。
- 字符串与非 seekable 字节流进入同一事务实现。
- 每次无 key 主动保存产生新 Item。
- 同 key、同指纹返回同一 Item/Version/Event 和相同核心哈希；`warnings` 按重试时的投影事实生成，同 key、不同指纹明确冲突。
- 两个进程并发使用同一 key 时最多产生一个 Item。
- 新分配 ID 的最终目录已存在时不覆盖、不冒认，返回可重试 `atomic_commit_failed + not-committed`。
- `saved: true` 必须对应最终路径中可回读、哈希正确的不可变版本和匹配的 `capture.created` Event。
- 创建 Event 写入或校验失败时不提交 Item；只有提交后的 `capture.yaml` 投影失败返回成功加 repair warning。
- GBrain、网络、KB、SOP、模型和生产 Capture Store 均不参与测试。

完整的逐故障点崩溃矩阵仍属于 C6；C3 不得因此宣称已经完成全部断电或恢复保证。

## 10. 明确延后的内容

以下问题不会改变 C3 的第一次本地保存结果，因此不应阻塞 C3：

- 幂等索引的磁盘格式和增量维护。
- 每个幂等键、每个 Item 的细粒度锁。
- `get_capture`、`list_captures`、`append_capture_version`。
- 投影/索引的自动重建命令。
- Capture Store 的 Git 仓库拓扑和备份计划。
- 路由提案、SOP-000A/SOP-001/SOP-002。
- GBrain 镜像、账号、API key 和远程权限。
- DeepSeek Harness、CLI、Obsidian 式 UI 和状态回滚交互。
- 生产配置文件与 `E:\KnowledgeFlowData\capture-store` 的创建。

## 11. 确认记录与后续门禁

以下六项已于 2026-09-08 获得人工确认：

- [x] C3D-01：字符串与二进制 UTF-8 流共享有界流式写入器，BOM 拒绝且不静默修改。
- [x] C3D-02：新建时原子提交包含版本、Envelope 与 `capture.created` 的完整 Item；只有 `capture.yaml` 是可恢复的提交后步骤。
- [x] C3D-03：只冻结 `capture.created` 和初始 `capture-state` 两个最小 v1 schema。
- [x] C3D-04：复用 Store 级 Windows 内核锁；锁文件长期存在，不清理所谓过期锁。
- [x] C3D-05：使用规范 scope、带域前缀的 key 哈希和 Envelope 扫描，不在 C3 预建索引。
- [x] C3D-06：MVP 固定 `user/local-user`，机器时间使用规范 UTC 毫秒格式。

设计确认后的执行顺序是：

1. 把决策同步进 Capture Envelope、操作契约、实现拆解和编码执行方案，消除旧冲突并补充 golden fixture 要求。
2. 对文档链接、状态、旧冲突措辞和授权边界做一致性复核。
3. C3A/C3B 已在后续独立停点完成，C3C/C3V 已于 2026-09-11 闭合并验收完整 `capture_text` 事务；C4、C5 与 C6 也已闭合并版本化。截至 C6C `ea8f84e` 已同步到 `origin/main`，Windows CI 运行 `35319645501` 首次通过；下一功能门禁为需单独授权的 C7 受限 CLI。

补充确认记录：2026-09-08 进一步确认 `capture.created` 必须与 Item 原子提交，避免提交后 Event 写入失败时无法精确恢复原始 `occurred_at`；该修正不改变 C3 编码与生产初始化仍需另行授权的门禁。

编码前收口记录：2026-09-09 统一成功回执字段和固定错误消息，明确“同一回执”只要求不可变身份、版本和哈希字段稳定，`warnings` 反映重试时观察到的投影事实；幂等命中不得静默重建投影。该收口仍不授权 C3 编码或生产初始化。

实现进度记录：2026-09-10 完成 C3A 契约能力（`346164d`）与 C3B 写入基础（`8050d88`），全量测试从进入 C3 前的 93 项增至 122 项。两批均未形成公开 `capture_text` 或正式 Item；该时点停在 C3C 独立授权前。

C3C 完成记录：2026-09-11 公开 `capture_text` 并闭合 T0–T9，在缩小阈值下覆盖 CT-01–CT-24 的完整功能分支，全量测试增至 140 项。真实 4/64 MiB、加强版 Windows 竞态/故障验收和固定验收命令仍留在 C3V；生产配置与生产 Store 未创建。

C3V 完成记录：2026-09-11 以运行时生成的真实 4/64 MiB 边界、可观测非 seekable 流、锁边界双进程同 key 竞争、默认 10 秒写锁超时和加强版故障磁盘证据完成独立验收，全量测试增至 144 项。生产源代码和既有公共/磁盘契约未改动；生产配置与生产 Store 仍未创建。

R0 加固记录：2026-09-11 以 `92a37b3` 修复初始化事务 marker 过早删除问题，以 `79515ed` 将配置临时文件绑定完整请求身份；INIT-17–19 与 FI-07 将全量测试增至 148 项。两项修复只加固初始化所有权和恢复边界，不改变 C3 公共操作或磁盘契约；生产配置与生产 Store 仍未创建。

R0.3D 记录：2026-09-13 新增 3 项特征测试，确认未知候选 `stat` 失败会阻断幂等重开、二次清理身份失败会遮蔽原始阶段、durability 当前只缺 WinError 32/33 的可重试分类；设计权威以 C-032–C-034 冻结 R0.3F 边界。当前全量 159 项通过，未修改生产代码或 C3 契约，并已通过独立本地提交闭合且未 push。

R0.3F 记录：2026-09-13 按 C-032–C-034 完成三项局部实现和 4 项新增负向回归，把 R0.3D 的 3 项特征测试转换为目标行为；当时全量 163 项普通与严格模式均通过，未改变 C3 数据格式、写入提交点或公开 Capture 操作。本批已通过独立本地提交闭合且未 push。

C4A 记录：2026-09-13 在不修改顶层公开入口和 `operations.py` 的边界内完成读取 schema、模型、游标 codec、版本链纯原语与两版本 golden；新增 19 项后当时全量 182 项普通与严格模式均通过，独立提交 `06cff02` 后续已 push。

C4B/C4C/C4V 记录：2026-09-13，C4B `get_capture` 与 C4C `list_captures` 分别以独立提交 `666ba18`、`231ad09` 完成并 push；2026-09-14，C4V 新增 2 项公共 API 组合验收并重跑 GET/LIST/C3V 目标矩阵，全量增至 214 项，随后以独立提交 `1e38f2f` 闭合并 push。三批均只使用测试持有的临时 Store，未创建生产配置或 Store。C5-0 同日完成追加契约内容与本地验证，不修改本文件的 C3 行为。
