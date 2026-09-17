# MVP-0 捕获内核编码执行方案

<!-- knowledgeflow-doc-status tests=258 capture_tests=243 script_tests=15 next_gate=C6B -->

> 状态：Approved Design；C6A 业务事务崩溃恢复已完成，当前 258 项全量通过；下一功能门禁为 C6B 派生状态重建<br>
> 整理日期：2026-09-02<br>
> 确认日期：2026-09-02<br>
> 补充确认日期：2026-09-03<br>
> C2B 复核日期：2026-09-03<br>
> C2B-1 完成日期：2026-09-03<br>
> C2B-2 完成日期：2026-09-03<br>
> C2B-3 完成日期：2026-09-04<br>
> C3-0 行为确认日期：2026-09-08<br>
> C3 编码前收口日期：2026-09-09<br>
> C3 分批确认日期：2026-09-10<br>
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
> 稳定基线同步日期：2026-09-14（截至 C4V 提交 `1e38f2f` 已 push 至 `origin/main`）<br>
> C4A 完成日期：2026-09-13（独立提交 `06cff02`；已 push 至 `origin/main`）<br>
> C4B 完成与版本化收口日期：2026-09-13（独立提交 `666ba18`；已 push 至 `origin/main`）<br>
> C4C 完成与版本化收口日期：2026-09-13（独立提交 `231ad09`；现已 push 至 `origin/main`）<br>
> C4V 完成与版本化收口日期：2026-09-14（独立提交 `1e38f2f`；已 push 至 `origin/main`）<br>
> C5-0 内容与本地验证日期：2026-09-14（独立提交 `ea530ad`；2026-09-16 已 push 至 `origin/main`）<br>
> 最小 Windows CI 首次通过日期：2026-09-16（提交 `c4d2c7b`；远端运行 `35075692046`）<br>
> C5A 内容与本地验证日期：2026-09-16（独立提交 `63a3250`；未 push）<br>
> C5B 内容与本地验证日期：2026-09-17（独立提交 `ab2a613`；未 push）<br>
> C5V 阶段验收日期：2026-09-17（本独立提交；未 push）<br>
> C6A 业务事务崩溃恢复日期：2026-09-17（本独立提交；未 push）<br>
> 当前状态同步日期：2026-09-17<br>
> 适用范围：MVP-0 本地 Capture Store 与四个文本操作的分批实现<br>
> 前置依据：[MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)<br>
> 执行进度：C0–C2 已闭合；C3A 已以 `346164d` 完成并在 105 项全量测试下验收，C3B 已以 `8050d88` 完成并在 122 项全量测试下验收，C3C 在 140 项全量测试下闭合事务，C3V 在 144 项全量测试下完成阶段验收；R0.1/R0.2 分别以 `92a37b3`、`79515ed` 完成，R0 后为 148 项；D0G 后 156 项，R0.3D 后 159 项，R0.3F 后 163 项；C4A 后为 182 项并以 `06cff02` 推送；C4B 后为 197 项并以 `666ba18` 推送；C4C 后为 212 项并以 `231ad09` 推送；C4V 后为 214 项并以 `1e38f2f` 推送；C5-0 `ea530ad` 与最小 Windows CI `c4d2c7b` 也已推送，首次远端 CI 已通过；C5A 后为 231 项，C5B 后为 250 项，C5V 后为 253 项，C6A 新增 5 项捕获内核测试后当前全量为 258 项<br>
> 当前授权：用户已授权 C6；C6A 已完成，下一批为 C6B；push、真实 Capture Store 和外部系统接入均未授权

## 0. 结论先行

编码不应一次性铺开。建议按 C0–C8 九个批次推进，每个批次都必须满足“改动范围固定、测试可独立运行、结果可审查、失败可停下”的条件。

第一步 C0 已完成：已经建立隔离 Python 包和可自动发现的测试骨架。第二步 C1 也已完成：错误模型、UUIDv7、四类哈希和受限 YAML codec 均已有实现、golden fixture 与单元测试。C2A 亦已完成：本地配置、Windows 路径策略和 Store Manifest v1 已实现并通过测试。

C2B-2 已实现测试边界内的 Capture Store 安全初始化、严格重开、无覆盖配置连接、保守残片归属和正常多进程并发。C2B-3 已实现六个内部初始化故障点和跨进程崩溃恢复验证：故障钩子是纯内部能力（生产默认 no-op，公开 `init_capture_store()` 不再暴露任何依赖注入通道），崩溃用子进程 `os._exit()` 模拟，恢复全部由无故障钩子的新进程仅凭磁盘事实完成。

C3A 已实现严格 Event/Projection v1、渠道和时间校验、幂等 scope/key 摘要、精确成功回执与 golden fixture；C3B 已实现固定 Store 级 Windows 写锁、单遍有界 UTF-8 写入与磁盘复算，以及 T0 所有权标记和固定树 staging 清理。两批分别以提交 `346164d`、`8050d88` 完成。C3C 已将这些原语集成为公开 `capture_text` 的完整 T0–T9 事务，并在缩小阈值下覆盖 CT-01–CT-24 核心分支。C3V 又以运行时生成的真实 4/64 MiB 数据、锁边界进程屏障、默认 10 秒超时和加强版磁盘证据完成阶段验收，当时普通与严格 `ResourceWarning` 全量测试均为 144 项。R0.1/R0.2 随后闭合初始化清理所有权和配置临时文件请求身份，R0 后两种模式均为 148 项；D0G 后为 156 项；R0.3D 后为 159 项；R0.3F 后为 163 项；C4A 后为 182 项；C4B 后为 197 项；C4C 后为 212 项；C4V 后为 214 项；C5A 后为 231 项；C5B 后为 250 项；C5V 后为 253 项；C6A 新增 5 项测试后当前为 258 项。

