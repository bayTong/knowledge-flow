#!/usr/bin/env python3
"""
Wikilink 验证器 —— 专项检查 [[wikilink]] 的目标是否存在。

与 lint.py 的区别：
  - lint.py 做 SOP-003 全量 9 项检查（断链 / 孤立页面 / index 完整性 / frontmatter /
    标签审计 / 页面过大 / 日志轮转 / entity 孤立 / 图谱过滤），见其文档字符串
  - link-validator.py 只做 wikilink 专项深度验证
  - 适合只想快速修断链时使用——更快、更聚焦

用法：
  python scripts/link-validator.py /path/to/kb
  python scripts/link-validator.py /path/to/kb --json

设计原则：
  - 零外部依赖——只用 Python 标准库
  - LLM-agnostic——输入文件路径，输出 stdout
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict


# ============================================================
#  基础工具 —— 从 markdown 中提取 wikilink
# ============================================================

def extract_wikilinks(content: str) -> list[tuple[str, str, str]]:
    """
    从 markdown 正文中提取所有 [[wikilink]]，排除代码块。

    返回三元组列表：
      (原始链接, 目标 slug, 显示文本)

    示例：
      [[铁三角能力模型|方法论与策略 · 铁三角能力模型]]
      → ("铁三角能力模型|方法论与策略 · 铁三角能力模型", "铁三角能力模型", "方法论与策略 · 铁三角能力模型")

    对于无管道符的链接（[[slug]]），slug 和显示文本相同。

    使用状态机排除代码块——` ``` ` 包裹区域内的 [[...]] 是示例代码，不是真实链接。
    """
    links = []
    in_code_block = False
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        for match in re.finditer(r"\[\[([^\]]+)\]\]", line):
            raw = match.group(1)
            # 跳过外部 URL
            if raw.startswith("http://") or raw.startswith("https://"):
                continue
            if "|" in raw:
                slug, _, display = raw.partition("|")
                links.append((raw, slug.strip(), display.strip()))
            else:
                links.append((raw, raw.strip(), raw.strip()))
    return links


def resolve_slug(target_slug: str, all_pages: dict[str, Path]) -> Path | None:
    """
    尝试将 wikilink 的目标 slug 解析为实际文件。

    匹配策略（按优先级）：
      1. 精确匹配完整相对路径（如 "01-方法论与策略/铁三角能力模型"）
      2. 匹配文件名不含扩展名（如 "铁三角能力模型" → wiki/**/铁三角能力模型.md）
      3. 路径后缀匹配（如 "/铁三角能力模型" 出现在完整路径末尾）

    all_pages 是 {相对路径: Path对象} 的字典，包含两套 key：
      - 完整相对路径（如 "01-模块/页面名"）
      - 纯文件名不含扩展名（如 "页面名"）
    """
    if target_slug in all_pages:
        return all_pages[target_slug]
    for rel_path, fpath in all_pages.items():
        if fpath.stem == target_slug:
            return fpath
        if rel_path.endswith("/" + target_slug):
            return fpath
    return None


# ============================================================
#  主函数
# ============================================================

def validate(kb_path: str) -> dict:
    """
    扫描知识库所有 wiki 页面，验证每个 wikilink 的目标是否存在。

    流程：
      1. 建立「wiki 页面索引」——所有 .md 文件的相对路径和文件名
      2. 逐页面提取 wikilink，尝试解析目标
      3. 统计 resolved / unresolved

    返回结构化字典，包含 resolved 和 unresolved 两个列表。
    """
    kb = Path(kb_path)
    wiki_dir = kb / "wiki"
    if not wiki_dir.exists():
        return {"error": "wiki/ 目录不存在"}

    # 建立页面索引：两种 key 形式都支持匹配
    #   "01-模块/页面名"（完整相对路径）
    #   "页面名"（纯文件名，用于只有文件名的 wikilink）
    all_pages = {}
    for f in sorted(wiki_dir.rglob("*.md")):
        rel = str(f.relative_to(wiki_dir).with_suffix("")).replace("\\", "/")
        all_pages[rel] = f
        all_pages[f.stem] = f

    results = {
        "kb_path": str(kb),
        "resolved": [],    # 解析成功的链接
        "unresolved": [],  # 解析失败的链接
        "stats": {}
    }

    total = 0
    resolved_count = 0

    for f in sorted(wiki_dir.rglob("*.md")):
        rel = str(f.relative_to(wiki_dir).with_suffix("")).replace("\\", "/")
        content = f.read_text(encoding="utf-8-sig")
        links = extract_wikilinks(content)

        for raw, slug, display in links:
            total += 1
            target = resolve_slug(slug, all_pages)
            if target:
                resolved_count += 1
                results["resolved"].append({
                    "source": rel,                              # 来源页面
                    "link": raw,                                # 原始链接字符串
                    "target": str(target.relative_to(wiki_dir)  # 目标文件
                                .with_suffix("")).replace("\\", "/")
                })
            else:
                results["unresolved"].append({
                    "source": rel,          # 来源页面
                    "link": raw,            # 原始链接字符串（方便定位）
                    "target_slug": slug     # 未能解析的 slug
                })

    results["stats"] = {
        "total": total,
        "resolved": resolved_count,
        "unresolved": total - resolved_count
    }
    return results


# ============================================================
#  输出格式化
# ============================================================

def format_report(results: dict) -> str:
    """将验证结果转为人类可读报告。"""
    if "error" in results:
        return f"致命错误: {results['error']}"

    stats = results["stats"]
    lines = ["=== Wikilink 验证报告 ===", ""]

    # 先展示未解析的（最需要关注）
    if results["unresolved"]:
        lines.append(f"未解析的链接 ({stats['unresolved']} 条):")
        by_file = defaultdict(list)
        for item in results["unresolved"]:
            by_file[item["source"]].append(item)
        for fname in sorted(by_file):
            lines.append(f"  ☒ {fname}")
            for item in by_file[fname]:
                lines.append(f"     → [[{item['link']}]]")
                lines.append(f"       目标 slug '{item['target_slug']}' 未找到对应文件")
        lines.append("")

    # 展示已解析的（确认状态）
    if results["resolved"]:
        lines.append(f"已解析的链接 ({stats['resolved']} 条):")
        by_file = defaultdict(list)
        for item in results["resolved"]:
            by_file[item["source"]].append(item)
        for fname in sorted(by_file):
            lines.append(f"  ☑ {fname}（{len(by_file[fname])} 条链接）")
        lines.append("")

    lines.append(
        f"总计: {stats['total']} 条链接已检查, "
        f"{stats['resolved']} 条解析成功, "
        f"{stats['unresolved']} 条未解析。"
    )
    return "\n".join(lines)


# ============================================================
#  CLI 入口
# ============================================================

if __name__ == "__main__":
    # GBK 控制台（中文 Windows 默认）下 ☒/☑ 等符号触发 UnicodeEncodeError——统一重配置为 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2:
        print("用法: python scripts/link-validator.py /path/to/kb [--json]")
        sys.exit(1)

    kb_path = sys.argv[1]
    as_json = "--json" in sys.argv

    results = validate(kb_path)

    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(format_report(results))

    # 有未解析链接时退出码为 1，方便 CI 判定
    if results.get("unresolved"):
        sys.exit(1)
