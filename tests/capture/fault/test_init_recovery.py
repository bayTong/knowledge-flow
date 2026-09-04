"""C2B-3 fault-injection recovery tests.

Each test crashes one child process at a fixed initialization fault point via
``os._exit`` (no exception unwinding), then proves that a brand-new process
without fault hooks recovers from disk facts alone: the kernel lock is
released by the operating system, owned fragments are cleaned, unknown
fragments stay byte-identical, no second store identity appears, and the
production config and capture-store paths are untouched.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest

from knowledgeflow_capture.config import (
    LocalConfig,
    create_local_config,
    dump_local_config,
    parse_local_config,
)
from knowledgeflow_capture.manifest import (
    CaptureStoreManifest,
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
    _dump_init_transaction,
    _init_capture_store_with_dependencies,
    _initialization_request_sha256,
    _load_init_transaction,
    init_capture_store,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_INLINE_THRESHOLD = 4 * 1024 * 1024
_MAXIMUM = 64 * 1024 * 1024
_UUIDS = (
    "01991a7e-7b20-7a31-8d14-0b8ab6b35431",
    "01991a7e-7b20-7a31-8d14-0b8ab6b35432",
)
_UNKNOWN_TEMP_BYTES = b"unknown config fragment"
_EMPTY_DIRECTORIES = (
    ("items",),
    ("outbox", "pending"),
    ("outbox", "running"),
    ("outbox", "failed"),
    ("outbox", "completed"),
    ("indexes", "idempotency"),
    (".staging",),
    ("journal",),
)
_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA")
_REAL_CONFIG_PATH = (
    Path(_LOCAL_APP_DATA) / "KnowledgeFlow" / "config.yaml"
    if _LOCAL_APP_DATA
    else None
)
_REAL_CAPTURE_STORE = Path("E:/") / "KnowledgeFlowData" / "capture-store"


def _load_support_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "knowledgeflow_capture_test_support",
        _SUPPORT_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load capture test support script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SUPPORT = _load_support_module()
_FAULT_EXIT_CODE = _SUPPORT.FAULT_EXIT_CODE


def _metadata_snapshot(path: Path | None) -> object:
    """Metadata-only snapshot; never reads file content."""

    if path is None:
        return None
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    if not stat.S_ISDIR(path_stat.st_mode):
        return ("file", path_stat.st_size, path_stat.st_mtime_ns)
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return ("directory", path_stat.st_mtime_ns, "unreadable")
    return (
        "directory",
        path_stat.st_mtime_ns,
        {child.name: _metadata_snapshot(child) for child in children},
    )


class InitFaultRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C2B-3 crash recovery contract is Windows-first")
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

    # ------------------------------------------------------------------ setup

    def _seed_unknown_fragments(self) -> tuple[Path, Path]:
        unknown_transaction = self.owned_root / f".knowledgeflow-init-{_UUIDS[0]}"
        unknown_transaction.mkdir()
        (unknown_transaction / "transaction.yaml").write_bytes(
            _dump_init_transaction(
                _InitTransaction(
                    transaction_id=_UUIDS[0],
                    request_sha256="sha256:" + ("0" * 64),
                )
            )
        )
        self.config_path.parent.mkdir(parents=False, exist_ok=False)
        unknown_temp = self.config_path.parent / (
            f".knowledgeflow-config-{_UUIDS[1]}.tmp"
        )
        unknown_temp.write_bytes(_UNKNOWN_TEMP_BYTES)
        return unknown_transaction, unknown_temp

    # --------------------------------------------------------------- children

    def _run_fault_child(self, fault_point: str) -> None:
        result_path = self.owned_root / "fault.result.json"
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                "init-store-fault",
                str(self.owned_root),
                str(self.config_path),
                str(self.capture_root),
                str(_INLINE_THRESHOLD),
                str(_MAXIMUM),
                fault_point,
                str(result_path),
            ],
            cwd=_REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(f"fault child never reached {fault_point}: {stderr!r}")
        if process.returncode != _FAULT_EXIT_CODE:
            details = (
                result_path.read_text(encoding="utf-8")
                if result_path.exists()
                else "<no result>"
            )
            self.fail(
                f"fault child must exit with {_FAULT_EXIT_CODE} at "
                f"{fault_point}, got {process.returncode}: "
                f"stdout={stdout!r}, stderr={stderr!r}, result={details}"
            )
        self.assertFalse(
            result_path.exists(),
            "crashed child must not leave a success or failure receipt",
        )

    def _run_recovery_child(self) -> dict[str, object]:
        started = self.owned_root / "recovery.started"
        gate = self.owned_root / "recovery.gate"
        result_path = self.owned_root / "recovery.result.json"
        gate.write_bytes(b"go")
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                "init-store",
                str(self.owned_root),
                str(self.config_path),
                str(self.capture_root),
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
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(f"recovery child did not finish: {stderr!r}")
        self.assertEqual(
            process.returncode,
            0,
            f"recovery child failed: stdout={stdout!r}, stderr={stderr!r}",
        )
        self.assertTrue(result_path.is_file())
        return json.loads(result_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------- assertions

    def _assert_complete_store(self, root: Path) -> CaptureStoreManifest:
        manifest_path = root / CAPTURE_STORE_MANIFEST_FILENAME
        self.assertTrue(manifest_path.is_file())
        manifest = load_capture_store_manifest(manifest_path.read_bytes())
        for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
            self.assertTrue(root.joinpath(*parts).is_dir(), parts)
        return manifest

    def _assert_no_business_artifacts(self, root: Path) -> None:
        files = tuple(path for path in root.rglob("*") if path.is_file())
        self.assertEqual(
            files,
            (root / CAPTURE_STORE_MANIFEST_FILENAME,),
        )
        for parts in _EMPTY_DIRECTORIES:
            self.assertEqual(tuple(root.joinpath(*parts).iterdir()), ())

    def _assert_common_recovery(
        self,
        result: dict[str, object],
        *,
        created: bool,
        expected_store_id: str | None,
    ) -> str:
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["store_initialized"], result)
        self.assertTrue(result["config_connected"], result)
        self.assertEqual(result["created"], created, result)
        self.assertNotIn("saved", result)
        self.assertNotIn("commit_state", result)
        store_id = result["store_id"]
        self.assertIsInstance(store_id, str)
        if expected_store_id is not None:
            self.assertEqual(store_id, expected_store_id)
        self.assertEqual(Path(str(result["capture_root"])), self.capture_root)
        manifest = self._assert_complete_store(self.capture_root)
        self.assertEqual(manifest.store_id, store_id)
        self._assert_no_business_artifacts(self.capture_root)
        config = parse_local_config(
            self.config_path.read_bytes(),
            path_policy=self.policy,
        )
        self.assertEqual(config.capture.root, self.capture_root)
        return store_id

    def _assert_unknown_fragments(
        self,
        unknown_transaction: Path,
        unknown_transaction_before: dict[str, tuple[str, bytes | None]],
        unknown_temp: Path,
    ) -> None:
        self.assertEqual(
            self._snapshot(unknown_transaction),
            unknown_transaction_before,
        )
        self.assertEqual(unknown_temp.read_bytes(), _UNKNOWN_TEMP_BYTES)

    def _assert_owned_marker(self, transaction_path: Path) -> None:
        marker = transaction_path / "transaction.yaml"
        transaction = _load_init_transaction(marker.read_bytes())
        self.assertEqual(
            transaction_path.name,
            f".knowledgeflow-init-{transaction.transaction_id}",
        )
        self.assertEqual(transaction.request_sha256, self._request_sha256())

    # ---------------------------------------------------------------- helpers

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

    def _config_temp_candidates(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in self.config_path.parent.iterdir()
            if path.name.startswith(".knowledgeflow-config-")
        )

    def _crashed_transaction(self, unknown_transaction: Path) -> Path:
        candidates = [
            path
            for path in self._transaction_candidates()
            if path != unknown_transaction
        ]
        self.assertEqual(len(candidates), 1, self._transaction_candidates())
        return candidates[0]

    def _local_config(self) -> LocalConfig:
        return create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )

    def _request_sha256(self) -> str:
        return _initialization_request_sha256(
            config_path=self.policy.validate_config_path(self.config_path),
            capture_root=self._local_config().capture.root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
        )

    def _canonical_config_bytes(self) -> bytes:
        return dump_local_config(self._local_config())

    def _production_snapshot(self) -> tuple[object, object]:
        return (
            _metadata_snapshot(_REAL_CONFIG_PATH),
            _metadata_snapshot(_REAL_CAPTURE_STORE),
        )

    # ---------------------------------------------------- internal capability

    def test_public_init_surface_has_no_injection_channel(self) -> None:
        parameters = inspect.signature(init_capture_store).parameters
        self.assertEqual(
            set(parameters),
            {
                "config_path",
                "capture_root",
                "inline_text_threshold_bytes",
                "max_text_version_bytes",
                "path_policy",
            },
        )
        self.assertTrue(
            all(
                parameter.kind is inspect.Parameter.KEYWORD_ONLY
                for parameter in parameters.values()
            )
        )
        private_parameters = inspect.signature(
            _init_capture_store_with_dependencies
        ).parameters
        self.assertEqual(
            set(private_parameters),
            {
                "config_path",
                "capture_root",
                "inline_text_threshold_bytes",
                "max_text_version_bytes",
                "path_policy",
                "dependencies",
            },
        )
        self.assertIsNone(_StoreDependencies().fault_point)

    def test_selected_fault_points_stay_noop_with_default_hook(self) -> None:
        for point in _InitFaultPoint:
            with self.subTest(point=point.value):
                sub_root = self.owned_root / point.value
                sub_root.mkdir()
                result = _init_capture_store_with_dependencies(
                    config_path=sub_root / "config" / "config.yaml",
                    capture_root=sub_root / "capture-store",
                    inline_text_threshold_bytes=_INLINE_THRESHOLD,
                    max_text_version_bytes=_MAXIMUM,
                    path_policy=self.policy,
                    dependencies=_StoreDependencies(fault_point=point),
                )
                self.assertIsInstance(result, InitStoreResult)
                self.assertTrue(result.created)
                self._assert_complete_store(sub_root / "capture-store")

    # -------------------------------------------------------------- FI tests

    def test_fi_01_crash_after_init_temp_created_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("after_init_temp_created")

        self.assertFalse(self.capture_root.exists())
        self.assertFalse(self.config_path.exists())
        crashed = self._crashed_transaction(unknown_transaction)
        self._assert_owned_marker(crashed)
        self.assertTrue((crashed / "store").is_dir())
        self.assertEqual(tuple((crashed / "store").iterdir()), ())

        result = self._run_recovery_child()
        self._assert_common_recovery(result, created=True, expected_store_id=None)
        self.assertFalse(crashed.exists())
        self.assertEqual(self._transaction_candidates(), (unknown_transaction,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)

    def test_fi_02_crash_after_manifest_written_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("after_manifest_written")

        self.assertFalse(self.capture_root.exists())
        self.assertFalse(self.config_path.exists())
        crashed = self._crashed_transaction(unknown_transaction)
        self._assert_owned_marker(crashed)
        for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
            self.assertTrue((crashed / "store").joinpath(*parts).is_dir(), parts)

        result = self._run_recovery_child()
        self._assert_common_recovery(result, created=True, expected_store_id=None)
        self.assertFalse(crashed.exists())
        self.assertEqual(self._transaction_candidates(), (unknown_transaction,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)

    def test_fi_03_crash_after_manifest_flushed_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("after_manifest_flushed")

        self.assertFalse(self.capture_root.exists())
        self.assertFalse(self.config_path.exists())
        crashed = self._crashed_transaction(unknown_transaction)
        self._assert_owned_marker(crashed)
        staged_manifest = self._assert_complete_store(crashed / "store")

        result = self._run_recovery_child()
        store_id = self._assert_common_recovery(
            result,
            created=True,
            expected_store_id=None,
        )
        self.assertNotEqual(store_id, staged_manifest.store_id)
        self.assertFalse(crashed.exists())
        self.assertEqual(self._transaction_candidates(), (unknown_transaction,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)

    def test_fi_04_crash_after_root_renamed_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("after_root_renamed")

        manifest = self._assert_complete_store(self.capture_root)
        self.assertFalse(self.config_path.exists())
        crashed = self._crashed_transaction(unknown_transaction)
        self._assert_owned_marker(crashed)
        self.assertEqual(
            sorted(path.name for path in crashed.iterdir()),
            ["transaction.yaml"],
        )
        store_before = self._snapshot(self.capture_root)

        result = self._run_recovery_child()
        self._assert_common_recovery(
            result,
            created=False,
            expected_store_id=manifest.store_id,
        )
        self.assertEqual(self._snapshot(self.capture_root), store_before)
        self.assertFalse(crashed.exists())
        self.assertEqual(self._transaction_candidates(), (unknown_transaction,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)

    def test_fi_05_crash_before_config_replaced_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("before_config_replaced")

        manifest = self._assert_complete_store(self.capture_root)
        self.assertFalse(self.config_path.exists())
        self.assertEqual(self._transaction_candidates(), (unknown_transaction,))
        temps = self._config_temp_candidates()
        self.assertEqual(len(temps), 2)
        child_temp = next(path for path in temps if path != unknown_temp)
        self.assertEqual(child_temp.read_bytes(), self._canonical_config_bytes())
        store_before = self._snapshot(self.capture_root)

        result = self._run_recovery_child()
        self._assert_common_recovery(
            result,
            created=False,
            expected_store_id=manifest.store_id,
        )
        self.assertEqual(self._snapshot(self.capture_root), store_before)
        self.assertFalse(child_temp.exists())
        self.assertEqual(self._config_temp_candidates(), (unknown_temp,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)

    def test_fi_06_crash_after_config_replaced_recovers_in_new_process(self) -> None:
        production_before = self._production_snapshot()
        unknown_transaction, unknown_temp = self._seed_unknown_fragments()
        unknown_before = self._snapshot(unknown_transaction)
        self._run_fault_child("after_config_replaced")

        manifest = self._assert_complete_store(self.capture_root)
        canonical = self._canonical_config_bytes()
        self.assertTrue(self.config_path.is_file())
        self.assertEqual(self.config_path.read_bytes(), canonical)
        self.assertEqual(self._config_temp_candidates(), (unknown_temp,))
        store_before = self._snapshot(self.capture_root)

        result = self._run_recovery_child()
        self._assert_common_recovery(
            result,
            created=False,
            expected_store_id=manifest.store_id,
        )
        self.assertEqual(self.config_path.read_bytes(), canonical)
        self.assertEqual(self._snapshot(self.capture_root), store_before)
        self.assertEqual(self._config_temp_candidates(), (unknown_temp,))
        self._assert_unknown_fragments(unknown_transaction, unknown_before, unknown_temp)
        self.assertEqual(self._production_snapshot(), production_before)


if __name__ == "__main__":
    unittest.main()
