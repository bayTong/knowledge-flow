# SOP-10：新建知识库骨架

> 状态：Review Candidate（阶段二联合契约收口稿；尚未实现，也不授权编码）<br>
> 历史编号：SOP-000A（只用于旧材料追溯）<br>
> 原设计确认日期：2026-09-01<br>
> 联合契约修订日期：2026-10-13<br>
> 技术复核修订日期：2026-10-15<br>
> 本地版本边界修订日期：2026-10-15<br>
> 目标：确定性创建一个不填造领域、SCHEMA 或可信知识的 `provisional` KB 容器<br>
> 上游：[深入策展流程总览](00-deep-curation-workflow-深入策展流程总览.md)与[捕获及路由规范](../capture/capture-and-routing-spec-捕获与路由规范.md)<br>
> 下游：[SOP-20 材料深度理解与策展地图](20-sop-deep-curation-map-材料深度理解与策展地图.md)和[SOP-30 批准后写入可信知识](30-sop-trusted-write-批准后写入可信知识.md)

## 1. 唯一职责

SOP-10 只创建一个可识别、可审计、保持可信隔离的知识库容器。它不负责推荐目标 KB、理解材料、生成策展地图、确定最终领域、写入可信 Wiki、开启可信检索或接入 GBrain。

它有两种合法入口：

1. **有原料新建**：用户确认把某个精确 Capture 版本放入新 KB；先创建容器，成功后再由路由层机械归档到 `raw/`。
2. **无原料预建**：用户只要求提前建立空 KB；初始化和待用报告完成后结束，不生成地图或知识正文。

目标尚未确定时不得为了运行 SOP-20 自动建库；没有目标 KB 也可以在受控工作区生成地图。

## 2. 授权与输入

运行前必须同时具备：

| 输入 | 约束 |
|---|---|
| `bootstrap_request_id` | 一次新建意图的稳定幂等身份；同一身份重试不得生成第二个 KB |
| `parent_root` | 用户确认的绝对父目录；必须来自部署配置列出的允许知识库根，而不是代码内硬编码盘符 |
| `root_policy_id + revision` | 本次校验所用允许根策略；策略变化后旧请求不能静默改投其他目录 |
| `requested_display_name` | 可空；用户明确给出时沿用，未给出时由第 3 节分配日期序号 |
| `requested_by` | 发起本次新建请求的用户或入口身份 |
| `requested_at` | 系统记录的 UTC 时间；显示日期使用配置时区 |
| `naming_date + naming_timezone` | 请求首次建立时冻结的本地日期及其时区身份/偏移；重试不得按“今天”重新计算名称 |
| `repository_mode` | 首个实现只接受 `managed-local`；由 KnowledgeFlow 在新 KB 根内建立对用户透明、无远端的本地 Git 版本库 |
| `version_engine_policy_id + revision` | 本次使用的本地版本引擎政策；至少冻结引擎种类、仓库 object format、受管 ref、树条目/路径规则、规范提交消息、技术提交身份、UTC 提交时间/重试规则、精确字节、离线执行、宿主配置隔离、禁止远端副作用和回执重建规则，不是 GitHub 账号或远端配置 |

用户明确说“新建一个库”但未给出父目录时，必须先确认父目录。模型建议新建、目录看起来合适、或来源暂时无法分类，都不构成新建授权。

`repository_mode: inherited` 和 `unmanaged` 暂不属于 SOP-10 首个切片；实现收到这些值时应明确返回“当前不支持”，不得把用户已有仓库当成自管仓库，也不得降级成无检查点运行。Capture 保存和无目标地图终点不调用 SOP-10，因此不受本地 Git 前置限制。正式产品以后可以增加已有仓库接入，但必须另行解决用户暂存区、仓库策略和回滚边界。

## 3. 名称、路径与稳定身份

三个概念必须分开：

| 概念 | 作用 | 是否可变 |
|---|---|---|
| `kb_id` | UUIDv7 稳定身份 | 创建后不可变 |
| `storage_name` | 父目录下的物理目录名 | 首版创建后不可自动更改 |
| `display_name` | UI、README 和报告中的可见名称 | 用户明确批准后可改，不改变前两项 |

分配规则：

