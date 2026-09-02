# MVP-0 捕获内核实现拆解与测试矩阵

> 状态：Approved Design；C0–C1 已完成，四操作尚未实现<br>
> 确认日期：2026-09-02<br>
> 适用范围：本地 Capture Store 初始化、配置解析、四个文本操作及验证<br>
> 边界：本文定义实现与测试要求；不授权 C2、生产 `E:\KnowledgeFlowData`、GBrain、LLM、KB 路由或 UI

## 0. 结论先行

系统必须表现成什么样，以及第一版采用什么语言和工程结构实现，均已完成确认。本文确定：

1. 用 Python 3.13 建立独立的本地捕获参考内核，不把逻辑塞进现有三个 Lint 脚本。
2. 内核只暴露初始化动作和四个受限操作；DeepSeek Harness、未来桌面 UI、QQ 或其他入口只能经适配层调用，不能直接取得 Capture Store 文件系统权限。
3. 配置默认位于 Windows 用户本地配置目录，当前建议为 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`；测试和开发允许显式指定另一个绝对配置路径。
4. Capture Store 根目录增加不含绝对路径的 `capture-store.yaml` 身份文件，防止把任意非空目录误当成 Store。
5. 保持文件式规范真源，不引入 SQLite、Postgres、GBrain 或后台服务。
6. 存储继续使用已批准的 YAML 契约；捕获包已在 C0 隔离并锁定 `PyYAML==6.0.3`，但安全子集、schema 和规范发射仍由项目自己的受限 codec 控制。
7. 调用适配层使用 JSON 元数据和原始 UTF-8 流；正文不能作为命令行参数，避免转义错误、长度限制和进程列表泄露。

以上方案及第 13 节九项技术选择已于 2026-09-02 获批。C0 与 C1 已另行授权并完成；这不自动授权 C2、创建生产目录、提交 Git 或接入外部系统。

## 1. 当前项目基线

### 1.1 已有内容

- 三个独立 Python 标准库脚本：`lint.py`、`link-validator.py`、`index-generator.py`。
- 文档、Prompt、模板和测试夹具。
- 已批准的 Capture Envelope、捕获路由和四操作契约。
- C0 建立的 `pyproject.toml`、`src/knowledgeflow_capture` 最小包和 `tests/capture/unit` 测试骨架。
- C1 已实现错误模型、数据值对象、UUIDv7、四类哈希和受限 YAML codec，并建立三份 golden fixture。
- 捕获包已精确锁定 `PyYAML==6.0.3`；自动发现共通过 30 项测试，其中 29 项覆盖 C1，另 1 项为包导入 smoke test。

### 1.2 尚不存在

- 没有 `package.json`、Node/Bun 应用或桌面前端。
- 没有 Capture Store 初始化器和任何四操作实现。
- 没有 Capture Store 初始化、四操作、集成、并发、故障或迁移测试。
- 没有统一 CLI；C1 纯函数与 codec 测试通过不代表捕获业务行为已经实现。
- 没有接入 DeepSeek Harness，也没有可调用的 GBrain 适配器。

### 1.3 当前机器只读盘点

| 项目 | 当前结果 | 对 MVP-0 的影响 |
|---|---|---|
| Python | 3.13.5 | 可作为当前参考实现运行时 |
| Python `uuid.uuid7` | 不可用 | C1 已内部实现并通过 RFC 9562 固定向量、位布局与时钟回拨测试 |
| Python YAML 依赖 | C0 已在 `pyproject.toml` 锁定 `PyYAML==6.0.3` | 只能经项目受限 codec 使用，不能依赖默认加载/发射行为 |
| Node.js | 22.22.3 | 可用，但仓库没有 Node 工程 |
| Bun | 未安装 | 不应成为本地捕获前置条件 |
| 自动化测试 | C0–C1 自动发现并通过 30 项测试 | 已覆盖确定性基础原语；尚无 Store 与四操作回归保障 |
| 生产 `capture-root` | 尚未创建 | 所有实现测试必须使用隔离临时目录 |

这些是 2026-09-02 的本机事实，不是跨机器规范。

## 2. 实现边界

### 2.1 组件关系

```text
未来 UI / CLI / DeepSeek Harness / 其他入口
                    |
                    v
       受限适配层（JSON 元数据 + 文本流）
                    |
                    v
     Capture Operations（四个已批准操作）
                    |
                    v
 配置 / 路径 / 锁 / 哈希 / Envelope / 原子事务
                    |
                    v
          本地 Capture Store 规范原件
