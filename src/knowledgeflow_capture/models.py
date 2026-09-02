"""Immutable value objects used by the C1 deterministic primitives."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping
from uuid import UUID, RFC_4122


_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROCESSING_MODES = frozenset({"capture-only", "raw-source", "deep-curation"})


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
        _require_string(self.type, "channel.type")
        _require_string(self.instance_id, "channel.instance_id")
        _require_string(self.external_ref, "channel.external_ref", nullable=True)
        _require_string(
            self.source_created_at,
            "channel.source_created_at",
            nullable=True,
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
        if self.operation not in {"capture_text", "append_capture_version"}:
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
