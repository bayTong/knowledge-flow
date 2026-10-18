# SOP-30：批准后写入可信知识

> 状态：Review Candidate（阶段二联合契约收口稿；尚未实现，也不授权真实 KB 写入）<br>
> 历史编号：SOP-002；新知识库首次启用门禁承接历史 SOP-000B<br>
> 形成日期：2026-10-13<br>
> 技术复核修订日期：2026-10-15<br>
> 本地版本边界修订日期：2026-10-15<br>
> 概念边界澄清日期：2026-10-18<br>
> 目标：把获批地图选择转成精确变更集，并由无模型、受限、可恢复的写入器应用到单一目标 KB<br>
> 上游：[深入策展流程总览](00-deep-curation-workflow-深入策展流程总览.md)与[SOP-20 材料深度理解与策展地图](20-sop-deep-curation-map-材料深度理解与策展地图.md)<br>
> 可选新库准备：[SOP-10 新建知识库骨架](10-sop-new-kb-bootstrap-新建知识库骨架.md)

## 1. 两个阶段必须分开

SOP-30 包含两个职责不同的阶段：

1. **Prepare**：读取精确地图、用户选择和目标快照，完成查重与组织判断，生成全部最终候选字节和精确变更集；只写 `proposals/changes/`。
2. **Apply**：在用户批准完整变更集后，由受限写入器按原样应用；不调用模型、不补写内容、不扩大范围。

Prepare 可以使用 Agent；Apply 必须是确定性执行器。用户说“帮我深入整理并入库”可以授权来源处理和方案准备，但在精确变更尚不存在时不能预先批准 Apply。

## 2. 首个切片边界

首个实现只处理：

- 一份精确文本 Capture 来源；
- 一份已发布的 SOP-20 地图版本；
- 一个由 SOP-10 创建、具有 `managed-local` 离线本地 Git 版本库的全新隔离 `provisional` KB；
- 首批 SCHEMA、导航和可信页面创建；
- 新知识库首次启用门禁与首批可信写入的同批提交；
- 提交后的显示名元数据变更。

这里的首批 `SCHEMA` 是该文件式知识库的最小表示与维护契约：规定首批页面、来源引用、导航和必要校验怎样组织。它不要求首个切片建立领域 Ontology、通用知识图谱 schema、图数据库或推理引擎；这些能力只有在真实跨来源复用、关系查询或一致性维护需求出现后，才通过独立门禁引入。

已有 `active` KB 更新、删除/归档、跨 KB 写入、物理目录迁移、自动合并冲突和 GBrain 同步全部后置。材料出现这些候选时只标记 `deferred/unsupported`。

### 2.1 新知识库首次启用门禁（历史 SOP-000B）

首次启用门禁不是第四条用户流程，也没有独立执行器。它只在目标是 SOP-10 创建的 `provisional` KB 时，由 SOP-30 判断这个新库是否可以随首批可信内容一起转为 `active`。已有 `active` KB 更新时跳过本门禁。

下列条件必须全部满足：

1. 当前 `kb.yaml` 可解析，`lifecycle: provisional`，`kb_id` 与目标一致。
2. 当前没有未知或未恢复的 KB 事务，目标 Git 前置状态与变更集一致。
3. `raw/` 副本与 Capture Payload 哈希一致，来源旁车映射可回读，Capture 规范原件未被替换。
4. SOP-20 地图仍是方案绑定的精确版本，处理范围、缺口和延期项可见。
5. 变更集包含最小领域边界、最小 `SCHEMA.md`、至少一个首批可信页面、导航、日志和最终 manifest 的精确字节。
6. 所有页面都能指向精确来源映射或 Evidence locator；来源主张、系统推断和未核实事实没有混写。
7. 候选树验证通过，不存在越界路径、未批准文件、无依据链接或留待 Apply 时再作语义决定的占位符。
8. `managed-local` 版本库能够在无网络、无账号、无远端副作用下建立提交后检查点；任何批准绑定或目标前置状态变化都会使原批准失效。

领域边界和 SCHEMA 只需覆盖首批获批内容，不得把第一份材料推断成永久完整领域模型。目标 manifest 至少把以下状态作为批准前已存在的精确候选：

