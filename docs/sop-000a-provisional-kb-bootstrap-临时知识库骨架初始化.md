# SOP-000A：临时知识库骨架初始化

> 状态：Approved Design，已确认但尚未实现<br>
> 整理日期：2026-08-31<br>
> 确认日期：2026-09-01<br>
> 目标：只定义“如何安全地创建一个尚未确定领域和 SCHEMA 的 KB 容器”<br>
> 约束：不在本 SOP 中创建可信 wiki 内容，不做语义分类，不自动接入联邦检索；主题优先级见[设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)

## 0. 编号说明

本文正式使用 **SOP-000A**，把知识库初始化拆成两个阶段：

- SOP-000A：创建 `provisional` 临时骨架。
- SOP-000B：在领域、SCHEMA 和首批策展方案获批后，将 KB 激活为 `active`。

现行 SOP-000 中“模式 A / 模式 B”的旧称只属于旧版初始化分支，不再拥有当前编号语义；重构旧 SOP 时应改名或归档，不能据此改变本文件编号。

## 1. 定位

SOP-000A 是一个**确定性的容器初始化流程**。它解决的是：用户想创建一个新知识库，但尚不能可靠定义领域、模块、标签和页面类型时，系统仍可先获得一个安全、可审计、可继续摄入原料的最小落点。

它不解决以下问题：

- 这个 KB 最终覆盖什么领域。
- 第一份原料应该提取哪些知识。
- 应建立哪些页面类型、关系类型、标签或模块。
- 是否应与另一个 KB 合并。
- 是否应加入 GBrain 联邦检索。

这些都涉及语义判断，应由后续策展地图和人工审核决定。

## 2. 与“立即保存”的关系

SOP-000A 不是所有捕获的前置步骤。

| 捕获情况 | 是否执行 SOP-000A | 立即落点 |
|---|---|---|
| 用户明确选择已有 KB | 否 | 先进入本地 Capture Store，记录 `assigned` 路由授权，再显示于该 KB Inbox |
| 暂时不知道归属 | 否 | 先进入本地 Capture Store，状态 `unassigned`，显示于 Global Intake |
| 模型只“建议”新建 KB | 否 | 本地 Capture Store + Global Intake + `pending` 路由提案 |
| 用户明确确认新建 KB | 是 | 原件先在 Capture Store；创建成功后记录路由并显示于新 KB Inbox |

因此，保存原料永远不需要等待领域讨论；只有创建一个新 KB 容器需要用户授权。

## 3. 触发条件

同时满足以下条件时触发：

1. 用户明确要求或明确批准创建一个新 KB。
2. 已确定创建位置和临时显示名称。
3. 目标位置不存在另一个 KB，或现有目录经检查可安全采用。
4. 当前操作主体具有在目标位置创建文件的权限。

以下情况不得自动触发：

- 模型仅根据内容相似度判断“最好新建一个库”。
- 捕获内容暂时无法分类。
- 已有 KB 的领域定义不够清晰。
- 为了绕过已有 KB 的写入审核而创建新库。

## 4. 最小输入

SOP-000A 只要求：

- `display_name`：用户可识别的临时名称，可在激活前调整。
- `path`：目标目录。
- `requested_by`：创建请求来源或操作者。
- `created_at`：由系统生成的时间。
- `repository_mode`：使用父级 Git 还是 KB 独立 Git；如架构尚未定案则记录为 `inherited`，不擅自 `git init`。

以下信息不是前置条件：

- 完整领域描述。
- 页面类型和关系类型。
- 标签分类法。
- 模块目录。
- 首份原料。
- GBrain source 标识。

## 5. 输出状态

成功执行后，KB 处于：

```yaml
lifecycle: provisional
domain_status: pending
schema_status: absent
wiki_status: empty
trusted_search_visibility: none
```

`provisional` 表示“容器已经存在并可接收原料”，不表示“它已经是可供正式检索和写作使用的可信知识库”。

## 6. 最小目录骨架

建议输出：

```text
<kb-root>/
├── kb.yaml
├── README.md
├── inbox/
├── raw/
│   ├── articles/
│   ├── papers/
│   ├── transcripts/
│   └── assets/
├── proposals/
│   ├── routing/
│   ├── curation-maps/
│   ├── promotions/
│   ├── changes/
│   └── maintenance/
├── wiki/
├── schema/
│   └── log.md
└── _archive/
```

空目录是否使用 `.gitkeep` 由版本存储方式决定，这是机械实现细节。

### 6.1 各目录职责

| 路径 | 职责 | 临时状态下允许写入什么 |
|---|---|---|
| `inbox/` | 已明确属于该 KB、但尚未完成标准化摄入的暂存区 | 用户原文、附件、链接清单和机器元数据 |
| `raw/` | 已完成来源记录和哈希的不可变原料档案 | 原始内容及确定性元数据，不写模型策展结论 |
| `proposals/` | 所有待审核的语义工件隔离区 | 路由、策展地图、提升、变更和维护提案 |
| `wiki/` | 获批后的可信知识页面 | `provisional` 阶段保持为空 |
| `schema/` | KB 的规范、导航和审计记录 | 只先创建追加式 `log.md`；不创建虚假的 `SCHEMA.md` |
| `_archive/` | 已退役工件的归档区 | 初始化时为空 |

