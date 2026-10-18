# KnowledgeFlow 文档阅读地图

> 状态：Current Documentation Index<br>
> 建立日期：2026-09-21<br>
> 作用：提供唯一的文档阅读顺序和职责导航；本页不维护动态项目状态，也不建立新的产品需求或技术契约。

KnowledgeFlow 根级文档的文件名保持语义化且稳定，不使用数字前缀表达权威高低。单一业务流程目录可以使用 `00/10/20/30` 前缀表达该目录内的阅读和执行顺序，但编号不能覆盖主题权威，也不能掩盖可选分支。如果本页与[设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)冲突，以后者的主题级裁决为准。

## 00 — 先确认项目当前状态

先阅读[项目状态与当前门禁](project-status-项目状态与当前门禁.md)，了解当前阶段、最近完成点、下一门禁、已知问题和验证证据。

根目录双语 README 只提供稳定的项目介绍和本页入口，不复制动态检查点。需要判断“必须做什么”时继续阅读 01；需要判断“哪份文档优先”时继续阅读 02。

## 01 — 主产品需求

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [KnowledgeFlow 主产品需求文档（Master PRD）](requirements-and-governance-baseline-需求与治理基线.md) | `Approved Design`，唯一 L0 入口 | 产品背景与目标、用户与旅程、范围、功能/非功能需求、产品治理、依赖风险、验收标准和待决问题 |

任何愿景、路线图、研究输入、概念导读或方法草案都不能覆盖这份主 PRD。当前代码进度、提交和 CI 事实不在主 PRD 中维护。

## 02 — 权威关系与冲突裁决

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md) | `Approved Design` | 每个主题以哪份文件为准、功能前置条件、已冻结决策、待解决冲突和批准的阶段顺序；不维护当前下一步 |

当两份文档说法不同、状态词不清楚或历史文档看起来更“完整”时，以该登记为入口，不按文件长度或修改时间判断权威。

## 02A — 跨主题概念架构导读

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [KnowledgeFlow 概念架构导读](knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md) | `Explanatory Guide`，非规范性 | 用户可从哪些知识任务开始，工件类型与治理状态怎样分开，以及策展地图、三种 Schema、领域 Ontology、知识图谱、SOP、Karpathy LLM Wiki、RAG、GBrain 与可信 Wiki 如何组合 |

这份导读不建立第二份需求或技术契约。发生冲突时，必须修改导读以服从 01 的 L0 基线、02 的主题权威和后续各主题规范，不能反向用导读覆盖它们。

## 03 — P0/MVP-0 已完成实施与验收证据

按下面顺序追溯已经完成的实施与验收证据；这些文件不负责当前排期：

1. [C8 总验收报告](../archive/2026-implementation-history/mvp-0-capture-c8-acceptance-report-C8总验收报告.md)：已归档但仍有效的 MVP-0 本地与远端直接证据、未证明项和状态范围；不承担现行契约职责。
2. [2026 MVP-0 实施历史归档](../archive/2026-implementation-history/README.md)：C3-0 决策、实现拆解/测试矩阵和 C0–C8 编码批次的历史索引。
3. [2026 P0 低敏感度 Pilot 实施历史归档](../archive/2026-p0-low-sensitivity-pilot/README.md)：P0A/P0B/P0C/P0D/P0V 的设计、授权、真实使用与恢复验收索引。

C0–C8 与 P0D/P0V 均已完成并形成证据。MVP-0 捕获内核以及 P0B/P0C 各自已测范围为 `Implemented`；P0V 只在本机低敏感度 Pilot 的初步可用性和恢复证据范围通过，长期使用、异盘灾备和正式私人内容环境仍未验证。精确提交、CI 运行、当前下一门禁和开放问题统一由[项目状态文档](project-status-项目状态与当前门禁.md)导航。

## 04 — Capture 与本地运行稳定契约

建议按业务边界到磁盘细节的顺序阅读：

1. [捕获与路由规范](capture/capture-and-routing-spec-捕获与路由规范.md)：捕获、Global Intake、人工路由和未审核层边界。
2. [Capture Envelope v1](capture/capture-envelope-v1-捕获信封数据契约与原子保存事务.md)：身份、版本、哈希、事件和原子保存事务。
3. [MVP-0 本地文本捕获操作契约](capture/mvp-0-capture-operations-本地文本捕获操作契约.md)：四个公共操作以及 C7 机器入口的完整命令、帧和退出语义。
4. [Capture Store 管理、备份与恢复契约](capture/capture-store-administration-and-backup-contract-捕获存储管理与备份恢复契约.md)：独立 `init/verify/backup/restore` 管理面、Backup Bundle v1、零覆盖恢复和数据保护声明。
5. [最小本地收件箱产品规范](capture/local-inbox-product-spec-本地收件箱产品规范.md)：当前 Tk 收件箱的用户任务、四操作映射、进程内重试、安全提示和已知 UX 缺口。

`docs/capture/` 下这五份文件维护 Capture 与本地运行的现行稳定行为；其中“捕获与路由规范”只有 `CUR-MVP-1` 使用的目标决定、权限交接和无目标分支获准分批实施，其余路由仍不能被误读为已实现。C8 报告和两个历史归档只用于追溯实现与验收证据，不能反向覆盖稳定契约。

## 05 — 深入策展联合契约与待实验方法

