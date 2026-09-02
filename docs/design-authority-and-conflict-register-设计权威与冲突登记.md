# KnowledgeFlow 设计权威与冲突登记

> 状态：Approved Design；C0–C1 已完成，Capture Store 与业务操作尚未实现<br>
> 确认日期：2026-09-01<br>
> 补充确认日期：2026-09-02<br>
> 作用：规定各主题应以哪份文档为准，冻结 MVP 的最小决策，并登记尚未解决的设计冲突<br>
> 边界：本文件不声称任何业务能力已经实现，也不替代后续 SOP 的具体执行规范

## 1. 为什么需要本文件

项目同时存在旧版完整 SOP、长期建设路线、GBrain 集成方案，以及新形成的需求基线、捕获规范和 Capture Envelope。它们形成于不同阶段，不能再用“最后修改时间”或“文件名看起来最完整”判断谁优先。

从本文件确认之日起，项目采用两条规则：

1. **按主题确定权威文件。** 一份文档可以在某个主题上继续有效，在另一个主题上被新规范取代。
2. **新设计不等于已实现。** `Approved Design` 只表示可以作为后续实现依据，README、代码和测试必须另行验收后才能声称已经交付。

## 2. 文档状态词

| 状态 | 含义 |
|---|---|
| `Draft` | 正在讨论，不能作为实现必须遵守的最终规则 |
| `Approved Design` | 设计已经人工确认，可以作为后续设计和实现依据，但不代表已有实现 |
| `Effective` | 已有实现和验收与该规范对齐，当前运行系统必须遵守 |
| `Superseded` | 对应主题已经被新规范取代，仅供迁移和历史追溯 |
| `Historical` | 完整历史版本，不再参与当前设计决策 |

当前项目尚未完成捕获内核，因此本轮新规范最高状态为 `Approved Design`，不标记为 `Effective`。

## 3. 主题级权威矩阵

| 主题 | 当前权威 | 状态 | 其他文档如何处理 |
|---|---|---|---|
| 产品目标、知识策展悖论、语义写入原则 | [需求与治理基线](requirements-and-governance-baseline-需求与治理基线.md) | Approved Design | README、愿景和路线图只作解释，不得反向覆盖治理红线 |
| 文档优先级、冲突登记、功能门禁 | 本文件 | Approved Design | 发现新冲突先登记，再修改对应规范 |
| 临时 KB 创建与 `provisional` 生命周期 | [SOP-000A](sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md) | Approved Design | 旧 SOP-000 在冷启动、领域前置和 SCHEMA 前置方面被取代 |
| 捕获、Global Intake、人工路由和处理方式 | [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md) | Approved Design | 旧 SOP-001 步骤 0 和 SOP-006 不再负责捕获及最终归属决策 |
| 捕获身份、版本、哈希、事务、幂等和恢复 | [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md) | Approved Design | GBrain 原生 capture、可变页面或 sidecar 设想不得替代本地规范原件 |
| MVP-0 `capture-root` 与四个文本操作接口 | [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md) | Approved Design | 已确认每机配置、绝对解析、迁移、4 MiB 内联阈值和 64 MiB 默认安全上限 |
| MVP-0 运行时、初始化、工程拆分和测试矩阵 | [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md) | Approved Design | 9 项技术选择已确认；C0–C1 已完成，C2 尚未授权 |
| MVP-0 编码批次、执行停点和授权边界 | [MVP-0 捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) | Approved Design | C0–C1 已完成并停在 C2 门禁前 |
| 策展地图内部格式和覆盖审计方法 | 现有 SOP-001、`prompts/` 与 `extraction-interface.md` 中不冲突的部分 | Draft，待重构 | 只复用提取和地图格式；捕获、路径、触发和写入边界服从新规范 |
| SOP-000B：KB 激活 | 尚未定义 | Blocking Draft | 在 `provisional` KB 激活前必须完成 |
| 可信知识写入、精确批准和回滚 | 尚待重构的 SOP-002 | Blocking Draft | 旧 SOP-002 不得作为自动语义写入授权 |
| GBrain 未审核镜像最小接入 | 本文件第 8 节 + Capture Envelope 第 13 节 | Approved Design | 仅批准 POC 边界；旧 GBrain 集成方案只作远期能力研究，不是 MVP 接入指令 |
| GBrain、第二大脑、可视化、QQ 的长期路线 | `gbrain-integration-plan.md`、`build-plan.md`、`second-brain-vision.md`、`qq-qa-bot-plan.md` | Planning | 不得阻塞 MVP，也不得绕过本文件的人工闸门 |
| 现有 Lint、链接和 index 脚本 | `scripts/` | Existing Reference Implementation | 只证明旧知识库维护能力，不证明捕获、路由、审批或回滚已经实现 |

