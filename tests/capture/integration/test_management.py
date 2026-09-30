from __future__ import annotations

from io import BytesIO
import errno
import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.errors import FailureResult, PublicErrorCode
from knowledgeflow_capture.management import (
    BackupCaptureStoreResult,
    CAPTURE_BACKUP_MANIFEST_FILENAME,
    CAPTURE_BACKUP_STORE_DIRECTORY,
    InitializeCaptureStoreResult,
    RestoreCaptureStoreResult,
    VerifyCaptureStoreResult,
    _ManagementDependencies,
    _ManagementFaultPoint,
    _backup_capture_store_with_dependencies,
    backup_capture_store,
    initialize_capture_store,
    load_capture_backup_manifest,
    restore_capture_store,
    verify_capture_store,
)
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
)
from knowledgeflow_capture.operations import (
    append_capture_version,
    capture_text,
    get_capture,
    list_captures,
)
from knowledgeflow_capture.paths import PathPolicy


_INLINE = 32
_MAXIMUM = 4096


class _SimulatedInterruption(BaseException):
    pass


class P0BManagementIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0B management is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"

    def _initialize(self) -> InitializeCaptureStoreResult:
        result = initialize_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=_INLINE,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, InitializeCaptureStoreResult)
        return result

    def _capture(self, text: str, key: str = "p0b-capture") -> object:
        result = capture_text(
            CaptureTextRequest(
                text=text,
                channel=ChannelMetadata(
                    type="app",
                    instance_id="p0b-integration",
                ),
                idempotency_key=key,
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(result, FailureResult)
        return result

    def _stable_bytes(self, root: Path) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if relative == "journal/capture-write.lock":
                continue
            if path.is_file():
                result[relative] = path.read_bytes()
        return result

    def test_init_is_idempotent_and_verify_is_non_repairing(self) -> None:
        created = self._initialize()
        reopened = self._initialize()

        self.assertTrue(created.created)
        self.assertFalse(reopened.created)
        self.assertEqual(reopened.store_id, created.store_id)
        before = self._stable_bytes(self.capture_root)
        verified = verify_capture_store(
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(verified, VerifyCaptureStoreResult)
        self.assertEqual(verified.items_verified, 0)
        self.assertEqual(verified.versions_verified, 0)
        self.assertEqual(self._stable_bytes(self.capture_root), before)

    def test_backup_restore_and_four_operations_form_one_complete_loop(self) -> None:
        initialized = self._initialize()
        first = self._capture("first version")
        capture_id = str(first.receipt["capture_id"])
        appended = append_capture_version(
            AppendCaptureVersionRequest(
                capture_id=capture_id,
                expected_current_version=1,
                text="second version",
                channel=ChannelMetadata(
                    type="app",
                    instance_id="p0b-integration",
                ),
                idempotency_key="p0b-append",
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(appended, FailureResult)

        source_before = self._stable_bytes(self.capture_root)
        config_before = self.config_path.read_bytes()
        backup_root = self.owned_root / "backup-one"
        backup = backup_capture_store(
            config_path=self.config_path,
            backup_root=backup_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(backup, BackupCaptureStoreResult)
        self.assertEqual(backup.store_id, initialized.store_id)
        self.assertEqual(backup.protection_scope, "operational-copy")
        self.assertEqual(self._stable_bytes(self.capture_root), source_before)
        self.assertEqual(self.config_path.read_bytes(), config_before)

        manifest = load_capture_backup_manifest(
            (backup_root / CAPTURE_BACKUP_MANIFEST_FILENAME).read_bytes()
        )
        paths = {record.relative_path for record in manifest.files}
        self.assertNotIn("journal/capture-write.lock", paths)
        self.assertFalse(any(path.startswith(".staging/") for path in paths))
        self.assertTrue(any(path.endswith("capture.yaml") for path in paths))

        restored_root = self.owned_root / "restored-store"
        restored = restore_capture_store(
            backup_root=backup_root,
            target_root=restored_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(restored, RestoreCaptureStoreResult)
        self.assertFalse(restored.config_switched)
        self.assertEqual(restored.snapshot_sha256, backup.snapshot_sha256)
        self.assertEqual(self._stable_bytes(restored_root), source_before)
        self.assertEqual(self.config_path.read_bytes(), config_before)

        restored_config = self.owned_root / "restored-config" / "config.yaml"
        connected = initialize_capture_store(
            config_path=restored_config,
            capture_root=restored_root,
            inline_text_threshold_bytes=_INLINE,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertIsInstance(connected, InitializeCaptureStoreResult)
        self.assertFalse(connected.created)
        self.assertEqual(connected.store_id, initialized.store_id)

        listed = list_captures(
            ListCapturesRequest(limit=10),
            config_path=restored_config,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(listed, FailureResult)
        self.assertEqual([item.capture_id for item in listed.items], [capture_id])
        sink = BytesIO()
        read = get_capture(
            GetCaptureRequest(capture_id=capture_id, body_sink=sink),
            config_path=restored_config,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(read, FailureResult)
        self.assertEqual(sink.getvalue(), b"second version")
        appended_again = append_capture_version(
            AppendCaptureVersionRequest(
                capture_id=capture_id,
                expected_current_version=2,
                text="third version",
                channel=ChannelMetadata(
                    type="app",
                    instance_id="p0b-restored",
                ),
                idempotency_key="p0b-restored-append",
            ),
            config_path=restored_config,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(appended_again, FailureResult)
        captured_again = capture_text(
            CaptureTextRequest(
                text="new restored item",
                channel=ChannelMetadata(
                    type="app",
                    instance_id="p0b-restored",
                ),
                idempotency_key="p0b-restored-capture",
            ),
            config_path=restored_config,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(captured_again, FailureResult)

    def test_foreign_or_even_empty_existing_targets_are_never_overwritten(self) -> None:
        self._initialize()
        self._capture("source")
        source_before = self._stable_bytes(self.capture_root)
        foreign = self.owned_root / "foreign-backup"
        foreign.mkdir()
        sentinel = foreign / "sentinel.bin"
        sentinel.write_bytes(b"foreign")

        rejected = backup_capture_store(
            config_path=self.config_path,
            backup_root=foreign,
            path_policy=self.policy,
        )
        self.assertIsInstance(rejected, FailureResult)
        self.assertEqual(
            rejected.error.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(sentinel.read_bytes(), b"foreign")
        self.assertEqual(self._stable_bytes(self.capture_root), source_before)

        empty = self.owned_root / "existing-empty"
        empty.mkdir()
        rejected_empty = backup_capture_store(
            config_path=self.config_path,
            backup_root=empty,
            path_policy=self.policy,
        )
        self.assertIsInstance(rejected_empty, FailureResult)
        self.assertEqual(tuple(empty.iterdir()), ())

    def test_tampered_backup_is_rejected_without_creating_restore_target(self) -> None:
        self._initialize()
        self._capture("tamper target")
        backup_root = self.owned_root / "backup-tamper"
        result = backup_capture_store(
            config_path=self.config_path,
            backup_root=backup_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, BackupCaptureStoreResult)
        payload = next(
            (backup_root / CAPTURE_BACKUP_STORE_DIRECTORY).rglob("primary.txt")
        )
        source = payload.read_bytes()
        payload.write_bytes(bytes([source[0] ^ 1]) + source[1:])

        restored_root = self.owned_root / "tampered-restore"
        restored = restore_capture_store(
            backup_root=backup_root,
            target_root=restored_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(restored, FailureResult)
        self.assertEqual(
            restored.error.code,
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )
        self.assertFalse(restored_root.exists())

    def test_interrupted_backup_is_preserved_and_not_resumed(self) -> None:
        self._initialize()
        self._capture("interrupt me")
        source_before = self._stable_bytes(self.capture_root)
        target = self.owned_root / "interrupted-backup"

        def interrupt() -> None:
            raise _SimulatedInterruption

        with self.assertRaises(_SimulatedInterruption):
            _backup_capture_store_with_dependencies(
                config_path=self.config_path,
                backup_root=target,
                path_policy=self.policy,
                dependencies=_ManagementDependencies(
                    fault_point=(
                        _ManagementFaultPoint.AFTER_BACKUP_FILE_COPIED
                    ),
                    fault_hook=interrupt,
                ),
            )
        self.assertTrue(target.is_dir())
        partial_before = self._stable_bytes(target)
        self.assertNotIn(CAPTURE_BACKUP_MANIFEST_FILENAME, partial_before)
        retried = backup_capture_store(
            config_path=self.config_path,
            backup_root=target,
            path_policy=self.policy,
        )
        self.assertIsInstance(retried, FailureResult)
        self.assertEqual(
            retried.error.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(self._stable_bytes(target), partial_before)
        self.assertEqual(self._stable_bytes(self.capture_root), source_before)

    def test_space_failure_leaves_evidence_and_source_unchanged(self) -> None:
        self._initialize()
        self._capture("space failure")
        source_before = self._stable_bytes(self.capture_root)
        config_before = self.config_path.read_bytes()
        target = self.owned_root / "space-failure-backup"

        def no_space(_descriptor: int) -> None:
            raise OSError(errno.ENOSPC, "no space")

        result = _backup_capture_store_with_dependencies(
            config_path=self.config_path,
            backup_root=target,
            path_policy=self.policy,
            dependencies=_ManagementDependencies(transfer_fsync=no_space),
        )
        self.assertIsInstance(result, FailureResult)
        self.assertEqual(
            result.error.code,
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        )
        self.assertTrue(target.exists())
        self.assertFalse((target / CAPTURE_BACKUP_MANIFEST_FILENAME).exists())
        self.assertEqual(self._stable_bytes(self.capture_root), source_before)
        self.assertEqual(self.config_path.read_bytes(), config_before)

    def test_staging_is_excluded_but_incomplete_tail_directory_is_preserved(self) -> None:
        self._initialize()
        captured = self._capture("tail source")
        item = next((self.capture_root / "items").rglob(str(captured.receipt["capture_id"])))
        tail = item / "versions" / "000002"
        tail.mkdir()
        unknown_staging = self.capture_root / ".staging" / "unknown-p0b"
        unknown_staging.mkdir()
        (unknown_staging / "sentinel.bin").write_bytes(b"do not copy")

        target = self.owned_root / "policy-backup"
        result = backup_capture_store(
            config_path=self.config_path,
            backup_root=target,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, BackupCaptureStoreResult)
        manifest = load_capture_backup_manifest(
            (target / CAPTURE_BACKUP_MANIFEST_FILENAME).read_bytes()
        )
        self.assertIn(
            tail.relative_to(self.capture_root).as_posix(),
            manifest.directories,
        )
        self.assertFalse(
            any("unknown-p0b" in value for value in manifest.directories)
        )
        self.assertFalse(
            (target / CAPTURE_BACKUP_STORE_DIRECTORY / ".staging" / "unknown-p0b").exists()
        )


if __name__ == "__main__":
    unittest.main()
