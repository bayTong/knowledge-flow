# Changelog

---

## Unreleased

### 治理式捕获架构与 C1 确定性基础

- **建立主题级设计权威**：新增需求与治理基线、设计权威与冲突登记、SOP-000A、捕获与路由规范、Capture Envelope v1、MVP-0 四操作契约、实现拆解与编码执行方案。
- **冻结语义写入边界**：捕获允许先保存后审核；模型只生成路由或策展提案；旧 SOP-002 及其写入提示词暂停执行，策展地图迁移到 `proposals/curation-maps/`。
- **完成 C0–C1**：新增内部 `knowledgeflow-capture` Python 包，实现结构化错误与三态提交状态、UUIDv7、Payload/Payload Set/Request Fingerprint/Envelope 四类哈希，以及受限 YAML 语法门禁、schema 校验和确定性发射。
- **建立可复现验证**：加入 30 项自动化测试和三份 JSON/YAML golden fixture；标准与显式测试发现方式均通过。golden 文件固定使用 LF，避免 Windows checkout 改变契约字节。
- **清理仓库临时产物**：删除误提交的 `.eval-tmp` 合成数据，补充本地环境、构建产物和实验目录忽略规则。
- **明确尚未交付范围**：Capture Store 初始化、四个文本操作、State Event、幂等索引、人工路由、GBrain、Harness、UI 和可信知识写入均未实现。

`pyproject.toml` 中的 `0.1.0.dev0` 是内部捕获包版本，独立于 KnowledgeFlow 文档项目当前的 v2.x 历史版本；正式发布策略待 MVP-0 闭环后再确定。

## v2.2.1 — 2026-08-24

### 脚本与规范对齐（improvement-action-plan P0-1 / P0-2 / P0-3）

- **SOP-003 检查项 6 升级为两档阈值**：>300 行警告（拆分候选）、>500 行错误（必须拆分红线）。原 500 行红线仅存在于脚本实现（`LINE_LIMIT_ERROR`），现写入规范——脚本与规范自创口径的分歧按「对规范是净改进」方向解决
- **SCHEMA 模板第五章注册格式标准化**：注册标签统一以反引号包裹（`` `标签名` ``，不带 `#`），`templates/SCHEMA-template.md` 与 `docs/sop-v2-full.md` SOP-000 内嵌模板同步；`scripts/lint.py` 标签审计改为解析该格式（只认标签体系章内的表格行，向后兼容 `` `#标签` `` 旧格式），并实现「已注册但未使用」提醒——修复原实现对模板格式 SCHEMA 解析恒为空集、标签审计静默失效的缺陷
- **lint.py 补齐 4 项缺失检查**：index 完整性（检查 3）、日志轮转（检查 7，仅报告）、entity 孤立（检查 8，Error 级）、图谱过滤规则（检查 9，仅报告；非 Obsidian 知识库跳过）
- **lint.py 口径对齐**：frontmatter 检查从 3 字段扩展至 7 字段 + type 合法性 + title 格式匹配（检查 4）；孤立页面从 Notice 升为 Error（检查 2，与 SOP-003 输出级别一致）；新增行内代码 wikilink 排除（检查 1，SOP-003 实现说明要求）；所有消息加 `[检查N]` 前缀，与 SOP-003 检查项编号一一对应
- **脚本 Windows 健壮性**：三个脚本 stdout/stderr 重配置为 UTF-8（修复 GBK 控制台 `UnicodeEncodeError` 崩溃）、文件读取改为 `utf-8-sig`（修复带 BOM 文件 frontmatter 误判缺失）
- **index-generator.py 对齐 SCHEMA 规范**：slug 改为纯文件名（不含路径与扩展名，SCHEMA 第六章）；条目尾注从「type — tags」改为机械式一句话摘要（正文首段截断，frontmatter 缺失时降级为文件名，注明建议人工润色）；分组对齐第七章（concept/comparison 按模块、entity 归「实体」段、query 归「问答」段）；头部统计行对齐 SOP-000 步骤 4 模板；`--write` 显式 LF 写入，预览输出与写入内容字节级一致；文档字符串补免责说明（全量重生成会覆盖手工摘要，建议配合 git 审阅）

---

## v2.2 — 2026-07-13

### 自适应提取分层 + 独立覆盖审计

核心变更：从一刀切多轮次改为自适应模式——默认单次提取 + 独立覆盖审计，长文自动升级。

**新增文件**：
- `prompts/sop-001-modeA.md` — Mode A 提取模板（第 1-9 节，默认推荐）
- `prompts/sop-001-modeA-fast.md` — Mode A-fast 快速路径（含自检覆盖报告）
- `prompts/sop-001-modeA-auditor.md` — Mode A 独立覆盖审计员（第 10 节）
- `prompts/sop-001-modeB-pass1-entities-claims.md` — Mode B Pass 1（实体+论点合并）

