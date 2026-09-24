# KnowledgeFlow 设计权威与冲突登记

<!-- knowledgeflow-doc-status tests=300 capture_tests=285 script_tests=15 next_gate=C7V -->

> 状态：Approved Design；C7B 四操作适配与安装入口已完成本地实现与验证，当前 300 项全量通过；下一功能门禁为 C7V CLI 阶段独立验收（未授权）<br>
> 确认日期：2026-09-01<br>
> 补充确认日期：2026-09-03<br>
> C2 完成记录日期：2026-09-04<br>
> C3 编码前收口日期：2026-09-09<br>
> C3A/C3B 完成日期：2026-09-10<br>
> C3C 完成日期：2026-09-11<br>
> C3V 完成日期：2026-09-11<br>
> R0.1/R0.2 完成日期：2026-09-11<br>
> D0 内容与本地验证日期：2026-09-11<br>
> D0-F 版本化收口日期：2026-09-12（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> D0G 内容与本地验证日期：2026-09-12；版本化收口日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> C4-0 读取契约完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> R0.3D 诊断与裁决完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> R0.3F 完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> C4A 完成日期：2026-09-13（独立提交 `06cff02`；已 push 至 `origin/main`）<br>
> C4B 完成与版本化收口日期：2026-09-13（独立提交 `666ba18`；已 push 至 `origin/main`）<br>
> C4C 完成与版本化收口日期：2026-09-13（独立提交 `231ad09`；现已 push 至 `origin/main`）<br>
> C4V 完成与版本化收口日期：2026-09-14（独立提交 `1e38f2f`；已 push 至 `origin/main`）<br>
> C5-0 内容与本地验证日期：2026-09-14（独立提交 `ea530ad`；2026-09-16 已 push 至 `origin/main`）<br>
> 最小 Windows CI 首次通过日期：2026-09-16（提交 `c4d2c7b`；远端运行 `35075692046`）<br>
> C5A 内容与本地验证日期：2026-09-16（独立提交 `63a3250`；2026-09-18 已 push 至 `origin/main`）<br>
> C5B 内容与本地验证日期：2026-09-17（独立提交 `ab2a613`；2026-09-18 已 push 至 `origin/main`）<br>
> C5V 阶段验收日期：2026-09-17（独立提交 `a9913e2`；2026-09-18 已 push 至 `origin/main`）<br>
> C6A 业务事务崩溃恢复日期：2026-09-17（独立提交 `84ee1d7`；2026-09-18 已 push 至 `origin/main`）<br>
> C6B 派生状态重建日期：2026-09-17（独立提交 `f686941`；2026-09-18 已 push 至 `origin/main`）<br>
> C6C Store 迁移日期：2026-09-18（独立提交 `ea8f84e`；已 push 至 `origin/main`）<br>
> C6 远端门禁通过日期：2026-09-18（截至 `ea8f84e`；Windows CI 运行 `35319645501` 首次通过）<br>
> 渐进式处理方向红线确认日期：2026-09-21（具体方法与实现仍为 Draft）<br>
> R1 产品需求总收口内容与本地验证日期：2026-09-21（提交 `fa00c7e`；已随 `fb61358` 同步至 `origin/main`；不改变下一功能门禁）<br>
> 2026-09-21 研究输入登记日期：2026-09-21（提交 `3967047`；已随 `fb61358` 同步至 `origin/main`；不改变下一功能门禁）<br>
> D1A/D1B 文档信息架构内容与本地验证日期：2026-09-21（提交 `ba12420`；已随 `fb61358` 同步至 `origin/main`；不改变下一功能门禁）<br>
> C7-0 CLI 契约收口日期：2026-09-21（独立提交 `dbe8329`；已随 `fb61358` 同步至 `origin/main`）<br>
> C7A 协议能力与安全原语完成并独立版本化日期：2026-09-22（提交 `fb61358`；已同步至 `origin/main`）<br>
> R1.2 通用、自适应知识工作、工作知识层与渐进晋升需求收口日期：2026-09-23；2026-09-24 已按主 PRD 与非规范性导读的职责重新组织（本地提交 `3b8777f`；尚未 push；不改变下一功能门禁）<br>
> C7B 四操作适配与安装入口完成日期：2026-09-24（本批完成本地验证并独立版本化；尚未 push）<br>
> 当前状态同步日期：2026-09-24<br>
> 作用：规定各主题应以哪份文档为准，冻结 MVP 的最小决策，并登记尚未解决的设计冲突<br>
> 边界：本文件把 C3 `capture_text`、C4B `get_capture`、C4C `list_captures`、C4V、C5、C6、C7-0 与 C7A 记为已完成并已 push，把 C7B 记为已完成本地内容、验证和独立版本化但尚未 push；最后一轮已登记的干净 Windows CI 仍截至 `ea8f84e`。C7V、C8、生产初始化与后续路由未完成，本文整体仍不是 `Effective`

## 1. 为什么需要本文件

项目同时保存已归档的旧版完整 SOP、长期建设路线和 GBrain 集成研究，也维护当前需求基线、捕获规范和 Capture Envelope。它们形成于不同阶段，不能用“最后修改时间”或“文件名看起来最完整”判断谁优先；阅读入口统一见[文档阅读地图](README.md)。

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

当前项目已完成并独立版本化 C3 写入内核、C4 读取阶段、C5 追加阶段、C6 崩溃恢复/派生状态重建/Store 迁移，以及 C7A/C7B 受限 CLI 协议、生产分派和安装入口；完整 MVP-0 仍缺 C7V CLI 阶段验收与 C8 全量验收，因此本轮新规范最高状态仍为 `Approved Design`，不标记为 `Effective`。

## 2A. 编号空间与辨识规则

本仓库的编号来自不同文档职责，不能放在一条时间线上比较，也不能用编号大小判断优先级：