公开 `capture_text` 已在测试持有的临时 Store 中通过 C3 阶段验收；C4B `get_capture` 与 C4C `list_captures` 均已独立版本化并 push。C4V 又以公开 API 闭合真实 4/64 MiB 写入—列表—读取、静态分页和页间受控新增的阶段验收，并以独立提交 `1e38f2f` push。C5B `ab2a613` 已公开完整 `append_capture_version` 并在缩小阈值、单进程和确定性故障范围闭合 APP-04–APP-23；C5V 进一步以两个真实 Windows 进程和真实 4/64 MiB append → list/get 闭合 APP-06、APP-07、APP-24 及整阶段矩阵。C6A 又以每事务租约、保守扫描和 16 个真实进程终止边界闭合业务事务恢复。没有创建 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml` 或 `E:\KnowledgeFlowData\capture-store`。

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
4. [C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md)：`capture_text` 编码前已确认的输入、原子提交、投影、写锁、幂等和 actor/时间补充边界。
5. [MVP-0 本地文本捕获操作契约](mvp-0-capture-operations-本地文本捕获操作契约.md)：四个操作的输入、输出、错误和大小边界。
6. [MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)：运行时、工程结构、初始化和验收矩阵。
7. 本文：编码批次、文件范围、执行停点和报告方式。

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

目标：闭合“从机器配置定位并识别一个合法 Store”的最小链路，并且只在测试拥有的临时父目录中证明初始化、重新打开、并发和进程崩溃恢复。C2 是一个逻辑批次，但分为 C2A、C2B 两个独立授权和验收停点，不能一次授权自动跨过中间复核。

本轮复核冻结以下行为：

- `PublicErrorCode` 正式增加 `unrecognized_existing_directory`、`unsupported_store_version` 和 `config_store_conflict`；不能把三类情况折叠成 `config_invalid`。
- 初始化成功使用独立的 `InitStoreResult`，包含 Store 初始化和配置连接事实；不复用 `CommittedWriteResult`，也不出现 `saved` 或 Capture 提交语义。
- 本地配置允许读取通过受限语法与 schema 校验但不是规范排版的 YAML；任何配置写入都必须规范发射。Manifest 由程序生成，读取时也必须是规范字节。
- 配置和 Manifest 都拒绝重复键、未知字段、错误版本和错误类型；`store_id` 必须是 `store_` 前缀的合法 UUIDv7，`created_at` 必须是 UTC `Z` 时间，Manifest 不得带主机绝对路径。
- “已有合法 Store”必须同时具备规范 Manifest、合法身份和完整的固定目录骨架；不完整 Store 返回错误，不自动修复。只有规范化后的完整配置与本次请求完全一致时才是幂等重试，root 或阈值任一不一致都返回 `config_store_conflict`，不得静默覆盖。
- 初始化锁以配置目标为竞争域，并且必须在创建 Store 之前取得。同一请求并发只能产生一个 `store_id`；不同 root 竞争同一配置时，失败方不能留下孤儿 Store。
- Windows MVP 拒绝 UNC、设备命名空间以及 reparse/symlink 越界；只承诺经过自动化验证的进程崩溃恢复，不宣称突然断电绝对安全。

#### C2A：配置、路径与 Manifest

只允许新增：

- `src/knowledgeflow_capture/config.py`
- `src/knowledgeflow_capture/paths.py`
- `src/knowledgeflow_capture/manifest.py`
- `tests/capture/unit/test_config.py`
- `tests/capture/unit/test_paths.py`
- `tests/capture/unit/test_manifest.py`
- `tests/capture/fixtures/local-config-v1.yaml`
- `tests/capture/fixtures/capture-store-v1.yaml`

只允许修改：

- `src/knowledgeflow_capture/errors.py`
- `tests/capture/unit/test_errors.py`

必须覆盖实现拆解文档的 CFG-01–CFG-09 和 MAN-01–MAN-06：默认配置查找、显式绝对配置路径、阈值关系、生产/测试路径策略、Windows 特殊路径、受限配置读取、规范写出、Manifest golden 字节、身份字段和未知版本拒绝。C2A 不创建 Store、不取得文件锁，也不写任何配置文件。

实际验收结果（2026-09-03）：

- 已新增 `config.py`、`paths.py`、`manifest.py`，并为三类 C2 冲突补充独立公共错误码。
- 已新增两份 golden fixture，CFG-01–CFG-09 与 MAN-01–MAN-06 均可追溯到自动化测试。
- 配置读取允许通过安全语法与 schema 校验的非规范排版，配置发射固定为规范字节；Manifest 读取和发射均要求规范字节。
- 路径策略覆盖绝对路径、生产/测试禁止目录、UNC/设备路径、`..`、reparse/symlink 越界与无法可靠检查 KB 边界时的 fail-closed 行为。
- 新增 18 项测试；连同 C0–C1，自动发现共 48 项并全部通过。`compileall`、依赖完整性和 `git diff --check` 同时通过。
- 本批未创建配置、Store、锁或 Capture，也未访问网络、GBrain、模型服务或真实 KB。

#### C2B：锁、durability、安全初始化与恢复

只允许新增：

- `src/knowledgeflow_capture/locking.py`
- `src/knowledgeflow_capture/durability.py`
- `src/knowledgeflow_capture/store.py`
- `tests/capture/_support.py`
- `tests/capture/unit/test_locking.py`
- `tests/capture/unit/test_durability.py`
- `tests/capture/integration/__init__.py`
- `tests/capture/integration/test_init_store.py`
- `tests/capture/fault/__init__.py`
- `tests/capture/fault/test_init_recovery.py`

C2B 可以按已冻结接口增量修改 C2A 文件和对应测试，但若需要改变 `codec.py`、Capture Envelope、四操作、ID/哈希或版本语义，必须停止并报告，不能自行扩张范围。`InitStoreResult` 定义在 `store.py`；配置和 Manifest 的 schema 分别留在 `config.py` 与 `manifest.py`，复用通用 codec，不修改其 Envelope registry。

编码前冻结以下实现边界：

- 锁域是解析后的 `config_path`。Windows 使用操作系统文件锁；`<config_path>.init.lock` 可以长期存在，不能用“删除看起来陈旧的锁文件”恢复。默认等待上限 10 秒，超时返回可重试的 `capture_store_unavailable`。
- `config_path` 不得位于 `capture_root` 内；Store 的直接父目录必须预先存在。配置直接父目录最多允许有限创建一层，禁止无界递归创建。测试中的配置、锁、事务目录和 Store 必须全部位于同一个测试持有根。
- 初始化事务目录位于 Store 父目录，使用 `.knowledgeflow-init-<transaction-uuid>/transaction.yaml + store/`。标记只保存 schema/version、UUIDv7 和当前初始化请求哈希，不保存绝对路径；该哈希只是内部恢复键，不改变已确认的四类 Capture 哈希。
- 每个承诺文件都必须 flush、`fsync`、关闭回读并重新校验；Store 使用同卷无覆盖目录 rename，初次配置连接也不得覆盖意外出现的目标。目录元数据 flush 只在平台明确支持时作为额外保证。
- C2B 的 I/O、权限、flush、rename 和无法安全判断磁盘事实统一使用 `capture_store_unavailable`；仅明确的临时锁/共享冲突标记 `retryable=true`。不得使用 Capture 专用的 `atomic_commit_failed`，失败结果也不得出现 `saved` 或 `commit_state`。
- 已有合法 Store 只要求固定骨架条目存在且类型安全，不要求目录为空；额外普通条目保持不动，也不能代替缺失骨架。

C2B 按三个内部停点执行，不增加新的产品阶段：

1. **C2B-1：锁与 durability 原语。** 只实现 `locking.py`、`durability.py`、测试支持和对应单元测试，覆盖 LOCK-01–04、DUR-01–04；不实现 `store.py`，不创建任何结构上可识别的 Store。
2. **C2B-2：安全初始化与并发。** 实现 `store.py` 和初始化集成测试，覆盖 INIT-01–16，包括事务残片归属；所有 Store 都位于测试持有根，不运行故障子进程。
3. **C2B-3：崩溃恢复。** 实现六个内部故障点和新进程恢复测试，覆盖 FI-01–06，再运行 C2 全量验收。

C2B-1 实际验收结果（2026-09-03）：

- 已新增 `locking.py` 和 `durability.py`，以及一个仅供测试子进程使用的支持模块和两份单元测试；没有创建 `store.py`。
- LOCK-01–04 已在真实 Windows 多进程条件下验证同配置互斥、不同配置互不阻塞、强制终止后内核锁释放，以及默认 10 秒/内部快速时钟的可重试超时语义；持久锁文件不作为持锁真相，也不会由实现删除。
- DUR-01–04 已验证独占写入、flush、文件 `fsync`、关闭后精确回读、严格 Manifest/配置校验、同卷无覆盖 rename、目标竞态的完全匹配/冲突分支，以及目录元数据 flush 的支持/明确不支持/异常三种结果。
- Windows 标准库路径当前明确报告目录元数据 flush `unsupported`，不影响进程崩溃恢复目标，但不宣称抗突然断电；意外 I/O 仍失败关闭。
- 新增 9 项测试，自动发现累计 57 项全部通过；`ResourceWarning` 严格模式、`compileall`、依赖完整性和 `git diff --check` 同时通过。全部磁盘行为只发生在测试持有的系统临时目录，没有生成结构上可识别的 Store、真实配置、Capture 或外部请求。

C2B-1 已在此停点完成。

C2B-2 实际验收结果（2026-09-03）：

- 已新增 `store.py`、初始化集成测试和正常初始化子进程入口；实现完整 Store 骨架、Manifest、无覆盖配置连接、已有目标分类、锁内重读和请求归属残片清理，没有增加故障注入点或四个捕获操作。
- INIT-01–16 均已逐项覆盖并通过。同请求并发只产生一个 Store 身份且分别返回 `created=true/false`；不同 root 竞争同一配置时只有胜者目标保留，失败方返回 `config_store_conflict` 且不留下目标或 staging。
- 并发复跑发现并修复了 Windows 真实路径解析偶发返回本地 `\\?\C:\…` 形式的竞态：只规范化操作系统可信解析结果，用户直接输入的设备路径仍被拒绝；同请求与异请求并发又分别连续通过 100 次和 50 次。
- 新增 19 项测试，自动发现累计 76 项全部通过；全量测试同时在 `ResourceWarning` 严格模式通过，`compileall`、依赖完整性和 `git diff --check` 亦通过。全部磁盘行为只发生在测试持有的系统临时目录，真实配置和生产 Store 均不存在，也没有产生 Capture、State Event、outbox job、网络请求或 GBrain 调用。

C2B-2 当时已在此停点完成；此句记录其历史授权边界。后续 C2B-3 已按独立授权完成，真实生产初始化仍属于独立门禁 P0。

C2B-3 实际验收结果（2026-09-04）：

- 已在 `store.py` 增加内部 `_InitFaultPoint` 与 `_FaultHook`，生产默认值为 no-op；故障点不可通过 YAML、环境变量、CLI 或公开参数选择。公开 `init_capture_store()` 已移除 `_dependencies` 测试入口，依赖与故障钩子注入收敛到仅测试支持代码调用的私有 `_init_capture_store_with_dependencies()`。
- `durability.py` 增加仅内部使用的“字节写完、flush 前”回调；单元测试证明该回调严格位于写入之后、flush 与 `fsync` 之前。`os._exit()` 固定退出码 70 在子进程内模拟进程崩溃，不执行任何 except/finally 清理。
- FI-01–06 每项均有独立可追溯测试：崩溃子进程到达故障点后立即退出且无任何回执；父测试确认各故障点对应的磁盘事实（最终 root 缺失、事务目录形态、Store 已提交未连接、配置临时文件、配置已提交）；随后由完全独立、无故障钩子的新进程仅凭磁盘事实重新初始化。
- 六个恢复边界全部验证：未提交 Store 不被误认为成功；已提交 Store 复用原 `store_id` 且 `created=false`；配置不被覆盖重写；只有事务标记与请求哈希共同确认归属的残片被清理；预置的未知事务目录和字节不匹配的配置临时文件逐字节不变。
- 加入 no-op 故障钩子后，同请求并发与异 root 竞争分别连续复跑 100 次和 50 次再次通过。新增 9 项测试（6 项 FI、1 项 durability 回调顺序、2 项公开接口与 no-op 边界），自动发现累计 85 项全部通过；全量测试在 `ResourceWarning` 严格模式通过，`compileall`、依赖完整性和 `git diff --check` 同时通过。
- 全部磁盘行为只发生在测试持有的系统临时目录；真实 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml` 与 `E:\KnowledgeFlowData\capture-store` 测试前后元数据快照一致（当前均不存在，测试未创建），也没有产生 Capture、State Event、outbox job、网络请求或 GBrain 调用。`os._exit()` 模拟的是应用进程崩溃，仍不承诺突然断电安全。

