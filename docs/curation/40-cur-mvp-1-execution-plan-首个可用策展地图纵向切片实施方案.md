# CUR-MVP-1：首个可用策展地图纵向切片实施方案

> 状态：Approved Implementation Plan（项目所有者已授权 `CUR1A/CUR1B/CUR1C`；`CUR1D/CUR1V` 仍逐批授权；不预授权模型调用、外部传输、生产知识库写入或生产配置）<br>
> 形成日期：2026-10-18<br>
> CUR1A 授权日期：2026-10-18<br>
> CUR1B 授权日期：2026-10-18<br>
> CUR1B 远端门禁闭合日期：2026-10-19（CI 可移植性修复 `b8525b9`；Windows CI #17 成功）<br>
> CUR1C 授权与本地实现日期：2026-10-19（独立版本化与可选远端门禁尚待闭合）<br>
> 产品里程碑：一份精确本地材料形成可查看、可回证、可修改、可在地图处结束的策展地图<br>
> 上位约束：[主产品需求文档](../requirements-and-governance-baseline-需求与治理基线.md)、[设计权威与冲突登记](../design-authority-and-conflict-register-设计权威与冲突登记.md)、[EVIDENCE-0 实验协议](../evidence-first-experiment-protocol-Evidence优先实验协议.md)<br>
> 执行契约候选：[捕获与路由规范](../capture/capture-and-routing-spec-捕获与路由规范.md)、[SOP-10 新建知识库骨架](10-sop-new-kb-bootstrap-新建知识库骨架.md)、[SOP-20 材料深度理解与策展地图](20-sop-deep-curation-map-材料深度理解与策展地图.md)

## 1. 本计划解决什么问题

现有文档已经回答“产品为什么需要深入策展”“三个权限怎样分开”“地图和可信知识有什么区别”，但还没有把这些候选契约压缩成一组可以逐批编码、测试、复核和停止的工作单元。

本计划只解决这一缺口。它不再扩写长期架构，也不把分段、范围和 Evidence locator 单独包装成新的产品阶段。它把必要机械能力放回同一条用户可见纵向链：

```text
选择本地 UTF-8 文件
  → 形成精确 Capture 版本
  → 展示目标建议，用户确认新库或明确暂不选库
  → 选择新库时建立一个隔离 provisional KB，并校验 raw/ 原料副本
  → 显示全文结构、实际处理范围、延期范围和缺口
  → 生成带精确证据的策展地图
  → 用户查看证据、修改结果，并选择“保存地图后结束”
```

只有最后一项能够由用户实际完成，`CUR-MVP-1` 才算完成。前面的机械批次可以独立提交和复核，但都不能单独升级为“产品里程碑已完成”。

## 2. 完成定义

`CUR-MVP-1` 必须同时证明以下结果：

1. **来源精确**：活动文件经严格 UTF-8 校验后，通过现有公共 Capture 操作成为实验 Store 中的精确版本；原文件身份、Capture ID/版本、Payload 哈希和字节数能够互证，不修改 Capture v1 schema。
2. **权限分开**：系统分别记录目标归属授权和深度处理授权；本切片不请求、也不产生可信知识写入批准。
3. **目标可选**：主旅程使用一个全新隔离 provisional KB；受控分支证明用户暂不选库时不会创建 KB、不会写 `raw/`、不会伪造 Route Record。
4. **原料可核验**：选择新库后，目标 `raw/text/` 中的文件与 Capture Payload 同字节，来源映射、Route Record 和本地版本检查点一致。
5. **范围可见**：完整来源的字节范围都被记为已处理、延期、失败或缺口之一；机械结构覆盖全文，语义处理不能通过只截取开头冒充全文。
6. **证据可回读**：每个具体主张、争议、限制或关系能够打开精确 Capture 版本中的 UTF-8 字节范围；错版本、越界、切断多字节字符或哈希不符时明确失败。
7. **地图可使用**：用户能阅读概览、结构、概念、主张、争议、限制和缺口，能区分原文内容、处理器归纳、用户修改和未核实项。
8. **地图可修改**：接受、拒绝、延期只形成决定记录；改变候选含义时形成新地图版本，不覆盖旧版，也不静默复用旧候选身份。
9. **地图可独立结束**：用户保存地图并结束后不产生 `wiki/` 正文、不改变 KB 的可信可见性，也不自动进入 SOP-30。
10. **实验结论受限**：记录首次有用结果时间、人工复核负担、证据问题、范围缺口、处理器调用和成本；一次成功不外推为任意领域或任意规模已有效。