| 形式 | 所属文档/用途 | 示例 | 辨识要点 |
|---|---|---|---|
| `FR-*` / `NFR-*` | 需求基线中的功能/非功能需求 | `FR-WORK-001` | 是产品义务，不是实施步骤 |
| `P1`–`P12` | 需求基线中的治理原则 | `P12` | 是长期红线，不是阶段 |
| `D-001` 起 | 本文件中的已确认决策 | `D-016` | 按登记顺序分配 |
| `C-001` 起 | 本文件中的冲突/歧义记录 | `C-062` | **带连字符**，不是编码阶段 |
| `R1`、`R1.2` | 需求或文档收口批次 | `R1.2` | 记录一次治理工作，不是产品版本 |
| `C0`–`C8`、`C7A/B/V` | MVP-0 编码阶段和小批次 | `C7B` | **不带连字符**，由编码执行方案定义 |
| `CT-*`、`CLI-*` 等 | 各测试矩阵中的验收场景 | `CLI-20` | 只在对应测试矩阵内解释 |
| `T0`–`T3` | 产品信任层 | `T2` 提案隔离层 | 是概念层级，不是持久化格式 |
| `SOP-*` | 标准操作流程 | `SOP-000A` | 定义流程，不证明功能已实现 |

最容易混淆的是 `C-062` 与 `C7B`：前者是第 62 条冲突记录，后者是 C7 编码阶段的 B 批次。新增编号必须沿用其所属命名空间；若无法说明它属于哪一类，不应先创造编号。

## 3. 主题级权威矩阵

| 主题 | 当前权威 | 状态 | 其他文档如何处理 |
|---|---|---|---|
| 顶层产品需求：产品目标，用户与旅程，功能/非功能需求，范围，产品治理，依赖风险，验收标准和待决问题 | [KnowledgeFlow 主产品需求文档（Master PRD）](requirements-and-governance-baseline-需求与治理基线.md) | Approved Design | 本文件是唯一 L0 顶层需求入口；README、愿景、路线图、概念导读和 Draft 方法规范只作解释或实验，不得建立并行总需求或反向覆盖产品需求 |
| 文档优先级、冲突登记、功能门禁 | 本文件 | Approved Design | 发现新冲突先登记，再修改对应规范 |
| 用户知识任务、统一生命周期、工作知识空间、策展策略、Ontology、Schema、SOP、Karpathy LLM Wiki、RAG、GBrain、可信 Wiki 与知识图谱之间的跨主题概念关系 | [KnowledgeFlow 概念架构导读](knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md) | Explanatory Guide，非规范性 | 只负责解释和导航，不建立新需求、机器 schema、功能门禁或实现授权；冲突时服从本矩阵和各主题权威 |
| 临时 KB 创建与 `provisional` 生命周期 | [SOP-000A](sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md) | Approved Design | 旧 SOP-000 在冷启动、领域前置和 SCHEMA 前置方面被取代 |
| 捕获、Global Intake、人工路由和处理方式 | [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md) | Approved Design | 旧 SOP-001 步骤 0 和 SOP-006 不再负责捕获及最终归属决策 |
| 捕获身份、版本、哈希、事务、幂等和恢复 | [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md) | Approved Design | GBrain 原生 capture、可变页面或 sidecar 设想不得替代本地规范原件 |
| C3 `capture_text` 输入、原子 Item/Event、投影、写锁、幂等、回执及 actor/时间补充边界 | [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md) | Approved Design | 2026-09-09 已完成编码前收口；C3A/C3B 支撑实现于 2026-09-10 验收，C3C 完整事务与 C3V 独立验收于 2026-09-11 完成 |
| MVP-0 `capture-root` 与四个文本操作接口 | [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md) | Approved Design | 已确认每机配置、绝对解析、迁移、4/64 MiB 边界；C4-0 冻结读取语义，C5-0 冻结追加契约，C6A 冻结事务恢复边界；C6B/C6C 管理操作与四个日常文本操作分离 |
| MVP-0 运行时、初始化、工程拆分和测试矩阵 | [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md) | Approved Design | C0–C2 里程碑 85 项、稳定化后 93 项；C3A 后 105 项、C3B 后 122 项、C3C 后 140 项、C3V 后 144 项；R0.1/R0.2 后 148 项；D0G 后 156 项；R0.3D 后 159 项；R0.3F 后 163 项；C4A 后 182 项；C4B 后 197 项；C4C 后 212 项；C4V 后 214 项；C5A 后 231 项；C5B 后 250 项；C5V 后 253 项；C6A 后 258 项；C6B 后 265 项；C6C 后 274 项；C7A 后 293 项；C7B 后当前 300 项通过 |
| MVP-0 编码批次、执行停点和授权边界 | [MVP-0 捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) | Approved Design | C7B 已完成本地内容、验证与独立版本化但尚未 push；下一功能门禁为需单独授权的 C7V |
| C3 后评估、建议顺序和待裁决清单 | [已归档的 C3 后综合评估与实施方案](../archive/2026-design-history/post-c3-integrated-assessment-and-implementation-plan-C3后综合评估与实施方案.md) | Historical | 阶段建议和执行事实已由当前编码方案、本文件及变更记录承接；归档文本只保留决策过程，不再参与当前排期 |
| C3 后评估的来源证据 | [历史研究输入](research/README.md) | Historical | 仅供追溯；其中的命令、旧行号、状态与结论必须重新核验，不构成授权或主题权威 |
| 三类 Processing Profile 的名称/默认路由、Source Segment/Ledger 物理契约、检索栈和候选图谱方法 | [渐进式知识提炼规范](progressive-knowledge-refinement-spec-渐进式知识提炼规范.md) | Draft，待实验 | 已确认的只是上行治理红线；本行细节在方法论实验和独立功能门禁前不授权实现 RAG、候选图谱或新的持久化 schema |
| 策展地图内部格式和覆盖审计方法 | 现有 SOP-001、`prompts/` 与 `extraction-interface.md` 中不冲突的部分 | Draft，待重构 | 只复用提取和地图格式；捕获、路径、触发和写入边界服从新规范 |
| SOP-000B：KB 激活 | 尚未定义 | Blocking Draft | 在 `provisional` KB 激活前必须完成 |
| 可信知识写入、精确批准和回滚 | 尚待重构的 SOP-002 | Blocking Draft | 旧 SOP-002 不得作为自动语义写入授权 |
| GBrain 未审核镜像最小接入 | 本文件第 8 节 + Capture Envelope 第 13 节 | Approved Design | 仅批准 POC 边界；旧 GBrain 集成方案只作远期能力研究，不是 MVP 接入指令 |
| GBrain、第二大脑、可视化、QQ 的长期路线 | [2026 设计历史归档](../archive/2026-design-history/README.md)中的 GBrain、建设规划、第二大脑愿景与 QQ 方案 | Historical | 不得阻塞 MVP，也不得绕过本文件的人工闸门；如需重启任一方向，先形成新的范围提案 |
| 现有 Lint、链接和 index 脚本 | `scripts/` | Existing Reference Implementation | 只证明旧知识库维护能力，不证明捕获、路由、审批或回滚已经实现 |

