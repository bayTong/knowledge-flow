"""Explicit C6 recovery operations for rebuildable Capture Store state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
import stat
from typing import TypeAlias
from uuid import UUID

from .codec import dump_capture_state, load_capture_state
from .config import ConfigLoadError, read_local_config_file, resolve_config_path
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
    _acquire_capture_write_lock,
)
from .manifest import CaptureStoreManifest
from .models import format_utc_milliseconds
from .operations import (
    _DiskCaptureVersionChain,
    _IntegrityFailure,
    _PROJECTION_MAXIMUM_BYTES,
    _StoreIoFailure,
    _UnsupportedMachineSchema,
    _attest_version_payloads,
    _check_machine_identity,
    _directory_entries,
    _is_reparse_point,
    _load_disk_capture_version_chain,
    _locate_capture_items,
    _lstat_if_present,
    _read_regular_bytes,
    _same_identity,
)
from .paths import PathPolicy, PathPolicyError
from .store import _InitFailure, _inspect_store_for_derived_rebuild


_LockFactory = Callable[[Path], CaptureWriteLock]
_UtcNow = Callable[[], datetime]
_UuidFactory = Callable[[], UUID]
_ReplaceFile = Callable[[Path, Path], None]
_FaultHook = Callable[[], None]

_DERIVED_DIRECTORY_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("outbox", ("pending", "running", "failed", "completed")),
    ("indexes", ("idempotency",)),
)


class _RebuildFaultPoint(StrEnum):
    """Internal-only process-crash boundaries for C6B tests."""

    AFTER_PROJECTION_REPLACED = "after_projection_replaced"


def _default_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _noop_fault_hook() -> None:
    return None


@dataclass(frozen=True, slots=True)
class _RebuildDependencies:
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
    fault_point: _RebuildFaultPoint | None = field(
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
class RebuildDerivedStateResult:
    """Stable metadata-only receipt for one explicit derived-state rebuild."""

    store_id: str
    items_scanned: int
    versions_verified: int
    idempotency_records_verified: int
    projections_rebuilt: int
    projections_unchanged: int
    derived_directories_created: int
    outbox_jobs_rebuilt: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        validate_typed_id(self.store_id, IdKind.STORE)
        counts = (
            self.items_scanned,
            self.versions_verified,
            self.idempotency_records_verified,
            self.projections_rebuilt,
            self.projections_unchanged,
            self.derived_directories_created,
            self.outbox_jobs_rebuilt,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("rebuild counts must be non-negative integers")
        if self.projections_rebuilt + self.projections_unchanged != self.items_scanned:
            raise ValueError("projection counts must equal items_scanned")
        if self.outbox_jobs_rebuilt != 0:
            raise ValueError("MVP-0 cannot rebuild outbox jobs")

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "store_id": self.store_id,
            "items_scanned": self.items_scanned,
            "versions_verified": self.versions_verified,
            "idempotency_records_verified": self.idempotency_records_verified,
            "projections_rebuilt": self.projections_rebuilt,
            "projections_unchanged": self.projections_unchanged,
            "derived_directories_created": self.derived_directories_created,
            "outbox_jobs_rebuilt": self.outbox_jobs_rebuilt,
        }


RebuildDerivedStateOperationResult: TypeAlias = (
    RebuildDerivedStateResult | FailureResult
)


@dataclass(frozen=True, slots=True)
class _ProjectionPlan:
    disk_chain: _DiskCaptureVersionChain
    expected_destination: os.stat_result | None = field(
        repr=False,
        compare=False,
    )
    state_bytes: bytes | None = field(repr=False)

    @property
    def needs_rebuild(self) -> bool:
        return self.state_bytes is not None


@dataclass(frozen=True, slots=True)
class _RebuildPlan:
    projections: tuple[_ProjectionPlan, ...]
    missing_directories: tuple[Path, ...]
    versions_verified: int
    idempotency_records_verified: int


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
    point: _RebuildFaultPoint,
    dependencies: _RebuildDependencies,
) -> None:
    if dependencies.fault_point == point:
        dependencies.fault_hook()


def _require_plain_derived_directory(path: Path) -> None:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise _StoreIoFailure(stage="derived-state-layout") from exc
    if path_stat is None or not stat.S_ISDIR(path_stat.st_mode) or (
        _is_reparse_point(path_stat)
    ):
        raise _StoreIoFailure(stage="derived-state-layout")


def _inspect_derived_directories(capture_root: Path) -> tuple[Path, ...]:
    """Validate the formatless MVP-0 derived trees and find absent directories."""

    missing: list[Path] = []
    for parent_name, child_names in _DERIVED_DIRECTORY_LAYOUT:
        parent = capture_root / parent_name
        try:
            parent_stat = _lstat_if_present(parent)
        except OSError as exc:
            raise _StoreIoFailure(stage="derived-state-layout") from exc
        if parent_stat is None:
            missing.append(parent)
            missing.extend(parent / name for name in child_names)
            continue
        if not stat.S_ISDIR(parent_stat.st_mode) or _is_reparse_point(parent_stat):
            raise _StoreIoFailure(stage="derived-state-layout")

        entries = _directory_entries(parent, stage="derived-state-layout")
        allowed = frozenset(child_names)
        if any(entry.name not in allowed for entry in entries):
            raise _UnsupportedMachineSchema
        by_name = {entry.name: entry for entry in entries}
        for child_name in child_names:
            child = by_name.get(child_name)
            if child is None:
                missing.append(parent / child_name)
                continue
            _require_plain_derived_directory(child)
            if _directory_entries(child, stage="derived-state-layout"):
                # C6B deliberately has no on-disk idempotency or outbox job
                # schema.  Unknown bytes are preserved and fail closed.
                raise _UnsupportedMachineSchema
    return tuple(missing)


def _projection_context(
    disk_chain: _DiskCaptureVersionChain,
) -> tuple[Mapping[str, object], Mapping[str, object] | None]:
    current = disk_chain.chain.current
    previous = disk_chain.chain.version(current.version - 1)
    return current.event, previous.envelope if previous is not None else None


def _projection_is_current(
    disk_chain: _DiskCaptureVersionChain,
    source: bytes,
) -> bool:
    _check_machine_identity(
        source,
        expected_schema="knowledgeflow.capture-state",
        invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
    )
    current = disk_chain.chain.current
    current_event, previous_envelope = _projection_context(disk_chain)
    try:
        load_capture_state(
            source,
            envelope=current.envelope,
            current_event=(current_event if current.version > 1 else None),
            previous_envelope=previous_envelope,
            require_canonical=True,
        )
    except (TypeError, ValueError):
        return False
    return True


def _build_projection_bytes(
    disk_chain: _DiskCaptureVersionChain,
    *,
    verified_at: str,
) -> bytes:
    current = disk_chain.chain.current
    current_event, previous_envelope = _projection_context(disk_chain)
    state = {
        "schema": "knowledgeflow.capture-state",
        "schema_version": 1,
        "capture_id": disk_chain.chain.capture_id,
        "current_version": current.version,
        "current_envelope_sha256": current.envelope["envelope_sha256"],
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
        "updated_at": (
            verified_at if current.version == 1 else current.event["occurred_at"]
        ),
    }
    return dump_capture_state(
        state,
        envelope=current.envelope,
        current_event=(current_event if current.version > 1 else None),
        previous_envelope=previous_envelope,
    )


def _plan_projection(
    disk_chain: _DiskCaptureVersionChain,
    *,
    dependencies: _RebuildDependencies,
) -> _ProjectionPlan:
    destination = disk_chain.item.item_path / "capture.yaml"
    try:
        destination_stat = _lstat_if_present(destination)
    except OSError as exc:
        raise _StoreIoFailure(stage="projection-read") from exc
    if destination_stat is not None and (
        not stat.S_ISREG(destination_stat.st_mode)
        or _is_reparse_point(destination_stat)
    ):
        raise _StoreIoFailure(stage="projection-target-type")

    current = False
    if destination_stat is not None:
        try:
            source = _read_regular_bytes(
                destination,
                maximum_bytes=_PROJECTION_MAXIMUM_BYTES,
                missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
                invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            )
            current = _projection_is_current(disk_chain, source)
        except _UnsupportedMachineSchema:
            raise
        except _IntegrityFailure:
            current = False
    if current:
        return _ProjectionPlan(
            disk_chain=disk_chain,
            expected_destination=destination_stat,
            state_bytes=None,
        )

    verified_at = format_utc_milliseconds(dependencies.utc_now())
    return _ProjectionPlan(
        disk_chain=disk_chain,
        expected_destination=destination_stat,
        state_bytes=_build_projection_bytes(
            disk_chain,
            verified_at=verified_at,
        ),
    )


def _verify_idempotency_records(
    chains: tuple[_DiskCaptureVersionChain, ...],
) -> int:
    seen: dict[tuple[str, str], str] = {}
    count = 0
    for disk_chain in chains:
        for committed in disk_chain.chain.versions:
            if committed.envelope.get("delivery_requests") != []:
                raise _UnsupportedMachineSchema
            identity = committed.envelope.get("idempotency")
            if identity is None:
                continue
            if not isinstance(identity, Mapping):
                raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
            scope = identity.get("scope")
            key_sha256 = identity.get("key_sha256")
            request_sha256 = identity.get("request_fingerprint_sha256")
            if not all(
                type(value) is str
                for value in (scope, key_sha256, request_sha256)
            ):
                raise _IntegrityFailure(CauseCode.ENVELOPE_HASH_MISMATCH)
            key = (scope, key_sha256)
            if key in seen:
                raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
            seen[key] = request_sha256
            count += 1
    return count


def _build_rebuild_plan(
    capture_root: Path,
    *,
    dependencies: _RebuildDependencies,
) -> _RebuildPlan:
    missing_directories = _inspect_derived_directories(capture_root)
    chains = tuple(
        _load_disk_capture_version_chain(item)
        for item in _locate_capture_items(capture_root)
    )

    versions_verified = 0
    for disk_chain in chains:
        for committed in disk_chain.chain.versions:
            version_path = disk_chain.version_paths.get(committed.version)
            if version_path is None:
                raise _IntegrityFailure(CauseCode.EVENT_REFERENCE_MISMATCH)
            _attest_version_payloads(version_path, committed.envelope)
            versions_verified += 1

    idempotency_records_verified = _verify_idempotency_records(chains)
    projections = tuple(
        _plan_projection(disk_chain, dependencies=dependencies)
        for disk_chain in chains
    )
    return _RebuildPlan(
        projections=projections,
        missing_directories=missing_directories,
        versions_verified=versions_verified,
        idempotency_records_verified=idempotency_records_verified,
    )


def _create_derived_directory(
    path: Path,
    *,
    durability: DurabilityBackend,
) -> None:
    _require_plain_derived_directory(path.parent)
    try:
        os.mkdir(path)
    except OSError as exc:
        raise _StoreIoFailure(stage="derived-directory-create") from exc
    _require_plain_derived_directory(path)
    durability.flush_directory_metadata(path.parent)


def _projection_validator(
    disk_chain: _DiskCaptureVersionChain,
) -> Callable[[bytes], object]:
    current = disk_chain.chain.current
    current_event, previous_envelope = _projection_context(disk_chain)

    def validate(source: bytes) -> object:
        return load_capture_state(
            source,
            envelope=current.envelope,
            current_event=(current_event if current.version > 1 else None),
            previous_envelope=previous_envelope,
            require_canonical=True,
        )

    return validate


def _replace_projection(
    plan: _ProjectionPlan,
    *,
    dependencies: _RebuildDependencies,
) -> None:
    if plan.state_bytes is None:
        raise TypeError("projection plan does not require a rebuild")
    item_path = plan.disk_chain.item.item_path
    destination = item_path / "capture.yaml"
    transaction_id = dependencies.uuid_factory()
    if not isinstance(transaction_id, UUID) or transaction_id.version != 7:
        raise TypeError("uuid_factory must return a UUIDv7")
    temporary = item_path / f".capture-state-rebuild-{transaction_id}.tmp"
    temporary_stat: os.stat_result | None = None
    try:
        validator = _projection_validator(plan.disk_chain)
        dependencies.durability.write_new_file_durable(
            temporary,
            plan.state_bytes,
            validator=validator,
        )
        temporary_stat = _lstat_if_present(temporary)
        if temporary_stat is None or not stat.S_ISREG(temporary_stat.st_mode) or (
            _is_reparse_point(temporary_stat)
        ):
            raise _StoreIoFailure(stage="projection-temp-identity")

        if plan.expected_destination is None:
            if _lstat_if_present(destination) is not None:
                raise _StoreIoFailure(stage="projection-target-changed")
        elif not _same_identity(destination, plan.expected_destination):
            raise _StoreIoFailure(stage="projection-target-changed")
        if not _same_identity(temporary, temporary_stat):
            raise _StoreIoFailure(stage="projection-temp-identity")

        try:
            dependencies.replace_file(temporary, destination)
        except OSError as exc:
            raise _StoreIoFailure(stage="projection-replace") from exc
        dependencies.durability.flush_directory_metadata(item_path)
        _trigger_fault(
            _RebuildFaultPoint.AFTER_PROJECTION_REPLACED,
            dependencies,
        )

        try:
            source = _read_regular_bytes(
                destination,
                maximum_bytes=_PROJECTION_MAXIMUM_BYTES,
                missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
                invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            )
            if source != plan.state_bytes:
                raise _StoreIoFailure(stage="projection-readback")
            validator(source)
        except _IntegrityFailure as exc:
            raise _StoreIoFailure(stage="projection-readback") from exc
        except (TypeError, ValueError) as exc:
            raise _StoreIoFailure(stage="projection-readback") from exc
    finally:
        if temporary_stat is not None and _same_identity(temporary, temporary_stat):
            try:
                temporary.unlink()
                dependencies.durability.flush_directory_metadata(item_path)
            except (DurabilityError, OSError):
                pass


def _apply_rebuild_plan(
    capture_root: Path,
    plan: _RebuildPlan,
    *,
    dependencies: _RebuildDependencies,
) -> tuple[int, int]:
    directories_created = 0
    for path in plan.missing_directories:
        _create_derived_directory(path, durability=dependencies.durability)
        directories_created += 1

    projections_rebuilt = 0
    for projection in plan.projections:
        if not projection.needs_rebuild:
            continue
        _replace_projection(projection, dependencies=dependencies)
        projections_rebuilt += 1

    # Revalidate the complete derived result before claiming success.  This is
    # intentionally separate from immutable planning so a crash can be resumed.
    if _inspect_derived_directories(capture_root):
        raise _StoreIoFailure(stage="derived-state-readback")
    for projection in plan.projections:
        destination = projection.disk_chain.item.item_path / "capture.yaml"
        try:
            source = _read_regular_bytes(
                destination,
                maximum_bytes=_PROJECTION_MAXIMUM_BYTES,
                missing_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
                invalid_cause=CauseCode.ENVELOPE_HASH_MISMATCH,
            )
            if not _projection_is_current(projection.disk_chain, source):
                raise _StoreIoFailure(stage="projection-readback")
        except _IntegrityFailure as exc:
            raise _StoreIoFailure(stage="projection-readback") from exc
    return directories_created, projections_rebuilt


def _load_rebuild_environment(
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
) -> tuple[Path, CaptureStoreManifest]:
    if not isinstance(path_policy, PathPolicy):
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID)
    selected = resolve_config_path(config_path)
    try:
        selected = path_policy.validate_config_path(selected)
    except PathPolicyError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    local_config = read_local_config_file(selected, path_policy=path_policy)
    manifest = _inspect_store_for_derived_rebuild(local_config.capture.root)
    if manifest is None:
        raise _InitFailure(
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED,
                retryable=False,
            )
        )
    return local_config.capture.root, manifest


def _run_rebuild_capture_store_derived_state(
    *,
    config_path: str | os.PathLike[str] | None,
    path_policy: PathPolicy,
    dependencies: _RebuildDependencies,
) -> RebuildDerivedStateOperationResult:
    try:
        capture_root, initial_manifest = _load_rebuild_environment(
            config_path=config_path,
            path_policy=path_policy,
        )
    except ConfigLoadError as exc:
        return _failure(exc.code)
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
    except (OSError, TypeError, ValueError):
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)

    locked_result: RebuildDerivedStateResult | None = None
    try:
        with dependencies.lock_factory(capture_root):
            current_manifest = _inspect_store_for_derived_rebuild(capture_root)
            if current_manifest is None or current_manifest != initial_manifest:
                raise _StoreIoFailure(stage="store-identity")
            plan = _build_rebuild_plan(
                capture_root,
                dependencies=dependencies,
            )
            directories_created, projections_rebuilt = _apply_rebuild_plan(
                capture_root,
                plan,
                dependencies=dependencies,
            )
            locked_result = RebuildDerivedStateResult(
                store_id=current_manifest.store_id,
                items_scanned=len(plan.projections),
                versions_verified=plan.versions_verified,
                idempotency_records_verified=(
                    plan.idempotency_records_verified
                ),
                projections_rebuilt=projections_rebuilt,
                projections_unchanged=(
                    len(plan.projections) - projections_rebuilt
                ),
                derived_directories_created=directories_created,
            )
        if locked_result is None:
            raise _StoreIoFailure(stage="lock-release")
        return locked_result
    except CaptureWriteLockError as exc:
        if locked_result is not None:
            return locked_result
        return FailureResult(error=exc.to_operation_error())
    except _InitFailure as exc:
        return FailureResult(error=exc.error)
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
    except DurabilityError as exc:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=exc.retryable,
            stage=exc.stage.value,
        )
    except DestinationAlreadyExistsError:
        return _failure(
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            stage="projection-temp-collision",
        )
    except (TypeError, ValueError):
        return _failure(
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
            cause_code=CauseCode.ENVELOPE_HASH_MISMATCH,
        )
    except OSError:
        return _failure(PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)


def rebuild_capture_store_derived_state(
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
) -> RebuildDerivedStateOperationResult:
    """Validate immutable facts, then explicitly rebuild MVP-0 derived state.

    This administrative operation is intentionally separate from the four
    everyday text operations.  It never repairs staging or an uncommitted tail.
    """

    return _run_rebuild_capture_store_derived_state(
        config_path=config_path,
        path_policy=path_policy,
        dependencies=_RebuildDependencies(),
    )


def _rebuild_capture_store_derived_state_with_dependencies(
    *,
    config_path: str | os.PathLike[str] | None = None,
    path_policy: PathPolicy,
    dependencies: _RebuildDependencies,
) -> RebuildDerivedStateOperationResult:
    """Internal deterministic/fault-injection entry point for C6B tests."""

    if not isinstance(dependencies, _RebuildDependencies):
        raise TypeError("dependencies must be _RebuildDependencies")
    return _run_rebuild_capture_store_derived_state(
        config_path=config_path,
        path_policy=path_policy,
        dependencies=dependencies,
    )


__all__ = [
    "RebuildDerivedStateOperationResult",
    "RebuildDerivedStateResult",
    "rebuild_capture_store_derived_state",
]
