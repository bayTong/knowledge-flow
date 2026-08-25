#!/usr/bin/env python3
"""
SOP-003 知识库 Lint 扫描器（全量健康检查）。

功能：
  扫描知识库的 wiki/ 与 schema/ 目录，按 SOP-003 的 9 项检查规范逐项排查，
  输出「错误 / 警告 / 提示」三级分类报告。每条消息以 [检查N] 前缀标注
  对应的 SOP-003 检查项编号。

检查项（与 docs/sop-v2-full.md「SOP-003」章一一对应）：

  | #  | 检查项                                 | 严重度                            |
  |----|---------------------------------------|----------------------------------|
  | 1  | 断裂 wikilink + 管道格式校验           | Error                            |
  | 2  | 孤立页面（非 entity，入站链接 0）      | Error                            |
  | 3  | index 完整性（缺失 / 多余条目）        | Warning                          |
  | 4  | Frontmatter（7 字段 / type / title）   | Error（必填缺失）/ Warning（其余） |
  | 5  | 标签审计（未注册 / 已注册未使用）       | Warning / Notice                 |
  | 6  | 页面过大（>300 拆分候选 / >500 红线）  | Warning / Error                  |
  | 7  | 日志轮转（log.md >500 条）             | Notice                           |
  | 8  | entity 孤立（无内容页入链）            | Error                            |
  | 9  | 图谱过滤规则（graph.json search 字段） | Error                            |

与 SOP-003 的脚本边界（Agent 职责不在脚本内做）：
  - 检查 3 缺失条目补全、检查 7 日志轮转、检查 9 search 字段补全在
    SOP-003 中属自动修复白名单——脚本只报告，消息中标注「可由 SOP-003 自动修复」
  - 检查 9：.obsidian/ 目录不存在（非 Obsidian 知识库）时跳过

用法：
  python scripts/lint.py /path/to/kb           # 人类可读报告
  python scripts/lint.py /path/to/kb --json    # JSON（供其他程序消费，如 MC-001 Cron）
  python scripts/lint.py /path/to/kb --quiet   # 只输出 Error（CI 模式）

设计原则：
  - 零外部依赖——只用 Python 标准库（json, re, sys, pathlib, collections）
  - LLM-agnostic——输入是文件系统路径，输出是 stdout，不与任何 AI 平台绑定
  - 独立可运行——不依赖其他脚本或配置文件
  - 编码健壮——按 utf-8-sig 读取（兼容带 BOM 文件），stdout 重配置为 UTF-8
    （兼容 GBK 控制台，见 __main__）
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict


# ============================================================
#  配置常量 —— SOP-003 规定的阈值
# ============================================================
LINE_LIMIT_WARN = 300   # 检查 6：超过 → Warning（拆分候选）
LINE_LIMIT_ERROR = 500  # 检查 6：超过 → Error（必须拆分红线）
LOG_ENTRY_LIMIT = 500   # 检查 7：log.md 条目超过 → 建议轮转
PAGE_TYPES = {"concept", "comparison", "entity", "query"}  # 检查 4：type 合法值
FRONTMATTER_REQUIRED = ["title", "created", "updated", "type", "tags"]
FRONTMATTER_RECOMMENDED = ["sources", "confidence"]


# ============================================================
#  基础工具函数 —— 解析 markdown 文件的结构元素
# ============================================================

def parse_frontmatter(content: str) -> dict:
    """
    从 markdown 文件中提取 YAML frontmatter。

    Frontmatter 位于文件开头的两个 `---` 之间：
        ---
        title: 某页面
        type: concept
        tags: [方法论, 求职]
        ---

    返回一个字典，key 是字段名，value 是原始字符串（不去掉方括号）。
    如果文件没有 frontmatter 或格式异常，返回空字典。
    """
    if not content.startswith("---"):
        return {}
    # 找到第二个 `---` 的位置（第一个在行首，跳过）
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


def extract_wikilinks(content: str) -> list:
    """
    从 markdown 正文中提取所有 [[wikilink]]。

    排除两类代码区域（SOP-003 检查 1 的实现说明）：
      - 代码块（``` 包裹——状态机逐行跟踪）
      - 行内代码（`...` 包裹）——匹配前先剥离行内代码段，
        `[[示例|标题]]` 这类代码示例不视为真实链接

    返回原始链接字符串的列表，保留 `|` 分隔符和显示文本。
    如 `[[铁三角能力模型|方法论与策略 · 铁三角能力模型]]`
    """
    links = []
    in_code_block = False  # 状态机：当前是否在代码块内部
    for line in content.split("\n"):
        # 遇到 ``` 切换代码块状态
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # 剥离行内代码段后再匹配 wikilink
        text = re.sub(r"`[^`]*`", "", line)
        for match in re.finditer(r"\[\[([^\]]+)\]\]", text):
            links.append(match.group(1))
    return links


