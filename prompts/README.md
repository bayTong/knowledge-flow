# Prompt 模板使用说明

本文档说明 `prompts/` 目录下的 LLM-agnostic 提示词模板的格式、占位符替换规则，以及如何接入不同的 LLM 工具。

---

## 模板格式

所有模板使用 `{{PLACEHOLDER}}` 占位符，不绑定任何特定 LLM 工具。使用前将占位符替换为实际内容即可。

### 占位符约定

| 占位符 | 含义 | 替换为 |
|---|---|---|
| `{{SOURCE_CONTENT}}` | 待提取的原料全文 | 粘贴 URL 抓取的 markdown 内容、论文正文、对话记录等 |
| `{{KB_DOMAIN}}` | 知识库覆盖的领域描述 | 如「大模型应用开发：RAG、Agent、知识图谱、上下文工程」 |
| `{{PASS1_OUTPUT}}` | 多轮次提取 Pass 1 的输出 | 将 `rough-reader-pass1-entities.md` 的执行结果粘贴到此 |
| `{{PASS2_OUTPUT}}` | 多轮次提取 Pass 2 的输出 | 将 `rough-reader-pass2-relationships.md` 的执行结果粘贴到此 |
| `{{CURATION_MAP}}` | 审核通过的策展地图 | 用户审核后的策展地图全文 |
| `{{SCHEMA_MD}}` | 知识库 SCHEMA.md 内容 | 粘贴 `schema/SCHEMA.md` 全文 |
| `{{INDEX_MD}}` | 知识库 index.md 内容 | 粘贴 `schema/index.md` 全文 |
| `{{WIKI_DIR}}` | wiki/ 目录路径 | 知识库的 `wiki/` 目录绝对路径 |

---

## 单轮次 vs 多轮次提取

### 单轮次（快速上手）

使用 `rough-reader.md`——一条 prompt 完成全部提取。

- **优点**：一次 LLM 调用，速度快
- **缺点**：LLM 同时关注实体、关系、论点三个维度，可能遗漏
- **适用**：短原料（< 5000 字）、快速试跑

### 多轮次（推荐）

分三次 LLM 调用：

```
Pass 1: rough-reader-pass1-entities.md      → 仅提取实体与概念
Pass 2: rough-reader-pass2-relationships.md → 仅提取关系（依赖 Pass 1 输出）
Pass 3: rough-reader-pass3-claims.md        → 仅提取论点与主张（依赖 Pass 1+2 输出）
        ↓
手动合并三份输出为完整策展地图
```

- **优点**：每轮只关注一个维度，显著减少遗漏
- **缺点**：3 次 LLM 调用，需手动合并
- **适用**：长原料（> 5000 字）、重要原料（你想确保不遗漏任何内容）

### 模型选择建议

| 步骤 | 推荐模型级别 | 理由 |
|---|---|---|
| Pass 1（实体提取） | 中-高 | 实体识别需要广域知识 |
| Pass 2（关系提取） | 高 | 关系判断需要深层语义理解 |
| Pass 3（论点提取） | 中-高 | 论点提取对模型要求适中 |
| 策展入库（curator.md） | 高 | 需要精确遵守 SCHEMA 约束 |
| Lint 扫描（lint.md） | 中 | 主要是格式检查，语义判断少 |

---

## 如何接入不同 LLM 工具

模板本身是纯文本 markdown 文件，与任何具体工具无关。使用步骤：

1. **打开模板文件**——在编辑器中查看完整的 prompt 内容
2. **替换占位符**——将 `{{...}}` 替换为实际内容
3. **粘贴到 LLM 输入框**——复制整段 prompt 到所用工具的聊天输入、API 调用或 system prompt
4. **执行**——发送消息，LLM 按 prompt 指令执行

不同工具的接入示例：

| LLM 工具 | 使用方式 |
|---|---|
| ChatGPT / Claude Web | 复制 prompt 全文粘贴到聊天输入框 |
| API 调用 | 将 prompt 作为 `system` 或第一个 `user` message 的内容 |
| Hermes Agent | 设置 Cron job 或直接对话中引用 prompt 内容 |
| Cursor / Copilot | 将 prompt 粘贴到 composer / chat 中 |

---

## 文件索引

| 文件 | 对应 SOP | 用途 |
|---|---|---|
| `rough-reader.md` | SOP-001 | 单轮次策展地图生成 |
| `rough-reader-pass1-entities.md` | SOP-001 Step 3a | 多轮次 Pass 1：实体与概念提取 |
| `rough-reader-pass2-relationships.md` | SOP-001 Step 3b | 多轮次 Pass 2：关系提取 |
| `rough-reader-pass3-claims.md` | SOP-001 Step 3c | 多轮次 Pass 3：论点与主张提取 |
| `curator.md` | SOP-002 | 策展入库（基于审核过的策展地图） |
| `lint.md` | SOP-003 | 知识库健康扫描 |
| `extraction-interface.md` | — | 提取接口技术规范（所有 prompt 的格式参考） |

---

完整 SOP 规范见 [`docs/sop-v2-full.md`](../docs/sop-v2-full.md)。
