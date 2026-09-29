from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import venv

from knowledgeflow_capture.cli import _execute_operation, _run_cli
from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SUPPORT_SCRIPT = _REPOSITORY_ROOT / "tests" / "capture" / "_cli_support.py"
_ACCEPTANCE_SUPPORT_SCRIPT = (
    _REPOSITORY_ROOT / "tests" / "capture" / "_cli_acceptance_support.py"
)
_REQUEST_SCHEMA = "knowledgeflow.capture-cli-request"
_RESPONSE_SCHEMA = "knowledgeflow.capture-cli-response"
_INTERNAL_FAILURE_LINE = b"knowledgeflow-capture: internal failure\n"
_MIB = 1024 * 1024
_INLINE_THRESHOLD = 4 * _MIB
_MAXIMUM = 64 * _MIB
_CHUNK_SIZE = _MIB
_STABLE_CAPTURE_FIELDS = (
    "capture_id",
    "event_id",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)


class _FailingBinaryOutput:
    def __init__(
        self,
        *,
        fail_after_bytes: int | None = None,
        fail_flush: bool = False,
    ) -> None:
        self.value = bytearray()
        self._remaining = fail_after_bytes
        self._fail_flush = fail_flush

    def write(self, source: bytes, /) -> int:
        if self._remaining is None:
            self.value.extend(source)
            return len(source)
        if self._remaining <= 0:
            raise OSError("sensitive stdout failure")
        accepted = min(len(source), self._remaining)
        self.value.extend(source[:accepted])
        self._remaining -= accepted
        return accepted

    def flush(self) -> None:
        if self._fail_flush:
            raise OSError("sensitive stdout flush failure")


class CliAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C7V CLI acceptance is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        self._processes: list[subprocess.Popen[bytes]] = []
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
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    @staticmethod
    def _channel() -> dict[str, object]:
        return {
            "type": "app",
            "instance_id": "c7v-acceptance",
            "external_ref": "acceptance-42",
            "source_created_at": "2026-09-28T01:02:03.004Z",
        }

    @staticmethod
    def _encode_header(**business_fields: object) -> bytes:
        body_length = business_fields.pop("body_length_bytes", 0)
        header = {
            "schema": _REQUEST_SCHEMA,
            "schema_version": 1,
            "body_length_bytes": body_length,
            **business_fields,
        }
        return (
            json.dumps(
                header,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    def _frame(self, body: bytes = b"", **business_fields: object) -> bytes:
        return self._encode_header(
            body_length_bytes=len(body),
            **business_fields,
        ) + body

    def _command(self, operation: str) -> list[str]:
        return [
            sys.executable,
            str(_SUPPORT_SCRIPT),
            str(self.owned_root),
            operation,
            "--config",
            str(self.config_path),
        ]

    def _run_small(
        self,
        operation: str,
        frame: bytes,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            self._command(operation),
            input=frame,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )

    def _decode_bytes(
        self,
        completed: subprocess.CompletedProcess[bytes],
    ) -> tuple[dict[str, object], bytes]:
        header_source, separator, body = completed.stdout.partition(b"\n")
        self.assertEqual(separator, b"\n")
        header = json.loads(header_source.decode("utf-8"))
        self.assertEqual(header["schema"], _RESPONSE_SCHEMA)
        self.assertEqual(header["schema_version"], 1)
        self.assertEqual(len(body), header["body_length_bytes"])
        return header, body

    def _write_streaming_frame(
        self,
        path: Path,
        *,
        byte_size: int,
        fill: bytes,
        business_fields: dict[str, object],
    ) -> str:
        self.assertEqual(len(fill), 1)
        digest = hashlib.sha256()
        header = self._encode_header(
            body_length_bytes=byte_size,
            **business_fields,
        )
        remaining = byte_size
        with path.open("xb") as stream:
            stream.write(header)
            while remaining:
                chunk = fill * min(_CHUNK_SIZE, remaining)
                self.assertLessEqual(len(chunk), _CHUNK_SIZE)
                stream.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        return "sha256:" + digest.hexdigest()

    def _run_streaming(
        self,
        operation: str,
        input_path: Path,
        output_path: Path,
    ) -> subprocess.CompletedProcess[bytes]:
        with input_path.open("rb") as stdin, output_path.open("xb") as stdout:
            return subprocess.run(
                self._command(operation),
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                check=False,
                timeout=240,
            )

    def _read_streaming_response(
        self,
        path: Path,
    ) -> tuple[dict[str, object], int, str]:
        digest = hashlib.sha256()
        observed = 0
        with path.open("rb") as stream:
            header = json.loads(stream.readline().decode("utf-8"))
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                self.assertLessEqual(len(chunk), _CHUNK_SIZE)
                digest.update(chunk)
                observed += len(chunk)
        self.assertEqual(header["schema"], _RESPONSE_SCHEMA)
        self.assertEqual(header["schema_version"], 1)
        self.assertEqual(observed, header["body_length_bytes"])
        return header, observed, "sha256:" + digest.hexdigest()

    def _item_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                path
                for path in (self.capture_root / "items").glob("*/*/cap_*")
                if path.is_dir()
            )
        )

    def _store_snapshot(self) -> tuple[tuple[str, str, int], ...]:
        entries: list[tuple[str, str, int]] = []
        for path in sorted(self.capture_root.rglob("*")):
            relative = path.relative_to(self.capture_root).as_posix()
            if path.is_dir():
                entries.append((relative, "directory", 0))
            elif path.is_file():
                entries.append(
                    (
                        relative,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        path.stat().st_size,
                    )
                )
            else:
                entries.append((relative, "other", 0))
        return tuple(entries)

    def _wait_for_paths(self, paths: list[Path], message: str) -> None:
        deadline = time.monotonic() + 30.0
        while not all(path.exists() for path in paths):
            if time.monotonic() >= deadline:
                self.fail(message)
            time.sleep(0.01)

    def _capture_small(self, body: bytes, key: str) -> dict[str, object]:
        completed = self._run_small(
            "capture_text",
            self._frame(
                body,
                channel=self._channel(),
                idempotency_key=key,
                user_intent={"processing_mode": "capture-only"},
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        header, response_body = self._decode_bytes(completed)
        self.assertEqual(response_body, b"")
        return header

    def test_cli_10_real_trailing_byte_is_rejected_before_any_commit(self) -> None:
        body = b"valid body"
        frame = self._frame(
            body,
            channel=self._channel(),
            idempotency_key="c7v-trailing-byte",
        ) + b"\n"
        before = self._store_snapshot()

        completed = self._run_small("capture_text", frame)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, b"")
        header, response_body = self._decode_bytes(completed)
        self.assertEqual(header["error"]["code"], "invalid_input")
        self.assertEqual(header["commit_state"], "not-committed")
        self.assertEqual(response_body, b"")
        self.assertEqual(self._store_snapshot(), before)
        self.assertEqual(self._item_paths(), ())
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())

    def test_cli_20_real_4_mib_capture_and_64_mib_append_get(self) -> None:
        capture_input = self.owned_root / "capture-4m.frame"
        capture_output = self.owned_root / "capture-4m.response"
        capture_sha256 = self._write_streaming_frame(
            capture_input,
            byte_size=_INLINE_THRESHOLD,
            fill=b"c",
            business_fields={
                "channel": self._channel(),
                "idempotency_key": "c7v-real-4m",
                "user_intent": {"processing_mode": "capture-only"},
            },
        )
        captured = self._run_streaming(
            "capture_text",
            capture_input,
            capture_output,
        )
        self.assertEqual(captured.returncode, 0, captured.stderr)
        self.assertEqual(captured.stderr, b"")
        capture_header, capture_body_size, _ = self._read_streaming_response(
            capture_output
        )
        self.assertEqual(capture_body_size, 0)
        self.assertEqual(capture_header["primary_payload_sha256"], capture_sha256)
        capture_id = capture_header["capture_id"]
        self.assertIsInstance(capture_id, str)

        append_input = self.owned_root / "append-64m.frame"
        append_output = self.owned_root / "append-64m.response"
        append_sha256 = self._write_streaming_frame(
            append_input,
            byte_size=_MAXIMUM,
            fill=b"a",
            business_fields={
                "capture_id": capture_id,
                "expected_current_version": 1,
                "channel": self._channel(),
                "idempotency_key": "c7v-real-64m",
            },
        )
        appended = self._run_streaming(
            "append_capture_version",
            append_input,
            append_output,
        )
        self.assertEqual(appended.returncode, 0, appended.stderr)
        self.assertEqual(appended.stderr, b"")
        append_header, append_body_size, _ = self._read_streaming_response(
            append_output
        )
        self.assertEqual(append_body_size, 0)
        self.assertEqual(append_header["version"], 2)
        self.assertEqual(append_header["primary_payload_sha256"], append_sha256)

        for version, expected_size, expected_sha256 in (
            (1, _INLINE_THRESHOLD, capture_sha256),
            (2, _MAXIMUM, append_sha256),
        ):
            with self.subTest(version=version, byte_size=expected_size):
                get_input = self.owned_root / f"get-v{version}.frame"
                get_output = self.owned_root / f"get-v{version}.response"
                get_input.write_bytes(
                    self._encode_header(capture_id=capture_id, version=version)
                )
                read = self._run_streaming("get_capture", get_input, get_output)
                self.assertEqual(read.returncode, 0, read.stderr)
                self.assertEqual(read.stderr, b"")
                get_header, observed, observed_sha256 = (
                    self._read_streaming_response(get_output)
                )
                self.assertEqual(observed, expected_size)
                self.assertEqual(observed_sha256, expected_sha256)
                self.assertEqual(get_header["capture"]["byte_size"], expected_size)
                self.assertEqual(
                    get_header["capture"]["primary_payload_sha256"],
                    expected_sha256,
                )

    def test_cli_23_stdout_write_body_and_flush_failures_are_terminal(self) -> None:
        source = b"stdout-secret-body"
        captured = self._capture_small(source, "c7v-stdout-failure")
        capture_id = captured["capture_id"]
        self.assertIsInstance(capture_id, str)
        frame = self._frame(capture_id=capture_id)

        successful_stdout = io.BytesIO()
        successful_stderr = io.BytesIO()
        successful_exit = _run_cli(
            ["get_capture", "--config", str(self.config_path)],
            stdin=io.BytesIO(frame),
            stdout=successful_stdout,
            stderr=successful_stderr,
            path_policy=self.policy,
            executor=_execute_operation,
        )
        self.assertEqual(successful_exit, 0)
        header_length = successful_stdout.getvalue().index(b"\n") + 1

        cases = (
            ("header", _FailingBinaryOutput(fail_after_bytes=7)),
            (
                "body",
                _FailingBinaryOutput(fail_after_bytes=header_length + 3),
            ),
            ("flush", _FailingBinaryOutput(fail_flush=True)),
        )
        for label, stdout in cases:
            with self.subTest(label=label):
                stderr = io.BytesIO()
                exit_code = _run_cli(
                    ["get_capture", "--config", str(self.config_path)],
                    stdin=io.BytesIO(frame),
                    stdout=stdout,
                    stderr=stderr,
                    path_policy=self.policy,
                    executor=_execute_operation,
                )
                emitted = bytes(stdout.value)
                self.assertEqual(exit_code, 70)
                self.assertEqual(stderr.getvalue(), _INTERNAL_FAILURE_LINE)
                self.assertLessEqual(emitted.count(b'"schema"'), 1)
                self.assertNotIn(b"internal failure", emitted)
                self.assertNotIn(source, stderr.getvalue())
        self.assertTrue(bytes(cases[1][1].value).endswith(source[:3]))

    def test_cli_25_clean_temporary_install_discovers_console_script(self) -> None:
        source_root = self.owned_root / "install-source"
        source_root.mkdir()
        for filename in ("LICENSE", "README.md", "pyproject.toml"):
            shutil.copy2(_REPOSITORY_ROOT / filename, source_root / filename)
        shutil.copytree(
            _REPOSITORY_ROOT / "src",
            source_root / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        environment_root = self.owned_root / "clean-install"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(
            environment_root
        )
        python = environment_root / "Scripts" / "python.exe"
        entry = environment_root / "Scripts" / "knowledgeflow-capture.exe"
        self.assertFalse(entry.exists())
        build_temp = self.owned_root / "build-temp"
        pip_cache = self.owned_root / "pip-cache"
        build_temp.mkdir()
        pip_cache.mkdir()
        environment = dict(os.environ)
        environment.update(
            {
                "PIP_CACHE_DIR": str(pip_cache),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONNOUSERSITE": "1",
                "TEMP": str(build_temp),
                "TMP": str(build_temp),
                "KNOWLEDGEFLOW_TEST_OWNED_ROOT": str(self.owned_root),
            }
        )
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)

        installed = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "--no-compile",
                "--force-reinstall",
                str(source_root),
            ],
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=240,
        )
        install_error = installed.stderr.decode("utf-8", "replace")
        self.assertEqual(installed.returncode, 0, install_error)
        self.assertTrue(entry.is_file())

        imported = subprocess.run(
            [
                str(python),
                "-c",
                "import pathlib,knowledgeflow_capture; print(pathlib.Path(knowledgeflow_capture.__file__).resolve())",
            ],
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
            text=True,
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        imported_path = Path(imported.stdout.strip()).resolve()
        self.assertTrue(imported_path.is_relative_to(environment_root))
        self.assertFalse(imported_path.is_relative_to(_REPOSITORY_ROOT))

        missing_config = self.owned_root / "clean-entry-missing.yaml"
        completed = subprocess.run(
            [
                str(entry),
                "list_captures",
                "--config",
                str(missing_config),
            ],
            input=self._frame(),
            cwd=self.owned_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        header, body = self._decode_bytes(completed)
        self.assertEqual(header["error"]["code"], "config_not_found")
        self.assertEqual(body, b"")
        self.assertEqual(completed.stderr, b"")
        self.assertFalse(missing_config.exists())

    def test_cli_26_two_real_processes_same_key_converge(self) -> None:
        body = b"two real CLI processes"
        frame = self._frame(
            body,
            channel=self._channel(),
            idempotency_key="c7v-two-process-same-key",
        )
        frame_path = self.owned_root / "race.frame"
        frame_path.write_bytes(frame)
        gate_path = self.owned_root / "race.gate"
        ready_paths = [self.owned_root / f"race-ready-{index}" for index in range(2)]
        for ready_path in ready_paths:
            input_stream = frame_path.open("rb")
            self.addCleanup(input_stream.close)
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(_ACCEPTANCE_SUPPORT_SCRIPT),
                    str(self.owned_root),
                    str(ready_path),
                    str(gate_path),
                    "capture_text",
                    "--config",
                    str(self.config_path),
                ],
                stdin=input_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._processes.append(process)

        self._wait_for_paths(
            ready_paths,
            "CLI subprocesses did not reach the executor barrier",
        )
        self.assertTrue(all(process.poll() is None for process in self._processes))
        self.assertEqual(self._item_paths(), ())
        gate_path.write_bytes(b"go")

        responses: list[dict[str, object]] = []
        for process in self._processes:
            stdout, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stderr, b"")
            completed = subprocess.CompletedProcess(
                args=process.args,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
            header, response_body = self._decode_bytes(completed)
            self.assertEqual(response_body, b"")
            responses.append(header)
        for field in _STABLE_CAPTURE_FIELDS:
            self.assertEqual(responses[0][field], responses[1][field])
        self.assertEqual(len(self._item_paths()), 1)
        self.assertEqual(tuple((self.capture_root / ".staging").iterdir()), ())


if __name__ == "__main__":
    unittest.main()
