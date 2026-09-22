# KnowledgeFlow 文档阅读地图

> 状态：Current Documentation Index<br>
> 建立日期：2026-09-21<br>
> 作用：提供唯一的文档阅读顺序和状态导航；本页不建立新的产品需求或技术契约。

KnowledgeFlow 的文件名保持语义化且稳定，**不使用数字前缀表达优先级**。数字只表示推荐阅读顺序；如果本页与[设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md)冲突，以后者的主题级裁决为准。

## 00 — 先确认项目当前状态

先阅读仓库根目录的[中文 README](../README-zh.md)或[英文 README](../README.md)，了解当前已实现范围、下一功能门禁以及尚未创建生产 Store 等事实。

README 是状态摘要，不是完整需求或实现授权。需要判断“必须做什么”时继续阅读 01；需要判断“哪份文档优先”时继续阅读 02。

## 01 — 产品需求与治理底线

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [需求与治理基线](requirements-and-governance-baseline-需求与治理基线.md) | `Approved Design`，唯一 L0 入口 | 为谁解决什么问题、功能/非功能需求、版本范围、成功信号、信任边界和未决策项 |

任何愿景、路线图、研究输入或方法草案都不能覆盖这份 L0 基线。

## 02 — 权威关系与冲突裁决

| 文档 | 状态 | 负责回答 |
|---|---|---|
| [设计权威与冲突登记](design-authority-and-conflict-register-设计权威与冲突登记.md) | `Approved Design` | 每个主题以哪份文件为准、当前功能门禁、已冻结决策和待解决冲突 |

当两份文档说法不同、状态词不清楚或历史文档看起来更“完整”时，以该登记为入口，不按文件长度或修改时间判断权威。

## 03 — 当前 MVP-0 执行顺序

按下面顺序阅读，不要把“已批准设计”误认为“已经实现”：

1. [捕获内核编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md)：当前批次、授权停点和验收顺序。
2. [捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)：运行时选择、模块边界和测试矩阵。
3. [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md)：C3 写入阶段已冻结的细粒度行为；保留到 C8 总验收完成后再归档。

C7-0 已完成受限 CLI v1 的文档契约收口但尚未实现代码；下一功能门禁是需要单独授权的 C7A 协议能力。本页不授权 C7A、C7B、C7V、C8、生产初始化或外部接入。

## 04 — Capture 核心契约

建议按业务边界到磁盘细节的顺序阅读：

1. [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md)：捕获、Global Intake、人工路由和未审核层边界。
2. [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md)：身份、版本、哈希、事件和原子保存事务。
3. [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)：`capture_text`、`get_capture`、`list_captures`、`append_capture_version` 的公共语义。

## 05 — MVP-0 之后的已批准边界与待实验方法

| 文档 | 状态 | 当前用途 |
|---|---|---|
| [SOP-000A：临时知识库骨架初始化](sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md) | `Approved Design`，尚未实现 | 人工路由后的最小 KB 冷启动边界 |
| [渐进式知识提炼规范](progressive-knowledge-refinement-spec-渐进式知识提炼规范.md) | 治理红线已确认；具体方法仍为 `Draft` | 定义不承诺语义零遗漏、证据绑定、处理缺口可见和分层处理候选 |

`full-map`、`hierarchical-map`、`retrieval-first`、Source Ledger、RAG 和候选图谱的具体实现仍需实验和独立授权，不能仅凭方法文档开始编码。

## 06 — 维护工具、提示词和样例

- [提示词说明](../prompts/README.md)：现有 SOP-001 提示词只作为实验材料；旧 SOP-002 写入提示词暂停执行。
- [维护脚本说明](../scripts/README.md)：旧 Markdown KB 的 lint、链接和索引维护工具，以及本仓库文档护栏。
- [SCHEMA 模板](../templates/SCHEMA-template.md)：现有 Markdown KB 宪法模板。
- [`examples/`](../examples/)：历史说明性样例，原始材料未随仓库提供，不能当作可复现实证。

## 90 — 研究输入与历史归档

| 入口 | 性质 | 使用规则 |
|---|---|---|
| [研究输入索引](research/README.md) | 非权威评估快照 | 只追溯判断来源；命令式文字不构成授权，旧状态必须重新核验 |
| [2026 设计历史](../archive/2026-design-history/README.md) | 已退出当前文档集的旧方案、愿景与 SOP | 不参与当前优先级；需要复用时先形成新提案并重新裁决 |
| [v1.0 历史版本](../archive/v1.0/README.md) | 完整历史版本 | 仅用于版本演进追溯 |
| [变更记录](../CHANGELOG.md) | 历史事实日志 | 记录当时发生的变更，不替代当前状态或主题权威 |

## 文档维护规则

1. `docs/` 顶层只保留当前需求、权威登记、活动期执行计划和仍有效的主题契约。
2. 历史分析、已被吸收的愿景和退出主线的方案进入 `archive/`，不以“内容可能还有用”为由继续占据当前入口。
3. 第三方评估和阶段性复核进入 `docs/research/`，必须在研究索引登记；它们不是项目指令。
4. 文件名保持稳定；阅读顺序只在本页编号。确需改名或移动时，应同时修复引用、README 路由和确定性文档护栏。
5. C8 完成后，重新评估 C3-0、MVP-0 实现拆解和编码执行方案，将已经完成的阶段材料作为一组归档。
