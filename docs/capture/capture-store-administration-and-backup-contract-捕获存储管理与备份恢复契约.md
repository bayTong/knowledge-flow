# Capture Store 管理、备份与恢复契约

> 状态：`Implemented`（限定 P0B-min 已实现与已验收范围）<br>
> 契约提取日期：2026-10-09<br>
> 适用范围：单机、单用户、本地文件系统上的显式 Store 初始化、非修复校验、冷备份和新目标恢复<br>
> 文档职责：长期维护管理入口、Backup Bundle v1、失败关闭和数据保护声明；不维护当前项目门禁、历史执行顺序或本机实例路径

## 1. 结论与职责

Capture Store 的日常业务面仍然只有 `capture_text`、`get_capture`、`list_captures` 和 `append_capture_version` 四个操作。初始化、完整校验、备份和恢复属于独立管理面，不能伪装成第五个日常操作，也不能被界面静默触发。

本契约负责以下稳定行为：

1. 显式初始化或幂等重开一个用户选定的 Store；
2. 在 Store 写锁内进行完整、只读、非修复校验；
3. 生成可独立验证的 `knowledgeflow.capture-backup` v1 冷备份；
4. 把已验证备份恢复到一个此前不存在的新目标，且不切换活动配置；
5. 以路径无关的机器回执公开结果，以失败关闭和零覆盖保护未知数据。

本契约不定义 Capture 四操作的业务语义、派生状态重建、Store 迁移、单条删除、历史版本恢复、定时备份、保留策略或远端同步。四操作见[MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)；身份、不可变版本和事务真源见[Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md)。

## 2. 稳定管理操作

| 操作 | 输入 | 成功效果 | 不会做什么 |
|---|---|---|---|
| `init` | 明确的配置路径、Store 路径和两个正整数阈值 | 初始化新 Store，或在配置、Store 身份和阈值完全相容时幂等重开 | 不猜默认目标；不接管陌生目录；不覆盖冲突配置 |
| `verify` | 明确的配置路径 | 在写锁内校验 Store 身份、不可变事实、当前派生状态和稳定树摘要，返回计数与哈希 | 不修复、不重建、不迁移、不写入业务事实 |
| `backup` | 明确的配置路径和此前不存在的备份目标 | 在源 Store 写锁内验证、复制、回读，并以最后写入的 Manifest 封存 Bundle | 不续传失败目标；不清理残留；不覆盖任何既有目标 |
| `restore` | 明确的 Backup Bundle 和此前不存在的恢复目标 | 完整验证 Bundle 后复制到新 Store 根并回读验证 | 不覆盖目标；不写配置；不把恢复目标切换为活动 Store |

默认阈值为：

- `inline_text_threshold_bytes = 4 MiB`（4,194,304 bytes）；
- `max_text_version_bytes = 64 MiB`（67,108,864 bytes）。

只有 `init` 可以选择阈值；其余操作使用并验证 Store 或 Bundle 已记录的实际阈值。管理操作的结果不是 Capture 写入回执，不使用 `saved` 或写操作的 `commit_state` 推断管理任务状态。

## 3. 安装态管理入口

安装入口固定为 `knowledgeflow-capture-admin`，只接受以下四种形式：

```text
knowledgeflow-capture-admin init --config <absolute-local-path> --store <absolute-local-path> [--inline-threshold <positive-integer>] [--max-version <positive-integer>]
knowledgeflow-capture-admin verify --config <absolute-local-path>
knowledgeflow-capture-admin backup --config <absolute-local-path> --target <absolute-local-path>
knowledgeflow-capture-admin restore --backup <absolute-local-path> --target <absolute-local-path>
```

选项顺序可以变化，但每个选项只能出现一次；缺少必填值、重复选项、未知选项、未知操作、空值和非法正整数都属于 `invalid_input`。管理入口没有隐式默认配置路径，也不接收正文、JSON 请求体或测试策略开关。