## 4. 已冻结的八项 MVP-0 最小决策

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

## 4A. 已确认的四项方向红线

以下红线于 2026-09-21 获得方向确认，可以约束后续设计，但不表示具体方法已经实证有效，也不授权实现新的持久化 schema、RAG 或候选图谱。

### D-009：不承诺语义零遗漏，承诺处理状态和证据可见

KnowledgeFlow 不把 LLM 的“提取一切”作为可证明的系统保证。系统真正承诺的是：原料不丢失、声明覆盖整个 Capture 版本时每个确定性区段都有状态；只处理子集时明确记录选择边界、理由以及未选区段的 `out-of-scope`/`deferred` 状态；知识候选有来源证据，未处理和失败不会被静默显示为已完成。

### D-010：深度处理允许分层和按需，不要求统一完整地图

内容可以根据规模、结构、风险、问题和审核预算采用高覆盖策展、分层理解或检索优先等不同策略，不得用一个固定全文阈值强制所有材料生成完整地图。Capture v1 的 `processing_mode` 仍只表达用户处理意图；三类 Profile 的名称、默认映射和路由规则属于下节 Draft 假设。

### D-011：RAG 和动态图谱属于派生候选层

检索结果、摘要、问答和图谱候选不能仅因生成或可检索就获得可信知识身份。候选应从带 Capture 版本和 Source Segment 定位的证据中生成，并经过独立的合并、冲突和批准流程。

### D-012：覆盖指标必须区分处理记账、证据绑定和语义召回

处理记账和证据绑定可以成为机械门禁；语义召回率只能通过人工 gold set 和对照实验估计。节级密度、全景概括对照和多 Pass 分歧只能作为异常信号。

## 4B. 已确认的四项通用知识工作边界

以下边界于 2026-09-23 获得需求确认。它们修正长期产品定位和后续能力方向，不改变 Capture v1、C7/C8 顺序，也不授权实现新的任务、研究、结构或可信写入 schema。

### D-013：从知识任务开始，不以前置 KB 结构开始

KnowledgeFlow 是通用、适应性、治理优先的个人知识工作与知识管理系统。用户可以从原始材料、问题、研究主题、已有 KB 或模糊意图开始；捕获、搜索、研究、问答、聚类和候选组织不得要求完整 KB Profile、Schema、受控词表、Taxonomy 或 Ontology 已经存在。

### D-014：知识结构是可选、渐进、可提案的成果

集合、标签、Wiki、受控词表、Taxonomy、Ontology、知识图谱和 RAG 是可组合的组织或访问方式，不是所有 KB 必须依次通过的统一阶梯。“不是统一阶梯”不等于没有共同流程：材料仍应经历来源级纳入、工作级可用、候选/提案、选择性可信晋升和持续治理；系统应从真实材料和使用中提出候选结构，只有需要长期稳定、跨内容复用或改变可信层时才进入版本化治理，并允许延期、替换、迁移和回滚。

### D-015：人工闸门按风险分层，不转嫁全部策展劳动

系统应承担批量阅读、研究辅助、材料解释、聚类、比对、证据绑定、候选生成、diff 准备和确定性维护。低风险机械操作可自动，可逆派生语义工作可自动生成，普通可信变更可按明确批次批准，高影响结构变化须精确批准，大范围或不可逆操作必须有检查点、事务和回滚计划。

### D-016：先纳入、先可用，再选择性晋升

Capture 只解决来源可靠保存，不代表已经完成知识管理。来源在进入可信层之前，应能在工作知识空间中获得可搜索、可浏览、有状态的来源卡片、摘要/提纲、问答、临时集合或候选关系等适合当前任务和成本的可用形态；并非每条内容都必须深度处理或晋升，但延期、失败和未处理范围必须可见。工作知识仍属 T1/T2 范围，不因立即可用而自动取得可信身份；具体物理 schema 和交互必须另经实验与门禁冻结。

## 4C. 待验证的方法与实现假设（Draft）

以下假设用于组织实验，不得作为已实现能力或自动执行授权：

1. `full-map`、`hierarchical-map`、`retrieval-first` 是三类处理策略的当前工作名称；它们的默认适用范围和切换规则仍待真实材料验证。
2. Source Segment 和 Source Ledger 可用于机械表达处理边界；具体分段稳定性、事件格式、投影布局和迁移规则尚未冻结。
3. Source Ledger 的确定性清单和状态投影可以重建；人工审核、批准、拒绝和延期必须另有不可变审计事件或等价规范记录，不能只保存在可覆盖状态中。
4. 本地全文/BM25/向量/层次索引、Evidence Bundle、候选图谱、自动路由阈值和质量门槛均须经过实验与各自功能门禁。

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
| Source Segment | Capture 版本经确定性切分得到的可追踪源文单元 |
| Source Ledger | 由 Capture/Segment 事实、处理事件和人工决策记录计算出的台账投影；物理格式仍为 Draft，人工决定本身不能仅存在可覆盖投影中 |
| Processing Profile | 对内容选择高覆盖策展、分层理解或检索优先等派生策略的 Draft 工作概念，不是 Capture v1 输入值 |
| Evidence Bundle | 一次查询、审核或提案所使用并绑定来源版本/区段的证据集合 |
| Knowledge Candidate | 尚未获准进入可信知识层的实体、关系、主张或摘要候选 |
| Knowledge Task | 用户当前要完成的保存、研究、理解、组织、学习或维护工作；只是概念职责，正式身份与持久化契约尚未定义 |
| KB Profile | 某个长期知识空间的目的、范围、证据偏好和已批准结构等版本化上下文的工作名称；允许部分未知，物理格式尚未定义 |
| 捕获热路径 | 从接收输入到返回本地耐久成功之间的同步操作集合 |

## 6. 已冻结的最小捕获链路与长期知识任务入口

