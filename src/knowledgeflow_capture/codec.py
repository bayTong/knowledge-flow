"""Restricted YAML syntax, schema validation, and deterministic emission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, DirectiveToken, TagToken

from .ids import IdKind, validate_typed_id
from .models import (
    ChannelMetadata,
    canonical_idempotency_scope,
    require_canonical_utc_milliseconds,
)


class YamlSyntaxGateError(ValueError):
    """The input is outside KnowledgeFlow's safe YAML subset."""


class SchemaValidationError(ValueError):
    """The parsed value does not match its declared machine-file schema."""


class NonCanonicalYamlError(ValueError):
    """The data is valid but its source bytes are not canonical."""


class CaptureEventReferenceError(SchemaValidationError):
    """A valid capture.created document points at a different Envelope."""


SchemaValidator = Callable[[object, str], None]


class ValueSchema:
    def normalize(self, value: object, path: str) -> object:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ScalarSchema(ValueSchema):
    value_type: type
    allowed_values: tuple[object, ...] | None = None
    minimum: int | None = None
    nonempty: bool = False
    pattern: re.Pattern[str] | None = None

    def normalize(self, value: object, path: str) -> object:
        if type(value) is not self.value_type:
            raise SchemaValidationError(
                f"{path} must be {self.value_type.__name__}"
            )
        if self.allowed_values is not None and value not in self.allowed_values:
            raise SchemaValidationError(f"{path} is not an allowed v1 value")
        if self.minimum is not None and value < self.minimum:
            raise SchemaValidationError(f"{path} is below the allowed minimum")
        if self.nonempty and value == "":
            raise SchemaValidationError(f"{path} must not be empty")
        if self.pattern is not None and self.pattern.fullmatch(value) is None:
            raise SchemaValidationError(f"{path} has an invalid canonical form")
        return value


@dataclass(frozen=True, slots=True)
class NullableSchema(ValueSchema):
    inner: ValueSchema

    def normalize(self, value: object, path: str) -> object:
        if value is None:
            return None
        return self.inner.normalize(value, path)


