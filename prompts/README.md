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
| `{{PASS1_OUTPUT}}` | Pass 1 的输出（全景概括 + 提取层次 + 实体清单） | 将 `sop-001-pass1-entities.md` 的执行结果粘贴到此 |
| `{{PASS2_OUTPUT}}` | Pass 2 的输出（关系清单） | 将 `sop-001-pass2-relationships.md` 的执行结果粘贴到此 |
| `{{PASS3_OUTPUT}}` | Pass 3 的输出（论点与主张） | 将 `sop-001-pass3-claims.md` 的执行结果粘贴到此 |
| `{{CURATION_MAP}}` | 审核通过的策展地图 | 用户审核后的策展地图全文 |
| `{{SCHEMA_MD}}` | 知识库 SCHEMA.md 内容 | 粘贴 `schema/SCHEMA.md` 全文 |
| `{{INDEX_MD}}` | 知识库 index.md 内容 | 粘贴 `schema/index.md` 全文 |
| `{{WIKI_DIR}}` | wiki/ 目录路径 | 知识库的 `wiki/` 目录绝对路径 |

---

## 提取流程（三 Pass + 组装）

策展地图的产出分四个阶段——三轮纯提取，一轮组装：

```
源文
 │
 ├── Pass 1（sop-001-pass1-entities.md）         ← 第 1 次 LLM 调用
 │     输入：{{SOURCE_CONTENT}}
 │     产出：第 1 节「全景概括」+ 第 2 节「提取层次说明」+ 第 3 节「实体清单」
 │
 ├── Pass 2（sop-001-pass2-relationships.md）    ← 第 2 次 LLM 调用
 │     输入：{{SOURCE_CONTENT}} + {{PASS1_OUTPUT}}
 │     产出：第 4 节「关系清单」
 │
 ├── Pass 3（sop-001-pass3-claims.md）           ← 第 3 次 LLM 调用
 │     输入：{{SOURCE_CONTENT}} + {{PASS1_OUTPUT}} + {{PASS2_OUTPUT}}
 │     产出：第 5 节「事实主张」
 │
 └── 组装（sop-001-rough-reader.md）             ← 第 4 次 LLM 调用
       输入：{{SOURCE_CONTENT}} + {{PASS1_OUTPUT}} + {{PASS2_OUTPUT}} + {{PASS3_OUTPUT}}
       产出：完整 9 节策展地图
             · 嵌入第 1–5 节（来自三份 Pass）
             · 补全第 6 节「不确定标记」（跨 Pass 聚合）
             · 补全第 7 节「缺口分析」（全局视野）
             · 补全第 8 节「SCHEMA 建议」（全局视野）
             · 补全第 9 节「Agent 签名」（统计 + 覆盖声明）
```

### 为什么三 Pass

LLM 在一次调用中同时做「识别实体」「判断关系」「提取论点」会分散注意力——每个维度的提取质量都会下降。三轮分治，每轮只关注一件事，显著减少遗漏

- **Pass 1 先做全景概括**：在逐段标注之前完成全局理解，防止注意力被局部细节牵引
- **Pass 2 依赖 Pass 1**：关系两端必须是已提取的实体标识符
- **Pass 3 依赖 Pass 1+2**：参考实体定义和关系，避免将实体描述误判为论点
- **组装阶段独立**：缺口分析、SCHEMA 建议需要看到全部提取结果才能判断——任何单个 Pass 都没有这个视野

---

## 模型选择建议

| 步骤 | 推荐模型级别 | 理由 |
|---|---|---|
| Pass 1（全景概括 + 实体提取） | 中-高 | 全景概括需要宏观理解，实体识别需要广域知识 |
| Pass 2（关系提取） | 高 | 关系判断需要深层语义理解 |
| Pass 3（论点提取） | 中-高 | 论点识别和置信度判断需要准确度 |
| 组装（缺口 + SCHEMA + 签名） | 中-高 | 综合分析能力，不涉及大规模提取 |
| 策展入库（sop-002-curator.md） | 高 | 需要精确遵守 SCHEMA 约束 |
| Lint 扫描（sop-003-lint.md） | 中 | 主要是格式检查，语义判断少 |

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

| 文件 | 用途 |
|------|------|
| `sop-001-pass1-entities.md` | Pass 1：全景概括 + 提取层次说明 + 实体清单（第 1/2/3 节） |
| `sop-001-pass2-relationships.md` | Pass 2：关系清单（第 4 节） |
| `sop-001-pass3-claims.md` | Pass 3：论点与主张提取（第 5 节） |
| `sop-001-rough-reader.md` | 组装模板：将三份 Pass 输出组装为完整 9 节策展地图 |
| `sop-002-curator.md` | SOP-002：策展入库（基于审核过的策展地图创建/更新 wiki 页面） |
| `sop-003-lint.md` | SOP-003：知识库健康扫描（9 项检查 + 轻量/全量模式） |
| `extraction-interface.md` | 提取接口技术规范（所有 prompt 的格式权威参考，跨 SOP 共用） |

---

完整 SOP 规范见 [`docs/sop-v2-full.md`](../docs/sop-v2-full.md)
