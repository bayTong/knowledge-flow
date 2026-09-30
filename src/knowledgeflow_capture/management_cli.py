"""Installed, path-safe machine CLI for the four P0B management operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Protocol

from .cli import _production_path_policy
from .errors import FailureResult, OperationError, PublicErrorCode
from .management import (
    DEFAULT_INLINE_TEXT_THRESHOLD_BYTES,
    DEFAULT_MAX_TEXT_VERSION_BYTES,
    backup_capture_store,
    initialize_capture_store,
    restore_capture_store,
    verify_capture_store,
)
from .paths import PathPolicy


_RESPONSE_SCHEMA = "knowledgeflow.capture-management-response"
_RESPONSE_SCHEMA_VERSION = 1
_INTERNAL_FAILURE_LINE = b"knowledgeflow-capture-admin: internal failure\n"
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|//)")
_MAXIMUM_INTEGER = (2**63) - 1

_INIT = "init"
_VERIFY = "verify"
_BACKUP = "backup"
_RESTORE = "restore"
_OPERATIONS = frozenset({_INIT, _VERIFY, _BACKUP, _RESTORE})


class _ManagementExecutor(Protocol):
    def __call__(
        self,
        operation: str,
        arguments: Mapping[str, object],
        *,
        path_policy: PathPolicy,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class _Invocation:
    operation: str
    arguments: Mapping[str, object]


class _ProtocolFailure(Exception):
    def __init__(self, operation: str | None) -> None:
        self.operation = operation
        super().__init__("invalid management command")


def _recognized_operation(argv: object) -> str | None:
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
        return None
    if not argv:
        return None
    operation = argv[0]
    if type(operation) is str and operation in _OPERATIONS:
        return operation
    return None


def _parse_positive_integer(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("integer argument must use decimal ASCII digits")
    parsed = int(value, 10)
    if parsed <= 0 or parsed > _MAXIMUM_INTEGER:
        raise ValueError("integer argument is outside the supported range")
    return parsed


def _parse_options(
    values: Sequence[str],
    *,
    allowed: frozenset[str],
) -> dict[str, str]:
    if len(values) % 2:
        raise ValueError("each option requires one value")
    parsed: dict[str, str] = {}
    for index in range(0, len(values), 2):
        name = values[index]
        value = values[index + 1]
        if name not in allowed or name in parsed or not value:
            raise ValueError("invalid management option")
        parsed[name] = value
    return parsed


def _parse_cli_arguments(argv: Sequence[str]) -> _Invocation:
    operation = _recognized_operation(argv)
    if operation is None:
        raise _ProtocolFailure(None)
    try:
        if not all(type(value) is str for value in argv):
            raise ValueError("arguments must be strings")
        if operation == _INIT:
            options = _parse_options(
                argv[1:],
                allowed=frozenset(
                    {
                        "--config",
                        "--store",
                        "--inline-threshold",
                        "--max-version",
                    }
                ),
            )
            if not {"--config", "--store"}.issubset(options):
                raise ValueError("init requires config and store")
            arguments: dict[str, object] = {
                "config_path": Path(options["--config"]),
                "capture_root": Path(options["--store"]),
                "inline_text_threshold_bytes": _parse_positive_integer(
                    options.get(
                        "--inline-threshold",
                        str(DEFAULT_INLINE_TEXT_THRESHOLD_BYTES),
                    )
                ),
                "max_text_version_bytes": _parse_positive_integer(
                    options.get(
                        "--max-version",
                        str(DEFAULT_MAX_TEXT_VERSION_BYTES),
                    )
                ),
            }
        elif operation == _VERIFY:
            options = _parse_options(
                argv[1:],
                allowed=frozenset({"--config"}),
            )
            if set(options) != {"--config"}:
                raise ValueError("verify requires config")
            arguments = {"config_path": Path(options["--config"])}
        elif operation == _BACKUP:
            options = _parse_options(
                argv[1:],
                allowed=frozenset({"--config", "--target"}),
            )
            if set(options) != {"--config", "--target"}:
                raise ValueError("backup requires config and target")
            arguments = {
                "config_path": Path(options["--config"]),
                "backup_root": Path(options["--target"]),
            }
        else:
            options = _parse_options(
                argv[1:],
                allowed=frozenset({"--backup", "--target"}),
            )
            if set(options) != {"--backup", "--target"}:
                raise ValueError("restore requires backup and target")
            arguments = {
                "backup_root": Path(options["--backup"]),
                "target_root": Path(options["--target"]),
            }
        return _Invocation(operation=operation, arguments=arguments)
    except (KeyError, TypeError, ValueError) as exc:
        raise _ProtocolFailure(operation) from exc


def _execute_management_operation(
    operation: str,
    arguments: Mapping[str, object],
    *,
    path_policy: PathPolicy,
) -> object:
    if operation == _INIT:
        return initialize_capture_store(
            config_path=arguments["config_path"],
            capture_root=arguments["capture_root"],
            inline_text_threshold_bytes=arguments[
                "inline_text_threshold_bytes"
            ],
            max_text_version_bytes=arguments["max_text_version_bytes"],
            path_policy=path_policy,
        )
    if operation == _VERIFY:
        return verify_capture_store(
            config_path=arguments["config_path"],
            path_policy=path_policy,
        )
    if operation == _BACKUP:
        return backup_capture_store(
            config_path=arguments["config_path"],
            backup_root=arguments["backup_root"],
            path_policy=path_policy,
        )
    if operation == _RESTORE:
        return restore_capture_store(
            backup_root=arguments["backup_root"],
            target_root=arguments["target_root"],
            path_policy=path_policy,
        )
    raise TypeError("unknown management operation")


def _failure_result() -> FailureResult:
    return FailureResult(
        error=OperationError(
            code=PublicErrorCode.INVALID_INPUT,
            retryable=False,
        )
    )


def _response_mapping(operation: str | None, result: object) -> dict[str, object]:
    if not hasattr(result, "to_dict"):
        raise TypeError("management result must provide to_dict")
    body = result.to_dict()
    if not isinstance(body, dict) or type(body.get("ok")) is not bool:
        raise TypeError("management result mapping is invalid")
    if {"schema", "schema_version", "operation"}.intersection(body):
        raise TypeError("management result overrides reserved fields")
    response: dict[str, object] = {
        "schema": _RESPONSE_SCHEMA,
        "schema_version": _RESPONSE_SCHEMA_VERSION,
        "operation": operation,
        **body,
    }
    return response


def _validate_path_free_json(value: object) -> None:
    if isinstance(value, str):
        if _ABSOLUTE_PATH.search(value):
            raise ValueError("management response contains an absolute path")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_path_free_json(key)
            _validate_path_free_json(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_path_free_json(item)


def _encode_response(operation: str | None, result: object) -> bytes:
    response = _response_mapping(operation, result)
    _validate_path_free_json(response)
    return (
        json.dumps(
            response,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_all(stream: object, source: bytes) -> None:
    writer = getattr(stream, "write", None)
    if not callable(writer):
        raise TypeError("output stream must provide write")
    remaining = memoryview(source)
    while remaining:
        written = writer(remaining)
        if type(written) is not int or written <= 0 or written > remaining.nbytes:
            raise OSError("short output write")
        remaining = remaining[written:]
    flusher = getattr(stream, "flush", None)
    if callable(flusher):
        flusher()


def _emit_internal_failure(stderr: object) -> int:
    try:
        _write_all(stderr, _INTERNAL_FAILURE_LINE)
    except Exception:
        pass
    return 1


def _run_management_cli(
    argv: Sequence[str],
    *,
    stdout: object,
    stderr: object,
    path_policy: PathPolicy,
    executor: _ManagementExecutor = _execute_management_operation,
) -> int:
    try:
        invocation = _parse_cli_arguments(argv)
    except _ProtocolFailure as exc:
        try:
            _write_all(stdout, _encode_response(exc.operation, _failure_result()))
            return 2
        except Exception:
            return _emit_internal_failure(stderr)
    try:
        if not isinstance(path_policy, PathPolicy) or not callable(executor):
            raise TypeError("invalid management dependencies")
        result = executor(
            invocation.operation,
            invocation.arguments,
            path_policy=path_policy,
        )
        _write_all(stdout, _encode_response(invocation.operation, result))
        return 2 if isinstance(result, FailureResult) else 0
    except Exception:
        return _emit_internal_failure(stderr)


def main() -> int:
    """Run the installed P0B administration entry with binary stdout/stderr."""

    stderr = getattr(sys.stderr, "buffer", sys.stderr)
    try:
        stdout = sys.stdout.buffer
        path_policy = _production_path_policy()
    except Exception:
        return _emit_internal_failure(stderr)
    return _run_management_cli(
        sys.argv[1:],
        stdout=stdout,
        stderr=stderr,
        path_policy=path_policy,
    )


__all__: tuple[str, ...] = ()
