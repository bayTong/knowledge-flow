# 2026 设计历史归档

> 状态：Historical<br>
> 归档日期：2026-09-21<br>
> 作用：保存已退出当前权威/执行集的方案、愿景、审计清单与旧 SOP，便于追溯设计演变。

本目录中的文件**不是当前需求、当前路线图或实现授权**。阅读当前项目时应从 [`docs/README.md`](../../docs/README.md) 开始；判断冲突时以[设计权威与冲突登记](../../docs/design-authority-and-conflict-register-设计权威与冲突登记.md)为准。

归档保留原文件名，使历史引用和 Git 演进仍可追踪。文档正文中的时间、测试数、价格、外部产品能力和实施顺序只代表成文时点；复用任何结论前都必须重新核验。

## 归档映射

| 原路径 | 归档文件 | 归档原因 | 当前替代入口或用途 |
|---|---|---|---|
| `docs/adaptive-extraction-plan.md` | [自适应提取分层方案](adaptive-extraction-plan.md) | 记录旧 Mode A/B/C 与覆盖审计方案；阈值和写入流程不再决定当前实现 | [渐进式知识提炼规范](../../docs/progressive-knowledge-refinement-spec-渐进式知识提炼规范.md)；旧提示词实验背景 |
| `docs/build-plan.md` | [外置第二大脑建设规划](build-plan.md) | 长期候选能力与旧阶段划分不再决定当前顺序 | [需求与治理基线](../../docs/requirements-and-governance-baseline-需求与治理基线.md)和[当前编码执行方案](../../docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) |
| `docs/curation-paradox.md` | [策展悖论](curation-paradox.md) | 核心问题已被 L0 需求基线吸收 | [需求与治理基线](../../docs/requirements-and-governance-baseline-需求与治理基线.md)中的问题、信任与治理边界 |
| `docs/gbrain-integration-plan.md` | [GBrain 集成方案](gbrain-integration-plan.md) | 远期集成研究，不是 MVP-0 主线或当前接入指令 | 设计权威登记中的 GBrain POC 边界；重新提案后方可实施 |
| `docs/improvement-action-plan.md` | [评估整改清单](improvement-action-plan.md) | 旧审计任务大多已完成、延期或被新的追踪体系吸收 | 当前冲突登记、需求追踪矩阵和变更记录 |
| `docs/post-c3-integrated-assessment-and-implementation-plan-C3后综合评估与实施方案.md` | [C3 后综合评估与实施方案](post-c3-integrated-assessment-and-implementation-plan-C3后综合评估与实施方案.md) | 阶段建议和执行事实已进入当前编码计划及权威登记 | 当前编码执行方案；保留为 C3 后决策过程记录 |
| `docs/qq-qa-bot-plan.md` | [QQ 问答机器人方案](qq-qa-bot-plan.md) | 可选入口及外部依赖研究，不属于当前产品主线 | 未来渠道功能需重新核验平台能力、成本和网络条件 |
| `docs/second-brain-vision.md` | [第二大脑愿景](second-brain-vision.md) | 愿景已被 L0 产品目标和分层路线吸收 | 需求与治理基线；仅保留理念演进背景 |
| `docs/sop-v2-full.md` | [旧版完整 SOP v2.2](sop-v2-full.md) | 多个主题已被 Capture、路由、SOP-000A 和可信写入边界取代 | 旧策展地图与 SOP-003 的历史参考；旧 SOP-002 继续暂停 |

## 归档边界

- 归档不是删除：文件内容和 Git 历史继续保留。
- 归档不是批准：文档里出现的命令、阶段、工期或技术选型不能直接执行。
- 归档不是废除所有细节：仍被提示词或维护脚本引用的旧格式，应明确作为“历史参考”引用。
- 如果归档内容重新成为候选能力，应先在当前需求、权威登记和相应主题规范中形成新的、范围明确的提案，而不是直接把本目录文件移回 `docs/`。