```yaml
lifecycle: active
domain:
  status: approved
schema:
  status: approved
wiki:
  status: initialized
search:
  trusted_visibility: local
gbrain:
  federated: false
```

完整 manifest 继续保留 SOP-10 建立的稳定身份、创建时间、`storage_name` 和版本控制信息；首次启用不得改变 `kb_id` 或 `storage_name`。最终候选还必须保存非自引用的 `last_change_set_id + last_transaction_id`，其中 `last_transaction_id` 等于 Prepare 时预分配并冻结的 `apply_transaction_id`，用于把 manifest、治理日志和结果 commit 重新关联，但不得保存包含自身的结果 commit。`trusted_visibility: local` 只表示本地可信范围可读，不表示加入 GBrain、GitHub、远端同步或联邦搜索。

## 3. Prepare 输入

必须绑定：

- `curation_run_id`
- `map_id + map_version + map_sha256`
- `decision_set_id + version + decision_sha256`
- 精确 Capture 与 `raw/` 来源映射
- 决定记录中逐候选的接受、修改、拒绝和延期事实
- 单一 `target_kb_id` 与规范路径
- 目标 `kb.yaml` 哈希、版本引擎政策、`refs/heads/knowledgeflow` 受管 ref、`target_content_base_commit`，以及所有待触碰路径的当前哈希/不存在证明
- 当前 KB 格式政策；新库使用本批准备并展示的最小 SCHEMA 候选

地图或用户选择还在变化时可以重新 Prepare，但必须产生新的变更集版本。

## 4. 查重与组织判断

Prepare 阶段可以读取目标范围并决定候选如何组织，但每个结果必须进入方案：

| 判断 | 首个新库切片的处理 |
|---|---|
| 新概念/页面 | 准备新文件最终字节 |
| 多个候选应合并 | 在方案中显示合并后的最终页面和来源对应 |
| 候选重复 | 标记跳过及理由，不创建空变更 |
| 来源内部存在矛盾 | 在候选正文中并列观点与证据，不替用户裁定事实 |
| 需要未批准的标签、模块或结构 | 把相应 SCHEMA/导航变化纳入同一方案；否则延期 |
| 需要更新、删除、归档已有可信页面 | 首个切片标为不支持，不执行一半 |

不能为满足模板数量编造链接、标签或页面。页面形式由获批最小 SCHEMA 决定，不把旧版四种页面模板升级为全产品硬编码。

## 5. 变更集 v1

每个可批准对象存放为：

```text
<kb>/proposals/changes/<change_set_id>/v0001/
├── change-set.yaml
├── files/                 # 每个 create/replace 操作的精确候选字节
└── review.md              # 面向人的影响、证据和差异说明

<kb>/proposals/changes/<change_set_id>/approvals/
└── <approval_id>.yaml     # 对某个不可变版本的批准或撤回记录
```

`change-set.yaml` 至少冻结：

| 字段 | 含义 |
|---|---|
| `change_set_id` / `version` | 稳定 ID 与单调版本 |
| `change_set_sha256` | 对绑定输入、规范化操作清单、`files/` 路径/哈希清单及 `review.md` 哈希计算的摘要；摘要计算排除该字段自身 |
| `prepare_transaction_id` / `apply_transaction_id` | 前者标识本版本提案发布事务；后者在 Prepare 时预分配并进入候选 manifest/日志，批准后的 Apply 必须复用该身份，不得在执行时另换 ID |
| `target_kb_id` / `target_path` | 单一目标身份 |
| `base_manifest_sha256` / `target_content_base_commit` | Prepare 开始时的目标 manifest 与本地内容前置状态；这里的 commit 不是远端状态，也不同于随后保存提案/批准产生的协议检查点 |
| `source_binding` / `map_binding` | 来源和地图精确版本 |
| `decision_binding` | 决定记录的 ID、版本和精确文件摘要；每个被采用或延期的候选必须能回到稳定 `candidate_id` |
| `operations` | 有序的 `create` 或 `replace-exact`；目标相对路径、候选哈希、预期旧哈希或不存在证明 |
| `deferred` | 明确不执行的候选与原因 |
| `validation_profile` | 写入前后必须运行的检查集合及版本 |
| `activation` | 首个新库为“首次启用门禁”的精确候选；已有 active KB 时为 `null` |
| `prepared_by` / `prepared_at` | 处理器、提示词/工具版本和 UTC 时间 |