### 6.2 为什么不在此时创建 `SCHEMA.md`

如果领域、页面类型和关系还未从真实原料中显现，提前生成“完整 SCHEMA”只会把模型猜测伪装成规范。SOP-000A 因此明确使用 `schema_status: absent`，让后续 SOP-001 的无 SCHEMA 分支真正可达。

这不是说 KB 永远不需要 SCHEMA，而是把创建 SCHEMA 的时点推迟到“有代表性原料 + 策展地图 + 人工确认”之后。

## 7. `kb.yaml` 的定义

`kb.yaml` 是每个 KB 根目录下的**机器可读清单（manifest）**。它类似 KB 的身份证和状态卡，用来让脚本、UI、Agent 和 GBrain 适配层在没有 `SCHEMA.md` 时仍能可靠识别：

- 这是一个 KnowledgeFlow KB，而不是普通文件夹。
- KB 的稳定 ID 是什么。
- 当前是临时态还是正式态。
- 领域和 SCHEMA 是否已经确认。
- 哪些搜索和写入权限当前可用。
- 它以后映射到哪个 GBrain brain/source。

`kb.yaml` 不保存知识正文，也不替代 `SCHEMA.md`。前者描述容器身份和生命周期，后者描述已经获批的领域语义与知识结构规则。

建议的最小草案：

```yaml
format_version: 1
kb_id: "<uuid>"
slug: "<stable-english-slug>"
display_name: "<用户确认的临时名称>"
created_at: "<ISO-8601 timestamp>"
created_by: "<request source>"

lifecycle: provisional

domain:
  status: pending

schema:
  status: absent

wiki:
  status: empty

canonical_store:
  type: markdown-git
  repository_mode: inherited

search:
  trusted_visibility: none

gbrain:
  brain: null
  source: null
  federated: false
```

字段和枚举需在实现前另行定版。`kb.yaml` 是固定机器契约，因此是“英文名-中文名”文件命名规则的明确例外。

## 8. 确定性执行步骤

### 步骤 0：验证授权和目标

1. 确认存在明确的新建授权。
2. 将目标路径解析为绝对路径。
3. 检查目标不在禁止位置，且不会覆盖已有 KB。
4. 若发现 `kb.yaml`，转入幂等检查，不重复创建新身份。
5. 若目录非空但不是 KB，暂停并报告冲突，不自行移动或删除内容。

### 步骤 1：生成稳定身份

1. 生成不可变 `kb_id`。
2. 根据临时名称生成稳定英文 `slug`；如需修改，应在激活前由用户确认。
3. 记录创建时间和请求来源。
4. 不推断领域、标签或 GBrain source。

### 步骤 2：创建目录

按第 6 节创建固定骨架。操作必须幂等：目录已存在时验证类型和权限，不覆盖其中内容。

### 步骤 3：写入最小治理文件

1. 写入 `kb.yaml`。
2. 写入 `README.md`，仅说明这是临时 KB、当前名称、状态、允许操作和下一步。
3. 写入 `schema/log.md` 的初始化记录。
4. 不创建 `SCHEMA.md`、`index.md`、模块目录、实体页或查询页。

### 步骤 4：建立版本检查点

根据已确认的 Git 拓扑执行：

- `repository_mode: inherited`：由父级仓库追踪这些文件，不在 KB 内创建 `.git/`。
- `repository_mode: independent`：在该 KB 根目录初始化独立仓库并创建骨架 commit。

如果拓扑尚未定案，只记录文件并报告“等待纳入版本控制”，不得擅自创建嵌套 Git 仓库。

### 步骤 5：保持检索隔离

1. 不创建 GBrain source，或创建后保持 `federated: false` 且可信检索不可见。
2. 不为 `wiki/` 建立正式索引。
3. 若 GBrain 用于捕获，必须将内容标为未审核，并与可信查询结果隔离。

### 步骤 6：验收并报告

输出创建结果、绝对路径、`kb_id`、生命周期、Git 模式、检索隔离状态和下一步建议。报告不得声称领域或 SCHEMA 已经完成。

## 9. 临时态权限

| 操作 | `provisional` 是否允许 | 条件 |
|---|---|---|
| 捕获到 `inbox/` | 允许 | 用户明确选择此 KB |
| 从 `inbox/` 机械归档到 `raw/` | 允许 | 来源、时间和哈希完整；不改变正文语义 |
| 运行 SOP-001 | 允许 | 输出只能进入 `proposals/curation-maps/` |
| 生成领域/SCHEMA 建议 | 允许 | 仅作为 `pending` 提案 |
| 写入可信 `wiki/` | 禁止 | 等待领域、SCHEMA 和精确变更获批 |
| 创建或修改 `SCHEMA.md` | 禁止直接执行 | 必须先由策展地图提出并经人确认 |
| 加入联邦搜索 | 禁止 | 等待 SOP-000B 激活 |
| 自动合并到其他 KB | 禁止 | 必须形成迁移方案并由人确认 |