1. 用户给出名称时，系统展示规范化后的安全 `storage_name` 和 `display_name`；只有用户输入本身可直接安全使用时才无需二次确认。
2. 用户未给出名称时，两者初值均为请求首次建立时冻结的 `naming_date` 下的 `YYYY-MM-DD-NN`，例如 `2026-10-13-01`；跨午夜或换机重试不重新计算日期。
3. `NN` 从 `01` 开始，在同一父目录、同一日期下递增。分配、目标冲突检查和目录发布必须受同一父级排他锁保护。
4. 序号判断同时检查现有有效 manifest、同名目录和本流程拥有的未完成事务；不能只扫描当前有效 KB。
5. 策展后给出的语义名称只是显示名建议。首版接受建议时只改 `display_name` 和 README；物理目录迁移另设契约。

## 4. 最小目录与职责

初始化成功后至少存在：

```text
<kb-root>/
├── .git/                    # managed-local 本地版本元数据；不配置远端
├── kb.yaml
├── README.md
├── .gitignore
├── .knowledgeflow/
│   ├── routes/
│   ├── runs/
│   ├── transactions/
│   └── receipts/
├── inbox/
├── raw/
│   ├── text/
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

Git 不保存空目录。首个实现因此在需要随版本库存在、但尚无业务内容的叶目录中写入固定零字节 `.gitkeep`；校验器把它视为结构标记，不视为 inbox、原料、提案、SCHEMA 或可信 Wiki 内容。被精确忽略的 `.knowledgeflow/transactions/`、`.knowledgeflow/receipts/` 和锁/临时目录属于本机运行结构，在首次打开时确定性重建，不要求进入 commit。干净 checkout 加一次非修复性打开必须得到同一最小骨架，不能依赖首次创建机器上偶然遗留的空目录。

`managed-local` 只表示使用 KB 根内的离线本地 Git 版本历史。KnowledgeFlow 不创建 GitHub 项目，不配置 remote，不执行 fetch/pull/push，也不要求账号或网络。版本适配器不得运行仓库 hooks、外部 clean/smudge filter、签名器或凭据助手；具体使用受控 CLI 还是内嵌兼容实现留给实现门禁，但行为必须等价、可测试且跨平台配置化。

| 路径 | 临时态允许内容 |
|---|---|
| `.knowledgeflow/` | 机器可读治理记录；`routes/`、`runs/` 纳入版本检查点，`transactions/`、`receipts/` 只作本机恢复/操作记录；均不得当作可信知识 |
| `inbox/` | 已确认属于该 KB、尚未完成原料归档的引用或副本 |
| `raw/` | 精确来源副本及独立来源映射；首个 UTF-8 Capture 切片固定进入 `raw/text/`，不混入模型结论；其他类型目录为后续适配器预留 |
| `proposals/` | T1/T2 地图、变更和维护提案 |
| `wiki/` | `provisional` 阶段必须为空 |
| `schema/` | 初始化时只含追加式 `log.md`，不得伪造正式 `SCHEMA.md` |
| `_archive/` | 初始化时为空 |

`.knowledgeflow/transactions/` 可以保存恢复所需证据，但有效 KB 清单不得把仅存在于初始化 staging 中的半骨架列为可用库。

`.gitignore` 只忽略 `.knowledgeflow/transactions/`、`.knowledgeflow/receipts/` 和锁/临时文件；路由记录、运行身份、地图、变更集、批准记录、manifest、SCHEMA、Wiki 与日志仍须纳入版本检查点。不尝试把包含结果 commit 的回执写进其自身所指向的同一个 Git commit。未来 KB 备份必须明确覆盖或可重建这些被忽略的恢复证据；当前隔离切片尚不声称已具备 KB 备份。

## 5. `kb.yaml` v1 最小契约

首个实现使用受限 UTF-8 YAML。键固定，未知键拒绝；示意值如下：

```yaml
format: knowledgeflow.kb-manifest
format_version: 1
kb_id: "<uuidv7>"
storage_name: "2026-10-13-01"
display_name: "2026-10-13-01"
created_at: "<UTC ISO-8601>"
created_by: "<request source>"
creation_request_id: "<bootstrap_request_id>"
lifecycle: provisional
domain:
  status: pending
schema:
  status: absent
wiki:
  status: empty
version_control:
  mode: managed-local
  engine: git
  remote: none
search:
  trusted_visibility: none
gbrain:
  federated: false
