# MVP-0 捕获内核实现拆解与测试矩阵

<!-- knowledgeflow-doc-status tests=214 capture_tests=199 script_tests=15 next_gate=C5A -->

> 状态：Approved Design；C4V `1e38f2f`、C5-0 `ea530ad` 与最小 Windows CI `c4d2c7b` 均已 push，首次远端 CI 已通过；下一功能门禁为 C5A<br>
> 确认日期：2026-09-02<br>
> 补充确认日期：2026-09-03<br>
> C2B 复核日期：2026-09-03<br>
> C2B-1 完成日期：2026-09-03<br>
> C2B-2 完成日期：2026-09-03<br>
> C2B-3 完成日期：2026-09-04<br>
> C3-0 行为确认日期：2026-09-08<br>
> C3 编码前收口日期：2026-09-09<br>
> C3A/C3B 完成日期：2026-09-10<br>
> C3C 完成日期：2026-09-11<br>
> C3V 完成日期：2026-09-11<br>
> R0.1/R0.2 完成日期：2026-09-11<br>
> D0 内容与本地验证日期：2026-09-11；D0-F 版本化收口日期：2026-09-12（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> D0G 内容与本地验证日期：2026-09-12；版本化收口日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> C4-0 读取契约完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> R0.3D 诊断与裁决完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> R0.3F 完成日期：2026-09-13（完成时未 push；现已随 `dc3a35f` 同步至 `origin/main`）<br>
> C4A 完成日期：2026-09-13（独立提交 `06cff02`；已 push 至 `origin/main`）<br>
> C4B 完成与版本化收口日期：2026-09-13（独立提交 `666ba18`；已 push 至 `origin/main`）<br>
> C4C 完成与版本化收口日期：2026-09-13（独立提交 `231ad09`；现已 push 至 `origin/main`）<br>
> C4V 完成与版本化收口日期：2026-09-14（独立提交 `1e38f2f`；已 push 至 `origin/main`）<br>
> C5-0 内容与本地验证日期：2026-09-14（独立提交 `ea530ad`；2026-09-16 已 push 至 `origin/main`）<br>
> 最小 Windows CI 首次通过日期：2026-09-16（提交 `c4d2c7b`；远端运行 `35075692046`）<br>
> 适用范围：本地 Capture Store 初始化、配置解析、四个文本操作及验证<br>
> 边界：本文定义实现与测试要求；C4V `1e38f2f`、C5-0 `ea530ad` 与最小 Windows CI `c4d2c7b` 均已 push，首次远端 CI 已通过；当前不授权 C5A、生产 `E:\KnowledgeFlowData`、GBrain、LLM、KB 路由或 UI

## 0. 结论先行

系统必须表现成什么样，以及第一版采用什么语言和工程结构实现，均已完成确认。本文确定：

1. 用 Python 3.13 建立独立的本地捕获参考内核，不把逻辑塞进现有三个 Lint 脚本。
2. 内核只暴露初始化动作和四个受限操作；DeepSeek Harness、未来桌面 UI、QQ 或其他入口只能经适配层调用，不能直接取得 Capture Store 文件系统权限。
3. 配置默认位于 Windows 用户本地配置目录，当前建议为 `%LOCALAPPDATA%\KnowledgeFlow\config.yaml`；测试和开发允许显式指定另一个绝对配置路径。
4. Capture Store 根目录增加不含绝对路径的 `capture-store.yaml` 身份文件，防止把任意非空目录误当成 Store。
5. 保持文件式规范真源，不引入 SQLite、Postgres、GBrain 或后台服务。
6. 存储继续使用已批准的 YAML 契约；捕获包已在 C0 隔离并锁定 `PyYAML==6.0.3`，但安全子集、schema 和规范发射仍由项目自己的受限 codec 控制。
7. 调用适配层使用 JSON 元数据和原始 UTF-8 流；正文不能作为命令行参数，避免转义错误、长度限制和进程列表泄露。

以上方案及第 13 节九项技术选择已于 2026-09-02 获批。C0–C2（含 C2B-3 崩溃恢复）已逐批授权并完成；[C3-0 阻塞性行为决策](c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md)已于 2026-09-08 获批，成功回执、固定错误消息与幂等命中警告语义于 2026-09-09 完成编码前收口。C3A 与 C3B 已于 2026-09-10 分别完成，C3C、C3V、R0.1 与 R0.2 已于 2026-09-11 先后完成，D0-F、D0G、C4-0、R0.3D、R0.3F 与 C4A 已分别完成版本化收口；C4A `06cff02`、C4B `666ba18` 和 C4C `231ad09` 已同步到 `origin/main`。C4V 后续获得单独授权并已完成验收及独立本地提交；这不授权 push、C5-0 或创建生产目录、接入外部系统。

## 1. 当前项目基线

### 1.1 已有内容

- 三个独立 Python 标准库脚本：`lint.py`、`link-validator.py`、`index-generator.py`。
- 文档、Prompt、模板和测试夹具。
- 已批准的 Capture Envelope、捕获路由和四操作契约。
- C0 建立的 `pyproject.toml`、`src/knowledgeflow_capture` 最小包和 `tests/capture/unit` 测试骨架。
- C1 已实现错误模型、数据值对象、UUIDv7、四类哈希和受限 YAML codec，并建立三份 golden fixture。
- C2A 已实现本地配置契约、Windows 路径策略和 Store Manifest v1，并建立两份 golden fixture。
- C2B-1 已实现 Windows 初始化内核锁、通用 durability 原语和多进程测试支持。
- C2B-2 已实现 Capture Store 安全初始化编排、无覆盖配置连接、已有目标分类、保守残片归属和正常多进程并发，并建立 INIT-01–16 集成测试。
- C2B-3 已实现六个内部初始化故障点（内部 no-op 钩子，公开接口无注入通道）和跨进程崩溃恢复测试，覆盖 FI-01–06。
- C3A 已实现 Event/Projection v1、输入/时间/渠道边界、幂等摘要和精确回执，提交为 `346164d`；C3B 已实现 Store 写锁、有界 UTF-8 写入和可验证归属的 staging，提交为 `8050d88`；C3C 已实现公开 `capture_text` 的完整 T0–T9 事务，C3V 已完成真实大小、加强版竞态与故障验收。R0.1 `92a37b3` 和 R0.2 `79515ed` 随后修复初始化事务清理顺序与配置临时文件请求身份。
- C4A 已在未公开操作的边界内实现严格追加 Event schema、读取请求/结果、规范游标 codec、Event 证明的连续版本链纯原语、内存状态重建及真实两版本 golden，并由独立提交 `06cff02` 闭环及 push。
- C4B 已公开 `get_capture` 并闭合 latest/历史版本、目标 Payload 完整证明、Store 外磁盘 spool、sink 失败和投影只读降级；独立提交 `666ba18` 已 push。
- C4C 已公开 `list_captures`，闭合全 Store 结构验证、内存状态筛选、有界预览、稳定 keyset 分页及 warning 归属，并由独立提交 `231ad09` 完成版本化和 push。
- C4V 已在不修改生产代码、公共契约或磁盘 schema 的边界内新增 2 项公共 API 组合验收，闭合真实 4/64 MiB 写入—列表—读取、静态分页及页间受控新增证据，并由独立提交 `1e38f2f` 完成版本化和 push。
- C5-0 已冻结追加的请求/结果、幂等优先于 CAS、唯一尾部窄续封、Event rename 三态证据、追加投影时间、独立 staging 所有权、错误优先级和 APP-01–APP-24，内容与本地验证已由独立提交 `ea530ad` 版本化并 push；未修改生产代码或磁盘 schema。最小 Windows CI `c4d2c7b` 的首次远端运行已通过。
- 捕获包已精确锁定 `PyYAML==6.0.3`；C0–C2 里程碑自动发现 85 项测试，稳定化后为 93 项，C3A 后为 105 项，C3B 后为 122 项，C3C 后为 140 项，C3V 后为 144 项，R0.1/R0.2 后为 148 项，D0G 后为 156 项，R0.3D 后为 159 项，R0.3F 后为 163 项，C4A 后为 182 项，C4B 后为 197 项，C4C 后为 212 项，C4V 内容后当前为 214 项。

