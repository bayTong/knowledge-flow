from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from knowledgeflow_capture.codec import load_envelope
from knowledgeflow_capture.config import create_local_config, dump_local_config
from knowledgeflow_capture.errors import (
    CommitState,
    CommittedWriteResult,
    FailureResult,
    PublicErrorCode,
)
from knowledgeflow_capture.hashing import DEFAULT_CHUNK_SIZE, hash_stream
from knowledgeflow_capture.locking import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    _acquire_capture_write_lock,
)
from knowledgeflow_capture.models import CaptureTextRequest, ChannelMetadata
from knowledgeflow_capture.operations import capture_text
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_MIB = 1024 * 1024
_INLINE_THRESHOLD = 4 * _MIB
_MAXIMUM = 64 * _MIB
_STABLE_RECEIPT_FIELDS = (
    "capture_id",
    "event_id",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)


class _GeneratedNonSeekableStream:
    """Generate a fixed-size UTF-8 stream while recording every bounded read."""

    def __init__(self, byte_size: int) -> None:
        self._remaining = byte_size
        self.total_bytes_returned = 0
        self.data_reads = 0
        self.eof_reads = 0
        self.read_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        if size < 0:
            raise AssertionError("capture_text issued an unbounded read")
        if size == 0:
            raise AssertionError("capture_text issued a zero-byte read")
        self.read_sizes.append(size)
        if self._remaining == 0:
            self.eof_reads += 1
            return b""
        returned = min(size, self._remaining)
        self._remaining -= returned
        self.total_bytes_returned += returned
        self.data_reads += 1
        return b"x" * returned


class CaptureTextAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C3V capture acceptance is Windows-first")
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
    ) -> CaptureTextRequest:
        return CaptureTextRequest(
            text=text,
            channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            idempotency_key=key,
        )

    def _capture(
        self,
        request: CaptureTextRequest,
    ) -> CommittedWriteResult | FailureResult:
        return capture_text(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
        )

    def _item_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                path
                for path in (self.capture_root / "items").glob("*/*/cap_*")
                if path.is_dir()
            )
        )

    def _assert_success(
        self,
        result: CommittedWriteResult | FailureResult,
    ) -> CommittedWriteResult:
        self.assertIsInstance(result, CommittedWriteResult)
        success = result
        self.assertEqual(success.to_dict()["commit_state"], CommitState.COMMITTED.value)
        return success

    def _assert_failure(
        self,
        result: CommittedWriteResult | FailureResult,
        code: PublicErrorCode,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        self.assertEqual(failure.commit_state, CommitState.NOT_COMMITTED)
        return failure

    def _assert_single_pass_source(
        self,
        source: _GeneratedNonSeekableStream,
        *,
        expected_bytes: int,
        expected_eof_reads: int,
    ) -> None:
        self.assertEqual(source.total_bytes_returned, expected_bytes)
        expected_data_reads = (
            expected_bytes + DEFAULT_CHUNK_SIZE - 1
        ) // DEFAULT_CHUNK_SIZE
        self.assertEqual(source.data_reads, expected_data_reads)
        self.assertEqual(source.eof_reads, expected_eof_reads)
        self.assertTrue(source.read_sizes)
        self.assertLessEqual(max(source.read_sizes), DEFAULT_CHUNK_SIZE)

    def _assert_payload(
        self,
        result: CommittedWriteResult,
        *,
        expected_bytes: int,
    ) -> None:
        receipt = result.to_dict()
        matches = tuple(
            self.capture_root.glob(f"items/*/*/{receipt['capture_id']}")
        )
        self.assertEqual(len(matches), 1)
        version = matches[0] / "versions" / "000001"
        payload_path = version / "payloads" / "primary.txt"
        self.assertEqual(payload_path.stat().st_size, expected_bytes)
        with payload_path.open("rb") as stream:
            digest = hash_stream(stream)
        self.assertEqual(digest.byte_size, expected_bytes)
        self.assertEqual(digest.sha256, receipt["primary_payload_sha256"])
        envelope = load_envelope((version / "envelope.yaml").read_bytes())
        self.assertEqual(envelope["payloads"][0]["byte_size"], expected_bytes)
        self.assertEqual(
            envelope["payloads"][0]["sha256"],
            receipt["primary_payload_sha256"],
        )

    def _wait_for_paths(self, paths: list[Path], message: str) -> None:
        deadline = time.monotonic() + 30.0
        while not all(path.exists() for path in paths):
            if time.monotonic() >= deadline:
                self.fail(message)
            time.sleep(0.01)

    def test_ct_05_06_real_4_mib_boundary_uses_one_bounded_input_pass(self) -> None:
        cases = (("CT-05", _INLINE_THRESHOLD), ("CT-06", _INLINE_THRESHOLD + 1))
        for case_id, byte_size in cases:
            with self.subTest(case_id=case_id, byte_size=byte_size):
                source = _GeneratedNonSeekableStream(byte_size)
                success = self._assert_success(self._capture(self._request(source)))
                self._assert_single_pass_source(
                    source,
                    expected_bytes=byte_size,
                    expected_eof_reads=1,
                )
                self._assert_payload(success, expected_bytes=byte_size)
        self.assertEqual(len(self._item_paths()), 2)

    def test_ct_07_08_09_real_64_mib_limit_and_raised_retry(self) -> None:
        exact_source = _GeneratedNonSeekableStream(_MAXIMUM)
        exact = self._assert_success(self._capture(self._request(exact_source)))
        self._assert_single_pass_source(
            exact_source,
            expected_bytes=_MAXIMUM,
            expected_eof_reads=1,
        )
        self._assert_payload(exact, expected_bytes=_MAXIMUM)

        before_oversize = self._item_paths()
        oversize_source = _GeneratedNonSeekableStream(_MAXIMUM + 1)
        oversize = self._assert_failure(
            self._capture(self._request(oversize_source, key="raised-real-limit")),
            PublicErrorCode.TEXT_TOO_LARGE,
        )
        self.assertFalse(oversize.error.retryable)
        self._assert_single_pass_source(
            oversize_source,
            expected_bytes=_MAXIMUM + 1,
            expected_eof_reads=0,
        )
        self.assertEqual(self._item_paths(), before_oversize)
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

        raised = create_local_config(
            root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM + 1,
            path_policy=self.policy,
        )
        self.config_path.write_bytes(dump_local_config(raised))
        retry_source = _GeneratedNonSeekableStream(_MAXIMUM + 1)
        retried = self._assert_success(
            self._capture(self._request(retry_source, key="raised-real-limit"))
        )
        self._assert_single_pass_source(
            retry_source,
            expected_bytes=_MAXIMUM + 1,
            expected_eof_reads=1,
        )
        self._assert_payload(retried, expected_bytes=_MAXIMUM + 1)
        self.assertEqual(len(self._item_paths()), 2)

    def test_ct_17_processes_race_from_the_lock_boundary(self) -> None:
        gate = self.owned_root / "capture-lock.gate"
        ready_paths = [self.owned_root / f"lock-ready-{index}" for index in range(2)]
        result_paths = [self.owned_root / f"result-{index}.json" for index in range(2)]
        for index in range(2):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(_SUPPORT_SCRIPT),
                    "capture-text-lock-barrier",
                    str(self.owned_root),
                    str(self.config_path),
                    "lock-boundary body",
                    "lock-boundary-key",
                    str(ready_paths[index]),
                    str(gate),
                    str(result_paths[index]),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._processes.append(process)

        self._wait_for_paths(
            ready_paths,
            "capture subprocesses did not reach the lock boundary",
        )
        staging = tuple((self.capture_root / ".staging").iterdir())
        self.assertEqual(len(staging), 2)
        self.assertEqual(self._item_paths(), ())
        self.assertTrue(all(process.poll() is None for process in self._processes))

        gate.write_bytes(b"go")
        outputs: list[dict[str, object]] = []
        for process, result_path in zip(self._processes, result_paths, strict=True):
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
            outputs.append(json.loads(result_path.read_text(encoding="utf-8")))
        self.assertTrue(all(result["ok"] for result in outputs))
        for field in _STABLE_RECEIPT_FIELDS:
            self.assertEqual(outputs[0][field], outputs[1][field])
        self.assertEqual(len(self._item_paths()), 1)
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_ct_18_default_lock_wait_expires_after_ten_seconds(self) -> None:
        started = time.monotonic()
        with _acquire_capture_write_lock(self.capture_root):
            failure = self._assert_failure(
                self._capture(self._request("default lock timeout")),
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            )
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, DEFAULT_LOCK_TIMEOUT_SECONDS)
        self.assertTrue(failure.error.retryable)
        self.assertEqual(self._item_paths(), ())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())


if __name__ == "__main__":
    unittest.main()
