"""Safe initialization and recognition of a local Capture Store v1."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
from uuid import RFC_4122, UUID

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
from .errors import FailureResult, OperationError, OperationWarning, PublicErrorCode
from .ids import generate_store_id, generate_uuid7, validate_typed_id, IdKind
from .locking import (
    InitializationLock,
    InitializationLockError,
    acquire_initialization_lock,
)
from .manifest import (
    CAPTURE_STORE_LAYOUT_VERSION,
    CAPTURE_STORE_SCHEMA_VERSION,
    CaptureStoreManifest,
    ManifestLoadError,
    dump_capture_store_manifest,
    load_capture_store_manifest,
)
from .paths import PathPolicy, PathPolicyError


CAPTURE_STORE_MANIFEST_FILENAME = "capture-store.yaml"
CAPTURE_STORE_REQUIRED_DIRECTORIES: tuple[tuple[str, ...], ...] = (
    ("items",),
    ("outbox",),
    ("outbox", "pending"),
    ("outbox", "running"),
    ("outbox", "failed"),
    ("outbox", "completed"),
    ("indexes",),
    ("indexes", "idempotency"),
    (".staging",),
    ("journal",),
)

_INIT_TRANSACTION_SCHEMA_NAME = "knowledgeflow.init-transaction"
_INIT_TRANSACTION_SCHEMA_VERSION = 1
_INIT_TRANSACTION_PREFIX = ".knowledgeflow-init-"
_CONFIG_TEMP_PREFIX = ".knowledgeflow-config-"
_CONFIG_TEMP_SUFFIX = ".tmp"
_INIT_REQUEST_DOMAIN = b"knowledgeflow.init-request.v1\n"
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_LockFactory = Callable[[Path], InitializationLock]
_UtcNow = Callable[[], datetime]
_StoreIdFactory = Callable[[], str]
_UuidFactory = Callable[[], UUID]
_FaultHook = Callable[[], None]


class _InitFaultPoint(StrEnum):
    """Internal crash-injection points for initialization recovery tests.

    Never selectable through YAML, environment variables, CLI, or any public
    parameter; production dependencies leave ``fault_point`` unset so every
    hook invocation stays a no-op.
    """

    AFTER_INIT_TEMP_CREATED = "after_init_temp_created"
    AFTER_MANIFEST_WRITTEN = "after_manifest_written"
    AFTER_MANIFEST_FLUSHED = "after_manifest_flushed"
    AFTER_ROOT_RENAMED = "after_root_renamed"
    BEFORE_CONFIG_REPLACED = "before_config_replaced"
    AFTER_CONFIG_REPLACED = "after_config_replaced"


def _noop_fault_hook() -> None:
    return None


@dataclass(frozen=True, slots=True)
class InitStoreResult:
    created: bool
    store_id: str
    capture_root: Path
    warnings: tuple[OperationWarning, ...] = ()
    store_initialized: bool = field(default=True, init=False)
    config_connected: bool = field(default=True, init=False)
    schema_version: int = field(
        default=CAPTURE_STORE_SCHEMA_VERSION,
        init=False,
    )
    layout_version: int = field(
        default=CAPTURE_STORE_LAYOUT_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if type(self.created) is not bool:
            raise TypeError("created must be boolean")
        validate_typed_id(self.store_id, IdKind.STORE)
        if not isinstance(self.capture_root, Path):
            raise TypeError("capture_root must be pathlib.Path")
        warnings = tuple(self.warnings)
        if not all(isinstance(warning, OperationWarning) for warning in warnings):
            raise TypeError("warnings must contain OperationWarning values")
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "store_initialized": self.store_initialized,
            "config_connected": self.config_connected,
            "created": self.created,
            "store_id": self.store_id,
            "capture_root": str(self.capture_root),
            "schema_version": self.schema_version,
            "layout_version": self.layout_version,
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


InitStoreOperationResult = InitStoreResult | FailureResult


@dataclass(frozen=True, slots=True)
class _InitRequest:
    config_path: Path
    capture_root: Path
    local_config: LocalConfig
    request_sha256: str


@dataclass(frozen=True, slots=True)
class _InitTransaction:
    transaction_id: str
    request_sha256: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": _INIT_TRANSACTION_SCHEMA_NAME,
            "schema_version": _INIT_TRANSACTION_SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
            "request_sha256": self.request_sha256,
        }


def _default_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _trigger_fault(
    point: _InitFaultPoint,
    dependencies: _StoreDependencies,
) -> None:
    if dependencies.fault_point == point:
        dependencies.fault_hook()


@dataclass(frozen=True, slots=True)
class _StoreDependencies:
    durability: DurabilityBackend = field(default_factory=DurabilityBackend)
    lock_factory: _LockFactory = field(
        default=acquire_initialization_lock,
        repr=False,
        compare=False,
    )
    utc_now: _UtcNow = field(
        default=_default_utc_now,
        repr=False,
        compare=False,
    )
    store_id_factory: _StoreIdFactory = field(
        default=generate_store_id,
        repr=False,
        compare=False,
    )
    uuid_factory: _UuidFactory = field(
        default=generate_uuid7,
        repr=False,
        compare=False,
    )
    fault_point: _InitFaultPoint | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    fault_hook: _FaultHook = field(
        default=_noop_fault_hook,
        repr=False,
        compare=False,
    )


class _InitFailure(RuntimeError):
    def __init__(self, error: OperationError) -> None:
        self.error = error
        super().__init__(error.code.value)


def _fail(
    code: PublicErrorCode,
    *,
    retryable: bool = False,
    stage: str | None = None,
) -> None:
    details: dict[str, object] = {}
    if stage is not None:
        details["stage"] = stage
    raise _InitFailure(
        OperationError(
            code=code,
            retryable=retryable,
            details=details,
        )
    )


def _field(name: str, schema: ValueSchema) -> SchemaField:
    return SchemaField(name, schema)


def _validate_uuid7_text(value: str) -> None:
    if type(value) is not str or value != value.lower():
        raise ValueError("transaction UUID must be canonical lowercase text")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("transaction UUID is invalid") from exc
    if str(parsed) != value or parsed.version != 7 or parsed.variant != RFC_4122:
        raise ValueError("transaction UUID must be canonical UUIDv7")


def _validate_transaction(value: object, path: str) -> None:
    transaction = value
    if not isinstance(transaction, Mapping):
        raise SchemaValidationError(f"{path} must be a mapping")
    try:
        _validate_uuid7_text(transaction["transaction_id"])
    except ValueError as exc:
        raise SchemaValidationError(
            f"{path}.transaction_id must be canonical UUIDv7"
        ) from exc


_INIT_TRANSACTION_SCHEMA_V1 = MappingSchema(
    (
        _field(
            "schema",
            ScalarSchema(str, allowed_values=(_INIT_TRANSACTION_SCHEMA_NAME,)),
        ),
        _field(
            "schema_version",
            ScalarSchema(
                int,
                allowed_values=(_INIT_TRANSACTION_SCHEMA_VERSION,),
            ),
        ),
        _field("transaction_id", ScalarSchema(str, nonempty=True)),
        _field("request_sha256", ScalarSchema(str, pattern=_SHA256_PATTERN)),
    ),
    validator=_validate_transaction,
)


def _dump_init_transaction(transaction: _InitTransaction) -> bytes:
    return dump_restricted_yaml(
        transaction.as_mapping(),
        _INIT_TRANSACTION_SCHEMA_V1,
    )


def _load_init_transaction(source: bytes) -> _InitTransaction:
    try:
        parsed = parse_restricted_yaml(source)
        normalized = validate_document(parsed, _INIT_TRANSACTION_SCHEMA_V1)
        transaction = _InitTransaction(
            transaction_id=normalized["transaction_id"],
            request_sha256=normalized["request_sha256"],
        )
        if _dump_init_transaction(transaction) != source:
            raise ValueError("transaction marker is not canonical")
        return transaction
    except (YamlSyntaxGateError, SchemaValidationError, TypeError, ValueError) as exc:
        raise ValueError("transaction marker is invalid") from exc


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _lstat_if_present(path: Path) -> os.stat_result | None:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        _fail(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE, stage="path-stat")


def _plain_directory_stat(
    path: Path,
    *,
    invalid_code: PublicErrorCode,
    stage: str | None = None,
) -> os.stat_result:
    path_stat = _lstat_if_present(path)
    if path_stat is None:
        _fail(invalid_code, stage=stage)
    if not stat.S_ISDIR(path_stat.st_mode) or _is_reparse_point(path_stat):
        _fail(invalid_code, stage=stage)
    return path_stat


def _path_key(path: Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def _is_same_or_within(path: Path, parent: Path) -> bool:
    path_key = _path_key(path)
    parent_key = _path_key(parent)
    try:
        return ntpath.commonpath((path_key, parent_key)) == parent_key
    except ValueError:
        return False


def _initialization_request_sha256(
    *,
    config_path: Path,
    capture_root: Path,
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
) -> str:
    canonical = json.dumps(
        {
            "capture_root": _path_key(capture_root),
            "config_path": _path_key(config_path),
            "inline_text_threshold_bytes": inline_text_threshold_bytes,
            "max_text_version_bytes": max_text_version_bytes,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(_INIT_REQUEST_DOMAIN + canonical).hexdigest()


def _ensure_config_parent(
    config_path: Path,
    dependencies: _StoreDependencies,
) -> None:
    parent = config_path.parent
    parent_stat = _lstat_if_present(parent)
    if parent_stat is not None:
        if not stat.S_ISDIR(parent_stat.st_mode) or _is_reparse_point(parent_stat):
            _fail(PublicErrorCode.CONFIG_INVALID, stage="config-parent-type")
        return

    _plain_directory_stat(
        parent.parent,
        invalid_code=PublicErrorCode.CONFIG_INVALID,
        stage="config-parent-ancestor",
    )
    try:
        parent.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        _plain_directory_stat(
            parent,
            invalid_code=PublicErrorCode.CONFIG_INVALID,
            stage="config-parent-race-type",
        )
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-parent-create",
        )
    dependencies.durability.flush_directory_metadata(parent.parent)


def _prepare_request(
    *,
    config_path: str | os.PathLike[str],
    capture_root: str | os.PathLike[str],
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
    path_policy: PathPolicy,
    dependencies: _StoreDependencies,
    create_config_parent: bool,
) -> _InitRequest:
    if not isinstance(path_policy, PathPolicy):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="path-policy-type")
    try:
        resolved_config_path = path_policy.validate_config_path(config_path)
    except (PathPolicyError, TypeError, ValueError):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="config-path-resolve")
    try:
        local_config = create_local_config(
            root=capture_root,
            inline_text_threshold_bytes=inline_text_threshold_bytes,
            max_text_version_bytes=max_text_version_bytes,
            path_policy=path_policy,
        )
    except (ConfigLoadError, PathPolicyError, TypeError, ValueError):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="capture-config")

    resolved_capture_root = local_config.capture.root
    if _is_same_or_within(resolved_config_path, resolved_capture_root):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="config-inside-store")
    _plain_directory_stat(
        resolved_capture_root.parent,
        invalid_code=PublicErrorCode.CONFIG_INVALID,
        stage="store-parent",
    )
    if create_config_parent:
        _ensure_config_parent(resolved_config_path, dependencies)
    else:
        _plain_directory_stat(
            resolved_config_path.parent,
            invalid_code=PublicErrorCode.CONFIG_INVALID,
            stage="config-parent-locked",
        )

    config_stat = _lstat_if_present(resolved_config_path)
    if config_stat is not None and (
        not stat.S_ISREG(config_stat.st_mode) or _is_reparse_point(config_stat)
    ):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="config-file-type")

    return _InitRequest(
        config_path=resolved_config_path,
        capture_root=resolved_capture_root,
        local_config=local_config,
        request_sha256=_initialization_request_sha256(
            config_path=resolved_config_path,
            capture_root=resolved_capture_root,
            inline_text_threshold_bytes=inline_text_threshold_bytes,
            max_text_version_bytes=max_text_version_bytes,
        ),
    )


def _requests_match(first: _InitRequest, second: _InitRequest) -> bool:
    return (
        _path_key(first.config_path) == _path_key(second.config_path)
        and _path_key(first.capture_root) == _path_key(second.capture_root)
        and first.local_config == second.local_config
        and first.request_sha256 == second.request_sha256
    )


def _configs_match(first: LocalConfig, second: LocalConfig) -> bool:
    return (
        _path_key(first.capture.root) == _path_key(second.capture.root)
        and first.capture.inline_text_threshold_bytes
        == second.capture.inline_text_threshold_bytes
        and first.capture.max_text_version_bytes
        == second.capture.max_text_version_bytes
    )


def _read_config(
    config_path: Path,
    *,
    path_policy: PathPolicy,
) -> LocalConfig | None:
    config_stat = _lstat_if_present(config_path)
    if config_stat is None:
        return None
    if not stat.S_ISREG(config_stat.st_mode) or _is_reparse_point(config_stat):
        _fail(PublicErrorCode.CONFIG_INVALID, stage="config-read-type")
    try:
        source = config_path.read_bytes()
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-read",
        )
    try:
        return parse_local_config(source, path_policy=path_policy)
    except ConfigLoadError:
        _fail(PublicErrorCode.CONFIG_INVALID, stage="config-parse")


def _inspect_store(capture_root: Path) -> CaptureStoreManifest | None:
    root_stat = _lstat_if_present(capture_root)
    if root_stat is None:
        return None
    if not stat.S_ISDIR(root_stat.st_mode) or _is_reparse_point(root_stat):
        _fail(PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY)

    manifest_path = capture_root / CAPTURE_STORE_MANIFEST_FILENAME
    manifest_stat = _lstat_if_present(manifest_path)
    if manifest_stat is None or not stat.S_ISREG(manifest_stat.st_mode) or (
        _is_reparse_point(manifest_stat)
    ):
        _fail(PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY)
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="manifest-read",
        )
    try:
        manifest = load_capture_store_manifest(manifest_bytes)
    except ManifestLoadError as exc:
        _fail(exc.code)

    for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
        candidate = capture_root.joinpath(*parts)
        candidate_stat = _lstat_if_present(candidate)
        if candidate_stat is None or not stat.S_ISDIR(candidate_stat.st_mode) or (
            _is_reparse_point(candidate_stat)
        ):
            _fail(PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED)
    return manifest


def _canonical_uuid_from_factory(factory: _UuidFactory) -> str:
    value = factory()
    if not isinstance(value, UUID):
        raise TypeError("uuid_factory must return UUID")
    text = str(value)
    _validate_uuid7_text(text)
    return text


def _created_at(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TypeError("utc_now must return an aware datetime")
    utc = now.astimezone(timezone.utc)
    milliseconds = (utc.microsecond // 1000) * 1000
    return utc.replace(microsecond=milliseconds).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _create_directory(path: Path, dependencies: _StoreDependencies) -> None:
    try:
        path.mkdir(parents=False, exist_ok=False)
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="directory-create",
        )
    dependencies.durability.flush_directory_metadata(path.parent)


def _transaction_path(
    parent: Path,
    dependencies: _StoreDependencies,
) -> tuple[str, Path]:
    for _attempt in range(8):
        transaction_id = _canonical_uuid_from_factory(dependencies.uuid_factory)
        path = parent / f"{_INIT_TRANSACTION_PREFIX}{transaction_id}"
        try:
            path.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        except OSError:
            _fail(
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                stage="transaction-create",
            )
        dependencies.durability.flush_directory_metadata(parent)
        return transaction_id, path
    _fail(
        PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        stage="transaction-collision",
    )


def _build_staged_store(
    request: _InitRequest,
    dependencies: _StoreDependencies,
    *,
    transaction_id: str,
    transaction_path: Path,
) -> CaptureStoreManifest:
    transaction = _InitTransaction(
        transaction_id=transaction_id,
        request_sha256=request.request_sha256,
    )
    transaction_bytes = _dump_init_transaction(transaction)
    dependencies.durability.write_new_file_durable(
        transaction_path / "transaction.yaml",
        transaction_bytes,
        validator=_load_init_transaction,
    )

    staged_store = transaction_path / "store"
    _create_directory(staged_store, dependencies)
    _trigger_fault(_InitFaultPoint.AFTER_INIT_TEMP_CREATED, dependencies)
    for parts in CAPTURE_STORE_REQUIRED_DIRECTORIES:
        _create_directory(staged_store.joinpath(*parts), dependencies)

    store_id = dependencies.store_id_factory()
    validate_typed_id(store_id, IdKind.STORE)
    manifest = CaptureStoreManifest(
        store_id=store_id,
        created_at=_created_at(dependencies.utc_now()),
    )
    manifest_bytes = dump_capture_store_manifest(manifest)
    dependencies.durability.write_new_file_durable(
        staged_store / CAPTURE_STORE_MANIFEST_FILENAME,
        manifest_bytes,
        validator=load_capture_store_manifest,
        _before_flush=lambda _path: _trigger_fault(
            _InitFaultPoint.AFTER_MANIFEST_WRITTEN,
            dependencies,
        ),
    )
    _trigger_fault(_InitFaultPoint.AFTER_MANIFEST_FLUSHED, dependencies)
    staged_manifest = _inspect_store(staged_store)
    if staged_manifest != manifest:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="staged-store-verify",
        )
    return manifest


def _safe_transaction_tree(
    transaction_path: Path,
    *,
    expected_request_sha256: str,
) -> tuple[tuple[Path, os.stat_result], tuple[tuple[Path, os.stat_result], ...]] | None:
    transaction_stat = _lstat_if_present(transaction_path)
    if transaction_stat is None or not stat.S_ISDIR(transaction_stat.st_mode) or (
        _is_reparse_point(transaction_stat)
    ):
        return None
    name = transaction_path.name
    if not name.startswith(_INIT_TRANSACTION_PREFIX):
        return None
    transaction_id = name[len(_INIT_TRANSACTION_PREFIX) :]
    try:
        _validate_uuid7_text(transaction_id)
    except ValueError:
        return None

    marker_path = transaction_path / "transaction.yaml"
    marker_stat = _lstat_if_present(marker_path)
    if marker_stat is None or not stat.S_ISREG(marker_stat.st_mode) or (
        _is_reparse_point(marker_stat)
    ):
        return None
    try:
        marker = _load_init_transaction(marker_path.read_bytes())
    except (OSError, ValueError):
        return None
    if (
        marker.transaction_id != transaction_id
        or marker.request_sha256 != expected_request_sha256
    ):
        return None

    allowed: dict[tuple[str, ...], dict[str, str]] = {
        (): {"transaction.yaml": "file", "store": "directory"},
        ("store",): {
            CAPTURE_STORE_MANIFEST_FILENAME: "file",
            "items": "directory",
            "outbox": "directory",
            "indexes": "directory",
            ".staging": "directory",
            "journal": "directory",
        },
        ("store", "items"): {},
        ("store", "outbox"): {
            "pending": "directory",
            "running": "directory",
            "failed": "directory",
            "completed": "directory",
        },
        ("store", "outbox", "pending"): {},
        ("store", "outbox", "running"): {},
        ("store", "outbox", "failed"): {},
        ("store", "outbox", "completed"): {},
        ("store", "indexes"): {"idempotency": "directory"},
        ("store", "indexes", "idempotency"): {},
        ("store", ".staging"): {},
        ("store", "journal"): {},
    }
    files: list[tuple[Path, os.stat_result]] = [(marker_path, marker_stat)]
    directories: list[tuple[Path, os.stat_result]] = []

    def visit(relative: tuple[str, ...], directory: Path) -> bool:
        try:
            entries = tuple(directory.iterdir())
        except OSError:
            return False
        rules = allowed[relative]
        for entry in entries:
            expected_kind = rules.get(entry.name)
            if expected_kind is None:
                return False
            entry_stat = _lstat_if_present(entry)
            if entry_stat is None or _is_reparse_point(entry_stat):
                return False
            child_relative = relative + (entry.name,)
            if expected_kind == "file":
                if not stat.S_ISREG(entry_stat.st_mode):
                    return False
                if entry != marker_path:
                    files.append((entry, entry_stat))
            else:
                if not stat.S_ISDIR(entry_stat.st_mode):
                    return False
                directories.append((entry, entry_stat))
                if not visit(child_relative, entry):
                    return False
        return True

    if not visit((), transaction_path):
        return None
    directories.append((transaction_path, transaction_stat))
    return tuple(files), tuple(directories)


def _same_identity(path: Path, expected: os.stat_result) -> bool:
    current = _lstat_if_present(path)
    return current is not None and (
        current.st_dev == expected.st_dev
        and current.st_ino == expected.st_ino
        and current.st_mode == expected.st_mode
        and not _is_reparse_point(current)
    )


def _remove_owned_transaction(
    transaction_path: Path,
    *,
    expected_request_sha256: str,
    dependencies: _StoreDependencies,
) -> bool:
    safe_tree = _safe_transaction_tree(
        transaction_path,
        expected_request_sha256=expected_request_sha256,
    )
    if safe_tree is None:
        return False
    files, directories = safe_tree
    try:
        if not all(_same_identity(path, path_stat) for path, path_stat in files):
            return False
        if not all(
            _same_identity(path, path_stat) for path, path_stat in directories
        ):
            return False
        for path, expected_stat in files:
            if not _same_identity(path, expected_stat):
                return False
            path.unlink()
        for path, expected_stat in sorted(
            directories,
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            if not _same_identity(path, expected_stat):
                return False
            path.rmdir()
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="transaction-cleanup",
        )
    dependencies.durability.flush_directory_metadata(transaction_path.parent)
    return True


def _valid_uuid_name(value: str) -> bool:
    try:
        _validate_uuid7_text(value)
    except ValueError:
        return False
    return True


def _cleanup_transaction_candidates(
    request: _InitRequest,
    dependencies: _StoreDependencies,
) -> None:
    try:
        candidates = tuple(request.capture_root.parent.iterdir())
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="transaction-scan",
        )
    for candidate in candidates:
        if not candidate.name.startswith(_INIT_TRANSACTION_PREFIX):
            continue
        suffix = candidate.name[len(_INIT_TRANSACTION_PREFIX) :]
        if not _valid_uuid_name(suffix):
            continue
        _remove_owned_transaction(
            candidate,
            expected_request_sha256=request.request_sha256,
            dependencies=dependencies,
        )


def _config_temp_id(name: str) -> str | None:
    if not name.startswith(_CONFIG_TEMP_PREFIX) or not name.endswith(
        _CONFIG_TEMP_SUFFIX
    ):
        return None
    value = name[len(_CONFIG_TEMP_PREFIX) : -len(_CONFIG_TEMP_SUFFIX)]
    if not _valid_uuid_name(value):
        return None
    return value


def _remove_exact_config_temp(
    path: Path,
    *,
    expected_bytes: bytes,
    dependencies: _StoreDependencies,
) -> bool:
    path_stat = _lstat_if_present(path)
    if path_stat is None or not stat.S_ISREG(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        return False
    try:
        actual = path.read_bytes()
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-temp-read",
        )
    if actual != expected_bytes or not _same_identity(path, path_stat):
        return False
    try:
        path.unlink()
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-temp-cleanup",
        )
    dependencies.durability.flush_directory_metadata(path.parent)
    return True


def _cleanup_config_temp_candidates(
    request: _InitRequest,
    dependencies: _StoreDependencies,
) -> None:
    expected_bytes = dump_local_config(request.local_config)
    try:
        candidates = tuple(request.config_path.parent.iterdir())
    except OSError:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-temp-scan",
        )
    for candidate in candidates:
        if _config_temp_id(candidate.name) is None:
            continue
        _remove_exact_config_temp(
            candidate,
            expected_bytes=expected_bytes,
            dependencies=dependencies,
        )


def _cleanup_recovery_candidates(
    request: _InitRequest,
    dependencies: _StoreDependencies,
) -> None:
    _cleanup_transaction_candidates(request, dependencies)
    _cleanup_config_temp_candidates(request, dependencies)


def _cleanup_current_transaction(
    transaction_path: Path,
    request: _InitRequest,
    dependencies: _StoreDependencies,
) -> None:
    removed = _remove_owned_transaction(
        transaction_path,
        expected_request_sha256=request.request_sha256,
        dependencies=dependencies,
    )
    if not removed:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="transaction-cleanup-identity",
        )


def _cleanup_current_config_temp(
    path: Path,
    *,
    expected_bytes: bytes,
    dependencies: _StoreDependencies,
) -> None:
    if _lstat_if_present(path) is None:
        return
    removed = _remove_exact_config_temp(
        path,
        expected_bytes=expected_bytes,
        dependencies=dependencies,
    )
    if not removed:
        _fail(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="config-temp-cleanup-identity",
        )


def _create_or_adopt_store(
    request: _InitRequest,
    dependencies: _StoreDependencies,
) -> tuple[CaptureStoreManifest, bool]:
    transaction_path: Path | None = None
    try:
        transaction_id, transaction_path = _transaction_path(
            request.capture_root.parent,
            dependencies,
        )
        staged_manifest = _build_staged_store(
            request,
            dependencies,
            transaction_id=transaction_id,
            transaction_path=transaction_path,
        )
        staged_store = transaction_path / "store"
        try:
            dependencies.durability.commit_directory_no_replace(
                staged_store,
                request.capture_root,
            )
            created = True
        except DestinationAlreadyExistsError:
            created = False
        if created:
            _trigger_fault(_InitFaultPoint.AFTER_ROOT_RENAMED, dependencies)

        final_manifest = _inspect_store(request.capture_root)
        if final_manifest is None:
            _fail(
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                stage="final-store-missing",
            )
        if created and final_manifest != staged_manifest:
            _fail(
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                stage="final-store-identity",
            )
        _cleanup_current_transaction(transaction_path, request, dependencies)
        transaction_path = None
        return final_manifest, created
    except Exception:
        if transaction_path is not None:
            _cleanup_current_transaction(transaction_path, request, dependencies)
        raise


def _new_config_temp_path(
    request: _InitRequest,
    expected_bytes: bytes,
    *,
    path_policy: PathPolicy,
    dependencies: _StoreDependencies,
) -> Path:
    for _attempt in range(8):
        transaction_id = _canonical_uuid_from_factory(dependencies.uuid_factory)
        path = request.config_path.parent / (
            f"{_CONFIG_TEMP_PREFIX}{transaction_id}{_CONFIG_TEMP_SUFFIX}"
        )
        try:
            dependencies.durability.write_new_file_durable(
                path,
                expected_bytes,
                validator=lambda source: parse_local_config(
                    source,
                    path_policy=path_policy,
                ),
            )
        except DestinationAlreadyExistsError:
            continue
        return path
    _fail(
        PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
        stage="config-temp-collision",
    )

def _connect_config(
    request: _InitRequest,
    *,
    path_policy: PathPolicy,
    dependencies: _StoreDependencies,
) -> None:
    expected_bytes = dump_local_config(request.local_config)
    config_temp = _new_config_temp_path(
        request,
        expected_bytes,
        path_policy=path_policy,
        dependencies=dependencies,
    )
    try:
        _trigger_fault(_InitFaultPoint.BEFORE_CONFIG_REPLACED, dependencies)
        try:
            dependencies.durability.commit_file_no_replace(
                config_temp,
                request.config_path,
                expected_bytes,
                validator=lambda source: parse_local_config(
                    source,
                    path_policy=path_policy,
                ),
            )
        except DestinationAlreadyExistsError:
            existing = _read_config(request.config_path, path_policy=path_policy)
            _cleanup_current_config_temp(
                config_temp,
                expected_bytes=expected_bytes,
                dependencies=dependencies,
            )
            if existing is None or not _configs_match(
                existing,
                request.local_config,
            ):
                _fail(PublicErrorCode.CONFIG_STORE_CONFLICT)
        _trigger_fault(_InitFaultPoint.AFTER_CONFIG_REPLACED, dependencies)

        connected = _read_config(request.config_path, path_policy=path_policy)
        if connected is None or not _configs_match(connected, request.local_config):
            _fail(PublicErrorCode.CONFIG_STORE_CONFLICT)
    except Exception:
        _cleanup_current_config_temp(
            config_temp,
            expected_bytes=expected_bytes,
            dependencies=dependencies,
        )
        raise


def _success(
    *,
    manifest: CaptureStoreManifest,
    request: _InitRequest,
    created: bool,
) -> InitStoreResult:
    return InitStoreResult(
        created=created,
        store_id=manifest.store_id,
        capture_root=request.capture_root,
    )


def _initialize(
    *,
    config_path: str | os.PathLike[str],
    capture_root: str | os.PathLike[str],
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
    path_policy: PathPolicy,
    dependencies: _StoreDependencies,
) -> InitStoreResult:
    request = _prepare_request(
        config_path=config_path,
        capture_root=capture_root,
        inline_text_threshold_bytes=inline_text_threshold_bytes,
        max_text_version_bytes=max_text_version_bytes,
        path_policy=path_policy,
        dependencies=dependencies,
        create_config_parent=True,
    )
    with dependencies.lock_factory(request.config_path):
        locked_request = _prepare_request(
            config_path=config_path,
            capture_root=capture_root,
            inline_text_threshold_bytes=inline_text_threshold_bytes,
            max_text_version_bytes=max_text_version_bytes,
            path_policy=path_policy,
            dependencies=dependencies,
            create_config_parent=False,
        )
        if not _requests_match(request, locked_request):
            _fail(PublicErrorCode.CONFIG_INVALID, stage="locked-request-changed")
        request = locked_request

        existing_config = _read_config(
            request.config_path,
            path_policy=path_policy,
        )
        if existing_config is not None:
            if not _configs_match(existing_config, request.local_config):
                _fail(PublicErrorCode.CONFIG_STORE_CONFLICT)
            manifest = _inspect_store(request.capture_root)
            if manifest is None:
                _fail(PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED)
            _cleanup_recovery_candidates(request, dependencies)
            return _success(manifest=manifest, request=request, created=False)

        manifest = _inspect_store(request.capture_root)
        if manifest is None:
            _cleanup_recovery_candidates(request, dependencies)
            manifest, created = _create_or_adopt_store(request, dependencies)
        else:
            _cleanup_recovery_candidates(request, dependencies)
            created = False

        _connect_config(
            request,
            path_policy=path_policy,
            dependencies=dependencies,
        )
        connected = _read_config(request.config_path, path_policy=path_policy)
        final_manifest = _inspect_store(request.capture_root)
        if connected is None or not _configs_match(
            connected,
            request.local_config,
        ):
            _fail(PublicErrorCode.CONFIG_STORE_CONFLICT)
        if final_manifest is None or final_manifest != manifest:
            _fail(
                PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                stage="final-reopen",
            )
        return _success(manifest=manifest, request=request, created=created)


def init_capture_store(
    *,
    config_path: str | os.PathLike[str],
    capture_root: str | os.PathLike[str],
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
    path_policy: PathPolicy,
) -> InitStoreOperationResult:
    """Initialize or idempotently reopen one Store without overwriting targets."""

    return _init_capture_store_with_dependencies(
        config_path=config_path,
        capture_root=capture_root,
        inline_text_threshold_bytes=inline_text_threshold_bytes,
        max_text_version_bytes=max_text_version_bytes,
        path_policy=path_policy,
        dependencies=_StoreDependencies(),
    )


def _init_capture_store_with_dependencies(
    *,
    config_path: str | os.PathLike[str],
    capture_root: str | os.PathLike[str],
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
    path_policy: PathPolicy,
    dependencies: _StoreDependencies,
) -> InitStoreOperationResult:
    """Internal entry point reserved for the test support subprocess.

    Production callers must use ``init_capture_store``, which never exposes the
    dependency or fault-hook injection channel.
    """

    try:
        return _initialize(
            config_path=config_path,
            capture_root=capture_root,
            inline_text_threshold_bytes=inline_text_threshold_bytes,
            max_text_version_bytes=max_text_version_bytes,
            path_policy=path_policy,
            dependencies=dependencies,
        )
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except InitializationLockError as exc:
        return FailureResult(error=exc.to_operation_error())
    except DurabilityError as exc:
        return FailureResult(error=exc.to_operation_error())
    except ConfigLoadError as exc:
        return FailureResult(
            error=OperationError(code=exc.code, retryable=False)
        )
    except ManifestLoadError as exc:
        return FailureResult(
            error=OperationError(code=exc.code, retryable=False)
        )
    except (PathPolicyError, TypeError, ValueError):
        return FailureResult(
            error=OperationError(
                code=PublicErrorCode.CONFIG_INVALID,
                retryable=False,
            )
        )
    except OSError:
        return FailureResult(
            error=OperationError(
                code=PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                retryable=False,
            )
        )


__all__ = [
    "CAPTURE_STORE_MANIFEST_FILENAME",
    "CAPTURE_STORE_REQUIRED_DIRECTORIES",
    "InitStoreOperationResult",
    "InitStoreResult",
    "init_capture_store",
]