**改名**：统一 `modeA/modeB/modeBC/modeC` 命名规则
- `sop-001-rough-reader.md` → `sop-001-modeBC-assembler.md`
- `sop-001-pass1-entities.md` → `sop-001-modeC-pass1-entities.md`
- `sop-001-pass2-relationships.md` → `sop-001-modeBC-pass2-relationships.md`
- `sop-001-pass3-claims.md` → `sop-001-modeC-pass3-claims.md`

**策展地图新第 10 节「覆盖报告」**（不新增 LLM 调用）：
- Mode A 默认：独立审计（auditor 对照源文）
- Mode A-fast 可选：自检覆盖
- Mode B/C：交叉校验（assembler 对照独立 Pass 产出）

**四种提取模式**：
- Mode A（默认）：提取 + 独立审计 + 策展 = 3 次 LLM
- Mode A-fast：提取含自检 + 策展 = 2 次 LLM（< 3000 字可选）
- Mode B：2 Pass + 轻量组装 + 策展 = 4 次 LLM（> 10000 字自动触发）
- Mode C：3 Pass + 完整组装 + 策展 = 5 次 LLM（人审触发）

**文档更新**：
- `extraction-interface.md` 新增第 10 节覆盖报告格式
- `prompts/README.md` 重写（四种模式选择指南 + 人审流程）
- `docs/sop-v2-full.md` 策展地图 9→10 节，字数阈值统一
- `docs/build-plan.md` 阶段 1 更新
- `docs/adaptive-extraction-plan.md` — 新增修改方案文档

### 项目工程化补全——prompts/ 目录 + 术语统一 + 文档合并

v2.0 完成了方法论核心（SOP-000~006），但缺少让用户「拿起来就能用」的桥接层。v2.1 将其补齐。

#### 新增：`prompts/` 目录（8 个文件）

项目核心交付物的缺失部分——LLM-agnostic 提示词模板，使用 `{{PLACEHOLDER}}` 占位符，不绑定任何特定 LLM 工具。

| 文件 | 用途 |
|------|------|
| `prompts/README.md` | 模板使用说明（格式、占位符、接入不同 LLM 工具的方式） |
| `prompts/sop-001-rough-reader.md` | SOP-001 组装模板（将三份 Pass 输出组装为完整策展地图） |
| `prompts/sop-001-pass1-entities.md` | Pass 1：全景概括 + 提取层次 + 实体清单 |
| `prompts/sop-001-pass2-relationships.md` | Pass 2：关系提取 |
| `prompts/sop-001-pass3-claims.md` | Pass 3：论点与主张提取 |
| `prompts/sop-002-curator.md` | SOP-002 策展入库（基于审核过的策展地图） |
| `prompts/sop-003-lint.md` | SOP-003 知识库健康扫描 |
| `prompts/extraction-interface.md` | 提取接口技术规范（所有 prompt 的格式权威参考） |

所有模板使用 `.md` 扩展名——在 GitHub 上自动渲染标题/表格/代码块，复制进 LLM 时 markdown 标记本身是结构信号。

#### 术语统一：「阅读地图」→「策展地图」

> （本节为历史边界标注；v2.0 条目中的术语已随 v2.1 同步更新为「策展地图」。v2.0 原始文档使用的是「阅读地图」。）

全局改名原因：「策展地图（Curation Map）」更精确地描述了该产物的角色——它是穷举提取的结构化产物，是人审和策展决策的核心参考面。「阅读」暗示被动消费，与 SOP-002「策展入库」术语不一致。

影响范围（6 个文件）：`docs/sop-v2-full.md`、`README.md`、`README-zh.md`、`CHANGELOG.md`、`templates/SCHEMA-template.md`、`examples/curation-map-example.md`（文件重命名）。`archive/v1.0/` 保留历史术语不变。

#### 文档合并

- `docs/second-brain-roadmap.md` → 精简为 `docs/second-brain-vision.md`（战略愿景，1 页）。原详细执行计划保留在 `docs/build-plan.md` 中。
- `docs/project-gap-analysis.md` → **删除**。一次性快照，状态已失准，内容已被 build-plan 覆盖。
- `docs/build-plan.md` 定为外置第二大脑项目的**唯一权威路线图**。

#### 其他

- `.gitignore`：补齐 Python 缓存规则（`__pycache__/`, `*.py[cod]`, `*.pyo`）
- README ×2：更新项目结构图（反映 `prompts/` 目录和 `docs/` 下的实际文件）；加入 `prompts/` 使用说明

---

## v2.0 — 2026-07-06

### 架构重构：两阶段管线（粗读器 → 策展入库）

v1.0 的核心矛盾：提取和策展合并在同一 SOP 中，Agent 必须在穷举提取概念的同时暗中做重要性判断——这两个认知任务是冲突的。Agent 提取出的东西已经是它「认为值得入库」的子集，用户无法验证 Agent 漏掉了什么。

v2.0 的解决方案：将原 SOP-001 拆分为两个独立的 SOP。

#### 新增 SOP-001：粗读器（策展地图）