```

入口只能表达用户请求，不能绕过 Operations 直接编辑 `capture.yaml`、Envelope、Payload、事件或索引。

### 2.2 MVP-0 允许

- 初始化一个新的本地 Capture Store。
- 加载和机械校验机器本地配置。
- `capture_text`、`get_capture`、`list_captures`、`append_capture_version`。
- 重建当前状态投影和幂等索引所需的内部只读扫描能力。
- 自动化单元、集成、并发和故障注入测试。
- 一个供开发和未来适配器调用的机器接口。

### 2.3 MVP-0 禁止

- 不实现删除、覆盖旧版本、全文搜索或语义搜索。
- 不实现 KB 创建、路由、`raw/` 归档或 SOP。
- 不调用 DeepSeek Harness、任何模型、GBrain、Git 或网络。
- 不创建守护进程、HTTP 服务、WebSocket 或桌面编辑器。
- 不把真实捕获正文写入项目仓库或测试夹具。
- 不因未来 UI 设想而扩大内核权限。

## 3. 运行时与依赖建议

### 3.1 推荐：Python 3.13 参考内核

推荐理由：

- 当前仓库已有 Python 标准库脚本，维护者不需要同时引入第二套工程体系。
- MVP-0 主要是本地文件事务、哈希、锁和测试，不需要前端运行时。
- Python API 可以接收流，便于实现 4–64 MiB 文本的 staging 写入。
- 以后可通过 JSON/流适配、子进程、ACP/MCP 包装或同进程 SDK 接入不同宿主，而不改变文件契约。
- 先隔离捕获内核，可以防止 DeepSeek Harness 获得无边界目录写权限。

这不决定最终桌面界面必须使用 Python。未来 UI 可以采用其他技术栈，只依赖四操作契约。

### 3.2 为什么不直接从 DeepSeek Harness 开始

- 捕获热路径明确不调用模型。
- Harness 不是当前仓库依赖，直接绑定会扩大安装、升级和权限风险。
- Capture Store 必须在 Harness 不可用时仍能保存和读取。
- Harness 将来只需要拿到最小工具接口，不应拥有任意路径和整库写权限。

### 3.3 YAML 依赖的现实问题

Python 3.13 标准库不提供 YAML 解析器，而已批准契约使用 `capture-store.yaml`、`capture.yaml` 和 `envelope.yaml`。可选方案是：

| 方案 | 优点 | 问题 | 建议 |
|---|---|---|---|
| 捕获包使用一个锁定的 YAML 库 | 代码少、解析成熟、可做安全加载 | 增加一个外部依赖 | **推荐** |
| 自写通用 YAML 解析器 | 表面零依赖 | 安全和兼容成本远超 MVP | 不采用 |
| 把机器契约改成 JSON | 标准库原生、确定性强 | 需要重新打开已批准格式决策 | 仅在坚持零依赖时讨论 |

已确认采用推荐方案：

- 外部 YAML 依赖只属于新的捕获包，不改变现有三个脚本的“纯标准库”属性。
- C0 已核验并在 `pyproject.toml` 精确锁定 `PyYAML==6.0.3`；不能改用机器全局包。
- 语法门禁只允许单文档、mapping/list 和 string/integer/boolean/null；拒绝 float、时间对象、binary、重复键、anchor、alias、显式 tag、merge key、多文档和非字符串 key。
- 语法通过后仍按文件类型执行严格 schema 校验：必填/可选字段、类型、枚举、nullable、顺序约束和未知字段分别检查。
- 写出必须通过固定 golden fixture 锁定 UTF-8、LF、无 BOM、2 空格、block style、schema 字段顺序、双引号字符串、无空行和恰好一个末尾换行。
- 完整规则以 [Capture Envelope v1](capture-envelope-v1-捕获信封数据契约与原子保存事务.md)第 8.7 节为准。

### 3.4 UUIDv7

当前机器的 Python 3.13.5 已实测没有 `uuid.uuid7()`。捕获包内实现一个很小、可独立测试的 UUIDv7 生成器，不再为它增加第二个依赖。

UUID 使用 48 位 Unix 毫秒、version 7、RFC variant `10` 和 74 位操作系统安全随机数，并加固定类型前缀。同一毫秒只要求唯一，不承诺严格单调；时钟回拨时使用当次观察值和新随机位，不钳制或伪造时间。测试覆盖固定向量、版本/variant 位、不同毫秒的时间位、同毫秒唯一性和回拨合法性；不能用正文、标题或文件名生成 ID，也不能静默退化为自增整数。

### 3.5 Windows 优先，但数据格式可迁移

第一实现目标是当前 Windows 单机场景：

- 文件替换和同盘 rename 使用平台原子能力。
- 锁实现放在独立模块，Windows 版本不得散落在业务代码中。
- 目录元数据 flush 在平台不能完整保证时必须记录为能力差异，不能夸大“断电绝对不丢”。
- Envelope 和 Payload 不记录盘符，保证以后更换磁盘或实现 Linux 适配时数据不变。

进程崩溃恢复可自动测试；突然断电和存储控制器缓存行为需要在标记为 `Effective` 前另做真实环境验收。

### 3.6 适配层如何传输正文

核心 Python API 接受“小型结构化元数据对象 + 文本字符串或二进制 UTF-8 流”，不要求所有正文先塞入 JSON。

- `capture_text` / `append_capture_version`：渠道、幂等键和预期版本使用小型 JSON 元数据；正文通过 stdin、受控文件流或同进程 stream 传入。
- `get_capture`：元数据和状态可以返回 JSON；大正文通过调用方明确选择的输出流返回，避免把 64 MiB 文本强行嵌入 JSON。
- `list_captures`：只返回列表元数据和 160 code point 预览，可以完整使用 JSON。
- 命令行不得接收 `--text "完整正文"`；否则正文可能受 shell 转义、命令长度和进程列表暴露影响。
- CLI 的精确帧格式属于 M0-E12，但无论如何不能改变四操作的身份、幂等、哈希和版本语义。

## 4. 机器本地配置

### 4.1 推荐配置位置

当前 Windows 默认位置：

```text
%LOCALAPPDATA%\KnowledgeFlow\config.yaml
```

在当前机器通常解析为：

```text
C:\Users\94233\AppData\Local\KnowledgeFlow\config.yaml
```

后者只作解释，不能硬编码。解析顺序建议固定为：

1. 测试或命令明确传入的绝对 `--config` 路径。
2. 否则使用操作系统用户本地配置目录中的默认文件。
3. 找不到配置时返回 `config_not_found`，不扫描磁盘猜测 Store。
4. 配置存在但 YAML、schema、字段或值不合法时返回 `config_invalid`，不与“文件不存在”混为一类。

MVP-0 暂不增加环境变量覆盖，减少同一机器上“实际用了哪个配置”的隐性来源。

### 4.2 配置内容

```yaml
schema: "knowledgeflow.local-config"
schema_version: 1