## 3. 本轮冻结输入与运行边界

### 3.1 两份活动材料

| ID | 精确身份 | 本轮用途 | 外推限制 |
|---|---|---|---|
| `E0-F` | 提交 `11b4722` 中 Git blob `ec5c67086e10817cc92eed62d1c9ee088a06c600`，17,327 bytes | 身份、分段、范围、locator、回读、双跑和无目标分支夹具 | 项目自有且答案已暴露，不证明语义价值 |
| `E0-C` | `大模型应用开发核心解决的是什么问题.md`，1,184,815 bytes，`sha256:32a640a72483a513885e8c035da76d3c84b0796c30cd087dc84fbc4992179f66` | 新库主旅程和真实长文策展价值验证 | 只代表这一份低敏感度历史对话材料 |

2026-10-18 的只读预检再次确认：`E0-F` blob 可从本地 Git 对象库读取且大小匹配；`E0-C` 原件大小和 SHA-256 与登记值匹配。

运行时不得把仓库工作树中的“最新版概念导读”替代 `E0-F` 冻结 blob，也不得在哈希不匹配时自动把另一份同名文件当成 `E0-C`。产品实现不得硬编码 `E:`、用户名、盘符或上述原件路径；绝对路径只进入当次获准的实验清单和本机回执。

### 3.2 隔离位置

本轮只使用一次性、显式配置的实验根，根内至少分开：

```text
<experiment-root>/
├── capture-config.yaml  # 只连接本实验 Store 的本地配置
├── capture-store/       # 全新实验 Store，只含 E0-F/E0-C 的获准副本
├── curation-work/       # 无目标地图、机械派生物和运行记录
├── kb-root/             # 最多一个新建 provisional KB
└── reports/             # 测量、人工核查与验收报告
```

这些目录不能位于 Pilot Store、Pilot 备份、恢复副本或任何既有 active KB 内。默认采用测试临时目录或用户明确选择的实验目录；不创建生产 Capture Store，不使用 `E:\KnowledgeFlowData\capture-store`，也不要求异盘、BitLocker、GitHub 或网络。

### 3.3 三项权限

| 权限 | 本轮如何取得 | 能做什么 | 不能推导出什么 |
|---|---|---|---|
| 来源保存 | 项目所有者批准把两份精确材料复制到实验 Store | 建立 Capture v1 | 不等于可以深度处理或归属某 KB |
| 深度处理 | 单独记录处理范围、任务、处理器和预算 | 建立 T1/T2 地图 | 不等于可以写可信 Wiki |
| 目标归属 | 用户确认“一个新 KB”或“暂不选库” | 新库分支可复制到 `raw/`；无目标分支只写工作根 | 不等于深度处理或可信写入批准 |

可信知识写入批准不属于 `CUR-MVP-1`，只有后续 `CUR-MVP-2` 才可能请求。

## 4. 最小实现形态

### 4.1 包和入口边界

保持 `knowledgeflow_capture` 的已实现四操作、Store schema 和 Tk 收件箱不变。新增同级、受限的 `knowledgeflow_curation` 包承接实验能力，避免把地图状态塞进 Capture 内核。预计职责如下，精确文件拆分可以在不改变职责的前提下微调：