- **穷举提取，不做筛选**（C5 硬约束）——Agent 从原料中提取所有概念、实体、关系、事实主张，不判断重要性
- **7 字段提取接口**——每条提取必须包含：标识符、名称、所属层次、一句话描述、原文引用、置信度、不确定原因
- **5 种不确定原因分类**——来源不可靠 / Agent 理解局限 / 原文模糊 / 信息不完整 / 总结压缩损失
- **全景概括**——先逐段覆盖缩写，再拼接整合为连贯全景叙述，确保 Agent 在提取前真正理解了原料
- **缺口分析**——基于用户目标（先问用户「你想从中获得什么」）列出原料应涵盖但未涵盖的内容
- **SCHEMA 建议**——冷启动时推导完整 SCHEMA，已有 SCHEMA 时做差异分析
- **Agent 建议严格隔离**——独立子标题 + 允许/禁止清单，防止建议污染事实层
- **7 条硬约束**（C1–C7）——其中 5 条为禁止项（☒），2 条为强制义务（☑）
- **规模分级**——四级原料规模（<500 / 500-5000 / 5000-20000 / >20000 字），各有不同策略
- **覆盖盲区声明**（C6）——超长原料必须列出未细读的章节
- **轻量领域门禁**——从「确定属于」降级为「不显然不属于」，粗读前快速筛而非阻止
- ☒ 不创建任何 wiki 页面——只产策展地图，等人审核

#### 新增 SOP-002：策展入库

吸收原 SOP-001 的步骤 2（定向）、2.5（领域门禁）、4（决策树）、5（写入+4 套模板+8 条通用约束）、5.0→4（SCHEMA 同步检查）、6（导航更新）、7（自检 8 项）、8（报告）。

关键变更：

- **操作对象从「Agent 自己的提取结果」改为「策展地图中用户确认入库的条目」**——Agent 只处理人类已审核的内容
- **新增步骤 1（验证前置）**——验证 raw 原料 SHA256 + 策展地图审核状态 + 提取确认条目 + 确认 SCHEMA 版本
- **全文搜索不可跳过**——步骤 2.3 从建议升级为硬性要求，且给出了跳过它会导致的退化模式（两份页面讲同一件事）
- **标签注册死锁问题解决**——v1.0 中标签需先在 SCHEMA 注册才能使用，但标签定义又来自对原料的理解。v2.0 的粗读器只提取不注册，策展时才在步骤 4 统一注册，顺序天然合理

#### 其他 SOP 变更

| SOP | 变更 |
|-----|------|
| SOP-000 | **6 处微调**：步骤 2 新增 `raw/_curation-maps/` 目录；步骤 6 拆为 6a（粗读）→ 6b（人审）→ 6c（策展）；步骤 7 检查项 ⑤ 增补策展地图要求、检查项 ⑥ 保证来源改为 SOP-002；步骤 9 报告增加「用户暂停审核」中间态 |
| SOP-003 | 原 SOP-002，编号后移。**新增检查项 9：图谱过滤规则**——检测 Obsidian 关闭时自动覆写 `graph.json` 导致 SCHEMA 文件污染图谱的已知陷阱。轻量版仍为 3 项；完整版从 8 项增至 9 项。交叉引用已同步更新 |
| SOP-004 | 原 SOP-003，编号后移。交叉引用已同步更新 |
| SOP-005 | 原 SOP-004，编号后移。交叉引用已同步更新 |
| SOP-006 | 原 SOP-005，编号后移。**出口修改**：用户选「入库」后不再走原 SOP-001，改为：导出对话 + 计算 SHA256 + 生成简化策展地图 → 调用 SOP-002（策展入库）。跳过完整粗读器的理由：用户刚刚参与了对话，已经实时审核了内容——不需要再粗读一遍 |

#### 编号对照

```
旧 → 新
SOP-000 → SOP-000（6 处微调）
SOP-001 → 删除（拆分为新 SOP-001 + SOP-002）
SOP-002 → SOP-003
SOP-003 → SOP-004
SOP-004 → SOP-005
SOP-005 → SOP-006
```

---

## v1.0 — 初版

### 首次完整 SOP 体系

- **6 个 SOP**：SOP-000（初始化）至 SOP-005（话题切换提炼提案）
- **单阶段摄入**：原 SOP-001 同时完成提取、决策、写入——一步从原料到 wiki 页面
- **三层防御体系**：SOP-001 自检（增量）→ SOP-002 全量 Lint（累积）→ SOP-003 SCHEMA 一致性（连锁）
- **领域门禁**三级出口：☑ 继续 / ⚠ 部分提取 / ☒ 人工介入
- **4 套页面模板**：concept / comparison / entity / query
- **8 条写入通用约束**
- **批量摄入模式**：多原料时合并执行查重
- **人类审查面缺失**——这是 v1.0 最根本的架构局限，也是驱动 v2.0 重构的核心动力

### 归档位置

v1.0 原始文档已归档至 [`archive/v1.0/`](archive/v1.0/)：
- [`sop-v1-original.md`](archive/v1.0/sop-v1-original.md) — v1.0 完整 SOP 规范原文
- [`README.md`](archive/v1.0/README.md) — v1.0 局限性说明