当前交付 Profile 是 Windows-first，因此当前实现按 Windows 本地绝对路径校验。长期契约要求的是“由当前平台 Profile 验证的本地绝对路径和受信生产路径策略”，不是固定盘符、用户名或某一台机器的字面路径。未来支持其他平台时应替换平台路径与锁实现，而不是改变 Store、Bundle 或公开操作语义。

已安装入口只由受信代码构造 `PathPolicy.production`。命令行、环境变量和普通调用数据都不能打开测试目录能力；临时 Store 测试只能通过不安装、不导出的测试 runner 注入 `PathPolicy.test_owned`。

## 4. 管理响应与退出语义

公共成功或公共失败时，stdout 恰好输出一行规范 UTF-8 JSON。传输字段固定为 `schema: "knowledgeflow.capture-management-response"`、整数 `schema_version: 1` 和 `operation`；已识别调用的 `operation` 是 `init`、`verify`、`backup` 或 `restore`，连操作都无法识别的协议失败使用 `null`。

实际响应在上述传输字段之后包含对应结果的 `to_dict()` 字段：

| 操作 | 成功结果的稳定信息 |
|---|---|
| `init` | `store_id`、是否本次创建、配置已连接、实际阈值和 warning |
| `verify` | `store_id`、实际阈值、已验证 Item/Version 数、目录/文件/字节数和 `snapshot_sha256` |
| `backup` | `backup_id`、`store_id`、创建时间、实际阈值、目录/文件/字节数、快照与 Manifest 哈希、`protection_scope` |
| `restore` | `backup_id`、`store_id`、备份时间、实际阈值、已验证 Item/Version 数、目录/文件/字节数、快照与 Manifest 哈希，以及固定为 `false` 的 `config_switched` |

公共失败使用既有 `FailureResult` 的 `ok: false` 和结构化错误；管理入口不得把正文、preview、幂等键、配置字节、完整路径或临时文件名加入回执。

| 退出码 | 含义 | stdout | stderr |
|---:|---|---|---|
| `0` | 完整公共成功 JSON 已写完并 flush | 一行完整 JSON | 空 |
| `2` | 完整公共失败 JSON 已写完并 flush | 一行完整 JSON | 空 |
| `1` | 内部异常、路径泄露防护触发或输出不可靠 | 必须视为不可信 | 只允许固定行 `knowledgeflow-capture-admin: internal failure` |

调用方必须先按退出码判断 stdout 是否可信，再读取 JSON 中的结构化业务错误；不得从 exit `1` 的部分输出恢复状态。

## 5. Backup Bundle v1

成功的备份根只允许两个直接子项：

```text
<backup-root>/
├── backup.json
└── capture-store/
```

`backup.json` 是严格、规范、拒绝重复 key 的 UTF-8 JSON，固定为 `knowledgeflow.capture-backup` schema version `1`。Manifest 至少绑定：

- `backup_id`、规范 UTC 创建时间和固定的 `protection_scope`；
- 源 `store_id`、Store schema/layout version 和实际 4/64 MiB 类阈值；
- 固定的 inclusion policy；
- 已排序、唯一、POSIX 相对路径形式的目录集合；
- 每个文件的相对路径、字节数和 SHA-256；
- 总目录数、文件数、字节数及 `snapshot_sha256`。

Manifest 必须在 Store 副本完成验证后最后写入，并立即回读；缺少、非规范、被篡改或与 `capture-store/` 不一致的 Manifest 都不能构成成功备份。

### 5.1 固定纳入与排除规则

| Store 内容 | Bundle v1 规则 |
|---|---|
| 已提交 Item、Version、Envelope、Event、Payload | 纳入 |
| 当前派生状态 | 纳入；备份前必须可完整验证 |
| 唯一逻辑不可见的未提交 Item 版本尾部 | 纳入现场副本；恢复后仍按四操作规则保持不可见或处理 |
| `.staging/` 目录本身 | 保留规范空骨架 |
| `.staging/` 下的事务内容 | 排除 |
| `journal/capture-write.lock` | 排除；目标按管理流程建立自己的锁文件 |
| reparse point、未知对象类型、不支持的机器 schema 或完整性损坏 | 整体失败关闭 |