### 1.2 尚不存在

- 没有 `package.json`、Node/Bun 应用或桌面前端。
- `append_capture_version` 尚未实现；`get_capture` 与 `list_captures` 已分别由 C4B、C4C 独立版本化并 push，C4V 验收也已以 `1e38f2f` push。下一实现门禁 C5A 未授权。
- 没有追加故障注入、投影与幂等索引恢复或迁移测试；初始化崩溃恢复和 C3 新建事务已验收，但捕获业务崩溃恢复尚未验收。
- 没有统一 CLI；C3 的 Python 操作边界通过测试不代表机器适配层已经实现。
- 没有接入 DeepSeek Harness，也没有可调用的 GBrain 适配器。

### 1.3 当前机器只读盘点

| 项目 | 当前结果 | 对 MVP-0 的影响 |
|---|---|---|
| Python | 3.13.5 | 可作为当前参考实现运行时 |
| Python `uuid.uuid7` | 不可用 | C1 已内部实现并通过 RFC 9562 固定向量、位布局与时钟回拨测试 |
| Python YAML 依赖 | C0 已在 `pyproject.toml` 锁定 `PyYAML==6.0.3` | 只能经项目受限 codec 使用，不能依赖默认加载/发射行为 |
| Node.js | 22.22.3 | 可用，但仓库没有 Node 工程 |
| Bun | 未安装 | 不应成为本地捕获前置条件 |
| 自动化测试 | C4V 内容后当前全量 214 项通过（捕获内核 199 项、维护脚本 7 项、文档护栏 8 项） | 已覆盖 C3 T0–T9、GET/LIST 全矩阵、真实 4/64 MiB 公共读取闭环、静态/变化中分页、R0 初始化所有权回归及确定性文档漂移 |
| 生产 `capture-root` | 尚未创建 | 所有实现测试必须使用隔离临时目录 |

Python、Node.js 与 Bun 盘点来自 2026-09-02 至 2026-09-04；实现与测试状态已同步至 2026-09-14。它们都是本机事实，不是跨机器规范。

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
- `get_capture`：结构化结果返回元数据和 `body_length_bytes`；正文先在 Store 外磁盘 spool 中以不超过 1 MiB 的块完成全量验证，再通过调用方提供的二进制 sink 返回，避免把 64 MiB 文本强行嵌入 JSON 或内存。
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

配置读取和写出采用不同严格度：

- 读取允许通过受限 YAML 语法门禁和本配置 schema 校验、但缩进或引号等排版不是规范形式的安全输入。
- 每次由程序新建或替换配置时，都使用 `codec.py` 的确定性规则发射规范字节；配置 schema 定义在 `config.py`，不加入 Envelope schema registry。
- 重复键、未知字段、错误 schema/version、错误类型和非法阈值一律拒绝。
- 初始化遇到已有配置时，只有规范化后的 root、两个阈值以及所有固定字段都与本次请求一致，才视为幂等连接；root 或阈值任一不一致都返回 `config_store_conflict`，并且必须发生在创建目标 Store 之前。
- 已有安全但非规范排版的配置若语义完整且与请求一致，可以直接读取且不为“整理格式”而改写；一旦确实需要写入，就必须整体规范发射。

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
- Windows MVP 只接受本机盘符上的绝对路径，拒绝 UNC、`\\?\`/`\\.\` 设备命名空间和普通相对路径；先规范化再做包含关系判断，不能用字符串前缀代替路径边界。
- 对所有已存在的祖先路径检查 reparse point/symlink，解析结果不得逃离被策略允许的根；生产保护路径来自受信任构造参数，不能由配置、CLI 或环境变量自行解除。

## 5. Capture Store Manifest

### 5.1 v1 固定文件

在 `<capture-root>` 增加机器契约文件：

```text
capture-store.yaml
```

v1 固定最小内容：

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

### 5.4 Manifest 校验与规范字节

- Manifest schema 定义在 `manifest.py`，复用通用受限 YAML codec，不修改 Envelope schema registry。
- Manifest 只能由程序生成，保存和重新打开时都要求与规范发射结果逐字节一致；安全但非规范排版的 Manifest 也不能作为 Store 身份。
- `store_id` 必须是 `store_` 前缀的合法 UUIDv7；`created_at` 必须是规范 UTC `Z` 时间；schema、schema version 和 layout version 必须精确受支持。
- 重复键、未知字段、缺失字段、错误类型和未知版本均拒绝；未知 schema/layout 返回 `unsupported_store_version`。
- Manifest 不能增加绝对路径、主机/用户身份、KB/GBrain 字段或可重建计数。
- 合法已有 Store 还必须具备第 6.2 节全部固定目录，且每个路径类型正确、未被 reparse/symlink 替代；缺项只报错，不自动补齐或修复。

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

路径关系在进入锁与写入前固定为：

- `config_path` 与 `capture_root` 都必须先成为规范化并解析 reparse/symlink 后的本机绝对路径。
- `config_path` 不得等于或位于 `capture_root` 内；已存在的配置文件、锁文件和配置临时文件都必须是普通文件，不能是 symlink、junction 或其他 reparse point。
- `capture_root` 的直接父目录必须预先存在、类型正确并通过路径策略；初始化器不递归创建任意数据父目录。用户以后选择生产位置时，应先由文件选择器或安装流程确认/创建该父目录。
- `config_path` 的直接父目录可以由初始化器创建，但只允许创建这一层；它的父目录必须已经存在、类型正确并通过边界检查，不能使用无界的递归 `parents=True`。
- 测试 `PathPolicy` 要求配置、锁、配置临时文件、初始化事务目录和 Store 全部位于同一个测试持有根内。生产策略仍使用受信任的默认配置位置或显式绝对配置位置，不能由 YAML 打开测试豁免。

### 6.2 初始化顺序

```text
I0 解析配置位置和目标根路径，验证/有限创建配置目录，并以解析后的 config_path 为竞争域取得初始化锁
 -> I1 验证路径边界、父目录和文件系统
 -> I2 在锁内重读配置，并检查配置冲突及目标不存在/同一合法 Store
 -> I3 在目标父目录创建带可验证事务标记的本次专属初始化目录
 -> I4 写入目录骨架和 capture-store.yaml
 -> I5 flush、回读并验证 Manifest 与同盘 rename 能力
 -> I6 原子 rename 为最终 capture-root
 -> I6.5 从最终路径重验 Store，并清理已验证归属的初始化事务目录
 -> I7 以“不覆盖已出现目标”的原子提交连接机器本地 config.yaml
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

#### 6.2.1 初始化锁

- Windows 参考实现使用标准库可用的操作系统文件锁；锁文件建议为 `<config_path>.init.lock`，锁的真相是当前进程持有的内核锁，不是该文件是否存在。
- 锁文件可以长期留在配置目录。正常退出、异常退出或进程被终止后，操作系统释放锁；重试不得因为看见旧锁文件就删除它或永久拒绝启动。
- 默认等待上限为 10 秒；单元测试通过内部时钟/等待注入缩短时间，YAML、CLI 和环境变量均不能打开测试钩子或改变锁语义。
- 超时或已知的临时共享冲突返回 `capture_store_unavailable` 且 `retryable=true`。锁从 I0 一直持有到 I8 完成或失败清理结束。
- 相同解析配置路径必须互斥；不同配置路径互不阻塞。锁文件若被替换为目录、symlink、junction 或其他 reparse point，必须拒绝使用。