@dataclass(frozen=True, slots=True)
class SequenceSchema(ValueSchema):
    item_schema: ValueSchema
    minimum_items: int = 0
    maximum_items: int | None = None
    validator: SchemaValidator | None = None

    def normalize(self, value: object, path: str) -> object:
        if type(value) is not list:
            raise SchemaValidationError(f"{path} must be list")
        if len(value) < self.minimum_items:
            raise SchemaValidationError(f"{path} contains too few items")
        if self.maximum_items is not None and len(value) > self.maximum_items:
            raise SchemaValidationError(f"{path} contains too many items")
        normalized = [
            self.item_schema.normalize(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
        if self.validator is not None:
            self.validator(normalized, path)
        return normalized


@dataclass(frozen=True, slots=True)
class SchemaField:
    name: str
    value_schema: ValueSchema
    required: bool = True


@dataclass(frozen=True, slots=True)
class MappingSchema(ValueSchema):
    fields: tuple[SchemaField, ...]
    validator: SchemaValidator | None = None

    def normalize(self, value: object, path: str) -> object:
        if not isinstance(value, Mapping):
            raise SchemaValidationError(f"{path} must be mapping")
        if any(type(key) is not str for key in value):
            raise SchemaValidationError(f"{path} keys must be strings")

        expected_names = {field.name for field in self.fields}
        unknown = set(value).difference(expected_names)
        if unknown:
            raise SchemaValidationError(f"{path} contains unknown fields")

        normalized: dict[str, object] = {}
        for schema_field in self.fields:
            if schema_field.name not in value:
                if schema_field.required:
                    raise SchemaValidationError(
                        f"{path}.{schema_field.name} is required"
                    )
                continue
            normalized[schema_field.name] = schema_field.value_schema.normalize(
                value[schema_field.name],
                f"{path}.{schema_field.name}",
            )
        if self.validator is not None:
            self.validator(normalized, path)
        return normalized


_STRING = ScalarSchema(str, nonempty=True)
_NULLABLE_STRING = NullableSchema(_STRING)
_POSITIVE_INTEGER = ScalarSchema(int, minimum=1)
_NONNEGATIVE_INTEGER = ScalarSchema(int, minimum=0)
_BOOLEAN = ScalarSchema(bool)
_NULL = ScalarSchema(type(None), allowed_values=(None,))
_SHA256 = ScalarSchema(
    str,
    pattern=re.compile(r"sha256:[0-9a-f]{64}\Z"),
)
_CAPTURE_ID = ScalarSchema(
    str,
    pattern=re.compile(
        r"cap_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
    ),
)
_EVENT_ID = ScalarSchema(
    str,
    pattern=re.compile(
        r"evt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
    ),
)


def _field(name: str, schema: ValueSchema, *, required: bool = True) -> SchemaField:
    return SchemaField(name, schema, required)


_ACTOR_SCHEMA = MappingSchema(
    (
        _field("type", ScalarSchema(str, allowed_values=("user",))),
        _field("actor_id", ScalarSchema(str, allowed_values=("local-user",))),
    )
)


def _validate_channel(value: object, path: str) -> None:
    channel = value
    try:
        ChannelMetadata(
            type=channel["type"],
            instance_id=channel["instance_id"],
            external_ref=channel["external_ref"],
            source_created_at=channel["source_created_at"],
        )
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(f"{path} contains invalid channel metadata") from exc


_CHANNEL_SCHEMA = MappingSchema(
    (
        _field("type", _STRING),
        _field("instance_id", _STRING),
        _field("external_ref", _NULLABLE_STRING),
        _field("source_created_at", _NULLABLE_STRING),
    ),
    validator=_validate_channel,
)

_IDEMPOTENCY_SCHEMA = MappingSchema(
    (
        _field("scope", _STRING),
        _field("key_sha256", _SHA256),
        _field("request_fingerprint_sha256", _SHA256),
    )
)


def _validate_payload(value: object, path: str) -> None:
    payload = value
    if payload["payload_id"] != payload["sha256"]:
        raise SchemaValidationError(f"{path}.payload_id must equal {path}.sha256")


_PAYLOAD_SCHEMA = MappingSchema(
    (
        _field("payload_id", _SHA256),
        _field("ordinal", _NONNEGATIVE_INTEGER),
        _field("role", ScalarSchema(str, allowed_values=("primary", "attachment"))),
        _field("kind", _STRING),
        _field("path", _STRING),
        _field("original_name", _NULLABLE_STRING),
        _field("media_type", _STRING),
        _field("encoding", _NULLABLE_STRING),
        _field(
            "fidelity",
            ScalarSchema(
                str,
                allowed_values=(
                    "byte-exact",
                    "channel-exact",
                    "canonical-snapshot",
                    "reference-only",
                ),
            ),
        ),
        _field("byte_size", _NONNEGATIVE_INTEGER),
        _field("sha256", _SHA256),
    ),
    validator=_validate_payload,
)


def _validate_payload_sequence(value: object, path: str) -> None:
    payloads = value
    ordinals = [payload["ordinal"] for payload in payloads]
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise SchemaValidationError(f"{path} ordinals must be unique and ascending")
    primary = [payload for payload in payloads if payload["role"] == "primary"]
    if len(primary) != 1 or primary[0]["ordinal"] != 0:
        raise SchemaValidationError(f"{path} must have one ordinal-0 primary")


_PAYLOADS_SCHEMA = SequenceSchema(
    _PAYLOAD_SCHEMA,
    minimum_items=1,
    validator=_validate_payload_sequence,
)

_EVIDENCE_SCHEMA = MappingSchema(
    (
        _field("event_id", _EVENT_ID),
        _field("payload_id", _SHA256),
    )
)

_USER_INTENT_SCHEMA = MappingSchema(
    (
        _field("target_kb_id", _NULLABLE_STRING),
        _field(
            "processing_mode",
            NullableSchema(
                ScalarSchema(
                    str,
                    allowed_values=("capture-only", "raw-source", "deep-curation"),
                )
            ),
        ),
        _field("requested_new_kb_name", _NULLABLE_STRING),
        _field("evidence", _EVIDENCE_SCHEMA),
    )
)

_ENVELOPE_SERIALIZATION_SCHEMA = MappingSchema(
    (
        _field("encoding", ScalarSchema(str, allowed_values=("utf-8",))),
        _field("line_endings", ScalarSchema(str, allowed_values=("lf",))),
        _field("bom", ScalarSchema(bool, allowed_values=(False,))),
        _field(
            "key_order",
            ScalarSchema(str, allowed_values=("schema-defined",)),
        ),
    )
)


def _validate_envelope(value: object, path: str) -> None:
    envelope = value
    try:
        validate_typed_id(envelope["capture_id"], IdKind.CAPTURE)
        validate_typed_id(envelope["event_id"], IdKind.EVENT)
    except ValueError as exc:
        raise SchemaValidationError(f"{path} contains an invalid typed UUIDv7") from exc

    for field_name in ("received_at", "captured_at"):
        try:
            require_canonical_utc_milliseconds(
                envelope[field_name],
                f"{path}.{field_name}",
            )
        except ValueError as exc:
            raise SchemaValidationError(str(exc)) from exc

    version = envelope["version"]
    previous = envelope["previous_version"]
    if version == 1 and previous is not None:
        raise SchemaValidationError(f"{path}.previous_version must be null for version 1")
    if version > 1 and previous != version - 1:
        raise SchemaValidationError(
            f"{path}.previous_version must identify the preceding version"
        )

    evidence = envelope["user_intent"]["evidence"]
    if evidence["event_id"] != envelope["event_id"]:
        raise SchemaValidationError(f"{path}.user_intent.evidence event mismatch")
    payload_ids = {payload["payload_id"] for payload in envelope["payloads"]}
    if evidence["payload_id"] not in payload_ids:
        raise SchemaValidationError(f"{path}.user_intent.evidence payload mismatch")

    idempotency = envelope["idempotency"]
    if idempotency is not None:
        operation = idempotency["scope"].rsplit(":", 1)[-1]
        try:
            expected_scope = canonical_idempotency_scope(
                ChannelMetadata(
                    type=envelope["channel"]["type"],
                    instance_id=envelope["channel"]["instance_id"],
                    external_ref=envelope["channel"]["external_ref"],
                    source_created_at=envelope["channel"]["source_created_at"],
                ),
                operation,
            )
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"{path}.idempotency.scope has an invalid canonical form"
            ) from exc
        if idempotency["scope"] != expected_scope:
            raise SchemaValidationError(
                f"{path}.idempotency.scope does not match channel"
            )


_ENVELOPE_BASE_FIELDS = (
    _field(
        "schema",
        ScalarSchema(str, allowed_values=("knowledgeflow.capture-envelope",)),
    ),
    _field("schema_version", ScalarSchema(int, allowed_values=(1,))),
    _field("capture_id", _CAPTURE_ID),
    _field("event_id", _EVENT_ID),
    _field("version", _POSITIVE_INTEGER),
    _field("previous_version", NullableSchema(_POSITIVE_INTEGER)),
    _field("received_at", _STRING),
    _field("captured_at", _STRING),
    _field("actor", _ACTOR_SCHEMA),
    _field("channel", _CHANNEL_SCHEMA),
    _field("idempotency", NullableSchema(_IDEMPOTENCY_SCHEMA)),
    _field("payloads", _PAYLOADS_SCHEMA),
    _field("payload_set_sha256", _SHA256),
    _field("user_intent", _USER_INTENT_SCHEMA),
    _field("delivery_requests", SequenceSchema(_STRING, maximum_items=0)),
    _field("envelope_serialization", _ENVELOPE_SERIALIZATION_SCHEMA),
)

ENVELOPE_PREHASH_SCHEMA_V1 = MappingSchema(
    _ENVELOPE_BASE_FIELDS,
    validator=_validate_envelope,
)
ENVELOPE_SCHEMA_V1 = MappingSchema(
    _ENVELOPE_BASE_FIELDS + (_field("envelope_sha256", _SHA256),),
    validator=_validate_envelope,
)


def _validate_capture_event_schema(value: object, path: str) -> None:
    event = value
    try:
        validate_typed_id(event["event_id"], IdKind.EVENT)
        validate_typed_id(event["capture_id"], IdKind.CAPTURE)
        require_canonical_utc_milliseconds(
            event["occurred_at"],
            f"{path}.occurred_at",
        )
    except ValueError as exc:
        raise SchemaValidationError(
            f"{path} contains an invalid capture.created identity or time"
        ) from exc


CAPTURE_EVENT_SCHEMA_V1 = MappingSchema(
    (
        _field(
            "schema",
            ScalarSchema(str, allowed_values=("knowledgeflow.capture-event",)),
        ),
        _field("schema_version", ScalarSchema(int, allowed_values=(1,))),
        _field("event_id", _EVENT_ID),
        _field("event_type", ScalarSchema(str, allowed_values=("capture.created",))),
        _field("capture_id", _CAPTURE_ID),
        _field("version", ScalarSchema(int, allowed_values=(1,))),
        _field("envelope_sha256", _SHA256),
        _field("occurred_at", _STRING),
        _field("actor", _ACTOR_SCHEMA),
    ),
    validator=_validate_capture_event_schema,
)

_DURABILITY_SCHEMA = MappingSchema(
    (
        _field("status", ScalarSchema(str, allowed_values=("durable",))),
        _field("verified_at", _STRING),
    )
)
_ROUTING_SCHEMA = MappingSchema(
    (
        _field("status", ScalarSchema(str, allowed_values=("unassigned",))),
        _field("target_kb_ids", SequenceSchema(_STRING, maximum_items=0)),
    )
)
_TRUST_SCHEMA = MappingSchema(
    (
        _field(
            "status",
            ScalarSchema(str, allowed_values=("unreviewed-capture",)),
        ),
    )
)
_GBRAIN_SCHEMA = MappingSchema(
    (
        _field("sync_status", ScalarSchema(str, allowed_values=("not-requested",))),
        _field("source_id", _NULL),
        _field("page_slug", _NULL),
        _field("mirrored_version", _NULL),
        _field("mirrored_envelope_sha256", _NULL),
    )
)
_BACKUP_SCHEMA = MappingSchema(
    (
        _field("git_status", ScalarSchema(str, allowed_values=("uncommitted",))),
        _field("commit", _NULL),
        _field("remote_status", ScalarSchema(str, allowed_values=("not-requested",))),
    )
)


def _validate_capture_state_schema(value: object, path: str) -> None:
    state = value
    try:
        validate_typed_id(state["capture_id"], IdKind.CAPTURE)
        require_canonical_utc_milliseconds(
            state["durability"]["verified_at"],
            f"{path}.durability.verified_at",
        )
        require_canonical_utc_milliseconds(
            state["updated_at"],
            f"{path}.updated_at",
        )
    except ValueError as exc:
        raise SchemaValidationError(
            f"{path} contains an invalid projection identity or time"
        ) from exc
    if state["durability"]["verified_at"] != state["updated_at"]:
        raise SchemaValidationError(
            f"{path}.updated_at must equal durability.verified_at for initial state"
        )


CAPTURE_STATE_SCHEMA_V1 = MappingSchema(
    (
        _field(
            "schema",
            ScalarSchema(str, allowed_values=("knowledgeflow.capture-state",)),
        ),
        _field("schema_version", ScalarSchema(int, allowed_values=(1,))),
        _field("capture_id", _CAPTURE_ID),
        _field("current_version", ScalarSchema(int, allowed_values=(1,))),
        _field("current_envelope_sha256", _SHA256),
        _field("durability", _DURABILITY_SCHEMA),
        _field("routing", _ROUTING_SCHEMA),
        _field("trust", _TRUST_SCHEMA),
        _field("gbrain", _GBRAIN_SCHEMA),
        _field("backup", _BACKUP_SCHEMA),
        _field("updated_at", _STRING),
    ),
    validator=_validate_capture_state_schema,
)

_SCHEMA_REGISTRY: Mapping[tuple[str, int], MappingSchema] = {
    ("knowledgeflow.capture-envelope", 1): ENVELOPE_SCHEMA_V1,
    ("knowledgeflow.capture-event", 1): CAPTURE_EVENT_SCHEMA_V1,
    ("knowledgeflow.capture-state", 1): CAPTURE_STATE_SCHEMA_V1,
}

_ALLOWED_SCALAR_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
    }
)
_PLAIN_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


