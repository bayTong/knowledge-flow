"""Explicit C6 migration of one Capture Store between local Windows roots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import ntpath
import os
from pathlib import Path
import stat
from typing import BinaryIO, TypeAlias
from uuid import UUID

from .config import (
    ConfigLoadError,
    LocalConfig,
    create_local_config,
    dump_local_config,
    parse_local_config,
)
from .durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
)
from .errors import CauseCode, FailureResult, OperationError, PublicErrorCode
from .ids import IdKind, generate_uuid7, validate_typed_id
from .locking import (
    CaptureWriteLock,
    CaptureWriteLockError,
    InitializationLock,
    InitializationLockError,
    _acquire_capture_write_lock,
    acquire_initialization_lock,
)
from .manifest import CaptureStoreManifest, ManifestLoadError
from .operations import (
    _IntegrityFailure,
    _StoreIoFailure,
    _UnsupportedMachineSchema,
    _is_reparse_point,
)
from .paths import PathPolicy, PathPolicyError
from .recovery import _RebuildDependencies, _build_rebuild_plan
from .store import _InitFailure, _inspect_store


_COPY_CHUNK_BYTES = 1024 * 1024
_CONFIG_MAXIMUM_BYTES = 64 * 1024

_InitializationLockFactory = Callable[[Path], InitializationLock]
_CaptureLockFactory = Callable[[Path], CaptureWriteLock]
_UuidFactory = Callable[[], UUID]
_ReplaceFile = Callable[[Path, Path], None]
_FileFsync = Callable[[int], None]
_FaultHook = Callable[[], None]


class _MigrationFaultPoint(StrEnum):
    """Internal-only process-crash boundaries for C6C tests."""

    AFTER_TARGET_FILE_COPIED = "after_target_file_copied"
    BEFORE_CONFIG_REPLACED = "before_config_replaced"
    AFTER_CONFIG_REPLACED = "after_config_replaced"


def _noop_fault_hook() -> None:
    return None


@dataclass(frozen=True, slots=True)
class _MigrationDependencies:
    durability: DurabilityBackend = field(default_factory=DurabilityBackend)
    initialization_lock_factory: _InitializationLockFactory = field(
        default=acquire_initialization_lock,
        repr=False,
        compare=False,
    )
    capture_lock_factory: _CaptureLockFactory = field(
        default=_acquire_capture_write_lock,
        repr=False,
        compare=False,
    )
    uuid_factory: _UuidFactory = field(
        default=generate_uuid7,
        repr=False,
        compare=False,
    )
    replace_file: _ReplaceFile = field(
        default=os.replace,
        repr=False,
        compare=False,
    )
    fsync: _FileFsync = field(default=os.fsync, repr=False, compare=False)
    fault_point: _MigrationFaultPoint | None = field(
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
class MigrateCaptureStoreResult:
    """Metadata-only receipt for one explicit Store migration."""

    store_id: str
    source_root: Path
    target_root: Path
    config_switched: bool
    files_copied: int
    files_reused: int
    bytes_copied: int
    bytes_reused: int
    items_verified: int
    versions_verified: int
    source_retained: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        validate_typed_id(self.store_id, IdKind.STORE)
        if not isinstance(self.source_root, Path) or not isinstance(
            self.target_root,
            Path,
        ):
            raise TypeError("migration roots must be pathlib.Path values")
        if type(self.config_switched) is not bool:
            raise TypeError("config_switched must be boolean")
        counts = (
            self.files_copied,
            self.files_reused,
            self.bytes_copied,
            self.bytes_reused,
            self.items_verified,
            self.versions_verified,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("migration counts must be non-negative integers")
        if self.source_retained is not True:
            raise ValueError("C6C must retain the source Store")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "store_id": self.store_id,
            "source_root": str(self.source_root),
            "target_root": str(self.target_root),
            "config_switched": self.config_switched,
            "source_retained": self.source_retained,
            "files_copied": self.files_copied,
            "files_reused": self.files_reused,
            "bytes_copied": self.bytes_copied,
            "bytes_reused": self.bytes_reused,
            "items_verified": self.items_verified,
            "versions_verified": self.versions_verified,
        }


MigrateCaptureStoreOperationResult: TypeAlias = (
    MigrateCaptureStoreResult | FailureResult
)


@dataclass(frozen=True, slots=True)
class _FileRecord:
    relative_parts: tuple[str, ...]
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _StoreSnapshot:
    directories: frozenset[tuple[str, ...]]
    files: tuple[_FileRecord, ...]

    @property
    def files_by_path(self) -> dict[tuple[str, ...], _FileRecord]:
        return {record.relative_parts: record for record in self.files}


@dataclass(frozen=True, slots=True)
class _ConfigSnapshot:
    config: LocalConfig
    source: bytes = field(repr=False)
    path_stat: os.stat_result = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _MigrationRequest:
    config_path: Path
    source_root: Path
    target_root: Path
    expected_store_id: str
    config_snapshot: _ConfigSnapshot
    source_manifest: CaptureStoreManifest
    already_connected_to_target: bool


@dataclass(frozen=True, slots=True)
class _ValidationSummary:
    items_verified: int
    versions_verified: int


@dataclass(frozen=True, slots=True)
class _CopySummary:
    files_copied: int
    files_reused: int
    bytes_copied: int
    bytes_reused: int


class _MigrationIoFailure(RuntimeError):
    def __init__(self, *, stage: str, retryable: bool = False) -> None:
        self.stage = stage
        self.retryable = retryable
        super().__init__("capture store migration I/O failed")


class _MigrationTargetConflict(RuntimeError):
    pass


class _MigrationConfigConflict(RuntimeError):
    pass


def _failure(
    code: PublicErrorCode,
    *,
    retryable: bool = False,
    cause_code: CauseCode | None = None,
    stage: str | None = None,
) -> FailureResult:
    details: dict[str, object] = {}
    if stage is not None:
        details["stage"] = stage
    return FailureResult(
        error=OperationError(
            code=code,
            retryable=retryable,
            cause_code=cause_code,
            details=details,
        )
    )


def _trigger_fault(
    point: _MigrationFaultPoint,
    dependencies: _MigrationDependencies,
) -> None:
    if dependencies.fault_point == point:
        dependencies.fault_hook()


def _path_key(path: Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def _same_path(first: Path, second: Path) -> bool:
    return _path_key(first) == _path_key(second)


def _is_same_or_within(path: Path, parent: Path) -> bool:
    try:
        return ntpath.commonpath((_path_key(path), _path_key(parent))) == _path_key(
            parent
        )
    except ValueError:
        return False


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


def _plain_directory(path: Path, *, stage: str) -> os.stat_result:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _MigrationIoFailure(stage=stage) from exc
    if path_stat is None or not stat.S_ISDIR(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        raise _MigrationIoFailure(stage=stage)
    return path_stat


def _plain_file(path: Path, *, stage: str) -> os.stat_result:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _MigrationIoFailure(stage=stage) from exc
    if path_stat is None or not stat.S_ISREG(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        raise _MigrationIoFailure(stage=stage)
    return path_stat


def _directory_entries(path: Path, *, stage: str) -> tuple[Path, ...]:
    _plain_directory(path, stage=stage)
    try:
        return tuple(sorted(path.iterdir(), key=lambda entry: entry.name))
    except OSError as exc:
        raise _MigrationIoFailure(stage=stage) from exc


def _read_small_file(
    path: Path,
    *,
    maximum_bytes: int,
    stage: str,
) -> tuple[bytes, os.stat_result]:
    path_stat = _plain_file(path, stage=stage)
    if path_stat.st_size > maximum_bytes:
        raise _MigrationIoFailure(stage=stage)
    try:
        with path.open("rb") as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == path_stat.st_dev
                and handle_stat.st_ino == path_stat.st_ino
                and handle_stat.st_mode == path_stat.st_mode
            ):
                raise _MigrationIoFailure(stage=stage)
            source = stream.read(maximum_bytes + 1)
            if type(source) is not bytes or len(source) > maximum_bytes:
                raise _MigrationIoFailure(stage=stage)
    except _MigrationIoFailure:
        raise
    except OSError as exc:
        raise _MigrationIoFailure(stage=stage) from exc
    if not _same_identity(path, path_stat):
        raise _MigrationIoFailure(stage=stage)
    return source, path_stat


def _digest_file(path: Path, *, stage: str) -> _FileRecord:
    path_stat = _plain_file(path, stage=stage)
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with path.open("rb") as stream:
            handle_stat = os.fstat(stream.fileno())
            if not (
                stat.S_ISREG(handle_stat.st_mode)
                and handle_stat.st_dev == path_stat.st_dev
                and handle_stat.st_ino == path_stat.st_ino
                and handle_stat.st_mode == path_stat.st_mode
            ):
                raise _MigrationIoFailure(stage=stage)
            while True:
                chunk = stream.read(_COPY_CHUNK_BYTES)
                if type(chunk) is not bytes:
                    raise _MigrationIoFailure(stage=stage)
                if not chunk:
                    break
                digest.update(chunk)
                byte_size += len(chunk)
    except _MigrationIoFailure:
        raise
    except OSError as exc:
        raise _MigrationIoFailure(stage=stage) from exc
    if byte_size != path_stat.st_size or not _same_identity(path, path_stat):
        raise _MigrationIoFailure(stage=stage)
    return _FileRecord(
        relative_parts=(),
        byte_size=byte_size,
        sha256="sha256:" + digest.hexdigest(),
    )


def _snapshot_store(
    capture_root: Path,
    *,
    target: bool,
) -> _StoreSnapshot:
    """Hash one plain tree while excluding ephemeral staging and lock contents."""

    _plain_directory(capture_root, stage="migration-tree-read")
    directories: set[tuple[str, ...]] = set()
    files: list[_FileRecord] = []

    def visit(directory: Path, relative_parts: tuple[str, ...]) -> None:
        entries = _directory_entries(directory, stage="migration-tree-read")
        for entry in entries:
            parts = relative_parts + (entry.name,)
            try:
                entry_stat = _lstat_if_present(entry)
            except OSError as exc:
                raise _MigrationIoFailure(stage="migration-tree-read") from exc
            if entry_stat is None or _is_reparse_point(entry_stat):
                raise _MigrationIoFailure(stage="migration-tree-read")

            if parts == (".staging",):
                if not stat.S_ISDIR(entry_stat.st_mode):
                    raise _MigrationIoFailure(stage="migration-tree-read")
                directories.add(parts)
                if target and _directory_entries(
                    entry,
                    stage="migration-target-staging",
                ):
                    raise _MigrationTargetConflict
                continue

            if parts == ("journal", "capture-write.lock"):
                if not stat.S_ISREG(entry_stat.st_mode):
                    raise _MigrationIoFailure(stage="migration-tree-read")
                continue

            if stat.S_ISDIR(entry_stat.st_mode):
                directories.add(parts)
                visit(entry, parts)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise _MigrationIoFailure(stage="migration-tree-read")
            record = _digest_file(entry, stage="migration-file-read")
            files.append(
                _FileRecord(
                    relative_parts=parts,
                    byte_size=record.byte_size,
                    sha256=record.sha256,
                )
            )

    visit(capture_root, ())
    return _StoreSnapshot(
        directories=frozenset(directories),
        files=tuple(sorted(files, key=lambda record: record.relative_parts)),
    )


def _assert_compatible_subset(
    candidate: _StoreSnapshot,
    expected: _StoreSnapshot,
) -> None:
    if not candidate.directories.issubset(expected.directories):
        raise _MigrationTargetConflict
    expected_files = expected.files_by_path
    for record in candidate.files:
        if expected_files.get(record.relative_parts) != record:
            raise _MigrationTargetConflict


def _assert_exact_snapshot(
    candidate: _StoreSnapshot,
    expected: _StoreSnapshot,
) -> None:
    if candidate != expected:
        raise _MigrationTargetConflict


def _create_directory(
    path: Path,
    *,
    dependencies: _MigrationDependencies,
) -> None:
    _plain_directory(path.parent, stage="migration-directory-parent")
    try:
        path.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        _plain_directory(path, stage="migration-directory-race")
        return
    except OSError as exc:
        raise _MigrationIoFailure(stage="migration-directory-create") from exc
    _plain_directory(path, stage="migration-directory-create")
    dependencies.durability.flush_directory_metadata(path.parent)


def _ensure_target_root(
    target_root: Path,
    *,
    dependencies: _MigrationDependencies,
) -> None:
    _plain_directory(target_root.parent, stage="migration-target-parent")
    try:
        target_stat = _lstat_if_present(target_root)
    except OSError as exc:
        raise _MigrationIoFailure(stage="migration-target-read") from exc
    if target_stat is None:
        _create_directory(target_root, dependencies=dependencies)
        return
    if not stat.S_ISDIR(target_stat.st_mode) or _is_reparse_point(target_stat):
        raise _MigrationTargetConflict


def _ensure_target_journal(
    target_root: Path,
    *,
    dependencies: _MigrationDependencies,
) -> None:
    journal = target_root / "journal"
    try:
        journal_stat = _lstat_if_present(journal)
    except OSError as exc:
        raise _MigrationIoFailure(stage="migration-target-journal") from exc
    if journal_stat is None:
        _create_directory(journal, dependencies=dependencies)
        return
    if not stat.S_ISDIR(journal_stat.st_mode) or _is_reparse_point(journal_stat):
        raise _MigrationTargetConflict


def _open_source_file(
    path: Path,
    expected: _FileRecord,
) -> tuple[BinaryIO, os.stat_result]:
    path_stat = _plain_file(path, stage="migration-copy-read")
    if path_stat.st_size != expected.byte_size:
        raise _MigrationIoFailure(stage="migration-copy-read")
    try:
        stream = path.open("rb")
        handle_stat = os.fstat(stream.fileno())
    except OSError as exc:
        raise _MigrationIoFailure(stage="migration-copy-read") from exc
    if not (
        stat.S_ISREG(handle_stat.st_mode)
        and handle_stat.st_dev == path_stat.st_dev
        and handle_stat.st_ino == path_stat.st_ino
        and handle_stat.st_mode == path_stat.st_mode
    ):
        stream.close()
        raise _MigrationIoFailure(stage="migration-copy-read")
    return stream, path_stat


def _copy_new_file(
    source: Path,
    destination: Path,
    expected: _FileRecord,
    *,
    dependencies: _MigrationDependencies,
) -> None:
    _plain_directory(destination.parent, stage="migration-copy-parent")
    source_stream, source_stat = _open_source_file(source, expected)
    digest = hashlib.sha256()
    byte_size = 0
    try:
        try:
            destination_stream = destination.open("xb")
        except FileExistsError as exc:
            raise DestinationAlreadyExistsError from exc
        with source_stream, destination_stream:
            while True:
                chunk = source_stream.read(_COPY_CHUNK_BYTES)
                if type(chunk) is not bytes:
                    raise _MigrationIoFailure(stage="migration-copy-read")
                if not chunk:
                    break
                digest.update(chunk)
                byte_size += len(chunk)
                remaining = memoryview(chunk)
                while remaining:
                    written = destination_stream.write(remaining)
                    if (
                        type(written) is not int
                        or written <= 0
                        or written > remaining.nbytes
                    ):
                        raise _MigrationIoFailure(stage="migration-copy-write")
                    remaining = remaining[written:]
            destination_stream.flush()
            try:
                dependencies.fsync(destination_stream.fileno())
            except OSError as exc:
                raise _MigrationIoFailure(stage="migration-copy-fsync") from exc
    except DestinationAlreadyExistsError:
        raise
    except _MigrationIoFailure:
        raise
    except OSError as exc:
        raise _MigrationIoFailure(stage="migration-copy-write") from exc

    actual_sha256 = "sha256:" + digest.hexdigest()
    if (
        byte_size != expected.byte_size
        or actual_sha256 != expected.sha256
        or not _same_identity(source, source_stat)
    ):
        raise _MigrationIoFailure(stage="migration-copy-read")
    destination_record = _digest_file(
        destination,
        stage="migration-copy-readback",
    )
    if (
        destination_record.byte_size != expected.byte_size
        or destination_record.sha256 != expected.sha256
    ):
        raise _MigrationIoFailure(stage="migration-copy-readback")
    dependencies.durability.flush_directory_metadata(destination.parent)


def _copy_snapshot(
    source_root: Path,
    target_root: Path,
    expected: _StoreSnapshot,
    *,
    dependencies: _MigrationDependencies,
) -> _CopySummary:
    current = _snapshot_store(target_root, target=True)
    _assert_compatible_subset(current, expected)

    for parts in sorted(expected.directories, key=lambda value: (len(value), value)):
        destination = target_root.joinpath(*parts)
        try:
            destination_stat = _lstat_if_present(destination)
        except OSError as exc:
            raise _MigrationIoFailure(stage="migration-directory-read") from exc
        if destination_stat is None:
            _create_directory(destination, dependencies=dependencies)
        elif not stat.S_ISDIR(destination_stat.st_mode) or _is_reparse_point(
            destination_stat
        ):
            raise _MigrationTargetConflict

    current_files = current.files_by_path
    files_copied = 0
    files_reused = 0
    bytes_copied = 0
    bytes_reused = 0
    for record in expected.files:
        if current_files.get(record.relative_parts) == record:
            files_reused += 1
            bytes_reused += record.byte_size
            continue
        source = source_root.joinpath(*record.relative_parts)
        destination = target_root.joinpath(*record.relative_parts)
        try:
            _copy_new_file(
                source,
                destination,
                record,
                dependencies=dependencies,
            )
        except DestinationAlreadyExistsError:
            appeared = _digest_file(
                destination,
                stage="migration-copy-race",
            )
            if (
                appeared.byte_size != record.byte_size
                or appeared.sha256 != record.sha256
            ):
                raise _MigrationTargetConflict
            files_reused += 1
            bytes_reused += record.byte_size
            continue
        files_copied += 1
        bytes_copied += record.byte_size
        _trigger_fault(
            _MigrationFaultPoint.AFTER_TARGET_FILE_COPIED,
            dependencies,
        )

    final_snapshot = _snapshot_store(target_root, target=True)
    _assert_exact_snapshot(final_snapshot, expected)
    return _CopySummary(
        files_copied=files_copied,
        files_reused=files_reused,
        bytes_copied=bytes_copied,
        bytes_reused=bytes_reused,
    )


def _config_values_match(first: LocalConfig, second: LocalConfig) -> bool:
    return (
        _same_path(first.capture.root, second.capture.root)
        and first.capture.inline_text_threshold_bytes
        == second.capture.inline_text_threshold_bytes
        and first.capture.max_text_version_bytes
        == second.capture.max_text_version_bytes
    )


def _read_config_snapshot(
    config_path: Path,
    *,
    path_policy: PathPolicy,
) -> _ConfigSnapshot:
    source, path_stat = _read_small_file(
        config_path,
        maximum_bytes=_CONFIG_MAXIMUM_BYTES,
        stage="migration-config-read",
    )
    try:
        config = parse_local_config(source, path_policy=path_policy)
    except ConfigLoadError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    return _ConfigSnapshot(config=config, source=source, path_stat=path_stat)


def _prepare_request(
    *,
    config_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    expected_store_id: str,
    path_policy: PathPolicy,
) -> _MigrationRequest:
    if not isinstance(path_policy, PathPolicy):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)
    try:
        validate_typed_id(expected_store_id, IdKind.STORE)
        selected_config = path_policy.validate_config_path(config_path)
        selected_source = path_policy.validate_capture_root(source_root)
        selected_target = path_policy.validate_capture_root(target_root)
    except (PathPolicyError, TypeError, ValueError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc

    if (
        _same_path(selected_source, selected_target)
        or _is_same_or_within(selected_source, selected_target)
        or _is_same_or_within(selected_target, selected_source)
        or _is_same_or_within(selected_config, selected_source)
        or _is_same_or_within(selected_config, selected_target)
    ):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)

    config_snapshot = _read_config_snapshot(
        selected_config,
        path_policy=path_policy,
    )
    configured_root = config_snapshot.config.capture.root
    if _same_path(configured_root, selected_source):
        already_connected = False
    elif _same_path(configured_root, selected_target):
        already_connected = True
    else:
        raise _MigrationConfigConflict

    source_manifest = _inspect_store(selected_source)
    if source_manifest is None:
        raise _InitFailure(
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
                retryable=False,
            )
        )
    if source_manifest.store_id != expected_store_id:
        raise _MigrationConfigConflict
    return _MigrationRequest(
        config_path=selected_config,
        source_root=selected_source,
        target_root=selected_target,
        expected_store_id=expected_store_id,
        config_snapshot=config_snapshot,
        source_manifest=source_manifest,
        already_connected_to_target=already_connected,
    )


def _requests_match(first: _MigrationRequest, second: _MigrationRequest) -> bool:
    return (
        _same_path(first.config_path, second.config_path)
        and _same_path(first.source_root, second.source_root)
        and _same_path(first.target_root, second.target_root)
        and first.expected_store_id == second.expected_store_id
        and first.source_manifest == second.source_manifest
        and first.already_connected_to_target
        == second.already_connected_to_target
        and first.config_snapshot.source == second.config_snapshot.source
        and _same_identity(first.config_path, first.config_snapshot.path_stat)
        and _same_identity(second.config_path, second.config_snapshot.path_stat)
    )


def _validate_store(
    capture_root: Path,
    *,
    expected_store_id: str,
) -> _ValidationSummary:
    manifest = _inspect_store(capture_root)
    if manifest is None:
        raise _InitFailure(
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
                retryable=False,
            )
        )
    if manifest.store_id != expected_store_id:
        raise _MigrationTargetConflict
    plan = _build_rebuild_plan(
        capture_root,
        dependencies=_RebuildDependencies(),
    )
    if plan.missing_directories or any(
        projection.needs_rebuild for projection in plan.projections
    ):
        raise _MigrationIoFailure(stage="migration-derived-state")
    return _ValidationSummary(
        items_verified=len(plan.projections),
        versions_verified=plan.versions_verified,
    )


def _new_config(
    request: _MigrationRequest,
    *,
    path_policy: PathPolicy,
) -> LocalConfig:
    old = request.config_snapshot.config.capture
    return create_local_config(
        root=request.target_root,
        inline_text_threshold_bytes=old.inline_text_threshold_bytes,
        max_text_version_bytes=old.max_text_version_bytes,
        path_policy=path_policy,
    )


def _new_config_temp_path(
    config_path: Path,
    *,
    dependencies: _MigrationDependencies,
) -> Path:
    for _attempt in range(8):
        transaction_id = dependencies.uuid_factory()
        if not isinstance(transaction_id, UUID) or transaction_id.version != 7:
            raise TypeError("uuid_factory must return UUIDv7 values")
        candidate = config_path.parent / (
            f".knowledgeflow-migration-{transaction_id}.tmp"
        )
        if _lstat_if_present(candidate) is None:
            return candidate
    raise _MigrationIoFailure(stage="migration-config-temp-collision")


def _cleanup_config_temp(
    path: Path,
    expected_stat: os.stat_result | None,
    *,
    dependencies: _MigrationDependencies,
) -> None:
    if expected_stat is None or not _same_identity(path, expected_stat):
        return
    try:
        path.unlink()
        dependencies.durability.flush_directory_metadata(path.parent)
    except (DurabilityError, OSError):
        pass


def _switch_config(
    request: _MigrationRequest,
    new_config: LocalConfig,
    *,
    path_policy: PathPolicy,
    dependencies: _MigrationDependencies,
) -> None:
    new_bytes = dump_local_config(new_config)
    temporary = _new_config_temp_path(
        request.config_path,
        dependencies=dependencies,
    )
    temporary_stat: os.stat_result | None = None
    try:
        dependencies.durability.write_new_file_durable(
            temporary,
            new_bytes,
            validator=lambda source: parse_local_config(
                source,
                path_policy=path_policy,
            ),
        )
        temporary_stat = _plain_file(
            temporary,
            stage="migration-config-temp",
        )
        current = _read_config_snapshot(
            request.config_path,
            path_policy=path_policy,
        )
        if (
            current.source != request.config_snapshot.source
            or not _same_identity(
                request.config_path,
                request.config_snapshot.path_stat,
            )
            or not _config_values_match(
                current.config,
                request.config_snapshot.config,
            )
        ):
            raise _MigrationConfigConflict

        _trigger_fault(
            _MigrationFaultPoint.BEFORE_CONFIG_REPLACED,
            dependencies,
        )
        replacement_error: Exception | None = None
        try:
            dependencies.replace_file(temporary, request.config_path)
            dependencies.durability.flush_directory_metadata(
                request.config_path.parent
            )
            _trigger_fault(
                _MigrationFaultPoint.AFTER_CONFIG_REPLACED,
                dependencies,
            )
        except Exception as exc:
            replacement_error = exc

        try:
            final = _read_config_snapshot(
                request.config_path,
                path_policy=path_policy,
            )
        except (ConfigLoadError, _MigrationIoFailure) as exc:
            raise _MigrationIoFailure(stage="migration-config-readback") from exc
        if final.source == new_bytes and _config_values_match(
            final.config,
            new_config,
        ):
            return
        if final.source == request.config_snapshot.source and _config_values_match(
            final.config,
            request.config_snapshot.config,
        ):
            raise _MigrationIoFailure(stage="migration-config-replace") from (
                replacement_error
            )
        raise _MigrationConfigConflict
    finally:
        _cleanup_config_temp(
            temporary,
            temporary_stat,
            dependencies=dependencies,
        )


def _already_migrated_result(
    request: _MigrationRequest,
    *,
    dependencies: _MigrationDependencies,
) -> MigrateCaptureStoreResult:
    completed: MigrateCaptureStoreResult | None = None
    with dependencies.capture_lock_factory(request.source_root):
        source_manifest = _inspect_store(request.source_root)
        if source_manifest != request.source_manifest:
            raise _MigrationConfigConflict
        _validate_store(
            request.source_root,
            expected_store_id=request.expected_store_id,
        )
        with dependencies.capture_lock_factory(request.target_root):
            target_validation = _validate_store(
                request.target_root,
                expected_store_id=request.expected_store_id,
            )
            completed = MigrateCaptureStoreResult(
                store_id=request.expected_store_id,
                source_root=request.source_root,
                target_root=request.target_root,
                config_switched=False,
                files_copied=0,
                files_reused=0,
                bytes_copied=0,
                bytes_reused=0,
                items_verified=target_validation.items_verified,
                versions_verified=target_validation.versions_verified,
            )
    if completed is None:
        raise _MigrationIoFailure(stage="migration-lock-release")
    return completed


def _migrate_locked(
    request: _MigrationRequest,
    *,
    path_policy: PathPolicy,
    dependencies: _MigrationDependencies,
) -> MigrateCaptureStoreResult:
    if request.already_connected_to_target:
        return _already_migrated_result(request, dependencies=dependencies)

    completed: MigrateCaptureStoreResult | None = None
    with dependencies.capture_lock_factory(request.source_root):
        current_config = _read_config_snapshot(
            request.config_path,
            path_policy=path_policy,
        )
        if (
            current_config.source != request.config_snapshot.source
            or not _config_values_match(
                current_config.config,
                request.config_snapshot.config,
            )
        ):
            raise _MigrationConfigConflict
        source_manifest = _inspect_store(request.source_root)
        if source_manifest != request.source_manifest:
            raise _MigrationConfigConflict
        source_validation = _validate_store(
            request.source_root,
            expected_store_id=request.expected_store_id,
        )
        source_snapshot = _snapshot_store(request.source_root, target=False)

        _ensure_target_root(
            request.target_root,
            dependencies=dependencies,
        )
        target_before_lock = _snapshot_store(request.target_root, target=True)
        _assert_compatible_subset(target_before_lock, source_snapshot)
        _ensure_target_journal(
            request.target_root,
            dependencies=dependencies,
        )

        with dependencies.capture_lock_factory(request.target_root):
            target_under_lock = _snapshot_store(
                request.target_root,
                target=True,
            )
            _assert_compatible_subset(target_under_lock, source_snapshot)
            copied = _copy_snapshot(
                request.source_root,
                request.target_root,
                source_snapshot,
                dependencies=dependencies,
            )
            target_validation = _validate_store(
                request.target_root,
                expected_store_id=request.expected_store_id,
            )
            if target_validation != source_validation:
                raise _MigrationTargetConflict

            new_config = _new_config(request, path_policy=path_policy)
            _switch_config(
                request,
                new_config,
                path_policy=path_policy,
                dependencies=dependencies,
            )
            completed = MigrateCaptureStoreResult(
                store_id=request.expected_store_id,
                source_root=request.source_root,
                target_root=request.target_root,
                config_switched=True,
                files_copied=copied.files_copied,
                files_reused=copied.files_reused,
                bytes_copied=copied.bytes_copied,
                bytes_reused=copied.bytes_reused,
                items_verified=target_validation.items_verified,
                versions_verified=target_validation.versions_verified,
            )
    if completed is None:
        raise _MigrationIoFailure(stage="migration-lock-release")
    return completed


def _run_migrate_capture_store(
    *,
    config_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    expected_store_id: str,
    path_policy: PathPolicy,
    dependencies: _MigrationDependencies,
) -> MigrateCaptureStoreOperationResult:
    completed: MigrateCaptureStoreResult | None = None
    try:
        initial = _prepare_request(
            config_path=config_path,
            source_root=source_root,
            target_root=target_root,
            expected_store_id=expected_store_id,
            path_policy=path_policy,
        )
        with dependencies.initialization_lock_factory(initial.config_path):
            locked = _prepare_request(
                config_path=config_path,
                source_root=source_root,
                target_root=target_root,
                expected_store_id=expected_store_id,
                path_policy=path_policy,
            )
            if not _requests_match(initial, locked):
                raise _MigrationConfigConflict
            completed = _migrate_locked(
                locked,
                path_policy=path_policy,
                dependencies=dependencies,
            )
        if completed is None:
            raise _MigrationIoFailure(stage="migration-lock-release")
        return completed
    except (InitializationLockError, CaptureWriteLockError) as exc:
        if completed is not None:
            return completed
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage="migration-lock",
        )
    except ConfigLoadError as exc:
        return _failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except ManifestLoadError as exc:
        return _failure(exc.code)
    except _MigrationConfigConflict:
        return _failure(PublicErrorCode.CONFIG_STORE_CONFLICT)
    except _MigrationTargetConflict:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="migration-target-conflict",
        )
    except _UnsupportedMachineSchema:
        return _failure(PublicErrorCode.UNSUPPORTED_STORE_VERSION)
    except _IntegrityFailure as exc:
        return _failure(
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            cause_code=exc.cause_code,
        )
    except _StoreIoFailure as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            cause_code=exc.cause_code,
            stage=exc.stage,
        )
    except _MigrationIoFailure as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage=exc.stage,
        )
    except DurabilityError as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage=exc.stage.value,
        )
    except DestinationAlreadyExistsError:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="migration-target-race",
        )
    except (OSError, TypeError, ValueError):
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


def migrate_capture_store(
    *,
    config_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    expected_store_id: str,
    path_policy: PathPolicy,
) -> MigrateCaptureStoreOperationResult:
    """Copy, fully verify, then atomically connect one explicit target Store.

    The operation never deletes the source.  It is intentionally separate from
    the four everyday Capture operations and requires both roots plus the exact
    source Store identity.
    """

    return _run_migrate_capture_store(
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
        expected_store_id=expected_store_id,
        path_policy=path_policy,
        dependencies=_MigrationDependencies(),
    )


def _migrate_capture_store_with_dependencies(
    *,
    config_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    expected_store_id: str,
    path_policy: PathPolicy,
    dependencies: _MigrationDependencies,
) -> MigrateCaptureStoreOperationResult:
    """Internal deterministic/fault-injection entry point for C6C tests."""

    if not isinstance(dependencies, _MigrationDependencies):
        raise TypeError("dependencies must be _MigrationDependencies")
    return _run_migrate_capture_store(
        config_path=config_path,
        source_root=source_root,
        target_root=target_root,
        expected_store_id=expected_store_id,
        path_policy=path_policy,
        dependencies=dependencies,
    )


__all__ = [
    "MigrateCaptureStoreOperationResult",
    "MigrateCaptureStoreResult",
    "migrate_capture_store",
]
