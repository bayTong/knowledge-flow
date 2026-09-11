"""Governed public capture operations for the local Capture Store."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from .codec import (
    CaptureEventReferenceError,
    dump_capture_event,
    dump_capture_state,
    load_capture_event,
    load_capture_state,
    load_envelope,
)
from .config import (
    ConfigLoadError,
    LocalConfig,
    read_local_config_file,
    resolve_config_path,
)
from .durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
    DurabilityStage,
    InvalidTextInputError,
)
from .errors import (
    CauseCode,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
    WarningCode,
)
from .hashing import (
    ByteLimitExceeded,
    DEFAULT_CHUNK_SIZE,
    idempotency_key_sha256,
    payload_set_sha256,
    request_fingerprint_sha256,
    seal_envelope,
    verify_envelope,
)
from .ids import (
    IdKind,
    generate_capture_id,
    generate_event_id,
    generate_uuid7,
    validate_typed_id,
)
from .locking import (
    CaptureWriteLock,
    CaptureWriteLockError,
    _acquire_capture_write_lock,
)
from .models import (
    CaptureTextRequest,
    DigestResult,
    PayloadMetadata,
    PayloadSetEntry,
    RequestFingerprint,
    UserIntent,
    canonical_idempotency_scope,
    format_utc_milliseconds,
)
from .paths import PathPolicy, PathPolicyError
from .store import (
    _CaptureStaging,
    _InitFailure,
    _cleanup_capture_staging,
    _create_capture_staging,
    _inspect_store,
)


CaptureTextOperationResult = CommittedWriteResult | FailureResult

_ACTOR = {"type": "user", "actor_id": "local-user"}
_ENVELOPE_MAXIMUM_BYTES = 1024 * 1024
_EVENT_MAXIMUM_BYTES = 256 * 1024
_PROJECTION_MAXIMUM_BYTES = 1024 * 1024
_YEAR_PATTERN = re.compile(r"[0-9]{4}\Z")
_MONTH_PATTERN = re.compile(r"(?:0[1-9]|1[0-2])\Z")
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_LockFactory = Callable[[Path], CaptureWriteLock]
_UtcNow = Callable[[], datetime]
_TypedIdFactory = Callable[[], str]
_UuidFactory = Callable[[], UUID]
_FaultHook = Callable[[], None]
_ReplaceFile = Callable[[Path, Path], None]


class _CaptureFaultPoint(StrEnum):
    """Internal-only C3 fault points; never accepted from public input."""

    BEFORE_EVENT_WRITE = "before_event_write"
    BEFORE_PROJECTION_REPLACE = "before_projection_replace"


def _default_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _noop_fault_hook() -> None:
    return None


@dataclass(frozen=True, slots=True)
class _CaptureDependencies:
    durability: DurabilityBackend = field(default_factory=DurabilityBackend)
    lock_factory: _LockFactory = field(
        default=_acquire_capture_write_lock,
        repr=False,
        compare=False,
    )
    utc_now: _UtcNow = field(
        default=_default_utc_now,
        repr=False,
        compare=False,
    )
    capture_id_factory: _TypedIdFactory = field(
        default=generate_capture_id,
        repr=False,
        compare=False,
    )
    event_id_factory: _TypedIdFactory = field(
        default=generate_event_id,
        repr=False,
        compare=False,
    )
    staging_uuid_factory: _UuidFactory = field(
        default=generate_uuid7,
        repr=False,
        compare=False,
    )
    replace_file: _ReplaceFile = field(
        default=os.replace,
        repr=False,
        compare=False,
    )
    fault_point: _CaptureFaultPoint | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    fault_hook: _FaultHook = field(
        default=_noop_fault_hook,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class _StoredItem:
    item_path: Path
    envelope: Mapping[str, object]
    event: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _CandidateItem:
    capture_id: str
    event_id: str
    received_at: str
    envelope: Mapping[str, object]
    envelope_bytes: bytes
    event: Mapping[str, object]
    event_bytes: bytes
    payload_digest: DigestResult
    payload_set_sha256: str


class _IntegrityFailure(RuntimeError):
    def __init__(self, cause_code: CauseCode) -> None:
        self.cause_code = CauseCode(cause_code)
        super().__init__(self.cause_code.value)


class _StoreIoFailure(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        cause_code: CauseCode | None = None,
    ) -> None:
        self.stage = stage
        self.cause_code = cause_code
        super().__init__(stage)


class _IdempotencyConflict(RuntimeError):
    pass


def _trigger_fault(
    point: _CaptureFaultPoint,
    dependencies: _CaptureDependencies,
) -> None:
    if dependencies.fault_point == point:
        dependencies.fault_hook()


def _failure(
    code: PublicErrorCode,
    state: CommitState,
    *,
    retryable: bool = False,
    cause_code: CauseCode | None = None,
    details: Mapping[str, object] | None = None,
) -> FailureResult:
    return FailureResult(
        error=OperationError(
            code=code,
            retryable=retryable,
            cause_code=cause_code,
            details={} if details is None else details,
        ),
        commit_state=state,
    )


def _integrity_failure(
    failure: _IntegrityFailure,
    state: CommitState,
) -> FailureResult:
    return _failure(
        PublicErrorCode.INTEGRITY_CHECK_FAILED,
        state,
        cause_code=failure.cause_code,
    )


def _io_failure(
    failure: _StoreIoFailure,
    state: CommitState,
) -> FailureResult:
    return _failure(
        PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        state,
        cause_code=failure.cause_code,
        details={"stage": failure.stage},
    )


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _lstat_if_present(path: Path) -> os.stat_result | None:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_identity(path: Path, expected: os.stat_result) -> bool:
    try:
        current = _lstat_if_present(path)
    except OSError:
        return False
    return current is not None and (
        current.st_dev == expected.st_dev
        and current.st_ino == expected.st_ino
        and current.st_mode == expected.st_mode
        and not _is_reparse_point(current)
    )


def _plain_directory_stat(path: Path, *, stage: str) -> os.stat_result:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _StoreIoFailure(stage=stage) from exc
    if path_stat is None or not stat.S_ISDIR(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        raise _StoreIoFailure(stage=stage)
    return path_stat


def _directory_entries(path: Path, *, stage: str) -> tuple[Path, ...]:
    _plain_directory_stat(path, stage=stage)
    try:
        return tuple(sorted(path.iterdir(), key=lambda item: item.name))
    except OSError as exc:
        raise _StoreIoFailure(stage=stage) from exc


def _read_regular_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    missing_cause: CauseCode,
    invalid_cause: CauseCode,
    io_cause: CauseCode | None = None,
) -> bytes:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _StoreIoFailure(
            stage="immutable-read",
            cause_code=io_cause,
        ) from exc
    if path_stat is None:
        raise _IntegrityFailure(missing_cause)
    if not stat.S_ISREG(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise _IntegrityFailure(invalid_cause)
    if path_stat.st_size > maximum_bytes:
        raise _IntegrityFailure(invalid_cause)

    try:
        with path.open("rb") as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == path_stat.st_dev
                and handle_stat.st_ino == path_stat.st_ino
                and handle_stat.st_mode == path_stat.st_mode
            ):
                raise _IntegrityFailure(invalid_cause)
            chunks: list[bytes] = []
            total = 0
            while True:
                value = stream.read(min(64 * 1024, maximum_bytes - total + 1))
                if not isinstance(value, bytes):
                    raise _IntegrityFailure(invalid_cause)
                if not value:
                    break
                total += len(value)
                if total > maximum_bytes:
                    raise _IntegrityFailure(invalid_cause)
                chunks.append(value)
    except _IntegrityFailure:
        raise
    except OSError as exc:
        raise _StoreIoFailure(
            stage="immutable-read",
            cause_code=io_cause,
        ) from exc
    if not _same_identity(path, path_stat):
        raise _IntegrityFailure(invalid_cause)
    return b"".join(chunks)


def _load_item_core(
    item_path: Path,
    *,
    expected_capture_id: str,
    expected_year: str | None = None,
    expected_month: str | None = None,
) -> _StoredItem:
    _plain_directory_stat(item_path, stage="item-read")
    version_path = item_path / "versions" / "000001"
    _plain_directory_stat(version_path, stage="version-read")
    envelope_path = version_path / "envelope.yaml"
    envelope_bytes = _read_regular_bytes(
        envelope_path,
        maximum_bytes=_ENVELOPE_MAXIMUM_BYTES,
        missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
    )
    try:
        envelope = load_envelope(envelope_bytes, require_canonical=True)
    except ValueError as exc:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH) from exc
    if not verify_envelope(envelope):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    if (
        envelope["capture_id"] != expected_capture_id
        or envelope["version"] != 1
        or envelope["previous_version"] is not None
    ):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    received_at = envelope["received_at"]
    if type(received_at) is not str:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    if expected_year is not None and received_at[:4] != expected_year:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    if expected_month is not None and received_at[5:7] != expected_month:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)

    event_path = item_path / "events" / f"{envelope['event_id']}.yaml"
    event_bytes = _read_regular_bytes(
        event_path,
        maximum_bytes=_EVENT_MAXIMUM_BYTES,
        missing_cause=CauseCode.EVENT_MISSING,
        invalid_cause=CauseCode.EVENT_SCHEMA_INVALID,
    )
    try:
        event = load_capture_event(
            event_bytes,
            envelope=envelope,
            require_canonical=True,
        )
    except CaptureEventReferenceError as exc:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH) from exc
    except ValueError as exc:
        raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID) from exc
    return _StoredItem(item_path=item_path, envelope=envelope, event=event)


def _payload_mappings(
    envelope: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    try:
        payloads = envelope["payloads"]
    except KeyError as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH) from exc
    if type(payloads) is not list or not all(
        isinstance(payload, Mapping) for payload in payloads
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    return tuple(payloads)


def _payload_entry(payload: Mapping[str, object]) -> PayloadSetEntry:
    try:
        ordinal = payload["ordinal"]
        role = payload["role"]
        kind = payload["kind"]
        media_type = payload["media_type"]
        byte_size = payload["byte_size"]
        sha256 = payload["sha256"]
    except KeyError as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH) from exc
    if (
        type(ordinal) is not int
        or type(role) is not str
        or type(kind) is not str
        or type(media_type) is not str
        or type(byte_size) is not int
        or type(sha256) is not str
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    try:
        return PayloadSetEntry(
            ordinal=ordinal,
            role=role,
            kind=kind,
            media_type=media_type,
            byte_size=byte_size,
            sha256=sha256,
        )
    except (TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH) from exc


def _payload_entries(envelope: Mapping[str, object]) -> tuple[PayloadSetEntry, ...]:
    return tuple(_payload_entry(payload) for payload in _payload_mappings(envelope))


def _verify_primary_payload(stored: _StoredItem) -> DigestResult:
    envelope = stored.envelope
    entries = _payload_entries(envelope)
    try:
        expected_payload_set = payload_set_sha256(entries)
    except (TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH) from exc
    stored_payload_set = envelope["payload_set_sha256"]
    if type(stored_payload_set) is not str or not hmac.compare_digest(
        expected_payload_set, stored_payload_set
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)

    payloads = _payload_mappings(envelope)
    primary = next(
        (
            payload
            for payload in payloads
            if payload["ordinal"] == 0 and payload["role"] == "primary"
        ),
        None,
    )
    if primary is None:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    primary_path = primary["path"]
    primary_size = primary["byte_size"]
    primary_sha256 = primary["sha256"]
    if (
        type(primary_path) is not str
        or primary_path != "payloads/primary.txt"
        or type(primary_size) is not int
        or type(primary_sha256) is not str
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    payload_path = stored.item_path / "versions" / "000001" / primary_path
    try:
        path_stat = _lstat_if_present(payload_path)
    except OSError as exc:
        raise _StoreIoFailure(
            stage="payload-read",
            cause_code=CauseCode.PAYLOAD_READ_FAILED,
        ) from exc
    if path_stat is None or not stat.S_ISREG(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    if path_stat.st_size != primary_size:
        raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)

    digest = hashlib.sha256()
    byte_size = 0
    try:
        with payload_path.open("rb") as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == path_stat.st_dev
                and handle_stat.st_ino == path_stat.st_ino
                and handle_stat.st_mode == path_stat.st_mode
            ):
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
            while True:
                chunk = stream.read(DEFAULT_CHUNK_SIZE)
                if not isinstance(chunk, bytes):
                    raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                if not chunk:
                    break
                digest.update(chunk)
                byte_size += len(chunk)
    except _IntegrityFailure:
        raise
    except OSError as exc:
        raise _StoreIoFailure(
            stage="payload-read",
            cause_code=CauseCode.PAYLOAD_READ_FAILED,
        ) from exc
    if not _same_identity(payload_path, path_stat):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    if byte_size != primary_size:
        raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)
    actual_sha256 = "sha256:" + digest.hexdigest()
    if not hmac.compare_digest(actual_sha256, primary_sha256):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    return DigestResult(byte_size=byte_size, sha256=actual_sha256)


def _capture_items(capture_root: Path) -> Iterator[tuple[Path, str, str]]:
    items_root = capture_root / "items"
    for year_path in _directory_entries(items_root, stage="idempotency-scan"):
        if _YEAR_PATTERN.fullmatch(year_path.name) is None:
            continue
        _plain_directory_stat(year_path, stage="idempotency-scan")
        for month_path in _directory_entries(year_path, stage="idempotency-scan"):
            if _MONTH_PATTERN.fullmatch(month_path.name) is None:
                continue
            _plain_directory_stat(month_path, stage="idempotency-scan")
            for item_path in _directory_entries(month_path, stage="idempotency-scan"):
                if not item_path.name.startswith("cap_"):
                    continue
                try:
                    validate_typed_id(item_path.name, IdKind.CAPTURE)
                except ValueError as exc:
                    raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH) from exc
                _plain_directory_stat(item_path, stage="idempotency-scan")
                yield item_path, year_path.name, month_path.name


def _find_idempotent_item(
    capture_root: Path,
    *,
    scope: str,
    key_sha256: str,
    request_sha256: str,
) -> _StoredItem | None:
    matched: _StoredItem | None = None
    for item_path, year, month in _capture_items(capture_root):
        stored = _load_item_core(
            item_path,
            expected_capture_id=item_path.name,
            expected_year=year,
            expected_month=month,
        )
        identity = stored.envelope["idempotency"]
        if identity is None:
            continue
        if not isinstance(identity, Mapping):
            raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
        if identity["scope"] != scope or identity["key_sha256"] != key_sha256:
            continue
        if identity["request_fingerprint_sha256"] != request_sha256:
            raise _IdempotencyConflict
        if matched is not None:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        matched = stored
    if matched is not None:
        _verify_primary_payload(matched)
    return matched


def _projection_is_valid(stored: _StoredItem) -> bool:
    try:
        source = _read_regular_bytes(
            stored.item_path / "capture.yaml",
            maximum_bytes=_PROJECTION_MAXIMUM_BYTES,
            missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        )
        load_capture_state(
            source,
            envelope=stored.envelope,
            require_canonical=True,
        )
        return True
    except (_IntegrityFailure, _StoreIoFailure, ValueError):
        return False


def _warnings_for_projection(stored: _StoredItem) -> tuple[OperationWarning, ...]:
    if _projection_is_valid(stored):
        return ()
    return (OperationWarning(code=WarningCode.PROJECTION_NEEDS_REBUILD),)


def _receipt_from_stored(stored: _StoredItem) -> dict[str, object]:
    envelope = stored.envelope
    primary = next(
        payload
        for payload in _payload_mappings(envelope)
        if payload["ordinal"] == 0 and payload["role"] == "primary"
    )
    return {
        "capture_id": envelope["capture_id"],
        "event_id": envelope["event_id"],
        "version": envelope["version"],
        "primary_payload_sha256": primary["sha256"],
        "payload_set_sha256": envelope["payload_set_sha256"],
        "envelope_sha256": envelope["envelope_sha256"],
        "durability": "durable",
        "routing_status": "unassigned",
        "trust_status": "unreviewed-capture",
        "gbrain_sync_status": "not-requested",
    }


def _success_from_stored(stored: _StoredItem) -> CommittedWriteResult:
    return CommittedWriteResult(
        receipt=_receipt_from_stored(stored),
        warnings=_warnings_for_projection(stored),
    )


def _sample_time(dependencies: _CaptureDependencies) -> str:
    return format_utc_milliseconds(dependencies.utc_now())


def _typed_id(factory: _TypedIdFactory, kind: IdKind) -> str:
    value = factory()
    validate_typed_id(value, kind)
    return value


def _build_candidate(
    request: CaptureTextRequest,
    *,
    received_at: str,
    payload_digest: DigestResult,
    payload_set_digest: str,
    request_digest: str,
    scope: str | None,
    key_digest: str | None,
    dependencies: _CaptureDependencies,
) -> _CandidateItem:
    capture_id = _typed_id(dependencies.capture_id_factory, IdKind.CAPTURE)
    event_id = _typed_id(dependencies.event_id_factory, IdKind.EVENT)
    captured_at = _sample_time(dependencies)
    intent = request.user_intent
    if intent is None:  # defensive; CaptureTextRequest normalizes this in C3A
        raise TypeError("CaptureTextRequest.user_intent was not normalized")
    idempotency: dict[str, object] | None = None
    if scope is not None and key_digest is not None:
        idempotency = {
            "scope": scope,
            "key_sha256": key_digest,
            "request_fingerprint_sha256": request_digest,
        }
    envelope_without_hash: dict[str, object] = {
        "schema": "knowledgeflow.capture-envelope",
        "schema_version": 1,
        "capture_id": capture_id,
        "event_id": event_id,
        "version": 1,
        "previous_version": None,
        "received_at": received_at,
        "captured_at": captured_at,
        "actor": dict(_ACTOR),
        "channel": request.channel.as_canonical_mapping(),
        "idempotency": idempotency,
        "payloads": [
            {
                "payload_id": payload_digest.sha256,
                "ordinal": 0,
                "role": "primary",
                "kind": "text",
                "path": "payloads/primary.txt",
                "original_name": None,
                "media_type": "text/plain; charset=utf-8",
                "encoding": "utf-8",
                "fidelity": "channel-exact",
                "byte_size": payload_digest.byte_size,
                "sha256": payload_digest.sha256,
            }
        ],
        "payload_set_sha256": payload_set_digest,
        "user_intent": {
            **intent.as_canonical_mapping(),
            "evidence": {
                "event_id": event_id,
                "payload_id": payload_digest.sha256,
            },
        },
        "delivery_requests": [],
        "envelope_serialization": {
            "encoding": "utf-8",
            "line_endings": "lf",
            "bom": False,
            "key_order": "schema-defined",
        },
    }
    sealed = seal_envelope(envelope_without_hash)
    occurred_at = _sample_time(dependencies)
    event: dict[str, object] = {
        "schema": "knowledgeflow.capture-event",
        "schema_version": 1,
        "event_id": event_id,
        "event_type": "capture.created",
        "capture_id": capture_id,
        "version": 1,
        "envelope_sha256": sealed.sha256,
        "occurred_at": occurred_at,
        "actor": dict(_ACTOR),
    }
    event_bytes = dump_capture_event(event, envelope=sealed.envelope)
    return _CandidateItem(
        capture_id=capture_id,
        event_id=event_id,
        received_at=received_at,
        envelope=sealed.envelope,
        envelope_bytes=sealed.yaml_bytes,
        event=event,
        event_bytes=event_bytes,
        payload_digest=payload_digest,
        payload_set_sha256=payload_set_digest,
    )


def _require_exact_envelope(source: bytes, candidate: _CandidateItem) -> object:
    envelope = load_envelope(source, require_canonical=True)
    if envelope != candidate.envelope or not verify_envelope(envelope):
        raise ValueError("Envelope does not match the transaction candidate")
    return envelope


def _require_exact_event(source: bytes, candidate: _CandidateItem) -> object:
    event = load_capture_event(
        source,
        envelope=candidate.envelope,
        require_canonical=True,
    )
    if event != candidate.event:
        raise ValueError("Event does not match the transaction candidate")
    return event


def _write_candidate_metadata(
    staging: _CaptureStaging,
    candidate: _CandidateItem,
    dependencies: _CaptureDependencies,
) -> None:
    dependencies.durability.write_new_file_durable(
        staging.version_path / "envelope.yaml",
        candidate.envelope_bytes,
        validator=lambda source: _require_exact_envelope(source, candidate),
    )
    _trigger_fault(_CaptureFaultPoint.BEFORE_EVENT_WRITE, dependencies)
    dependencies.durability.write_new_file_durable(
        staging.item_path / "events" / f"{candidate.event_id}.yaml",
        candidate.event_bytes,
        validator=lambda source: _require_exact_event(source, candidate),
    )


def _validate_candidate_at(
    item_path: Path,
    candidate: _CandidateItem,
    *,
    expected_year: str | None = None,
    expected_month: str | None = None,
) -> _StoredItem:
    stored = _load_item_core(
        item_path,
        expected_capture_id=candidate.capture_id,
        expected_year=expected_year,
        expected_month=expected_month,
    )
    if stored.envelope != candidate.envelope:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    if stored.event != candidate.event:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    actual_payload = _verify_primary_payload(stored)
    if actual_payload.byte_size != candidate.payload_digest.byte_size:
        raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)
    if not hmac.compare_digest(
        actual_payload.sha256,
        candidate.payload_digest.sha256,
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    return stored


def _ensure_partition_directory(
    parent: Path,
    name: str,
    durability: DurabilityBackend,
) -> tuple[Path, os.stat_result]:
    _plain_directory_stat(parent, stage="partition-create")
    target = parent / name
    try:
        target_stat = _lstat_if_present(target)
    except OSError as exc:
        raise _StoreIoFailure(stage="partition-create") from exc
    if target_stat is None:
        try:
            target.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _StoreIoFailure(stage="partition-create") from exc
        try:
            durability.flush_directory_metadata(parent)
        except DurabilityError as exc:
            raise _StoreIoFailure(stage="partition-create") from exc
    target_stat = _plain_directory_stat(target, stage="partition-create")
    return target, target_stat


def _final_item_path(
    capture_root: Path,
    candidate: _CandidateItem,
    dependencies: _CaptureDependencies,
) -> tuple[Path, str, str]:
    year = candidate.received_at[:4]
    month = candidate.received_at[5:7]
    year_path, year_stat = _ensure_partition_directory(
        capture_root / "items",
        year,
        dependencies.durability,
    )
    month_path, month_stat = _ensure_partition_directory(
        year_path,
        month,
        dependencies.durability,
    )
    if year_stat.st_dev != month_stat.st_dev:
        raise _StoreIoFailure(stage="partition-create")
    return month_path / candidate.capture_id, year, month


_UNPROVABLE = object()


def _probe(path: Path) -> os.stat_result | None | object:
    try:
        return _lstat_if_present(path)
    except OSError:
        return _UNPROVABLE


def _source_is_original_directory(
    source_path: Path,
    source_stat: os.stat_result,
    probe: os.stat_result | None | object,
) -> bool:
    return isinstance(probe, os.stat_result) and (
        stat.S_ISDIR(probe.st_mode)
        and not _is_reparse_point(probe)
        and probe.st_dev == source_stat.st_dev
        and probe.st_ino == source_stat.st_ino
        and probe.st_mode == source_stat.st_mode
        and _same_identity(source_path, source_stat)
    )


def _classify_commit_exception(
    staging: _CaptureStaging,
    final_path: Path,
    candidate: _CandidateItem,
    *,
    source_stat: os.stat_result,
    year: str,
    month: str,
) -> _StoredItem | FailureResult:
    source_probe = _probe(staging.item_path)
    target_probe = _probe(final_path)
    if source_probe is _UNPROVABLE or target_probe is _UNPROVABLE:
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.UNKNOWN,
            retryable=True,
        )
    if _source_is_original_directory(staging.item_path, source_stat, source_probe):
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
            retryable=True,
        )
    if source_probe is None and isinstance(target_probe, os.stat_result):
        try:
            return _validate_candidate_at(
                final_path,
                candidate,
                expected_year=year,
                expected_month=month,
            )
        except _IntegrityFailure as exc:
            return _integrity_failure(exc, CommitState.UNKNOWN)
        except _StoreIoFailure:
            return _failure(
                PublicErrorCode.ATOMIC_COMMIT_FAILED,
                CommitState.UNKNOWN,
                retryable=True,
            )
    return _failure(
        PublicErrorCode.ATOMIC_COMMIT_FAILED,
        CommitState.UNKNOWN,
        retryable=True,
    )


def _commit_candidate(
    staging: _CaptureStaging,
    candidate: _CandidateItem,
    dependencies: _CaptureDependencies,
) -> _StoredItem | FailureResult:
    final_path, year, month = _final_item_path(
        staging.capture_root,
        candidate,
        dependencies,
    )
    source_stat = _plain_directory_stat(
        staging.item_path,
        stage="item-commit",
    )
    target_before = _probe(final_path)
    if target_before is _UNPROVABLE:
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.UNKNOWN,
            retryable=True,
        )
    if target_before is not None:
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.NOT_COMMITTED,
            retryable=True,
        )

    try:
        dependencies.durability.commit_directory_no_replace(
            staging.item_path,
            final_path,
        )
    except (DestinationAlreadyExistsError, DurabilityError, OSError):
        return _classify_commit_exception(
            staging,
            final_path,
            candidate,
            source_stat=source_stat,
            year=year,
            month=month,
        )

    try:
        return _validate_candidate_at(
            final_path,
            candidate,
            expected_year=year,
            expected_month=month,
        )
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.UNKNOWN)
    except _StoreIoFailure:
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.UNKNOWN,
            retryable=True,
        )


def _initial_projection(
    candidate: _CandidateItem,
    *,
    verified_at: str,
) -> dict[str, object]:
    return {
        "schema": "knowledgeflow.capture-state",
        "schema_version": 1,
        "capture_id": candidate.capture_id,
        "current_version": 1,
        "current_envelope_sha256": candidate.envelope["envelope_sha256"],
        "durability": {"status": "durable", "verified_at": verified_at},
        "routing": {"status": "unassigned", "target_kb_ids": []},
        "trust": {"status": "unreviewed-capture"},
        "gbrain": {
            "sync_status": "not-requested",
            "source_id": None,
            "page_slug": None,
            "mirrored_version": None,
            "mirrored_envelope_sha256": None,
        },
        "backup": {
            "git_status": "uncommitted",
            "commit": None,
            "remote_status": "not-requested",
        },
        "updated_at": verified_at,
    }


def _write_projection(
    stored: _StoredItem,
    candidate: _CandidateItem,
    staging: _CaptureStaging,
    dependencies: _CaptureDependencies,
) -> bool:
    temporary_path = stored.item_path / (
        f".capture-state-{staging.transaction_id}.tmp"
    )
    destination_path = stored.item_path / "capture.yaml"
    temporary_stat: os.stat_result | None = None
    try:
        verified_at = _sample_time(dependencies)
        state = _initial_projection(candidate, verified_at=verified_at)
        state_bytes = dump_capture_state(state, envelope=candidate.envelope)
        dependencies.durability.write_new_file_durable(
            temporary_path,
            state_bytes,
            validator=lambda source: load_capture_state(
                source,
                envelope=candidate.envelope,
                require_canonical=True,
            ),
        )
        temporary_stat = _lstat_if_present(temporary_path)
        if temporary_stat is None or not stat.S_ISREG(temporary_stat.st_mode) or (
            _is_reparse_point(temporary_stat)
        ):
            return False
        destination_stat = _lstat_if_present(destination_path)
        if destination_stat is not None and (
            not stat.S_ISREG(destination_stat.st_mode)
            or _is_reparse_point(destination_stat)
        ):
            return False
        _trigger_fault(_CaptureFaultPoint.BEFORE_PROJECTION_REPLACE, dependencies)
        if not _same_identity(temporary_path, temporary_stat):
            return False
        dependencies.replace_file(temporary_path, destination_path)
        dependencies.durability.flush_directory_metadata(stored.item_path)
        return _projection_is_valid(stored)
    except Exception:
        return False
    finally:
        if temporary_stat is not None and _same_identity(
            temporary_path,
            temporary_stat,
        ):
            try:
                temporary_path.unlink()
                dependencies.durability.flush_directory_metadata(stored.item_path)
            except (DurabilityError, OSError):
                pass


def _new_success(
    stored: _StoredItem,
    candidate: _CandidateItem,
    staging: _CaptureStaging,
    dependencies: _CaptureDependencies,
) -> CommittedWriteResult:
    projection_valid = _write_projection(
        stored,
        candidate,
        staging,
        dependencies,
    )
    warnings: tuple[OperationWarning, ...] = ()
    if not projection_valid:
        warnings = (
            OperationWarning(code=WarningCode.PROJECTION_NEEDS_REBUILD),
        )
    return CommittedWriteResult(
        receipt=_receipt_from_stored(stored),
        warnings=warnings,
    )


def _load_capture_environment(
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
) -> tuple[LocalConfig, Path]:
    if not isinstance(path_policy, PathPolicy):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)
    selected = resolve_config_path(config_path)
    try:
        selected = path_policy.validate_config_path(selected)
    except PathPolicyError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    local_config = read_local_config_file(
        selected,
        path_policy=path_policy,
    )
    manifest = _inspect_store(local_config.capture.root)
    if manifest is None:
        raise _InitFailure(
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
                retryable=False,
            )
        )
    return local_config, local_config.capture.root


def _capture_while_locked(
    request: CaptureTextRequest,
    *,
    staging: _CaptureStaging,
    received_at: str,
    payload_digest: DigestResult,
    payload_set_digest: str,
    request_digest: str,
    scope: str | None,
    key_digest: str | None,
    dependencies: _CaptureDependencies,
) -> CaptureTextOperationResult:
    if scope is not None and key_digest is not None:
        try:
            matched = _find_idempotent_item(
                staging.capture_root,
                scope=scope,
                key_sha256=key_digest,
                request_sha256=request_digest,
            )
        except _IdempotencyConflict:
            return _failure(
                PublicErrorCode.IDEMPOTENCY_CONFLICT,
                CommitState.NOT_COMMITTED,
            )
        except _IntegrityFailure as exc:
            return _integrity_failure(exc, CommitState.UNKNOWN)
        except _StoreIoFailure as exc:
            return _io_failure(exc, CommitState.UNKNOWN)
        if matched is not None:
            return _success_from_stored(matched)

    candidate = _build_candidate(
        request,
        received_at=received_at,
        payload_digest=payload_digest,
        payload_set_digest=payload_set_digest,
        request_digest=request_digest,
        scope=scope,
        key_digest=key_digest,
        dependencies=dependencies,
    )
    _write_candidate_metadata(staging, candidate, dependencies)
    _validate_candidate_at(staging.item_path, candidate)
    committed = _commit_candidate(staging, candidate, dependencies)
    if isinstance(committed, FailureResult):
        return committed
    return _new_success(committed, candidate, staging, dependencies)


def _run_capture_text(
    request: CaptureTextRequest,
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
    dependencies: _CaptureDependencies,
) -> CaptureTextOperationResult:
    if not isinstance(request, CaptureTextRequest):
        return _failure(
            PublicErrorCode.INVALID_INPUT,
            CommitState.NOT_COMMITTED,
        )
    try:
        received_at = _sample_time(dependencies)
        local_config, capture_root = _load_capture_environment(
            config_path=config_path,
            path_policy=path_policy,
        )
    except ConfigLoadError as exc:
        return _failure(exc.code, CommitState.NOT_COMMITTED)
    except _InitFailure as exc:
        return FailureResult(
            error=exc.error,
            commit_state=CommitState.NOT_COMMITTED,
        )
    except (OSError, TypeError, ValueError):
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            CommitState.NOT_COMMITTED,
        )

    staging: _CaptureStaging | None = None
    try:
        staging = _create_capture_staging(
            capture_root,
            durability=dependencies.durability,
            uuid_factory=dependencies.staging_uuid_factory,
        )
        chunk_size = min(
            DEFAULT_CHUNK_SIZE,
            local_config.capture.inline_text_threshold_bytes,
        )
        try:
            payload_digest = dependencies.durability.write_new_utf8_file_durable(
                staging.payload_path,
                request.text,
                maximum_bytes=local_config.capture.max_text_version_bytes,
                chunk_size=chunk_size,
            )
        except DurabilityError as exc:
            raise _StoreIoFailure(
                stage=exc.stage.value,
                cause_code=CauseCode.PAYLOAD_WRITE_FAILED,
            ) from exc
        payload_entry = PayloadSetEntry(
            ordinal=0,
            role="primary",
            kind="text",
            media_type="text/plain; charset=utf-8",
            byte_size=payload_digest.byte_size,
            sha256=payload_digest.sha256,
        )
        payload_set_digest = payload_set_sha256((payload_entry,))
        user_intent = request.user_intent
        if not isinstance(user_intent, UserIntent):
            raise TypeError("normalized user_intent must be UserIntent")
        fingerprint = RequestFingerprint(
            operation="capture_text",
            payload_set_sha256=payload_set_digest,
            channel=request.channel,
            payload_metadata=(PayloadMetadata(ordinal=0),),
            user_intent=user_intent,
        )
        request_digest = request_fingerprint_sha256(fingerprint)
        scope: str | None = None
        key_digest: str | None = None
        if request.idempotency_key is not None:
            scope = canonical_idempotency_scope(request.channel, "capture_text")
            key_digest = idempotency_key_sha256(request.idempotency_key)

        locked_result: CaptureTextOperationResult | None = None
        try:
            with dependencies.lock_factory(capture_root):
                locked_result = _capture_while_locked(
                    request,
                    staging=staging,
                    received_at=received_at,
                    payload_digest=payload_digest,
                    payload_set_digest=payload_set_digest,
                    request_digest=request_digest,
                    scope=scope,
                    key_digest=key_digest,
                    dependencies=dependencies,
                )
            if locked_result is None:
                raise _StoreIoFailure(stage="lock-release")
            return locked_result
        except CaptureWriteLockError as exc:
            if locked_result is not None:
                return locked_result
            return FailureResult(
                error=exc.to_operation_error(),
                commit_state=CommitState.NOT_COMMITTED,
            )
    except ByteLimitExceeded as exc:
        return _failure(
            PublicErrorCode.TEXT_TOO_LARGE,
            CommitState.NOT_COMMITTED,
            details={
                "maximum_bytes": exc.maximum_bytes,
                "observed_bytes": exc.byte_size,
            },
        )
    except InvalidTextInputError:
        return _failure(
            PublicErrorCode.INVALID_INPUT,
            CommitState.NOT_COMMITTED,
        )
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.NOT_COMMITTED)
    except _StoreIoFailure as exc:
        return _io_failure(exc, CommitState.NOT_COMMITTED)
    except DurabilityError as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            CommitState.NOT_COMMITTED,
            details={"stage": exc.stage.value},
        )
    except DestinationAlreadyExistsError:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            CommitState.NOT_COMMITTED,
        )
    except (TypeError, ValueError):
        return _failure(
            PublicErrorCode.INVALID_INPUT,
            CommitState.NOT_COMMITTED,
        )
    except OSError:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            CommitState.NOT_COMMITTED,
        )
    finally:
        if staging is not None:
            _cleanup_capture_staging(
                staging,
                durability=dependencies.durability,
            )


def capture_text(
    request: CaptureTextRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
) -> CaptureTextOperationResult:
    """Save one new text Capture through the complete C3 T0-T9 transaction."""

    return _run_capture_text(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_CaptureDependencies(),
    )


def _capture_text_with_dependencies(
    request: CaptureTextRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
    dependencies: _CaptureDependencies,
) -> CaptureTextOperationResult:
    """Internal deterministic/fault-injection entry point for test support."""

    if not isinstance(dependencies, _CaptureDependencies):
        raise TypeError("dependencies must be _CaptureDependencies")
    return _run_capture_text(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


__all__ = ["CaptureTextOperationResult", "capture_text"]