#### 6.2.2 初始化事务目录

初始化临时区与最终 Store 内部的 `<capture-root>/.staging/` 是两个不同概念。前者位于目标父目录，只服务一次 Store 初始化；后者是最终骨架的一部分，留给后续 Capture 事务。

```text
<capture-root-parent>/.knowledgeflow-init-<transaction-uuid>/
├── transaction.yaml
└── store/
```

`transaction.yaml` 的字段固定为：

```yaml
schema: "knowledgeflow.init-transaction"
schema_version: 1
transaction_id: "01991a7e-7b20-7a31-8d14-0b8ab6b35421"
request_sha256: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
```

- `transaction_id` 是无类型前缀的规范 UUIDv7，并与目录名中的 UUID 完全相同。该内部 schema 定义在 `store.py`，复用通用受限 codec，但不加入 Envelope registry，也不要求新增公开 golden fixture。
- 标记不记录绝对路径、正文或凭据；未知字段、错误类型、非规范字节或身份不匹配都使其成为不可自动清理的未知残片。
- `request_sha256` 只对“解析后的配置路径、解析后的 Store 路径和两个阈值”的内部规范表示计算，用于崩溃清理匹配；它不是第五类 Capture 内容哈希，不进入 Manifest、Envelope 或公共 API。
- `store/` 子目录内构建固定骨架；I6 只把这个子目录无覆盖地 rename 为最终 root，因此事务标记不会进入 Store。
- `after_init_temp_created` 的固定含义是事务目录、规范标记和 `store/` 子目录已经完成 flush/回读。操作系统若在更早的任意指令间崩溃，未知残片可以保留，但绝不能猜测删除。
- 新进程只扫描目标父目录下一层、名称符合固定前缀的候选；只有目录名、规范事务标记、UUID 和当前请求哈希全部匹配时才能清理。任何缺失、损坏或不匹配对象均保持原样。
- I6 后先从最终 root 重验 Manifest 和骨架，再删除已经匹配的外层事务目录；清理失败时不连接配置，返回 `capture_store_unavailable`，由同请求重试继续。
- 配置临时文件使用保留前缀、完整 `request_sha256` 和事务 UUID 命名；请求哈希已绑定规范化后的精确配置路径、Store 路径与两个阈值。重试只能删除“请求身份匹配、普通非 reparse 文件、名称合法且字节与当前应写规范配置完全一致”的候选；旧式、外来或无法完整证明归属的配置临时文件保持原样。

#### 6.2.3 C2B durability 边界

- 每个需要承诺的文件都必须完成应用缓冲区 flush、文件句柄 `fsync`、关闭后按最终字节回读；Manifest 和配置还要重新通过各自严格校验。
- Store 提交使用同一卷内的无覆盖目录 rename。最终 root 已存在时绝不能使用 `os.replace` 覆盖，而是重新进入已有目标分类。
- 初次配置连接只在 I2 确认配置缺失时发生：先在同目录写入并验证本次专属临时文件，提交前再次检查目标；目标若已经出现则不覆盖，改为重读并判断“完全匹配”或 `config_store_conflict`。
- root rename 后再次从最终路径验证 Manifest 和完整骨架；配置提交后再次从配置打开同一 Store，二者都成功才返回 `InitStoreResult`。
- 目录元数据 flush 在 Windows/文件系统明确支持时执行。平台明确不支持时不把它伪装成已完成，也不因此夸大承诺；已知不支持记录在测试结果中，其他 I/O 失败按 `capture_store_unavailable` 处理。
- C2B 的 `durable` 只证明应用进程崩溃后可恢复。突然断电、控制器缓存和文件系统损坏仍留给人工耐久验收。

### 6.3 已存在目标的处理

| 目标状态 | 行为 |
|---|---|
| 不存在 | 按 I0–I8 初始化 |
| 存在且 Manifest 规范、身份合法、固定骨架完整 | 配置缺失时可连接；配置完整匹配时视为幂等重试，只重开验收，不重建 Store |
| 存在但为空 | 返回 `unrecognized_existing_directory`；MVP-0 不自动接管 |
| 存在且非空、无合法规范 Manifest | 返回 `unrecognized_existing_directory`；零写入、零清理 |
| Manifest schema/layout 版本未知 | 返回 `unsupported_store_version`，等待显式迁移方案 |
| Manifest 可识别但固定骨架缺失或类型错误 | 返回 `capture_store_not_initialized`；不得自动补目录或修复 |
| 配置 root 或阈值与请求不一致 | 返回 `config_store_conflict`，不得静默切换或覆盖；冲突检查先于目标创建 |

“固定骨架完整”只要求全部保留名称存在、类型正确并且不是 symlink、junction 或其他 reparse point，不要求目录为空。合法 Store 中额外的普通条目（例如以后独立批准的 `.git/`）不使 v1 身份失效，但 C2B 不读取、修改或删除这些额外条目。任何额外条目都不能替代缺失的固定目录。

### 6.4 失败与恢复

- I6 前失败：最终根目录不存在；只允许清理由规范事务标记和当前请求哈希共同确认归属的初始化目录。
- I6 后、I7 前失败：Store 已存在但尚未连接配置；重试读取合法 Manifest 后继续，不创建第二个 `store_id`。
- I7 后、I8 前失败：配置和 Store 可能都已提交；重试必须返回原 Store，而不是覆盖。
- 未知非空目录和旧生产 Store永不由初始化器自动删除。
- 初始化成功回执必须同时区分 `store_initialized` 与 `config_connected`。
- 锁必须在任何 Store 目标或 staging 创建前获得并覆盖到 I8；锁内所有判断都重新从磁盘读取，不能依赖锁前快照。
- 相同请求并发时只允许一个调用创建 Store；另一个等待后返回同一 `store_id` 且 `created=false`。
- 不同 root 对同一配置并发时，胜者完成后，失败方在创建自身目标前返回 `config_store_conflict`，不能留下孤儿 Store。
- 自动化测试证明的是受控进程故障后的磁盘恢复，不把 `flush` 和原子 rename 夸大为突然断电绝对不丢。

### 6.5 固定成功回执

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

该回执使用独立的 `InitStoreResult`，不复用 Capture 写入专用的 `CommittedWriteResult`，因此不得出现 `saved`、`commit_state`、Capture ID、版本号或 State Event。初始化失败继续使用统一 `OperationError`/`FailureResult`，且错误详情不得泄露受保护路径。

### 6.6 C2B 失败分类

配置文件不存在对普通“打开 Store”仍是 `config_not_found`，但对显式 `init_capture_store` 是允许的未连接状态，不作为失败。C2B 的固定分类如下：

| 条件 | 公共错误码 | `retryable` |
|---|---|---:|
| 已有配置的 YAML/schema/字段/阈值非法，或配置/Store 路径关系违反本节硬约束 | `config_invalid` | `false` |
| 已存在目标为空、无规范 Manifest，或不是可识别 Store | `unrecognized_existing_directory` | `false` |
| Manifest schema/layout 版本不受支持 | `unsupported_store_version` | `false` |
| Manifest 合法但固定骨架缺失、类型错误或被 reparse 对象替代 | `capture_store_not_initialized` | `false` |
| 已有配置与请求的 root 或任一阈值不同 | `config_store_conflict` | `false` |
| 初始化锁等待超时或已知临时共享冲突 | `capture_store_unavailable` | `true` |
| 权限拒绝、父目录/卷不可用、空间不足、flush/rename/回读失败或无法安全判断磁盘事实 | `capture_store_unavailable` | 默认 `false`；仅明确识别为临时共享冲突时为 `true` |

