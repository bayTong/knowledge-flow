"""Stable public failures and warnings for the capture operation boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any


class CommitState(StrEnum):
    NOT_COMMITTED = "not-committed"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


class PublicErrorCode(StrEnum):
    CONFIG_NOT_FOUND = "config_not_found"
    CONFIG_INVALID = "config_invalid"
    CAPTURE_STORE_NOT_INITIALIZED = "capture_store_not_initialized"
    CAPTURE_STORE_UNAVAILABLE = "capture_store_unavailable"
    INVALID_INPUT = "invalid_input"
    TEXT_TOO_LARGE = "text_too_large"
    CAPTURE_NOT_FOUND = "capture_not_found"
    VERSION_NOT_FOUND = "version_not_found"
    VERSION_CONFLICT = "version_conflict"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INTEGRITY_CHECK_FAILED = "integrity_check_failed"
    ATOMIC_COMMIT_FAILED = "atomic_commit_failed"


class CauseCode(StrEnum):
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"
    PAYLOAD_SET_HASH_MISMATCH = "payload_set_hash_mismatch"
    ENVELOPE_HASH_MISMATCH = "envelope_hash_mismatch"
    BYTE_SIZE_MISMATCH = "byte_size_mismatch"
    PAYLOAD_READ_FAILED = "payload_read_failed"
    PAYLOAD_WRITE_FAILED = "payload_write_failed"
    PROJECTION_UPDATE_FAILED = "projection_update_failed"
    OUTBOX_PROJECTION_FAILED = "outbox_projection_failed"


class WarningCode(StrEnum):
    PROJECTION_NEEDS_REBUILD = "projection_needs_rebuild"
    OUTBOX_NEEDS_REBUILD = "outbox_needs_rebuild"


_ERROR_MESSAGES: Mapping[PublicErrorCode, str] = {
    PublicErrorCode.CONFIG_NOT_FOUND: "capture configuration was not found",
    PublicErrorCode.CONFIG_INVALID: "capture configuration is invalid",
    PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED: "capture store is not initialized",
    PublicErrorCode.CAPTURE_STORE_UNAVAILABLE: "capture store is unavailable",
    PublicErrorCode.INVALID_INPUT: "request input is invalid",
    PublicErrorCode.TEXT_TOO_LARGE: "text exceeds the configured safety limit",
    PublicErrorCode.CAPTURE_NOT_FOUND: "capture was not found",
    PublicErrorCode.VERSION_NOT_FOUND: "capture version was not found",
    PublicErrorCode.VERSION_CONFLICT: "capture version changed since it was read",
    PublicErrorCode.IDEMPOTENCY_CONFLICT: "idempotency key refers to a different request",
    PublicErrorCode.INTEGRITY_CHECK_FAILED: "stored data failed integrity verification",
    PublicErrorCode.ATOMIC_COMMIT_FAILED: "atomic capture commit failed",
}

_WARNING_MESSAGES: Mapping[WarningCode, str] = {
    WarningCode.PROJECTION_NEEDS_REBUILD: "capture state projection needs rebuild",
    WarningCode.OUTBOX_NEEDS_REBUILD: "outbox projection needs rebuild",
}

_INTEGRITY_CAUSES = frozenset(
    {
        CauseCode.PAYLOAD_HASH_MISMATCH,
        CauseCode.PAYLOAD_SET_HASH_MISMATCH,
        CauseCode.ENVELOPE_HASH_MISMATCH,
        CauseCode.BYTE_SIZE_MISMATCH,
    }
)
_POST_COMMIT_CAUSES = frozenset(
    {
        CauseCode.PROJECTION_UPDATE_FAILED,
        CauseCode.OUTBOX_PROJECTION_FAILED,
    }
)

_FORBIDDEN_DIAGNOSTIC_KEYS = frozenset(
    {
        "api_key",
        "body",
        "capture_root",
        "content",
        "credential",
        "credentials",
        "file_path",
        "idempotency_key",
        "password",
        "path",
        "payload",
        "preview",
        "raw_idempotency_key",
        "secret",
        "text",
        "token",
    }
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?:^|[\s\"'=(])/(?!/)")
_FORBIDDEN_DIAGNOSTIC_KEY_TOKENS = frozenset(
    re.sub(r"[^a-z0-9]", "", key.casefold())
    for key in _FORBIDDEN_DIAGNOSTIC_KEYS
)
_RESERVED_SUCCESS_KEYS = frozenset({"ok", "saved", "commit_state", "warnings"})


def _freeze_safe_json(value: object, *, key_path: str = "details") -> object:
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is str:
        if len(value) > 512 or "\n" in value or "\r" in value:
            raise ValueError(f"{key_path} contains an unsafe diagnostic string")
        if _WINDOWS_ABSOLUTE_PATH.search(value) or _POSIX_ABSOLUTE_PATH.search(value):
            raise ValueError(f"{key_path} must not contain an absolute path")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{key_path} keys must be strings")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized_key in _FORBIDDEN_DIAGNOSTIC_KEY_TOKENS:
                raise ValueError(f"{key_path} contains forbidden field {key!r}")
            frozen[key] = _freeze_safe_json(item, key_path=f"{key_path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            _freeze_safe_json(item, key_path=f"{key_path}[]") for item in value
        )
    raise ValueError(f"{key_path} contains a non-JSON or unsafe value")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class OperationError:
    code: PublicErrorCode
    retryable: bool
    cause_code: CauseCode | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            code = PublicErrorCode(self.code)
        except ValueError as exc:
            raise ValueError("unknown public error code") from exc
        object.__setattr__(self, "code", code)
        if self.cause_code is not None:
            try:
                cause = CauseCode(self.cause_code)
            except ValueError as exc:
                raise ValueError("unknown internal cause code") from exc
            object.__setattr__(self, "cause_code", cause)
        if self.cause_code in _POST_COMMIT_CAUSES:
            raise ValueError("post-commit projection causes must be returned as warnings")
        if self.code is PublicErrorCode.INTEGRITY_CHECK_FAILED:
            if self.cause_code not in _INTEGRITY_CAUSES:
                raise ValueError("integrity_check_failed requires an integrity cause_code")
        elif self.cause_code in _INTEGRITY_CAUSES:
            raise ValueError("integrity mismatch causes require integrity_check_failed")
        if type(self.retryable) is not bool:
            raise ValueError("retryable must be boolean")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", _freeze_safe_json(self.details))

    @property
    def message(self) -> str:
        return _ERROR_MESSAGES[self.code]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "cause_code": self.cause_code.value if self.cause_code else None,
            "message": self.message,
            "retryable": self.retryable,
            "details": _thaw_json(self.details),
        }


@dataclass(frozen=True, slots=True)
class OperationWarning:
    code: WarningCode
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            code = WarningCode(self.code)
        except ValueError as exc:
            raise ValueError("unknown public warning code") from exc
        object.__setattr__(self, "code", code)
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", _freeze_safe_json(self.details))

    @property
    def message(self) -> str:
        return _WARNING_MESSAGES[self.code]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": _thaw_json(self.details),
        }


@dataclass(frozen=True, slots=True)
class FailureResult:
    error: OperationError
    commit_state: CommitState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.error, OperationError):
            raise TypeError("error must be OperationError")
        if self.commit_state is not None:
            try:
                state = CommitState(self.commit_state)
            except ValueError as exc:
                raise ValueError("unknown commit state") from exc
            if state is CommitState.COMMITTED:
                raise ValueError("a committed write must be returned as success with warnings")
            object.__setattr__(self, "commit_state", state)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"ok": False}
        if self.commit_state is not None:
            result["commit_state"] = self.commit_state.value
        result["error"] = self.error.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class CommittedWriteResult:
    receipt: Mapping[str, object] = field(default_factory=dict)
    warnings: tuple[OperationWarning, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, Mapping):
            raise ValueError("receipt must be a mapping")
        reserved = _RESERVED_SUCCESS_KEYS.intersection(self.receipt)
        if reserved:
            raise ValueError("receipt must not override operation result fields")
        object.__setattr__(self, "receipt", _freeze_safe_json(self.receipt, key_path="receipt"))
        warnings = tuple(self.warnings)
        if not all(isinstance(warning, OperationWarning) for warning in warnings):
            raise TypeError("warnings must contain OperationWarning values")
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": True,
            "saved": True,
            "commit_state": CommitState.COMMITTED.value,
        }
        result.update(_thaw_json(self.receipt))
        result["warnings"] = [warning.to_dict() for warning in self.warnings]
        return result


__all__ = [
    "CauseCode",
    "CommitState",
    "CommittedWriteResult",
    "FailureResult",
    "OperationError",
    "OperationWarning",
    "PublicErrorCode",
    "WarningCode",
]
