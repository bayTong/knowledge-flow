from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"


def _load_script(module_name: str, filename: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load maintenance script {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaintenanceScriptRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lint_module = _load_script("knowledgeflow_lint", "lint.py")
        cls.link_module = _load_script(
            "knowledgeflow_link_validator",
            "link-validator.py",
        )
        cls.index_module = _load_script(
            "knowledgeflow_index_generator",
            "index-generator.py",
        )

    def _run_script(
        self,
        filename: str,
        kb_root: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_ROOT / filename),
                str(kb_root),
                *arguments,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_lint_missing_wiki_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_script("lint.py", Path(temp_dir), "--json")

        self.assertEqual(result.returncode, 2)
        self.assertIn('"error"', result.stdout)

    def test_link_validator_missing_wiki_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_script(
                "link-validator.py",
                Path(temp_dir),
                "--json",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn('"error"', result.stdout)

    def test_index_generator_missing_wiki_never_overwrites_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_root = Path(temp_dir)
            index_path = kb_root / "schema" / "index.md"
            index_path.parent.mkdir()
            index_path.write_text("sentinel\n", encoding="utf-8")

            result = self._run_script(
                "index-generator.py",
                kb_root,
                "--write",
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("致命错误", result.stderr)
            self.assertEqual(index_path.read_text(encoding="utf-8"), "sentinel\n")

    def test_link_validator_ignores_inline_code(self) -> None:
        content = "real [[outside|Outside]] and `[[inside|Inside]]`"

        self.assertEqual(
            self.link_module.extract_wikilinks(content),
            [("outside|Outside", "outside", "Outside")],
        )

    def test_lint_reports_duplicate_basenames_and_ambiguous_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_root = Path(temp_dir)
            for relative in ("wiki/a/shared.md", "wiki/b/shared.md"):
                path = kb_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# shared\n", encoding="utf-8")
            source = kb_root / "wiki" / "source.md"
            source.write_text("[[shared|Shared]]\n", encoding="utf-8")

            result = self.lint_module.lint(str(kb_root))

        messages = [item["message"] for item in result["errors"]]
        self.assertTrue(any("wiki 文件名不唯一" in message for message in messages))
        self.assertTrue(any("wikilink 目标不唯一" in message for message in messages))

    def test_link_validator_rejects_duplicate_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_root = Path(temp_dir)
            for relative in ("wiki/a/shared.md", "wiki/b/shared.md"):
                path = kb_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# shared\n", encoding="utf-8")

            result = self.link_module.validate(str(kb_root))

        self.assertIn("error", result)
        self.assertEqual(result["duplicates"][0]["slug"], "shared")
        self.assertEqual(len(result["duplicates"][0]["paths"]), 2)

    def test_index_generator_rejects_duplicate_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_root = Path(temp_dir)
            for relative in ("wiki/a/shared.md", "wiki/b/shared.md"):
                path = kb_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# shared\n", encoding="utf-8")

            with self.assertRaises(self.index_module.IndexGenerationError):
                self.index_module.generate(str(kb_root))


if __name__ == "__main__":
    unittest.main()
