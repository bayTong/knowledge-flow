from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.management_cli import _run_management_cli
from knowledgeflow_capture.paths import PathPolicy


class P0BManagementCliTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0B management CLI is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config = self.owned_root / "config" / "config.yaml"
        self.store = self.owned_root / "store"

    def _run(
        self,
        *arguments: str,
        executor: object | None = None,
    ) -> tuple[int, dict[str, object] | None, bytes, bytes]:
        stdout = BytesIO()
        stderr = BytesIO()
        keywords: dict[str, object] = {
            "stdout": stdout,
            "stderr": stderr,
            "path_policy": self.policy,
        }
        if executor is not None:
            keywords["executor"] = executor
        code = _run_management_cli(arguments, **keywords)
        raw = stdout.getvalue()
        decoded = json.loads(raw.decode("utf-8")) if raw else None
        return code, decoded, raw, stderr.getvalue()

    def test_cli_runs_complete_empty_store_management_cycle_without_path_output(self) -> None:
        backup = self.owned_root / "backup"
        restored = self.owned_root / "restored"
        commands = (
            (
                "init",
                "--config",
                str(self.config),
                "--store",
                str(self.store),
                "--inline-threshold",
                "32",
                "--max-version",
                "4096",
            ),
            ("verify", "--config", str(self.config)),
            (
                "backup",
                "--config",
                str(self.config),
                "--target",
                str(backup),
            ),
            (
                "restore",
                "--backup",
                str(backup),
                "--target",
                str(restored),
            ),
        )
        for command in commands:
            code, response, raw, stderr = self._run(*command)
            self.assertEqual(code, 0, stderr)
            self.assertIsNotNone(response)
            self.assertTrue(response["ok"])
            self.assertEqual(response["operation"], command[0])
            self.assertEqual(
                response["schema"],
                "knowledgeflow.capture-management-response",
            )
            self.assertNotIn(str(self.owned_root).encode("utf-8"), raw)
            self.assertEqual(stderr, b"")

    def test_invalid_arguments_return_one_path_free_machine_failure(self) -> None:
        code, response, raw, stderr = self._run(
            "backup",
            "--config",
            str(self.config),
        )

        self.assertEqual(code, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["operation"], "backup")
        self.assertEqual(response["error"]["code"], "invalid_input")
        self.assertNotIn(str(self.owned_root).encode("utf-8"), raw)
        self.assertEqual(stderr, b"")

    def test_expected_core_failure_uses_stdout_and_never_echoes_paths(self) -> None:
        code, response, raw, stderr = self._run(
            "verify",
            "--config",
            str(self.config),
        )

        self.assertEqual(code, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "config_not_found")
        self.assertNotIn(str(self.config).encode("utf-8"), raw)
        self.assertEqual(stderr, b"")

    def test_internal_or_path_leaking_executor_has_fixed_stderr_only(self) -> None:
        def leaking_executor(*_args: object, **_kwargs: object) -> object:
            class _LeakingResult:
                def to_dict(self) -> dict[str, object]:
                    return {
                        "ok": True,
                        "path": str(self_config),
                    }

            self_config = self.config
            return _LeakingResult()

        code, response, raw, stderr = self._run(
            "verify",
            "--config",
            str(self.config),
            executor=leaking_executor,
        )

        self.assertEqual(code, 1)
        self.assertIsNone(response)
        self.assertEqual(raw, b"")
        self.assertEqual(
            stderr,
            b"knowledgeflow-capture-admin: internal failure\n",
        )

        def overriding_executor(*_args: object, **_kwargs: object) -> object:
            class _OverridingResult:
                def to_dict(self) -> dict[str, object]:
                    return {
                        "ok": True,
                        "schema": "forged",
                    }

            return _OverridingResult()

        code, response, raw, stderr = self._run(
            "verify",
            "--config",
            str(self.config),
            executor=overriding_executor,
        )
        self.assertEqual(code, 1)
        self.assertIsNone(response)
        self.assertEqual(raw, b"")
        self.assertEqual(
            stderr,
            b"knowledgeflow-capture-admin: internal failure\n",
        )


if __name__ == "__main__":
    unittest.main()