C2B-3 已在此停点完成，C2 全部闭合。只有用户明确说“继续 C3A”才进入 `capture_text` 的第一小批；C3B、C3C、C3V 分别保留独立停点，真实生产初始化仍属于独立门禁 P0。

必须覆盖 LOCK-01–04、DUR-01–04、INIT-01–16 和全部六个初始化故障点，包括完整骨架、已有 Store 幂等重开、配置完整匹配、初始化锁、同请求并发、不同 root 竞争、同盘 staging/rename、flush/回读、无覆盖配置连接、事务残片归属，以及每个故障点后的新进程重开。不得顺带实现 Item 扫描、投影重建、四个捕获操作、CLI、UI、Harness、GBrain 或 SOP。

共同验收：

- C2B-2 基线的 76 项测试继续通过，并且每个后续 FI 编号都能追溯到具体测试或 `subTest`；不以固定的新增测试数量代替场景覆盖。
- 所有写入都位于测试框架创建并持有的同一临时根；默认用户配置位置只验证解析，真实配置和真实 Capture Store 在测试前后快照一致。
- 故障注入后用新进程依据磁盘事实复核；同请求并发只保留一个 Store 身份，冲突请求不留下孤儿目标。
- C0–C2 测试不产生 Capture 或 State Event；从 C3 起只能在测试持有的临时 Store 中产生它们。所有批次均不得产生生产 Capture、outbox job、网络请求或 GBrain 调用。
- 全量 `unittest`、`compileall`、依赖完整性、`git diff --check` 和精确工作树清单均通过。

### C3：`capture_text`

目标：闭合第一个真正可用的本地保存事务。C3 仍是一个产品阶段，但按 C3A、C3B、C3C、C3V 四个独立授权、复核和提交停点执行；任何一批通过都不自动授权下一批。最终批使用 `C3V`，避免与 C3-0 已存在的 `C3D-01`–`C3D-06` 设计决策编号混淆。

C3 四批共同遵守以下边界：

- 每批先列出权威条款、目标文件和不可触碰范围，再编写本批失败测试；运行本批测试后必须以普通模式和 `ResourceWarning` 严格模式重跑此前全部测试，并执行 `compileall`、依赖完整性、diff 与精确工作树检查。93 项只是进入 C3 前的基线，累计数量随新测试增长，不把固定测试数量当作验收目标。
- C3A 与 C3B 不得提前暴露或声称 `capture_text` 已可用；只有 C3C 完整闭合 T0–T9 后才存在业务操作，C3V 负责最终验收而不新增产品能力。
- 所有磁盘测试只允许使用测试框架创建并持有的临时 Store；每批前后确认真实默认配置与生产 Store 未出现，不访问网络、GBrain、KB、模型、SOP 或 UI。
- C3 不引入新外部依赖、不修改 `requires-python`、Manifest schema 或已有 golden fixture 字节，不迁移测试框架，不创建数据库、幂等索引或细粒度锁，也不为代码行数重构已经稳定的 C2 初始化流程。
- `.eval-tmp/`、`tmp-eval/`、空 `assets/`、README 测试说明和全局换行策略均是独立 housekeeping，不进入任一 C3 提交。
- 如果实现要求改变 Envelope、Event/Projection 磁盘格式、公共输入输出、哈希、版本或提交状态语义，立即停止并登记真实冲突；不能在某个代码批次内顺手改写上游契约。

进入相应生产实现前，必须先用文档断言或失败测试锁定以下局部边界：

| 冻结点 | 所属批次 | 必须先明确的结果 |
|---|---|---|
| Python 调用面 | C3A | `str`/二进制 `read(size)` 联合输入、channel 与可选 intent/key 的类型、配置解析入口，以及测试依赖只能通过私有入口注入 |
| Event/回执错误层 | C3A | `capture.created` 缺失、schema 非法或交叉引用不一致的稳定公共映射与 `cause_code`；`capture_text` 成功回执的精确必填字段集合 |
| 投影时间 | C3A | `durability.verified_at` 与 `updated_at` 的采样时点、是否共用一次注入时钟值，以及规范 UTC 毫秒字节 |
| staging 归属与清理 | C3B | T0 即可建立的 capture 专用所有权标记、允许树形和验证方式；Request Fingerprint 在 T2 前尚不存在，不能把它当作唯一 T0 归属证据；提交后或幂等命中后的清理失败不得倒置已证明的提交事实 |
| 扫描与 rename 核验 | C3C | 扫描到不可读/损坏的已识别不可变记录时失败关闭；rename 异常后按源、目标和候选内容的磁盘事实区分 committed/not-committed/unknown |

#### C3A：契约能力

只允许增量修改：

- `src/knowledgeflow_capture/models.py`
- `src/knowledgeflow_capture/codec.py`
- `src/knowledgeflow_capture/errors.py`
- `src/knowledgeflow_capture/hashing.py`
- 对应的 `tests/capture/unit/` 测试，以及 `tests/capture/fixtures/` 下新增的小型 Event/Projection golden

本批完成：

- 实现严格 `knowledgeflow.capture-event` v1 与 `knowledgeflow.capture-state` v1 schema、规范加载/发射、字段顺序、Event/Envelope 交叉引用和初始固定状态。
- 把 channel token、2048-byte external ref、规范来源 UTC、512-byte 幂等键、固定 `user/local-user` actor 和调用方不可覆盖字段落实为单一验证边界。
- 实现规范 scope、带域前缀的 key 摘要，以及省略可选 channel 字段/`user_intent` 与显式 `null` 生成同一 Request Fingerprint 的归一化。
- 为 `capture_text` 定义精确成功回执必填字段；通用字段白名单不能继续允许空回执或任意合法子集冒充本操作成功。
- 冻结上表中的 Event 完整性原因与投影时间语义。固定错误消息用精确字典断言；golden 只用于稳定的 Event/Projection 规范字节，除非以后另行冻结公共回执线协议。

C3A 必须覆盖 CT-16 及支撑 CT-11、CT-20–CT-22 的纯契约边界，并重跑进入本批前的全部测试。本批不得创建 `operations.py`、获取 Capture 写锁、创建 staging 或提交任何 Item。

完成记录（2026-09-10）：C3A 经逐批指令实施并以 `346164d` 单独提交；新增 Event/Projection golden 与契约测试后，普通和严格 `ResourceWarning` 全量测试均为 105 项，`compileall`、依赖完整性和 diff 检查通过。未创建 staging、正式 Item、公开 `capture_text` 或生产 Store。

#### C3B：写入基础

只允许增量修改：

- `src/knowledgeflow_capture/locking.py`
- `src/knowledgeflow_capture/durability.py`
- 为 capture staging 所需的最小 `src/knowledgeflow_capture/store.py` 内部增量
- 对应的锁、durability、staging 单元/子进程测试与测试支持代码

本批完成：

- 从现有实现中复用已经验证的 Windows 字节锁与等待机制，保留 `acquire_initialization_lock()` 行为不变，新增固定指向 `<capture-root>/journal/capture-write.lock` 的内部 Capture 写锁入口；不另造 PID、时间戳或删除“陈旧锁文件”的协议。
- 新增真正有界的 UTF-8 流式写入原语：所有入口读取均显式传入上限内的 `size`，严格增量校验 UTF-8/BOM，边写边计数和哈希，flush/`fsync`/关闭后再从磁盘分块回读复算；不得把完整 64 MiB 输入或回读副本重新聚合进内存。
- 建立 capture 专用 staging 所有权与固定允许树；失败时只清理当前调用创建、身份和结构均可验证且尚未提交的对象，不枚举删除其他事务或 C2 初始化残片。
- 对提交后、幂等命中后及清理自身 staging 失败的行为先按冻结点形成精确测试；任何结果都不能把已证明提交的不可变 Item 改报为未提交。

C3B 必须在原语层覆盖 CT-03–CT-09、CT-14–CT-15、CT-18、CT-24 所需能力，包括工具化的非 seekable 流对最大请求块和读取次数的断言；真实 4/64 MiB 端到端验收仍留到 C3V。本批不得新增公开 `capture_text`、扫描正式 Item 或写 `capture.yaml`。

完成记录（2026-09-10）：C3B 经下一独立停点指令实施并以 `8050d88` 单独提交；普通和严格 `ResourceWarning` 全量测试均为 122 项，`compileall`、依赖完整性和 diff 检查通过。默认配置与生产 Store 仍不存在，也未新增 `operations.py`、扫描正式 Item 或写 `capture.yaml`。

#### C3C：完整事务

主要文件：

- 新增 `src/knowledgeflow_capture/operations.py`
- 必要的 `src/knowledgeflow_capture/__init__.py`、`store.py` 与 C3A/C3B 文件小幅集成增量
- `tests/capture/integration/test_capture_text.py`
- 必要的 capture 并发、提交边界、故障和子进程测试支持文件

本批按 Capture Envelope v1 的 T0–T9 完整实现：机械校验与 staging、单遍 Payload 写入、Payload Set/Request Fingerprint、Store 写锁、幂等扫描、ID 分配、Envelope/Event 封存、完整 Item 无覆盖 rename、最终路径回读、投影尝试和结构化回执。不得发布只写 Payload、只写版本目录或提交后再补创建 Event 的半事务。

幂等扫描必须失败关闭：无法安全读取、规范解析或验证的已识别不可变 Envelope/Event 不能被当作“key 不存在”而继续新建。命中同请求后验证最终 Envelope、Payload 与创建 Event，只读检查投影并返回原稳定身份/哈希和当前警告；不在命中路径修复投影。

