"""CUR1D map build, review, versioning, and close operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
from typing import cast

from knowledgeflow_capture import GetCaptureRequest, get_capture
from knowledgeflow_capture.durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
)
from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.models import format_utc_milliseconds
from knowledgeflow_capture.paths import PathPolicy

from .codec import (
    curation_map_artifact_sha256,
    dump_curation_map,
    dump_map_decision,
    load_curation_map,
    load_map_decision,
    map_decision_sha256,
    render_curation_map_markdown,
)
from .contracts import (
    ByteRange,
    CandidateDecision,
    CurationEvidenceRecord,
    CurationMap,
    CurationRunManifest,
    EvidenceLocator,
    MapCandidate,
    MapDecision,
    ProcessorProfile,
    ProcessorUsage,
    ScopeRecord,
    SHORT_READING_MAX_BYTES,
    SHORT_READING_MAX_RANGE_BYTES,
    SHORT_READING_MAX_UNITS,
    SHORT_READING_PROFILE,
    TargetBinding,
)
from .errors import (
    CurationCommitState,
    CurationError,
    CurationErrorCode,
    CurationFailure,
)
from .ids import generate_curation_id
from .locking import LockUnavailable, exclusive_file_lock
from .operations import SourceInspectRequest, SourceInspectResult, inspect_source
from .processing import (
    AttemptRecord,
    BudgetExhausted,
    CUR1D_PROCESSOR_PROFILE,
    CUR1D_PROCESSOR_PROFILE_REVISION,
    SHORT_READING_MAX_CANDIDATES,
    SHORT_READING_PROCESSOR_PROFILE,
    SHORT_READING_PROCESSOR_PROFILE_REVISION,
    ExecutedUnit,
    FocusTopic,
    PriorCandidate,
    ProcessingBudgetLedger,
    ProcessingBudgetLimits,
    ProcessingStage,
    ProcessorCallError,
    ProcessorCallUsage,
    ProcessorCandidateDraft,
    ProcessorFailureDiagnostic,
    ProcessorPort,
    ProcessorRequest,
    ProcessorResponse,
    ProcessorSegment,
    RemoteProcessingAuthorization,
    TokenCounter,
    Utf8ByteUpperBoundTokenCounter,
)
from .targeting import (
    TargetDecideResult,
    inspect_target_decision,
)
from .versioning import (
    ManagedGit,
    ManagedGitConflict,
    ManagedGitError,
    ManagedGitIntegrityError,
    ManagedGitUnavailable,
)


_SAFE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MAP_ID = re.compile(
    r"map_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_MAX_INTERNAL_BYTES = 64 * 1024 * 1024
_REPARSE_ATTRIBUTE = 0x400
_L1_TARGET_TOKENS = 24_576
_INPUT_HARD_LIMIT = 32_768
_TOKEN_PLANNING_SAFETY_MARGIN = 512
_TARGET_SAMPLE_INITIAL_BYTES = 2_048
_TARGET_SAMPLE_MINIMUM_BYTES = 512
_PROCESSING_WINDOW_PROFILE = "heading-tree-token-bounded"
_PROCESSING_WINDOW_PROFILE_REVISION = 1
_SHORT_READING_PROFILE = SHORT_READING_PROFILE
_SHORT_DIRECT_MAX_BYTES = SHORT_READING_MAX_BYTES
_SHORT_DIRECT_MAX_UNITS = SHORT_READING_MAX_UNITS
_SHORT_LINE_CHUNK_BYTES = SHORT_READING_MAX_RANGE_BYTES
_BUDGET_COUNTER_FIELDS = (
    "first_work_units",
    "http_attempts",
    "input_tokens",
    "visible_output_tokens",
    "reasoning_tokens",
    "cost_microusd",
)


class _MapIdempotencyConflict(ValueError):
    pass


class _RecoveryRequired(RuntimeError):
    pass


class _RemoteAuthorizationError(ValueError):
    def __init__(self, code: CurationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class _ReadingProfileUnavailable(ValueError):
    pass


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or _SAFE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe lowercase token")
    return value


def _is_reparse(value: os.stat_result) -> bool:
    return bool(getattr(value, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _plain_directory(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or _is_reparse(value):
        raise OSError("path is not a plain directory")


def _plain_file(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or _is_reparse(value):
        raise OSError("path is not a plain file")


def _absolute(value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    return Path(os.path.abspath(path))


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        pass
    _plain_directory(path)


def _ensure_parents(root: Path, relative_paths: Sequence[str]) -> None:
    _plain_directory(root)
    directories = {
        PurePosixPath(value).parent
        for value in relative_paths
        if PurePosixPath(value).parent != PurePosixPath(".")
    }
    for relative in sorted(directories, key=lambda item: (len(item.parts), item.as_posix())):
        current = root
        for part in relative.parts:
            current = current / part
            _ensure_directory(current)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _read_bounded(path: Path) -> bytes:
    _plain_file(path)
    if path.stat().st_size > _MAX_INTERNAL_BYTES:
        raise ValueError("internal artifact exceeds its byte limit")
    return path.read_bytes()


def _read_canonical_mapping(path: Path) -> tuple[Mapping[str, object], bytes]:
    body = _read_bounded(path)
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, Mapping) or _canonical_json(value) != body:
        raise ValueError("internal artifact is not a canonical JSON object")
    return value, body


def _write_new_or_same(
    path: Path,
    body: bytes,
    durability: DurabilityBackend,
) -> None:
    try:
        durability.write_new_file_durable(path, body)
    except DestinationAlreadyExistsError:
        _plain_file(path)
        if _read_bounded(path) != body:
            raise _MapIdempotencyConflict(
                "existing artifact differs from the transaction"
            )


def _failure(
    code: CurationErrorCode,
    *,
    stage: str,
    state: CurationCommitState = CurationCommitState.NOT_COMMITTED,
    retryable: bool = False,
) -> CurationFailure:
    return CurationFailure(
        CurationError(code=code, retryable=retryable, details={"stage": stage}),
        state,
    )


def _validate_remote_authorization(
    authorization: RemoteProcessingAuthorization | None,
    *,
    source_request_id: str,
    run: CurationRunManifest,
    processor: ProcessorPort,
) -> dict[str, object] | None:
    provider_profile = processor.provider_profile
    if provider_profile is None:
        if authorization is not None:
            raise _RemoteAuthorizationError(CurationErrorCode.INVALID_INPUT)
        return None
    if authorization is None:
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_REQUIRED)
    if not isinstance(authorization, RemoteProcessingAuthorization):
        raise _RemoteAuthorizationError(CurationErrorCode.INVALID_INPUT)
    if (
        authorization.source_request_id != source_request_id
        or authorization.payload_sha256 != run.source.payload_sha256
        or authorization.allowed_range != run.declared_scope
        or authorization.provider_profile != provider_profile
        or authorization.model_id != processor.profile.model_id
    ):
        raise _RemoteAuthorizationError(
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
        )
    return authorization.as_mapping()


@dataclass(frozen=True, slots=True)
class MapBuildRequest:
    request_id: str
    source_request_id: str
    target_decision_request_id: str
    kb_parent: Path | None = None
    target_suggestion_request_id: str | None = None
    reading_profile: str | None = None

    def __post_init__(self) -> None:
        _token(self.request_id, "request_id")
        _token(self.source_request_id, "source_request_id")
        _token(self.target_decision_request_id, "target_decision_request_id")
        if self.target_suggestion_request_id is not None:
            _token(
                self.target_suggestion_request_id,
                "target_suggestion_request_id",
            )
        if self.kb_parent is not None:
            object.__setattr__(self, "kb_parent", _absolute(self.kb_parent))
        if self.reading_profile not in {None, _SHORT_READING_PROFILE}:
            raise ValueError("reading_profile is not supported")


@dataclass(frozen=True, slots=True)
class TargetSuggestRequest:
    request_id: str
    source_request_id: str
    suggested_by: str

    def __post_init__(self) -> None:
        _token(self.request_id, "request_id")
        _token(self.source_request_id, "source_request_id")
        _token(self.suggested_by, "suggested_by")


@dataclass(frozen=True, slots=True)
class TargetSuggestResult:
    request_id: str
    source_request_id: str
    synopsis: str
    suggestion_choice: str
    suggestion_rationale: str
    suggested_by: str
    suggested_at: str
    selected_locator_ids: tuple[str, ...]
    selected_segment_count: int
    total_segment_count: int
    selected_byte_size: int
    coverage_is_complete: bool
    result_path: Path
    replayed: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "request_id"),
            (self.source_request_id, "source_request_id"),
            (self.suggested_by, "suggested_by"),
        ):
            _token(value, label)
        if type(self.synopsis) is not str or not self.synopsis.strip():
            raise ValueError("synopsis must be non-blank text")
        if self.suggestion_choice not in {"new-kb", "no-target"}:
            raise ValueError("suggestion_choice is not supported")
        if type(self.suggestion_rationale) is not str or not self.suggestion_rationale.strip():
            raise ValueError("suggestion_rationale must be non-blank text")
        if not self.selected_locator_ids or len(set(self.selected_locator_ids)) != len(
            self.selected_locator_ids
        ):
            raise ValueError("selected_locator_ids must be non-empty and unique")
        if (
            type(self.selected_segment_count) is not int
            or type(self.total_segment_count) is not int
            or type(self.selected_byte_size) is not int
            or not 0 < self.selected_segment_count <= self.total_segment_count
            or self.selected_byte_size < 1
        ):
            raise ValueError("target suggestion coverage counts are invalid")
        if type(self.coverage_is_complete) is not bool:
            raise TypeError("coverage_is_complete must be boolean")
        if not isinstance(self.result_path, Path) or not self.result_path.is_absolute():
            raise ValueError("result_path must be absolute")
        if type(self.replayed) is not bool:
            raise TypeError("replayed must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "target.suggest",
            "request_id": self.request_id,
            "source_request_id": self.source_request_id,
            "synopsis": self.synopsis,
            "suggestion_choice": self.suggestion_choice,
            "suggestion_rationale": self.suggestion_rationale,
            "suggested_by": self.suggested_by,
            "suggested_at": self.suggested_at,
            "selected_locator_ids": list(self.selected_locator_ids),
            "selected_segment_count": self.selected_segment_count,
            "total_segment_count": self.total_segment_count,
            "selected_byte_size": self.selected_byte_size,
            "coverage_is_complete": self.coverage_is_complete,
            "requires_human_confirmation": True,
            "target_decision_recorded": False,
            "kb_created": False,
            "raw_routed": False,
            "result_path": str(self.result_path),
            "saved": True,
            "commit_state": CurationCommitState.COMMITTED.value,
            "replayed": self.replayed,
            "warnings": (
                []
                if self.coverage_is_complete
                else ["target synopsis is based on a bounded representative sample"]
            ),
        }


@dataclass(frozen=True, slots=True)
class MapBuildResult:
    request_id: str
    curation_map: CurationMap
    map_sha256: str
    yaml_sha256: str
    markdown_sha256: str
    yaml_path: Path
    markdown_path: Path
    run_record_path: Path
    target_repository: Path | None
    result_commit: str | None
    replayed: bool = False

    def __post_init__(self) -> None:
        _token(self.request_id, "request_id")
        if not isinstance(self.curation_map, CurationMap):
            raise TypeError("curation_map must be CurationMap")
        for value, label in (
            (self.map_sha256, "map_sha256"),
            (self.yaml_sha256, "yaml_sha256"),
            (self.markdown_sha256, "markdown_sha256"),
        ):
            if type(value) is not str or not value.startswith("sha256:"):
                raise ValueError(f"{label} must be SHA-256 text")
        for value in (self.yaml_path, self.markdown_path, self.run_record_path):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError("map result paths must be absolute")
        if (self.target_repository is None) != (self.result_commit is None):
            raise ValueError("target repository and result commit must appear together")
        if type(self.replayed) is not bool:
            raise TypeError("replayed must be boolean")

    def to_dict(self) -> dict[str, object]:
        usage = self.curation_map.processor_usage
        return {
            "ok": True,
            "operation": "map.build",
            "request_id": self.request_id,
            "curation_run_id": self.curation_map.curation_run_id,
            "map_id": self.curation_map.map_id,
            "map_version": self.curation_map.map_version,
            "map_sha256": self.map_sha256,
            "map_yaml_sha256": self.yaml_sha256,
            "map_markdown_sha256": self.markdown_sha256,
            "map_yaml_path": str(self.yaml_path),
            "map_markdown_path": str(self.markdown_path),
            "run_record_path": str(self.run_record_path),
            "target_kb_id": (
                None
                if self.curation_map.target_binding is None
                else self.curation_map.target_binding.kb_id
            ),
            "processor": self.curation_map.processor_profile.as_mapping(),
            "usage": usage.as_mapping(),
            "scope": [item.as_mapping() for item in self.curation_map.scope],
            "candidate_count": len(self.curation_map.candidates),
            "state": "map-ready",
            "wiki_written": False,
            "saved": True,
            "commit_state": CurationCommitState.COMMITTED.value,
            "result_commit": self.result_commit,
            "replayed": self.replayed,
            "warnings": [],
        }


@dataclass(frozen=True, slots=True)
class MapDecideRequest:
    request_id: str
    source_request_id: str
    target_decision_request_id: str
    map_id: str
    map_version: int
    outcome: str
    decided_by: str
    decisions: tuple[CandidateDecision, ...]
    kb_parent: Path | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "request_id"),
            (self.source_request_id, "source_request_id"),
            (self.target_decision_request_id, "target_decision_request_id"),
            (self.decided_by, "decided_by"),
        ):
            _token(value, label)
        if type(self.map_id) is not str or _MAP_ID.fullmatch(self.map_id) is None:
            raise ValueError("map_id must be a canonical map UUIDv7")
        if type(self.map_version) is not int or self.map_version < 1:
            raise ValueError("map_version must be positive")
        if self.outcome not in {
            "map-closed",
            "revision-requested",
            "change-requested",
            "deferred",
        }:
            raise ValueError("outcome is not supported")
        decisions = tuple(self.decisions)
        if not decisions or not all(isinstance(item, CandidateDecision) for item in decisions):
            raise ValueError("decisions must contain CandidateDecision values")
        if len({item.candidate_id for item in decisions}) != len(decisions):
            raise ValueError("candidate decisions must be unique")
        if any(item.action == "modify" for item in decisions) and self.outcome != "revision-requested":
            raise ValueError("candidate modification requires revision-requested")
        object.__setattr__(self, "decisions", decisions)
        if self.kb_parent is not None:
            object.__setattr__(self, "kb_parent", _absolute(self.kb_parent))


@dataclass(frozen=True, slots=True)
class MapDecisionResult:
    request_id: str
    decision: MapDecision
    decision_sha256: str
    decision_path: Path
    run_record_path: Path
    state: str
    revised_map: CurationMap | None = None
    revised_map_sha256: str | None = None
    result_commit: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        _token(self.request_id, "request_id")
        if not isinstance(self.decision, MapDecision):
            raise TypeError("decision must be MapDecision")
        if not isinstance(self.run_record_path, Path) or not self.run_record_path.is_absolute():
            raise ValueError("decision run record path must be absolute")
        if self.state not in {
            "map-closed",
            "revision-requested",
            "change-requested",
            "deferred",
        }:
            raise ValueError("decision state is invalid")
        if (self.revised_map is None) != (self.revised_map_sha256 is None):
            raise ValueError("revised map and digest must appear together")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "map.close" if self.state == "map-closed" else "map.decide",
            "request_id": self.request_id,
            "decision_set_id": self.decision.decision_set_id,
            "decision_version": self.decision.version,
            "decision_sha256": self.decision_sha256,
            "decision_path": str(self.decision_path),
            "decision_run_record_path": str(self.run_record_path),
            "map_sha256": self.decision.map_sha256,
            "state": self.state,
            "revised_map_id": None if self.revised_map is None else self.revised_map.map_id,
            "revised_map_version": (
                None if self.revised_map is None else self.revised_map.map_version
            ),
            "revised_map_sha256": self.revised_map_sha256,
            "result_commit": self.result_commit,
            "wiki_written": False,
            "saved": True,
            "commit_state": CurationCommitState.COMMITTED.value,
            "replayed": self.replayed,
            "warnings": [],
        }


MapBuildOperationResult = MapBuildResult | CurationFailure
MapDecisionOperationResult = MapDecisionResult | CurationFailure
TargetSuggestOperationResult = TargetSuggestResult | CurationFailure


@dataclass(frozen=True, slots=True)
class _Layout:
    root: Path
    config_path: Path
    work_root: Path
    transactions_root: Path
    staging_root: Path
    receipts_root: Path
    locks_root: Path
    suggestions_root: Path


def _layout(experiment_root: str | os.PathLike[str]) -> _Layout:
    root = _absolute(experiment_root)
    work = root / "curation-work"
    return _Layout(
        root=root,
        config_path=root / "capture-config.yaml",
        work_root=work,
        transactions_root=work / "map-transactions",
        staging_root=work / ".map-staging",
        receipts_root=work / ".map-receipts",
        locks_root=work / ".map-locks",
        suggestions_root=work / "target-suggestions",
    )


def _prepare_layout(layout: _Layout) -> None:
    _plain_directory(layout.root)
    _plain_directory(layout.work_root)
    for path in (
        layout.transactions_root,
        layout.staging_root,
        layout.receipts_root,
        layout.locks_root,
        layout.suggestions_root,
    ):
        _ensure_directory(path)


def _read_source_bytes(
    source: SourceInspectResult,
    *,
    config_path: Path,
    path_policy: PathPolicy,
) -> bytes:
    sink = io.BytesIO()
    result = get_capture(
        GetCaptureRequest(
            capture_id=source.run.source.capture_id,
            version=source.run.source.capture_version,
            body_sink=sink,
        ),
        config_path=config_path,
        path_policy=path_policy,
    )
    if isinstance(result, FailureResult):
        raise ValueError("exact Capture source cannot be read")
    body = sink.getvalue()
    if (
        len(body) != source.run.source.byte_size
        or hash_bytes(body).sha256 != source.run.source.payload_sha256
    ):
        raise ValueError("exact Capture source failed readback")
    body.decode("utf-8", errors="strict")
    return body


def _processor_segments(
    body: bytes,
    evidence: CurationEvidenceRecord,
) -> tuple[ProcessorSegment, ...]:
    locator_by_range = {
        (item.byte_range.start_byte, item.byte_range.end_byte): item
        for item in evidence.locators
    }
    result: list[ProcessorSegment] = []
    for segment in evidence.segments:
        selected = body[segment.byte_range.start_byte : segment.byte_range.end_byte]
        if hash_bytes(selected).sha256 != segment.body_sha256:
            raise ValueError("segment bytes failed integrity verification")
        locator = locator_by_range.get(
            (segment.byte_range.start_byte, segment.byte_range.end_byte)
        )
        if locator is None or locator.excerpt_sha256 != segment.body_sha256:
            raise ValueError("segment has no matching exact Evidence locator")
        result.append(
            ProcessorSegment(
                reference=f"s{segment.ordinal + 1:06d}",
                ordinal=segment.ordinal,
                heading_path=segment.heading_path,
                body=selected.decode("utf-8", errors="strict"),
                locator_id=locator.locator_id,
                byte_range=segment.byte_range,
            )
        )
    return tuple(result)


def _short_line_ranges(body: bytes) -> tuple[ByteRange, ...]:
    ranges: list[ByteRange] = []
    start = 0
    while start < len(body):
        newline = body.find(b"\n", start)
        line_end = len(body) if newline < 0 else newline + 1
        while start < line_end:
            end = min(start + _SHORT_LINE_CHUNK_BYTES, line_end)
            while end < line_end and body[end] & 0xC0 == 0x80:
                end -= 1
            if end <= start:
                raise ValueError("short reading unit has no UTF-8 boundary")
            ranges.append(ByteRange(start, end))
            start = end
    return tuple(ranges)


def _short_segments(
    body: bytes,
    ranges: Sequence[ByteRange],
    locator_ids: Sequence[str],
) -> tuple[ProcessorSegment, ...]:
    return tuple(
        ProcessorSegment(
            reference=f"line{index:04d}",
            ordinal=index - 1,
            heading_path=(),
            body=body[item.start_byte : item.end_byte].decode("utf-8", errors="strict"),
            locator_id=locator_id,
            byte_range=item,
        )
        for index, (item, locator_id) in enumerate(
            zip(ranges, locator_ids, strict=True), 1
        )
    )


def _short_reading_draft(segments: Sequence[ProcessorSegment]) -> ProcessorRequest:
    return ProcessorRequest(
        unit_id="short-map-001",
        stage=ProcessingStage.GLOBAL_MAP,
        task=(
            "Read the entire authorized short source in order and write a concise "
            "human-readable curation map in its language. Prefer one grounded overview "
            "and one structure/extraction-layer item, then select useful concepts, "
            "relationships, claims, uncertainties and visible gaps only where supported. "
            f"Use at most {SHORT_READING_MAX_CANDIDATES} self-contained, concise "
            "candidates with natural paragraph "
            "or short-list formatting; the limit is a ceiling, not a target. When the "
            "source supports multiple important concepts, entities or relationships, "
            "give each distinct item its own candidate and its own directly relevant "
            "line evidence_refs. Do not bundle several independent items into one "
            "candidate or spend the response mostly on repeated claims. Do not pad "
            "sections, repeat the "
            "same point, invent facts, promise exhaustive extraction or propose a KB "
            "structure for this no-target task. Put exact disclosed line refs only in "
            "evidence_refs, never machine references or locator IDs in summary text. "
            "Use separate candidates for distinct claims, and short lines "
            "or lists where that makes the summary easier to scan. Explain why any "
            "extraction layer is useful, distinguish why an item is uncertain, and "
            "separate source omissions from processing limits. Cite concrete claims, "
            "relationships and disputes with exact refs. Preserve quotation, speaker "
            "and fictional narrative layers; distinguish source content from inference. "
            "Return no focus topics."
        ),
        segments=tuple(segments),
        thinking=True,
        reasoning_effort="low",
        max_visible_tokens=4096,
        max_reasoning_tokens=6144,
        planned_input_tokens=1,
        prompt_profile=SHORT_READING_PROCESSOR_PROFILE,
        prompt_profile_revision=SHORT_READING_PROCESSOR_PROFILE_REVISION,
    )


def _short_direct_plan(
    body: bytes,
    run: CurationRunManifest,
    evidence: CurationEvidenceRecord,
    counter: TokenCounter,
    *,
    no_target: bool,
) -> tuple[ByteRange, ...] | None:
    if (
        not no_target
        or len(body) > _SHORT_DIRECT_MAX_BYTES
        or evidence.declared_scope != ByteRange(0, len(body))
        or run.processing_authorization.allowed_range != evidence.declared_scope
        or len(evidence.scope) != 1
        or evidence.scope[0].status != "processed"
    ):
        return None
    ranges = _short_line_ranges(body)
    if not ranges or len(ranges) > _SHORT_DIRECT_MAX_UNITS:
        return None
    planned_segments = _short_segments(body, ranges, ("planned",) * len(ranges))
    try:
        _planned_request(_short_reading_draft(planned_segments), counter)
    except BudgetExhausted:
        return None
    return ranges


def _short_review_locators(
    *,
    body: bytes,
    source: CurationRunManifest,
    ranges: Sequence[ByteRange],
    transaction: Path,
    durability: DurabilityBackend,
) -> tuple[EvidenceLocator, ...]:
    path = transaction / "short-review-locators.json"
    expected_ranges = [item.as_mapping() for item in ranges]
    if path.exists():
        record = json.loads(_read_bounded(path).decode("utf-8"))
        if (
            not isinstance(record, Mapping)
            or set(record) != {"schema", "schema_version", "source", "ranges", "locators"}
            or record["schema"] != "knowledgeflow.short-review-locators"
            or record["schema_version"] != 1
            or record["source"] != source.source.as_mapping()
            or record["ranges"] != expected_ranges
            or not isinstance(record["locators"], list)
        ):
            raise ValueError("stored short review locator plan differs from the source")
        locators = tuple(
            EvidenceLocator.from_mapping(item) for item in record["locators"]
        )
    else:
        locators = tuple(
            EvidenceLocator(
                locator_id=generate_curation_id("loc_"),
                source=source.source,
                byte_range=item,
                start_line=body.count(b"\n", 0, item.start_byte) + 1,
                end_line=body.count(b"\n", 0, item.end_byte - 1) + 1,
                excerpt_sha256=hash_bytes(
                    body[item.start_byte : item.end_byte]
                ).sha256,
            )
            for item in ranges
        )
        _write_new_or_same(
            path,
            _canonical_json(
                {
                    "schema": "knowledgeflow.short-review-locators",
                    "schema_version": 1,
                    "source": source.source.as_mapping(),
                    "ranges": expected_ranges,
                    "locators": [item.as_mapping() for item in locators],
                }
            ),
            durability,
        )
    if len(locators) != len(ranges) or any(
        locator.source != source.source
        or locator.byte_range != byte_range
        or locator.excerpt_sha256
        != hash_bytes(body[byte_range.start_byte : byte_range.end_byte]).sha256
        or locator.start_line != body.count(b"\n", 0, byte_range.start_byte) + 1
        or locator.end_line != body.count(b"\n", 0, byte_range.end_byte - 1) + 1
        for locator, byte_range in zip(locators, ranges, strict=True)
    ):
        raise ValueError("stored short review locator facts do not match exact source bytes")
    return locators


def _planned_request(
    request: ProcessorRequest,
    counter: TokenCounter,
    *,
    hard_limit: int = _INPUT_HARD_LIMIT,
) -> ProcessorRequest:
    planned = counter.count_request(request) + _TOKEN_PLANNING_SAFETY_MARGIN
    if planned > hard_limit:
        raise BudgetExhausted("planned request exceeds its input token hard limit")
    return replace(request, planned_input_tokens=planned)


def _l1_draft(
    unit_id: str,
    segments: Sequence[ProcessorSegment],
) -> ProcessorRequest:
    return ProcessorRequest(
        unit_id=unit_id,
        stage=ProcessingStage.L1_WINDOW,
        task=(
            "Describe the main content and structure covered by this heading-tree "
            "window; separate source claims from inference and retain evidence refs."
        ),
        segments=tuple(segments),
        thinking=False,
        max_visible_tokens=2048,
        planned_input_tokens=1,
    )


def _heading_tree_root(segment: ProcessorSegment) -> str | None:
    return segment.heading_path[0] if segment.heading_path else None


def _same_heading_tree(
    current: Sequence[ProcessorSegment],
    candidate: ProcessorSegment,
) -> bool:
    if not current:
        return True
    return _heading_tree_root(current[0]) == _heading_tree_root(candidate)


def _l1_requests(
    segments: Sequence[ProcessorSegment],
    counter: TokenCounter,
) -> tuple[ProcessorRequest, ...]:
    windows: list[tuple[ProcessorSegment, ...]] = []
    current: list[ProcessorSegment] = []
    for segment in segments:
        if current and not _same_heading_tree(current, segment):
            windows.append(tuple(current))
            current = []
        candidate = (*current, segment)
        try:
            planned = _planned_request(_l1_draft("l1-001", candidate), counter)
        except BudgetExhausted:
            if not current:
                raise BudgetExhausted(
                    "one Segment exceeds the request input hard limit"
                )
            windows.append(tuple(current))
            current = [segment]
            _planned_request(_l1_draft("l1-001", current), counter)
            continue
        if current and planned.planned_input_tokens > _L1_TARGET_TOKENS:
            windows.append(tuple(current))
            current = [segment]
            _planned_request(_l1_draft("l1-001", current), counter)
        else:
            current = list(candidate)
    if current:
        windows.append(tuple(current))
    if len(windows) > 48:
        raise BudgetExhausted("L1 processing requires more than 48 windows")
    return tuple(
        _planned_request(
            _l1_draft(f"l1-{index:03d}", window),
            counter,
        )
        for index, window in enumerate(windows, 1)
    )


def _prior_candidates(units: Sequence[ExecutedUnit]) -> tuple[PriorCandidate, ...]:
    result: list[PriorCandidate] = []
    for unit in units:
        for index, candidate in enumerate(unit.response.candidates, 1):
            result.append(
                PriorCandidate(
                    reference=f"{unit.request.unit_id}-c{index:03d}",
                    kind=candidate.kind,
                    summary=candidate.summary,
                    evidence_refs=candidate.evidence_refs,
                    provenance=candidate.provenance,
                    uncertainty=candidate.uncertainty,
                )
            )
    return tuple(result)


def _section_requests(
    l1_units: Sequence[ExecutedUnit],
    counter: TokenCounter,
) -> tuple[ProcessorRequest, ...]:
    if not l1_units:
        raise ValueError("section synthesis requires L1 results")
    group_size = max(1, (len(l1_units) + 11) // 12)
    result: list[ProcessorRequest] = []
    for index, offset in enumerate(range(0, len(l1_units), group_size), 1):
        selected = l1_units[offset : offset + group_size]
        result.append(
            _planned_request(
                ProcessorRequest(
                    unit_id=f"section-{index:03d}",
                    stage=ProcessingStage.SECTION_SYNTHESIS,
                    task=(
                        "Synthesize this ordered part from validated window candidates; "
                        "retain evidence refs and identify only material relationships or gaps."
                    ),
                    segments=(),
                    prior_candidates=_prior_candidates(selected),
                    thinking=True,
                    reasoning_effort="low",
                    max_visible_tokens=3072,
                    max_reasoning_tokens=5120,
                    planned_input_tokens=1,
                ),
                counter,
            )
        )
    return tuple(result)


def _global_request(
    section_units: Sequence[ExecutedUnit],
    counter: TokenCounter,
) -> ProcessorRequest:
    return _planned_request(
        ProcessorRequest(
            unit_id="global-001",
            stage=ProcessingStage.GLOBAL_MAP,
            task=(
                "Create a thin whole-source map: overview, major parts, a small number "
                "of cross-part repetitions/evolutions/conflicts, visible gaps, next steps, "
                "and at most five justified focus topics."
            ),
            segments=(),
            prior_candidates=_prior_candidates(section_units),
            thinking=True,
            reasoning_effort="low",
            max_visible_tokens=8192,
            max_reasoning_tokens=8192,
            planned_input_tokens=1,
        ),
        counter,
    )


def _focus_requests(
    global_unit: ExecutedUnit,
    segments: Sequence[ProcessorSegment],
    counter: TokenCounter,
) -> tuple[ProcessorRequest, ...]:
    by_reference = {item.reference: item for item in segments}
    priors = _prior_candidates((global_unit,))
    result: list[ProcessorRequest] = []
    for index, topic in enumerate(global_unit.response.focus_topics[:5], 1):
        selected = tuple(by_reference[ref] for ref in topic.evidence_refs if ref in by_reference)
        if not selected:
            raise ValueError("focus topic cannot be mapped to exact source segments")
        result.append(
            _planned_request(
                ProcessorRequest(
                    unit_id=f"focus-{index:03d}",
                    stage=ProcessingStage.FOCUS_DEEPENING,
                    task=(
                        f"Deepen only this focus: {topic.title}. Reason: {topic.rationale}. "
                        "Explain what, why, evidence, limitations, and a bounded next step."
                    ),
                    segments=selected,
                    prior_candidates=priors,
                    thinking=True,
                    reasoning_effort="low",
                    max_visible_tokens=4096,
                    max_reasoning_tokens=6144,
                    planned_input_tokens=1,
                ),
                counter,
            )
        )
    return tuple(result)


def _request_digest(request: ProcessorRequest) -> str:
    body = _canonical_json(
        {
            "provider_payload": request.provider_mapping(),
            "thinking": request.thinking,
            "reasoning_effort": request.reasoning_effort,
            "max_visible_tokens": request.max_visible_tokens,
            "max_reasoning_tokens": request.max_reasoning_tokens,
            "planned_input_tokens": request.planned_input_tokens,
        }
    )
    return hash_bytes(body).sha256


def _request_metadata(request: ProcessorRequest) -> dict[str, object]:
    return {
        "segment_references": [item.reference for item in request.segments],
        "heading_paths": [list(item.heading_path) for item in request.segments],
        "segment_ranges": [
            None if item.byte_range is None else item.byte_range.as_mapping()
            for item in request.segments
        ],
        "segment_body_sha256": [
            hash_bytes(item.body.encode("utf-8")).sha256
            for item in request.segments
        ],
        "prior_candidate_references": [
            item.reference for item in request.prior_candidates
        ],
        "thinking": request.thinking,
        "reasoning_effort": request.reasoning_effort,
        "max_visible_tokens": request.max_visible_tokens,
        "max_reasoning_tokens": request.max_reasoning_tokens,
        "planned_input_tokens": request.planned_input_tokens,
    }


def _token_counter_profile(counter: TokenCounter) -> dict[str, object]:
    if (
        not callable(getattr(counter, "profile_mapping", None))
        or not callable(getattr(counter, "count_request", None))
        or type(getattr(counter, "profile_id", None)) is not str
        or type(getattr(counter, "revision", None)) is not int
    ):
        raise TypeError("token_counter does not implement TokenCounter")
    value = counter.profile_mapping()
    required = {
        "profile_id",
        "revision",
        "mode",
        "model_id",
        "implementation",
        "implementation_version",
        "asset_source",
        "asset_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("token counter profile is invalid")
    result = dict(value)
    if (
        result["profile_id"] != counter.profile_id
        or result["revision"] != counter.revision
        or type(result["profile_id"]) is not str
        or type(result["revision"]) is not int
        or result["mode"]
        not in {"model-prompt-estimate", "conservative-byte-estimate"}
        or type(result["implementation"]) is not str
    ):
        raise ValueError("token counter profile identity is invalid")
    for key in (
        "model_id",
        "implementation_version",
        "asset_source",
        "asset_sha256",
    ):
        if result[key] is not None and type(result[key]) is not str:
            raise ValueError("token counter profile value is invalid")
    asset_sha256 = result["asset_sha256"]
    if asset_sha256 is not None and re.fullmatch(
        r"sha256:[0-9a-f]{64}", cast(str, asset_sha256)
    ) is None:
        raise ValueError("token counter asset digest is invalid")
    return result


def _require_counter_processor_match(
    profile: Mapping[str, object],
    processor: ProcessorPort,
) -> None:
    expected_model = processor.profile.model_id
    observed_model = profile["model_id"]
    if processor.profile.network_allowed:
        if expected_model is None or observed_model != expected_model:
            raise ValueError(
                "remote processing requires an explicit token counter for the exact model"
            )
    elif observed_model is not None:
        raise ValueError("offline processors require a model-neutral token counter")


def _processing_window_profile() -> dict[str, object]:
    return {
        "profile_id": _PROCESSING_WINDOW_PROFILE,
        "revision": _PROCESSING_WINDOW_PROFILE_REVISION,
        "grouping": "contiguous-segments-within-one-top-level-heading-tree",
        "target_input_tokens": _L1_TARGET_TOKENS,
        "hard_input_tokens": _INPUT_HARD_LIMIT,
        "planning_safety_margin_tokens": _TOKEN_PLANNING_SAFETY_MARGIN,
        "maximum_l1_windows": 48,
    }


def _short_processing_window_profile() -> dict[str, object]:
    return {
        "profile_id": _SHORT_READING_PROFILE,
        "revision": 1,
        "grouping": "complete-source-in-ordered-utf8-line-ranges",
        "maximum_source_bytes": _SHORT_DIRECT_MAX_BYTES,
        "maximum_line_ranges": _SHORT_DIRECT_MAX_UNITS,
        "maximum_range_bytes": _SHORT_LINE_CHUNK_BYTES,
        "hard_input_tokens": _INPUT_HARD_LIMIT,
        "planning_safety_margin_tokens": _TOKEN_PLANNING_SAFETY_MARGIN,
    }


def _response_mapping(response: ProcessorResponse) -> dict[str, object]:
    return {
        "synopsis": response.synopsis,
        "target_choice": response.target_choice,
        "target_rationale": response.target_rationale,
        "candidates": [
            {
                "kind": item.kind,
                "summary": item.summary,
                "evidence_refs": list(item.evidence_refs),
                "provenance": item.provenance,
                "uncertainty": item.uncertainty,
                "markdown_anchor": item.markdown_anchor,
            }
            for item in response.candidates
        ],
        "focus_topics": [
            {
                "title": item.title,
                "evidence_refs": list(item.evidence_refs),
                "rationale": item.rationale,
            }
            for item in response.focus_topics
        ],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "visible_output_tokens": response.usage.visible_output_tokens,
            "reasoning_tokens": response.usage.reasoning_tokens,
            "elapsed_ms": response.usage.elapsed_ms,
            "response_model": response.usage.response_model,
            "system_fingerprint": response.usage.system_fingerprint,
            "finish_reason": response.usage.finish_reason,
        },
    }


def _response_from_mapping(value: object) -> ProcessorResponse:
    if not isinstance(value, Mapping) or set(value) != {
        "synopsis",
        "target_choice",
        "target_rationale",
        "candidates",
        "focus_topics",
        "usage",
    }:
        raise ValueError("stored processor response is invalid")
    candidates_raw = value.get("candidates")
    topics_raw = value.get("focus_topics")
    usage_raw = value.get("usage")
    if (
        not isinstance(candidates_raw, list)
        or not isinstance(topics_raw, list)
        or not isinstance(usage_raw, Mapping)
        or set(usage_raw) != {
            "input_tokens",
            "visible_output_tokens",
            "reasoning_tokens",
            "elapsed_ms",
            "response_model",
            "system_fingerprint",
            "finish_reason",
        }
    ):
        raise ValueError("stored processor response has invalid collections")
    if any(
        not isinstance(item, Mapping)
        or set(item)
        != {
            "kind",
            "summary",
            "evidence_refs",
            "provenance",
            "uncertainty",
            "markdown_anchor",
        }
        or not isinstance(item["evidence_refs"], list)
        or not all(type(reference) is str for reference in item["evidence_refs"])
        for item in candidates_raw
    ):
        raise ValueError("stored candidate response is invalid")
    if any(
        not isinstance(item, Mapping)
        or set(item) != {"title", "evidence_refs", "rationale"}
        or not isinstance(item["evidence_refs"], list)
        or not all(type(reference) is str for reference in item["evidence_refs"])
        for item in topics_raw
    ):
        raise ValueError("stored focus response is invalid")
    candidates = tuple(
        ProcessorCandidateDraft(
            kind=item["kind"],
            summary=item["summary"],
            evidence_refs=tuple(item["evidence_refs"]),
            provenance=item["provenance"],
            uncertainty=item["uncertainty"],
            markdown_anchor=item["markdown_anchor"],
        )
        for item in candidates_raw
        if isinstance(item, Mapping)
    )
    if len(candidates) != len(candidates_raw):
        raise ValueError("stored candidate response is invalid")
    topics = tuple(
        FocusTopic(
            title=item["title"],
            evidence_refs=tuple(item["evidence_refs"]),
            rationale=item["rationale"],
        )
        for item in topics_raw
        if isinstance(item, Mapping)
    )
    if len(topics) != len(topics_raw):
        raise ValueError("stored focus response is invalid")
    return ProcessorResponse(
        synopsis=value.get("synopsis"),
        target_choice=value.get("target_choice"),
        target_rationale=value.get("target_rationale"),
        candidates=candidates,
        focus_topics=topics,
        usage=ProcessorCallUsage(
            input_tokens=usage_raw.get("input_tokens"),
            visible_output_tokens=usage_raw.get("visible_output_tokens"),
            reasoning_tokens=usage_raw.get("reasoning_tokens"),
            elapsed_ms=usage_raw.get("elapsed_ms"),
            response_model=usage_raw.get("response_model"),
            system_fingerprint=usage_raw.get("system_fingerprint"),
            finish_reason=usage_raw.get("finish_reason"),
        ),
    )


def _ledger_mapping(ledger: ProcessingBudgetLedger) -> dict[str, int]:
    return ledger.as_mapping()


def _unit_record_mapping(
    executed: ExecutedUnit,
    ledger: ProcessingBudgetLedger,
) -> dict[str, object]:
    return {
        "schema": "knowledgeflow.curation-processor-unit",
        "schema_version": 1,
        "unit_id": executed.request.unit_id,
        "stage": executed.request.stage.value,
        "request_sha256": _request_digest(executed.request),
        "request_metadata": _request_metadata(executed.request),
        "attempts": [item.as_mapping() for item in executed.attempts],
        "response": _response_mapping(executed.response),
        "budget_after": _ledger_mapping(ledger),
    }


def _attempt_reservation_mapping(
    request: ProcessorRequest,
    attempt: int,
    budget_before: Mapping[str, int],
    ledger: ProcessingBudgetLedger,
) -> dict[str, object]:
    return {
        "schema": "knowledgeflow.curation-processor-attempt-reservation",
        "schema_version": 1,
        "unit_id": request.unit_id,
        "stage": request.stage.value,
        "request_sha256": _request_digest(request),
        "request_metadata": _request_metadata(request),
        "attempt": attempt,
        "budget_before": dict(budget_before),
        "budget_after_reservation": _ledger_mapping(ledger),
    }


def _attempt_result_mapping(
    request: ProcessorRequest,
    record: AttemptRecord,
    ledger: ProcessingBudgetLedger,
    *,
    response: ProcessorResponse | None,
    request_sent: bool | None,
    retry_after_seconds: int | None,
    recovered_after_interruption: bool,
    diagnostic: ProcessorFailureDiagnostic | None,
) -> dict[str, object]:
    return {
        "schema": "knowledgeflow.curation-processor-attempt-result",
        "schema_version": 1,
        "unit_id": request.unit_id,
        "stage": request.stage.value,
        "request_sha256": _request_digest(request),
        "attempt": record.attempt,
        "status": record.status,
        "retryable": record.retryable,
        "unknown_usage": record.unknown_usage,
        "http_status": record.http_status,
        "request_sent": request_sent,
        "retry_after_seconds": retry_after_seconds,
        "recovered_after_interruption": recovered_after_interruption,
        "diagnostic": None if diagnostic is None else diagnostic.as_mapping(),
        "response": None if response is None else _response_mapping(response),
        "budget_after": _ledger_mapping(ledger),
    }


def _attempt_paths(
    transaction: Path,
    request: ProcessorRequest,
    attempt: int,
) -> tuple[Path, Path]:
    stem = f"attempt-{request.unit_id}-{attempt:02d}"
    return transaction / f"{stem}-reserved.json", transaction / f"{stem}-result.json"


def _attempt_record_from_result(value: Mapping[str, object]) -> AttemptRecord:
    attempt = value["attempt"]
    status = value["status"]
    retryable = value["retryable"]
    unknown_usage = value["unknown_usage"]
    http_status = value["http_status"]
    if (
        type(attempt) is not int
        or not 1 <= attempt <= 3
        or type(status) is not str
        or type(retryable) is not bool
        or type(unknown_usage) is not bool
        or (
            http_status is not None
            and (type(http_status) is not int or not 100 <= http_status <= 599)
        )
    ):
        raise ValueError("stored processor attempt result is invalid")
    record = AttemptRecord(
        attempt=attempt,
        status=status,
        retryable=retryable,
        unknown_usage=unknown_usage,
        http_status=cast(int | None, http_status),
    )
    if status == "succeeded":
        if retryable or unknown_usage or http_status != 200:
            raise ValueError("stored successful processor attempt is invalid")
    elif status == "unknown":
        if not unknown_usage:
            raise ValueError("stored unknown processor attempt is invalid")
    elif status == "failed":
        if unknown_usage:
            raise ValueError("stored failed processor attempt is invalid")
    else:
        raise ValueError("stored processor attempt status is invalid")
    return record


def _load_attempt_result(
    path: Path,
    request: ProcessorRequest,
    attempt: int,
    ledger: ProcessingBudgetLedger,
) -> tuple[AttemptRecord, ProcessorResponse | None, int | None]:
    value = json.loads(_read_bounded(path).decode("utf-8"))
    required = {
        "schema",
        "schema_version",
        "unit_id",
        "stage",
        "request_sha256",
        "attempt",
        "status",
        "retryable",
        "unknown_usage",
        "http_status",
        "request_sent",
        "retry_after_seconds",
        "recovered_after_interruption",
        "response",
        "budget_after",
    }
    allowed = required | {"diagnostic"}
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or not set(value).issubset(allowed)
    ):
        raise ValueError("stored processor attempt result is invalid")
    if (
        value["schema"] != "knowledgeflow.curation-processor-attempt-result"
        or value["schema_version"] != 1
        or value["unit_id"] != request.unit_id
        or value["stage"] != request.stage.value
        or value["request_sha256"] != _request_digest(request)
        or value["attempt"] != attempt
        or type(value["recovered_after_interruption"]) is not bool
    ):
        raise ValueError("stored processor attempt does not match the request")
    request_sent = value["request_sent"]
    recovered = value["recovered_after_interruption"]
    if request_sent is not None and type(request_sent) is not bool:
        raise ValueError("stored processor send state is invalid")
    retry_after = value["retry_after_seconds"]
    if retry_after is not None and (
        type(retry_after) is not int or not 0 <= retry_after <= 60
    ):
        raise ValueError("stored processor retry delay is invalid")
    record = _attempt_record_from_result(value)
    diagnostic_raw = value.get("diagnostic")
    diagnostic = (
        None
        if diagnostic_raw is None
        else ProcessorFailureDiagnostic.from_mapping(diagnostic_raw)
    )
    if retry_after is not None and not record.retryable:
        raise ValueError("stored non-retryable attempt has a retry delay")
    if recovered:
        if (
            request_sent is not None
            or record.status != "unknown"
            or record.retryable
            or not record.unknown_usage
            or record.http_status is not None
            or retry_after is not None
            or diagnostic is not None
        ):
            raise ValueError("stored interrupted attempt recovery is invalid")
    elif type(request_sent) is not bool:
        raise ValueError("stored live attempt send state is invalid")
    response: ProcessorResponse | None = None
    if record.status == "succeeded":
        if (
            value["response"] is None
            or request_sent is not True
            or diagnostic is not None
        ):
            raise ValueError("stored successful processor response is missing")
        response = _response_from_mapping(value["response"])
        response.validate_against(request)
        try:
            ledger.record_success(response.usage, request=request)
        except BudgetExhausted:
            if value["budget_after"] != ledger.as_mapping():
                raise ValueError("stored processor budget ledger is not reproducible")
            raise
    else:
        if value["response"] is not None:
            raise ValueError("stored failed processor attempt has a response")
        if diagnostic is not None and request_sent is not True:
            raise ValueError("stored processor diagnostic has no sent request")
        if diagnostic is not None and (
            record.http_status != 200
            or (diagnostic.usage is None) != record.unknown_usage
        ):
            raise ValueError("stored processor diagnostic state is inconsistent")
        if diagnostic is not None and diagnostic.usage is not None:
            try:
                ledger.record_observed_usage(diagnostic.usage, request=request)
            except BudgetExhausted:
                if value["budget_after"] != ledger.as_mapping():
                    raise ValueError(
                        "stored processor budget ledger is not reproducible"
                    )
                raise
        elif record.unknown_usage:
            ledger.record_unknown(request)
    if value["budget_after"] != ledger.as_mapping():
        raise ValueError("stored processor budget ledger is not reproducible")
    return record, response, cast(int | None, retry_after)


def _record_live_attempt_error(
    result_path: Path,
    request: ProcessorRequest,
    ledger: ProcessingBudgetLedger,
    durability: DurabilityBackend,
    *,
    attempt: int,
    error: ProcessorCallError,
) -> AttemptRecord:
    record = AttemptRecord(
        attempt=attempt,
        status="unknown" if error.unknown_usage else "failed",
        retryable=error.retryable,
        unknown_usage=error.unknown_usage,
        http_status=error.http_status,
    )
    budget_error: BudgetExhausted | None = None
    try:
        if error.diagnostic is not None and error.diagnostic.usage is not None:
            ledger.record_observed_usage(error.diagnostic.usage, request=request)
        elif error.unknown_usage:
            ledger.record_unknown(request)
    except BudgetExhausted as exc:
        budget_error = exc
    _write_new_or_same(
        result_path,
        _canonical_json(
            _attempt_result_mapping(
                request,
                record,
                ledger,
                response=None,
                request_sent=error.request_sent,
                retry_after_seconds=error.retry_after_seconds,
                recovered_after_interruption=False,
                diagnostic=error.diagnostic,
            )
        ),
        durability,
    )
    if budget_error is not None:
        raise budget_error
    return record


def _execute_unit(
    transaction: Path,
    processor: ProcessorPort,
    request: ProcessorRequest,
    ledger: ProcessingBudgetLedger,
    durability: DurabilityBackend,
    sleeper: Callable[[float], None],
) -> ExecutedUnit:
    path = transaction / f"unit-{request.unit_id}.json"
    first_reservation, _first_result = _attempt_paths(transaction, request, 1)
    if path.exists() and not first_reservation.exists():
        raise ValueError("stored processor unit has no attempt journal")
    attempts: list[AttemptRecord] = []
    for attempt in range(1, 4):
        reservation_path, result_path = _attempt_paths(
            transaction,
            request,
            attempt,
        )
        reservation_existed = reservation_path.exists()
        result_existed = result_path.exists()
        if result_existed and not reservation_existed:
            raise ValueError("stored processor result has no reservation")
        budget_before = ledger.as_mapping()
        ledger.reserve_attempt(request, first_attempt=attempt == 1)
        _write_new_or_same(
            reservation_path,
            _canonical_json(
                _attempt_reservation_mapping(
                    request,
                    attempt,
                    budget_before,
                    ledger,
                )
            ),
            durability,
        )

        if result_existed:
            record, response, retry_after = _load_attempt_result(
                result_path,
                request,
                attempt,
                ledger,
            )
        elif reservation_existed:
            # A durable reservation without a durable result means the old
            # process may have transmitted the request.  Charge the worst case
            # and terminate this immutable unit instead of sending it again.
            ledger.record_unknown(request)
            record = AttemptRecord(attempt, "unknown", False, True, None)
            response = None
            retry_after = None
            _write_new_or_same(
                result_path,
                _canonical_json(
                    _attempt_result_mapping(
                        request,
                        record,
                        ledger,
                        response=None,
                        request_sent=None,
                        retry_after_seconds=None,
                        recovered_after_interruption=True,
                        diagnostic=None,
                    )
                ),
                durability,
            )
        else:
            try:
                response = processor.process(request)
                response.validate_against(request)
            except ProcessorCallError as exc:
                record = _record_live_attempt_error(
                    result_path,
                    request,
                    ledger,
                    durability,
                    attempt=attempt,
                    error=exc,
                )
                retry_after = exc.retry_after_seconds
                response = None
            except Exception as exc:
                wrapped = ProcessorCallError(
                    "processor attempt ended without a classified response",
                    retryable=False,
                    request_sent=True,
                    unknown_usage=True,
                )
                record = _record_live_attempt_error(
                    result_path,
                    request,
                    ledger,
                    durability,
                    attempt=attempt,
                    error=wrapped,
                )
                wrapped.attempt_records = tuple((*attempts, record))
                raise wrapped from exc
            else:
                record = AttemptRecord(attempt, "succeeded", False, False, 200)
                try:
                    ledger.record_success(response.usage, request=request)
                except BudgetExhausted:
                    _write_new_or_same(
                        result_path,
                        _canonical_json(
                            _attempt_result_mapping(
                                request,
                                record,
                                ledger,
                                response=response,
                                request_sent=True,
                                retry_after_seconds=None,
                                recovered_after_interruption=False,
                                diagnostic=None,
                            )
                        ),
                        durability,
                    )
                    raise
                _write_new_or_same(
                    result_path,
                    _canonical_json(
                        _attempt_result_mapping(
                            request,
                            record,
                            ledger,
                            response=response,
                            request_sent=True,
                            retry_after_seconds=None,
                            recovered_after_interruption=False,
                            diagnostic=None,
                        )
                    ),
                    durability,
                )
                retry_after = None

        attempts.append(record)
        if response is not None:
            executed = ExecutedUnit(request, response, tuple(attempts))
            expected = _canonical_json(_unit_record_mapping(executed, ledger))
            if path.exists():
                if _read_bounded(path) != expected:
                    raise ValueError("stored processor unit record is invalid")
            else:
                _write_new_or_same(path, expected, durability)
            return executed

        if not record.retryable or attempt == 3:
            exc = ProcessorCallError(
                "processor attempt journal contains a terminal result",
                retryable=record.retryable,
                request_sent=True,
                unknown_usage=record.unknown_usage,
                http_status=record.http_status,
                retry_after_seconds=retry_after,
            )
            exc.attempt_records = tuple(attempts)
            raise exc
        delay = (2, 8)[attempt - 1]
        if retry_after is not None:
            delay = retry_after
        sleeper(float(delay))
    raise AssertionError("processor retry loop ended unexpectedly")


def _persist_processing_stop(
    transaction: Path | None,
    evidence: CurationEvidenceRecord | None,
    ledger: ProcessingBudgetLedger | None,
    *,
    error_code: CurationErrorCode,
    stop_reason: str,
    durability: DurabilityBackend,
) -> None:
    if transaction is None or evidence is None or ledger is None:
        return
    processed: set[str] = set()
    completed_units: list[str] = []
    for path in sorted(transaction.glob("unit-*.json"), key=lambda item: item.name):
        value = json.loads(_read_bounded(path).decode("utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("stored processor unit record is invalid")
        metadata = value.get("request_metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("stored processor request metadata is invalid")
        references = metadata.get("segment_references")
        if not isinstance(references, list) or not all(
            type(item) is str for item in references
        ):
            raise ValueError("stored processor segment references are invalid")
        if value.get("stage") == ProcessingStage.L1_WINDOW.value:
            processed.update(cast(list[str], references))
        unit_id = value.get("unit_id")
        if type(unit_id) is not str:
            raise ValueError("stored processor unit identity is invalid")
        completed_units.append(unit_id)
    scope = []
    for segment in evidence.segments:
        reference = f"s{segment.ordinal + 1:06d}"
        scope.append(
            {
                "segment_reference": reference,
                "start_byte": segment.byte_range.start_byte,
                "end_byte": segment.byte_range.end_byte,
                "status": "processed" if reference in processed else "deferred",
            }
        )
    body = _canonical_json(
        {
            "schema": "knowledgeflow.curation-processing-stop",
            "schema_version": 1,
            "error_code": error_code.value,
            "stop_reason": stop_reason,
            "completed_units": completed_units,
            "budget": ledger.as_mapping(),
            "scope": scope,
            "map_published": False,
            "wiki_written": False,
        }
    )
    digest = hash_bytes(body).sha256.removeprefix("sha256:")[:16]
    _write_new_or_same(transaction / f"stop-{digest}.json", body, durability)


def _utf8_sample(
    segment: ProcessorSegment,
    *,
    maximum_bytes: int,
    position: str,
) -> ProcessorSegment:
    """Return one exact UTF-8 subrange while retaining its parent Evidence locator."""

    if segment.byte_range is None:
        raise ValueError("target sampling requires exact source byte ranges")
    raw = segment.body.encode("utf-8")
    if len(raw) <= maximum_bytes:
        return segment
    if position == "start":
        start = 0
    elif position == "middle":
        start = max(0, (len(raw) - maximum_bytes) // 2)
    elif position == "end":
        start = max(0, len(raw) - maximum_bytes)
    else:
        raise ValueError("target sample position is unsupported")
    while start < len(raw) and raw[start] & 0xC0 == 0x80:
        start += 1
    end = min(len(raw), start + maximum_bytes)
    while end > start and end < len(raw) and raw[end] & 0xC0 == 0x80:
        end -= 1
    if end <= start:
        raise ValueError("target sample cannot preserve a UTF-8 boundary")
    selected = raw[start:end]
    return replace(
        segment,
        body=selected.decode("utf-8", errors="strict"),
        byte_range=ByteRange(
            segment.byte_range.start_byte + start,
            segment.byte_range.start_byte + end,
        ),
    )


def _target_summary_draft(
    segments: Sequence[ProcessorSegment],
) -> ProcessorRequest:
    return ProcessorRequest(
        unit_id="target-summary-001",
        stage=ProcessingStage.TARGET_SUMMARY,
        task=(
            "Using only these disclosed representative source samples, provide a "
            "minimal synopsis and a non-authoritative new-kb or no-target suggestion. "
            "The samples come from the beginning, middle, and end when those ranges "
            "exist. Do not claim that unselected source ranges were reviewed."
        ),
        segments=tuple(segments),
        thinking=False,
        max_visible_tokens=2048,
        planned_input_tokens=1,
    )


def _target_summary_request(
    segments: Sequence[ProcessorSegment],
    counter: TokenCounter,
) -> ProcessorRequest:
    """Fit mandatory beginning/middle/end samples without silently dropping anchors."""

    if not segments:
        raise ValueError("target suggestion requires source segments")
    if len(segments) == 1:
        anchors = [(0, "start")]
    elif len(segments) == 2:
        anchors = [(0, "start"), (1, "end")]
    else:
        anchors = [
            (0, "start"),
            (len(segments) // 2, "middle"),
            (len(segments) - 1, "end"),
        ]

    full_anchors = tuple(segments[index] for index, _ in anchors)
    try:
        return _planned_request(
            _target_summary_draft(full_anchors),
            counter,
            hard_limit=16_384,
        )
    except BudgetExhausted:
        pass

    maximum_bytes = _TARGET_SAMPLE_INITIAL_BYTES
    while maximum_bytes >= _TARGET_SAMPLE_MINIMUM_BYTES:
        selected = tuple(
            _utf8_sample(
                segments[index],
                maximum_bytes=maximum_bytes,
                position=position,
            )
            for index, position in anchors
        )
        try:
            return _planned_request(
                _target_summary_draft(selected),
                counter,
                hard_limit=16_384,
            )
        except BudgetExhausted:
            maximum_bytes //= 2
    raise BudgetExhausted(
        "representative beginning/middle/end samples do not fit the "
        "target-suggestion input hard limit"
    )


def suggest_target(
    request: TargetSuggestRequest,
    *,
    experiment_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    processor: ProcessorPort,
    remote_authorization: RemoteProcessingAuthorization | None = None,
    token_counter: TokenCounter | None = None,
    budget_limits: ProcessingBudgetLimits | None = None,
    durability: DurabilityBackend | None = None,
    now: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> TargetSuggestOperationResult:
    """Persist a bounded synopsis and suggestion without deciding or creating a target."""

    published = False
    try:
        if not isinstance(request, TargetSuggestRequest) or not isinstance(
            path_policy, PathPolicy
        ):
            raise TypeError("invalid target suggestion dependencies")
        if not callable(getattr(processor, "process", None)) or not isinstance(
            processor.profile, ProcessorProfile
        ):
            raise TypeError("processor does not implement ProcessorPort")
        selected_durability = durability or DurabilityBackend()
        selected_counter = token_counter or Utf8ByteUpperBoundTokenCounter()
        token_counter_profile = _token_counter_profile(selected_counter)
        selected_limits = budget_limits or ProcessingBudgetLimits()
        if not isinstance(selected_limits, ProcessingBudgetLimits):
            raise TypeError("budget_limits must be ProcessingBudgetLimits")
        selected_now = now or (lambda: datetime.now(timezone.utc))
        layout = _layout(experiment_root)
        _prepare_layout(layout)
        source = inspect_source(
            SourceInspectRequest(request_id=request.source_request_id),
            experiment_root=layout.root,
        )
        if not isinstance(source, SourceInspectResult):
            return _failure(source.error.code, stage="source-inspect")
        if source.run.target_decision is not None:
            return _failure(CurationErrorCode.TARGET_CONFLICT, stage="target-already-decided")
        remote_authorization_mapping = _validate_remote_authorization(
            remote_authorization,
            source_request_id=request.source_request_id,
            run=source.run,
            processor=processor,
        )
        _require_counter_processor_match(token_counter_profile, processor)
        body = _read_source_bytes(
            source,
            config_path=layout.config_path,
            path_policy=path_policy,
        )
        segments = _processor_segments(body, source.evidence)
        unit_request = _target_summary_request(segments, selected_counter)
        transaction = layout.transactions_root / f"target-suggestion-{request.request_id}"
        lock = layout.locks_root / f"target-suggestion-{request.request_id}.lock"
        with exclusive_file_lock(lock):
            _ensure_directory(transaction)
            request_body = _canonical_json(
                {
                    "schema": "knowledgeflow.target-suggestion-request",
                    "schema_version": 1,
                    "request_id": request.request_id,
                    "source_request_id": request.source_request_id,
                    "suggested_by": request.suggested_by,
                    "processor_profile": processor.profile.as_mapping(),
                    "provider_profile": processor.provider_profile,
                    "key_reference": processor.key_reference,
                    "remote_authorization": remote_authorization_mapping,
                    "token_counter_profile": token_counter_profile,
                    "budget_limits": {
                        name: getattr(selected_limits, name)
                        for name in selected_limits.__slots__
                    },
                    "unit_request_sha256": _request_digest(unit_request),
                }
            )
            _write_new_or_same(
                transaction / "request.json",
                request_body,
                selected_durability,
            )
            identity = _load_or_create_suggestion_identity(
                transaction,
                now=selected_now,
                durability=selected_durability,
            )
            ledger = ProcessingBudgetLedger(selected_limits)
            executed = _execute_unit(
                transaction,
                processor,
                unit_request,
                ledger,
                selected_durability,
                sleeper,
            )
            response = executed.response
            assert response.synopsis is not None
            assert response.target_choice is not None
            assert response.target_rationale is not None
            locator_ids = tuple(item.locator_id for item in unit_request.segments)
            selected_bytes = sum(
                len(item.body.encode("utf-8")) for item in unit_request.segments
            )
            total_bytes = sum(len(item.body.encode("utf-8")) for item in segments)
            coverage_is_complete = (
                len(unit_request.segments) == len(segments)
                and selected_bytes == total_bytes
            )
            selected_samples = [
                {
                    "segment_reference": item.reference,
                    "locator_id": item.locator_id,
                    "range": (
                        None
                        if item.byte_range is None
                        else item.byte_range.as_mapping()
                    ),
                    "body_sha256": hash_bytes(item.body.encode("utf-8")).sha256,
                }
                for item in unit_request.segments
            ]
            result_body = _canonical_json(
                {
                    "schema": "knowledgeflow.target-suggestion",
                    "schema_version": 2,
                    "transaction_id": identity["transaction_id"],
                    "request_id": request.request_id,
                    "source_request_id": request.source_request_id,
                    "curation_run_id": source.run.curation_run_id,
                    "synopsis": response.synopsis,
                    "suggestion_choice": response.target_choice,
                    "suggestion_rationale": response.target_rationale,
                    "suggested_by": request.suggested_by,
                    "suggested_at": identity["suggested_at"],
                    "selected_segment_references": [
                        item.reference for item in unit_request.segments
                    ],
                    "selected_locator_ids": list(locator_ids),
                    "selected_samples": selected_samples,
                    "selected_segment_count": len(unit_request.segments),
                    "total_segment_count": len(segments),
                    "selected_byte_size": selected_bytes,
                    "coverage_is_complete": coverage_is_complete,
                    "processor_profile": processor.profile.as_mapping(),
                    "provider_profile": processor.provider_profile,
                    "key_reference": processor.key_reference,
                    "remote_authorization": remote_authorization_mapping,
                    "prompt_profile": CUR1D_PROCESSOR_PROFILE,
                    "prompt_profile_revision": CUR1D_PROCESSOR_PROFILE_REVISION,
                    "token_counter_profile": token_counter_profile,
                    "budget_limits": {
                        name: getattr(selected_limits, name)
                        for name in selected_limits.__slots__
                    },
                    "thinking": unit_request.thinking,
                    "reasoning_effort": unit_request.reasoning_effort,
                    "max_visible_tokens": unit_request.max_visible_tokens,
                    "max_reasoning_tokens": unit_request.max_reasoning_tokens,
                    "planned_input_tokens": unit_request.planned_input_tokens,
                    "attempts": [item.as_mapping() for item in executed.attempts],
                    "usage": _response_mapping(response)["usage"],
                    "budget": ledger.as_mapping(),
                    "requires_human_confirmation": True,
                    "target_decision_recorded": False,
                    "kb_created": False,
                    "raw_routed": False,
                }
            )
            destination = layout.suggestions_root / request.request_id
            replayed = destination.exists()
            if not replayed:
                staging = Path(
                    tempfile.mkdtemp(prefix="target-suggestion-", dir=layout.staging_root)
                )
                try:
                    selected_durability.write_new_file_durable(
                        staging / "suggestion.json",
                        result_body,
                    )
                    selected_durability.commit_directory_no_replace(
                        staging,
                        destination,
                    )
                finally:
                    if staging.exists():
                        _plain_directory(staging)
                        if staging.parent.resolve(strict=True) != layout.staging_root.resolve(
                            strict=True
                        ):
                            raise ValueError("target-suggestion staging escaped its root")
                        shutil.rmtree(staging)
            result_path = destination / "suggestion.json"
            if _read_bounded(result_path) != result_body:
                raise ValueError("published target suggestion differs from the transaction")
            published = True
            return TargetSuggestResult(
                request_id=request.request_id,
                source_request_id=request.source_request_id,
                synopsis=response.synopsis,
                suggestion_choice=response.target_choice,
                suggestion_rationale=response.target_rationale,
                suggested_by=request.suggested_by,
                suggested_at=cast(str, identity["suggested_at"]),
                selected_locator_ids=locator_ids,
                selected_segment_count=len(unit_request.segments),
                total_segment_count=len(segments),
                selected_byte_size=selected_bytes,
                coverage_is_complete=coverage_is_complete,
                result_path=result_path.resolve(strict=True),
                replayed=replayed,
            )
    except BudgetExhausted:
        return _failure(CurationErrorCode.BUDGET_EXHAUSTED, stage="target-suggestion-budget")
    except _RemoteAuthorizationError as exc:
        return _failure(exc.code, stage="remote-authorization")
    except ProcessorCallError as exc:
        return _failure(
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
            stage="target-suggestion-processor",
            retryable=exc.retryable and not exc.unknown_usage,
        )
    except _MapIdempotencyConflict:
        return _failure(
            CurationErrorCode.IDEMPOTENCY_CONFLICT,
            stage="target-suggestion-idempotency",
        )
    except (DestinationAlreadyExistsError, DurabilityError, LockUnavailable, OSError):
        return _failure(
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
            stage="target-suggestion-publish",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
            retryable=True,
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return _failure(
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
            stage="target-suggestion-validate",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
        )


def _prior_target_suggestion_budget(
    *,
    layout: _Layout,
    request: MapBuildRequest,
    target: TargetDecideResult,
    processor: ProcessorPort,
    token_counter_profile: Mapping[str, object],
    remote_authorization: Mapping[str, object] | None,
    limits: ProcessingBudgetLimits,
) -> tuple[dict[str, int], int, Mapping[str, object] | None]:
    empty = {name: 0 for name in _BUDGET_COUNTER_FIELDS}
    suggestion = target.record.suggestion
    suggestion_request_id = request.target_suggestion_request_id
    if suggestion_request_id is None:
        if processor.provider_profile is not None and suggestion is not None:
            raise _RemoteAuthorizationError(
                CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
            )
        return empty, 0, None
    if suggestion is None:
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    try:
        path = layout.suggestions_root / suggestion_request_id / "suggestion.json"
        value, _body = _read_canonical_mapping(path)
        transaction = (
            layout.transactions_root / f"target-suggestion-{suggestion_request_id}"
        )
        request_record, _request_body = _read_canonical_mapping(
            transaction / "request.json"
        )
        identity, _identity_body = _read_canonical_mapping(
            transaction / "identity.json"
        )
        unit, _unit_body = _read_canonical_mapping(
            transaction / "unit-target-summary-001.json"
        )
    except (OSError, ValueError) as exc:
        raise _RemoteAuthorizationError(
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
        ) from exc
    expected_limits = {name: getattr(limits, name) for name in limits.__slots__}
    suggestion_schema_version = value.get("schema_version")
    if (
        value.get("schema") != "knowledgeflow.target-suggestion"
        or suggestion_schema_version not in (1, 2)
        or value.get("request_id") != suggestion_request_id
        or value.get("source_request_id") != request.source_request_id
        or value.get("curation_run_id") != target.updated_run.curation_run_id
        or value.get("suggestion_choice") != suggestion.choice
        or value.get("suggestion_rationale") != suggestion.rationale
        or value.get("suggested_by") != suggestion.suggested_by
        or value.get("processor_profile") != processor.profile.as_mapping()
        or value.get("provider_profile") != processor.provider_profile
        or value.get("key_reference") != processor.key_reference
        or value.get("remote_authorization") != remote_authorization
        or value.get("token_counter_profile") != token_counter_profile
        or value.get("budget_limits") != expected_limits
    ):
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    raw_budget = value.get("budget")
    usage = value.get("usage")
    attempts = value.get("attempts")
    unit_response = unit.get("response")
    unit_metadata = unit.get("request_metadata")
    if (
        not isinstance(raw_budget, Mapping)
        or set(raw_budget) != set(_BUDGET_COUNTER_FIELDS)
        or any(type(raw_budget.get(name)) is not int or raw_budget[name] < 0 for name in _BUDGET_COUNTER_FIELDS)
        or raw_budget["first_work_units"] != 1
        or not 1 <= raw_budget["http_attempts"] <= 3
        or not isinstance(usage, Mapping)
        or not isinstance(attempts, list)
        or not isinstance(unit_response, Mapping)
        or not isinstance(unit_metadata, Mapping)
    ):
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    if suggestion_schema_version == 2:
        references = value.get("selected_segment_references")
        locator_ids = value.get("selected_locator_ids")
        ranges = unit_metadata.get("segment_ranges")
        body_hashes = unit_metadata.get("segment_body_sha256")
        if not all(
            isinstance(item, list)
            for item in (references, locator_ids, ranges, body_hashes)
        ):
            raise _RemoteAuthorizationError(
                CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
            )
        assert isinstance(references, list)
        assert isinstance(locator_ids, list)
        assert isinstance(ranges, list)
        assert isinstance(body_hashes, list)
        if not (
            len(references)
            == len(locator_ids)
            == len(ranges)
            == len(body_hashes)
            > 0
        ):
            raise _RemoteAuthorizationError(
                CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
            )
        expected_samples = [
            {
                "segment_reference": reference,
                "locator_id": locator_id,
                "range": byte_range,
                "body_sha256": body_sha256,
            }
            for reference, locator_id, byte_range, body_sha256 in zip(
                references,
                locator_ids,
                ranges,
                body_hashes,
                strict=True,
            )
        ]
        if value.get("selected_samples") != expected_samples:
            raise _RemoteAuthorizationError(
                CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH
            )
    request_fields = {
        "schema",
        "schema_version",
        "request_id",
        "source_request_id",
        "suggested_by",
        "processor_profile",
        "provider_profile",
        "key_reference",
        "remote_authorization",
        "token_counter_profile",
        "budget_limits",
        "unit_request_sha256",
    }
    identity_fields = {
        "schema",
        "schema_version",
        "transaction_id",
        "suggested_at",
    }
    unit_fields = {
        "schema",
        "schema_version",
        "unit_id",
        "stage",
        "request_sha256",
        "request_metadata",
        "attempts",
        "response",
        "budget_after",
    }
    if (
        set(request_record) != request_fields
        or request_record.get("schema")
        != "knowledgeflow.target-suggestion-request"
        or request_record.get("schema_version") != 1
        or request_record.get("request_id") != suggestion_request_id
        or request_record.get("source_request_id") != request.source_request_id
        or request_record.get("suggested_by") != suggestion.suggested_by
        or request_record.get("processor_profile") != processor.profile.as_mapping()
        or request_record.get("provider_profile") != processor.provider_profile
        or request_record.get("key_reference") != processor.key_reference
        or request_record.get("remote_authorization") != remote_authorization
        or request_record.get("token_counter_profile") != token_counter_profile
        or request_record.get("budget_limits") != expected_limits
        or set(identity) != identity_fields
        or identity.get("schema")
        != "knowledgeflow.target-suggestion-transaction-identity"
        or identity.get("schema_version") != 1
        or identity.get("transaction_id") != value.get("transaction_id")
        or identity.get("suggested_at") != value.get("suggested_at")
        or set(unit) != unit_fields
        or unit.get("schema") != "knowledgeflow.curation-processor-unit"
        or unit.get("schema_version") != 1
        or unit.get("unit_id") != "target-summary-001"
        or unit.get("stage") != ProcessingStage.TARGET_SUMMARY.value
        or unit.get("request_sha256")
        != request_record.get("unit_request_sha256")
        or unit.get("attempts") != attempts
        or unit.get("budget_after") != raw_budget
        or unit_response.get("usage") != usage
        or unit_response.get("synopsis") != value.get("synopsis")
        or unit_response.get("target_choice") != value.get("suggestion_choice")
        or unit_response.get("target_rationale")
        != value.get("suggestion_rationale")
        or unit_metadata.get("segment_references")
        != value.get("selected_segment_references")
        or unit_metadata.get("thinking") != value.get("thinking")
        or unit_metadata.get("reasoning_effort") != value.get("reasoning_effort")
        or unit_metadata.get("max_visible_tokens")
        != value.get("max_visible_tokens")
        or unit_metadata.get("max_reasoning_tokens")
        != value.get("max_reasoning_tokens")
        or unit_metadata.get("planned_input_tokens")
        != value.get("planned_input_tokens")
    ):
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    usage_fields = (
        "input_tokens",
        "visible_output_tokens",
        "reasoning_tokens",
        "elapsed_ms",
    )
    if any(type(usage.get(name)) is not int or usage[name] < 0 for name in usage_fields):
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    if (
        raw_budget["input_tokens"] < usage["input_tokens"]
        or raw_budget["visible_output_tokens"] < usage["visible_output_tokens"]
        or raw_budget["reasoning_tokens"] < usage["reasoning_tokens"]
    ):
        raise _RemoteAuthorizationError(CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH)
    budget = {name: cast(int, raw_budget[name]) for name in _BUDGET_COUNTER_FIELDS}
    ledger = ProcessingBudgetLedger(limits, **budget)
    ledger._require_within_limits()
    return (
        budget,
        cast(int, usage["elapsed_ms"]),
        {
            "request_id": suggestion_request_id,
            "budget": dict(budget),
            "usage": dict(usage),
        },
    )


def _valid_versioned_prior_target_suggestion(
    value: object,
    request_id: str | None,
) -> bool:
    if request_id is None:
        return value is None
    if not isinstance(value, Mapping) or set(value) != {
        "request_id",
        "budget",
        "usage",
    }:
        return False
    budget = value.get("budget")
    usage = value.get("usage")
    usage_fields = {
        "input_tokens",
        "visible_output_tokens",
        "reasoning_tokens",
        "elapsed_ms",
        "response_model",
        "system_fingerprint",
        "finish_reason",
    }
    if (
        value.get("request_id") != request_id
        or not isinstance(budget, Mapping)
        or set(budget) != set(_BUDGET_COUNTER_FIELDS)
        or any(
            type(budget.get(name)) is not int or budget[name] < 0
            for name in _BUDGET_COUNTER_FIELDS
        )
        or budget["first_work_units"] != 1
        or not 1 <= budget["http_attempts"] <= 3
        or not isinstance(usage, Mapping)
        or set(usage) != usage_fields
        or any(
            type(usage.get(name)) is not int or usage[name] < 0
            for name in (
                "input_tokens",
                "visible_output_tokens",
                "reasoning_tokens",
                "elapsed_ms",
            )
        )
        or (
            usage.get("response_model") is not None
            and type(usage.get("response_model")) is not str
        )
        or (
            usage.get("system_fingerprint") is not None
            and type(usage.get("system_fingerprint")) is not str
        )
        or usage.get("finish_reason") != "stop"
        or budget["input_tokens"] < usage["input_tokens"]
        or budget["visible_output_tokens"] < usage["visible_output_tokens"]
        or budget["reasoning_tokens"] < usage["reasoning_tokens"]
    ):
        return False
    return True


def _build_request_mapping(
    request: MapBuildRequest,
    processor: ProcessorPort,
    counter: TokenCounter,
    limits: ProcessingBudgetLimits,
    remote_authorization: Mapping[str, object] | None,
    prior_budget: Mapping[str, int],
    *,
    short_reading: bool = False,
) -> dict[str, object]:
    result = {
        "schema": "knowledgeflow.map-build-request",
        "schema_version": 1,
        "request_id": request.request_id,
        "source_request_id": request.source_request_id,
        "target_decision_request_id": request.target_decision_request_id,
        "target_parent_present": request.kb_parent is not None,
        "target_suggestion_request_id": request.target_suggestion_request_id,
        "processor_profile": processor.profile.as_mapping(),
        "provider_profile": processor.provider_profile,
        "key_reference": processor.key_reference,
        "remote_authorization": remote_authorization,
        "token_counter_profile": _token_counter_profile(counter),
        "processing_window_profile": (
            _short_processing_window_profile()
            if short_reading
            else _processing_window_profile()
        ),
        "budget_limits": {
            name: getattr(limits, name) for name in limits.__slots__
        },
        "prior_budget": dict(prior_budget),
    }
    if short_reading:
        result["reading_profile"] = _SHORT_READING_PROFILE
    return result


def _load_or_create_identity(
    transaction: Path,
    *,
    now: Callable[[], datetime],
    durability: DurabilityBackend,
) -> Mapping[str, object]:
    path = transaction / "identity.json"
    if path.exists():
        value = json.loads(_read_bounded(path).decode("utf-8"))
        if not isinstance(value, Mapping) or set(value) != {
            "schema",
            "schema_version",
            "transaction_id",
            "map_id",
            "created_at",
        }:
            raise ValueError("map transaction identity is invalid")
        return value
    instant = now()
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError("now must return an aware datetime")
    value = {
        "schema": "knowledgeflow.map-transaction-identity",
        "schema_version": 1,
        "transaction_id": generate_curation_id("txn_"),
        "map_id": generate_curation_id("map_"),
        "created_at": format_utc_milliseconds(instant.astimezone(timezone.utc)),
    }
    _write_new_or_same(path, _canonical_json(value), durability)
    return value


def _load_or_create_suggestion_identity(
    transaction: Path,
    *,
    now: Callable[[], datetime],
    durability: DurabilityBackend,
) -> Mapping[str, object]:
    path = transaction / "identity.json"
    if path.exists():
        value = json.loads(_read_bounded(path).decode("utf-8"))
        if not isinstance(value, Mapping) or set(value) != {
            "schema",
            "schema_version",
            "transaction_id",
            "suggested_at",
        }:
            raise ValueError("target-suggestion transaction identity is invalid")
        return value
    instant = now()
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError("now must return an aware datetime")
    value = {
        "schema": "knowledgeflow.target-suggestion-transaction-identity",
        "schema_version": 1,
        "transaction_id": generate_curation_id("txn_"),
        "suggested_at": format_utc_milliseconds(instant.astimezone(timezone.utc)),
    }
    _write_new_or_same(path, _canonical_json(value), durability)
    return value


def _candidate_ids(
    transaction: Path,
    count: int,
    durability: DurabilityBackend,
) -> tuple[str, ...]:
    path = transaction / "candidate-ids.json"
    if path.exists():
        value = json.loads(_read_bounded(path).decode("utf-8"))
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != "knowledgeflow.map-candidate-identities"
            or value.get("schema_version") != 1
            or not isinstance(value.get("candidate_ids"), list)
        ):
            raise ValueError("candidate identity record is invalid")
        result = tuple(value["candidate_ids"])
        if len(result) != count:
            raise ValueError("candidate identity count changed during replay")
        return result
    result = tuple(generate_curation_id("cand_") for _ in range(count))
    _write_new_or_same(
        path,
        _canonical_json(
            {
                "schema": "knowledgeflow.map-candidate-identities",
                "schema_version": 1,
                "candidate_ids": list(result),
            }
        ),
        durability,
    )
    return result


def _assembled_drafts(
    section_units: Sequence[ExecutedUnit],
    global_unit: ExecutedUnit,
    focus_units: Sequence[ExecutedUnit],
) -> tuple[ProcessorCandidateDraft, ...]:
    drafts = [*global_unit.response.candidates]
    for unit in section_units:
        drafts.extend(unit.response.candidates)
    for unit in focus_units:
        drafts.extend(unit.response.candidates)
    anchors = [item.markdown_anchor for item in drafts]
    if not drafts or len(set(anchors)) != len(anchors):
        raise ValueError("assembled map candidates are empty or have duplicate anchors")
    return tuple(drafts)


def _curation_map(
    *,
    identity: Mapping[str, object],
    run: CurationRunManifest,
    evidence: CurationEvidenceRecord,
    target_binding: TargetBinding | None,
    processor: ProcessorPort,
    ledger: ProcessingBudgetLedger,
    executed_units: Sequence[ExecutedUnit],
    drafts: Sequence[ProcessorCandidateDraft],
    transaction: Path,
    durability: DurabilityBackend,
    segments: Sequence[ProcessorSegment],
    prior_elapsed_ms: int,
    reading_profile: str | None = None,
    review_locators: Sequence[EvidenceLocator] = (),
) -> CurationMap:
    locator_by_reference = {item.reference: item.locator_id for item in segments}
    identifiers = _candidate_ids(transaction, len(drafts), durability)
    candidates = tuple(
        MapCandidate(
            candidate_id=candidate_id,
            kind=draft.kind,
            summary=draft.summary,
            evidence_locator_ids=tuple(
                locator_by_reference[reference] for reference in draft.evidence_refs
            ),
            provenance=draft.provenance,
            uncertainty=draft.uncertainty,
            markdown_anchor=draft.markdown_anchor,
        )
        for candidate_id, draft in zip(identifiers, drafts, strict=True)
    )
    elapsed = prior_elapsed_ms + sum(
        item.response.usage.elapsed_ms for item in executed_units
    )
    usage = ProcessorUsage(
        call_count=ledger.http_attempts,
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.visible_output_tokens,
        elapsed_ms=elapsed,
        cost_currency=("USD" if processor.provider_profile is not None else None),
        cost_minor_units=(
            (ledger.cost_microusd + 9_999) // 10_000
            if processor.provider_profile is not None
            else None
        ),
    )
    result = CurationMap(
        map_id=cast(str, identity["map_id"]),
        map_version=1,
        curation_run_id=run.curation_run_id,
        created_at=cast(str, identity["created_at"]),
        source=run.source,
        declared_scope=run.declared_scope,
        scope=evidence.scope,
        processor_profile=processor.profile,
        processor_usage=usage,
        target_binding=target_binding,
        candidates=candidates,
        reading_profile=reading_profile,
        review_locators=tuple(review_locators),
    )
    result.validate_against(evidence)
    result.validate_against_run(
        replace(run, processor_profile=processor.profile, state="map-ready")
    )
    return result


def _run_record(
    *,
    identity: Mapping[str, object],
    request: MapBuildRequest,
    curation_map: CurationMap,
    map_sha256: str,
    processor: ProcessorPort,
    counter: TokenCounter,
    remote_authorization: Mapping[str, object] | None,
    publish_base_commit: str | None,
    ledger: ProcessingBudgetLedger,
    units: Sequence[ExecutedUnit],
    prior_target_suggestion: Mapping[str, object] | None,
    short_reading: bool = False,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.curation-map-run",
            "schema_version": 1,
            "transaction_id": identity["transaction_id"],
            "request_id": request.request_id,
            "source_request_id": request.source_request_id,
            "target_decision_request_id": request.target_decision_request_id,
            "curation_run_id": curation_map.curation_run_id,
            "map_id": curation_map.map_id,
            "map_version": curation_map.map_version,
            "map_sha256": map_sha256,
            "state": "map-ready",
            "publish_base_commit": publish_base_commit,
            "processor_profile": processor.profile.as_mapping(),
            "provider_profile": processor.provider_profile,
            "key_reference": processor.key_reference,
            "remote_authorization": remote_authorization,
            "prompt_profile": (
                SHORT_READING_PROCESSOR_PROFILE
                if short_reading
                else CUR1D_PROCESSOR_PROFILE
            ),
            "prompt_profile_revision": (
                SHORT_READING_PROCESSOR_PROFILE_REVISION
                if short_reading
                else CUR1D_PROCESSOR_PROFILE_REVISION
            ),
            "token_counter_profile": _token_counter_profile(counter),
            "processing_window_profile": (
                _short_processing_window_profile()
                if short_reading
                else _processing_window_profile()
            ),
            "budget_limits": {
                name: getattr(ledger.limits, name) for name in ledger.limits.__slots__
            },
            "sent_field_categories": (
                []
                if processor.provider_profile is None
                else [
                    (
                        "authorized-line-range-text"
                        if short_reading
                        else "authorized-segment-text"
                    ),
                    "opaque-segment-reference",
                    "heading-context",
                    "validated-prior-candidate",
                    "task-and-output-contract",
                ]
            ),
            "budget": ledger.as_mapping(),
            "prior_target_suggestion": prior_target_suggestion,
            "work_units": [
                {
                    "unit_id": item.request.unit_id,
                    "stage": item.request.stage.value,
                    "request_sha256": _request_digest(item.request),
                    "segment_references": [
                        segment.reference for segment in item.request.segments
                    ],
                    "heading_paths": [
                        list(segment.heading_path)
                        for segment in item.request.segments
                    ],
                    "heading_tree_root": (
                        _heading_tree_root(item.request.segments[0])
                        if item.request.stage is ProcessingStage.L1_WINDOW
                        and item.request.segments
                        else None
                    ),
                    "prior_candidate_references": [
                        candidate.reference
                        for candidate in item.request.prior_candidates
                    ],
                    "thinking": item.request.thinking,
                    "reasoning_effort": item.request.reasoning_effort,
                    "max_visible_tokens": item.request.max_visible_tokens,
                    "max_reasoning_tokens": item.request.max_reasoning_tokens,
                    "planned_input_tokens": item.request.planned_input_tokens,
                    "attempts": [attempt.as_mapping() for attempt in item.attempts],
                    "usage": _response_mapping(item.response)["usage"],
                }
                for item in units
            ],
            "stop_reason": "completed",
            "wiki_written": False,
        }
    )


def _map_relative_paths(curation_map: CurationMap) -> tuple[str, str, str]:
    prefix = (
        f"proposals/curation-maps/{curation_map.map_id}/"
        f"v{curation_map.map_version:04d}"
    )
    return f"{prefix}/map.yaml", f"{prefix}/map.md", f"{prefix}/run.json"


def _file_manifest(files: Mapping[str, bytes]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": hash_bytes(files[path]).sha256}
        for path in sorted(files)
    ]


def _publish_manifest(
    *,
    kind: str,
    request_id: str,
    transaction_id: str,
    base_commit: str | None,
    files: Mapping[str, bytes],
) -> bytes:
    if kind not in {"map", "decision"}:
        raise ValueError("publish transaction kind is invalid")
    return _canonical_json(
        {
            "schema": "knowledgeflow.curation-publish-transaction",
            "schema_version": 1,
            "kind": kind,
            "request_id": request_id,
            "transaction_id": transaction_id,
            "base_commit": base_commit,
            "files": _file_manifest(files),
        }
    )


def _assert_no_unresolved_publish_transaction(
    transactions_root: Path,
    *,
    current_name: str,
) -> None:
    _plain_directory(transactions_root)
    for child in transactions_root.iterdir():
        if child.name == current_name or not child.is_dir():
            continue
        if _has_unresolved_publish_transaction(child):
            raise _RecoveryRequired("another curation publish transaction is unresolved")


def _has_unresolved_publish_transaction(transaction: Path) -> bool:
    if not os.path.lexists(transaction):
        return False
    _plain_directory(transaction)
    publish = transaction / "publish.json"
    complete = transaction / "complete.json"
    publish_exists = os.path.lexists(publish)
    complete_exists = os.path.lexists(complete)
    if publish_exists:
        _plain_file(publish)
    if complete_exists:
        _plain_file(complete)
    if complete_exists and not publish_exists:
        raise _RecoveryRequired("curation completion has no publish manifest")
    return publish_exists and not complete_exists


def _prepare_publish_transaction(
    transaction: Path,
    *,
    kind: str,
    request_id: str,
    transaction_id: str,
    base_commit: str | None,
    files: Mapping[str, bytes],
    durability: DurabilityBackend,
    tree_staging: bool = False,
) -> Path:
    _ensure_directory(transaction)
    _write_new_or_same(
        transaction / "publish.json",
        _publish_manifest(
            kind=kind,
            request_id=request_id,
            transaction_id=transaction_id,
            base_commit=base_commit,
            files=files,
        ),
        durability,
    )
    staging = transaction / "staging"
    _ensure_directory(staging)
    if tree_staging:
        _ensure_parents(staging, tuple(files))
    for index, relative in enumerate(sorted(files)):
        body = files[relative]
        staged = (
            staging.joinpath(*PurePosixPath(relative).parts)
            if tree_staging
            else staging / f"{index:04d}.artifact"
        )
        _write_new_or_same(staged, body, durability)
        if _read_bounded(staged) != body:
            raise _RecoveryRequired("staged curation artifact failed readback")
    return staging


def _final_file_states(
    root: Path,
    files: Mapping[str, bytes],
) -> tuple[bool, bool]:
    present = 0
    for relative, body in files.items():
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not os.path.lexists(path):
            continue
        present += 1
        _plain_file(path)
        if _read_bounded(path) != body:
            raise _MapIdempotencyConflict("published path contains different bytes")
    return present == 0, present == len(files)


def _publish_staged_files(
    root: Path,
    staging: Path,
    files: Mapping[str, bytes],
    durability: DurabilityBackend,
    *,
    tree_staging: bool = False,
) -> None:
    _ensure_parents(root, tuple(files))
    for index, relative in enumerate(sorted(files)):
        body = files[relative]
        staged = (
            staging.joinpath(*PurePosixPath(relative).parts)
            if tree_staging
            else staging / f"{index:04d}.artifact"
        )
        if _read_bounded(staged) != body:
            raise _RecoveryRequired("staged curation artifact changed")
        _write_new_or_same(
            root.joinpath(*PurePosixPath(relative).parts),
            body,
            durability,
        )


def _complete_publish_transaction(
    transaction: Path,
    *,
    receipt_path: Path,
    receipt_body: bytes,
    result_commit: str | None,
    durability: DurabilityBackend,
) -> bool:
    replayed = receipt_path.exists()
    _write_new_or_same(receipt_path, receipt_body, durability)
    if _read_bounded(receipt_path) != receipt_body:
        raise _RecoveryRequired("curation receipt failed readback")
    _write_new_or_same(
        transaction / "complete.json",
        _canonical_json(
            {
                "schema": "knowledgeflow.curation-publish-completion",
                "schema_version": 1,
                "receipt_sha256": hash_bytes(receipt_body).sha256,
                "result_commit": result_commit,
            }
        ),
        durability,
    )
    return replayed


def _target_checkpoint(
    *,
    repository: Path,
    transaction: Path,
    files: Mapping[str, bytes],
    base_commit: str,
    checkpoint_time: str,
    message: str,
    git: ManagedGit,
    durability: DurabilityBackend,
) -> tuple[str, bool]:
    staging = transaction / "staging"
    started = transaction / "publish-started.json"
    candidate_path = transaction / "candidate-commit.txt"
    candidate = _load_candidate(candidate_path)
    candidate_was_present = candidate is not None
    try:
        none_present, all_present = _final_file_states(repository, files)
    except _MapIdempotencyConflict as exc:
        raise ManagedGitConflict("managed publish path overlaps unknown bytes") from exc
    reconstructed = False

    if candidate is None and all_present and not started.exists():
        checkpoint = git.find_unique_checkpoint(
            repository,
            files,
            base_commit=base_commit,
        )
        candidate = checkpoint.commit
        _persist_candidate(candidate_path, candidate, durability)
        reconstructed = True

    if candidate is None:
        if not started.exists():
            if not none_present or git.paths_have_changes(repository, tuple(files)):
                raise ManagedGitConflict("managed publish paths already contain changes")
            _write_new_or_same(
                started,
                _canonical_json(
                    {
                        "schema": "knowledgeflow.curation-publish-start",
                        "schema_version": 1,
                        "files": _file_manifest(files),
                    }
                ),
                durability,
            )
        _publish_staged_files(repository, staging, files, durability)
        current = git.current_commit(repository)
        if current != base_commit:
            raise ManagedGitConflict("managed ref changed before curation checkpoint")
        checkpoint = git.checkpoint(
            repository,
            files,
            base_commit=base_commit,
            checkpoint_time=checkpoint_time,
            message=message,
            index_path=transaction / "index",
            persist_candidate=lambda value: _persist_candidate(
                candidate_path,
                value,
                durability,
            ),
        )
        candidate = checkpoint.commit
    else:
        current = git.current_commit(repository)
        if current == base_commit:
            git.recover_checkpoint(
                repository,
                files,
                base_commit=base_commit,
                candidate_commit=candidate,
            )
        else:
            git.verify_reachable_checkpoint(
                repository,
                files,
                base_commit=base_commit,
                candidate_commit=candidate,
            )
    return candidate, reconstructed or candidate_was_present


def _receipt_body(
    *,
    request_id: str,
    transaction_id: str,
    curation_map: CurationMap,
    map_sha256: str,
    yaml_sha256: str,
    markdown_sha256: str,
    base_commit: str | None,
    files: Mapping[str, bytes],
    result_commit: str | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.map-publish-receipt",
            "schema_version": 1,
            "request_id": request_id,
            "transaction_id": transaction_id,
            "map_id": curation_map.map_id,
            "map_version": curation_map.map_version,
            "map_sha256": map_sha256,
            "map_yaml_sha256": yaml_sha256,
            "map_markdown_sha256": markdown_sha256,
            "base_commit": base_commit,
            "files": _file_manifest(files),
            "result_commit": result_commit,
            "state": "map-ready",
        }
    )


def _persist_candidate(path: Path, commit: str, durability: DurabilityBackend) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ManagedGitIntegrityError("candidate commit is invalid")
    _write_new_or_same(path, (commit + "\n").encode("ascii"), durability)


def _load_candidate(path: Path) -> str | None:
    if not path.exists():
        return None
    value = _read_bounded(path).decode("ascii").removesuffix("\n")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("candidate commit record is invalid")
    return value


def _publish_no_target_map(
    *,
    layout: _Layout,
    request: MapBuildRequest,
    identity: Mapping[str, object],
    curation_map: CurationMap,
    files: Mapping[str, bytes],
    durability: DurabilityBackend,
) -> tuple[Path, Path, Path, None, Path, bool]:
    maps_root = layout.work_root / curation_map.curation_run_id / "curation-maps"
    run_root = maps_root.parent
    _ensure_directory(run_root)
    _ensure_directory(maps_root)
    destination = maps_root / curation_map.map_id
    transaction = layout.transactions_root / request.request_id
    _assert_no_unresolved_publish_transaction(
        layout.transactions_root,
        current_name=transaction.name,
    )
    expected = {
        f"v{curation_map.map_version:04d}/{name}": body
        for name, body in files.items()
    }
    staging = _prepare_publish_transaction(
        transaction,
        kind="map",
        request_id=request.request_id,
        transaction_id=cast(str, identity["transaction_id"]),
        base_commit=None,
        files=expected,
        durability=durability,
    )
    started = transaction / "publish-started.json"
    none_present, all_present = _final_file_states(destination, expected) if destination.exists() else (True, False)
    replayed_publish = all_present
    if not started.exists():
        if not none_present and not all_present:
            raise _RecoveryRequired("no-target map publication is incomplete")
        _write_new_or_same(
            started,
            _canonical_json(
                {
                    "schema": "knowledgeflow.curation-publish-start",
                    "schema_version": 1,
                    "files": _file_manifest(expected),
                }
            ),
            durability,
        )
    if not destination.exists():
        publish_tree = transaction / "publish-tree"
        _ensure_directory(publish_tree)
        try:
            _publish_staged_files(
                publish_tree,
                staging,
                expected,
                durability,
            )
            durability.commit_directory_no_replace(publish_tree, destination)
        finally:
            if publish_tree.exists():
                _plain_directory(publish_tree)
                if publish_tree.parent.resolve(strict=True) != transaction.resolve(
                    strict=True
                ):
                    raise _RecoveryRequired("no-target publish tree escaped transaction")
                shutil.rmtree(publish_tree)
    none_present, all_present = _final_file_states(destination, expected)
    if none_present or not all_present:
        raise _RecoveryRequired("no-target map publication did not close atomically")
    version_root = destination / f"v{curation_map.map_version:04d}"
    return (
        version_root / "map.yaml",
        version_root / "map.md",
        version_root / "run.json",
        None,
        transaction,
        replayed_publish,
    )


def _publish_target_map(
    *,
    request: MapBuildRequest,
    identity: Mapping[str, object],
    target: TargetDecideResult,
    repository: Path,
    curation_map: CurationMap,
    files: Mapping[str, bytes],
    git: ManagedGit,
    durability: DurabilityBackend,
) -> tuple[Path, Path, Path, str, Path, bool]:
    relative_yaml, relative_md, relative_run = _map_relative_paths(curation_map)
    expected = {
        relative_yaml: files["map.yaml"],
        relative_md: files["map.md"],
        relative_run: files["run.json"],
    }
    transactions_root = repository / ".knowledgeflow" / "transactions"
    _plain_directory(transactions_root)
    transaction = transactions_root / f"map-{request.request_id}"
    _assert_no_unresolved_publish_transaction(
        transactions_root,
        current_name=transaction.name,
    )
    base_commit = cast(str, target.result_commit)
    _prepare_publish_transaction(
        transaction,
        kind="map",
        request_id=request.request_id,
        transaction_id=cast(str, identity["transaction_id"]),
        base_commit=base_commit,
        files=expected,
        durability=durability,
    )
    candidate, replayed_publish = _target_checkpoint(
        repository=repository,
        transaction=transaction,
        files=expected,
        base_commit=base_commit,
        checkpoint_time=curation_map.created_at,
        message=(
            f"Publish curation map {curation_map.map_id} v{curation_map.map_version}\n\n"
            f"KnowledgeFlow-Transaction: {identity['transaction_id']}\n"
        ),
        git=git,
        durability=durability,
    )
    return (
        repository.joinpath(*PurePosixPath(relative_yaml).parts),
        repository.joinpath(*PurePosixPath(relative_md).parts),
        repository.joinpath(*PurePosixPath(relative_run).parts),
        candidate,
        transaction,
        replayed_publish,
    )


def _validate_published_map(
    yaml_path: Path,
    markdown_path: Path,
    run_path: Path,
    expected_map: CurationMap,
    expected_run: bytes,
) -> tuple[str, str, str]:
    yaml_body = _read_bounded(yaml_path)
    markdown_body = _read_bounded(markdown_path)
    if load_curation_map(yaml_body) != expected_map:
        raise ValueError("published map YAML failed readback")
    if render_curation_map_markdown(expected_map) != markdown_body:
        raise ValueError("published map Markdown diverges from map facts")
    if _read_bounded(run_path) != expected_run:
        raise ValueError("published map run record failed readback")
    return (
        curation_map_artifact_sha256(yaml_body, markdown_body),
        hash_bytes(yaml_body).sha256,
        hash_bytes(markdown_body).sha256,
    )


def _recover_target_map_checkout(
    *,
    layout: _Layout,
    request: MapBuildRequest,
    target: TargetDecideResult,
    repository: Path,
    processor: ProcessorPort,
    counter: TokenCounter,
    limits: ProcessingBudgetLimits,
    remote_authorization: Mapping[str, object] | None,
    git: ManagedGit,
    durability: DurabilityBackend,
) -> MapBuildResult | None:
    maps_root = repository / "proposals" / "curation-maps"
    if not maps_root.exists():
        return None
    _plain_directory(maps_root)
    matches: list[tuple[Path, Mapping[str, object]]] = []
    for map_root in maps_root.iterdir():
        if not map_root.is_dir() or _MAP_ID.fullmatch(map_root.name) is None:
            continue
        _plain_directory(map_root)
        for version_root in map_root.iterdir():
            if not version_root.is_dir() or re.fullmatch(r"v[0-9]{4}", version_root.name) is None:
                continue
            _plain_directory(version_root)
            run_path = version_root / "run.json"
            if not run_path.exists():
                continue
            value = json.loads(_read_bounded(run_path).decode("utf-8"))
            if isinstance(value, Mapping) and value.get("request_id") == request.request_id:
                matches.append((version_root, value))
    if not matches:
        return None
    if len(matches) != 1:
        raise _RecoveryRequired("map request matches more than one versioned run")
    version_root, run = matches[0]
    curation_map, yaml_body, markdown_body, map_sha256 = _load_map_version(version_root)
    expected_limits = {name: getattr(limits, name) for name in limits.__slots__}
    if (
        run.get("schema") != "knowledgeflow.curation-map-run"
        or run.get("schema_version") != 1
        or run.get("source_request_id") != request.source_request_id
        or run.get("target_decision_request_id") != request.target_decision_request_id
        or run.get("curation_run_id") != target.updated_run.curation_run_id
        or run.get("map_id") != curation_map.map_id
        or run.get("map_version") != curation_map.map_version
        or run.get("map_sha256") != map_sha256
        or run.get("processor_profile") != processor.profile.as_mapping()
        or run.get("provider_profile") != processor.provider_profile
        or run.get("key_reference") != processor.key_reference
        or run.get("remote_authorization") != remote_authorization
        or run.get("token_counter_profile") != _token_counter_profile(counter)
        or run.get("processing_window_profile") != _processing_window_profile()
        or run.get("budget_limits") != expected_limits
        or not _valid_versioned_prior_target_suggestion(
            run.get("prior_target_suggestion"),
            request.target_suggestion_request_id,
        )
        or curation_map.source != target.updated_run.source
        or curation_map.target_binding != target.record.target_binding
    ):
        raise _MapIdempotencyConflict(
            "versioned map request differs from the requested processing facts"
        )
    transaction_id = run.get("transaction_id")
    base_commit = run.get("publish_base_commit")
    if (
        type(transaction_id) is not str
        or _SAFE_TOKEN.fullmatch(transaction_id) is None
        or type(base_commit) is not str
        or not re.fullmatch(r"[0-9a-f]{40}", base_commit)
        or base_commit != target.result_commit
    ):
        raise _RecoveryRequired("versioned map recovery identity is invalid")
    relative_yaml, relative_md, relative_run = _map_relative_paths(curation_map)
    run_body = _read_bounded(version_root / "run.json")
    files = {
        relative_yaml: yaml_body,
        relative_md: markdown_body,
        relative_run: run_body,
    }
    transactions_root = repository / ".knowledgeflow" / "transactions"
    _plain_directory(transactions_root)
    transaction = transactions_root / f"map-{request.request_id}"
    _assert_no_unresolved_publish_transaction(
        transactions_root,
        current_name=transaction.name,
    )
    _prepare_publish_transaction(
        transaction,
        kind="map",
        request_id=request.request_id,
        transaction_id=transaction_id,
        base_commit=base_commit,
        files=files,
        durability=durability,
    )
    result_commit, _ = _target_checkpoint(
        repository=repository,
        transaction=transaction,
        files=files,
        base_commit=base_commit,
        checkpoint_time=curation_map.created_at,
        message=(
            f"Publish curation map {curation_map.map_id} v{curation_map.map_version}\n\n"
            f"KnowledgeFlow-Transaction: {transaction_id}\n"
        ),
        git=git,
        durability=durability,
    )
    observed_map_hash, yaml_hash, markdown_hash = _validate_published_map(
        version_root / "map.yaml",
        version_root / "map.md",
        version_root / "run.json",
        curation_map,
        run_body,
    )
    if observed_map_hash != map_sha256:
        raise _RecoveryRequired("versioned map changed during receipt rebuild")
    receipt = _receipt_body(
        request_id=request.request_id,
        transaction_id=transaction_id,
        curation_map=curation_map,
        map_sha256=map_sha256,
        yaml_sha256=yaml_hash,
        markdown_sha256=markdown_hash,
        base_commit=base_commit,
        files=files,
        result_commit=result_commit,
    )
    receipt_path = (
        repository
        / ".knowledgeflow"
        / "receipts"
        / f"map-{request.request_id}.json"
    )
    _complete_publish_transaction(
        transaction,
        receipt_path=receipt_path,
        receipt_body=receipt,
        result_commit=result_commit,
        durability=durability,
    )
    return MapBuildResult(
        request_id=request.request_id,
        curation_map=curation_map,
        map_sha256=map_sha256,
        yaml_sha256=yaml_hash,
        markdown_sha256=markdown_hash,
        yaml_path=(version_root / "map.yaml").resolve(strict=True),
        markdown_path=(version_root / "map.md").resolve(strict=True),
        run_record_path=(version_root / "run.json").resolve(strict=True),
        target_repository=repository,
        result_commit=result_commit,
        replayed=True,
    )


def build_map(
    request: MapBuildRequest,
    *,
    experiment_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    processor: ProcessorPort,
    remote_authorization: RemoteProcessingAuthorization | None = None,
    token_counter: TokenCounter | None = None,
    budget_limits: ProcessingBudgetLimits | None = None,
    git: ManagedGit | None = None,
    durability: DurabilityBackend | None = None,
    now: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> MapBuildOperationResult:
    """Build and atomically publish one evidence-bound map without writing Wiki."""

    published = False
    selected_durability = durability or DurabilityBackend()
    stop_transaction: Path | None = None
    stop_evidence: CurationEvidenceRecord | None = None
    stop_ledger: ProcessingBudgetLedger | None = None
    try:
        if not isinstance(request, MapBuildRequest) or not isinstance(path_policy, PathPolicy):
            raise TypeError("invalid map build dependencies")
        if not callable(getattr(processor, "process", None)) or not isinstance(
            processor.profile,
            ProcessorProfile,
        ):
            raise TypeError("processor does not implement ProcessorPort")
        if (
            request.reading_profile == _SHORT_READING_PROFILE
            and processor.provider_profile is not None
            and budget_limits is None
        ):
            return _failure(CurationErrorCode.INVALID_INPUT, stage="reading-budget")
        selected_git = git or ManagedGit()
        selected_counter = token_counter or Utf8ByteUpperBoundTokenCounter()
        token_counter_profile = _token_counter_profile(selected_counter)
        selected_limits = budget_limits or ProcessingBudgetLimits()
        selected_now = now or (lambda: datetime.now(timezone.utc))
        layout = _layout(experiment_root)
        _prepare_layout(layout)
        source = inspect_source(
            SourceInspectRequest(request_id=request.source_request_id),
            experiment_root=layout.root,
        )
        if not isinstance(source, SourceInspectResult):
            return _failure(source.error.code, stage="source-inspect")
        stop_evidence = source.evidence
        target = inspect_target_decision(
            request.target_decision_request_id,
            experiment_root=layout.root,
            kb_parent=request.kb_parent,
            git=selected_git,
        )
        if not isinstance(target, TargetDecideResult):
            return _failure(
                target.error.code,
                stage="target-inspect",
                state=target.commit_state or CurationCommitState.NOT_COMMITTED,
                retryable=target.error.retryable,
            )
        if (
            target.record.source_request_id != request.source_request_id
            or target.updated_run.curation_run_id != source.run.curation_run_id
        ):
            return _failure(CurationErrorCode.TARGET_CONFLICT, stage="target-binding")
        remote_authorization_mapping = _validate_remote_authorization(
            remote_authorization,
            source_request_id=request.source_request_id,
            run=source.run,
            processor=processor,
        )
        _require_counter_processor_match(token_counter_profile, processor)
        transaction = layout.transactions_root / request.request_id
        stop_transaction = transaction
        lock = layout.locks_root / f"{request.request_id}.lock"
        if target.record.target_binding is not None:
            if request.kb_parent is None or target.storage_name is None:
                raise ValueError("target-bound map has no repository location")
            recovery_repository = (
                request.kb_parent.resolve(strict=True) / target.storage_name
            )
            with exclusive_file_lock(lock):
                target_transactions = (
                    recovery_repository / ".knowledgeflow" / "transactions"
                )
                target_transaction = target_transactions / f"map-{request.request_id}"
                with exclusive_file_lock(
                    recovery_repository
                    / ".knowledgeflow"
                    / "locks"
                    / "curation-write.lock"
                ):
                    _assert_no_unresolved_publish_transaction(
                        target_transactions,
                        current_name=target_transaction.name,
                    )
                    if not transaction.exists():
                        recovered = _recover_target_map_checkout(
                            layout=layout,
                            request=request,
                            target=target,
                            repository=recovery_repository,
                            processor=processor,
                            counter=selected_counter,
                            limits=selected_limits,
                            remote_authorization=remote_authorization_mapping,
                            git=selected_git,
                            durability=selected_durability,
                        )
                        if recovered is not None:
                            return recovered
                        if _has_unresolved_publish_transaction(target_transaction):
                            raise _RecoveryRequired(
                                "map publish exists without its local processing journal"
                            )
        else:
            with exclusive_file_lock(lock):
                _assert_no_unresolved_publish_transaction(
                    layout.transactions_root,
                    current_name=transaction.name,
                )
        (
            prior_budget,
            prior_elapsed_ms,
            prior_target_suggestion,
        ) = _prior_target_suggestion_budget(
            layout=layout,
            request=request,
            target=target,
            processor=processor,
            token_counter_profile=token_counter_profile,
            remote_authorization=remote_authorization_mapping,
            limits=selected_limits,
        )
        body = _read_source_bytes(
            source,
            config_path=layout.config_path,
            path_policy=path_policy,
        )
        segments = _processor_segments(body, source.evidence)
        short_reading = request.reading_profile == _SHORT_READING_PROFILE
        short_ranges = (
            _short_direct_plan(
                body,
                source.run,
                source.evidence,
                selected_counter,
                no_target=target.record.target_binding is None,
            )
            if short_reading
            else None
        )
        if short_reading and short_ranges is None:
            raise _ReadingProfileUnavailable(
                "short reading requires a complete, bounded no-target source"
            )
        request_body = _canonical_json(
            _build_request_mapping(
                request,
                processor,
                selected_counter,
                selected_limits,
                remote_authorization_mapping,
                prior_budget,
                short_reading=short_reading,
            )
        )
        with exclusive_file_lock(lock):
            _ensure_directory(transaction)
            _write_new_or_same(transaction / "request.json", request_body, selected_durability)
            identity = _load_or_create_identity(
                transaction,
                now=selected_now,
                durability=selected_durability,
            )
            ledger = ProcessingBudgetLedger(selected_limits, **prior_budget)
            stop_ledger = ledger
            review_locators: tuple[EvidenceLocator, ...] = ()
            map_segments = segments
            if short_reading:
                assert short_ranges is not None
                review_locators = _short_review_locators(
                    body=body,
                    source=source.run,
                    ranges=short_ranges,
                    transaction=transaction,
                    durability=selected_durability,
                )
                map_segments = _short_segments(
                    body,
                    short_ranges,
                    tuple(item.locator_id for item in review_locators),
                )
                direct_unit = _execute_unit(
                    transaction,
                    processor,
                    _planned_request(
                        _short_reading_draft(map_segments), selected_counter
                    ),
                    ledger,
                    selected_durability,
                    sleeper,
                )
                if direct_unit.response.focus_topics:
                    raise ValueError("short reading response must not request focus work")
                all_units = (direct_unit,)
                drafts = direct_unit.response.candidates
            else:
                l1_units = tuple(
                    _execute_unit(
                        transaction,
                        processor,
                        unit,
                        ledger,
                        selected_durability,
                        sleeper,
                    )
                    for unit in _l1_requests(segments, selected_counter)
                )
                section_units = tuple(
                    _execute_unit(
                        transaction,
                        processor,
                        unit,
                        ledger,
                        selected_durability,
                        sleeper,
                    )
                    for unit in _section_requests(l1_units, selected_counter)
                )
                global_unit = _execute_unit(
                    transaction,
                    processor,
                    _global_request(section_units, selected_counter),
                    ledger,
                    selected_durability,
                    sleeper,
                )
                focus_units = tuple(
                    _execute_unit(
                        transaction,
                        processor,
                        unit,
                        ledger,
                        selected_durability,
                        sleeper,
                    )
                    for unit in _focus_requests(global_unit, segments, selected_counter)
                )
                all_units = (*l1_units, *section_units, global_unit, *focus_units)
                drafts = _assembled_drafts(section_units, global_unit, focus_units)
            target_binding = target.record.target_binding
            curation_map = _curation_map(
                identity=identity,
                run=target.updated_run,
                evidence=source.evidence,
                target_binding=target_binding,
                processor=processor,
                ledger=ledger,
                executed_units=all_units,
                drafts=drafts,
                transaction=transaction,
                durability=selected_durability,
                segments=map_segments,
                prior_elapsed_ms=prior_elapsed_ms,
                reading_profile=(
                    _SHORT_READING_PROFILE if short_reading else None
                ),
                review_locators=review_locators,
            )
            yaml_body = dump_curation_map(curation_map)
            markdown_body = render_curation_map_markdown(curation_map)
            map_sha256 = curation_map_artifact_sha256(yaml_body, markdown_body)
            run_body = _run_record(
                identity=identity,
                request=request,
                curation_map=curation_map,
                map_sha256=map_sha256,
                processor=processor,
                counter=selected_counter,
                remote_authorization=remote_authorization_mapping,
                publish_base_commit=(
                    None if target_binding is None else target.result_commit
                ),
                ledger=ledger,
                units=all_units,
                prior_target_suggestion=prior_target_suggestion,
                short_reading=short_reading,
            )
            files = {
                "map.yaml": yaml_body,
                "map.md": markdown_body,
                "run.json": run_body,
            }
            repository: Path | None = None
            if target_binding is not None:
                if request.kb_parent is None or target.storage_name is None:
                    raise ValueError("target-bound map has no repository location")
                repository = request.kb_parent.resolve(strict=True) / target.storage_name
                publish_lock = repository / ".knowledgeflow" / "locks" / "curation-write.lock"
            else:
                publish_lock = (
                    layout.locks_root
                    / f"map-state-{curation_map.curation_run_id}.lock"
                )
            with exclusive_file_lock(publish_lock):
                # From this point a publish marker or checkpoint candidate may exist.
                published = True
                if repository is None:
                    (
                        yaml_path,
                        markdown_path,
                        run_path,
                        result_commit,
                        publish_transaction,
                        replayed_publish,
                    ) = _publish_no_target_map(
                        layout=layout,
                        request=request,
                        identity=identity,
                        curation_map=curation_map,
                        files=files,
                        durability=selected_durability,
                    )
                    receipt_files = {
                        f"v{curation_map.map_version:04d}/{name}": body
                        for name, body in files.items()
                    }
                    receipt_path = layout.receipts_root / f"map-{request.request_id}.json"
                    base_commit = None
                else:
                    (
                        yaml_path,
                        markdown_path,
                        run_path,
                        result_commit,
                        publish_transaction,
                        replayed_publish,
                    ) = _publish_target_map(
                        request=request,
                        identity=identity,
                        target=target,
                        repository=repository,
                        curation_map=curation_map,
                        files=files,
                        git=selected_git,
                        durability=selected_durability,
                    )
                    relative_yaml, relative_md, relative_run = _map_relative_paths(
                        curation_map
                    )
                    receipt_files = {
                        relative_yaml: files["map.yaml"],
                        relative_md: files["map.md"],
                        relative_run: files["run.json"],
                    }
                    receipt_path = (
                        repository
                        / ".knowledgeflow"
                        / "receipts"
                        / f"map-{request.request_id}.json"
                    )
                    base_commit = cast(str, target.result_commit)
                observed_map_hash, yaml_hash, markdown_hash = _validate_published_map(
                    yaml_path,
                    markdown_path,
                    run_path,
                    curation_map,
                    run_body,
                )
                if observed_map_hash != map_sha256:
                    raise ValueError("published map artifact hash changed")
                receipt = _receipt_body(
                    request_id=request.request_id,
                    transaction_id=cast(str, identity["transaction_id"]),
                    curation_map=curation_map,
                    map_sha256=map_sha256,
                    yaml_sha256=yaml_hash,
                    markdown_sha256=markdown_hash,
                    base_commit=base_commit,
                    files=receipt_files,
                    result_commit=result_commit,
                )
                replayed = _complete_publish_transaction(
                    publish_transaction,
                    receipt_path=receipt_path,
                    receipt_body=receipt,
                    result_commit=result_commit,
                    durability=selected_durability,
                ) or replayed_publish
            return MapBuildResult(
                request_id=request.request_id,
                curation_map=curation_map,
                map_sha256=map_sha256,
                yaml_sha256=yaml_hash,
                markdown_sha256=markdown_hash,
                yaml_path=yaml_path.resolve(strict=True),
                markdown_path=markdown_path.resolve(strict=True),
                run_record_path=run_path.resolve(strict=True),
                target_repository=repository,
                result_commit=result_commit,
                replayed=replayed,
            )
    except BudgetExhausted:
        try:
            _persist_processing_stop(
                stop_transaction,
                stop_evidence,
                stop_ledger,
                error_code=CurationErrorCode.BUDGET_EXHAUSTED,
                stop_reason="processor-budget",
                durability=selected_durability,
            )
        except (OSError, ValueError, DurabilityError):
            return _failure(
                CurationErrorCode.ATOMIC_PUBLISH_FAILED,
                stage="processing-stop-record",
                retryable=True,
            )
        return _failure(CurationErrorCode.BUDGET_EXHAUSTED, stage="processor-budget")
    except _ReadingProfileUnavailable:
        return _failure(CurationErrorCode.INVALID_INPUT, stage="reading-profile")
    except _RemoteAuthorizationError as exc:
        return _failure(exc.code, stage="remote-authorization")
    except ProcessorCallError as exc:
        try:
            _persist_processing_stop(
                stop_transaction,
                stop_evidence,
                stop_ledger,
                error_code=CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
                stop_reason=("processor-usage-unknown" if exc.unknown_usage else "processor-call"),
                durability=selected_durability,
            )
        except (OSError, ValueError, DurabilityError):
            return _failure(
                CurationErrorCode.ATOMIC_PUBLISH_FAILED,
                stage="processing-stop-record",
                retryable=True,
            )
        return _failure(
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
            stage="processor-call",
            retryable=exc.retryable and not exc.unknown_usage,
        )
    except _MapIdempotencyConflict:
        return _failure(
            CurationErrorCode.IDEMPOTENCY_CONFLICT,
            stage="map-idempotency",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
        )
    except _RecoveryRequired:
        return _failure(
            CurationErrorCode.RECOVERY_REQUIRED,
            stage="map-recovery",
            state=CurationCommitState.UNKNOWN,
            retryable=True,
        )
    except (ManagedGitConflict, ManagedGitIntegrityError):
        return _failure(
            CurationErrorCode.TARGET_CONFLICT,
            stage="managed-ref",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
        )
    except ManagedGitUnavailable:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            stage="version-control",
        )
    except ManagedGitError:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            stage="version-control",
            retryable=True,
        )
    except (DestinationAlreadyExistsError, DurabilityError, LockUnavailable, OSError):
        return _failure(
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
            stage="map-publish",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
            retryable=True,
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return _failure(
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
            stage="map-validate",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
        )


def _map_location(
    *,
    layout: _Layout,
    target: TargetDecideResult,
    map_id: str,
    map_version: int,
    kb_parent: Path | None,
) -> tuple[Path, Path | None]:
    if target.record.target_binding is None:
        root = (
            layout.work_root
            / target.updated_run.curation_run_id
            / "curation-maps"
            / map_id
        )
        return root / f"v{map_version:04d}", None
    if kb_parent is None or target.storage_name is None:
        raise ValueError("target-bound map requires kb_parent")
    repository = kb_parent.resolve(strict=True) / target.storage_name
    return (
        repository
        / "proposals"
        / "curation-maps"
        / map_id
        / f"v{map_version:04d}",
        repository,
    )


def _load_map_version(root: Path) -> tuple[CurationMap, bytes, bytes, str]:
    yaml_body = _read_bounded(root / "map.yaml")
    markdown_body = _read_bounded(root / "map.md")
    curation_map = load_curation_map(yaml_body)
    if render_curation_map_markdown(curation_map) != markdown_body:
        raise ValueError("map YAML and Markdown do not share one fact source")
    digest = curation_map_artifact_sha256(yaml_body, markdown_body)
    run = json.loads(_read_bounded(root / "run.json").decode("utf-8"))
    if not isinstance(run, Mapping) or run.get("map_sha256") != digest:
        raise ValueError("map run record does not bind the map artifact")
    return curation_map, yaml_body, markdown_body, digest


def _revised_map(
    original: CurationMap,
    decisions: Sequence[CandidateDecision],
    *,
    created_at: str,
    transaction: Path,
    durability: DurabilityBackend,
) -> CurationMap | None:
    by_id = {item.candidate_id: item for item in decisions}
    modified = [item for item in decisions if item.action == "modify"]
    if not modified:
        return None
    ids_path = transaction / "revised-candidate-ids.json"
    if ids_path.exists():
        value = json.loads(_read_bounded(ids_path).decode("utf-8"))
        identifiers = tuple(value.get("candidate_ids", ())) if isinstance(value, Mapping) else ()
        if len(identifiers) != len(modified):
            raise ValueError("revised candidate identity record is invalid")
    else:
        identifiers = tuple(generate_curation_id("cand_") for _ in modified)
        _write_new_or_same(
            ids_path,
            _canonical_json(
                {
                    "schema": "knowledgeflow.revised-candidate-identities",
                    "schema_version": 1,
                    "candidate_ids": list(identifiers),
                }
            ),
            durability,
        )
    replacement_ids = iter(identifiers)
    candidates: list[MapCandidate] = []
    for candidate in original.candidates:
        decision = by_id.get(candidate.candidate_id)
        if decision is None or decision.action != "modify":
            candidates.append(candidate)
            continue
        candidates.append(
            MapCandidate(
                candidate_id=next(replacement_ids),
                kind=candidate.kind,
                summary=cast(str, decision.replacement_text),
                evidence_locator_ids=candidate.evidence_locator_ids,
                provenance="user-revision",
                uncertainty="unknown",
                markdown_anchor=f"{candidate.markdown_anchor}-v{original.map_version + 1}",
                supersedes=candidate.candidate_id,
            )
        )
    return replace(
        original,
        map_version=original.map_version + 1,
        created_at=created_at,
        candidates=tuple(candidates),
    )


def _decision_request_body(request: MapDecideRequest) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.map-decision-request",
            "schema_version": 1,
            "request_id": request.request_id,
            "source_request_id": request.source_request_id,
            "target_decision_request_id": request.target_decision_request_id,
            "map_id": request.map_id,
            "map_version": request.map_version,
            "outcome": request.outcome,
            "decided_by": request.decided_by,
            "decisions": [item.as_mapping() for item in request.decisions],
            "target_parent_present": request.kb_parent is not None,
        }
    )


def _decision_run_record(
    *,
    identity: Mapping[str, object],
    request: MapDecideRequest,
    decision_relative_path: str,
    decision_sha256: str,
    curation_map: CurationMap,
    map_sha256: str,
    base_commit: str | None,
    revised: CurationMap | None,
    revised_map_sha256: str | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.map-decision-run",
            "schema_version": 1,
            "transaction_id": identity["transaction_id"],
            "request_id": request.request_id,
            "decision_set_id": identity["decision_set_id"],
            "decision_version": 1,
            "decision_relative_path": decision_relative_path,
            "decision_sha256": decision_sha256,
            "map_binding": {
                "map_id": curation_map.map_id,
                "map_version": curation_map.map_version,
                "map_sha256": map_sha256,
            },
            "target_binding": (
                None
                if curation_map.target_binding is None
                else curation_map.target_binding.as_mapping()
            ),
            "base_commit": base_commit,
            "outcome": request.outcome,
            "revised_map": (
                None
                if revised is None
                else {
                    "map_id": revised.map_id,
                    "map_version": revised.map_version,
                    "map_sha256": revised_map_sha256,
                }
            ),
            "publish_state": "published",
        }
    )


def _decision_receipt_body(
    *,
    request: MapDecideRequest,
    identity: Mapping[str, object],
    decision: MapDecision,
    decision_sha256: str,
    base_commit: str | None,
    files: Mapping[str, bytes],
    result_commit: str | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.map-decision-publish-receipt",
            "schema_version": 1,
            "request_id": request.request_id,
            "transaction_id": identity["transaction_id"],
            "decision_set_id": decision.decision_set_id,
            "decision_version": decision.version,
            "decision_sha256": decision_sha256,
            "map_sha256": decision.map_sha256,
            "base_commit": base_commit,
            "files": _file_manifest(files),
            "result_commit": result_commit,
            "state": request.outcome,
        }
    )


def _publish_no_target_decision(
    *,
    layout: _Layout,
    transaction: Path,
    request: MapDecideRequest,
    identity: Mapping[str, object],
    map_root: Path,
    files: Mapping[str, bytes],
    durability: DurabilityBackend,
) -> tuple[Path, Path, bool]:
    _assert_no_unresolved_publish_transaction(
        layout.transactions_root,
        current_name=transaction.name,
    )
    staging = _prepare_publish_transaction(
        transaction,
        kind="decision",
        request_id=request.request_id,
        transaction_id=cast(str, identity["transaction_id"]),
        base_commit=None,
        files=files,
        durability=durability,
    )
    started = transaction / "publish-started.json"
    none_present, all_present = _final_file_states(map_root, files)
    replayed = all_present
    if not started.exists():
        if not none_present and not all_present:
            raise _RecoveryRequired("no-target decision paths predate the transaction")
        _write_new_or_same(
            started,
            _canonical_json(
                {
                    "schema": "knowledgeflow.curation-publish-start",
                    "schema_version": 1,
                    "files": _file_manifest(files),
                }
            ),
            durability,
        )
    _publish_staged_files(map_root, staging, files, durability)
    none_present, all_present = _final_file_states(map_root, files)
    if none_present or not all_present:
        raise _RecoveryRequired("no-target decision publication is incomplete")
    decision_relative = next(path for path in files if path.endswith(".yaml") and "/decisions/" in f"/{path}")
    run_relative = decision_relative.removesuffix(".yaml") + ".run.json"
    return (
        map_root.joinpath(*PurePosixPath(decision_relative).parts),
        map_root.joinpath(*PurePosixPath(run_relative).parts),
        replayed,
    )


def _recover_target_decision_identity(
    repository: Path,
    request: MapDecideRequest,
) -> tuple[Mapping[str, object], str, tuple[str, ...]] | None:
    decisions_root = (
        repository
        / "proposals"
        / "curation-maps"
        / request.map_id
        / "decisions"
    )
    if not decisions_root.exists():
        return None
    _plain_directory(decisions_root)
    matches: list[tuple[Path, Mapping[str, object]]] = []
    for decision_set_root in decisions_root.iterdir():
        if not decision_set_root.is_dir() or not decision_set_root.name.startswith("dset_"):
            continue
        _plain_directory(decision_set_root)
        for run_path in decision_set_root.glob("v[0-9][0-9][0-9][0-9].run.json"):
            _plain_file(run_path)
            value = json.loads(_read_bounded(run_path).decode("utf-8"))
            if isinstance(value, Mapping) and value.get("request_id") == request.request_id:
                matches.append((run_path, value))
    if not matches:
        return None
    if len(matches) != 1:
        raise _RecoveryRequired("decision request matches more than one sidecar")
    run_path, sidecar = matches[0]
    decision_path = run_path.with_name(run_path.name.removesuffix(".run.json") + ".yaml")
    decision = load_map_decision(_read_bounded(decision_path))
    expected_relative = decision_path.relative_to(repository).as_posix()
    transaction_id = sidecar.get("transaction_id")
    base_commit = sidecar.get("base_commit")
    map_binding = sidecar.get("map_binding")
    if (
        sidecar.get("schema") != "knowledgeflow.map-decision-run"
        or sidecar.get("schema_version") != 1
        or sidecar.get("decision_set_id") != decision.decision_set_id
        or sidecar.get("decision_version") != decision.version
        or sidecar.get("decision_relative_path") != expected_relative
        or sidecar.get("decision_sha256") != map_decision_sha256(decision)
        or not isinstance(map_binding, Mapping)
        or map_binding.get("map_id") != request.map_id
        or map_binding.get("map_version") != request.map_version
        or map_binding.get("map_sha256") != decision.map_sha256
        or sidecar.get("outcome") != request.outcome
        or sidecar.get("publish_state") != "published"
        or type(transaction_id) is not str
        or _SAFE_TOKEN.fullmatch(transaction_id) is None
        or type(base_commit) is not str
        or re.fullmatch(r"[0-9a-f]{40}", base_commit) is None
    ):
        raise _RecoveryRequired("versioned decision recovery evidence is invalid")
    if (
        decision.outcome != request.outcome
        or decision.decided_by != request.decided_by
        or decision.decisions != request.decisions
    ):
        raise _MapIdempotencyConflict(
            "versioned decision differs from the repeated request"
        )

    modified = {
        item.candidate_id: item
        for item in request.decisions
        if item.action == "modify"
    }
    revised_binding = sidecar.get("revised_map")
    revised_candidate_ids: tuple[str, ...] = ()
    if modified:
        if not isinstance(revised_binding, Mapping) or set(revised_binding) != {
            "map_id",
            "map_version",
            "map_sha256",
        }:
            raise _RecoveryRequired("versioned revised-map recovery evidence is invalid")
        original_root = (
            repository
            / "proposals"
            / "curation-maps"
            / request.map_id
            / f"v{request.map_version:04d}"
        )
        revised_root = original_root.with_name(f"v{request.map_version + 1:04d}")
        original, _, _, _ = _load_map_version(original_root)
        revised, _, _, revised_sha256 = _load_map_version(revised_root)
        if (
            revised_binding.get("map_id") != request.map_id
            or revised_binding.get("map_version") != request.map_version + 1
            or revised_binding.get("map_sha256") != revised_sha256
            or revised.map_id != original.map_id
            or revised.map_version != original.map_version + 1
            or revised.created_at != decision.decided_at
            or revised.curation_run_id != original.curation_run_id
            or revised.source != original.source
            or revised.declared_scope != original.declared_scope
            or revised.scope != original.scope
            or revised.processor_profile != original.processor_profile
            or revised.processor_usage != original.processor_usage
            or revised.target_binding != original.target_binding
            or len(revised.candidates) != len(original.candidates)
        ):
            raise _RecoveryRequired("versioned revised map does not match its decision")
        recovered_ids: list[str] = []
        for previous, current in zip(
            original.candidates,
            revised.candidates,
            strict=True,
        ):
            change = modified.get(previous.candidate_id)
            if change is None:
                if current != previous:
                    raise _RecoveryRequired(
                        "versioned revised map changed an undecided candidate"
                    )
                continue
            if (
                current.kind != previous.kind
                or current.summary != change.replacement_text
                or current.evidence_locator_ids != previous.evidence_locator_ids
                or current.provenance != "user-revision"
                or current.uncertainty != "unknown"
                or current.markdown_anchor
                != f"{previous.markdown_anchor}-v{original.map_version + 1}"
                or current.supersedes != previous.candidate_id
            ):
                raise _RecoveryRequired(
                    "versioned revised candidate does not match its decision"
                )
            recovered_ids.append(current.candidate_id)
        if len(recovered_ids) != len(modified):
            raise _RecoveryRequired("versioned revised candidate identities are incomplete")
        revised_candidate_ids = tuple(recovered_ids)
    elif revised_binding is not None:
        raise _RecoveryRequired("decision unexpectedly binds a revised map")
    return (
        {
            "schema": "knowledgeflow.map-decision-identity",
            "schema_version": 1,
            "transaction_id": transaction_id,
            "decision_set_id": decision.decision_set_id,
            "decided_at": decision.decided_at,
        },
        base_commit,
        revised_candidate_ids,
    )


def decide_map(
    request: MapDecideRequest,
    *,
    experiment_root: str | os.PathLike[str],
    git: ManagedGit | None = None,
    durability: DurabilityBackend | None = None,
    now: Callable[[], datetime] | None = None,
) -> MapDecisionOperationResult:
    """Persist immutable candidate decisions and optional user-revised map version."""

    published = False
    try:
        if not isinstance(request, MapDecideRequest):
            raise TypeError("request must be MapDecideRequest")
        selected_git = git or ManagedGit()
        selected_durability = durability or DurabilityBackend()
        selected_now = now or (lambda: datetime.now(timezone.utc))
        layout = _layout(experiment_root)
        _prepare_layout(layout)
        target = inspect_target_decision(
            request.target_decision_request_id,
            experiment_root=layout.root,
            kb_parent=request.kb_parent,
            git=selected_git,
        )
        if not isinstance(target, TargetDecideResult):
            return _failure(
                target.error.code,
                stage="target-inspect",
                state=target.commit_state or CurationCommitState.NOT_COMMITTED,
            )
        if target.record.source_request_id != request.source_request_id:
            return _failure(CurationErrorCode.TARGET_CONFLICT, stage="target-binding")
        version_root, repository = _map_location(
            layout=layout,
            target=target,
            map_id=request.map_id,
            map_version=request.map_version,
            kb_parent=request.kb_parent,
        )
        transaction = layout.transactions_root / f"decision-{request.request_id}"
        request_lock = layout.locks_root / f"decision-{request.request_id}.lock"
        with exclusive_file_lock(request_lock):
            _ensure_directory(transaction)
            _write_new_or_same(
                transaction / "request.json",
                _decision_request_body(request),
                selected_durability,
            )
            identity_path = transaction / "identity.json"
            if identity_path.exists():
                identity = json.loads(_read_bounded(identity_path).decode("utf-8"))
            else:
                recovered_identity: (
                    tuple[Mapping[str, object], str, tuple[str, ...]] | None
                ) = None
                if repository is not None:
                    with exclusive_file_lock(
                        repository
                        / ".knowledgeflow"
                        / "locks"
                        / "curation-write.lock"
                    ):
                        recovered_identity = _recover_target_decision_identity(
                            repository,
                            request,
                        )
                if recovered_identity is None:
                    instant = selected_now()
                    if not isinstance(instant, datetime) or instant.tzinfo is None:
                        raise ValueError("now must return an aware datetime")
                    identity = {
                        "schema": "knowledgeflow.map-decision-identity",
                        "schema_version": 1,
                        "transaction_id": generate_curation_id("txn_"),
                        "decision_set_id": generate_curation_id("dset_"),
                        "decided_at": format_utc_milliseconds(
                            instant.astimezone(timezone.utc)
                        ),
                    }
                else:
                    identity, recovered_base_commit, recovered_revised_ids = (
                        recovered_identity
                    )
                    _write_new_or_same(
                        transaction / "publish-base-commit.txt",
                        (recovered_base_commit + "\n").encode("ascii"),
                        selected_durability,
                    )
                    if recovered_revised_ids:
                        _write_new_or_same(
                            transaction / "revised-candidate-ids.json",
                            _canonical_json(
                                {
                                    "schema": "knowledgeflow.revised-candidate-identities",
                                    "schema_version": 1,
                                    "candidate_ids": list(recovered_revised_ids),
                                }
                            ),
                            selected_durability,
                        )
                _write_new_or_same(
                    identity_path,
                    _canonical_json(identity),
                    selected_durability,
                )
            if repository is None:
                state_lock = (
                    layout.locks_root
                    / f"map-state-{target.updated_run.curation_run_id}.lock"
                )
            else:
                state_lock = repository / ".knowledgeflow" / "locks" / "curation-write.lock"
            with exclusive_file_lock(state_lock):
                curation_map, _, _, map_sha256 = _load_map_version(version_root)
                if (
                    curation_map.map_id != request.map_id
                    or curation_map.map_version != request.map_version
                    or curation_map.curation_run_id != target.updated_run.curation_run_id
                ):
                    return _failure(
                        CurationErrorCode.IDEMPOTENCY_CONFLICT,
                        stage="map-binding",
                    )
                base_commit: str | None = None
                if repository is not None:
                    base_path = transaction / "publish-base-commit.txt"
                    if base_path.exists():
                        base_commit = _read_bounded(base_path).decode("ascii").strip()
                        if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
                            raise _RecoveryRequired("decision base commit is invalid")
                    else:
                        base_commit = selected_git.current_commit(repository)
                        _write_new_or_same(
                            base_path,
                            (base_commit + "\n").encode("ascii"),
                            selected_durability,
                        )
                decision = MapDecision(
                    decision_set_id=identity["decision_set_id"],
                    version=1,
                    map_sha256=map_sha256,
                    outcome=request.outcome,
                    decided_by=request.decided_by,
                    decided_at=identity["decided_at"],
                    decisions=request.decisions,
                )
                decision.validate_against(curation_map, map_sha256)
                revised = _revised_map(
                    curation_map,
                    request.decisions,
                    created_at=identity["decided_at"],
                    transaction=transaction,
                    durability=selected_durability,
                )
                decision_body = dump_map_decision(decision)
                decision_sha256 = map_decision_sha256(decision)
                if repository is None:
                    map_root = version_root.parent
                    relative_decision = (
                        f"decisions/{decision.decision_set_id}/v0001.yaml"
                    )
                else:
                    map_root = repository
                    relative_decision = (
                        f"proposals/curation-maps/{request.map_id}/decisions/"
                        f"{decision.decision_set_id}/v0001.yaml"
                    )
                relative_decision_run = (
                    relative_decision.removesuffix(".yaml") + ".run.json"
                )
                revised_digest: str | None = None
                revised_files: dict[str, bytes] = {}
                if revised is not None:
                    revised_yaml = dump_curation_map(revised)
                    revised_md = render_curation_map_markdown(revised)
                    revised_digest = curation_map_artifact_sha256(
                        revised_yaml,
                        revised_md,
                    )
                    prior_run = json.loads(
                        _read_bounded(version_root / "run.json").decode("utf-8")
                    )
                    if not isinstance(prior_run, Mapping):
                        raise ValueError("prior map run record is invalid")
                    revised_run = dict(prior_run)
                    revised_run.update(
                        {
                            "transaction_id": identity["transaction_id"],
                            "request_id": request.request_id,
                            "map_version": revised.map_version,
                            "map_sha256": revised_digest,
                            "publish_base_commit": base_commit,
                            "state": "map-ready",
                            "stop_reason": "user-revision",
                        }
                    )
                    prefix = (
                        f"v{revised.map_version:04d}"
                        if repository is None
                        else (
                            f"proposals/curation-maps/{request.map_id}/"
                            f"v{revised.map_version:04d}"
                        )
                    )
                    revised_files = {
                        f"{prefix}/map.yaml": revised_yaml,
                        f"{prefix}/map.md": revised_md,
                        f"{prefix}/run.json": _canonical_json(revised_run),
                    }
                decision_run_body = _decision_run_record(
                    identity=identity,
                    request=request,
                    decision_relative_path=relative_decision,
                    decision_sha256=decision_sha256,
                    curation_map=curation_map,
                    map_sha256=map_sha256,
                    base_commit=base_commit,
                    revised=revised,
                    revised_map_sha256=revised_digest,
                )
                files: dict[str, bytes] = {
                    relative_decision: decision_body,
                    relative_decision_run: decision_run_body,
                    **revised_files,
                }
                published = True
                if repository is None:
                    decision_path, decision_run_path, replayed_publish = (
                        _publish_no_target_decision(
                            layout=layout,
                            transaction=transaction,
                            request=request,
                            identity=identity,
                            map_root=map_root,
                            files=files,
                            durability=selected_durability,
                        )
                    )
                    result_commit = None
                    publish_transaction = transaction
                    receipt_path = (
                        layout.receipts_root / f"decision-{request.request_id}.json"
                    )
                else:
                    transactions_root = repository / ".knowledgeflow" / "transactions"
                    _plain_directory(transactions_root)
                    publish_transaction = (
                        transactions_root / f"decision-{request.request_id}"
                    )
                    _assert_no_unresolved_publish_transaction(
                        transactions_root,
                        current_name=publish_transaction.name,
                    )
                    _prepare_publish_transaction(
                        publish_transaction,
                        kind="decision",
                        request_id=request.request_id,
                        transaction_id=cast(str, identity["transaction_id"]),
                        base_commit=base_commit,
                        files=files,
                        durability=selected_durability,
                    )
                    assert base_commit is not None
                    result_commit, replayed_publish = _target_checkpoint(
                        repository=repository,
                        transaction=publish_transaction,
                        files=files,
                        base_commit=base_commit,
                        checkpoint_time=decision.decided_at,
                        message=(
                            f"Record curation map decision {decision.decision_set_id} v1\n\n"
                            f"KnowledgeFlow-Transaction: {identity['transaction_id']}\n"
                        ),
                        git=selected_git,
                        durability=selected_durability,
                    )
                    decision_path = repository.joinpath(
                        *PurePosixPath(relative_decision).parts
                    )
                    decision_run_path = repository.joinpath(
                        *PurePosixPath(relative_decision_run).parts
                    )
                    receipt_path = (
                        repository
                        / ".knowledgeflow"
                        / "receipts"
                        / f"decision-{request.request_id}.json"
                    )
                if load_map_decision(_read_bounded(decision_path)) != decision:
                    raise ValueError("decision failed final readback")
                if _read_bounded(decision_run_path) != decision_run_body:
                    raise ValueError("decision run record failed final readback")
                if revised is not None:
                    revised_root = (
                        map_root
                        / f"v{revised.map_version:04d}"
                        if repository is None
                        else (
                            repository
                            / "proposals"
                            / "curation-maps"
                            / request.map_id
                            / f"v{revised.map_version:04d}"
                        )
                    )
                    observed_revised, _, _, observed_digest = _load_map_version(
                        revised_root
                    )
                    if observed_revised != revised or observed_digest != revised_digest:
                        raise ValueError("revised map failed final readback")
                receipt = _decision_receipt_body(
                    request=request,
                    identity=identity,
                    decision=decision,
                    decision_sha256=decision_sha256,
                    base_commit=base_commit,
                    files=files,
                    result_commit=result_commit,
                )
                replayed = _complete_publish_transaction(
                    publish_transaction,
                    receipt_path=receipt_path,
                    receipt_body=receipt,
                    result_commit=result_commit,
                    durability=selected_durability,
                ) or replayed_publish
            return MapDecisionResult(
                request_id=request.request_id,
                decision=decision,
                decision_sha256=decision_sha256,
                decision_path=decision_path.resolve(strict=True),
                run_record_path=decision_run_path.resolve(strict=True),
                state=request.outcome,
                revised_map=revised,
                revised_map_sha256=revised_digest,
                result_commit=result_commit,
                replayed=replayed,
            )
    except _MapIdempotencyConflict:
        return _failure(
            CurationErrorCode.IDEMPOTENCY_CONFLICT,
            stage="decision-idempotency",
            state=(
                CurationCommitState.UNKNOWN
                if published
                else CurationCommitState.NOT_COMMITTED
            ),
        )
    except _RecoveryRequired:
        return _failure(
            CurationErrorCode.RECOVERY_REQUIRED,
            stage="decision-recovery",
            state=CurationCommitState.UNKNOWN,
            retryable=True,
        )
    except (ManagedGitConflict, ManagedGitIntegrityError):
        return _failure(
            CurationErrorCode.TARGET_CONFLICT,
            stage="managed-ref",
            state=CurationCommitState.UNKNOWN if published else CurationCommitState.NOT_COMMITTED,
        )
    except ManagedGitUnavailable:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            stage="version-control",
        )
    except ManagedGitError:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            stage="version-control",
            retryable=True,
        )
    except (DestinationAlreadyExistsError, DurabilityError, LockUnavailable, OSError):
        return _failure(
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
            stage="decision-publish",
            state=CurationCommitState.UNKNOWN if published else CurationCommitState.NOT_COMMITTED,
            retryable=True,
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return _failure(
            CurationErrorCode.INVALID_INPUT,
            stage="decision-validate",
            state=CurationCommitState.UNKNOWN if published else CurationCommitState.NOT_COMMITTED,
        )


def close_map(
    request: MapDecideRequest,
    **kwargs: object,
) -> MapDecisionOperationResult:
    """Close a map only through a complete, immutable decision set."""

    if not isinstance(request, MapDecideRequest) or request.outcome != "map-closed":
        return _failure(CurationErrorCode.INVALID_INPUT, stage="map-close")
    return decide_map(request, **kwargs)


__all__ = [
    "MapBuildOperationResult",
    "MapBuildRequest",
    "MapBuildResult",
    "MapDecideRequest",
    "MapDecisionOperationResult",
    "MapDecisionResult",
    "TargetSuggestOperationResult",
    "TargetSuggestRequest",
    "TargetSuggestResult",
    "build_map",
    "close_map",
    "decide_map",
    "suggest_target",
]