| 组件 | 最小职责 |
|---|---|
| `contracts` | 运行、来源映射、Segment、范围账、locator、目标决定、地图和回执的受限值对象与安全 YAML/JSON 校验 |
| `source` | 从明确白名单文件读取严格 UTF-8 bytes，调用公共 Capture API，并记录外部文件与 Capture 版本的实验映射 |
| `segmentation` | 按冻结实验 Profile 生成覆盖全文的确定性区段；不承担语义判断 |
| `evidence` | 校验 Capture/版本/Payload/范围/片段哈希并回读证据 |
| `kb` | 仅创建一个 `managed-local` provisional KB；不接管已有仓库 |
| `routing` | 在确认目标后执行复制—校验—记录到 `raw/text/`；无目标时不运行 |
| `processor` | 定义可替换的语义处理边界；核心不绑定供应商、账号或网络 |
| `maps` | 校验候选、生成同事实的 `map.yaml + map.md`、发布新版本与决定记录 |
| `cli` | 提供首轮受限操作入口和机器可读回执，不扩成通用搜索或完整工作台 |

`pyproject.toml` 只需把新包和一个受限 `knowledgeflow-curation` 入口纳入构建。首轮不引入数据库、向量库、图数据库、后台服务、Web 前端或模型厂商 SDK。

### 4.2 实验分段 Profile

首个实现只提供组合身份 `profile_id=experiment-markdown-blocks + revision=1`（下文简称 `experiment-markdown-blocks-v1`），明确标记为可废弃的实验选择，不冻结为永久产品策略：

1. 严格按原始 UTF-8 bytes 工作，不规范化换行、不重写 Unicode。
2. 原始 Segment 层无重叠，所有 bytes 恰好归属一个有序 Segment；空行、标题分隔、表格、代码块和消息标记不能被静默丢弃。
3. 优先在 Markdown 标题前、空行后、完整行末建立边界；超长行只在合法 UTF-8 字符边界切分。
4. 实验初值采用 16 KiB 目标大小、32 KiB 硬上限；Profile ID、数值和算法修订进入运行记录。真实运行后可以废弃或调整，不能据此宣称适用于所有材料。
5. `segment_id` 绑定精确 Capture/版本、Payload 哈希、半开字节区间、片段哈希和 Profile 修订；显示行号只作导航。
6. 后续语义批次可以组合多个 Segment 或形成有重叠的处理窗口，但范围账必须单独记录重复 bytes，不能把重叠算成额外覆盖。

### 4.3 全文结构与语义预算分层

`E0-C` 的 1.18 MB 原文不要求一次调用或一次上下文全部送给模型。首轮地图分成两层：

- **零模型机械层**：覆盖全文的标题/消息/区段结构、字节范围、状态和缺口，必须完整；
- **获准语义层**：只处理运行前批准的 Segment/窗口，形成概览、主题、主张、争议和限制；未处理范围继续在地图中可见。

如果获准预算不足以支持全文语义处理，必须在运行前缩小语义范围或采用分层批次，并在地图中明确显示延期范围。不得静默截取开头、把机械覆盖率冒充语义覆盖率，或凭输入字节数虚构 token/费用。

### 4.4 首个语义处理器边界

核心先实现一个供应商无关的文件交换端口和一个确定性测试处理器：

1. KnowledgeFlow 生成绑定运行 ID、来源哈希、获准范围、任务、输出约束和预算的处理请求包。
2. 外部或本地处理器返回受限候选包；候选只能引用请求包允许的 Segment/locator。
3. KnowledgeFlow 重新校验所有范围、证据、来源属性、不确定性和输出上限，再决定是否发布地图。
4. 测试处理器只用于契约、失败和复现测试，不能证明真实语义价值。
5. `E0-C` 的真实处理器、是否联网、模型身份、数据发送范围、调用次数、token 和费用上限必须在语义批次前另行确认；本计划不预授权任何外部传输。

