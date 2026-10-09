# 2026 P0 低敏感度 Pilot 实施历史归档

> 状态：Historical Implementation Record<br>
> 归档日期：2026-10-09<br>
> 归档批次：D2 文档职责与归档维护<br>
> 作用：保存 P0 生产前管理能力、最小本地收件箱、低敏感度 Pilot、操作副本和恢复演练的设计、授权与验收记录。

本目录只回答“P0 当时怎样实施、授权和验收”，**不再维护当前项目状态、下一门禁或稳定产品契约**。当前阅读入口是 [`docs/README.md`](../../docs/README.md)；当前阶段与下一门禁只看[项目状态文档](../../docs/project-status-项目状态与当前门禁.md)。

## 归档映射

| 原路径 | 归档文件 | 归档原因 | 当前替代入口 |
|---|---|---|---|
| `docs/p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md` | [P0 低敏感度 Pilot 与最小收件箱 dogfood 实施方案](p0-production-dogfood-plan-P0生产初始化与最小收件箱试用方案.md) | P0A/P0B/P0C/P0D/P0V 已完成；稳定行为已迁入长期契约，方案只剩历史实施与验收职责 | [Capture Store 管理、备份与恢复契约](../../docs/capture/capture-store-administration-and-backup-contract-捕获存储管理与备份恢复契约.md)、[最小本地收件箱产品规范](../../docs/capture/local-inbox-product-spec-本地收件箱产品规范.md)与[项目状态文档](../../docs/project-status-项目状态与当前门禁.md) |

## D2 承接说明

- 管理入口、Backup Bundle v1、零覆盖恢复和数据保护声明由[管理、备份与恢复契约](../../docs/capture/capture-store-administration-and-backup-contract-捕获存储管理与备份恢复契约.md)维护。
- 当前 Tk 收件箱的用户任务、四操作映射、重试边界和已知 UX 缺口由[最小本地收件箱产品规范](../../docs/capture/local-inbox-product-spec-本地收件箱产品规范.md)维护。
- P0V 的限定结论、精确提交、远端门禁、真实 Pilot、操作副本和恢复演练证据保留在归档正文中；其中出现的“当前状态”“下一步”只代表历史时点。
- 本归档不包含 Pilot Store、正文、备份或恢复副本，也不扩大内容敏感度、删除、加密、异盘灾备或生产就绪声明。
- [C8 总验收报告](../2026-implementation-history/mvp-0-capture-c8-acceptance-report-C8总验收报告.md)继续作为 MVP-0 的现行直接验收证据，不因 P0 方案归档而改变职责。
