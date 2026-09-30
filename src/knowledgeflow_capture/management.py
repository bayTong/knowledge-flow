"""Narrow P0B management operations for one local Capture Store.

The four everyday Capture operations remain the only normal content boundary.
This module provides explicit initialization, read-only verification, cold
backup, and restore-to-new-target operations for an operator-controlled window.
It deliberately does not schedule backups, rotate history, switch an active
configuration during restore, or delete failed targets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath
from typing import TypeAlias

from .config import ConfigLoadError, LocalConfig, read_local_config_file
from .durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
)
from .errors import (
    CauseCode,
    FailureResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
)
from .ids import IdKind, generate_job_id, validate_typed_id
from .locking import (
    CaptureWriteLock,
    CaptureWriteLockError,
    _acquire_capture_write_lock,
)
from .manifest import (
    CAPTURE_STORE_LAYOUT_VERSION,
    CAPTURE_STORE_SCHEMA_VERSION,
    CaptureStoreManifest,
    ManifestLoadError,
)
from .migration import (
    _CopySummary,
    _FileRecord,
    _MigrationDependencies,
    _MigrationFaultPoint,
    _MigrationIoFailure,
    _MigrationTargetConflict,
    _StoreSnapshot,
    _assert_exact_snapshot,
    _copy_snapshot,
    _ensure_target_journal,
    _ensure_target_root,
    _is_same_or_within,
    _lstat_if_present,
    _path_key,
    _plain_directory,
    _read_small_file,
    _same_path,
    _snapshot_store,
    _validate_store,
)
from .models import (
    format_utc_milliseconds,
    require_canonical_utc_milliseconds,
    require_sha256,
)
from .operations import (
    _IntegrityFailure,
    _StoreIoFailure,
    _UnsupportedMachineSchema,
)
from .paths import PathPolicy, PathPolicyError
from .store import (
    _InitFailure,
    _inspect_store,
    init_capture_store,
)


DEFAULT_INLINE_TEXT_THRESHOLD_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TEXT_VERSION_BYTES = 64 * 1024 * 1024

CAPTURE_BACKUP_SCHEMA = "knowledgeflow.capture-backup"
CAPTURE_BACKUP_SCHEMA_VERSION = 1
CAPTURE_BACKUP_MANIFEST_FILENAME = "backup.json"
CAPTURE_BACKUP_STORE_DIRECTORY = "capture-store"
CAPTURE_BACKUP_PROTECTION_SCOPE = "operational-copy"
CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES = 64 * 1024 * 1024

_BACKUP_INCLUSION_POLICY: Mapping[str, str] = {
    "derived_state": "included",
    "journal_lock": "excluded",
    "staging_contents": "excluded",
    "uncommitted_item_tails": "included",
}

_LockFactory = Callable[[Path], CaptureWriteLock]
_UtcNow = Callable[[], datetime]
_JobIdFactory = Callable[[], str]
_FileFsync = Callable[[int], None]
_FaultHook = Callable[[], None]


class _ManagementFaultPoint(StrEnum):
    AFTER_BACKUP_FILE_COPIED = "after-backup-file-copied"
    AFTER_RESTORE_FILE_COPIED = "after-restore-file-copied"


def _default_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _noop_fault_hook() -> None:
    return None


@dataclass(frozen=True, slots=True)
class _ManagementDependencies:
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
    job_id_factory: _JobIdFactory = field(
        default=generate_job_id,
        repr=False,
        compare=False,
    )
    transfer_fsync: _FileFsync = field(
        default=os.fsync,
        repr=False,
        compare=False,
    )
    fault_point: _ManagementFaultPoint | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    fault_hook: _FaultHook = field(
        default=_noop_fault_hook,
        repr=False,
        compare=False,
    )


def _require_nonnegative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_text(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class InitializeCaptureStoreResult:
    """Path-free receipt for explicit Store initialization or reopen."""

    store_id: str
    created: bool
    inline_text_threshold_bytes: int
    max_text_version_bytes: int
    warnings: tuple[OperationWarning, ...] = ()

    def __post_init__(self) -> None:
        validate_typed_id(self.store_id, IdKind.STORE)
        if type(self.created) is not bool:
            raise TypeError("created must be boolean")
        inline = _require_positive(
            self.inline_text_threshold_bytes,
            "inline_text_threshold_bytes",
        )
        maximum = _require_positive(
            self.max_text_version_bytes,
            "max_text_version_bytes",
        )
        if inline > maximum:
            raise ValueError("inline threshold must not exceed maximum")
        warnings = tuple(self.warnings)
        if not all(isinstance(value, OperationWarning) for value in warnings):
            raise TypeError("warnings must contain OperationWarning values")
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "store_id": self.store_id,
            "created": self.created,
            "store_initialized": True,
            "config_connected": True,
            "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
            "max_text_version_bytes": self.max_text_version_bytes,
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class VerifyCaptureStoreResult:
    """Path-free receipt for one complete, non-repairing verification."""

    store_id: str
    inline_text_threshold_bytes: int
    max_text_version_bytes: int
    items_verified: int
    versions_verified: int
    directory_count: int
    file_count: int
    byte_count: int
    snapshot_sha256: str

    def __post_init__(self) -> None:
        validate_typed_id(self.store_id, IdKind.STORE)
        inline = _require_positive(
            self.inline_text_threshold_bytes,
            "inline_text_threshold_bytes",
        )
        maximum = _require_positive(
            self.max_text_version_bytes,
            "max_text_version_bytes",
        )
        if inline > maximum:
            raise ValueError("inline threshold must not exceed maximum")
        for name in (
            "items_verified",
            "versions_verified",
            "directory_count",
            "file_count",
            "byte_count",
        ):
            _require_nonnegative(getattr(self, name), name)
        require_sha256(self.snapshot_sha256, "snapshot_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "store_id": self.store_id,
            "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
            "max_text_version_bytes": self.max_text_version_bytes,
            "items_verified": self.items_verified,
            "versions_verified": self.versions_verified,
            "directory_count": self.directory_count,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True, slots=True)
class BackupCaptureStoreResult:
    """Path-free receipt bound to one durable backup Manifest."""

    backup_id: str
    store_id: str
    created_at: str
    inline_text_threshold_bytes: int
    max_text_version_bytes: int
    directory_count: int
    file_count: int
    byte_count: int
    snapshot_sha256: str
    manifest_sha256: str
    protection_scope: str = field(
        default=CAPTURE_BACKUP_PROTECTION_SCOPE,
        init=False,
    )

    def __post_init__(self) -> None:
        validate_typed_id(self.backup_id, IdKind.JOB)
        validate_typed_id(self.store_id, IdKind.STORE)
        require_canonical_utc_milliseconds(self.created_at, "created_at")
        inline = _require_positive(
            self.inline_text_threshold_bytes,
            "inline_text_threshold_bytes",
        )
        maximum = _require_positive(
            self.max_text_version_bytes,
            "max_text_version_bytes",
        )
        if inline > maximum:
            raise ValueError("inline threshold must not exceed maximum")
        for name in ("directory_count", "file_count", "byte_count"):
            _require_nonnegative(getattr(self, name), name)
        require_sha256(self.snapshot_sha256, "snapshot_sha256")
        require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.protection_scope != CAPTURE_BACKUP_PROTECTION_SCOPE:
            raise ValueError("unsupported backup protection scope")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "backup_id": self.backup_id,
            "store_id": self.store_id,
            "created_at": self.created_at,
            "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
            "max_text_version_bytes": self.max_text_version_bytes,
            "directory_count": self.directory_count,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "snapshot_sha256": self.snapshot_sha256,
            "manifest_sha256": self.manifest_sha256,
            "protection_scope": self.protection_scope,
        }


@dataclass(frozen=True, slots=True)
class RestoreCaptureStoreResult:
    """Path-free receipt for restore into a new, unconfigured Store root."""

    backup_id: str
    store_id: str
    backup_created_at: str
    inline_text_threshold_bytes: int
    max_text_version_bytes: int
    items_verified: int
    versions_verified: int
    directory_count: int
    file_count: int
    byte_count: int
    snapshot_sha256: str
    manifest_sha256: str
    config_switched: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        validate_typed_id(self.backup_id, IdKind.JOB)
        validate_typed_id(self.store_id, IdKind.STORE)
        require_canonical_utc_milliseconds(
            self.backup_created_at,
            "backup_created_at",
        )
        inline = _require_positive(
            self.inline_text_threshold_bytes,
            "inline_text_threshold_bytes",
        )
        maximum = _require_positive(
            self.max_text_version_bytes,
            "max_text_version_bytes",
        )
        if inline > maximum:
            raise ValueError("inline threshold must not exceed maximum")
        for name in (
            "items_verified",
            "versions_verified",
            "directory_count",
            "file_count",
            "byte_count",
        ):
            _require_nonnegative(getattr(self, name), name)
        require_sha256(self.snapshot_sha256, "snapshot_sha256")
        require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.config_switched is not False:
            raise ValueError("P0B restore cannot switch configuration")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "backup_id": self.backup_id,
            "store_id": self.store_id,
            "backup_created_at": self.backup_created_at,
            "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
            "max_text_version_bytes": self.max_text_version_bytes,
            "items_verified": self.items_verified,
            "versions_verified": self.versions_verified,
            "directory_count": self.directory_count,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "snapshot_sha256": self.snapshot_sha256,
            "manifest_sha256": self.manifest_sha256,
            "config_switched": self.config_switched,
        }


InitializeCaptureStoreOperationResult: TypeAlias = (
    InitializeCaptureStoreResult | FailureResult
)
VerifyCaptureStoreOperationResult: TypeAlias = VerifyCaptureStoreResult | FailureResult
BackupCaptureStoreOperationResult: TypeAlias = BackupCaptureStoreResult | FailureResult
RestoreCaptureStoreOperationResult: TypeAlias = RestoreCaptureStoreResult | FailureResult


def _require_relative_path(value: object, name: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must be one canonical relative path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"{name} must be one canonical relative path")
    canonical = "/".join(candidate.parts)
    if canonical != value:
        raise ValueError(f"{name} must be one canonical relative path")
    return canonical


@dataclass(frozen=True, slots=True, order=True)
class BackupFileRecord:
    relative_path: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        _require_relative_path(self.relative_path, "relative_path")
        _require_nonnegative(self.byte_size, "byte_size")
        require_sha256(self.sha256, "sha256")

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _snapshot_mapping(
    directories: tuple[str, ...],
    files: tuple[BackupFileRecord, ...],
) -> dict[str, object]:
    return {
        "directories": list(directories),
        "files": [record.as_mapping() for record in files],
    }


def _snapshot_sha256(
    directories: tuple[str, ...],
    files: tuple[BackupFileRecord, ...],
) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json_bytes(_snapshot_mapping(directories, files))
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CaptureBackupManifest:
    backup_id: str
    created_at: str
    store_id: str
    inline_text_threshold_bytes: int
    max_text_version_bytes: int
    directories: tuple[str, ...]
    files: tuple[BackupFileRecord, ...]
    snapshot_sha256: str
    protection_scope: str = field(
        default=CAPTURE_BACKUP_PROTECTION_SCOPE,
        init=False,
    )

    def __post_init__(self) -> None:
        validate_typed_id(self.backup_id, IdKind.JOB)
        validate_typed_id(self.store_id, IdKind.STORE)
        require_canonical_utc_milliseconds(self.created_at, "created_at")
        inline = _require_positive(
            self.inline_text_threshold_bytes,
            "inline_text_threshold_bytes",
        )
        maximum = _require_positive(
            self.max_text_version_bytes,
            "max_text_version_bytes",
        )
        if inline > maximum:
            raise ValueError("inline threshold must not exceed maximum")
        directories = tuple(self.directories)
        if any(
            _require_relative_path(value, "directory") != value
            for value in directories
        ):
            raise ValueError("invalid backup directory")
        if directories != tuple(sorted(set(directories))):
            raise ValueError("backup directories must be unique and sorted")
        files = tuple(self.files)
        if not all(isinstance(value, BackupFileRecord) for value in files):
            raise TypeError("files must contain BackupFileRecord values")
        if files != tuple(sorted(set(files))):
            raise ValueError("backup files must be unique and sorted")
        if len({record.relative_path for record in files}) != len(files):
            raise ValueError("backup file paths must be unique")
        expected_snapshot = _snapshot_sha256(directories, files)
        if self.snapshot_sha256 != expected_snapshot:
            raise ValueError("backup snapshot digest mismatch")
        if self.protection_scope != CAPTURE_BACKUP_PROTECTION_SCOPE:
            raise ValueError("unsupported backup protection scope")
        object.__setattr__(self, "directories", directories)
        object.__setattr__(self, "files", files)

    @property
    def byte_count(self) -> int:
        return sum(record.byte_size for record in self.files)

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": CAPTURE_BACKUP_SCHEMA,
            "schema_version": CAPTURE_BACKUP_SCHEMA_VERSION,
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "protection_scope": self.protection_scope,
            "source": {
                "store_id": self.store_id,
                "store_schema_version": CAPTURE_STORE_SCHEMA_VERSION,
                "store_layout_version": CAPTURE_STORE_LAYOUT_VERSION,
                "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
                "max_text_version_bytes": self.max_text_version_bytes,
            },
            "inclusion_policy": dict(_BACKUP_INCLUSION_POLICY),
            "snapshot": {
                "directory_count": len(self.directories),
                "file_count": len(self.files),
                "byte_count": self.byte_count,
                "snapshot_sha256": self.snapshot_sha256,
                **_snapshot_mapping(self.directories, self.files),
            },
        }


class BackupManifestLoadError(ValueError):
    def __init__(self, code: PublicErrorCode) -> None:
        if code not in {
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        }:
            raise ValueError("invalid backup Manifest error code")
        self.code = code
        super().__init__(code.value)


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _require_exact_keys(
    value: object,
    keys: frozenset[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("backup Manifest fields are invalid")
    if not all(type(key) is str for key in value):
        raise ValueError("backup Manifest keys must be strings")
    return value


def dump_capture_backup_manifest(manifest: CaptureBackupManifest) -> bytes:
    if not isinstance(manifest, CaptureBackupManifest):
        raise TypeError("manifest must be CaptureBackupManifest")
    source = _canonical_json_bytes(manifest.as_mapping())
    if len(source) > CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES:
        raise ValueError("backup Manifest exceeds the P0B metadata limit")
    return source


def _parse_capture_backup_manifest(source: bytes) -> CaptureBackupManifest:
    try:
        parsed = json.loads(
            source.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey, ValueError) as exc:
        raise BackupManifestLoadError(
            PublicErrorCode.INTEGRITY_CHECK_FAILED
        ) from exc
    if isinstance(parsed, Mapping):
        schema = parsed.get("schema")
        schema_version = parsed.get("schema_version")
        if (
            type(schema) is str
            and schema != CAPTURE_BACKUP_SCHEMA
        ) or (
            schema == CAPTURE_BACKUP_SCHEMA
            and type(schema_version) is int
            and schema_version != CAPTURE_BACKUP_SCHEMA_VERSION
        ):
            raise BackupManifestLoadError(
                PublicErrorCode.UNSUPPORTED_STORE_VERSION
            )
    try:
        root = _require_exact_keys(
            parsed,
            frozenset(
                {
                    "schema",
                    "schema_version",
                    "backup_id",
                    "created_at",
                    "protection_scope",
                    "source",
                    "inclusion_policy",
                    "snapshot",
                }
            ),
        )
        if (
            type(root["schema"]) is not str
            or type(root["schema_version"]) is not int
        ):
            raise ValueError("invalid backup schema identity")
        if (
            root["schema"] != CAPTURE_BACKUP_SCHEMA
            or root["schema_version"] != CAPTURE_BACKUP_SCHEMA_VERSION
        ):
            raise BackupManifestLoadError(
                PublicErrorCode.UNSUPPORTED_STORE_VERSION
            )
        if (
            type(root["protection_scope"]) is not str
            or root["protection_scope"] != CAPTURE_BACKUP_PROTECTION_SCOPE
        ):
            raise ValueError("invalid protection scope")
        policy = _require_exact_keys(
            root["inclusion_policy"],
            frozenset(_BACKUP_INCLUSION_POLICY),
        )
        if dict(policy) != dict(_BACKUP_INCLUSION_POLICY):
            raise ValueError("invalid inclusion policy")
        store = _require_exact_keys(
            root["source"],
            frozenset(
                {
                    "store_id",
                    "store_schema_version",
                    "store_layout_version",
                    "inline_text_threshold_bytes",
                    "max_text_version_bytes",
                }
            ),
        )
        if (
            type(store["store_schema_version"]) is not int
            or type(store["store_layout_version"]) is not int
        ):
            raise ValueError("invalid source Store version identity")
        if (
            store["store_schema_version"] != CAPTURE_STORE_SCHEMA_VERSION
            or store["store_layout_version"] != CAPTURE_STORE_LAYOUT_VERSION
        ):
            raise BackupManifestLoadError(
                PublicErrorCode.UNSUPPORTED_STORE_VERSION
            )
        snapshot = _require_exact_keys(
            root["snapshot"],
            frozenset(
                {
                    "directory_count",
                    "file_count",
                    "byte_count",
                    "snapshot_sha256",
                    "directories",
                    "files",
                }
            ),
        )
        directory_values = snapshot["directories"]
        file_values = snapshot["files"]
        if not isinstance(directory_values, list) or not isinstance(file_values, list):
            raise ValueError("backup snapshot lists are invalid")
        directories = tuple(
            _require_relative_path(value, "directory")
            for value in directory_values
        )
        files: list[BackupFileRecord] = []
        for value in file_values:
            record = _require_exact_keys(
                value,
                frozenset({"path", "byte_size", "sha256"}),
            )
            files.append(
                BackupFileRecord(
                    relative_path=_require_relative_path(
                        record["path"],
                        "path",
                    ),
                    byte_size=_require_nonnegative(
                        record["byte_size"],
                        "byte_size",
                    ),
                    sha256=require_sha256(record["sha256"], "sha256"),
                )
            )
        manifest = CaptureBackupManifest(
            backup_id=_require_text(root["backup_id"], "backup_id"),
            created_at=_require_text(root["created_at"], "created_at"),
            store_id=_require_text(store["store_id"], "store_id"),
            inline_text_threshold_bytes=_require_positive(
                store["inline_text_threshold_bytes"],
                "inline_text_threshold_bytes",
            ),
            max_text_version_bytes=_require_positive(
                store["max_text_version_bytes"],
                "max_text_version_bytes",
            ),
            directories=directories,
            files=tuple(files),
            snapshot_sha256=require_sha256(
                snapshot["snapshot_sha256"],
                "snapshot_sha256",
            ),
        )
        if _require_nonnegative(
            snapshot["directory_count"],
            "directory_count",
        ) != len(manifest.directories):
            raise ValueError("directory count mismatch")
        if _require_nonnegative(
            snapshot["file_count"],
            "file_count",
        ) != len(manifest.files):
            raise ValueError("file count mismatch")
        if _require_nonnegative(
            snapshot["byte_count"],
            "byte_count",
        ) != manifest.byte_count:
            raise ValueError("byte count mismatch")
        return manifest
    except BackupManifestLoadError:
        raise
    except (TypeError, ValueError) as exc:
        raise BackupManifestLoadError(
            PublicErrorCode.INTEGRITY_CHECK_FAILED
        ) from exc


def load_capture_backup_manifest(
    source: bytes | bytearray | memoryview,
) -> CaptureBackupManifest:
    if not isinstance(source, (bytes, bytearray, memoryview)):
        raise TypeError("backup Manifest source must be bytes-like")
    raw = bytes(source)
    if len(raw) > CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES:
        raise BackupManifestLoadError(PublicErrorCode.INTEGRITY_CHECK_FAILED)
    manifest = _parse_capture_backup_manifest(raw)
    if dump_capture_backup_manifest(manifest) != raw:
        raise BackupManifestLoadError(PublicErrorCode.INTEGRITY_CHECK_FAILED)
    return manifest


@dataclass(frozen=True, slots=True)
class _ConfiguredStore:
    config_path: Path
    config: LocalConfig
    manifest: CaptureStoreManifest


@dataclass(frozen=True, slots=True)
class _BackupBundle:
    root: Path
    store_root: Path
    manifest: CaptureBackupManifest
    manifest_bytes: bytes = field(repr=False)


class _ManagementTargetConflict(RuntimeError):
    pass


class _ManagementIoFailure(RuntimeError):
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


def _configs_match(first: LocalConfig, second: LocalConfig) -> bool:
    return (
        _path_key(first.capture.root) == _path_key(second.capture.root)
        and first.capture.inline_text_threshold_bytes
        == second.capture.inline_text_threshold_bytes
        and first.capture.max_text_version_bytes
        == second.capture.max_text_version_bytes
    )


def _load_configured_store(
    config_path: str | os.PathLike[str],
    *,
    path_policy: PathPolicy,
) -> _ConfiguredStore:
    if not isinstance(path_policy, PathPolicy):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)
    try:
        selected = path_policy.validate_config_path(config_path)
    except (PathPolicyError, TypeError, ValueError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    config = read_local_config_file(selected, path_policy=path_policy)
    manifest = _inspect_store(config.capture.root)
    if manifest is None:
        raise _InitFailure(
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
                retryable=False,
            )
        )
    return _ConfiguredStore(
        config_path=selected,
        config=config,
        manifest=manifest,
    )


def _configured_store_unchanged(
    initial: _ConfiguredStore,
    current: _ConfiguredStore,
) -> bool:
    return (
        _same_path(initial.config_path, current.config_path)
        and _configs_match(initial.config, current.config)
        and initial.manifest == current.manifest
    )


def _snapshot_records(
    snapshot: _StoreSnapshot,
) -> tuple[tuple[str, ...], tuple[BackupFileRecord, ...]]:
    directories = tuple(
        sorted("/".join(parts) for parts in snapshot.directories)
    )
    files = tuple(
        BackupFileRecord(
            relative_path="/".join(record.relative_parts),
            byte_size=record.byte_size,
            sha256=record.sha256,
        )
        for record in snapshot.files
    )
    return directories, files


def _snapshot_from_manifest(manifest: CaptureBackupManifest) -> _StoreSnapshot:
    return _StoreSnapshot(
        directories=frozenset(
            tuple(value.split("/")) for value in manifest.directories
        ),
        files=tuple(
            _FileRecord(
                relative_parts=tuple(record.relative_path.split("/")),
                byte_size=record.byte_size,
                sha256=record.sha256,
            )
            for record in manifest.files
        ),
    )


def _snapshot_counts(
    snapshot: _StoreSnapshot,
) -> tuple[int, int, int, str]:
    directories, files = _snapshot_records(snapshot)
    return (
        len(directories),
        len(files),
        sum(record.byte_size for record in files),
        _snapshot_sha256(directories, files),
    )


def _require_disjoint_paths(*paths: Path) -> None:
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if (
                _same_path(first, second)
                or _is_same_or_within(first, second)
                or _is_same_or_within(second, first)
            ):
                raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)


def _require_absent_target(path: Path, *, stage: str) -> None:
    try:
        _plain_directory(path.parent, stage=stage)
        existing = _lstat_if_present(path)
    except _MigrationIoFailure as exc:
        raise _ManagementIoFailure from exc
    except OSError as exc:
        raise _ManagementIoFailure from exc
    if existing is not None:
        raise _ManagementTargetConflict


def _create_directory(
    path: Path,
    *,
    dependencies: _ManagementDependencies,
) -> None:
    _require_absent_target(path, stage="management-target-parent")
    try:
        path.mkdir(parents=False, exist_ok=False)
        _plain_directory(path, stage="management-target-create")
        dependencies.durability.flush_directory_metadata(path.parent)
    except FileExistsError as exc:
        raise _ManagementTargetConflict from exc
    except (DurabilityError, OSError, _MigrationIoFailure) as exc:
        raise _ManagementIoFailure from exc


def _transfer_dependencies(
    dependencies: _ManagementDependencies,
    *,
    operation_fault_point: _ManagementFaultPoint,
) -> _MigrationDependencies:
    selected_fault = None
    if dependencies.fault_point == operation_fault_point:
        selected_fault = _MigrationFaultPoint.AFTER_TARGET_FILE_COPIED
    return _MigrationDependencies(
        durability=dependencies.durability,
        fsync=dependencies.transfer_fsync,
        fault_point=selected_fault,
        fault_hook=dependencies.fault_hook,
    )


def _manifest_for_snapshot(
    configured: _ConfiguredStore,
    snapshot: _StoreSnapshot,
    *,
    dependencies: _ManagementDependencies,
) -> CaptureBackupManifest:
    directories, files = _snapshot_records(snapshot)
    backup_id = dependencies.job_id_factory()
    validate_typed_id(backup_id, IdKind.JOB)
    created_at = format_utc_milliseconds(dependencies.utc_now())
    return CaptureBackupManifest(
        backup_id=backup_id,
        created_at=created_at,
        store_id=configured.manifest.store_id,
        inline_text_threshold_bytes=(
            configured.config.capture.inline_text_threshold_bytes
        ),
        max_text_version_bytes=configured.config.capture.max_text_version_bytes,
        directories=directories,
        files=files,
        snapshot_sha256=_snapshot_sha256(directories, files),
    )


def _bundle_entries_are_exact(root: Path) -> bool:
    try:
        entries = tuple(sorted(entry.name for entry in root.iterdir()))
    except OSError:
        return False
    return entries == tuple(
        sorted(
            (
                CAPTURE_BACKUP_MANIFEST_FILENAME,
                CAPTURE_BACKUP_STORE_DIRECTORY,
            )
        )
    )


def _load_backup_bundle(
    backup_root: str | os.PathLike[str],
    *,
    path_policy: PathPolicy,
) -> _BackupBundle:
    if not isinstance(path_policy, PathPolicy):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)
    try:
        root = path_policy.validate_capture_root(backup_root)
        _plain_directory(root, stage="backup-bundle-read")
    except (PathPolicyError, TypeError, ValueError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    except _MigrationIoFailure as exc:
        raise _ManagementIoFailure from exc
    if not _bundle_entries_are_exact(root):
        raise _ManagementTargetConflict
    store_root = root / CAPTURE_BACKUP_STORE_DIRECTORY
    try:
        _plain_directory(store_root, stage="backup-store-read")
        manifest_bytes, _manifest_stat = _read_small_file(
            root / CAPTURE_BACKUP_MANIFEST_FILENAME,
            maximum_bytes=CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES,
            stage="backup-manifest-read",
        )
    except _MigrationIoFailure as exc:
        raise _ManagementIoFailure from exc
    manifest = load_capture_backup_manifest(manifest_bytes)
    return _BackupBundle(
        root=root,
        store_root=store_root,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )


def _verified_backup_snapshot(bundle: _BackupBundle) -> tuple[_StoreSnapshot, int, int]:
    validation = _validate_store(
        bundle.store_root,
        expected_store_id=bundle.manifest.store_id,
    )
    actual = _snapshot_store(bundle.store_root, target=True)
    expected = _snapshot_from_manifest(bundle.manifest)
    _assert_exact_snapshot(actual, expected)
    return actual, validation.items_verified, validation.versions_verified


def initialize_capture_store(
    *,
    config_path: str | os.PathLike[str],
    capture_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    inline_text_threshold_bytes: int = DEFAULT_INLINE_TEXT_THRESHOLD_BYTES,
    max_text_version_bytes: int = DEFAULT_MAX_TEXT_VERSION_BYTES,
) -> InitializeCaptureStoreOperationResult:
    """Initialize or idempotently reopen one explicitly selected Store."""

    result = init_capture_store(
        config_path=config_path,
        capture_root=capture_root,
        inline_text_threshold_bytes=inline_text_threshold_bytes,
        max_text_version_bytes=max_text_version_bytes,
        path_policy=path_policy,
    )
    if isinstance(result, FailureResult):
        return result
    return InitializeCaptureStoreResult(
        store_id=result.store_id,
        created=result.created,
        inline_text_threshold_bytes=inline_text_threshold_bytes,
        max_text_version_bytes=max_text_version_bytes,
        warnings=result.warnings,
    )


def _run_verify_capture_store(
    *,
    config_path: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> VerifyCaptureStoreOperationResult:
    completed: VerifyCaptureStoreResult | None = None
    try:
        initial = _load_configured_store(config_path, path_policy=path_policy)
        with dependencies.lock_factory(initial.config.capture.root):
            current = _load_configured_store(config_path, path_policy=path_policy)
            if not _configured_store_unchanged(initial, current):
                return _failure(PublicErrorCode.CONFIG_STORE_CONFLICT)
            validation = _validate_store(
                current.config.capture.root,
                expected_store_id=current.manifest.store_id,
            )
            snapshot = _snapshot_store(current.config.capture.root, target=False)
            directory_count, file_count, byte_count, digest = _snapshot_counts(
                snapshot
            )
            completed = VerifyCaptureStoreResult(
                store_id=current.manifest.store_id,
                inline_text_threshold_bytes=(
                    current.config.capture.inline_text_threshold_bytes
                ),
                max_text_version_bytes=(
                    current.config.capture.max_text_version_bytes
                ),
                items_verified=validation.items_verified,
                versions_verified=validation.versions_verified,
                directory_count=directory_count,
                file_count=file_count,
                byte_count=byte_count,
                snapshot_sha256=digest,
            )
        if completed is None:
            raise _ManagementIoFailure
        return completed
    except CaptureWriteLockError as exc:
        if completed is not None:
            return completed
        return FailureResult(error=exc.to_operation_error())
    except ConfigLoadError as exc:
        return _failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except ManifestLoadError as exc:
        return _failure(exc.code)
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
            stage="verify-read",
        )
    except _MigrationIoFailure:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="verify-read",
        )
    except (OSError, TypeError, ValueError, _ManagementIoFailure):
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


def verify_capture_store(
    *,
    config_path: str | os.PathLike[str],
    path_policy: PathPolicy,
) -> VerifyCaptureStoreOperationResult:
    """Verify immutable facts, current projections, and one stable tree hash."""

    return _run_verify_capture_store(
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_ManagementDependencies(),
    )


def _run_backup_capture_store(
    *,
    config_path: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> BackupCaptureStoreOperationResult:
    completed: BackupCaptureStoreResult | None = None
    try:
        initial = _load_configured_store(config_path, path_policy=path_policy)
        try:
            target = path_policy.validate_capture_root(backup_root)
        except (PathPolicyError, TypeError, ValueError) as exc:
            raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
        _require_disjoint_paths(
            initial.config_path,
            initial.config.capture.root,
            target,
        )
        _require_absent_target(target, stage="backup-target-parent")

        with dependencies.lock_factory(initial.config.capture.root):
            current = _load_configured_store(config_path, path_policy=path_policy)
            if not _configured_store_unchanged(initial, current):
                return _failure(PublicErrorCode.CONFIG_STORE_CONFLICT)
            source_validation = _validate_store(
                current.config.capture.root,
                expected_store_id=current.manifest.store_id,
            )
            source_snapshot = _snapshot_store(
                current.config.capture.root,
                target=False,
            )
            _require_absent_target(target, stage="backup-target-parent")
            _create_directory(target, dependencies=dependencies)
            target_store = target / CAPTURE_BACKUP_STORE_DIRECTORY
            transfer = _transfer_dependencies(
                dependencies,
                operation_fault_point=(
                    _ManagementFaultPoint.AFTER_BACKUP_FILE_COPIED
                ),
            )
            _ensure_target_root(target_store, dependencies=transfer)
            _ensure_target_journal(target_store, dependencies=transfer)
            with dependencies.lock_factory(target_store):
                copied: _CopySummary = _copy_snapshot(
                    current.config.capture.root,
                    target_store,
                    source_snapshot,
                    dependencies=transfer,
                )
                if copied.files_copied + copied.files_reused != len(
                    source_snapshot.files
                ):
                    raise _ManagementIoFailure
                target_validation = _validate_store(
                    target_store,
                    expected_store_id=current.manifest.store_id,
                )
                if target_validation != source_validation:
                    raise _MigrationTargetConflict
                target_snapshot = _snapshot_store(target_store, target=True)
                _assert_exact_snapshot(target_snapshot, source_snapshot)

                manifest = _manifest_for_snapshot(
                    current,
                    source_snapshot,
                    dependencies=dependencies,
                )
                manifest_bytes = dump_capture_backup_manifest(manifest)
                dependencies.durability.write_new_file_durable(
                    target / CAPTURE_BACKUP_MANIFEST_FILENAME,
                    manifest_bytes,
                    validator=load_capture_backup_manifest,
                )
                if not _bundle_entries_are_exact(target):
                    raise _ManagementTargetConflict
                readback, _ = _read_small_file(
                    target / CAPTURE_BACKUP_MANIFEST_FILENAME,
                    maximum_bytes=CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES,
                    stage="backup-manifest-readback",
                )
                loaded = load_capture_backup_manifest(readback)
                if loaded != manifest:
                    raise _ManagementIoFailure
                completed = BackupCaptureStoreResult(
                    backup_id=manifest.backup_id,
                    store_id=manifest.store_id,
                    created_at=manifest.created_at,
                    inline_text_threshold_bytes=(
                        manifest.inline_text_threshold_bytes
                    ),
                    max_text_version_bytes=manifest.max_text_version_bytes,
                    directory_count=len(manifest.directories),
                    file_count=len(manifest.files),
                    byte_count=manifest.byte_count,
                    snapshot_sha256=manifest.snapshot_sha256,
                    manifest_sha256=(
                        "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
                    ),
                )
        if completed is None:
            raise _ManagementIoFailure
        return completed
    except CaptureWriteLockError as exc:
        if completed is not None:
            return completed
        return FailureResult(error=exc.to_operation_error())
    except ConfigLoadError as exc:
        return _failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except ManifestLoadError as exc:
        return _failure(exc.code)
    except PathPolicyError:
        return _failure(PublicErrorCode.CONFIG_INVALID)
    except _ManagementTargetConflict:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="backup-target-conflict",
        )
    except _MigrationTargetConflict:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="backup-target-conflict",
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
            stage="backup-read",
        )
    except (_MigrationIoFailure, _ManagementIoFailure):
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="backup-copy",
        )
    except DurabilityError as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage="backup-durability",
        )
    except DestinationAlreadyExistsError:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="backup-target-race",
        )
    except (OSError, TypeError, ValueError):
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


def backup_capture_store(
    *,
    config_path: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    path_policy: PathPolicy,
) -> BackupCaptureStoreOperationResult:
    """Create one validated cold backup at a previously absent target leaf."""

    return _run_backup_capture_store(
        config_path=config_path,
        backup_root=backup_root,
        path_policy=path_policy,
        dependencies=_ManagementDependencies(),
    )


def _run_restore_capture_store(
    *,
    backup_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> RestoreCaptureStoreOperationResult:
    completed: RestoreCaptureStoreResult | None = None
    try:
        bundle = _load_backup_bundle(backup_root, path_policy=path_policy)
        try:
            target = path_policy.validate_capture_root(target_root)
        except (PathPolicyError, TypeError, ValueError) as exc:
            raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
        _require_disjoint_paths(bundle.root, target)
        _require_absent_target(target, stage="restore-target-parent")

        with dependencies.lock_factory(bundle.store_root):
            current_bundle = _load_backup_bundle(
                backup_root,
                path_policy=path_policy,
            )
            if (
                current_bundle.manifest_bytes != bundle.manifest_bytes
                or current_bundle.manifest != bundle.manifest
            ):
                return _failure(PublicErrorCode.INTEGRITY_CHECK_FAILED)
            source_snapshot, source_items, source_versions = (
                _verified_backup_snapshot(current_bundle)
            )
            _require_absent_target(target, stage="restore-target-parent")
            transfer = _transfer_dependencies(
                dependencies,
                operation_fault_point=(
                    _ManagementFaultPoint.AFTER_RESTORE_FILE_COPIED
                ),
            )
            _ensure_target_root(target, dependencies=transfer)
            _ensure_target_journal(target, dependencies=transfer)
            with dependencies.lock_factory(target):
                _copy_snapshot(
                    current_bundle.store_root,
                    target,
                    source_snapshot,
                    dependencies=transfer,
                )
                target_validation = _validate_store(
                    target,
                    expected_store_id=current_bundle.manifest.store_id,
                )
                if (
                    target_validation.items_verified != source_items
                    or target_validation.versions_verified != source_versions
                ):
                    raise _MigrationTargetConflict
                target_snapshot = _snapshot_store(target, target=True)
                _assert_exact_snapshot(target_snapshot, source_snapshot)
                manifest = current_bundle.manifest
                completed = RestoreCaptureStoreResult(
                    backup_id=manifest.backup_id,
                    store_id=manifest.store_id,
                    backup_created_at=manifest.created_at,
                    inline_text_threshold_bytes=(
                        manifest.inline_text_threshold_bytes
                    ),
                    max_text_version_bytes=manifest.max_text_version_bytes,
                    items_verified=target_validation.items_verified,
                    versions_verified=target_validation.versions_verified,
                    directory_count=len(manifest.directories),
                    file_count=len(manifest.files),
                    byte_count=manifest.byte_count,
                    snapshot_sha256=manifest.snapshot_sha256,
                    manifest_sha256=(
                        "sha256:"
                        + hashlib.sha256(current_bundle.manifest_bytes).hexdigest()
                    ),
                )
        if completed is None:
            raise _ManagementIoFailure
        return completed
    except CaptureWriteLockError as exc:
        if completed is not None:
            return completed
        return FailureResult(error=exc.to_operation_error())
    except ConfigLoadError as exc:
        return _failure(exc.code)
    except BackupManifestLoadError as exc:
        return _failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except ManifestLoadError as exc:
        return _failure(exc.code)
    except PathPolicyError:
        return _failure(PublicErrorCode.CONFIG_INVALID)
    except _ManagementTargetConflict:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="restore-target-conflict",
        )
    except _MigrationTargetConflict:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="restore-target-conflict",
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
            stage="restore-read",
        )
    except (_MigrationIoFailure, _ManagementIoFailure):
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="restore-copy",
        )
    except DurabilityError as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage="restore-durability",
        )
    except DestinationAlreadyExistsError:
        return _failure(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            stage="restore-target-race",
        )
    except (OSError, TypeError, ValueError):
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


def restore_capture_store(
    *,
    backup_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    path_policy: PathPolicy,
) -> RestoreCaptureStoreOperationResult:
    """Restore one verified backup to a new Store without switching config."""

    return _run_restore_capture_store(
        backup_root=backup_root,
        target_root=target_root,
        path_policy=path_policy,
        dependencies=_ManagementDependencies(),
    )


def _verify_capture_store_with_dependencies(
    *,
    config_path: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> VerifyCaptureStoreOperationResult:
    return _run_verify_capture_store(
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


def _backup_capture_store_with_dependencies(
    *,
    config_path: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> BackupCaptureStoreOperationResult:
    return _run_backup_capture_store(
        config_path=config_path,
        backup_root=backup_root,
        path_policy=path_policy,
        dependencies=dependencies,
    )


def _restore_capture_store_with_dependencies(
    *,
    backup_root: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    dependencies: _ManagementDependencies,
) -> RestoreCaptureStoreOperationResult:
    return _run_restore_capture_store(
        backup_root=backup_root,
        target_root=target_root,
        path_policy=path_policy,
        dependencies=dependencies,
    )


__all__ = [
    "BackupCaptureStoreOperationResult",
    "BackupCaptureStoreResult",
    "BackupFileRecord",
    "BackupManifestLoadError",
    "CAPTURE_BACKUP_MANIFEST_FILENAME",
    "CAPTURE_BACKUP_MANIFEST_MAXIMUM_BYTES",
    "CAPTURE_BACKUP_PROTECTION_SCOPE",
    "CAPTURE_BACKUP_SCHEMA",
    "CAPTURE_BACKUP_SCHEMA_VERSION",
    "CAPTURE_BACKUP_STORE_DIRECTORY",
    "CaptureBackupManifest",
    "DEFAULT_INLINE_TEXT_THRESHOLD_BYTES",
    "DEFAULT_MAX_TEXT_VERSION_BYTES",
    "InitializeCaptureStoreOperationResult",
    "InitializeCaptureStoreResult",
    "RestoreCaptureStoreOperationResult",
    "RestoreCaptureStoreResult",
    "VerifyCaptureStoreOperationResult",
    "VerifyCaptureStoreResult",
    "backup_capture_store",
    "dump_capture_backup_manifest",
    "initialize_capture_store",
    "load_capture_backup_manifest",
    "restore_capture_store",
    "verify_capture_store",
]
