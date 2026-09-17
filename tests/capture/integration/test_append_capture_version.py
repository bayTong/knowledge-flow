from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

import knowledgeflow_capture.operations as operations_module
from knowledgeflow_capture.codec import (
    load_capture_event,
    load_capture_state,
    load_envelope,
)
from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CommitState,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
)
from knowledgeflow_capture.operations import (
    _AppendTargetEvidence,
    _CaptureDependencies,
    _CaptureFaultPoint,
    _StoreIoFailure,
    _append_capture_version_with_dependencies,
    append_capture_version,
    capture_text,
    get_capture,
    list_captures,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_INLINE_THRESHOLD = 16
_MAXIMUM = 256
_APPEND_EVENT_ID = "evt_01991a7e-7b24-72ae-9ef5-4f45249ad335"
_STAGING_UUID = UUID("01991a7e-7b25-72ae-9ef5-4f45249ad336")
_MISSING_CAPTURE_ID = "cap_01991a7e-7b29-72ae-9ef5-4f45249ad339"
_BASE_TIME = datetime(2026, 9, 16, 1, 2, 3, tzinfo=timezone.utc)


class AppendCaptureVersionIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C5B append transaction is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)
        created = capture_text(
            CaptureTextRequest(
                text="version one",
                channel=self._channel(),
                idempotency_key="create-base",
                user_intent=UserIntent(
                    target_kb_id="kb_original",
                    processing_mode="deep-curation",
                    requested_new_kb_name="Original",
                ),
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(created, FailureResult)
        self.capture_id = str(created.receipt["capture_id"])
        matches = tuple(self.capture_root.glob(f"items/*/*/{self.capture_id}"))
        self.assertEqual(len(matches), 1)
        self.item_path = matches[0]

    @staticmethod
    def _channel(*, external_ref: str | None = None) -> ChannelMetadata:
        return ChannelMetadata(
            type="app",
            instance_id="local-desktop",
            external_ref=external_ref,
        )

    def _request(
        self,
        text: str | object,
        *,
        key: str,
        expected: int = 1,
        capture_id: str | None = None,
        channel: ChannelMetadata | None = None,
        intent: UserIntent | None = None,
    ) -> AppendCaptureVersionRequest:
        return AppendCaptureVersionRequest(
            capture_id=self.capture_id if capture_id is None else capture_id,
            expected_current_version=expected,
            text=text,
            channel=self._channel() if channel is None else channel,
            idempotency_key=key,
            user_intent=intent,
        )

    def _append(
        self,
        request: AppendCaptureVersionRequest,
        *,
        dependencies: _CaptureDependencies | None = None,
    ) -> AppendCaptureVersionResult | FailureResult:
        if dependencies is None:
            return append_capture_version(
                request,
                config_path=self.config_path,
                path_policy=self.policy,
            )
        return _append_capture_version_with_dependencies(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
            dependencies=dependencies,
        )

    def _assert_success(
        self,
        result: AppendCaptureVersionResult | FailureResult,
    ) -> AppendCaptureVersionResult:
        self.assertIsInstance(result, AppendCaptureVersionResult)
        success = result
        self.assertEqual(success.to_dict()["commit_state"], "committed")
        return success

    def _assert_failure(
        self,
        result: AppendCaptureVersionResult | FailureResult,
        code: PublicErrorCode,
        state: CommitState,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        self.assertEqual(failure.commit_state, state)
        return failure

    def _fixed_dependencies(
        self,
        *,
        durability: DurabilityBackend | None = None,
        **changes: object,
    ) -> _CaptureDependencies:
        counter = 0

        def now() -> datetime:
            nonlocal counter
            value = _BASE_TIME + timedelta(milliseconds=counter)
            counter += 1
            return value

        base = _CaptureDependencies(
            durability=(durability if durability is not None else DurabilityBackend()),
            utc_now=now,
            event_id_factory=lambda: _APPEND_EVENT_ID,
            staging_uuid_factory=lambda: _STAGING_UUID,
        )
        return replace(base, **changes)

    def _fail_event_rename_dependencies(self) -> _CaptureDependencies:
        def rename(source: Path, destination: Path) -> None:
            if source.parent.name == "events":
                raise OSError("deterministic Event rename failure")
            os.rename(source, destination)

        backend = DurabilityBackend(_rename=rename)
        return self._fixed_dependencies(durability=backend)

    def _create_matching_tail(
        self,
        request: AppendCaptureVersionRequest,
    ) -> FailureResult:
        failure = self._assert_failure(
            self._append(
                request,
                dependencies=self._fail_event_rename_dependencies(),
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertTrue((self.item_path / "versions" / "000002").is_dir())
        self.assertEqual(len(tuple((self.item_path / "events").glob("*.yaml"))), 1)
        return failure

    def test_app_04_11_12_normal_append_preserves_history_and_updates_reads(self) -> None:
        old_version = self.item_path / "versions" / "000001"
        old_event = next((self.item_path / "events").glob("*.yaml"))
        old_bytes = {
            "payload": (old_version / "payloads" / "primary.txt").read_bytes(),
            "envelope": (old_version / "envelope.yaml").read_bytes(),
            "event": old_event.read_bytes(),
        }
        request = self._request("version two 中文🙂", key="append-normal")

        success = self._assert_success(self._append(request))

        receipt = success.to_dict()
        self.assertEqual(receipt["capture_id"], self.capture_id)
        self.assertEqual(receipt["previous_version"], 1)
        self.assertEqual(receipt["version"], 2)
        self.assertEqual(receipt["warnings"], [])
        version_2 = self.item_path / "versions" / "000002"
        envelope_1 = load_envelope(old_bytes["envelope"])
        envelope_2 = load_envelope((version_2 / "envelope.yaml").read_bytes())
        event_2 = load_capture_event(
            (self.item_path / "events" / f"{receipt['event_id']}.yaml").read_bytes(),
            envelope=envelope_2,
            previous_envelope=envelope_1,
        )
        state = load_capture_state(
            (self.item_path / "capture.yaml").read_bytes(),
            envelope=envelope_2,
            current_event=event_2,
            previous_envelope=envelope_1,
        )
        self.assertEqual(state["current_version"], 2)
        self.assertEqual(state["updated_at"], event_2["occurred_at"])
        self.assertNotEqual(state["updated_at"], state["durability"]["verified_at"])
        self.assertEqual(
            envelope_2["user_intent"],
            {
                "target_kb_id": None,
                "processing_mode": None,
                "requested_new_kb_name": None,
                "evidence": {
                    "event_id": receipt["event_id"],
                    "payload_id": receipt["primary_payload_sha256"],
                },
            },
        )
        self.assertEqual(
            (old_version / "payloads" / "primary.txt").read_bytes(),
            old_bytes["payload"],
        )
        self.assertEqual((old_version / "envelope.yaml").read_bytes(), old_bytes["envelope"])
        self.assertEqual(old_event.read_bytes(), old_bytes["event"])

        for version, expected in ((1, b"version one"), (None, "version two 中文🙂".encode())):
            sink = io.BytesIO()
            read = get_capture(
                GetCaptureRequest(
                    capture_id=self.capture_id,
                    version=version,
                    body_sink=sink,
                ),
                config_path=self.config_path,
                path_policy=self.policy,
            )
            self.assertIsInstance(read, GetCaptureResult)
            self.assertEqual(sink.getvalue(), expected)
        listed = list_captures(
            ListCapturesRequest(),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(listed, ListCapturesResult)
        self.assertEqual(listed.items[0].current_version, 2)

        same_body = self._assert_success(
            self._append(
                self._request("version two 中文🙂", key="append-same", expected=2)
            )
        )
        self.assertEqual(same_body.receipt["version"], 3)

    def test_app_05_10_and_staging_priority_return_precise_precommit_failures(self) -> None:
        stale = self._assert_failure(
            self._append(self._request("stale", key="append-stale", expected=2)),
            PublicErrorCode.VERSION_CONFLICT,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(
            dict(stale.error.details),
            {"current_version": 1, "expected_current_version": 2},
        )
        self._assert_failure(
            self._append(
                self._request(
                    "missing",
                    key="append-missing",
                    capture_id=_MISSING_CAPTURE_ID,
                )
            ),
            PublicErrorCode.CAPTURE_NOT_FOUND,
            CommitState.NOT_COMMITTED,
        )
        self._assert_failure(
            self._append(
                self._request(
                    io.BytesIO(b"x" * (_MAXIMUM + 1)),
                    key="append-oversize",
                    capture_id=_MISSING_CAPTURE_ID,
                )
            ),
            PublicErrorCode.TEXT_TOO_LARGE,
            CommitState.NOT_COMMITTED,
        )
        self._assert_success(
            self._append(self._request("version two", key="append-winner"))
        )
        self._assert_failure(
            self._append(self._request("loser", key="append-loser")),
            PublicErrorCode.VERSION_CONFLICT,
            CommitState.NOT_COMMITTED,
        )
        self.assertFalse((self.item_path / "versions" / "000003").exists())

    def test_app_08_committed_idempotency_precedes_cas_and_warnings_are_dynamic(self) -> None:
        first_request = self._request("version two", key="append-first")
        first = self._assert_success(self._append(first_request))
        self._assert_success(
            self._append(self._request("version three", key="append-second", expected=2))
        )

        retried = self._assert_success(self._append(first_request))
        for field in (
            "capture_id",
            "event_id",
            "previous_version",
            "version",
            "primary_payload_sha256",
            "payload_set_sha256",
            "envelope_sha256",
        ):
            self.assertEqual(retried.receipt[field], first.receipt[field])
        self.assertEqual(retried.receipt["version"], 2)

        (self.item_path / "capture.yaml").write_bytes(b"known bad projection")
        warned = self._assert_success(self._append(first_request))
        self.assertEqual(warned.receipt["version"], 2)
        self.assertEqual(len(warned.warnings), 1)
        self.assertEqual(warned.warnings[0].code, WarningCode.PROJECTION_NEEDS_REBUILD)
        self.assertEqual(warned.warnings[0].details["capture_id"], self.capture_id)

    def test_app_09_idempotency_conflict_precedes_missing_target_and_cas(self) -> None:
        self._assert_success(
            self._append(self._request("version two", key="append-conflict"))
        )
        for request in (
            self._request("changed body", key="append-conflict"),
            self._request(
                "changed target",
                key="append-conflict",
                capture_id=_MISSING_CAPTURE_ID,
            ),
            self._request(
                "version two",
                key="append-conflict",
                channel=self._channel(external_ref="changed-channel"),
            ),
        ):
            with self.subTest(request=request):
                self._assert_failure(
                    self._append(request),
                    PublicErrorCode.IDEMPOTENCY_CONFLICT,
                    CommitState.NOT_COMMITTED,
                )

    def test_app_13_current_payload_tamper_blocks_append_before_cas(self) -> None:
        payload = self.item_path / "versions" / "000001" / "payloads" / "primary.txt"
        payload.write_bytes(b"VERSION ONE")
        self._assert_failure(
            self._append(self._request("version two", key="append-tamper")),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertFalse((self.item_path / "versions" / "000002").exists())

    def test_app_14_unknown_committed_schema_fails_closed(self) -> None:
        envelope_path = self.item_path / "versions" / "000001" / "envelope.yaml"
        envelope_path.write_bytes(
            envelope_path.read_bytes().replace(
                b"schema_version: 1",
                b"schema_version: 9",
                1,
            )
        )
        self._assert_failure(
            self._append(self._request("version two", key="append-schema")),
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
            CommitState.NOT_COMMITTED,
        )

    def test_app_14_bad_committed_machine_bytes_fail_integrity(self) -> None:
        event_path = next((self.item_path / "events").glob("*.yaml"))
        event_path.write_bytes(event_path.read_bytes() + b"unknown_field: true\n")
        self._assert_failure(
            self._append(self._request("version two", key="append-bad-event")),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.NOT_COMMITTED,
        )

    def test_app_15_matching_tail_is_adopted_without_allocating_n_plus_two(self) -> None:
        request = self._request("version two", key="append-tail")
        self._create_matching_tail(request)
        tail_envelope = load_envelope(
            (self.item_path / "versions" / "000002" / "envelope.yaml").read_bytes()
        )

        success = self._assert_success(self._append(request))

        self.assertEqual(success.receipt["version"], 2)
        self.assertEqual(success.receipt["event_id"], tail_envelope["event_id"])
        self.assertTrue(
            (self.item_path / "events" / f"{tail_envelope['event_id']}.yaml").is_file()
        )
        self.assertFalse((self.item_path / "versions" / "000003").exists())

    def test_app_09_16_foreign_or_conflicting_tail_is_preserved(self) -> None:
        original = self._request("version two", key="append-tail-owner")
        self._create_matching_tail(original)
        tail_path = self.item_path / "versions" / "000002"
        before = (tail_path / "envelope.yaml").read_bytes()

        foreign = self._assert_failure(
            self._append(self._request("version two", key="append-other-key")),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(foreign.error.details["stage"], "version-target-conflict")
        self.assertEqual((tail_path / "envelope.yaml").read_bytes(), before)
        self._assert_failure(
            self._append(self._request("different", key="append-tail-owner")),
            PublicErrorCode.IDEMPOTENCY_CONFLICT,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual((tail_path / "envelope.yaml").read_bytes(), before)

    def test_app_14_tail_identity_io_uncertainty_fails_before_final_write(self) -> None:
        request = self._request("version two", key="append-tail-io")
        self._create_matching_tail(request)
        with patch(
            "knowledgeflow_capture.operations._read_append_tail_envelope_source",
            side_effect=_StoreIoFailure(stage="tail-identity"),
        ):
            failure = self._assert_failure(
                self._append(request),
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                CommitState.NOT_COMMITTED,
            )
        self.assertEqual(failure.error.details["stage"], "tail-identity")
        self.assertTrue((self.item_path / "versions" / "000002").is_dir())

    def test_app_17_multiple_uncommitted_tails_are_integrity_failure(self) -> None:
        request = self._request("version two", key="append-multiple-tail")
        self._create_matching_tail(request)
        (self.item_path / "versions" / "000003").mkdir()
        self._assert_failure(
            self._append(request),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.NOT_COMMITTED,
        )

    def test_app_18_version_and_event_failures_are_not_committed_and_keep_unknown_staging(self) -> None:
        unknown = self.capture_root / ".staging" / "foreign-evidence"
        unknown.mkdir()
        (unknown / "keep.bin").write_bytes(b"foreign")

        def fail_version_rename(source: Path, destination: Path) -> None:
            if source.name == "version":
                raise OSError("deterministic version rename failure")
            os.rename(source, destination)

        version_failure = self._assert_failure(
            self._append(
                self._request("version two", key="append-version-fail"),
                dependencies=self._fixed_dependencies(
                    durability=DurabilityBackend(_rename=fail_version_rename)
                ),
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(version_failure.error.details["stage"], "version-commit")
        self.assertFalse((self.item_path / "versions" / "000002").exists())
        self.assertEqual((unknown / "keep.bin").read_bytes(), b"foreign")

        failure = self._assert_failure(
            self._append(
                self._request("version two", key="append-rename-fail"),
                dependencies=self._fail_event_rename_dependencies(),
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(failure.error.details["stage"], "event-commit")
        self.assertEqual((unknown / "keep.bin").read_bytes(), b"foreign")
        self.assertTrue((self.item_path / "versions" / "000002").is_dir())

    def test_app_19_event_preflight_conflict_is_not_overwritten_or_adopted(self) -> None:
        event_path = self.item_path / "events" / f"{_APPEND_EVENT_ID}.yaml"

        def create_conflict() -> None:
            event_path.write_bytes(b"foreign event target")

        dependencies = self._fixed_dependencies(
            fault_point=_CaptureFaultPoint.BEFORE_APPEND_EVENT_PREFLIGHT,
            fault_hook=create_conflict,
        )
        failure = self._assert_failure(
            self._append(
                self._request("version two", key="append-event-conflict"),
                dependencies=dependencies,
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(failure.error.details["stage"], "event-target-conflict")
        self.assertEqual(event_path.read_bytes(), b"foreign event target")

    def test_app_20_event_rename_raise_after_move_remains_committed(self) -> None:
        def rename(source: Path, destination: Path) -> None:
            os.rename(source, destination)
            if destination.parent.name == "events":
                raise OSError("rename reported failure after durable move")

        dependencies = self._fixed_dependencies(
            durability=DurabilityBackend(_rename=rename)
        )
        success = self._assert_success(
            self._append(
                self._request("version two", key="append-moved"),
                dependencies=dependencies,
            )
        )
        self.assertEqual(success.receipt["event_id"], _APPEND_EVENT_ID)
        self.assertEqual(success.receipt["version"], 2)

    def test_app_20_unprovable_event_site_returns_unknown(self) -> None:
        original_probe = operations_module._probe_append_target
        probe_count = 0

        def probe(path: Path):
            nonlocal probe_count
            probe_count += 1
            if probe_count == 3:
                return _AppendTargetEvidence.UNPROVABLE
            return original_probe(path)

        with patch(
            "knowledgeflow_capture.operations._probe_append_target",
            side_effect=probe,
        ):
            failure = self._assert_failure(
                self._append(
                    self._request("version two", key="append-unknown"),
                    dependencies=self._fail_event_rename_dependencies(),
                ),
                PublicErrorCode.ATOMIC_COMMIT_FAILED,
                CommitState.UNKNOWN,
            )
        self.assertEqual(failure.error.details["stage"], "event-commit")

    def test_app_21_corrupt_event_after_rename_is_integrity_unknown(self) -> None:
        def rename(source: Path, destination: Path) -> None:
            os.rename(source, destination)
            if destination.parent.name == "events":
                destination.write_bytes(b"corrupt committed event")
                raise OSError("corrupt after move")

        failure = self._assert_failure(
            self._append(
                self._request("version two", key="append-corrupt-event"),
                dependencies=self._fixed_dependencies(
                    durability=DurabilityBackend(_rename=rename)
                ),
            ),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            CommitState.UNKNOWN,
        )
        self.assertIsNotNone(failure.error.cause_code)

    def test_app_22_projection_failure_cannot_invert_committed_append(self) -> None:
        def fail_replace(_source: Path, _destination: Path) -> None:
            raise OSError("projection replacement failed")

        success = self._assert_success(
            self._append(
                self._request("version two", key="append-projection"),
                dependencies=self._fixed_dependencies(replace_file=fail_replace),
            )
        )
        self.assertEqual(success.receipt["version"], 2)
        self.assertEqual(len(success.warnings), 1)
        self.assertEqual(success.warnings[0].code, WarningCode.PROJECTION_NEEDS_REBUILD)
        sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(capture_id=self.capture_id, body_sink=sink),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(read, GetCaptureResult)
        self.assertEqual(sink.getvalue(), b"version two")

    def test_public_boundary_rejects_wrong_request_without_touching_store(self) -> None:
        before = tuple(self.capture_root.rglob("*"))
        result = append_capture_version(  # type: ignore[arg-type]
            object(),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self._assert_failure(
            result,
            PublicErrorCode.INVALID_INPUT,
            CommitState.NOT_COMMITTED,
        )
        self.assertEqual(tuple(self.capture_root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