## 4. 已冻结的八项最小决策

### D-001：本地 Capture Store 是捕获规范真源

第一份可证明、可恢复的原件写入用户控制的本地文件系统。GBrain、Git 远端、LLM 和任何入口平台都不是捕获成功的同步前置条件。

“本地”描述第一持久化和控制权，不排斥后续 Git 备份、设备同步或远端容灾。

### D-002：捕获时不要求 KB

用户保存内容时可以不选择、不创建、不定义 KB。系统必须先保存，再允许用户或后续提案决定归属。

用户明确指定已有 KB 时，该指令是**路由授权**，不是可信 wiki 写入授权。

### D-003：Global Intake 不是 KB

Global Intake 是所有尚未确定 KB 归属的 Capture Item 的逻辑队列，推荐由 `routing.status: unassigned` 等状态投影形成。

它没有领域、SCHEMA 或可信知识身份，也不需要复制出第二份唯一原件。未来 UI 可以把它显示成一个“收件箱”，底层规范原件仍在 Capture Store。

### D-004：捕获成功只依赖本地原子保存

用户收到 `saved: true` 之前的同步热路径只允许包含：输入和边界检查、身份与版本分配、Payload 保存与哈希、不可变 Envelope 提交，以及足以恢复结果的最小审计记录。

以下工作不得阻塞保存成功：LLM、GBrain、Git commit/push、embedding、路由推断、SOP-001、网页抓取补全和可信知识写入。

### D-005：语义判断只能形成提案

模型可以生成标题、摘要、标签、实体、关系、KB 路由、SCHEMA 和维护建议，但这些结果只能进入派生层或 `proposals/`。

任何会改变内容含义、知识归属、结构规则或可信结论的操作，都必须先展示方案并由人工确认。

### D-006：SOP-000A 只在明确授权新建 KB 时运行

归属未知、模型建议新建 KB、或现有 KB 结构不清晰，都不能自动触发 SOP-000A。只有用户明确要求或批准新建 KB 时，系统才创建 `provisional` 容器。

### D-007：GBrain 是可选异步工作层

GBrain 可以承担未审核镜像、捕获范围检索和用户主动触发的派生处理，但不能证明原件、决定 KB 归属或直接修改可信 wiki。

GBrain 完全不可用时，本地捕获仍然成功；未接入 GBrain 的 KnowledgeFlow 仍是正确但功能较少的系统。

### D-008：MVP-0 先限制为单机、单用户、文本捕获

第一条可执行链路只实现文本 Capture Item。URL 快照、附件、音频、OCR、多设备并发、远程身份、AI 路由、QQ 和完整 Obsidian 式界面，分别在其功能门禁满足后增加。

这一限制不删除 Envelope 对未来 Payload 类型的表达能力，只限制第一轮实现和验收范围。

## 5. 统一术语

| 术语 | 定义 |
|---|---|
| Capture | 一次保存输入的操作/事务 |
| Capture Event | 一次明确用户动作或渠道事件的审计身份 |
| Capture Item | 可追加版本、路由、归档和提升的逻辑对象 |
| Capture Version | Capture Item 的一个不可变版本 |
| Payload | 按渠道保真规则保存的原始字节或文本 |
| Capture Store | 保存 Item、Version、Payload、Envelope、事件和可重建投影的本地物理存储 |
| Global Intake | `routing.status: unassigned` 等未分配 Item 的逻辑队列，不是 KB |
| KB Inbox | 已由用户明确授权属于某个 KB、但尚未标准化归档或策展的队列 |
| Raw | 已完成来源、哈希和归档记录的不可变原料层 |
| Proposal | 尚未获准改变可信知识的语义工件 |
| Trusted Wiki | 只接受获批精确变更的可信知识层 |
| 捕获热路径 | 从接收输入到返回本地耐久成功之间的同步操作集合 |

## 6. 最小链路

