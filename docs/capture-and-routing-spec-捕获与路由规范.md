# KnowledgeFlow 捕获与路由规范

> 状态：Approved Design；C1 捕获基础原语已实现，路由流程尚未实现<br>
> 整理日期：2026-08-31<br>
> 确认日期：2026-09-01<br>
> 作用：定义内容从任意入口被立即保存，到确定知识库归属和后续处理方式的最小闭环<br>
> 边界：本文件不定义策展地图内部结构，不执行可信 wiki 写入；主题优先级见[设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)

## 0. 与其他文档的关系

本规范位于 [需求与治理基线](requirements-and-governance-baseline-需求与治理基线.md) 和 [SOP-000A](sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md) 之间：

```text
任意入口
  -> 本规范：捕获、暂存、路由、选择处理方式
  -> 需要新 KB 时：SOP-000A
  -> 需要深度策展时：SOP-001
  -> 策展方案获批后：SOP-000B / SOP-002（待重构）
```

本文优先解决此前没有闭环的五个问题：

1. 捕获时不知道属于哪个 KB，原料先放哪里。
2. 已明确目标 KB 时，是否还需要人工重复确认。
3. 模型可以如何推荐路由，但不能擅自决定最终归属。
4. “路由到 KB”与“提升为可信知识”如何彻底分开。
5. 从 Global Intake / GBrain 到 `inbox/`、`raw/` 时，如何保证不丢失、可重试、可回滚。

## 1. 定位与目标

捕获与路由层是整个系统的入口治理层。它必须同时满足两个看似相反的要求：

- **捕获足够快**：用户不需要先回答领域、标签、页面类型等问题，原始内容先可靠保存。
- **归属足够慎重**：模型不能因为一次相似度判断，就把内容永久归入某个 KB、创建新 KB 或写入可信 wiki。

该层的输出不是知识页面，而是以下三类结果之一：

1. 一个尚未分配 KB 的安全捕获项。
2. 一个已经由用户授权、进入某个 KB 待处理队列的捕获项。
3. 一个待人工审核的路由/处理建议。

## 2. 四个必须分开的概念

### 2.1 捕获落点

捕获落点回答“原始内容现在安全保存在哪里”。规范答案固定为：**本地 Capture Store**。Global Intake 和 KB Inbox 是 Capture Item 的逻辑队列/路由状态，GBrain 是可选异步镜像；三者都不与 Capture Store 竞争原件身份。

### 2.2 知识库归属

知识库归属回答“这个捕获项由哪个 KB 负责后续处理”。它可以是零个、一个或多个 KB，但模型推断的归属必须由人确认。

### 2.3 处理方式

处理方式回答“进入待处理范围后，下一步做什么”。最小分为：

- 只保留捕获。
- 归档为不可变原料。
- 启动深度策展。
- 形成提升为可信知识的提案。

### 2.4 信任等级

信任等级回答“查询和写作时能否把它当作已经确认的知识”。捕获、归属和 GBrain 可检索都不自动提高信任等级。

> 核心结论：**保存成功 ≠ 已有归属；已有归属 ≠ 已策展；已策展提案 ≠ 可信入库。**

## 3. 核心原则

### R1：先可靠保存，再做任何模型判断

捕获热路径不得等待摘要、标签、embedding、KB 推荐、策展分析、GBrain 或 Git。只有本地 Capture Store 中的原始载荷、不可变 Envelope 和可恢复的最小审计身份完成原子提交后，系统才能向用户报告“已保存”。

### R2：用户明确指定目标即构成路由授权

如果用户在捕获时明确说“放入 KB X”，系统可直接执行到 KB X 的机械路由，不再重复询问。该授权只覆盖路由和原料暂存，不覆盖 wiki 写入、SCHEMA 修改或领域扩展。

### R3：模型推荐永远只是提案

模型可以推荐已有 KB、建议新建 KB、建议处理轨道，但不得直接应用。提案必须绑定捕获项的精确版本和候选目标。

### R4：未知归属不能阻塞捕获

不知道放哪里时，Capture Item 保持在本地 Capture Store，状态为 `unassigned`，并因此出现在 Global Intake 视图中。系统不得为了“保持整洁”而拒绝保存，也不得随意挑选一个最像的 KB。

### R5：路由不等于语义提升

路由只决定责任范围和待处理队列。即使用户明确选择了 KB，内容仍是 `unreviewed` 或 `raw-source`，不能因此成为可信 wiki 页面。

### R6：原始版本不可被模型覆盖

模型生成的标题、摘要、转写修订、分类和关系只能保存在派生区或提案中。原始文本、文件或音频按版本保留，所有后续授权都绑定具体哈希。

