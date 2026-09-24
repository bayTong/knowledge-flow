from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from unittest import mock

from knowledgeflow_capture import cli as cli_module
from knowledgeflow_capture.cli import (
    _CliDependencies,
    _execute_operation,
    _production_path_policy,
    _production_source_root,
    _run_cli,
)
from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    UserIntent,
)
from knowledgeflow_capture.operations import append_capture_version, capture_text
from knowledgeflow_capture.paths import PathPolicy, PathPolicyError
from knowledgeflow_capture.store import init_capture_store

from .._samples import CAPTURE_ID


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_cli_support.py"
_REQUEST_SCHEMA = "knowledgeflow.capture-cli-request"
_RESPONSE_SCHEMA = "knowledgeflow.capture-cli-response"
_MAXIMUM = 1024 * 1024
_STABLE_CAPTURE_FIELDS = (
    "capture_id",
    "event_id",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)
_STABLE_APPEND_FIELDS = (
    "capture_id",
    "event_id",
    "previous_version",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)


class _FailingOutputSpool:
    def __enter__(self) -> _FailingOutputSpool:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _size: int = -1, /) -> bytes:
        return b""

    def write(self, _source: bytes, /) -> int:
        raise OSError("sensitive temporary output path")

    def seek(self, _offset: int, _whence: int = 0, /) -> int:
        return 0

    def flush(self) -> None:
        return None


class CliIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C7 CLI integration is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=16,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)

    @staticmethod
    def _channel() -> dict[str, object]:
        return {
            "type": "app",
            "instance_id": "c7b-integration",
            "external_ref": "message-42",
            "source_created_at": "2026-09-24T01:02:03.004Z",
        }

    @staticmethod
    def _python_channel() -> ChannelMetadata:
        return ChannelMetadata(
            type="app",
            instance_id="c7b-integration",
            external_ref="message-42",
            source_created_at="2026-09-24T01:02:03.004Z",
        )

    def _frame(
        self,
        body: bytes = b"",
        **business_fields: object,
    ) -> bytes:
        header = {
            "schema": _REQUEST_SCHEMA,
            "schema_version": 1,
            "body_length_bytes": len(body),
            **business_fields,
        }
        return (
            json.dumps(
                header,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
            + body
        )

    def _run(
        self,
        operation: str,
        frame: bytes,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                str(self.owned_root),
                operation,
                "--config",
                str(self.config_path),
            ],
            input=frame,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )

    def _decode(
        self,
        completed: subprocess.CompletedProcess[bytes],
    ) -> tuple[dict[str, object], bytes]:
        header_source, separator, body = completed.stdout.partition(b"\n")
        self.assertEqual(separator, b"\n")
        header = json.loads(header_source.decode("utf-8"))
        self.assertEqual(header["schema"], _RESPONSE_SCHEMA)
        self.assertEqual(header["schema_version"], 1)
        self.assertEqual(len(body), header["body_length_bytes"])
        return header, body

    @staticmethod
    def _operation_payload(header: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in header.items()
            if key not in {"schema", "schema_version", "body_length_bytes"}
        }

    def _capture(
        self,
        *,
        body: bytes,
        key: str,
    ) -> dict[str, object]:
        completed = self._run(
            "capture_text",
            self._frame(
                body,
                channel=self._channel(),
                idempotency_key=key,
                user_intent={"processing_mode": "capture-only"},
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        header, response_body = self._decode(completed)
        self.assertEqual(response_body, b"")
        return header

    def test_cli_14_capture_round_trip_replay_matches_python_api(self) -> None:
        body = "子进程捕获🙂".encode("utf-8")
        first = self._capture(body=body, key="c7b-capture-replay")
        second = self._capture(body=body, key="c7b-capture-replay")
        for field in _STABLE_CAPTURE_FIELDS:
            self.assertEqual(first[field], second[field])
        self.assertEqual(first["commit_state"], "committed")
        self.assertEqual(second["warnings"], [])

        direct = capture_text(
            CaptureTextRequest(
                text=io.BytesIO(body),
                channel=self._python_channel(),
                idempotency_key="c7b-capture-replay",
                user_intent=UserIntent(processing_mode="capture-only"),
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertEqual(self._operation_payload(second), direct.to_dict())

    def test_cli_15_append_round_trip_idempotency_precedes_cas(self) -> None:
        captured = self._capture(body=b"version one", key="c7b-base")
        capture_id = captured["capture_id"]
        self.assertIsInstance(capture_id, str)

        def append_frame(text: bytes, expected: int, key: str) -> bytes:
            return self._frame(
                text,
                capture_id=capture_id,
                expected_current_version=expected,
                channel=self._channel(),
                idempotency_key=key,
            )

        first = self._run(
            "append_capture_version",
            append_frame(b"version two", 1, "c7b-append-first"),
        )
        second = self._run(
            "append_capture_version",
            append_frame(b"version three", 2, "c7b-append-second"),
        )
        replay = self._run(
            "append_capture_version",
            append_frame(b"version two", 1, "c7b-append-first"),
        )
        for completed in (first, second, replay):
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, b"")
        first_header, _ = self._decode(first)
        replay_header, _ = self._decode(replay)
        for field in _STABLE_APPEND_FIELDS:
            self.assertEqual(first_header[field], replay_header[field])
        self.assertEqual(replay_header["version"], 2)

        direct = append_capture_version(
            AppendCaptureVersionRequest(
                capture_id=capture_id,
                expected_current_version=1,
                text=io.BytesIO(b"version two"),
                channel=self._python_channel(),
                idempotency_key="c7b-append-first",
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertEqual(self._operation_payload(replay_header), direct.to_dict())

        conflict = self._run(
            "append_capture_version",
            append_frame(b"loser", 1, "c7b-append-loser"),
        )
        self.assertEqual(conflict.returncode, 2)
        conflict_header, conflict_body = self._decode(conflict)
        self.assertEqual(conflict_body, b"")
        self.assertEqual(conflict_header["commit_state"], "not-committed")
        self.assertEqual(conflict_header["error"]["code"], "version_conflict")

    def test_cli_16_list_empty_multiple_pages_and_bad_cursor(self) -> None:
        empty = self._run("list_captures", self._frame(limit=2))
        self.assertEqual(empty.returncode, 0)
        empty_header, empty_body = self._decode(empty)
        self.assertEqual(empty_header["items"], [])
        self.assertEqual(empty_body, b"")

        for index in range(3):
            self._capture(body=f"item-{index}".encode(), key=f"c7b-list-{index}")
        first = self._run("list_captures", self._frame(limit=2))
        first_header, first_body = self._decode(first)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first_body, b"")
        self.assertEqual(len(first_header["items"]), 2)
        cursor = first_header["next_cursor"]
        self.assertIsInstance(cursor, str)

        second = self._run(
            "list_captures",
            self._frame(limit=2, cursor=cursor),
        )
        second_header, second_body = self._decode(second)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second_body, b"")
        self.assertEqual(len(second_header["items"]), 1)
        first_ids = {item["capture_id"] for item in first_header["items"]}
        second_ids = {item["capture_id"] for item in second_header["items"]}
        self.assertTrue(first_ids.isdisjoint(second_ids))

        invalid = self._run(
            "list_captures",
            self._frame(limit=2, cursor="not-a-cursor"),
        )
        self.assertEqual(invalid.returncode, 2)
        invalid_header, invalid_body = self._decode(invalid)
        self.assertEqual(invalid_body, b"")
        self.assertEqual(invalid_header["error"]["code"], "invalid_input")

    def test_cli_17_and_18_get_exact_body_then_withholds_failed_body(self) -> None:
        source = "精确正文🙂\r\nsecond line".encode("utf-8")
        captured = self._capture(body=source, key="c7b-get")
        capture_id = captured["capture_id"]
        self.assertIsInstance(capture_id, str)

        success = self._run(
            "get_capture",
            self._frame(capture_id=capture_id),
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(success.stderr, b"")
        success_header, success_body = self._decode(success)
        self.assertEqual(success_body, source)
        self.assertEqual(success_header["body_length_bytes"], len(source))
        self.assertEqual(success_header["capture"]["byte_size"], len(source))
        self.assertNotIn(source, success.stdout.split(b"\n", 1)[0])

        missing = self._run(
            "get_capture",
            self._frame(capture_id=CAPTURE_ID),
        )
        self.assertEqual(missing.returncode, 2)
        missing_header, missing_body = self._decode(missing)
        self.assertEqual(missing_header["body_length_bytes"], 0)
        self.assertEqual(missing_header["error"]["code"], "capture_not_found")
        self.assertEqual(missing_body, b"")

        item = next((self.capture_root / "items").glob(f"*/*/{capture_id}"))
        payload = item / "versions" / "000001" / "payloads" / "primary.txt"
        payload.write_bytes(b"x" * len(source))
        corrupt = self._run(
            "get_capture",
            self._frame(capture_id=capture_id),
        )
        self.assertEqual(corrupt.returncode, 2)
        corrupt_header, corrupt_body = self._decode(corrupt)
        self.assertEqual(corrupt_header["body_length_bytes"], 0)
        self.assertEqual(corrupt_header["error"]["code"], "integrity_check_failed")
        self.assertEqual(corrupt_body, b"")
        self.assertNotIn(source[:4], corrupt.stdout)

    def test_cli_19_real_get_sink_failure_is_public_and_redacted(self) -> None:
        captured = self._capture(body=b"sink body", key="c7b-sink")
        capture_id = captured["capture_id"]
        stdin = io.BytesIO(self._frame(capture_id=capture_id))
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        exit_code = _run_cli(
            ["get_capture", "--config", str(self.config_path)],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            path_policy=self.policy,
            executor=_execute_operation,
            dependencies=_CliDependencies(
                temporary_file_factory=lambda purpose: (
                    _FailingOutputSpool()
                    if purpose == "output"
                    else tempfile.TemporaryFile(mode="w+b")
                )
            ),
        )
        self.assertEqual(exit_code, 2)
        header_source, separator, body = stdout.getvalue().partition(b"\n")
        self.assertEqual(separator, b"\n")
        header = json.loads(header_source)
        self.assertEqual(header["error"]["code"], "output_write_failed")
        self.assertTrue(header["error"]["retryable"])
        self.assertEqual(header["body_length_bytes"], 0)
        self.assertEqual(body, b"")
        self.assertEqual(stderr.getvalue(), b"")
        self.assertNotIn(b"sensitive", stdout.getvalue())

    def test_cli_21_and_22_real_core_failure_has_stable_exit_and_no_secrets(self) -> None:
        secret_body = b"never echo this body"
        secret_key = "never-echo-this-key"
        missing_config = self.owned_root / "missing-secret-config.yaml"
        completed = self._run(
            "capture_text",
            self._frame(
                secret_body,
                channel=self._channel(),
                idempotency_key=secret_key,
            ),
        )
        self.assertEqual(completed.returncode, 0)

        unavailable = subprocess.run(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                str(self.owned_root),
                "capture_text",
                "--config",
                str(missing_config),
            ],
            input=self._frame(
                secret_body,
                channel=self._channel(),
                idempotency_key=secret_key,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(unavailable.returncode, 2)
        header, body = self._decode(unavailable)
        self.assertEqual(header["error"]["code"], "config_not_found")
        self.assertEqual(body, b"")
        self.assertEqual(unavailable.stderr, b"")
        emitted = unavailable.stdout + unavailable.stderr
        for secret in (secret_body, secret_key.encode(), str(missing_config).encode()):
            self.assertNotIn(secret, emitted)

    def test_cli_24_and_25_production_policy_and_installed_entry_are_isolated(
        self,
    ) -> None:
        self.assertEqual(_production_source_root(), _REPOSITORY_ROOT)
        with mock.patch.dict(
            os.environ,
            {"KNOWLEDGEFLOW_TEST_OWNED_ROOT": str(self.owned_root)},
        ):
            production_policy = _production_path_policy()
        with self.assertRaises(PathPolicyError):
            production_policy.validate_capture_root(
                _REPOSITORY_ROOT / "must-not-be-a-store"
            )
        with self.assertRaises(PathPolicyError):
            production_policy.validate_capture_root(
                Path(tempfile.gettempdir()).resolve() / "must-not-be-a-store"
            )
        self.assertEqual(cli_module.__all__, ())

        entry = shutil.which("knowledgeflow-capture")
        if entry is None:
            scripts_directory = Path(sysconfig.get_path("scripts"))
            candidate = scripts_directory / "knowledgeflow-capture.exe"
            entry = str(candidate) if candidate.is_file() else None
        self.assertIsNotNone(entry, "installed console script is not discoverable")
        missing_config = self.owned_root / "entry-missing-config.yaml"
        self.assertFalse(missing_config.exists())
        env = dict(os.environ)
        env["KNOWLEDGEFLOW_TEST_OWNED_ROOT"] = str(self.owned_root)
        completed = subprocess.run(
            [
                entry,
                "list_captures",
                "--config",
                str(missing_config),
            ],
            input=self._frame(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env=env,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        header, body = self._decode(completed)
        self.assertEqual(header["error"]["code"], "config_not_found")
        self.assertEqual(body, b"")
        self.assertEqual(completed.stderr, b"")
        self.assertFalse(missing_config.exists())


if __name__ == "__main__":
    unittest.main()