```

`kb.yaml` 只描述身份和生命周期，不保存知识正文。初始化时 `domain.status` 必须为 `pending`、`schema.status` 必须为 `absent`、`wiki.status` 必须为 `empty`、`trusted_visibility` 必须为 `none`。

首个实现前可以把上述示意转成 JSON Schema 或等价校验器，但不得改变字段含义、默认信任状态或稳定身份语义；任何新增必填字段须回到本契约复核。

## 6. 确定性执行

### A0：验证授权与父目录

1. 解析 `parent_root`，按绑定的 `root_policy_id + revision` 验证它仍位于配置允许根内，不经过链接、重解析点或路径逃逸进入其他位置。允许根按部署配置解析，不能假设盘符、分区数量或项目安装目录。
2. 按 `version_engine_policy_id + revision` 验证受控本地版本适配器可用且满足总览第 4.1 节：固定 `refs/heads/knowledgeflow`、不读取用户提交身份、不受系统/全局 Git 定制影响，并能在完全离线、无账号、无远端副作用的条件下保存精确字节和创建 commit；失败时不得创建目标 KB。
3. 验证最终 KB 路径不位于另一个 Git 工作树内部，也不包含既有 `.git`、文件或未知目录；首个切片不创建嵌套仓库，也不接管用户已有仓库。
4. 获取父级创建锁；锁失败不创建任何目标文件。父目录不是版本库，不对其执行 Git 操作。

### A1：分配名称与身份

1. 按第 3 节得到 `storage_name` 和 `display_name`。
2. 创建一次 `kb_id` 和一次 `transaction_id`；同一 `bootstrap_request_id` 的可证明重试复用原身份。
3. 目标已是有效 KB 时只允许幂等重开；非空非 KB 目录、身份不一致或未知残留均停止并报告冲突。

### A2：在本流程拥有的 staging 中准备

1. 在 `parent_root` 下建立可识别且只属于本次事务的隐藏 staging。
2. 写入完整目录、manifest、README、精确 `.gitignore` 和初始化日志。
3. 不复制原料，不建立 `SCHEMA.md`、索引、模块、Wiki 页面、GBrain source 或可信检索入口。
4. 在 staging 根建立 `managed-local` 本地版本库；显式保持 remote 为空，以固定技术身份、事务中冻结的时间和 `refs/heads/knowledgeflow` 创建只含最小骨架的初始 root commit。提交消息绑定 `bootstrap_request_id + transaction_id`，但 manifest 不保存结果 commit；宿主默认分支、姓名/邮箱、换行转换、hooks、filter、签名或凭据配置不得改变结果。
5. 验证 staging 的路径、文件类型、UTF-8、manifest、空 Wiki、仓库 object format、初始 commit 树、每个 `100644` blob 与工作树精确字节、无远端状态和工作树整洁性；拒绝符号链接/reparse、路径规范化碰撞，commit 不得包含 staging 外路径。

### A3：发布与版本检查点

1. 在仍持有父级锁时，将完整 staging 发布为最终目录；不得逐文件暴露半骨架。
2. 从最终路径重新打开本地版本库，核对受管 ref、初始 HEAD、完整树、blob 精确字节、无 remote、manifest 身份和目标路径；发布期间任何漂移都停止并进入恢复判断。
3. 验证初始 root commit 只包含本次 KB 最小骨架，没有父目录文件、原料、可信页面或 staging 路径泄漏。
4. Git 初始化、提交、发布后重开或结果树校验失败时不报告成功；可证明未被外部修改时撤销本批发布，否则保留证据并进入 `recovery_required`。
5. 只有最终目录、初始 commit 和已经持久化并回读的本机回执都互相匹配时才返回成功；结果 commit 不写回受其自身覆盖的 manifest，也不触发任何网络操作。

最终目录已经出现但初始化事务/回执尚未闭合时，KB 发现与打开入口必须把它标为 `recovery_required`，不得仅因 `kb.yaml` 可解析就把它列为可用 `provisional` KB。可用判定至少要求：manifest 和仓库身份一致、没有未解决初始化事务、原始或确定性重建的初始化回执有效、受管 ref 的初始 commit 与回读树匹配。

## 7. 回执

成功或幂等成功必须返回：

- `bootstrap_request_id`
- `transaction_id`
- `kb_id`
- `path`
- `storage_name`
- `display_name`
- `root_policy_id + revision`
- `naming_date + naming_timezone`
- `lifecycle: provisional`
- `repository_mode`
- `version_engine_policy_id + revision`
- `repository_root + initial_commit + remote: none`
- `result: created | already_completed`
- `trusted_visibility: none`

失败回执必须区分至少：输入无效、父目录越界、路径冲突、锁不可用、已有身份冲突、staging 校验失败、发布状态未知、Git 检查点失败和恢复需要人工处理。失败不得携带虚假的成功 `kb_id`；已经可靠建立的身份应作为诊断事实返回而不是重新生成。

## 8. 幂等、失败与恢复

- 同一 `bootstrap_request_id` + 同一输入重试，返回同一 KB 或继续可证明属于本次的未完成事务。
- 同一幂等身份但父目录、名称、冻结命名日期/时区、允许根策略、版本引擎政策或仓库身份不同，返回幂等冲突。
- 不以目录名相同推断属于同一请求；必须核对 manifest 与事务证据。
- 只清理本流程创建且身份、范围、文件状态全部可证明的 staging；未知文件或含用户内容的残留原样保留。
- 不运行 `git reset --hard`，不访问远端，不覆盖初始化后出现的用户修改。
- 初始化提交成功后的业务撤销不是崩溃回滚；须另行显示影响并获得用户确认。

本机回执不是唯一历史真源。干净 checkout、换机或只保留 Git 历史的恢复目标缺少本机回执时，恢复器可以从 `kb.yaml.creation_request_id`、初始化日志、唯一可达的初始化 commit 及其提交身份、完整树和无远端政策重建一份标记为 `reconstructed` 的本机回执。只有这些事实唯一且互相匹配时才允许重建；提交身份歧义、树被未知 commit 改写、manifest 不匹配或存在未解决事务时进入 `recovery_required`。

本地 Git 只提供版本历史，不提供介质故障或整机丢失恢复。首个隔离实验 KB 可以按实验清理规则删除并从来源重建；在真实、不可替代内容进入前，必须另行建立并演练包含 `.git/` 和必要本机恢复证据的 KB 备份/新目标恢复方案。本 SOP 不复用 Capture Store 的 Backup Bundle，也不把 remote/push 冒充备份。

## 9. 与后续 SOP 的交接

```text
SOP-10 成功
  ├─ 无原料预建：输出待用报告并结束
  └─ 有精确来源且目标已确认：
       路由层复制—校验—记录到 raw/
       → SOP-20 生成 T1/T2 地图
       → 地图处结束，或由 SOP-30 准备精确变更
       → 用户批准
       → SOP-30 首次启用门禁 + 首批可信写入在同一事务中提交