def wikilink_target_slug(link: str) -> str:
    """
    从 wikilink 中提取目标 slug（文件名部分）。

    [[slug|显示文本]] → "slug"
    [[slug]]         → "slug"
    """
    if "|" in link:
        return link.split("|")[0].strip()
    return link.strip()


def load_schema_tags(schema_path: Path) -> set:
    """
    从 SCHEMA.md「标签体系」章提取已注册标签（检查 5 的比对基准）。

    注册行的标准格式（templates/SCHEMA-template.md）：标签体系章内的表格行，
    首列标签名以反引号包裹，如 | `rag` | 检索增强生成 |。
    向后兼容旧格式 | `#rag` | ...（剥离 # 前缀）。

    只解析「标签体系」章（含该词的 ## 标题起、下一个 ## 标题止）内的表格行——
    章内说明文字中的反引号词不会被误注册为标签。
    SCHEMA 不存在时返回空集合，由调用方决定是否跳过检查。
    """
    if not schema_path.exists():
        return set()
    text = schema_path.read_text(encoding="utf-8-sig")
    chapter = []
    in_chapter = False
    for line in text.split("\n"):
        if line.startswith("## "):
            if in_chapter:
                break  # 下一个 ## 章——标签体系章结束
            if "标签体系" in line:
                in_chapter = True
            continue
        if in_chapter:
            chapter.append(line)
    tags = set()
    for line in chapter:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue  # 只认表格行
        first_cell = stripped.strip("|").split("|")[0]
        m = re.search(r"`#?([^`]+)`", first_cell)
        if m:
            tags.add(m.group(1).strip())
    return tags


def load_index_slugs(index_path: Path) -> set:
    """
    从 index.md 中提取所有条目 slug（[[slug|title]] 的 slug 部分）。

    HTML 注释（<!-- ... -->）内的内容不参与统计——SOP-000 的 index 模板
    自带注释格式说明，其中含 [[文件名|模块·标题]] 示例，不是真实条目。
    index.md 不存在时返回空集合。
    """
    if not index_path.exists():
        return set()
    text = index_path.read_text(encoding="utf-8-sig")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    slugs = set()
    for match in re.finditer(r"\[\[([^\]|]+)", text):
        slugs.add(match.group(1).strip())
    return slugs


# ============================================================
#  单项检查函数 —— 每个函数对应 SOP-003 的一项检查
# ============================================================

def check_frontmatter(fm: dict) -> list:
    """
    检查 4：frontmatter 完整性与合法性。

    Error  ：必填字段缺失（title/created/updated/type/tags）
    Warning：推荐字段缺失（sources/confidence）；type 不在 4 种合法值内；
             title 格式与 type 不匹配（concept/comparison 应为「模块名 · 主标题」，
             entity 应为「实体 · 名称」，query 应为「问答 · 问题简述」）
    """
    issues = []
    for field in FRONTMATTER_REQUIRED:
        if field not in fm:
            issues.append(("error", f"[检查4] 缺少 frontmatter 必填字段: {field}"))
    for field in FRONTMATTER_RECOMMENDED:
        if field not in fm:
            issues.append(("warning", f"[检查4] 缺少 frontmatter 推荐字段: {field}"))
    ptype = fm.get("type", "")
    if ptype and ptype not in PAGE_TYPES:
        issues.append(("warning", f"[检查4] type 值不合法: {ptype}（应为 concept/comparison/entity/query 之一）"))
    title = fm.get("title", "")
    if title and ptype in PAGE_TYPES:
        if ptype in ("concept", "comparison") and " · " not in title:
            issues.append(("warning", f"[检查4] title 格式与 type={ptype} 不匹配（应为「模块名 · 页面主标题」）"))
        elif ptype == "entity" and not title.startswith("实体 ·"):
            issues.append(("warning", "[检查4] title 格式与 type=entity 不匹配（应为「实体 · 实体名称」）"))
        elif ptype == "query" and not title.startswith("问答 ·"):
            issues.append(("warning", "[检查4] title 格式与 type=query 不匹配（应为「问答 · 问题简述」）"))
    return issues


def parse_page_tags(fm: dict) -> list:
    """解析页面 tags 字段为标签列表（兼容 # 前缀与逗号/空格分隔）。"""
    raw = fm.get("tags", "")
    if not raw:
        return []
    return re.findall(r"#?([a-zA-Z0-9\u4e00-\u9fff\-_]+)", raw)


