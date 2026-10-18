"""Stable public failures for the first curation slice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import re
from types import MappingProxyType


class CurationCommitState(StrEnum):
    NOT_COMMITTED = "not-committed"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


class CurationErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    SOURCE_INTEGRITY_FAILED = "source_integrity_failed"
    AUTHORIZATION_REQUIRED = "authorization_required"
    AUTHORIZATION_SCOPE_MISMATCH = "authorization_scope_mismatch"
    UNSUPPORTED_SOURCE = "unsupported_source"
    TARGET_NOT_CONFIRMED = "target_not_confirmed"
    TARGET_CONFLICT = "target_conflict"
    VERSION_CONTROL_UNAVAILABLE = "version_control_unavailable"
    LOCATOR_INVALID = "locator_invalid"
    EVIDENCE_INTEGRITY_FAILED = "evidence_integrity_failed"
    RANGE_LEDGER_INVALID = "range_ledger_invalid"
    PROCESSOR_OUTPUT_INVALID = "processor_output_invalid"
    BUDGET_EXHAUSTED = "budget_exhausted"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    ATOMIC_PUBLISH_FAILED = "atomic_publish_failed"
    RECOVERY_REQUIRED = "recovery_required"


_ERROR_MESSAGES: Mapping[CurationErrorCode, str] = {
    CurationErrorCode.INVALID_INPUT: "curation request input is invalid",
    CurationErrorCode.SOURCE_NOT_FOUND: "the exact curation source was not found",
    CurationErrorCode.SOURCE_IDENTITY_MISMATCH: (
        "source identity does not match the authorized version"
    ),
    CurationErrorCode.SOURCE_INTEGRITY_FAILED: (
        "curation source failed integrity verification"
    ),
    CurationErrorCode.AUTHORIZATION_REQUIRED: (
        "deep-processing authorization is required"
    ),
    CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH: (
        "requested processing exceeds the authorized scope"
    ),
    CurationErrorCode.UNSUPPORTED_SOURCE: "source type is not supported by CUR-MVP-1",
    CurationErrorCode.TARGET_NOT_CONFIRMED: (
        "a target decision is required before routing"
    ),
    CurationErrorCode.TARGET_CONFLICT: "target knowledge-base state conflicts with the request",
    CurationErrorCode.VERSION_CONTROL_UNAVAILABLE: (
        "managed local version control is unavailable"
    ),
    CurationErrorCode.LOCATOR_INVALID: "Evidence locator is invalid for the exact source",
    CurationErrorCode.EVIDENCE_INTEGRITY_FAILED: (
        "Evidence locator bytes failed integrity verification"
    ),
    CurationErrorCode.RANGE_LEDGER_INVALID: (
        "processing ranges do not explain the declared scope"
    ),
    CurationErrorCode.PROCESSOR_OUTPUT_INVALID: (
        "processor output does not satisfy the curation contract"
    ),
    CurationErrorCode.BUDGET_EXHAUSTED: (
        "the approved processing budget was exhausted"
    ),
    CurationErrorCode.IDEMPOTENCY_CONFLICT: (
        "curation identity refers to a different request"
    ),
    CurationErrorCode.ATOMIC_PUBLISH_FAILED: (
        "curation artifact publication did not complete safely"
    ),
    CurationErrorCode.RECOVERY_REQUIRED: (
        "curation state requires recovery before work can continue"
    ),
}

_SAFE_STAGE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_UUID7_ID = re.compile(
    r"(?:cap|run|map|kb|target|auth|seg|loc|cand|dset)_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12}\Z"
)
_INTEGER_FIELDS = frozenset(
    {
        "version",
        "start_byte",
        "end_byte",
        "maximum_bytes",
        "observed_bytes",
        "call_count",
        "input_tokens",
        "output_tokens",
    }
)
_ID_FIELDS = frozenset(
    {"capture_id", "curation_run_id", "map_id", "kb_id", "locator_id"}
)
_ALLOWED_DETAIL_FIELDS = _INTEGER_FIELDS | _ID_FIELDS | {"stage"}


def _freeze_details(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str or key not in _ALLOWED_DETAIL_FIELDS:
            raise ValueError("details contains an unsupported field")
        if key == "stage":
            if type(item) is not str or _SAFE_STAGE.fullmatch(item) is None:
                raise ValueError("details.stage must be a safe machine token")
        elif key in _ID_FIELDS:
            if type(item) is not str or _UUID7_ID.fullmatch(item) is None:
                raise ValueError(f"details.{key} must be a canonical typed UUIDv7")
        elif type(item) is not int or item < 0:
            raise ValueError(f"details.{key} must be a non-negative integer")
        frozen[key] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class CurationError:
    code: CurationErrorCode
    retryable: bool
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            code = CurationErrorCode(self.code)
        except ValueError as exc:
            raise ValueError("unknown curation error code") from exc
        object.__setattr__(self, "code", code)
        if type(self.retryable) is not bool:
            raise ValueError("retryable must be boolean")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", _freeze_details(self.details))

    @property
    def message(self) -> str:
        return _ERROR_MESSAGES[self.code]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class CurationFailure:
    error: CurationError
    commit_state: CurationCommitState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.error, CurationError):
            raise TypeError("error must be CurationError")
        if self.commit_state is not None:
            try:
                state = CurationCommitState(self.commit_state)
            except ValueError as exc:
                raise ValueError("unknown curation commit state") from exc
            if state is CurationCommitState.COMMITTED:
                raise ValueError("committed curation work must be returned as success")
            object.__setattr__(self, "commit_state", state)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"ok": False}
        if self.commit_state is not None:
            result["commit_state"] = self.commit_state.value
            if self.commit_state is CurationCommitState.NOT_COMMITTED:
                result["saved"] = False
        result["error"] = self.error.to_dict()
        return result


__all__ = [
    "CurationCommitState",
    "CurationError",
    "CurationErrorCode",
    "CurationFailure",
]
