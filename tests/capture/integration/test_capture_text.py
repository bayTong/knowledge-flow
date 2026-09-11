from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import UUID

from knowledgeflow_capture.codec import (
    load_capture_event,
    load_capture_state,
    load_envelope,
)
from knowledgeflow_capture.config import create_local_config, dump_local_config
from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.errors import (
    CommitState,
    CommittedWriteResult,
    FailureResult,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.locking import _acquire_capture_write_lock
from knowledgeflow_capture.models import (
    CaptureTextRequest,
    ChannelMetadata,
    UserIntent,
)
from knowledgeflow_capture.operations import (
    _CaptureDependencies,
    _CaptureFaultPoint,
    _capture_text_with_dependencies,
    capture_text,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store

from .._samples import CAPTURE_ID, EVENT_ID


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_INLINE_THRESHOLD = 16
_MAXIMUM = 64
_FIXED_TIME = datetime(2026, 9, 11, 1, 2, 3, 456789, tzinfo=timezone.utc)
_STAGING_UUID = UUID("01991a7e-7b22-72ae-9ef5-4f45249ad334")
_STABLE_RECEIPT_FIELDS = (
    "capture_id",
    "event_id",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)


class _NonSeekableStream:
    def __init__(self, value: bytes) -> None:
        self._value = value
        self._offset = 0
        self.read_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        if size < 0:
            raise AssertionError("capture_text issued an unbounded read")
        self.read_sizes.append(size)
        start = self._offset
        self._offset = min(len(self._value), start + size)
        return self._value[start : self._offset]


class CaptureTextIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C3C capture transaction is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        self._processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._stop_processes)
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)

    def _stop_processes(self) -> None:
        for process in self._processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def _request(
        self,
        text: str | object,
        *,
        key: str | None = None,
        intent: UserIntent | None = None,
    ) -> CaptureTextRequest:
        return CaptureTextRequest(
            text=text,
            channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            idempotency_key=key,
            user_intent=intent,
        )

    def _capture(
        self,
        request: CaptureTextRequest,
        *,
        dependencies: _CaptureDependencies | None = None,
    ) -> CommittedWriteResult | FailureResult:
        if dependencies is None:
            return capture_text(
                request,
                config_path=self.config_path,
                path_policy=self.policy,
            )
        return _capture_text_with_dependencies(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
            dependencies=dependencies,
        )

    def _item_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                path
                for path in (self.capture_root / "items").glob("*/*/cap_*")
                if path.is_dir()
            )
        )

    def _item_for(self, result: CommittedWriteResult) -> Path:
        receipt = result.to_dict()
        matches = tuple(
            self.capture_root.glob(f"items/*/*/{receipt['capture_id']}")
        )
        self.assertEqual(len(matches), 1)
        return matches[0]

    def _assert_success(
        self,
        result: CommittedWriteResult | FailureResult,
    ) -> CommittedWriteResult:
        self.assertIsInstance(result, CommittedWriteResult)
        success = result
        serialized = success.to_dict()
        self.assertTrue(serialized["ok"])
        self.assertTrue(serialized["saved"])
        self.assertEqual(serialized["commit_state"], "committed")
        return success

    def _assert_failure(
        self,
        result: CommittedWriteResult | FailureResult,
        code: PublicErrorCode,
        state: CommitState,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        self.assertEqual(failure.commit_state, state)
        serialized = failure.to_dict()
        self.assertFalse(serialized["ok"])
        self.assertNotIn("saved", serialized)
        return failure

    def _fixed_dependencies(self, **changes: object) -> _CaptureDependencies:
        base = _CaptureDependencies(
            utc_now=lambda: _FIXED_TIME,
            capture_id_factory=lambda: CAPTURE_ID,
            event_id_factory=lambda: EVENT_ID,
            staging_uuid_factory=lambda: _STAGING_UUID,
        )
        return replace(base, **changes)

    def _assert_item_integrity(
        self,
        result: CommittedWriteResult,
        expected: bytes,
    ) -> None:
        item = self._item_for(result)
        version = item / "versions" / "000001"
        payload_path = version / "payloads" / "primary.txt"
        envelope = load_envelope((version / "envelope.yaml").read_bytes())
        event = load_capture_event(
            (item / "events" / f"{envelope['event_id']}.yaml").read_bytes(),
            envelope=envelope,
        )
        state = load_capture_state(
            (item / "capture.yaml").read_bytes(),
            envelope=envelope,
        )
        self.assertEqual(payload_path.read_bytes(), expected)
        self.assertEqual(event["capture_id"], envelope["capture_id"])
        self.assertEqual(state["current_envelope_sha256"], envelope["envelope_sha256"])

    def test_ct_01_02_04_13_20_preserves_text_and_commits_complete_items(self) -> None:
        values = (
            ("CT-01", "中文 English 🙂"),
            ("CT-02-mixed-lines", "  first\r\nsecond\nlast  "),
            ("CT-04", " \n "),
            ("CT-02-no-final-newline", "no-final-newline"),
        )
        for case_id, value in values:
            with self.subTest(case_id=case_id):
                success = self._assert_success(self._capture(self._request(value)))
                self.assertEqual(success.warnings, ())
                self._assert_item_integrity(success, value.encode("utf-8"))

        self.assertEqual(len(self._item_paths()), len(values))
        self.assertEqual(
            tuple((self.capture_root / "outbox" / "pending").iterdir()),
            (),
        )

    def test_ct_03_08_15_rejects_empty_oversize_bom_and_invalid_utf8(self) -> None:
        invalid_sources = (
            ("CT-03", io.BytesIO(b""), PublicErrorCode.INVALID_INPUT),
            (
                "CT-08-scaled",
                io.BytesIO(b"x" * (_MAXIMUM + 1)),
                PublicErrorCode.TEXT_TOO_LARGE,
            ),
            (
                "CT-15-bom",
                io.BytesIO(b"\xef\xbb\xbfprivate"),
                PublicErrorCode.INVALID_INPUT,
            ),
            ("CT-15-invalid-utf8", io.BytesIO(b"\xff"), PublicErrorCode.INVALID_INPUT),
        )
        for case_id, source, code in invalid_sources:
            with self.subTest(case_id=case_id):
                self._assert_failure(
                    self._capture(self._request(source)),
                    code,
                    CommitState.NOT_COMMITTED,
                )
        self.assertEqual(self._item_paths(), ())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_ct_05_06_07_scaled_thresholds_use_one_bounded_payload(self) -> None:
        cases = (
            ("CT-05-scaled", _INLINE_THRESHOLD),
            ("CT-06-scaled", _INLINE_THRESHOLD + 1),
            ("CT-07-scaled", _MAXIMUM),
        )
        for case_id, size in cases:
            source = _NonSeekableStream(b"x" * size)
            with self.subTest(case_id=case_id, size=size):
                success = self._assert_success(self._capture(self._request(source)))
                self._assert_item_integrity(success, b"x" * size)
                self.assertTrue(source.read_sizes)
                self.assertLessEqual(max(source.read_sizes), _INLINE_THRESHOLD)

    def test_ct_09_higher_local_limit_allows_same_oversize_request_to_retry(self) -> None:
        source = b"x" * (_MAXIMUM + 1)
        self._assert_failure(
            self._capture(self._request(io.BytesIO(source), key="raised-limit")),
            PublicErrorCode.TEXT_TOO_LARGE,
            CommitState.NOT_COMMITTED,
        )
        raised = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=len(source),
            path_policy=self.policy,
        )
        self.config_path.write_bytes(dump_local_config(raised))

        success = self._assert_success(
            self._capture(self._request(io.BytesIO(source), key="raised-limit"))
        )
        self._assert_item_integrity(success, source)

    def test_ct_10_without_key_same_content_creates_distinct_items(self) -> None:
        first = self._assert_success(self._capture(self._request("same"))).to_dict()
        second = self._assert_success(self._capture(self._request("same"))).to_dict()
        self.assertNotEqual(first["capture_id"], second["capture_id"])
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["primary_payload_sha256"], second["primary_payload_sha256"])

    def test_ct_11_12_14_idempotent_retry_unifies_string_and_stream(self) -> None:
        first_success = self._assert_success(
            self._capture(self._request("知识🙂", key="save-42"))
        )
        first = first_success.to_dict()
        self.assertEqual(
            set(first),
            {
                "ok",
                "saved",
                "commit_state",
                "capture_id",
                "event_id",
                "version",
                "primary_payload_sha256",
                "payload_set_sha256",
                "envelope_sha256",
                "durability",
                "routing_status",
                "trust_status",
                "gbrain_sync_status",
                "warnings",
            },
        )
        self.assertNotIn("payload_count", first)
        item = self._item_for(first_success)
        immutable_metadata = (
            (item / "versions" / "000001" / "envelope.yaml").read_bytes()
            + next((item / "events").iterdir()).read_bytes()
            + (item / "capture.yaml").read_bytes()
        )
        self.assertNotIn(b"save-42", immutable_metadata)
        stream = _NonSeekableStream("知识🙂".encode("utf-8"))
        second = self._assert_success(
            self._capture(self._request(stream, key="save-42"))
        ).to_dict()
        for field in _STABLE_RECEIPT_FIELDS:
            self.assertEqual(first[field], second[field])
        self.assertEqual(second["warnings"], [])
        self.assertEqual(len(self._item_paths()), 1)
        self.assertTrue(stream.read_sizes)

        conflict = self._capture(
            self._request(
                "知识🙂",
                key="save-42",
                intent=UserIntent(processing_mode="capture-only"),
            )
        )
        self._assert_failure(
            conflict,
            PublicErrorCode.IDEMPOTENCY_CONFLICT,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(len(self._item_paths()), 1)

    def test_ct_16_core_owns_actor_and_canonical_times(self) -> None:
        success = self._assert_success(
            self._capture(
                self._request("actor boundary"),
                dependencies=self._fixed_dependencies(),
            )
        )
        item = self._item_for(success)
        envelope = load_envelope(
            (item / "versions" / "000001" / "envelope.yaml").read_bytes()
        )
        self.assertEqual(envelope["actor"], {"type": "user", "actor_id": "local-user"})
        for field in ("received_at", "captured_at"):
            self.assertEqual(envelope[field], "2026-09-11T01:02:03.456Z")

    def test_ct_17_two_processes_same_key_commit_at_most_one_item(self) -> None:
        gate = self.owned_root / "capture.gate"
        result_paths = [self.owned_root / f"result-{index}.json" for index in range(2)]
        started_paths = [self.owned_root / f"started-{index}" for index in range(2)]
        for index in range(2):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(_SUPPORT_SCRIPT),
                    "capture-text",
                    str(self.owned_root),
                    str(self.config_path),
                    "concurrent body",
                    "same-process-key",
                    str(started_paths[index]),
                    str(gate),
                    str(result_paths[index]),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._processes.append(process)
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in started_paths):
            if time.monotonic() >= deadline:
                self.fail("capture subprocesses did not reach the gate")
            time.sleep(0.01)
        gate.write_bytes(b"go")
        outputs = []
        for process, result_path in zip(self._processes, result_paths, strict=True):
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
            outputs.append(json.loads(result_path.read_text(encoding="utf-8")))
        self.assertTrue(all(result["ok"] for result in outputs))
        for field in _STABLE_RECEIPT_FIELDS:
            self.assertEqual(outputs[0][field], outputs[1][field])
        self.assertEqual(len(self._item_paths()), 1)

    def test_ct_18_lock_timeout_is_retryable_and_not_committed(self) -> None:
        with _acquire_capture_write_lock(self.capture_root):
            dependencies = _CaptureDependencies(
                lock_factory=lambda root: _acquire_capture_write_lock(
                    root,
                    timeout_seconds=0.01,
                    poll_interval_seconds=0.005,
                )
            )
            failure = self._assert_failure(
                self._capture(self._request("locked"), dependencies=dependencies),
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                CommitState.NOT_COMMITTED,
            )
        self.assertTrue(failure.error.retryable)
        self.assertEqual(self._item_paths(), ())

    def test_ct_19_new_id_target_conflict_is_not_adopted_or_overwritten(self) -> None:
        target = self.capture_root / "items" / "2026" / "09" / CAPTURE_ID
        target.mkdir(parents=True)
        sentinel = target / "sentinel.bin"
        sentinel.write_bytes(b"pre-existing")

        failure = self._assert_failure(
            self._capture(
                self._request("collision"),
                dependencies=self._fixed_dependencies(),
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertTrue(failure.error.retryable)
        self.assertEqual(sentinel.read_bytes(), b"pre-existing")
        self.assertFalse((target / "versions").exists())
        self.assertEqual(tuple(target.iterdir()), (sentinel,))
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_ct_21_event_failure_does_not_commit_an_item(self) -> None:
        def fail_event() -> None:
            raise OSError("injected event write failure")

        dependencies = replace(
            _CaptureDependencies(),
            fault_point=_CaptureFaultPoint.BEFORE_EVENT_WRITE,
            fault_hook=fail_event,
        )
        self._assert_failure(
            self._capture(self._request("event failure"), dependencies=dependencies),
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(self._item_paths(), ())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_ct_22_projection_failure_is_committed_and_retry_does_not_rebuild(self) -> None:
        def fail_projection() -> None:
            raise OSError("injected projection failure")

        dependencies = replace(
            _CaptureDependencies(),
            fault_point=_CaptureFaultPoint.BEFORE_PROJECTION_REPLACE,
            fault_hook=fail_projection,
        )
        first = self._assert_success(
            self._capture(
                self._request("projection failure", key="projection-key"),
                dependencies=dependencies,
            )
        )
        self.assertEqual(
            tuple(w.code for w in first.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )
        item = self._item_for(first)
        self.assertFalse((item / "capture.yaml").exists())
        immutable_before = {
            path.relative_to(item).as_posix(): path.read_bytes()
            for path in item.rglob("*")
            if path.is_file()
        }

        retried = self._assert_success(
            self._capture(self._request("projection failure", key="projection-key"))
        )
        self.assertEqual(
            tuple(w.code for w in retried.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )
        self.assertFalse((item / "capture.yaml").exists())
        immutable_after = {
            path.relative_to(item).as_posix(): path.read_bytes()
            for path in item.rglob("*")
            if path.is_file()
        }
        self.assertEqual(immutable_after, immutable_before)
        for field in _STABLE_RECEIPT_FIELDS:
            self.assertEqual(first.to_dict()[field], retried.to_dict()[field])

    def test_ct_23_unprovable_rename_result_returns_unknown(self) -> None:
        def lose_source(source: Path, destination: Path) -> None:
            if source.name == "item":
                os.rename(source, source.parent / "lost-item")
                raise OSError("injected ambiguous rename")
            os.rename(source, destination)

        dependencies = _CaptureDependencies(
            durability=DurabilityBackend(_rename=lose_source)
        )
        self._assert_failure(
            self._capture(self._request("unknown"), dependencies=dependencies),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.UNKNOWN,
        )
        self.assertEqual(self._item_paths(), ())
        staging = tuple((self.capture_root / ".staging").iterdir())
        self.assertEqual(len(staging), 1)
        self.assertTrue((staging[0] / "transaction.yaml").is_file())
        self.assertTrue((staging[0] / "lost-item").is_dir())

    def test_rename_rejection_with_original_source_is_not_committed(self) -> None:
        def reject_item(source: Path, destination: Path) -> None:
            if source.name == "item":
                raise OSError("injected pre-rename rejection")
            os.rename(source, destination)

        dependencies = _CaptureDependencies(
            durability=DurabilityBackend(_rename=reject_item)
        )
        self._assert_failure(
            self._capture(self._request("not committed"), dependencies=dependencies),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(self._item_paths(), ())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_rename_exception_after_commit_is_proven_from_final_item(self) -> None:
        def commit_then_raise(source: Path, destination: Path) -> None:
            os.rename(source, destination)
            if source.name == "item":
                raise OSError("injected post-rename error")

        dependencies = _CaptureDependencies(
            durability=DurabilityBackend(_rename=commit_then_raise)
        )
        success = self._assert_success(
            self._capture(self._request("proved committed"), dependencies=dependencies)
        )
        self._assert_item_integrity(success, b"proved committed")

    def test_source_gone_with_invalid_target_is_integrity_unknown(self) -> None:
        def commit_corrupt_then_raise(source: Path, destination: Path) -> None:
            os.rename(source, destination)
            if source.name == "item":
                envelope = destination / "versions" / "000001" / "envelope.yaml"
                envelope.write_bytes(envelope.read_bytes() + b"corrupt")
                raise OSError("injected corrupt target")

        dependencies = _CaptureDependencies(
            durability=DurabilityBackend(_rename=commit_corrupt_then_raise)
        )
        self._assert_failure(
            self._capture(self._request("corrupt"), dependencies=dependencies),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.UNKNOWN,
        )

    def test_ct_24_failure_cleans_only_owned_staging(self) -> None:
        unknown = self.capture_root / ".staging" / "unknown"
        unknown.mkdir()
        sentinel = unknown / "sentinel.bin"
        sentinel.write_bytes(b"unchanged")

        def fail_event() -> None:
            raise OSError("injected event failure")

        dependencies = replace(
            _CaptureDependencies(),
            fault_point=_CaptureFaultPoint.BEFORE_EVENT_WRITE,
            fault_hook=fail_event,
        )
        self._capture(self._request("cleanup"), dependencies=dependencies)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), (unknown,))

    def test_idempotency_scan_fails_closed_for_corrupt_immutable_event(self) -> None:
        first = self._assert_success(
            self._capture(self._request("immutable", key="immutable-key"))
        )
        item = self._item_for(first)
        event_path = next((item / "events").iterdir())
        event_path.write_bytes(event_path.read_bytes() + b"corrupt")

        self._assert_failure(
            self._capture(self._request("immutable", key="immutable-key")),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.UNKNOWN,
        )
        self.assertEqual(len(self._item_paths()), 1)


if __name__ == "__main__":
    unittest.main()