```

SOP-10 不把“建库”解释成深度处理授权或可信写入批准。

## 10. 首个实现验收

至少覆盖：

- 有名称和无名称的首次创建；日期序号按配置时区分配。
- 跨午夜重试仍复用首次冻结的命名日期；不同机器/盘符布局只依赖各自显式允许根配置，不改变契约。
- 两个进程并发分配同日序号而不重名。
- 同一请求重试返回同一 `kb_id`；相同幂等键不同输入明确冲突。
- 有效已有 KB 重开、非空非 KB 目录、同名未知残留和路径逃逸。
- staging 写入、发布、Git 检查点各阶段故障后的恢复或安全停止。
- 无网络、无 GitHub 账号和无远端配置时仍能完成初始化；执行过程不运行 hooks、外部 filter、签名、凭据助手或网络 Git 命令。
- 宿主配置了不同默认分支、姓名/邮箱、自动换行、hooksPath、filter、签名、凭据助手、pager/editor 或文件监视助手时，初始化仍使用冻结的 object format、受控 `refs/heads/knowledgeflow`、`100644` 树条目、规范提交消息、固定技术身份和精确工作树字节，不执行外部副作用。
- Windows/Linux 上相同规范输入的受管路径、blob 和树语义一致；符号链接/reparse、可执行位、大小写折叠或 Unicode 规范化碰撞不会被静默接受。
- 同一初始化事务重试复用冻结的提交事实，不产生第二个等价 root commit；受管 ref 被外部进程抢先改变时失败关闭，不覆盖并发结果。
- 目标位于另一 Git 工作树内、已有 `.git` 或非空未知目录时安全拒绝，不创建嵌套或接管式仓库。
- 初始 root commit 只包含最小 KB 骨架，结果树不越出目标 KB，也不包含原料或可信知识。
- 初始化结果不存在 `SCHEMA.md` 或可信页面，且不进入可信搜索。
- 初始化 commit 在全新 checkout 中仍能得到完整必需目录；零字节 `.gitkeep` 不被误判为知识内容。
- 干净 checkout、换机和只保留 Git 历史的恢复目标可以在完整验证后重建本机回执；证据不完整时失败关闭。
- 最终目录已发布但初始化回执未闭合的故障窗口不会被列为可用 KB；恢复完成前后续路由、地图和可信写入均被拒绝。
- 后续放入原料后重试初始化不会覆盖 `raw/`、提案、日志或用户内容。
- 修改 `display_name` 不改变 `kb_id`、`storage_name` 或物理目录。

首个切片不实现已有仓库 `inherited` 接入、无版本检查点的可信 Wiki、多 KB 批量创建、物理目录改名、GBrain 注册或生产知识库创建。