```text
任何提交原始材料的入口
  -> 本地 Capture Transaction
  -> Capture Store 中形成不可变 Version + Envelope
  -> 返回 saved: true
  -> 根据当前状态显示在 Global Intake 或已授权的 KB Inbox

保存成功之后，彼此独立地执行：
  -> GBrain 未审核镜像（可选、异步、可重建）
  -> Git 批量备份（异步）
  -> 人工路由或路由提案
  -> raw 归档
  -> 确定性分段、Source Ledger 和派生检索底座（C8 后经独立门禁）
  -> 按获批处理策略生成概要、局部/完整策展提案或 Evidence Bundle（当前 Profile 细节为 Draft）
  -> 候选图谱/Promotion Proposal（仍在未审核层）
  -> 人工批准精确变更
  -> SOP-000B / SOP-002 写入可信知识
```

Capture Store 是物理原件层；Global Intake 和 KB Inbox 首先是状态/队列视图。实现可以为检索效率建立索引或引用，但不得悄悄产生两个相互竞争的规范原件。

长期产品还允许从问题、研究主题、已有 KB 或模糊意图开始 Knowledge Task。其任务身份、研究工作空间和外部来源落地契约尚未定义；未来设计必须使重要来源与结论可追溯，但不得为了复用上述捕获链而假装这些契约已经实现，也不得要求先存在完整 KB Profile、Schema、Taxonomy 或 Ontology。

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
| C-017 | C2 初始化的错误码、成功回执、配置/Manifest 规范、已有 Store 判定及并发恢复边界未闭合 | 增加三项初始化专用错误码和独立 `InitStoreResult`；配置允许安全但非规范的输入并规范写出，Manifest 必须是规范字节；只有完整骨架与完整配置匹配才视为幂等；配置目标锁、并发竞争和六个初始化故障点都纳入 C2 | 2026-09-03 解决 |
| C-018 | Envelope 回执示例包含 `payload_count`，但公共操作契约与成功回执代码白名单不接受该字段 | C3 成功回执以操作契约第 4.3 节为公共权威；删除冗余 `payload_count`，补齐 `ok`、`commit_state` 和 `trust_status` | 2026-09-09 解决 |
| C-019 | “同一幂等键返回同一回执”没有区分不可变身份/哈希与当前投影警告 | 同一请求必须返回相同 Item/Version/Event 与核心哈希；`warnings` 按命中时投影事实生成，C3 不在幂等命中路径静默重建投影 | 2026-09-09 解决 |
| C-020 | 捕获与路由规范保留了另一套旧 `capture.yaml` 伪格式，可能与 `knowledgeflow.capture-state` v1 混淆 | 删除第二套机器格式，只保留路由/信任概念片段；精确 schema 唯一引用 Envelope 第 9 节与 C3-0 | 2026-09-09 解决 |
| C-021 | 操作契约的完整性错误示例写 `stored payload...`，代码与测试固定为 `stored data...` | 公共固定消息统一为 `stored data failed integrity verification`，同时覆盖 Payload 与 Envelope 完整性失败 | 2026-09-09 解决 |
| C-022 | Envelope/C3-0 把调用方 `user_intent` 定义为可选，操作请求表却写成必填 | `capture_text` 可省略 `user_intent`；省略与三个字段显式为 `null` 机械归一化为同一请求指纹，Envelope 仍写完整对象与 evidence | 2026-09-09 解决 |
| C-023 | 捕获与路由步骤一度把 Payload staging 写在“持久化原始载荷”步骤之前 | 路由规范只在 C1 校验重试上下文；staging、指纹、锁内查询和未命中后分配 ID 统一引用 Envelope 第 10 节事务顺序 | 2026-09-09 解决 |
| C-024 | 新分配 ID 的最终目录已存在时只写“身份冲突”，但没有公共错误码和提交状态 | 不覆盖、不冒认；固定返回可重试 `atomic_commit_failed + commit_state: not-committed`，与 rename 结果未知严格区分 | 2026-09-09 解决 |
| C-025（R-001） | 初始化事务清理可能先删除所有权 marker，随后内容清理失败会留下无法证明归属、无法自动恢复的残片 | 先删除并核对自有内容文件/目录，只有事务根仅剩同一身份 marker 时才删除 marker，最后删除空根；中途失败保留 marker 并 fail-closed | 2026-09-11 以 `92a37b3` 解决；INIT-17/FI-07 验证 |
| C-026（R-002） | 配置临时文件只以事务 UUID 区分，内容相同但目标配置路径不同的并发初始化可能相互误删在途文件 | 临时文件名绑定完整 `request_sha256 + transaction_id`；只清理请求身份匹配、普通非 reparse 且规范字节完全匹配的候选，旧式或不可证明候选保留 | 2026-09-11 以 `79515ed` 解决；INIT-18/INIT-19 验证 |
| C-027 | C5 追加时“版本目录已落盘”和 `capture.version-appended` Event 尚非一个已冻结的逻辑提交单位；C4 若仅取最高完整目录，可能暴露未完成追加 | 可读版本固定为由唯一版本建立 Event 证明的连续 `1..N` 前缀；N>1 先提交版本目录、后无覆盖提交绑定前后 Envelope 哈希的追加 Event，Event 是逻辑提交点。唯一无 Event 的 N+1 尾部目录不可见并警告，其他矛盾 fail-closed，恢复/隔离留给 C6 | C4A–C4C 已落实读取可见性；C5B/C5V 已落实追加提交点；C6A/C6B 保持尾部逻辑隔离且不借恢复扩大可见链 |
| C-028 | `get_capture` 若把正文嵌入结果或验证时整体读入内存，会让 64 MiB 上限与“错误前零输出”无法同时成立 | 结果只含元数据和 `body_length_bytes`；正文经调用方二进制 sink 输出。先用 Store 外、块不超过 1 MiB 的磁盘 spool 完整验证，再公开；sink 失败独立为 `output_write_failed` | C4A 已实现请求/结果与错误形状；C4B 已实现有界 spool、全部目标 Payload attestation 与实际 sink 交付并独立版本化 |
| C-029 | `list_captures` 若全量哈希所有 Payload 会使捕获箱 I/O 随总正文体积增长；若完全信任投影又会错误筛选或漏项 | 列表验证版本/Event/Envelope/结构、交叉引用和实际文件大小，只读有界预览前缀；不声明完整 Payload attestation。投影异常时从不可变 Event 内存重建后筛选，任何不可变矛盾使整页失败 | C4A 已实现连续链、内存状态和结果模型；C4C 已实现全 Store 结构校验、内存重建筛选和每个返回项至多 640 byte 的有界预览，并通过 LIST-14–LIST-17 |
| C-030 | 游标没有冻结编码、查询绑定、时间边界和并发快照承诺，可能跨 Store/查询误用或产生含糊分页保证 | 使用带领域前缀 checksum 的 `c1` 规范 JSON keyset 游标，绑定 Store、规范查询与末项 `(captured_at,capture_id)`；limit 可变，时间边界严格排除，无 TTL，仅对静态数据集保证无重复/遗漏 | C4A 已实现规范查询指纹、编码、校验与坏 token 拒绝；C4C 已落实实际 keyset 分页、跨 Store/查询拒绝、limit 可变和无快照语义，并通过 LIST-02–LIST-04、LIST-09–LIST-11、LIST-19 |
| C-031 | 预览换行/grapheme 及 warning 归属未定，列表可能改变展示语义或产生无法定位的修复提示 | preview 精确取前 160 Unicode code point 并保留换行，不承诺 grapheme 边界；Item warning 必带 `capture_id`，未完成版本还带 `version`，并按稳定键排序 | C4A 已实现结果/warning 形状及稳定排序；C4C 已落实 code point 预览与当页 warning 归属/排序，并通过 LIST-06、LIST-13、LIST-18 |
| C-032（R0.3-M1） | R0.3D 确认 `_lstat_if_present` 会把 `stat` 的 `OSError` 转成 `_InitFailure`；这不使 `_remove_owned_transaction` 的整个 `except OSError` 成为死代码，但此前一个尚未证明属于当前请求的未知候选若 `stat` 不可读，会阻断已有合法 Store 的纯幂等重开 | 候选尚未通过 marker/request 身份证明时，`stat`/遍历/marker 读取失败统一视为“不可证明归属”，保守跳过且不删除；一旦已证明为本请求自有树，身份复核、`unlink` 或 `rmdir` 失败仍必须 fail-closed、保留 marker 并返回稳定清理阶段。不得全局放宽共享 `_lstat_if_present` | 2026-09-13 由 R0.3D 复现并裁决；R0.3F 已按边界实现、验证并由独立本地提交闭合 |
| C-033（R0.3-M3） | R0.3D 时，原操作失败后的二次清理若又发生身份或 I/O 失败，清理异常会覆盖原始公共 `details.stage`，调用方失去首个失败阶段 | 首个原操作错误拥有 `code`、`cause_code`、`retryable` 和 `details.stage` 的公共优先级；清理错误只能作为次级诊断，以新增安全 token `details.cleanup_stage` 保留，不得暴露路径或原始 OS 文本。仅清理本身失败时，清理阶段仍作为主 `stage`；初始化结果始终不含 `saved`/`commit_state` | 2026-09-13 由 R0.3D 复现并裁决；R0.3F 已覆盖 Store/配置两条清理路径并由独立本地提交闭合 |
| C-034（R0.3-M4） | R0.3D 时 `DurabilityError` 恒定 `retryable=false`，使明确的 Windows sharing/lock violation（WinError 32/33）与初始化规范不一致；锁模块的 `errno.EACCES` 回退若直接复用又会把永久 ACL 拒绝误归类 | durability 默认 `retryable=false`；仅当直接保留的 Windows I/O 原因具有 `winerror` 32 或 33 时为 `true`。WinError 5、仅 `errno.EACCES`、无底层原因、校验失败及未知错误均保持 `false`；锁等待循环的上下文分类不外推到通用 durability | 2026-09-13 由 R0.3D 复现并裁决；R0.3F 已按窄分类实现、验证并由独立本地提交闭合 |
| C-035 | append 请求只列字段，未冻结 Python 类型、`expected_current_version` 上界、可选意图和成功回执是否复用 capture_text 类型；实现可能让 bool/999999 进入 N+1，或放宽已稳定的创建回执 | 新增关键字、frozen/slots 的 `AppendCaptureVersionRequest`；expected 只接受整数 `1..999998`，key 必填，意图省略归一化为全 `null`。新增独立精确 `AppendCaptureVersionResult`，不修改 capture_text 回执形状 | 2026-09-14 由 C5-0 解决；2026-09-16 由 C5A 实现并验证 |
| C-036 | 同 key 已提交重试与 CAS 的检查顺序未定；若先检查当前版本，原 N+1 的回执丢失后，在 Item 已推进到 N+2 时会错误返回 `version_conflict` | 锁内先验证不可变结构，再按 `scope + key_sha256` 做幂等；同身份同指纹的已提交命中优先于 CAS 并返回原稳定版本，同身份不同指纹的 `idempotency_conflict` 也优先于目标不存在和版本冲突 | 2026-09-14 由 C5-0 解决；APP-08/APP-09 验收 |
| C-037 | append 的锁范围和完整性深度不明确：全量重哈希所有历史正文代价失控，只信 Envelope/投影又可能在损坏基线上追加 | 正文锁外 staging；Store 级 Windows 锁覆盖全 Store 结构扫描、幂等、目标链、CAS、提交、最终回读和投影尝试。普通扫描验证结构/Event/Envelope/大小；对幂等命中、可采用尾部和目标当前版本完整 attestation 全部 Payload，不顺带重哈希更早历史正文 | 2026-09-14 由 C5-0 解决；APP-13/APP-14 验收 |
| C-038 | C4 允许唯一无 Event 的 N+1 尾部，但 C5 未规定同 key 重试是续封、生成 N+2、覆盖还是等待 C6，也未区分“已知部分尾部”和“I/O 无法判断尾部身份” | 仅规范、可读、自哈希有效且绑定 Item/版本的尾部 Envelope 可参与未提交身份判定；已知缺失/部分/非规范尾部不保留全 Store key，I/O 无法判断则写前 `capture_store_unavailable + not-committed`。只有全部 Payload/前一版本/身份/指纹也完全匹配时才采用既有 N+1/Event ID/Envelope 续封；其他目标尾部不采用、不覆盖、不删除并返回 atomic not-committed，通用恢复仍属 C6 | 2026-09-14 由 C5-0 解决；APP-14–APP-17 验收 |
| C-039 | “Event 是逻辑提交点”尚不足以判定 rename 抛错后的公共三态；版本 rename 不明可能被误报 unknown，Event 已落盘也可能被后续异常倒置 | Event 未尝试且目标确定不存在时始终 `not-committed`，即使可能留下不可见版本尾部；Event rename 后用 source/target 与最终 Event/前后版本/Payload 证据判定：明确未落为 not-committed，精确匹配继续 committed，事实不可证明为 atomic unknown，确定损坏为 integrity unknown | 2026-09-14 由 C5-0 解决；APP-18–APP-21 验收 |
| C-040 | append 的公共错误优先级、Event writer 复用和动态 warning 未冻结，且 warning 表只把未完成尾部列为读取语义 | 固定机械请求/正文 staging 在锁前，锁内按“结构/版本支持 → 幂等 → 目标 → CAS → 提交证据”判定；writer 复用同一严格 Event codec。稳定回执不变，warning 从命中版本所在 Item 的当前完整链生成；已提交 append 幂等命中也可报告随后出现的唯一尾部，但不触发修复或接管不匹配尾部 | 2026-09-14 由 C5-0 解决；APP-03/APP-20–APP-23 验收 |
| C-041 | 现有 `capture-state` v1 代码只接受 `current_version: 1` 并强制 `updated_at == durability.verified_at`；C5 无法表达版本 2，若直接删除相等校验又会让任意投影时间通过 | 同一 state v1 向后兼容支持 `current_version 1..999999`：版本 1 保持旧相等规则和 golden；版本 >1 必须向 state codec 提供当前追加 Event 与前一 Envelope，复用严格引用校验，使 `updated_at == Event.occurred_at`，而 `durability.verified_at` 为最终回读后的独立时间。C4 返回时间仍从 Event 重建 | 2026-09-14 由 C5-0 解决；2026-09-16 由 C5A 实现并验证，APP-04/APP-22 已随 C5B/C5V 闭合 |
| C-042 | C3 staging marker 只接受 `capture_text` 且固定树是完整新 Item；若 C5 直接复用该类型/清理器，会把追加版本误建成 `000001` 整 Item，或在部分 rename 后错误拒绝、误删事务对象 | 追加使用独立内部 staging 类型和 `version/ + events/` 固定树；同一 capture-transaction v1 marker 仅增加 append operation，C3 规范字节不变。按 marker operation 选择互斥允许树，校验根与对象身份，容许已 rename 对象缺席，拒绝额外/替换/reparse 对象；marker 最后删除且绝不触及最终尾部 | 2026-09-14 由 C5-0 解决；2026-09-16 由 C5A 实现、负向验证并完成 C3 回归 |
| C-043 | capture/append 正文在 Store 锁外 staging；若取得 Store 锁的进程只凭目录存在和全局锁就清理 `.staging`，可能误删另一个仍在准备正文或等待锁的活跃事务 | 每个新事务根从创建起持有空 `active.lock` 的 Windows 内核字节锁直至安全清理；恢复器只处理规范直接子目录、匹配 marker、普通非 reparse 既有租约且可无等待取得租约、扫描前后身份不变、固定树完全通过的候选。不得为旧式/未知树补建租约；占用、缺失、额外对象、reparse、身份变化或 I/O 不可证明均保持原字节。内容先删，租约释放并删除后 marker 最后删除；marker v1 规范字节不变 | 2026-09-17 由 C6A 解决；活跃兄弟事务、真实崩溃、legacy/未知/reparse/身份变化均有自动化证据 |
| C-044 | “恢复或隔离未完成版本/Event”未规定 C6A 是否必须移动外来尾部；直接发明 quarantine 布局会改变磁盘 schema，而无 Event 尾部又不能误当作已提交版本 | 只有完整匹配同一幂等请求的唯一 N+1 尾部沿用 C5 规则续封既有 Event；其他或不可证明尾部不移动、不覆盖、不删除，继续由 Event 真源保持逻辑不可见并失败关闭。C6A 的“隔离”是逻辑隔离，不新增物理 quarantine schema，也不以目录时间、最高版本或租约文件作为提交事实 | 2026-09-17 由 C6A 解决；追加崩溃边界和新进程同 key 恢复验证 |
| C-045 | REC-02/REC-03 要求“重建幂等索引/outbox”，但当前 Store 只有空目录骨架，既无幂等索引文件 schema，也无 Delivery Request 或 outbox job schema；若为通过测试临时发明格式，会制造第二真源与未经批准的迁移负担 | C6B 不创建索引文件或 job。锁内扫描所有已提交 Envelope，校验每个 `scope + key_sha256` 只对应一个不可变请求记录；恢复 `indexes/idempotency/` 后仍为空，公开写入的同 key 重试继续依赖不可变 Envelope 扫描。Envelope v1 强制 `delivery_requests: []`，因此恢复 outbox 只重建四个空 bucket；未知派生条目原样保留并返回 `unsupported_store_version` | 2026-09-17 由 C6B 解决；REC-02/REC-03 与同 key 重试回归验证 |
| C-046 | 自动在读取或幂等重试中修投影会破坏既有只读/动态 warning 语义；逐项边验原件边写又可能在后续发现损坏时留下误导性的“部分成功” | 新增与四个日常文本操作分离的显式管理操作 `recovery.rebuild_capture_store_derived_state`。它先在 Store 写锁内完整验证全部 Item/Version/Event、全部已提交 Payload 哈希、幂等唯一性和派生目录格式，全部通过后才应用；每个 `capture.yaml` 以同目录临时文件耐久写入并原子替换，进程中断后再次运行只补剩余项。未知 projection schema、未知派生文件、未知 staging、未提交尾部和损坏原件均不修复、不删除；版本 1 的重建验证时间是本次证明时间，版本 >1 的 `updated_at` 仍绑定当前 Event | 2026-09-17 由 C6B 解决；REC-01、中断后新进程续建及写前失败测试验证 |
| C-047 | 跨盘 Store 迁移若依赖 rename、只比较 Manifest 或直接改配置，可能启用部分/损坏副本；简单覆盖非空目标又会破坏外来数据 | 显式管理操作 `migration.migrate_capture_store` 必须同时绑定配置、源路径、目标路径和预期 Store ID。在配置初始化锁与源/目标 Store 锁下，先完整验证源，再以不超过 1 MiB 的块复制稳定树；目标只能为空或逐文件字节数/哈希匹配的兼容子集。源 `.staging/` 内容和锁文件状态不迁移，但稳定 Item 中逻辑不可见的未提交尾部按原字节保留。目标字节快照与语义均完整通过后，才以同目录临时文件 + `os.replace` 切换配置；源永不自动删除。完整已复制的兼容部分目标可续传；损坏或单文件部分写入的目标失败关闭，不宣称自动修复 | 2026-09-18 由 C6C 解决；MIG-01–MIG-05、真实进程中断、失败回退与幂等重放验证 |
| C-048 | 写请求可能在配置切换前已读到旧根，但在迁移释放旧 Store 锁后才获锁；若不复核，会在切换后回写源并造成 A/B 分叉 | `capture_text` 与 `append_capture_version` 在获得已选 Store 锁后、执行恢复或任何最终修改前，必须重读同一配置并比对 root 与大小阈值。绑定已变更时返回 `capture_store_unavailable + not-committed`，内部阶段为 `config-binding-changed`，且只清理本请求自有 staging；读操作可以完成已开始的只读快照，不会制造分叉 | 2026-09-18 由 C6C 解决；真实等待写进程与迁移切换竞态验证 |
| C-049 | “穷举提取一切”被当作系统保证，但 LLM 语义召回不可由提示词或节级数量证明 | 不承诺语义零遗漏；将处理记账、证据绑定和语义召回分开。前两项可设机械门禁，语义召回必须由人工 gold set 和对照实验估计 | 2026-09-21：方向红线 Approved Design；具体评测方法仍为 Draft |
| C-050 | 固定完整策展地图会把长文 token 成本和人工审核成本线性转嫁给用户 | 允许高覆盖策展、分层理解和检索优先等不同策略，不强制统一完整地图；三个 Profile 名称、默认适用范围和阈值暂不冻结 | 2026-09-21：分层/按需红线 Approved Design；Profile 细节仍为 Draft |
| C-051 | 现有 `deep-curation` 容易被理解为必须生成完整地图，且路由只按字数阈值选择 Mode A/B/C | `deep-curation` 仍是用户处理意图，不等价于固定 Profile；实际策略可综合规模、结构、风险、复用价值和审核预算，字数不能单独决定 | 2026-09-21：意图边界 Approved Design；自动路由仍为 Draft |
| C-052 | RAG、摘要、问答和动态知识图谱可能被误当作可信知识或第二真源 | 所有检索和图谱结果均属可重建派生层或 Knowledge Candidate；候选必须绑定 Capture 版本和来源区段，不能从最终回答文本直接晋升 | 2026-09-21：信任边界 Approved Design；候选层物理实现仍为 Draft |
| C-053 | 用户只问过的内容形成查询偏置，未被问到的全局主题可能永远不会进入动态图谱 | 查询驱动候选必须显式披露查询偏置，不能宣称全局覆盖；是否采用全局结构索引、抽样及其周期由实验决定 | 2026-09-21：风险边界 Approved Design；缓解机制仍为 Draft |
| C-054（R1） | 产品目标、治理、主题规范、实现状态和路线分散在多份文档；若再新建一份“完整 PRD”，会产生第二个总需求真源，同时现有基线仍有 GBrain 首落、已批准 Profile、零遗漏审核和旧路线等漂移 | 保留并增强现有需求与治理基线，使其成为唯一 L0 顶层需求入口；用稳定 `FR-*`/`NFR-*` ID、版本范围、成功信号和追踪矩阵连接 L1 主题规范与 L2 实施证据。字段、schema、错误码和测试不复制进 L0；已识别漂移同步修正 | 2026-09-21：R1 内容与本地验证由提交 `fa00c7e` 闭合，后已随 `fb61358` 同步至 `origin/main`；不改变 Capture v1 或现有实现 |
| C-055（C7-0） | 旧 C7 只说“操作名 + JSON 头 + 正文”，未固定入口名、精确操作名、字段白名单、头上限和严格 JSON；不同调用方可能各自发明不兼容协议 | 入口固定为 `knowledgeflow-capture`，操作名严格复用四个 Python 名称；只接受操作后的可选绝对 `--config`。请求 schema/version、每操作及嵌套字段白名单、65,536 byte 头上限、LF/CRLF 和严格 JSON/UTF-8 规则以实现矩阵第 3.7 节为准 | 2026-09-24：C7A 私有解析/映射与 C7B 安装入口/真实四操作适配均已通过；真实边界总验收留待 C7V |
| C-056（C7-0） | 若核心操作已经提交后适配器才检查短正文、尾随 byte 或第二 JSON 行，CLI 会出现“返回帧错误但事实已保存”的危险反转 | 写操作先预检配置大小上限，再把声明正文以不超过 1 MiB 的块完整验证到 Store 外独占磁盘 spool，并确认 EOF 后才调用核心；任何帧错误均为 `invalid_input + not-committed`。核心随后重新验证配置并保持事务语义真源 | 2026-09-24：C7B 已在测试持有的临时 Store 中闭合真实核心写入/重放/CAS；真实 4/64 MiB 和跨进程零提交验收留待 C7V |
| C-057（C7-0） | `get_capture` 核心先写 sink，CLI 却必须先发结果头；退出码、部分 stdout 和 stderr 若不冻结，也可能让机器调用方误判或泄露正文/路径 | CLI 用第二个 Store 外输出 spool 接住已验证正文，核心成功后才发头和精确正文。exit 0/2/70 分别只代表完整成功帧、完整公共失败帧、无可靠完整帧；0/2 stderr 为空，70 只发固定行，所有路径禁止 traceback 和敏感值 | 2026-09-24：C7B 已覆盖真实核心 get 成功/完整性失败/sink 失败及公共错误脱敏；stdout 中途失败和真实大正文留待 C7V |
| C-058（C7-0） | 生产 CLI 必须拒绝源码/临时目录，子进程测试却只能使用临时 Store；若用公开 flag 或环境变量切换 policy，就会把测试能力变成生产绕过口 | 安装入口只从可信包/安装上下文构造生产 `PathPolicy`，不得从参数、JSON 或环境变量覆盖。测试只经不导出、不安装的私有 runner 注入 `PathPolicy.test_owned`；另用真实入口无写入 smoke test 证明没有后门 | 2026-09-24：C7B 已安装生产 entry，并以环境变量无效、无写入 smoke test 和测试专用 support 证明隔离；干净临时安装复核留待 C7V |
| C-059（R1.2） | 当前实现和文档重心集中在 Capture、路由与可信写入，容易把“当前底座”误读成“最终产品全部”，并把用户已有明确 KB 当作所有知识工作的起点 | L0 明确产品是通用、自适应、治理优先的个人知识工作系统；允许从材料、问题、研究主题、已有 KB 或模糊意图开始。Capture 仍是可靠底座，但研究、问答、学习、组织和维护属于长期一等能力 | 2026-09-23：Approved Design；相应任务/研究/交互契约与实现仍待独立门禁 |
| C-060（R1.2） | `SCHEMA-template.md`、旧提取词表和概念导读中的完整 KB Profile/Ontology 路径，可能被误读为用户开始处理前必须先建立的全局结构 | 现有 Schema 与提示词只作可选 Profile/实验资产；受控词表、Taxonomy、Ontology 和知识图谱按实际价值从材料与使用中形成候选，缺失时不阻塞捕获、搜索、研究、问答或候选组织 | 2026-09-23：Approved Design；具体结构契约与选择方法仍为 Draft/未定义 |
| C-061（R1.2） | “所有语义写入需人工批准”若不区分风险，可能退化为让用户逐条审核所有候选，反而重建策展悖论 | 人工控制按风险与影响分层：机械操作自动、可逆派生自动生成、普通可信变更按清晰批次批准、高影响结构变化精确批准、大范围操作要求检查点和回滚；不得借降负担扩大可信写权限 | 2026-09-23：Approved Design；风险分类、阈值与审核交互待实验和 L1 冻结 |
| C-062（R1.2） | “可选组织方式不是统一阶梯”可能被误读为没有共同入库流程，或认为 Capture 保存后长期停在无组织文件层即可 | 统一生命周期为来源级纳入 → 工作级可用 → 候选/提案 → 选择性可信晋升 → 持续治理；工作知识层是一等产品能力，但仍与可信知识分层，不能把可靠保存冒充知识管理，也不能把快速可用冒充可信批准 | 2026-09-23：Approved Design；任务/工作知识物理契约、最小成果和交互仍待实验与 L1/L2 冻结 |

