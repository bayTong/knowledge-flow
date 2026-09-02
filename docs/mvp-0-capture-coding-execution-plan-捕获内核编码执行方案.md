# MVP-0 捕获内核编码执行方案

> 状态：Approved Design；C0–C1 已完成，停在 C2 授权门禁<br>
> 整理日期：2026-09-02<br>
> 确认日期：2026-09-02<br>
> 适用范围：MVP-0 本地 Capture Store 与四个文本操作的分批实现<br>
> 前置依据：[MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)<br>
> 执行进度：C0 与 C1 已于 2026-09-02 完成；当前停在 C1/C2 批次边界<br>
> 当前授权：A0、A1 与 A2（仅 C1）已通过；尚未授权 C2、真实 Capture Store、Git 操作或外部系统接入

## 0. 结论先行

编码不应一次性铺开。建议按 C0–C8 九个批次推进，每个批次都必须满足“改动范围固定、测试可独立运行、结果可审查、失败可停下”的条件。

第一步 C0 已完成：已经建立隔离 Python 包和可自动发现的测试骨架。第二步 C1 也已完成：错误模型、UUIDv7、四类哈希和受限 YAML codec 均已有实现、golden fixture 与单元测试。

C0–C1 均未实现 Capture Store 业务行为，也没有创建 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml` 或 `E:\KnowledgeFlowData\capture-store`。后续必须明确说出“继续 C2”或包含 C2 的批次范围，才可进入配置、路径、Manifest 与测试临时 Store 初始化。

## 1. 本方案解决什么问题

已批准的实现拆解文档定义了技术选择、操作完成标准和测试矩阵，但还缺少实际落地时的控制面：

- 先创建哪些文件，后创建哪些文件。
- 每一批允许实现什么、明确不实现什么。
- 每一批如何验证，何时必须停止。
- 如何避免当前脏工作树、真实数据目录和偶然全局依赖影响结果。
- 哪些动作仍需额外授权。

本文只补齐这些执行规则，不修改上游已批准的数据契约和操作语义。

## 2. 权威关系与偏差处理

实现时按以下顺序服从文档：

1. [需求与治理基线](requirements-and-governance-baseline-需求与治理基线.md)：产品目标、语义写入红线和人工批准原则。
2. [捕获与路由规范](capture-and-routing-spec-捕获与路由规范.md)：Capture、Global Intake、路由和后续处理边界。
3. [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md)：身份、版本、哈希、事件、原子事务和恢复语义。
4. [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)：四个操作的输入、输出、错误和大小边界。
5. [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)：运行时、工程结构、初始化和验收矩阵。
6. 本文：编码批次、文件范围、执行停点和报告方式。

若代码实现需要改变上游契约，不能以“实现方便”为理由直接改代码或测试。应停止当前批次，记录矛盾、影响范围和两个以上可选解法，先由用户确认文档变更。

## 3. 执行前硬边界

### 3.1 不触碰真实数据

在 C0–C8 的自动化开发和测试阶段：

- 不创建或写入 `E:\KnowledgeFlowData\capture-store`。
- 不创建或写入真实 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`。
- 不使用任何既有私人目录、KB、GBrain 目录或源码目录作为测试 Store。
- 每项文件系统测试只使用该测试创建并持有的隔离临时目录。
- 测试完成只清理自己创建且身份可验证的临时目录。

真实生产初始化属于独立门禁 P0，只有用户明确要求“初始化生产 Capture Store”后才能执行。

### 3.2 保留当前工作树

当前仓库已有用户或前序工作留下的修改、未跟踪文件和 `.eval-tmp` 删除记录。编码期间必须：

- 不运行 `git reset --hard`、`git clean` 或批量恢复命令。
- 不删除、移动或覆盖无法确认归属的文件。
- 不把 `.eval-tmp` 的当前删除状态混入本实现。
- 每批开始前检查 `git status --short`，结束后只说明本批实际改动。
- 遇到用户同时修改同一个目标文件时先停下核对，不覆盖用户版本。

### 3.3 不扩大系统范围

C0–C8 不接入：

