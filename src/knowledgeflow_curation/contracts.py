"""Immutable value objects for the first governed curation slice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import re
from uuid import RFC_4122, UUID

from knowledgeflow_capture.ids import IdKind, validate_typed_id
from knowledgeflow_capture.models import (
    require_canonical_utc_milliseconds,
    require_sha256,
)


EXPERIMENT_SEGMENTATION_PROFILE_ID = "experiment-markdown-blocks"
EXPERIMENT_SEGMENTATION_PROFILE_REVISION = 1
EXPERIMENT_TARGET_BYTES = 16 * 1024
EXPERIMENT_MAX_BYTES = 32 * 1024

_MAX_CAPTURE_VERSION = 999999
_MAX_TEXT_BYTES = 16 * 1024
_MAX_SHORT_TEXT_BYTES = 512
_MAX_COLLECTION_ITEMS = 100000
_SAFE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MARKDOWN_ANCHOR = re.compile(r"[a-z0-9][a-z0-9-]{0,127}\Z")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_STORAGE_NAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_WINDOWS_RESERVED_STORAGE_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

_CANDIDATE_KINDS = frozenset(
    {
        "overview",
        "structure",
        "claim",
        "concept",
        "relationship",
        "dispute",
        "limitation",
        "gap",
        "organization",
    }
)
_EVIDENCE_OPTIONAL_KINDS = frozenset({"gap", "organization"})
_PROVENANCE_VALUES = frozenset(
    {
        "source-claim",
        "quoted-claim",
        "processor-inference",
        "user-revision",
        "unverified",
    }
)
_UNCERTAINTY_VALUES = frozenset({"none", "low", "medium", "high", "unknown"})
_SCOPE_STATUSES = frozenset(
    {"processed", "deferred", "failed", "excluded-by-user"}
)
_PROCESSOR_KINDS = frozenset({"mechanical", "test-fixture", "file-exchange"})
_RUN_STATES = frozenset({"authorized", "processing", "failed", "cancelled"})
_DECISION_ACTIONS = frozenset({"accept", "reject", "defer", "modify"})
_DECISION_OUTCOMES = frozenset(
    {"map-closed", "revision-requested", "change-requested", "deferred"}
)


class CurationOperation(StrEnum):
    SOURCE_PREPARE = "source.prepare"
    SOURCE_INSPECT = "source.inspect"
    EVIDENCE_SHOW = "evidence.show"
    TARGET_DECIDE = "target.decide"
    MAP_BUILD = "map.build"
    MAP_DECIDE = "map.decide"
    MAP_CLOSE = "map.close"


def _require_exact_keys(
    value: object,
    expected: set[str],
    field_name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{field_name} must be a string-keyed mapping")
    if set(value) != expected:
        raise ValueError(f"{field_name} must contain the exact v1 fields")
    return value


def _require_string(
    value: object,
    field_name: str,
    *,
    maximum_bytes: int = _MAX_TEXT_BYTES,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or not value or value != value.strip():
        suffix = " or null" if nullable else ""
        raise ValueError(f"{field_name} must be a non-empty trimmed string{suffix}")
    if "\x00" in value or "\r" in value:
        raise ValueError(f"{field_name} contains unsupported control characters")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field_name} exceeds its UTF-8 byte limit")
    return value


def _require_token(value: object, field_name: str) -> str:
    if type(value) is not str or _SAFE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe lowercase token")
    return value


def _require_single_line_string(
    value: object,
    field_name: str,
    *,
    maximum_bytes: int = _MAX_SHORT_TEXT_BYTES,
) -> str:
    checked = _require_string(
        value,
        field_name,
        maximum_bytes=maximum_bytes,
    )
    assert isinstance(checked, str)
    if "\n" in checked:
        raise ValueError(f"{field_name} must be a single line")
    return checked


def _require_nonnegative(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_positive(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_version_one(value: object, field_name: str) -> None:
    if type(value) is not int or value != 1:
        raise ValueError(f"{field_name} must be integer 1")


def _require_uuid7_id(value: object, prefix: str, field_name: str) -> str:
    if type(value) is not str or not value.startswith(prefix) or value != value.lower():
        raise ValueError(f"{field_name} must use the {prefix} UUIDv7 form")
    try:
        parsed = UUID(value[len(prefix) :])
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must use the {prefix} UUIDv7 form") from exc
    if (
        str(parsed) != value[len(prefix) :]
        or parsed.version != 7
        or parsed.variant != RFC_4122
    ):
        raise ValueError(f"{field_name} must use the {prefix} UUIDv7 form")
    return value


def _require_sequence(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> Sequence[object]:
    if type(value) not in (list, tuple):
        raise ValueError(f"{field_name} must be a sequence")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > _MAX_COLLECTION_ITEMS:
        raise ValueError(f"{field_name} contains too many items")
    return value


@dataclass(frozen=True, slots=True)
class ByteRange:
    start_byte: int
    end_byte: int

    def __post_init__(self) -> None:
        _require_nonnegative(self.start_byte, "start_byte")
        _require_positive(self.end_byte, "end_byte")
        if self.start_byte >= self.end_byte:
            raise ValueError("byte range must be non-empty and half-open")

    def as_mapping(self) -> dict[str, object]:
        return {"start_byte": self.start_byte, "end_byte": self.end_byte}

    @classmethod
    def from_mapping(cls, value: object, field_name: str = "range") -> ByteRange:
        raw = _require_exact_keys(value, {"start_byte", "end_byte"}, field_name)
        return cls(start_byte=raw["start_byte"], end_byte=raw["end_byte"])


@dataclass(frozen=True, slots=True)
class SourceBinding:
    capture_id: str
    capture_version: int
    envelope_sha256: str
    payload_sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        validate_typed_id(self.capture_id, IdKind.CAPTURE)
        if (
            type(self.capture_version) is not int
            or not 1 <= self.capture_version <= _MAX_CAPTURE_VERSION
        ):
            raise ValueError("capture_version must be from 1 through 999999")
        require_sha256(self.envelope_sha256, "envelope_sha256")
        require_sha256(self.payload_sha256, "payload_sha256")
        _require_positive(self.byte_size, "byte_size")

    def as_mapping(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "capture_version": self.capture_version,
            "envelope_sha256": self.envelope_sha256,
            "payload_sha256": self.payload_sha256,
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SourceBinding:
        raw = _require_exact_keys(
            value,
            {
                "capture_id",
                "capture_version",
                "envelope_sha256",
                "payload_sha256",
                "byte_size",
            },
            "source",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class SourceFileMapping:
    """Bind one approved local-file identity to one exact Capture version."""

    source_mapping_id: str
    source_reference: str
    source_sha256: str
    source_byte_size: int
    capture: SourceBinding
    mapped_at: str
    strict_utf8: bool = True

    def __post_init__(self) -> None:
        _require_uuid7_id(
            self.source_mapping_id,
            "smap_",
            "source_mapping_id",
        )
        _require_token(self.source_reference, "source_reference")
        require_sha256(self.source_sha256, "source_sha256")
        _require_positive(self.source_byte_size, "source_byte_size")
        if not isinstance(self.capture, SourceBinding):
            raise TypeError("capture must be SourceBinding")
        if self.source_sha256 != self.capture.payload_sha256:
            raise ValueError("source and Capture Payload hashes must match")
        if self.source_byte_size != self.capture.byte_size:
            raise ValueError("source and Capture Payload byte sizes must match")
        require_canonical_utc_milliseconds(self.mapped_at, "mapped_at")
        if type(self.strict_utf8) is not bool or not self.strict_utf8:
            raise ValueError("strict_utf8 must be true for CUR-MVP-1")

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": "knowledgeflow.curation-source-mapping",
            "schema_version": 1,
            "source_mapping_id": self.source_mapping_id,
            "source_reference": self.source_reference,
            "source_sha256": self.source_sha256,
            "source_byte_size": self.source_byte_size,
            "capture": self.capture.as_mapping(),
            "mapped_at": self.mapped_at,
            "strict_utf8": self.strict_utf8,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SourceFileMapping:
        raw = _require_exact_keys(
            value,
            {
                "schema",
                "schema_version",
                "source_mapping_id",
                "source_reference",
                "source_sha256",
                "source_byte_size",
                "capture",
                "mapped_at",
                "strict_utf8",
            },
            "source mapping",
        )
        if raw["schema"] != "knowledgeflow.curation-source-mapping":
            raise ValueError("source mapping schema is not supported")
        _require_version_one(raw["schema_version"], "source mapping schema_version")
        return cls(
            source_mapping_id=raw["source_mapping_id"],
            source_reference=raw["source_reference"],
            source_sha256=raw["source_sha256"],
            source_byte_size=raw["source_byte_size"],
            capture=SourceBinding.from_mapping(raw["capture"]),
            mapped_at=raw["mapped_at"],
            strict_utf8=raw["strict_utf8"],
        )


@dataclass(frozen=True, slots=True)
class ProcessingAuthorization:
    authorization_id: str
    authorized_by: str
    authorized_at: str
    allowed_range: ByteRange
    task_ids: tuple[str, ...]
    budget_id: str | None = None

    def __post_init__(self) -> None:
        _require_uuid7_id(self.authorization_id, "auth_", "authorization_id")
        _require_token(self.authorized_by, "authorized_by")
        require_canonical_utc_milliseconds(self.authorized_at, "authorized_at")
        if not isinstance(self.allowed_range, ByteRange):
            raise TypeError("allowed_range must be ByteRange")
        tasks = tuple(_require_sequence(self.task_ids, "task_ids", allow_empty=False))
        if not tasks or len(tasks) > 32:
            raise ValueError("task_ids must contain from 1 through 32 values")
        for task_id in tasks:
            _require_token(task_id, "task_ids item")
        if len(set(tasks)) != len(tasks):
            raise ValueError("task_ids must be unique")
        object.__setattr__(self, "task_ids", tasks)
        if self.budget_id is not None:
            _require_token(self.budget_id, "budget_id")

    def as_mapping(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "authorized_by": self.authorized_by,
            "authorized_at": self.authorized_at,
            "allowed_range": self.allowed_range.as_mapping(),
            "task_ids": list(self.task_ids),
            "budget_id": self.budget_id,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ProcessingAuthorization:
        raw = _require_exact_keys(
            value,
            {
                "authorization_id",
                "authorized_by",
                "authorized_at",
                "allowed_range",
                "task_ids",
                "budget_id",
            },
            "processing_authorization",
        )
        tasks = _require_sequence(raw["task_ids"], "task_ids", allow_empty=False)
        return cls(
            authorization_id=raw["authorization_id"],
            authorized_by=raw["authorized_by"],
            authorized_at=raw["authorized_at"],
            allowed_range=ByteRange.from_mapping(raw["allowed_range"], "allowed_range"),
            task_ids=tuple(tasks),
            budget_id=raw["budget_id"],
        )


@dataclass(frozen=True, slots=True)
class TargetDecision:
    target_decision_id: str
    choice: str
    requested_display_name: str | None
    target_kb_id: str | None
    decided_by: str
    decided_at: str

    def __post_init__(self) -> None:
        _require_uuid7_id(
            self.target_decision_id,
            "target_",
            "target_decision_id",
        )
        if self.choice not in {"new-kb", "no-target"}:
            raise ValueError("choice must be new-kb or no-target")
        if self.requested_display_name is not None:
            _require_single_line_string(
                self.requested_display_name,
                "requested_display_name",
                maximum_bytes=_MAX_SHORT_TEXT_BYTES,
            )
        if self.target_kb_id is not None:
            _require_uuid7_id(self.target_kb_id, "kb_", "target_kb_id")
        if self.choice == "new-kb" and self.target_kb_id is not None:
            raise ValueError("new-kb decision cannot bind an uncreated kb_id")
        if self.choice == "no-target" and (
            self.requested_display_name is not None or self.target_kb_id is not None
        ):
            raise ValueError("no-target decision cannot carry KB fields")
        _require_token(self.decided_by, "decided_by")
        require_canonical_utc_milliseconds(self.decided_at, "decided_at")

    def as_mapping(self) -> dict[str, object]:
        return {
            "target_decision_id": self.target_decision_id,
            "choice": self.choice,
            "requested_display_name": self.requested_display_name,
            "target_kb_id": self.target_kb_id,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_mapping(cls, value: object) -> TargetDecision:
        raw = _require_exact_keys(
            value,
            {
                "target_decision_id",
                "choice",
                "requested_display_name",
                "target_kb_id",
                "decided_by",
                "decided_at",
            },
            "target_decision",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class SegmentationProfile:
    profile_id: str = EXPERIMENT_SEGMENTATION_PROFILE_ID
    revision: int = EXPERIMENT_SEGMENTATION_PROFILE_REVISION
    target_bytes: int = EXPERIMENT_TARGET_BYTES
    maximum_bytes: int = EXPERIMENT_MAX_BYTES
    overlap_bytes: int = 0

    def __post_init__(self) -> None:
        if self.profile_id != EXPERIMENT_SEGMENTATION_PROFILE_ID:
            raise ValueError("profile_id is not the CUR1 experimental profile")
        _require_version_one(self.revision, "segmentation profile revision")
        _require_positive(self.target_bytes, "target_bytes")
        _require_positive(self.maximum_bytes, "maximum_bytes")
        _require_nonnegative(self.overlap_bytes, "overlap_bytes")
        if self.target_bytes != EXPERIMENT_TARGET_BYTES:
            raise ValueError("target_bytes is not the CUR1 experimental value")
        if self.maximum_bytes != EXPERIMENT_MAX_BYTES:
            raise ValueError("maximum_bytes is not the CUR1 experimental value")
        if self.overlap_bytes != 0:
            raise ValueError("the raw CUR1 Segment layer does not overlap")

    def as_mapping(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "revision": self.revision,
            "target_bytes": self.target_bytes,
            "maximum_bytes": self.maximum_bytes,
            "overlap_bytes": self.overlap_bytes,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SegmentationProfile:
        raw = _require_exact_keys(
            value,
            {
                "profile_id",
                "revision",
                "target_bytes",
                "maximum_bytes",
                "overlap_bytes",
            },
            "segmentation_profile",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ProcessorProfile:
    kind: str
    processor_id: str
    revision: int
    model_id: str | None
    network_allowed: bool

    def __post_init__(self) -> None:
        if self.kind not in _PROCESSOR_KINDS:
            raise ValueError("kind is not a supported CUR1 processor kind")
        _require_token(self.processor_id, "processor_id")
        _require_positive(self.revision, "processor revision")
        if self.model_id is not None:
            _require_single_line_string(
                self.model_id,
                "model_id",
                maximum_bytes=_MAX_SHORT_TEXT_BYTES,
            )
        if type(self.network_allowed) is not bool:
            raise ValueError("network_allowed must be boolean")
        if self.kind in {"mechanical", "test-fixture"} and (
            self.model_id is not None or self.network_allowed
        ):
            raise ValueError("mechanical and test processors must be offline and model-free")

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "processor_id": self.processor_id,
            "revision": self.revision,
            "model_id": self.model_id,
            "network_allowed": self.network_allowed,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ProcessorProfile:
        raw = _require_exact_keys(
            value,
            {"kind", "processor_id", "revision", "model_id", "network_allowed"},
            "processor_profile",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ProcessorUsage:
    call_count: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cost_currency: str | None = None
    cost_minor_units: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "call_count",
            "input_tokens",
            "output_tokens",
            "elapsed_ms",
        ):
            _require_nonnegative(getattr(self, field_name), field_name)
        if (self.cost_currency is None) != (self.cost_minor_units is None):
            raise ValueError("cost currency and units must both be null or both be present")
        if self.cost_currency is not None:
            if type(self.cost_currency) is not str or not re.fullmatch(
                r"[A-Z]{3}", self.cost_currency
            ):
                raise ValueError("cost_currency must be a three-letter uppercase code")
            _require_nonnegative(self.cost_minor_units, "cost_minor_units")

    def as_mapping(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "cost_currency": self.cost_currency,
            "cost_minor_units": self.cost_minor_units,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ProcessorUsage:
        raw = _require_exact_keys(
            value,
            {
                "call_count",
                "input_tokens",
                "output_tokens",
                "elapsed_ms",
                "cost_currency",
                "cost_minor_units",
            },
            "processor_usage",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class CurationRunManifest:
    curation_run_id: str
    source_mapping_id: str
    source: SourceBinding
    processing_authorization: ProcessingAuthorization
    declared_scope: ByteRange
    target_decision: TargetDecision | None
    segmentation_profile: SegmentationProfile
    processor_profile: ProcessorProfile
    state: str = "authorized"

    def __post_init__(self) -> None:
        _require_uuid7_id(self.curation_run_id, "run_", "curation_run_id")
        _require_uuid7_id(
            self.source_mapping_id,
            "smap_",
            "source_mapping_id",
        )
        if not isinstance(self.source, SourceBinding):
            raise TypeError("source must be SourceBinding")
        if not isinstance(self.processing_authorization, ProcessingAuthorization):
            raise TypeError("processing_authorization must be ProcessingAuthorization")
        if self.processing_authorization.allowed_range.end_byte > self.source.byte_size:
            raise ValueError("processing authorization exceeds source bytes")
        if not isinstance(self.declared_scope, ByteRange):
            raise TypeError("declared_scope must be ByteRange")
        if (
            self.declared_scope.start_byte
            < self.processing_authorization.allowed_range.start_byte
            or self.declared_scope.end_byte
            > self.processing_authorization.allowed_range.end_byte
        ):
            raise ValueError("declared_scope exceeds processing authorization")
        if self.target_decision is not None and not isinstance(
            self.target_decision,
            TargetDecision,
        ):
            raise TypeError("target_decision must be TargetDecision or null")
        if not isinstance(self.segmentation_profile, SegmentationProfile):
            raise TypeError("segmentation_profile must be SegmentationProfile")
        if not isinstance(self.processor_profile, ProcessorProfile):
            raise TypeError("processor_profile must be ProcessorProfile")
        if self.state not in _RUN_STATES:
            raise ValueError("state is not a supported CUR1 run state")

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": "knowledgeflow.curation-experiment-run",
            "schema_version": 1,
            "curation_run_id": self.curation_run_id,
            "source_mapping_id": self.source_mapping_id,
            "source": self.source.as_mapping(),
            "processing_authorization": self.processing_authorization.as_mapping(),
            "declared_scope": self.declared_scope.as_mapping(),
            "target_decision": (
                None
                if self.target_decision is None
                else self.target_decision.as_mapping()
            ),
            "segmentation_profile": self.segmentation_profile.as_mapping(),
            "processor_profile": self.processor_profile.as_mapping(),
            "state": self.state,
        }

    @classmethod
    def from_mapping(cls, value: object) -> CurationRunManifest:
        raw = _require_exact_keys(
            value,
            {
                "schema",
                "schema_version",
                "curation_run_id",
                "source_mapping_id",
                "source",
                "processing_authorization",
                "declared_scope",
                "target_decision",
                "segmentation_profile",
                "processor_profile",
                "state",
            },
            "curation run",
        )
        if raw["schema"] != "knowledgeflow.curation-experiment-run":
            raise ValueError("curation run schema is not supported")
        _require_version_one(raw["schema_version"], "curation run schema_version")
        return cls(
            curation_run_id=raw["curation_run_id"],
            source_mapping_id=raw["source_mapping_id"],
            source=SourceBinding.from_mapping(raw["source"]),
            processing_authorization=ProcessingAuthorization.from_mapping(
                raw["processing_authorization"]
            ),
            declared_scope=ByteRange.from_mapping(
                raw["declared_scope"],
                "declared_scope",
            ),
            target_decision=(
                None
                if raw["target_decision"] is None
                else TargetDecision.from_mapping(raw["target_decision"])
            ),
            segmentation_profile=SegmentationProfile.from_mapping(
                raw["segmentation_profile"]
            ),
            processor_profile=ProcessorProfile.from_mapping(raw["processor_profile"]),
            state=raw["state"],
        )

    def validate_source_mapping(self, mapping: SourceFileMapping) -> None:
        if not isinstance(mapping, SourceFileMapping):
            raise TypeError("mapping must be SourceFileMapping")
        if self.source_mapping_id != mapping.source_mapping_id:
            raise ValueError("curation run binds a different source mapping")
        if self.source != mapping.capture:
            raise ValueError("curation run and source mapping use different Captures")


@dataclass(frozen=True, slots=True)
class SegmentRecord:
    segment_id: str
    ordinal: int
    byte_range: ByteRange
    start_line: int
    end_line: int
    heading_path: tuple[str, ...]
    body_sha256: str
    profile_id: str
    profile_revision: int

    def __post_init__(self) -> None:
        _require_uuid7_id(self.segment_id, "seg_", "segment_id")
        _require_nonnegative(self.ordinal, "segment ordinal")
        if not isinstance(self.byte_range, ByteRange):
            raise TypeError("byte_range must be ByteRange")
        _require_positive(self.start_line, "start_line")
        _require_positive(self.end_line, "end_line")
        if self.start_line > self.end_line:
            raise ValueError("start_line must not exceed end_line")
        headings = tuple(_require_sequence(self.heading_path, "heading_path"))
        if len(headings) > 32:
            raise ValueError("heading_path contains too many items")
        for heading in headings:
            _require_single_line_string(
                heading,
                "heading_path item",
                maximum_bytes=_MAX_SHORT_TEXT_BYTES,
            )
        object.__setattr__(self, "heading_path", headings)
        require_sha256(self.body_sha256, "body_sha256")
        if self.profile_id != EXPERIMENT_SEGMENTATION_PROFILE_ID:
            raise ValueError("segment profile_id is not the CUR1 experimental profile")
        _require_version_one(self.profile_revision, "segment profile_revision")

    def as_mapping(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "ordinal": self.ordinal,
            "range": self.byte_range.as_mapping(),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "heading_path": list(self.heading_path),
            "body_sha256": self.body_sha256,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SegmentRecord:
        raw = _require_exact_keys(
            value,
            {
                "segment_id",
                "ordinal",
                "range",
                "start_line",
                "end_line",
                "heading_path",
                "body_sha256",
                "profile_id",
                "profile_revision",
            },
            "segment",
        )
        headings = _require_sequence(raw["heading_path"], "heading_path")
        return cls(
            segment_id=raw["segment_id"],
            ordinal=raw["ordinal"],
            byte_range=ByteRange.from_mapping(raw["range"], "segment.range"),
            start_line=raw["start_line"],
            end_line=raw["end_line"],
            heading_path=tuple(headings),
            body_sha256=raw["body_sha256"],
            profile_id=raw["profile_id"],
            profile_revision=raw["profile_revision"],
        )


@dataclass(frozen=True, slots=True)
class ScopeRecord:
    byte_range: ByteRange
    status: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.byte_range, ByteRange):
            raise TypeError("byte_range must be ByteRange")
        if self.status not in _SCOPE_STATUSES:
            raise ValueError("scope status is not supported")
        if self.status == "processed":
            if self.reason is not None:
                raise ValueError("processed scope must not carry a reason")
        else:
            _require_single_line_string(
                self.reason,
                "scope reason",
                maximum_bytes=_MAX_SHORT_TEXT_BYTES,
            )

    def as_mapping(self) -> dict[str, object]:
        return {
            "range": self.byte_range.as_mapping(),
            "status": self.status,
            "reason": self.reason,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ScopeRecord:
        raw = _require_exact_keys(value, {"range", "status", "reason"}, "scope item")
        return cls(
            byte_range=ByteRange.from_mapping(raw["range"], "scope item.range"),
            status=raw["status"],
            reason=raw["reason"],
        )


def _require_exact_range_cover(
    declared_scope: ByteRange,
    ranges: Sequence[ByteRange],
    field_name: str,
) -> None:
    if not ranges:
        raise ValueError(f"{field_name} must not be empty")
    cursor = declared_scope.start_byte
    for item in ranges:
        if item.start_byte != cursor:
            raise ValueError(f"{field_name} must cover declared scope without gaps or overlap")
        cursor = item.end_byte
    if cursor != declared_scope.end_byte:
        raise ValueError(f"{field_name} must cover declared scope exactly")


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    locator_id: str
    source: SourceBinding
    byte_range: ByteRange
    start_line: int
    end_line: int
    excerpt_sha256: str

    def __post_init__(self) -> None:
        _require_uuid7_id(self.locator_id, "loc_", "locator_id")
        if not isinstance(self.source, SourceBinding):
            raise TypeError("source must be SourceBinding")
        if not isinstance(self.byte_range, ByteRange):
            raise TypeError("byte_range must be ByteRange")
        if self.byte_range.end_byte > self.source.byte_size:
            raise ValueError("locator range exceeds source bytes")
        _require_positive(self.start_line, "start_line")
        _require_positive(self.end_line, "end_line")
        if self.start_line > self.end_line:
            raise ValueError("start_line must not exceed end_line")
        require_sha256(self.excerpt_sha256, "excerpt_sha256")

    def as_mapping(self) -> dict[str, object]:
        return {
            "locator_id": self.locator_id,
            "source": self.source.as_mapping(),
            "range": self.byte_range.as_mapping(),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "excerpt_sha256": self.excerpt_sha256,
        }

    @classmethod
    def from_mapping(cls, value: object) -> EvidenceLocator:
        raw = _require_exact_keys(
            value,
            {
                "locator_id",
                "source",
                "range",
                "start_line",
                "end_line",
                "excerpt_sha256",
            },
            "locator",
        )
        return cls(
            locator_id=raw["locator_id"],
            source=SourceBinding.from_mapping(raw["source"]),
            byte_range=ByteRange.from_mapping(raw["range"], "locator.range"),
            start_line=raw["start_line"],
            end_line=raw["end_line"],
            excerpt_sha256=raw["excerpt_sha256"],
        )


@dataclass(frozen=True, slots=True)
class CurationEvidenceRecord:
    curation_run_id: str
    source: SourceBinding
    declared_scope: ByteRange
    segmentation_profile: SegmentationProfile
    segments: tuple[SegmentRecord, ...]
    scope: tuple[ScopeRecord, ...]
    locators: tuple[EvidenceLocator, ...]

    def __post_init__(self) -> None:
        _require_uuid7_id(self.curation_run_id, "run_", "curation_run_id")
        if not isinstance(self.source, SourceBinding):
            raise TypeError("source must be SourceBinding")
        if not isinstance(self.declared_scope, ByteRange):
            raise TypeError("declared_scope must be ByteRange")
        if self.declared_scope.end_byte > self.source.byte_size:
            raise ValueError("declared_scope exceeds source bytes")
        if not isinstance(self.segmentation_profile, SegmentationProfile):
            raise TypeError("segmentation_profile must be SegmentationProfile")

        segments = tuple(
            _require_sequence(self.segments, "segments", allow_empty=False)
        )
        if not segments or not all(isinstance(item, SegmentRecord) for item in segments):
            raise ValueError("segments must contain SegmentRecord values")
        if [item.ordinal for item in segments] != list(range(len(segments))):
            raise ValueError("segment ordinals must start at zero and be contiguous")
        if len({item.segment_id for item in segments}) != len(segments):
            raise ValueError("segment IDs must be unique")
        if any(
            item.byte_range.end_byte - item.byte_range.start_byte
            > self.segmentation_profile.maximum_bytes
            for item in segments
        ):
            raise ValueError("segment exceeds the segmentation profile maximum")
        _require_exact_range_cover(
            self.declared_scope,
            [item.byte_range for item in segments],
            "segments",
        )
        object.__setattr__(self, "segments", segments)

        scope = tuple(_require_sequence(self.scope, "scope", allow_empty=False))
        if not all(isinstance(item, ScopeRecord) for item in scope):
            raise ValueError("scope must contain ScopeRecord values")
        _require_exact_range_cover(
            self.declared_scope,
            [item.byte_range for item in scope],
            "scope",
        )
        object.__setattr__(self, "scope", scope)

        locators = tuple(_require_sequence(self.locators, "locators"))
        if not all(isinstance(item, EvidenceLocator) for item in locators):
            raise ValueError("locators must contain EvidenceLocator values")
        if len({item.locator_id for item in locators}) != len(locators):
            raise ValueError("locator IDs must be unique")
        for locator in locators:
            if locator.source != self.source:
                raise ValueError("locator source must match evidence source")
            if (
                locator.byte_range.start_byte < self.declared_scope.start_byte
                or locator.byte_range.end_byte > self.declared_scope.end_byte
            ):
                raise ValueError("locator must stay inside declared_scope")
        object.__setattr__(self, "locators", locators)

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": "knowledgeflow.curation-experiment-record",
            "schema_version": 1,
            "curation_run_id": self.curation_run_id,
            "source": self.source.as_mapping(),
            "declared_scope": self.declared_scope.as_mapping(),
            "segmentation_profile": self.segmentation_profile.as_mapping(),
            "segments": [item.as_mapping() for item in self.segments],
            "scope": [item.as_mapping() for item in self.scope],
            "locators": [item.as_mapping() for item in self.locators],
        }

    @classmethod
    def from_mapping(cls, value: object) -> CurationEvidenceRecord:
        raw = _require_exact_keys(
            value,
            {
                "schema",
                "schema_version",
                "curation_run_id",
                "source",
                "declared_scope",
                "segmentation_profile",
                "segments",
                "scope",
                "locators",
            },
            "curation experiment record",
        )
        if raw["schema"] != "knowledgeflow.curation-experiment-record":
            raise ValueError("curation experiment record schema is not supported")
        _require_version_one(
            raw["schema_version"],
            "curation experiment record schema_version",
        )
        segments = _require_sequence(raw["segments"], "segments", allow_empty=False)
        scope = _require_sequence(raw["scope"], "scope", allow_empty=False)
        locators = _require_sequence(raw["locators"], "locators")
        return cls(
            curation_run_id=raw["curation_run_id"],
            source=SourceBinding.from_mapping(raw["source"]),
            declared_scope=ByteRange.from_mapping(raw["declared_scope"], "declared_scope"),
            segmentation_profile=SegmentationProfile.from_mapping(
                raw["segmentation_profile"]
            ),
            segments=tuple(SegmentRecord.from_mapping(item) for item in segments),
            scope=tuple(ScopeRecord.from_mapping(item) for item in scope),
            locators=tuple(EvidenceLocator.from_mapping(item) for item in locators),
        )

    def validate_against_run(self, run: CurationRunManifest) -> None:
        if not isinstance(run, CurationRunManifest):
            raise TypeError("run must be CurationRunManifest")
        if self.curation_run_id != run.curation_run_id:
            raise ValueError("evidence and run use different curation_run_id values")
        if self.source != run.source:
            raise ValueError("evidence and run use different sources")
        if self.declared_scope != run.declared_scope:
            raise ValueError("evidence and run use different declared_scope values")
        if self.segmentation_profile != run.segmentation_profile:
            raise ValueError("evidence and run use different segmentation profiles")


@dataclass(frozen=True, slots=True)
class TargetBinding:
    kb_id: str
    manifest_sha256: str
    raw_mapping_sha256: str
    managed_ref: str
    base_commit: str
    version_policy_id: str
    version_policy_revision: int

    def __post_init__(self) -> None:
        _require_uuid7_id(self.kb_id, "kb_", "kb_id")
        require_sha256(self.manifest_sha256, "manifest_sha256")
        require_sha256(self.raw_mapping_sha256, "raw_mapping_sha256")
        if self.managed_ref != "refs/heads/knowledgeflow":
            raise ValueError("managed_ref must be refs/heads/knowledgeflow")
        if type(self.base_commit) is not str or _GIT_OBJECT_ID.fullmatch(
            self.base_commit
        ) is None:
            raise ValueError("base_commit must be a lowercase Git object ID")
        _require_token(self.version_policy_id, "version_policy_id")
        _require_positive(self.version_policy_revision, "version_policy_revision")

    def as_mapping(self) -> dict[str, object]:
        return {
            "kb_id": self.kb_id,
            "manifest_sha256": self.manifest_sha256,
            "raw_mapping_sha256": self.raw_mapping_sha256,
            "managed_ref": self.managed_ref,
            "base_commit": self.base_commit,
            "version_policy_id": self.version_policy_id,
            "version_policy_revision": self.version_policy_revision,
        }

    @classmethod
    def from_mapping(cls, value: object) -> TargetBinding:
        raw = _require_exact_keys(
            value,
            {
                "kb_id",
                "manifest_sha256",
                "raw_mapping_sha256",
                "managed_ref",
                "base_commit",
                "version_policy_id",
                "version_policy_revision",
            },
            "target_binding",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class KnowledgeBaseManifest:
    """The non-trusted, provisional KB identity defined by SOP-10."""

    kb_id: str
    storage_name: str
    display_name: str
    created_at: str
    created_by: str
    creation_request_id: str
    lifecycle: str = "provisional"
    domain_status: str = "pending"
    schema_status: str = "absent"
    wiki_status: str = "empty"
    version_control_mode: str = "managed-local"
    version_control_engine: str = "git"
    version_control_remote: str = "none"
    trusted_visibility: str = "none"
    gbrain_federated: bool = False

    def __post_init__(self) -> None:
        _require_uuid7_id(self.kb_id, "kb_", "kb_id")
        if (
            type(self.storage_name) is not str
            or _STORAGE_NAME.fullmatch(self.storage_name) is None
            or self.storage_name in {".", ".."}
            or self.storage_name.split(".", 1)[0]
            in _WINDOWS_RESERVED_STORAGE_STEMS
        ):
            raise ValueError("storage_name must be a safe portable path component")
        _require_single_line_string(
            self.display_name,
            "display_name",
            maximum_bytes=_MAX_SHORT_TEXT_BYTES,
        )
        require_canonical_utc_milliseconds(self.created_at, "created_at")
        _require_token(self.created_by, "created_by")
        _require_token(self.creation_request_id, "creation_request_id")
        expected = {
            "lifecycle": (self.lifecycle, "provisional"),
            "domain_status": (self.domain_status, "pending"),
            "schema_status": (self.schema_status, "absent"),
            "wiki_status": (self.wiki_status, "empty"),
            "version_control_mode": (
                self.version_control_mode,
                "managed-local",
            ),
            "version_control_engine": (self.version_control_engine, "git"),
            "version_control_remote": (self.version_control_remote, "none"),
            "trusted_visibility": (self.trusted_visibility, "none"),
        }
        for field_name, (actual, required) in expected.items():
            if actual != required:
                raise ValueError(f"{field_name} must be {required}")
        if type(self.gbrain_federated) is not bool or self.gbrain_federated:
            raise ValueError("gbrain_federated must be false for a provisional KB")

    def as_mapping(self) -> dict[str, object]:
        return {
            "format": "knowledgeflow.kb-manifest",
            "format_version": 1,
            "kb_id": self.kb_id,
            "storage_name": self.storage_name,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "creation_request_id": self.creation_request_id,
            "lifecycle": self.lifecycle,
            "domain": {"status": self.domain_status},
            "schema": {"status": self.schema_status},
            "wiki": {"status": self.wiki_status},
            "version_control": {
                "mode": self.version_control_mode,
                "engine": self.version_control_engine,
                "remote": self.version_control_remote,
            },
            "search": {"trusted_visibility": self.trusted_visibility},
            "gbrain": {"federated": self.gbrain_federated},
        }

    @classmethod
    def from_mapping(cls, value: object) -> KnowledgeBaseManifest:
        raw = _require_exact_keys(
            value,
            {
                "format",
                "format_version",
                "kb_id",
                "storage_name",
                "display_name",
                "created_at",
                "created_by",
                "creation_request_id",
                "lifecycle",
                "domain",
                "schema",
                "wiki",
                "version_control",
                "search",
                "gbrain",
            },
            "KB manifest",
        )
        if raw["format"] != "knowledgeflow.kb-manifest":
            raise ValueError("KB manifest format is not supported")
        _require_version_one(raw["format_version"], "KB manifest format_version")
        domain = _require_exact_keys(raw["domain"], {"status"}, "domain")
        schema = _require_exact_keys(raw["schema"], {"status"}, "schema")
        wiki = _require_exact_keys(raw["wiki"], {"status"}, "wiki")
        version_control = _require_exact_keys(
            raw["version_control"],
            {"mode", "engine", "remote"},
            "version_control",
        )
        search = _require_exact_keys(
            raw["search"],
            {"trusted_visibility"},
            "search",
        )
        gbrain = _require_exact_keys(raw["gbrain"], {"federated"}, "gbrain")
        return cls(
            kb_id=raw["kb_id"],
            storage_name=raw["storage_name"],
            display_name=raw["display_name"],
            created_at=raw["created_at"],
            created_by=raw["created_by"],
            creation_request_id=raw["creation_request_id"],
            lifecycle=raw["lifecycle"],
            domain_status=domain["status"],
            schema_status=schema["status"],
            wiki_status=wiki["status"],
            version_control_mode=version_control["mode"],
            version_control_engine=version_control["engine"],
            version_control_remote=version_control["remote"],
            trusted_visibility=search["trusted_visibility"],
            gbrain_federated=gbrain["federated"],
        )


@dataclass(frozen=True, slots=True)
class MapCandidate:
    candidate_id: str
    kind: str
    summary: str
    evidence_locator_ids: tuple[str, ...]
    provenance: str
    uncertainty: str
    markdown_anchor: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        _require_uuid7_id(self.candidate_id, "cand_", "candidate_id")
        if self.kind not in _CANDIDATE_KINDS:
            raise ValueError("candidate kind is not supported")
        _require_string(self.summary, "candidate summary")
        locator_ids = tuple(
            _require_sequence(
                self.evidence_locator_ids,
                "evidence_locator_ids",
            )
        )
        if not locator_ids and self.kind not in _EVIDENCE_OPTIONAL_KINDS:
            raise ValueError("this candidate kind requires evidence")
        for locator_id in locator_ids:
            _require_uuid7_id(locator_id, "loc_", "evidence locator ID")
        if len(set(locator_ids)) != len(locator_ids):
            raise ValueError("evidence locator IDs must be unique")
        object.__setattr__(self, "evidence_locator_ids", locator_ids)
        if self.provenance not in _PROVENANCE_VALUES:
            raise ValueError("candidate provenance is not supported")
        if self.uncertainty not in _UNCERTAINTY_VALUES:
            raise ValueError("candidate uncertainty is not supported")
        if type(self.markdown_anchor) is not str or _MARKDOWN_ANCHOR.fullmatch(
            self.markdown_anchor
        ) is None:
            raise ValueError("markdown_anchor must be a safe lowercase anchor")
        if self.supersedes is not None:
            _require_uuid7_id(self.supersedes, "cand_", "supersedes")
            if self.supersedes == self.candidate_id:
                raise ValueError("candidate cannot supersede itself")

    def as_mapping(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "summary": self.summary,
            "evidence_locator_ids": list(self.evidence_locator_ids),
            "provenance": self.provenance,
            "uncertainty": self.uncertainty,
            "markdown_anchor": self.markdown_anchor,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_mapping(cls, value: object) -> MapCandidate:
        raw = _require_exact_keys(
            value,
            {
                "candidate_id",
                "kind",
                "summary",
                "evidence_locator_ids",
                "provenance",
                "uncertainty",
                "markdown_anchor",
                "supersedes",
            },
            "map candidate",
        )
        locator_ids = _require_sequence(
            raw["evidence_locator_ids"], "evidence_locator_ids"
        )
        return cls(
            candidate_id=raw["candidate_id"],
            kind=raw["kind"],
            summary=raw["summary"],
            evidence_locator_ids=tuple(locator_ids),
            provenance=raw["provenance"],
            uncertainty=raw["uncertainty"],
            markdown_anchor=raw["markdown_anchor"],
            supersedes=raw["supersedes"],
        )


@dataclass(frozen=True, slots=True)
class CurationMap:
    map_id: str
    map_version: int
    curation_run_id: str
    created_at: str
    source: SourceBinding
    declared_scope: ByteRange
    scope: tuple[ScopeRecord, ...]
    processor_profile: ProcessorProfile
    processor_usage: ProcessorUsage
    target_binding: TargetBinding | None
    candidates: tuple[MapCandidate, ...]

    def __post_init__(self) -> None:
        _require_uuid7_id(self.map_id, "map_", "map_id")
        _require_positive(self.map_version, "map_version")
        _require_uuid7_id(self.curation_run_id, "run_", "curation_run_id")
        require_canonical_utc_milliseconds(self.created_at, "created_at")
        if not isinstance(self.source, SourceBinding):
            raise TypeError("source must be SourceBinding")
        if not isinstance(self.declared_scope, ByteRange):
            raise TypeError("declared_scope must be ByteRange")
        if self.declared_scope.end_byte > self.source.byte_size:
            raise ValueError("declared_scope exceeds source bytes")
        scope = tuple(_require_sequence(self.scope, "scope", allow_empty=False))
        if not all(isinstance(item, ScopeRecord) for item in scope):
            raise ValueError("scope must contain ScopeRecord values")
        _require_exact_range_cover(
            self.declared_scope,
            [item.byte_range for item in scope],
            "scope",
        )
        object.__setattr__(self, "scope", scope)
        if not isinstance(self.processor_profile, ProcessorProfile):
            raise TypeError("processor_profile must be ProcessorProfile")
        if not isinstance(self.processor_usage, ProcessorUsage):
            raise TypeError("processor_usage must be ProcessorUsage")
        if self.target_binding is not None and not isinstance(
            self.target_binding, TargetBinding
        ):
            raise TypeError("target_binding must be TargetBinding or null")
        candidates = tuple(
            _require_sequence(self.candidates, "candidates", allow_empty=False)
        )
        if not candidates or not all(isinstance(item, MapCandidate) for item in candidates):
            raise ValueError("candidates must contain MapCandidate values")
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise ValueError("candidate IDs must be unique")
        if len({item.markdown_anchor for item in candidates}) != len(candidates):
            raise ValueError("candidate markdown anchors must be unique")
        object.__setattr__(self, "candidates", candidates)

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": "knowledgeflow.curation-map",
            "schema_version": 1,
            "map_id": self.map_id,
            "map_version": self.map_version,
            "curation_run_id": self.curation_run_id,
            "created_at": self.created_at,
            "source": self.source.as_mapping(),
            "declared_scope": self.declared_scope.as_mapping(),
            "scope": [item.as_mapping() for item in self.scope],
            "processor_profile": self.processor_profile.as_mapping(),
            "processor_usage": self.processor_usage.as_mapping(),
            "target_binding": (
                self.target_binding.as_mapping()
                if self.target_binding is not None
                else None
            ),
            "candidates": [item.as_mapping() for item in self.candidates],
        }

    @classmethod
    def from_mapping(cls, value: object) -> CurationMap:
        raw = _require_exact_keys(
            value,
            {
                "schema",
                "schema_version",
                "map_id",
                "map_version",
                "curation_run_id",
                "created_at",
                "source",
                "declared_scope",
                "scope",
                "processor_profile",
                "processor_usage",
                "target_binding",
                "candidates",
            },
            "curation map",
        )
        if raw["schema"] != "knowledgeflow.curation-map":
            raise ValueError("curation map schema is not supported")
        _require_version_one(raw["schema_version"], "curation map schema_version")
        scope = _require_sequence(raw["scope"], "scope", allow_empty=False)
        candidates = _require_sequence(
            raw["candidates"], "candidates", allow_empty=False
        )
        return cls(
            map_id=raw["map_id"],
            map_version=raw["map_version"],
            curation_run_id=raw["curation_run_id"],
            created_at=raw["created_at"],
            source=SourceBinding.from_mapping(raw["source"]),
            declared_scope=ByteRange.from_mapping(raw["declared_scope"], "declared_scope"),
            scope=tuple(ScopeRecord.from_mapping(item) for item in scope),
            processor_profile=ProcessorProfile.from_mapping(raw["processor_profile"]),
            processor_usage=ProcessorUsage.from_mapping(raw["processor_usage"]),
            target_binding=(
                TargetBinding.from_mapping(raw["target_binding"])
                if raw["target_binding"] is not None
                else None
            ),
            candidates=tuple(MapCandidate.from_mapping(item) for item in candidates),
        )

    def validate_against(self, evidence: CurationEvidenceRecord) -> None:
        if not isinstance(evidence, CurationEvidenceRecord):
            raise TypeError("evidence must be CurationEvidenceRecord")
        if self.curation_run_id != evidence.curation_run_id:
            raise ValueError("map and evidence use different curation runs")
        if self.source != evidence.source:
            raise ValueError("map and evidence use different sources")
        if self.declared_scope != evidence.declared_scope or self.scope != evidence.scope:
            raise ValueError("map and evidence use different scope records")
        available = {item.locator_id for item in evidence.locators}
        referenced = {
            locator_id
            for candidate in self.candidates
            for locator_id in candidate.evidence_locator_ids
        }
        if not referenced.issubset(available):
            raise ValueError("map references an unknown Evidence locator")

    def validate_against_run(self, run: CurationRunManifest) -> None:
        if not isinstance(run, CurationRunManifest):
            raise TypeError("run must be CurationRunManifest")
        if self.curation_run_id != run.curation_run_id or self.source != run.source:
            raise ValueError("map and run use different identities")
        if self.declared_scope != run.declared_scope:
            raise ValueError("map and run use different declared_scope values")
        if self.processor_profile != run.processor_profile:
            raise ValueError("map and run use different processor profiles")
        if run.target_decision is None:
            raise ValueError("map requires a recorded target decision")
        if run.target_decision.choice == "no-target" and self.target_binding is not None:
            raise ValueError("no-target run cannot produce a target-bound map")
        if run.target_decision.choice == "new-kb" and self.target_binding is None:
            raise ValueError("new-kb run requires a target-bound map")


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    action: str
    replacement_text: str | None = None

    def __post_init__(self) -> None:
        _require_uuid7_id(self.candidate_id, "cand_", "candidate_id")
        if self.action not in _DECISION_ACTIONS:
            raise ValueError("decision action is not supported")
        if self.action == "modify":
            _require_string(self.replacement_text, "replacement_text")
        elif self.replacement_text is not None:
            raise ValueError("replacement_text is allowed only for modify")

    def as_mapping(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "replacement_text": self.replacement_text,
        }

    @classmethod
    def from_mapping(cls, value: object) -> CandidateDecision:
        raw = _require_exact_keys(
            value,
            {"candidate_id", "action", "replacement_text"},
            "candidate decision",
        )
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class MapDecision:
    decision_set_id: str
    version: int
    map_sha256: str
    outcome: str
    decided_by: str
    decided_at: str
    decisions: tuple[CandidateDecision, ...]

    def __post_init__(self) -> None:
        _require_uuid7_id(self.decision_set_id, "dset_", "decision_set_id")
        _require_positive(self.version, "decision version")
        require_sha256(self.map_sha256, "map_sha256")
        if self.outcome not in _DECISION_OUTCOMES:
            raise ValueError("decision outcome is not supported")
        _require_token(self.decided_by, "decided_by")
        require_canonical_utc_milliseconds(self.decided_at, "decided_at")
        decisions = tuple(
            _require_sequence(self.decisions, "decisions", allow_empty=False)
        )
        if not decisions or not all(
            isinstance(item, CandidateDecision) for item in decisions
        ):
            raise ValueError("decisions must contain CandidateDecision values")
        if len({item.candidate_id for item in decisions}) != len(decisions):
            raise ValueError("candidate decisions must be unique")
        object.__setattr__(self, "decisions", decisions)

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": "knowledgeflow.curation-map-decision",
            "schema_version": 1,
            "decision_set_id": self.decision_set_id,
            "version": self.version,
            "map_sha256": self.map_sha256,
            "outcome": self.outcome,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "decisions": [item.as_mapping() for item in self.decisions],
        }

    @classmethod
    def from_mapping(cls, value: object) -> MapDecision:
        raw = _require_exact_keys(
            value,
            {
                "schema",
                "schema_version",
                "decision_set_id",
                "version",
                "map_sha256",
                "outcome",
                "decided_by",
                "decided_at",
                "decisions",
            },
            "map decision",
        )
        if raw["schema"] != "knowledgeflow.curation-map-decision":
            raise ValueError("map decision schema is not supported")
        _require_version_one(raw["schema_version"], "map decision schema_version")
        decisions = _require_sequence(
            raw["decisions"], "decisions", allow_empty=False
        )
        return cls(
            decision_set_id=raw["decision_set_id"],
            version=raw["version"],
            map_sha256=raw["map_sha256"],
            outcome=raw["outcome"],
            decided_by=raw["decided_by"],
            decided_at=raw["decided_at"],
            decisions=tuple(
                CandidateDecision.from_mapping(item) for item in decisions
            ),
        )

    def validate_against(
        self,
        curation_map: CurationMap,
        map_sha256: str,
    ) -> None:
        if not isinstance(curation_map, CurationMap):
            raise TypeError("curation_map must be CurationMap")
        require_sha256(map_sha256, "map_sha256")
        if self.map_sha256 != map_sha256:
            raise ValueError("decision record binds a different map artifact")
        available = {item.candidate_id for item in curation_map.candidates}
        decided = {item.candidate_id for item in self.decisions}
        if not decided.issubset(available):
            raise ValueError("decision record references an unknown map candidate")
        if self.outcome == "map-closed" and decided != available:
            raise ValueError("map-closed must decide every candidate")


__all__ = [
    "ByteRange",
    "CandidateDecision",
    "CurationEvidenceRecord",
    "CurationMap",
    "CurationOperation",
    "CurationRunManifest",
    "EXPERIMENT_MAX_BYTES",
    "EXPERIMENT_SEGMENTATION_PROFILE_ID",
    "EXPERIMENT_SEGMENTATION_PROFILE_REVISION",
    "EXPERIMENT_TARGET_BYTES",
    "EvidenceLocator",
    "KnowledgeBaseManifest",
    "MapCandidate",
    "MapDecision",
    "ProcessingAuthorization",
    "ProcessorProfile",
    "ProcessorUsage",
    "ScopeRecord",
    "SegmentRecord",
    "SegmentationProfile",
    "SourceBinding",
    "SourceFileMapping",
    "TargetBinding",
    "TargetDecision",
]
