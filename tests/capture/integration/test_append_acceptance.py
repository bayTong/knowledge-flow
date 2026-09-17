from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from knowledgeflow_capture import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
    append_capture_version,
    capture_text,
    get_capture,
    list_captures,
)
from knowledgeflow_capture.codec import load_envelope
from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
)
from knowledgeflow_capture.hashing import DEFAULT_CHUNK_SIZE, hash_stream
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_support.py"
_MIB = 1024 * 1024
_INLINE_THRESHOLD = 4 * _MIB
_MAXIMUM = 64 * _MIB
_STABLE_APPEND_FIELDS = (
    "capture_id",
    "event_id",
    "previous_version",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
    "durability",
    "routing_status",
    "trust_status",
    "gbrain_sync_status",
)


class _GeneratedUtf8Stream:
    """Generate one exact ASCII UTF-8 body while proving bounded reads."""

    def __init__(self, byte_size: int, fill: bytes) -> None:
        if len(fill) != 1 or not fill.isascii():
            raise ValueError("fill must be one ASCII byte")
        self._remaining = byte_size
        self._fill = fill
        self.total_bytes_returned = 0
        self.maximum_read = 0
        self.eof_reads = 0

    def read(self, size: int = -1, /) -> bytes:
        if size <= 0:
            raise AssertionError("C5V source received an unbounded read")
        self.maximum_read = max(self.maximum_read, size)
        if self._remaining == 0:
            self.eof_reads += 1
            return b""
        returned = min(size, self._remaining)
        self._remaining -= returned
        self.total_bytes_returned += returned
        return self._fill * returned