def _decode_yaml_source(source: str | bytes | bytearray | memoryview) -> tuple[str, bytes]:
    if type(source) is str:
        if source.startswith("\ufeff"):
            raise YamlSyntaxGateError("YAML byte order mark is not allowed")
        return source, source.encode("utf-8")
    if isinstance(source, (bytes, bytearray, memoryview)):
        raw = bytes(source)
        if raw.startswith(b"\xef\xbb\xbf"):
            raise YamlSyntaxGateError("YAML byte order mark is not allowed")
        try:
            return raw.decode("utf-8"), raw
        except UnicodeDecodeError as exc:
            raise YamlSyntaxGateError("YAML must be valid UTF-8") from exc
    raise TypeError("YAML source must be str or bytes")


def _inspect_yaml_node(node: Node, path: str = "$") -> None:
    if isinstance(node, ScalarNode):
        if node.tag not in _ALLOWED_SCALAR_TAGS:
            raise YamlSyntaxGateError(f"{path} uses a disallowed YAML scalar type")
        return
    if isinstance(node, SequenceNode):
        if node.tag != "tag:yaml.org,2002:seq":
            raise YamlSyntaxGateError(f"{path} uses a disallowed YAML sequence tag")
        for index, item in enumerate(node.value):
            _inspect_yaml_node(item, f"{path}[{index}]")
        return
    if isinstance(node, MappingNode):
        if node.tag != "tag:yaml.org,2002:map":
            raise YamlSyntaxGateError(f"{path} uses a disallowed YAML mapping tag")
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise YamlSyntaxGateError(f"{path} has a non-string mapping key")
            key = key_node.value
            if key == "<<":
                raise YamlSyntaxGateError(f"{path} uses a YAML merge key")
            if key in seen:
                raise YamlSyntaxGateError(f"{path} has a duplicate mapping key")
            seen.add(key)
            _inspect_yaml_node(value_node, f"{path}.{key}")
        return
    raise YamlSyntaxGateError(f"{path} uses an unsupported YAML node")


