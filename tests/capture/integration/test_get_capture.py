from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import knowledgeflow_capture
from knowledgeflow_capture.codec import (
    CAPTURE_EVENT_SCHEMA_V1,
    dump_capture_event,
    dump_envelope,
    dump_restricted_yaml,
    load_capture_event,
    load_envelope,
)
from knowledgeflow_capture.errors import (
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.hashing import (
    DEFAULT_CHUNK_SIZE,
    envelope_sha256,
    hash_bytes,
    payload_set_sha256,
    seal_envelope,
)
from knowledgeflow_capture.models import (
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    PayloadSetEntry,
)
from knowledgeflow_capture.operations import (
    _GetCaptureDependencies,
    _get_capture_with_dependencies,
    get_capture,
)
import knowledgeflow_capture.operations as capture_operations
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store

from .._samples import CAPTURE_ID, PAYLOAD_BYTES


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_MIB = 1024 * 1024
_MAXIMUM = 64 * _MIB
_SECOND_EVENT_ID = "evt_01991a7e-7b23-72ae-9ef5-4f45249ad335"


class _GeneratedStream:
    def __init__(self, byte_size: int) -> None:
        self.remaining = byte_size
        self.maximum_read = 0

    def read(self, size: int = -1, /) -> bytes:
        if size <= 0:
            raise AssertionError("get acceptance source received an unbounded read")
        self.maximum_read = max(self.maximum_read, size)
        returned = min(size, self.remaining)
        self.remaining -= returned
        return b"x" * returned


class _DigestSink:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.byte_size = 0
        self.maximum_write = 0
        self.close_calls = 0
        self.flush_calls = 0

    def write(self, value: bytes) -> int:
        if type(value) is not bytes:
            raise AssertionError("body sink must receive bytes")
        self.maximum_write = max(self.maximum_write, len(value))
        self.byte_size += len(value)
        self.digest.update(value)
        return len(value)

    def close(self) -> None:
        self.close_calls += 1

    def flush(self) -> None:
        self.flush_calls += 1

    @property
    def sha256(self) -> str:
        return "sha256:" + self.digest.hexdigest()


class _ShortWriteSink(_DigestSink):
    def __init__(self, maximum_acceptance: int) -> None:
        super().__init__()
        self.maximum_acceptance = maximum_acceptance

    def write(self, value: bytes) -> int:
        accepted = min(self.maximum_acceptance, len(value))
        return super().write(value[:accepted])


class _FailingSink(_DigestSink):
    def __init__(self, failure: object, *, accept_first: int = 0) -> None:
        super().__init__()
        self.failure = failure
        self.accept_first = accept_first
        self.calls = 0

    def write(self, value: bytes) -> int:
        self.calls += 1
        if self.calls == 1 and self.accept_first:
            return super().write(value[: self.accept_first])
        if isinstance(self.failure, BaseException):
            raise self.failure
        if self.failure == "too-large":
            return len(value) + 1
        return self.failure  # type: ignore[return-value]


class _RecordingSpool:
    def __init__(self, parent: Path) -> None:
        self.parent = parent
        self._stream = tempfile.TemporaryFile(mode="w+b", dir=parent)
        self.maximum_write = 0

    def write(self, value: bytes) -> int:
        self.maximum_write = max(self.maximum_write, len(value))
        return self._stream.write(value)

    def read(self, size: int = -1, /) -> bytes:
        if size < 0:
            raise AssertionError("body spool received an unbounded read")
        return self._stream.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._stream.seek(offset, whence)

    def flush(self) -> None:
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


class GetCaptureIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C4B get_capture is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=4 * _MIB,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)
        self.item = self.capture_root / "items" / "2026" / "09" / CAPTURE_ID

    def _install_golden_item(
        self,
        *,
        include_v2: bool = False,
        projection: bool = True,
    ) -> Path:
        version_1 = self.item / "versions" / "000001"
        (version_1 / "payloads").mkdir(parents=True)
        (self.item / "events").mkdir()
        (version_1 / "payloads" / "primary.txt").write_bytes(PAYLOAD_BYTES)
        (version_1 / "envelope.yaml").write_bytes(
            (FIXTURES / "envelope-v1.yaml").read_bytes()
        )
        (self.item / "events" / "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332.yaml").write_bytes(
            (FIXTURES / "capture-event-v1.yaml").read_bytes()
        )
        if include_v2:
            version_2 = self.item / "versions" / "000002"
            (version_2 / "payloads").mkdir(parents=True)
            (version_2 / "payloads" / "primary.txt").write_bytes(
                (FIXTURES / "payload-v2.txt").read_bytes()
            )
            (version_2 / "envelope.yaml").write_bytes(
                (FIXTURES / "envelope-v2.yaml").read_bytes()
            )
            (self.item / "events" / "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333.yaml").write_bytes(
                (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes()
            )
        if projection:
            (self.item / "capture.yaml").write_bytes(
                (FIXTURES / "capture-state-v1.yaml").read_bytes()
            )
        return self.item

    def _reset_item(self, **options: object) -> Path:
        if self.item.exists() or self.item.is_symlink():
            if self.item.is_symlink():
                self.item.unlink()
            else:
                shutil.rmtree(self.item)
        return self._install_golden_item(**options)

    def _get(
        self,
        sink: object,
        *,
        capture_id: str = CAPTURE_ID,
        version: int | None = None,
        dependencies: _GetCaptureDependencies | None = None,
    ) -> GetCaptureResult | FailureResult:
        request = GetCaptureRequest(
            capture_id=capture_id,
            version=version,
            body_sink=sink,
        )
        if dependencies is None:
            return get_capture(
                request,
                config_path=self.config_path,
                path_policy=self.policy,
            )
        return _get_capture_with_dependencies(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
            dependencies=dependencies,
        )

    def _assert_failure(
        self,
        result: GetCaptureResult | FailureResult,
        code: PublicErrorCode,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        self.assertIsNone(failure.commit_state)
        self.assertNotIn("commit_state", failure.to_dict())
        self.assertNotIn("integrity", failure.to_dict())
        return failure

    def _assert_success(
        self,
        result: GetCaptureResult | FailureResult,
    ) -> GetCaptureResult:
        self.assertIsInstance(result, GetCaptureResult)
        success = result
        serialized = success.to_dict()
        self.assertEqual(serialized["integrity"], "verified")
        self.assertNotIn("commit_state", serialized)
        self.assertNotIn("text", serialized)
        return success

    def _replace_bytes(self, path: Path, old: bytes, new: bytes) -> None:
        source = path.read_bytes()
        self.assertIn(old, source)
        path.write_bytes(source.replace(old, new, 1))

    def _install_multi_payload_item(self) -> tuple[Path, bytes]:
        self._install_golden_item()
        version = self.item / "versions" / "000001"
        envelope = load_envelope((version / "envelope.yaml").read_bytes())
        event = load_capture_event(
            next((self.item / "events").iterdir()).read_bytes(),
            envelope=envelope,
        )
        attachment = b"attachment"
        attachment_digest = hash_bytes(attachment)
        candidate = deepcopy(envelope)
        candidate.pop("envelope_sha256")
        candidate["payloads"].append(
            {
                "payload_id": attachment_digest.sha256,
                "ordinal": 1,
                "role": "attachment",
                "kind": "binary",
                "path": "payloads/attachment.bin",
                "original_name": "attachment.bin",
                "media_type": "application/octet-stream",
                "encoding": None,
                "fidelity": "byte-exact",
                "byte_size": attachment_digest.byte_size,
                "sha256": attachment_digest.sha256,
            }
        )
        entries = tuple(
            PayloadSetEntry(
                ordinal=payload["ordinal"],
                role=payload["role"],
                kind=payload["kind"],
                media_type=payload["media_type"],
                byte_size=payload["byte_size"],
                sha256=payload["sha256"],
            )
            for payload in candidate["payloads"]
        )
        candidate["payload_set_sha256"] = payload_set_sha256(entries)
        sealed = seal_envelope(candidate)
        event["envelope_sha256"] = sealed.sha256
        (version / "envelope.yaml").write_bytes(sealed.yaml_bytes)
        event_path = self.item / "events" / f"{event['event_id']}.yaml"
        event_path.write_bytes(dump_capture_event(event, envelope=sealed.envelope))
        attachment_path = version / "payloads" / "attachment.bin"
        attachment_path.write_bytes(attachment)
        return attachment_path, attachment

    def test_get_01_02_08_latest_and_history_follow_event_proved_chain(self) -> None:
        self._install_golden_item(include_v2=True)
        latest_sink = io.BytesIO()
        latest = self._assert_success(self._get(latest_sink))
        self.assertEqual(latest.capture.version, 2)
        self.assertEqual(latest.capture.current_version, 2)
        self.assertEqual(latest_sink.getvalue(), (FIXTURES / "payload-v2.txt").read_bytes())

        history_sink = io.BytesIO()
        history = self._assert_success(self._get(history_sink, version=1))
        self.assertEqual(history.capture.version, 1)
        self.assertEqual(history.capture.current_version, 2)
        self.assertEqual(history.capture.captured_at, "2026-09-02T01:02:03.004Z")
        self.assertEqual(history_sink.getvalue(), PAYLOAD_BYTES)
        self.assertEqual(
            tuple(warning.code for warning in history.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )

    def test_get_03_04_16_not_found_and_success_shapes_never_claim_commit(self) -> None:
        missing_sink = io.BytesIO()
        missing = self._get(
            missing_sink,
            capture_id="cap_01991a7e-7b20-7a31-8d14-0b8ab6b35422",
        )
        self._assert_failure(missing, PublicErrorCode.CAPTURE_NOT_FOUND)
        self.assertEqual(missing_sink.getvalue(), b"")

        self._install_golden_item()
        version_sink = io.BytesIO()
        absent = self._get(version_sink, version=2)
        self._assert_failure(absent, PublicErrorCode.VERSION_NOT_FOUND)
        self.assertEqual(version_sink.getvalue(), b"")

        body_sink = io.BytesIO()
        result = self._assert_success(self._get(body_sink, version=1))
        self.assertEqual(result.body_length_bytes, len(body_sink.getvalue()))
        self.assertEqual(result.capture.byte_size, len(body_sink.getvalue()))

    def test_get_05_checks_every_target_payload_before_releasing_primary(self) -> None:
        attachment_path, original = self._install_multi_payload_item()
        valid_sink = io.BytesIO()
        self._assert_success(self._get(valid_sink))
        self.assertEqual(valid_sink.getvalue(), PAYLOAD_BYTES)

        attachment_path.write_bytes(original[:-1] + b"X")
        failed_sink = io.BytesIO()
        failure = self._get(failed_sink)
        self._assert_failure(failure, PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(failed_sink.getvalue(), b"")

    def test_get_05_detects_primary_size_hash_and_payload_set_damage(self) -> None:
        self._install_golden_item()
        primary = self.item / "versions" / "000001" / "payloads" / "primary.txt"
        primary.write_bytes(b"X" + PAYLOAD_BYTES[1:])
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

        self._reset_item()
        primary.write_bytes(PAYLOAD_BYTES + b"X")
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

        self._reset_item()
        envelope_path = self.item / "versions" / "000001" / "envelope.yaml"
        envelope = load_envelope(envelope_path.read_bytes())
        event_path = next((self.item / "events").iterdir())
        event = load_capture_event(event_path.read_bytes(), envelope=envelope)
        envelope["payload_set_sha256"] = "sha256:" + ("f" * 64)
        envelope["envelope_sha256"] = envelope_sha256(envelope)
        event["envelope_sha256"] = envelope["envelope_sha256"]
        envelope_path.write_bytes(dump_envelope(envelope))
        event_path.write_bytes(
            dump_capture_event(event, envelope=envelope)
        )
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

    def test_get_06_envelope_tamper_is_rejected_before_sink_output(self) -> None:
        self._install_golden_item()
        envelope_path = self.item / "versions" / "000001" / "envelope.yaml"
        self._replace_bytes(envelope_path, b"msg-42", b"msg-43")
        sink = io.BytesIO()
        failure = self._get(sink)
        self._assert_failure(failure, PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

    def test_get_07_projection_missing_or_known_invalid_is_read_only_warning(self) -> None:
        self._install_golden_item(projection=False)
        sink = io.BytesIO()
        result = self._assert_success(self._get(sink))
        self.assertEqual(sink.getvalue(), PAYLOAD_BYTES)
        self.assertEqual(
            tuple(warning.code for warning in result.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )
        self.assertFalse((self.item / "capture.yaml").exists())

        projection = self.item / "capture.yaml"
        projection.write_bytes(b"schema: \"knowledgeflow.capture-state\"\n")
        before = projection.read_bytes()
        self._assert_success(self._get(io.BytesIO()))
        self.assertEqual(projection.read_bytes(), before)

    def test_get_09_one_uncommitted_tail_is_hidden_and_left_untouched(self) -> None:
        self._install_golden_item()
        tail = self.item / "versions" / "000002"
        tail.mkdir()
        marker = tail / "partial.bin"
        marker.write_bytes(b"partial")

        sink = io.BytesIO()
        latest = self._assert_success(self._get(sink))
        self.assertEqual(latest.capture.version, 1)
        self.assertEqual(sink.getvalue(), PAYLOAD_BYTES)
        warning = latest.warnings[0]
        self.assertEqual(warning.code, WarningCode.INCOMPLETE_VERSION_IGNORED)
        self.assertEqual(dict(warning.details), {"capture_id": CAPTURE_ID, "version": 2})
        self.assertEqual(marker.read_bytes(), b"partial")

        exact_sink = io.BytesIO()
        exact = self._get(exact_sink, version=2)
        self._assert_failure(exact, PublicErrorCode.VERSION_NOT_FOUND)
        self.assertEqual(exact_sink.getvalue(), b"")
        self.assertEqual(marker.read_bytes(), b"partial")

    def test_get_10_committed_event_conflict_or_payload_loss_never_falls_back(self) -> None:
        self._install_golden_item(include_v2=True)
        event_path = self.item / "events" / "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333.yaml"
        self._replace_bytes(
            event_path,
            b"sha256:d060313160f00566464a47a23f37d530a8cd77a100a6efcda591a7224c17515a",
            b"sha256:" + (b"f" * 64),
        )
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

        self._reset_item(include_v2=True)
        (self.item / "versions" / "000002" / "payloads" / "primary.txt").unlink()
        historical_sink = io.BytesIO()
        self._assert_failure(
            self._get(historical_sink, version=1),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )
        self.assertEqual(historical_sink.getvalue(), b"")

    def test_get_11_gap_duplicate_orphan_event_and_multiple_tails_fail_closed(self) -> None:
        self._install_golden_item(include_v2=True)
        (self.item / "versions" / "000002").rename(
            self.item / "versions" / "000003"
        )
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

        self._reset_item(include_v2=True)
        envelope_2 = load_envelope(
            (self.item / "versions" / "000002" / "envelope.yaml").read_bytes()
        )
        duplicate = load_capture_event(
            (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes(),
            envelope=envelope_2,
            previous_envelope=load_envelope(
                (FIXTURES / "envelope-v1.yaml").read_bytes()
            ),
        )
        duplicate["event_id"] = _SECOND_EVENT_ID
        (self.item / "events" / f"{_SECOND_EVENT_ID}.yaml").write_bytes(
            dump_restricted_yaml(duplicate, CAPTURE_EVENT_SCHEMA_V1)
        )
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

        self._reset_item()
        (self.item / "events" / "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333.yaml").write_bytes(
            (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes()
        )
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

        self._reset_item()
        (self.item / "versions" / "000002").mkdir()
        (self.item / "versions" / "000003").mkdir()
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

    def test_get_12_unsupported_identity_is_distinct_from_known_invalid_data(self) -> None:
        self._install_golden_item()
        envelope_path = self.item / "versions" / "000001" / "envelope.yaml"
        self._replace_bytes(envelope_path, b"schema_version: 1", b"schema_version: 2")
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.UNSUPPORTED_STORE_VERSION)
        self.assertEqual(sink.getvalue(), b"")

        self._reset_item()
        event_path = next((self.item / "events").iterdir())
        self._replace_bytes(event_path, b"schema_version: 1", b"schema_version: 2")
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )

        self._reset_item()
        projection_path = self.item / "capture.yaml"
        self._replace_bytes(
            projection_path,
            b"schema_version: 1",
            b"schema_version: 2",
        )
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )

        self._reset_item()
        source = envelope_path.read_bytes().replace(
            b'captured_at: "2026-09-02T01:02:03.004Z"\n',
            b"",
        )
        envelope_path.write_bytes(source)
        self._assert_failure(
            self._get(io.BytesIO()),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

    def test_get_13_real_64_mib_body_uses_bounded_external_disk_spool(self) -> None:
        source = _GeneratedStream(_MAXIMUM)
        written = knowledgeflow_capture.capture_text(
            CaptureTextRequest(
                text=source,
                channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(written, CommittedWriteResult)
        receipt = written.to_dict()

        spools: list[_RecordingSpool] = []

        def spool_factory(root: Path) -> _RecordingSpool:
            self.assertEqual(root, self.capture_root)
            spool = _RecordingSpool(root.parent)
            spools.append(spool)
            return spool

        sink = _DigestSink()
        result = self._assert_success(
            self._get(
                sink,
                capture_id=receipt["capture_id"],
                dependencies=_GetCaptureDependencies(spool_factory=spool_factory),
            )
        )
        self.assertEqual(result.body_length_bytes, _MAXIMUM)
        self.assertEqual(sink.byte_size, _MAXIMUM)
        self.assertEqual(sink.sha256, receipt["primary_payload_sha256"])
        self.assertLessEqual(source.maximum_read, DEFAULT_CHUNK_SIZE)
        self.assertLessEqual(sink.maximum_write, DEFAULT_CHUNK_SIZE)
        self.assertEqual(len(spools), 1)
        self.assertEqual(spools[0].parent, self.capture_root.parent)
        self.assertLessEqual(spools[0].maximum_write, DEFAULT_CHUNK_SIZE)
        self.assertEqual(sink.close_calls, 0)
        self.assertEqual(sink.flush_calls, 0)

    def test_get_14_short_writes_continue_and_invalid_sink_results_are_retryable(self) -> None:
        self._install_golden_item()
        short = _ShortWriteSink(3)
        success = self._assert_success(self._get(short))
        self.assertEqual(success.body_length_bytes, len(PAYLOAD_BYTES))
        self.assertEqual(short.byte_size, len(PAYLOAD_BYTES))
        self.assertEqual(short.sha256, hash_bytes(PAYLOAD_BYTES).sha256)
        self.assertEqual(short.close_calls, 0)
        self.assertEqual(short.flush_calls, 0)

        invalid_values: tuple[object, ...] = (
            0,
            None,
            True,
            "too-large",
            OSError("sink failed"),
        )
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                sink = _FailingSink(invalid)
                failure = self._assert_failure(
                    self._get(sink),
                    PublicErrorCode.OUTPUT_WRITE_FAILED,
                )
                self.assertTrue(failure.error.retryable)
                self.assertEqual(failure.error.message, "capture body output failed")
                self.assertEqual(sink.close_calls, 0)
                self.assertEqual(sink.flush_calls, 0)

        partial = _FailingSink(OSError("second write failed"), accept_first=5)
        failure = self._assert_failure(
            self._get(partial),
            PublicErrorCode.OUTPUT_WRITE_FAILED,
        )
        self.assertTrue(failure.error.retryable)
        self.assertEqual(partial.byte_size, 5)

    def test_get_15_wrong_shard_duplicate_and_escape_fail_without_output(self) -> None:
        self._install_golden_item()
        wrong_parent = self.capture_root / "items" / "2025" / "01"
        wrong_parent.mkdir(parents=True)
        self.item.rename(wrong_parent / CAPTURE_ID)
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

        self._install_golden_item()
        shutil.copytree(self.item, wrong_parent / CAPTURE_ID, dirs_exist_ok=True)
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")
        shutil.rmtree(wrong_parent / CAPTURE_ID)

        envelope_path = self.item / "versions" / "000001" / "envelope.yaml"
        event_path = next((self.item / "events").iterdir())
        envelope = load_envelope(envelope_path.read_bytes())
        event = load_capture_event(event_path.read_bytes(), envelope=envelope)
        candidate = deepcopy(envelope)
        candidate.pop("envelope_sha256")
        candidate["payloads"][0]["path"] = "../../../outside.txt"
        sealed = seal_envelope(candidate)
        event["envelope_sha256"] = sealed.sha256
        envelope_path.write_bytes(sealed.yaml_bytes)
        event_path.write_bytes(dump_capture_event(event, envelope=sealed.envelope))
        (self.owned_root / "outside.txt").write_bytes(PAYLOAD_BYTES)
        sink = io.BytesIO()
        self._assert_failure(self._get(sink), PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(sink.getvalue(), b"")

    def test_get_15_reparse_item_is_never_followed(self) -> None:
        self._install_golden_item()
        external = self.owned_root / "external-item"
        shutil.copytree(self.item, external)
        shutil.rmtree(self.item)
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(self.item), str(external)],
            check=False,
            capture_output=True,
        )
        if created.returncode != 0:
            self.skipTest("Windows junction creation is unavailable")
        try:
            sink = io.BytesIO()
            self._assert_failure(
                self._get(sink),
                PublicErrorCode.INTEGRITY_CHECK_FAILED,
            )
            self.assertEqual(sink.getvalue(), b"")
        finally:
            os.rmdir(self.item)

    def test_get_16_store_io_failure_precedes_output_and_public_has_no_test_hook(self) -> None:
        self._install_golden_item()
        sink = io.BytesIO()
        original_lstat = capture_operations._lstat_if_present

        def fail_envelope_stat(path: Path):
            if path.name == "envelope.yaml":
                raise OSError("simulated Store read failure")
            return original_lstat(path)

        with patch.object(
            capture_operations,
            "_lstat_if_present",
            side_effect=fail_envelope_stat,
        ):
            failure = self._get(sink)
        self._assert_failure(failure, PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)
        self.assertEqual(sink.getvalue(), b"")

        parameters = inspect.signature(get_capture).parameters
        self.assertEqual(tuple(parameters), ("request", "config_path", "path_policy"))
        self.assertNotIn("dependencies", parameters)

        invalid = get_capture(
            object(),  # type: ignore[arg-type]
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self._assert_failure(invalid, PublicErrorCode.INVALID_INPUT)


if __name__ == "__main__":
    unittest.main()