这种边界使 Capture、范围、证据、地图保存和本地版本历史在断网时仍可工作，同时允许以后替换成本地模型或不同服务，不把首轮实验绑定到单一账号。

### 4.5 最小用户入口

首轮使用“受限命令入口 + 可直接阅读的 `map.md` + 精确证据打开命令”，不扩建完整 Tk/Obsidian 式工作台。至少支持以下用户任务：

- 准备一个精确来源并查看身份；
- 查看目标建议，确认一个新 KB 或选择暂不选库；
- 查看全文范围与当前缺口；
- 生成并打开地图；
- 按候选打开证据；
- 接受、拒绝、延期或用替代文本修改候选；
- 保存新地图/决定版本；
- 保存地图并结束。

命令任务名在 `CUR1A` 固定；每个命令的首个可执行批次再固定其最小参数，避免为尚未实现的后续能力预设伪接口。无论采用交互式提示还是显式参数，都必须提供结构化回执和单一可执行的修正提示。只有生成机械诊断文件而没有上述查看、修改和结束入口，不算完成。

`CUR1A` 冻结以下用户任务名称和未来 CLI 拼写，但不暴露“尚未实现却返回成功”的空壳命令。对应子命令只在表中所列批次实现后进入可执行入口：

| 用户任务 | 操作身份 / CLI 拼写 | 首次实现批次 |
|---|---|---|
| 准备精确来源 | `source.prepare` / `knowledgeflow-curation source prepare` | `CUR1B` |
| 查看来源、区段与范围 | `source.inspect` / `knowledgeflow-curation source inspect` | `CUR1B` |
| 打开精确证据 | `evidence.show` / `knowledgeflow-curation evidence show` | `CUR1B` |
| 确认新库或暂不选库 | `target.decide` / `knowledgeflow-curation target decide` | `CUR1C` |
| 生成地图 | `map.build` / `knowledgeflow-curation map build` | `CUR1D` |
| 接受、拒绝、延期或修改候选 | `map.decide` / `knowledgeflow-curation map decide` | `CUR1D` |
| 保存地图并结束 | `map.close` / `knowledgeflow-curation map close` | `CUR1D` |

全部命令最终只输出一个 UTF-8 JSON 回执；失败沿用 `knowledgeflow_curation` 的稳定错误码和 `not-committed / unknown` 提交状态。`unknown` 不得伪报 `saved: false`，成功状态也不能仅凭文件存在推断。首个可执行子命令进入 `CUR1B` 时再把 `knowledgeflow-curation` 注册到 `pyproject.toml`，CUR1A 不安装误导性的占位 CLI。

`CUR1B` 固定的首组显式参数如下；所有路径由用户在本机运行时给出，产品代码不保存原件绝对路径，也不提供默认生产 Store：

```text
knowledgeflow-curation --experiment-root <绝对路径> source prepare
  --source <绝对 UTF-8 文件路径>
  --source-reference <安全来源代号>
  --expected-sha256 <sha256:...>
  --expected-bytes <正整数>
  --request-id <幂等请求代号>
  --authorized-by <授权者代号>
  --task-id <任务代号> [--task-id <任务代号> ...]
  [--budget-id <预算代号>]
  [--authorized-start-byte N --authorized-end-byte N]
  [--declared-start-byte N --declared-end-byte N]

knowledgeflow-curation --experiment-root <绝对路径> source inspect
  --request-id <已准备请求代号>

knowledgeflow-curation --experiment-root <绝对路径> evidence show
  --request-id <已准备请求代号>
  --locator-id <source inspect 返回的 loc_...>
  --output <尚不存在的绝对输出路径>
```

