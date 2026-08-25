# KnowledgeFlow × GBrain 集成方案

> 本文档是 KnowledgeFlow 与 [GBrain](https://github.com/garrytan/gbrain) 集成的**唯一权威规划文档**。
> 定位为「可视化知识管理项目」的设计方案,与 [`docs/build-plan.md`](build-plan.md)(建设路线图)并列。
> GBrain 本地源码:git clone 位于 `E:\Workstation\code_space\gbrain\gbrain`
> (master HEAD `4e4677b1`,v0.46.28.0 + 7 个发布后修复提交;2026-08-25 复核)。

---

## 目录

1. [定位与目标](#一定位与目标)
2. [结论摘要:三条权限轨](#二结论摘要三条权限轨)
3. [结合点总览](#三结合点总览)
4. [目标架构](#四目标架构)
5. [写入权限模型(核心)](#五写入权限模型核心)
6. [报告制事后加工:复用 GBrain 现成机制](#六报告制事后加工复用-gbrain-现成机制)
7. [统一审核面](#七统一审核面)
8. [分阶段路线图](#八分阶段路线图)
9. [关键设计决策](#九关键设计决策)
10. [风险与对策](#十风险与对策)
11. [决策记录与待确认](#十一决策记录与待确认)
12. [附录:GBrain 关键参考点](#十二附录gbrain-关键参考点)

---

## 一、定位与目标

### 1.1 两者关系:方法论 ↔ 引擎,天然互补

**KnowledgeFlow** 解决了「知识策展悖论」——LLM 穷举提取、人做语义判断、两阶段管线,
但它是纯方法论:只有 SOP 规范、prompt 模板和 Python 参考脚本,**没有存储、检索、图谱和运行时**。

**GBrain** 是成熟的引擎:Postgres/PGLite 存储、混合检索(向量 + BM25 + 图)、
知识图谱、任务队列(Minions)、MCP 服务、技能体系,但它的哲学是**低摩擦直接写、事后加工**,
没有「深度内容入库前的人审闸门」。

集成的本质:**KnowledgeFlow 提供「怎么把知识管对」的策展纪律,GBrain 提供「知识存哪、怎么查、怎么连、怎么跑」的引擎能力**。不是二选一,也不是 fork 其中一个,而是把 KnowledgeFlow 的管线作为 GBrain 之上的技能层 + 审核层。

### 1.2 目标

1. 深度内容(长篇幅资料 / 研究 / 学习材料)入库**不黑盒**:人能看到资料是什么、有哪些主要内容、要不要入库怎么入库,审核通过后才策展写入。
2. 轻量内容(灵感 / 随手笔记 / 自动搜集)保持**低摩擦**:系统直接写,只做事后加工,不做先审。
3. 所有轨道的**后续更新、关联调整**走「报告 + 提醒 + 人确认后确定性执行」,机器不静默改语义。
4. 以 GBrain 的数据(图、轨迹、覆盖报告、健康指标)为原料,构建**可视化知识管理界面**。

### 1.3 文档治理与取代关系

现有四份规划文档,分工已清晰(2026-08-24 起):

- `build-plan.md` — 长期路线图(阶段 0-3)
- `improvement-action-plan.md` — 当前版本缺陷整改清单(P0/P1/P2,P0-1/P0-2 已完成)
- `qq-qa-bot-plan.md` — 问答入口怎么搭(QQ 通道 + dsh + 检索层)
- 本方案 — 存储/检索引擎集成(GBrain)

本方案**取代了 build-plan 的一部分设计**:多知识库路由表 + unified-index.json(改为 brain/source 两轴)、
MC-001 的落地方式(改为 Dream Cycle + Minions 复用)、Hermes cron 假设(改为 Minions 调度)——
连带 `second-brain-vision.md` 中对应段落过时。

漂移防治不再靠本方案自设流程,而**并入 improvement-action-plan 的既有机制**:

1. **P1-1 `doc-check.py` 一致性护栏**:本方案的跨文档引用纳入其比对范围;
2. **P2-4 状态标注**:build-plan / vision 的「规划中 vs 已实现」标注与本方案的取代标注一并执行;
3. 四份规划文档与 P0-1/P0-2 的修改一起纳入 **P0-4** 提交范围,不再各自 untracked 漂移。

本方案定位为「引擎集成的分册」,不新增「唯一权威」名号。

---

## 二、结论摘要:三条权限轨

> 这是全部讨论收敛出的核心结论。详细论证见第五节。

| 轨道 | 内容类型 | 写入时机 | 审核方式 | 落地机制 |
|---|---|---|---|---|
| **B-捕获** | 灵感、想法、随手笔记 | 直接写 | 无先审,事后加工 | `gbrain capture` + signal-detector + inbox |
| **B-搜集** | 自动搜集(API / 网页 / 会话记录) | 直接写 + 留痕 | 主张级 / 实体级报告制人审 | enrich 管线 + `put_raw_data` + take_proposals / contradictions |
| **A-策展** | 长篇幅深度研究材料 | **人审后写** | 策展地图级先审 + 事后报告制 | SOP-001/002 技能 + curation_map 页面 |
| **维护** | 所有轨道的更新 / 关联调整 | 报告 + 确认后写 | 报告制人审,确认即执行 | drift / contradictions / propose_takes |

**triage 规则(何时走哪条轨):**

> 当「漏掉」比「多写」更不可修复时走轨道 A;反过来走轨道 B。
> 「多写」的噪音删除只需几秒;「漏掉」的关键概念一旦漏了,人永远不知道它没被提取。

这个规则就是策展悖论的自然延伸,也是唯一的判据,不需要更复杂的分类。

---

## 三、结合点总览

按管线逐段对齐 KnowledgeFlow 概念与 GBrain 能力:

| KnowledgeFlow 概念 | GBrain 对应物 | 结合方式 |
|---|---|---|
| wiki 仓库(markdown + frontmatter + wikilink) | brain repo + page | `sources add` + `sync --watch` 增量同步,文件即 system of record |
| SCHEMA.md(页面 type / 关系 type) | schema packs(类型分类法) | SCHEMA 映射为自定义 pack;frontmatter type → 类型,关系 → typed links |
| 原料 + SHA256 溯源指纹(C2 硬约束) | `put_raw_data`(raw_data 表) | 溯源从「文档约定」变成「机器强制」 |
| SOP-001 策展地图(10 节) | 作为一等页面(type: curation_map) | `add_link` 链回原料页,「用完即弃的中间产物」变成可检索的持久审计工件 |
| 人审断点 | 无页面级先审(GBrain 的缺口) | **新建**:策展地图 `status: pending-review → approved` 状态流 |
| SOP-002 策展入库 | `put_page` / `add_link` / `add_tag` / `add_timeline_entry` | 写成 GBrain 技能,SCHEMA 约束做写前校验 + 写后自检 |
| SOP-003 lint / 三个 Python 脚本 | `gbrain doctor` / `orphans` / `check-resolvable`(均有 --json) | 文件层脚本继续跑,引擎层 doctor 互补 |
| MC-001 元认知六维度 | Dream Cycle + Minions + eval | 逐维度复用,见第六节;定时执行用 Minions + cron-scheduler skill |
| 多知识库路由表 + 联合索引 | brain ⊥ source 两轴 + mounts + 联邦搜索 | **删掉自建设计**:每个 KB = 一个 source(一个脑库多 source),各 KB 的 SCHEMA.md = per-source schema pack |
| 主动检索规范 | `volunteer_context`(push 上下文)+ `search` / `think` | 直接复用 |
| 可视化(新增部分) | admin SPA 先例 + `traverse_graph` / `find_trajectory` | 新建独立 viz 应用,见第七、八节 |

**结论:** 集成不要求改造 GBrain 核心;需要新建的只有两类东西——**策展地图级审核面**(GBrain 完全没有)和**统一审核看板**(收拢 GBrain 已有的散落机制)。

---

## 四、目标架构

```
┌────────────────────────────────────────────────────────────┐
│  可视化知识管理 App(React,新项目,viz 层)                      │
│  知识图谱视图 · 策展管线看板 · 覆盖报告图表 · 健康仪表盘          │
│  · 统一审核面(所有待审内容的一屏收件箱)                          │
└───────────────┬────────────────────────────────────────────┘
                │ HTTP MCP(OAuth)  或  库模式直接 import
┌───────────────▼────────────────────────────────────────────┐
│  GBrain(引擎层,不 fork,当依赖/服务用)                          │
│  PGLite/Postgres · 混合检索 · typed graph · Minions           │
│  doctor/eval · serve --http · spend controls                │
│  ┌────────────────────────────────────────────────┐        │
│  │ KnowledgeFlow 技能层(skillpack,新写)              │        │
│  │ sop-001-extract / sop-002-curate / sop-003-lint │        │
│  └────────────────────────────────────────────────┘        │
└───────────────┬────────────────────────────────────────────┘
                │ sources add + sync --watch
┌───────────────▼────────────────────────────────────────────┐
│  knowledge-flow 知识库仓库(markdown,人审断点所在地)            │
│  轨道 A:策展地图 → 人审 → 入库                                │
│  轨道 B:capture / enrich 直接写                              │
└────────────────────────────────────────────────────────────┘
```

三层分工:

- **文件层**(知识库仓库):人可读、可 git 版本化的 system of record;人审断点落在这里。
- **引擎层**(GBrain):存储、检索、图谱、队列、报告制事后加工。职责是「机器能力」。
- **技能层 + 审核层**(KnowledgeFlow):策展纪律(先审后写)与统一审核面。职责是「把判断权留在人手里」。

### 4.1 Agent 与模型分工(DeepSeek harness)

成品形态:基于 **DeepSeek harness 搭建的 agent** 做对话与编排,前端**看板**做系统展示与交互管理。
这里要把「LLM 出现在哪」分成两个位置,不要混为一谈:

| 位置 | 谁在调模型 | 模型怎么配 |
|---|---|---|
| Agent 层(对话编排) | DeepSeek harness 自己的运行时 | harness 侧配置,DeepSeek 模型 |
| GBrain 内部加工(Dream Cycle 提取 / 合成 / think / 查询扩展) | GBrain 的模型网关 | `models.*` 配置指向 `deepseek:deepseek-v4-flash` / `deepseek-v4-pro` |

GBrain 对 DeepSeek 的支持现状(已核实 v0.46.28.0 源码):

- 专用 recipe(`src/core/ai/recipes/deepseek.ts`),模型 `deepseek-v4-flash` / `deepseek-v4-pro`;
  `deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 退役,旧名会 404,勿再使用。
- 支持工具调用与子 agent 循环(`supports_subagent_loop: true`)——即 Minions 的持久化子 agent 也能跑 DeepSeek。
- thinking 模式默认开启,GBrain 内置了 `reasoning_content` 的传输适配(且不会把思维链回灌进上下文)。
- **DeepSeek 无 embedding 模型(chat only)**。向量检索需单独配 embedding provider:
  国内云用 DashScope(Qwen)/ 智谱;本地零成本用 Ollama / llama-server 跑 BGE-M3。

结论:整条链路可以全 DeepSeek + 一个国内 embedding provider,完全符合「先本地、低成本」的起点;
Minions 子 agent 也无需 Anthropic key(Anthropic 直连硬绑定只针对 OpenRouter 路由场景)。

**Agent 运行时选型已落定(见 [`qq-qa-bot-plan.md`](qq-qa-bot-plan.md)):官方 deepseek-harness(dsh)。**
三档演进:headless 单次调用 → ACP 常驻服务 → KB 检索做成 dsh 插件;dsh 通过 MCP 连 GBrain,
与本节的「MCP 服务模式优先」一致。dsh 是 v0.1 预览版(2026-08-13 发布),对策是 pin 版本 +
网关侧薄适配器 + eval 回归——与本方案「集成面保持薄」同构。

**跨文档一致性提醒(2026-08-25 核查):** qq-qa-bot-plan 的 D6 与成本节使用
`deepseek-chat`(V3.2)/ `deepseek-reasoner` 两个模型名——GBrain 源码
(`src/core/ai/recipes/deepseek.ts`)注明这两名已于 **2026-07-24 被 DeepSeek 官方退役(API 404)**,
映射为 `deepseek-v4-flash` / `deepseek-v4-pro`。qq 计划写于退役之后,模型名过时;
上线前须以 DeepSeek 官方最新文档为准统一(本方案采用 v4 口径,详见开放问题清单)。

### 4.2 多知识库映射与部署演进

KnowledgeFlow 已有的规范「不同内容建立不同知识库」在 GBrain 里对应为:

- **每个知识库 = 一个 source**(同一个脑数据库里的一个仓库)。一个本地 PGLite 脑可以挂多个 source。
- **每个 KB 的 SCHEMA.md = per-source schema pack**——GBrain 的 schema pack 解析链支持 per-source DB key,
  各 KB 保持各自的「知识库宪法」,互不污染。
- 联邦搜索默认开启:查询可跨 source 召回;需要隔离的 source 设 `federated=false`。
- 进入某个 KB 目录时用 `.gbrain-source` 点文件自动钉住 source,不需要手工维护路由表。
- build-plan 里的「知识库路由表 + unified-index.json」**删除**,由 GBrain 联邦搜索 + 两轴路由替代。

什么情况下才拆成多个 brain(多个数据库):数据归属不同、生命周期不同、或需要共享给团队的 KB。
判据沿用 GBrain 文档的规则——**数据 owner 变了才是 brain 边界,owner 不变只是主题不同则是 source 边界**。

部署演进(已决策):**初期纯本地单机(PGLite),长期远程多端。** 因为集成面走 MCP 服务模式,
从本地切远程不需要重新架构:`gbrain serve --http` + 换 Postgres/Supabase 引擎即可,数据与接口不变。
GBrain 获取方式(已解决):网络已通,git clone 完成于 `E:\Workstation\code_space\gbrain\gbrain`
(master HEAD `4e4677b1`,比 zip 快照 `67e7e8a9` 新 7 个提交,内容差异已复核、不推翻本方案任何结论)。
Phase 0 以此 clone 为准。

**仓库整理待办(不阻塞 Phase 0,但别拖):** 目前同一台机器上有三份 GBrain 副本,极易拿错版本:

| 路径 | 版本 | 处置建议 |
|---|---|---|
| `E:\Workstation\code_space\gbrain\gbrain` | master HEAD(0.46.28.0+7) | **保留为唯一权威 clone** |
| `E:\Workstation\code_space\gbrain`(外层) | 0.42.44.0(6 月旧版) | 删除或归档;它现在只是新 clone 的"包装目录" |
| `E:\Workstation\code_space\gbrain-master`(zip 解压) | 0.46.28.0(落后 7 提交,无 .git) | 删除或归档,已被 clone 取代 |

理想布局是直接把权威 clone 放在 `E:\Workstation\code_space\gbrain`(拆掉嵌套)。
删除属破坏性操作,动手前先备份或与我确认。

### 4.3 规模边界与引擎切换

GBrain 官方文档给出的量级分层(已核实 `docs/ENGINES.md` 与 README):

| 引擎 | 舒适区间 | 已验证上限 | 限制 |
|---|---|---|---|
| PGLite(本地,WASM 内嵌 Postgres) | **< 1,000 页/文件(每脑)** | ~50K 页(设计软顶,非舒适区) | 单进程并发、单机、备份靠手工拷贝文件;大库时 sync / Dream Cycle 明显变慢 |
| Postgres + pgvector(Supabase / 自建) | 10K+ 页,生产验证 | **146K+ 页**(GBrain 自己的生产脑约 146,646 页) | 需要 $25/mo Supabase Pro 或自建;有连接池 / RLS / 多端能力 |

结论:**对个人到团队量级,GBrain 几乎不会触顶;真正的边界只有一个,而且是无损切换**——
单脑总量超过 ~1,000 页(或需要多端 / 并发 / 团队共享)时,从 PGLite 迁到 Postgres。
`gbrain migrate --to supabase` 双向无损(页面、chunks、embeddings、links、tags、timeline、facts 全迁),
不存在「数据大了要重来」的死胡同。

**先于「页数上限」成为瓶颈的通常是另外三件事**,规划时按这个顺序盯:

1. **Embedding 成本**:每个 chunk 一次 API 调用。长文多 chunk,向量化支出随 chunk 数线性增长
   (GBrain 有 spend controls 兜底,可设预算门)。
2. **Dream Cycle 的 LLM 成本与时长**:页数越多,夜间加工越贵越慢;可 phase 级裁剪 + 预算封顶。
3. **同步速度**:增量 sync 只走 diff,但首次全量导入大库耗时长。

**多库场景的量级算法**:总量按「单脑内所有 source 的页数之和」算,而不是按单个 KB 算。
你的规范是「不同内容建不同 KB」→ 多个 source 挂在一个 PGLite 脑里,所以看的是**跨库总页数**。
按每个 KB 几十~几百页的规模,即使十几个 KB 也远在 1,000 页舒适线以内。

**可视化层有它自己的、更早的实用边界**(与存储上限无关):图视图全量渲染到几千节点就会拥挤,
届时需要子图 / 折叠 / 按 source 分层。G6 原生支持这些,方案已按「多库 + 全量图起步、到量级再分层」预留。

### 4.4 双入口系统形态(2026-08-24 起)

项目现为两个并行的产品入口,共享同一个 GBrain 引擎与同一份索引:

```
┌──────────────────────────┐        ┌──────────────────────────┐
│ 问答入口(QQ + dsh)        │        │ 审核/管理入口(网页看板)     │
│ · 只读:search/get_page   │        │ · 读 + 人确认后的写          │
│ · 必须引用出处,答不出明说 │        │ · 统一审核面(第七节)        │
└────────────┬─────────────┘        └────────────┬─────────────┘
             │ MCP(只读)                        │ MCP(读写,经人确认)
             └────────────────┬─────────────────┘
                              ▼
                     GBrain(PGLite/Postgres,混合检索)
                              │ sources + sync
                              ▼
                 knowledge-flow 知识库仓库(markdown)
```

- **问答入口**只挂 `search_knowledge` / `get_page` 两类只读工具,严禁写库;答不出就明说
  「知识库里没有相关内容」,不凭模型记忆补答(见 qq-qa-bot-plan 的 D1/D2)。
- **审核/管理入口**承载策展地图逐条审核、take 提案、drift / 矛盾报告、inbox 提升建议——统一审核面。
- 问答侧产生的「这条应该入库 / 和已有页面矛盾」提议,**以报告制进入统一审核面**,
  由人在看板确认后写入——与「机器不静默改语义」铁律一致(qq-qa-bot-plan M5 与本方案第七节汇合)。

---

## 五、写入权限模型(核心)

### 5.1 三条权限轨的完整定义

**轨道 B-捕获(直接写,无先审)**

- 对象:灵感、想法、随手笔记、临时备忘。
- 机制:`gbrain capture`(默认落 `inbox/YYYY-MM-DD-<hash8>`)+ signal-detector 环境捕获。
- 理由:噪音删除代价低,漏写几乎无代价——先审反而杀死了「随手记」的摩擦优势。

**轨道 B-搜集(直接写 + 留痕,主张级事后人审)**

- 对象:网页、API、会话记录等机器搜集的内容。
- 机制:enrich 管线(分层 spend)+ 原始响应先存 `put_raw_data` 留痕 + 逐事实 `[Source: ...]` 引用。
- 理由:机器生成的内容量大且可重跑,不值得页面级先审;但机器写出的**论断**需要人审,因此走主张级(take_proposals)报告制。

**轨道 A-策展(先审后写)**

- 对象:长篇幅资料、研究材料、需要系统性学习管理的文档。
- 机制:SOP-001 生成策展地图(含覆盖报告)→ 人在审核面逐条标记「确认入库 / 忽略 / 待更多原料」→ SOP-002 只处理确认条目。
- 理由:遗漏代价高,且入库过程必须对人透明——这是 KnowledgeFlow 的核心价值,GBrain 没有,必须新建。

**维护轨(所有轨道的更新 / 关联调整)**

- 机制:报告制——机器产出「拟改内容 + 依据」,人确认后**确定性执行**。
- 铁律:**确认动作就是调整动作**。报告里放的是具体 diff / 粘贴即用命令,人审的是那个具体内容;绝不允许「人点头 → 机器再跑一轮 LLM 思考再改」的二段式,那会在最后一步把黑盒重新放回来。

### 5.2 Dream Cycle 阶段分类:哪些自动、哪些报告制

GBrain 的 Dream Cycle 共 **23 个阶段**(`PHASE_SCOPE` 定义;其中 `skillopt` 默认关闭,活跃 22 个),
不是整体「事后加工」一团,必须按「是否改变知识语义」分类处理:

| 类别 | 阶段 | 对轨道 A 的处置 | 说明 |
|---|---|---|---|
| 纯结构(机械) | lint、backlinks、embed、sync、purge、recompute_emotional_weight、resolve_symbol_edges、orphans(报告型) | 自动执行 | 只做链接 / 分块 / embedding / 孤儿检测,不改语义 |
| 报告制(语义) | propose_takes、drift、suspected-contradictions | 全局启用,产出去统一审核面 | 机器只写报告 / 队列,**不落地内容** |
| 自动改语义 | synthesize、patterns、consolidate、synthesize_concepts、extract_facts / extract_atoms 写入 | **全局关闭,不保留自动执行** | 见 5.2.1:这些阶段会绕过人审自动改内容(甚至反向写盘) |

### 5.2.1 「轨道 A 只读」的落地机制——修正与实证(2026-08-25 源码复核)

**原方案此处的表述不成立,特此修正。** 初版方案写「配置上把自动改语义阶段钉死在轨道 B,
轨道 A 目录对它们只读」,依据的两根支柱经复核都不撑这个结论:

1. **PROTECTED 防的是提交通道,不是写入。** 源码 `ctx.remote !== false && isProtectedJobName(name)`
   只拒绝 **MCP 远程调用者**提交 synthesize / patterns / consolidate 三类 job(防 OAuth 客户端烧预算);
   **本地 CLI / autopilot 照常能提交,夜间 Dream Cycle 根本不经 job 提交通道,完全不受其影响。**
2. **不存在 per-slug / per-type 作用域过滤。** `phase-scope.ts` 的作用域只有 `source / mixed / global` 三档;
   mixed(如 synthesize、patterns)与 global(如 synthesize_concepts、drift、embed)阶段**全脑只跑一次**,
   无法按目录或类型圈定。
3. **比"改 DB"更直接:会反向写盘。** `src/core/cycle/synthesize.ts` 的 `writeReversePages` +
   `writeSummaryPage` 直接 `writeFileSync` 到 brain repo 目录——夜间全量 Dream Cycle 会在知识库目录里
   新建 / 改写 `.md` 文件。这不是理论风险,是实现行为。

**真实存在的杠杆(已验证)只有这些:**

| 杠杆 | 覆盖范围 | 出处 |
|---|---|---|
| config 阶段开关(`dream.<phase>.enabled` / `cycle.<phase>.enabled`) | patterns、synthesize、drift、conversation_facts_backfill、enrich_thin、skillopt | cycle.ts 的 onceForPhase 注释块 |
| pack-gating(`packDeclaresPhase`) | 仅 extract_atoms、synthesize_concepts(schema pack 未声明该阶段则跳过) | cycle.ts v0.41 T9 |
| per-source 隐式循环只跑确定性阶段 | 对非默认 source 的 `dream --source X` 只跑 SOURCE_FRESHNESS_PHASES(lint/backlinks/sync/extract/extract_facts/recompute_emotional_weight) | resolveCyclePhases |
| 调度层显式 phase 列表 | **consolidate 与 extract_facts 未发现 config 开关**,只能在调度时用显式 `--phase` 列表排除 | cycle.ts consolidate/extract_facts dispatch 无 enabled gate |
| `--dry-run` 预览 | 全阶段可预览不写(注意:synthesize 的 dry-run 仍可能产生 LLM 调用) | dream.ts |

**修正后的设计姿态:** 用户的治理模型本来就要求**一切语义变更走报告 → 人确认**,
所以正确做法不是「把自动改语义阶段钉到轨道 B」,而是**三层关闭**:config 开关关掉有开关的阶段
(synthesize、patterns 等自动改语义阶段)、pack-gating 不声明 extract_atoms/synthesize_concepts、
调度层显式 phase 列表排除无开关的 consolidate/extract_facts——只保留报告制阶段
(drift、propose_takes、suspected-contradictions)产出统一审核面。
这样轨道 A「只读」自然成立——因为全脑没有任何阶段再自动改语义。
代价:概念自动合成的**静默路径**关闭——但不是舍弃该能力,而是降级为**提案制**(报告制合成,见 5.4):机器扫库 → 草拟概念提案(附证据锚定)→ 人审批准 → SOP-002 确定性写入。快轨的单条论断仍走 take 提案人审。

**此结论作为 Phase 0 的强制实证项**(见 Phase 0 步骤 7):在试点 KB 上跑一轮完整 Dream Cycle,
前后对比文件哈希,验证「关闭自动改语义阶段后,知识库原文件零改动」。这一个实验同时验证或证伪整个第五节。

### 5.3 权限边界总表

| 可自动执行 | 需人确认后执行 |
|---|---|
| 结构维护:lint、backlinks、embed、sync、purge | 策展地图逐条确认 / 忽略 / 待更多原料 |
| 报告生成:drift、contradictions、take_proposals | 轨道 A 的页面写入(SOP-002) |
| 轨道 B 直接写入(capture / enrich + 留痕) | 轨道 B 机器论断的 promote(take accept) |
| inbox 扫描与提升建议 | 更新 / 合并 / 拆分 / 关联调整的落地 |
| (自动语义写入:不存在——三层关闭后全脑无静默语义路径) | 概念合成提案的逐条批准与落地(见 5.4) |

### 5.4 报告制合成:概念自动合成的提案制形态

三层关闭后,概念自动合成的**能力**保留、**静默路径**消失。标准形态是提案制(2026-08-25 决策):

> 机器扫库 → 草拟概念提案(附证据锚定)→ 人在统一审核面逐个批准 → SOP-002 确定性写入。

**这不是新管线**:一份合成提案在结构上就是一份「原料为内部语料的策展地图」——

| 策展地图(现有) | 合成提案(新增) |
|---|---|
| 原料 = 一篇外部文档 | 原料 = 库内已有页面 / 近期新增内容 |
| 实体清单 + 原文引用 | 概念清单 + 证据引用(哪些页面、哪些段落支撑该概念) |
| 覆盖报告(原文哪些节被扫过) | 扫描范围声明(哪个 source、哪个时间窗) |
| 人逐条标记 确认 / 忽略 / 待更多原料 | 人逐个概念标记 确认 / 忽略 |
| SOP-002 只处理 approved 条目 | SOP-002 原样复用,零改造 |

**落地细节(六项决策)**:

| 决策点 | 选择 | 理由 |
|---|---|---|
| 载体 | 页面类型 `synthesis_proposal`(或复用 `curation_map` + 来源标记,二选一见待确认 3),`status: pending-review → approved` | 与策展地图状态流同构,统一审核面直接加一个分组 |
| 粒度 | 每个概念一条、附证据链接,不整页一锅端 | 与策展地图逐条标记对齐;人可以只批 N 个中的 1 个 |
| 每次限量 | 单次提案 ≤5-10 个概念,按证据强度排序 | 概念数量失控 = 没人审得动(improvement-action-plan P2-3 超大审核负载的教训同样适用) |
| 执行 | approved → SOP-002 确定性写入,草稿文本即最终文本 | 「确认即执行」:人批的就是落盘的,中间不插第二轮 LLM |
| 触发 | 周度 Minions cron + 按需手动,spend controls 设预算 | 合成是 LLM 密集操作,与 MC-001 同频、成本封顶 |
| 溯源标记 | 合成页 frontmatter 标 `origin: machine-proposed` + `approved: 日期` | 事后可分清哪页出自机器提案;QA 通道引用时可带出处性质 |

**两条纪律**:

1. **`--once` 不作主路径**:它是「触发即确认」而非「内容级确认」——只作一次性批处理旧数据的兜底;常设机制必须走提案制。
2. **草稿质量 = 最终质量**:人批准的就是草稿文本本身,没有「批大方向、机器再润色」的二段式。合成提案的生成提示词须按 SOP-001 标准写(证据锚定、不确定标注、Agent 建议隔离)。

---

## 六、报告制事后加工:复用 GBrain 现成机制

「报告 + 提醒 + 人确认后执行」不是要新造的功能——GBrain 已经有一族现成机制,各自的粒度、触发时机、用途如下。我们的工作是**收拢**,不是**重造**。

| 机制 | 触发时机 | 干什么 | 人审形式 | 我们的复用 |
|---|---|---|---|---|
| `propose_takes` | 夜间 Dream Cycle | 把页面 prose 提案成可评分论断,写入 `take_proposals` 队列 | `gbrain takes propose` 逐条 accept / reject(J/K 审核界面) | 轨道 B 机器论断的主张级人审 |
| `drift`(默认关,`dream.drift.enabled`) | 夜间 Dream Cycle | 判断 takes 是否与近期 timeline 证据漂移,写 `reports/drift-<date>` | 报告页;v1 明确 auto_update 不改任何内容 | 轨道 A 维护轨的「过时检测」 |
| `eval suspected-contradictions` | 每日 Dream Cycle + doctor + MCP | 检索配对 + LLM 法官标矛盾,出带 `resolution_command` 的报告 | 粘贴即用命令 / `# manual review` 注释 | 轨道 A 维护轨的「冲突检测」 |
| 实体提取隔离车道 | 实体提取运行时 | 提议实体先入 `extraction_pending`,不进图 | `extraction_review` 人审放行 | 实体级人审 |
| reports skill + morning briefing | cron 输出 / 用户询问 | 定时摘要存 `reports/{category}/{date}.md`,交付前过 Actionability Gate | 用户主动读 | 每日简报入口 |
| ask-user 选择门 | 决策点 | 呈递 2-4 选项后**停轮等人** | 用户响应触发下一轮 | 危险操作 / 路由决策 |

> 以上是 GBrain 的现成机制;**报告制合成(概念合成的提案制形态)是本方案新建的第七个机制**——GBrain 没有对应物,设计见 5.4。

两个复用时的纪律:

1. **复用其队列和表,不复制一套**。统一审核面读的是 `take_proposals`、drift / contradictions 报告页、extraction 队列的原生数据。
2. **确认即执行**。复用 contradictions 的 `resolution_command` 模式:报告给出确定性命令,人审通过后确定性应用,中间不插入新的 LLM 判断。

---

## 七、统一审核面

这是产品的第一屏,也是 KnowledgeFlow 相对 GBrain 的最大增量。四类待审内容合并为一个收件箱:

```
┌────────────────────────────────────────────────┐
│  待审核收件箱(按内容类型分组,按优先级排序)         │
├────────────────────────────────────────────────┤
│  A. 策展地图待审   原料 → 覆盖报告 → 逐条标记     │
│     [确认入库] [忽略] [待更多原料]               │
│  B. take 提案      机器论断 → accept / reject    │
│  C. 报告类         drift / contradictions →      │
│     查看拟改 diff → [应用] / [忽略]              │
│  D. inbox 提升建议  同主题 ≥3 条 → 建议升正式页    │
└────────────────────────────────────────────────┘
```

### 7.1 四种审核粒度的定位

「粒度」= 人一次看到并做决定的单元。用同一份原料(一篇讲 RAG 的文章)贯穿说明:

| 粒度 | 单元 | 审什么 | 能否看见遗漏 |
|---|---|---|---|
| 实体级 | 一个实体要不要进图 | 机器说「这段提到 RAG / Chunking,建议建页」→ 逐个 yes/no | 否 |
| 主张级 | 一条可评分论断 | 「检索质量主要受 chunk 策略影响」要不要立为 take | 否 |
| 页面级 | 一整页 wiki | 整页草稿发布前给人看(GBrain 没有此级先审) | 否 |
| **策展地图级** | 一份原料的完整结构化提取 | 所有实体 + 论断 + 关系 + **覆盖报告** | **是** |

关键区别:实体级 / 主张级只能审「机器提了什么」,审不了「机器漏了什么」;
策展地图级带着覆盖报告,能把「第 4 节 0 条提取」这类遗漏信号暴露给人。
**防遗漏必须靠策展地图级审核,这是轨道 A 不能退化为 GBrain 细粒度队列的原因。**

### 7.2 与轨道映射

- 轨道 B 内容 → 主张级 / 实体级审核(便宜、细粒度、机器提议)。
- 轨道 A 内容 → 策展地图级审核(带覆盖报告,防遗漏)。
- 概念合成提案(5.4)→ 同策展地图级视图:证据锚定 + 扫描范围声明,复用 A 类收件箱交互。
- 两种粒度映射到审核面的不同视图,不强行统一。

---

## 八、分阶段路线图

### Phase 0 — 零代码验证(1 天)

**目标:** 证明「文件层 + 引擎层」的粘合成立,再写任何代码。

**环境现状(2026-08-24 已摸底)**

- Node v22.22.3 ✅ / git 2.54.0 ✅ / winget ✅ / **Bun ❌ 未安装**
- clone 无 `node_modules`,`bun install` 是唯一需要网络的一步(bunfig.toml 无镜像配置,不通则配 npmmirror)
- 已有 7 个知识库在 `E:\KnowledgeBase`(合计约 143 个 md 文件,远在 1,000 页舒适线内):
  Agent_Learning / Agent_Learning_new / Curator_Design / Environment_Learning /
  Hermes_Learning / Job_DUI / Loop_Learning
- 试点选 **Curator_Design**(12 个 md 文件,最小);**避开 Job_DUI**(含真实简历文件)。
  ⚠️ 任何 KB 内容都不得提交进 knowledge-flow 仓库(隐私铁律)。

**逐步清单(Windows PowerShell)**

- [ ] **0. 安装 Bun**(GBrain 的运行时,要求 ≥ 1.3.10)
  - 方式一(已确认可用):`winget install --id Oven-sh.Bun -e`
  - 方式二(官方脚本):`powershell -c "irm bun.sh/install.ps1 | iex"`
  - 重开终端验证:`bun --version`
- [ ] **1. 安装依赖**(唯一需要网络的一步;失败 = 本阶段的阻塞点)
  - `cd E:\Workstation\code_space\gbrain\gbrain`
  - `bun install`
  - 验证:`node_modules` 生成、命令无报错;`[gbrain] postinstall skipped` 提示属正常,忽略
  - 网络不通的备选:`bun config set registry https://registry.npmmirror.com` 后重试
- [ ] **2. 建立 gbrain 命令入口**
  - 在 clone 目录执行:`bun link`(Windows 会生成 gbrain shim 进 PATH)
  - 验证:`gbrain --version` 输出 `0.46.28.0`
- [ ] **3. 初始化本地脑(PGLite)**
  - 先 keyless 验证管道:`gbrain init --pglite --no-embedding`
  - 验证:`gbrain doctor` 核心项通过;数据落在 `~/.gbrain/brain.pglite`
  - 有 key 则顺手接:`DEEPSEEK_API_KEY`(chat)+ DashScope / 智谱(embedding);
    无 key 不影响本阶段主路径(关键词检索可用)
- [ ] **4. 注册试点知识库为 source**
  - `gbrain sources add curator-design --path E:\KnowledgeBase\Curator_Design`
  - 验证:`gbrain sources list` 可见 curator-design
- [ ] **5. 同步**
  - `gbrain sync --source curator-design`(首次全量;之后 `--watch` 增量)
  - 验证:`gbrain stats` 的页数与 KB 内 md 文件数吻合
- [ ] **6. 验证四连**
  - `gbrain search "策展"` → 返回 Curator_Design 的 wiki 页面(**keyless 可用**)
  - `gbrain graph-query ...` → 出图(**keyless 可用**,纯 DB 操作)
  - `gbrain think "..."` → 需 chat key(DeepSeek),keyless 时此步跳过
  - `gbrain search --explain "..."` → 看混合检索各阶段归因(向量臂需 embedding key)
- [ ] **7. Dream Cycle 实证(第五节安全生命线的验证,不可跳过)**
  1. 快照文件哈希:`Get-ChildItem E:\KnowledgeBase\Curator_Design -Recurse -File | Get-FileHash | Out-File hashes-before.csv`
  2. 预览:`gbrain dream --dry-run --json` → 记录哪些阶段计划执行、哪些会写页面
  3. 基线观察:直接跑一轮完整 `gbrain dream --json` → 对比哈希,记录**未加控制时**哪些阶段改了哪些文件
     (预期 synthesize 的反向写盘在此暴露)
  4. 三层关闭:config 关 synthesize/patterns 等 + pack 不声明 extract_atoms/synthesize_concepts +
     显式 phase 列表排除 consolidate/extract_facts → 再跑一轮 → 对比哈希
  5. 结论回填 5.2.1:哪个开关有效、哪个阶段仍写盘、缺口在哪
- [ ] **8. 验收对照**
  - 文件层照旧是人审断点、GBrain 只做引擎——同步不改变任何 KB 原文件
  - 步骤 7 证实在三层关闭后知识库原文件零改动(仅允许预期的确定性阶段行为)
  - 知识库页面可检索、可出图;结论成立则进入 Phase 1

**通过标准:** 步骤 0-8 全部打勾;`search` 命中 Curator_Design 页面,`graph-query` 出图,
且步骤 7 证实「三层关闭后 `E:\KnowledgeBase` 原文件零改动」。步骤 7 若证伪(仍有关闭不住的写盘),
第五节须重写,不进入 Phase 1。

### Phase 1 — 管道落地(核心阶段)

**目标:** 把 KnowledgeFlow 的 SOP 从「复制粘贴的 prompt」变成「可执行的技能」,并把策展地图级人审闸门立起来。
**工作量(粗估,待拆解确认):** 技能层 2-4 天;状态流 + 最小审核网页 1-2 周(前端从零)。
**前置:** 动工前先产出一页纸拆解(技能清单、状态流转表、最小审核页的接口清单)。

- 写三个 GBrain 技能并打包成 skillpack:`sop-001-extract`(穷举提取 → 策展地图页面)、`sop-002-curate`(只处理 approved 条目,写前查重 + SCHEMA 校验)、`sop-003-lint`(写后自检)。
- 策展地图定为页面类型 `curation_map`,`add_link` 链回原料页;frontmatter 携带 `status: pending-review`。
- 人审闸门:交付**专门的网页看板最小版**(已决策)——策展地图逐条标记「确认入库 / 忽略 / 待更多原料」+
  take 提案 accept / reject,把 status 改为 `approved`,SOP-002 只读 approved。与 Phase 3 完整看板解耦,
  先立闸门再美化。
- 原料溯源:`put_raw_data` 存原始资料 + SHA256 指纹(C2 硬约束机器化)。

**验收:** 一份长文走完「原料 → 策展地图 → 人审 → 入库」全流程,且未 approve 的内容不进入检索。

### Phase 2 — 元认知(复用 Dream Cycle + Minions)

**目标:** 把 MC-001 六维度用 GBrain 原生能力落地,不重造。

| MC-001 维度 | GBrain 落地 | 省掉的活 |
|---|---|---|
| 1 遗漏检测 | chunk embeddings + contradictions 配对管线 | 自建 embedding 比对 |
| 2 质量抽检 | Minions cron job + `gbrain think` | Hermes skill |
| 3 跨页面关联发现 | chunk embeddings 查「高相似无链接」页对 | 自建 unified-index.json |
| 4 概念漂移 | `find_trajectory` + timeline | log.md 手工解析 |
| 5 结构趋势 | `gbrain doctor` / `orphans`(均 --json) | 自写规则统计 |
| 6 仪表盘 | viz 应用接入 doctor 数据 | 自建 kb-health.html |

- 定时执行改用 Minions + cron-scheduler skill,替代 build-plan 中的 Hermes cron 假设。
- 成本上限复用 GBrain 的 spend controls,替代「手工数 LLM 调用」。
- **报告制合成(5.4)在本阶段落地**——本阶段唯一的新建件(其余皆复用):周度 Minions cron 扫库 → 概念合成提案 → 统一审核面 → 批准后 SOP-002 写入。

**验收:** 每周自动产出健康报告 + 漂移 / 矛盾 / 高相似无链接清单 + 概念合成提案(≤10 条/次),全部进统一审核面。

### Phase 3 — 可视化(主交付)

**目标:** 构建可视化知识管理 App。GBrain 提供数据,app 提供界面。
**工作量:暂无估计——这是全方案研究最薄、风险最高的一层。**
**前置:** 动工前必须单独产出一页纸拆解(界面清单、数据接口、G6 / React Flow / ECharts 分工、里程碑);
建议在 Phase 1 的最小审核页上先验证前端技术栈,把不确定性前移到小成本阶段。

- **知识图谱视图**:页面 = 节点,typed links = 边(数据源 `traverse_graph`)。KnowledgeFlow 规模是几十~几百页,可全量渲染——这是相对 GBrain 146K 页规模的差异化空间。
- **策展管线看板**:原料 → 策展地图 → 人审 → 入库的状态流。
- **覆盖报告图表**:提取密度、节级覆盖、不确定性分布(策展地图第 10 节数据直接可视化)。
- **统一审核面**:第七节的四类收件箱正式落地。
- **健康仪表盘 + 轨迹时间线**:doctor 数据 + `find_trajectory`。
- 复用 GBrain admin SPA 的 dark theme 设计体系(DESIGN.md 的 color / typography tokens)。

**验收:** 从一张图出发能点击进入页面、看覆盖报告、完成一次审核操作。

### Phase 4 — 增强

- `volunteer_context` 主动检索(push 上下文)接入日常问答。
- 多知识库:用 GBrain mounts + 联邦搜索替代路由表;跨库查询由 agent 决策(latent-space 联邦)。
- 轨迹时间线、chronicle 编年视图完善。

### 与 qq-qa-bot-plan(M0-M5)的轨道对照

两条产品轨道共享 GBrain 基础设施,合并视图如下:

| qq-qa-bot-plan | 本方案 | 关系 |
|---|---|---|
| M0 账号与通道决策 | — | 独立 |
| M1 检索打通 | Phase 0 | **同一件事**(init + sources + sync + 索引);M1 依赖 Phase 0 完成 |
| M2/M3 dsh + 网关 + QQ 接入 | Phase 4 的 agent 面(提前) | qq 轨道提前到 M2/M3,不阻塞 Phase 1-3 |
| M4 硬化(eval、成本帽、注入防御) | Phase 2 元认知的一部分 | 共享 eval 纪律与 spend controls |
| M5 多库路由 / 报告制写回 | Phase 2 / 4 | **依赖 Phase 1 的统一审核面** |

结论:两条轨道可并行。**Phase 0 是共同前置**;问答轨道(M1-M4)与策展轨道(Phase 1-3)互不阻塞,
唯 M5 依赖 Phase 1 的统一审核面先行。

---

## 九、关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 是否 fork GBrain | **不 fork** | GBrain 迭代极快(0.46.x 周级),fork 即失去上游升级、安全补丁与技能生态 |
| 集成模式 | MCP 服务模式优先(`gbrain serve --http`,OAuth);库模式(直接 import `gbrain/engine` 等 exports)留给离线单机场景 | 服务模式解耦,升级自由;库模式控制深但耦合重 |
| Agent 与模型分工 | DeepSeek harness 做对话编排;GBrain 内部加工也用 `deepseek:deepseek-v4-*`;embedding 另配 DashScope / 智谱 / 本地 BGE-M3 | DeepSeek 是 GBrain 一等 chat recipe(工具 + 子 agent 循环都支持),但无 embedding 模型 |
| 多知识库映射 | 每个 KB = 一个 source(一个脑多 source);各 KB SCHEMA.md = per-source schema pack | 保留「不同内容不同知识库」规范,联邦搜索跨库召回,路由表 / 联合索引删除 |
| 部署形态 | 初期本地 PGLite 单机,长期远程多端;集成面走 MCP 服务模式 | 本地切远程零重架构(`serve --http` + 换引擎即可) |
| 人审闸门实现 | 策展地图 `status` 状态流(pending → approved)+ 复用 `take_proposals` 先例 | 最小实现;GBrain 的「队列 → 显式 accept 才写回」已验证是正确姿态 |
| 审核粒度 | 轨道 A 用策展地图级;轨道 B 用主张级 / 实体级 | 防遗漏靠覆盖报告,防噪音靠细粒度队列,两者不强行统一 |
| 事后加工权限 | 结构阶段全局自动;报告制阶段全局启用;**自动改语义阶段三层关闭**(config 开关 + pack-gating + 调度层排除) | 防 Dream Cycle 污染人审过的策展成果;「钉死到轨道 B」经复核无此机制,见 5.2.1 |
| 确认即执行 | 报告携带具体 diff / 粘贴即用命令,确认即确定性应用 | 杜绝「人确认 → 机器再想一遍」的二段式黑盒 |
| 可视化技术栈 | React + AntV G6(知识图谱)+ React Flow(管线看板)+ ECharts(图表);独立 app,不复用 admin SPA | 国内生态、中文文档;具体选型 Phase 3 前再最终确认 |

---

## 十、风险与对策

| 风险 | 后果 | 对策 |
|---|---|---|
| fork GBrain | 升级、安全、生态全部脱钩 | 作为依赖 / 服务用,集成面保持薄(见「关键设计决策」) |
| Dream Cycle 自动改语义阶段污染轨道 A | 机器绕过人审策展(甚至反向改写知识库 .md 文件),悖论白解决 | 三层关闭:config 开关(synthesize/patterns)+ pack-gating(extract_atoms/synthesize_concepts)+ 调度层排除(consolidate/extract_facts);Phase 0 实证验证原文件零改动 |
| 「人确认后调整」做成二段式 | 最后一步重新引入黑盒 | 报告制 = 拟改 diff + 确定性命令,确认即执行 |
| 审核粒度过细(全退化为 take 级) | 防不住遗漏 | 轨道 A 必须保策展地图级 + 覆盖报告 |
| GBrain 版本升级破坏集成面 | 技能 / viz 失效 | 通过 MCP 协议 + 官方 exports 集成,不依赖内部实现;升级后跑 Phase 0 验收清单 |
| 隐私泄露 | 个人知识库暴露 | 默认 PGLite 本地;公开文档沿用 KnowledgeFlow 占位符规则 |

---

## 十一、决策记录与待确认

### 已决策(2026-08-24)

| 问题 | 决策 | 对方案的影响 |
|---|---|---|
| 成品形态 | 基于 DeepSeek harness 搭 agent;前端看板做系统展示与交互管理 | 已写入 4.1(两个模型位置的分工表) |
| 多知识库语义 | 项目规范即「不同内容建立不同知识库」 | 已写入 4.2:每个 KB = 一个 source + per-source schema pack |
| 部署形态 | 初期纯本地单机,长期远程多端 | Phase 0 用 PGLite;MCP 服务模式保证远程零重架构 |
| GBrain 获取方式 | git clone 已完成(`E:\Workstation\code_space\gbrain\gbrain`,master HEAD) | 4.2 已更新;三份副本待整理(见 4.2 仓库整理待办) |
| 可视化技术栈 | 推荐 React + G6 / React Flow / ECharts | 已写入决策表;最终选型 Phase 3 前再确认 |
| 审核面形态 | **专门的网页看板** | 与 Phase 3 可视化解耦:Phase 1 先交付最小审核页(策展地图逐条标记 + take 提案 accept/reject),Phase 3 再整合进完整看板 |
| 规模定位 | **未来肯定多库**;单脑舒适线 < 1,000 页,超线无损迁 Postgres | 已写入 4.3 规模边界;跨库总量按单脑所有 source 之和计 |

### 已决策(2026-08-25 追补)

| 问题 | 决策 | 对方案的影响 |
|---|---|---|
| 概念自动合成的去留 | **保留能力,降级为提案制**(报告制合成):静默路径随三层关闭消失,提案路径为标准形态 | 新增 5.4;Phase 2 增落地条目;5.2.1 代价段、5.3、第六节、7.2 同步改写 |
| 问答入口 | **QQ + dsh**(qq-qa-bot-plan),只读检索;网页看板做审核与管理 | 已写入 4.4 双入口形态;qq 计划 M1 依赖本方案 Phase 0 |

### 仍待确认

1. **可视化技术栈最终选型**:G6 / ECharts / React Flow 的组合是推荐方案,Phase 3 动手前按实际界面再定。
2. **远程部署的具体形态**(长期):Supabase Pro($25/mo,托管)还是自建 Postgres + pgvector(Docker/服务器)——不影响 Phase 0-2,远程阶段再拍。
3. **合成提案的载体与频率**(5.4):独立页面类型 `synthesis_proposal`,还是复用 `curation_map` + 来源标记;周度自动 + 按需手动是否够用——Phase 2 动工前定。
4. **跨文档模型名冲突(需修正 qq-qa-bot-plan)**:其 D6 / 成本节使用的
   `deepseek-chat`(V3.2)/ `deepseek-reasoner` 已于 2026-07-24 被 DeepSeek 官方退役(GBrain 源码注明 API 404),
   应统一为 `deepseek-v4-flash` / `deepseek-v4-pro`(以官方最新文档为准,上线前实测);
   另其 M1 的「SiliconFlow」不在 GBrain embedding 目录内(本地 BGE-M3 可,SiliconFlow 需 LiteLLM 代理)。

---

## 十二、附录:GBrain 关键参考点

本方案涉及的所有 GBrain 能力,其权威出处(路径相对 GBrain 仓库根):

| 能力 | 出处 |
|---|---|
| 引擎契约(140+ 方法) | `src/core/engine.ts` |
| 操作契约源(100+ 操作,CLI + MCP 同源) | `src/core/operations.ts`(facade,实现在 `src/core/ops/*`) |
| Dream Cycle 阶段(PHASE_SCOPE 定义 23 个,skillopt 默认关) | `src/core/cycle.ts`(调度)+ `src/core/cycle/*.ts`(逐阶段文件)+ `src/core/cycle/phase-scope.ts`(作用域);`phases/` 子目录仅 consolidate.ts |
| take 提案队列 | `src/core/take-proposals.ts` + `gbrain takes propose` |
| 矛盾探测 | `docs/contradictions.md` + `gbrain eval suspected-contradictions` |
| 漂移检测(报告制) | `src/core/cycle.ts`(drift 阶段,默认关) |
| 实体提取隔离车道 | `extract_entities` / `extraction_pending` / `extraction_review` 操作 |
| 报告与晨间简报 | `skills/reports/SKILL.md` |
| 选择门模式 | `skills/ask-user/SKILL.md` |
| 信号捕获 | `skills/signal-detector/SKILL.md` |
| 富化管线 | `docs/guides/enrichment-pipeline.md` + `skills/enrich/SKILL.md` |
| 实时同步 | `docs/guides/live-sync.md`(`sources add` + `sync --watch`) |
| 两轴模型(brain ⊥ source) | `docs/architecture/brains-and-sources.md` |
| Schema packs | `docs/architecture/schema-packs.md` |
| 检索理论 | `docs/architecture/RETRIEVAL.md` |
| MCP / 部署 | `docs/mcp/DEPLOY.md`、`gbrain serve --http` |
| 设计体系(dark theme / SVG 图表) | `DESIGN.md` + `admin/src/` |
| 成本控制 | `docs/operations/spend-controls.md` |
| 技能分发(skillpack) | `docs/skillpack-anatomy.md` |

### 术语对照

| KnowledgeFlow | GBrain |
|---|---|
| 知识库 | brain(数据库)+ source(库内仓库) |
| 页面 | page(唯一键 source_id + slug) |
| wikilink | link(typed edge,自动抽取) |
| SCHEMA 页面 type | schema pack page type |
| 原料 | raw_data 行 + files 附件 |
| 策展地图 | page(type: curation_map,status 状态流) |
| 论断 | take / fact |
| 人审断点 | 统一审核面(新建)+ take_proposals / extraction 队列(复用) |

---

> 最后更新:2026-08-25
> 基于 KnowledgeFlow v2.2.1 现状与 GBrain git clone master HEAD `4e4677b1`
> (v0.46.28.0 + 7 个发布后修复)编写,2026-08-25 复核。