- GBrain、LL-Wiki 或其他知识引擎。
- DeepSeek Harness、任何 LLM、API key 或账号。
- QQ、桌面 UI、HTTP 服务、守护进程或数据库。
- KB 路由、SOP-000A、SOP-001、SOP-002 或可信 wiki 写入。
- Git commit、push、分支创建或发布流程，除非用户另行明确要求。

## 4. 工程与依赖方案

### 4.1 目标结构

文件按批次逐步出现，最终结构为：

```text
knowledge-flow/
├── pyproject.toml
├── src/
│   └── knowledgeflow_capture/
│       ├── __init__.py
│       ├── errors.py
│       ├── config.py
│       ├── paths.py
│       ├── codec.py
│       ├── ids.py
│       ├── hashing.py
│       ├── locking.py
│       ├── durability.py
│       ├── manifest.py
│       ├── models.py
│       ├── store.py
│       ├── operations.py
│       └── cli.py
└── tests/
    └── capture/
        ├── unit/
        ├── integration/
        ├── fault/
        ├── migration/
        └── fixtures/
```

机器接口、包和模块使用英文，文档继续采用“英文名-中文名”。现有 `scripts/` 三个标准库工具不迁移、不重写，也不被迫依赖新包。

### 4.2 Python 环境

- 使用当前已确认的 Python 3.13 作为 MVP-0 参考运行时。
- 使用仓库内 `.venv` 隔离环境，不把依赖安装到全局 Python。
- `.venv` 不提交 Git；若 `.gitignore` 已覆盖则不重复修改。
- 测试使用标准库 `unittest`，MVP-0 不增加 `pytest`。
- 包采用 `src/` 布局，测试必须从安装后的包导入，避免误用工作目录中的同名文件。

### 4.3 YAML 依赖

默认候选为 PyYAML，但不依赖当前机器偶然可导入的全局 `yaml` 模块。C0 开始时应核验官方发行信息、Python 3.13 兼容性和已知安全状态，然后在 `pyproject.toml` 中固定精确版本。

若候选不满足要求，停止 C0 并提交依赖变更说明，不能静默更换库或退回自写通用 YAML 解析器。若安装需要联网或提升权限，按工具提示另行请求授权；不需要 GBrain 或模型账号。

运行时只允许这一项 YAML 依赖。安全解析、语法门禁、逐文件 schema 校验和确定性发射仍由本项目的受限 codec 负责，不能把库的默认行为当成契约保证；精确规则以 Capture Envelope 第 8.7 节为准。

## 5. 可测试性设计

为测试异常和并发而新增的注入点必须是内部依赖，不能成为生产 CLI 参数。至少包括：

- `Clock`：提供固定 UTC 时间。
- `RandomSource`：为 UUIDv7 测试提供固定随机位。
- `PathPolicy`：生产策略与测试临时目录策略分离。
- `DurabilityBackend`：封装 flush、replace、rename 和目录同步能力。
- `LockBackend`：封装 Windows 锁与测试替身。
- `FaultHook`：只在测试构造对象时注入故障点。

这些接口的目的不是构建通用框架，而是让哈希、ID、崩溃恢复和竞态结果可重复验证。生产入口不能从 YAML、环境变量或命令行开启测试策略和故障钩子。

## 6. 分批编码计划

### C0：工程骨架与测试发现（已完成）

目标：证明新的捕获包可以在隔离环境中安装、导入和执行测试，同时没有任何业务写入。

允许新增或修改：

- `pyproject.toml`
- `src/knowledgeflow_capture/__init__.py`
- `tests/__init__.py`
- `tests/capture/__init__.py`
- `tests/capture/unit/__init__.py`
- `tests/capture/unit/test_smoke.py`
- `.gitignore`，仅在尚未忽略 `.venv` 时补一条最小规则

执行内容：

1. 记录开始时的 Git 状态，不清理现有改动。
2. 核验并精确固定 YAML 依赖。
3. 建立 `.venv`，以 editable 方式安装当前包。
4. 添加一项只验证包身份和版本常量的真实 smoke test。
5. 运行测试发现、编译检查和补丁格式检查。

验收：

- 自动发现至少 1 项测试，且测试通过。
- 从隔离环境导入的是 `src/knowledgeflow_capture`。
- 没有新增 Capture Store、配置文件或 Capture Item。
- 没有改动 `scripts/` 的运行方式和依赖声明。