- C2B 不使用 `atomic_commit_failed`；该码保留给 C3 以后 Capture 版本提交。
- 初始化失败的 `FailureResult` 不携带 `saved` 或 `commit_state`。即使 I6 后已存在合法 Store，也通过同请求重试恢复和确认，不把 Capture 写入三态套到部署动作上。
- 错误 `details` 最多包含安全阶段名等枚举信息，不包含配置路径、Store 路径、事务目录名或底层异常文本。

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
| `locking.py` | C2 已实现配置目标初始化锁，C3 已实现 Store 级写锁；MVP-0 追加继续复用 Store 级写锁 | 提前引入细粒度 Item 锁 |
| `durability.py` | staging、flush、原子替换/rename | 远程备份 |
| `manifest.py` | Store 身份和布局版本 | 保存主机路径 |
| `store.py` | C2 只负责初始化、重开和布局校验；后续批次再增加扫描、投影重建原语 | UI、GBrain |
| `operations.py` | 四个操作的事务编排 | 任意文件系统访问接口 |
| `cli.py` | JSON 结果头、精确长度正文流和退出码 | 把正文放进命令行参数或 JSON |

Python import、包和机器契约名称使用英文，属于此前双语命名规则的机器接口例外；说明文档继续使用“英文名-中文名”。

## 8. 实现任务拆分

| ID | 任务 | 依赖 | 完成标准 |
|---|---|---|---|
| M0-D1 | 技术选择基线 | 无 | 已于 2026-09-02 确认，后续实现不得静默偏离 |
| M0-E1 | 建立隔离 Python 包和测试骨架 | M0-D1 | **已于 2026-09-02 通过：自动发现 1 项测试，包可从 `src/` 导入** |
| M0-E2 | 配置解析和路径安全 | E1 | **已于 2026-09-03 通过：受限读取、规范写出、绝对解析、禁止目录、Windows 特殊路径和越界测试通过** |
| M0-E3 | 错误模型、YAML codec 与 golden fixture | E1 | **已于 2026-09-02 通过：错误分层、受限 YAML、Envelope schema 与 golden 已实现** |
| M0-E4 | UUIDv7、时钟、四类哈希和字节计数 | E1 | **已于 2026-09-02 通过：固定向量、时钟回拨、流式字节计数与四类哈希通过** |
| M0-E5 | 锁与 durability 原语 | E1 | **已于 2026-09-03 通过：Windows 内核锁、同盘无覆盖 rename、flush 与目录能力分级通过** |
| M0-E6 | Manifest 与 `init_capture_store` | E2–E5 | **已于 2026-09-04 通过：Manifest、完整骨架、并发幂等、配置连接与六点崩溃恢复通过** |
| M0-D2 | C3 阻塞性行为冻结 | E2–E6 | **已确认：2026-09-08 冻结输入、完整 Item/Event 原子提交、投影、写锁、幂等及 actor/时间；2026-09-09 完成回执、输入省略归一化与目标碰撞结果收口** |
| M0-E7 | `capture_text` | M0-D2 | 版本 1、哈希、Envelope、原子创建 Event、投影和回执闭环 |
| M0-D3 | C4-0 读取契约冻结 | E3、E7 | **2026-09-13 已由独立本地提交闭合：冻结 Event 证明的连续可见版本、读取 sink、完整性深度、游标、时间/快照和 warning 归属；完成时未 push，现已随 `dc3a35f` 同步** |
| M0-D4 | R0.3D 初始化错误语义诊断 | E6、M0-D3 | **2026-09-13 已通过独立本地提交闭合：3 项特征测试复现 C-032–C-034，并冻结未知候选、错误优先级和 WinError 分类；完成时未 push，现已随 `dc3a35f` 同步** |
| M0-E6F | R0.3F 初始化错误语义修复 | M0-D4 | **2026-09-13 已完成并由独立本地提交闭合：按 C-032–C-034 完成局部修复，把 3 项特征测试转换为目标行为并新增 4 项负向回归；全量 163 项通过，完成时未 push，现已随 `dc3a35f` 同步** |
| M0-E8A | C4A 读取侧契约能力 | M0-E6F | **2026-09-13 已完成并由独立提交 `06cff02` 闭环、已 push：追加 Event schema、连续版本发现、请求/结果模型、游标 codec 与真实两版本 golden 闭环；182 项全绿且不公开读取操作** |
| M0-E8 | `get_capture`（C4B） | E7、E8A | **2026-09-13 已由独立提交 `666ba18` 闭合并 push：先完整验证、再经 Store 外有界磁盘 spool 向调用方 sink 输出；GET-01–GET-16 与当时 197 项全量通过** |
| M0-E9 | `list_captures`（C4C） | E7、E8A | **2026-09-13 已完成并由独立提交 `231ad09` 闭合且已 push：有界预览、稳定 keyset 游标、投影内存重建和 Global Intake 视图闭环；LIST-01–LIST-19 与 212 项全量通过** |
| M0-V0 | C4V 读取阶段验收 | E8、E9 | **2026-09-14 已完成并由独立提交 `1e38f2f` 闭合、已 push：GET/LIST 全矩阵、真实 4/64 MiB 公共读取闭环、静态分页和页间受控新增通过；当前全量 214 项** |
| M0-D5 | C5-0 追加写入契约冻结 | E4、E5、E7–E9、M0-D3 | **2026-09-14 已完成内容与本地验证并由独立提交 `ea530ad` 版本化，2026-09-16 已 push：冻结公开请求/回执、幂等优先于 CAS、唯一尾部窄续封、Event rename 三态证据、追加投影时间、独立 staging 所有权、错误优先级和 APP-01–APP-24** |
| M0-E10A | C5A 追加契约能力与写入基础 | M0-D5 | 请求/结果模型、版本/投影 schema 泛化、追加 Event writer、staging 与现场探测纯能力通过；不公开 append |
| M0-E10B | C5B 完整 `append_capture_version` | M0-E10A | 锁内幂等/CAS、版本先落盘、Event 逻辑提交、最终回读、投影和窄续封闭环 |
| M0-E10V | C5V 追加阶段验收 | M0-E10B | APP-01–APP-24、真实边界、双进程与三态证据全部通过 |
| M0-E11 | 投影/索引重建和恢复扫描 | E7–E10V | 删除派生投影后可由不可变记录重建 |
| M0-E12 | JSON/文本流 CLI 适配 | E6–E11 | stdin 使用 JSON 头 + 精确长度正文；stdout 使用 JSON 结果头 + `get_capture` 精确长度正文 |
| M0-V1 | 全故障注入和并发验证 | E6–E12 | 第 10 节全部自动化场景通过 |
| M0-V2 | 迁移演练 | E11、V1 | 临时 Store 复制—校验—切换后身份和哈希不变 |
| M0-V3 | Windows 人工耐久验收 | V1–V2 | 强制终止恢复通过；断电声明按实测校准 |
| M0-R1 | 实现审查和状态升级 | V1–V3 | 规范与实现一致后，才从 Approved Design 升为 Effective |

不得把 E7 的“能保存一次”当作 MVP 完成。E8–E11 和 V1–V3 是可恢复性承诺的一部分。

## 9. 四操作完成定义

### 9.1 `capture_text`

- 内联和流式入口共享同一事务实现。
- 完整 Item（版本 1、Envelope、Payload 与匹配的 `capture.created` Event）原子提交并从最终路径回读前不返回成功。
- 同幂等键重试返回同一 Item/Version/Event 和相同核心哈希；警告按当前投影事实生成，C3 不在命中路径静默重建投影。
- 创建 Event 在提交前失败时不产生可见 Item；只有提交后的 `capture.yaml` 投影失败返回成功加 repair warning。
- Store 级 Windows 内核写锁覆盖幂等扫描、完整 Item 提交、最终回读和投影尝试；锁文件存在不等于持锁。
- 核心固定可信 actor 与规范 UTC 毫秒时间；普通请求不能覆盖 actor，也不能提交非法渠道 token、BOM 或非法 UTF-8。
- 不生成标题、摘要、标签、KB 或 Delivery Request。

