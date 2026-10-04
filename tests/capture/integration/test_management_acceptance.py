from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT = (
    _REPOSITORY_ROOT / "tests" / "capture" / "_management_cli_support.py"
)


class P0BInstalledManagementAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0B installed management acceptance is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()

    def _decode(self, completed: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
        self.assertEqual(completed.stderr, b"")
        response = json.loads(completed.stdout.decode("utf-8"))
        self.assertNotIn(str(self.owned_root), completed.stdout.decode("utf-8"))
        return response

    def test_installed_entry_and_package_execute_the_full_empty_store_cycle(self) -> None:
        source_root = self.owned_root / "install-source"
        source_root.mkdir()
        for filename in ("LICENSE", "README.md", "pyproject.toml"):
            shutil.copy2(_REPOSITORY_ROOT / filename, source_root / filename)
        shutil.copytree(
            _REPOSITORY_ROOT / "src",
            source_root / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        environment_root = self.owned_root / "installed-env"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(
            environment_root
        )
        python = environment_root / "Scripts" / "python.exe"
        entry = environment_root / "Scripts" / "knowledgeflow-capture-admin.exe"
        inbox_entry = environment_root / "Scripts" / "knowledgeflow-inbox.exe"
        self.assertFalse(entry.exists())
        self.assertFalse(inbox_entry.exists())

        build_temp = self.owned_root / "build-temp"
        pip_cache = self.owned_root / "pip-cache"
        build_temp.mkdir()
        pip_cache.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "TMP": str(build_temp),
                "TEMP": str(build_temp),
                "PIP_CACHE_DIR": str(pip_cache),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            }
        )
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        installed = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-build-isolation",
                "--no-deps",
                "--no-index",
                str(source_root),
            ],
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=240,
        )
        self.assertEqual(
            installed.returncode,
            0,
            installed.stderr.decode("utf-8", "replace"),
        )
        self.assertTrue(entry.is_file())
        self.assertTrue(inbox_entry.is_file())

        inbox_environment = environment.copy()
        inbox_environment["PYTHONIOENCODING"] = "cp1252:strict"
        inbox_help = subprocess.run(
            [str(inbox_entry), "--help"],
            cwd=self.owned_root,
            env=inbox_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        self.assertEqual(inbox_help.returncode, 0)
        self.assertEqual(inbox_help.stderr, b"")
        self.assertIn(b"knowledgeflow-inbox", inbox_help.stdout)
        self.assertIn("不会初始化".encode("utf-8"), inbox_help.stdout)
        self.assertNotIn(str(self.owned_root).encode("utf-8"), inbox_help.stdout)

        imported = subprocess.run(
            [
                str(python),
                "-c",
                "import pathlib,knowledgeflow_capture.management; "
                "print(pathlib.Path(knowledgeflow_capture.management.__file__).resolve())",
            ],
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
            text=True,
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        imported_path = Path(imported.stdout.strip())
        self.assertTrue(imported_path.is_relative_to(environment_root))
        self.assertFalse(imported_path.is_relative_to(_REPOSITORY_ROOT))

        missing = subprocess.run(
            [str(entry), "verify", "--config", str(self.owned_root / "missing.yaml")],
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        self.assertEqual(missing.returncode, 2)
        missing_response = self._decode(missing)
        self.assertFalse(missing_response["ok"])

        config = self.owned_root / "config" / "config.yaml"
        store = self.owned_root / "store"
        backup = self.owned_root / "backup"
        restored = self.owned_root / "restored"
        commands = (
            (
                "init",
                "--config",
                str(config),
                "--store",
                str(store),
                "--inline-threshold",
                "32",
                "--max-version",
                "4096",
            ),
            ("verify", "--config", str(config)),
            ("backup", "--config", str(config), "--target", str(backup)),
            ("restore", "--backup", str(backup), "--target", str(restored)),
        )
        for command in commands:
            completed = subprocess.run(
                [
                    str(python),
                    str(_SUPPORT),
                    str(self.owned_root),
                    *command,
                ],
                cwd=self.owned_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=120,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", "replace"),
            )
            response = self._decode(completed)
            self.assertTrue(response["ok"])
            self.assertEqual(response["operation"], command[0])


if __name__ == "__main__":
    unittest.main()
