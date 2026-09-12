from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from knowledgeflow_capture.config import (
    create_local_config,
    dump_local_config,
    parse_local_config,
)
from knowledgeflow_capture.durability import DurabilityError, DurabilityStage
from knowledgeflow_capture.errors import FailureResult, PublicErrorCode
from knowledgeflow_capture.manifest import (
    CaptureStoreManifest,
    dump_capture_store_manifest,
    load_capture_store_manifest,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import (
    CAPTURE_STORE_MANIFEST_FILENAME,
    CAPTURE_STORE_REQUIRED_DIRECTORIES,
    InitStoreResult,
    _InitFaultPoint,
    _InitTransaction,
    _StoreDependencies,
    _config_temp_name,
    _dump_init_transaction,
    _init_capture_store_with_dependencies,
    _initialization_request_sha256,
    init_capture_store,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_INLINE_THRESHOLD = 4 * 1024 * 1024
_MAXIMUM = 64 * 1024 * 1024
_STORE_ID = "store_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
_CREATED_AT = "2026-09-03T01:02:03.004Z"
_UUIDS = (
    "01991a7e-7b20-7a31-8d14-0b8ab6b35421",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35422",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35423",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35424",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35425",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35426",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35427",
)


class InitCaptureStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C2B-2 initialization contract is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        self._processes: list[subprocess.Popen[str]] = []
        self.addCleanup(self._stop_processes)

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

    def _init(
        self,
        *,
        config_path: Path | None = None,
        capture_root: Path | None = None,
        inline_threshold: int = _INLINE_THRESHOLD,
        maximum: int = _MAXIMUM,
    ) -> InitStoreResult | FailureResult:
        return init_capture_store(
            config_path=config_path or self.config_path,
            capture_root=capture_root or self.capture_root,
            inline_text_threshold_bytes=inline_threshold,
            max_text_version_bytes=maximum,
            path_policy=self.policy,
        )

    def _assert_failure(
        self,
        result: InitStoreResult | FailureResult,
        code: PublicErrorCode,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        serialized = failure.to_dict()
        self.assertFalse(serialized["ok"])
        self.assertNotIn("saved", serialized)
        self.assertNotIn("commit_state", serialized)
        return failure

    def _assert_success(
        self,
        result: InitStoreResult | FailureResult,
    ) -> InitStoreResult:
        self.assertIsInstance(result, InitStoreResult)
        success = result
        serialized = success.to_dict()
        self.assertTrue(serialized["ok"])
        self.assertTrue(serialized["store_initialized"])
        self.assertTrue(serialized["config_connected"])
        self.assertNotIn("saved", serialized)
        self.assertNotIn("commit_state", serialized)
        return success

    def _make_valid_store(
        self,
        root: Path,
        *,
        store_id: str = _STORE_ID,
    ) -> CaptureStoreManifest:
        root.mkdir()
        for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
            root.joinpath(*parts).mkdir()
        manifest = CaptureStoreManifest(
            store_id=store_id,
            created_at=_CREATED_AT,
        )
        (root / CAPTURE_STORE_MANIFEST_FILENAME).write_bytes(
            dump_capture_store_manifest(manifest)
        )
        return manifest

    def _assert_complete_store(self, root: Path) -> CaptureStoreManifest:
        manifest_path = root / CAPTURE_STORE_MANIFEST_FILENAME
        self.assertTrue(manifest_path.is_file())
        manifest = load_capture_store_manifest(manifest_path.read_bytes())
        for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
            self.assertTrue(root.joinpath(*parts).is_dir(), parts)
        return manifest

    def _snapshot(self, root: Path) -> dict[str, tuple[str, bytes | None]]:
        if not root.exists():
            return {}
        snapshot: dict[str, tuple[str, bytes | None]] = {}

        def visit(path: Path) -> None:
            relative = path.relative_to(root).as_posix() or "."
            path_stat = os.stat(path, follow_symlinks=False)
            if os.path.isdir(path):
                snapshot[relative] = ("directory", None)
                for child in sorted(path.iterdir(), key=lambda item: item.name):
                    visit(child)
            elif os.path.isfile(path):
                snapshot[relative] = ("file", path.read_bytes())
            else:
                snapshot[relative] = (f"other:{path_stat.st_mode}", None)

        visit(root)
        return snapshot

    def _transaction_candidates(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in self.owned_root.iterdir()
            if path.name.startswith(".knowledgeflow-init-")
        )

    def _start_initializer(
        self,
        *,
        label: str,
        config_path: Path,
        capture_root: Path,
        gate: Path,
    ) -> tuple[subprocess.Popen[str], Path, Path]:
        started = self.owned_root / f"{label}.started"
        result_path = self.owned_root / f"{label}.result.json"
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                "init-store",
                str(self.owned_root),
                str(config_path),
                str(capture_root),
                str(_INLINE_THRESHOLD),
                str(_MAXIMUM),
                str(started),
                str(gate),
                str(result_path),
            ],
            cwd=_REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        return process, started, result_path

    def _wait_for_marker(
        self,
        marker: Path,
        process: subprocess.Popen[str],
        *,
        timeout: float = 5.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker.exists():
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(
                    f"initializer exited early with {process.returncode}: "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            time.sleep(0.01)
        self.fail("timed out waiting for initializer marker")

    def _collect_initializer(
        self,
        process: subprocess.Popen[str],
        result_path: Path,
    ) -> dict[str, object]:
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(
            process.returncode,
            0,
            f"stdout={stdout!r}, stderr={stderr!r}",
        )
        return json.loads(result_path.read_text(encoding="utf-8"))

    def test_init_01_missing_target_creates_complete_store_and_config(self) -> None:
        success = self._assert_success(self._init())

        self.assertTrue(success.created)
        manifest = self._assert_complete_store(self.capture_root)
        self.assertEqual(success.store_id, manifest.store_id)
        config = parse_local_config(
            self.config_path.read_bytes(),
            path_policy=self.policy,
        )
        self.assertEqual(config.capture.root, self.capture_root)
        self.assertEqual(success.capture_root, self.capture_root)
        self.assertEqual(self._transaction_candidates(), ())

    def test_init_02_valid_store_retry_reuses_identity(self) -> None:
        first = self._assert_success(self._init())
        store_snapshot = self._snapshot(self.capture_root)
        config_bytes = self.config_path.read_bytes()

        second = self._assert_success(self._init())

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.store_id, first.store_id)
        self.assertEqual(self._snapshot(self.capture_root), store_snapshot)
        self.assertEqual(self.config_path.read_bytes(), config_bytes)

    def test_init_03_empty_existing_directory_is_not_adopted(self) -> None:
        self.capture_root.mkdir()
        before = self._snapshot(self.capture_root)

        result = self._init()

        self._assert_failure(
            result,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(self._snapshot(self.capture_root), before)
        self.assertFalse(self.config_path.exists())

    def test_init_04_unknown_nonempty_directory_is_untouched(self) -> None:
        self.capture_root.mkdir()
        sentinel = self.capture_root / "user-file.txt"
        sentinel.write_bytes(b"must remain")
        before = self._snapshot(self.capture_root)

        result = self._init()

        self._assert_failure(
            result,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(self._snapshot(self.capture_root), before)
        self.assertFalse(self.config_path.exists())

    def test_init_05_unknown_manifest_version_waits_for_migration(self) -> None:
        self.capture_root.mkdir()
        unsupported = dump_capture_store_manifest(
            CaptureStoreManifest(store_id=_STORE_ID, created_at=_CREATED_AT)
        ).replace(b"layout_version: 1\n", b"layout_version: 2\n")
        manifest_path = self.capture_root / CAPTURE_STORE_MANIFEST_FILENAME
        manifest_path.write_bytes(unsupported)
        before = self._snapshot(self.capture_root)

        result = self._init()

        self._assert_failure(result, PublicErrorCode.UNSUPPORTED_STORE_VERSION)
        self.assertEqual(self._snapshot(self.capture_root), before)
        self.assertFalse(self.config_path.exists())

    def test_init_06_existing_config_cannot_switch_to_another_store(self) -> None:
        first = self._assert_success(self._init())
        first_store = self._snapshot(self.capture_root)
        config_bytes = self.config_path.read_bytes()
        other_root = self.owned_root / "other-store"

        result = self._init(capture_root=other_root)

        self._assert_failure(result, PublicErrorCode.CONFIG_STORE_CONFLICT)
        self.assertTrue(first.created)
        self.assertFalse(other_root.exists())
        self.assertEqual(self._snapshot(self.capture_root), first_store)
        self.assertEqual(self.config_path.read_bytes(), config_bytes)

    def test_init_07_existing_unconnected_store_is_reused(self) -> None:
        manifest = self._make_valid_store(self.capture_root)

        success = self._assert_success(self._init())

        self.assertFalse(success.created)
        self.assertEqual(success.store_id, manifest.store_id)
        self.assertTrue(self.config_path.is_file())
        self.assertEqual(self._assert_complete_store(self.capture_root), manifest)

    def test_init_08_manifest_contains_no_host_absolute_path(self) -> None:
        self._assert_success(self._init())

        manifest_bytes = (
            self.capture_root / CAPTURE_STORE_MANIFEST_FILENAME
        ).read_bytes()
        load_capture_store_manifest(manifest_bytes)
        self.assertNotIn(str(self.owned_root).encode("utf-8"), manifest_bytes)
        self.assertNotIn(b"capture_root", manifest_bytes)

    def test_init_09_success_creates_no_capture_job_or_external_artifact(self) -> None:
        self._assert_success(self._init())

        empty_directories = (
            ("items",),
            ("outbox", "pending"),
            ("outbox", "running"),
            ("outbox", "failed"),
            ("outbox", "completed"),
            ("indexes", "idempotency"),
            (".staging",),
            ("journal",),
        )
        for parts in empty_directories:
            with self.subTest(parts=parts):
                self.assertEqual(tuple(self.capture_root.joinpath(*parts).iterdir()), ())
        files = tuple(path for path in self.capture_root.rglob("*") if path.is_file())
        self.assertEqual(
            files,
            (self.capture_root / CAPTURE_STORE_MANIFEST_FILENAME,),
        )

    def test_init_10_incomplete_or_wrong_type_skeleton_is_not_repaired(self) -> None:
        missing_root = self.owned_root / "missing-skeleton"
        self._make_valid_store(missing_root)
        (missing_root / "journal").rmdir()
        missing_before = self._snapshot(missing_root)

        result = self._init(
            config_path=self.owned_root / "missing-config" / "config.yaml",
            capture_root=missing_root,
        )
        self._assert_failure(
            result,
            PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
        )
        self.assertEqual(self._snapshot(missing_root), missing_before)

        wrong_type_root = self.owned_root / "wrong-type-skeleton"
        self._make_valid_store(wrong_type_root)
        (wrong_type_root / "items").rmdir()
        (wrong_type_root / "items").write_bytes(b"not a directory")
        wrong_type_before = self._snapshot(wrong_type_root)

        result = self._init(
            config_path=self.owned_root / "wrong-config" / "config.yaml",
            capture_root=wrong_type_root,
        )
        self._assert_failure(
            result,
            PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
        )
        self.assertEqual(self._snapshot(wrong_type_root), wrong_type_before)

    def test_init_11_same_request_concurrency_has_one_creator(self) -> None:
        gate = self.owned_root / "same-request.gate"
        first, first_started, first_result = self._start_initializer(
            label="first",
            config_path=self.config_path,
            capture_root=self.capture_root,
            gate=gate,
        )
        second, second_started, second_result = self._start_initializer(
            label="second",
            config_path=self.config_path,
            capture_root=self.capture_root,
            gate=gate,
        )
        self._wait_for_marker(first_started, first)
        self._wait_for_marker(second_started, second)
        gate.write_bytes(b"go")

        results = (
            self._collect_initializer(first, first_result),
            self._collect_initializer(second, second_result),
        )

        self.assertEqual(
            [result["ok"] for result in results],
            [True, True],
            results,
        )
        self.assertEqual(
            sorted(result["created"] for result in results),
            [False, True],
        )
        self.assertEqual(results[0]["store_id"], results[1]["store_id"])
        self.assertEqual(
            self._assert_complete_store(self.capture_root).store_id,
            results[0]["store_id"],
        )
        self.assertEqual(self._transaction_candidates(), ())

    def test_init_12_different_roots_competing_for_config_leave_no_orphan(self) -> None:
        first_root = self.owned_root / "first-store"
        second_root = self.owned_root / "second-store"
        gate = self.owned_root / "different-roots.gate"
        first, first_started, first_result = self._start_initializer(
            label="first",
            config_path=self.config_path,
            capture_root=first_root,
            gate=gate,
        )
        second, second_started, second_result = self._start_initializer(
            label="second",
            config_path=self.config_path,
            capture_root=second_root,
            gate=gate,
        )
        self._wait_for_marker(first_started, first)
        self._wait_for_marker(second_started, second)
        gate.write_bytes(b"go")

        results = (
            self._collect_initializer(first, first_result),
            self._collect_initializer(second, second_result),
        )
        successes = [result for result in results if result["ok"]]
        failures = [result for result in results if not result["ok"]]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            failures[0]["error"]["code"],
            PublicErrorCode.CONFIG_STORE_CONFLICT.value,
        )
        winning_root = Path(successes[0]["capture_root"])
        losing_root = second_root if winning_root == first_root else first_root
        self._assert_complete_store(winning_root)
        self.assertFalse(losing_root.exists())
        self.assertEqual(self._transaction_candidates(), ())

    def test_init_13_threshold_difference_is_a_zero_write_conflict(self) -> None:
        self._assert_success(self._init())
        store_before = self._snapshot(self.capture_root)
        config_before = self.config_path.read_bytes()

        result = self._init(inline_threshold=_INLINE_THRESHOLD - 1)

        self._assert_failure(result, PublicErrorCode.CONFIG_STORE_CONFLICT)
        self.assertEqual(self._snapshot(self.capture_root), store_before)
        self.assertEqual(self.config_path.read_bytes(), config_before)
        self.assertEqual(self._transaction_candidates(), ())

    def test_init_14_invalid_path_relationships_create_no_target_chain(self) -> None:
        nested_config = self.capture_root / "config.yaml"
        result = self._init(config_path=nested_config)
        self._assert_failure(result, PublicErrorCode.CONFIG_INVALID)
        self.assertFalse(self.capture_root.exists())

        missing_store_parent = self.owned_root / "missing-store-parent"
        store_with_missing_parent = missing_store_parent / "store"
        result = self._init(
            config_path=self.owned_root / "store-parent-config" / "config.yaml",
            capture_root=store_with_missing_parent,
        )
        self._assert_failure(result, PublicErrorCode.CONFIG_INVALID)
        self.assertFalse(missing_store_parent.exists())

        first_missing = self.owned_root / "first-missing"
        recursive_config = first_missing / "second-missing" / "config.yaml"
        result = self._init(
            config_path=recursive_config,
            capture_root=self.owned_root / "recursive-config-store",
        )
        self._assert_failure(result, PublicErrorCode.CONFIG_INVALID)
        self.assertFalse(first_missing.exists())

    def test_init_15_extra_plain_entries_survive_idempotent_reopen(self) -> None:
        first = self._assert_success(self._init())
        extra_file = self.capture_root / "operator-note.txt"
        extra_file.write_bytes(b"preserve exactly")
        extra_directory = self.capture_root / ".git"
        extra_directory.mkdir()
        (extra_directory / "config").write_bytes(b"git metadata")
        extras_before = {
            "file": extra_file.read_bytes(),
            "git": (extra_directory / "config").read_bytes(),
        }

        second = self._assert_success(self._init())

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.store_id, first.store_id)
        self.assertEqual(extra_file.read_bytes(), extras_before["file"])
        self.assertEqual(
            (extra_directory / "config").read_bytes(),
            extras_before["git"],
        )

    def test_init_16_only_owned_recovery_candidates_are_removed(self) -> None:
        self.config_path.parent.mkdir()
        local_config = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        config_bytes = dump_local_config(local_config)
        request_sha256 = _initialization_request_sha256(
            config_path=self.policy.validate_config_path(self.config_path),
            capture_root=local_config.capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )

        owned_transaction = self.owned_root / f".knowledgeflow-init-{_UUIDS[0]}"
        owned_transaction.mkdir()
        (owned_transaction / "transaction.yaml").write_bytes(
            _dump_init_transaction(
                _InitTransaction(
                    transaction_id=_UUIDS[0],
                    request_sha256=request_sha256,
                )
            )
        )
        (owned_transaction / "store").mkdir()

        other_transaction = self.owned_root / f".knowledgeflow-init-{_UUIDS[1]}"
        other_transaction.mkdir()
        (other_transaction / "transaction.yaml").write_bytes(
            _dump_init_transaction(
                _InitTransaction(
                    transaction_id=_UUIDS[1],
                    request_sha256="sha256:" + ("0" * 64),
                )
            )
        )
        other_before = self._snapshot(other_transaction)

        unexpected_transaction = (
            self.owned_root / f".knowledgeflow-init-{_UUIDS[2]}"
        )
        unexpected_transaction.mkdir()
        (unexpected_transaction / "transaction.yaml").write_bytes(
            _dump_init_transaction(
                _InitTransaction(
                    transaction_id=_UUIDS[2],
                    request_sha256=request_sha256,
                )
            )
        )
        (unexpected_transaction / "unexpected.txt").write_bytes(b"preserve")
        unexpected_before = self._snapshot(unexpected_transaction)

        exact_temp = self.config_path.parent / _config_temp_name(
            request_sha256,
            _UUIDS[3],
        )
        exact_temp.write_bytes(config_bytes)
        foreign_config_path = self.config_path.parent / "foreign.yaml"
        foreign_request_sha256 = _initialization_request_sha256(
            config_path=self.policy.validate_config_path(foreign_config_path),
            capture_root=local_config.capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )
        foreign_temp = self.config_path.parent / _config_temp_name(
            foreign_request_sha256,
            _UUIDS[4],
        )
        foreign_temp.write_bytes(config_bytes)
        legacy_temp = self.config_path.parent / (
            f".knowledgeflow-config-{_UUIDS[5]}.tmp"
        )
        legacy_temp.write_bytes(config_bytes)

        success = self._assert_success(self._init())

        self.assertTrue(success.created)
        self.assertFalse(owned_transaction.exists())
        self.assertFalse(exact_temp.exists())
        self.assertEqual(foreign_temp.read_bytes(), config_bytes)
        self.assertEqual(legacy_temp.read_bytes(), config_bytes)
        self.assertEqual(self._snapshot(other_transaction), other_before)
        self.assertEqual(
            self._snapshot(unexpected_transaction),
            unexpected_before,
        )
        self._assert_complete_store(self.capture_root)

    def test_init_17_content_cleanup_failure_preserves_marker_for_retry(
        self,
    ) -> None:
        self.config_path.parent.mkdir()
        local_config = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        request_sha256 = _initialization_request_sha256(
            config_path=self.policy.validate_config_path(self.config_path),
            capture_root=local_config.capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )
        owned_transaction = self.owned_root / (
            f".knowledgeflow-init-{_UUIDS[0]}"
        )
        owned_transaction.mkdir()
        marker = owned_transaction / "transaction.yaml"
        marker.write_bytes(
            _dump_init_transaction(
                _InitTransaction(
                    transaction_id=_UUIDS[0],
                    request_sha256=request_sha256,
                )
            )
        )
        staged_store = owned_transaction / "store"
        staged_store.mkdir()
        content_file = staged_store / CAPTURE_STORE_MANIFEST_FILENAME
        content_file.write_bytes(b"owned incomplete manifest")

        original_unlink = Path.unlink

        def fail_owned_content(path: Path, missing_ok: bool = False) -> None:
            if path == content_file:
                raise PermissionError("injected content cleanup failure")
            original_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", new=fail_owned_content):
            failure = self._assert_failure(
                self._init(),
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            )

        self.assertEqual(failure.error.details, {"stage": "transaction-cleanup"})
        self.assertTrue(marker.is_file())
        self.assertEqual(content_file.read_bytes(), b"owned incomplete manifest")

        recovered = self._assert_success(self._init())

        self.assertTrue(recovered.created)
        self.assertFalse(owned_transaction.exists())
        self._assert_complete_store(self.capture_root)

    def test_init_18_distinct_config_targets_do_not_delete_inflight_temp(
        self,
    ) -> None:
        first_config = self.owned_root / "config" / "first.yaml"
        second_config = self.owned_root / "config" / "second.yaml"
        local_config = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        first_request_sha256 = _initialization_request_sha256(
            config_path=self.policy.validate_config_path(first_config),
            capture_root=local_config.capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )
        paused = threading.Event()
        release = threading.Event()

        def pause_before_config_commit() -> None:
            paused.set()
            if not release.wait(timeout=15):
                raise TimeoutError("timed out waiting to release config commit")

        first_dependencies = _StoreDependencies(
            fault_point=_InitFaultPoint.BEFORE_CONFIG_REPLACED,
            fault_hook=pause_before_config_commit,
        )

        def initialize_first() -> InitStoreResult | FailureResult:
            return _init_capture_store_with_dependencies(
                config_path=first_config,
                capture_root=self.capture_root,
                inline_text_threshold_bytes=_INLINE_THRESHOLD,
                max_text_version_bytes=_MAXIMUM,
                path_policy=self.policy,
                dependencies=first_dependencies,
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            first_future = executor.submit(initialize_first)
            if not paused.wait(timeout=10):
                release.set()
                self.fail("first initializer did not reach config commit barrier")
            try:
                inflight_candidates = tuple(
                    path
                    for path in first_config.parent.iterdir()
                    if path.name.startswith(".knowledgeflow-config-")
                )
                self.assertEqual(len(inflight_candidates), 1)
                first_temp = inflight_candidates[0]
                self.assertTrue(
                    first_temp.name.startswith(
                        ".knowledgeflow-config-"
                        f"{first_request_sha256.removeprefix('sha256:')}-"
                    )
                )
                first_temp_bytes = first_temp.read_bytes()
                second = self._assert_success(
                    self._init(
                        config_path=second_config,
                        capture_root=self.capture_root,
                    )
                )
                self.assertTrue(first_temp.is_file())
                self.assertEqual(first_temp.read_bytes(), first_temp_bytes)
            finally:
                release.set()
            first = self._assert_success(first_future.result(timeout=15))

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.store_id, second.store_id)
        self.assertTrue(first_config.is_file())
        self.assertTrue(second_config.is_file())
        self.assertEqual(
            tuple(
                path
                for path in first_config.parent.iterdir()
                if path.name.startswith(".knowledgeflow-config-")
            ),
            (),
        )

    def test_init_19_matching_identity_with_wrong_bytes_is_preserved(
        self,
    ) -> None:
        manifest = self._make_valid_store(self.capture_root)
        self.config_path.parent.mkdir()
        local_config = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        request_sha256 = _initialization_request_sha256(
            config_path=self.policy.validate_config_path(self.config_path),
            capture_root=local_config.capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )
        unknown_temp = self.config_path.parent / _config_temp_name(
            request_sha256,
            _UUIDS[6],
        )
        unknown_temp.write_bytes(b"unknown config fragment")

        success = self._assert_success(self._init())

        self.assertFalse(success.created)
        self.assertEqual(success.store_id, manifest.store_id)
        self.assertEqual(unknown_temp.read_bytes(), b"unknown config fragment")
        self.assertTrue(self.config_path.is_file())

    def test_r03d_m1_unknown_candidate_stat_failure_currently_blocks_reopen(
        self,
    ) -> None:
        first = self._assert_success(self._init())
        unknown_transaction = self.owned_root / (
            f".knowledgeflow-init-{_UUIDS[0]}"
        )
        unknown_transaction.mkdir()
        original_stat = os.stat
        observed_stat_failures = 0

        def fail_unknown_transaction_stat(
            path: object,
            *args: object,
            **kwargs: object,
        ) -> os.stat_result:
            nonlocal observed_stat_failures
            if (
                isinstance(path, (str, os.PathLike))
                and Path(path) == unknown_transaction
            ):
                observed_stat_failures += 1
                raise PermissionError("injected unknown transaction stat failure")
            return original_stat(path, *args, **kwargs)

        with mock.patch.object(os, "stat", new=fail_unknown_transaction_stat):
            failure = self._assert_failure(
                self._init(),
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            )

        self.assertEqual(observed_stat_failures, 1)
        self.assertFalse(failure.error.retryable)
        self.assertEqual(failure.error.details, {"stage": "path-stat"})
        self.assertTrue(unknown_transaction.is_dir())

        reopened = self._assert_success(self._init())
        self.assertFalse(reopened.created)
        self.assertEqual(reopened.store_id, first.store_id)
        self.assertTrue(unknown_transaction.is_dir())

    def test_r03d_m3_cleanup_identity_failure_currently_masks_primary_stage(
        self,
    ) -> None:
        primary = DurabilityError(DurabilityStage.FILE_READBACK)
        residue: list[Path] = []

        def fail_after_manifest_flush() -> None:
            candidates = tuple(
                path
                for path in self.owned_root.iterdir()
                if path.name.startswith(".knowledgeflow-init-")
            )
            self.assertEqual(len(candidates), 1)
            residue.append(candidates[0])
            (candidates[0] / "unexpected.txt").write_bytes(b"foreign evidence")
            raise primary

        dependencies = _StoreDependencies(
            fault_point=_InitFaultPoint.AFTER_MANIFEST_FLUSHED,
            fault_hook=fail_after_manifest_flush,
        )
        failure = self._assert_failure(
            _init_capture_store_with_dependencies(
                config_path=self.config_path,
                capture_root=self.capture_root,
                inline_text_threshold_bytes=_INLINE_THRESHOLD,
                max_text_version_bytes=_MAXIMUM,
                path_policy=self.policy,
                dependencies=dependencies,
            ),
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        )

        self.assertEqual(
            primary.to_operation_error().details,
            {"stage": "file-readback"},
        )
        self.assertEqual(
            failure.error.details,
            {"stage": "transaction-cleanup-identity"},
        )
        self.assertEqual(len(residue), 1)
        self.assertEqual(
            (residue[0] / "unexpected.txt").read_bytes(),
            b"foreign evidence",
        )

        recovered = self._assert_success(self._init())
        self.assertTrue(recovered.created)
        self.assertTrue(residue[0].is_dir())


if __name__ == "__main__":
    unittest.main()
