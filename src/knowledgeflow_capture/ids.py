"""Stateless UUIDv7 generation with KnowledgeFlow type prefixes."""

from __future__ import annotations

from enum import StrEnum
import secrets
import time
from uuid import UUID, RFC_4122


_MAX_UNIX_TS_MS = (1 << 48) - 1
_RANDOM_BITS = 74
_RANDOM_MASK = (1 << _RANDOM_BITS) - 1


class IdKind(StrEnum):
    CAPTURE = "capture"
    EVENT = "event"
    STORE = "store"
    JOB = "job"


_PREFIXES = {
    IdKind.CAPTURE: "cap_",
    IdKind.EVENT: "evt_",
    IdKind.STORE: "store_",
    IdKind.JOB: "job_",
}


def generate_uuid7(
    *,
    unix_ts_ms: int | None = None,
    random_bytes: bytes | bytearray | memoryview | None = None,
) -> UUID:
    """Generate RFC 9562 UUIDv7 without monotonic or persisted clock state.

    Fixed inputs are exposed for deterministic tests. Production callers should omit
    both arguments so the observed system time and OS cryptographic randomness are used.
    """

    if unix_ts_ms is None:
        unix_ts_ms = time.time_ns() // 1_000_000
    if type(unix_ts_ms) is not int or not 0 <= unix_ts_ms <= _MAX_UNIX_TS_MS:
        raise ValueError("unix_ts_ms must be an unsigned 48-bit integer")

    if random_bytes is None:
        random_material = secrets.token_bytes(10)
    else:
        try:
            random_material = bytes(random_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("random_bytes must contain exactly 10 bytes") from exc
        if len(random_material) != 10:
            raise ValueError("random_bytes must contain exactly 10 bytes")

    random_74 = int.from_bytes(random_material, "big") & _RANDOM_MASK
    rand_a = random_74 >> 62
    rand_b = random_74 & ((1 << 62) - 1)

    value = (
        (unix_ts_ms << 80)
        | (0b0111 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return UUID(int=value)


def extract_unix_ts_ms(value: UUID | str) -> int:
    parsed = value if isinstance(value, UUID) else UUID(value)
    if parsed.version != 7 or parsed.variant != RFC_4122:
        raise ValueError("value is not an RFC UUIDv7")
    return (parsed.int >> 80) & _MAX_UNIX_TS_MS


def generate_typed_id(
    kind: IdKind | str,
    *,
    unix_ts_ms: int | None = None,
    random_bytes: bytes | bytearray | memoryview | None = None,
) -> str:
    try:
        normalized_kind = IdKind(kind)
    except ValueError as exc:
        raise ValueError("unknown KnowledgeFlow ID kind") from exc
    return _PREFIXES[normalized_kind] + str(
        generate_uuid7(unix_ts_ms=unix_ts_ms, random_bytes=random_bytes)
    )


def validate_typed_id(value: str, expected_kind: IdKind | str) -> UUID:
    try:
        kind = IdKind(expected_kind)
    except ValueError as exc:
        raise ValueError("unknown KnowledgeFlow ID kind") from exc
    if type(value) is not str or value != value.lower():
        raise ValueError("typed ID must be a lowercase string")
    prefix = _PREFIXES[kind]
    if not value.startswith(prefix):
        raise ValueError(f"typed ID must use the {prefix} prefix")
    uuid_text = value[len(prefix) :]
    try:
        parsed = UUID(uuid_text)
    except ValueError as exc:
        raise ValueError("typed ID contains an invalid UUID") from exc
    if str(parsed) != uuid_text:
        raise ValueError("typed ID UUID must use canonical hyphenated form")
    if parsed.version != 7 or parsed.variant != RFC_4122:
        raise ValueError("typed ID must contain an RFC UUIDv7")
    return parsed


def generate_capture_id(**kwargs: object) -> str:
    return generate_typed_id(IdKind.CAPTURE, **kwargs)


def generate_event_id(**kwargs: object) -> str:
    return generate_typed_id(IdKind.EVENT, **kwargs)


def generate_store_id(**kwargs: object) -> str:
    return generate_typed_id(IdKind.STORE, **kwargs)


def generate_job_id(**kwargs: object) -> str:
    return generate_typed_id(IdKind.JOB, **kwargs)


__all__ = [
    "IdKind",
    "extract_unix_ts_ms",
    "generate_capture_id",
    "generate_event_id",
    "generate_job_id",
    "generate_store_id",
    "generate_typed_id",
    "generate_uuid7",
    "validate_typed_id",
]