### 9.2 `get_capture`

- 指定版本严格读取，不存在时不降级为最新。
- latest 只取由唯一匹配版本建立 Event 证明的连续最高版本；目录、投影和修改时间都不能扩大可见范围。
- 每次公开正文前验证全链的版本/Event/Envelope/引用，并验证目标版本全部 Payload 的实际大小/SHA256 和 Payload Set 哈希；不借读取当前版本全量重哈希其他历史正文。
- 正文不进入结构化结果；先以不超过 1 MiB 的块写入 Store 外磁盘 spool，全部验证通过后才复制到调用方二进制 sink，64 MiB 正文不整体驻留内存。
- 任一 Store 错误使 sink 保持零字节；sink 自身失败返回 `output_write_failed`，调用方丢弃可能存在的已验证部分输出后重试。
- 投影缺失、损坏或落后时从不可变版本/Event 在内存中重建当前状态并发出带 Item 身份的警告。
- 唯一无 Event 的 N+1 尾部残留对 latest 不可见并产生警告；显式读取该版本为 `version_not_found`。其他缺口、重复/孤立 Event 或交叉引用矛盾 fail-closed。
- 不借读取动作静默修复或改写 Store。
- 读取成功/失败均不返回 `commit_state`。

### 9.3 `list_captures`

- 固定 `captured_at DESC, capture_id DESC`。
- `c1` keyset 游标以规范 JSON 绑定 Store、规范查询和末项排序键；checksum 只防误传/篡改，不承担认证，无 TTL。limit 不进入查询指纹，可在合法范围内跨页调整。
- 游标分页只在同一静态数据集上保证不重复、不漏项；不承诺跨页快照，并发变化后从空 cursor 重新扫描。
- preview 保留当前正文前 160 个 Unicode code point 的原字符和换行，只读有界 UTF-8 前缀，不写回文件，也不承诺 grapheme cluster 边界。
- 列表验证版本/Event/Envelope/结构和声明大小，不为每条大正文计算完整哈希；完整 Payload attestation 由 `get_capture` 承担。
- 投影不可信时以不可变 Event 在内存中重建状态后再筛选；Global Intake 只是该状态下 `routing_status=unassigned` 的过滤结果。
- 任一不可变矛盾使整个列表失败，不返回部分 items/cursor；唯一无 Event 的 N+1 尾部目录被忽略并产生归属到 Item/版本的警告。
- 时间筛选使用版本 1 `captured_at` 且边界严格排除；结果 `updated_at` 使用当前版本建立 Event 的 `occurred_at`。
- 不实现全文或语义搜索。
- 读取成功/失败均不返回 `commit_state`。

### 9.4 `append_capture_version`

- 公开 `AppendCaptureVersionRequest` 使用 `frozen + slots + kw_only`，包含 `capture_id`、`expected_current_version`、完整 `text`/二进制流、`channel`、必填 `idempotency_key` 和可省略 `user_intent`；省略意图归一化为全 `null`。
- `expected_current_version` 只接受整数 `1..999998`，`bool` 无效；v1 已到 `999999` 返回 `invalid_input`，不分配越界版本。
- 新增独立、精确字段的 `AppendCaptureVersionResult` 与 `AppendCaptureVersionOperationResult`；不放宽现有 `CommittedWriteResult` 的 capture_text 回执。
- 保存完整新 Payload，不保存补丁链；输入验证、安全上限、UTF-8/BOM 和有界 staging 复用 C3B 能力。
- 暂存使用独立内部类型和 `.staging/<tx>/version + events` 固定树；capture-transaction v1 marker 仅增加 append operation，按 operation 分流所有权允许树。部分 rename 后只清理本事务仍在 staging 的对象，marker 最后删除，最终尾部和未知 staging 永不删除；C3 布局/规范字节保持不变。
- 正文在锁外 staging 并生成 Request Fingerprint；Store 级 Windows 锁覆盖全 Store 不可变扫描、幂等判定、目标链/当前 Payload attestation、CAS、提交、最终回读和投影尝试。
- 锁内优先级固定为不可变完整性/版本支持 → 幂等命中或冲突 → `capture_not_found` → CAS `version_conflict` → 目标/写入证据。同 key 已提交命中优先于 CAS，即使 Item 后来已推进也返回原版本。
- 同一基线的不同 key 并发追加最多一个成功；同 key、同请求并发返回同一版本/Event，同 key、不同指纹返回 `idempotency_conflict`。
- 只有完全规范、全部 Payload 已验证、绑定当前 N 且幂等身份/指纹相同的唯一 N+1 无 Event 尾部可由同 key 续封；采用其既有版本、Event ID 和 Envelope，不生成 N+2。其他尾部不采用、不覆盖、不清理，留给 C6。
- 版本目录先无覆盖提交，匹配的 `capture.version-appended` Event 后无覆盖提交；Event 是 N>1 的唯一逻辑提交点。版本 rename 结果不明但 Event 被证明不存在时仍是 `not-committed`。
- Event rename 之后按 source/target 与最终规范字节、引用和 Payload attestation 区分 `not-committed | committed | unknown`；确定损坏为 `integrity_check_failed + unknown`，无法证明为 `atomic_commit_failed + unknown`。
- 追加 Event 复用同一严格 codec，同时绑定 N、N+1 及前后 Envelope 哈希；投影只能在 Event 提交并完成最终回读后推进，失败只产生成功 warning。
- state v1 的版本 1 分支保持 `updated_at == durability.verified_at` 与旧调用/golden；版本 >1 的 codec 必须取得当前 Event 和前一 Envelope，严格验证 `updated_at == Event.occurred_at`，验证时间独立采样。
- 旧版本、旧 Event、旧哈希和旧批准不变，新版本不继承批准；C5 不实现通用恢复、索引、路由、GBrain 或生产初始化。

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

实际结果（2026-09-02）：ERR-01–06、ID-01–03、HASH-01–04、YAML-01–04 已由 29 项 C1 单元/golden 测试覆盖并全部通过；加上 C0 smoke test，当时自动发现总计 30 项。该结果不覆盖第 10.1 节及以后任何 Store 行为。

### 10.1 配置和路径

| ID | 场景 | 预期 |
|---|---|---|
| CFG-01 | 默认本地配置不存在 | `config_not_found`，不扫描磁盘 |
| CFG-02 | 显式绝对测试配置 | 精确使用该配置 |
| CFG-03 | 普通相对配置路径 | 拒绝，不按 CWD 猜测 |
| CFG-04 | `capture.root` 位于源码仓库内 | 拒绝 |
| CFG-05 | root 位于 KB、GBrain 或系统临时目录 | 拒绝 |
| CFG-06 | `..`、UNC、设备路径、symlink/reparse 越界 | 规范化后拒绝，不能用字符串前缀误判 |
| CFG-07 | 未知配置字段、重复 YAML key 或错误 schema/version | 拒绝 |
| CFG-08 | 阈值为 0、负数或 inline > max | 拒绝 |
| CFG-09 | 安全且合 schema、但排版非规范的配置 | 允许读取；程序写出时与 `local-config-v1.yaml` golden 字节一致 |

### 10.2 Manifest

| ID | 场景 | 预期 |
|---|---|---|
| MAN-01 | 固定 Store 身份对象规范发射 | 与 `capture-store-v1.yaml` golden 的 UTF-8 字节完全一致 |
| MAN-02 | `store_id` 与 `created_at` | 只接受 `store_` + 合法 UUIDv7，以及规范 UTC `Z` 时间 |
| MAN-03 | 重复键、未知/缺失字段、错误类型 | 分别在语法门禁或 Manifest schema 校验拒绝 |
| MAN-04 | 未知 schema/schema version/layout version | 返回 `unsupported_store_version`，不尝试猜测或迁移 |
| MAN-05 | 语义安全但字节非规范的 Manifest | 拒绝作为 Store 身份，不自动重写 |
| MAN-06 | Manifest 字段审计 | 不含绝对路径、主机/用户、KB、GBrain 或可重建计数 |