def _parse_restricted_yaml(
    source: str | bytes | bytearray | memoryview,
) -> tuple[object, bytes]:
    text, raw = _decode_yaml_source(source)
    try:
        for token in yaml.scan(text, Loader=yaml.SafeLoader):
            if isinstance(token, (AnchorToken, AliasToken, TagToken, DirectiveToken)):
                raise YamlSyntaxGateError("YAML anchors, aliases, tags, and directives are not allowed")
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except YamlSyntaxGateError:
        raise
    except yaml.YAMLError as exc:
        raise YamlSyntaxGateError("invalid restricted YAML syntax") from exc

    if len(nodes) != 1 or nodes[0] is None:
        raise YamlSyntaxGateError("exactly one non-empty YAML document is required")
    _inspect_yaml_node(nodes[0])

    try:
        documents = list(yaml.load_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise YamlSyntaxGateError("invalid restricted YAML syntax") from exc
    if len(documents) != 1:
        raise YamlSyntaxGateError("exactly one YAML document is required")
    return documents[0], raw


def parse_restricted_yaml(source: str | bytes | bytearray | memoryview) -> object:
    """Apply only the syntax gate and return safe Python primitives."""

    value, _ = _parse_restricted_yaml(source)
    return value


def _schema_for_document(value: object) -> MappingSchema:
    if not isinstance(value, Mapping):
        raise SchemaValidationError("$ must be a mapping with schema identity")
    schema_name = value.get("schema")
    schema_version = value.get("schema_version")
    if type(schema_name) is not str or type(schema_version) is not int:
        raise SchemaValidationError("$.schema and $.schema_version are required")
    try:
        return _SCHEMA_REGISTRY[(schema_name, schema_version)]
    except KeyError as exc:
        raise SchemaValidationError("unknown schema or schema_version") from exc


def validate_document(
    value: object,
    schema: ValueSchema | None = None,
) -> object:
    selected = schema if schema is not None else _schema_for_document(value)
    return selected.normalize(value, "$")


def _render_inline(value: object) -> str | None:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is list and not value:
        return "[]"
    if isinstance(value, Mapping) and not value:
        return "{}"
    return None


def _validate_plain_key(key: str) -> None:
    if _PLAIN_KEY.fullmatch(key) is None or key == "<<":
        raise SchemaValidationError("schema contains a non-canonical YAML key")


def _emit_mapping_entry(key: str, value: object, indent: int) -> list[str]:
    _validate_plain_key(key)
    prefix = (" " * indent) + key + ":"
    inline = _render_inline(value)
    if inline is not None:
        return [prefix + " " + inline]
    return [prefix] + _emit_block(value, indent + 2)


def _emit_mapping(value: Mapping[str, object], indent: int) -> list[str]:
    lines: list[str] = []
    for key, item in value.items():
        lines.extend(_emit_mapping_entry(key, item, indent))
    return lines


def _emit_sequence(value: list[object], indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for item in value:
        inline = _render_inline(item)
        if inline is not None:
            lines.append(prefix + "- " + inline)
            continue
        if isinstance(item, Mapping):
            pairs = list(item.items())
            first_key, first_value = pairs[0]
            _validate_plain_key(first_key)
            first_inline = _render_inline(first_value)
            if first_inline is not None:
                lines.append(prefix + "- " + first_key + ": " + first_inline)
            else:
                lines.append(prefix + "- " + first_key + ":")
                lines.extend(_emit_block(first_value, indent + 4))
            for key, nested in pairs[1:]:
                lines.extend(_emit_mapping_entry(key, nested, indent + 2))
            continue
        if type(item) is list:
            lines.append(prefix + "-")
            lines.extend(_emit_sequence(item, indent + 2))
            continue
        raise SchemaValidationError("schema normalization produced an unsupported value")
    return lines


def _emit_block(value: object, indent: int) -> list[str]:
    if isinstance(value, Mapping):
        return _emit_mapping(value, indent)
    if type(value) is list:
        return _emit_sequence(value, indent)
    raise SchemaValidationError("schema normalization produced an unsupported block value")


def dump_restricted_yaml(
    value: object,
    schema: ValueSchema | None = None,
) -> bytes:
    """Validate and deterministically emit the restricted YAML subset."""

    normalized = validate_document(value, schema)
    inline = _render_inline(normalized)
    if inline is not None:
        text = inline
    else:
        text = "\n".join(_emit_block(normalized, 0))
    return (text + "\n").encode("utf-8")


def load_restricted_yaml(
    source: str | bytes | bytearray | memoryview,
    schema: ValueSchema | None = None,
    *,
    require_canonical: bool = False,
) -> object:
    value, raw = _parse_restricted_yaml(source)
    normalized = validate_document(value, schema)
    if require_canonical and dump_restricted_yaml(normalized, schema) != raw:
        raise NonCanonicalYamlError("YAML bytes do not match canonical serialization")
    return normalized


def validate_envelope(value: object, *, require_hash: bool = True) -> dict[str, object]:
    schema = ENVELOPE_SCHEMA_V1 if require_hash else ENVELOPE_PREHASH_SCHEMA_V1
    normalized = validate_document(value, schema)
    return normalized


def dump_envelope(value: object) -> bytes:
    return dump_restricted_yaml(value, ENVELOPE_SCHEMA_V1)


def dump_envelope_for_hash(value: object) -> bytes:
    return dump_restricted_yaml(value, ENVELOPE_PREHASH_SCHEMA_V1)


def load_envelope(
    source: str | bytes | bytearray | memoryview,
    *,
    require_canonical: bool = True,
) -> dict[str, object]:
    return load_restricted_yaml(
        source,
        ENVELOPE_SCHEMA_V1,
        require_canonical=require_canonical,
    )


def _validated_reference_envelope(value: object) -> dict[str, object]:
    try:
        return validate_envelope(value)
    except (TypeError, ValueError, SchemaValidationError) as exc:
        raise SchemaValidationError("envelope reference is not a valid v1 Envelope") from exc


def _validate_capture_event_references(
    event: Mapping[str, object],
    envelope: Mapping[str, object],
) -> None:
    fields = (
        ("event_id", "event_id"),
        ("capture_id", "capture_id"),
        ("version", "version"),
        ("envelope_sha256", "envelope_sha256"),
        ("actor", "actor"),
    )
    for event_field, envelope_field in fields:
        if event[event_field] != envelope[envelope_field]:
            raise CaptureEventReferenceError(
                f"$.{event_field} does not match the referenced Envelope"
            )


def validate_capture_event(
    value: object,
    *,
    envelope: object,
) -> dict[str, object]:
    """Validate capture.created schema and all immutable Envelope references."""

    normalized = validate_document(value, CAPTURE_EVENT_SCHEMA_V1)
    normalized_envelope = _validated_reference_envelope(envelope)
    _validate_capture_event_references(normalized, normalized_envelope)
    return normalized


def dump_capture_event(value: object, *, envelope: object) -> bytes:
    normalized = validate_capture_event(value, envelope=envelope)
    return dump_restricted_yaml(normalized, CAPTURE_EVENT_SCHEMA_V1)


def load_capture_event(
    source: str | bytes | bytearray | memoryview,
    *,
    envelope: object,
    require_canonical: bool = True,
) -> dict[str, object]:
    normalized = load_restricted_yaml(
        source,
        CAPTURE_EVENT_SCHEMA_V1,
        require_canonical=require_canonical,
    )
    normalized_envelope = _validated_reference_envelope(envelope)
    _validate_capture_event_references(normalized, normalized_envelope)
    return normalized


def _validate_capture_state_references(
    state: Mapping[str, object],
    envelope: Mapping[str, object],
) -> None:
    fields = (
        ("capture_id", "capture_id"),
        ("current_version", "version"),
        ("current_envelope_sha256", "envelope_sha256"),
    )
    for state_field, envelope_field in fields:
        if state[state_field] != envelope[envelope_field]:
            raise SchemaValidationError(
                f"$.{state_field} does not match the referenced Envelope"
            )


def validate_capture_state(
    value: object,
    *,
    envelope: object,
) -> dict[str, object]:
    """Validate the complete fixed C3 initial projection and its reference."""

    normalized = validate_document(value, CAPTURE_STATE_SCHEMA_V1)
    normalized_envelope = _validated_reference_envelope(envelope)
    _validate_capture_state_references(normalized, normalized_envelope)
    return normalized


def dump_capture_state(value: object, *, envelope: object) -> bytes:
    normalized = validate_capture_state(value, envelope=envelope)
    return dump_restricted_yaml(normalized, CAPTURE_STATE_SCHEMA_V1)


def load_capture_state(
    source: str | bytes | bytearray | memoryview,
    *,
    envelope: object,
    require_canonical: bool = True,
) -> dict[str, object]:
    normalized = load_restricted_yaml(
        source,
        CAPTURE_STATE_SCHEMA_V1,
        require_canonical=require_canonical,
    )
    normalized_envelope = _validated_reference_envelope(envelope)
    _validate_capture_state_references(normalized, normalized_envelope)
    return normalized


__all__ = [
    "CAPTURE_EVENT_SCHEMA_V1",
    "CAPTURE_STATE_SCHEMA_V1",
    "CaptureEventReferenceError",
    "ENVELOPE_PREHASH_SCHEMA_V1",
    "ENVELOPE_SCHEMA_V1",
    "MappingSchema",
    "NonCanonicalYamlError",
    "NullableSchema",
    "ScalarSchema",
    "SchemaField",
    "SchemaValidationError",
    "SequenceSchema",
    "ValueSchema",
    "YamlSyntaxGateError",
    "dump_envelope",
    "dump_envelope_for_hash",
    "dump_capture_event",
    "dump_capture_state",
    "dump_restricted_yaml",
    "load_envelope",
    "load_capture_event",
    "load_capture_state",
    "load_restricted_yaml",
    "parse_restricted_yaml",
    "validate_document",
    "validate_capture_event",
    "validate_capture_state",
    "validate_envelope",
]
