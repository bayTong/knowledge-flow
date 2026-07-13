# Prompt 模板使用说明

本文档说明 `prompts/` 目录下的 LLM-agnostic 提示词模板的使用方式、提取模式选择、覆盖报告机制、以及如何接入不同的 LLM 工具。

---

## 一、提取模式选择

KnowledgeFlow 提供四种提取模式，按成本和可靠性递进：

| 模式 | LLM 调用（含策展） | 覆盖报告 | 适用场景 |
|------|-------------------|---------|---------|
| **Mode A（默认）** | 3 次 | 独立审计 | 默认路径。提取 + 独立覆盖审查分离——飞行员和塔台是不同的人 |
| **Mode A-fast** | 2 次 | 自检 | < 3000 字短文 + 用户对质量有信心。覆盖报告与提取同一调用 |
| **Mode B（2 Pass）** | 4 次 | 交叉校验 | > 10000 字长文，或人审发现 Mode A 遗漏。Pass 1 合并实体+论点，Pass 2 独立关系 |
| **Mode C（3 Pass）** | 5 次 | 交叉校验 | 人审发现 Mode B 仍不够。实体/关系/论点三 Pass 各司其职——准确性最高 |

### 模式选择决策

```
if 源文字数 > 10000:
    → 至少模式 B（长文注意力衰减显著）

else if 源文字数 < 3000 且用户确认使用快速路径:
    → 模式 A-fast（2 次 LLM，覆盖报告为自检）

else:
    → 模式 A（默认 3 次 LLM，覆盖报告为独立审计）

人审策展地图时发现遗漏 → 升级到更高模式重新提取整篇。
```

---

## 二、文件索引

### 提取模板

| 文件 | 模式 | 用途 |
|------|------|------|
| `sop-001-modeA.md` | Mode A | 默认提取模板。一次 LLM 调用产出第 1-9 节策展地图。覆盖报告由 auditor 独立完成 |
| `sop-001-modeA-fast.md` | Mode A-fast | 快速提取模板。一次 LLM 调用产出全部 10 节（含自检覆盖报告） |
| `sop-001-modeA-auditor.md` | Mode A | 独立覆盖审计员。输入源文 + 第 1-9 节，输出第 10 节。推荐便宜模型 |
| `sop-001-modeB-pass1-entities-claims.md` | Mode B | Pass 1：全景概括 + 实体 + 论点（合并提取）。内置自检步骤 |
| `sop-001-modeBC-pass2-relationships.md` | Mode B/C | Pass 2：关系提取。被 B 和 C 共享 |
| `sop-001-modeBC-assembler.md` | Mode B/C | 组装器。将被 B 和 C 共享。支持轻量（B）和完整（C）模式 |
| `sop-001-modeC-pass1-entities.md` | Mode C | Pass 1：实体与概念提取（纯实体，不包含论点） |
| `sop-001-modeC-pass3-claims.md` | Mode C | Pass 3：论点与主张提取（在已知实体和关系后独立执行） |

### 策展与检查模板

| 文件 | 用途 |
|------|------|
| `sop-002-curator.md` | SOP-002 策展入库——基于审核过的策展地图创建/更新 wiki 页面 |
| `sop-003-lint.md` | SOP-003 知识库健康扫描 |

### 规范文档

| 文件 | 用途 |
|------|------|
| `extraction-interface.md` | **权威格式参考**。定义所有提取字段和覆盖报告的格式规范。所有 prompt 模板以此为准 |

---

## 三、各模式完整流程

### Mode A（默认，3 次 LLM）

```
Call 1：sop-001-modeA.md          → 第 1-9 节策展地图
Call 2：sop-001-modeA-auditor.md  → 第 10 节覆盖报告（独立审计——对照源文检查覆盖。可用便宜模型）
Call 3：sop-002-curator.md        → wiki 页面（人审通过后）

人审：先看第 10 节覆盖报告（30 秒，不需要领域知识），再逐节审核第 1-9 节内容。
```

### Mode A-fast（可选快速路径，2 次 LLM）

```
Call 1：sop-001-modeA-fast.md     → 完整 10 节策展地图（含自检覆盖报告）
Call 2：sop-002-curator.md        → wiki 页面（人审通过后）

覆盖报告标注「自检——非独立审计」。
如有疑虑，升级到 Mode A（独立审计）或直接 Mode B。
```

