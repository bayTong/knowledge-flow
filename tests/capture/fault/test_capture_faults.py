"""C6A real-process crash recovery for the initial capture transaction."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_FAULT_EXIT_CODE = 70
_CAPTURE_FAULT_POINTS = (
    "after_lock_acquired",
    "after_payload_written",
    "after_payload_flushed",
    "after_envelope_written",
    "after_readback_verified",
    "after_version_renamed",
    "after_event_appended",
    "after_projection_replaced",
    "before_receipt_returned",
)


class CaptureFaultRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C6A business crash recovery is Windows-first")

    def _initialize(self, owned_root: Path) -> tuple[Path, Path]:
        config_path = owned_root / "config" / "config.yaml"
        capture_root = owned_root / "capture-store"
        result = init_capture_store(
            config_path=config_path,
            capture_root=capture_root,
            inline_text_threshold_bytes=128,
            max_text_version_bytes=4096,
            path_policy=PathPolicy.test_owned(owned_root),
        )
        self.assertNotIsInstance(result, FailureResult)
        return config_path, capture_root

    def _run(
        self,
        *arguments: object,
        expected_exit: int,
    ) -> None:
        completed = subprocess.run(
            [sys.executable, str(_SUPPORT_SCRIPT), *(str(value) for value in arguments)],
            cwd=_REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            expected_exit,
            (completed.stdout, completed.stderr),
        )

    def _capture(
        self,
        *,
        owned_root: Path,
        config_path: Path,
        text: str,
        key: str,
        result_path: Path,
        fault_point: str | None = None,
    ) -> dict[str, object] | None:
        arguments: list[object] = [
            "capture-text-c6",
            owned_root,
            config_path,
            text,
            key,
            result_path,
        ]
        expected_exit = 0
        if fault_point is not None:
            arguments.extend(("--fault-point", fault_point))
            expected_exit = _FAULT_EXIT_CODE
        self._run(*arguments, expected_exit=expected_exit)
        if fault_point is not None:
            self.assertFalse(result_path.exists())
            return None
        return json.loads(result_path.read_text(encoding="utf-8"))

    def test_all_capture_fault_points_recover_in_a_new_process(self) -> None:
        for point in _CAPTURE_FAULT_POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temporary:
                owned_root = Path(temporary).resolve()
                config_path, capture_root = self._initialize(owned_root)
                unknown = capture_root / ".staging" / "unknown-tree"
                unknown.mkdir()
                sentinel = unknown / "sentinel.bin"
                sentinel.write_bytes(b"unknown staging must remain")
                text = f"C6A capture crash boundary: {point}"
                key = f"c6a-capture-{point}"

                self._capture(
                    owned_root=owned_root,
                    config_path=config_path,
                    text=text,
                    key=key,
                    result_path=owned_root / "fault-result.json",
                    fault_point=point,
                )
                crashed = tuple(
                    path
                    for path in (capture_root / ".staging").iterdir()
                    if path != unknown
                )
                self.assertEqual(len(crashed), 1)
                self.assertTrue((crashed[0] / "transaction.yaml").is_file())
                self.assertTrue((crashed[0] / "active.lock").is_file())

                recovered = self._capture(
                    owned_root=owned_root,
                    config_path=config_path,
                    text=text,
                    key=key,
                    result_path=owned_root / "recovered-result.json",
                )
                assert recovered is not None
                self.assertTrue(recovered["ok"])
                self.assertTrue(recovered["saved"])
                self.assertEqual(recovered["commit_state"], "committed")
                self.assertEqual(
                    tuple((capture_root / ".staging").iterdir()),
                    (unknown,),
                )
                self.assertEqual(sentinel.read_bytes(), b"unknown staging must remain")

                retried = self._capture(
                    owned_root=owned_root,
                    config_path=config_path,
                    text=text,
                    key=key,
                    result_path=owned_root / "retry-result.json",
                )
                assert retried is not None
                for field in (
                    "capture_id",
                    "version",
                    "event_id",
                    "envelope_sha256",
                ):
                    self.assertEqual(retried[field], recovered[field])

                items = tuple(capture_root.glob("items/*/*/cap_*"))
                self.assertEqual(len(items), 1)
                self.assertEqual(
                    (items[0] / "versions" / "000001" / "payloads" / "primary.txt").read_text(
                        encoding="utf-8"
                    ),
                    text,
                )
                self.assertEqual(len(tuple((items[0] / "events").glob("*.yaml"))), 1)


if __name__ == "__main__":
    unittest.main()