完成 C0 后先报告并停下，不自动进入 C1。

实际验收结果（2026-09-02）：

- 已建立 `pyproject.toml`、`src/knowledgeflow_capture` 和 `tests/capture/unit` 最小骨架。
- 官方核验并精确锁定 `PyYAML==6.0.3`；依赖只安装在仓库内 `.venv`。
- `unittest` 自动发现并通过 1 项 smoke test，包从 `src/knowledgeflow_capture` editable 导入。
- 编译、依赖完整性和补丁格式检查通过。
- 未创建真实用户配置、生产 Capture Store、Capture Item 或任何业务操作实现。

### C1：确定性基础原语（已完成）

目标：先完成不依赖 Store 布局的纯函数和受限序列化能力。

执行状态：错误模型、四类哈希、UUIDv7 和受限 YAML 规则已于 2026-09-02 获批、实现并通过验收。

主要文件：

- `errors.py`
- `models.py`
- `ids.py`
- `hashing.py`
- `codec.py`
- `tests/capture/unit/test_errors.py`
- `tests/capture/unit/test_ids.py`
- `tests/capture/unit/test_hashing.py`
- `tests/capture/unit/test_codec.py`
- `tests/capture/fixtures/` 下的最小 golden 文件

必须覆盖：

- 公共错误码、内部 `cause_code`、成功警告和写操作三态 `commit_state`；不得把原文或敏感值放入错误/警告。
- UUIDv7 的 48 位毫秒、version/variant 位、74 位安全随机数、固定向量、同毫秒唯一性和时钟回拨；不测试或承诺同毫秒严格单调。
- Payload、Payload Set、Request Fingerprint、Envelope 四类 SHA256 的规范输入与 golden；正文按 UTF-8 字节流计数和哈希，不先复制整份大文本。
- YAML 的语法门禁与逐文件 schema 校验分别测试；不能把“能安全解析”当成“符合文件契约”。
- YAML 确定性发射固定 UTF-8、LF、无 BOM、2 空格、block style、schema 字段顺序、双引号字符串、无空行和一个末尾换行。
- 重复键、tag、anchor、alias、merge key、多文档、float、时间对象、binary、非字符串 key、未知字段和未知 schema 版本均被对应关卡拒绝。

验收：实现拆解文档第 10.0 节全部通过；C1 只使用内存或 fixture，不接触任何真实配置和 Store。

实际验收结果（2026-09-02）：

- 已实现 `errors.py`、`models.py`、`ids.py`、`hashing.py` 和 `codec.py`。
- 已建立三份 golden fixture，并覆盖错误分层、UUIDv7 固定向量、四类哈希、语法门禁、schema 校验和确定性 YAML 发射。
- `unittest` 自动发现共通过 30 项测试，其中 29 项覆盖 C1，另 1 项为 C0 包导入 smoke test。
- 编译和依赖完整性检查通过；实现只使用内存和仓库测试 fixture。
- 未创建或访问真实配置、生产 Capture Store、Capture Item、GBrain、网络或模型服务。

C1 明确不实现 Store 初始化、路径锁、flush/rename、四个操作、State Event、幂等索引、生产配置或生产目录；这些能力继续留在 C2 及以后，并在进入对应批次前解决各自的阻塞性细节。

### C2：配置、路径、Manifest 与安全初始化

目标：能在测试拥有的临时父目录中初始化和重新打开一个合法 Store。

主要文件：

- `config.py`
- `paths.py`
- `locking.py`
- `durability.py`
- `manifest.py`
- `store.py`
- `tests/capture/unit/test_config.py`
- `tests/capture/unit/test_paths.py`
- `tests/capture/integration/test_init_store.py`

必须覆盖实现拆解文档中的 CFG-01–CFG-09 和 INIT-01–INIT-09，包括：

- 默认配置查找与显式绝对配置路径。
- root 绝对解析、禁止目录、reparse/symlink 越界和阈值关系。
- `capture-store.yaml` 身份校验与未知布局拒绝。
- 初始化临时目录、flush、回读、同盘 rename、配置原子替换。
- 初始化崩溃后的幂等续接，不生成第二个 `store_id`。
- 空目录和未知非空目录都不自动接管。

