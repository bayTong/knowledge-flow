# 2026 MVP-0 实施历史归档

> 状态：Historical Implementation Record<br>
> 归档日期：2026-10-09<br>
> 归档批次：D2 文档职责与归档维护<br>
> 作用：保存 MVP-0 捕获内核已经完成的编码前决策、实现拆解、测试矩阵和分批授权记录。

本目录中的文件用于追溯“当时为何这样实现、各批次如何授权和验收”，**不再维护当前项目状态、下一门禁或新的实现授权**。当前阅读入口是 [`docs/README.md`](../../docs/README.md)；当前阶段与下一门禁只看[项目状态文档](../../docs/project-status-项目状态与当前门禁.md)，需求以[主产品需求文档](../../docs/requirements-and-governance-baseline-需求与治理基线.md)为准，主题权威与冲突裁决以[设计权威与冲突登记](../../docs/design-authority-and-conflict-register-设计权威与冲突登记.md)为准。

## 归档映射

| 原路径 | 归档文件 | 归档原因 | 当前替代入口 |
|---|---|---|---|
| `docs/c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md` | [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md) | C3A–C3V 已完成并由 C8 验收覆盖；冻结行为已进入稳定契约和实现 | [Capture Envelope v1](../../docs/capture-envelope-v1-捕获信封数据契约与原子保存事务.md)与[MVP-0 操作契约](../../docs/mvp-0-capture-operations-本地文本捕获操作契约.md) |
| `docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md` | [MVP-0 实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md) | C0–C8 的工程拆分和测试矩阵均已执行完毕；不应继续充当动态计划 | [MVP-0 操作契约](../../docs/mvp-0-capture-operations-本地文本捕获操作契约.md)、[C8 验收报告](../../docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md)及当前代码/测试 |
| `docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md` | [MVP-0 编码执行方案](mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) | C0–C8 批次、授权停点和远端门禁已经闭合 | [设计权威与冲突登记](../../docs/design-authority-and-conflict-register-设计权威与冲突登记.md)、[C8 验收报告](../../docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md)和[变更记录](../../CHANGELOG.md) |

## D2 承接说明

- 原实现矩阵第 3.7 节仍然有效的 C7 受限 CLI 线协议，已在归档前迁入[MVP-0 操作契约第 7A 节](../../docs/mvp-0-capture-operations-本地文本捕获操作契约.md#7a-c7-受限-cli-适配映射)，避免当前规范依赖历史计划。
- [C8 总验收报告](../../docs/mvp-0-capture-c8-acceptance-report-C8总验收报告.md)仍是现行验收证据入口，因此没有随实施计划一起归档。
- 三份归档正文保留成文时的批次号、提交、测试事实和解释材料；其中出现的“当前状态”“下一步”或授权措辞只代表历史时点。
- 归档不是删除，也不是撤销已经实现的契约；它只结束这些文件作为当前入口和动态状态载体的职责。
- 若未来需要改变已经实现的行为，应修改当前需求/主题契约并新增独立决策记录，不得直接把归档计划重新当作执行指令。