rename 异常后的最小证据矩阵固定为：

| 可证明的磁盘事实 | 结果 |
|---|---|
| staging 源仍在且最终目标不存在 | `atomic_commit_failed + not-committed` |
| staging 源仍在且目标被证明为预先存在的冲突对象 | 不覆盖、不冒认，`atomic_commit_failed + not-committed` |
| staging 源消失且目标完整验证为本次候选 Item | `committed`，继续最终回读与投影 |
| 源/目标无法安全探测、事实矛盾或无法证明上述任一分支 | `atomic_commit_failed + unknown` |
| 源已消失、目标可读但本次候选的 schema、哈希或交叉引用验证失败 | `integrity_check_failed + unknown`；不得返回成功或把目标冒认为既有冲突 |

C3C 使用缩小阈值完成端到端 CT-01–CT-24 功能分支，尤其必须在本批已有同 key 双进程、目标冲突、Event 提交前失败、投影提交后失败和 rename unknown 的核心测试；C3V 再以真实大小、加强竞态和固定验收命令复核。本批不实现 C4 读取 API、C5 追加、C6 自动恢复/重建或生产初始化。

完成记录（2026-09-11）：C3C 经独立停点指令实施，在测试持有的临时 Store 中公开 `capture_text` 并闭合 T0–T9；缩小阈值端到端场景覆盖 CT-01–CT-24 的全部功能分支，包括同 key 双进程、目标冲突、Event 提交前失败、投影提交后失败、rename 的 committed/not-committed/unknown 证据矩阵、幂等扫描失败关闭和安全 staging 清理。普通与严格 `ResourceWarning` 全量测试均为 140 项，`compileall`、依赖完整性、`operations.py` 静态检查和 diff 检查通过。真实 4/64 MiB 和加强版验收仍留在 C3V，默认配置与生产 Store 未创建。

#### C3V：验收

C3V 默认只增加或强化测试、测试支持和批次验收记录；若验收暴露缺陷，可以做与既有 C3 契约一致的最小修复，但若需要改变公共或磁盘契约必须停止，不能借“验收”引入新能力。

必须完成：

- CT-01–CT-24 每个编号对应明确测试方法或 `subTest`，不以新增测试数量代替场景追溯。
- 运行时生成真实 4 MiB、4 MiB + 1 byte、64 MiB、64 MiB + 1 byte 数据，不提交巨大 fixture；64 MiB 使用可观测的非 seekable 生成流，证明没有无界 `read()` 或入口二次读取。
- 用进程同步屏障制造两个进程同 key 的真实竞争，并验证最多一个 Item、两份结果具有相同稳定身份/版本/哈希。
- 注入新 ID 目标冲突、创建 Event 提交前失败、投影提交后失败、rename 结果未知和自有/未知 staging 并存，逐项核对提交状态、不可变磁盘事实与清理边界。
- 运行普通全量测试、`ResourceWarning` 严格全量测试、`compileall`、依赖完整性、`git diff --check`、精确工作树清单和变更文档链接检查；验收前后确认真实配置、生产 Store、网络与 GBrain 均未被触碰。

C3V 的 CT-01–CT-24 追溯如下；同一测试方法覆盖多个编号时，方法名或 `case_id` 明确保留对应编号：

| ID | 明确测试方法或 `subTest` |
|---|---|
| CT-01 | `CaptureTextIntegrationTest.test_ct_01_02_04_13_20_preserves_text_and_commits_complete_items` / `case_id=CT-01` |
| CT-02 | 同上 / `case_id=CT-02-mixed-lines`、`case_id=CT-02-no-final-newline` |
| CT-03 | `CaptureTextIntegrationTest.test_ct_03_08_15_rejects_empty_oversize_bom_and_invalid_utf8` / `case_id=CT-03` |
| CT-04 | `CaptureTextIntegrationTest.test_ct_01_02_04_13_20_preserves_text_and_commits_complete_items` / `case_id=CT-04` |
| CT-05 | `CaptureTextAcceptanceTest.test_ct_05_06_real_4_mib_boundary_uses_one_bounded_input_pass` / `case_id=CT-05` |
| CT-06 | 同上 / `case_id=CT-06` |
| CT-07 | `CaptureTextAcceptanceTest.test_ct_07_08_09_real_64_mib_limit_and_raised_retry` 的 64 MiB 成功段 |
| CT-08 | 同上 / 64 MiB + 1 byte 拒绝段；缩小阈值回归另见 `case_id=CT-08-scaled` |
| CT-09 | 同上 / 调高本地上限后的同 key 重试段 |
| CT-10 | `CaptureTextIntegrationTest.test_ct_10_without_key_same_content_creates_distinct_items` |
| CT-11 | `CaptureTextIntegrationTest.test_ct_11_12_14_idempotent_retry_unifies_string_and_stream` 的同请求重试段 |
| CT-12 | 同上 / 不同请求冲突段 |
| CT-13 | `CaptureTextIntegrationTest.test_ct_01_02_04_13_20_preserves_text_and_commits_complete_items` 的纯本地提交及空 outbox 断言 |
| CT-14 | `CaptureTextIntegrationTest.test_ct_11_12_14_idempotent_retry_unifies_string_and_stream` 的 `str`/非 seekable 流重试段 |
| CT-15 | `CaptureTextIntegrationTest.test_ct_03_08_15_rejects_empty_oversize_bom_and_invalid_utf8` / `case_id=CT-15-bom`、`case_id=CT-15-invalid-utf8` |
| CT-16 | `CaptureContractTest.test_ct_16_channel_token_reference_and_time_boundaries`、`test_ct_16_envelope_channel_actor_and_times_are_validated` 及 `CaptureTextIntegrationTest.test_ct_16_core_owns_actor_and_canonical_times` |
| CT-17 | `CaptureTextAcceptanceTest.test_ct_17_processes_race_from_the_lock_boundary` |
| CT-18 | `CaptureTextAcceptanceTest.test_ct_18_default_lock_wait_expires_after_ten_seconds` |
| CT-19 | `CaptureTextIntegrationTest.test_ct_19_new_id_target_conflict_is_not_adopted_or_overwritten` |
| CT-20 | `CaptureTextIntegrationTest.test_ct_01_02_04_13_20_preserves_text_and_commits_complete_items` 与 `CaptureContractTest.test_ct_20_contract_event_and_projection_match_golden_bytes` |
| CT-21 | `CaptureTextIntegrationTest.test_ct_21_event_failure_does_not_commit_an_item` 与 `CaptureContractTest.test_ct_20_21_contract_event_schema_and_references_are_strict` |
| CT-22 | `CaptureTextIntegrationTest.test_ct_22_projection_failure_is_committed_and_retry_does_not_rebuild` |
| CT-23 | `CaptureTextIntegrationTest.test_ct_23_unprovable_rename_result_returns_unknown` |
| CT-24 | `CaptureTextIntegrationTest.test_ct_24_failure_cleans_only_owned_staging` 与 `CaptureStagingTest.test_ct_24_cleanup_removes_only_the_exact_owned_staging` |

C3V 通过后只能记录“C3 `capture_text` 已实现并通过本阶段验收”，不能把整个 MVP-0 或所有 Capture Envelope 能力升级为 `Effective`；C4–C8 仍按后续独立门禁推进。

完成记录（2026-09-11）：C3V 经独立停点指令实施，默认只强化测试、测试支持与验收记录，没有修改生产源代码、公共契约或磁盘契约。新增 4 项真实验收测试后，全量增至 144 项：运行时生成 4 MiB、4 MiB + 1 byte、64 MiB、64 MiB + 1 byte，不提交巨大 fixture；可观测非 seekable 生成流证明所有输入读取均有界于 1 MiB，成功入口只读至一次 EOF；两个子进程在标准 Store 锁调用的精确边界同步后以同 key 竞争，最终只有一个 Item 且稳定回执字段一致；默认写锁实际等待满 10 秒后返回可重试的 `not-committed`。目标冲突、Event 提交前失败、投影提交后失败、rename unknown 和自有/未知 staging 并存测试进一步核对了不可变内容、保留证据和清理边界。普通与严格 `ResourceWarning` 全量测试、`compileall`、依赖完整性、diff、精确工作树及变更文档链接检查均通过；验收前后默认配置与 `E:\KnowledgeFlowData\capture-store` 均不存在，本批未触碰网络或 GBrain。结论仅为“C3 `capture_text` 已实现并通过本阶段验收”；当时下一门禁统称 C4，D0 后细化为 C4-0。

R0 加固记录（2026-09-11）：R0.1 `92a37b3` 把初始化事务内容、marker 与根目录拆开校验并固定 marker 最后删除，INIT-17/FI-07 证明清理失败保留所有权且新进程可恢复；R0.2 `79515ed` 将配置临时文件绑定完整 `request_sha256 + transaction_id`，INIT-18/INIT-19 证明不同配置目标不互删在途文件、身份匹配但字节不符的未知候选仍被保留。两批后普通与严格 `ResourceWarning` 全量测试均为 148 项（捕获内核 141 项、维护脚本 7 项），生产配置与生产 Store 仍未创建。

### C4-0：读取契约收口（已完成）

目标：只修改文档与契约，裁决正文传输和内存边界、已提交版本的唯一判定、版本解析、`get_capture`/`list_captures` 完整性深度、游标与时间快照以及 warning 归属，并解决冲突登记 C-027。C4-0 不创建公开操作、不修改 Store、不写测试数据；完成并独立复核后，C4 实现仍需另行授权。