实际结果（2026-09-03）：CFG-01–CFG-09 与 MAN-01–MAN-06 已由 18 项 C2A 单元/golden 测试覆盖并全部通过；加上 C0–C1 的 30 项，当时自动发现总计 48 项。实现没有写入配置或 Store，也没有创建锁、目录骨架、Capture 或外部请求；第 10.3 节初始化行为仍完全属于 C2B。

### 10.2A C2B 锁与 durability 原语

| ID | 场景 | 预期 |
|---|---|---|
| LOCK-01 | 两个进程竞争同一解析配置路径 | 任一时刻只有一个持锁；等待者只在前者释放后进入 |
| LOCK-02 | 两个不同配置路径 | 互不阻塞，证明竞争域不是全局锁 |
| LOCK-03 | 持锁子进程被强制结束，锁文件仍存在 | 内核锁自动释放；新进程可取得同一锁，不按文件存在判断陈旧锁 |
| LOCK-04 | 持锁超过等待上限 | 生产默认上限 10 秒；测试用内部注入快速验证 `capture_store_unavailable`、`retryable=true` |
| DUR-01 | 写 Manifest/配置临时文件 | 精确字节写入、flush、`fsync`、关闭回读和严格解析均发生，任一步失败不得继续提交 |
| DUR-02 | 同卷目录无覆盖 rename | 目标缺失时提交成功；目标已存在时零覆盖并转入已有目标分类 |
| DUR-03 | 初次配置连接期间目标意外出现 | 不覆盖；完全匹配则接受，否则 `config_store_conflict` |
| DUR-04 | 目录元数据 flush 支持/明确不支持 | 支持时执行并验证调用；不支持时记录平台限制，不宣称抗突然断电 |

实际结果（2026-09-03）：LOCK-01–04 与 DUR-01–04 已由 9 项 C2B-1 单元/多进程测试覆盖并全部通过；加上 C0–C2A 的 48 项，当时自动发现总计 57 项。Windows 强制终止、目标在无覆盖 rename 前后竞态、严格回读失败和目录 flush 三态均已实际验证；Windows 默认目录元数据 flush 明确记录为 `unsupported`，因此仍只承诺进程崩溃恢复。测试只写测试框架持有的系统临时目录，没有创建 `store.py`、结构上可识别的 Store、真实配置、Capture 或外部请求。

### 10.3 初始化

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
| INIT-10 | Manifest 可识别但固定骨架缺项/类型错误 | `capture_store_not_initialized`，零自动修复 |
| INIT-11 | 两个相同初始化请求并发 | 一个 `created=true`、另一个 `created=false`，两者返回同一 `store_id` |
| INIT-12 | 不同 root 并发竞争同一配置 | 胜者连接；失败方返回 `config_store_conflict`，其目标和 staging 均不存在 |
| INIT-13 | 已有配置的 root 相同但任一阈值不同 | `config_store_conflict`；配置与 Store 均零修改 |
| INIT-14 | 配置位于 Store 内、Store 父目录缺失，或配置需递归创建多层父目录 | `config_invalid`；不得为了取得锁而提前创建 Store 或任意祖先链 |
| INIT-15 | 合法 Store 含额外普通条目 | 可重开且 `created=false`；额外条目逐字节不变，不能代替固定骨架 |
| INIT-16 | 已知与未知初始化事务目录、配置临时文件并存 | 只处理规范标记/请求哈希匹配的目录及字节完全匹配的配置临时文件，其他对象逐字节不变 |
| INIT-17 | 自有初始化事务的内容清理失败 | 返回 `capture_store_unavailable`，保留 marker 与未删内容；同请求重试可以验证归属、完成清理并初始化 |
| INIT-18 | 同一父目录下不同配置目标并发连接同一 Store | 后发请求不得删除先发请求已写、仍在途的配置临时文件；两者最终连接同一 `store_id` |
| INIT-19 | 临时文件请求身份匹配但规范字节不符 | 视为未知候选并逐字节保留，不因名称匹配而删除或冒认 |

R0.3D 特征证据与 R0.3F 实现结果：

| ID | R0.3D 修复前事实 | R0.3F 实现结果 |
|---|---|---|
| R03D-01（M1） | 未知合法命名事务候选仅一次 `stat` 失败，会让已有合法 Store 的幂等重开返回不可重试 `capture_store_unavailable`、`stage=path-stat`；既有 INIT-17 证明 `unlink` 原生错误仍能到达清理 handler | 未证明 marker/request 归属前的根或 marker `stat` 失败均保守跳过且不删除；已证明自有后的遍历/stat/unlink/rmdir 失败保留 marker、返回稳定 `transaction-cleanup` 并失败关闭 |
| R03D-02（M3） | 原始 `file-readback` 失败后的清理身份失败，会把公共 `stage` 覆盖为 `transaction-cleanup-identity` | Store 事务和配置临时文件两条路径均保持原错误的 `code/cause_code/retryable/stage`，次级清理阶段只进入安全 `details.cleanup_stage`；清理是唯一错误时仍作为主 stage |
| R03D-03（M4） | WinError 32/33/5 与仅 `errno.EACCES` 在 durability 映射中都不可重试 | 默认不可重试，仅直接原因 32/33 为可重试；5、999、仅 EACCES、无原因和校验失败保持不可重试，锁等待分类未外推 |

实际结果（2026-09-03）：INIT-01–16 已由 16 项初始化集成测试逐项覆盖并全部通过，另增加 3 项配置路径边界及 Windows 可信解析结果回归测试；加上 C0–C2B-1 的 57 项，当时自动发现总计 76 项。同请求并发与异 root 竞争分别额外连续复跑 100 次和 50 次，均保持单一身份、无覆盖和无孤儿目标。实现只在测试持有根内创建 Store、配置、锁和事务对象，当时尚未加入故障注入点，也未创建真实配置或生产 Store，未产生 Capture、State Event、outbox job、网络请求或 GBrain 调用。全量测试在 `ResourceWarning` 严格模式通过，`compileall`、依赖完整性和 `git diff --check` 同时通过。这是 C2B-2 停在 C2B-3 授权门禁时的历史验收记录；C2B-3 后续结果以编码执行方案的实际验收记录为准。

### 10.4 `capture_text`

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
| CT-11 | 同 key 同请求重试 | 返回同一 Item/Version/Event 和相同核心哈希；投影有效时警告为空 |
| CT-12 | 同 key 不同请求 | `idempotency_conflict` |
| CT-13 | GBrain、网络完全不可用 | 本地保存不受影响 |
| CT-14 | `str` 与不可 seek 的二进制流输入同一正文 | 共享同一有界事务实现；Payload 与四类核心哈希一致 |
| CT-15 | UTF-8 BOM、字符串首字符 `U+FEFF` 或非法 UTF-8 | `invalid_input`；不静默删除或替换，无可见 Item |
| CT-16 | 非法渠道 token、越界 external ref/key、非规范来源时间或调用方 actor | 机械拒绝；核心 actor 固定为 `user/local-user`，时间为规范 UTC 毫秒格式 |
| CT-17 | 两个进程以同 key、同请求并发 | 最多一个 Item；两者得到相同已提交身份、版本和哈希字段 |
| CT-18 | Store 写锁等待超过 10 秒 | 可重试 `capture_store_unavailable`，`commit_state: not-committed` |
| CT-19 | 分配新 ID 后最终 `<capture-id>` 目标已存在 | 不覆盖、不冒认既有 Item；可重试 `atomic_commit_failed`，`commit_state: not-committed` |
| CT-20 | 正常创建完成 | 最终完整 Item 同时包含可回读、哈希与交叉引用正确的版本 1 和 `capture.created` |
| CT-21 | Event 写入、schema 或交叉引用在 rename 前失败 | 不提交 Item，不返回成功 |
| CT-22 | Item 已提交后 `capture.yaml` 投影失败 | 返回成功及 `projection_needs_rebuild`；同 key 重试保持原身份/哈希并继续警告，不静默重建投影；不可变版本/Event 不变 |
| CT-23 | rename 边界发生无法证明结果的 I/O 异常 | `commit_state: unknown`；不猜测成功或失败 |
| CT-24 | 自有 staging 与未知 staging 并存后失败/重试 | 只清理可验证归属于本事务且未提交的 staging，未知对象逐字节不变 |