首个切片不允许 `delete`、通配路径、绝对目标路径、符号链接/reparse、可执行树条目、大小写折叠或 Unicode 规范化后碰撞的路径、运行时生成正文、网络调用或“更新所有相关文件”这类开放操作。全部受管文件固定为 Git mode `100644`；所有候选正文必须在批准前已经存在于 `files/`，用户可以逐文件查看最终字节和 diff。

Prepare 必须先预分配稳定的 `apply_transaction_id`，再在本流程拥有的临时位置生成完整目录；最终 manifest、治理日志、操作清单和 `files/` 中的候选字节都绑定该 ID。验证路径、哈希和引用后才原子发布该版本。`review.md` 必须由同一冻结事实生成，其精确哈希进入 `change_set_sha256`，避免用户看到的说明与被批准文件脱节。无效或中断输出不得占用一个看似可批准的正式版本；已经发布的版本不可原地覆盖。

### 5.1 Prepare 发布检查点

`prepared` 不是“目录已经出现”。Prepare 发布必须复用 SOP-20 第 7.1 节的目标 KB 工作工件事务：在统一锁内绑定受管 ref 和 `target_content_base_commit`，原子发布完整变更集目录，再以受控版本适配器创建只包含该版本提案的本地检查点。结果 commit 写入本机回执；`change-set.yaml` 保存非自引用的 `prepare_transaction_id` 和预分配的 `apply_transaction_id`，但不保存包含自身的结果 commit。只有事务、回执、commit、完整目录和摘要匹配时状态才是 `prepared`。

该结果 commit 称为 `change_set_checkpoint_commit`。它可以由本机回执直接取得，也可以在回执缺失时从唯一包含相同 `change_set_id + version + prepare_transaction_id` 的可达 commit 和当前字节重建。歧义、目标内容路径变化、未知 ref 漂移或未解决事务均失败关闭。

## 6. 批准契约

有效批准至少记录：

- `approval_id`
- `change_set_id + version + change_set_sha256`
- `target_kb_id + base_manifest_sha256 + target_content_base_commit`
- `change_set_checkpoint_commit`
- `map_id + version + map_sha256`
- `decision_set_id + version + decision_sha256`
- 明确批准人、批准时间和决定 `approved`
- 被批准的完整操作范围；首个切片不支持只批准未重新生成计划的任意子集

批准、拒绝与撤回各自写成追加式、不可变记录；不得通过覆盖旧 `approval_id` 改写历史决定。批准记录不属于 `change_set_sha256` 的自引用输入，但必须绑定该摘要和 `change_set_checkpoint_commit`。

用户决定持久化后，系统须再使用同一工作工件事务创建只包含该批准/拒绝/撤回记录的本地检查点。批准记录保存 `approval_transaction_id`，不保存包含自身的结果 commit；结果由本机回执或唯一可达 commit 确定。只有该检查点闭合后状态才是 `approved/rejected/withdrawn`。Apply 把闭合批准对应的结果称为 `approval_checkpoint_commit`，并要求执行开始时受管 ref 仍精确指向它；技术 commit 只封存决定，不替代决定人的业务身份。

以下任一发生，批准自动失效：

- 变更集、候选文件、地图版本、来源绑定、决定记录或用户选择变化；
- 目标 manifest、`target_content_base_commit` 以来任何可信/待触碰路径的前置事实变化，或 Apply 时受管 ref 不再等于可证明的 `approval_checkpoint_commit`；
- 目标生命周期、只读/锁定状态或恢复状态变化；
- 验证规则版本变化会改变结果；
- 用户撤回批准。

首版不设置任意时间超时；是否失效只由绑定事实和显式撤回决定。计划变化时创建新版本并重新批准，不修改旧批准记录。

## 7. Apply 事务

### T0：装载并验证批准

解析受限 YAML，重新计算地图工件、决定文件、变更集、候选文件和 `review.md` 摘要，验证所有 ID、候选引用、哈希、路径、操作和批准绑定；再从闭合回执或唯一版本历史解析 `change_set_checkpoint_commit` 与 `approval_checkpoint_commit`。失败或结果不唯一时零目标写入。

