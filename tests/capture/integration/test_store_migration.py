"""C6C copy, verification, and atomic configuration-switch acceptance."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from knowledgeflow_capture.config import read_local_config_file
from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    PublicErrorCode,
)
from knowledgeflow_capture.migration import (
    MigrateCaptureStoreResult,
    _MigrationDependencies,
    _MigrationFaultPoint,
    _migrate_capture_store_with_dependencies,
    migrate_capture_store,
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
from knowledgeflow_capture.store import InitStoreResult, init_capture_store


_SUPPORT = Path(__file__).resolve().parents[1] / "_support.py"
_FAULT_EXIT_CODE = 70


class StoreMigrationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C6C Store migration is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.source_root = self.owned_root / "capture-store-a"
        self.target_root = self.owned_root / "capture-store-b"
        self._processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._stop_processes)

        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.source_root,
            inline_text_threshold_bytes=32,
            max_text_version_bytes=4096,
            path_policy=self.policy,
        )
        self.assertIsInstance(initialized, InitStoreResult)
        self.store_id = initialized.store_id

        created = capture_text(
            self._capture_request("base version 1", key="c6c-create-base"),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(created, CommittedWriteResult)
        self.capture_id = str(created.receipt["capture_id"])
        appended = append_capture_version(
            self._append_request(
                self.capture_id,
                expected=1,
                text="base version 2",
                key="c6c-append-base-v2",
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(appended, AppendCaptureVersionResult)

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

    @staticmethod
    def _channel() -> ChannelMetadata:
        return ChannelMetadata(type="app", instance_id="c6c-migration")

    def _capture_request(self, text: str, *, key: str) -> CaptureTextRequest:
        return CaptureTextRequest(
            text=text,
            channel=self._channel(),
            idempotency_key=key,
        )

    def _append_request(
        self,
        capture_id: str,
        *,
        expected: int,
        text: str,
        key: str,
    ) -> AppendCaptureVersionRequest:
        return AppendCaptureVersionRequest(
            capture_id=capture_id,
            expected_current_version=expected,
            text=text,
            channel=self._channel(),
            idempotency_key=key,
        )

    def _migrate(
        self,
        *,
        dependencies: _MigrationDependencies | None = None,
    ) -> MigrateCaptureStoreResult | FailureResult:
        arguments = {
            "config_path": self.config_path,
            "source_root": self.source_root,
            "target_root": self.target_root,
            "expected_store_id": self.store_id,
            "path_policy": self.policy,
        }
        if dependencies is None:
            return migrate_capture_store(**arguments)
        return _migrate_capture_store_with_dependencies(
            **arguments,
            dependencies=dependencies,
        )

    def _configured_root(self) -> Path:
        return read_local_config_file(
            self.config_path,
            path_policy=self.policy,
        ).capture.root

    @staticmethod
    def _stable_store_bytes(capture_root: Path) -> dict[str, bytes]:
        snapshot: dict[str, bytes] = {}
        for path in sorted(capture_root.rglob("*")):
            relative = path.relative_to(capture_root)
            if relative.parts and relative.parts[0] == ".staging":
                continue
            if relative.as_posix() == "journal/capture-write.lock":
                continue
            if path.is_file():
                snapshot[relative.as_posix()] = path.read_bytes()
        return snapshot

    @staticmethod
    def _item(capture_root: Path, capture_id: str) -> Path | None:
        matches = tuple(capture_root.glob(f"items/*/*/{capture_id}"))
        if not matches:
            return None
        if len(matches) != 1:
            raise AssertionError("capture identity is not unique")
        return matches[0]

    def _list(self) -> ListCapturesResult:
        result = list_captures(
            ListCapturesRequest(limit=100),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, ListCapturesResult)
        return result

    def _fault_migration(
        self,
        result_path: Path,
        fault_point: _MigrationFaultPoint,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(_SUPPORT),
                "migrate-store-c6",
                str(self.owned_root),
                str(self.config_path),
                str(self.source_root),
                str(self.target_root),
                self.store_id,
                str(result_path),
                "--fault-point",
                fault_point.value,
            ],
            cwd=self.owned_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def _wait_for_path(self, path: Path, message: str) -> None:
        deadline = time.monotonic() + 30.0
        while not path.exists():
            if time.monotonic() >= deadline:
                self.fail(message)
            time.sleep(0.01)

    def test_mig_01_04_05_copies_switches_and_runs_all_four_operations(self) -> None:
        source_before = self._stable_store_bytes(self.source_root)

        migrated = self._migrate()

        self.assertIsInstance(migrated, MigrateCaptureStoreResult)
        self.assertTrue(migrated.config_switched)
        self.assertTrue(migrated.source_retained)
        self.assertEqual(migrated.store_id, self.store_id)
        self.assertEqual(self._configured_root(), self.target_root)
        self.assertEqual(
            self._stable_store_bytes(self.target_root),
            source_before,
        )
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)

        sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(capture_id=self.capture_id, body_sink=sink),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(read, GetCaptureResult)
        self.assertEqual(sink.getvalue(), b"base version 2")
        listed = self._list()
        self.assertEqual(
            {item.capture_id for item in listed.items},
            {self.capture_id},
        )

        created = capture_text(
            self._capture_request("created after migration", key="c6c-after-copy"),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(created, CommittedWriteResult)
        new_capture_id = str(created.receipt["capture_id"])
        appended = append_capture_version(
            self._append_request(
                self.capture_id,
                expected=2,
                text="base version 3",
                key="c6c-append-after-copy",
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(appended, AppendCaptureVersionResult)
        self.assertEqual(appended.receipt["version"], 3)
        self.assertIsNotNone(self._item(self.target_root, new_capture_id))
        self.assertIsNone(self._item(self.source_root, new_capture_id))
        source_item = self._item(self.source_root, self.capture_id)
        target_item = self._item(self.target_root, self.capture_id)
        self.assertIsNotNone(source_item)
        self.assertIsNotNone(target_item)
        self.assertFalse((source_item / "versions" / "000003").exists())
        self.assertTrue((target_item / "versions" / "000003").is_dir())
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)

    def test_mig_02_process_exit_keeps_source_config_and_retry_resumes(self) -> None:
        source_before = self._stable_store_bytes(self.source_root)
        result_path = self.owned_root / "migration-fault-result.json"

        process = self._fault_migration(
            result_path,
            _MigrationFaultPoint.AFTER_TARGET_FILE_COPIED,
        )

        self.assertEqual(process.returncode, _FAULT_EXIT_CODE)
        self.assertFalse(result_path.exists())
        self.assertEqual(self._configured_root(), self.source_root)
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)
        copied_files = [
            path
            for path in self.target_root.rglob("*")
            if path.is_file()
            and path.relative_to(self.target_root).as_posix()
            != "journal/capture-write.lock"
        ]
        self.assertEqual(len(copied_files), 1)

        retried = self._migrate()

        self.assertIsInstance(retried, MigrateCaptureStoreResult)
        self.assertTrue(retried.config_switched)
        self.assertGreaterEqual(retried.files_reused, 1)
        self.assertEqual(self._configured_root(), self.target_root)
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)

    def test_mig_03_corrupt_partial_target_is_rejected_without_switch(self) -> None:
        result_path = self.owned_root / "migration-corrupt-result.json"
        process = self._fault_migration(
            result_path,
            _MigrationFaultPoint.AFTER_TARGET_FILE_COPIED,
        )
        self.assertEqual(process.returncode, _FAULT_EXIT_CODE)
        copied_files = [
            path
            for path in self.target_root.rglob("*")
            if path.is_file()
            and path.relative_to(self.target_root).as_posix()
            != "journal/capture-write.lock"
        ]
        self.assertEqual(len(copied_files), 1)
        corrupted = copied_files[0]
        corrupted.write_bytes(corrupted.read_bytes() + b"corrupt")
        corrupt_bytes = corrupted.read_bytes()

        result = self._migrate()

        self.assertIsInstance(result, FailureResult)
        self.assertEqual(
            result.error.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(self._configured_root(), self.source_root)
        self.assertEqual(corrupted.read_bytes(), corrupt_bytes)
        self.assertEqual(
            {item.capture_id for item in self._list().items},
            {self.capture_id},
        )

    def test_nonempty_unknown_target_is_preserved_and_rejected(self) -> None:
        self.target_root.mkdir()
        foreign = self.target_root / "foreign.bin"
        foreign.write_bytes(b"foreign target bytes")

        result = self._migrate()

        self.assertIsInstance(result, FailureResult)
        self.assertEqual(
            result.error.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(self._configured_root(), self.source_root)
        self.assertEqual(foreign.read_bytes(), b"foreign target bytes")
        self.assertEqual(tuple(self.target_root.iterdir()), (foreign,))

    def test_config_replace_failure_leaves_source_active_and_retry_reuses_target(
        self,
    ) -> None:
        source_before = self._stable_store_bytes(self.source_root)

        def fail_replace(_source: Path, _destination: Path) -> None:
            raise OSError("injected config replacement failure")

        failed = self._migrate(
            dependencies=_MigrationDependencies(replace_file=fail_replace)
        )

        self.assertIsInstance(failed, FailureResult)
        self.assertEqual(
            failed.error.code,
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        )
        self.assertEqual(
            failed.error.details["stage"],
            "migration-config-replace",
        )
        self.assertEqual(self._configured_root(), self.source_root)
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)
        self.assertEqual(self._stable_store_bytes(self.target_root), source_before)

        retried = self._migrate()

        self.assertIsInstance(retried, MigrateCaptureStoreResult)
        self.assertTrue(retried.config_switched)
        self.assertEqual(retried.files_copied, 0)
        self.assertGreater(retried.files_reused, 0)
        self.assertEqual(self._configured_root(), self.target_root)

    def test_process_exit_after_atomic_switch_replays_as_completed(self) -> None:
        source_before = self._stable_store_bytes(self.source_root)
        result_path = self.owned_root / "migration-after-switch-result.json"

        process = self._fault_migration(
            result_path,
            _MigrationFaultPoint.AFTER_CONFIG_REPLACED,
        )

        self.assertEqual(process.returncode, _FAULT_EXIT_CODE)
        self.assertFalse(result_path.exists())
        self.assertEqual(self._configured_root(), self.target_root)
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)
        self.assertEqual(self._stable_store_bytes(self.target_root), source_before)

        replay = self._migrate()

        self.assertIsInstance(replay, MigrateCaptureStoreResult)
        self.assertFalse(replay.config_switched)
        self.assertTrue(replay.source_retained)
        self.assertEqual(self._configured_root(), self.target_root)

    def test_waiting_writer_rechecks_config_and_cannot_diverge_source(self) -> None:
        ready = self.owned_root / "waiting-writer.ready"
        gate = self.owned_root / "waiting-writer.gate"
        result_path = self.owned_root / "waiting-writer-result.json"
        source_before = self._stable_store_bytes(self.source_root)
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT),
                "capture-text-lock-barrier",
                str(self.owned_root),
                str(self.config_path),
                "waiting writer body",
                "c6c-waiting-writer",
                str(ready),
                str(gate),
                str(result_path),
            ],
            cwd=self.owned_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        self._wait_for_path(
            ready,
            "writer did not reach the pre-lock migration boundary",
        )
        self.assertEqual(len(tuple((self.source_root / ".staging").iterdir())), 1)

        migrated = self._migrate()
        self.assertIsInstance(migrated, MigrateCaptureStoreResult)
        gate.write_bytes(b"go")
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, (stdout, stderr))
        waiting_result = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(waiting_result["ok"])
        self.assertEqual(waiting_result["commit_state"], CommitState.NOT_COMMITTED)
        self.assertEqual(
            waiting_result["error"]["code"],
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        )
        self.assertEqual(
            waiting_result["error"]["details"]["stage"],
            "config-binding-changed",
        )
        self.assertEqual(tuple((self.source_root / ".staging").iterdir()), ())
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)
        self.assertEqual(
            {item.capture_id for item in self._list().items},
            {self.capture_id},
        )

        retried = capture_text(
            CaptureTextRequest(
                text="waiting writer body",
                channel=ChannelMetadata(
                    type="app",
                    instance_id="local-desktop",
                ),
                idempotency_key="c6c-waiting-writer",
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(retried, CommittedWriteResult)
        retried_id = str(retried.receipt["capture_id"])
        self.assertIsNotNone(self._item(self.target_root, retried_id))
        self.assertIsNone(self._item(self.source_root, retried_id))

    def test_source_integrity_failure_happens_before_target_creation(self) -> None:
        item = self._item(self.source_root, self.capture_id)
        self.assertIsNotNone(item)
        payload = item / "versions" / "000002" / "payloads" / "primary.txt"
        payload.write_bytes(b"tampered source")

        result = self._migrate()

        self.assertIsInstance(result, FailureResult)
        self.assertEqual(result.error.code, PublicErrorCode.INTEGRITY_CHECK_FAILED)
        self.assertEqual(self._configured_root(), self.source_root)
        self.assertFalse(self.target_root.exists())

    def test_completed_migration_replay_is_read_only_and_idempotent(self) -> None:
        first = self._migrate()
        self.assertIsInstance(first, MigrateCaptureStoreResult)
        source_before = self._stable_store_bytes(self.source_root)
        target_before = self._stable_store_bytes(self.target_root)
        config_before = self.config_path.read_bytes()

        replay = self._migrate()

        self.assertIsInstance(replay, MigrateCaptureStoreResult)
        self.assertFalse(replay.config_switched)
        self.assertTrue(replay.source_retained)
        self.assertEqual(self.config_path.read_bytes(), config_before)
        self.assertEqual(self._stable_store_bytes(self.source_root), source_before)
        self.assertEqual(self._stable_store_bytes(self.target_root), target_before)


if __name__ == "__main__":
    unittest.main()