### Mode B（2 Pass，4 次 LLM）

```
Call 1：sop-001-modeB-pass1-entities-claims.md  → 第 1/2/3/5 节
Call 2：sop-001-modeBC-pass2-relationships.md   → 第 4 节
Call 3：sop-001-modeBC-assembler.md (light)     → 第 6-10 节（轻量组装）
Call 4：sop-002-curator.md                      → wiki 页面
```

### Mode C（3 Pass，5 次 LLM）

```
Call 1：sop-001-modeC-pass1-entities.md         → 第 1/2/3 节
Call 2：sop-001-modeBC-pass2-relationships.md   → 第 4 节
Call 3：sop-001-modeC-pass3-claims.md           → 第 5 节
Call 4：sop-001-modeBC-assembler.md (full)      → 第 6-10 节（完整组装）
Call 5：sop-002-curator.md                      → wiki 页面
```

---

## 四、覆盖报告说明

策展地图第 10 节是覆盖报告——提供不需要领域知识的覆盖异常信号。人审时**先看覆盖报告（约 30 秒），再看内容**。

三种覆盖报告类型：

| 类型 | 生成方式 | 可信度 | 出现在 |
|------|---------|--------|--------|
| **独立审计** | 独立 auditor Agent——与提取 Agent 分离，对照源文逐节检查覆盖 | 高 | Mode A（默认） |
| **自检** | 提取 Agent 同一调用——对照全景概括做有限交叉校验 | 低于独立审计。标记了异常更可能是真的 | Mode A-fast |
| **交叉校验** | assembler——对照独立 Pass 的提取输出生成 | 高。Mode B 对比两方，Mode C 对比三方 | Mode B / Mode C |

---

## 五、人审流程

```
Step 1：看覆盖报告（第 10 节，30 秒）——不需要领域知识

  - 看「元信息」确认覆盖报告类型
  - 看「节级覆盖」：有没有 0 条的节？→ 是代码/引用 → 通过。是文字描述 → ⚠
  - Mode A/A-fast 看「全景概括对照」：概括提到但提取缺的 → ⚠
  - 看「密度异常」：偏低且非盲区 → ⚠
  - 看「结构一致性」：覆盖率 < 80% → ⚠

Step 2：看策展地图内容（第 1-9 节，正常审核）

  - 概念分类是否清晰？
  - 关系提取是否合理？
  - 标记「确认入库」/「忽略」/「需要更多源」

Step 3：决定是否升级

  Mode A-fast 覆盖报告异常 → 升级到 Mode A（独立审计）或直接 Mode B
  Mode A 覆盖报告 ≥2 个文字描述盲区 → 升级到 Mode B
  Mode B 论点有误判 → 升级到 Mode C
```

---

## 六、如何接入不同 LLM 工具

模板使用 `{{PLACEHOLDER}}` 占位符，不绑定任何特定 LLM 工具。

### 占位符约定

| 占位符 | 替换为 |
|--------|--------|
| `{{SOURCE_CONTENT}}` | 待提取的原料全文 |
| `{{KB_DOMAIN}}` | 知识库领域描述（如「大模型应用开发：RAG、Agent、知识图谱」） |
| `{{PASS1_OUTPUT}}` | Pass 1 的完整输出 |
| `{{PASS2_OUTPUT}}` | Pass 2 的完整输出 |
| `{{PASS3_OUTPUT}}` | Pass 3 的完整输出（Mode B 时为空） |
| `{{CURATION_MAP_S1_9}}` | 策展地图第 1-9 节完整内容 |
| `{{ASSEMBLY_MODE}}` | `light`（Mode B）或 `full`（Mode C） |

### 接入方式

| LLM 工具 | 使用方式 |
|----------|---------|
| ChatGPT / Claude Web | 替换占位符后复制全文粘贴到聊天输入框 |
| API 调用 | 作为 `system` 或第一个 `user` message |
| Hermes Agent | Cron job 或对话中引用模板内容，替换占位符后执行 |
| Cursor / Copilot | 粘贴到 composer / chat 中 |

---

完整 SOP 规范见 [`docs/sop-v2-full.md`](../docs/sop-v2-full.md)。
架构设计与修改方案见 [`docs/adaptive-extraction-plan.md`](../docs/adaptive-extraction-plan.md)。
