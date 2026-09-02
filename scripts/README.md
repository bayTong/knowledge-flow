# 参考实现脚本

三个纯 Python 标准库脚本,把 SOP-003 健康检查与 SOP-000 导航维护做成可复现命令。
它们是旧版 SOP-003 知识库维护规则的**参考实现**,不是独立的第二套规则。对应检查口径暂以 `docs/sop-v2-full.md` 的 SOP-003 章节为准；主题级优先关系见 `docs/design-authority-and-conflict-register-设计权威与冲突登记.md`。

这些脚本不实现也不证明 Capture Store、Global Intake、路由、批准绑定、GBrain 镜像或可信写入回滚已经交付。`index-generator.py --write` 只应对明确选择的现有 KB 使用。

## 用法

```bash
python scripts/lint.py            <知识库路径> [--json] [--quiet]   # SOP-003 九项检查
python scripts/link-validator.py  <知识库路径> [--json]             # 仅 wikilink 断链/格式
python scripts/index-generator.py <知识库路径> [--write]            # index.md 生成(不带 --write 为预览)
```

`lint.py` 输出的每条消息带 `[检查N]` 前缀,与 `docs/sop-v2-full.md` SOP-003 的检查项编号一一对应:

| 编号 | 检查项 | 级别 | 说明 |
|---|---|---|---|
| 1 | wikilink 格式与断链 | Error | 排除代码块与行内代码中的链接 |
| 2 | 孤立页面 | Error | 无入链的 wiki 页面 |
| 3 | index 完整性 | Error | wiki/ 文件与 index.md 条目双向对比 |
| 4 | frontmatter 完整性 | Error | 7 字段 + type 合法性 + title 格式 |
| 5 | 标签合规 | Error/Warning | 未注册标签告警;已注册未使用提醒 |
| 6 | 页面行数 | Warning/Error | >300 行警告(拆分候选)、>500 行错误(必须拆分) |
| 7 | 日志轮转 | Notice | 仅报告,轮转由执行 SOP-003 的 Agent 处理 |
| 8 | entity 孤立专项 | Error | `wiki/entities/` 下无 concept 入链 |
| 9 | 图谱过滤规则 | Notice | 仅报告;非 Obsidian 知识库自动跳过 |

## Windows 平台注意事项(重要)

- **控制台编码**:脚本已在入口重配置 stdout/stderr 为 UTF-8,中文 Windows 默认 GBK 控制台下
  不会 `UnicodeEncodeError`。若在旧 Python 上异常,设 `PYTHONIOENCODING=utf-8`。
- **UTF-8 BOM**:脚本用 `utf-8-sig` 读取文件,PowerShell `Set-Content -Encoding UTF8` 或
  Windows 编辑器产出的带 BOM 文件不会导致 frontmatter 误判缺失。
- **文件名**:脚本使用 Python 3 路径接口处理文件名；对包含中文、空格或括号的真实 KB 执行写入前，仍应先用不带 `--write` 的命令预览结果。

## `--json` 输出契约

- 输出为合法 UTF-8 JSON,`lint.py` 的结构为 `{ "kb": ..., "errors": [...], "warnings": [...], "notices": [...] }`
  (消息对象含 `[检查N]` 编号字段),供 `doc-check.py` 或 CI 消费。
- 退出码:检出 Error 时非 0(`link-validator.py` 为未解析链接非 0),供脚本链/CI 判失败。

## 测试状态

当前尚未提交 `scripts/` 专用自动化回归测试或固定夹具。后续实现 P2-1 时，测试代码与合成夹具必须同批加入；临时实验目录不得作为固定夹具提交。
