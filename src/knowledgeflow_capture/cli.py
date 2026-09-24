"""Restricted C7 wire-protocol adapter for the four Capture operations.

The installed ``main`` entry constructs only the production path policy and maps
the already-validated frame to the existing operations.  Tests that need a
temporary Store continue to call the unexported runner from test-only support.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
import codecs
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import BinaryIO, Protocol

from .config import (
    ConfigLoadError,
    LocalConfig,
    read_local_config_file,
    resolve_config_path,
)
from .errors import (
    AppendCaptureVersionResult,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    OperationError,
    PublicErrorCode,
)
from .models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
)
from .operations import (
    append_capture_version,
    capture_text,
    get_capture,
    list_captures,
)
from .paths import PathPolicy, PathPolicyError


_REQUEST_SCHEMA = "knowledgeflow.capture-cli-request"
_RESPONSE_SCHEMA = "knowledgeflow.capture-cli-response"
_SCHEMA_VERSION = 1
_MAXIMUM_HEADER_BYTES = 65_536
_CHUNK_SIZE = 1024 * 1024
_EXIT_SUCCESS = 0
_EXIT_PUBLIC_FAILURE = 2
_EXIT_INTERNAL_FAILURE = 70
_INTERNAL_FAILURE_LINE = b"knowledgeflow-capture: internal failure\n"

_CAPTURE_TEXT = "capture_text"
_GET_CAPTURE = "get_capture"
_LIST_CAPTURES = "list_captures"
_APPEND_CAPTURE_VERSION = "append_capture_version"
_OPERATIONS = frozenset(
    {
        _CAPTURE_TEXT,
        _GET_CAPTURE,
        _LIST_CAPTURES,
        _APPEND_CAPTURE_VERSION,
    }
)
_WRITE_OPERATIONS = frozenset({_CAPTURE_TEXT, _APPEND_CAPTURE_VERSION})
_COMMON_FIELDS = frozenset({"schema", "schema_version", "body_length_bytes"})
_BUSINESS_FIELDS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    _CAPTURE_TEXT: (
        frozenset({"channel"}),
        frozenset({"idempotency_key", "user_intent"}),
    ),
    _APPEND_CAPTURE_VERSION: (
        frozenset(
            {
                "capture_id",
                "expected_current_version",
                "channel",
                "idempotency_key",
            }
        ),
        frozenset({"user_intent"}),
    ),
    _GET_CAPTURE: (
        frozenset({"capture_id"}),
        frozenset({"version"}),
    ),
    _LIST_CAPTURES: (
        frozenset(),
        frozenset(
            {
                "routing_status",
                "created_after",
                "created_before",
                "limit",
                "cursor",
            }
        ),
    ),
}
_CHANNEL_REQUIRED_FIELDS = frozenset({"type", "instance_id"})
_CHANNEL_OPTIONAL_FIELDS = frozenset({"external_ref", "source_created_at"})
_USER_INTENT_FIELDS = frozenset(
    {"target_kb_id", "processing_mode", "requested_new_kb_name"}
)


class _ConfigReader(Protocol):
    def __call__(
        self,
        config_path: str | os.PathLike[str],
        *,
        path_policy: PathPolicy,
    ) -> LocalConfig:
        ...


class _OperationExecutor(Protocol):
    def __call__(
        self,
        operation: str,
        request: object,
        *,
        config_path: Path | None,
        path_policy: PathPolicy,
    ) -> object:
        ...


def _new_temporary_file(_purpose: str) -> BinaryIO:
    return tempfile.TemporaryFile(mode="w+b")


@dataclass(frozen=True, slots=True)
class _CliDependencies:
    config_path_resolver: Callable[[str | os.PathLike[str] | None], Path] = (
        resolve_config_path
    )
    config_reader: _ConfigReader = read_local_config_file
    temporary_file_factory: Callable[[str], BinaryIO] = _new_temporary_file


@dataclass(frozen=True, slots=True)
class _CliInvocation:
    operation: str
    config_path: Path | None


class _ProtocolFailure(Exception):
    def __init__(
        self,
        code: PublicErrorCode,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = PublicErrorCode(code)
        self.details = dict(details or {})
        super().__init__(self.code.value)


class _OutputFailure(Exception):
    pass


class _DuplicateKey(ValueError):
    pass


class _InvalidConstant(ValueError):
    pass


def _parse_cli_arguments(argv: Sequence[str]) -> _CliInvocation:
    if isinstance(argv, (str, bytes)):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    values = tuple(argv)
    if not values or type(values[0]) is not str or values[0] not in _OPERATIONS:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    if len(values) == 1:
        return _CliInvocation(operation=values[0], config_path=None)
    if (
        len(values) != 3
        or values[1] != "--config"
        or type(values[2]) is not str
        or not values[2]
    ):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    try:
        config_path = resolve_config_path(values[2])
    except ConfigLoadError as exc:
        # ``--config`` syntax belongs to the CLI request contract.  Runtime
        # config-not-found/config-invalid classifications begin only once the
        # selected absolute file is read.
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT) from exc
    return _CliInvocation(operation=values[0], config_path=config_path)


def _recognized_operation(argv: object) -> str | None:
    if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
        return None
    if not argv:
        return None
    operation = argv[0]
    return operation if type(operation) is str and operation in _OPERATIONS else None


def _read_binary(stream: object, size: int) -> bytes:
    reader = getattr(stream, "read", None)
    if not callable(reader):
        raise TypeError("binary input must provide read(size)")
    value = reader(size)
    if type(value) is not bytes:
        raise TypeError("binary input read(size) must return bytes")
    if size >= 0 and len(value) > size:
        raise TypeError("binary input read(size) returned too many bytes")
    return value


def _read_header_line(stdin: object) -> bytes:
    header = bytearray()
    while True:
        value = _read_binary(stdin, 1)
        if not value:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
        if value == b"\n":
            break
        header.extend(value)
        if len(header) > _MAXIMUM_HEADER_BYTES + 1:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
        if (
            len(header) == _MAXIMUM_HEADER_BYTES + 1
            and header[-1] != 0x0D
        ):
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)

    if header.endswith(b"\r"):
        del header[-1]
    if (
        len(header) > _MAXIMUM_HEADER_BYTES
        or header.startswith(b"\xef\xbb\xbf")
        or b"\r" in header
    ):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    return bytes(header)


def _reject_json_constant(value: str) -> object:
    raise _InvalidConstant(value)


def _normalize_json_string(value: str) -> str:
    normalized: list[str] = []
    index = 0
    while index < len(value):
        code_point = ord(value[index])
        if 0xD800 <= code_point <= 0xDBFF:
            if index + 1 >= len(value):
                raise ValueError("JSON contains a lone high surrogate")
            low = ord(value[index + 1])
            if not 0xDC00 <= low <= 0xDFFF:
                raise ValueError("JSON contains a lone high surrogate")
            normalized.append(
                chr(0x10000 + ((code_point - 0xD800) << 10) + (low - 0xDC00))
            )
            index += 2
            continue
        if 0xDC00 <= code_point <= 0xDFFF:
            raise ValueError("JSON contains a lone low surrogate")
        normalized.append(value[index])
        index += 1
    return "".join(normalized)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        normalized_key = _normalize_json_string(key)
        if normalized_key in result:
            raise _DuplicateKey(normalized_key)
        result[normalized_key] = value
    return result


def _normalize_json_strings(value: object) -> object:
    if type(value) is str:
        return _normalize_json_string(value)
    if type(value) is dict:
        return {key: _normalize_json_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_strings(item) for item in value]
    return value


def _validate_json_scalars(value: object) -> None:
    if type(value) is str:
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("JSON contains a surrogate code point")
        return
    if type(value) is float and not math.isfinite(value):
        raise ValueError("JSON contains a non-finite number")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_json_scalars(key)
            _validate_json_scalars(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_scalars(item)


def _decode_header(source: bytes) -> dict[str, object]:
    try:
        text = source.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        value = _normalize_json_strings(value)
        _validate_json_scalars(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateKey,
        _InvalidConstant,
        RecursionError,
        ValueError,
    ) as exc:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT) from exc
    if type(value) is not dict:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    return value


def _require_exact_fields(
    value: object,
    *,
    required: frozenset[str],
    optional: frozenset[str],
) -> dict[str, object]:
    if type(value) is not dict:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    return value


def _validate_nested_shapes(header: Mapping[str, object], operation: str) -> None:
    if "channel" in header:
        _require_exact_fields(
            header["channel"],
            required=_CHANNEL_REQUIRED_FIELDS,
            optional=_CHANNEL_OPTIONAL_FIELDS,
        )
    if "user_intent" in header and header["user_intent"] is not None:
        _require_exact_fields(
            header["user_intent"],
            required=frozenset(),
            optional=_USER_INTENT_FIELDS,
        )

    if operation == _CAPTURE_TEXT:
        if header.get("idempotency_key") is not None and type(
            header.get("idempotency_key")
        ) is not str:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    elif operation == _APPEND_CAPTURE_VERSION:
        if type(header.get("idempotency_key")) is not str:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    elif operation == _GET_CAPTURE:
        if "version" in header and header["version"] is not None and type(
            header["version"]
        ) is not int:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    elif operation == _LIST_CAPTURES:
        for field_name in (
            "routing_status",
            "created_after",
            "created_before",
            "cursor",
        ):
            if (
                field_name in header
                and header[field_name] is not None
                and type(header[field_name]) is not str
            ):
                raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
        if "limit" in header and type(header["limit"]) is not int:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)


def _validate_request_header(
    header: dict[str, object],
    operation: str,
) -> int:
    required_business, optional_business = _BUSINESS_FIELDS[operation]
    _require_exact_fields(
        header,
        required=_COMMON_FIELDS | required_business,
        optional=optional_business,
    )
    if header["schema"] != _REQUEST_SCHEMA:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    if type(header["schema_version"]) is not int or header["schema_version"] != 1:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    body_length = header["body_length_bytes"]
    if type(body_length) is not int or body_length < 0:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    if operation in _WRITE_OPERATIONS:
        if body_length < 1:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    elif body_length != 0:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    _validate_nested_shapes(header, operation)
    return body_length


def _write_all(stream: object, source: bytes) -> None:
    writer = getattr(stream, "write", None)
    if not callable(writer):
        raise _OutputFailure("binary output must provide write(bytes)")
    offset = 0
    while offset < len(source):
        chunk = source[offset : offset + _CHUNK_SIZE]
        try:
            written = writer(chunk)
        except Exception as exc:
            raise _OutputFailure("binary output write failed") from exc
        if type(written) is not int or not 1 <= written <= len(chunk):
            raise _OutputFailure("binary output made no valid progress")
        offset += written


def _flush_output(stream: object) -> None:
    flusher = getattr(stream, "flush", None)
    if not callable(flusher):
        raise _OutputFailure("binary output must provide flush()")
    try:
        flusher()
    except Exception as exc:
        raise _OutputFailure("binary output flush failed") from exc


def _write_spool(spool: BinaryIO, source: bytes) -> None:
    try:
        _write_all(spool, source)
    except _OutputFailure as exc:
        raise OSError("temporary input write failed") from exc


def _finish_input_spool(spool: BinaryIO) -> None:
    try:
        spool.flush()
        spool.seek(0)
    except Exception as exc:
        raise OSError("temporary input rewind failed") from exc


def _spool_request_body(stdin: object, body_length: int, spool: BinaryIO) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    prefix = bytearray()
    remaining = body_length

    try:
        while remaining:
            chunk = _read_binary(stdin, min(_CHUNK_SIZE, remaining))
            if not chunk:
                raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
            remaining -= len(chunk)

            if len(prefix) < min(3, body_length):
                needed = min(3, body_length) - len(prefix)
                prefix.extend(chunk[:needed])
                chunk = chunk[needed:]
                if len(prefix) == min(3, body_length):
                    if body_length >= 3 and bytes(prefix) == b"\xef\xbb\xbf":
                        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
                    decoder.decode(bytes(prefix), final=False)
                    _write_spool(spool, bytes(prefix))

            if chunk:
                decoder.decode(chunk, final=False)
                _write_spool(spool, chunk)

        decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT) from exc

    if _read_binary(stdin, 1):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)
    _finish_input_spool(spool)


def _require_stdin_eof(stdin: object) -> None:
    if _read_binary(stdin, 1):
        raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT)


def _preflight_write_limit(
    invocation: _CliInvocation,
    body_length: int,
    *,
    path_policy: PathPolicy,
    dependencies: _CliDependencies,
) -> None:
    try:
        selected_path = dependencies.config_path_resolver(invocation.config_path)
        selected_path = path_policy.validate_config_path(selected_path)
        config = dependencies.config_reader(
            selected_path,
            path_policy=path_policy,
        )
    except ConfigLoadError as exc:
        raise _ProtocolFailure(exc.code) from exc
    except PathPolicyError as exc:
        raise _ProtocolFailure(PublicErrorCode.CONFIG_INVALID) from exc
    if not isinstance(config, LocalConfig):
        raise TypeError("config reader returned an invalid value")
    maximum = config.capture.max_text_version_bytes
    if body_length > maximum:
        raise _ProtocolFailure(
            PublicErrorCode.TEXT_TOO_LARGE,
            details={"maximum_bytes": maximum, "observed_bytes": body_length},
        )


def _channel_from_header(header: Mapping[str, object]) -> ChannelMetadata:
    channel = header["channel"]
    if type(channel) is not dict:
        raise TypeError("channel must be an object")
    return ChannelMetadata(
        type=channel["type"],
        instance_id=channel["instance_id"],
        external_ref=channel.get("external_ref"),
        source_created_at=channel.get("source_created_at"),
    )


def _user_intent_from_header(header: Mapping[str, object]) -> UserIntent | None:
    value = header.get("user_intent")
    if value is None:
        return None
    if type(value) is not dict:
        raise TypeError("user_intent must be an object or null")
    return UserIntent(
        target_kb_id=value.get("target_kb_id"),
        processing_mode=value.get("processing_mode"),
        requested_new_kb_name=value.get("requested_new_kb_name"),
    )


def _build_request(
    operation: str,
    header: Mapping[str, object],
    *,
    input_spool: BinaryIO | None,
    output_spool: BinaryIO | None,
) -> object:
    if operation == _CAPTURE_TEXT:
        if input_spool is None:
            raise TypeError("capture_text requires an input spool")
        return CaptureTextRequest(
            text=input_spool,
            channel=_channel_from_header(header),
            idempotency_key=header.get("idempotency_key"),
            user_intent=_user_intent_from_header(header),
        )
    if operation == _APPEND_CAPTURE_VERSION:
        if input_spool is None:
            raise TypeError("append_capture_version requires an input spool")
        return AppendCaptureVersionRequest(
            capture_id=header["capture_id"],
            expected_current_version=header["expected_current_version"],
            text=input_spool,
            channel=_channel_from_header(header),
            idempotency_key=header["idempotency_key"],
            user_intent=_user_intent_from_header(header),
        )
    if operation == _GET_CAPTURE:
        if output_spool is None:
            raise TypeError("get_capture requires an output spool")
        return GetCaptureRequest(
            capture_id=header["capture_id"],
            version=header.get("version"),
            body_sink=output_spool,
        )
    if operation == _LIST_CAPTURES:
        return ListCapturesRequest(
            routing_status=header.get("routing_status"),
            created_after=header.get("created_after"),
            created_before=header.get("created_before"),
            limit=header.get("limit", 50),
            cursor=header.get("cursor"),
        )
    raise TypeError("unknown operation")


def _failure_result(
    code: PublicErrorCode,
    *,
    operation: str | None,
    details: Mapping[str, object] | None = None,
) -> FailureResult:
    return FailureResult(
        error=OperationError(
            code=code,
            retryable=code is PublicErrorCode.OUTPUT_WRITE_FAILED,
            details=details or {},
        ),
        commit_state=(
            CommitState.NOT_COMMITTED if operation in _WRITE_OPERATIONS else None
        ),
    )


def _validate_operation_result(operation: str, result: object) -> None:
    if isinstance(result, FailureResult):
        return
    expected_types: Mapping[str, type[object]] = {
        _CAPTURE_TEXT: CommittedWriteResult,
        _APPEND_CAPTURE_VERSION: AppendCaptureVersionResult,
        _GET_CAPTURE: GetCaptureResult,
        _LIST_CAPTURES: ListCapturesResult,
    }
    if not isinstance(result, expected_types[operation]):
        raise TypeError("operation executor returned an invalid result type")


def _prepare_get_body(
    result: object,
    output_spool: BinaryIO | None,
) -> tuple[int, BinaryIO | None]:
    if not isinstance(result, GetCaptureResult):
        return 0, None
    if output_spool is None:
        raise TypeError("get_capture result has no output spool")
    try:
        output_spool.flush()
        output_spool.seek(0, os.SEEK_END)
        observed_length = output_spool.tell()
        output_spool.seek(0)
    except Exception as exc:
        raise _ProtocolFailure(PublicErrorCode.OUTPUT_WRITE_FAILED) from exc
    if observed_length != result.body_length_bytes:
        raise TypeError("get_capture body length does not match its result")
    return result.body_length_bytes, output_spool


def _encode_response_header(result: object, body_length: int) -> bytes:
    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("operation result must provide to_dict()")
    operation_payload = to_dict()
    if type(operation_payload) is not dict:
        raise TypeError("operation result to_dict() must return a dictionary")

    if "body_length_bytes" in operation_payload:
        if operation_payload["body_length_bytes"] != body_length:
            raise TypeError("result body length conflicts with response framing")
        operation_payload = dict(operation_payload)
        del operation_payload["body_length_bytes"]

    response: dict[str, object] = {
        "schema": _RESPONSE_SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "body_length_bytes": body_length,
    }
    if set(response).intersection(operation_payload):
        raise TypeError("operation result overrides response framing")
    response.update(operation_payload)
    _validate_json_scalars(response)
    return (
        json.dumps(
            response,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _copy_spool_to_stdout(
    spool: BinaryIO,
    body_length: int,
    stdout: object,
) -> None:
    remaining = body_length
    while remaining:
        requested = min(_CHUNK_SIZE, remaining)
        try:
            chunk = spool.read(requested)
        except Exception as exc:
            raise _OutputFailure("temporary output read failed") from exc
        if type(chunk) is not bytes or not chunk or len(chunk) > requested:
            raise _OutputFailure("temporary output ended early")
        _write_all(stdout, chunk)
        remaining -= len(chunk)
    try:
        trailing = spool.read(1)
    except Exception as exc:
        raise _OutputFailure("temporary output final read failed") from exc
    if trailing != b"":
        raise _OutputFailure("temporary output contains trailing bytes")


def _emit_result(
    result: object,
    *,
    body_length: int,
    body_spool: BinaryIO | None,
    stdout: object,
) -> int:
    header = _encode_response_header(result, body_length)
    _write_all(stdout, header)
    if body_length:
        if body_spool is None:
            raise _OutputFailure("response body spool is missing")
        _copy_spool_to_stdout(body_spool, body_length, stdout)
    _flush_output(stdout)
    return _EXIT_PUBLIC_FAILURE if isinstance(result, FailureResult) else _EXIT_SUCCESS


def _emit_internal_failure(stderr: object) -> int:
    try:
        _write_all(stderr, _INTERNAL_FAILURE_LINE)
        _flush_output(stderr)
    except Exception:
        pass
    return _EXIT_INTERNAL_FAILURE


def _open_spool(
    stack: ExitStack,
    dependencies: _CliDependencies,
    purpose: str,
) -> BinaryIO:
    try:
        candidate = dependencies.temporary_file_factory(purpose)
        spool = stack.enter_context(candidate)
    except Exception as exc:
        if purpose == "output":
            raise _ProtocolFailure(PublicErrorCode.OUTPUT_WRITE_FAILED) from exc
        raise
    if not all(callable(getattr(spool, name, None)) for name in ("read", "write", "seek")):
        raise TypeError("temporary file factory returned an invalid binary spool")
    return spool


def _execute_valid_invocation(
    invocation: _CliInvocation,
    *,
    stdin: object,
    stdout: object,
    path_policy: PathPolicy,
    executor: _OperationExecutor,
    dependencies: _CliDependencies,
) -> int:
    header = _decode_header(_read_header_line(stdin))
    body_length = _validate_request_header(header, invocation.operation)

    if invocation.operation in _WRITE_OPERATIONS:
        _preflight_write_limit(
            invocation,
            body_length,
            path_policy=path_policy,
            dependencies=dependencies,
        )

    with ExitStack() as stack:
        input_spool: BinaryIO | None = None
        output_spool: BinaryIO | None = None
        if invocation.operation in _WRITE_OPERATIONS:
            input_spool = _open_spool(stack, dependencies, "input")
            _spool_request_body(stdin, body_length, input_spool)
        else:
            _require_stdin_eof(stdin)

        if invocation.operation == _GET_CAPTURE:
            output_spool = _open_spool(stack, dependencies, "output")

        try:
            request = _build_request(
                invocation.operation,
                header,
                input_spool=input_spool,
                output_spool=output_spool,
            )
        except (TypeError, ValueError) as exc:
            raise _ProtocolFailure(PublicErrorCode.INVALID_INPUT) from exc

        result = executor(
            invocation.operation,
            request,
            config_path=invocation.config_path,
            path_policy=path_policy,
        )
        _validate_operation_result(invocation.operation, result)
        response_body_length, response_spool = _prepare_get_body(
            result,
            output_spool,
        )
        return _emit_result(
            result,
            body_length=response_body_length,
            body_spool=response_spool,
            stdout=stdout,
        )


def _run_cli(
    argv: Sequence[str],
    *,
    stdin: object,
    stdout: object,
    stderr: object,
    path_policy: PathPolicy,
    executor: _OperationExecutor,
    dependencies: _CliDependencies | None = None,
) -> int:
    """Run one v1 CLI frame with explicitly injected trusted dependencies."""

    operation: str | None = None
    selected_dependencies = dependencies or _CliDependencies()
    try:
        operation = _recognized_operation(argv)
        if not isinstance(path_policy, PathPolicy) or not callable(executor):
            raise TypeError("private CLI dependencies are invalid")
        invocation = _parse_cli_arguments(argv)
        return _execute_valid_invocation(
            invocation,
            stdin=stdin,
            stdout=stdout,
            path_policy=path_policy,
            executor=executor,
            dependencies=selected_dependencies,
        )
    except _ProtocolFailure as exc:
        try:
            return _emit_result(
                _failure_result(
                    exc.code,
                    operation=operation,
                    details=exc.details,
                ),
                body_length=0,
                body_spool=None,
                stdout=stdout,
            )
        except Exception:
            return _emit_internal_failure(stderr)
    except Exception:
        return _emit_internal_failure(stderr)


def _production_source_root() -> Path:
    """Return the trusted package root, or the whole repository in a src checkout."""

    package_root = Path(__file__).resolve(strict=True).parent
    repository_root = package_root.parent.parent
    if (
        package_root.parent.name.casefold() == "src"
        and (repository_root / "pyproject.toml").is_file()
    ):
        return repository_root
    return package_root


def _production_path_policy() -> PathPolicy:
    """Construct the fixed production policy without caller-controlled inputs."""

    return PathPolicy.production(source_root=_production_source_root())


def _execute_operation(
    operation: str,
    request: object,
    *,
    config_path: Path | None,
    path_policy: PathPolicy,
) -> object:
    """Dispatch exactly one protocol operation to its existing core function."""

    if operation == _CAPTURE_TEXT:
        selected = capture_text
    elif operation == _GET_CAPTURE:
        selected = get_capture
    elif operation == _LIST_CAPTURES:
        selected = list_captures
    elif operation == _APPEND_CAPTURE_VERSION:
        selected = append_capture_version
    else:
        raise TypeError("unknown operation")
    return selected(
        request,
        config_path=config_path,
        path_policy=path_policy,
    )


def main() -> int:
    """Run the installed machine entry with binary standard streams."""

    stderr = getattr(sys.stderr, "buffer", sys.stderr)
    try:
        stdin = sys.stdin.buffer
        stdout = sys.stdout.buffer
        path_policy = _production_path_policy()
    except Exception:
        return _emit_internal_failure(stderr)
    return _run_cli(
        sys.argv[1:],
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        path_policy=path_policy,
        executor=_execute_operation,
    )


__all__: tuple[str, ...] = ()
