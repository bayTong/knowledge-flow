"""CUR1B source preparation, inspection, and exact Evidence readback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from types import MappingProxyType
from typing import Protocol

from knowledgeflow_capture import (
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    UserIntent,
    capture_text,
    get_capture,
)
from knowledgeflow_capture.durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
)
from knowledgeflow_capture.errors import (
    CommitState,
    FailureResult,
    GetCaptureResult,
    PublicErrorCode,
)
from knowledgeflow_capture.hashing import ByteLimitExceeded, hash_bytes, hash_stream
from knowledgeflow_capture.management import initialize_capture_store
from knowledgeflow_capture.models import format_utc_milliseconds, require_sha256
from knowledgeflow_capture.paths import PathPolicy

from .codec import (
    dump_curation_evidence,
    dump_curation_run,
    dump_source_mapping,
    load_curation_evidence,
    load_curation_run,
    load_source_mapping,
)
from .contracts import (
    ByteRange,
    CurationEvidenceRecord,
    CurationRunManifest,
    EvidenceLocator,
    ProcessingAuthorization,
    ProcessorProfile,
    ScopeRecord,
    SegmentationProfile,
    SourceBinding,
    SourceFileMapping,
)
from .errors import (
    CurationCommitState,
    CurationError,
    CurationErrorCode,
    CurationFailure,
)
from .ids import generate_curation_id
from .segmentation import build_evidence_record


_SAFE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_LOCATOR_ID = re.compile(
    r"loc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_RUN_ID = re.compile(
    r"run_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_MAX_INTERNAL_FILE_BYTES = 64 * 1024 * 1024
_BUNDLE_FILES = frozenset(
    {
        "request.json",
        "capture-warnings.json",
        "source-mapping.yaml",
        "run.yaml",
        "evidence.yaml",
    }
)
_CAPTURE_WARNING_CODES = frozenset(
    {
        "projection_needs_rebuild",
        "outbox_needs_rebuild",
        "incomplete_version_ignored",
    }
)
_REPARSE_ATTRIBUTE = 0x400


class BinaryWritable(Protocol):
    def write(self, data: bytes, /) -> int:
        ...


def _require_token(value: object, field_name: str) -> str:
    if type(value) is not str or _SAFE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe lowercase token")
    return value


def _freeze_warning_codes(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(values)
    if any(type(value) is not str or value not in _CAPTURE_WARNING_CODES for value in normalized):
        raise ValueError("capture warning codes contain an unsupported value")
    if len(set(normalized)) != len(normalized):
        raise ValueError("capture warning codes must be unique")
    return tuple(sorted(normalized))


def _scope_summary(
    scope: Sequence[ScopeRecord],
    *,
    source_byte_size: int,
    declared_scope: ByteRange,
) -> Mapping[str, int]:
    result = {
        "processed_bytes": 0,
        "deferred_bytes": 0,
        "failed_bytes": 0,
        "excluded_by_user_bytes": 0,
        "outside_declared_scope_bytes": (
            source_byte_size
            - (declared_scope.end_byte - declared_scope.start_byte)
        ),
    }
    names = {
        "processed": "processed_bytes",
        "deferred": "deferred_bytes",
        "failed": "failed_bytes",
        "excluded-by-user": "excluded_by_user_bytes",
    }
    for item in scope:
        result[names[item.status]] += item.byte_range.end_byte - item.byte_range.start_byte
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePrepareRequest:
    request_id: str
    source_path: str | os.PathLike[str]
    source_reference: str
    expected_sha256: str
    expected_byte_size: int
    authorized_by: str
    task_ids: tuple[str, ...]
    authorized_range: ByteRange | None = None
    declared_scope: ByteRange | None = None
    scope: tuple[ScopeRecord, ...] | None = None
    budget_id: str | None = None

    def __post_init__(self) -> None:
        _require_token(self.request_id, "request_id")
        try:
            path = Path(self.source_path)
        except TypeError as exc:
            raise ValueError("source_path must be path-like") from exc
        if not path.is_absolute():
            raise ValueError("source_path must be absolute")
        object.__setattr__(self, "source_path", path)
        _require_token(self.source_reference, "source_reference")
        require_sha256(self.expected_sha256, "expected_sha256")
        if type(self.expected_byte_size) is not int or self.expected_byte_size < 1:
            raise ValueError("expected_byte_size must be a positive integer")
        _require_token(self.authorized_by, "authorized_by")
        tasks = tuple(self.task_ids)
        if not 1 <= len(tasks) <= 32:
            raise ValueError("task_ids must contain from 1 through 32 values")
        for task_id in tasks:
            _require_token(task_id, "task_ids item")
        if len(set(tasks)) != len(tasks):
            raise ValueError("task_ids must be unique")
        object.__setattr__(self, "task_ids", tasks)
        if self.authorized_range is not None and not isinstance(
            self.authorized_range,
            ByteRange,
        ):
            raise TypeError("authorized_range must be ByteRange or null")
        if self.declared_scope is not None and not isinstance(
            self.declared_scope,
            ByteRange,
        ):
            raise TypeError("declared_scope must be ByteRange or null")
        if self.scope is not None:
            normalized_scope = tuple(self.scope)
            if not normalized_scope or not all(
                isinstance(item, ScopeRecord) for item in normalized_scope
            ):
                raise ValueError("scope must contain ScopeRecord values")
            object.__setattr__(self, "scope", normalized_scope)
        if self.budget_id is not None:
            _require_token(self.budget_id, "budget_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceInspectRequest:
    request_id: str

    def __post_init__(self) -> None:
        _require_token(self.request_id, "request_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceShowRequest:
    request_id: str
    locator_id: str
    body_sink: BinaryWritable

    def __post_init__(self) -> None:
        _require_token(self.request_id, "request_id")
        if type(self.locator_id) is not str or _LOCATOR_ID.fullmatch(self.locator_id) is None:
            raise ValueError("locator_id must use the loc_ UUIDv7 form")
        if not callable(getattr(self.body_sink, "write", None)):
            raise TypeError("body_sink must provide write(bytes)")


@dataclass(frozen=True, slots=True)
class SourcePrepareResult:
    request_id: str
    mapping: SourceFileMapping
    run: CurationRunManifest
    evidence: CurationEvidenceRecord
    capture_warning_codes: tuple[str, ...] = ()
    replayed: bool = False

    def __post_init__(self) -> None:
        _require_token(self.request_id, "request_id")
        if not isinstance(self.mapping, SourceFileMapping):
            raise TypeError("mapping must be SourceFileMapping")
        if not isinstance(self.run, CurationRunManifest):
            raise TypeError("run must be CurationRunManifest")
        if not isinstance(self.evidence, CurationEvidenceRecord):
            raise TypeError("evidence must be CurationEvidenceRecord")
        self.run.validate_source_mapping(self.mapping)
        self.evidence.validate_against_run(self.run)
        object.__setattr__(
            self,
            "capture_warning_codes",
            _freeze_warning_codes(self.capture_warning_codes),
        )
        if type(self.replayed) is not bool:
            raise TypeError("replayed must be boolean")

    def to_dict(self) -> dict[str, object]:
        return _bundle_result_mapping(
            self.request_id,
            self.mapping,
            self.run,
            self.evidence,
            self.capture_warning_codes,
            operation="source.prepare",
            replayed=self.replayed,
            committed=True,
        )


@dataclass(frozen=True, slots=True)
class SourceInspectResult:
    request_id: str
    mapping: SourceFileMapping
    run: CurationRunManifest
    evidence: CurationEvidenceRecord
    capture_warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        SourcePrepareResult(
            request_id=self.request_id,
            mapping=self.mapping,
            run=self.run,
            evidence=self.evidence,
            capture_warning_codes=self.capture_warning_codes,
        )

    def to_dict(self) -> dict[str, object]:
        return _bundle_result_mapping(
            self.request_id,
            self.mapping,
            self.run,
            self.evidence,
            self.capture_warning_codes,
            operation="source.inspect",
            replayed=None,
            committed=False,
        )


@dataclass(frozen=True, slots=True)
class EvidenceShowResult:
    request_id: str
    curation_run_id: str
    locator: EvidenceLocator
    body_length_bytes: int
    capture_warning_codes: tuple[str, ...] = ()
    integrity: str = field(default="verified", init=False)

    def __post_init__(self) -> None:
        _require_token(self.request_id, "request_id")
        if (
            type(self.curation_run_id) is not str
            or _RUN_ID.fullmatch(self.curation_run_id) is None
        ):
            raise ValueError("curation_run_id must use the run_ UUIDv7 form")
        if not isinstance(self.locator, EvidenceLocator):
            raise TypeError("locator must be EvidenceLocator")
        expected = self.locator.byte_range.end_byte - self.locator.byte_range.start_byte
        if type(self.body_length_bytes) is not int or self.body_length_bytes != expected:
            raise ValueError("body_length_bytes must equal the locator range length")
        object.__setattr__(
            self,
            "capture_warning_codes",
            _freeze_warning_codes(self.capture_warning_codes),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "operation": "evidence.show",
            "request_id": self.request_id,
            "curation_run_id": self.curation_run_id,
            "locator_id": self.locator.locator_id,
            "capture_id": self.locator.source.capture_id,
            "capture_version": self.locator.source.capture_version,
            "range": self.locator.byte_range.as_mapping(),
            "start_line": self.locator.start_line,
            "end_line": self.locator.end_line,
            "body_length_bytes": self.body_length_bytes,
            "excerpt_sha256": self.locator.excerpt_sha256,
            "integrity": self.integrity,
            "output_written": True,
            "warnings": _warning_mappings(self.capture_warning_codes),
        }


SourcePrepareOperationResult = SourcePrepareResult | CurationFailure
SourceInspectOperationResult = SourceInspectResult | CurationFailure
EvidenceShowOperationResult = EvidenceShowResult | CurationFailure


def _warning_mappings(codes: Sequence[str]) -> list[dict[str, str]]:
    return [{"source": "capture", "code": code} for code in codes]


def _bundle_result_mapping(
    request_id: str,
    mapping: SourceFileMapping,
    run: CurationRunManifest,
    evidence: CurationEvidenceRecord,
    warning_codes: Sequence[str],
    *,
    operation: str,
    replayed: bool | None,
    committed: bool,
) -> dict[str, object]:
    summary = _scope_summary(
        evidence.scope,
        source_byte_size=evidence.source.byte_size,
        declared_scope=evidence.declared_scope,
    )
    result: dict[str, object] = {
        "ok": True,
        "operation": operation,
        "request_id": request_id,
        "source_mapping_id": mapping.source_mapping_id,
        "curation_run_id": run.curation_run_id,
        "source": {
            "source_reference": mapping.source_reference,
            "source_sha256": mapping.source_sha256,
            "source_byte_size": mapping.source_byte_size,
            "capture_id": mapping.capture.capture_id,
            "capture_version": mapping.capture.capture_version,
            "envelope_sha256": mapping.capture.envelope_sha256,
        },
        "authorized_range": run.processing_authorization.allowed_range.as_mapping(),
        "declared_scope": run.declared_scope.as_mapping(),
        "segmentation_profile": run.segmentation_profile.as_mapping(),
        "segment_count": len(evidence.segments),
        "locator_count": len(evidence.locators),
        "scope_summary": dict(summary),
        "target_decision_recorded": run.target_decision is not None,
        "warnings": _warning_mappings(warning_codes),
    }
    if committed:
        result.update(
            {
                "saved": True,
                "commit_state": CurationCommitState.COMMITTED.value,
                "replayed": replayed,
            }
        )
    if operation == "source.inspect":
        result["segments"] = [item.as_mapping() for item in evidence.segments]
        result["scope"] = [item.as_mapping() for item in evidence.scope]
        result["locators"] = [
            {
                "locator_id": item.locator_id,
                "range": item.byte_range.as_mapping(),
                "start_line": item.start_line,
                "end_line": item.end_line,
                "excerpt_sha256": item.excerpt_sha256,
            }
            for item in evidence.locators
        ]
    return result


@dataclass(frozen=True, slots=True)
class _Layout:
    root: Path
    config_path: Path
    capture_root: Path
    work_root: Path
    requests_root: Path
    staging_root: Path


@dataclass(frozen=True, slots=True)
class _Bundle:
    request_bytes: bytes
    warning_codes: tuple[str, ...]
    mapping: SourceFileMapping
    run: CurationRunManifest
    evidence: CurationEvidenceRecord


class _ExistingConflict(Exception):
    pass


class _ExistingCorrupt(Exception):
    pass


def _failure(
    code: CurationErrorCode,
    *,
    retryable: bool = False,
    commit_state: CurationCommitState | None = None,
    stage: str | None = None,
) -> CurationFailure:
    details: dict[str, object] = {}
    if stage is not None:
        details["stage"] = stage
    return CurationFailure(
        CurationError(code=code, retryable=retryable, details=details),
        commit_state,
    )


def _is_reparse(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_ATTRIBUTE)


def _require_plain_directory(path: Path) -> None:
    stat_result = path.lstat()
    if not stat.S_ISDIR(stat_result.st_mode) or _is_reparse(stat_result):
        raise OSError("path is not a plain directory")


def _resolve_absolute(value: str | os.PathLike[str]) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    return Path(os.path.abspath(path))


def _layout_for(experiment_root: str | os.PathLike[str]) -> _Layout:
    root = _resolve_absolute(experiment_root)
    work_root = root / "curation-work"
    return _Layout(
        root=root,
        config_path=root / "capture-config.yaml",
        capture_root=root / "capture-store",
        work_root=work_root,
        requests_root=work_root / "requests",
        staging_root=work_root / ".staging",
    )


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        pass
    _require_plain_directory(path)


def _prepare_layout(layout: _Layout) -> None:
    if not layout.root.exists():
        _require_plain_directory(layout.root.parent)
        layout.root.mkdir(parents=False, exist_ok=False)
    _require_plain_directory(layout.root)
    _ensure_directory(layout.work_root)
    _ensure_directory(layout.requests_root)
    _ensure_directory(layout.staging_root)


def _require_existing_layout(layout: _Layout) -> None:
    for path in (
        layout.root,
        layout.work_root,
        layout.requests_root,
        layout.staging_root,
    ):
        _require_plain_directory(path)


@contextmanager
def _open_plain_source(path: Path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _is_reparse(before):
        raise OSError("source is not a plain file")
    stream = path.open("rb")
    try:
        after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise OSError("source identity changed while opening")
        yield stream
    finally:
        stream.close()


def _hash_exact_source(path: Path, expected_size: int) -> tuple[int, str]:
    with _open_plain_source(path) as stream:
        digest = hash_stream(stream, maximum_bytes=expected_size)
    return digest.byte_size, digest.sha256


def _source_ranges_use_character_boundaries(
    path: Path,
    ranges: Sequence[ByteRange],
    source_size: int,
) -> bool:
    offsets = {
        offset
        for byte_range in ranges
        for offset in (byte_range.start_byte, byte_range.end_byte)
        if offset not in {0, source_size}
    }
    with _open_plain_source(path) as stream:
        for offset in sorted(offsets):
            stream.seek(offset)
            value = stream.read(1)
            if len(value) != 1 or value[0] & 0xC0 == 0x80:
                return False
    return True


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


def _resolved_ranges(
    request: SourcePrepareRequest,
) -> tuple[ByteRange, ByteRange, tuple[ScopeRecord, ...]]:
    full = ByteRange(0, request.expected_byte_size)
    authorized = request.authorized_range or full
    declared = request.declared_scope or authorized
    if authorized.end_byte > request.expected_byte_size:
        raise ValueError("authorized_range exceeds expected source bytes")
    if (
        declared.start_byte < authorized.start_byte
        or declared.end_byte > authorized.end_byte
    ):
        raise ValueError("declared_scope exceeds authorized_range")
    scope = request.scope or (ScopeRecord(declared, "processed"),)
    cursor = declared.start_byte
    for item in scope:
        if item.byte_range.start_byte != cursor:
            raise ValueError("scope must cover declared_scope without gaps or overlap")
        cursor = item.byte_range.end_byte
    if cursor != declared.end_byte:
        raise ValueError("scope must cover declared_scope exactly")
    return authorized, declared, tuple(scope)


def _request_bytes(
    request: SourcePrepareRequest,
    authorized: ByteRange,
    declared: ByteRange,
    scope: Sequence[ScopeRecord],
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.curation-source-prepare-request",
            "schema_version": 1,
            "request_id": request.request_id,
            "source_reference": request.source_reference,
            "expected_sha256": request.expected_sha256,
            "expected_byte_size": request.expected_byte_size,
            "authorized_by": request.authorized_by,
            "authorized_range": authorized.as_mapping(),
            "declared_scope": declared.as_mapping(),
            "task_ids": list(request.task_ids),
            "budget_id": request.budget_id,
            "scope": [item.as_mapping() for item in scope],
            "segmentation_profile": SegmentationProfile().as_mapping(),
        }
    )


def _read_bounded(path: Path) -> bytes:
    stat_result = path.lstat()
    if not stat.S_ISREG(stat_result.st_mode) or _is_reparse(stat_result):
        raise _ExistingCorrupt
    if stat_result.st_size > _MAX_INTERNAL_FILE_BYTES:
        raise _ExistingCorrupt
    return path.read_bytes()


def _load_warning_codes(source: bytes) -> tuple[str, ...]:
    try:
        value = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ExistingCorrupt from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "schema_version",
        "codes",
    }:
        raise _ExistingCorrupt
    if (
        value["schema"] != "knowledgeflow.capture-warning-codes"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise _ExistingCorrupt
    codes = value["codes"]
    if type(codes) is not list:
        raise _ExistingCorrupt
    try:
        normalized = _freeze_warning_codes(tuple(codes))
    except ValueError as exc:
        raise _ExistingCorrupt from exc
    if _canonical_json(value) != source:
        raise _ExistingCorrupt
    return normalized


def _reject_duplicate_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_request_metadata(source: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(
            source.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _ExistingCorrupt from exc
    expected_keys = {
        "schema",
        "schema_version",
        "request_id",
        "source_reference",
        "expected_sha256",
        "expected_byte_size",
        "authorized_by",
        "authorized_range",
        "declared_scope",
        "task_ids",
        "budget_id",
        "scope",
        "segmentation_profile",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise _ExistingCorrupt
    try:
        if (
            value["schema"] != "knowledgeflow.curation-source-prepare-request"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError("unsupported request schema")
        _require_token(value["request_id"], "request_id")
        _require_token(value["source_reference"], "source_reference")
        require_sha256(value["expected_sha256"], "expected_sha256")
        if type(value["expected_byte_size"]) is not int or value[
            "expected_byte_size"
        ] < 1:
            raise ValueError("invalid expected_byte_size")
        _require_token(value["authorized_by"], "authorized_by")
        authorized = ByteRange.from_mapping(value["authorized_range"])
        declared = ByteRange.from_mapping(value["declared_scope"])
        if (
            declared.start_byte < authorized.start_byte
            or declared.end_byte > authorized.end_byte
        ):
            raise ValueError("declared scope exceeds authorization")
        tasks = value["task_ids"]
        if type(tasks) is not list or not 1 <= len(tasks) <= 32:
            raise ValueError("invalid task_ids")
        for task_id in tasks:
            _require_token(task_id, "task_ids item")
        if len(set(tasks)) != len(tasks):
            raise ValueError("duplicate task ID")
        if value["budget_id"] is not None:
            _require_token(value["budget_id"], "budget_id")
        raw_scope = value["scope"]
        if type(raw_scope) is not list or not raw_scope:
            raise ValueError("invalid scope")
        scope = tuple(ScopeRecord.from_mapping(item) for item in raw_scope)
        cursor = declared.start_byte
        for item in scope:
            if item.byte_range.start_byte != cursor:
                raise ValueError("scope gap or overlap")
            cursor = item.byte_range.end_byte
        if cursor != declared.end_byte:
            raise ValueError("scope does not cover declared range")
        SegmentationProfile.from_mapping(value["segmentation_profile"])
        if _canonical_json(value) != source:
            raise ValueError("request JSON is not canonical")
    except (TypeError, ValueError) as exc:
        raise _ExistingCorrupt from exc
    return value


def _load_bundle(directory: Path) -> _Bundle:
    try:
        _require_plain_directory(directory)
        names = frozenset(item.name for item in directory.iterdir())
        if names != _BUNDLE_FILES:
            raise _ExistingCorrupt
        request_bytes = _read_bounded(directory / "request.json")
        request_metadata = _load_request_metadata(request_bytes)
        warning_bytes = _read_bounded(directory / "capture-warnings.json")
        mapping = load_source_mapping(_read_bounded(directory / "source-mapping.yaml"))
        run = load_curation_run(_read_bounded(directory / "run.yaml"))
        evidence = load_curation_evidence(_read_bounded(directory / "evidence.yaml"))
        run.validate_source_mapping(mapping)
        evidence.validate_against_run(run)
        warning_codes = _load_warning_codes(warning_bytes)
        if request_metadata["request_id"] != directory.name:
            raise _ExistingCorrupt
        if (
            request_metadata["source_reference"] != mapping.source_reference
            or request_metadata["expected_sha256"] != mapping.source_sha256
            or request_metadata["expected_byte_size"] != mapping.source_byte_size
            or ByteRange.from_mapping(request_metadata["authorized_range"])
            != run.processing_authorization.allowed_range
            or ByteRange.from_mapping(request_metadata["declared_scope"])
            != run.declared_scope
            or request_metadata["authorized_by"]
            != run.processing_authorization.authorized_by
            or tuple(request_metadata["task_ids"])
            != run.processing_authorization.task_ids
            or request_metadata["budget_id"]
            != run.processing_authorization.budget_id
            or tuple(
                ScopeRecord.from_mapping(item) for item in request_metadata["scope"]
            )
            != evidence.scope
            or SegmentationProfile.from_mapping(
                request_metadata["segmentation_profile"]
            )
            != run.segmentation_profile
        ):
            raise _ExistingCorrupt
    except _ExistingCorrupt:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise _ExistingCorrupt from exc
    return _Bundle(request_bytes, warning_codes, mapping, run, evidence)


def _existing_bundle(directory: Path, request_bytes: bytes) -> _Bundle | None:
    try:
        directory.lstat()
    except FileNotFoundError:
        return None
    bundle = _load_bundle(directory)
    if bundle.request_bytes != request_bytes:
        raise _ExistingConflict
    return bundle


def _result_from_bundle(
    request_id: str,
    bundle: _Bundle,
    *,
    replayed: bool,
) -> SourcePrepareResult:
    return SourcePrepareResult(
        request_id=request_id,
        mapping=bundle.mapping,
        run=bundle.run,
        evidence=bundle.evidence,
        capture_warning_codes=bundle.warning_codes,
        replayed=replayed,
    )


def _capture_failure_result(result: FailureResult) -> CurationFailure:
    mapping = {
        PublicErrorCode.INVALID_INPUT: CurationErrorCode.UNSUPPORTED_SOURCE,
        PublicErrorCode.TEXT_TOO_LARGE: CurationErrorCode.UNSUPPORTED_SOURCE,
        PublicErrorCode.IDEMPOTENCY_CONFLICT: CurationErrorCode.IDEMPOTENCY_CONFLICT,
        PublicErrorCode.INTEGRITY_CHECK_FAILED: CurationErrorCode.SOURCE_INTEGRITY_FAILED,
    }
    code = mapping.get(result.error.code, CurationErrorCode.ATOMIC_PUBLISH_FAILED)
    state = CurationCommitState.NOT_COMMITTED
    if result.commit_state is CommitState.UNKNOWN:
        state = CurationCommitState.UNKNOWN
    return _failure(
        code,
        retryable=result.error.retryable,
        commit_state=state,
        stage="capture",
    )


def _capture_warning_codes(result: object) -> tuple[str, ...]:
    warnings = getattr(result, "warnings", ())
    return _freeze_warning_codes(tuple(item.code.value for item in warnings))


def _write_bundle(
    layout: _Layout,
    destination: Path,
    *,
    request_bytes: bytes,
    warning_codes: tuple[str, ...],
    mapping: SourceFileMapping,
    run: CurationRunManifest,
    evidence: CurationEvidenceRecord,
    durability: DurabilityBackend,
) -> None:
    staging = Path(tempfile.mkdtemp(prefix="prepare-", dir=layout.staging_root))
    try:
        files = {
            "request.json": request_bytes,
            "capture-warnings.json": _canonical_json(
                {
                    "schema": "knowledgeflow.capture-warning-codes",
                    "schema_version": 1,
                    "codes": list(warning_codes),
                }
            ),
            "source-mapping.yaml": dump_source_mapping(mapping),
            "run.yaml": dump_curation_run(run),
            "evidence.yaml": dump_curation_evidence(evidence),
        }
        for name, data in files.items():
            durability.write_new_file_durable(staging / name, data)
        durability.commit_directory_no_replace(staging, destination)
    finally:
        if staging.exists():
            try:
                if staging.parent.resolve(strict=True) == layout.staging_root.resolve(
                    strict=True
                ) and staging.name.startswith("prepare-"):
                    shutil.rmtree(staging)
            except OSError:
                pass


def _write_all(sink: BinaryWritable, value: bytes) -> None:
    remaining = memoryview(value)
    while remaining:
        written = sink.write(remaining)
        if written is None or type(written) is not int or written <= 0:
            raise OSError("short output write")
        remaining = remaining[written:]


def prepare_source(
    request: SourcePrepareRequest,
    *,
    experiment_root: str | os.PathLike[str],
    path_policy: PathPolicy,
) -> SourcePrepareOperationResult:
    """Capture, verify, segment, and atomically publish one exact source bundle."""

    capture_committed = False
    try:
        if not isinstance(request, SourcePrepareRequest) or not isinstance(
            path_policy,
            PathPolicy,
        ):
            raise ValueError("invalid operation dependencies")
        layout = _layout_for(experiment_root)
        authorized, declared, scope = _resolved_ranges(request)
        request_bytes = _request_bytes(request, authorized, declared, scope)
        _prepare_layout(layout)
        initialized = initialize_capture_store(
            config_path=layout.config_path,
            capture_root=layout.capture_root,
            path_policy=path_policy,
        )
        if isinstance(initialized, FailureResult):
            return _capture_failure_result(initialized)

        destination = layout.requests_root / request.request_id
        existing = _existing_bundle(destination, request_bytes)
        if existing is not None:
            return _result_from_bundle(request.request_id, existing, replayed=True)

        source_path = Path(request.source_path)
        observed_size, observed_hash = _hash_exact_source(
            source_path,
            request.expected_byte_size,
        )
        if (
            observed_size != request.expected_byte_size
            or observed_hash != request.expected_sha256
        ):
            return _failure(
                CurationErrorCode.SOURCE_IDENTITY_MISMATCH,
                commit_state=CurationCommitState.NOT_COMMITTED,
                stage="source-preflight",
            )
        if not _source_ranges_use_character_boundaries(
            source_path,
            (authorized, declared, *(item.byte_range for item in scope)),
            request.expected_byte_size,
        ):
            return _failure(
                CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH,
                commit_state=CurationCommitState.NOT_COMMITTED,
                stage="scope-boundary",
            )

        with _open_plain_source(source_path) as stream:
            captured = capture_text(
                CaptureTextRequest(
                    text=stream,
                    channel=ChannelMetadata(
                        type="curation",
                        instance_id="knowledgeflow-curation",
                        external_ref=request.source_reference,
                    ),
                    idempotency_key=f"curation-source-prepare:{request.request_id}",
                    user_intent=UserIntent(processing_mode="deep-curation"),
                ),
                config_path=layout.config_path,
                path_policy=path_policy,
            )
        if isinstance(captured, FailureResult):
            return _capture_failure_result(captured)
        capture_committed = True
        receipt = captured.receipt
        if (
            receipt["primary_payload_sha256"] != request.expected_sha256
            or receipt["version"] != 1
        ):
            return _failure(
                CurationErrorCode.SOURCE_INTEGRITY_FAILED,
                commit_state=CurationCommitState.UNKNOWN,
                stage="capture-receipt",
            )

        after_size, after_hash = _hash_exact_source(
            source_path,
            request.expected_byte_size,
        )
        if after_size != observed_size or after_hash != observed_hash:
            return _failure(
                CurationErrorCode.SOURCE_IDENTITY_MISMATCH,
                commit_state=CurationCommitState.UNKNOWN,
                stage="source-postflight",
            )

        body_sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(
                capture_id=receipt["capture_id"],
                version=1,
                body_sink=body_sink,
            ),
            config_path=layout.config_path,
            path_policy=path_policy,
        )
        if isinstance(read, FailureResult):
            return _failure(
                CurationErrorCode.SOURCE_INTEGRITY_FAILED,
                retryable=read.error.retryable,
                commit_state=CurationCommitState.UNKNOWN,
                stage="capture-readback",
            )
        source_bytes = body_sink.getvalue()
        if (
            read.body_length_bytes != request.expected_byte_size
            or hash_bytes(source_bytes).sha256 != request.expected_sha256
        ):
            return _failure(
                CurationErrorCode.SOURCE_INTEGRITY_FAILED,
                commit_state=CurationCommitState.UNKNOWN,
                stage="capture-readback",
            )

        source = SourceBinding(
            capture_id=receipt["capture_id"],
            capture_version=receipt["version"],
            envelope_sha256=receipt["envelope_sha256"],
            payload_sha256=receipt["primary_payload_sha256"],
            byte_size=request.expected_byte_size,
        )
        now = format_utc_milliseconds(datetime.now(timezone.utc))
        mapping = SourceFileMapping(
            source_mapping_id=generate_curation_id("smap_"),
            source_reference=request.source_reference,
            source_sha256=request.expected_sha256,
            source_byte_size=request.expected_byte_size,
            capture=source,
            mapped_at=now,
        )
        run = CurationRunManifest(
            curation_run_id=generate_curation_id("run_"),
            source_mapping_id=mapping.source_mapping_id,
            source=source,
            processing_authorization=ProcessingAuthorization(
                authorization_id=generate_curation_id("auth_"),
                authorized_by=request.authorized_by,
                authorized_at=now,
                allowed_range=authorized,
                task_ids=request.task_ids,
                budget_id=request.budget_id,
            ),
            declared_scope=declared,
            target_decision=None,
            segmentation_profile=SegmentationProfile(),
            processor_profile=ProcessorProfile(
                kind="mechanical",
                processor_id="cur1b-markdown-segmenter",
                revision=1,
                model_id=None,
                network_allowed=False,
            ),
            state="authorized",
        )
        evidence = build_evidence_record(source_bytes, run, scope=scope)
        warning_codes = _capture_warning_codes(captured)
        try:
            _write_bundle(
                layout,
                destination,
                request_bytes=request_bytes,
                warning_codes=warning_codes,
                mapping=mapping,
                run=run,
                evidence=evidence,
                durability=DurabilityBackend(),
            )
        except (DestinationAlreadyExistsError, DurabilityError, OSError):
            try:
                winner = _existing_bundle(destination, request_bytes)
            except (_ExistingConflict, _ExistingCorrupt):
                return _failure(
                    CurationErrorCode.RECOVERY_REQUIRED,
                    retryable=True,
                    commit_state=CurationCommitState.UNKNOWN,
                    stage="work-publish",
                )
            if winner is not None:
                return _result_from_bundle(request.request_id, winner, replayed=True)
            return _failure(
                CurationErrorCode.ATOMIC_PUBLISH_FAILED,
                retryable=True,
                commit_state=CurationCommitState.UNKNOWN,
                stage="work-publish",
            )
        return SourcePrepareResult(
            request_id=request.request_id,
            mapping=mapping,
            run=run,
            evidence=evidence,
            capture_warning_codes=warning_codes,
            replayed=False,
        )
    except _ExistingConflict:
        return _failure(
            CurationErrorCode.IDEMPOTENCY_CONFLICT,
            commit_state=CurationCommitState.NOT_COMMITTED,
            stage="request-replay",
        )
    except _ExistingCorrupt:
        return _failure(
            CurationErrorCode.RECOVERY_REQUIRED,
            retryable=True,
            commit_state=CurationCommitState.UNKNOWN,
            stage="work-readback",
        )
    except FileNotFoundError:
        return _failure(
            CurationErrorCode.SOURCE_NOT_FOUND,
            commit_state=(
                CurationCommitState.UNKNOWN
                if capture_committed
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="source-open",
        )
    except ByteLimitExceeded:
        return _failure(
            CurationErrorCode.SOURCE_IDENTITY_MISMATCH,
            commit_state=(
                CurationCommitState.UNKNOWN
                if capture_committed
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="source-preflight",
        )
    except UnicodeDecodeError:
        return _failure(
            CurationErrorCode.UNSUPPORTED_SOURCE,
            commit_state=(
                CurationCommitState.UNKNOWN
                if capture_committed
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="utf8-validation",
        )
    except (OSError, TypeError, ValueError):
        return _failure(
            CurationErrorCode.INVALID_INPUT,
            commit_state=(
                CurationCommitState.UNKNOWN
                if capture_committed
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="validate",
        )


def inspect_source(
    request: SourceInspectRequest,
    *,
    experiment_root: str | os.PathLike[str],
) -> SourceInspectOperationResult:
    """Read and cross-validate one already published CUR1B source bundle."""

    try:
        if not isinstance(request, SourceInspectRequest):
            raise ValueError("request must be SourceInspectRequest")
        layout = _layout_for(experiment_root)
        _require_existing_layout(layout)
        bundle = _load_bundle(layout.requests_root / request.request_id)
        return SourceInspectResult(
            request_id=request.request_id,
            mapping=bundle.mapping,
            run=bundle.run,
            evidence=bundle.evidence,
            capture_warning_codes=bundle.warning_codes,
        )
    except FileNotFoundError:
        return _failure(CurationErrorCode.SOURCE_NOT_FOUND, stage="work-readback")
    except _ExistingCorrupt:
        return _failure(
            CurationErrorCode.SOURCE_INTEGRITY_FAILED,
            stage="work-readback",
        )
    except (OSError, TypeError, ValueError):
        return _failure(CurationErrorCode.INVALID_INPUT, stage="validate")


def show_evidence(
    request: EvidenceShowRequest,
    *,
    experiment_root: str | os.PathLike[str],
    path_policy: PathPolicy,
) -> EvidenceShowOperationResult:
    """Verify one locator against its exact Capture and then emit its bytes."""

    try:
        if not isinstance(request, EvidenceShowRequest) or not isinstance(
            path_policy,
            PathPolicy,
        ):
            raise ValueError("invalid operation dependencies")
        layout = _layout_for(experiment_root)
        _require_existing_layout(layout)
        bundle = _load_bundle(layout.requests_root / request.request_id)
        locator = next(
            (
                item
                for item in bundle.evidence.locators
                if item.locator_id == request.locator_id
            ),
            None,
        )
        if locator is None:
            return _failure(CurationErrorCode.LOCATOR_INVALID, stage="locator-lookup")

        sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(
                capture_id=locator.source.capture_id,
                version=locator.source.capture_version,
                body_sink=sink,
            ),
            config_path=layout.config_path,
            path_policy=path_policy,
        )
        if isinstance(read, FailureResult):
            code = (
                CurationErrorCode.SOURCE_INTEGRITY_FAILED
                if read.error.code is PublicErrorCode.INTEGRITY_CHECK_FAILED
                else CurationErrorCode.SOURCE_NOT_FOUND
            )
            return _failure(code, retryable=read.error.retryable, stage="capture-readback")
        if not isinstance(read, GetCaptureResult):
            raise ValueError("unexpected Capture read result")
        metadata = read.capture
        if (
            metadata.capture_id != locator.source.capture_id
            or metadata.version != locator.source.capture_version
            or metadata.envelope_sha256 != locator.source.envelope_sha256
            or metadata.primary_payload_sha256 != locator.source.payload_sha256
            or metadata.byte_size != locator.source.byte_size
        ):
            return _failure(
                CurationErrorCode.SOURCE_INTEGRITY_FAILED,
                stage="source-binding",
            )
        body = sink.getvalue()
        body.decode("utf-8", errors="strict")
        start = locator.byte_range.start_byte
        end = locator.byte_range.end_byte
        if end > len(body):
            return _failure(CurationErrorCode.LOCATOR_INVALID, stage="locator-range")
        excerpt = body[start:end]
        excerpt.decode("utf-8", errors="strict")
        if hash_bytes(excerpt).sha256 != locator.excerpt_sha256:
            return _failure(
                CurationErrorCode.EVIDENCE_INTEGRITY_FAILED,
                stage="locator-digest",
            )
        _write_all(request.body_sink, excerpt)
        warning_codes = _freeze_warning_codes(
            tuple(
                sorted(
                    set(bundle.warning_codes)
                    | {item.code.value for item in read.warnings}
                )
            )
        )
        return EvidenceShowResult(
            request_id=request.request_id,
            curation_run_id=bundle.run.curation_run_id,
            locator=locator,
            body_length_bytes=len(excerpt),
            capture_warning_codes=warning_codes,
        )
    except FileNotFoundError:
        return _failure(CurationErrorCode.SOURCE_NOT_FOUND, stage="work-readback")
    except _ExistingCorrupt:
        return _failure(
            CurationErrorCode.SOURCE_INTEGRITY_FAILED,
            stage="work-readback",
        )
    except UnicodeDecodeError:
        return _failure(
            CurationErrorCode.EVIDENCE_INTEGRITY_FAILED,
            stage="utf8-validation",
        )
    except OSError:
        return _failure(
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
            retryable=True,
            stage="output-write",
        )
    except (TypeError, ValueError):
        return _failure(CurationErrorCode.INVALID_INPUT, stage="validate")


__all__ = [
    "EvidenceShowOperationResult",
    "EvidenceShowRequest",
    "EvidenceShowResult",
    "SourceInspectOperationResult",
    "SourceInspectRequest",
    "SourceInspectResult",
    "SourcePrepareOperationResult",
    "SourcePrepareRequest",
    "SourcePrepareResult",
    "inspect_source",
    "prepare_source",
    "show_evidence",
]