### T1：获取单一 KB 写锁

锁绑定规范 `kb_id` 与路径；锁内再次读取 manifest、`managed-local` 仓库状态，验证 `HEAD` 符号指向受管 ref、受管 ref 精确等于 `approval_checkpoint_commit`，并核对 `target_content_base_commit` 以来只增加了当前变更集检查点与当前批准记录检查点，且可信/待触碰路径前置字节未变。锁不可用、目标漂移、detached/其他分支、仓库出现 remote/未知策略或未知事务存在时停止。待触碰路径存在未被变更集精确绑定的 staged/unstaged/工作树变化时批准失效；目标外变化可以保留，但不得进入本批提交。

### T2：建立事务记录与候选树

以变更集内已经冻结的 `apply_transaction_id` 建立或幂等重开唯一 Apply 事务，不得在批准后生成新的事务身份。在 `.knowledgeflow/transactions/<apply_transaction_id>/` 写入事务记录、批准副本、候选树、首次启动时冻结的技术提交时间，以及恢复所需的旧字节/不存在证明。若同一 ID 已存在但绑定事实、状态或字节不一致，进入 `recovery_required`；候选树只能包含批准路径。

### T3：写入前验证

对完整候选状态运行：manifest/SCHEMA 解析、路径和 UTF-8、来源引用、内部链接、导航、日志、页面格式、无越界操作，以及新知识库首次启用前置检查。验证器不得通过调用模型“顺便修复”。

### T4：应用精确字节

只执行获批的 `create` 和 `replace-exact`。每个目标写入使用同目录临时文件、耐久刷新和原子替换；跨文件进度由事务日志记录。`raw/` 与 Capture Store 不在可写范围。

### T5：发布激活候选

首个新库中，普通内容、SCHEMA、导航和日志先应用；目标 `kb.yaml` 的 `active` 字节最后应用。`active` manifest 本身不是可见性提交点：在事务 committed 前，可信读取仍因未完成事务而关闭。

### T6：回读验证与 Git 提交

逐文件回读并比对获批 SHA-256，重新运行验证，确认没有未批准路径变化，并再次核对 `refs/heads/knowledgeflow` 仍等于 `approval_checkpoint_commit`。使用总览第 4.1 节的受控版本适配器和隔离索引，以 `approval_checkpoint_commit` 为唯一父提交创建只包含本批获批目标、manifest 和治理日志差异的本地 commit，再以比较后更新推进受管 ref；ref 被外部进程抢先改变时不得覆盖并发结果。已封存的变更集和批准记录从父提交继承且不得在 Apply 中改写。ref 更新后只对齐本批路径在默认索引中的条目，目标外 index 条目及其 staged/unstaged 语义保持不变；该对齐尚未完成时事务仍为 `git_committed`。验证结果 commit 的父提交、树差异、每个 blob 精确字节、默认索引和工作树没有越界，也没有吞入或改写原有 staged/unstaged 变化。提交使用版本政策固定的技术身份和事务中冻结的时间，消息包含 `change_set_id` 和 `transaction_id`；manifest 与治理日志保存相同的非自引用身份。事务/回执目录由 SOP-10 的精确 `.gitignore` 排除。

版本适配器不得配置或访问 remote，不得执行 fetch/pull/push，不得请求 GitHub/其他账号，也不得运行仓库 hooks、外部 clean/smudge filter、签名器或凭据助手。上述限制属于可测试的执行边界，不依赖“当前刚好断网”。

### T7：提交回执

本地 Git 提交成功后，在 `.knowledgeflow/receipts/` 持久化包含结果 commit 的 committed 回执，再把事务标记为完成并清理可安全删除的 staging。若进程在 Git 提交后、回执完成前崩溃，恢复器用提交消息中的事务身份、manifest/治理日志中的非自引用身份、目标字节和批准记录重建判断；只有回执、结果 commit、最终 manifest 和实际文件全部互相匹配时才向当前调用报告成功。