### R7：失败时宁可保持未路由，也不能丢失

路由、GBrain 同步或 Git 提交失败时，捕获项仍留在安全暂存层，并显示失败状态。系统不得在目标写入尚未验证前删除唯一原件。

### R8：未审核内容与可信搜索隔离

GBrain 可以立即索引低摩擦捕获，但必须将其置于单独的未审核查询范围；默认可信知识查询不得把它与正式 KB 内容混合返回。

## 4. 术语

| 术语 | 定义 |
|---|---|
| Capture Event | 一次保存动作；即使内容重复，也可能是不同的用户事件 |
| Capture Item | 被保存的逻辑对象，拥有稳定 `capture_id` 和一个或多个不可变版本 |
| Capture Version | Capture Item 的一个不可变内容版本；后续编辑新增版本而不覆盖旧版 |
| Payload | 用户提供的原始文本、URL、文件、音频或会话快照 |
| Capture Envelope | 本地不可变版本的数据契约：稳定 ID、版本、时间、来源、Payload 清单、哈希、意图和投递请求；具体字段以 [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md) 为准 |
| Capture Store | 保存 Capture Item、不可变 Version、Payload、Envelope、事件和可重建投影的本地物理存储 |
| Global Intake | `routing: unassigned` 的 Capture Item 形成的全局未审核逻辑队列；它不是知识库，也不是第二份规范原件 |
| KB Inbox | 已经明确由某个 KB 负责、但尚未完成原料归档或策展的队列 |
| Route Proposal | 模型提出的候选 KB 和处理方式，只能待审，不能自行执行 |
| Route Record | 用户明确指定或批准后形成的不可变路由审计记录 |
| Materialize | 将捕获项的精确版本复制/导出到 KB `inbox/` 或 `raw/` 并验证哈希 |
| Promote | 从捕获/原料形成可信知识的语义提升；必须另走提案和审核 |

## 5. 逻辑架构

### 5.1 总流程

```text
QQ / App / 浏览器 / 文件 / API / 对话 / 语音
                    │
                    v
             Capture Gateway
                    │
                    v
       本地 Capture Transaction
                    │
                    v
 Capture Store：Payload + Envelope + 审计身份
                    │
             返回 saved: true
                    v
       Global Intake / KB Inbox 状态视图
                    │
          ┌─────────┴─────────┐
          │                   │
          v                   v
 GBrain 异步未审核镜像    路由/处理提案
                              │
                       人工选择或批准
                    │
        ┌───────────┼────────────┐
        v           v            v
     已有 KB      新建 KB       暂缓/归档
        │           │
        │       SOP-000A
        └──────┬────┘
               v
     capture-only / raw-source / SOP-001
```

### 5.2 “GBrain 先写后审”的准确含义

“先写后审”指用户无需在保存前完成语义审核，内容会先成为本地 `unreviewed-capture`；若启用 GBrain，系统随后把它异步复制到 GBrain 的未审核范围。它不表示 GBrain 是第一原件，也不表示 GBrain 页面一经写入就成为可信知识。

顺序固定为：

```text
本地 Capture Store 原子保存成功
  -> 向用户返回成功
  -> 若已显式启用，则异步请求 GBrain 镜像；MVP-0 跳过
  -> 后续再进行路由、提取和审核
```

GBrain 页面损坏、被编辑或全部丢失时，系统从本地不可变版本重建；不得把 GBrain 页面反向覆盖为本地 Payload。

### 5.3 本地 Capture Store 与 Global Intake

