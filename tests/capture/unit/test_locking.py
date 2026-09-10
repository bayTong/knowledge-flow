from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from knowledgeflow_capture.errors import PublicErrorCode
from knowledgeflow_capture.locking import (
    CaptureWriteLockError,
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    InitializationLockError,
    _acquire_capture_write_lock,
    _acquire_initialization_lock,
    _capture_write_lock_path,
    acquire_initialization_lock,
    initialization_lock_path,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class InitializationLockTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C2B-1 lock contract is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
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

    def _start_holder(
        self,
        config_path: Path,
        label: str,
    ) -> tuple[subprocess.Popen[str], Path, Path, Path]:
        started = self.root / f"{label}.started"
        acquired = self.root / f"{label}.acquired"
        release = self.root / f"{label}.release"
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                "hold-lock",
                str(config_path),
                str(started),
                str(acquired),
                str(release),
            ],
            cwd=_REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        return process, started, acquired, release

    def _start_capture_holder(
        self,
        capture_root: Path,
        label: str,
    ) -> tuple[subprocess.Popen[str], Path, Path, Path]:
        started = self.root / f"{label}.started"
        acquired = self.root / f"{label}.acquired"
        release = self.root / f"{label}.release"
        process = subprocess.Popen(
            [
                sys.executable,
                str(_SUPPORT_SCRIPT),
                "hold-capture-lock",
                str(capture_root),
                str(started),
                str(acquired),
                str(release),
            ],
            cwd=_REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes.append(process)
        return process, started, acquired, release

    def _capture_root(self, name: str) -> Path:
        capture_root = self.root / name
        capture_root.mkdir()
        (capture_root / "journal").mkdir()
        return capture_root

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
                    f"lock helper exited early with {process.returncode}: "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            time.sleep(0.01)
        self.fail("timed out waiting for lock helper marker")

    def _release_holder(
        self,
        process: subprocess.Popen[str],
        release: Path,
    ) -> None:
        release.write_bytes(b"release")
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(
            process.returncode,
            0,
            f"stdout={stdout!r}, stderr={stderr!r}",
        )

    def test_lock_01_same_resolved_config_path_is_mutually_exclusive(self) -> None:
        config_path = self.root / "config.yaml"
        first, _, first_acquired, first_release = self._start_holder(
            config_path,
            "first",
        )
        self._wait_for_marker(first_acquired, first)

        second, second_started, second_acquired, second_release = self._start_holder(
            config_path,
            "second",
        )
        self._wait_for_marker(second_started, second)
        time.sleep(0.1)
        self.assertFalse(second_acquired.exists())

        self._release_holder(first, first_release)
        self._wait_for_marker(second_acquired, second)
        self._release_holder(second, second_release)

    def test_lock_02_different_config_paths_do_not_share_a_global_lock(self) -> None:
        first, _, first_acquired, first_release = self._start_holder(
            self.root / "first-config.yaml",
            "first",
        )
        self._wait_for_marker(first_acquired, first)
        second, _, second_acquired, second_release = self._start_holder(
            self.root / "second-config.yaml",
            "second",
        )
        self._wait_for_marker(second_acquired, second)

        self._release_holder(second, second_release)
        self._release_holder(first, first_release)

    def test_lock_03_process_termination_releases_kernel_lock_not_file(self) -> None:
        config_path = self.root / "config.yaml"
        process, _, acquired, _ = self._start_holder(config_path, "holder")
        self._wait_for_marker(acquired, process)
        lock_path = initialization_lock_path(config_path)
        self.assertTrue(lock_path.is_file())

        process.terminate()
        process.communicate(timeout=5)
        self.assertTrue(lock_path.is_file())
        with acquire_initialization_lock(config_path) as lock:
            self.assertTrue(lock.is_held)
            self.assertEqual(lock.lock_path, lock_path)

    def test_lock_04_timeout_uses_internal_clock_and_is_retryable(self) -> None:
        self.assertEqual(DEFAULT_LOCK_TIMEOUT_SECONDS, 10.0)
        config_path = self.root / "config.yaml"
        process, _, acquired, release = self._start_holder(config_path, "holder")
        self._wait_for_marker(acquired, process)
        fake_time = _FakeTime()

        with self.assertRaises(InitializationLockError) as raised:
            _acquire_initialization_lock(
                config_path,
                timeout_seconds=0.2,
                poll_interval_seconds=0.05,
                _clock=fake_time.monotonic,
                _sleeper=fake_time.sleep,
            )

        self.assertEqual(raised.exception.code, PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(
            raised.exception.to_operation_error().to_dict(),
            {
                "code": "capture_store_unavailable",
                "cause_code": None,
                "message": "capture store is unavailable",
                "retryable": True,
                "details": {},
            },
        )
        self._release_holder(process, release)

    def test_non_regular_lock_file_is_rejected_without_deletion(self) -> None:
        config_path = self.root / "config.yaml"
        lock_path = Path(f"{config_path}.init.lock")
        lock_path.mkdir()

        with self.assertRaises(InitializationLockError) as raised:
            acquire_initialization_lock(config_path)

        self.assertFalse(raised.exception.retryable)
        self.assertTrue(lock_path.is_dir())

    def test_ct_18_capture_write_lock_reuses_kernel_wait_and_fixed_path(self) -> None:
        capture_root = self._capture_root("capture-store")
        expected_path = capture_root / "journal" / "capture-write.lock"
        self.assertEqual(_capture_write_lock_path(capture_root), expected_path)

        holder, _, acquired, release = self._start_capture_holder(
            capture_root,
            "capture-holder",
        )
        self._wait_for_marker(acquired, holder)
        fake_time = _FakeTime()

        with self.assertRaises(CaptureWriteLockError) as raised:
            _acquire_capture_write_lock(
                capture_root,
                timeout_seconds=0.2,
                poll_interval_seconds=0.05,
                _clock=fake_time.monotonic,
                _sleeper=fake_time.sleep,
            )

        self.assertEqual(raised.exception.code, PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(
            raised.exception.to_operation_error().to_dict(),
            {
                "code": "capture_store_unavailable",
                "cause_code": None,
                "message": "capture store is unavailable",
                "retryable": True,
                "details": {},
            },
        )
        self._release_holder(holder, release)

    def test_capture_write_lock_domains_are_per_store_not_global(self) -> None:
        first_root = self._capture_root("first-store")
        second_root = self._capture_root("second-store")
        first, _, first_acquired, first_release = self._start_capture_holder(
            first_root,
            "first-capture",
        )
        self._wait_for_marker(first_acquired, first)
        second, _, second_acquired, second_release = self._start_capture_holder(
            second_root,
            "second-capture",
        )
        self._wait_for_marker(second_acquired, second)

        self._release_holder(second, second_release)
        self._release_holder(first, first_release)

    def test_capture_write_lock_file_persists_after_process_termination(self) -> None:
        capture_root = self._capture_root("crash-store")
        process, _, acquired, _ = self._start_capture_holder(
            capture_root,
            "crash-holder",
        )
        self._wait_for_marker(acquired, process)
        lock_path = _capture_write_lock_path(capture_root)

        process.terminate()
        process.communicate(timeout=5)

        self.assertTrue(lock_path.is_file())
        with _acquire_capture_write_lock(capture_root) as lock:
            self.assertTrue(lock.is_held)
            self.assertEqual(lock.capture_root, capture_root)
            self.assertEqual(lock.lock_path, lock_path)

    def test_capture_write_lock_rejects_missing_or_nonregular_journal(self) -> None:
        missing_journal = self.root / "missing-journal"
        missing_journal.mkdir()
        with self.assertRaises(CaptureWriteLockError):
            _acquire_capture_write_lock(missing_journal)

        nonregular_root = self.root / "nonregular-lock"
        nonregular_root.mkdir()
        (nonregular_root / "journal").mkdir()
        lock_path = nonregular_root / "journal" / "capture-write.lock"
        lock_path.mkdir()
        with self.assertRaises(CaptureWriteLockError) as raised:
            _acquire_capture_write_lock(nonregular_root)
        self.assertFalse(raised.exception.retryable)
        self.assertTrue(lock_path.is_dir())


if __name__ == "__main__":
    unittest.main()