验收：所有路径写入均位于测试框架刚创建的临时根；默认用户配置位置只测试“如何解析”，不实际写入。

### C3：`capture_text`

目标：闭合第一个真正可用的本地保存事务。

主要文件：

- `operations.py`
- 必要的 `store.py`、`durability.py` 增量
- `tests/capture/integration/test_capture_text.py`

必须覆盖 CT-01–CT-13：

- 中文、英文、emoji、CRLF/LF、首尾空白和无末尾换行字节往返一致。
- 空字符串拒绝，但仅空白文本允许保存。
- `<= 4 MiB` 内联；`> 4 MiB` 到 `<= 64 MiB` 流式写入一个完整 Payload。
- `> 64 MiB` 默认拒绝且零部分成功；调高配置后可重试。
- 每次主动保存产生新 Item；同一幂等键重试返回同一回执。
- GBrain 和网络完全不存在时仍可保存。

测试分两层：日常快速测试注入更小阈值以验证分支；本批验收另跑真实 4 MiB、4 MiB + 1 byte、64 MiB 和 64 MiB + 1 byte 边界，避免只证明缩小后的替身阈值。

### C4：`get_capture` 与 `list_captures`

目标：闭合读取、完整性校验、Global Intake 列表和稳定分页。

主要文件：

- `operations.py`
- 必要的 `store.py` 增量
- `tests/capture/integration/test_get_capture.py`
- `tests/capture/integration/test_list_captures.py`

必须覆盖 GET-01–GET-07 和 LIST-01–LIST-08：

- 默认最高完整版本和精确历史版本读取。
- Payload/Envelope 被篡改时返回完整性错误，不返回 `verified=true`。
- `capture.yaml` 投影缺失时仍能从不可变记录读取，并给出警告但不偷偷修复。
- 列表按稳定键排序，游标翻页无重复无遗漏。
- Global Intake 由 `routing.status=unassigned` 投影形成。
- 预览严格取 160 Unicode code point，不调用分词、摘要或模型。
- `limit > 100` 返回 `invalid_input`，不静默钳制。

### C5：`append_capture_version` 与并发控制

目标：闭合乐观并发、追加版本和批准不继承规则。

主要文件：

- `operations.py`
- 必要的锁、事件和幂等索引增量
- `tests/capture/integration/test_append_capture_version.py`
- `tests/capture/integration/test_concurrency.py`

必须覆盖 APP-01–APP-08，并增加多进程竞态：

- `expected_version` 一致时只创建 N+1。
- stale 版本返回 `version_conflict`，不覆盖、不产生半版本。
- 两个并发追加只能一个成功，另一个得到可解释冲突。
- 成功后的幂等重试不能生成 N+2。
- 即使正文相同，用户主动追加仍形成新版本。
- 新版本不继承旧版本的批准状态。

### C6：故障注入、恢复与迁移

目标：证明文件式 Store 不依赖偶然 happy path 才成立。

主要文件：

- `tests/capture/fault/test_init_faults.py`
- `tests/capture/fault/test_capture_faults.py`
- `tests/capture/fault/test_append_faults.py`
- `tests/capture/integration/test_recovery.py`
- `tests/capture/migration/test_store_move.py`
- 为修复测试暴露问题所需的现有模块小幅增量

必须覆盖：

- 实现拆解文档第 11 节列出的全部初始化、捕获和追加故障点。
- 故障后以新进程重新打开磁盘状态，不使用原进程缓存作结论。
- REC-01–REC-03 的投影和幂等索引重建。
- MIG-01–MIG-05 的复制、校验、切换和源目录保留。
- staging 残片只能按可验证事务身份处理，未知文件不自动删除。

本批自动化只能证明进程崩溃边界。突然断电、控制器缓存和第三方软件长期占用仍保留到人工耐久验收，不能用模拟测试替代。

### C7：机器适配 CLI

目标：给未来 DeepSeek Harness 或 UI 一个受限机器接口，不让调用方直接写 Store 文件。

主要文件：

- `cli.py`
- `pyproject.toml` 的命令入口增量
- `tests/capture/integration/test_cli.py`