面向非实现者的 M1/M3/M4 档案室类比、错误优先级示例和 Windows 重试判断，统一收录在[MVP-0 捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md)的“R0.3D → 面向非实现者的通俗解释”小节；本登记保留规范性裁决，避免在多个权威入口复制并逐渐漂移。

## 10. 功能门禁

| 要实现的能力 | 必须先完成 |
|---|---|
| 本地文本捕获 | 本文件、Capture Envelope、捕获与路由规范及已批准的 MVP-0 操作契约 |
| 本地文本读取与列表 | C4A 内部契约能力、C4B `get_capture` 与 C4C `list_captures` 已独立版本化；C4V 重跑完整矩阵并新增 2 项公共 API 组合验收，当时 214 项全量通过且提交 `1e38f2f` 已 push |
| 本地文本追加版本 | C5A 已实现类型、codec/writer、投影、staging 与证据原语；C5B 已公开完整 append 事务，C5V 已以 APP-01–APP-24、真实双进程和真实 4/64 MiB 读回完成追加阶段验收 |
| 业务事务崩溃恢复 | C6A 已用每事务 Windows 内核租约、保守直接子项扫描和 9 个 capture + 7 个 append 真实 `os._exit()` 边界完成；未知、旧式、活跃、reparse 与身份变化对象均不自动清理 |
| 派生状态重建 | C6B 已实现显式管理操作：完整验证不可变事实后原子重建 `capture.yaml`，恢复空索引/outbox 骨架并证明可重复、可中断；不发明持久索引/job schema，也不借机修复 staging、尾部或损坏原件 |
| Store 迁移 | C6C 已实现显式管理操作：先验源、有界复制、完整验目标、同目录原子切换配置并保留源；兼容部分目标可续传，外来或损坏目标保留并失败关闭 |
| 受限 CLI | C7A/C7B 协议层、真实四操作分派与安装入口已完成本地验证和独立版本化；仍须完成单独授权的 C7V 子进程/真实边界验收与 C8 总验收 |
| URL 捕获 | URL 原始输入、抓取快照、失败降级和哈希规则 |
| 文件/音频捕获 | 单文件大小上限、二进制保存、转写/OCR 派生和敏感数据策略 |
| GBrain 镜像 | 本地文本捕获通过；完成副作用关闭与查询隔离实证 |
| 渐进式知识处理 | C8 完成；Source Segment、Source Ledger、三类 Processing Profile、Evidence Bundle、候选知识状态和覆盖指标完成方法论实验并通过各自设计门禁 |
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

1. D-009–D-012 的治理红线已于 2026-09-21 确认；R1 同日把现有需求基线收口为唯一 L0 顶层需求入口并建立稳定需求 ID 与追踪矩阵，R1.2 又由 D-013–D-016 明确通用知识任务、结构非前置、风险分层和工作知识层。第 4C 节和渐进式规范中的方法/实现细节继续保持 Draft，不修改 Capture v1 或现有实现。
2. 已批准 [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)第 13 节的 9 项技术选择。
3. [MVP-0 捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md)已经批准；C0–C7A 已逐批完成并版本化，截至 `fb61358` 已同步到 `origin/main`，最后一轮已登记的干净 Windows CI 为运行 `35319645501` 在 `ea8f84e` 上通过。C7B 已完成本地内容、300 项验证与独立版本化但尚未 push，下一功能门禁为需单独授权的 C7V。
4. 所有开发和故障测试先使用隔离临时 Store；创建真实 `E:\KnowledgeFlowData\capture-store` 需要用户另行明确授权。
5. C7B 已独立复核并随本批提交；下一步逐批完成 C7V 和 C8。在纯本地文本链路验收前，不接 GBrain、不实现人工路由，也不启动 SOP-001/002 重构或渐进式处理实验。