### 10.5 `get_capture`

| ID | 场景 | 预期 |
|---|---|---|
| GET-01 | 不传版本 | 返回最高连续且由 Event 证明的已提交版本，不按最高目录或投影选择 |
| GET-02 | 指定历史版本 | 返回指定正文和当前版本号 |
| GET-03 | Item 不存在 | `capture_not_found` |
| GET-04 | 版本不存在 | `version_not_found`，不回退 |
| GET-05 | 任一 Payload 被篡改、大小或 Payload Set 不符 | `integrity_check_failed`，sink 零字节，不返回 verified |
| GET-06 | Envelope 被篡改 | `integrity_check_failed` |
| GET-07 | `capture.yaml` 缺失 | 从不可变记录读取并警告，不静默写回 |
| GET-08 | 合法两版本 fixture | latest 返回版本 2；历史版本 1 不变；当前状态与所读版本不混淆 |
| GET-09 | 唯一 N+1 目录缺追加 Event | latest 返回 N 并给出带 capture/version 的 `incomplete_version_ignored`；显式 N+1 为 `version_not_found`，sink 零字节 |
| GET-10 | Event 存在但版本/Envelope/Payload/前后哈希不匹配 | `integrity_check_failed`，不回退到 N |
| GET-11 | 版本缺口、重复/孤立版本 Event 或多个尾部残留 | `integrity_check_failed` |
| GET-12 | 不支持的机器 schema/schema version | `unsupported_store_version`；已知 schema 非法仍为完整性错误 |
| GET-13 | 64 MiB 正文 | 验证和输出块均不超过 1 MiB，正文不整体驻留内存，sink 字节精确 |
| GET-14 | sink 异常、零/非法返回或合法短写 | 短写正确续传；其余为 `output_write_failed`、固定消息、可重试且无 `commit_state`，调用方丢弃部分输出；核心不 close/flush sink |
| GET-15 | Item 分片不符、重复 capture ID、reparse/越界路径 | fail-closed，不任选一个 Item 或越界读取 |
| GET-16 | 所有成功/Store 失败结果 | `body_length_bytes` 与输出精确一致；正文不嵌入结果；无 `commit_state` |

### 10.6 `list_captures`

| ID | 场景 | 预期 |
|---|---|---|
| LIST-01 | 空 Store | 空 items、无错误 |
| LIST-02 | 多 Item 相同时间 | 用 `capture_id` 稳定打破平局 |
| LIST-03 | 多页遍历 | 无重复、无漏项 |
| LIST-04 | 非法游标 | `invalid_input`，不猜测位置；游标本身没有 TTL |
| LIST-05 | `routing_status=unassigned` | 结果即 Global Intake 视图 |
| LIST-06 | emoji/组合字符/换行预览 | 精确前 160 code point，保留换行；不承诺 grapheme 边界，不破坏原文 |
| LIST-07 | `limit` 为 0、>100、bool 或非整数 | 返回 `invalid_input`，不静默钳制 |
| LIST-08 | 投影损坏 | 返回可解释警告，不能把 Item 当成丢失 |
| LIST-09 | 游标用于另一 Store 或不同过滤条件 | `invalid_input`；不能跨 Store/查询复用 |
| LIST-10 | 同查询下一页改变合法 limit | 接受并保持 keyset 边界，无重复 |
| LIST-11 | 时间边界与 after>=before | after/before 严格排除；非法区间为 `invalid_input` |
| LIST-12 | 两版本 Item | `captured_at` 来自 v1，`updated_at`/当前哈希来自版本 2 的匹配 Event |
| LIST-13 | 唯一 N+1 目录缺 Event | 列出 N，并给出带 capture/version 的 `incomplete_version_ignored` |
| LIST-14 | 任一 Item 有 Event/版本/Envelope 矛盾 | 整个请求 `integrity_check_failed`，无部分 items/cursor |
| LIST-15 | 大 Payload 前缀后的等长篡改 | 列表不声称完整 attestation；`get_capture` 必须发现完整哈希失败 |
| LIST-16 | 64 MiB 当前正文 | 仅读取生成 160 code point 所需的有界前缀，不全量哈希或整体入内存 |
| LIST-17 | 投影缺失/落后且带 routing filter | 先从不可变事件内存重建再筛选，警告带 `capture_id`，不写回 |
| LIST-18 | 多 Item warning | 按 capture_id/code/version 确定排序；读取结果无 `commit_state` |
| LIST-19 | 静态分页期间并发创建/状态变化 | 不声称快照一致；从空 cursor 重启可获得新鲜视图 |

`LIST-07` 已选定“拒绝”而不是“钳制”：返回 `invalid_input`，让调用错误可见。

### 10.7 `append_capture_version`

| ID | 场景 | 预期 |
|---|---|---|
| APP-01 | 构造公开请求 | 精确字段、关键字调用、frozen/slots；坏 ID、缺 key、空 key、`bool` expected 和 expected 0/999999 均拒绝 |
| APP-02 | `str` 与非 seekable 二进制流进入 append staging | 严格 UTF-8、无 BOM、原字符/字节不改写，单块不超过 1 MiB；marker 先写且固定树/operation 正确，C3 marker 与清理回归不变 |
| APP-03 | 省略意图与显式全 `null` | 归一化对象、scope、key 摘要和 Request Fingerprint 完全相同；golden 精确匹配 |
| APP-04 | expected=N 且当前为 N | 生成完整 N+1、严格追加 Event、版本 N+1 投影和精确成功回执；投影 updated/verified 时间语义符合 C-041 |
| APP-05 | stale expected | `version_conflict + not-committed`，带安全 current/expected，零新最终 Event/可见版本 |
| APP-06 | 不同 key、两个进程同时 expected=N | 恰好一个提交 N+1，另一个版本冲突，无 N+2/重复 Event |
| APP-07 | 同 key、同请求两个进程竞争 | 两者返回同一 N+1/Event/哈希，只有一组最终原件 |
| APP-08 | 成功后同 key 重试且 Item 已被其他 key 推进 | 仍返回原 N+1 稳定回执，不误报版本冲突、不生成更高版本 |
| APP-09 | 同 key、不同正文/渠道/意图/capture/expected | `idempotency_conflict`，且优先于 `capture_not_found`/`version_conflict` |
| APP-10 | 规范但不存在的 capture ID | `capture_not_found + not-committed`，无 ID 分配或最终残片 |
| APP-11 | 新正文与旧正文逐字相同 | 不按内容去重；新 key 的主动追加仍生成 N+1 |
| APP-12 | 旧版本已有批准或意图 | 旧字节/哈希/批准不变；新版本不继承批准或未明确意图 |
| APP-13 | 当前基线 Payload 等长篡改 | CAS 前 `integrity_check_failed`，不写新最终对象 |
| APP-14 | 全 Store 扫描遇到坏已提交机器字节、未知 schema/version，或尾部身份读取 I/O 不明 | 前两者分别失败关闭为完整性错误或 `unsupported_store_version`；尾部已知部分字节不保留 key，I/O 无法判定身份则 `capture_store_unavailable + not-committed`，均不得误作已提交 key 未命中 |
| APP-15 | 唯一 N+1 尾部与本请求身份/指纹完全一致 | 全量验证后采用既有版本/Event ID/Envelope，只续封 Event，不生成 N+2 |
| APP-16 | 唯一尾部使用其他/缺失幂等身份或无法完全证明 | `atomic_commit_failed + not-committed`、`stage=version-target-conflict`；不采用、不覆盖、不删除；同身份不同指纹仍由 APP-09 处理 |
| APP-17 | 多尾部、版本缺口或 Event 引用矛盾 | `integrity_check_failed`，不回退或自动清理 |
| APP-18 | 版本 rename 抛错或现场不明，但 Event 目标确定不存在；同时存在未知 staging | `atomic_commit_failed + not-committed`；最终尾部保持不可见且不被本事务清理，未知 staging 逐字节不变 |
| APP-19 | Event 目标在首次逻辑提交尝试前冲突 | 不覆盖、不冒认；可证明未提交时为 `atomic_commit_failed + not-committed` |
| APP-20 | Event rename 分别形成 source 存在/target 不存在、source 消失/target 精确匹配、现场不可判定 | 依次为 `not-committed`、继续 `committed`、`unknown` |
| APP-21 | Event 已出现且最终回读确定损坏或只因 I/O 无法证明 | 分别为 `integrity_check_failed + unknown`、`atomic_commit_failed + unknown`，绝不返回成功 |
| APP-22 | Event/Version 最终有效而投影更新失败 | `ok=true + saved=true + committed`，warning 为 `projection_needs_rebuild` |
| APP-23 | 成功回执字段、值域及同 key 动态 warning | 追加类型精确；稳定字段不变，warning 反映当前投影/尾部且不触发修复 |
| APP-24 | 真实 4 MiB/64 MiB 追加后经 C4 list/get 读取新旧版本 | 新版字节/哈希精确、有界 I/O；旧版不变；唯一未完成尾部仍按 C4 规则隐藏 |

