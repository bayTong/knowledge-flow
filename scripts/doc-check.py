#!/usr/bin/env python3
"""KnowledgeFlow repository-document consistency checker.

This checker intentionally validates only deterministic repository facts:

* README route targets and structure-tree files are present and Git-tracked;
* English and Chinese README route/tree target sets agree;
* relative links in current project Markdown resolve to tracked targets;
* archived research inputs are explicitly listed by the research index;
* selected current-status documents carry one identical machine-readable anchor.

Historical research bodies and the v1.0 archive are not interpreted as current
instructions.  The checker uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable
from urllib.parse import unquote


ROUTE_ALLOWLIST = frozenset(
    {
        "CHANGELOG.md",
        "archive/v1.0/",
        "docs/build-plan.md",
        "docs/c3-0-blocking-behavior-decisions-C3-0阻塞性行为决策.md",
        "docs/capture-and-routing-spec-捕获与路由规范.md",
        "docs/design-authority-and-conflict-register-设计权威与冲突登记.md",
        "docs/improvement-action-plan.md",
        "docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md",
        "docs/post-c3-integrated-assessment-and-implementation-plan-C3后综合评估与实施方案.md",
        "docs/research/README.md",
        "docs/second-brain-vision.md",
        "docs/sop-v2-full.md",
    }
)

README_SPECS = (
    ("README.md", "| Looking for | Jump to |"),
    ("README-zh.md", "| 想看什么 | 跳转 |"),
)

STATUS_ANCHOR_FILES = (
    "README.md",
    "README-zh.md",
    "docs/design-authority-and-conflict-register-设计权威与冲突登记.md",
    "docs/mvp-0-capture-coding-execution-plan-捕获内核编码执行方案.md",
    "docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md",
    "docs/post-c3-integrated-assessment-and-implementation-plan-C3后综合评估与实施方案.md",
)

RESEARCH_INDEX = "docs/research/README.md"
RESEARCH_BODY_PREFIX = "docs/research/"
ARCHIVE_PREFIX = "archive/"

STATUS_RE = re.compile(
    r"^<!-- knowledgeflow-doc-status "
    r"tests=(?P<tests>\d+) "
    r"capture_tests=(?P<capture_tests>\d+) "
    r"script_tests=(?P<script_tests>\d+) "
    r"next_gate=(?P<next_gate>[A-Z0-9.-]+) -->$",
    re.MULTILINE,
)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
TREE_LINE_RE = re.compile(
    r"^(?P<prefix>(?:(?:│   |    ))*)(?:├──|└──)\s+(?P<name>\S+)"
)


class GitInventoryError(RuntimeError):
    """Raised when the repository Git inventory cannot be read safely."""


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _normalise_repo_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def _git_paths(repo_root: Path, *arguments: str) -> set[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=false", *arguments, "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitInventoryError(diagnostic or "git inventory command failed")
    try:
        values = completed.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise GitInventoryError("git inventory was not valid UTF-8") from exc
    return {_normalise_repo_path(value) for value in values if value}


def _git_inventory(repo_root: Path) -> tuple[set[str], set[str]]:
    tracked = _git_paths(repo_root, "ls-files")
    untracked = _git_paths(repo_root, "ls-files", "--others", "--exclude-standard")
    return tracked, untracked


def _read_text(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8-sig")


def _markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        without_inline_code = re.sub(r"`[^`]*`", "", line)
        targets.extend(
            match.group(1).strip()
            for match in MARKDOWN_LINK_RE.finditer(without_inline_code)
        )
    return targets


def _route_table_targets(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index(header)
    except ValueError:
        return []

    table_lines: list[str] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        table_lines.append(line)
    return _markdown_targets("\n".join(table_lines))


def _structure_tree_files(text: str) -> set[str]:
    lines = text.splitlines()
    block: list[str] | None = None
    for index, line in enumerate(lines[:-1]):
        if line.strip().startswith("```") and lines[index + 1].strip() == "knowledge-flow/":
            block = []
            for candidate in lines[index + 2 :]:
                if candidate.strip().startswith("```"):
                    break
                block.append(candidate)
            break
    if block is None:
        return set()

    directories: dict[int, tuple[str, ...]] = {}
    files: set[str] = set()
    for line in block:
        match = TREE_LINE_RE.match(line)
        if match is None:
            continue
        depth = len(match.group("prefix")) // 4
        name = match.group("name")
        parent = directories.get(depth - 1, ()) if depth else ()
        parts = (*parent, name.rstrip("/"))
        for stale_depth in [value for value in directories if value >= depth]:
            del directories[stale_depth]
        if name.endswith("/"):
            directories[depth] = parts
        else:
            files.add("/".join(parts))
    return files


def _resolved_target(
    repo_root: Path,
    source_path: str,
    raw_target: str,
) -> tuple[str | None, str | None]:
    target = html.unescape(raw_target.strip())
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#"):
        return None, None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        if re.match(r"^[A-Za-z]:[/\\]", target):
            return None, "absolute local path"
        return None, None
    if target.startswith(("/", "\\")):
        return None, "absolute local path"

    path_part = unquote(target.split("#", 1)[0])
    if not path_part:
        return None, None
    source_parent = (repo_root / source_path).parent
    repository = repo_root.resolve()
    resolved = (source_parent / path_part).resolve()
    try:
        relative = resolved.relative_to(repository).as_posix()
    except ValueError:
        return None, "target escapes repository"
    return relative, None


def _tracked_target(
    repo_root: Path,
    target: str,
    tracked_files: set[str],
) -> bool:
    target_path = repo_root / target
    if target_path.is_dir():
        prefix = target.rstrip("/") + "/"
        return any(path.startswith(prefix) for path in tracked_files)
    return target in tracked_files


def _validate_target(
    repo_root: Path,
    source_path: str,
    raw_target: str,
    tracked_files: set[str],
    code_prefix: str,
) -> tuple[str | None, list[dict[str, str]]]:
    target, invalid_reason = _resolved_target(repo_root, source_path, raw_target)
    if invalid_reason is not None:
        return None, [
            _issue(
                f"{code_prefix}_INVALID",
                source_path,
                f"{raw_target!r}: {invalid_reason}",
            )
        ]
    if target is None:
        return None, []
    target_path = repo_root / target
    if not target_path.exists():
        return target, [
            _issue(
                f"{code_prefix}_MISSING",
                source_path,
                f"relative target does not exist: {target}",
            )
        ]
    if not _tracked_target(repo_root, target, tracked_files):
        return target, [
            _issue(
                f"{code_prefix}_UNTRACKED",
                source_path,
                f"relative target is not Git-tracked: {target}",
            )
        ]
    return target, []


def _check_untracked_documents(untracked_files: set[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for path in sorted(untracked_files):
        is_root_document = path in {"README.md", "README-zh.md", "CHANGELOG.md"}
        if path.endswith(".md") and (is_root_document or path.startswith("docs/")):
            issues.append(
                _issue(
                    "UNTRACKED_PROJECT_DOCUMENT",
                    path,
                    "project Markdown under the governed document scope is not Git-tracked",
                )
            )
    return issues


def _check_readmes(
    repo_root: Path,
    tracked_files: set[str],
) -> tuple[list[dict[str, str]], int, int]:
    issues: list[dict[str, str]] = []
    route_sets: dict[str, set[str]] = {}
    tree_sets: dict[str, set[str]] = {}

    for path, header in README_SPECS:
        full_path = repo_root / path
        if not full_path.is_file():
            issues.append(_issue("README_MISSING", path, "README file is missing"))
            continue
        text = _read_text(repo_root, path)
        raw_targets = _route_table_targets(text, header)
        if not raw_targets:
            issues.append(
                _issue("README_ROUTE_TABLE_MISSING", path, "route table was not found or is empty")
            )
        resolved_targets: set[str] = set()
        for raw_target in raw_targets:
            target, target_issues = _validate_target(
                repo_root,
                path,
                raw_target,
                tracked_files,
                "README_ROUTE_TARGET",
            )
            issues.extend(target_issues)
            if target is not None:
                if (repo_root / target).is_dir():
                    target += "/"
                resolved_targets.add(target)
        route_sets[path] = resolved_targets
        if resolved_targets != ROUTE_ALLOWLIST:
            missing = sorted(ROUTE_ALLOWLIST - resolved_targets)
            extra = sorted(resolved_targets - ROUTE_ALLOWLIST)
            issues.append(
                _issue(
                    "README_ROUTE_ALLOWLIST_MISMATCH",
                    path,
                    f"missing={missing}; extra={extra}",
                )
            )

        tree_files = _structure_tree_files(text)
        tree_sets[path] = tree_files
        if not tree_files:
            issues.append(
                _issue("README_STRUCTURE_TREE_MISSING", path, "project structure tree is missing")
            )
        for target in sorted(tree_files):
            target_path = repo_root / target
            if not target_path.exists():
                issues.append(
                    _issue(
                        "README_STRUCTURE_TARGET_MISSING",
                        path,
                        f"structure-tree file does not exist: {target}",
                    )
                )
            elif target not in tracked_files:
                issues.append(
                    _issue(
                        "README_STRUCTURE_TARGET_UNTRACKED",
                        path,
                        f"structure-tree file is not Git-tracked: {target}",
                    )
                )

    if len(route_sets) == len(README_SPECS):
        values = list(route_sets.values())
        if values[0] != values[1]:
            issues.append(
                _issue(
                    "README_ROUTE_SET_MISMATCH",
                    "README.md / README-zh.md",
                    "English and Chinese README route target sets differ",
                )
            )
    if len(tree_sets) == len(README_SPECS):
        values = list(tree_sets.values())
        if values[0] != values[1]:
            issues.append(
                _issue(
                    "README_STRUCTURE_SET_MISMATCH",
                    "README.md / README-zh.md",
                    "English and Chinese README structure-tree file sets differ",
                )
            )

    route_count = len(next(iter(route_sets.values()), set()))
    tree_count = len(next(iter(tree_sets.values()), set()))
    return issues, route_count, tree_count


def _is_current_project_markdown(path: str) -> bool:
    if not path.endswith(".md"):
        return False
    if path.startswith(ARCHIVE_PREFIX):
        return False
    if path.startswith(RESEARCH_BODY_PREFIX) and path != RESEARCH_INDEX:
        return False
    return True


def _check_relative_links(
    repo_root: Path,
    tracked_files: set[str],
) -> tuple[list[dict[str, str]], int]:
    issues: list[dict[str, str]] = []
    checked_files = 0
    for path in sorted(tracked_files):
        if not _is_current_project_markdown(path):
            continue
        full_path = repo_root / path
        if not full_path.is_file():
            issues.append(
                _issue("TRACKED_MARKDOWN_MISSING", path, "tracked Markdown is absent from the worktree")
            )
            continue
        checked_files += 1
        for raw_target in _markdown_targets(_read_text(repo_root, path)):
            _, target_issues = _validate_target(
                repo_root,
                path,
                raw_target,
                tracked_files,
                "RELATIVE_LINK_TARGET",
            )
            issues.extend(target_issues)
    return issues, checked_files


def _check_research_index(
    repo_root: Path,
    tracked_files: set[str],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if RESEARCH_INDEX not in tracked_files or not (repo_root / RESEARCH_INDEX).is_file():
        return [
            _issue(
                "RESEARCH_INDEX_MISSING",
                RESEARCH_INDEX,
                "research index must exist and be Git-tracked",
            )
        ]

    indexed: set[str] = set()
    for raw_target in _markdown_targets(_read_text(repo_root, RESEARCH_INDEX)):
        target, _ = _resolved_target(repo_root, RESEARCH_INDEX, raw_target)
        if target is not None and target.startswith(RESEARCH_BODY_PREFIX):
            indexed.add(target)
    bodies = {
        path
        for path in tracked_files
        if path.startswith(RESEARCH_BODY_PREFIX)
        and path != RESEARCH_INDEX
        and path.endswith(".md")
    }
    missing = sorted(bodies - indexed)
    extra = sorted(indexed - bodies)
    if missing or extra:
        issues.append(
            _issue(
                "RESEARCH_INDEX_ALLOWLIST_MISMATCH",
                RESEARCH_INDEX,
                f"unlisted_tracked_inputs={missing}; indexed_non_inputs={extra}",
            )
        )
    return issues


def _check_status_anchors(
    repo_root: Path,
) -> tuple[list[dict[str, str]], dict[str, int | str] | None]:
    issues: list[dict[str, str]] = []
    values_by_path: dict[str, dict[str, int | str]] = {}
    for path in STATUS_ANCHOR_FILES:
        full_path = repo_root / path
        if not full_path.is_file():
            issues.append(_issue("STATUS_FILE_MISSING", path, "status-anchor file is missing"))
            continue
        matches = list(STATUS_RE.finditer(_read_text(repo_root, path)))
        if len(matches) != 1:
            issues.append(
                _issue(
                    "STATUS_ANCHOR_COUNT",
                    path,
                    f"expected exactly one status anchor, found {len(matches)}",
                )
            )
            continue
        groups = matches[0].groupdict()
        values: dict[str, int | str] = {
            "tests": int(groups["tests"]),
            "capture_tests": int(groups["capture_tests"]),
            "script_tests": int(groups["script_tests"]),
            "next_gate": groups["next_gate"],
        }
        if values["tests"] != values["capture_tests"] + values["script_tests"]:
            issues.append(
                _issue(
                    "STATUS_TEST_TOTAL_INVALID",
                    path,
                    "tests must equal capture_tests + script_tests",
                )
            )
        values_by_path[path] = values

    canonical = values_by_path.get(STATUS_ANCHOR_FILES[0])
    if canonical is not None:
        for path, values in values_by_path.items():
            if values != canonical:
                issues.append(
                    _issue(
                        "STATUS_ANCHOR_MISMATCH",
                        path,
                        f"expected {canonical}, found {values}",
                    )
                )
    return issues, canonical


def check_repository(
    repo_root: Path | str,
    *,
    tracked_files: Iterable[str] | None = None,
    untracked_files: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a deterministic report for ``repo_root``.

    ``tracked_files`` and ``untracked_files`` are injectable only to make unit
    fixtures independent from a real Git index.  Normal callers should omit them.
    """

    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise GitInventoryError(f"repository path is not a directory: {root}")
    if tracked_files is None and untracked_files is None:
        tracked, untracked = _git_inventory(root)
    elif tracked_files is not None:
        tracked = {_normalise_repo_path(path) for path in tracked_files}
        untracked = {
            _normalise_repo_path(path) for path in (untracked_files or ())
        }
    else:
        raise ValueError("untracked_files cannot be supplied without tracked_files")

    issues = _check_untracked_documents(untracked)
    readme_issues, route_count, tree_count = _check_readmes(root, tracked)
    issues.extend(readme_issues)
    link_issues, markdown_count = _check_relative_links(root, tracked)
    issues.extend(link_issues)
    issues.extend(_check_research_index(root, tracked))
    status_issues, status = _check_status_anchors(root)
    issues.extend(status_issues)
    issues.sort(key=lambda item: (item["code"], item["path"], item["message"]))

    return {
        "repository": str(root),
        "errors": issues,
        "stats": {
            "tracked_files": len(tracked),
            "untracked_files": len(untracked),
            "markdown_files_checked": markdown_count,
            "route_targets": route_count,
            "structure_files": tree_count,
            "status": status,
        },
    }


def _format_report(report: dict[str, object]) -> str:
    errors = report["errors"]
    assert isinstance(errors, list)
    if not errors:
        stats = report["stats"]
        assert isinstance(stats, dict)
        return (
            "文档一致性检查通过："
            f"{stats['markdown_files_checked']} 个现行 Markdown，"
            f"{stats['route_targets']} 个路由目标，"
            f"{stats['structure_files']} 个结构树文件。"
        )
    lines = [f"文档一致性检查失败：{len(errors)} 个错误"]
    for item in errors:
        assert isinstance(item, dict)
        lines.append(f"- [{item['code']}] {item['path']}: {item['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    arguments = parser.parse_args(argv)

    try:
        report = check_repository(arguments.repo_root)
    except (GitInventoryError, OSError, UnicodeError, ValueError) as exc:
        fatal = {"repository": str(arguments.repo_root), "fatal": str(exc)}
        if arguments.json:
            print(json.dumps(fatal, ensure_ascii=False, indent=2))
        else:
            print(f"致命错误：{exc}", file=sys.stderr)
        return 2

    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_report(report))
    errors = report["errors"]
    assert isinstance(errors, list)
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    raise SystemExit(main())