```text
任意入口
  -> 本地 Capture Transaction
  -> Capture Store 中形成不可变 Version + Envelope
  -> 返回 saved: true
  -> 根据当前状态显示在 Global Intake 或已授权的 KB Inbox

保存成功之后，彼此独立地执行：
  -> GBrain 未审核镜像（可选、异步、可重建）
  -> Git 批量备份（异步）
  -> 人工路由或路由提案
  -> raw 归档
  -> SOP-001 生成策展地图
  -> 人工批准精确变更
  -> SOP-000B / SOP-002 写入可信知识
```

Capture Store 是物理原件层；Global Intake 和 KB Inbox 首先是状态/队列视图。实现可以为检索效率建立索引或引用，但不得悄悄产生两个相互竞争的规范原件。

## 7. 捕获热路径边界

### 7.1 同步必需

1. 验证输入非空、类型受支持且未超过当前入口上限。
2. 生成或解析 `event_id`、`capture_id`、目标版本与幂等身份。
3. 保存 Payload，回读并计算/核验哈希。
4. 生成不可变 Envelope，并以 staging + 同盘原子提交完成版本目录。
5. 写入或确保可以恢复最小审计身份。
6. 返回稳定回执。

### 7.2 必须移出热路径

- LLM 调用和任何语义推断。
- GBrain 同步、索引和查询。
- Git commit、push 和远端备份。
- 自动摘要、标签、实体、关系和 KB 分类。
- SOP-001/002、可信 wiki 写入和 SCHEMA 变更。
- URL 的补充抓取、文件文本提取、OCR 和转写；对应入口必须先保存可验证输入，再异步派生。

## 8. GBrain 最小接入决策

### 8.1 不要求独立“镜像导出器”

系统只要求存在一个确定性的格式映射边界，不要求生成长期存在的 Markdown 镜像目录。

MVP POC 推荐：

1. 使用本地、keyless 的 GBrain PGLite。
2. 创建专门的 DB-only、`federated: false` source：`knowledgeflow-intake`。
3. Capture Store 保存成功后，由异步同步适配器显式调用 `put_page`。
4. 不启用 HTTP/OAuth，不要求 GBrain 账号或厂商 API key。
5. 不运行 Dream/autopilot，并关闭或实证隔离自动链接、timeline、facts、chronicle 等语义副作用。
6. GBrain 写入失败只更新投递状态，不改变本地保存回执。

如果直接 `put_page` 的 POC 证明不适合长文本或 Windows 传输，再评估临时文件传输、生成式 Markdown 视图或专用 importer；不得在实证前预建复杂导出子系统。

### 8.2 固定映射，不做语义转换

同步适配器只允许：

- 将本地稳定身份映射成合法 GBrain slug。
- 选择约定版本并复制正文。
- 写入版本、哈希、来源和 `unreviewed-capture` 标记。
- 按哈希幂等创建、更新、跳过和重建镜像。
- 移除不应泄露的绝对路径、幂等密钥和渠道秘密。

同步适配器不得生成摘要、标签、实体、关系、路由或 SCHEMA 建议。

本地 ID `cap_<uuid>` 映射为 GBrain slug 时必须把下划线转换为连字符，例如：

```text
capture_id: cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421
page_slug:  inbox/knowledgeflow/cap-01991a7e-7b20-7a31-8d14-0b8ab6b35421
```

原始 `capture_id` 必须完整保存在 GBrain frontmatter 中，不能用转换后的 slug 反推审计身份。

## 9. 冲突登记