C4-0 固定结论：

- 已提交版本是由唯一匹配版本建立 Event 证明的连续 `1..N` 前缀；版本 1 随完整 Item 提交，N>1 以 `capture.version-appended` Event 的无覆盖最终提交为逻辑提交点。
- 唯一无 Event 的 N+1 尾部目录不可见并产生 `incomplete_version_ignored`；其他缺口、孤立/重复 Event 或引用矛盾 fail-closed。读取不修复或清理。
- `get_capture` 先用 Store 外有界磁盘 spool 完整验证，再把正文写入调用方二进制 sink；Store 错误零输出，sink 错误使用独立 `output_write_failed`。
- `list_captures` 验证版本/Event/Envelope/结构与文件大小，只读生成 160 code point 预览所需的有界前缀；完整 Payload attestation 由 `get_capture` 承担。
- 列表使用绑定 Store、查询和末项键的 `c1` 规范 keyset 游标；时间边界严格排除，无 TTL、无跨请求快照，limit 不进入查询指纹。
- 投影异常由不可变 Event 在内存中重建，warning 归属到 `capture_id`，未完成版本还包含 `version`；所有读取结果省略 `commit_state`。

完成记录（2026-09-13）：操作契约、Envelope、设计权威、实现矩阵、编码方案及状态入口已同步上述裁决；未修改 `src/`、测试、fixture 或提示词，未创建配置/生产 Store。文档护栏、普通与严格 `ResourceWarning` 全量 156 项测试、`compileall`、`pip check` 和 diff 检查均通过；本批由独立本地提交完成版本化闭环，未执行 push。

### R0.3D：初始化错误语义诊断与裁决（已完成）

目标：不修改生产代码，只用确定性特征测试验证 M1、M3、M4 的当前公共行为，并把目标语义写入冲突登记；不得把诊断授权扩大为 R0.3F。

诊断结论：

- M1 的清理 `except OSError` 可由 `unlink`/`rmdir` 到达，不能删除或通过全局放宽 `_lstat_if_present`“复活”；真实差距是尚未证明归属的未知候选发生 `stat` 错误时会阻断合法 Store 的幂等重开。R0.3F 只允许局部跳过不可证明候选，已证明自有后的失败仍保留 marker 并 fail-closed。
- M3 已复现：原始 `file-readback` 失败会被二次 `transaction-cleanup-identity` 覆盖。R0.3F 必须保持原错误的公共 `code/cause_code/retryable/stage`，只以安全 `details.cleanup_stage` 保存次级清理阶段；初始化失败仍没有 `saved`/`commit_state`。
- M4 已复现：当前 durability 对 WinError 32、33、5 与仅 `errno.EACCES` 都返回不可重试；目标表只把 32/33 改为 `retryable=true`，5、仅 EACCES、未知/无原因和校验失败保持 `false`。锁等待的上下文分类不能直接外推。

#### 面向非实现者的通俗解释

初始化可以类比为“打开档案室前，检查并清理上次搬运遗留的临时纸箱”。程序既要恢复自己的中断事务，又不能误删无法证明属于自己的文件。M1、M3、M4 分别回答“陌生对象是否阻塞”“多个故障报告哪个”和“是否值得重试”三个不同问题：

1. **M1——看不清陌生纸箱，不应封锁正常档案室，也不能擅自删除。** 一个名称像初始化事务、但尚未由 `transaction.yaml` 和请求摘要证明归属的目录，可能来自旧版本、人工操作或其他请求。过去只要 Windows 暂时拒绝对此候选执行 `stat`，即使正式 Store 完好，幂等重开也会整体失败。正确行为是保留并跳过这个不可证明候选；一旦 marker 已证明它属于本请求，后续遍历、身份复核、`unlink` 或 `rmdir` 失败就必须失败关闭、保留 marker 并返回稳定清理阶段。这里修的是归属证明前后的边界，不是忽略所有磁盘错误。
2. **M3——发动机先坏、拖车后刮伤，报告不能只写拖车刮伤。** 原操作可能先在 `file-readback` 等阶段失败，随后安全清理又发生 `transaction-cleanup-identity` 或配置临时文件清理错误。过去后一个错误会遮蔽真正的首因。正确回执保留首个错误的 `code`、`cause_code`、`retryable` 和 `details.stage`，只把第二个清理阶段作为安全机器 token 放进 `details.cleanup_stage`；若原操作成功而只有清理失败，则清理阶段仍是主 `stage`。这不会泄露路径或原始 OS 文本，也不会给初始化回执增加写入事务专用的 `saved`/`commit_state`。
3. **M4——“文件暂时被占用”和“永久没有权限”不能同样处理。** `retryable` 只表示“不改变请求，稍后再试是否有合理成功机会”，不表示自动无限重试。直接底层 WinError 32（共享冲突）和 33（锁冲突）通常是短暂占用，因此为 `true`；WinError 5、只有 `errno.EACCES`、无底层原因、校验失败和未知错误可能是永久权限或数据问题，继续保持 `false`。锁等待循环知道自己正在争锁，可以使用更宽的上下文判断；通用 durability 层没有这个上下文，不能照搬。

因此，M1 决定“遇到谁可以跳过”，M3 决定“同时失败时向外报告谁”，M4 决定“报告后是否建议稍后重试”。三项都只约束初始化边界，不改变 Capture 数据格式、写入提交点或读取契约。

测试映射：

| 证据 | 测试 |
|---|---|
| M1 未知候选 stat 在 R0.3D 会阻断幂等重开；R0.3F 后跳过并原样保留 | `InitCaptureStoreTest.test_r03f_m1_unknown_candidate_stat_failure_is_skipped` |
| M1 unlink 原生错误到达清理 handler、保留 marker 并可重试 | 既有 `InitCaptureStoreTest.test_init_17_content_cleanup_failure_preserves_marker_for_retry` |
| M3 二次清理身份错误在 R0.3D 遮蔽原始阶段；R0.3F 后保留主阶段 | `InitCaptureStoreTest.test_r03f_m3_primary_stage_survives_transaction_cleanup_failure` |
| M4 在 R0.3F 后只把直接 WinError 32/33 判为可重试 | `DurabilityBackendTest.test_r03f_m4_windows_retryability_is_narrowly_classified` |

完成记录（2026-09-13）：新增 3 项特征测试并把 C-032–C-034 写入设计权威；普通与严格 `ResourceWarning` 全量均为 159 项，`compileall`、`pip check`、文档护栏和 diff 检查通过。未修改 `src/`、公开接口、磁盘格式、配置、fixture 或提示词，所有新磁盘行为只发生在测试持有的临时目录，默认配置和生产 Store 未创建。本批已通过独立本地提交闭合且未 push；下一步另行授权 R0.3F。

### R0.3F：初始化错误语义条件式修复（已完成）

授权边界：只允许按 C-032–C-034 实现三项局部修复，把上述 3 项特征测试转换为目标行为回归，并补充 `details.cleanup_stage` 的类型化白名单/敏感信息拒绝测试。不得全局改变未知路径、锁等待或 Capture 写入语义，不得创建生产配置/Store。

实现结果（2026-09-13）：

- M1 只在读取事务根和 marker、尚未证明请求归属时吸收 `path-stat`，把候选视为未知并原样保留；marker/request 已匹配后，目录遍历和身份复核的 `stat` 错误统一成为 `transaction-cleanup`，继续失败关闭并保留 marker。既有 `unlink` 清理失败语义不变。
- M3 为公共诊断增加仅接受安全机器 token 的 `details.cleanup_stage`；Store 事务与配置临时文件两条 `except` 路径均先保存原异常，再尝试清理，清理失败时重建错误但原 `code/cause_code/retryable/stage` 不变。正常流程中唯一的清理错误仍作为主 `stage`。
- M4 将 `DurabilityError.retryable` 收窄为直接底层 `OSError.winerror in {32, 33}`；WinError 5、999、仅 `errno.EACCES`、无原因与校验异常均保持 `false`，未改锁模块判断。
- 3 项 R0.3D 特征测试已转换为目标行为；新增未知 marker stat、自有树 stat、配置清理主错误优先和 `cleanup_stage` 安全白名单 4 项负向回归。普通与严格 `ResourceWarning` 全量均为 163 项；`compileall`、`pip check` 与文档护栏通过。

本批未改变公开函数签名、Capture schema、磁盘布局、写入提交点、fixture 或提示词；所有磁盘测试仅使用测试持有的临时目录，默认配置和生产 Store 未创建。本批已通过独立本地提交闭合且未 push；在该批完成时，下一步是请求 C4A 授权。

### C4A：读取侧契约能力（已完成）

目标：在不公开读取操作的前提下，把 C4-0 裁决落实为可单测的严格 schema、模型和纯读取原语。

主要文件：

- `codec.py`、`models.py`、`errors.py`
- 必要且保持内部的 `store.py` 版本发现/交叉引用原语
- `tests/capture/fixtures/` 中真实两版本 Event/Envelope/Payload golden
- 对应单元测试

交付边界：

- 严格 `capture.version-appended` Event v1 与创建 Event 分支；追加 Event 绑定 N/N+1 及前后 Envelope 哈希。
- `GetCaptureRequest/Result`、`ListCapturesRequest/Result`、warning details 和 `output_write_failed` 公共形状。
- 六位版本目录、连续已提交前缀、唯一尾部残留和投影内存重建所需的纯原语。
- `c1` cursor/query fingerprint codec、固定 JSON 字节和坏 token 拒绝。
- 不修改公共 `__init__` 导出，不公开 `get_capture`/`list_captures`，不实现 append writer。