capture:
  root: 'E:\KnowledgeFlowData\capture-store'
  inline_text_threshold_bytes: 4194304
  max_text_version_bytes: 67108864
```

约束：

- 配置不保存 API key、密码或模型信息。
- `capture.root` 在使用前规范化为绝对路径。
- `0 < inline_text_threshold_bytes <= max_text_version_bytes`。
- 未识别字段默认报错，避免拼错配置后静默使用错误值。
- 配置文件更新使用“同目录临时文件—flush—原子替换”。
- 机器本地配置不提交进 KnowledgeFlow 仓库。

### 4.3 配置与 Store 的关系

配置回答“当前程序连接哪个 Store”；Store 自身的身份由根目录内的 Manifest 回答。二者不能合并：

- 换机器或换盘时修改配置，但 Store Manifest 和所有 Capture ID 不变。
- 配置指向一个没有合法 Manifest 的目录时拒绝打开。
- 不扫描 `E:\` 或用户目录寻找“看起来像 Store”的文件夹。
- 一个进程实例在启动后固定使用一个解析完成的根路径，不能在单次事务中途切换。

### 4.4 生产路径策略与测试路径策略

生产规则继续禁止系统临时目录。自动化测试则必须在独立临时 Store 中运行，两者通过内部依赖注入的 `PathPolicy` 区分：

- 生产 `PathPolicy` 固定拒绝系统临时目录、源码仓库、带 `kb.yaml` 的 KB 祖先目录，以及已知 GBrain 数据目录。
- 测试 `PathPolicy` 只允许测试框架刚刚创建并持有的临时根，不能接受任意用户路径。
- “允许临时根”不能由 YAML 配置、命令行参数或环境变量开启，只能在测试代码中注入。
- 路径安全单元测试覆盖测试策略；另外保留生产策略测试，证明真实配置仍拒绝临时目录。
- 对没有 `kb.yaml` 等身份标记的任意私人目录，程序无法凭空识别其业务用途；初始化仍依赖用户明确选择和“目标不存在/合法 Manifest”规则共同防误写。

## 5. Capture Store Manifest

### 5.1 推荐文件

在 `<capture-root>` 增加机器契约文件：

```text
capture-store.yaml
```

建议最小内容：

```yaml
schema: "knowledgeflow.capture-store"
schema_version: 1
store_id: "store_0199..."
layout_version: 1
created_at: "2026-09-02T00:00:00.000Z"
```

### 5.2 Manifest 不记录

- 不记录 `E:\...` 绝对路径。
- 不记录计算机名、Windows 用户名或模型账号。
- 不记录 KB、GBrain source 或可信知识状态。
- 不记录当前 Capture Item 数量；这类值必须通过扫描或可重建投影获得。

### 5.3 作用

- 防止程序误接管任意非空目录。
- 区分 Store 身份和当前位置，支持迁移。
- 声明布局版本，为未来显式迁移提供依据。
- 让初始化重试能够判断“已经成功”还是“只留下未知残片”。

## 6. 一次性初始化

初始化是部署动作，建议内部名称为 `init_capture_store`，但它不计入四个日常捕获操作。

### 6.1 输入

```yaml
config_path: "<解析后的绝对配置路径>"
capture_root: "E:\KnowledgeFlowData\capture-store"
inline_text_threshold_bytes: 4194304
max_text_version_bytes: 67108864
```

禁止提供 `force`、`overwrite` 或“自动采用任意非空目录”的捷径。

### 6.2 初始化顺序

```text
I0 解析配置位置和目标根路径
 -> I1 验证路径边界、父目录和文件系统
 -> I2 检查目标不存在，或已经是同一合法 Store
 -> I3 在目标父目录创建本次专属初始化临时目录
 -> I4 写入目录骨架和 capture-store.yaml
 -> I5 flush、回读并验证 Manifest 与同盘 rename 能力
 -> I6 原子 rename 为最终 capture-root
 -> I7 原子写入机器本地 config.yaml
 -> I8 重新从配置打开 Store 并返回初始化回执