class _DigestSink:
    """Consume a public read without retaining the large body in memory."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.byte_size = 0
        self.maximum_write = 0
        self.close_calls = 0
        self.flush_calls = 0

    def write(self, value: bytes) -> int:
        if type(value) is not bytes:
            raise AssertionError("C5V sink must receive bytes")
        self._digest.update(value)
        self.byte_size += len(value)
        self.maximum_write = max(self.maximum_write, len(value))
        return len(value)

    def close(self) -> None:
        self.close_calls += 1

    def flush(self) -> None:
        self.flush_calls += 1

    @property
    def sha256(self) -> str:
        return "sha256:" + self._digest.hexdigest()


class AppendAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C5V append acceptance is Windows-first")
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

    @staticmethod
    def _channel() -> ChannelMetadata:
        return ChannelMetadata(type="app", instance_id="c5v-acceptance")

    def _create_base(self, label: str) -> tuple[str, Path, bytes]:
        body = f"original version {label}".encode("utf-8")
        created = capture_text(
            CaptureTextRequest(
                text=body.decode("utf-8"),
                channel=self._channel(),
                idempotency_key=f"c5v-create-{label}",
                user_intent=UserIntent(
                    target_kb_id="kb_original",
                    processing_mode="deep-curation",
                    requested_new_kb_name="Original",
                ),
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(created, CommittedWriteResult)
        capture_id = str(created.receipt["capture_id"])
        matches = tuple(self.capture_root.glob(f"items/*/*/{capture_id}"))
        self.assertEqual(len(matches), 1)
        return capture_id, matches[0], body

    def _wait_for_paths(self, paths: list[Path], message: str) -> None:
        deadline = time.monotonic() + 30.0
        while not all(path.exists() for path in paths):
            if time.monotonic() >= deadline:
                self.fail(message)
            time.sleep(0.01)

    def _race_append(
        self,
        *,
        capture_id: str,
        bodies: tuple[str, str],
        keys: tuple[str, str],
    ) -> tuple[dict[str, object], dict[str, object]]:
        gate = self.owned_root / "append-lock.gate"
        ready_paths = [self.owned_root / f"append-ready-{index}" for index in range(2)]
        result_paths = [self.owned_root / f"append-result-{index}.json" for index in range(2)]
        for index in range(2):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(_SUPPORT_SCRIPT),
                    "append-capture-version-lock-barrier",
                    str(self.owned_root),
                    str(self.config_path),
                    capture_id,
                    "1",
                    bodies[index],
                    keys[index],
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
            "append subprocesses did not reach the Store lock boundary",
        )
        staging = tuple((self.capture_root / ".staging").iterdir())
        self.assertEqual(len(staging), 2)
        self.assertTrue(all(process.poll() is None for process in self._processes))

        gate.write_bytes(b"go")
        outputs: list[dict[str, object]] = []
        for process, result_path in zip(self._processes, result_paths, strict=True):
            stdout, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
            outputs.append(json.loads(result_path.read_text(encoding="utf-8")))
        return outputs[0], outputs[1]

    @staticmethod
    def _version_names(item_path: Path) -> tuple[str, ...]:
        return tuple(
            sorted(path.name for path in (item_path / "versions").iterdir() if path.is_dir())
        )

    def _latest_body(self, capture_id: str) -> bytes:
        sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(capture_id=capture_id, body_sink=sink),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(read, GetCaptureResult)
        return sink.getvalue()

    def test_app_06_two_processes_with_different_keys_allow_one_version(self) -> None:
        capture_id, item_path, original_body = self._create_base("different-keys")
        original_payload = item_path / "versions" / "000001" / "payloads" / "primary.txt"
        bodies = ("candidate alpha", "candidate beta")
        outputs = self._race_append(
            capture_id=capture_id,
            bodies=bodies,
            keys=("c5v-different-a", "c5v-different-b"),
        )

        winner_indexes = [index for index, result in enumerate(outputs) if result["ok"]]
        loser_indexes = [index for index, result in enumerate(outputs) if not result["ok"]]
        self.assertEqual(len(winner_indexes), 1)
        self.assertEqual(len(loser_indexes), 1)
        winner = outputs[winner_indexes[0]]
        loser = outputs[loser_indexes[0]]
        self.assertEqual(winner["commit_state"], "committed")
        self.assertEqual(winner["previous_version"], 1)
        self.assertEqual(winner["version"], 2)
        self.assertEqual(loser["commit_state"], "not-committed")
        self.assertEqual(loser["error"]["code"], "version_conflict")
        self.assertEqual(
            loser["error"]["details"],
            {"current_version": 2, "expected_current_version": 1},
        )
        self.assertEqual(self._version_names(item_path), ("000001", "000002"))
        self.assertEqual(len(tuple((item_path / "events").glob("*.yaml"))), 2)
        self.assertEqual(self._latest_body(capture_id), bodies[winner_indexes[0]].encode())
        self.assertEqual(original_payload.read_bytes(), original_body)
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_app_07_two_processes_with_same_key_return_one_stable_fact(self) -> None:
        capture_id, item_path, _original_body = self._create_base("same-key")
        body = "same request body"
        outputs = self._race_append(
            capture_id=capture_id,
            bodies=(body, body),
            keys=("c5v-shared-key", "c5v-shared-key"),
        )

        self.assertTrue(all(result["ok"] for result in outputs))
        for result in outputs:
            self.assertEqual(result["commit_state"], "committed")
            self.assertEqual(result["previous_version"], 1)
            self.assertEqual(result["version"], 2)
            self.assertEqual(result["warnings"], [])
        for field in _STABLE_APPEND_FIELDS:
            self.assertEqual(outputs[0][field], outputs[1][field])
        self.assertEqual(self._version_names(item_path), ("000001", "000002"))
        self.assertEqual(len(tuple((item_path / "events").glob("*.yaml"))), 2)
        self.assertEqual(self._latest_body(capture_id), body.encode())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_app_24_real_4_and_64_mib_append_list_get_round_trip(self) -> None:
        accepted: dict[str, tuple[int, bytes, bytes, dict[str, object], Path]] = {}
        for label, byte_size, fill in (
            ("4-mib", _INLINE_THRESHOLD, b"a"),
            ("64-mib", _MAXIMUM, b"z"),
        ):
            with self.subTest(label=label):
                capture_id, item_path, original_body = self._create_base(label)
                version_1 = item_path / "versions" / "000001"
                original_files = {
                    "payload": (version_1 / "payloads" / "primary.txt").read_bytes(),
                    "envelope": (version_1 / "envelope.yaml").read_bytes(),
                    "events": tuple(
                        (path.name, path.read_bytes())
                        for path in sorted((item_path / "events").glob("*.yaml"))
                    ),
                }
                source = _GeneratedUtf8Stream(byte_size, fill)
                appended = append_capture_version(
                    AppendCaptureVersionRequest(
                        capture_id=capture_id,
                        expected_current_version=1,
                        text=source,
                        channel=self._channel(),
                        idempotency_key=f"c5v-append-{label}",
                    ),
                    config_path=self.config_path,
                    path_policy=self.policy,
                )
                self.assertIsInstance(appended, AppendCaptureVersionResult)
                receipt = appended.to_dict()
                self.assertEqual(receipt["previous_version"], 1)
                self.assertEqual(receipt["version"], 2)
                self.assertEqual(receipt["warnings"], [])
                self.assertEqual(source.total_bytes_returned, byte_size)
                self.assertEqual(source.eof_reads, 1)
                self.assertLessEqual(source.maximum_read, DEFAULT_CHUNK_SIZE)

                version_2 = item_path / "versions" / "000002"
                payload_2 = version_2 / "payloads" / "primary.txt"
                self.assertEqual(payload_2.stat().st_size, byte_size)
                with payload_2.open("rb") as stream:
                    digest = hash_stream(stream)
                self.assertEqual(digest.byte_size, byte_size)
                self.assertEqual(digest.sha256, receipt["primary_payload_sha256"])
                envelope_2 = load_envelope((version_2 / "envelope.yaml").read_bytes())
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
                    (version_1 / "payloads" / "primary.txt").read_bytes(),
                    original_files["payload"],
                )
                self.assertEqual(
                    (version_1 / "envelope.yaml").read_bytes(),
                    original_files["envelope"],
                )
                for event_name, event_bytes in original_files["events"]:
                    self.assertEqual(
                        (item_path / "events" / event_name).read_bytes(),
                        event_bytes,
                    )
                accepted[capture_id] = (
                    byte_size,
                    fill,
                    original_body,
                    receipt,
                    item_path,
                )

        listed = list_captures(
            ListCapturesRequest(limit=10),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(listed, ListCapturesResult)
        self.assertEqual({item.capture_id for item in listed.items}, set(accepted))
        self.assertEqual(listed.warnings, ())
        for item in listed.items:
            byte_size, fill, original_body, receipt, item_path = accepted[item.capture_id]
            self.assertEqual(item.current_version, 2)
            self.assertEqual(item.preview, fill.decode("ascii") * 160)
            self.assertEqual(item.envelope_sha256, receipt["envelope_sha256"])

            old_sink = io.BytesIO()
            old_read = get_capture(
                GetCaptureRequest(
                    capture_id=item.capture_id,
                    version=1,
                    body_sink=old_sink,
                ),
                config_path=self.config_path,
                path_policy=self.policy,
            )
            self.assertIsInstance(old_read, GetCaptureResult)
            self.assertEqual(old_sink.getvalue(), original_body)

            sink = _DigestSink()
            current = get_capture(
                GetCaptureRequest(capture_id=item.capture_id, body_sink=sink),
                config_path=self.config_path,
                path_policy=self.policy,
            )
            self.assertIsInstance(current, GetCaptureResult)
            self.assertEqual(current.capture.version, 2)
            self.assertEqual(current.body_length_bytes, byte_size)
            self.assertEqual(current.capture.byte_size, byte_size)
            self.assertEqual(
                current.capture.primary_payload_sha256,
                receipt["primary_payload_sha256"],
            )
            self.assertEqual(sink.byte_size, byte_size)
            self.assertEqual(sink.sha256, receipt["primary_payload_sha256"])
            self.assertLessEqual(sink.maximum_write, DEFAULT_CHUNK_SIZE)
            self.assertEqual(sink.close_calls, 0)
            self.assertEqual(sink.flush_calls, 0)
            self.assertEqual(self._version_names(item_path), ("000001", "000002"))


if __name__ == "__main__":
    unittest.main()