### 10.8 恢复和迁移

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

这里的 `after_init_temp_created` 指第 6.2.2 节事务目录、规范 `transaction.yaml` 和 `store/` 子目录均已完成 flush/回读之后；测试钩子仍保持内部注入，不进入配置、CLI 或公开 API。`before_config_replaced` 保留为故障点名称，但 C2B 的初次连接实际采用无覆盖原子提交，不授权覆盖既有配置。

C2B 必须逐点注入并在新进程中验证：

| ID | 故障点 | 重试后的磁盘事实 |
|---|---|---|
| FI-01 | `after_init_temp_created` | 最终 root 不存在；只识别并清理由规范标记和当前请求哈希共同确认的初始化目录，再安全重试 |
| FI-02 | `after_manifest_written` | 不信任未 flush 的临时内容；最终 root 不存在，未知残片不删除 |
| FI-03 | `after_manifest_flushed` | 最终 root 不存在；可以清理已验证归属的 staging 后重新初始化 |
| FI-04 | `after_root_renamed` | 重用最终 Store 的原 `store_id` 并补做配置连接，不生成第二个最终身份 |
| FI-05 | `before_config_replaced` | 重用原 Store；只处理可验证归属的配置临时文件，随后完成原子连接 |
| FI-06 | `after_config_replaced` | 配置和 Store 已提交；重试返回同一 `store_id`、`created=false`，不重写正文或创建业务记录 |
| FI-07 | `after_owned_transaction_content_removed` | 自有内容已删除但 marker 仍在；新进程可仅凭剩余规范 marker 完成清理并安全重试，未知残片保持不变 |

每个初始化故障测试还必须证明：真实默认配置和生产 root 的测试前后快照一致、没有 Capture/事件/outbox job、没有冲突请求遗留的孤儿 root，并且初始化结果从不使用 `saved`/`commit_state`。

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

# append 专用边界（只允许内部测试依赖注入）
before_append_version_rename
after_append_version_rename
before_append_event_rename
after_append_event_rename
after_append_final_readback
before_append_projection_replace
before_append_receipt_returned
```

每个捕获/追加故障点至少验证：

- 是否存在最终版本。
- 是否允许同 key 安全重试。
- 是否产生重复 Item/Version/Event。
- 是否有不完整目录被误认为成功。
- 回执中的 `saved` 是否与磁盘事实一致。
- 追加 Event rename 抛错后，分别伪造“source 仍在且 target 不在”“source 已消失且 target 精确匹配”“source/target 无法可靠读取”“target 确定损坏”四类现场，验证 APP-20/APP-21 的三态和错误码。
- 版本 rename 后、Event 前的所有现场都不得让 C4 读取 N+1；同 key 只接管 APP-15 的完全匹配尾部，任何其他尾部均保持原样。

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
| C0–C2A：工程骨架、配置、路径、YAML codec、ID/哈希 | 2–3 天 |
| C2B：初始化锁、durability、Store 初始化与六点恢复 | 2–3 天 |
| 四个操作 | 2–3 天 |
| 并发、故障注入、恢复和迁移测试 | 2.5–4 天 |
| CLI 适配、说明和最终审查 | 1–1.5 天 |
| **合计** | **约 10–15 天** |

这是“满足已承诺可靠性”的估计，不是只做一次成功演示的估计。2026-09-03 的 C2B 编码前复核把操作系统锁、可验证事务残片、无覆盖配置连接和 LOCK/DUR 验收纳入原承诺，因此将整体规划从 9–14 天校准为约 10–15 天；这不增加产品功能范围。若只实现 happy path，可能 2–4 天，但不能安全地称为 KnowledgeFlow MVP-0。

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
| G0.5 编码方案 | **C0–C4V 与 C5-0 已逐批通过、版本化并 push；最小 Windows CI 已建立且首次远端运行通过，下一功能门禁为 C5A** | C5A 及后续未授权批次的业务代码和真实 Store |
| G1 测试骨架与基础原语 | **已于 2026-09-02 通过：自动发现并通过 30 项测试** | 实现 Store 或四操作 |
| G2A 配置与身份 | **已于 2026-09-03 通过：CFG/MAN 全绿，自动发现总计 48 项测试** | 创建任何 Store 或初始化锁 |
| G2B 初始化 | **已于 2026-09-04 通过：LOCK/DUR/INIT/FI 全绿，自动发现总计 85 项测试** | 使用真实生产 root |
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
| I-009 | 采用完整可靠性范围；2026-09-03 C2B 复核后预算按约 10–15 天评估 | 2–4 天 happy path 不满足恢复、并发和审计承诺 |

以上选择已确认，本文保持 `Approved Design`。C0–C2 里程碑为 85 项测试，稳定化后为 93 项；C3A 契约能力与 C3B 写入基础分别以 `346164d`、`8050d88` 完成，C3C 完成公开 `capture_text` 事务，C3V 完成独立阶段验收时全量为 144 项；R0.1/R0.2 初始化所有权加固后为 148 项，D0G 后为 156 项，R0.3D 后为 159 项，R0.3F 后为 163 项，C4A 后为 182 项，C4B 后为 197 项，C4C 后为 212 项，C4V 后当前为 214 项。安全 Store 初始化、初始化崩溃恢复、C3 `capture_text`、C4B `get_capture`、C4C `list_captures` 及 C4V 读取阶段验收均已实现或验收并独立版本化。C4V `1e38f2f`、C5-0 `ea530ad` 与最小 Windows CI `c4d2c7b` 均已 push，首次远端 CI 已通过；下一功能门禁为 C5A，仍需另行明确授权。追加和业务事务恢复尚未实现。真实 `E:\KnowledgeFlowData\capture-store` 仍只有在用户另行明确要求“初始化生产 Capture Store”后才允许创建。