| 文档 | 状态 | 当前用途 |
|---|---|---|
| [00：深入策展流程总览](curation/00-deep-curation-workflow-深入策展流程总览.md) | Mixed；`CUR-MVP-1` 子集获准实施 | 用编号和任务名展示已有库、新建库、无目标地图和无原料预建四条路径；SOP-30 仍未授权 |
| [SOP-10：新建知识库骨架](curation/10-sop-new-kb-bootstrap-新建知识库骨架.md) | `Approved Implementation Contract`（限 `CUR-MVP-1`） | 可选新库分支；日期序号、稳定身份、staging、无 remote 的 `managed-local` 检查点与恢复边界 |
| [SOP-20：材料深度理解与策展地图](curation/20-sop-deep-curation-map-材料深度理解与策展地图.md) | `Approved Implementation Contract`（限 `CUR-MVP-1`） | 精确来源、处理授权、范围/证据、地图版本及地图处结束；真实处理器仍需单独确认 |
| [SOP-30：批准后写入可信知识](curation/30-sop-trusted-write-批准后写入可信知识.md) | `Review Candidate`，尚未实现 | Prepare、批准失效、无模型 Apply、本地版本检查点、回执重建、事务恢复及内部新库首次启用门禁 |
| [CUR-MVP-1：首个可用策展地图纵向切片实施方案](curation/40-cur-mvp-1-execution-plan-首个可用策展地图纵向切片实施方案.md) | `Approved Implementation Plan`；仅 `CUR1A` 已获当前授权 | 把精确 Capture、目标确认、一个隔离新库/`raw/`、范围/证据和可修改地图拆成 `CUR1A–CUR1V`；后续批次和模型/可信写入仍分别授权 |
| [渐进式知识提炼规范](progressive-knowledge-refinement-spec-渐进式知识提炼规范.md) | 治理红线已确认；具体方法仍为 `Draft` | 定义不承诺语义零遗漏、证据绑定、处理缺口可见和分层处理候选 |
| [深入策展路径：已有 SOP 逐项审查与实施建议](deep-curation-sop-review-深入策展SOP审查与实施建议.md) | `Approved Direction / Design Rationale` | 解释为何形成 `00` 总览与 SOP-10/20/30；不再承担执行契约职责 |
| [EVIDENCE-0：Evidence-first 首轮实验协议](evidence-first-experiment-protocol-Evidence优先实验协议.md) | 已版本化的 `Proposed Experiment Protocol`，不构成实现授权 | 保存代表材料、来源身份、测量与隔离方法；活动范围以对应获批修订为准，不代替深入策展 SOP、`CUR-MVP-1` 实施授权或可信写入批准 |

`full-map`、`hierarchical-map`、`retrieval-first`、Source Ledger、RAG 和候选图谱的具体实现仍需实验和独立授权，不能仅凭方法文档开始编码。

## 06 — 维护工具、提示词和样例

- [提示词说明](../prompts/README.md)：历史 SOP-001 提示词只作为 SOP-20 候选契约下的可替换实验处理器；历史 SOP-002 写入提示词继续暂停执行。
- [维护脚本说明](../scripts/README.md)：旧 Markdown KB 的 lint、链接和索引维护工具，以及本仓库文档护栏。
- [SCHEMA 模板](../templates/SCHEMA-template.md)：现有 Markdown KB 宪法模板。
- [`examples/`](../examples/)：历史说明性样例，原始材料未随仓库提供，不能当作可复现实证。

## 90 — 研究输入与历史归档

| 入口 | 性质 | 使用规则 |
|---|---|---|
| [研究输入索引](research/README.md) | 非权威评估快照 | 只追溯判断来源；命令式文字不构成授权，旧状态必须重新核验 |
| [2026 设计历史](../archive/2026-design-history/README.md) | 已退出当前文档集的旧方案、愿景与 SOP | 不参与当前优先级；需要复用时先形成新提案并重新裁决 |
| [2026 MVP-0 实施历史](../archive/2026-implementation-history/README.md) | 已完成的 C3-0 与 C0–C8 实施记录 | 只追溯实现拆解、授权和验收形成过程；当前行为看第 04 节契约 |
| [2026 P0 低敏感度 Pilot 实施历史](../archive/2026-p0-low-sensitivity-pilot/README.md) | 已完成的 P0A–P0V 实施与人工证据 | 只追溯 Pilot、操作副本和恢复演练；当前状态只看项目状态文档 |
| [v1.0 历史版本](../archive/v1.0/README.md) | 完整历史版本 | 仅用于版本演进追溯 |
| [变更记录](../CHANGELOG.md) | 历史事实日志 | 记录当时发生的变更，不替代当前状态或主题权威 |

## 文档维护规则

1. `docs/` 顶层只保留当前需求、权威登记、活动期执行计划和仍有效的主题契约。
2. 历史分析、已被吸收的愿景和退出主线的方案进入 `archive/`，不以“内容可能还有用”为由继续占据当前入口。
3. 第三方评估和阶段性复核进入 `docs/research/`，必须在研究索引登记；它们不是项目指令。
4. 文件名保持稳定；阅读顺序只在本页编号。确需改名或移动时，应同时修复引用、README 路由和确定性文档护栏。
5. 任何阶段切换只更新项目状态文档和相应证据；本页、稳定契约与历史实施材料不得复制“当前下一门禁”。