Capture Store 的目录、不可变边界和 outbox 结构以 [Capture Envelope v1 第 7 节](capture-envelope-v1-捕获信封数据契约与原子保存事务.md#7-推荐物理布局) 为准，本规范不再维护第二套简化目录草案。

Global Intake 推荐实现为对 Capture Item 当前状态的查询/投影视图：

```text
routing: unassigned  -> 出现在 Global Intake
routing: assigned    -> 出现在对应 KB Inbox
routing: archived    -> 移出日常待处理视图，但保留历史和原件
```

为了性能可以建立可重建索引，但不得复制出另一份无法判定真假的“Global Intake 原件”。`capture.yaml`、`envelope.yaml`、`events/` 等机器契约名称是双语命名规则的明确例外。

## 6. 捕获热路径

### 步骤 C0：接收输入

入口只需提交原始载荷，并可选提交：用户标题、目标 KB、处理意图、来源 URL 和敏感级别。缺少这些可选项不影响保存。

### 步骤 C1：分配身份并处理重试

1. 生成稳定 `capture_id`。
2. 接收入口提供的 `idempotency_key`；同一重试键不得产生第二份捕获。
3. 对同一捕获的后续编辑生成新版本，不静默覆盖旧版本。

### 步骤 C2：持久化原始载荷

1. 文本按用户原文保存。
2. 文件和音频保存原始字节。
3. URL 至少保存原始 URL、捕获时间；抓取快照作为独立 Payload 或派生版本保存。
4. 会话保存明确的消息范围和原始顺序。
5. 计算原始载荷 SHA256。

### 步骤 C3：写入最小机器元数据

`capture.yaml` 是本地可重建的当前状态投影；不可变字段和完整示例以 Capture Envelope v1 为准。以下片段只说明本规范使用的路由字段，不另立数据契约：

```yaml
format_version: 1
capture_id: "<uuid>"
version: 1
captured_at: "<ISO-8601 timestamp>"
captured_by: "<user-or-entry-id>"
channel: "app|qq|browser|api|file|conversation|voice"

payload:
  kind: "text|url|file|audio|conversation"
  path: "payload.md"
  sha256: "<sha256>"
  source_url: null

user_intent:
  target_kb_id: null
  processing_mode: null

state:
  durability: durable
  routing: unassigned
  trust: unreviewed

gbrain:
  sync_status: pending
  page_id: null
```

`user_intent` 只能记录用户明确表达的内容，不能把模型推断伪装成用户意图。模型建议必须进入独立 Route Proposal。

### 步骤 C4：立即确认

系统只在持久化成功后返回：

- `capture_id`
- 保存成功/失败
- 当前落点
- 用户已明确指定时的目标 KB
- 原始记录所在后端，以及必要时的 GBrain 同步状态

确认消息不等待模型生成标题、摘要、标签或路由。

### 步骤 C5：异步机械处理

允许自动执行：

- MIME/文件类型识别。
- SHA256 和大小计算。
- URL 规范化和抓取重试。
- OCR、语音转写、HTML 转 Markdown，但结果必须标记为派生文本。
- GBrain 捕获持久化/同步、embedding 和索引。
- 精确重复检测和状态报告。

不允许自动应用：

- AI 标题覆盖用户标题或原文件名。
- KB 归属。
- 领域、标签、关系和页面类型。
- Wiki 页面创建、合并或改写。

## 7. 不同输入的默认捕获方式

| 输入 | 用户未指定 KB 时 | 用户明确指定 KB 时 | 默认处理轨道 |
|---|---|---|---|
| 临时灵感、随手笔记 | Global Intake + GBrain 未审核 inbox | GBrain 未审核捕获，并在 KB `inbox/` 建立待处理记录 | `capture-only` |
| 短对话/语音想法 | 保存原始消息/音频，转写为派生文本；进入未审核层 | 同上，并关联指定 KB | `capture-only` |
| URL、网页剪藏 | 保存 URL 与抓取快照到 Global Intake | 进入 KB `inbox/`，验证后可归档 `raw/articles/` | `raw-source` |
| PDF/文档/附件 | 原文件进入 Global Intake | 进入 KB `inbox/`，验证后可归档相应 `raw/` | `raw-source` |
| 长文、论文、研究资料 | 先保存，等待选定 KB | 先进入 KB 原料链；用户要求深度整理或该 KB 已有人为配置的长文规则时启动 SOP-001 | `raw-source`；满足触发条件后转 `deep-curation` |
| API/自动搜集结果 | 保存原始响应和来源，不信任机器论断 | 进入 KB 的搜集待审队列或 `raw/` | `raw-source` + 主张提案 |

表中的“默认轨道”只决定保存后的建议动作。SOP-001 生成的是待审策展地图，因此不需要在生成地图前审核内容；但它需要一次性用户意图、后续人工选择或用户预先配置的 KB 规则作为触发依据，以免“只想收藏”也自动产生模型成本。

## 8. 路由授权的三种来源

### 8.1 用户在捕获时明确指定

示例：“把这篇文章保存到 Agent 学习库”。这已经是精确路由授权，可机械执行，无需再次询问。

系统仍需验证：

- 目标 `kb_id` 存在。
- KB 未被归档、锁定或设为只读。
- 用户拥有捕获/原料写入权限。
- 授权绑定当前捕获版本。

### 8.2 用户稍后手动选择

用户在 Global Intake 中选择一个或多个捕获项，再选择已有 KB 或“新建 KB”。这同样构成精确路由授权。

### 8.3 模型生成 Route Proposal

当目标未知时，模型可读取 KB 注册信息、已确认领域边界和必要的检索摘要，最多给出 3 个候选，并允许给出“暂不路由”或“建议新建 KB”。

模型不得：

- 直接创建 KB。
- 自动应用最高置信度候选。
- 因为没有合适候选就把内容塞入“最接近”的 KB。
- 自动把一个捕获项复制到多个 KB。
- 建议删除原始捕获来“清理收件箱”。

## 9. Route Proposal 最小结构

每份路由提案必须绑定精确输入和 KB 注册表版本：

```yaml
proposal_id: "<uuid>"
proposal_type: routing
capture_id: "<capture-id>"
capture_version: 1
capture_sha256: "<sha256>"
registry_revision: "<git-commit-or-version>"
status: pending

candidates:
  - kb_id: "<existing-kb-id>"
    suggested_processing_mode: capture-only
    confidence: medium
    reason: "<可审阅理由>"
    evidence: ["<与目标 KB 的具体重合点>"]

new_kb_suggestion: null
generated_at: "<ISO-8601 timestamp>"
generated_by: "<model-and-prompt-version>"
```

审核操作至少支持：

- 选择某个已有 KB。
- 选择模型未推荐的 KB。
- 明确新建 KB。
- 保持 `unassigned`，以后再处理。
- 归档捕获，但不提升为知识。
- 要求模型根据人工补充条件重新提案。

捕获版本或候选 KB 的关键状态变化后，旧批准失效，必须重新确认。

## 10. 路由和处理方式必须分两步表达

用户选择目标 KB 后，还需要知道将采取哪种处理方式；二者可以在一次审核操作中同时确认，但数据上必须分开记录。

| `processing_mode` | 含义 | 自动写入边界 | 下一步 |
|---|---|---|---|
| `capture-only` | 只把内容放入该 KB 的待处理范围 | 可建立 inbox 记录/GBrain 关联；不写 `raw/` 或 `wiki/` | 日后批量审核或提升提案 |
| `raw-source` | 把精确原始版本归档为 KB 原料 | 可复制到 `raw/`、写来源元数据和哈希；不提炼知识 | 等待 SOP-001 或仅作来源保存 |
| `deep-curation` | 将原料交给长文策展流程 | 可先完成 `raw-source`；SOP-001 只生成策展地图 | 人审地图后再进入 SOP-000B/SOP-002 |
| `promotion-proposal` | 为短想法/捕获生成可信知识候选稿 | 只能写入 `proposals/promotions/` | 人审精确内容后执行 |

默认规则：

- 灵感、随手笔记默认 `capture-only`。
- 外部文件和 URL 默认建议 `raw-source`。
- 用户明确要求深度整理时，原料归档完成后可直接运行 SOP-001，不再增加一次事前内容审批。
- 用户可以为某个 KB 配置可见、可撤销且范围明确的规则，例如“路由到本库的论文自动生成策展地图”；符合规则时可自动运行 SOP-001。
- 只有模型认为某项适合深度策展、但没有用户意图或预设规则时，才需要先让用户确认是否运行。
- 任何模式都不能直接创建可信 wiki 页面。

这里必须区分：运行 SOP-001 的是**处理触发授权**，SOP-001 之后审核的是**地图内容和后续写入**。真正不可省略的人工闸门位于策展地图生成之后、SOP-000B/SOP-002 之前。

不运行 SOP-001 的长文不会丢失：未分配时留在 Global Intake，已分配时停在 KB Inbox 或 `raw-source`；它可以在 `capture/source` 范围检索，但不会产生覆盖报告、SCHEMA 建议或可信 wiki 页面。用户以后仍可批量选择深度策展、仅保留原料或归档，系统不得因长期未处理而自动删除。

## 11. 标准路由流程

### 步骤 R0：锁定输入版本

记录 `capture_id + version + sha256`。路由期间原始项产生新版本时，本次路由仍只处理已批准版本。

### 步骤 R1：确定授权来源

授权来源必须是：

- `explicit-at-capture`
- `manual-review`
- `approved-proposal`

仅有模型推荐记录时不得继续 materialize。

### 步骤 R2：验证目标

1. 目标 KB 可识别且 `kb_id` 匹配。
2. `active` KB 可正常接收捕获。
3. `provisional` KB 只有用户明确选择时才接收，用于冷启动。
4. `archived / locked / read-only` KB 拒绝写入并保留原捕获。

### 步骤 R3：必要时创建新 KB

- 用户主动说“新建 KB X”可直接视为新建授权。
- 模型建议新建时必须等待用户确认名称和创建位置。
- 确认后调用 SOP-000A。
- SOP-000A 验收失败时，捕获项仍留在 Global Intake，不得标记已路由。

### 步骤 R4：materialize 到 KB Inbox

建议先在 `inbox/` 建立以 `capture_id` 为身份的记录：

- 文本/小文件可复制精确 Payload。
- GBrain 捕获可写入只含 `capture_id`、GBrain page ID、版本和哈希的引用记录。
- 大文件采用复制、内容寻址或外部对象引用，具体方式待实现决策。

该步骤不修改原始内容，不生成 AI 文件名。

### 步骤 R5：按处理方式继续

- `capture-only`：停在 KB Inbox/GBrain 未审核范围。
- `raw-source`：执行第 12 节的确定性归档。
- `deep-curation`：完成原料归档后启动 SOP-001。
- `promotion-proposal`：生成待审核提升稿，不触碰 wiki。

### 步骤 R6：写入 Route Record

记录：

- 捕获 ID、版本和哈希。
- 目标 `kb_id`。
- 处理方式。
- 授权来源、审核人和时间。
- materialize 后路径。
- Git commit 或事务 ID。
- GBrain page/source 映射。
- 校验结果。

### 步骤 R7：完成状态更新

只有目标文件/引用存在、哈希验证通过、Route Record 已写入后，才把该路由标记为 `routed`。

## 12. 从 Intake/Inbox 到 `raw/` 的确定性归档

### 12.1 推荐策略：复制—校验—记录，而不是先移动

MVP 建议使用：

1. 从捕获项导出精确原始版本。
2. 复制到 KB `inbox/` 或目标 `raw/` 临时路径。
3. 重新计算 SHA256，与捕获版本一致后原子改为正式路径。
4. 写入来源元数据和 Route Record。
5. Git 提交或记录待提交批次。
6. 最后更新 Intake 状态。

在全部成功前不删除 Capture Store 中的规范原件，也不把 Item 从 Global Intake/KB Inbox 状态视图中提前移除。后续可根据保留策略清理已验证的重复物理副本，但捕获版本、清单和审计记录必须保留。

### 12.2 文件名

优先级为：

1. 用户明确提供的安全文件名。
2. 来源自带且经过字符规范化的文件名。
3. 确定性名称：`YYYYMMDD-HHMMSS-<capture-id8>.<ext>`。

模型生成的主题标题只能作为重命名提案。未经确认，不得用 AI 标题改变规范路径。

### 12.3 重复内容

- 同一 `idempotency_key` 的重试返回同一 Capture Event。
- 用户两次主动保存相同内容时，可保留两个事件，但底层 Payload 可内容寻址去重。
- 相同 `source_url + sha256` 可提示“已有相同版本”，不能静默丢弃新事件。
- URL 相同但哈希不同视为新快照版本。
- 已在目标 KB `raw/` 存在相同哈希时，可只新增 Route Record/引用，不重复写入正文。

## 13. 状态模型

不要用一个 `status` 同时表达所有事实，最少拆成四个维度。

### 13.1 持久化状态

```text
received -> durable
         -> failed
```

### 13.2 路由状态

```text
unassigned -> proposed -> approved -> materializing -> routed
     │           │          │              │
     ├-> deferred├-> rejected              └-> failed
     └-> archived└-> needs-revision
```

用户在捕获时明确指定 KB 时，可以从 `unassigned` 直接进入 `approved`，但仍需完成 materialize 和校验。

### 13.3 信任状态

```text
unreviewed-capture
  -> raw-source
  -> pending-knowledge-proposal
  -> trusted-knowledge
```

该链不表示必须逐级自动前进；任何语义提升都需要对应审核。

### 13.4 GBrain 同步状态

```text
not-requested | pending | synced | failed | stale
```

GBrain 同步始终发生在本地捕获成功之后。GBrain 持久化失败不能把已经本地持久化的捕获改成“保存失败”，只能把镜像状态更新为 `failed` 并等待重试。没有完成本地 Capture Store 原子提交时，系统不得报告成功。

## 14. 典型场景

### 场景 A：随手灵感，不指定 KB

```text
用户：“记一下，审核界面应该把批准对象的 hash 展示出来。”
-> 本地 Capture Store 立即形成符合 Capture Envelope 契约的记录
-> 返回 saved: true
-> Global Intake: unassigned / capture-only
-> 可选异步镜像到 GBrain 未审核 source
-> 不打断用户询问归属
-> 以后批量产生路由/提升建议
```

### 场景 B：明确放入已有 KB，但不要求深度整理

```text
用户：“把这个想法放到 KnowledgeFlow 设计库。”
-> 明确路由授权
-> 保存原文
-> 关联目标 KB Inbox
-> processing_mode: capture-only
-> 不写 wiki，不自动运行 SOP-001
```

### 场景 C：明确要求深度整理一篇长文

```text
用户：“把这篇论文放到 Agent 学习库，按深度流程整理。”
-> 保存原文/文件
-> 目标 KB 已明确，无需重复确认路由
-> raw-source 归档并验证哈希
-> SOP-001 生成 proposals/curation-maps/
-> 等人工审核，不执行 SOP-002
```

### 场景 D：模型认为需要新 KB

```text
捕获项位于 Global Intake
-> 模型提案：现有 KB 均不合适，建议新建“个人健康记录”
-> 保持 unassigned
-> 用户确认名称和创建位置
-> SOP-000A 创建 provisional KB
-> 捕获项进入新 KB Inbox
-> 用户选择 capture-only / raw-source / deep-curation
```

### 场景 E：一个来源涉及多个 KB

模型只能提交多目标建议。用户明确批准后，为每个目标建立独立 Route Record；其中一个路由失败不影响其他路由，也不删除 Capture Store 原件或历史路由状态。各 KB 是否保留完整原料副本，按第 12 节和后续存储策略处理。

## 15. 人工审核语义

以下动作视为有效授权：

- 用户在原始指令中明确说出目标 KB 和处理方式。
- 用户在审核界面手动选择目标 KB。
- 用户批准绑定具体捕获版本的 Route Proposal。
- 用户明确要求创建一个给定名称的新 KB。

以下动作不构成授权：

- 模型置信度很高。
- 过去相似内容通常进入某 KB。
- 用户只说“保存一下”，没有说归属。
- 用户批准了旧版本，但捕获内容或候选目标的治理状态已经变化。
- 用户只同意“方向”，但最终目标路径和处理方式尚未展示。

批量批准必须列出确切 `capture_id + version + target_kb_id + processing_mode`，不允许“以后类似内容都自动放这里”作为永久授权。未来若需要自动规则，必须单独建立用户可见、可撤销的确定性路由规则。

## 16. 搜索和展示隔离

最小查询范围分为：

| 查询范围 | 内容 | 默认用途 |
|---|---|---|
| `trusted` | active KB 中获批的可信 wiki | 普通知识问答默认范围 |
| `source` | 已路由的 `raw/` 原料 | 溯源、重新策展、查原文 |
| `capture` | Global Intake、KB Inbox、GBrain 未审核页 | “我之前记过什么”类个人回忆 |
| `proposal` | 路由、策展、提升和维护提案 | 审核界面，不作为事实回答 |

展示规则：

- 默认知识问答使用 `trusted`。
- 用户明确查询“我的灵感/未整理笔记”时可搜索 `capture`。
- 同时搜索多个范围时必须分组展示，并标注可信级别。
- 未审核内容不能以与可信知识相同的引用样式混入答案。
- `provisional` KB 默认不进入联邦可信搜索。

## 17. GBrain 边界

### 17.1 允许

- 接收低摩擦文本捕获。
- 为未审核捕获生成 embedding 和独立范围搜索。
- 生成摘要、实体、主张、候选标签和路由建议。
- 将所有语义结果送入提案队列。
- 保存捕获页与原始 Capture ID/哈希的映射。

### 17.2 禁止

- 自动把未审核捕获提升为可信知识。
- 根据模型分类直接改变 KB 归属。
- 让 Dream Cycle、autopilot 或其他后台任务反向改写规范 Markdown。
- 在用户批准后重新调用模型生成另一版最终正文。
- 把 `capture`、`proposal` 与 `trusted` 搜索范围静默混合。

### 17.3 同步一致性

- 本地不可变 Capture Envelope 与 Payload 是捕获审计锚点；GBrain 页面只记录所镜像本地版本的 `capture_id + version + envelope_sha256` 和 Payload 哈希。
- GBrain 页面被用户编辑时，导出为新的捕获版本，不覆盖已被路由或批准的版本。
- GBrain 索引删除不能删除本地原始版本；删除 Capture Store 原件必须走独立、显式的破坏性操作。
- Markdown/Git 中的可信内容仍是规范真源；GBrain 的可信索引应可重建。

## 18. 幂等、失败与回滚

### 18.1 幂等键

建议最小幂等键：

```text
捕获：channel + idempotency_key
路由：capture_id + version + target_kb_id + processing_mode
原料归档：target_kb_id + payload_sha256
GBrain 捕获/同步：capture_id + version
```

### 18.2 失败原则

- 捕获持久化失败：明确报告失败，不返回虚假 `capture_id`。
- GBrain 写入失败：本地捕获结果保持成功，镜像进入待同步重试；若本地 Capture Store 尚未完成原子提交，则捕获本身明确失败且不得尝试用 GBrain 成功掩盖。
- 路由失败：保持原位置，Route Record 标记 `failed`。
- 新 KB 创建失败：回到 `unassigned/approved`，不得丢失捕获。
- SOP-001 失败：原料仍在 `raw/`，不产生半完成的获批地图。
- Git 提交失败：不把路由报告为完全完成，保留可重试事务信息。

### 18.3 错误路由的纠正

错误路由属于语义纠正，不能由模型静默修复：

1. 提交“撤销原路由 + 新目标”的精确方案。
2. 用户确认受影响路径和引用。
3. 回滚对应 commit，或把错误目标中的记录移入归档并保留审计。
4. 重建 GBrain 派生索引。
5. 原始 Payload 和历史 Route Record 不被改写。

普通“归档”只把捕获移出待处理队列；永久物理删除属于单独的破坏性操作，必须由用户明确要求。

## 19. 成本与摩擦控制

### 19.1 捕获热路径零 LLM

保存、哈希、ID、时间和重试不依赖模型。GBrain 同步不依赖模型但仍必须移出热路径；即使模型、GBrain、Git 或网络服务不可用，也能完成本地捕获。

### 19.2 路由建议按需或批量生成

- MVP 可以先只提供人工选 KB，不做自动路由建议。
- 后续先用 KB 注册信息/检索缩小候选，再让低成本模型解释候选。
- 每项最多 3 个候选。
- 相同 `capture_sha256 + registry_revision` 复用提案，不重复付费。
- 不因每次随手记都弹窗询问；在统一收件箱批量处理。

### 19.3 深度策展使用预授权触发

SOP-001 只生成待审策展地图，不写可信知识，因此无需逐篇“先审核内容再允许生成”。它使用以下任一预授权触发：

- 用户捕获时明确要求深度整理。
- 用户在后续审核中选择 `deep-curation`。
- 已存在一条用户可见、可撤销且范围精确的规则。

仅有模型对长度或价值的判断时，只能建议运行。没有触发授权的长文保持 `raw-source`，以后再批量处理。

### 19.4 派生结果可重建

embedding、摘要、候选标签、OCR 修订和路由候选都不作为唯一原件。可重建结果可以按预算、时间窗口和优先级延迟执行。

## 20. MVP 最小实现范围

### 20.1 MVP-0：本地文本捕获

第一条可执行链路只需闭合：

1. 单机、单用户文本捕获。
2. 本地 Capture Store 原子保存、稳定 `capture_id`、不可变版本和 SHA256。
3. 不指定目标也能保存，并显示在 Global Intake。
4. 支持读取、列表和追加新版本。
5. GBrain、Git 和任何 LLM 都不参与保存成功判定。
6. 默认不实现 AI 自动路由、URL、文件、音频、SOP-001/002 或可信写入。

### 20.2 MVP-1：人工路由与原料归档

在 MVP-0 通过后增加：手动选择已有 KB、明确新建 KB、暂缓、归档，以及 `capture-only`、`raw-source`、`deep-curation` 处理意图。明确新建时调用 SOP-000A，`raw/` 归档使用“复制—校验—记录”。

### 20.3 MVP-2：GBrain 未审核镜像

在本地捕获稳定后，再把 GBrain 作为可选、异步、可重建的未审核工作副本接入。POC 优先使用本地 keyless PGLite、DB-only 且 `federated: false` 的 `knowledgeflow-intake` source 和薄同步适配器，不预建独立镜像导出目录或 HTTP/OAuth。

更后阶段再增加 URL/文件入口、AI Route Proposal、批量审核、多 KB 路由和 promotion proposal，避免在最小链路尚未验证前扩大成本。

## 21. 验收标准

- [ ] 用户不指定 KB，也能立即且可靠地保存内容。
- [ ] 捕获确认不等待任何 LLM 调用。
- [ ] 每个捕获项都有稳定 ID、原始 Payload 和哈希。
- [ ] 用户明确指定已有 KB 时，不出现重复确认，但不会写入 wiki。
- [ ] 模型推荐 KB 时，不经人工批准无法 materialize。
- [ ] 模型建议新建 KB 时，不经人工确认无法调用 SOP-000A。
- [ ] 用户批准新 KB 后，SOP-000A 失败不会导致原料丢失。
- [ ] `capture-only` 不会自动进入 `raw/` 或启动 SOP-001。
- [ ] 用户明确深度整理或命中人工配置规则时，SOP-001 可直接运行，但只生成待审核策展地图，不直接执行 SOP-000B/SOP-002。
- [ ] 没有运行 SOP-001 的长文仍可作为 `raw-source` 保留和检索，不会被冒充为可信知识或自动删除。
- [ ] Intake 到 `raw/` 的内容哈希一致。
- [ ] 重复请求不会产生重复路由或重复原料文件。
- [ ] GBrain 不可用时，本地捕获仍成功并显示镜像待同步/失败；本地原子提交失败时明确报告捕获失败。
- [ ] 默认可信搜索无法召回 Global Intake、KB Inbox 或 pending proposal。
- [ ] 错误路由存在明确、可审、可回滚的纠正流程。

## 22. 与现行方案的冲突和改造点

1. 现行 [SOP v2](sop-v2-full.md) 把捕获、规模判断、领域判断都塞入 SOP-001 步骤 0；本规范建议把捕获和路由独立出来，让 SOP-001 只消费已经保存、版本明确的原料。
2. 现行 SOP-001 把原料和策展地图同时写入 `raw/`；本规范要求原料进 `raw/`、语义提案进 `proposals/`。
3. 现行 SOP-001 会在流程中判断多原料归属；模型判断今后只能形成 Route Proposal。
4. 现行 SOP-006 可从对话提炼后直接准备 SOP-002 输入；今后对话应先成为 Capture Item，再明确路由和处理方式。
5. 当前 [GBrain 集成方案](gbrain-integration-plan.md) 把 B-捕获描述为“直接写”；需要明确这是写入未审核捕获层，不是写入可信知识层。
6. GBrain 集成方案中的 B-搜集允许机器内容直接写入，需要进一步拆成“原始响应可直接保存、机器论断只进入提案”。
7. 当前尚无正式 KB Registry、Global Intake 投影索引和跨库事务实现；本规范已经批准，但这些结构仍未实现。

## 23. 已确认项与后置决策

| 项目 | 已确认结论或当前建议 | 状态/理由 |
|---|---|---|
| Global Intake 是否是 KB | 不是；它是未分配 Capture Item 的逻辑视图 | 已确认 |
| Capture Envelope 的实现 | 本地文件式 Capture Store + 不可变 Envelope；投影/outbox 可重建 | 已确认 |
| 捕获的第一物理持久化位置 | 本地 Capture Store | 已确认；当前机器配置为 `E:\KnowledgeFlowData\capture-store`，运行时解析为绝对路径 |
| GBrain 角色 | 可选异步未审核镜像、捕获范围搜索和派生处理层 | 已确认；不承担唯一原件 |
| GBrain 最小接法 | POC 优先本地 DB-only source + 薄同步适配器 | 待 POC 实证，不阻塞本地捕获 |
| 已明确目标是否重复确认 | 不重复 | 用户明确指令已经是路由授权 |
| 未明确目标是否自动路由 | 不自动 | 模型只能提案；MVP 先人工选择 |
| Intake 到 `raw/` | 复制—校验—记录 | 在事务完成前始终保留安全原件 |
| 灵感是否都进 `raw/` | 否，默认 `capture-only` | 避免把未筛选灵感塞满原料层 |
| 长文是否都自动跑 SOP-001 | 不以长度单独决定 | 用户明确深度整理或命中人工配置规则时直接运行；否则保留为 `raw-source`，模型只能建议 |
| Git 提交粒度 | 捕获可批量提交；批准路由/策展批次单独提交 | 减少随手记的提交噪音，同时保留语义变更边界 |
| 多 KB 路由 | 支持数据模型，MVP 暂不优先 | 先闭合单目标路径，降低事务复杂度 |
| 未审核内容默认搜索 | 不进入 `trusted`；仅在 `capture` 范围可见 | 防止捕获噪音污染可信答案 |

## 24. 下一步

1. 实现拆解与编码执行方案已经批准，C0 测试骨架与 C1 确定性基础原语已经完成；下一步仍需明确授权 C2，才实现配置、路径、Manifest 与测试临时 Store 初始化。
2. 本地链路通过故障注入和迁移验收后，再实现人工路由和 SOP-000A 调用边界。
3. 以本地 DB-only source 实证 GBrain 未审核镜像、副作用关闭和查询隔离。
4. 定义 SOP-000B：如何基于首份获批策展地图写入 SCHEMA 并激活 KB。
5. 将 SOP-001 的“捕获与归属判断”移出，只保留深度提取和策展地图生成。
6. 将 SOP-002 改成只消费绑定哈希、已经批准的精确变更集，并补齐事务和回滚。