```

基础目录与 Capture Envelope 保持一致：

```text
<capture-root>/
├── capture-store.yaml
├── items/
├── outbox/
│   ├── pending/
│   ├── running/
│   ├── failed/
│   └── completed/
├── indexes/
│   └── idempotency/
├── .staging/
└── journal/
```

MVP-0 不启用 GBrain，因此 outbox 初始为空；保留目录只是为了与已批准布局一致。

### 6.3 已存在目标的处理

| 目标状态 | 行为 |
|---|---|
| 不存在 | 按 I0–I8 初始化 |
| 存在且 Manifest 合法、`store_id` 可读取 | 视为幂等重试，只补做配置连接和验收，不重建 Store |
| 存在但为空 | 返回 `unrecognized_existing_directory`；MVP-0 不自动接管 |
| 存在且非空、无合法 Manifest | 拒绝，不能写入或清理 |
| Manifest schema/layout 版本未知 | 返回 `unsupported_store_version`，等待显式迁移方案 |
| 配置已指向另一个 Store | 返回 `config_store_conflict`，不得静默切换 |

### 6.4 失败与恢复

- I6 前失败：最终根目录不存在；只允许清理由本次初始化 ID 明确标识的临时目录。
- I6 后、I7 前失败：Store 已存在但尚未连接配置；重试读取合法 Manifest 后继续，不创建第二个 `store_id`。
- I7 后、I8 前失败：配置和 Store 可能都已提交；重试必须返回原 Store，而不是覆盖。
- 未知非空目录和旧生产 Store永不由初始化器自动删除。
- 初始化成功回执必须同时区分 `store_initialized` 与 `config_connected`。

### 6.5 建议回执

```yaml
ok: true
store_initialized: true
config_connected: true
created: true
store_id: "store_0199..."
capture_root: "E:\KnowledgeFlowData\capture-store"
schema_version: 1
layout_version: 1
warnings: []
```

幂等重试时 `created: false`，其他身份保持不变。

## 7. 建议工程结构

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

职责边界：

| 模块 | 只负责 | 不负责 |
|---|---|---|
| `config.py` | 配置查找、严格解析、数值校验 | 创建 Capture Item |
| `paths.py` | 规范化、包含关系、reparse/symlink 边界 | 语义路由 |
| `codec.py` | 受限 YAML 读写和规范发射 | 通用 YAML 编辑器 |
| `ids.py` | UUIDv7 与类型前缀 | 从正文生成 ID |
| `hashing.py` | 流式 SHA256、字节计数 | 去重决策 |
| `locking.py` | 初始化、幂等和 Item 版本锁 | 长时间业务锁 |
| `durability.py` | staging、flush、原子替换/rename | 远程备份 |
| `manifest.py` | Store 身份和布局版本 | 保存主机路径 |
| `store.py` | 文件布局、扫描、投影重建原语 | UI、GBrain |
| `operations.py` | 四个操作的事务编排 | 任意文件系统访问接口 |
| `cli.py` | JSON/流适配和退出码 | 把正文放进命令行参数 |

Python import、包和机器契约名称使用英文，属于此前双语命名规则的机器接口例外；说明文档继续使用“英文名-中文名”。

## 8. 实现任务拆分

| ID | 任务 | 依赖 | 完成标准 |
|---|---|---|---|
| M0-D1 | 技术选择基线 | 无 | 已于 2026-09-02 确认，后续实现不得静默偏离 |
| M0-E1 | 建立隔离 Python 包和测试骨架 | M0-D1 | **已于 2026-09-02 通过：自动发现 1 项测试，包可从 `src/` 导入** |
| M0-E2 | 配置解析和路径安全 | E1 | 严格配置、绝对解析、禁止目录和越界测试通过 |
| M0-E3 | 错误模型、YAML codec 与 golden fixture | E1 | 公共错误/内部原因/警告分层；固定规范发射；危险或不合 schema 的 YAML 被拒绝 |
| M0-E4 | UUIDv7、时钟、四类哈希和字节计数 | E1 | 固定向量、同毫秒唯一性、时钟回拨、四类 golden 和 4/64 MiB 边界通过 |
| M0-E5 | 锁与 durability 原语 | E1 | 同盘 staging/rename、原子替换和崩溃钩子可测试 |
| M0-E6 | Manifest 与 `init_capture_store` | E2–E5 | 初始化、幂等重试、未知目录拒绝、配置连接通过 |
| M0-E7 | `capture_text` | E2–E6 | 版本 1、哈希、Envelope、事件、投影和回执闭环 |
| M0-E8 | `get_capture` | E3、E7 | 最新/历史读取与完整性错误闭环 |
| M0-E9 | `list_captures` | E3、E7 | 稳定排序、游标、预览和 Global Intake 视图闭环 |
| M0-E10 | `append_capture_version` | E4、E5、E7–E8 | CAS 版本冲突、幂等重试和完整新版本闭环 |
| M0-E11 | 投影/索引重建和恢复扫描 | E7–E10 | 删除派生投影后可由不可变记录重建 |
| M0-E12 | JSON/文本流 CLI 适配 | E6–E11 | stdin/文件描述符传正文；stdout 只输出结构化结果 |
| M0-V1 | 全故障注入和并发验证 | E6–E12 | 第 10 节全部自动化场景通过 |
| M0-V2 | 迁移演练 | E11、V1 | 临时 Store 复制—校验—切换后身份和哈希不变 |
| M0-V3 | Windows 人工耐久验收 | V1–V2 | 强制终止恢复通过；断电声明按实测校准 |
| M0-R1 | 实现审查和状态升级 | V1–V3 | 规范与实现一致后，才从 Approved Design 升为 Effective |

不得把 E7 的“能保存一次”当作 MVP 完成。E8–E11 和 V1–V3 是可恢复性承诺的一部分。

## 9. 四操作完成定义

### 9.1 `capture_text`

- 内联和流式入口共享同一事务实现。
- 版本目录提交前不返回成功。
- 同幂等键重试返回同一 Item/Version/Event。
- 事件或投影失败发生在版本提交后时返回成功加 repair warning。
- 不生成标题、摘要、标签、KB 或 Delivery Request。

### 9.2 `get_capture`

- 指定版本严格读取，不存在时不降级为最新。
- 每次返回正文前验证 Payload 和 Envelope 哈希。
- 投影缺失时从不可变版本确定当前版本并发出警告。
- 不借读取动作静默修复或改写 Store。

### 9.3 `list_captures`

- 固定 `captured_at DESC, capture_id DESC`。
- 游标分页在同一静态数据集上不重复、不漏项。
- preview 是内存派生，不写回文件。
- Global Intake 只是 `routing_status=unassigned` 过滤结果。
- 不实现全文或语义搜索。

### 9.4 `append_capture_version`

- 必须提供 `expected_current_version` 和幂等键。
- 保存完整新 Payload，不保存补丁链。
- 同一基线的并发追加最多一个成功。
- 旧版本、旧哈希和旧批准不变，新版本不继承批准。

## 10. 自动化测试矩阵

### 10.0 C1 确定性基础原语

| ID | 场景 | 预期 |
|---|---|---|
| ERR-01 | 构造公共失败 | 固定包含 `ok=false`、公共 `code`、可为 `null` 的诊断 `cause_code`、`message`、`retryable`、`details`；写操作另有三态 `commit_state` |
| ERR-02 | 配置缺失与配置非法 | 分别为 `config_not_found`、`config_invalid`，不再出现 `capture_root_not_configured` |
| ERR-03 | Payload/Envelope 哈希不一致 | 公共码为 `integrity_check_failed`，具体 mismatch 只进入 `cause_code` |
| ERR-04 | 原件提交后投影失败 | `ok=true`、`saved=true`、`commit_state=committed`，警告为 `projection_needs_rebuild` |
| ERR-05 | rename 附近无法判断结果 | `ok=false`、`commit_state=unknown`，提示保留输入并使用同一幂等键重试/查询 |
| ERR-06 | 错误与警告序列化 | 不含 Payload、预览、原始幂等键、凭据或敏感路径 |
| ID-01 | 固定毫秒与固定随机位 | UUIDv7 结果匹配 golden，version/variant 位正确 |
| ID-02 | 同一毫秒批量生成 | ID 唯一，但测试不要求严格单调 |
| ID-03 | 毫秒递增与时钟回拨 | 时间位反映观察值；回拨后仍为合法、唯一 UUID，不伪造时间 |
| HASH-01 | Payload 含中文、CRLF 和无末尾换行 | 对精确保存字节流式计数/哈希，任何字节变化都会改变结果 |
| HASH-02 | 多 Payload 次序输入不同 | 按 `ordinal` 排序后的 Payload Set 规范 JSON 与 golden 一致 |
| HASH-03 | 同一请求重复规范化 | Request Fingerprint 相同；正文、渠道、意图或追加基线变化时不同 |
| HASH-04 | Envelope 自哈希 | 删除整个 `envelope_sha256` 字段后的规范 YAML 与 golden 一致，回填后可验证 |
| YAML-01 | 合法对象确定性发射 | UTF-8、无 BOM、LF、2 空格、固定顺序、双引号字符串且恰好一个末尾换行 |
| YAML-02 | 重复键、anchor、alias、tag、merge key、多文档 | 在语法门禁拒绝，不进入 schema 校验 |
| YAML-03 | float、时间对象、binary、非字符串 key | 在语法门禁拒绝 |
| YAML-04 | 缺字段、错类型、错枚举、非法 null、未知字段/版本 | 语法可安全解析，但被对应 schema 拒绝 |

实际结果（2026-09-02）：ERR-01–06、ID-01–03、HASH-01–04、YAML-01–04 已由 29 项 C1 单元/golden 测试覆盖并全部通过；加上 C0 smoke test，当前自动发现总计 30 项。该结果不覆盖第 10.1 节及以后任何 Store 行为。

### 10.1 配置和路径

| ID | 场景 | 预期 |
|---|---|---|
| CFG-01 | 默认本地配置不存在 | `config_not_found`，不扫描磁盘 |
| CFG-02 | 显式绝对测试配置 | 精确使用该配置 |
| CFG-03 | 普通相对配置路径 | 拒绝，不按 CWD 猜测 |
| CFG-04 | `capture.root` 位于源码仓库内 | 拒绝 |
| CFG-05 | root 位于 KB、GBrain 或系统临时目录 | 拒绝 |
| CFG-06 | `..`、设备路径、symlink/reparse 越界 | 拒绝 |
| CFG-07 | 未知配置字段或重复 YAML key | 拒绝 |
| CFG-08 | 阈值为 0、负数或 inline > max | 拒绝 |
| CFG-09 | 配置中出现绝对当前 root | 解析成功，但该路径不写入 Envelope |

### 10.2 初始化

| ID | 场景 | 预期 |
|---|---|---|
| INIT-01 | 目标不存在 | 创建完整骨架、Manifest 和配置连接 |
| INIT-02 | 对合法 Store 重试 | 同一 `store_id`，`created=false` |
| INIT-03 | 空的既有目录 | 拒绝自动接管 |
| INIT-04 | 非空未知目录 | 零修改、零删除、返回冲突 |
| INIT-05 | 未知 schema/layout | 拒绝，等待迁移 |
| INIT-06 | 配置指向另一个 Store | 拒绝静默切换 |
| INIT-07 | I6 后崩溃、配置未写 | 重试连接原 Store，不生成新 ID |
| INIT-08 | Manifest 不含主机绝对路径 | 通过可移植性检查 |
| INIT-09 | 初始化成功 | 不产生示例 Capture、GBrain job 或网络请求 |

### 10.3 `capture_text`

| ID | 场景 | 预期 |
|---|---|---|
| CT-01 | 普通中文、英文和 emoji | channel-exact 往返一致 |
| CT-02 | CRLF、LF、首尾空白、无末尾换行 | 字节往返和哈希一致 |
| CT-03 | 空字符串 | `invalid_input` |
| CT-04 | 只有空格/换行 | 允许保存 |
| CT-05 | 恰好 4 MiB | 内联路径成功 |
| CT-06 | 4 MiB + 1 byte | 流式路径成功，同一 Payload |
| CT-07 | 恰好 64 MiB | 流式路径成功 |
| CT-08 | 64 MiB + 1 byte | `text_too_large`，无最终版本和部分成功 |
| CT-09 | 调高本地安全上限后重试 | 在磁盘校验允许时可流式保存 |
| CT-10 | 相同内容、不同主动保存 | 两个 Capture Event/Item |
| CT-11 | 同 key 同请求重试 | 返回同一回执 |
| CT-12 | 同 key 不同请求 | `idempotency_conflict` |
| CT-13 | GBrain、网络完全不可用 | 本地保存不受影响 |

### 10.4 `get_capture`

| ID | 场景 | 预期 |
|---|---|---|
| GET-01 | 不传版本 | 返回最高完整已提交版本 |
| GET-02 | 指定历史版本 | 返回指定正文和当前版本号 |
| GET-03 | Item 不存在 | `capture_not_found` |
| GET-04 | 版本不存在 | `version_not_found`，不回退 |
| GET-05 | Payload 被篡改 | `integrity_check_failed`，不返回 verified |
| GET-06 | Envelope 被篡改 | `integrity_check_failed` |
| GET-07 | `capture.yaml` 缺失 | 从不可变记录读取并警告，不静默写回 |

### 10.5 `list_captures`

| ID | 场景 | 预期 |
|---|---|---|
| LIST-01 | 空 Store | 空 items、无错误 |
| LIST-02 | 多 Item 相同时间 | 用 `capture_id` 稳定打破平局 |
| LIST-03 | 多页遍历 | 无重复、无漏项 |
| LIST-04 | 非法或过期游标 | 结构化错误，不猜测位置 |
| LIST-05 | `routing_status=unassigned` | 结果即 Global Intake 视图 |
| LIST-06 | emoji/换行预览 | 160 code point 机械派生，不破坏原文 |
| LIST-07 | 请求 `limit > 100` | 按当前推荐返回 `invalid_input`，不静默钳制 |
| LIST-08 | 投影损坏 | 返回可解释警告，不能把 Item 当成丢失 |

`LIST-07` 已选定“拒绝”而不是“钳制”：返回 `invalid_input`，让调用错误可见。

### 10.6 `append_capture_version`

| ID | 场景 | 预期 |
|---|---|---|
| APP-01 | expected 与当前一致 | 生成 N+1 完整版本 |
| APP-02 | stale expected | `version_conflict`，零覆盖 |
| APP-03 | 两个并发 expected=N | 一个成功，一个冲突 |
| APP-04 | 成功后同 key 重试 | 返回同一个 N+1，不生成 N+2 |
| APP-05 | 同 key 不同正文 | `idempotency_conflict` |
| APP-06 | 新正文与旧正文相同 | 用户主动追加时仍生成新版本 |
| APP-07 | 旧版本已有批准 | 新版本不继承批准 |
| APP-08 | 版本 1 回读 | 追加后字节和哈希完全不变 |

### 10.7 恢复和迁移

| ID | 场景 | 预期 |
|---|---|---|
| REC-01 | 删除 `capture.yaml` | 从版本和事件重建相同投影 |
| REC-02 | 删除幂等索引 | 从不可变记录恢复 key 映射 |
| REC-03 | 删除空 outbox 投影 | MVP-0 重建后仍为空 |
| MIG-01 | 将临时 Store 从路径 A 复制到 B | `store_id`、Capture ID 和哈希不变 |
| MIG-02 | 复制未完成 | 配置仍指向 A，B 不被启用 |
| MIG-03 | B 校验失败 | 拒绝切换，A 保持可读 |
| MIG-04 | B 验收通过后改配置 | 所有四操作在 B 正常工作 |
| MIG-05 | 迁移完成前 | A 不自动删除 |

## 11. 故障注入方案

### 11.1 注入原则

- 故障点通过内部依赖注入或测试专用 hook 提供，不能成为生产用户可随意触发的公开参数。
- 每个故障测试在独立临时 Store 中运行。
- 注入后必须重新启动新进程检查磁盘，而不是只检查原进程内存。
- 测试不得触碰 `E:\KnowledgeFlowData\capture-store`。

### 11.2 初始化故障点

```text
after_init_temp_created
after_manifest_written
after_manifest_flushed
after_root_renamed
before_config_replaced
after_config_replaced
```

### 11.3 捕获/追加故障点

```text
after_lock_acquired
after_payload_written
after_payload_flushed
after_envelope_written
after_readback_verified
after_version_renamed
after_event_appended
after_projection_replaced
before_receipt_returned
```

每个点至少验证：

- 是否存在最终版本。
- 是否允许同 key 安全重试。
- 是否产生重复 Item/Version/Event。
- 是否有不完整目录被误认为成功。
- 回执中的 `saved` 是否与磁盘事实一致。

### 11.4 无法仅靠自动化证明的部分

- 突然断电。
- 磁盘控制器谎报 flush。
- 文件系统损坏。
- 杀毒软件、同步盘或备份软件长期占用文件。

这些需要真实 Windows 环境人工验收和备份策略，不能被普通单元测试结果掩盖。

## 12. 成本与阶段门禁

### 12.1 粗略工作量

| 范围 | 预计专注工程时间 |
|---|---:|
| 工程骨架、配置、YAML codec、ID/哈希 | 1.5–2.5 天 |
| 初始化、路径、锁和 durability 原语 | 1.5–2.5 天 |
| 四个操作 | 2–3 天 |
| 并发、故障注入、恢复和迁移测试 | 2.5–4 天 |
| CLI 适配、说明和最终审查 | 1–1.5 天 |
| **合计** | **8.5–13.5 天** |

这是“满足已承诺可靠性”的估计，不是只做一次成功演示的估计。若只实现 happy path，可能 2–4 天，但不能安全地称为 KnowledgeFlow MVP-0。

### 12.2 当前阶段主动省下的成本

- 不做 UI：避免前端和桌面打包成本。
- 不接 Harness：避免模型、会话和插件运行时耦合。
- 不接 GBrain：避免账号、引擎、副作用和同步调试。
- 不建数据库：避免双真源、schema migration 和服务运维。
- 不支持 URL/文件/OCR：先证明最小文本事务。
- 不实现自动修复命令：先保证检测、拒绝和可重建原语正确。

### 12.3 门禁

| 门禁 | 通过条件 | 通过前禁止 |
|---|---|---|
| G0 技术选择 | **已于 2026-09-02 通过** | 未通过时禁止创建包或安装依赖 |
| G0.5 编码方案 | **已于 2026-09-02 对 C0–C1 通过；后续批次仍逐批授权** | 未授权批次的业务代码和真实 Store |
| G1 测试骨架与基础原语 | **已于 2026-09-02 通过：自动发现并通过 30 项测试** | 实现 Store 或四操作 |
| G2 初始化 | INIT/CFG 全绿 | 使用真实生产 root |
| G3 本地操作 | CT/GET/LIST/APP 全绿 | 接 UI/Harness |
| G4 恢复能力 | REC、故障注入、迁移全绿 | 将规范标记 Effective |
| G5 人工耐久 | Windows 强制终止/断电边界有实证记录 | 宣称抗断电 |
| G6 生产初始化 | 用户再次明确授权创建真实目录 | 写入 `E:\KnowledgeFlowData` |

## 13. 已确认的技术选择

| 编号 | 推荐选择 | 不这样选的主要影响 |
|---|---|---|
| I-001 | Python 3.13 作为 MVP-0 参考内核 | TypeScript 需新建另一套工程；语言中立伪代码无法完成实际验收 |
| I-002 | 捕获包允许一个锁定的 YAML 依赖 | 坚持零依赖就应重新讨论 JSON，不能自写通用 YAML |
| I-003 | Windows 第一实现，数据格式保持跨平台 | 同时承诺跨平台会显著扩大锁、flush、路径和 CI 测试成本 |
| I-004 | 默认配置放 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`，允许显式绝对 `--config` | 把配置放数据根内会产生“先知道 root 才能找到 root”的循环 |
| I-005 | 根目录增加不可变 `capture-store.yaml`，不记录绝对路径 | 没有 Manifest 难以防止误接管目录和识别迁移后的 Store |
| I-006 | 适配层用 JSON 元数据 + stdin/文件流传正文 | 把正文放命令行参数会带来转义、长度和泄露风险 |
| I-007 | `list limit > 100` 返回 `invalid_input` | 自动钳制会隐藏调用方错误 |
| I-008 | 不引入数据库和后台服务 | 引入后会增加双真源、迁移和运维成本 |
| I-009 | 采用完整可靠性范围，预算按 8.5–13.5 天评估 | 2–4 天 happy path 不满足恢复、并发和审计承诺 |

以上选择已确认，本文保持 `Approved Design`。C0 测试骨架和 C1 确定性基础原语已经完成；下一批 C2 尚未授权。真实 `E:\KnowledgeFlowData\capture-store` 仍只有在用户另行明确要求“初始化生产 Capture Store”后才允许创建。