备份不能通过人工挑文件改变这些规则。Bundle 与源 Store 具有相同内容敏感等级。

## 6. 一致性、目标与失败关闭

1. `verify`、`backup` 和 `restore` 在相应 Store 写锁边界内工作；`backup` 在锁内再次确认配置与 Store 未变化。
2. `backup` 先完整验证源，再创建目标；`restore` 先完整验证 Bundle，再创建目标。
3. 文件复制采用不超过 1 MiB 的有界块；复制后重新校验目标事实、文件集合、字节与哈希。
4. 配置路径、源 Store、Bundle 和目标必须满足受信路径策略，并按操作要求相互分离，不能互为父子或同一路径。
5. 备份和恢复目标的父目录必须已存在且是普通目录；目标叶在操作开始时必须完全不存在。即使已有目标为空，也必须拒绝。
6. 目标竞争、空间不足、I/O 中断或进程失败留下的部分目标保留为失败证据；实现不得自动删除、覆盖或续传。重试必须选择新的、此前不存在的目标叶。
7. 成功恢复只产生一个非活动 Store 根。`config_switched` 固定为 `false`；切换配置必须是未来另行批准的显式操作。

这些规则优先保护源 Store 和未知目标数据。失败后不能把“已复制一部分”解释为成功，也不能以自动清理掩盖无法证明归属的对象。

## 7. 数据保护声明

Backup Bundle v1 的 `protection_scope` 固定为 `operational-copy`。它证明副本具有规范 Manifest、完整字节与可恢复性，不证明：

- 源与副本位于不同物理设备；
- 能抵御整盘损坏、设备遗失、勒索软件或账号失陷；
- 具有应用层静态加密、安全擦除或自动保留能力；
- 已达到正式私人/高敏内容环境或长期灾备的要求。

同盘副本可以降低误操作或单个目录损坏的恢复成本，但不能称为磁盘故障备份。若产品将来声明 `device-failure-protected`、支持高敏内容或进入正式分发，必须另行定义并验证独立介质、静态保护、访问控制、保留、删除和恢复演练要求；这些平台部署事实不得写进 Capture schema。

## 8. 明确不在本契约内

- 自动调度、增量或去重备份、压缩、远端上传、云同步、备份管理 UI；
- 自动保留、轮换、删除、擦除或失败目标清理；
- 覆盖式恢复、原地回滚、活动配置自动切换；
- Capture 历史版本浏览或“用旧版正文创建新版本”；
- Store 迁移或派生状态重建；
- 生产安装包、自动升级、跨平台运行支持或高敏数据保护声明。

上述能力如进入范围，必须先更新主 PRD 或对应稳定契约、明确风险和验收，再单独授权实现。

## 9. 实现与验收证据

当前实现入口位于：

- [`management.py`](../../src/knowledgeflow_capture/management.py)：四个管理操作、Backup Bundle v1 与 Manifest；
- [`management_cli.py`](../../src/knowledgeflow_capture/management_cli.py)：安装态路径安全机器入口；
- [`pyproject.toml`](../../pyproject.toml)：`knowledgeflow-capture-admin` console script。

自动化证据覆盖幂等初始化、非修复校验、完整备份/恢复循环、既有目标零覆盖、篡改拒绝、中断和空间失败残留、staging 排除、未提交尾部保留、路径脱敏回执及非 editable 安装入口。P0 的真实低敏感度 Pilot 另完成两份同盘 `operational-copy` 与一次全新目标恢复；这些是历史验收证据，不扩大本契约的数据保护声明。

动态阶段、下一门禁和精确验证基线只看[项目状态与当前门禁](../project-status-项目状态与当前门禁.md)。
