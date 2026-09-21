# 参考实现脚本

本目录包含四个纯 Python 标准库脚本。前三个把 SOP-003 健康检查与 SOP-000 导航维护做成可复现命令，是旧版 SOP-003 知识库维护规则的**参考实现**，不是独立的第二套规则；`doc-check.py` 则只检查 KnowledgeFlow 仓库自身的确定性文档事实。对应业务检查口径暂以 `archive/2026-design-history/sop-v2-full.md` 的 SOP-003 历史章节为准；主题级优先关系见 `docs/design-authority-and-conflict-register-设计权威与冲突登记.md`。

这些脚本不实现也不证明 Capture Store、Global Intake、路由、批准绑定、GBrain 镜像或可信写入回滚已经交付。`index-generator.py --write` 只应对明确选择的现有 KB 使用。

## 用法

```bash
python scripts/lint.py            <知识库路径> [--json] [--quiet]   # SOP-003 九项检查
python scripts/link-validator.py  <知识库路径> [--json]             # 仅 wikilink 断链/格式
python scripts/index-generator.py <知识库路径> [--write]            # index.md 生成(不带 --write 为预览)
python scripts/doc-check.py       [仓库路径] [--json]               # Git 感知的项目文档一致性
```

`doc-check.py` 不理解所有自然语言，也不替代人工设计复核。它只检查：中英文 README 的路由目标集合和结构树已列文件、现行项目 Markdown 的相对链接、`docs/` 下未跟踪 Markdown、历史研究输入索引，以及六份状态文档中的测试数量/下一门禁锚点。历史研究正文和 v1.0 归档不作为现行语义解析。通过返回 `0`，发现确定性漂移返回 `1`，仓库/Git 前置条件无效返回 `2`。

`lint.py` 输出的每条消息带 `[检查N]` 前缀,与 `archive/2026-design-history/sop-v2-full.md` SOP-003 的检查项编号一一对应:

| 编号 | 检查项 | 级别 | 说明 |
|---|---|---|---|
| 1 | wikilink 格式、断链与文件名唯一性 | Error | 排除代码块与行内代码；basename-only 链接要求全库文件名唯一 |
| 2 | 孤立页面 | Error | 无入链的 wiki 页面 |
| 3 | index 完整性 | Warning | wiki/ 文件与 index.md 条目双向对比 |
| 4 | frontmatter 完整性 | Error/Warning | 必填字段缺失报错；推荐字段、type、title 格式告警 |
| 5 | 标签合规 | Warning/Notice | 未注册标签告警；已注册未使用提醒 |
| 6 | 页面行数 | Warning/Error | >300 行警告(拆分候选)、>500 行错误(必须拆分) |
| 7 | 日志轮转 | Notice | 仅报告,轮转由执行 SOP-003 的 Agent 处理 |
| 8 | entity 孤立专项 | Error | `wiki/entities/` 下无 concept 入链 |
| 9 | 图谱过滤规则 | Warning/Error | 配置缺失告警；配置损坏或过滤条件缺失报错；非 Obsidian KB 跳过 |

## Windows 平台注意事项(重要)

- **控制台编码**:脚本已在入口重配置 stdout/stderr 为 UTF-8,中文 Windows 默认 GBK 控制台下
  不会 `UnicodeEncodeError`。若在旧 Python 上异常,设 `PYTHONIOENCODING=utf-8`。
- **UTF-8 BOM**:脚本用 `utf-8-sig` 读取文件,PowerShell `Set-Content -Encoding UTF8` 或
  Windows 编辑器产出的带 BOM 文件不会导致 frontmatter 误判缺失。
- **文件名**:脚本使用 Python 3 路径接口处理文件名；对包含中文、空格或括号的真实 KB 执行写入前，仍应先用不带 `--write` 的命令预览结果。

## `--json` 输出契约

- 输出为合法 UTF-8 JSON，`lint.py` 的结构为 `{ "kb_path": ..., "errors": [...], "warnings": [...], "notices": [...] }`
  (消息对象含 `[检查N]` 编号字段),供 `doc-check.py` 或 CI 消费。
- `doc-check.py --json` 输出 `{ "repository": ..., "errors": [...], "stats": ... }`；错误按代码、路径和消息稳定排序，便于 CI 消费。
- 退出码：`0` 表示通过，`1` 表示扫描检出 Error/未解析链接，`2` 表示知识库前置条件无效或输出无法安全生成。三个脚本在 `wiki/` 缺失或类型错误时均以 `2` 失败；basename 重名时 `lint.py` 报 Error 并以 `1` 退出，专项验证器和生成器以 `2` 拒绝歧义输入。`index-generator.py --write` 不会在致命失败时创建或覆盖 index。

## 测试状态

现有 7 项标准库 `unittest` 回归覆盖三个知识库维护脚本的致命退出码、`index-generator.py --write` 失败不覆盖、行内代码排除、重复 basename 检出与拒绝。D0G 另增加 8 项文档护栏回归，覆盖当前仓库 CLI、未跟踪项目文档/路由目标、双语路由差异、结构树、相对链接、研究 allowlist 和状态锚点。当前脚本类回归共 15 项；测试只在框架持有的临时目录生成合成数据，不提交临时夹具。更完整的 P2-1 场景矩阵仍可继续扩展。
