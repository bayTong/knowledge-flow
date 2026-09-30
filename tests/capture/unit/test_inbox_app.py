from __future__ import annotations

import inspect
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from knowledgeflow_capture import inbox, inbox_app
from knowledgeflow_capture.inbox_app import _run_inbox
from knowledgeflow_capture.paths import PathPolicy


class InboxAppUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0C inbox entry is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()

    def _run(
        self,
        *arguments: str,
        launcher: object | None = None,
        policy_factory: object | None = None,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        keywords: dict[str, object] = {
            "stdout": stdout,
            "stderr": stderr,
            "launcher": launcher,
        }
        if policy_factory is not None:
            keywords["path_policy_factory"] = policy_factory
        code = _run_inbox(arguments, **keywords)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_is_offline_and_does_not_construct_runtime_or_gui(self) -> None:
        calls: list[str] = []

        def forbidden_policy() -> object:
            calls.append("policy")
            raise AssertionError("policy should not be built")

        def forbidden_launcher(_session: object) -> int:
            calls.append("launcher")
            raise AssertionError("GUI should not launch")

        code, stdout, stderr = self._run(
            "--help",
            launcher=forbidden_launcher,
            policy_factory=forbidden_policy,
        )

        self.assertEqual(code, 0)
        self.assertIn("knowledgeflow-inbox", stdout)
        self.assertIn("不会初始化", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(calls, [])

    def test_invalid_arguments_have_fixed_path_and_body_free_error(self) -> None:
        secret = r"C:\private\秘密正文"
        code, stdout, stderr = self._run("--text", secret)

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "knowledgeflow-inbox: invalid arguments\n")
        self.assertNotIn(secret, stderr)

    def test_launcher_receives_session_but_internal_failure_is_fixed(self) -> None:
        policy = PathPolicy.test_owned(self.owned_root)
        seen: list[object] = []

        def launcher(session: object) -> int:
            seen.append(session)
            raise RuntimeError(r"C:\private\秘密正文")

        code, stdout, stderr = self._run(
            "--config",
            str(self.owned_root / "config.yaml"),
            launcher=launcher,
            policy_factory=lambda: policy,
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "knowledgeflow-inbox: internal failure\n")
        self.assertEqual(len(seen), 1)
        self.assertNotIn("private", stderr)
        self.assertNotIn("秘密正文", stderr)

    def test_installed_entry_has_no_test_policy_or_text_argument_surface(self) -> None:
        self.assertEqual(inbox_app.__all__, ())
        self.assertEqual(tuple(inspect.signature(inbox_app.main).parameters), ())
        source = inspect.getsource(inbox_app.main)
        self.assertNotIn("test_owned", source)
        self.assertNotIn("environ", source)
        self.assertNotIn("text", inspect.getsource(inbox_app._parse_arguments))
        boundary_source = inspect.getsource(inbox) + inspect.getsource(inbox_app)
        for forbidden in (
            "import socket",
            "import subprocess",
            "import tempfile",
            "import urllib",
            "import requests",
            "from .store",
            "from knowledgeflow_capture.store",
        ):
            self.assertNotIn(forbidden, boundary_source)

        class Control:
            def __init__(self) -> None:
                self.state = "normal"

            def configure(self, *, state: str) -> None:
                self.state = state

        window = object.__new__(inbox_app._TkInboxWindow)
        window._configured_ready = False
        window._session = SimpleNamespace(
            pending_state=None,
            current_document=None,
        )
        window._new_button = Control()
        window._append_button = Control()
        window._retry_button = Control()
        window._abandon_button = Control()
        window._save_button = Control()
        window._editor_text = Control()
        window._sync_pending_controls()
        self.assertEqual(window._new_button.state, "disabled")
        self.assertEqual(window._append_button.state, "disabled")
        self.assertEqual(window._save_button.state, "disabled")
        self.assertEqual(window._editor_text.state, "disabled")
        pyproject = (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'knowledgeflow-inbox = "knowledgeflow_capture.inbox_app:main"',
            pyproject,
        )


if __name__ == "__main__":
    unittest.main()
