# MVP-0 捕获内核编码执行方案

> 状态：Approved Design；C0–C2 已完成，C3-0 已确认，停在 C3 编码前<br>
> 整理日期：2026-09-02<br>
> 确认日期：2026-09-02<br>
> 补充确认日期：2026-09-03<br>
> C2B 复核日期：2026-09-03<br>
> C2B-1 完成日期：2026-09-03<br>
> C2B-2 完成日期：2026-09-03<br>
> C2B-3 完成日期：2026-09-04<br>
> C3-0 行为确认日期：2026-09-08<br>
> 适用范围：MVP-0 本地 Capture Store 与四个文本操作的分批实现<br>
> 前置依据：[MVP-0 捕获内核实现拆解与测试矩阵](mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)<br>
> 执行进度：C0 与 C1 已于 2026-09-02 完成；C2A、C2B-1、C2B-2 已于 2026-09-03 完成并通过验收；C2B-3 已于 2026-09-04 完成并通过验收，C2 整体闭合，当前停在 C3 编码前<br>
> 当前授权：A0、A1 与 A2（C1、C2A、C2B-1、C2B-2、C2B-3）已通过，C3-0 仅完成设计确认；尚未授权 C3 `capture_text`、C4–C5 其余三个捕获操作、真实 Capture Store 或外部系统接入

## 0. 结论先行

编码不应一次性铺开。建议按 C0–C8 九个批次推进，每个批次都必须满足“改动范围固定、测试可独立运行、结果可审查、失败可停下”的条件。

第一步 C0 已完成：已经建立隔离 Python 包和可自动发现的测试骨架。第二步 C1 也已完成：错误模型、UUIDv7、四类哈希和受限 YAML codec 均已有实现、golden fixture 与单元测试。C2A 亦已完成：本地配置、Windows 路径策略和 Store Manifest v1 已实现并通过测试。

C2B-2 已实现测试边界内的 Capture Store 安全初始化、严格重开、无覆盖配置连接、保守残片归属和正常多进程并发。C2B-3 已实现六个内部初始化故障点和跨进程崩溃恢复验证：故障钩子是纯内部能力（生产默认 no-op，公开 `init_capture_store()` 不再暴露任何依赖注入通道），崩溃用子进程 `os._exit()` 模拟，恢复全部由无故障钩子的新进程仅凭磁盘事实完成。C3-0 已冻结 `capture_text` 的输入、原子 Item/Event、投影、写锁、幂等与 actor/时间边界，但未实现代码。四个捕获操作仍不存在，也没有创建 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml` 或 `E:\KnowledgeFlowData\capture-store`。后续必须另行明确说出“继续 C3”或等价的明确编码指令，才可开始实现 `capture_text`；其余三个操作继续留在 C4–C5。

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

C2B-3 已在此停点完成，C2 全部闭合。只有用户明确说“继续 C3”才进入 `capture_text` 编码；真实生产初始化仍属于独立门禁 P0。

必须覆盖 LOCK-01–04、DUR-01–04、INIT-01–16 和全部六个初始化故障点，包括完整骨架、已有 Store 幂等重开、配置完整匹配、初始化锁、同请求并发、不同 root 竞争、同盘 staging/rename、flush/回读、无覆盖配置连接、事务残片归属，以及每个故障点后的新进程重开。不得顺带实现 Item 扫描、投影重建、四个捕获操作、CLI、UI、Harness、GBrain 或 SOP。

共同验收：

- C2B-2 基线的 76 项测试继续通过，并且每个后续 FI 编号都能追溯到具体测试或 `subTest`；不以固定的新增测试数量代替场景覆盖。
- 所有写入都位于测试框架创建并持有的同一临时根；默认用户配置位置只验证解析，真实配置和真实 Capture Store 在测试前后快照一致。
- 故障注入后用新进程依据磁盘事实复核；同请求并发只保留一个 Store 身份，冲突请求不留下孤儿目标。
- C0–C2 测试不产生 Capture 或 State Event；从 C3 起只能在测试持有的临时 Store 中产生它们。所有批次均不得产生生产 Capture、outbox job、网络请求或 GBrain 调用。
- 全量 `unittest`、`compileall`、依赖完整性、`git diff --check` 和精确工作树清单均通过。

### C3：`capture_text`

目标：闭合第一个真正可用的本地保存事务。

主要文件：

- `operations.py`
- 必要的 `codec.py`、`models.py`、`store.py`、`durability.py` 增量
- `tests/capture/integration/test_capture_text.py`
- 必要的单元、并发与故障边界测试

必须覆盖实现拆解文档的 CT-01–CT-24：

- 中文、英文、emoji、CRLF/LF、首尾空白和无末尾换行字节往返一致。
- `str` 与不可 seek 二进制流共享有界写入事务；空字符串、BOM 和非法 UTF-8 拒绝，但仅空白文本允许保存。
- `<= 4 MiB` 内联；`> 4 MiB` 到 `<= 64 MiB` 流式写入一个完整 Payload；不重复读取入口流。
- `> 64 MiB` 默认拒绝且零部分成功；调高配置后可重试。
- 每次主动保存产生新 Item；同一幂等键重试返回同一回执，同 key 不同指纹冲突；并发同 key 最多创建一个 Item。
- 复用 Store 级 Windows 内核锁，10 秒超时返回可重试的 `not-committed`；不得按锁文件存在、PID 或年龄清理锁。
- 完整 Item、版本 1 与 `capture.created` 必须原子可见且从最终路径回读正确；Event 提交前失败不能留下可见 Item。
- `capture.yaml` 是提交后可重建投影；投影失败返回成功加 `projection_needs_rebuild`，不撤销不可变 Item/Event。
- 目标冲突不得覆盖；rename 边界无法证明结果时返回 `unknown`；只清理本事务拥有的未提交 staging。
- 渠道、幂等键和来源时间严格校验；actor 固定为 `user/local-user`，核心时间使用带 `Z` 的 UTC 毫秒格式。
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

- `tests/capture/fault/test_capture_faults.py`
- `tests/capture/fault/test_append_faults.py`
- `tests/capture/integration/test_recovery.py`
- `tests/capture/migration/test_store_move.py`
- 为修复测试暴露问题所需的现有模块小幅增量

必须覆盖：

- 重新运行 C2B 已交付的全部初始化故障测试，并覆盖实现拆解文档第 11 节列出的全部捕获和追加故障点。
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
| A2 后续批次 | 明确“继续 C1/C2A/C2B-1……”或一次写明批次范围 | 执行所列批次并在每批边界报告；C2B-1/2/3 分别停点 | 未授权批次和范围扩张 |
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
8. MVP-0 不增加 UI、GBrain、Harness、路由或 SOP 实现；C2B 编码前复核后的规划估算为约 10–15 个专注工程日，其中 C2B 为 2–3 天。

第 1–7 项已于 2026-09-02 获批；第 8 项的 C2 成本校准、C2A/C2B 停点及 C2B-1/2/3 内部边界于 2026-09-03 补充确认。C0–C2（含 C2B-3 崩溃恢复）已于 2026-09-04 全部完成；C3-0 六项行为与原子 Event 补充于 2026-09-08 确认。C3 及以后编码仍需逐批明确授权。