def check_tag_registry(fm: dict, schema_tags: set) -> list:
    """
    检查 5（前半）：页面标签是否在 SCHEMA 标签体系中注册。
    未注册 → Warning（SOP-003 检查 5 输出为 [警告]）。
    SCHEMA 不存在或未解析到任何注册标签时由调用方跳过。
    """
    issues = []
    for tag in parse_page_tags(fm):
        if tag not in schema_tags:
            issues.append(("warning", f"[检查5] 标签 '#{tag}' 未在 SCHEMA 标签体系中注册"))
    return issues


def check_wikilinks(content: str, all_wiki_slugs: set) -> list:
    """
    检查 1：wikilink 管道格式与断链。

    格式非法（无管道符）→ Error：无法判定目标，且违反 SCHEMA 第六章。
    目标 slug 不存在    → Error：知识图谱断裂。
    行内代码与代码块内的 [[...]] 已在 extract_wikilinks 中排除。
    外部 URL（http/https）跳过。
    """
    issues = []
    links = extract_wikilinks(content)
    for link in links:
        if link.startswith("http://") or link.startswith("https://"):
            continue
        if "|" not in link:
            issues.append(("error", f"[检查1] wikilink 缺少管道格式: [[{link}]]（期望 [[slug|title]]）"))
            continue
        target = wikilink_target_slug(link)
        found = any(target == slug or target == Path(slug).stem for slug in all_wiki_slugs)
        if not found:
            issues.append(("error", f"[检查1] wikilink 目标不存在: [[{link}]] → '{target}'"))
    return issues


def check_page_lines(content: str) -> list:
    """
    检查 6：页面行数，两档阈值（SOP-003 检查项 6）。

    Warning：超过 300 行 → 拆分候选
    Error  ：超过 500 行 → 必须拆分红线
    """
    issues = []
    lines = content.count("\n") + 1
    if lines > LINE_LIMIT_ERROR:
        issues.append(("error", f"[检查6] 页面 {lines} 行（红线 {LINE_LIMIT_ERROR}）——必须拆分"))
    elif lines > LINE_LIMIT_WARN:
        issues.append(("warning", f"[检查6] 页面 {lines} 行（阈值 {LINE_LIMIT_WARN}）——拆分候选"))
    return issues


def check_index_integrity(pages_by_stem: dict, index_slugs: set) -> list:
    """
    检查 3：index 完整性——wiki/ 全量页面与 index.md 条目双向比对。

    缺失方向按文件名判定（SCHEMA 规定 index 条目用文件名 slug），
    兼容条目写成完整相对路径的形式；多余方向：条目既不匹配文件名
    也不匹配相对路径。双向均为 Warning；SOP-003 中缺失条目补全属
    Agent 自动修复白名单——脚本只报告。
    """
    issues = []
    known = set(pages_by_stem) | set(pages_by_stem.values())
    for slug in sorted(index_slugs - known):
        issues.append(("warning", f"[检查3] index 多余条目: [[{slug}]]——目标文件不存在，建议删除该条目"))
    for stem, rel in sorted(pages_by_stem.items()):
        if stem not in index_slugs and rel not in index_slugs:
            issues.append(("warning", f"[检查3] index 缺失条目: [[{stem}]]（可由 SOP-003 自动修复）"))
    return issues


def check_log_rotation(log_path: Path) -> list:
    """
    检查 7：log.md 条目数（按 `## [日期]` 头行计数）。

    超过 500 条 → Notice（SOP-003 中轮转属自动修复白名单，脚本只报告）。
    log.md 不存在 → Warning（SOP-000 步骤 5 应创建）。
    """
    if not log_path.exists():
        return [("warning", "[检查7] log.md 不存在——SOP-000 步骤 5 应创建")]
    text = log_path.read_text(encoding="utf-8-sig")
    entries = len(re.findall(r"^## \[", text, flags=re.MULTILINE))
    if entries > LOG_ENTRY_LIMIT:
        return [("notice",
                 f"[检查7] log.md 共 {entries} 条记录（阈值 {LOG_ENTRY_LIMIT}）——建议轮转（可由 SOP-003 自动修复）")]
    return []


