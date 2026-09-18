"""C6B reconstruction of projections from immutable Capture facts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import UUID

from knowledgeflow_capture.codec import parse_restricted_yaml
from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CauseCode,
    CommittedWriteResult,
    FailureResult,
    ListCapturesResult,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    ListCapturesRequest,
)
from knowledgeflow_capture.operations import (
    append_capture_version,
    capture_text,
    list_captures,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.recovery import (
    RebuildDerivedStateResult,
    _RebuildDependencies,
    _RebuildFaultPoint,
    _rebuild_capture_store_derived_state_with_dependencies,
    rebuild_capture_store_derived_state,
)
from knowledgeflow_capture.store import init_capture_store


_SUPPORT = Path(__file__).resolve().parents[1] / "_support.py"
_REBUILD_TIME = datetime(2026, 9, 17, 8, 9, 10, tzinfo=timezone.utc)
_REBUILD_UUID = UUID("01991f8f-09a0-7000-8000-000000000001")


class DerivedStateRebuildIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C6B derived-state rebuild is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        self.policy = PathPolicy.test_owned(self.owned_root)
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=32,
            max_text_version_bytes=4096,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)
        self.base_request = self._capture_request(
            "base version",
            key="c6b-base-create",
        )
        self.base_result = self._capture(self.base_request)
        self.base_id = str(self.base_result.receipt["capture_id"])
        self.base_item = self._item(self.base_id)

    @staticmethod
    def _channel() -> ChannelMetadata:
        return ChannelMetadata(type="app", instance_id="c6b-rebuild")

    def _capture_request(self, text: str, *, key: str) -> CaptureTextRequest:
        return CaptureTextRequest(
            text=text,
            channel=self._channel(),
            idempotency_key=key,
        )

    def _capture(self, request: CaptureTextRequest) -> CommittedWriteResult:
        result = capture_text(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, CommittedWriteResult)
        return result

    def _append(
        self,
        capture_id: str,
        text: str,
        *,
        key: str,
    ) -> AppendCaptureVersionResult:
        result = append_capture_version(
            AppendCaptureVersionRequest(
                capture_id=capture_id,
                expected_current_version=1,
                text=text,
                channel=self._channel(),
                idempotency_key=key,
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, AppendCaptureVersionResult)
        return result

    def _item(self, capture_id: str) -> Path:
        matches = tuple(self.capture_root.glob(f"items/*/*/{capture_id}"))
        self.assertEqual(len(matches), 1)
        return matches[0]

    def _fixed_rebuild(self) -> RebuildDerivedStateResult | FailureResult:
        return _rebuild_capture_store_derived_state_with_dependencies(
            config_path=self.config_path,
            path_policy=self.policy,
            dependencies=_RebuildDependencies(
                utc_now=lambda: _REBUILD_TIME,
                uuid_factory=lambda: _REBUILD_UUID,
            ),
        )

    @staticmethod
    def _immutable_bytes(item_path: Path) -> dict[str, bytes]:
        immutable: dict[str, bytes] = {}
        for root_name in ("versions", "events"):
            root = item_path / root_name
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(item_path).as_posix()
                    immutable[relative] = path.read_bytes()
        return immutable

    def _list(self) -> ListCapturesResult:
        result = list_captures(
            ListCapturesRequest(limit=100),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, ListCapturesResult)
        return result

    def _support_run(
        self,
        result_path: Path,
        *,
        fault_point: _RebuildFaultPoint | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(_SUPPORT),
            "rebuild-derived-state-c6",
            str(self.owned_root),
            str(self.config_path),
            str(result_path),
        ]
        if fault_point is not None:
            command.extend(("--fault-point", fault_point.value))
        return subprocess.run(
            command,
            cwd=self.owned_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_rec_01_rebuilds_missing_corrupt_and_stale_projections_repeatably(
        self,
    ) -> None:
        original_v1_projection = (self.base_item / "capture.yaml").read_bytes()
        self._append(self.base_id, "base version two", key="c6b-base-append")
        (self.base_item / "capture.yaml").write_bytes(original_v1_projection)

        missing = self._capture(
            self._capture_request("missing projection", key="c6b-missing")
        )
        missing_item = self._item(str(missing.receipt["capture_id"]))
        (missing_item / "capture.yaml").unlink()

        corrupt = self._capture(
            self._capture_request("corrupt projection", key="c6b-corrupt")
        )
        corrupt_item = self._item(str(corrupt.receipt["capture_id"]))
        (corrupt_item / "capture.yaml").write_bytes(b"not: [valid")

        immutable_before = {
            item.name: self._immutable_bytes(item)
            for item in (self.base_item, missing_item, corrupt_item)
        }
        result = self._fixed_rebuild()

        self.assertIsInstance(result, RebuildDerivedStateResult)
        self.assertEqual(result.items_scanned, 3)
        self.assertEqual(result.versions_verified, 4)
        self.assertEqual(result.idempotency_records_verified, 4)
        self.assertEqual(result.projections_rebuilt, 3)
        self.assertEqual(result.projections_unchanged, 0)
        self.assertEqual(result.derived_directories_created, 0)
        self.assertEqual(result.outbox_jobs_rebuilt, 0)
        public = result.to_dict()
        self.assertEqual(public["ok"], True)
        self.assertNotIn("saved", public)
        self.assertNotIn("commit_state", public)
        self.assertNotIn("warnings", public)
        self.assertEqual(
            parse_restricted_yaml((self.base_item / "capture.yaml").read_bytes())[
                "current_version"
            ],
            2,
        )
        self.assertEqual(self._list().warnings, ())
        self.assertEqual(
            {
                item.name: self._immutable_bytes(item)
                for item in (self.base_item, missing_item, corrupt_item)
            },
            immutable_before,
        )

        projection_bytes = {
            item.name: (item / "capture.yaml").read_bytes()
            for item in (self.base_item, missing_item, corrupt_item)
        }
        repeated = self._fixed_rebuild()
        self.assertIsInstance(repeated, RebuildDerivedStateResult)
        self.assertEqual(repeated.projections_rebuilt, 0)
        self.assertEqual(repeated.projections_unchanged, 3)
        self.assertEqual(repeated.derived_directories_created, 0)
        self.assertEqual(
            {
                item.name: (item / "capture.yaml").read_bytes()
                for item in (self.base_item, missing_item, corrupt_item)
            },
            projection_bytes,
        )

    def test_rec_02_recreates_empty_index_and_retries_from_immutable_records(
        self,
    ) -> None:
        append_request = AppendCaptureVersionRequest(
            capture_id=self.base_id,
            expected_current_version=1,
            text="idempotent append",
            channel=self._channel(),
            idempotency_key="c6b-index-append",
        )
        appended = append_capture_version(
            append_request,
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(appended, AppendCaptureVersionResult)
        (self.capture_root / "indexes" / "idempotency").rmdir()
        (self.capture_root / "indexes").rmdir()

        result = rebuild_capture_store_derived_state(
            config_path=self.config_path,
            path_policy=self.policy,
        )

        self.assertIsInstance(result, RebuildDerivedStateResult)
        self.assertEqual(result.derived_directories_created, 2)
        self.assertEqual(result.idempotency_records_verified, 2)
        self.assertEqual(tuple((self.capture_root / "indexes").iterdir()), (
            self.capture_root / "indexes" / "idempotency",
        ))
        self.assertEqual(
            tuple((self.capture_root / "indexes" / "idempotency").iterdir()),
            (),
        )

        retried_create = capture_text(
            self.base_request,
            config_path=self.config_path,
            path_policy=self.policy,
        )
        retried_append = append_capture_version(
            append_request,
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(retried_create, CommittedWriteResult)
        self.assertIsInstance(retried_append, AppendCaptureVersionResult)
        self.assertEqual(retried_create.receipt, self.base_result.receipt)
        self.assertEqual(retried_append.receipt, appended.receipt)

    def test_rec_03_recreates_only_the_empty_outbox_skeleton(self) -> None:
        outbox = self.capture_root / "outbox"
        for name in ("pending", "running", "failed", "completed"):
            (outbox / name).rmdir()
        outbox.rmdir()

        result = rebuild_capture_store_derived_state(
            config_path=self.config_path,
            path_policy=self.policy,
        )

        self.assertIsInstance(result, RebuildDerivedStateResult)
        self.assertEqual(result.derived_directories_created, 5)
        self.assertEqual(result.outbox_jobs_rebuilt, 0)
        self.assertEqual(
            {path.name for path in (self.capture_root / "outbox").iterdir()},
            {"pending", "running", "failed", "completed"},
        )
        for path in (self.capture_root / "outbox").iterdir():
            self.assertTrue(path.is_dir())
            self.assertEqual(tuple(path.iterdir()), ())

    def test_immutable_damage_fails_before_any_projection_is_written(self) -> None:
        other = self._capture(
            self._capture_request("must stay missing", key="c6b-fail-before-write")
        )
        other_item = self._item(str(other.receipt["capture_id"]))
        projection = other_item / "capture.yaml"
        projection.unlink()
        payload = self.base_item / "versions" / "000001" / "payloads" / "primary.txt"
        damaged = b"X" * len(payload.read_bytes())
        payload.write_bytes(damaged)

        result = self._fixed_rebuild()

        self.assertIsInstance(result, FailureResult)
        self.assertEqual(result.error.code, PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(result.error.cause_code, CauseCode.PAYLOAD_HASH_MISMATCH)
        self.assertIsNone(result.commit_state)
        self.assertFalse(projection.exists())
        self.assertEqual(payload.read_bytes(), damaged)

    def test_unknown_projection_or_derived_format_is_preserved_and_rejected(
        self,
    ) -> None:
        projection = self.base_item / "capture.yaml"
        original_projection = projection.read_bytes()
        future_projection = (
            b"schema: knowledgeflow.capture-state\n"
            b"schema_version: 2\n"
        )
        projection.write_bytes(future_projection)

        future_result = self._fixed_rebuild()

        self.assertIsInstance(future_result, FailureResult)
        self.assertEqual(
            future_result.error.code,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )
        self.assertEqual(projection.read_bytes(), future_projection)

        projection.write_bytes(original_projection)
        unknown = self.capture_root / "outbox" / "pending" / "unknown.job"
        unknown_bytes = b"future outbox bytes"
        unknown.write_bytes(unknown_bytes)
        derived_result = self._fixed_rebuild()

        self.assertIsInstance(derived_result, FailureResult)
        self.assertEqual(
            derived_result.error.code,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )
        self.assertEqual(unknown.read_bytes(), unknown_bytes)
        self.assertEqual(projection.read_bytes(), original_projection)

    def test_rebuild_does_not_repair_incomplete_tail_or_unknown_staging(self) -> None:
        tail = self.base_item / "versions" / "000002"
        tail.mkdir()
        staging = self.capture_root / ".staging" / "unknown-c6b-input"
        staging.mkdir()
        sentinel = staging / "sentinel.bin"
        sentinel.write_bytes(b"do not touch")
        (self.base_item / "capture.yaml").unlink()

        result = self._fixed_rebuild()

        self.assertIsInstance(result, RebuildDerivedStateResult)
        self.assertTrue(tail.is_dir())
        self.assertEqual(tuple(tail.iterdir()), ())
        self.assertEqual(sentinel.read_bytes(), b"do not touch")
        listed = self._list()
        self.assertEqual(len(listed.warnings), 1)
        self.assertEqual(
            listed.warnings[0].code,
            WarningCode.INCOMPLETE_VERSION_IGNORED,
        )

    def test_process_interruption_is_resumed_by_a_new_process(self) -> None:
        second = self._capture(
            self._capture_request("second item", key="c6b-interruption")
        )
        second_item = self._item(str(second.receipt["capture_id"]))
        projections = (
            self.base_item / "capture.yaml",
            second_item / "capture.yaml",
        )
        for projection in projections:
            projection.unlink()

        crashed_result_path = self.owned_root / "crashed-result.json"
        crashed = self._support_run(
            crashed_result_path,
            fault_point=_RebuildFaultPoint.AFTER_PROJECTION_REPLACED,
        )

        self.assertEqual(crashed.returncode, 70, msg=crashed.stderr)
        self.assertFalse(crashed_result_path.exists())
        self.assertEqual(sum(path.is_file() for path in projections), 1)
        self.assertEqual(
            tuple(self.capture_root.glob("items/*/*/*/.capture-state-rebuild-*.tmp")),
            (),
        )

        resumed_result_path = self.owned_root / "resumed-result.json"
        resumed = self._support_run(resumed_result_path)
        self.assertEqual(resumed.returncode, 0, msg=resumed.stderr)
        receipt = json.loads(resumed_result_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["ok"], True)
        self.assertEqual(receipt["items_scanned"], 2)
        self.assertEqual(receipt["projections_rebuilt"], 1)
        self.assertEqual(receipt["projections_unchanged"], 1)
        self.assertTrue(all(path.is_file() for path in projections))
        self.assertEqual(self._list().warnings, ())


if __name__ == "__main__":
    unittest.main()