`source prepare` 的提交点是完整工作包的无覆盖原子发布；Capture 已提交但工作包状态无法确认时返回 `unknown/recovery_required`，不得伪报未保存。`source inspect` 只返回身份、范围和计数，不返回正文。`evidence show` 在核对精确 Capture 版本、Envelope/Payload 身份、UTF-8 范围和片段摘要后才写输出，并拒绝覆盖已有文件。失败 CLI 回执额外只给一个 `next_action` 机器动作，不输出原文或本机绝对路径。

## 5. 分批实施与独立停点

### `CUR1-0`：计划、合同适用范围与授权（当前批次）

只完成：

- 本实施方案；
- 文档索引、主题权威和项目状态中的计划入口；
- 两份输入的只读身份复核；
- 明确下一次授权对象是 `CUR1A`，而不是模糊的“继续开发”。

本批不修改产品代码、测试数量、Store、原件、KB 或处理器。完成后由项目所有者决定是否批准本计划并授权 `CUR1A`。

### `CUR1A`：最小执行契约与 golden fixtures

目标：把当前 Review Candidate 中本切片真正需要的字段和操作变成可测试边界，不一次性实现所有远期能力。

交付物：

1. 将捕获/路由、SOP-10 和 SOP-20 中 `CUR-MVP-1` 使用的条款标为获批实施范围；SOP-30 保持未授权。
2. 新建 `knowledgeflow_curation` 包骨架、受限值对象、错误码、规范编码和 golden fixtures。
3. 固定最小入口、结果回执、三项权限记录、实验 Profile、来源映射、范围账和 locator 语义。
4. 为 `map.yaml + map.md`、地图决定和 KB manifest 建立最小校验器；不得顺手冻结通用 Task/Ledger/Evidence/Graph schema。
5. 为新增 `tests/curation/` 扩展项目状态测试计数，使总数明确等于 Capture、Curation 和脚本测试之和；不能把策展测试误计为 Capture 测试。

验收：golden 往返字节稳定，未知字段/非法类型/越界值拒绝，错误码和状态不冒充已提交；现有 338 项测试不回退。

停点：单独复核并提交。未获下一批授权不读取真实 `E0-C` 正文。

执行记录（2026-10-18）：项目所有者精确授权本批后，本地实现新增独立 `knowledgeflow_curation` 包、不可变值对象、稳定错误语义、规范编码、白名单原文件到 Capture 的来源映射、独立的处理允许范围与本次声明范围、SOP-10 provisional KB manifest、6 类机器文件与同事实 `map.md` 共 7 份契约/呈现 golden、另 1 份 41-byte 来源正文夹具，以及 15 项 `tests/curation/` 测试；地图决定摘要按 SOP-20 使用决定文件精确 bytes 的 SHA-256。新增测试、严格 `ResourceWarning` 回归与文档护栏均通过，随后由本地提交 `9b33acc` 单独版本化。该批未读取真实 `E0-C` 正文、未创建 Store/KB、未调用模型。

### `CUR1B`：精确来源、分段、范围和 Evidence 回读

目标：完成纵向切片内部的机械检查点，但不把它宣称为产品里程碑。

交付物：

1. 通过已有初始化和 `capture_text/get_capture` 公共能力建立全新实验 Store，并把 `E0-F/E0-C` 各映射为一个 Capture v1；映射保存在实验工作层。
2. 实现 `experiment-markdown-blocks-v1`、范围账、locator 和严格原文回读。
3. 对相同输入/配置双跑，删除派生物后重建并比较有序 Segment、范围和摘要。
4. 提供查看来源身份、范围和证据的受限入口。

验收至少覆盖：LF/CRLF、无尾随换行、中文与组合字符、空行、标题、表格、代码块、超长行、非法 UTF-8、错误版本、无效字符边界、越界范围、Payload 哈希变化、完整/延期/失败范围及重叠窗口记账。`E0-C` 全文只做机械读取和记账，不调用模型。

停点：单独复核并提交。此时项目状态仍为 `CUR-MVP-1 in progress`，不得写“来源底座完成”或开始低摩擦/RAG。

