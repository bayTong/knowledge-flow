"""Governed public capture operations for the local Capture Store."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
import codecs
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import hmac
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import BinaryIO, TypeAlias, cast
from uuid import UUID

from .codec import (
    CAPTURE_EVENT_SCHEMA_V1,
    CaptureEventReferenceError,
    decode_capture_list_cursor,
    dump_capture_event,
    dump_capture_state,
    encode_capture_list_cursor,
    load_capture_event,
    load_capture_state,
    load_envelope,
    load_restricted_yaml,
    parse_restricted_yaml,
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
    AppendCaptureVersionResult,
    CauseCode,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
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
from .manifest import CaptureStoreManifest
from .models import (
    AppendCaptureVersionRequest,
    CaptureItemState,
    CaptureListItem,
    CaptureReadMetadata,
    CaptureTextRequest,
    ChannelMetadata,
    DigestResult,
    GetCaptureRequest,
    ListCapturesRequest,
    PayloadMetadata,
    PayloadSetEntry,
    RequestFingerprint,
    UserIntent,
    canonical_idempotency_scope,
    format_utc_milliseconds,
)
from .paths import PathPolicy, PathPolicyError
from .store import (
    _AppendStaging,
    _CommittedCaptureVersion,
    _CaptureVersionChain,
    _CaptureVersionChainError,
    _CaptureStaging,
    _InitFailure,
    _build_capture_version_chain,
    _cleanup_append_staging,
    _cleanup_capture_staging,
    _create_append_staging,
    _create_capture_staging,
    _inspect_store,
    _parse_capture_version_directory_name,
    _recover_abandoned_capture_staging,
    _rebuild_capture_read_state,
    _warnings_for_capture_version_chain,
)


CaptureTextOperationResult: TypeAlias = CommittedWriteResult | FailureResult
AppendCaptureVersionOperationResult: TypeAlias = (
    AppendCaptureVersionResult | FailureResult
)
GetCaptureOperationResult: TypeAlias = GetCaptureResult | FailureResult
ListCapturesOperationResult: TypeAlias = ListCapturesResult | FailureResult

_ACTOR = {"type": "user", "actor_id": "local-user"}
_ENVELOPE_MAXIMUM_BYTES = 1024 * 1024
_EVENT_MAXIMUM_BYTES = 256 * 1024
_PROJECTION_MAXIMUM_BYTES = 1024 * 1024
_CAPTURE_PREVIEW_CODE_POINTS = 160
_CAPTURE_PREVIEW_MAXIMUM_BYTES = _CAPTURE_PREVIEW_CODE_POINTS * 4
_YEAR_PATTERN = re.compile(r"[0-9]{4}\Z")
_MONTH_PATTERN = re.compile(r"(?:0[1-9]|1[0-2])\Z")
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_LockFactory = Callable[[Path], CaptureWriteLock]
_UtcNow = Callable[[], datetime]
_TypedIdFactory = Callable[[], str]
_UuidFactory = Callable[[], UUID]
_FaultHook = Callable[[], None]
_ReplaceFile = Callable[[Path, Path], None]
_BodySpoolFactory = Callable[[Path], BinaryIO]
_PreviewOpener = Callable[[Path], BinaryIO]


class _CaptureFaultPoint(StrEnum):
    """Internal-only C3/C5/C6 fault points; never accepted publicly."""

    AFTER_LOCK_ACQUIRED = "after_lock_acquired"
    AFTER_PAYLOAD_WRITTEN = "after_payload_written"
    AFTER_PAYLOAD_FLUSHED = "after_payload_flushed"
    AFTER_ENVELOPE_WRITTEN = "after_envelope_written"
    AFTER_READBACK_VERIFIED = "after_readback_verified"
    AFTER_VERSION_RENAMED = "after_version_renamed"
    AFTER_EVENT_APPENDED = "after_event_appended"
    AFTER_PROJECTION_REPLACED = "after_projection_replaced"
    BEFORE_RECEIPT_RETURNED = "before_receipt_returned"
    BEFORE_EVENT_WRITE = "before_event_write"
    BEFORE_APPEND_EVENT_PREFLIGHT = "before_append_event_preflight"
    BEFORE_PROJECTION_REPLACE = "before_projection_replace"
    BEFORE_APPEND_VERSION_RENAME = "before_append_version_rename"
    AFTER_APPEND_VERSION_RENAME = "after_append_version_rename"
    BEFORE_APPEND_EVENT_RENAME = "before_append_event_rename"
    AFTER_APPEND_EVENT_RENAME = "after_append_event_rename"
    AFTER_APPEND_FINAL_READBACK = "after_append_final_readback"
    BEFORE_APPEND_PROJECTION_REPLACE = "before_append_projection_replace"
    BEFORE_APPEND_RECEIPT_RETURNED = "before_append_receipt_returned"


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


def _default_body_spool_factory(capture_root: Path) -> BinaryIO:
    """Create a delete-on-close disk spool beside, never inside, the Store."""

    spool_parent = capture_root.parent
    if ntpath.normcase(str(spool_parent)) == ntpath.normcase(str(capture_root)):
        raise OSError("Capture Store root has no external spool parent")
    return cast(
        BinaryIO,
        tempfile.TemporaryFile(
            mode="w+b",
            prefix=".knowledgeflow-capture-read-",
            dir=spool_parent,
        ),
    )


@dataclass(frozen=True, slots=True)
class _GetCaptureDependencies:
    spool_factory: _BodySpoolFactory = field(
        default=_default_body_spool_factory,
        repr=False,
        compare=False,
    )


def _default_preview_opener(path: Path) -> BinaryIO:
    return cast(BinaryIO, path.open("rb"))


@dataclass(frozen=True, slots=True)
class _ListCapturesDependencies:
    preview_opener: _PreviewOpener = field(
        default=_default_preview_opener,
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


@dataclass(frozen=True, slots=True)
class _AppendCandidate:
    capture_id: str
    event_id: str
    previous_version: int
    version: int
    envelope: Mapping[str, object]
    envelope_bytes: bytes
    previous_envelope: Mapping[str, object]
    event: Mapping[str, object]
    event_bytes: bytes
    payload_digest: DigestResult
    payload_set_sha256: str


@dataclass(frozen=True, slots=True)
class _AppendRequestIdentity:
    scope: str
    key_sha256: str
    request_fingerprint_sha256: str


@dataclass(frozen=True, slots=True)
class _AppendTailObservation:
    disk_chain: _DiskCaptureVersionChain
    version: int
    envelope_source: bytes | None
    identity: _AppendRequestIdentity | None

    @property
    def version_path(self) -> Path:
        path = self.disk_chain.version_paths.get(self.version)
        if path is None:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        return path


@dataclass(frozen=True, slots=True)
class _AppendCommittedMatch:
    disk_chain: _DiskCaptureVersionChain
    committed: _CommittedCaptureVersion


@dataclass(frozen=True, slots=True)
class _AppendStoreScan:
    chains: tuple[_DiskCaptureVersionChain, ...]
    committed_match: _AppendCommittedMatch | None
    tail_match: _AppendTailObservation | None
    tails: tuple[_AppendTailObservation, ...]


class _AppendSourceEvidence(StrEnum):
    ORIGINAL = "original"
    ABSENT = "absent"
    OTHER = "other"
    UNPROVABLE = "unprovable"


class _AppendTargetEvidence(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"
    UNPROVABLE = "unprovable"


class _AppendTargetAttestation(StrEnum):
    NOT_RUN = "not-run"
    MATCH = "match"
    INVALID = "invalid"
    UNPROVABLE = "unprovable"


class _AppendCommitDisposition(StrEnum):
    NOT_COMMITTED = "not-committed"
    COMMITTED = "committed"
    UNKNOWN = "unknown"
    INTEGRITY_UNKNOWN = "integrity-unknown"


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


class _UnsupportedMachineSchema(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _LocatedCaptureItem:
    item_path: Path
    year: str
    month: str


@dataclass(frozen=True, slots=True)
class _DiskCaptureVersionChain:
    item: _LocatedCaptureItem
    chain: _CaptureVersionChain
    version_paths: Mapping[int, Path]


@dataclass(frozen=True, slots=True)
class _PayloadFile:
    metadata: Mapping[str, object]
    path: Path
    path_stat: os.stat_result = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _CaptureListCandidate:
    disk_chain: _DiskCaptureVersionChain
    captured_at: str
    updated_at: str
    routing_status: str
    trust_status: str
    envelope_sha256: str
    warnings: tuple[OperationWarning, ...]

    @property
    def capture_id(self) -> str:
        return self.disk_chain.chain.capture_id

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.captured_at, self.capture_id


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


def _read_failure(
    code: PublicErrorCode,
    *,
    retryable: bool = False,
    cause_code: CauseCode | None = None,
    details: Mapping[str, object] | None = None,
) -> FailureResult:
    """Build a read failure, which deliberately has no commit state."""

    return FailureResult(
        error=OperationError(
            code=code,
            retryable=retryable,
            cause_code=cause_code,
            details={} if details is None else details,
        )
    )


def _read_integrity_failure(failure: _IntegrityFailure) -> FailureResult:
    return _read_failure(
        PublicErrorCode.INTEGRITY_CHECK_FAILED,
        cause_code=failure.cause_code,
    )


def _read_io_failure(failure: _StoreIoFailure) -> FailureResult:
    return _read_failure(
        PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
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


def _machine_identity_is_unsupported(
    value: object,
    *,
    expected_schema: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    schema_name = value.get("schema")
    schema_version = value.get("schema_version")
    return (
        type(schema_name) is str
        and schema_name != expected_schema
    ) or (
        type(schema_version) is int
        and schema_version != 1
    )


def _check_machine_identity(
    source: bytes,
    *,
    expected_schema: str,
    invalid_cause: CauseCode,
) -> None:
    try:
        value = parse_restricted_yaml(source)
    except (TypeError, ValueError) as exc:
        raise _IntegrityFailure(invalid_cause) from exc
    if _machine_identity_is_unsupported(
        value,
        expected_schema=expected_schema,
    ):
        raise _UnsupportedMachineSchema


def _immutable_directory_stat(
    path: Path,
    *,
    missing_cause: CauseCode,
    invalid_cause: CauseCode,
    stage: str,
) -> os.stat_result:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _StoreIoFailure(stage=stage) from exc
    if path_stat is None:
        raise _IntegrityFailure(missing_cause)
    if not stat.S_ISDIR(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise _IntegrityFailure(invalid_cause)
    return path_stat


def _immutable_directory_entries(
    path: Path,
    *,
    missing_cause: CauseCode,
    invalid_cause: CauseCode,
    stage: str,
) -> tuple[Path, ...]:
    _immutable_directory_stat(
        path,
        missing_cause=missing_cause,
        invalid_cause=invalid_cause,
        stage=stage,
    )
    try:
        return tuple(sorted(path.iterdir(), key=lambda item: item.name))
    except OSError as exc:
        raise _StoreIoFailure(stage=stage) from exc


def _locate_capture_item(
    capture_root: Path,
    capture_id: str,
) -> _LocatedCaptureItem | None:
    """Locate exactly one canonical Item without trusting a shard or symlink."""

    matches: list[_LocatedCaptureItem] = []
    items_root = capture_root / "items"
    for year_path in _directory_entries(items_root, stage="item-locate"):
        if _YEAR_PATTERN.fullmatch(year_path.name) is None:
            continue
        _immutable_directory_stat(
            year_path,
            missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            stage="item-locate",
        )
        for month_path in _immutable_directory_entries(
            year_path,
            missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            stage="item-locate",
        ):
            if _MONTH_PATTERN.fullmatch(month_path.name) is None:
                continue
            _immutable_directory_stat(
                month_path,
                missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                stage="item-locate",
            )
            for item_path in _immutable_directory_entries(
                month_path,
                missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                stage="item-locate",
            ):
                if ntpath.normcase(item_path.name) != ntpath.normcase(capture_id):
                    continue
                if item_path.name != capture_id:
                    raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
                _immutable_directory_stat(
                    item_path,
                    missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                    invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                    stage="item-locate",
                )
                matches.append(
                    _LocatedCaptureItem(
                        item_path=item_path,
                        year=year_path.name,
                        month=month_path.name,
                    )
                )
    if len(matches) > 1:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    return matches[0] if matches else None


def _locate_capture_items(capture_root: Path) -> tuple[_LocatedCaptureItem, ...]:
    """Enumerate every canonical Item and reject duplicate Capture identities."""

    located: list[_LocatedCaptureItem] = []
    capture_ids: set[str] = set()
    items_root = capture_root / "items"
    for year_path in _directory_entries(items_root, stage="item-list"):
        if _YEAR_PATTERN.fullmatch(year_path.name) is None:
            continue
        _immutable_directory_stat(
            year_path,
            missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            stage="item-list",
        )
        for month_path in _immutable_directory_entries(
            year_path,
            missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
            stage="item-list",
        ):
            if _MONTH_PATTERN.fullmatch(month_path.name) is None:
                continue
            _immutable_directory_stat(
                month_path,
                missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                stage="item-list",
            )
            for item_path in _immutable_directory_entries(
                month_path,
                missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                stage="item-list",
            ):
                if not ntpath.normcase(item_path.name).startswith("cap_"):
                    continue
                try:
                    validate_typed_id(item_path.name, IdKind.CAPTURE)
                except (TypeError, ValueError) as exc:
                    raise _IntegrityFailure(
                        CauseCode.EVENT_REFERENCE_MISMATCH
                    ) from exc
                _immutable_directory_stat(
                    item_path,
                    missing_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                    invalid_cause=CauseCode.EVENT_REFERENCE_MISMATCH,
                    stage="item-list",
                )
                identity = ntpath.normcase(item_path.name)
                if identity in capture_ids:
                    raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
                capture_ids.add(identity)
                located.append(
                    _LocatedCaptureItem(
                        item_path=item_path,
                        year=year_path.name,
                        month=month_path.name,
                    )
                )
    return tuple(located)


def _load_event_without_references(path: Path) -> Mapping[str, object]:
    source = _read_regular_bytes(
        path,
        maximum_bytes=_EVENT_MAXIMUM_BYTES,
        missing_cause=CauseCode.EVENT_MISSING,
        invalid_cause=CauseCode.EVENT_SCHEMA_INVALID,
    )
    _check_machine_identity(
        source,
        expected_schema="knowledgeflow.capture-event",
        invalid_cause=CauseCode.EVENT_SCHEMA_INVALID,
    )
    try:
        event = load_restricted_yaml(
            source,
            CAPTURE_EVENT_SCHEMA_V1,
            require_canonical=True,
        )
    except (TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID) from exc
    if not isinstance(event, Mapping):
        raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID)
    return event


def _load_committed_envelope(path: Path) -> Mapping[str, object]:
    source = _read_regular_bytes(
        path,
        maximum_bytes=_ENVELOPE_MAXIMUM_BYTES,
        missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
    )
    _check_machine_identity(
        source,
        expected_schema="knowledgeflow.capture-envelope",
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
    )
    try:
        envelope = load_envelope(source, require_canonical=True)
    except (TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH) from exc
    if not verify_envelope(envelope):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    return envelope


def _payload_relative_parts(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    candidate = PurePosixPath(value)
    parts = candidate.parts
    drive, _tail = ntpath.splitdrive(value)
    if (
        drive
        or candidate.is_absolute()
        or candidate.as_posix() != value
        or len(parts) < 2
        or parts[0] != "payloads"
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or part.endswith((" ", "."))
            for part in parts
        )
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    return parts


def _payload_files(
    version_path: Path,
    envelope: Mapping[str, object],
) -> tuple[_PayloadFile, ...]:
    entries = _payload_entries(envelope)
    try:
        expected_payload_set = payload_set_sha256(entries)
        stored_payload_set = envelope["payload_set_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH) from exc
    if type(stored_payload_set) is not str or not hmac.compare_digest(
        expected_payload_set,
        stored_payload_set,
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)

    result: list[_PayloadFile] = []
    path_keys: set[str] = set()
    primary_count = 0
    for metadata in _payload_mappings(envelope):
        parts = _payload_relative_parts(metadata.get("path"))
        key = ntpath.normcase(ntpath.join(*parts))
        if key in path_keys:
            raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
        path_keys.add(key)

        is_primary = metadata.get("ordinal") == 0 and metadata.get("role") == "primary"
        if is_primary:
            primary_count += 1
            if (
                parts != ("payloads", "primary.txt")
                or metadata.get("kind") != "text"
                or metadata.get("media_type") != "text/plain; charset=utf-8"
                or metadata.get("encoding") != "utf-8"
                or metadata.get("fidelity") != "channel-exact"
                or metadata.get("original_name") is not None
            ):
                raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)

        parent = version_path
        for part in parts[:-1]:
            parent = parent / part
            _immutable_directory_stat(
                parent,
                missing_cause=CauseCode.PAYLOAD_HASH_MISMATCH,
                invalid_cause=CauseCode.PAYLOAD_HASH_MISMATCH,
                stage="payload-read",
            )
        payload_path = version_path.joinpath(*parts)
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
        expected_size = metadata.get("byte_size")
        if type(expected_size) is not int or path_stat.st_size != expected_size:
            raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)
        result.append(
            _PayloadFile(
                metadata=metadata,
                path=payload_path,
                path_stat=path_stat,
            )
        )
    if primary_count != 1:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    return tuple(result)


def _load_disk_capture_version_chain(
    item: _LocatedCaptureItem,
) -> _DiskCaptureVersionChain:
    item_path = item.item_path
    version_entries = _immutable_directory_entries(
        item_path / "versions",
        missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        stage="version-read",
    )
    version_paths: dict[int, Path] = {}
    version_names: list[str] = []
    for version_path in version_entries:
        try:
            version = _parse_capture_version_directory_name(version_path.name)
        except _CaptureVersionChainError as exc:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH) from exc
        _immutable_directory_stat(
            version_path,
            missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            stage="version-read",
        )
        if version in version_paths:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        version_paths[version] = version_path
        version_names.append(version_path.name)

    event_entries = _immutable_directory_entries(
        item_path / "events",
        missing_cause=CauseCode.EVENT_MISSING,
        invalid_cause=CauseCode.EVENT_SCHEMA_INVALID,
        stage="event-read",
    )
    events: list[Mapping[str, object]] = []
    for event_path in event_entries:
        if event_path.suffix != ".yaml":
            raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID)
        try:
            validate_typed_id(event_path.stem, IdKind.EVENT)
        except (TypeError, ValueError) as exc:
            raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID) from exc
        event = _load_event_without_references(event_path)
        if event.get("event_id") != event_path.stem:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        events.append(event)
    if not events:
        raise _IntegrityFailure(CauseCode.EVENT_MISSING)

    envelopes: dict[int, Mapping[str, object]] = {}
    for event in events:
        raw_event_version = event.get("version")
        if type(raw_event_version) is not int or raw_event_version in envelopes:
            continue
        event_version_path = version_paths.get(raw_event_version)
        if event_version_path is None:
            continue
        envelopes[raw_event_version] = _load_committed_envelope(
            event_version_path / "envelope.yaml"
        )

    try:
        chain = _build_capture_version_chain(
            capture_id=item.item_path.name,
            version_directory_names=version_names,
            envelopes_by_version=envelopes,
            events=events,
        )
    except _CaptureVersionChainError as exc:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH) from exc

    first_received_at = chain.versions[0].envelope.get("received_at")
    if type(first_received_at) is not str or (
        first_received_at[:4] != item.year
        or first_received_at[5:7] != item.month
    ):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)

    for committed in chain.versions:
        committed_version_path = version_paths.get(committed.version)
        if committed_version_path is None:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        _payload_files(committed_version_path, committed.envelope)

    return _DiskCaptureVersionChain(
        item=item,
        chain=chain,
        version_paths=version_paths,
    )


def _write_all_to_spool(spool: BinaryIO, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        try:
            written = spool.write(value[offset:])
        except Exception as exc:
            raise _StoreIoFailure(stage="body-spool") from exc
        if type(written) is not int or not 1 <= written <= len(value) - offset:
            raise _StoreIoFailure(stage="body-spool")
        offset += written


def _verify_target_payloads(
    disk_chain: _DiskCaptureVersionChain,
    *,
    version: int,
    spool: BinaryIO,
) -> Mapping[str, object]:
    committed = disk_chain.chain.version(version)
    version_path = disk_chain.version_paths.get(version)
    if committed is None or version_path is None:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    payloads = _payload_files(version_path, committed.envelope)
    primary: Mapping[str, object] | None = None

    for payload in payloads:
        is_primary = (
            payload.metadata.get("ordinal") == 0
            and payload.metadata.get("role") == "primary"
        )
        digest = hashlib.sha256()
        byte_size = 0
        prefix = bytearray()
        decoder = (
            codecs.getincrementaldecoder("utf-8")("strict")
            if is_primary
            else None
        )
        try:
            with payload.path.open("rb") as stream:
                handle_stat = os.fstat(stream.fileno())
                if not (
                    stat.S_ISREG(handle_stat.st_mode)
                    and handle_stat.st_dev == payload.path_stat.st_dev
                    and handle_stat.st_ino == payload.path_stat.st_ino
                    and handle_stat.st_mode == payload.path_stat.st_mode
                ):
                    raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                while True:
                    chunk = stream.read(DEFAULT_CHUNK_SIZE)
                    if type(chunk) is not bytes:
                        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                    if not chunk:
                        break
                    byte_size += len(chunk)
                    digest.update(chunk)
                    if is_primary:
                        if len(prefix) < 3:
                            prefix.extend(chunk[: 3 - len(prefix)])
                        try:
                            assert decoder is not None
                            decoder.decode(chunk, final=False)
                        except UnicodeDecodeError as exc:
                            raise _IntegrityFailure(
                                CauseCode.PAYLOAD_HASH_MISMATCH
                            ) from exc
                        _write_all_to_spool(spool, chunk)
        except (_IntegrityFailure, _StoreIoFailure):
            raise
        except OSError as exc:
            raise _StoreIoFailure(
                stage="payload-read",
                cause_code=CauseCode.PAYLOAD_READ_FAILED,
            ) from exc
        if not _same_identity(payload.path, payload.path_stat):
            raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
        expected_size = payload.metadata.get("byte_size")
        if type(expected_size) is not int or byte_size != expected_size:
            raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)
        actual_sha256 = "sha256:" + digest.hexdigest()
        expected_sha256 = payload.metadata.get("sha256")
        if type(expected_sha256) is not str or not hmac.compare_digest(
            actual_sha256,
            expected_sha256,
        ):
            raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
        if is_primary:
            if byte_size == 0 or bytes(prefix).startswith(b"\xef\xbb\xbf"):
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
            try:
                assert decoder is not None
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH) from exc
            primary = payload.metadata

    if primary is None:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    try:
        spool.flush()
        spool.seek(0)
    except Exception as exc:
        raise _StoreIoFailure(stage="body-spool") from exc
    return primary


def _projection_warning_for_read(
    disk_chain: _DiskCaptureVersionChain,
) -> tuple[OperationWarning, ...]:
    capture_id = disk_chain.chain.capture_id
    projection_path = disk_chain.item.item_path / "capture.yaml"
    try:
        path_stat = _lstat_if_present(projection_path)
    except OSError:
        path_stat = None
    if path_stat is not None and stat.S_ISREG(path_stat.st_mode) and not (
        _is_reparse_point(path_stat)
    ):
        try:
            source = _read_regular_bytes(
                projection_path,
                maximum_bytes=_PROJECTION_MAXIMUM_BYTES,
                missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
                invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            )
            _check_machine_identity(
                source,
                expected_schema="knowledgeflow.capture-state",
                invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            )
            current = disk_chain.chain.current
            previous = disk_chain.chain.version(current.version - 1)
            load_capture_state(
                source,
                envelope=current.envelope,
                current_event=(current.event if current.version > 1 else None),
                previous_envelope=(
                    previous.envelope if previous is not None else None
                ),
                require_canonical=True,
            )
            return ()
        except _UnsupportedMachineSchema:
            raise
        except (_IntegrityFailure, _StoreIoFailure, TypeError, ValueError):
            pass
    return (
        OperationWarning(
            code=WarningCode.PROJECTION_NEEDS_REBUILD,
            details={"capture_id": capture_id},
        ),
    )


def _capture_list_candidate(
    disk_chain: _DiskCaptureVersionChain,
) -> _CaptureListCandidate:
    read_state = _rebuild_capture_read_state(disk_chain.chain)
    return _CaptureListCandidate(
        disk_chain=disk_chain,
        captured_at=read_state.captured_at,
        updated_at=read_state.updated_at,
        routing_status=read_state.routing_status,
        trust_status=read_state.trust_status,
        envelope_sha256=read_state.current_envelope_sha256,
        warnings=(
            _warnings_for_capture_version_chain(disk_chain.chain)
            + _projection_warning_for_read(disk_chain)
        ),
    )


def _read_capture_preview(
    candidate: _CaptureListCandidate,
    *,
    dependencies: _ListCapturesDependencies,
) -> str:
    current = candidate.disk_chain.chain.current
    version_path = candidate.disk_chain.version_paths.get(current.version)
    if version_path is None:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    payloads = _payload_files(version_path, current.envelope)
    primary = next(
        (
            payload
            for payload in payloads
            if payload.metadata.get("ordinal") == 0
            and payload.metadata.get("role") == "primary"
        ),
        None,
    )
    if primary is None:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)

    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    decoded: list[str] = []
    decoded_code_points = 0
    prefix = bytearray()
    remaining = _CAPTURE_PREVIEW_MAXIMUM_BYTES
    reached_eof = False
    try:
        with dependencies.preview_opener(primary.path) as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == primary.path_stat.st_dev
                and handle_stat.st_ino == primary.path_stat.st_ino
                and handle_stat.st_mode == primary.path_stat.st_mode
            ):
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
            while remaining:
                chunk = stream.read(min(64, remaining))
                if type(chunk) is not bytes:
                    raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                if not chunk:
                    reached_eof = True
                    break
                if len(chunk) > remaining:
                    raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                remaining -= len(chunk)
                if len(prefix) < 3:
                    prefix.extend(chunk[: 3 - len(prefix)])
                for value in chunk:
                    decoded_chunk = decoder.decode(bytes((value,)), final=False)
                    if decoded_chunk:
                        decoded.append(decoded_chunk)
                        decoded_code_points += len(decoded_chunk)
                    if decoded_code_points >= _CAPTURE_PREVIEW_CODE_POINTS:
                        break
                if decoded_code_points >= _CAPTURE_PREVIEW_CODE_POINTS:
                    break
    except (_IntegrityFailure, _StoreIoFailure):
        raise
    except UnicodeDecodeError as exc:
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH) from exc
    except Exception as exc:
        raise _StoreIoFailure(
            stage="payload-read",
            cause_code=CauseCode.PAYLOAD_READ_FAILED,
        ) from exc

    if not _same_identity(primary.path, primary.path_stat):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    if not prefix or bytes(prefix).startswith(b"\xef\xbb\xbf"):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    if reached_eof:
        try:
            decoded.append(decoder.decode(b"", final=True))
        except UnicodeDecodeError as exc:
            raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH) from exc
    preview = "".join(decoded)
    if len(preview) < _CAPTURE_PREVIEW_CODE_POINTS and not reached_eof:
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    return preview[:_CAPTURE_PREVIEW_CODE_POINTS]


def _capture_list_item(
    candidate: _CaptureListCandidate,
    *,
    dependencies: _ListCapturesDependencies,
) -> CaptureListItem:
    return CaptureListItem(
        capture_id=candidate.capture_id,
        current_version=candidate.disk_chain.chain.current_version,
        captured_at=candidate.captured_at,
        updated_at=candidate.updated_at,
        preview=_read_capture_preview(candidate, dependencies=dependencies),
        routing_status=candidate.routing_status,
        trust_status=candidate.trust_status,
        envelope_sha256=candidate.envelope_sha256,
    )


def _capture_read_metadata(
    disk_chain: _DiskCaptureVersionChain,
    *,
    version: int,
    primary: Mapping[str, object],
) -> CaptureReadMetadata:
    committed = disk_chain.chain.version(version)
    if committed is None:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    envelope = committed.envelope
    channel = envelope.get("channel")
    user_intent = envelope.get("user_intent")
    if not isinstance(channel, Mapping) or not isinstance(user_intent, Mapping):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    fidelity = primary.get("fidelity")
    media_type = primary.get("media_type")
    encoding = primary.get("encoding")
    byte_size = primary.get("byte_size")
    primary_sha256 = primary.get("sha256")
    payload_set = envelope.get("payload_set_sha256")
    envelope_hash = envelope.get("envelope_sha256")
    captured_at = envelope.get("captured_at")
    channel_type = channel.get("type")
    channel_instance = channel.get("instance_id")
    external_ref = channel.get("external_ref")
    source_created_at = channel.get("source_created_at")
    target_kb_id = user_intent.get("target_kb_id")
    processing_mode = user_intent.get("processing_mode")
    requested_new_kb_name = user_intent.get("requested_new_kb_name")
    required_strings = (
        fidelity,
        media_type,
        encoding,
        primary_sha256,
        payload_set,
        envelope_hash,
        captured_at,
        channel_type,
        channel_instance,
    )
    optional_strings = (
        external_ref,
        source_created_at,
        target_kb_id,
        processing_mode,
        requested_new_kb_name,
    )
    if (
        not all(type(value) is str for value in required_strings)
        or type(byte_size) is not int
        or not all(value is None or type(value) is str for value in optional_strings)
    ):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    try:
        return CaptureReadMetadata(
            capture_id=disk_chain.chain.capture_id,
            version=version,
            current_version=disk_chain.chain.current_version,
            fidelity=cast(str, fidelity),
            media_type=cast(str, media_type),
            encoding=cast(str, encoding),
            byte_size=byte_size,
            primary_payload_sha256=cast(str, primary_sha256),
            payload_set_sha256=cast(str, payload_set),
            envelope_sha256=cast(str, envelope_hash),
            captured_at=cast(str, captured_at),
            channel=ChannelMetadata(
                type=cast(str, channel_type),
                instance_id=cast(str, channel_instance),
                external_ref=cast(str | None, external_ref),
                source_created_at=cast(str | None, source_created_at),
            ),
            user_intent=UserIntent(
                target_kb_id=cast(str | None, target_kb_id),
                processing_mode=cast(str | None, processing_mode),
                requested_new_kb_name=cast(str | None, requested_new_kb_name),
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH) from exc


def _emit_verified_body(
    spool: BinaryIO,
    sink: object,
    *,
    expected_bytes: int,
) -> bool:
    emitted = 0
    writer = getattr(sink, "write", None)
    if not callable(writer):
        return False
    try:
        while True:
            chunk = spool.read(DEFAULT_CHUNK_SIZE)
            if type(chunk) is not bytes:
                return False
            if not chunk:
                break
            offset = 0
            while offset < len(chunk):
                written = writer(chunk[offset:])
                if type(written) is not int or not 1 <= written <= len(chunk) - offset:
                    return False
                offset += written
                emitted += written
    except Exception:
        return False
    return emitted == expected_bytes


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


def _build_append_candidate(
    request: AppendCaptureVersionRequest,
    *,
    previous_envelope: Mapping[str, object],
    received_at: str,
    payload_digest: DigestResult,
    payload_set_digest: str,
    request_digest: str,
    dependencies: _CaptureDependencies,
) -> _AppendCandidate:
    """Preseal one append Envelope/Event pair without touching final paths."""

    if not isinstance(request, AppendCaptureVersionRequest):
        raise TypeError("request must be AppendCaptureVersionRequest")
    if not isinstance(previous_envelope, Mapping) or not verify_envelope(
        previous_envelope
    ):
        raise ValueError("previous_envelope must be a verified Envelope")
    if (
        previous_envelope.get("capture_id") != request.capture_id
        or previous_envelope.get("version") != request.expected_current_version
    ):
        raise ValueError("previous_envelope does not match the append request")
    intent = request.user_intent
    if not isinstance(intent, UserIntent):
        raise TypeError("AppendCaptureVersionRequest.user_intent was not normalized")

    event_id = _typed_id(dependencies.event_id_factory, IdKind.EVENT)
    version = request.expected_current_version + 1
    captured_at = _sample_time(dependencies)
    scope = canonical_idempotency_scope(
        request.channel,
        "append_capture_version",
    )
    key_digest = idempotency_key_sha256(request.idempotency_key)
    envelope_without_hash: dict[str, object] = {
        "schema": "knowledgeflow.capture-envelope",
        "schema_version": 1,
        "capture_id": request.capture_id,
        "event_id": event_id,
        "version": version,
        "previous_version": request.expected_current_version,
        "received_at": received_at,
        "captured_at": captured_at,
        "actor": dict(_ACTOR),
        "channel": request.channel.as_canonical_mapping(),
        "idempotency": {
            "scope": scope,
            "key_sha256": key_digest,
            "request_fingerprint_sha256": request_digest,
        },
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
    event: dict[str, object] = {
        "schema": "knowledgeflow.capture-event",
        "schema_version": 1,
        "event_id": event_id,
        "event_type": "capture.version-appended",
        "capture_id": request.capture_id,
        "version": version,
        "previous_version": request.expected_current_version,
        "previous_envelope_sha256": previous_envelope["envelope_sha256"],
        "envelope_sha256": sealed.sha256,
        "occurred_at": _sample_time(dependencies),
        "actor": dict(_ACTOR),
    }
    event_bytes = dump_capture_event(
        event,
        envelope=sealed.envelope,
        previous_envelope=previous_envelope,
    )
    return _AppendCandidate(
        capture_id=request.capture_id,
        event_id=event_id,
        previous_version=request.expected_current_version,
        version=version,
        envelope=sealed.envelope,
        envelope_bytes=sealed.yaml_bytes,
        previous_envelope=previous_envelope,
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
    _trigger_fault(_CaptureFaultPoint.AFTER_ENVELOPE_WRITTEN, dependencies)
    _trigger_fault(_CaptureFaultPoint.BEFORE_EVENT_WRITE, dependencies)
    dependencies.durability.write_new_file_durable(
        staging.item_path / "events" / f"{candidate.event_id}.yaml",
        candidate.event_bytes,
        validator=lambda source: _require_exact_event(source, candidate),
    )


def _require_exact_append_envelope(
    source: bytes,
    candidate: _AppendCandidate,
) -> object:
    envelope = load_envelope(source, require_canonical=True)
    if envelope != candidate.envelope or not verify_envelope(envelope):
        raise ValueError("Envelope does not match the append candidate")
    return envelope


def _require_exact_append_event(
    source: bytes,
    candidate: _AppendCandidate,
) -> object:
    event = load_capture_event(
        source,
        envelope=candidate.envelope,
        previous_envelope=candidate.previous_envelope,
        require_canonical=True,
    )
    if event != candidate.event:
        raise ValueError("Event does not match the append candidate")
    return event


def _write_append_candidate_metadata(
    staging: _AppendStaging,
    candidate: _AppendCandidate,
    dependencies: _CaptureDependencies,
) -> None:
    """Durably write and reread the presealed append metadata in staging."""

    if not isinstance(staging, _AppendStaging):
        raise TypeError("staging must be _AppendStaging")
    dependencies.durability.write_new_file_durable(
        staging.version_path / "envelope.yaml",
        candidate.envelope_bytes,
        validator=lambda source: _require_exact_append_envelope(source, candidate),
    )
    _trigger_fault(_CaptureFaultPoint.AFTER_ENVELOPE_WRITTEN, dependencies)
    dependencies.durability.write_new_file_durable(
        staging.event_path(candidate.event_id),
        candidate.event_bytes,
        validator=lambda source: _require_exact_append_event(source, candidate),
    )


def _decidable_append_tail_identity(
    source: bytes,
    *,
    expected_capture_id: str,
    expected_version: int,
    previous_envelope: Mapping[str, object],
) -> _AppendRequestIdentity | None:
    """Return an identity only for one canonical, self-bound append tail.

    Known partial, malformed, noncanonical, anonymous, or mismatched Envelopes
    deliberately return ``None`` and therefore reserve no idempotency key.
    Filesystem I/O uncertainty is handled before this pure byte boundary.
    """

    try:
        envelope = load_envelope(source, require_canonical=True)
        if not verify_envelope(envelope) or not verify_envelope(previous_envelope):
            return None
        if (
            type(expected_version) is not int
            or not 2 <= expected_version <= 999999
            or envelope["capture_id"] != expected_capture_id
            or envelope["version"] != expected_version
            or envelope["previous_version"] != expected_version - 1
            or previous_envelope["capture_id"] != expected_capture_id
            or previous_envelope["version"] != expected_version - 1
        ):
            return None
        identity = envelope["idempotency"]
        if not isinstance(identity, Mapping):
            return None
        scope = identity["scope"]
        key_sha256 = identity["key_sha256"]
        request_sha256 = identity["request_fingerprint_sha256"]
        if (
            type(scope) is not str
            or not scope.endswith(":append_capture_version")
            or type(key_sha256) is not str
            or type(request_sha256) is not str
        ):
            return None
        return _AppendRequestIdentity(
            scope=scope,
            key_sha256=key_sha256,
            request_fingerprint_sha256=request_sha256,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _attest_version_payloads(
    version_path: Path,
    envelope: Mapping[str, object],
) -> tuple[DigestResult, ...]:
    """Fully attest all payload bytes in one already-identified version."""

    payloads = _payload_files(version_path, envelope)
    results: list[DigestResult] = []
    for payload in payloads:
        is_primary = (
            payload.metadata.get("ordinal") == 0
            and payload.metadata.get("role") == "primary"
        )
        decoder = (
            codecs.getincrementaldecoder("utf-8")("strict")
            if is_primary
            else None
        )
        prefix = bytearray()
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with payload.path.open("rb") as stream:
                handle_stat = os.fstat(stream.fileno())
                if not (
                    stat.S_ISREG(handle_stat.st_mode)
                    and handle_stat.st_dev == payload.path_stat.st_dev
                    and handle_stat.st_ino == payload.path_stat.st_ino
                    and handle_stat.st_mode == payload.path_stat.st_mode
                ):
                    raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                while True:
                    chunk = stream.read(DEFAULT_CHUNK_SIZE)
                    if type(chunk) is not bytes:
                        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
                    if not chunk:
                        break
                    byte_size += len(chunk)
                    digest.update(chunk)
                    if is_primary:
                        if len(prefix) < 3:
                            prefix.extend(chunk[: 3 - len(prefix)])
                        try:
                            assert decoder is not None
                            decoder.decode(chunk, final=False)
                        except UnicodeDecodeError as exc:
                            raise _IntegrityFailure(
                                CauseCode.PAYLOAD_HASH_MISMATCH
                            ) from exc
        except _IntegrityFailure:
            raise
        except OSError as exc:
            raise _StoreIoFailure(
                stage="payload-read",
                cause_code=CauseCode.PAYLOAD_READ_FAILED,
            ) from exc
        if not _same_identity(payload.path, payload.path_stat):
            raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
        expected_size = payload.metadata.get("byte_size")
        if type(expected_size) is not int or byte_size != expected_size:
            raise _IntegrityFailure(CauseCode.BYTE_SIZE_MISMATCH)
        actual_sha256 = "sha256:" + digest.hexdigest()
        expected_sha256 = payload.metadata.get("sha256")
        if type(expected_sha256) is not str or not hmac.compare_digest(
            actual_sha256,
            expected_sha256,
        ):
            raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
        if is_primary:
            if byte_size == 0 or bytes(prefix).startswith(b"\xef\xbb\xbf"):
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
            try:
                assert decoder is not None
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH) from exc
        results.append(DigestResult(byte_size=byte_size, sha256=actual_sha256))
    return tuple(results)


def _append_identity_from_envelope(
    envelope: Mapping[str, object],
) -> _AppendRequestIdentity | None:
    identity = envelope.get("idempotency")
    if identity is None:
        return None
    if not isinstance(identity, Mapping):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    scope = identity.get("scope")
    key_sha256 = identity.get("key_sha256")
    request_sha256 = identity.get("request_fingerprint_sha256")
    if not all(type(value) is str for value in (scope, key_sha256, request_sha256)):
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    return _AppendRequestIdentity(
        scope=cast(str, scope),
        key_sha256=cast(str, key_sha256),
        request_fingerprint_sha256=cast(str, request_sha256),
    )


def _read_append_tail_envelope_source(path: Path) -> bytes | None:
    """Read a possible tail Envelope without upgrading known partial bytes.

    A missing, non-regular, reparse, oversized, or malformed file is a known
    incomplete tail and contributes no idempotency identity. I/O uncertainty
    is kept distinct and fails the append before any final write.
    """

    envelope_path = path / "envelope.yaml"
    try:
        path_stat = _lstat_if_present(envelope_path)
    except OSError as exc:
        raise _StoreIoFailure(stage="tail-identity") from exc
    if path_stat is None or not stat.S_ISREG(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        return None
    if path_stat.st_size > _ENVELOPE_MAXIMUM_BYTES:
        return None
    try:
        with envelope_path.open("rb") as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == path_stat.st_dev
                and handle_stat.st_ino == path_stat.st_ino
                and handle_stat.st_mode == path_stat.st_mode
            ):
                raise _StoreIoFailure(stage="tail-identity")
            source = stream.read(_ENVELOPE_MAXIMUM_BYTES + 1)
    except _StoreIoFailure:
        raise
    except OSError as exc:
        raise _StoreIoFailure(stage="tail-identity") from exc
    if not _same_identity(envelope_path, path_stat):
        raise _StoreIoFailure(stage="tail-identity")
    if type(source) is not bytes or len(source) > _ENVELOPE_MAXIMUM_BYTES:
        return None
    return source


def _scan_append_store(
    capture_root: Path,
    *,
    scope: str,
    key_sha256: str,
    request_sha256: str,
) -> _AppendStoreScan:
    """Validate the complete immutable Store, then resolve append identity."""

    chains = tuple(
        _load_disk_capture_version_chain(item)
        for item in _locate_capture_items(capture_root)
    )
    # Unknown projection machine versions are not silently replaced. Known
    # missing/corrupt projections remain rebuildable warnings.
    for chain in chains:
        _projection_warning_for_read(chain)

    tails: list[_AppendTailObservation] = []
    for chain in chains:
        incomplete = chain.chain.incomplete_version
        if incomplete is None:
            continue
        version_path = chain.version_paths.get(incomplete)
        if version_path is None:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        source = _read_append_tail_envelope_source(version_path)
        identity = None
        if source is not None:
            identity = _decidable_append_tail_identity(
                source,
                expected_capture_id=chain.chain.capture_id,
                expected_version=incomplete,
                previous_envelope=chain.chain.current.envelope,
            )
        tails.append(
            _AppendTailObservation(
                disk_chain=chain,
                version=incomplete,
                envelope_source=source,
                identity=identity,
            )
        )

    committed_matches: list[_AppendCommittedMatch] = []
    tail_matches: list[_AppendTailObservation] = []
    conflict = False
    for chain in chains:
        for committed in chain.chain.versions:
            identity = _append_identity_from_envelope(committed.envelope)
            if identity is None or (
                identity.scope != scope or identity.key_sha256 != key_sha256
            ):
                continue
            if identity.request_fingerprint_sha256 != request_sha256:
                conflict = True
            else:
                committed_matches.append(
                    _AppendCommittedMatch(
                        disk_chain=chain,
                        committed=committed,
                    )
                )
    for tail in tails:
        identity = tail.identity
        if identity is None or (
            identity.scope != scope or identity.key_sha256 != key_sha256
        ):
            continue
        if identity.request_fingerprint_sha256 != request_sha256:
            conflict = True
        else:
            tail_matches.append(tail)

    if conflict:
        raise _IdempotencyConflict
    if len(committed_matches) > 1 or (
        not committed_matches and len(tail_matches) > 1
    ):
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    return _AppendStoreScan(
        chains=chains,
        committed_match=(committed_matches[0] if committed_matches else None),
        tail_match=(tail_matches[0] if tail_matches else None),
        tails=tuple(tails),
    )


def _append_receipt_from_committed(
    committed: _CommittedCaptureVersion,
) -> dict[str, object]:
    envelope = committed.envelope
    primary = next(
        payload
        for payload in _payload_mappings(envelope)
        if payload["ordinal"] == 0 and payload["role"] == "primary"
    )
    return {
        "capture_id": envelope["capture_id"],
        "event_id": envelope["event_id"],
        "previous_version": envelope["previous_version"],
        "version": envelope["version"],
        "primary_payload_sha256": primary["sha256"],
        "payload_set_sha256": envelope["payload_set_sha256"],
        "envelope_sha256": envelope["envelope_sha256"],
        "durability": "durable",
        "routing_status": "unassigned",
        "trust_status": "unreviewed-capture",
        "gbrain_sync_status": "not-requested",
    }


def _append_warnings(
    disk_chain: _DiskCaptureVersionChain,
) -> tuple[OperationWarning, ...]:
    return (
        _warnings_for_capture_version_chain(disk_chain.chain)
        + _projection_warning_for_read(disk_chain)
    )


def _success_from_append_match(
    match: _AppendCommittedMatch,
) -> AppendCaptureVersionResult:
    version_path = match.disk_chain.version_paths.get(match.committed.version)
    if version_path is None:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    _attest_version_payloads(version_path, match.committed.envelope)
    return AppendCaptureVersionResult(
        receipt=_append_receipt_from_committed(match.committed),
        warnings=_append_warnings(match.disk_chain),
    )


def _adopt_append_tail_candidate(
    observation: _AppendTailObservation,
    request: AppendCaptureVersionRequest,
    *,
    payload_digest: DigestResult,
    payload_set_digest: str,
    request_digest: str,
    dependencies: _CaptureDependencies,
) -> _AppendCandidate | None:
    """Return a candidate only after the existing tail is completely proven."""

    source = observation.envelope_source
    identity = observation.identity
    if source is None or identity is None:
        return None
    previous_envelope = observation.disk_chain.chain.current.envelope
    try:
        envelope = load_envelope(source, require_canonical=True)
        if not verify_envelope(envelope):
            return None
        if (
            envelope.get("capture_id") != request.capture_id
            or envelope.get("version") != request.expected_current_version + 1
            or envelope.get("previous_version")
            != request.expected_current_version
            or identity.request_fingerprint_sha256 != request_digest
            or identity.scope
            != canonical_idempotency_scope(
                request.channel,
                "append_capture_version",
            )
            or identity.key_sha256
            != idempotency_key_sha256(request.idempotency_key)
            or envelope.get("channel") != request.channel.as_canonical_mapping()
            or envelope.get("actor") != _ACTOR
            or envelope.get("delivery_requests") != []
            or envelope.get("payload_set_sha256") != payload_set_digest
        ):
            return None
        event_id = envelope.get("event_id")
        if type(event_id) is not str:
            return None
        validate_typed_id(event_id, IdKind.EVENT)
        expected_intent = {
            **request.user_intent.as_canonical_mapping(),
            "evidence": {
                "event_id": event_id,
                "payload_id": payload_digest.sha256,
            },
        }
        if envelope.get("user_intent") != expected_intent:
            return None
        digests = _attest_version_payloads(observation.version_path, envelope)
        if len(digests) != 1 or (
            digests[0].byte_size != payload_digest.byte_size
            or not hmac.compare_digest(digests[0].sha256, payload_digest.sha256)
        ):
            return None
        event: dict[str, object] = {
            "schema": "knowledgeflow.capture-event",
            "schema_version": 1,
            "event_id": event_id,
            "event_type": "capture.version-appended",
            "capture_id": request.capture_id,
            "version": request.expected_current_version + 1,
            "previous_version": request.expected_current_version,
            "previous_envelope_sha256": previous_envelope["envelope_sha256"],
            "envelope_sha256": envelope["envelope_sha256"],
            "occurred_at": _sample_time(dependencies),
            "actor": dict(_ACTOR),
        }
        event_bytes = dump_capture_event(
            event,
            envelope=envelope,
            previous_envelope=previous_envelope,
        )
        return _AppendCandidate(
            capture_id=request.capture_id,
            event_id=event_id,
            previous_version=request.expected_current_version,
            version=request.expected_current_version + 1,
            envelope=envelope,
            envelope_bytes=source,
            previous_envelope=previous_envelope,
            event=event,
            event_bytes=event_bytes,
            payload_digest=payload_digest,
            payload_set_sha256=payload_set_digest,
        )
    except _StoreIoFailure:
        raise
    except (_IntegrityFailure, KeyError, TypeError, ValueError):
        return None


def _attest_append_candidate_at(
    version_path: Path,
    event_path: Path,
    candidate: _AppendCandidate,
) -> None:
    """Prove final or staging version/Event bytes equal one append candidate."""

    _immutable_directory_stat(
        version_path,
        missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
        stage="version-read",
    )
    envelope = _load_committed_envelope(version_path / "envelope.yaml")
    if envelope != candidate.envelope:
        raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
    digests = _attest_version_payloads(version_path, envelope)
    if len(digests) != 1:
        raise _IntegrityFailure(CauseCode.PAYLOAD_SET_HASH_MISMATCH)
    if (
        digests[0].byte_size != candidate.payload_digest.byte_size
        or not hmac.compare_digest(
            digests[0].sha256,
            candidate.payload_digest.sha256,
        )
    ):
        raise _IntegrityFailure(CauseCode.PAYLOAD_HASH_MISMATCH)
    source = _read_regular_bytes(
        event_path,
        maximum_bytes=_EVENT_MAXIMUM_BYTES,
        missing_cause=CauseCode.EVENT_MISSING,
        invalid_cause=CauseCode.EVENT_SCHEMA_INVALID,
    )
    try:
        event = load_capture_event(
            source,
            envelope=envelope,
            previous_envelope=candidate.previous_envelope,
            require_canonical=True,
        )
    except CaptureEventReferenceError as exc:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH) from exc
    except ValueError as exc:
        raise _IntegrityFailure(CauseCode.EVENT_SCHEMA_INVALID) from exc
    if event != candidate.event:
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)


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


def _probe_append_source(
    path: Path,
    expected_stat: os.stat_result,
) -> _AppendSourceEvidence:
    """Classify whether an append rename source is the originally owned object."""

    probed = _probe(path)
    if probed is _UNPROVABLE:
        return _AppendSourceEvidence.UNPROVABLE
    if probed is None:
        return _AppendSourceEvidence.ABSENT
    if _same_identity(path, expected_stat):
        return _AppendSourceEvidence.ORIGINAL
    return _AppendSourceEvidence.OTHER


def _probe_append_target(path: Path) -> _AppendTargetEvidence:
    """Classify target existence without treating existence as commit proof."""

    probed = _probe(path)
    if probed is _UNPROVABLE:
        return _AppendTargetEvidence.UNPROVABLE
    if probed is None:
        return _AppendTargetEvidence.ABSENT
    return _AppendTargetEvidence.PRESENT


def _attest_append_target(
    version_path: Path,
    event_path: Path,
    candidate: _AppendCandidate,
) -> _AppendTargetAttestation:
    try:
        _attest_append_candidate_at(version_path, event_path, candidate)
        return _AppendTargetAttestation.MATCH
    except _IntegrityFailure:
        return _AppendTargetAttestation.INVALID
    except _StoreIoFailure:
        return _AppendTargetAttestation.UNPROVABLE


def _classify_append_event_evidence(
    *,
    rename_attempted: bool,
    source: _AppendSourceEvidence,
    target: _AppendTargetEvidence,
    target_attestation: _AppendTargetAttestation,
) -> _AppendCommitDisposition:
    """Pure C5 Event-rename evidence matrix; never guesses from an exception."""

    if type(rename_attempted) is not bool:
        raise TypeError("rename_attempted must be boolean")
    source = _AppendSourceEvidence(source)
    target = _AppendTargetEvidence(target)
    target_attestation = _AppendTargetAttestation(target_attestation)

    if target is _AppendTargetEvidence.PRESENT and (
        target_attestation is _AppendTargetAttestation.INVALID
    ):
        return _AppendCommitDisposition.INTEGRITY_UNKNOWN
    if not rename_attempted:
        if target is _AppendTargetEvidence.ABSENT:
            return _AppendCommitDisposition.NOT_COMMITTED
        return _AppendCommitDisposition.UNKNOWN
    if (
        source is _AppendSourceEvidence.ORIGINAL
        and target is _AppendTargetEvidence.ABSENT
    ):
        return _AppendCommitDisposition.NOT_COMMITTED
    if (
        source is _AppendSourceEvidence.ABSENT
        and target is _AppendTargetEvidence.PRESENT
        and target_attestation is _AppendTargetAttestation.MATCH
    ):
        return _AppendCommitDisposition.COMMITTED
    return _AppendCommitDisposition.UNKNOWN


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
        _trigger_fault(_CaptureFaultPoint.AFTER_VERSION_RENAMED, dependencies)
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
        stored = _validate_candidate_at(
            final_path,
            candidate,
            expected_year=year,
            expected_month=month,
        )
        # Initial capture commits its version and Event in one Item rename.
        _trigger_fault(_CaptureFaultPoint.AFTER_EVENT_APPENDED, dependencies)
        return stored
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.UNKNOWN)
    except _StoreIoFailure:
        return _failure(
            PublicErrorCode.ATOMIC_COMMIT_FAILED,
            CommitState.UNKNOWN,
            retryable=True,
        )


def _append_atomic_failure(
    state: CommitState,
    *,
    stage: str,
) -> FailureResult:
    return _failure(
        PublicErrorCode.ATOMIC_COMMIT_FAILED,
        state,
        retryable=True,
        details={"stage": stage},
    )


def _append_disposition_after_event_attempt(
    staging: _AppendStaging,
    candidate: _AppendCandidate,
    *,
    version_path: Path,
    event_path: Path,
    source_stat: os.stat_result,
    rename_attempted: bool,
) -> _AppendCommitDisposition:
    source = _probe_append_source(
        staging.event_path(candidate.event_id),
        source_stat,
    )
    target = _probe_append_target(event_path)
    attestation = _AppendTargetAttestation.NOT_RUN
    if target is _AppendTargetEvidence.PRESENT:
        attestation = _attest_append_target(
            version_path,
            event_path,
            candidate,
        )
    elif target is _AppendTargetEvidence.UNPROVABLE:
        attestation = _AppendTargetAttestation.UNPROVABLE
    return _classify_append_event_evidence(
        rename_attempted=rename_attempted,
        source=source,
        target=target,
        target_attestation=attestation,
    )


def _failure_from_append_disposition(
    disposition: _AppendCommitDisposition,
    *,
    stage: str = "event-commit",
) -> FailureResult | None:
    if disposition is _AppendCommitDisposition.COMMITTED:
        return None
    if disposition is _AppendCommitDisposition.NOT_COMMITTED:
        return _append_atomic_failure(
            CommitState.NOT_COMMITTED,
            stage=stage,
        )
    if disposition is _AppendCommitDisposition.INTEGRITY_UNKNOWN:
        return _integrity_failure(
            _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH),
            CommitState.UNKNOWN,
        )
    return _append_atomic_failure(
        CommitState.UNKNOWN,
        stage=stage,
    )


def _final_append_chain(
    item: _LocatedCaptureItem,
    candidate: _AppendCandidate,
) -> _DiskCaptureVersionChain | FailureResult:
    try:
        disk_chain = _load_disk_capture_version_chain(item)
        committed = disk_chain.chain.version(candidate.version)
        if committed is None or (
            committed.envelope != candidate.envelope
            or committed.event != candidate.event
        ):
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        version_path = disk_chain.version_paths.get(candidate.version)
        if version_path is None:
            raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
        _attest_append_candidate_at(
            version_path,
            item.item_path / "events" / f"{candidate.event_id}.yaml",
            candidate,
        )
        return disk_chain
    except _UnsupportedMachineSchema:
        return _append_atomic_failure(
            CommitState.UNKNOWN,
            stage="final-readback",
        )
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.UNKNOWN)
    except _StoreIoFailure:
        return _append_atomic_failure(
            CommitState.UNKNOWN,
            stage="final-readback",
        )


def _commit_append_candidate(
    staging: _AppendStaging,
    target: _DiskCaptureVersionChain,
    candidate: _AppendCandidate,
    *,
    adopting_tail: bool,
    dependencies: _CaptureDependencies,
) -> _DiskCaptureVersionChain | FailureResult:
    """Commit one append with Event rename as the sole logical commit point."""

    item_path = target.item.item_path
    version_path = item_path / "versions" / f"{candidate.version:06d}"
    event_path = item_path / "events" / f"{candidate.event_id}.yaml"
    staged_event_path = staging.event_path(candidate.event_id)

    if adopting_tail:
        try:
            dependencies.durability.write_new_file_durable(
                staged_event_path,
                candidate.event_bytes,
                validator=lambda source: _require_exact_append_event(
                    source,
                    candidate,
                ),
            )
            _attest_append_candidate_at(
                version_path,
                staged_event_path,
                candidate,
            )
        except (_IntegrityFailure, _StoreIoFailure, DurabilityError, OSError):
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-target-conflict",
            )
    else:
        try:
            _write_append_candidate_metadata(staging, candidate, dependencies)
            _attest_append_candidate_at(
                staging.version_path,
                staged_event_path,
                candidate,
            )
            _trigger_fault(
                _CaptureFaultPoint.AFTER_READBACK_VERIFIED,
                dependencies,
            )
        except _IntegrityFailure as exc:
            return _integrity_failure(exc, CommitState.NOT_COMMITTED)
        except (_StoreIoFailure, DurabilityError, OSError):
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="candidate-write",
            )

        version_before = _probe_append_target(version_path)
        if version_before is _AppendTargetEvidence.UNPROVABLE:
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-target-conflict",
            )
        if version_before is _AppendTargetEvidence.PRESENT:
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-target-conflict",
            )
        try:
            _trigger_fault(
                _CaptureFaultPoint.BEFORE_APPEND_VERSION_RENAME,
                dependencies,
            )
            dependencies.durability.commit_directory_no_replace(
                staging.version_path,
                version_path,
            )
            _trigger_fault(
                _CaptureFaultPoint.AFTER_APPEND_VERSION_RENAME,
                dependencies,
            )
        except (DestinationAlreadyExistsError, DurabilityError, OSError):
            try:
                source_stat = _lstat_if_present(staged_event_path)
            except OSError:
                source_stat = None
            if source_stat is None or not stat.S_ISREG(source_stat.st_mode) or (
                _is_reparse_point(source_stat)
            ):
                return _append_atomic_failure(
                    CommitState.UNKNOWN,
                    stage="version-commit",
                )
            disposition = _append_disposition_after_event_attempt(
                staging,
                candidate,
                version_path=version_path,
                event_path=event_path,
                source_stat=source_stat,
                rename_attempted=False,
            )
            failure = _failure_from_append_disposition(
                disposition,
                stage="version-commit",
            )
            if failure is not None:
                return failure
        try:
            _attest_append_candidate_at(
                version_path,
                staged_event_path,
                candidate,
            )
        except (_IntegrityFailure, _StoreIoFailure):
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-readback",
            )

    try:
        source_stat = _lstat_if_present(staged_event_path)
    except OSError:
        source_stat = None
    if source_stat is None or not stat.S_ISREG(source_stat.st_mode) or (
        _is_reparse_point(source_stat)
    ):
        return _append_atomic_failure(
            CommitState.NOT_COMMITTED,
            stage="event-commit",
        )

    try:
        _trigger_fault(
            _CaptureFaultPoint.BEFORE_APPEND_EVENT_PREFLIGHT,
            dependencies,
        )
    except Exception:
        return _append_atomic_failure(
            CommitState.NOT_COMMITTED,
            stage="event-target-conflict",
        )
    event_before = _probe_append_target(event_path)
    if event_before is _AppendTargetEvidence.PRESENT:
        return _append_atomic_failure(
            CommitState.NOT_COMMITTED,
            stage="event-target-conflict",
        )
    if event_before is _AppendTargetEvidence.UNPROVABLE:
        return _append_atomic_failure(
            CommitState.UNKNOWN,
            stage="event-target-conflict",
        )

    try:
        _trigger_fault(
            _CaptureFaultPoint.BEFORE_APPEND_EVENT_RENAME,
            dependencies,
        )
        dependencies.durability.commit_file_no_replace_same_volume(
            staged_event_path,
            event_path,
            candidate.event_bytes,
            validator=lambda source: _require_exact_append_event(
                source,
                candidate,
            ),
        )
        _trigger_fault(
            _CaptureFaultPoint.AFTER_APPEND_EVENT_RENAME,
            dependencies,
        )
    except (DestinationAlreadyExistsError, DurabilityError, OSError):
        disposition = _append_disposition_after_event_attempt(
            staging,
            candidate,
            version_path=version_path,
            event_path=event_path,
            source_stat=source_stat,
            rename_attempted=True,
        )
        failure = _failure_from_append_disposition(disposition)
        if failure is not None:
            return failure

    final = _final_append_chain(target.item, candidate)
    if not isinstance(final, FailureResult):
        _trigger_fault(
            _CaptureFaultPoint.AFTER_APPEND_FINAL_READBACK,
            dependencies,
        )
    return final


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


def _appended_projection(
    candidate: _AppendCandidate,
    *,
    verified_at: str,
) -> dict[str, object]:
    """Build the current-state projection for a presealed append candidate."""

    state = {
        "schema": "knowledgeflow.capture-state",
        "schema_version": 1,
        "capture_id": candidate.capture_id,
        "current_version": candidate.version,
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
        "updated_at": candidate.event["occurred_at"],
    }
    # Validate here so no caller can obtain an unbound version >1 projection.
    dump_capture_state(
        state,
        envelope=candidate.envelope,
        current_event=candidate.event,
        previous_envelope=candidate.previous_envelope,
    )
    return state


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
        _trigger_fault(_CaptureFaultPoint.AFTER_PROJECTION_REPLACED, dependencies)
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


def _write_appended_projection(
    disk_chain: _DiskCaptureVersionChain,
    candidate: _AppendCandidate,
    staging: _AppendStaging,
    dependencies: _CaptureDependencies,
) -> bool:
    """Best-effort projection update after immutable append proof."""

    current = disk_chain.chain.current
    if (
        current.version != candidate.version
        or current.envelope != candidate.envelope
        or current.event != candidate.event
    ):
        return False
    item_path = disk_chain.item.item_path
    temporary_path = item_path / f".capture-state-{staging.transaction_id}.tmp"
    destination_path = item_path / "capture.yaml"
    temporary_stat: os.stat_result | None = None
    try:
        verified_at = _sample_time(dependencies)
        state = _appended_projection(candidate, verified_at=verified_at)
        state_bytes = dump_capture_state(
            state,
            envelope=candidate.envelope,
            current_event=candidate.event,
            previous_envelope=candidate.previous_envelope,
        )
        dependencies.durability.write_new_file_durable(
            temporary_path,
            state_bytes,
            validator=lambda source: load_capture_state(
                source,
                envelope=candidate.envelope,
                current_event=candidate.event,
                previous_envelope=candidate.previous_envelope,
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
        _trigger_fault(
            _CaptureFaultPoint.BEFORE_APPEND_PROJECTION_REPLACE,
            dependencies,
        )
        _trigger_fault(_CaptureFaultPoint.BEFORE_PROJECTION_REPLACE, dependencies)
        if not _same_identity(temporary_path, temporary_stat):
            return False
        dependencies.replace_file(temporary_path, destination_path)
        dependencies.durability.flush_directory_metadata(item_path)
        _trigger_fault(_CaptureFaultPoint.AFTER_PROJECTION_REPLACED, dependencies)
        return not _projection_warning_for_read(disk_chain)
    except Exception:
        return False
    finally:
        if temporary_stat is not None and _same_identity(
            temporary_path,
            temporary_stat,
        ):
            try:
                temporary_path.unlink()
                dependencies.durability.flush_directory_metadata(item_path)
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
    _trigger_fault(_CaptureFaultPoint.BEFORE_RECEIPT_RETURNED, dependencies)
    return CommittedWriteResult(
        receipt=_receipt_from_stored(stored),
        warnings=warnings,
    )


def _new_append_success(
    disk_chain: _DiskCaptureVersionChain,
    candidate: _AppendCandidate,
    staging: _AppendStaging,
    dependencies: _CaptureDependencies,
) -> AppendCaptureVersionResult:
    committed = disk_chain.chain.version(candidate.version)
    if committed is None or (
        committed.envelope != candidate.envelope
        or committed.event != candidate.event
    ):
        raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
    projection_valid = _write_appended_projection(
        disk_chain,
        candidate,
        staging,
        dependencies,
    )
    warnings = _warnings_for_capture_version_chain(disk_chain.chain)
    if not projection_valid:
        warnings += (
            OperationWarning(
                code=WarningCode.PROJECTION_NEEDS_REBUILD,
                details={"capture_id": candidate.capture_id},
            ),
        )
    _trigger_fault(
        _CaptureFaultPoint.BEFORE_APPEND_RECEIPT_RETURNED,
        dependencies,
    )
    return AppendCaptureVersionResult(
        receipt=_append_receipt_from_committed(committed),
        warnings=warnings,
    )


def _load_capture_environment(
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
) -> tuple[LocalConfig, Path, CaptureStoreManifest]:
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
    return local_config, local_config.capture.root, manifest


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
    _trigger_fault(_CaptureFaultPoint.AFTER_READBACK_VERIFIED, dependencies)
    committed = _commit_candidate(staging, candidate, dependencies)
    if isinstance(committed, FailureResult):
        return committed
    return _new_success(committed, candidate, staging, dependencies)


def _append_while_locked(
    request: AppendCaptureVersionRequest,
    *,
    staging: _AppendStaging,
    received_at: str,
    payload_digest: DigestResult,
    payload_set_digest: str,
    request_digest: str,
    scope: str,
    key_digest: str,
    dependencies: _CaptureDependencies,
) -> AppendCaptureVersionOperationResult:
    try:
        scan = _scan_append_store(
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
    except _UnsupportedMachineSchema:
        return _failure(
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
            CommitState.NOT_COMMITTED,
        )
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.NOT_COMMITTED)
    except _StoreIoFailure as exc:
        return _io_failure(exc, CommitState.NOT_COMMITTED)

    if scan.committed_match is not None:
        try:
            return _success_from_append_match(scan.committed_match)
        except _UnsupportedMachineSchema:
            return _failure(
                PublicErrorCode.UNSUPPORTED_STORE_VERSION,
                CommitState.UNKNOWN,
            )
        except _IntegrityFailure as exc:
            return _integrity_failure(exc, CommitState.UNKNOWN)
        except _StoreIoFailure:
            return _append_atomic_failure(
                CommitState.UNKNOWN,
                stage="idempotency-readback",
            )

    target = next(
        (
            chain
            for chain in scan.chains
            if chain.chain.capture_id == request.capture_id
        ),
        None,
    )
    if target is None:
        return _failure(
            PublicErrorCode.CAPTURE_NOT_FOUND,
            CommitState.NOT_COMMITTED,
        )

    current = target.chain.current
    current_path = target.version_paths.get(current.version)
    if current_path is None:
        return _integrity_failure(
            _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH),
            CommitState.NOT_COMMITTED,
        )
    try:
        _attest_version_payloads(current_path, current.envelope)
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.NOT_COMMITTED)
    except _StoreIoFailure as exc:
        return _io_failure(exc, CommitState.NOT_COMMITTED)

    if current.version != request.expected_current_version:
        return _failure(
            PublicErrorCode.VERSION_CONFLICT,
            CommitState.NOT_COMMITTED,
            details={
                "current_version": current.version,
                "expected_current_version": request.expected_current_version,
            },
        )

    target_tail = next(
        (
            tail
            for tail in scan.tails
            if tail.disk_chain.chain.capture_id == request.capture_id
        ),
        None,
    )
    adopting_tail = target_tail is not None
    if adopting_tail:
        if scan.tail_match is not target_tail:
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-target-conflict",
            )
        try:
            candidate = _adopt_append_tail_candidate(
                target_tail,
                request,
                payload_digest=payload_digest,
                payload_set_digest=payload_set_digest,
                request_digest=request_digest,
                dependencies=dependencies,
            )
        except _StoreIoFailure as exc:
            return _io_failure(exc, CommitState.NOT_COMMITTED)
        if candidate is None:
            return _append_atomic_failure(
                CommitState.NOT_COMMITTED,
                stage="version-target-conflict",
            )
    else:
        if scan.tail_match is not None:
            return _integrity_failure(
                _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH),
                CommitState.NOT_COMMITTED,
            )
        candidate = _build_append_candidate(
            request,
            previous_envelope=current.envelope,
            received_at=received_at,
            payload_digest=payload_digest,
            payload_set_digest=payload_set_digest,
            request_digest=request_digest,
            dependencies=dependencies,
        )

    committed = _commit_append_candidate(
        staging,
        target,
        candidate,
        adopting_tail=adopting_tail,
        dependencies=dependencies,
    )
    if isinstance(committed, FailureResult):
        return committed
    try:
        return _new_append_success(
            committed,
            candidate,
            staging,
            dependencies,
        )
    except _IntegrityFailure as exc:
        return _integrity_failure(exc, CommitState.UNKNOWN)
    except Exception:
        # Event and version were already proven. A projection/result-path fault
        # must never invert the immutable commit fact.
        committed_version = committed.chain.version(candidate.version)
        if committed_version is None:
            return _integrity_failure(
                _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH),
                CommitState.UNKNOWN,
            )
        return AppendCaptureVersionResult(
            receipt=_append_receipt_from_committed(committed_version),
            warnings=(
                OperationWarning(
                    code=WarningCode.PROJECTION_NEEDS_REBUILD,
                    details={"capture_id": candidate.capture_id},
                ),
            ),
        )


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
        local_config, capture_root, _manifest = _load_capture_environment(
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
                _before_flush=lambda _path: _trigger_fault(
                    _CaptureFaultPoint.AFTER_PAYLOAD_WRITTEN,
                    dependencies,
                ),
                _after_flush=lambda _path: _trigger_fault(
                    _CaptureFaultPoint.AFTER_PAYLOAD_FLUSHED,
                    dependencies,
                ),
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
                _trigger_fault(
                    _CaptureFaultPoint.AFTER_LOCK_ACQUIRED,
                    dependencies,
                )
                _recover_abandoned_capture_staging(
                    capture_root,
                    durability=dependencies.durability,
                    exclude_transaction_ids=(staging.transaction_id,),
                )
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


def _run_append_capture_version(
    request: AppendCaptureVersionRequest,
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
    dependencies: _CaptureDependencies,
) -> AppendCaptureVersionOperationResult:
    if not isinstance(request, AppendCaptureVersionRequest):
        return _failure(
            PublicErrorCode.INVALID_INPUT,
            CommitState.NOT_COMMITTED,
        )
    try:
        received_at = _sample_time(dependencies)
        local_config, capture_root, _manifest = _load_capture_environment(
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

    staging: _AppendStaging | None = None
    try:
        staging = _create_append_staging(
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
                _before_flush=lambda _path: _trigger_fault(
                    _CaptureFaultPoint.AFTER_PAYLOAD_WRITTEN,
                    dependencies,
                ),
                _after_flush=lambda _path: _trigger_fault(
                    _CaptureFaultPoint.AFTER_PAYLOAD_FLUSHED,
                    dependencies,
                ),
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
        intent = request.user_intent
        if not isinstance(intent, UserIntent):
            raise TypeError("normalized user_intent must be UserIntent")
        fingerprint = RequestFingerprint(
            operation="append_capture_version",
            payload_set_sha256=payload_set_digest,
            channel=request.channel,
            payload_metadata=(PayloadMetadata(ordinal=0),),
            user_intent=intent,
            capture_id=request.capture_id,
            expected_current_version=request.expected_current_version,
        )
        request_digest = request_fingerprint_sha256(fingerprint)
        scope = canonical_idempotency_scope(
            request.channel,
            "append_capture_version",
        )
        key_digest = idempotency_key_sha256(request.idempotency_key)

        locked_result: AppendCaptureVersionOperationResult | None = None
        try:
            with dependencies.lock_factory(capture_root):
                _trigger_fault(
                    _CaptureFaultPoint.AFTER_LOCK_ACQUIRED,
                    dependencies,
                )
                _recover_abandoned_capture_staging(
                    capture_root,
                    durability=dependencies.durability,
                    exclude_transaction_ids=(staging.transaction_id,),
                )
                locked_result = _append_while_locked(
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
            _cleanup_append_staging(
                staging,
                durability=dependencies.durability,
            )


def _run_get_capture(
    request: GetCaptureRequest,
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
    dependencies: _GetCaptureDependencies,
) -> GetCaptureOperationResult:
    if not isinstance(request, GetCaptureRequest):
        return _read_failure(PublicErrorCode.INVALID_INPUT)

    try:
        _local_config, capture_root, _manifest = _load_capture_environment(
            config_path=config_path,
            path_policy=path_policy,
        )
    except ConfigLoadError as exc:
        return _read_failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except (OSError, TypeError, ValueError):
        return _read_failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)

    spool: BinaryIO | None = None
    try:
        item = _locate_capture_item(capture_root, request.capture_id)
        if item is None:
            return _read_failure(PublicErrorCode.CAPTURE_NOT_FOUND)
        disk_chain = _load_disk_capture_version_chain(item)

        target_version = (
            disk_chain.chain.current_version
            if request.version is None
            else request.version
        )
        if disk_chain.chain.version(target_version) is None:
            return _read_failure(PublicErrorCode.VERSION_NOT_FOUND)

        try:
            spool = dependencies.spool_factory(capture_root)
        except Exception as exc:
            raise _StoreIoFailure(stage="body-spool") from exc
        if not all(
            callable(getattr(spool, name, None))
            for name in ("write", "read", "seek", "flush", "close")
        ):
            raise _StoreIoFailure(stage="body-spool")

        primary = _verify_target_payloads(
            disk_chain,
            version=target_version,
            spool=spool,
        )
        warnings = (
            _warnings_for_capture_version_chain(disk_chain.chain)
            + _projection_warning_for_read(disk_chain)
        )
        read_state = _rebuild_capture_read_state(disk_chain.chain)
        metadata = _capture_read_metadata(
            disk_chain,
            version=target_version,
            primary=primary,
        )
        result = GetCaptureResult(
            body_length_bytes=metadata.byte_size,
            capture=metadata,
            item_state=CaptureItemState(
                routing_status=read_state.routing_status,
                trust_status=read_state.trust_status,
            ),
            warnings=warnings,
        )
        if not _emit_verified_body(
            spool,
            request.body_sink,
            expected_bytes=metadata.byte_size,
        ):
            return _read_failure(
                PublicErrorCode.OUTPUT_WRITE_FAILED,
                retryable=True,
            )
        return result
    except _UnsupportedMachineSchema:
        return _read_failure(PublicErrorCode.UNSUPPORTED_STORE_VERSION)
    except _IntegrityFailure as exc:
        return _read_integrity_failure(exc)
    except _StoreIoFailure as exc:
        return _read_io_failure(exc)
    except (TypeError, ValueError):
        return _read_failure(
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            cause_code=CauseCode.ENVELOPE_HASH_MISMATCH,
        )
    except OSError:
        return _read_failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)
    finally:
        if spool is not None:
            try:
                spool.close()
            except Exception:
                pass


def _run_list_captures(
    request: ListCapturesRequest,
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
    dependencies: _ListCapturesDependencies,
) -> ListCapturesOperationResult:
    if not isinstance(request, ListCapturesRequest):
        return _read_failure(PublicErrorCode.INVALID_INPUT)

    try:
        _local_config, capture_root, manifest = _load_capture_environment(
            config_path=config_path,
            path_policy=path_policy,
        )
    except ConfigLoadError as exc:
        return _read_failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except (OSError, TypeError, ValueError):
        return _read_failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)

    cursor = None
    if request.cursor is not None:
        try:
            cursor = decode_capture_list_cursor(
                request.cursor,
                store_id=manifest.store_id,
                request=request,
            )
        except (TypeError, ValueError):
            return _read_failure(PublicErrorCode.INVALID_INPUT)

    try:
        candidates = tuple(
            _capture_list_candidate(_load_disk_capture_version_chain(item))
            for item in _locate_capture_items(capture_root)
        )
        filtered = (
            candidate
            for candidate in candidates
            if (
                request.routing_status is None
                or candidate.routing_status == request.routing_status
            )
            and (
                request.created_after is None
                or candidate.captured_at > request.created_after
            )
            and (
                request.created_before is None
                or candidate.captured_at < request.created_before
            )
            and (
                cursor is None
                or candidate.sort_key
                < (cursor.last_captured_at, cursor.last_capture_id)
            )
        )
        ordered = tuple(
            sorted(filtered, key=lambda candidate: candidate.sort_key, reverse=True)
        )
        page_candidates = ordered[: request.limit]
        items = tuple(
            _capture_list_item(candidate, dependencies=dependencies)
            for candidate in page_candidates
        )
        warnings = tuple(
            warning
            for candidate in page_candidates
            for warning in candidate.warnings
        )
        next_cursor = None
        if len(ordered) > request.limit:
            anchor = page_candidates[-1]
            next_cursor = encode_capture_list_cursor(
                store_id=manifest.store_id,
                request=request,
                last_captured_at=anchor.captured_at,
                last_capture_id=anchor.capture_id,
            )
        return ListCapturesResult(
            items=items,
            next_cursor=next_cursor,
            warnings=warnings,
        )
    except _UnsupportedMachineSchema:
        return _read_failure(PublicErrorCode.UNSUPPORTED_STORE_VERSION)
    except _IntegrityFailure as exc:
        return _read_integrity_failure(exc)
    except _StoreIoFailure as exc:
        return _read_io_failure(exc)
    except (TypeError, ValueError):
        return _read_failure(
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            cause_code=CauseCode.ENVELOPE_HASH_MISMATCH,
        )
    except OSError:
        return _read_failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


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


def append_capture_version(
    request: AppendCaptureVersionRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
) -> AppendCaptureVersionOperationResult:
    """Append one complete, immutable Capture version through the C5 transaction."""

    return _run_append_capture_version(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_CaptureDependencies(),
    )


def get_capture(
    request: GetCaptureRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
) -> GetCaptureOperationResult:
    """Verify and stream one exact or latest committed Capture version."""

    return _run_get_capture(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_GetCaptureDependencies(),
    )


def list_captures(
    request: ListCapturesRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
) -> ListCapturesOperationResult:
    """Return one stable keyset page with bounded current-text previews."""

    return _run_list_captures(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_ListCapturesDependencies(),
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


def _append_capture_version_with_dependencies(
    request: AppendCaptureVersionRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
    dependencies: _CaptureDependencies,
) -> AppendCaptureVersionOperationResult:
    """Internal deterministic/fault-injection entry point for C5 tests."""

    if not isinstance(dependencies, _CaptureDependencies):
        raise TypeError("dependencies must be _CaptureDependencies")
    return _run_append_capture_version(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


def _get_capture_with_dependencies(
    request: GetCaptureRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
    dependencies: _GetCaptureDependencies,
) -> GetCaptureOperationResult:
    """Internal deterministic entry point for bounded-spool tests."""

    if not isinstance(dependencies, _GetCaptureDependencies):
        raise TypeError("dependencies must be _GetCaptureDependencies")
    return _run_get_capture(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


def _list_captures_with_dependencies(
    request: ListCapturesRequest,
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
    dependencies: _ListCapturesDependencies,
) -> ListCapturesOperationResult:
    """Internal deterministic entry point for bounded-preview tests."""

    if not isinstance(dependencies, _ListCapturesDependencies):
        raise TypeError("dependencies must be _ListCapturesDependencies")
    return _run_list_captures(
        request,
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


__all__ = [
    "AppendCaptureVersionOperationResult",
    "CaptureTextOperationResult",
    "GetCaptureOperationResult",
    "ListCapturesOperationResult",
    "append_capture_version",
    "capture_text",
    "get_capture",
    "list_captures",
]
