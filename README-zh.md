[中文文档](README-zh.md) · [English](README.md)

# KnowledgeFlow

<!-- knowledgeflow-doc-status tests=300 capture_tests=285 script_tests=15 next_gate=C7V -->

> 通用、适应性、治理优先的个人知识工作系统——用户可以从材料、问题或模糊意图开始，
> 由系统承担大部分研究、理解、组织和维护劳动，并以证据、分层信任和可回滚批准控制高影响变化。

> **当前状态（2026-09-24）**：项目正在从旧版“直接初始化/策展写入流程”迁移到“本地可靠捕获 → 人工路由 → 提案 → 精确批准 → 可回滚写入”的新治理架构。R1.2 已明确长期产品允许从材料、问题、研究主题、已有 KB 或模糊意图开始，且受控词表、Taxonomy、Ontology 等结构不是前置门槛；这次需求收口不改变 Capture v1 或当前 C7V 门禁。C7-0 与 C7A 已随 `fb61358` 同步到 `origin/main`；最后一轮已登记的干净 Windows CI 仍是运行 [`35319645501`](https://github.com/bayTong/knowledge-flow/actions/runs/35319645501) 在 `ea8f84e` 上通过。C7B 现已把严格 CLI 协议连接到既有四个核心操作，并加入固定 `knowledgeflow-capture` console entry、只从可信安装上下文构造的生产 `PathPolicy`，以及不进入发布接口的测试专用子进程 support。新增 7 项集成测试后，本地全量为 300 项（捕获测试 285 项、维护脚本回归 7 项、文档护栏回归 8 项），普通与严格 `ResourceWarning` 全量均已通过；C7B 已完成本地内容与验证，随本批独立版本化且尚未 push。下一功能门禁为需单独授权的 C7V 独立验收。三类 Profile 的默认路由、Source Ledger 物理契约和检索实现仍为 Draft。生产配置和生产 Store 均未创建。当前权威范围和冲突裁决见 [`设计权威与冲突登记`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md)。旧 SOP-002 及其写入提示词暂停执行。

| 想看什么 | 跳转 |
|---------|------|
| 这个项目解决的根本问题 | [知识策展悖论](#知识策展悖论) |
| 方法论全貌——管线怎么跑 | [核心管线](#核心管线) |
| 为什么这样设计——硬约束、两阶段、三层防御 | [核心设计决策](#核心设计决策) |
| 文件在哪、每个文件是什么 | [项目结构](#项目结构) |
| 怎么上手——最短路径 | [快速开始](#快速开始) |
| 粗读器如何处理不确定性 | [不确定性处理](#不确定性处理) |
| 真实使用数据 | [实践数据](#实践数据) |
| 设计背后的思维方式 | [设计哲学](#设计哲学) |
| 文档总入口与编号阅读顺序 | [`docs/README.md`](docs/README.md) |
| 主产品需求文档（唯一 L0 PRD） | [`docs/requirements-and-governance-baseline-需求与治理基线.md`](docs/requirements-and-governance-baseline-需求与治理基线.md) |
| 当前设计权威与冲突 | [`docs/design-authority-and-conflict-register-设计权威与冲突登记.md`](docs/design-authority-and-conflict-register-设计权威与冲突登记.md) |
| 跨主题概念架构导读 | [`docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md`](docs/knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md) |
| 当前 MVP-0 编码执行方案 | [`docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md`](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md) |
| 版本与阶段变更记录 | [`CHANGELOG.md`](CHANGELOG.md) |

---

## 知识策展悖论

两个前提，各自合理，合在一起是一个悖论：

**前提一**：高质量知识策展需要领域判断力。你能区分核心概念和次要细节，能识别两个看似不同的说法实质上指向同一个概念，能从一个语料中识别到哪些是应该提取成领域相关的重点实体、哪些内容是无关的或者相关性低的知识库不需要重点关注的、哪些知识之间应该做关联、做怎样的关联——这些判断只有真正理解领域的人才能做好。

**前提二**：用户之所以需要知识管理工具，往往恰恰因为不熟悉领域。希望通过知识管理来更快速、更直观、更容易从陌生语料中获取和熟悉知识，做好知识管理，或者实现一系列可交互的扩展功能——这个过程需要大量借助 AI 帮我们做分析推理。

悖论在此：**策展的责任人在人类这边（因为只有人类知道自己的目标和语境），但策展的责任人缺乏策展所需的知识；而拥有知识处理能力的实体（LLM）又缺乏判断「什么对用户重要」的语境，且 AI 本身可能出现的信息提取遗漏、大模型幻觉等问题不容忽视**。两条各自成立的前提指向了一个矛盾——究竟由谁来做策展？

大多数 AI 知识管理工具的解法是**无视前提二**——让 LLM 直接做策展。LLM 读了原料，判断哪些值得建页面，写摘要、打标签、建链接。这个方案快、无摩擦，但有一个不可修复的缺陷：**LLM 的遗漏比噪音更难修复**。LLM 如果过度提取（噪音），你删掉多余的页面只需要几秒钟。LLM 如果漏掉了一个关键概念，你根本不知道它没提取——因为从原料到成品的推理过程完全在 LLM 黑箱里，没有任何中间工件可以审查。

KnowledgeFlow 的解法是**重新分配责任并显式记录边界**，而非假设 LLM 能保证语义完整：

- **系统负责大部分知识劳动**——可进行研究辅助、概要、聚类、实体/关系发现、证据整理、组织方案和精确 diff 准备；每条正式候选锚定到来源，不确定性显式标记，建议严格隔离在事实之外
- **人类控制目标与高影响判断**——低风险机械操作可自动，可逆派生结果可自动生成，普通可信变更可以按边界清晰的批次审核，高影响范围或结构变化精确批准；处理台账说明哪些区段已处理、延迟或失败
- **目标态由受限写入器执行写入**——新的 SOP-002 只处理经过精确批准的变更，在 SCHEMA、事务和回滚约束下执行；该环节仍待重构，当前不得运行旧版写入提示词

可信晋升管线的核心是**降低人工负担，同时保留可审查性、证据绑定和受控提升**。系统不承诺一次性提取全部语义；它承诺原料不丢失、处理状态可见、候选可回溯，且只有获批对象才能进入可信知识层。问答、学习或临时研究可以停在明确标识的派生/候选层，不必每次都写入 Wiki。

---

## 解决什么问题

承接上面的悖论框架，现有工具的具体问题可以精确定位：

**问题不只在 LLM 的能力，也在角色和验证边界的错配。** LLM 适合大规模候选生成、结构化提取和证据整理，但在长文中仍可能遗漏、压缩或误解；把它直接放在可信策展人的位置上会放大两种失败模式：

- **遗漏**：LLM 觉得一个概念不够重要，跳过了。你不看原料原文就永远不知道它漏了什么
- **过度简化**：LLM 写了一页 wiki 页面，但你无法判断「这页信息是原料中仅有的，还是 LLM 自己挑出来的子集」。你失去了控制感——成品看起来合理，但你不知道它和原料之间的差距有多大

因此 KnowledgeFlow 的设计目标不是「更好的策展算法」或不现实的零遗漏承诺，而是**把可信判断拉回人类这边，通过确定性分段、处理台账、证据绑定和分层路径降低静默遗漏风险，并用 gold set 实验评估语义召回。**

---

## 核心管线

下图只描述“原始材料准备进入可信知识”的晋升路径，不是所有知识任务的强制流程。无目标 KB 的捕获、先问答后组织和研究主题探索可以在派生/候选层先产生可用结果。

```
原料（URL / 论文 / 对话记录 / 粘贴文本）
    │
    ▼
┌──────────────────────────────────┐
│  第一阶段：按 Profile 的处理层       │
│                                    │
│  · 捕获原料 + SHA256 溯源指纹     │
│  · 确定性分段 + Source Ledger      │
│  · `full-map` / `hierarchical-map` │
│    / `retrieval-first`             │
│  · 概要、候选提取和 Evidence Bundle│
│  · 5 种不确定原因分类              │
│  · 候选关系与 SCHEMA 建议隔离       │
│  · ☒ 不得创建任何 wiki 页面       │
│                                    │
│  产出：处理台账、概要/地图、证据包及候选 │
└──────────────────┬───────────────┘
                   │
                   ▼
         ═════ 风险分层审核 ═════
         批量决定：[确认 / 修改 / 退回 / 延期]
         高影响范围与结构变化单独精确批准
         可请求更多来源或调整组织建议
                   │
                   ▼
┌──────────────────────────────────┐
│  第二阶段：可信写入（新 SOP-002） │
│  状态：待重构，当前未启用         │
│                                    │
│  · 仅处理你确认过的条目            │
│  · 全文搜索查重——防止重复建页面   │
│  · 领域门禁（三级出口）            │
│  · 决策树：创建 / 追加 /           │
│    标记矛盾 / 跳过                 │
│  · 按 4 套模板 + 8 条通用约束写入  │
│  · 自检（8 项）→ 报告             │
│                                    │
│  产出：wiki 页面 + 更新 index      │
│        + log + 变更报告            │
└──────────────────────────────────┘
```

---

## 核心设计决策

### 1. 用硬约束代替软指引

粗读器定义了 7 条硬约束（C1–C7），其中 5 条是以 ☒ 标记的禁止项：

| 编号 | 约束 | 类型 | 为什么 |
|------|------|:---:|------|
| C1 | 不得创建任何 wiki 页面 | ☒ | 粗读器只产策展地图，不建库 |
| C2 | 每条提取必须有原文引用 | ☒ | 可追溯 = 可验证 = 可修正 |
| C3 | 不确定必须显式标记，不得假装确定 | ☒ | 这是粗读器区别于直接策展的核心价值 |
| C4 | Agent 建议必须和事实节严格分离 | ☒ | 防止建议污染事实层 |
| C5 | 不得静默丢弃；允许延迟、分层和按需处理，但必须记录状态 | ☒ | 处理缺口不能伪装成已完成 |
| C6 | 超长原料必须确定性分段并建立处理台账 | ☑ | 你能看到处理、延迟和失败边界 |
| C7 | 隐式关系可提取但须标推测 + 置信度 ≤ 中 | ☑ | 不让推测冒充确定 |

系统真正可机械审计的是保存、分段、状态和证据绑定；语义召回仍需通过人工 gold set 和对照实验估计，不能由条目数量或覆盖报告单独证明。

### 2. 可信晋升管线 + 风险分层审查断点

派生处理和可信写入是两个**独立的阶段**，中间有与风险相称的审查断点。策展地图、Evidence Bundle 或精确 diff 都可以成为审查面；系统先完成批量阅读、证据绑定和变更准备，用户再审核边界清晰的批次或高影响差异，而不是逐条承担全部整理工作。

这个分离缓解了「策展悖论」：用户即使不了解领域，也能先获得有来源的解释和候选结构；当结果准备改变可信知识时，再在写入前暂停、复核关键证据和影响。用户可以选择继续研究、整体退回或延期，而不必一次性完成全部结构设计。

### 3. 三层防御体系

| 层次 | SOP | 检查范围 | 触发时机 |
|------|-----|------|------|
| 目标态增量自检 | 新 SOP-002（待重构） | 本次获批变更的格式与事务正确性 | 每次可信写入 |
| 全量扫描 | SOP-003 健康检查（9 项） | 整个知识库的结构健康 | 每周定时 / 手动 |
| 连锁检查 | SOP-004 SCHEMA 一致性（5 项） | SCHEMA 修改对全库的连锁影响 | SCHEMA 变更后立即 |

三层之间不重叠——各自检查对方不查的维度，形成互补兜底。单次操作遗漏的腐化在定期扫描时捕获。

---

## 项目结构

```
knowledge-flow/
├── README.md                         英文 README
├── README-zh.md                      中文 README（本文档）
├── CHANGELOG.md                      变更记录
├── LICENSE                           MIT
├── pyproject.toml                    捕获内核包与精确锁定的运行时依赖
├── src/
│   └── knowledgeflow_capture/
│       ├── __init__.py               C0/C3/C4C 包身份与公开捕获/读取接口
│       ├── errors.py                 C1/C3A/C4A 公共错误、写入回执与读取结果模型
│       ├── models.py                 C1/C3A/C4A 哈希、写入及读取请求值对象
│       ├── ids.py                    C1 UUIDv7 与类型前缀
│       ├── hashing.py                C1/C3A 四类哈希与幂等摘要原语
│       ├── codec.py                  C1/C3A/C4A 受限 YAML 与 Envelope/Event/Projection schema
│       ├── config.py                 C2A 本地配置契约与规范发射
│       ├── paths.py                  C2A Windows 路径安全策略
│       ├── manifest.py               C2A Capture Store 身份契约
│       ├── locking.py                C2B/C3B Windows 初始化锁与 Store 写锁
│       ├── durability.py             C2B/C3B 耐久提交与有界 UTF-8 流式写入
│       ├── store.py                  C2B–C6B 初始化恢复、staging 与版本链纯原语
│       ├── operations.py             C3–C6C 四个受治理文本操作与迁移绑定复核
│       ├── cli.py                    C7A/C7B 受限 CLI 帧、spool、生产分派与安装入口
│       ├── recovery.py               C6B 显式派生状态重建操作
│       └── migration.py              C6C 显式复制—验证—切换 Store 迁移
├── tests/
│   ├── capture/
│   │   ├── fixtures/                 C1–C4A 的 10 份 JSON/YAML/正文 golden 文件
│   │   ├── unit/                     C0–C7B 单元与平台测试
│   │   ├── integration/              C2B–C7B 事务、读取、CLI、重建、迁移、真实边界与并发测试
│   │   └── fault/                    C2B/C6A 进程崩溃恢复测试（捕获测试共 285 项）
│   └── scripts/
│       ├── test_doc_check.py          确定性文档护栏回归测试（8 项）
│       └── test_maintenance_scripts.py  维护脚本回归测试（7 项）
├── docs/
│   ├── README.md                    唯一文档阅读地图与编号顺序
│   ├── requirements-and-governance-baseline-需求与治理基线.md      主产品需求文档（唯一 L0 PRD）
│   ├── design-authority-and-conflict-register-设计权威与冲突登记.md  当前主题权威与冲突裁决
│   ├── knowledgeflow-conceptual-architecture-KnowledgeFlow概念架构导读.md  非规范性跨主题概念地图
│   ├── mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md       当前编码批次与授权门禁
│   ├── mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md  实现选择与测试矩阵
│   ├── c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md      C8 前保留的 C3 细粒度决策
│   ├── capture-and-routing-spec-捕获与路由规范.md                  捕获与人工路由设计
│   ├── capture-envelope-v1-捕获信封数据契约与原子保存事务.md      捕获身份与事务契约
│   ├── mvp-0-capture-operations-本地文本捕获操作契约.md           四个文本操作契约
│   ├── sop-000a-provisional-kb-bootstrap-临时知识库骨架初始化.md   临时 KB 创建设计
│   ├── progressive-knowledge-refinement-spec-渐进式知识提炼规范.md  已确认治理红线 + Draft 方法假设
│   └── research/
│       └── README.md                非权威研究输入索引
├── prompts/                          LLM-agnostic 提示词模板
│   ├── README.md                    模板使用说明
│   ├── sop-001-modeA.md             默认：单次提取（第 1-9 节）
│   ├── sop-001-modeA-auditor.md     默认：独立覆盖审计员（第 10 节）
│   ├── sop-001-modeA-fast.md        可选快速路径（含自检覆盖）
│   ├── sop-001-modeB-pass1-entities-claims.md  模式 B Pass 1：实体+论点
│   ├── sop-001-modeBC-pass2-relationships.md   B/C 共享：关系提取
│   ├── sop-001-modeBC-assembler.md             B/C 共享：组装器 + 覆盖报告
│   ├── sop-001-modeC-pass1-entities.md         模式 C Pass 1：实体
│   ├── sop-001-modeC-pass3-claims.md           模式 C Pass 3：论点
│   ├── sop-002-curator.md                   旧 SOP-002 写入模板（暂停执行）
│   ├── sop-003-lint.md                      SOP-003 健康扫描
│   └── extraction-interface.md      提取接口技术规范
├── scripts/                         参考实现脚本（纯 Python 标准库）
│   ├── README.md                    用法、Windows 注意事项、SOP-003 映射
│   ├── doc-check.py                 Git 感知的确定性文档护栏
│   ├── lint.py                      SOP-003 Lint 扫描器
│   ├── link-validator.py            Wikilink 验证器
│   └── index-generator.py           index.md 生成器
├── templates/
│   └── SCHEMA-template.md           可复用知识库宪法模板（7 章起步）
├── examples/
│   ├── curation-map-example.md      历史策展地图样例（25K 行；原始材料未收录）
│   └── wiki-page-example.md         wiki 页面样例（策展入库产出）
└── archive/
    ├── 2026-design-history/
    │   └── README.md                  九份旧方案、愿景与 SOP 的归档索引
    └── v1.0/
        ├── README.md                  v1.0 局限性说明
        └── sop-v1-original.md        v1.0 原始 SOP
```

---

## 快速开始

完整的捕获 MVP 尚未实现。公开 `capture_text`、`get_capture`、`list_captures` 与 `append_capture_version` 已实现，C5V、C6 各批以及 C7B 四操作 CLI 适配与安装入口也已通过本地验证。C7V、C8 总验收与生产初始化仍未完成，因此还不能宣称存在生产可用的完整链路。正确的后续建设顺序是：

1. 按 [设计权威与冲突登记](docs/design-authority-and-conflict-register-设计权威与冲突登记.md) 确认当前边界。
2. [MVP-0 捕获内核实现拆解与测试矩阵](docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md)和[编码执行方案](docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md)均已批准；C0–C6C 均已完成并版本化，捕获内核基线截至 `ea8f84e` 已 push，其干净 Windows CI 运行已通过。
3. 方向治理红线已经确认，但三类 Processing Profile、Source Ledger、Evidence Bundle、自动路由和语义召回评测方法仍为 Draft，不能据此直接实现 RAG 或候选图谱。
4. C7B 已完成本地内容与验证并随本批独立版本化；下一步依次完成单独授权的 C7V CLI 阶段验收和 C8 总验收。C8 通过后可另行授权生产 Capture Store 和仅使用现有 Capture 能力的最小收件箱 dogfood，同时用隔离临时 Store 做规模/结构基线实验，再冻结 Segment/Ledger/Profile/Evidence Bundle 契约并开展本地检索对照实验。
5. 实验证据形成后再增加人工路由、SOP-000A、SOP-001 重构、候选图谱和 GBrain 未审核镜像；只有在 SOP-000B 与新版 SOP-002 定义精确批准、事务和回滚后，才允许可信 wiki 写入。

现有 `prompts/sop-001-*` 仍可作为 `full-map` 或分层提取实验素材；产物应进入 `proposals/curation-maps/` 或相应未审核派生层，并在人工审核后停止。不要执行旧 [`prompts/sop-002-curator.md`](prompts/sop-002-curator.md) 写入真实知识库。现有 SOP-003 Lint 脚本仍可用于检查旧版或现有 Markdown KB。

---

## 不确定性处理

粗读器不假装确定。每条提取都有一个必填的「置信度」字段，当置信度不是「确定」时，Agent 必须从 5 种预设原因中选择一个：

| 类别 | 含义 | 典型场景 |
|------|------|------|
| `来源不可靠` | 原文中的数值/声明缺乏原始引用 | 「MRR 提升 15-40%」但无论文出处 |
| `Agent 理解局限` | 提取者不确定自己的理解是否正确 | 语义模糊的段落 |
| `原文模糊` | 原料本身的表述不够明确 | 类比过于简化 |
| `信息不完整` | 原文提到了但未展开 | 「此外还有 Graph RAG……」一笔带过 |
| `总结压缩损失` | 原料本身是二手总结，可能丢失了原始细节 | 对话总结而非原始记录 |

不同类别的不确定对应不同的人类处理策略——来源不可靠需要查原始论文，总结压缩损失需要找原始对话——这个分类本身就是一种行动指南。

---

## 实践数据

> 方法论形成过程参考了 4 个跨领域知识库的实践。仓库内当前可核查的证据只有 [`examples/`](examples/) 中一份历史 25K 行策展地图样例和一份派生 wiki 页面；原始材料未收录，因此它们是说明性样例，不构成可复现实证。

---

## 设计哲学

知识库有两种退化方式：**漂移**（页面内容过时）和**碎片化**（同一概念散落在多个页面）。大多数工具靠定期清理处理漂移，但很少有工具能有效防止碎片化。

KnowledgeFlow 通过两个机制同时应对两者：**宪法约束**（SCHEMA.md 是结构规则的唯一权威来源——Agent 写的任何页面都必须通过 SCHEMA 的格式和标签体系校验）和**纵深防御**（写入时查格式、Lint 时查结构、SCHEMA 变更时查连锁破坏）。系统设计让最危险的失败模式——重复页面、断裂链接、孤立实体、SCHEMA 与页面不一致——被自动捕获，不依赖人类的持续警惕。

---

## 许可

MIT
