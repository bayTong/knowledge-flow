from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "doc-check.py"
STATUS_MARKER = (
    "<!-- knowledgeflow-doc-status tests=156 capture_tests=141 "
    "script_tests=15 next_gate=C4-0 -->"
)


def _load_script() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("knowledgeflow_doc_check", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load doc-check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocCheckRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_script()

    def _write(self, root: Path, relative: str, content: str = "# Fixture\n") -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def _fixture(self, root: Path) -> tuple[set[str], set[str]]:
        route_rows = "\n".join(
            f"| {index} | [target]({target}) |"
            for index, target in enumerate(sorted(self.module.ROUTE_ALLOWLIST), start=1)
        )
        tree = """```text
knowledge-flow/
├── README.md
├── README-zh.md
└── docs/
    └── research/
        └── README.md
```
"""
        english = (
            "# Fixture\n\n"
            f"{STATUS_MARKER}\n\n"
            "| Looking for | Jump to |\n"
            "|---|---|\n"
            f"{route_rows}\n\n"
            "## Project Structure\n\n"
            f"{tree}"
        )
        chinese = (
            "# Fixture\n\n"
            f"{STATUS_MARKER}\n\n"
            "| 想看什么 | 跳转 |\n"
            "|---|---|\n"
            f"{route_rows}\n\n"
            "## 项目结构\n\n"
            f"{tree}"
        )
        self._write(root, "README.md", english)
        self._write(root, "README-zh.md", chinese)

        for target in self.module.ROUTE_ALLOWLIST:
            if target.endswith("/"):
                self._write(root, f"{target}README.md")
            elif target not in {"README.md", "README-zh.md"}:
                self._write(root, target)

        for path in self.module.STATUS_ANCHOR_FILES:
            if path not in {"README.md", "README-zh.md"}:
                self._write(root, path, f"# Status\n\n{STATUS_MARKER}\n")

        research_body = "docs/research/2026-09-11/input.md"
        self._write(root, research_body, "# Historical input\n")
        self._write(
            root,
            "docs/research/README.md",
            "# Research\n\n[Input](2026-09-11/input.md)\n",
        )
        self._write(root, "docs/link-source.md", "[Build](build-plan.md)\n")
        tracked = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        }
        return tracked, set()

    def _codes(self, report: dict[str, object]) -> set[str]:
        errors = report["errors"]
        assert isinstance(errors, list)
        return {str(item["code"]) for item in errors}

    def test_cli_current_repository_passes_as_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(PROJECT_ROOT), "--json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            report["stats"]["status"],
            {
                "tests": 212,
                "capture_tests": 197,
                "script_tests": 15,
                "next_gate": "C4V",
            },
        )

    def test_untracked_project_document_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            self._write(root, "docs/untracked-review.md")
            untracked.add("docs/untracked-review.md")

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("UNTRACKED_PROJECT_DOCUMENT", self._codes(report))

    def test_route_target_must_be_tracked_even_when_it_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            tracked.remove("docs/build-plan.md")
            untracked.add("docs/build-plan.md")

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("README_ROUTE_TARGET_UNTRACKED", self._codes(report))

    def test_english_and_chinese_route_sets_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            chinese = (root / "README-zh.md").read_text(encoding="utf-8")
            chinese = "\n".join(
                line for line in chinese.splitlines() if "docs/build-plan.md" not in line
            ) + "\n"
            self._write(root, "README-zh.md", chinese)

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        codes = self._codes(report)
        self.assertIn("README_ROUTE_SET_MISMATCH", codes)
        self.assertIn("README_ROUTE_ALLOWLIST_MISMATCH", codes)

    def test_structure_tree_file_must_be_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            self._write(root, "stray.md")
            untracked.add("stray.md")
            for readme in ("README.md", "README-zh.md"):
                text = (root / readme).read_text(encoding="utf-8")
                text = text.replace("└── docs/", "├── stray.md\n└── docs/")
                self._write(root, readme, text)

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("README_STRUCTURE_TARGET_UNTRACKED", self._codes(report))

    def test_relative_link_target_must_be_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            self._write(root, "docs/untracked-target.md")
            untracked.add("docs/untracked-target.md")
            self._write(root, "docs/link-source.md", "[Target](untracked-target.md)\n")

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("RELATIVE_LINK_TARGET_UNTRACKED", self._codes(report))

    def test_research_input_must_be_listed_by_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            extra = "docs/research/2026-09-12/extra.md"
            self._write(root, extra)
            tracked.add(extra)

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("RESEARCH_INDEX_ALLOWLIST_MISMATCH", self._codes(report))

    def test_status_anchors_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracked, untracked = self._fixture(root)
            path = "docs/mvp-0-capture-implementation-plan-捕获内核实现拆解与测试矩阵.md"
            mismatched = STATUS_MARKER.replace(
                "tests=156 capture_tests=141 script_tests=15",
                "tests=155 capture_tests=141 script_tests=14",
            )
            self._write(root, path, f"# Status\n\n{mismatched}\n")

            report = self.module.check_repository(
                root,
                tracked_files=tracked,
                untracked_files=untracked,
            )

        self.assertIn("STATUS_ANCHOR_MISMATCH", self._codes(report))


if __name__ == "__main__":
    unittest.main()
