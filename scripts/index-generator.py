#!/usr/bin/env python3
"""
Index.md 自动生成器 —— 从 wiki/ 目录结构自动生成索引文件。

功能：
  扫描 wiki/ 下所有 .md 文件，按 SCHEMA 规范生成 schema/index.md：

  - 分组（SCHEMA 第七章「导航与日志」）：concept/comparison 按模块目录分组
    （`## 01 — 模块名`），entity 归「实体」段，query 归「问答」段
  - 条目格式（SCHEMA 第六章「Wikilink 规范」）：`[[文件名|完整 title]] — 一句话摘要`
    —— 管道符前为实际文件名（不含路径、不含扩展名），管道符后为完整 frontmatter title
  - 头部统计行（SOP-000 步骤 4 模板）：
    `> 最后更新：YYYY-MM-DD | 总页面数：N | 模块数：N`

摘要说明：
  脚本无 LLM，摘要为机械截取——正文首个非空、非标题行的首行，
  超过 80 字符截断加省略号；正文为空时降级为文件名。
  自动摘要仅是基线，建议人工润色。SOP-003 检查 3 对缺失条目的
  自动补全由 Agent 生成语义摘要——能力优于本脚本，两者分工不冲突。

免责：
  `--write` 全量重生成会覆盖 index.md 中的手工维护内容（人工摘要、
  手工排序）。建议与 git 配合使用——重生成后 git diff 审阅，必要时回滚。

用法：
  python scripts/index-generator.py /path/to/kb          # 预览（stdout）
  python scripts/index-generator.py /path/to/kb --write  # 写入 schema/index.md

设计原则：
  - 零外部依赖——只用 Python 标准库（sys, re, pathlib, datetime）
  - LLM-agnostic——不绑定任何 AI 平台
  - 幂等——同一知识库状态重跑，输出一致（「最后更新」日期除外）
"""

import re
import sys
from pathlib import Path
from datetime import datetime


# ============================================================
#  工具函数
# ============================================================

SUMMARY_LIMIT = 80  # 机械摘要的单行截断长度（字符）


def parse_frontmatter(content: str) -> dict:
    """
    从 markdown 文件中提取 YAML frontmatter。

    Frontmatter 位于文件开头的两个 `---` 之间。
    返回字典，key 是字段名，value 是去掉方括号的原始值。
    没有_frontmatter 或格式异常时返回空字典。
    """
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    fm_text = content[3:end]
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip("[]")
    return fm


def strip_frontmatter(content: str) -> str:
    """返回 frontmatter 之后（第二个 `---` 之后）的正文。"""
    if not content.startswith("---"):
        return content
    end = content.find("---", 3)
    if end == -1:
        return content
    return content[end + 3:]


def extract_summary(body: str, fallback: str) -> str:
    """
    机械式一句话摘要：正文首个非空、非标题行的首行。

    跳过标题行（# 开头）与代码块（``` 包裹）——代码不是合格摘要。
    超过 80 字符截断加省略号。正文无可用内容时降级为 fallback（文件名）。
    """
    in_code = False
    for line in body.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if len(s) > SUMMARY_LIMIT:
            s = s[:SUMMARY_LIMIT - 1] + "…"
        return s
    return fallback


def module_heading(module_dir: str) -> str:
    """
    模块目录名 → index 分组标题。

    "01-核心架构" → "## 01 — 核心架构"（SOP-000 步骤 4 模板的分组格式）
    不符合「两位数字-名称」约定的目录名原样使用。
    """
    m = re.match(r"^(\d+)[-\s]+(.+)$", module_dir)
    if m:
        return f"## {m.group(1)} — {m.group(2)}"
    return f"## {module_dir}"


# ============================================================
#  主函数
# ============================================================

def generate(kb_path: str) -> str:
    """
    扫描知识库并生成 index.md 内容。

    流程：
      1. 遍历 wiki/ 下所有 **/*.md
      2. 解析 frontmatter（title）+ 提取机械摘要（正文首段）
      3. 分组：wiki/entities/ → 实体段；wiki/queries/ → 问答段；
         其余按模块目录分组（根目录散页归「未分组」）
      4. 输出 SOP-000 步骤 4 模板格式的 index（头部统计行 + 分组条目）
    """
    kb = Path(kb_path)
    wiki_dir = kb / "wiki"
    if not wiki_dir.exists():
        return f"# Wiki Index\n\n> wiki/ 目录不存在: {wiki_dir}"

    # modules = {"01-模块名": [(slug, title, summary), ...]}
    # entities / queries = [(slug, title, summary), ...]
    modules = {}
    entities = []
    queries = []

    for f in sorted(wiki_dir.rglob("*.md")):
        rel = f.relative_to(wiki_dir)
        parts = rel.parts
        content = f.read_text(encoding="utf-8-sig")
        fm = parse_frontmatter(content)

        title = fm.get("title") or f.stem
        # SCHEMA 第六章：管道符前为实际文件名（不含路径、不含扩展名）
        slug = f.stem
        summary = extract_summary(strip_frontmatter(content), f.stem)
        entry = (slug, title, summary)

        if len(parts) >= 2 and parts[0] == "entities":
            entities.append(entry)
        elif len(parts) >= 2 and parts[0] == "queries":
            queries.append(entry)
        else:
            module_dir = parts[0] if len(parts) >= 2 else "未分组"
            modules.setdefault(module_dir, []).append(entry)

    total_pages = sum(len(v) for v in modules.values()) + len(entities) + len(queries)
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "# Wiki Index",
        "",
        "> 内容目录。每个 wiki 页面按模块列出，附一句话摘要。",
        "> 阅读此文件可快速定位任何查询的相关页面。",
        f"> 最后更新：{today} | 总页面数：{total_pages} | 模块数：{len(modules)}",
        "",
        "<!-- 摘要由 scripts/index-generator.py 自动生成（正文首段截断），建议人工润色。",
        "     --write 全量重生成会覆盖手工摘要，建议配合 git 审阅变更。",
        "     新页面加入格式：",
        "     ## 01 — 模块名",
        "     - [[文件名|模块·标题]] — 一句话摘要",
        "-->",
        "",
    ]

    # 模块分组（concept/comparison）
    for module_dir in sorted(modules):
        lines.append(module_heading(module_dir))
        lines.append("")
        for slug, title, summary in modules[module_dir]:
            lines.append(f"- [[{slug}|{title}]] — {summary}")
        lines.append("")

    # 实体段 / 问答段（SCHEMA 第七章；为空时不输出）
    for heading, entries in [("实体", entities), ("问答", queries)]:
        if not entries:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for slug, title, summary in entries:
            lines.append(f"- [[{slug}|{title}]] — {summary}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ============================================================
#  CLI 入口
# ============================================================

if __name__ == "__main__":
    # GBK 控制台（中文 Windows 默认）下特殊符号可能触发 UnicodeEncodeError——与其他脚本统一重配置为 UTF-8；
    # stdout 同时关闭换行翻译（newline=""），保证预览输出与写入文件的换行一致
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", newline="")
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2:
        print("用法: python scripts/index-generator.py /path/to/kb [--write]")
        sys.exit(1)

    kb_path = sys.argv[1]
    do_write = "--write" in sys.argv

    output = generate(kb_path)

    if do_write:
        index_path = Path(kb_path) / "schema" / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        # 显式 LF 写入：与仓库内 markdown 的换行约定一致，
        # 且保证「预览输出」与「写入内容」字节级一致
        with open(index_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(output)
        print(f"已写入 {index_path}")
    else:
        # 预览输出与 --write 写入内容字节级一致（output 自带结尾换行）
        sys.stdout.write(output)