执行记录（2026-10-18 至 2026-10-19）：项目所有者已精确授权本批。实现复用公共 `initialize_capture_store`、`capture_text` 与 `get_capture`，新增 `experiment-markdown-blocks-v1` 的精确字节覆盖、UTF-8 字符边界、范围账、每段 locator、原文摘要回读、幂等工作包和 `source prepare` / `source inspect` / `evidence show` 三个受限命令；失败命令只给一个 `next_action`，且尚未实现的后续命令不暴露空壳。`target_decision` 在 CUR1B 可明确为 `null`，地图校验则在 CUR1C 记录决定前失败关闭，避免把“尚未决定”伪装成“用户选择无目标”。

本批新增 14 项测试，使 `tests/curation/` 为 29 项；已覆盖 LF/CRLF、无尾随换行、中文/组合字符、空行、标题、表格、代码块、超长行、非法 UTF-8、错版本、无效字符边界、范围缺口/重叠拒绝、Payload 篡改、混合范围状态、幂等冲突、派生物重建、工作包篡改和 CLI 输出不覆盖。真实机械验收在同一个一次性临时实验 Store 中把冻结 `E0-F` 映射为 17,327 bytes / 2 Segments，把精确 `E0-C` 映射为 1,184,815 bytes / 76 Segments；抽样 Evidence 回读、删除派生物后的有序范围/摘要重建与 Capture 复用均通过，staging 为空，临时根已整体删除。独立复核使用不污染真实暂存区的拟提交索引，普通与严格 `ResourceWarning` 全量测试均为 367/367，源码编译、依赖检查、文档一致性和差异检查通过。全程没有调用模型、网络、Git 版本适配器，没有创建 KB 或写入 `raw/`/`wiki/`，也没有硬编码原件路径进产品代码。实现与验证由独立提交 `79f6167` 版本化，事实由 `3ac2ed6` 同步；首次远端 Windows CI #16 只因未受保护的策展 fixture 在全新 Windows 检出时转换为 CRLF 而失败，`b8525b9` 固定 fixture LF 后，[Windows CI #17](https://github.com/bayTong/knowledge-flow/actions/runs/39223596557) 通过安装、普通与严格两轮 367 项测试以及全部静态门禁。该段只记录 CUR1B 的闭合事实；后续 CUR1C 状态见下一节和唯一项目状态文档。

### `CUR1C`：目标确认、新 provisional KB 与 `raw/` 映射

目标：实现主旅程需要的新库分支和受控无目标分支。

交付物：

1. 记录目标建议、用户确认/跳过和处理授权，不把建议冒充用户决定。
2. 在显式允许根内初始化最多一个 `managed-local` provisional KB；Git 只在 KB 根内离线使用，不配置或访问 remote。
3. 使用流程自有 staging、父级锁、稳定幂等身份和受控版本适配器发布最小骨架。
4. 用户确认目标后，把 Capture Payload 同字节复制到 `raw/text/`，生成来源旁车、Route Record 和限定路径检查点；任一验证失败都不发布成功状态。
5. 用户选择暂不选库时，只在 `curation-work/` 保存工作成果，不创建 KB、Git 仓库、`raw/` 副本或 Route Record。

验收至少覆盖：自定义名称/日期序号、同日并发、幂等冲突、路径越界、已有未知目录、无 Git/受控 Git 不可用、无网络/无账号/无 remote、宿主 Git 配置隔离、staging/发布/commit/回执故障、`raw/` 哈希不符、受管 ref 并发漂移和无目标零副作用。

停点：单独复核并提交。实验 KB 仍是 `provisional`，`wiki/` 为空，不具备可信搜索资格。