完成记录（2026-09-13）：已在 `codec.py` 中实现严格区分 `capture.created`/`capture.version-appended` 的 Event v1，并校验追加 Event 对前后 Envelope、版本、actor 与哈希的绑定；在 `models.py`/`errors.py` 中落实读取请求、元数据结果、列表结果、精确 warning details 和 `output_write_failed`；在内部 `store.py` 中实现六位目录解析、Event 证明的连续版本前缀、唯一无 Event 尾部隔离、warning 转换和只在内存构造的读取状态；同时实现绑定 Store/查询的规范 `c1` 游标及真实版本 2 Payload/Envelope/Event golden。新增 19 项测试后，捕获内核 167 项、维护与文档脚本 15 项，全量 182 项在普通和严格 `ResourceWarning` 模式均通过。顶层 `__init__.py` 与 `operations.py` 未改，未公开 `get_capture`/`list_captures`，未实现 append writer，未创建生产配置或 Store。本批由独立提交 `06cff02` 闭环并已 push 至 `origin/main`；C4B 后续另行获授权。

### C4B：`get_capture`

目标：闭合精确历史/latest 读取、完整 Payload attestation 和“验证后再公开”正文流。

主要文件：`operations.py`、必要的 `store.py` 增量和 `tests/capture/integration/test_get_capture.py`。

必须覆盖实现矩阵 GET-01–GET-16，尤其是两版本链、唯一未完成尾部、Event/版本矛盾、全部 Payload 哈希、64 MiB 有界 spool、sink 中途失败、重复 ID/错误分片/reparse，以及任何 Store 失败时 sink 零字节。只写测试拥有的临时目录。

完成记录（2026-09-13；独立提交 `666ba18`，已 push 至 `origin/main`）：已公开 `GetCaptureRequest`、`GetCaptureResult`、`GetCaptureOperationResult` 与 `get_capture`；运行时只按唯一规范 Item、六位版本目录和 Event 证明的连续 `1..N` 前缀确定 latest/历史版本，唯一无 Event 的 N+1 尾部保持不可见且不清理。链中全部已提交 Payload 先做安全路径、普通文件和声明大小检查，目标版本全部 Payload 再逐块计算实际大小/SHA256，主正文只有在所有 Store 校验及投影只读降级完成后才从 Store 外 delete-on-close 磁盘 spool 写入调用方 sink。sink 短写会续传，异常、0、`None`、boolean 或越界返回统一为可重试 `output_write_failed`，核心不 close/flush sink。

新增 `tests/capture/integration/test_get_capture.py` 的 15 项测试覆盖 GET-01–GET-16，包括真实两版本、未完成尾部、附件/主正文/Envelope/Event/Payload Set 损坏、未知机器 schema、64 MiB 有界读写、部分输出失败、错误分片、重复 ID、Windows junction reparse、路径穿越和模拟 Store I/O；完成时普通及严格 `ResourceWarning` 全量均为 197 项（捕获内核 182 项、维护与文档脚本 15 项）。本批没有实现 append writer、修改磁盘 schema/fixture 或创建生产配置/Store。

### C4C：`list_captures`

目标：闭合 Global Intake、稳定 keyset 分页、有界预览与投影只读降级。

主要文件：`operations.py`、必要的 `store.py` 增量和 `tests/capture/integration/test_list_captures.py`。

必须覆盖实现矩阵 LIST-01–LIST-19，尤其是游标 Store/查询绑定、合法 limit 跨页变化、严格时间边界、两版本时间来源、不可变矛盾整页失败、64 MiB 有界前缀、投影后重建再筛选、warning 确定顺序及无跨页快照承诺。不得以全量哈希所有列表正文换取伪“verified”。

完成记录（2026-09-13；独立提交 `231ad09`，已 push 至 `origin/main`）：已公开 `ListCapturesRequest`、`ListCapturesResult`、`ListCapturesOperationResult` 与 `list_captures`。运行时先枚举唯一规范 Item，验证所有已提交版本/Event/Envelope、Payload 集合、安全路径、普通文件和实际大小，再从不可变链在内存重建当前状态、执行严格时间/路由筛选与固定降序；`c1` 游标绑定 Store、规范查询和末项 key，允许跨页改变 limit。只对当页当前主正文读取最多 640 byte，精确保留前 160 个 Unicode code point；不扫描正文尾部、不全量哈希列表 Payload，也不返回 `integrity=verified`。投影缺失/已知损坏/落后与唯一 N+1 尾部只产生可归属且稳定排序的 warning，未知机器 schema 单独失败，其他不可变矛盾整页 fail-closed。

新增 `tests/capture/integration/test_list_captures.py` 的 15 项测试覆盖 LIST-01–LIST-19，包括空 Store、同毫秒 tie-break、多页无重复遗漏、坏游标与跨 Store/查询拒绝、Global Intake、精确 code-point 预览、严格时间边界、真实两版本、唯一未完成尾部、整页完整性失败、同大小正文篡改的列表/get 差异、真实 64 MiB 有界前缀、投影内存重建、warning 稳定归属及页间新增 Item 的无快照语义。普通及严格 `ResourceWarning` 全量均为 212 项（捕获内核 197 项、维护与文档脚本 15 项）。未实现 append writer，未改磁盘 schema/golden，未创建生产配置或 Store；C4C 后续以 `231ad09` push，下一门禁为 C4V。

### C4V：读取阶段独立验收

默认只补验收测试和证据；发现契约/实现缺陷时停下分类，不借验收批次扩写架构。至少重跑 GET/LIST 全矩阵、真实 4/64 MiB、静态多页、受控并发变化、普通及严格 `ResourceWarning` 全量测试，以及固定工程检查；确认生产配置/Store 仍不存在，`capture_text` 回归字节和回执不变。C4V 单独复核和提交。

C4V 的 GET-01–GET-16 追溯如下；一个测试方法覆盖多个编号时，仍逐项列出对应证据：

| ID | 明确测试方法 |
|---|---|
| GET-01 | `GetCaptureIntegrationTest.test_get_01_02_08_latest_and_history_follow_event_proved_chain` |
| GET-02 | `GetCaptureIntegrationTest.test_get_01_02_08_latest_and_history_follow_event_proved_chain` |
| GET-03 | `GetCaptureIntegrationTest.test_get_03_04_16_not_found_and_success_shapes_never_claim_commit` |
| GET-04 | `GetCaptureIntegrationTest.test_get_03_04_16_not_found_and_success_shapes_never_claim_commit` |
| GET-05 | `GetCaptureIntegrationTest.test_get_05_checks_every_target_payload_before_releasing_primary`、`test_get_05_detects_primary_size_hash_and_payload_set_damage` |
| GET-06 | `GetCaptureIntegrationTest.test_get_06_envelope_tamper_is_rejected_before_sink_output` |
| GET-07 | `GetCaptureIntegrationTest.test_get_07_projection_missing_or_known_invalid_is_read_only_warning` |
| GET-08 | `GetCaptureIntegrationTest.test_get_01_02_08_latest_and_history_follow_event_proved_chain` |
| GET-09 | `GetCaptureIntegrationTest.test_get_09_one_uncommitted_tail_is_hidden_and_left_untouched` |
| GET-10 | `GetCaptureIntegrationTest.test_get_10_committed_event_conflict_or_payload_loss_never_falls_back` |
| GET-11 | `GetCaptureIntegrationTest.test_get_11_gap_duplicate_orphan_event_and_multiple_tails_fail_closed` |
| GET-12 | `GetCaptureIntegrationTest.test_get_12_unsupported_identity_is_distinct_from_known_invalid_data` |
| GET-13 | `GetCaptureIntegrationTest.test_get_13_real_64_mib_body_uses_bounded_external_disk_spool` |
| GET-14 | `GetCaptureIntegrationTest.test_get_14_short_writes_continue_and_invalid_sink_results_are_retryable` |
| GET-15 | `GetCaptureIntegrationTest.test_get_15_wrong_shard_duplicate_and_escape_fail_without_output`、`test_get_15_reparse_item_is_never_followed` |
| GET-16 | `GetCaptureIntegrationTest.test_get_03_04_16_not_found_and_success_shapes_never_claim_commit`、`test_get_16_store_io_failure_precedes_output_and_public_has_no_test_hook` |

C4V 的 LIST-01–LIST-19 追溯如下：

