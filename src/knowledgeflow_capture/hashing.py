"""Streaming and canonical SHA256 primitives for Capture Envelope v1."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
import hashlib
import hmac
import json
from typing import BinaryIO

from .codec import (
    SchemaValidationError,
    dump_envelope,
    dump_envelope_for_hash,
    load_envelope,
    validate_envelope,
)
from .models import (
    DigestResult,
    EnvelopeSeal,
    PayloadSetEntry,
    RequestFingerprint,
)


PAYLOAD_SET_DOMAIN = b"knowledgeflow.payload-set.v1\n"
REQUEST_FINGERPRINT_DOMAIN = b"knowledgeflow.request-fingerprint.v1\n"
DEFAULT_CHUNK_SIZE = 1024 * 1024


class ByteLimitExceeded(ValueError):
    def __init__(self, byte_size: int, maximum_bytes: int) -> None:
        super().__init__("stream exceeds the configured byte limit")
        self.byte_size = byte_size
        self.maximum_bytes = maximum_bytes


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def hash_bytes(value: bytes | bytearray | memoryview) -> DigestResult:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("value must be bytes-like")
    view = memoryview(value)
    digest = hashlib.sha256()
    digest.update(view)
    return DigestResult(
        byte_size=view.nbytes,
        sha256="sha256:" + digest.hexdigest(),
    )


def hash_utf8_text(value: str) -> DigestResult:
    if type(value) is not str:
        raise TypeError("value must be str")
    return hash_bytes(value.encode("utf-8"))


def hash_stream(
    stream: BinaryIO,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    maximum_bytes: int | None = None,
) -> DigestResult:
    """Hash a binary stream without issuing an unbounded read."""

    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    if maximum_bytes is not None and (
        type(maximum_bytes) is not int or maximum_bytes < 0
    ):
        raise ValueError("maximum_bytes must be a non-negative integer or null")
    if not hasattr(stream, "read"):
        raise TypeError("stream must provide read(size)")

    digest = hashlib.sha256()
    byte_size = 0
    while True:
        read_size = chunk_size
        if maximum_bytes is not None:
            read_size = min(chunk_size, (maximum_bytes - byte_size) + 1)
        chunk = stream.read(read_size)
        if chunk == b"":
            break
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("binary stream read() must return bytes-like values")
        view = memoryview(chunk)
        next_size = byte_size + view.nbytes
        if maximum_bytes is not None and next_size > maximum_bytes:
            raise ByteLimitExceeded(next_size, maximum_bytes)
        digest.update(view)
        byte_size = next_size
    return DigestResult(
        byte_size=byte_size,
        sha256="sha256:" + digest.hexdigest(),
    )


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalized_payload_entries(
    entries: Iterable[PayloadSetEntry],
) -> tuple[PayloadSetEntry, ...]:
    normalized = tuple(entries)
    if not normalized or not all(isinstance(item, PayloadSetEntry) for item in normalized):
        raise ValueError("entries must contain at least one PayloadSetEntry")
    ordinals = [entry.ordinal for entry in normalized]
    if len(ordinals) != len(set(ordinals)):
        raise ValueError("payload ordinals must be unique")
    return tuple(sorted(normalized, key=lambda item: item.ordinal))


def payload_set_canonical_json(entries: Iterable[PayloadSetEntry]) -> bytes:
    normalized = _normalized_payload_entries(entries)
    return _compact_json_bytes(
        [entry.as_canonical_mapping() for entry in normalized]
    )


def payload_set_sha256(entries: Iterable[PayloadSetEntry]) -> str:
    return _sha256(PAYLOAD_SET_DOMAIN + payload_set_canonical_json(entries))


def request_fingerprint_canonical_json(request: RequestFingerprint) -> bytes:
    if not isinstance(request, RequestFingerprint):
        raise TypeError("request must be RequestFingerprint")
    return _compact_json_bytes(request.as_canonical_mapping())


def request_fingerprint_sha256(request: RequestFingerprint) -> str:
    return _sha256(
        REQUEST_FINGERPRINT_DOMAIN + request_fingerprint_canonical_json(request)
    )


def _envelope_payload_set_sha256(envelope: Mapping[str, object]) -> str:
    payloads = envelope["payloads"]
    entries = tuple(
        PayloadSetEntry(
            ordinal=payload["ordinal"],
            role=payload["role"],
            kind=payload["kind"],
            media_type=payload["media_type"],
            byte_size=payload["byte_size"],
            sha256=payload["sha256"],
        )
        for payload in payloads
    )
    return payload_set_sha256(entries)


def _without_envelope_hash(envelope: Mapping[str, object]) -> dict[str, object]:
    candidate = deepcopy(dict(envelope))
    candidate.pop("envelope_sha256", None)
    return candidate


def envelope_sha256(envelope: Mapping[str, object]) -> str:
    if not isinstance(envelope, Mapping):
        raise TypeError("envelope must be a mapping")
    candidate = _without_envelope_hash(envelope)
    canonical = dump_envelope_for_hash(candidate)
    return _sha256(canonical)


def seal_envelope(envelope: Mapping[str, object]) -> EnvelopeSeal:
    """Validate, self-hash, and canonically emit an Envelope without mutating input."""

    if not isinstance(envelope, Mapping):
        raise TypeError("envelope must be a mapping")
    candidate = _without_envelope_hash(envelope)
    normalized = validate_envelope(candidate, require_hash=False)
    expected_payload_set = _envelope_payload_set_sha256(normalized)
    if not hmac.compare_digest(normalized["payload_set_sha256"], expected_payload_set):
        raise SchemaValidationError("$.payload_set_sha256 does not match payloads")

    digest = _sha256(dump_envelope_for_hash(normalized))
    sealed: dict[str, object] = deepcopy(normalized)
    sealed["envelope_sha256"] = digest
    final_envelope = validate_envelope(sealed)
    yaml_bytes = dump_envelope(final_envelope)
    return EnvelopeSeal(
        envelope=final_envelope,
        yaml_bytes=yaml_bytes,
        sha256=digest,
    )


def verify_envelope(envelope: Mapping[str, object]) -> bool:
    if not isinstance(envelope, Mapping):
        return False
    try:
        normalized = validate_envelope(envelope)
        expected_payload_set = _envelope_payload_set_sha256(normalized)
        if not hmac.compare_digest(
            normalized["payload_set_sha256"],
            expected_payload_set,
        ):
            return False
        expected_envelope = envelope_sha256(normalized)
        return hmac.compare_digest(normalized["envelope_sha256"], expected_envelope)
    except (KeyError, TypeError, ValueError, SchemaValidationError):
        return False


def verify_envelope_bytes(source: bytes | bytearray | memoryview) -> bool:
    try:
        envelope = load_envelope(source, require_canonical=True)
    except ValueError:
        return False
    return verify_envelope(envelope)


__all__ = [
    "ByteLimitExceeded",
    "DEFAULT_CHUNK_SIZE",
    "PAYLOAD_SET_DOMAIN",
    "REQUEST_FINGERPRINT_DOMAIN",
    "envelope_sha256",
    "hash_bytes",
    "hash_stream",
    "hash_utf8_text",
    "payload_set_canonical_json",
    "payload_set_sha256",
    "request_fingerprint_canonical_json",
    "request_fingerprint_sha256",
    "seal_envelope",
    "verify_envelope",
    "verify_envelope_bytes",
]