执行记录（2026-10-19）：项目所有者已精确授权本批。实现新增独立的目标建议、用户目标决定、原料映射和 Route Record 契约；`target decide` 只接受显式实验根，建议与用户决定分别记录。新库分支在 `<experiment-root>/kb-root/` 下使用父级锁、稳定事务身份、流程自有 staging 和受控离线 Git 适配器，固定 `refs/heads/knowledgeflow`、技术作者、换行与隔离索引，不读取宿主 Git 身份、不配置 remote，也不要求账号或网络。发布后把精确 Capture Payload 同字节写入 `raw/text/`，连同来源旁车、Route Record、限定路径检查点和非自引用回执逐层回读；无目标分支只写 `curation-work/`。

本批新增 3 份 golden 和 13 项测试，使 `tests/curation/` 为 42 项、项目测试锚点为 Capture 323 + Curation 42 + 文档脚本 15 = 380。测试覆盖自定义/日期序号、同日双进程分配、未完成事务名称保留、请求幂等与冲突、路径越界、未知目录/事务、嵌套 Git 工作树拒绝、缺失 Git、宿主配置隔离、无 remote、staging/发布/checkpoint/回执故障、原料/记录篡改、受管 ref 漂移、隔离索引不触碰用户改动，以及无目标零 KB 副作用；42 项策展测试与 70 项受影响 Capture 回归已在本地通过。所有 KB/Store 都位于测试临时根并由测试清理；没有读取真实 `E0-C`、调用模型或网络，`wiki/` 除结构用零字节 `.gitkeep` 外没有正文，也未激活 KB、触碰 Pilot/生产 Store 或已有 KB。当前工作树仍待独立差异复核和本地提交，远端门禁未运行。

### `CUR1D`：真实处理器、地图生成、证据导航与修改

本批开始前必须先闭合：

- `C-K1`–`C-K8` 的独立人工确认；
- 用户的实际人工阅读基线；
- 真实处理器、数据发送范围、模型/版本、网络边界、调用次数、输入/输出 token、费用上限和预算耗尽停点；
- 处理器不得读取 gold、判分结果或已经包含答案的本轮上下文。

交付物：

1. 生成目标建议所需的最小材料梗概，并等待人工确认后才调用 `CUR1C` 的新库/路由能力。
2. 按获准层次处理范围，生成并严格验证地图候选；历史对话中的命令、链接和工具示例始终作为数据，不执行。
3. 原子发布 `map.yaml + map.md + run record`；两种表示必须来自同一事实。
4. 实现证据打开、候选接受/拒绝/延期、替代文本和新地图版本；旧版本不可变。
5. 实现 `map_closed`，确认该动作只结束地图任务，不写 `wiki/`、不激活 KB、不触发 SOP-30。

验收至少覆盖：无证据主张、locator 指向未授权范围、来源主张与处理器推断混淆、地图 YAML/Markdown 不一致、处理器输出截断/超限/无效、预算中止、用户修改、旧地图决定失效、发布故障、重试、无目标地图原子发布和有目标地图限定路径本地检查点。

停点：单独复核并提交。未经项目所有者对实测结果的判断，不进入 `CUR-MVP-2`。

### `CUR1V`：本地总验收与价值判断

按下列两条旅程验收：

1. `E0-F`：验证精确身份、全文机械范围、locator、回读、双跑、派生物重建和“暂不选库”零副作用；不把结果计为语义价值。
2. `E0-C`：在一个全新隔离 provisional KB 中完成来源 Capture、目标建议/确认、`raw/` 映射、分层地图、证据打开、至少一次用户修改和地图处结束。

验收同时运行所有新增单元/集成/故障测试、现有 338 项回归、严格 `ResourceWarning`、源码编译、依赖检查、文档一致性与差异检查。Windows CI 只作远端复核，不是本地使用、GitHub 账号或联网运行的产品前置。

结果报告必须分别给出：机械全通过/失败项、语义处理范围、可见缺口、证据支持问题、首次有用结果时间、人工基线与系统路径用时、用户修改、调用/token/费用、失败样例和清理结果。