| ID | 明确测试方法 |
|---|---|
| LIST-01 | `ListCapturesIntegrationTest.test_list_01_empty_result_and_public_signature` |
| LIST-02 | `ListCapturesIntegrationTest.test_list_02_03_10_tie_order_keyset_pages_and_limit_change` |
| LIST-03 | `ListCapturesIntegrationTest.test_list_02_03_10_tie_order_keyset_pages_and_limit_change` |
| LIST-04 | `ListCapturesIntegrationTest.test_list_04_malformed_cursor_is_invalid_input` |
| LIST-05 | `ListCapturesIntegrationTest.test_list_05_08_17_filter_rebuilds_projection_in_memory_without_writes` |
| LIST-06 | `ListCapturesIntegrationTest.test_list_06_preview_is_exactly_160_unicode_code_points` |
| LIST-07 | `ListCapturesIntegrationTest.test_list_07_11_request_bounds_reject_bool_and_invalid_time_range` |
| LIST-08 | `ListCapturesIntegrationTest.test_list_05_08_17_filter_rebuilds_projection_in_memory_without_writes` |
| LIST-09 | `ListCapturesIntegrationTest.test_list_09_cursor_is_bound_to_store_and_query` |
| LIST-10 | `ListCapturesIntegrationTest.test_list_02_03_10_tie_order_keyset_pages_and_limit_change` |
| LIST-11 | `ListCapturesIntegrationTest.test_list_07_11_request_bounds_reject_bool_and_invalid_time_range`、`test_list_11_time_boundaries_are_strict` |
| LIST-12 | `ListCapturesIntegrationTest.test_list_12_two_versions_use_v1_capture_time_and_current_event_update` |
| LIST-13 | `ListCapturesIntegrationTest.test_list_13_unique_uncommitted_tail_is_hidden_and_warned` |
| LIST-14 | `ListCapturesIntegrationTest.test_list_14_any_immutable_conflict_fails_the_whole_request` |
| LIST-15 | `ListCapturesIntegrationTest.test_list_15_same_size_body_tamper_is_not_full_attestation` |
| LIST-16 | `ListCapturesIntegrationTest.test_list_16_real_64_mib_body_reads_only_a_bounded_prefix` |
| LIST-17 | `ListCapturesIntegrationTest.test_list_05_08_17_filter_rebuilds_projection_in_memory_without_writes` |
| LIST-18 | `ListCapturesIntegrationTest.test_list_18_multiple_warnings_are_stable_and_page_owned` |
| LIST-19 | `ListCapturesIntegrationTest.test_list_19_mutation_between_pages_has_no_snapshot_claim` |

完成记录（2026-09-14；独立本地提交，未 push）：没有修改生产源代码、公共契约、磁盘 schema 或 golden fixture。新增 `tests/capture/integration/test_read_acceptance.py` 的 2 项公共 API 组合验收：`test_c4v_real_4_and_64_mib_public_write_list_get_round_trip` 使用运行时生成而非入库 fixture 的真实 4 MiB/64 MiB 正文，验证 `capture_text → list_captures → get_capture` 的 capture 身份、Envelope/Payload 哈希、精确输出字节、至多 1 MiB 的输入/输出块、调用方 sink 所有权及 4 MiB 幂等重试稳定回执；`test_c4v_static_pages_and_controlled_creation_use_keyset_boundaries` 仅经公开写入建立 7 个 Item，证明静态多页无重复/遗漏，并在首屏后受控新增 Item，按游标边界核对后续页且由空游标获得新鲜视图。

GET/LIST/C3V 目标矩阵 34 项先行通过，并与新增 2 项组合验收共同组成 36 项 C4V 定向验证；普通及严格 `ResourceWarning` 全量均为 214 项（捕获内核 199 项、维护与文档脚本 15 项）。`compileall`、`pip check`、文档护栏、diff 和工作树范围检查均通过；验收前后默认配置与 `E:\KnowledgeFlowData\capture-store` 均不存在。本批结论仅为“C4 读取能力已通过本阶段验收”；当前 `next_gate` 为 C5-0，仍需另行明确授权。

### C5-0：追加写入契约收口

目标：在不修改生产源代码和磁盘字节的前提下，把 C4-0 的读取可见性翻译成唯一可实现、可故障注入的写入契约。

冻结结果：

- 公共模型固定为关键字 `AppendCaptureVersionRequest`、独立精确 `AppendCaptureVersionResult` 和 `AppendCaptureVersionOperationResult`；不放宽 `capture_text` 的 `CommittedWriteResult`。
- `expected_current_version` 是唯一字段名且只接受整数 `1..999998`；幂等 key 必填，意图可省略并归一化为全 `null`。
- append 的 scope、Request Fingerprint 精确 JSON、锁内完整性/幂等/CAS 优先级和诊断字段固定；已提交同 key 命中优先于 CAS。
- 版本目录仍只是不可见候选，追加 Event 是唯一逻辑提交点；source/target 现场与最终 attestation 固定区分 `not-committed | committed | unknown`。
- 只有完全证明属于同一请求的唯一 N+1 尾部允许采用既有版本/Event ID/Envelope 续封；其他尾部不采用、不覆盖、不删除，通用恢复仍留给 C6。
- 追加使用独立 `version/ + events/` staging 固定树；capture-transaction v1 marker 只增加 append operation，按 operation 隔离允许树并保持 C3 marker 字节/清理回归不变。尾部已知不完整不保留全 Store key，I/O 无法判定身份则写前失败关闭。
- `capture-state` v1 向后兼容支持版本 `1..999999`；追加投影 `updated_at` 取当前 Event 时间，`durability.verified_at` 取最终回读后的独立时间，既有版本 1 golden 不变。
- APP-01–APP-24 取代原 APP-01–APP-08 粗粒度矩阵，覆盖契约、完整性、竞态、尾部、三态证据、投影和真实边界。

完成记录（2026-09-14；独立提交 `ea530ad`）：C4V 提交 `1e38f2f` 当时已 push 至 `origin/main`。本批只修改操作契约、Envelope、冲突登记、实现/编码计划、状态文档和文档护栏期望值；未修改 `src/`、磁盘 schema/golden、公开 API 或提示词，未创建生产配置/Store。`ea530ad` 后于 2026-09-16 push；在该时点全量为 214 项、后续门禁为 C5A。

远端门禁记录（2026-09-16）：最小 Windows CI 提交 `c4d2c7b` 已随 C5-0 及其事实同步提交推送至 `origin/main`；首次 `push` 运行 `35075692046` 在干净 `windows-latest` / Python 3.13 runner 上逐项通过普通与严格 `ResourceWarning` 全量测试、`compileall`、`pip check` 和确定性文档检查。该门禁不部署项目、不创建生产配置/Store，也不授权 C5A。

### C5A：追加契约能力与写入基础

目标：先交付可独立复核的类型、codec/writer、投影泛化、追加 staging 与现场探测原语，不公开 `append_capture_version`，不产生最终新版本。

主要文件：

- `models.py`：新增请求模型并复用渠道、意图、ID、版本和幂等校验。
- `errors.py`：新增独立追加成功结果与精确字段/值域验证，保持 capture_text 回执不变。
- `codec.py`：复用既有严格追加 Event 分支，并把 `capture-state` v1 从“仅初始版本 1”泛化为合法当前版本 `1..999999`；state codec 增加向后兼容的可选当前 Event/前一 Envelope 参数，版本 1 保持旧相等规则与调用形状，版本 >1 必须严格核对 `updated_at == Event.occurred_at`，`durability.verified_at` 使用最终回读后的独立样本。旧版本 1 golden 字节不得改变。
- `operations.py` / `store.py`：只增加内部追加候选、独立 `_AppendStaging`、`version/ + events/` 固定树、按 marker operation 分流的所有权/清理、Event writer、最终 source/target 探测与 attestation 原语；测试故障依赖保持内部。不得把 `_CaptureStaging` 直接改造成两种含义。
- `tests/capture/unit/`、`tests/capture/golden/`：至少闭合 APP-01–APP-03、追加回执、版本 2 投影/Event writer、版本上界、尾部身份可判定边界和 rename 证据纯能力；另做 capture_text marker/golden/清理不变、append marker 先写、部分 rename 后固定树清理、额外对象/替换身份/reparse 拒绝的负向回归。

停点：公共包顶层不得导出或执行 `append_capture_version`；不得扫描真实生产 Store、提交最终版本/Event、实现通用恢复或索引。C5A 单独复核、测试和提交后，才能请求 C5B 授权。

完成记录（2026-09-16；本独立提交，未 push）：新增公开但不可执行的追加请求/结果类型与操作结果联合类型，保持 `CommittedWriteResult` 精确形状不变；严格预封存追加 Envelope/Event；向后兼容地泛化 state v1，并要求版本大于 1 时绑定当前追加 Event 和前一 Envelope；新增独立 marker-first `_AppendStaging`、按 operation 隔离的固定树清理、尾部身份可判定边界、完整 Payload/Event attestation 及 Event rename source/target 证据矩阵。新增 17 项捕获测试后普通与严格 `ResourceWarning` 全量均为 231 项；`compileall`、`pip check`、文档护栏和 diff 检查通过。公共包仍不含 `append_capture_version`，未提交任何最终版本/Event，默认配置与生产 Store 均不存在。下一门禁为需单独授权的 C5B。

### C5B：完整 `append_capture_version`

目标：把 C5A 原语集成为一个公开完整事务，不发布只能写版本目录或无法判定 Event 结果的半操作。

固定顺序：锁外有界正文 staging/回读 → Store 锁 → 全 Store 不可变扫描 → 幂等优先判定 → 唯一目标和当前 Payload attestation → CAS → 同请求尾部采用或新候选预封存 → 版本无覆盖 rename → Event 无覆盖逻辑提交 → 最终回读 → 投影尝试 → 精确回执。Store 锁必须覆盖从扫描到投影尝试；不得引入 Item 锁、数据库或持久幂等索引。

本批至少闭合 APP-04–APP-23 的单进程功能、确定性故障和缩小阈值场景，包括：同 key 在当前版本后来推进后仍返回原版本、不同指纹冲突优先于 CAS、当前 Payload 篡改、完全匹配尾部续封、其他尾部保留、Event rename 三态和提交后投影 warning。可恢复失败必须保留同一幂等 key；任何已证明提交事实不能被后续清理或投影错误倒置。