def check_graph_filter(obsidian_dir: Path) -> list:
    """
    检查 9：.obsidian/graph.json 的 search 过滤规则。

    Obsidian 关闭时会自动覆写 graph.json 清空 search 字段——SOP-003 已知陷阱：
    search 缺失 '-path:schema' 时 SCHEMA/index/log 会污染关系图谱。
    .obsidian/ 目录不存在（非 Obsidian 知识库）时跳过，不报告。
    补全 search 字段在 SOP-003 中属自动修复白名单——脚本只报告。
    """
    if not obsidian_dir.exists():
        return []
    graph_json = obsidian_dir / "graph.json"
    if not graph_json.exists():
        return [("warning",
                 "[检查9] .obsidian/graph.json 不存在——使用 Obsidian 时应配置 search: \"-path:schema\"")]
    try:
        config = json.loads(graph_json.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        return [("error", f"[检查9] graph.json 解析失败: {exc}")]
    search = config.get("search") or ""
    if "-path:schema" not in search:
        return [("error",
                 "[检查9] 图谱过滤缺失: graph.json search 字段未包含 '-path:schema'（可由 SOP-003 自动修复）")]
    return []


# ============================================================
#  主函数 —— 串联所有检查，输出结构化报告
# ============================================================

def lint(kb_path: str) -> dict:
    """
    对知识库执行全量 Lint 扫描。

    流程：
      1. 预读 wiki/ 全部页面（内容 + frontmatter），供各项检查复用
      2. 第一遍：构建入链映射（检查 2 / 检查 8 的数据基础）
      3. 第二遍：逐页面执行检查 1 / 4 / 5 / 6，同时收集全库已用标签
      4. 全局检查：孤立页面（2）、entity 孤立（8）、index 完整性（3）、
         已注册未使用标签（5）、日志轮转（7）、图谱过滤（9）

    返回结构化字典，含 errors / warnings / notices 三个列表，
    每条目为 {file, message}，message 带 [检查N] 前缀。
    """
    kb = Path(kb_path)
    wiki_dir = kb / "wiki"
    schema_dir = kb / "schema"
    schema_path = schema_dir / "SCHEMA.md"
    index_path = schema_dir / "index.md"
    log_path = schema_dir / "log.md"
    obsidian_dir = kb / ".obsidian"

    if not wiki_dir.exists():
        return {"kb_path": str(kb), "error": "wiki/ 目录不存在"}

    schema_tags = load_schema_tags(schema_path)
    index_slugs = load_index_slugs(index_path)

    # 预读全部页面；slug 集合含完整相对路径与纯文件名两种形式（断链解析用）
    wiki_files = sorted(wiki_dir.rglob("*.md"))
    pages = {}
    pages_by_stem = {}   # {文件名: 完整相对路径}，index 完整性比对用
    all_wiki_slugs = set()
    for f in wiki_files:
        rel = str(f.relative_to(wiki_dir).with_suffix("")).replace("\\", "/")
        content = f.read_text(encoding="utf-8-sig")
        pages[rel] = {"content": content, "fm": parse_frontmatter(content)}
        all_wiki_slugs.add(rel)
        all_wiki_slugs.add(Path(rel).stem)
        pages_by_stem[Path(rel).stem] = rel

    results = {
        "kb_path": str(kb),
        "pages": len(wiki_files),
        "errors": [],
        "warnings": [],
        "notices": []
    }

    def add(severity: str, file: str, message: str):
        entry = {"file": file, "message": message}
        if severity == "error":
            results["errors"].append(entry)
        elif severity == "warning":
            results["warnings"].append(entry)
        else:
            results["notices"].append(entry)

    # 第一遍：入链映射（哪些页面被哪些页面引用）
    inbound = defaultdict(set)
    for rel, data in pages.items():
        for link in extract_wikilinks(data["content"]):
            if link.startswith("http"):
                continue
            inbound[wikilink_target_slug(link)].add(rel)

    # 第二遍：逐页面检查 1 / 4 / 5 / 6，收集全库已用标签
    used_tags = set()
    for rel, data in sorted(pages.items()):
        fm, content = data["fm"], data["content"]
        used_tags.update(parse_page_tags(fm))
        for severity, msg in check_frontmatter(fm):
            add(severity, rel, msg)
        if schema_tags:
            for severity, msg in check_tag_registry(fm, schema_tags):
                add(severity, rel, msg)
        for severity, msg in check_wikilinks(content, all_wiki_slugs):
            add(severity, rel, msg)
        for severity, msg in check_page_lines(content):
            add(severity, rel, msg)

    # 检查 2 / 检查 8：孤立页面与 entity 孤立（自链接不计入站）
    # entity 页面的入站按「内容页面（非 entities/）引用」判定——SOP-003 检查 8
    for rel in sorted(pages):
        stem = Path(rel).stem
        sources = (inbound.get(rel, set()) | inbound.get(stem, set())) - {rel}
        if rel.startswith("entities/"):
            if not {s for s in sources if not s.startswith("entities/")}:
                add("error", rel, "[检查8] entity 孤立——无内容页面（concept/comparison/query）引用它")
        elif not sources:
            add("error", rel, "[检查2] 孤立页面——入站链接 0，无任何其他页面引用")

    # 检查 3：index 完整性（双向比对）
    if index_path.exists():
        for severity, msg in check_index_integrity(pages_by_stem, index_slugs):
            add(severity, "schema/index.md", msg)
    else:
        add("warning", "schema/index.md", "[检查3] index.md 不存在——SOP-000 步骤 4 应创建")

    # 检查 5（后半）：已注册但未使用（SOP-003 输出为 [提醒]）
    if schema_tags:
        for tag in sorted(schema_tags - used_tags):
            add("notice", "schema/SCHEMA.md",
                f"[检查5] 标签 '#{tag}' 已注册但未使用——建议移除或保留供未来使用")
    elif schema_path.exists():
        add("warning", "schema/SCHEMA.md",
            "[检查5] SCHEMA 标签体系章未解析到注册标签（注册格式：表格行首列反引号包裹，"
            "如 | `rag` | 含义 |）——标签审计跳过")
    else:
        add("warning", "schema/SCHEMA.md", "[检查5] SCHEMA 不存在——标签审计跳过")

    # 检查 7：日志轮转
    for severity, msg in check_log_rotation(log_path):
        add(severity, "schema/log.md", msg)

    # 检查 9：图谱过滤规则（非 Obsidian 知识库自动跳过）
    for severity, msg in check_graph_filter(obsidian_dir):
        add(severity, ".obsidian/graph.json", msg)

    return results


# ============================================================
#  输出格式化 —— 将结构化结果转为人类可读报告
# ============================================================

def format_report(results: dict, quiet: bool = False) -> str:
    """
    将 lint() 返回的结构化结果格式化为可读的文本报告。

    quiet=True 时只输出 Error 级别（用于 CI 模式）。
    """
    if "error" in results:
        return f"致命错误: {results['error']}"

    lines = []
    lines.append("=== 知识库 Lint 报告 ===")
    lines.append(f"知识库: {results['kb_path']}")
    lines.append(f"页面数: {results['pages']}\n")

    # 按严重度分组输出：Errors → Warnings → Notices
    for severity, label in [
        ("errors", "错误 (Errors)"),
        ("warnings", "警告 (Warnings)"),
        ("notices", "提示 (Notices)")
    ]:
        items = results.get(severity, [])
        if quiet and severity != "errors":
            continue  # CI 模式跳过非 Error
        lines.append(f"--- {label} ({len(items)} 条) ---")
        if not items:
            lines.append("  (无)")
        else:
            # 按文件名聚合：同一文件的多个问题合并展示
            by_file = defaultdict(list)
            for item in items:
                by_file[item["file"]].append(item["message"])
            for fname in sorted(by_file):
                flag = {"errors": "☒", "warnings": "⚠", "notices": "ℹ"}[severity]
                lines.append(f"  {flag} {fname}")
                for msg in by_file[fname]:
                    lines.append(f"     → {msg}")
        lines.append("")

    # 汇总统计
    total_errors = len(results.get("errors", []))
    total_warnings = len(results.get("warnings", []))
    total_notices = len(results.get("notices", []))
    lines.append(
        f"汇总: {total_errors} 个错误, {total_warnings} 个警告, {total_notices} 个提示。"
    )
    if total_errors > 0:
        lines.append("⚠ 此知识库需要修复。")
    else:
        lines.append("☑ 此知识库结构健康。")
    return "\n".join(lines)


# ============================================================
#  CLI 入口 —— 解析命令行参数并执行扫描
# ============================================================

if __name__ == "__main__":
    # GBK 控制台（中文 Windows 默认）下 ☒/☑/ℹ 等符号触发 UnicodeEncodeError——统一重配置为 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2:
        print("用法: python scripts/lint.py /path/to/kb [--json] [--quiet]")
        sys.exit(1)

    kb_path = sys.argv[1]
    as_json = "--json" in sys.argv
    quiet = "--quiet" in sys.argv

    results = lint(kb_path)

    if as_json:
        # JSON 模式：输出结构化数据，供其他程序（如 MC-001 Cron）消费
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        # 默认模式：人类可读报告
        print(format_report(results, quiet=quiet))

    # 退出码：有 Error 时返回 1，方便 CI/脚本判断
    if results.get("errors"):
        sys.exit(1)