所有 KnowledgeFlow 可信读取入口必须执行同一个可见性谓词：目标 manifest 为 `active`，不存在未解决的本 KB Apply 事务，并且最近一次首次启用/可信写入的 committed 回执、结果本地 commit 与回读文件互相匹配。任一事实缺失、冲突或仍需恢复时，返回“可信状态暂不可用/需要恢复”，不得仅看 `kb.yaml` 就暴露 T3。直接使用文件管理器查看磁盘不等同于产品已经宣告可信提交。

## 8. 状态、事务与恢复

变更集/批准状态和 Apply 事务状态不是同一个状态机：

```text
change set: prepared -> approved -> applied
                   |         |-> superseded
                   `-> rejected / withdrawn

apply txn:  applying -> verifying -> git_committed -> committed
                |           |             |
                v           v             v
          rolling_back -> rolled_back   recovery_required
                |
                v
        recovery_required
```

`prepared/approved` 分别只在提案检查点和批准检查点的事务、回执、commit 与字节全部闭合后成立；目录或记录单独出现不构成相应状态。Apply 的事务身份在 Prepare 时预分配，运行记录只在 T2 建立或幂等重开。`git_committed` 表示 Git 已包含获批字节、但 committed 回执或事务完成标记尚未闭合，不能对外报告成功，也不能打开可信可见性。

- 进程重启时先扫描本 KB 未完成事务；未恢复前拒绝新 Apply。
- 能证明变更只来自本事务且目标没有后来编辑时，可继续或恢复事务前精确状态。
- 发现未知文件、外部编辑、身份不符或无法判断提交点时，保留全部证据并进入 `recovery_required`，不得猜测清理。
- 回滚范围只限本变更集拥有的路径；不执行全仓库 hard reset，不覆盖后来编辑。
- Git commit 是版本证据，不替代事务日志、前置检查、回读验证或 committed 回执。
- 启动、可信读取和下一次 Apply 都必须先分诊 `applying/verifying/git_committed/rolling_back/recovery_required`；不能因为 manifest 已是 `active` 就跳过恢复。

干净 checkout、换机或只保留本地 Git 历史的恢复目标可能没有 `.knowledgeflow/receipts/`。恢复器可以从 manifest/治理日志中的 `last_change_set_id + last_transaction_id`、唯一可达的带相同提交身份的 commit、版本化变更集与批准记录以及当前文件字节重建一份标记为 `reconstructed` 的 committed 回执。只有链条唯一、目标字节匹配、可信路径未被未知后续 commit 改写且不存在未解决事务时才允许重建；否则进入 `recovery_required`。本机回执因此是运行证据和快速判定入口，但不是脱离版本历史的唯一真源。

本地 Git 不提供介质或整机灾难恢复。当前切片只允许可删除、可重建的隔离 KB；正式或不可替代知识进入前，必须另行批准并演练覆盖工作树、`.git/` 历史和必要本机恢复证据的 KB 备份/新目标恢复方案。Capture Store 的 Backup Bundle、GitHub remote 或一次 push 都不能被自动解释为该方案已经成立。

## 9. 幂等与并发

- Apply 幂等键为 `target_kb_id + change_set_id + version + change_set_sha256`。
- 已 committed 的精确重试返回原回执，不重复页面、日志、manifest 更新或 Git commit。
- 相同 `change_set_id/version` 但哈希不同为完整性冲突。
- 同一 KB 同时只允许一个 Apply；不同 KB 的未来并发不属于首个切片。
- 批准后、锁前或锁内出现目标漂移均不自动合并；返回需要重新 Prepare。

## 10. 提交后撤销

崩溃恢复和业务撤销不同：

- **提交前恢复**：按事务证据回到精确前置状态。
- **提交后撤销**：基于目标本地 commit 和当前文件创建一个新的反向变更集，展示影响并重新批准；保留原 commit、地图、批准和回执。不得回退整个分支或抹除该批之后的用户笔记/其他获批变更。

首个切片不承诺自动生成任意反向计划。若批次 B 之后的用户笔记 A 与 B 修改同一路径或语义上依赖 B，Prepare 必须把冲突和保留选择展示给用户，不能用旧 commit 字节直接覆盖 A。若无法安全构造撤销，只报告需要人工方案，不能删除 Capture 原件、`raw/`、后来修改或审计历史。

## 11. 策展后显示名

首批入库成功后，Agent 可以根据获批内容提出一至三个显示名及理由。用户可以接受、修改、继续保留日期序号或延期。

显示名变化必须形成新的精确元数据变更：只修改 `kb.yaml.display_name` 和 README 对应字段，重新经过 Prepare、批准和 Apply；不得改变 `kb_id`、`storage_name` 或物理目录，也不是首次启用成功的前置条件。

## 12. 回执与报告

成功或失败回执至少包含：

- 变更集、批准和事务身份；
- 来源、地图和目标绑定；
- 实际创建、替换、跳过和延期路径；
- 每个目标的预期/结果哈希；
- 写入前后验证结果；
- 目标内容基础、变更集检查点、批准检查点与 Apply 结果本地 Git commit；
- 本地版本模式及 `remote: none` 验证结果；
- 激活旧/新状态；
- 恢复、回滚或人工处理状态；
- 实际执行时间，不含 Prepare 的模型调用则明确为零。

报告必须由事务和回读事实生成，不能由模型根据计划编写成功结论。

## 13. 首个实现验收

至少覆盖：

- Prepare 只写提案，不改 `schema/`、`wiki/`、manifest 或可信搜索。
- Prepare 预分配的 `apply_transaction_id` 已进入候选 manifest/治理日志与变更集摘要；批准后执行必须复用该 ID，不能在 Apply 时产生不同的最终字节。
- 候选文件、`review.md` 和 diff 在批准前完整可读；批准绑定所有关键哈希，篡改任一项都会使批准失效。
- 提案版本和批准/拒绝/撤回记录分别在独立本地检查点与回执闭合后才发布对应状态；每个检查点后崩溃都能唯一续完、重建或失败关闭。
- 修改地图、方案、候选字节、manifest、Git 基线或目标文件后旧批准失效。
- 修改决定记录或任何候选 ID/决定绑定后旧批准失效。
- Apply 期间不调用模型或网络，不产生批准外路径。
- 无 GitHub 账号、无 remote 且主动断网时仍能完成本地 commit；执行期间不运行 hooks、外部 filter、签名、凭据助手或任何网络 Git 命令。
- 宿主 Git 的默认分支、用户姓名/邮箱、自动换行、hooksPath、filter、签名、凭据、pager/editor 或文件监视配置不能改变提交身份、blob 字节或触发外部副作用。
- Windows/Linux 对规范路径与 `100644` 树条目得到相同受管语义；符号链接/reparse、可执行位、大小写折叠或 Unicode 规范化碰撞均在写入前失败关闭。
- 两进程同 KB 竞争时只有一个进入写入；另一方安全失败或等待策略明确。
- Prepare 发布、决定发布及每个 T0–T7 故障点均不会虚报状态或成功；可恢复则精确恢复，不可判断则保留证据。
- 重试 committed 批次无重复副作用。
- 激活与首批写入共同提交，trusted 只在 committed 后可见。
- 在 `active` manifest 已落盘但 Git/回执尚未闭合的故障窗口，所有产品可信读取仍拒绝或进入恢复；不能提前暴露半提交 T3。
- 缺少来源、地图、方案、批准、最小 SCHEMA、首批页面或检查点时拒绝首次启用；已有 active KB 跳过首次启用门禁。
- 显示名变更不改变稳定身份或物理目录。
- Git 提交失败、回读失败和验证失败分别可观察。
- KB 仓库存在无关用户笔记 A 或 staged/unstaged 变化时不被策展批次 B 提交、覆盖或清空；受管 ref 漂移使原批准失效。Apply 结果 commit 以批准检查点为唯一父提交，差异只含获批目标、manifest 和治理日志，不重复或改写已经检查点化的提案与批准记录。
- 待触碰路径上的未绑定修改会使批准失效；目标外修改可保留。外部进程并发推进受管 ref 时比较后更新失败且不覆盖对方 commit。
- 干净 checkout、换机和只保留 Git 历史的恢复目标在完整验证后可以重建 committed 回执；未知后续可信路径修改必须失败关闭。
- 撤销策展批次 B 不会抹除来源、地图、批准、审计历史或 B 之后的用户笔记 A。

`prompts/sop-002-curator.md` 继续是沿用历史编号的参考资产，不能作为 Apply 执行器，也不能对真实 KB 运行。