停点：只使用测试持有的临时 Store；不做 C6 启动扫描/未知尾部隔离、索引、CLI、路由、GBrain、UI 或生产初始化。C5B 单独复核、测试和提交后，才能请求 C5V 授权。

完成记录（2026-09-17；独立提交 `ab2a613`，未 push）：公开固定签名的 `append_capture_version`，按“锁外有界 staging → Store 锁 → 全 Store 不可变扫描 → 幂等优先 → 目标当前 Payload attestation → CAS → 匹配尾部采用或新候选 → 版本无覆盖提交 → Event 逻辑提交 → 最终回读 → 投影尝试”闭合完整事务；新增跨目录同卷 Event 无覆盖提交原语而不改变旧配置提交方法。18 项端到端追加测试与 1 项 durability 回归覆盖 APP-04–APP-23 的单进程、缩小阈值和确定性故障范围，普通与严格 `ResourceWarning` 全量均为 250 项，固定工程检查通过。未实现 C5V 双进程/真实大小验收、C6 通用恢复或生产初始化；下一门禁为需单独授权的 C5V。

### C5V：追加阶段独立验收

默认只增加验收测试和证据；发现契约或实现缺陷时先分类，不借验收批次扩写架构。必须：

- 重跑 APP-01–APP-24、GET-01–GET-16、LIST-01–LIST-19 和 C3/C4 关键回归。
- 使用两个真实 Windows 进程验证同 Item、同 expected 下的同 key 与不同 key 竞争，且只形成一组允许的最终事实。
- 运行时生成真实 4 MiB/64 MiB 新版本，证明 append → list/get 新旧版本的字节、哈希和有界 I/O。
- 逐一验证版本目标冲突、Event preflight 冲突、Event rename 三态、最终确定损坏、投影失败、完全匹配尾部续封及外来尾部不清理。
- 普通与严格 `ResourceWarning` 全量、`compileall`、`pip check`、文档护栏、diff/工作树范围及生产路径前后快照全部通过。

C5V 单独复核和提交；只有它通过后才可声明 C5 追加阶段完成并请求 C6。C5V 不自动授权 C6、C7、生产 Store 或任何外部接入。

完成记录（2026-09-17；本独立提交，未 push）：新增 3 项纯验收测试及仅供测试子进程使用的 append 锁边界屏障，没有修改 `src/`、公共契约、磁盘 schema 或 golden。APP-06 证明不同 key 的两个真实 Windows 进程在同 Item/同 expected 下恰好一个提交 N+1、另一个版本冲突；APP-07 证明同 key 同请求两进程返回同一版本/Event/哈希且只有一组最终事实；APP-24 以运行时生成的真实 4 MiB/64 MiB 新版本证明 append → list/get 的新旧字节、哈希、不继承意图和有界 I/O。APP/GET/LIST/C3/C4 定向 74 项通过，普通与严格 `ResourceWarning` 全量均为 253 项；`compileall`、`pip check`、文档护栏和 diff 检查通过。生产配置与 Store 未创建；下一门禁为需单独授权的 C6。

### C6：故障注入、恢复与迁移

目标：证明文件式 Store 不依赖偶然 happy path 才成立。为保持每个批次可复核，C6 分为 C6A/C6B/C6C 三个独立本地提交；三批都只使用测试持有的临时 Store。

#### C6A：业务事务崩溃恢复

主要文件：`locking.py`、`store.py`、`operations.py`、`durability.py`、`tests/capture/fault/test_capture_faults.py`、`tests/capture/fault/test_append_faults.py` 与 `tests/capture/integration/test_recovery.py`。

- capture/append 每个新 staging 根先创建并持续持有空 `active.lock` Windows 内核租约；进程终止时由操作系统释放，文件存在本身不表示事务仍活跃。
- 后续写操作取得 Store 锁后只扫描 `.staging` 直接子项；规范 UUIDv7 根、匹配 marker、既有普通非 reparse lease 可无等待取得、身份不变且固定树完整通过时才清理。
- 活跃、旧式、未知、额外对象、symlink、junction、其他 reparse、身份变化或 I/O 不可证明对象全部保持原字节；不得为它们补建租约。
- capture 的 9 个故障点与 append 的 7 个故障点均以子进程 `os._exit()` 强制终止，再由无故障钩子的新进程只依据磁盘事实恢复并验证同 key 稳定重试。
- 对版本已落盘而 Event 未提交的 append，只允许完全匹配同 key 的 C5 窄续封；其他尾部保持物理不变并由 Event 真源逻辑隔离，不新增 quarantine schema。

完成记录（2026-09-17；本独立提交，未 push）：上述 16 个进程终止边界、活跃兄弟事务保护、所有权/身份负向矩阵与真实 Windows junction/symlink 防越界均通过；新增 5 项捕获测试后普通及严格 `ResourceWarning` 全量均为 258 项。C2B 初始化故障测试与 C3–C5 回归同时通过。自动化只证明进程崩溃边界，不宣称突然断电、控制器缓存或第三方长期占用已经验证。

#### C6B：派生状态重建

- 从不可变 Item/Version/Event 全量验证后重建 `capture.yaml`；投影不能反向扩大可见链。
- 若本批引入幂等查询索引或空 outbox 投影，只允许作为可删除、可重复重建的派生状态；不可变原件仍是真源。
- 重建必须可重复、可中断、对原件只读，并验证删除/损坏/落后投影及中途失败后的再次运行。
- 完成 REC-01–REC-03，不借重建修复未知 staging、未提交尾部或损坏原件。

#### C6C：Store 迁移

- 实现显式源/目标 Store 身份、目标为空或可证明兼容、复制后完整验证、原子配置切换与失败回退。
- 完成 MIG-01–MIG-05；跨卷复制不得冒充 rename 原子性，切换前配置继续指向源，迁移完成也不自动删除源。
- 不创建或迁移生产 Store；只在测试持有的两个临时根之间演练。

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
.\.venv\Scripts\python.exe -W "error::ResourceWarning" -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
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

复核 C2B 的操作系统锁、事务残片归属、无覆盖连接和六个恢复边界后，MVP-0 的规划估算校准为 **约 10–15 个专注工程日**。增加的预算来自可靠性验证，不增加产品功能范围，也不构成某一批次的编码授权：

| 范围 | 预算 | 主要成本来源 |
|---|---:|---|
| C0–C2A：骨架、基础原语、配置、路径和 Manifest | 2–3 天 | 工程隔离、严格 YAML、UUIDv7、流式哈希和路径身份 |
| C2B：安全初始化 | 2–3 天 | Windows 内核锁、事务标记、flush、无覆盖 rename、并发竞争和六点恢复 |
| C3–C5：四操作与并发 | 3–4.5 天 | 大文本、完整性、游标、幂等和乐观并发 |
| C6：恢复、故障和迁移 | 1.5–2.5 天 | 新进程验证、故障点和移动 Store |
| C7–C8：CLI 与验收 | 1–1.5 天 | 流协议、泄露检查、文档和人工记录 |
| **合计** | **约 10–15 天** | 不包含 UI、GBrain、Harness、路由和 SOP 重构 |

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
| A2 后续批次 | 明确“继续 C1/C2A/…/C3V/R0.3D/C4A/C4B/C4C/C4V”中的当前批次 | 只执行本次点名批次并在边界报告；分批名称不能一次授权自动跨越 | 未授权批次和范围扩张 |
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
7. 未获明确 Git 授权时保留既有工作树修改，不自动清理、提交或恢复。
8. MVP-0 不增加 UI、GBrain、Harness、路由或 SOP 实现；C2B 编码前复核后的规划估算为约 10–15 个专注工程日，其中 C2B 为 2–3 天。

第 1–7 项已于 2026-09-02 获批；第 8 项的 C2 成本校准、C2A/C2B 停点及 C2B-1/2/3 内部边界于 2026-09-03 补充确认。C0–C2（含 C2B-3 崩溃恢复）已于 2026-09-04 全部完成；C3-0 六项行为与原子 Event 补充于 2026-09-08 确认，成功回执、固定错误消息和幂等命中警告语义于 2026-09-09 完成编码前收口，C3A/C3B/C3C/C3V 四个独立停点于 2026-09-10 确认。C3A 与 C3B 已于 2026-09-10 分别完成并单独提交，C3C 与 C3V 已于 2026-09-11 先后完成；R0.1/R0.2 随后分别以 `92a37b3`、`79515ed` 完成，D0-F 已于 2026-09-12 通过独立本地文档提交闭合。D0G、C4-0、R0.3D 与 R0.3F 均于 2026-09-13 通过各自独立本地提交闭合；C4A `06cff02`、C4B `666ba18` 与 C4C `231ad09` 均已同步到 `origin/main`。C4V 于 2026-09-14 完成 214 项验证并以 `1e38f2f` push；C5-0 同日完成契约内容与本地验证并以 `ea530ad` 版本化，2026-09-16 与最小 Windows CI `c4d2c7b` 一并 push，首次远端 CI 已通过。C5A `63a3250`、C5B `ab2a613` 与 C5V 已逐批闭合且尚未 push；用户于 2026-09-17 授权 C6，C6A 已完成并待独立本地提交，下一批为 C6B。push、生产 Store、C7 和外部接入仍未授权。
