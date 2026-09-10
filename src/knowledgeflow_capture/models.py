"""Immutable value objects used by the C1 deterministic primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Mapping, Protocol
from uuid import UUID, RFC_4122


_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROCESSING_MODES = frozenset({"capture-only", "raw-source", "deep-curation"})
_CHANNEL_TOKEN_PATTERN = re.compile(r"[a-z0-9._-]{1,64}\Z")
_UTC_MILLISECOND_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z"
)
_WRITE_OPERATIONS = frozenset({"capture_text", "append_capture_version"})
_MAX_EXTERNAL_REF_BYTES = 2048
_MAX_IDEMPOTENCY_KEY_BYTES = 512


class BinaryReadable(Protocol):
    """One-pass binary input accepted by the capture operation boundary."""

    def read(self, size: int = -1, /) -> bytes:
        ...


def is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None


def require_sha256(value: object, field_name: str) -> str:
    if not is_sha256(value):
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex digits>")
    return value


def _require_string(value: object, field_name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or not value:
        suffix = " or null" if nullable else ""
        raise ValueError(f"{field_name} must be a non-empty string{suffix}")
    return value


def _require_nonnegative_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_channel_token(value: object, field_name: str) -> str:
    if type(value) is not str or _CHANNEL_TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a 1-64 character lowercase ASCII token"
        )
    return value


def _require_optional_bounded_utf8(
    value: object,
    field_name: str,
    *,
    maximum_bytes: int,
) -> str | None:
    normalized = _require_string(value, field_name, nullable=True)
    if normalized is not None and len(normalized.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field_name} exceeds its UTF-8 byte limit")
    return normalized


def require_canonical_utc_milliseconds(value: object, field_name: str) -> str:
    """Require a real UTC timestamp in the exact v1 millisecond form."""

    if type(value) is not str or _UTC_MILLISECOND_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be canonical UTC milliseconds")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid UTC timestamp") from exc
    return value


def format_utc_milliseconds(value: datetime) -> str:
    """Format one aware clock sample as canonical UTC milliseconds."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("value must be an aware datetime")
    utc = value.astimezone(timezone.utc)
    milliseconds = (utc.microsecond // 1000) * 1000
    return utc.replace(microsecond=milliseconds).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def require_idempotency_key(value: object) -> str:
    """Validate a caller key before its raw value reaches hashing or storage."""

    if type(value) is not str:
        raise TypeError("idempotency_key must be a string")
    if not value:
        raise ValueError("idempotency_key must be a non-empty string")
    if len(value.encode("utf-8")) > _MAX_IDEMPOTENCY_KEY_BYTES:
        raise ValueError("idempotency_key exceeds its UTF-8 byte limit")
    return value


def canonical_idempotency_scope(
    channel: ChannelMetadata,
    operation: str,
) -> str:
    """Return the unambiguous v1 scope for a validated channel and operation."""

    if not isinstance(channel, ChannelMetadata):
        raise TypeError("channel must be ChannelMetadata")
    if operation not in _WRITE_OPERATIONS:
        raise ValueError("operation is not a supported write operation")
    return f"{channel.type}:{channel.instance_id}:{operation}"


def _require_capture_id(value: object) -> str:
    if type(value) is not str or not value.startswith("cap_") or value != value.lower():
        raise ValueError("capture_id must use the cap_ UUIDv7 form")
    try:
        parsed = UUID(value[4:])
    except (ValueError, AttributeError) as exc:
        raise ValueError("capture_id must use the cap_ UUIDv7 form") from exc
    if str(parsed) != value[4:] or parsed.version != 7 or parsed.variant != RFC_4122:
        raise ValueError("capture_id must use the cap_ UUIDv7 form")
    return value


@dataclass(frozen=True, slots=True)
class DigestResult:
    """Byte count and SHA256 computed during one streaming pass."""

    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        _require_nonnegative_integer(self.byte_size, "byte_size")
        require_sha256(self.sha256, "sha256")


@dataclass(frozen=True, slots=True)
class PayloadSetEntry:
    """The exact fields included in Payload Set canonical JSON."""

    ordinal: int
    role: str
    kind: str
    media_type: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        _require_nonnegative_integer(self.ordinal, "ordinal")
        _require_string(self.role, "role")
        _require_string(self.kind, "kind")
        _require_string(self.media_type, "media_type")
        _require_nonnegative_integer(self.byte_size, "byte_size")
        require_sha256(self.sha256, "sha256")

    def as_canonical_mapping(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "role": self.role,
            "kind": self.kind,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PayloadMetadata:
    ordinal: int
    original_name: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_integer(self.ordinal, "ordinal")
        _require_string(self.original_name, "original_name", nullable=True)

    def as_canonical_mapping(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "original_name": self.original_name,
        }


@dataclass(frozen=True, slots=True)
class ChannelMetadata:
    type: str
    instance_id: str
    external_ref: str | None = None
    source_created_at: str | None = None

    def __post_init__(self) -> None:
        _require_channel_token(self.type, "channel.type")
        _require_channel_token(self.instance_id, "channel.instance_id")
        _require_optional_bounded_utf8(
            self.external_ref,
            "channel.external_ref",
            maximum_bytes=_MAX_EXTERNAL_REF_BYTES,
        )
        if self.source_created_at is not None:
            require_canonical_utc_milliseconds(
                self.source_created_at,
                "channel.source_created_at",
            )

    def as_canonical_mapping(self) -> dict[str, object]:
        return {
            "type": self.type,
            "instance_id": self.instance_id,
            "external_ref": self.external_ref,
            "source_created_at": self.source_created_at,
        }


@dataclass(frozen=True, slots=True)
class UserIntent:
    target_kb_id: str | None = None
    processing_mode: str | None = None
    requested_new_kb_name: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.target_kb_id, "target_kb_id", nullable=True)
        _require_string(self.processing_mode, "processing_mode", nullable=True)
        _require_string(
            self.requested_new_kb_name,
            "requested_new_kb_name",
            nullable=True,
        )
        if self.processing_mode is not None and self.processing_mode not in _PROCESSING_MODES:
            raise ValueError("processing_mode is not a supported v1 value")

    def as_canonical_mapping(self) -> dict[str, object]:
        return {
            "target_kb_id": self.target_kb_id,
            "processing_mode": self.processing_mode,
            "requested_new_kb_name": self.requested_new_kb_name,
        }


@dataclass(frozen=True, slots=True)
class CaptureTextRequest:
    """Validated caller-controlled inputs, excluding server-owned fields."""

    text: str | BinaryReadable
    channel: ChannelMetadata
    idempotency_key: str | None = None
    user_intent: UserIntent | None = None

    def __post_init__(self) -> None:
        if type(self.text) is str:
            if not self.text:
                raise ValueError("text must not be empty")
            if self.text.startswith("\ufeff"):
                raise ValueError("text must not begin with a byte order mark")
        elif not callable(getattr(self.text, "read", None)):
            raise TypeError("text must be str or provide read(size)")
        if not isinstance(self.channel, ChannelMetadata):
            raise TypeError("channel must be ChannelMetadata")
        if self.idempotency_key is not None:
            require_idempotency_key(self.idempotency_key)
        intent = self.user_intent if self.user_intent is not None else UserIntent()
        if not isinstance(intent, UserIntent):
            raise TypeError("user_intent must be UserIntent or null")
        object.__setattr__(self, "user_intent", intent)


@dataclass(frozen=True, slots=True)
class RequestFingerprint:
    """Caller-controlled fields that determine write-request identity."""

    operation: str
    payload_set_sha256: str
    channel: ChannelMetadata
    payload_metadata: tuple[PayloadMetadata, ...]
    user_intent: UserIntent
    capture_id: str | None = None
    expected_current_version: int | None = None

    def __post_init__(self) -> None:
        if self.operation not in _WRITE_OPERATIONS:
            raise ValueError("operation must be capture_text or append_capture_version")
        require_sha256(self.payload_set_sha256, "payload_set_sha256")
        if not isinstance(self.channel, ChannelMetadata):
            raise TypeError("channel must be ChannelMetadata")
        if not isinstance(self.user_intent, UserIntent):
            raise TypeError("user_intent must be UserIntent")

        metadata = tuple(self.payload_metadata)
        if not metadata or not all(isinstance(item, PayloadMetadata) for item in metadata):
            raise ValueError("payload_metadata must contain at least one PayloadMetadata")
        ordinals = [item.ordinal for item in metadata]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("payload_metadata ordinals must be unique")
        if any(item.original_name is not None for item in metadata):
            raise ValueError("MVP-0 text payload original_name must be null")
        object.__setattr__(self, "payload_metadata", metadata)

        if self.operation == "capture_text":
            if self.capture_id is not None or self.expected_current_version is not None:
                raise ValueError(
                    "capture_text fingerprint requires null capture_id and expected_current_version"
                )
        else:
            _require_capture_id(self.capture_id)
            _require_positive_integer(
                self.expected_current_version,
                "expected_current_version",
            )

    def as_canonical_mapping(self) -> dict[str, object]:
        metadata = sorted(self.payload_metadata, key=lambda item: item.ordinal)
        return {
            "operation": self.operation,
            "payload_set_sha256": self.payload_set_sha256,
            "channel": self.channel.as_canonical_mapping(),
            "payload_metadata": [item.as_canonical_mapping() for item in metadata],
            "user_intent": self.user_intent.as_canonical_mapping(),
            "capture_id": self.capture_id,
            "expected_current_version": self.expected_current_version,
        }


@dataclass(frozen=True, slots=True)
class EnvelopeSeal:
    """A validated Envelope together with its deterministic serialized bytes."""

    envelope: Mapping[str, object]
    yaml_bytes: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, Mapping):
            raise TypeError("envelope must be a mapping")
        if type(self.yaml_bytes) is not bytes:
            raise TypeError("yaml_bytes must be bytes")
        require_sha256(self.sha256, "sha256")


__all__ = [
    "BinaryReadable",
    "CaptureTextRequest",
    "ChannelMetadata",
    "DigestResult",
    "EnvelopeSeal",
    "PayloadMetadata",
    "PayloadSetEntry",
    "RequestFingerprint",
    "UserIntent",
    "canonical_idempotency_scope",
    "format_utc_milliseconds",
    "is_sha256",
    "require_canonical_utc_milliseconds",
    "require_idempotency_key",
    "require_sha256",
]