协议固定为：

1. 命令行只携带操作名和可选的绝对 `--config` 路径，不允许 `--text`。
2. stdin 的第一行是单行 UTF-8 JSON 元数据，其中包含 `body_length_bytes`；随后紧接精确长度的正文原始 UTF-8 字节。无正文操作的长度为 0。
3. stdout 的第一行是单行 UTF-8 JSON 结果头，其中包含响应 `body_length_bytes`；`get_capture` 正文随后以原始字节输出，其余操作长度为 0。
4. stdout 只输出协议数据；诊断写 stderr，且不得含捕获正文、正文预览、幂等键或本机敏感路径。
5. JSON 中的结构化错误码是语义真源；进程退出码只区分成功、可预期请求失败和内部失败。
6. 声明长度与实际字节数不一致、尾随额外字节、非法 UTF-8 或多余 JSON 行一律拒绝，不能猜测修复。

必须通过子进程往返、空正文错误、大正文流、错误帧、退出码和日志泄露测试。CLI 只是适配器，不能重新实现或改变四操作语义。

### C8：全量验收与文档状态

目标：判断实现是否达到 `Implemented`，而不是继续增加功能。

执行内容：

- 运行完整单元、集成、并发、故障和迁移测试。
- 运行真实 4/64 MiB 边界测试和 Windows 强制终止测试。
- 检查安装后包、命令入口、README 使用说明和错误码表一致。
- 检查仓库内没有真实 Capture 内容、机器配置、绝对生产路径产物或 `.venv` 文件。
- 生成一份验收报告，列明通过项、未证明项和已知平台限制。

只有自动化矩阵全部通过，且人工耐久测试的实际结果被记录后，相关文档才可从 `Approved Design` 升级为 `Implemented` 或 `Effective`。状态升级本身仍需用户确认，不由测试脚本自动修改。

## 7. 每批固定执行循环

每个批次都按同一顺序执行：

```text
读取本批权威条款与当前 diff
  -> 列出本批目标文件和不可触碰范围
  -> 编写最小失败测试或验收 fixture
  -> 实现刚好使本批契约成立的代码
  -> 运行本批测试
  -> 运行全量已有测试，检查回归
  -> 检查 git diff 与格式
  -> 报告结果并停在批次边界
```

默认一轮只执行一个批次。每批报告至少包含：

- 实际改动文件。
- 新增和累计测试数量、执行命令与结果。
- 尚未覆盖或无法自动证明的内容。
- 是否偏离已批准契约。
- 是否触碰任何真实路径、网络或外部系统。
- 下一批的准确范围。

## 8. 固定验证命令