## 10. 验收标准

SOP-000A 只有全部满足时才算成功：

- [ ] 目标路径唯一且未覆盖其他 KB。
- [ ] `kb.yaml` 可解析，`kb_id` 存在且唯一。
- [ ] `lifecycle` 为 `provisional`。
- [ ] `domain.status` 为 `pending`。
- [ ] `schema.status` 为 `absent`，且不存在 `schema/SCHEMA.md`。
- [ ] `wiki.status` 为 `empty`，且 `wiki/` 不含可信页面。
- [ ] `inbox/`、`raw/`、`proposals/`、`wiki/`、`schema/` 和 `_archive/` 均存在。
- [ ] 策展地图路径是 `proposals/curation-maps/`，不是 `raw/_curation-maps/`。
- [ ] GBrain 联邦检索关闭，未审核内容不会伪装成可信知识。
- [ ] Git 模式与父级架构一致，未意外生成嵌套仓库。
- [ ] 初始化操作写入审计日志，并存在可恢复检查点或明确的未纳管警告。

## 11. 幂等、失败与回滚

### 11.1 幂等

使用同一目标重复执行时：

- 若 `kb_id` 和骨架一致，只补齐缺失的机械文件，并报告“已存在”。
- 不生成第二个 `kb_id`。
- 不重写用户已放入的原料。
- 不覆盖已经产生的提案或日志。

### 11.2 失败

任一步骤失败时，状态不得被报告为成功。能够安全清理本次新建空文件时可回滚；目标中已有用户内容时不得自动删除，应留下失败报告供人工处理。

### 11.3 回滚

- 若使用独立 Git，回滚到初始化 commit 之前或撤销后续批次。
- 若使用父级 Git，回滚对应 KB 路径的初始化 commit。
- 如果尚未纳入 Git，只允许删除本次创建且确认仍为空的骨架；一旦含有用户捕获内容，必须先迁移/备份并由用户确认。

## 12. 下一步：从临时态到正式态

SOP-000A 完成后的推荐链路：

```text
原料进入 inbox
  -> 确定性归档到 raw
  -> SOP-001（SCHEMA 不存在分支）
  -> proposals/curation-maps/ 中生成：
       - 材料全景与条目提取
       - 建议的 KB 名称和领域边界
       - 排除范围
       - 页面/关系类型
       - 标签和模块建议
       - 拟写入页面及精确内容
  -> 人工审核和修订
  -> SOP-000B（待定义）写入获批 SCHEMA 并激活 KB
  -> SOP-002 执行获批的首批可信写入
```

是否先由 SOP-000B 写 SCHEMA、再由 SOP-002 写 wiki，还是把两者放入同一原子事务，需要在 SOP-000B 设计时定案。

## 13. 与现行 SOP 的冲突清单

| 冲突 | 现行行为 | SOP-000A 草案 |
|---|---|---|
| 领域前置 | 领域不明确就暂停创建 | 可先创建 `provisional` 容器，领域后置审核 |
| SCHEMA 前置 | 初始化立即写完整 `SCHEMA.md` | 临时态明确保持 `schema_status: absent` |
| Wiki 骨架 | 预建 `entities/`、`queries/` | 不预设语义页面类型或模块 |
| 策展地图位置 | `raw/_curation-maps/` | `proposals/curation-maps/` |
| 检索身份 | 尚无临时态隔离协议 | 临时 KB 不进入可信/联邦检索 |
| Git/回滚 | 未定义 KB 级提交边界 | 初始化必须形成版本检查点或显式警告 |

本文件已经获批；[现行 SOP v2](sop-v2-full.md) 在冷启动、领域前置、SCHEMA 前置和策展地图路径方面由本文件及捕获治理规范取代。旧 SOP 的全面迁移应单独执行，不能在实现过程中混用两套规则。

## 14. 后置到对应功能前的决策

1. 每个 KB 独立 Git，还是所有 KB 由一个父级仓库统一管理。
2. `<capture-root>` 的最终位置和 Capture Store 保留周期；Global Intake 已确定为未分配 Capture Item 的逻辑视图。
3. 从 `inbox/` 到 `raw/` 是复制原始对象还是移动，并如何处理 URL/附件引用。
4. SOP-000B 的原子提交边界，以及激活失败时如何回滚。
5. GBrain 是否允许为临时 KB 提前创建私有 source；无论选择哪种，都必须验证未审核内容不会进入可信搜索。

以下事项已经确认，不再列为开放项：SOP-000A 正式编号、临时态不创建占位 `SCHEMA.md`、Global Intake 不是 KB 且不是第二份规范原件。
