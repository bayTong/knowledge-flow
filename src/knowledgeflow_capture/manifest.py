"""Capture Store v1 identity Manifest validation and canonical emission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import re

from .codec import (
    MappingSchema,
    ScalarSchema,
    SchemaField,
    SchemaValidationError,
    ValueSchema,
    YamlSyntaxGateError,
    dump_restricted_yaml,
    parse_restricted_yaml,
    validate_document,
)
from .errors import PublicErrorCode
from .ids import IdKind, validate_typed_id


CAPTURE_STORE_SCHEMA = "knowledgeflow.capture-store"
CAPTURE_STORE_SCHEMA_VERSION = 1
CAPTURE_STORE_LAYOUT_VERSION = 1

_UTC_MILLISECOND = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z"
)


class ManifestLoadError(ValueError):
    """A stable public classification for an unusable Store Manifest."""

    def __init__(self, code: PublicErrorCode) -> None:
        normalized = PublicErrorCode(code)
        if normalized not in {
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        }:
            raise ValueError("invalid Manifest error code")
        self.code = normalized
        super().__init__(normalized.value)


def _field(name: str, schema: ValueSchema) -> SchemaField:
    return SchemaField(name, schema)


def _validate_created_at(value: str, path: str) -> None:
    if _UTC_MILLISECOND.fullmatch(value) is None:
        raise SchemaValidationError(f"{path} must be canonical UTC milliseconds")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise SchemaValidationError(f"{path} is not a valid UTC timestamp") from exc


def _validate_manifest_values(value: object, path: str) -> None:
    manifest = value
    if not isinstance(manifest, Mapping):
        raise SchemaValidationError(f"{path} must be a mapping")
    try:
        validate_typed_id(manifest["store_id"], IdKind.STORE)
    except ValueError as exc:
        raise SchemaValidationError(f"{path}.store_id is not a valid Store UUIDv7") from exc
    _validate_created_at(manifest["created_at"], f"{path}.created_at")


CAPTURE_STORE_MANIFEST_SCHEMA_V1 = MappingSchema(
    (
        _field(
            "schema",
            ScalarSchema(str, allowed_values=(CAPTURE_STORE_SCHEMA,)),
        ),
        _field(
            "schema_version",
            ScalarSchema(int, allowed_values=(CAPTURE_STORE_SCHEMA_VERSION,)),
        ),
        _field("store_id", ScalarSchema(str, nonempty=True)),
        _field(
            "layout_version",
            ScalarSchema(int, allowed_values=(CAPTURE_STORE_LAYOUT_VERSION,)),
        ),
        _field("created_at", ScalarSchema(str, nonempty=True)),
    ),
    validator=_validate_manifest_values,
)


@dataclass(frozen=True, slots=True)
class CaptureStoreManifest:
    store_id: str
    created_at: str

    def __post_init__(self) -> None:
        try:
            validate_typed_id(self.store_id, IdKind.STORE)
            _validate_created_at(self.created_at, "$.created_at")
        except (ValueError, SchemaValidationError) as exc:
            raise ValueError("invalid Capture Store Manifest identity") from exc

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": CAPTURE_STORE_SCHEMA,
            "schema_version": CAPTURE_STORE_SCHEMA_VERSION,
            "store_id": self.store_id,
            "layout_version": CAPTURE_STORE_LAYOUT_VERSION,
            "created_at": self.created_at,
        }


def _uses_unsupported_identity(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    expected = {
        "schema": CAPTURE_STORE_SCHEMA,
        "schema_version": CAPTURE_STORE_SCHEMA_VERSION,
        "layout_version": CAPTURE_STORE_LAYOUT_VERSION,
    }
    expected_types = {"schema": str, "schema_version": int, "layout_version": int}
    for name, supported in expected.items():
        actual = value.get(name)
        if type(actual) is expected_types[name] and actual != supported:
            return True
    return False


def validate_capture_store_manifest(value: object) -> CaptureStoreManifest:
    """Validate a parsed Manifest and classify unsupported versions separately."""

    if _uses_unsupported_identity(value):
        raise ManifestLoadError(PublicErrorCode.UNSUPPORTED_STORE_VERSION)
    try:
        normalized = validate_document(value, CAPTURE_STORE_MANIFEST_SCHEMA_V1)
        return CaptureStoreManifest(
            store_id=normalized["store_id"],
            created_at=normalized["created_at"],
        )
    except (SchemaValidationError, TypeError, ValueError) as exc:
        raise ManifestLoadError(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY
        ) from exc


def dump_capture_store_manifest(manifest: CaptureStoreManifest) -> bytes:
    """Return canonical Manifest bytes without writing to the filesystem."""

    if not isinstance(manifest, CaptureStoreManifest):
        raise TypeError("manifest must be CaptureStoreManifest")
    return dump_restricted_yaml(
        manifest.as_mapping(),
        CAPTURE_STORE_MANIFEST_SCHEMA_V1,
    )


def _source_bytes(source: str | bytes | bytearray | memoryview) -> bytes:
    if type(source) is str:
        return source.encode("utf-8")
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    raise TypeError("Manifest source must be str or bytes")


def load_capture_store_manifest(
    source: str | bytes | bytearray | memoryview,
) -> CaptureStoreManifest:
    """Load a v1 Manifest, requiring its source bytes to be canonical."""

    try:
        parsed = parse_restricted_yaml(source)
    except YamlSyntaxGateError as exc:
        raise ManifestLoadError(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY
        ) from exc

    manifest = validate_capture_store_manifest(parsed)
    if dump_capture_store_manifest(manifest) != _source_bytes(source):
        raise ManifestLoadError(PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY)
    return manifest


__all__ = [
    "CAPTURE_STORE_LAYOUT_VERSION",
    "CAPTURE_STORE_MANIFEST_SCHEMA_V1",
    "CAPTURE_STORE_SCHEMA",
    "CAPTURE_STORE_SCHEMA_VERSION",
    "CaptureStoreManifest",
    "ManifestLoadError",
    "dump_capture_store_manifest",
    "load_capture_store_manifest",
    "validate_capture_store_manifest",
]
