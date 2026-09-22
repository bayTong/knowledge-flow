from __future__ import annotations

import io
import json
from pathlib import Path
import unittest

from knowledgeflow_capture import cli as cli_module
from knowledgeflow_capture.cli import _CliDependencies, _run_cli
from knowledgeflow_capture.config import CaptureConfig, ConfigLoadError, LocalConfig
from knowledgeflow_capture.errors import (
    CommitState,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    OperationError,
    PublicErrorCode,
)
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureItemState,
    CaptureTextRequest,
    ChannelMetadata,
    CaptureReadMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
)
from knowledgeflow_capture.paths import PathPolicy

from .._samples import (
    CAPTURE_ID,
    EVENT_ID,
    PAYLOAD_BYTES,
    PAYLOAD_SHA256,
    SINGLE_PAYLOAD_SET_SHA256,
)


OWNED_ROOT = Path(r"C:\KnowledgeFlowTests\cli-owned")
CONFIG_PATH = OWNED_ROOT / "config.yaml"
CAPTURE_ROOT = OWNED_ROOT / "capture-store"
ENVELOPE_SHA256 = "sha256:" + ("a" * 64)
REQUEST_SCHEMA = "knowledgeflow.capture-cli-request"
RESPONSE_SCHEMA = "knowledgeflow.capture-cli-response"
CHUNK_SIZE = 1024 * 1024


def _identity(path: Path) -> Path:
    return path


def _capture_receipt() -> dict[str, object]:
    return {
        "capture_id": CAPTURE_ID,
        "event_id": EVENT_ID,
        "version": 1,
        "primary_payload_sha256": PAYLOAD_SHA256,
        "payload_set_sha256": SINGLE_PAYLOAD_SET_SHA256,
        "envelope_sha256": ENVELOPE_SHA256,
        "durability": "durable",
        "routing_status": "unassigned",
        "trust_status": "unreviewed-capture",
        "gbrain_sync_status": "not-requested",
    }


def _public_failure(operation: str) -> FailureResult:
    return FailureResult(
        error=OperationError(
            code=PublicErrorCode.CONFIG_NOT_FOUND,
            retryable=False,
        ),
        commit_state=(
            CommitState.NOT_COMMITTED
            if operation in {"capture_text", "append_capture_version"}
            else None
        ),
    )


def _metadata(body_length: int) -> CaptureReadMetadata:
    return CaptureReadMetadata(
        capture_id=CAPTURE_ID,
        version=1,
        current_version=1,
        fidelity="channel-exact",
        media_type="text/plain; charset=utf-8",
        encoding="utf-8",
        byte_size=body_length,
        primary_payload_sha256=PAYLOAD_SHA256,
        payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
        envelope_sha256=ENVELOPE_SHA256,
        captured_at="2026-09-02T01:02:03.004Z",
        channel=ChannelMetadata(type="app", instance_id="local-desktop"),
        user_intent=UserIntent(),
    )


class _RecordingInput(io.BytesIO):
    def __init__(self, source: bytes) -> None:
        super().__init__(source)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class _TrackingSpool(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.closed_by_runner = False
        self.read_sizes: list[int] = []
        self.write_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)

    def write(self, data: bytes, /) -> int:
        self.write_sizes.append(len(data))
        return super().write(data)

    def close(self) -> None:
        self.closed_by_runner = True
        super().close()


class _RecordingOutput:
    def __init__(self) -> None:
        self.value = bytearray()
        self.write_sizes: list[int] = []
        self.flushed = False

    def write(self, data: bytes, /) -> int:
        self.write_sizes.append(len(data))
        self.value.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flushed = True


class _FailingOutput(_RecordingOutput):
    def __init__(self, *, fail_after_bytes: int) -> None:
        super().__init__()
        self.remaining = fail_after_bytes

    def write(self, data: bytes, /) -> int:
        if self.remaining <= 0:
            raise OSError("sensitive output failure")
        accepted = min(len(data), self.remaining)
        self.value.extend(data[:accepted])
        self.write_sizes.append(accepted)
        self.remaining -= accepted
        return accepted


class _FailingFlush(_RecordingOutput):
    def flush(self) -> None:
        raise OSError("sensitive flush failure")


class CliProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PathPolicy.test_owned(OWNED_ROOT, resolver=_identity)
        self.config = LocalConfig(
            capture=CaptureConfig(
                root=CAPTURE_ROOT,
                inline_text_threshold_bytes=8,
                max_text_version_bytes=(2 * CHUNK_SIZE) + 64,
            )
        )
        self.config_reads: list[tuple[Path, PathPolicy]] = []
        self.dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=self._read_config,
        )

    def _resolve_config_path(self, value: object) -> Path:
        return CONFIG_PATH if value is None else Path(value)

    def _read_config(
        self,
        path: str | object,
        *,
        path_policy: PathPolicy,
    ) -> LocalConfig:
        self.config_reads.append((Path(path), path_policy))
        return self.config

    def _header(
        self,
        operation: str,
        *,
        body_length: int | None = None,
        **updates: object,
    ) -> dict[str, object]:
        if body_length is None:
            body_length = len(PAYLOAD_BYTES) if operation in {
                "capture_text",
                "append_capture_version",
            } else 0
        header: dict[str, object] = {
            "schema": REQUEST_SCHEMA,
            "schema_version": 1,
            "body_length_bytes": body_length,
        }
        if operation == "capture_text":
            header["channel"] = {
                "type": "app",
                "instance_id": "local-desktop",
            }
        elif operation == "append_capture_version":
            header.update(
                {
                    "capture_id": CAPTURE_ID,
                    "expected_current_version": 1,
                    "channel": {
                        "type": "app",
                        "instance_id": "local-desktop",
                    },
                    "idempotency_key": "append-key",
                }
            )
        elif operation == "get_capture":
            header["capture_id"] = CAPTURE_ID
        header.update(updates)
        return header

    def _frame(
        self,
        header: dict[str, object],
        *,
        body: bytes = b"",
        terminator: bytes = b"\n",
    ) -> bytes:
        return (
            json.dumps(
                header,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + terminator
            + body
        )

    def _run(
        self,
        argv: list[str],
        source: bytes,
        executor: object,
        *,
        dependencies: _CliDependencies | None = None,
        stdin: object | None = None,
        stdout: object | None = None,
    ) -> tuple[int, bytes, bytes, object]:
        selected_stdin = io.BytesIO(source) if stdin is None else stdin
        selected_stdout = io.BytesIO() if stdout is None else stdout
        stderr = io.BytesIO()
        exit_code = _run_cli(
            argv,
            stdin=selected_stdin,
            stdout=selected_stdout,
            stderr=stderr,
            path_policy=self.policy,
            executor=executor,
            dependencies=dependencies or self.dependencies,
        )
        if isinstance(selected_stdout, io.BytesIO):
            stdout_bytes = selected_stdout.getvalue()
        else:
            stdout_bytes = bytes(getattr(selected_stdout, "value", b""))
        return exit_code, stdout_bytes, stderr.getvalue(), selected_stdin

    def _response(self, source: bytes) -> tuple[dict[str, object], bytes]:
        header, separator, body = source.partition(b"\n")
        self.assertEqual(separator, b"\n")
        value = json.loads(header.decode("utf-8"))
        self.assertIs(type(value), dict)
        self.assertEqual(len(body), value["body_length_bytes"])
        return value, body

    def _assert_invalid(
        self,
        argv: list[str],
        source: bytes,
        *,
        write_operation: bool = False,
    ) -> dict[str, object]:
        calls: list[object] = []

        def executor(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return ListCapturesResult(items=(), next_cursor=None)

        exit_code, stdout, stderr, _ = self._run(argv, source, executor)
        response, body = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr, b"")
        self.assertEqual(body, b"")
        self.assertEqual(response["error"]["code"], "invalid_input")
        self.assertEqual(
            response.get("commit_state"),
            "not-committed" if write_operation else None,
        )
        self.assertEqual(calls, [])
        return response

    def test_cli_01_accepts_only_exact_operation_and_argument_order(self) -> None:
        invalid_argv = (
            [],
            ["capture-text"],
            ["--config", str(CONFIG_PATH), "list_captures"],
            ["list_captures", "--config"],
            ["list_captures", "--config", str(CONFIG_PATH), "extra"],
            ["list_captures", "--config", str(CONFIG_PATH), "--config"],
            ["list_captures", "--help"],
            ["list_captures", "--config", "relative.yaml"],
        )
        valid_frame = self._frame(self._header("list_captures"))
        for argv in invalid_argv:
            with self.subTest(argv=argv):
                self._assert_invalid(argv, valid_frame)

        self._assert_invalid(
            ["capture_text", "extra"],
            self._frame(
                self._header("capture_text"),
                body=PAYLOAD_BYTES,
            ),
            write_operation=True,
        )

        seen: list[tuple[str, Path | None]] = []

        def executor(
            operation: str,
            request: object,
            *,
            config_path: Path | None,
            path_policy: PathPolicy,
        ) -> object:
            self.assertIsInstance(request, ListCapturesRequest)
            self.assertIs(path_policy, self.policy)
            seen.append((operation, config_path))
            return ListCapturesResult(items=(), next_cursor=None)

        exit_code, _, stderr, _ = self._run(
            ["list_captures", "--config", str(CONFIG_PATH)],
            valid_frame,
            executor,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, b"")
        self.assertEqual(seen, [("list_captures", CONFIG_PATH)])

    def test_cli_02_maps_capture_text_and_normalizes_optional_fields(self) -> None:
        cases = (
            ({}, None, UserIntent()),
            (
                {
                    "idempotency_key": "capture-key",
                    "user_intent": {
                        "target_kb_id": "kb-personal",
                        "processing_mode": "capture-only",
                        "requested_new_kb_name": None,
                    },
                },
                "capture-key",
                UserIntent(
                    target_kb_id="kb-personal",
                    processing_mode="capture-only",
                ),
            ),
            (
                {"idempotency_key": None, "user_intent": None},
                None,
                UserIntent(),
            ),
        )
        for updates, expected_key, expected_intent in cases:
            with self.subTest(updates=updates):
                calls: list[CaptureTextRequest] = []

                def executor(
                    operation: str,
                    request: object,
                    **kwargs: object,
                ) -> object:
                    self.assertEqual(operation, "capture_text")
                    self.assertIsInstance(request, CaptureTextRequest)
                    typed = request
                    self.assertEqual(typed.text.read(), PAYLOAD_BYTES)
                    self.assertEqual(typed.channel.type, "app")
                    self.assertEqual(typed.channel.instance_id, "local-desktop")
                    self.assertEqual(typed.idempotency_key, expected_key)
                    self.assertEqual(typed.user_intent, expected_intent)
                    calls.append(typed)
                    return CommittedWriteResult(receipt=_capture_receipt())

                frame = self._frame(
                    self._header("capture_text", **updates),
                    body=PAYLOAD_BYTES,
                )
                exit_code, stdout, stderr, _ = self._run(
                    ["capture_text"],
                    frame,
                    executor,
                )
                response, body = self._response(stdout)
                self.assertEqual(exit_code, 0)
                self.assertTrue(response["ok"])
                self.assertEqual(body, b"")
                self.assertEqual(stderr, b"")
                self.assertEqual(len(calls), 1)

    def test_cli_03_maps_append_request_exactly(self) -> None:
        seen: list[AppendCaptureVersionRequest] = []

        def executor(operation: str, request: object, **kwargs: object) -> object:
            self.assertEqual(operation, "append_capture_version")
            self.assertIsInstance(request, AppendCaptureVersionRequest)
            typed = request
            self.assertEqual(typed.capture_id, CAPTURE_ID)
            self.assertEqual(typed.expected_current_version, 1)
            self.assertEqual(typed.idempotency_key, "append-key")
            self.assertEqual(typed.text.read(), PAYLOAD_BYTES)
            self.assertEqual(
                typed.user_intent,
                UserIntent(processing_mode="raw-source"),
            )
            seen.append(typed)
            return _public_failure(operation)

        header = self._header(
            "append_capture_version",
            user_intent={"processing_mode": "raw-source"},
        )
        exit_code, stdout, stderr, _ = self._run(
            ["append_capture_version"],
            self._frame(header, body=PAYLOAD_BYTES),
            executor,
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["commit_state"], "not-committed")
        self.assertEqual(stderr, b"")
        self.assertEqual(len(seen), 1)

    def test_cli_04_maps_get_and_list_without_new_value_semantics(self) -> None:
        seen: list[object] = []

        def executor(operation: str, request: object, **kwargs: object) -> object:
            seen.append(request)
            return _public_failure(operation)

        get_header = self._header("get_capture", version=7)
        exit_code, _, _, _ = self._run(
            ["get_capture"],
            self._frame(get_header),
            executor,
        )
        self.assertEqual(exit_code, 2)
        self.assertIsInstance(seen[-1], GetCaptureRequest)
        self.assertEqual(seen[-1].version, 7)

        list_header = self._header(
            "list_captures",
            routing_status="unassigned",
            created_after="2026-09-01T00:00:00.000Z",
            created_before="2026-09-02T00:00:00.000Z",
            limit=100,
            cursor="opaque-cursor-for-core",
        )
        exit_code, _, _, _ = self._run(
            ["list_captures"],
            self._frame(list_header),
            executor,
        )
        self.assertEqual(exit_code, 2)
        self.assertIsInstance(seen[-1], ListCapturesRequest)
        self.assertEqual(seen[-1].limit, 100)
        self.assertEqual(seen[-1].cursor, "opaque-cursor-for-core")

        seen.clear()
        exit_code, _, _, _ = self._run(
            ["list_captures"],
            self._frame(self._header("list_captures")),
            executor,
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(seen[-1], ListCapturesRequest())

    def test_cli_05_accepts_lf_and_crlf_and_emits_canonical_bytes(self) -> None:
        expected_mapping = {
            "schema": RESPONSE_SCHEMA,
            "schema_version": 1,
            "body_length_bytes": 0,
            "ok": True,
            "items": [],
            "next_cursor": None,
            "warnings": [],
        }
        expected = (
            json.dumps(
                expected_mapping,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

        def executor(*args: object, **kwargs: object) -> object:
            return ListCapturesResult(items=(), next_cursor=None)

        for terminator in (b"\n", b"\r\n"):
            with self.subTest(terminator=terminator):
                exit_code, stdout, stderr, _ = self._run(
                    ["list_captures"],
                    self._frame(
                        self._header("list_captures"),
                        terminator=terminator,
                    ),
                    executor,
                )
                self.assertEqual(exit_code, 0)
                self.assertEqual(stdout, expected)
                self.assertFalse(stdout.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r", stdout)
                self.assertEqual(stderr, b"")

    def test_cli_06_header_boundary_and_line_failures_are_bounded(self) -> None:
        header = self._header("list_captures", cursor="")
        baseline = json.dumps(header, separators=(",", ":")).encode("utf-8")
        padding = 65_536 - len(baseline)
        self.assertGreater(padding, 0)
        header["cursor"] = "x" * padding
        exact = json.dumps(header, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(exact), 65_536)

        calls: list[object] = []

        def executor(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return ListCapturesResult(items=(), next_cursor=None)

        exit_code, _, _, _ = self._run(
            ["list_captures"],
            exact + b"\n",
            executor,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)

        invalid_sources = (
            exact[:-1] + b"xx\n",
            b"\xef\xbb\xbf" + exact + b"\n",
            exact + b"\r",
            exact,
            json.dumps(
                self._header("list_captures"),
                separators=(",", ":"),
            ).encode("utf-8").replace(b",", b"\r,", 1)
            + b"\n",
        )
        for source in invalid_sources:
            with self.subTest(length=len(source)):
                self._assert_invalid(["list_captures"], source)

    def test_cli_07_rejects_non_strict_json_and_unknown_fields(self) -> None:
        valid = self._header("list_captures")
        unknown = dict(valid)
        unknown["test_policy"] = "owned"
        invalid_headers = (
            b"[]\n",
            (
                b'{"schema":"knowledgeflow.capture-cli-request",'
                b'"schema":"knowledgeflow.capture-cli-request",'
                b'"schema_version":1,"body_length_bytes":0}\n'
            ),
            self._frame(unknown),
            self._frame({**valid, "schema_version": True}),
            self._frame({**valid, "body_length_bytes": 1.0}),
            (
                b'{"schema":"knowledgeflow.capture-cli-request",'
                b'"schema_version":1,"body_length_bytes":NaN}\n'
            ),
            (
                b'{"schema":"knowledgeflow.capture-cli-request",'
                b'"schema_version":1,"body_length_bytes":Infinity}\n'
            ),
            (
                b'{"schema":"knowledgeflow.capture-cli-request",'
                b'"schema_version":1,"body_length_bytes":0,'
                b'"cursor":"\\ud800"}\n'
            ),
            (
                b'{"schema":"knowledgeflow.capture-cli-request",'
                b'"schema_version":1,"body_length_bytes":0,'
                b'"cursor":"\\udc00"}\n'
            ),
        )
        for source in invalid_headers:
            with self.subTest(source=source[:80]):
                self._assert_invalid(["list_captures"], source)

        nested_unknown = self._header("capture_text", body_length=1)
        nested_unknown["channel"] = {
            "type": "app",
            "instance_id": "local-desktop",
            "secret": "must-not-be-accepted",
        }
        self._assert_invalid(
            ["capture_text"],
            self._frame(nested_unknown, body=b"x"),
            write_operation=True,
        )

        paired_surrogate = (
            b'{"schema":"knowledgeflow.capture-cli-request",'
            b'"schema_version":1,"body_length_bytes":0,'
            b'"cursor":"\\ud83d\\ude00"}\n'
        )

        def executor(operation: str, request: object, **kwargs: object) -> object:
            self.assertIsInstance(request, ListCapturesRequest)
            self.assertEqual(request.cursor, "😀")
            return ListCapturesResult(items=(), next_cursor=None)

        exit_code, stdout, stderr, _ = self._run(
            ["list_captures"],
            paired_surrogate,
            executor,
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 0)
        self.assertTrue(response["ok"])
        self.assertEqual(stderr, b"")

    def test_cli_08_enforces_operation_body_length_rules(self) -> None:
        self._assert_invalid(
            ["capture_text"],
            self._frame(self._header("capture_text", body_length=0)),
            write_operation=True,
        )
        self._assert_invalid(
            ["append_capture_version"],
            self._frame(
                self._header("append_capture_version", body_length=0)
            ),
            write_operation=True,
        )
        self._assert_invalid(
            ["get_capture"],
            self._frame(self._header("get_capture", body_length=1), body=b"x"),
        )
        self._assert_invalid(
            ["list_captures"],
            self._frame(self._header("list_captures", body_length=1), body=b"x"),
        )

    def test_cli_09_rejects_early_body_eof_before_calling_core(self) -> None:
        header = self._header("capture_text", body_length=4)
        self._assert_invalid(
            ["capture_text"],
            self._frame(header, body=b"abc"),
            write_operation=True,
        )

    def test_cli_10_rejects_every_trailing_byte_before_core_call(self) -> None:
        header = self._header("capture_text", body_length=1)
        for trailing in (b"x", b"\n", b'{"second":true}\n'):
            with self.subTest(trailing=trailing):
                self._assert_invalid(
                    ["capture_text"],
                    self._frame(header, body=b"a" + trailing),
                    write_operation=True,
                )

    def test_cli_11_rejects_body_bom_and_invalid_utf8_and_cleans_spool(self) -> None:
        for body in (b"\xef\xbb\xbftext", b"\xff", b"\xe2\x82"):
            with self.subTest(body=body):
                spools: list[_TrackingSpool] = []

                def factory(purpose: str) -> _TrackingSpool:
                    self.assertEqual(purpose, "input")
                    spool = _TrackingSpool()
                    spools.append(spool)
                    return spool

                dependencies = _CliDependencies(
                    config_path_resolver=self._resolve_config_path,
                    config_reader=self._read_config,
                    temporary_file_factory=factory,
                )
                header = self._header("capture_text", body_length=len(body))
                calls: list[object] = []
                exit_code, stdout, stderr, _ = self._run(
                    ["capture_text"],
                    self._frame(header, body=body),
                    lambda *args, **kwargs: calls.append((args, kwargs)),
                    dependencies=dependencies,
                )
                response, _ = self._response(stdout)
                self.assertEqual(exit_code, 2)
                self.assertEqual(response["error"]["code"], "invalid_input")
                self.assertEqual(response["commit_state"], "not-committed")
                self.assertEqual(stderr, b"")
                self.assertEqual(calls, [])
                self.assertEqual(len(spools), 1)
                self.assertTrue(spools[0].closed_by_runner)

    def test_cli_12_preflights_config_and_limit_before_reading_body(self) -> None:
        def missing_config(
            path: object,
            *,
            path_policy: PathPolicy,
        ) -> LocalConfig:
            raise ConfigLoadError(PublicErrorCode.CONFIG_NOT_FOUND)

        missing_dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=missing_config,
        )
        source = self._frame(
            self._header("capture_text", body_length=1),
            body=b"x",
        )
        recording = _RecordingInput(source)
        exit_code, stdout, stderr, _ = self._run(
            ["capture_text"],
            source,
            lambda *args, **kwargs: None,
            dependencies=missing_dependencies,
            stdin=recording,
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["error"]["code"], "config_not_found")
        self.assertEqual(response["commit_state"], "not-committed")
        self.assertEqual(recording.tell(), source.index(b"\n") + 1)
        self.assertEqual(stderr, b"")

        outside_reads: list[object] = []
        outside_dependencies = _CliDependencies(
            config_path_resolver=lambda value: Path(r"D:\outside\config.yaml"),
            config_reader=lambda path, *, path_policy: (
                outside_reads.append(path) or self.config
            ),
        )
        recording = _RecordingInput(source)
        exit_code, stdout, stderr, _ = self._run(
            ["capture_text"],
            source,
            lambda *args, **kwargs: None,
            dependencies=outside_dependencies,
            stdin=recording,
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["error"]["code"], "config_invalid")
        self.assertEqual(response["commit_state"], "not-committed")
        self.assertEqual(outside_reads, [])
        self.assertEqual(recording.tell(), source.index(b"\n") + 1)
        self.assertEqual(stderr, b"")

        small_config = LocalConfig(
            capture=CaptureConfig(
                root=CAPTURE_ROOT,
                inline_text_threshold_bytes=1,
                max_text_version_bytes=2,
            )
        )

        def read_small_config(
            path: object,
            *,
            path_policy: PathPolicy,
        ) -> LocalConfig:
            return small_config

        created_spools: list[str] = []
        limited_dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=read_small_config,
            temporary_file_factory=lambda purpose: (
                created_spools.append(purpose) or _TrackingSpool()
            ),
        )
        source = self._frame(
            self._header("capture_text", body_length=3),
            body=b"abc",
        )
        recording = _RecordingInput(source)
        exit_code, stdout, stderr, _ = self._run(
            ["capture_text"],
            source,
            lambda *args, **kwargs: None,
            dependencies=limited_dependencies,
            stdin=recording,
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["error"]["code"], "text_too_large")
        self.assertEqual(
            response["error"]["details"],
            {"maximum_bytes": 2, "observed_bytes": 3},
        )
        self.assertEqual(response["commit_state"], "not-committed")
        self.assertEqual(recording.tell(), source.index(b"\n") + 1)
        self.assertEqual(created_spools, [])
        self.assertEqual(stderr, b"")

    def test_cli_13_request_construction_failure_is_safe_and_complete(self) -> None:
        secret = "do-not-leak-body-key-or-C-path"
        header = self._header("capture_text", body_length=len(secret))
        header["channel"] = {
            "type": "INVALID TOKEN",
            "instance_id": "local-desktop",
        }
        calls: list[object] = []
        exit_code, stdout, stderr, stdin = self._run(
            ["capture_text"],
            self._frame(header, body=secret.encode("utf-8")),
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        response, body = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["error"]["code"], "invalid_input")
        self.assertEqual(response["commit_state"], "not-committed")
        self.assertEqual(body, b"")
        self.assertEqual(stderr, b"")
        self.assertEqual(stdin.read(), b"")
        self.assertEqual(calls, [])
        self.assertNotIn(secret.encode("utf-8"), stdout)

    def test_cli_17_get_spools_then_emits_header_and_exact_body(self) -> None:
        body = "正文\r\n🙂".encode("utf-8")
        spools: list[_TrackingSpool] = []

        def factory(purpose: str) -> _TrackingSpool:
            self.assertEqual(purpose, "output")
            spool = _TrackingSpool()
            spools.append(spool)
            return spool

        dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=self._read_config,
            temporary_file_factory=factory,
        )

        def executor(operation: str, request: object, **kwargs: object) -> object:
            self.assertEqual(operation, "get_capture")
            self.assertIsInstance(request, GetCaptureRequest)
            request.body_sink.write(body)
            return GetCaptureResult(
                body_length_bytes=len(body),
                capture=_metadata(len(body)),
                item_state=CaptureItemState(),
            )

        exit_code, stdout, stderr, _ = self._run(
            ["get_capture"],
            self._frame(self._header("get_capture")),
            executor,
            dependencies=dependencies,
        )
        response, emitted_body = self._response(stdout)
        self.assertEqual(exit_code, 0)
        self.assertTrue(response["ok"])
        self.assertEqual(response["body_length_bytes"], len(body))
        self.assertEqual(emitted_body, body)
        self.assertNotIn("text", response)
        self.assertEqual(stderr, b"")
        self.assertEqual(len(spools), 1)
        self.assertTrue(spools[0].closed_by_runner)

    def test_cli_19_output_spool_creation_failure_is_public_and_redacted(self) -> None:
        def factory(purpose: str) -> io.BytesIO:
            self.assertEqual(purpose, "output")
            raise OSError(r"secret C:\Users\name\temp-file")

        dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=self._read_config,
            temporary_file_factory=factory,
        )
        calls: list[object] = []
        exit_code, stdout, stderr, _ = self._run(
            ["get_capture"],
            self._frame(self._header("get_capture")),
            lambda *args, **kwargs: calls.append((args, kwargs)),
            dependencies=dependencies,
        )
        response, body = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["error"]["code"], "output_write_failed")
        self.assertTrue(response["error"]["retryable"])
        self.assertEqual(body, b"")
        self.assertEqual(stderr, b"")
        self.assertEqual(calls, [])
        self.assertNotIn(b"secret", stdout)
        self.assertNotIn(b"Users", stdout)

    def test_cli_20_adapter_io_chunks_never_exceed_one_mibibyte(self) -> None:
        body = b"a" * (CHUNK_SIZE + 17)
        source = self._frame(
            self._header("capture_text", body_length=len(body)),
            body=body,
        )
        stdin = _RecordingInput(source)
        input_spools: list[_TrackingSpool] = []

        def input_factory(purpose: str) -> _TrackingSpool:
            self.assertEqual(purpose, "input")
            spool = _TrackingSpool()
            input_spools.append(spool)
            return spool

        dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=self._read_config,
            temporary_file_factory=input_factory,
        )
        exit_code, _, _, _ = self._run(
            ["capture_text"],
            source,
            lambda operation, request, **kwargs: _public_failure(operation),
            dependencies=dependencies,
            stdin=stdin,
        )
        self.assertEqual(exit_code, 2)
        self.assertTrue(all(size <= CHUNK_SIZE for size in stdin.read_sizes))
        self.assertTrue(
            all(size <= CHUNK_SIZE for size in input_spools[0].write_sizes)
        )
        self.assertTrue(input_spools[0].closed_by_runner)

        output_spools: list[_TrackingSpool] = []

        def output_factory(purpose: str) -> _TrackingSpool:
            self.assertEqual(purpose, "output")
            spool = _TrackingSpool()
            output_spools.append(spool)
            return spool

        output_dependencies = _CliDependencies(
            config_path_resolver=self._resolve_config_path,
            config_reader=self._read_config,
            temporary_file_factory=output_factory,
        )
        stdout = _RecordingOutput()

        def get_executor(operation: str, request: object, **kwargs: object) -> object:
            request.body_sink.write(body[:CHUNK_SIZE])
            request.body_sink.write(body[CHUNK_SIZE:])
            return GetCaptureResult(
                body_length_bytes=len(body),
                capture=_metadata(len(body)),
                item_state=CaptureItemState(),
            )

        exit_code, emitted, stderr, _ = self._run(
            ["get_capture"],
            self._frame(self._header("get_capture")),
            get_executor,
            dependencies=output_dependencies,
            stdout=stdout,
        )
        response, emitted_body = self._response(emitted)
        self.assertEqual(exit_code, 0)
        self.assertEqual(response["body_length_bytes"], len(body))
        self.assertEqual(emitted_body, body)
        self.assertEqual(stderr, b"")
        self.assertTrue(all(size <= CHUNK_SIZE for size in stdout.write_sizes))
        self.assertTrue(
            all(
                size <= CHUNK_SIZE
                for size in output_spools[0].read_sizes
                if size >= 0
            )
        )
        self.assertTrue(output_spools[0].closed_by_runner)

    def test_cli_21_and_22_exit_codes_frames_stderr_and_redaction(self) -> None:
        list_frame = self._frame(self._header("list_captures"))

        exit_code, stdout, stderr, _ = self._run(
            ["list_captures"],
            list_frame,
            lambda *args, **kwargs: ListCapturesResult(items=(), next_cursor=None),
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 0)
        self.assertTrue(response["ok"])
        self.assertEqual(stderr, b"")

        exit_code, stdout, stderr, _ = self._run(
            ["list_captures"],
            list_frame,
            lambda operation, request, **kwargs: _public_failure(operation),
        )
        response, _ = self._response(stdout)
        self.assertEqual(exit_code, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(stderr, b"")

        secret = "body-key-C:\\secret\\store"

        def explode(*args: object, **kwargs: object) -> object:
            raise RuntimeError(secret)

        exit_code, stdout, stderr, _ = self._run(
            ["list_captures"],
            list_frame,
            explode,
        )
        self.assertEqual(exit_code, 70)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"knowledgeflow-capture: internal failure\n")
        self.assertNotIn(secret.encode("ascii"), stderr)

    def test_cli_23_stdout_write_and_flush_failures_return_only_exit_70(self) -> None:
        frame = self._frame(self._header("list_captures"))
        executor = lambda *args, **kwargs: ListCapturesResult(
            items=(),
            next_cursor=None,
        )

        for stdout in (
            _FailingOutput(fail_after_bytes=0),
            _FailingOutput(fail_after_bytes=7),
            _FailingFlush(),
        ):
            with self.subTest(stdout=type(stdout).__name__):
                exit_code, emitted, stderr, _ = self._run(
                    ["list_captures"],
                    frame,
                    executor,
                    stdout=stdout,
                )
                self.assertEqual(exit_code, 70)
                self.assertEqual(
                    stderr,
                    b"knowledgeflow-capture: internal failure\n",
                )
                self.assertLessEqual(emitted.count(b'"schema"'), 1)
                self.assertNotIn(b"internal failure", emitted)

        body = b"body-after-complete-header"

        def get_executor(operation: str, request: object, **kwargs: object) -> object:
            request.body_sink.write(body)
            return GetCaptureResult(
                body_length_bytes=len(body),
                capture=_metadata(len(body)),
                item_state=CaptureItemState(),
            )

        get_frame = self._frame(self._header("get_capture"))
        exit_code, complete, _, _ = self._run(
            ["get_capture"],
            get_frame,
            get_executor,
        )
        self.assertEqual(exit_code, 0)
        response_header_length = complete.index(b"\n") + 1
        stdout = _FailingOutput(fail_after_bytes=response_header_length + 2)
        exit_code, emitted, stderr, _ = self._run(
            ["get_capture"],
            get_frame,
            get_executor,
            stdout=stdout,
        )
        self.assertEqual(exit_code, 70)
        self.assertEqual(stderr, b"knowledgeflow-capture: internal failure\n")
        self.assertEqual(emitted.count(b'"schema"'), 1)
        self.assertTrue(emitted.endswith(body[:2]))

    def test_cli_24_private_runner_has_no_installed_or_test_policy_surface(self) -> None:
        self.assertEqual(cli_module.__all__, ())
        self.assertFalse(hasattr(cli_module, "main"))
        pyproject = (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("[project.scripts]", pyproject)
        self.assertNotIn("knowledgeflow-capture =", pyproject)

        header = self._header("list_captures")
        header["path_policy"] = "test-owned"
        self._assert_invalid(
            ["list_captures"],
            self._frame(header),
        )


if __name__ == "__main__":
    unittest.main()