只有用户确认地图对真实任务有净收益，且全部机械门禁通过，项目状态才可把 `CUR-MVP-1` 标为限定范围 `Implemented/Validated`。否则保留证据，做至多一次有界修正，或停止该路线；不能自动转向 embedding、RAG、图谱或更大模型。

## 6. 跨批次测试与提交纪律

每个批次都必须：

1. 只使用测试临时 Store、实验工作根和隔离 KB，不读取 Pilot 正文或既有 active KB。
2. 先运行本批新增测试，再运行受影响回归和 15 项文档脚本测试；`CUR1V` 才重跑全量。
3. 运行 `git diff --check` 和文档一致性检查；新增当前文档、状态或测试计数必须同步。
4. 单独复核、单独提交；push 和远端 CI 由项目所有者决定，不作为本地下一批编码的隐式授权。
5. 失败时保留最小诊断，但不得留下会被发现为有效 KB、已发布地图或可信知识的半成品。

建议提交边界：

| 批次 | 建议提交主题 |
|---|---|
| `CUR1-0` | `docs(curation): 制定CUR-MVP-1纵向实施方案` |
| `CUR1A` | `feat(curation): 建立策展切片契约与夹具` |
| `CUR1B` | `feat(curation): 实现精确范围与证据回读` |
| `CUR1C` | `feat(curation): 实现隔离新库与原料映射` |
| `CUR1D` | `feat(curation): 实现可核验可修改策展地图` |
| `CUR1V` | `test(curation): 完成CUR-MVP-1纵向验收` |

提交主题只是建议，不提前证明相应状态已经完成。

## 7. 明确后置内容

本计划不实施：

- SOP-30 的 Prepare、批准、首次激活或可信 Wiki 写入；
- 已有 active KB 接入、多目标、多 KB 或物理目录改名；
- 低摩擦批量整理、定时自动策展、独立检索、RAG、embedding 或重排序；
- Ontology、正式知识图谱、图数据库或通用 Graph schema；
- GBrain、QQ、云账号、GitHub remote、自动 push 或多人协作；
- 生产 Store、正式私人/高敏内容环境、产品级删除、安全擦除或异盘灾备；
- 完整 Tk/Web/Obsidian 式工作台；
- 通用 Task、Ledger、Evidence、Processor Registry 或模型平台。

这些能力只有在本切片暴露出真实阻塞，或进入其各自独立门禁时才重新评估。

## 8. 立即停止条件

出现以下任一情况时停止当前批次，不以“尽量继续”掩盖不确定状态：

- 输入哈希、字节数、Capture Payload 或已批准范围不匹配；
- 无法证明实验目录与 Pilot/既有 KB 隔离；
- Git 受控本地模式不可用，却试图降级成无版本检查点的新 KB；
- locator 无法精确回读，或处理器结果引用未授权/不存在范围；
- 地图发布、受管 ref 或回执处于 unknown/recovery-required；
- 真实处理器、网络发送范围或数值预算尚未获得授权；
- 达到 token/费用/调用上限；此时保留已处理范围并把其余标为缺口；
- 用户认为地图增加了理解或复核负担，或无法解释结果来源；
- 需要修改 Capture v1、触碰 Pilot、写入 `wiki/` 或扩成后置平台才能继续。

## 9. 当前停点与下一项工作

`CUR1A` 已由提交 `9b33acc` 版本化；`CUR1B` 已完成实现、真实机械验收、版本化及精确远端 Windows 门禁，最终远端基线为 `b8525b9` 与 Windows CI #17；`CUR1C` 已获授权并完成本地实现与测试。当前立即停点是 CUR1C 独立差异复核、文档护栏和本地版本化，push/远端 CI 仍由项目所有者决定。下一功能候选批次是 `CUR1D`，但它尚未授权；在 C-K 独立人工确认、人工阅读基线、真实处理器与数据/网络/预算边界闭合前，不得运行语义处理器、生成真实地图或写入 `wiki/`。