建立 `.venv` 后，从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
git status --short
```

如果后续需要增加专门的长时或破坏性模拟测试，可以在 `unittest` 内按测试目录单独发现，但不能让默认命令悄悄跳过基础回归。任何为了让 CI 变绿而跳过失败测试的做法都需要记录和用户确认。

未来如为旧工具增加 `scripts/tests`，测试代码和合成夹具应同批提交；它不作为新捕获内核测试目录，也不应被新测试复用。

## 9. 停止条件

出现以下任一情况，立即停在当前批次，不通过扩大权限或修改上游设计绕过：

- 实现需要改变 Capture Envelope、四操作输入输出、哈希或版本语义。
- 目标路径已存在但不是本测试创建并验证身份的目录。
- 发现与用户同时修改同一目标文件，无法安全合并。
- 依赖不兼容、存在未解决安全问题，或安装来源无法核验。
- Windows 文件系统不能满足已承诺的某项原子性，而现有降级语义未定义。
- 测试只能通过删除未知文件、降低完整性检查或继承旧批准状态。
- 需要 GBrain、模型、账号、API key、数据库或网络运行时才能继续。
- 本批预计工作显著超过原范围，或暴露新的设计冲突。

停止报告应包含已完成部分、磁盘现状、失败证据、是否存在可恢复残片，以及需要用户决定的最小问题。

## 10. 回退与恢复原则

- 代码编辑使用小补丁，失败批次保留可见 diff，不能用破坏性 Git 命令整体回滚。
- 若必须撤销本批，只反向修改本批明确创建的文件和行；遇到重叠用户修改先停止。
- 测试目录通过临时身份文件确认归属后才能清理。
- 测试失败不自动修改真实配置、放宽路径策略或删除未知目录。
- 已提交的 Capture Version 在任何恢复流程中都不可覆盖；可重建的只有投影、索引和未提交 staging。
- 生产初始化尚未授权，因此本阶段不存在“为了测试先建真实目录再删掉”的做法。

## 11. 成本控制

总预算继续采用已批准的 **8.5–13.5 个专注工程日**，不因拆成九批而增加新的产品范围：

| 范围 | 预算 | 主要成本来源 |
|---|---:|---|
| C0–C1：骨架和基础原语 | 1.5–2.5 天 | 工程隔离、严格 YAML、UUIDv7 和流式哈希 |
| C2：安全初始化 | 1.5–2.5 天 | Windows 路径、锁、flush、rename 和幂等恢复 |
| C3–C5：四操作与并发 | 3–4.5 天 | 大文本、完整性、游标、幂等和乐观并发 |
| C6：恢复、故障和迁移 | 1.5–2.5 天 | 新进程验证、故障点和移动 Store |
| C7–C8：CLI 与验收 | 1–1.5 天 | 流协议、泄露检查、文档和人工记录 |
| **合计** | **8.5–13.5 天** | 不包含 UI、GBrain、Harness、路由和 SOP 重构 |

当前成本约束：

- 只增加一个运行时依赖，不引入数据库、服务框架或测试框架。
- 所有 MVP-0 运行和测试都不调用模型，因此模型/API 成本为 0。
- 先完成本地 API 和机器适配协议，不提前制作 UI。
- 快速边界测试日常运行，真实 64 MiB 和多进程故障套件在批次验收和发布验收运行。
- 不用减少恢复测试来压缩工期；如需缩短时间，应缩小功能范围并重新标注交付级别。

## 12. 授权门禁

| 门禁 | 需要的明确意思 | 授权后允许 | 仍然禁止 |
|---|---|---|---|
| A0 方案批准 | “同意编码方案” | 把本文升级为 Approved Design | 修改代码、建环境、装依赖 |
| A1 C0 编码 | “开始编码”或“开始 C0” | 只执行 C0；创建代码骨架、`.venv` 并运行测试 | C1 以后业务实现、真实 Store |
| A2 后续批次 | 明确“继续 C1/C2……”或一次写明批次范围 | 执行所列批次并在每批边界报告 | 未授权批次和范围扩张 |
| A3 外部下载 | 工具在安装依赖时请求的联网/权限批准 | 下载并安装已核验且精确锁定的依赖 | 其他软件或全局安装 |
| A4 生产初始化 | “初始化生产 Capture Store”并确认目标 | 创建真实配置和 `capture-root` | 接入 GBrain 或 KB |
| A5 Git 操作 | 明确要求 commit/push/建分支 | 仅执行指定 Git 操作 | 自动提交或发布 |

用户也可以一次说“同意编码方案并开始 C0”，这同时通过 A0 和 A1；没有“开始”含义时，默认只更新文档状态。

## 13. 已确认结论

批准本方案意味着确认：

1. 默认一次只推进一个编码批次，并在批次边界停下报告。
2. 第一次“开始编码”默认只执行 C0；C0 完成后，后续批次仍需逐批明确授权。
3. 使用仓库内 `.venv`、`src/` 包布局和标准库 `unittest`。
4. 默认候选 YAML 库为 PyYAML，编码时核验后精确锁定版本；不使用偶然全局依赖。
5. CLI 使用“单行 JSON 头 + 精确长度原始字节”的 stdin/stdout 帧，不传正文命令行参数。
6. 所有开发测试只写测试持有的临时目录，不创建真实用户配置或生产 Capture Store。
7. 当前 Git 脏工作树全部保留，不自动清理、提交或恢复。
8. 预算仍为 8.5–13.5 个专注工程日，MVP-0 不增加 UI、GBrain、Harness、路由或 SOP 实现。

以上 8 项已于 2026-09-02 获批。C0 与 C1 已完成并停在批次边界；C2 及以后编码仍需逐批明确授权。