| ID | 冲突 | 当前结论 | 状态/门禁 |
|---|---|---|---|
| C-001 | README 把旧 SOP v2 当作全域现行规范 | 改为主题级权威，入口文档必须链接本文件 | 本轮解决 |
| C-002 | 捕获规范曾把 GBrain 或本地谁先落盘列为待定 | 本地 Capture Store 为第一规范原件 | 本轮解决 |
| C-003 | Global Intake 可能被误解为另一个 KB 或第二份原件 | 定义为未分配 Capture Item 的逻辑队列 | 本轮解决 |
| C-004 | “必须有镜像导出器”导致过度设计 | 只要求薄同步适配器；POC 优先直接 `put_page` | 本轮解决 |
| C-005 | `cap_...` 被直接放进 GBrain slug，但下划线不合法 | slug 使用 `cap-...`，frontmatter 保留原始 ID | 本轮解决 |
| C-006 | 旧 SOP 把策展地图放在 `raw/_curation-maps/` | 新流程使用 `proposals/curation-maps/` | SOP-001 重构前由新规范覆盖路径 |
| C-007 | 旧 SOP-002 允许自动扩展领域和注册标签 | 语义结构变化只能进入提案 | 重构 SOP-002 前暂停可信自动写入 |
| C-008 | `provisional` KB 没有激活协议 | 先定义 SOP-000B，才能进入 `active` | 激活功能阻塞项 |
| C-009 | 旧策展写入未绑定 Capture 精确版本与变更集 | 批准必须绑定 `capture_id + version + envelope_sha256` 和精确 diff | 可信写入阻塞项 |
| C-010 | 可信写入没有完整事务和回滚协议 | SOP-002 重构时定义 prepare/apply/verify/commit/rollback | 可信写入阻塞项 |
| C-011 | 文件大小、URL 快照和敏感内容策略未定 | 文本 MVP 不被阻塞；在开放对应入口前定案 | 对应功能门禁 |
| C-012 | 大规模双语重命名会制造引用迁移噪音 | 先确定命名规则，新文件遵守；旧文件在权威收口后分批迁移 | 非 MVP 阻塞项 |
| C-013 | 操作契约使用 `capture_root_not_configured`，测试矩阵使用 `config_not_found`；提交后投影失败又混在失败码中 | 配置缺失统一为 `config_not_found`，配置非法为 `config_invalid`；写操作增加三态 `commit_state`，提交后投影故障改为成功警告 | 2026-09-02 解决 |
| C-014 | “三类哈希”表述下实际列出四个对象，且部分规范输入字节未固定 | 明确为 Payload、Payload Set、Request Fingerprint、Envelope 四类核心哈希，并固定前缀、JSON/YAML 字节和字段顺序 | 2026-09-02 解决 |
| C-015 | UUIDv7 是否要求同毫秒单调、时钟回拨如何处理未定义 | 固定 48 位毫秒 + 74 位安全随机；只承诺唯一和合法，不承诺同毫秒绝对单调，不伪造/钳制回拨时间 | 2026-09-02 解决 |
| C-016 | “安全 YAML 加载”与“文件字段正确”被混为一个校验步骤 | 拆成语法门禁、逐文件 schema 校验和确定性发射；两关失败分别测试 | 2026-09-02 解决 |

## 10. 功能门禁

| 要实现的能力 | 必须先完成 |
|---|---|
| 本地文本捕获 | 本文件、Capture Envelope、捕获与路由规范及已批准的 MVP-0 操作契约 |
| URL 捕获 | URL 原始输入、抓取快照、失败降级和哈希规则 |
| 文件/音频捕获 | 单文件大小上限、二进制保存、转写/OCR 派生和敏感数据策略 |
| GBrain 镜像 | 本地文本捕获通过；完成副作用关闭与查询隔离实证 |
| 人工路由 | Route Record、幂等和错误纠正流程 |
| 新建临时 KB | SOP-000A 执行契约与路径/Git 输入确认 |
| 激活 KB | SOP-000B 获批并具备失败回滚 |
| 运行 SOP-001 | 输入版本绑定、地图路径和处理触发规则完成重构 |
| 写入可信 wiki | SOP-002 精确批准、diff、事务、Git 检查点和回滚全部完成 |
| 远程 Agent/GBrain HTTP | 受限身份、source/slug 权限、密钥保存和审计验收 |
| AI 自动建议 | 只能生成 Proposal；成本上限、触发条件和人工界面已定义 |
| QQ、多设备和完整编辑器 | 核心状态机、权限和恢复协议已经稳定 |

## 11. MVP-0 明确不做

- 不要求用户在保存前选择 KB。
- 不实现 AI 自动路由。
- 不实现语义标题、摘要、标签和实体生成。
- 不实现 SOP-001/002 自动调用。
- 不实现 URL、文件、音频和 OCR。
- 不实现 GBrain HTTP、OAuth 或远程身份。
- 不实现 QQ、移动端和多设备并发。
- 不实现完整 Obsidian 式编辑器。
- 不进行全项目文件批量重命名。

## 12. 下一步顺序

1. 已批准 [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)第 13 节的 9 项技术选择。
2. [MVP-0 捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md)已经批准，C0 测试骨架与 C1 确定性基础原语已经完成并通过 30 项自动化测试。下一步仍需明确授权 C2，才实现配置、路径、Manifest 和仅限测试临时目录的 Store 初始化。
3. 所有开发和故障测试先使用隔离临时 Store；创建真实 `E:\KnowledgeFlowData\capture-store` 需要用户另行明确授权。
4. 纯本地文本链路验收前，不接 GBrain、不实现人工路由，也不启动 SOP-001/002 重构。
