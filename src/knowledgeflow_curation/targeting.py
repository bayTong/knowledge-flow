"""CUR1C target confirmation, provisional KB bootstrap, and exact raw routing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

from knowledgeflow_capture import GetCaptureRequest, get_capture
from knowledgeflow_capture.durability import (
    DestinationAlreadyExistsError,
    DurabilityBackend,
    DurabilityError,
)
from knowledgeflow_capture.errors import FailureResult, GetCaptureResult, PublicErrorCode
from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.models import format_utc_milliseconds
from knowledgeflow_capture.paths import PathPolicy

from .codec import (
    dump_curation_run,
    dump_kb_manifest,
    dump_raw_source_mapping,
    dump_route_record,
    dump_target_decision_record,
    load_curation_run,
    load_kb_manifest,
    load_raw_source_mapping,
    load_route_record,
    load_target_decision_record,
)
from .contracts import (
    CurationRunManifest,
    KnowledgeBaseManifest,
    RawSourceMapping,
    RouteRecord,
    TargetBinding,
    TargetDecision,
    TargetDecisionRecord,
    TargetSuggestion,
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
from .versioning import (
    MANAGED_REF,
    VERSION_POLICY_ID,
    VERSION_POLICY_REVISION,
    ManagedGit,
    ManagedGitConflict,
    ManagedGitError,
    ManagedGitIntegrityError,
    ManagedGitUnavailable,
)


_SAFE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_STORAGE_NAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_DATE_STORAGE = re.compile(r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})-(?P<seq>[0-9]{2})\Z")
_UTC_OFFSET = re.compile(r"(?P<sign>[+-])(?P<hours>[0-1][0-9]|2[0-3]):(?P<minutes>[0-5][0-9])\Z")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_REPARSE_ATTRIBUTE = 0x400
_MAX_INTERNAL_BYTES = 64 * 1024 * 1024
_TARGET_BUNDLE_FILES = frozenset(
    {"request.json", "target-decision.yaml", "run.yaml", "result.json"}
)
_TARGET_REQUEST_KEYS = {
    "schema",
    "schema_version",
    "decision_request_id",
    "source_request_id",
    "choice",
    "decided_by",
    "root_policy_id",
    "root_policy_revision",
    "parent_index",
    "storage_name",
    "display_name",
    "authorization_source",
    "suggestion_choice",
    "suggestion_rationale",
    "suggested_by",
    "naming_timezone",
}


class _TargetConflict(Exception):
    pass


class _IdempotencyConflict(Exception):
    pass


class _TargetCorrupt(Exception):
    pass


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


def _fixed_timezone(value: str) -> timezone:
    if type(value) is not str:
        raise ValueError("naming_timezone must be a canonical UTC offset")
    match = _UTC_OFFSET.fullmatch(value)
    if match is None:
        raise ValueError("naming_timezone must be a canonical UTC offset")
    minutes = int(match.group("hours")) * 60 + int(match.group("minutes"))
    if match.group("sign") == "-":
        minutes = -minutes
    return timezone(timedelta(minutes=minutes))


def _load_canonical_json(source: bytes, expected_keys: set[str]) -> Mapping[str, object]:
    try:
        value = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _TargetCorrupt from exc
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise _TargetCorrupt
    if _canonical_json(value) != source:
        raise _TargetCorrupt
    return value


def _read_bounded(path: Path) -> bytes:
    try:
        _plain_file(path)
        if path.stat().st_size > _MAX_INTERNAL_BYTES:
            raise _TargetCorrupt
        return path.read_bytes()
    except _TargetCorrupt:
        raise
    except OSError as exc:
        raise _TargetCorrupt from exc


def _decode_internal(loader: Callable[[bytes], object], source: bytes) -> object:
    try:
        return loader(source)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _TargetCorrupt from exc


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        pass
    _plain_directory(path)


def _write_new_or_same(
    path: Path,
    body: bytes,
    durability: DurabilityBackend,
) -> None:
    try:
        durability.write_new_file_durable(path, body)
    except DestinationAlreadyExistsError:
        _plain_file(path)
        if path.read_bytes() != body:
            raise _TargetCorrupt


def _safe_rmtree_owned(staging: Path, parent: Path, owner_bytes: bytes) -> None:
    if not staging.exists():
        return
    _plain_directory(parent)
    _plain_directory(staging)
    if staging.parent.resolve(strict=True) != parent.resolve(strict=True):
        raise _TargetCorrupt
    if not staging.name.startswith(".knowledgeflow-staging-"):
        raise _TargetCorrupt
    marker = staging / ".knowledgeflow" / "transactions" / "bootstrap-owner.json"
    _plain_file(marker)
    if marker.read_bytes() != owner_bytes:
        raise _TargetCorrupt

    def make_writable(function: Callable[..., object], selected: str, _: object) -> None:
        os.chmod(selected, stat.S_IWRITE)
        function(selected)

    shutil.rmtree(staging, onerror=make_writable)


@dataclass(frozen=True, slots=True)
class KnowledgeBaseRootPolicy:
    """Trusted capability listing the exact parents eligible for new KBs."""

    policy_id: str
    revision: int
    allowed_parents: tuple[Path, ...]

    def __post_init__(self) -> None:
        if type(self.policy_id) is not str or _SAFE_TOKEN.fullmatch(self.policy_id) is None:
            raise ValueError("policy_id must be a safe lowercase token")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be positive")
        parents = tuple(self.allowed_parents)
        if not parents:
            raise ValueError("allowed_parents must not be empty")
        normalized: list[Path] = []
        identities: set[str] = set()
        for raw in parents:
            selected = _absolute(raw).resolve(strict=True)
            _plain_directory(selected)
            identity = os.path.normcase(str(selected))
            if identity in identities:
                raise ValueError("allowed_parents must be unique")
            identities.add(identity)
            normalized.append(selected)
        object.__setattr__(self, "allowed_parents", tuple(normalized))

    def select(self, parent: str | os.PathLike[str]) -> tuple[int, Path]:
        selected = _absolute(parent).resolve(strict=True)
        _plain_directory(selected)
        identity = os.path.normcase(str(selected))
        for index, allowed in enumerate(self.allowed_parents):
            if identity == os.path.normcase(str(allowed)):
                return index, allowed
        raise ValueError("KB parent is outside the authorized root policy")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDecideRequest:
    decision_request_id: str
    source_request_id: str
    choice: str
    decided_by: str
    kb_parent: Path | None = None
    storage_name: str | None = None
    display_name: str | None = None
    authorization_source: str = "manual-review"
    suggestion_choice: str | None = None
    suggestion_rationale: str | None = None
    suggested_by: str | None = None
    naming_timezone: str = "+08:00"

    def __post_init__(self) -> None:
        for value, label in (
            (self.decision_request_id, "decision_request_id"),
            (self.source_request_id, "source_request_id"),
            (self.decided_by, "decided_by"),
        ):
            if type(value) is not str or _SAFE_TOKEN.fullmatch(value) is None:
                raise ValueError(f"{label} must be a safe lowercase token")
        if self.choice not in {"new-kb", "no-target"}:
            raise ValueError("choice must be new-kb or no-target")
        supplied = (
            self.suggestion_choice,
            self.suggestion_rationale,
            self.suggested_by,
        )
        if any(value is not None for value in supplied) and not all(
            value is not None for value in supplied
        ):
            raise ValueError("suggestion fields must be supplied together")
        if self.suggestion_choice is not None:
            if self.suggestion_choice not in {"new-kb", "no-target"}:
                raise ValueError("suggestion_choice is not supported")
            if (
                type(self.suggestion_rationale) is not str
                or not self.suggestion_rationale.strip()
                or self.suggestion_rationale != self.suggestion_rationale.strip()
                or len(self.suggestion_rationale.encode("utf-8")) > 16 * 1024
            ):
                raise ValueError("suggestion_rationale is invalid")
            if type(self.suggested_by) is not str or _SAFE_TOKEN.fullmatch(
                self.suggested_by
            ) is None:
                raise ValueError("suggested_by must be a safe lowercase token")
        _fixed_timezone(self.naming_timezone)
        if self.authorization_source not in {
            "explicit-at-capture",
            "manual-review",
            "approved-proposal",
        }:
            raise ValueError("authorization_source is not supported")
        if self.choice == "no-target":
            if any(
                value is not None
                for value in (self.kb_parent, self.storage_name, self.display_name)
            ):
                raise ValueError("no-target cannot carry KB creation fields")
            return
        if self.kb_parent is None:
            raise ValueError("new-kb requires kb_parent")
        parent = _absolute(self.kb_parent)
        object.__setattr__(self, "kb_parent", parent)
        if self.storage_name is not None:
            if (
                type(self.storage_name) is not str
                or _STORAGE_NAME.fullmatch(self.storage_name) is None
                or self.storage_name.split(".", 1)[0] in _WINDOWS_RESERVED
            ):
                raise ValueError("storage_name is not portable")
        if self.display_name is not None:
            if (
                type(self.display_name) is not str
                or not self.display_name.strip()
                or self.display_name != self.display_name.strip()
                or "\n" in self.display_name
                or "\r" in self.display_name
                or "\x00" in self.display_name
                or len(self.display_name.encode("utf-8")) > 512
            ):
                raise ValueError("display_name is invalid")


@dataclass(frozen=True, slots=True)
class TargetDecideResult:
    decision_request_id: str
    record: TargetDecisionRecord
    updated_run: CurationRunManifest
    route: RouteRecord | None
    storage_name: str | None
    base_commit: str | None
    result_commit: str | None
    replayed: bool = False

    def __post_init__(self) -> None:
        if self.decision_request_id != self.record.decision_request_id:
            raise ValueError("decision request identity mismatch")
        if self.updated_run.curation_run_id != self.record.curation_run_id:
            raise ValueError("run identity mismatch")
        if (
            self.updated_run.source != self.record.source
            or self.updated_run.processing_authorization.authorization_id
            != self.record.processing_authorization_id
        ):
            raise ValueError("run authority does not match the target record")
        if self.updated_run.target_decision != self.record.decision:
            raise ValueError("run does not contain the target decision")
        if self.record.decision.choice == "no-target":
            if any(
                value is not None
                for value in (
                    self.route,
                    self.storage_name,
                    self.base_commit,
                    self.result_commit,
                )
            ):
                raise ValueError("no-target result cannot carry KB facts")
        else:
            if not isinstance(self.route, RouteRecord):
                raise TypeError("new-kb result requires RouteRecord")
            if (
                self.storage_name != self.record.target_storage_name
                or self.base_commit != self.record.target_binding.base_commit
                or type(self.result_commit) is not str
            ):
                raise ValueError("new-kb result facts are inconsistent")
        if type(self.replayed) is not bool:
            raise TypeError("replayed must be boolean")

    def to_dict(self) -> dict[str, object]:
        binding = self.record.target_binding
        return {
            "ok": True,
            "operation": "target.decide",
            "decision_request_id": self.decision_request_id,
            "source_request_id": self.record.source_request_id,
            "curation_run_id": self.record.curation_run_id,
            "target_decision_id": self.record.decision.target_decision_id,
            "choice": self.record.decision.choice,
            "suggestion_recorded": self.record.suggestion is not None,
            "suggestion_matched_decision": (
                None
                if self.record.suggestion is None
                else self.record.suggestion.choice == self.record.decision.choice
            ),
            "kb_created": binding is not None,
            "kb_id": None if binding is None else binding.kb_id,
            "storage_name": self.storage_name,
            "lifecycle": None if binding is None else "provisional",
            "raw_routed": self.route is not None,
            "route_id": None if self.route is None else self.route.route_id,
            "payload_path": None if self.route is None else self.route.payload_path,
            "managed_ref": None if binding is None else binding.managed_ref,
            "base_commit": self.base_commit,
            "result_commit": self.result_commit,
            "trusted_visibility": "none",
            "wiki_status": "not-created" if binding is None else "empty",
            "saved": True,
            "commit_state": CurationCommitState.COMMITTED.value,
            "replayed": self.replayed,
            "warnings": [],
        }


TargetDecideOperationResult = TargetDecideResult | CurationFailure


@dataclass(frozen=True, slots=True)
class _TargetLayout:
    root: Path
    config_path: Path
    work_root: Path
    targets_root: Path
    staging_root: Path
    transactions_root: Path
    locks_root: Path


def _layout(experiment_root: str | os.PathLike[str]) -> _TargetLayout:
    root = _absolute(experiment_root)
    work = root / "curation-work"
    return _TargetLayout(
        root=root,
        config_path=root / "capture-config.yaml",
        work_root=work,
        targets_root=work / "targets",
        staging_root=work / ".target-staging",
        transactions_root=work / "target-transactions",
        locks_root=work / ".target-locks",
    )


def _prepare_layout(layout: _TargetLayout) -> None:
    _plain_directory(layout.root)
    _plain_directory(layout.work_root)
    for path in (
        layout.targets_root,
        layout.staging_root,
        layout.transactions_root,
        layout.locks_root,
    ):
        _ensure_directory(path)


def _failure(
    code: CurationErrorCode,
    *,
    state: CurationCommitState = CurationCommitState.NOT_COMMITTED,
    retryable: bool = False,
    stage: str,
) -> CurationFailure:
    return CurationFailure(
        CurationError(code=code, retryable=retryable, details={"stage": stage}),
        state,
    )


def _request_bytes(
    request: TargetDecideRequest,
    *,
    parent_index: int | None,
    policy: KnowledgeBaseRootPolicy | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.target-decide-request",
            "schema_version": 1,
            "decision_request_id": request.decision_request_id,
            "source_request_id": request.source_request_id,
            "choice": request.choice,
            "decided_by": request.decided_by,
            "root_policy_id": None if policy is None else policy.policy_id,
            "root_policy_revision": None if policy is None else policy.revision,
            "parent_index": parent_index,
            "storage_name": request.storage_name,
            "display_name": request.display_name,
            "authorization_source": request.authorization_source,
            "suggestion_choice": request.suggestion_choice,
            "suggestion_rationale": request.suggestion_rationale,
            "suggested_by": request.suggested_by,
            "naming_timezone": request.naming_timezone,
        }
    )


def _load_request(source: bytes) -> Mapping[str, object]:
    value = _load_canonical_json(source, _TARGET_REQUEST_KEYS)
    if (
        value["schema"] != "knowledgeflow.target-decide-request"
        or value["schema_version"] != 1
    ):
        raise _TargetCorrupt
    return value


def _identity_bytes(
    *,
    request: TargetDecideRequest,
    decided_at: str,
    storage_name: str | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.target-transaction-identity",
            "schema_version": 1,
            "target_decision_id": generate_curation_id("target_"),
            "kb_id": None if request.choice == "no-target" else generate_curation_id("kb_"),
            "route_id": (
                None if request.choice == "no-target" else generate_curation_id("route_")
            ),
            "route_transaction_id": (
                None if request.choice == "no-target" else generate_curation_id("txn_")
            ),
            "decided_at": decided_at,
            "storage_name": storage_name,
        }
    )


def _load_identity(source: bytes) -> Mapping[str, object]:
    value = _load_canonical_json(
        source,
        {
            "schema",
            "schema_version",
            "target_decision_id",
            "kb_id",
            "route_id",
            "route_transaction_id",
            "decided_at",
            "storage_name",
        },
    )
    if (
        value["schema"] != "knowledgeflow.target-transaction-identity"
        or value["schema_version"] != 1
    ):
        raise _TargetCorrupt
    return value


def _reserved_storage_names(
    transactions_root: Path,
    *,
    current_request_id: str,
    policy: KnowledgeBaseRootPolicy,
    parent_index: int,
) -> frozenset[str]:
    reserved: set[str] = set()
    for transaction in transactions_root.iterdir():
        if transaction.name == current_request_id:
            continue
        _plain_directory(transaction)
        request_path = transaction / "request.json"
        identity_path = transaction / "identity.json"
        if not identity_path.exists():
            continue
        if not request_path.exists():
            raise _TargetCorrupt
        request = _load_request(_read_bounded(request_path))
        if (
            request["choice"] != "new-kb"
            or request["root_policy_id"] != policy.policy_id
            or request["root_policy_revision"] != policy.revision
            or request["parent_index"] != parent_index
        ):
            continue
        identity = _load_identity(_read_bounded(identity_path))
        storage_name = identity["storage_name"]
        if type(storage_name) is not str or _STORAGE_NAME.fullmatch(storage_name) is None:
            raise _TargetCorrupt
        reserved.add(storage_name.casefold())
    return frozenset(reserved)


def _next_date_name(
    parent: Path,
    local_date: str,
    reserved_names: frozenset[str],
) -> str:
    occupied: set[int] = set()
    for child in parent.iterdir():
        match = _DATE_STORAGE.fullmatch(child.name)
        if match is not None and match.group("date") == local_date:
            occupied.add(int(match.group("seq")))
    for reserved in reserved_names:
        match = _DATE_STORAGE.fullmatch(reserved)
        if match is not None and match.group("date") == local_date:
            occupied.add(int(match.group("seq")))
    for sequence in range(1, 100):
        if sequence not in occupied:
            return f"{local_date}-{sequence:02d}"
    raise _TargetConflict


def _portable_name_is_available(
    parent: Path,
    storage_name: str,
    reserved_names: frozenset[str] = frozenset(),
) -> bool:
    selected = storage_name.casefold()
    return selected not in reserved_names and all(
        child.name.casefold() != selected for child in parent.iterdir()
    )


def _initial_files(manifest: KnowledgeBaseManifest) -> dict[str, bytes]:
    placeholders = (
        ".knowledgeflow/routes/.gitkeep",
        ".knowledgeflow/runs/.gitkeep",
        "inbox/.gitkeep",
        "raw/text/.gitkeep",
        "raw/articles/.gitkeep",
        "raw/papers/.gitkeep",
        "raw/transcripts/.gitkeep",
        "raw/assets/.gitkeep",
        "proposals/routing/.gitkeep",
        "proposals/curation-maps/.gitkeep",
        "proposals/promotions/.gitkeep",
        "proposals/changes/.gitkeep",
        "proposals/maintenance/.gitkeep",
        "wiki/.gitkeep",
        "_archive/.gitkeep",
    )
    files = {path: b"" for path in placeholders}
    files.update(
        {
            ".gitattributes": b"* -text\n",
            ".gitignore": (
                b"/.knowledgeflow/transactions/*\n"
                b"/.knowledgeflow/receipts/*\n"
                b"/.knowledgeflow/locks/*\n"
            ),
            "README.md": (
                f"# {manifest.display_name}\n\n"
                "该知识库处于 provisional 状态；raw/ 不是可信 Wiki。\n"
            ).encode("utf-8"),
            "kb.yaml": dump_kb_manifest(manifest),
            "schema/log.md": b"# Schema log\n\nNo schema has been approved.\n",
        }
    )
    return files


def _create_directories_for_files(root: Path, paths: Mapping[str, bytes]) -> None:
    directories = {PurePosixPath(path).parent for path in paths}
    directories.update(
        {
            PurePosixPath(".knowledgeflow/transactions"),
            PurePosixPath(".knowledgeflow/receipts"),
            PurePosixPath(".knowledgeflow/locks"),
        }
    )
    for relative in sorted(directories, key=lambda item: (len(item.parts), item.as_posix())):
        current = root.joinpath(*relative.parts)
        current.mkdir(parents=True, exist_ok=True)
        _plain_directory(current)


def _persist_candidate(path: Path, value: str, durability: DurabilityBackend) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ManagedGitIntegrityError("candidate commit is invalid")
    _write_new_or_same(path, (value + "\n").encode("ascii"), durability)


def _candidate(path: Path) -> str | None:
    if not path.exists():
        return None
    source = _read_bounded(path)
    try:
        value = source.decode("ascii").removesuffix("\n")
    except UnicodeDecodeError as exc:
        raise _TargetCorrupt from exc
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise _TargetCorrupt
    return value


def _bootstrap_owner_bytes(decision_request_id: str, kb_id: str) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.staging-owner",
            "schema_version": 1,
            "decision_request_id": decision_request_id,
            "kb_id": kb_id,
        }
    )


def _bootstrap_kb(
    *,
    parent: Path,
    identity: Mapping[str, object],
    request: TargetDecideRequest,
    git: ManagedGit,
    durability: DurabilityBackend,
    transaction: Path,
) -> tuple[Path, KnowledgeBaseManifest, dict[str, bytes], str]:
    storage_name = identity["storage_name"]
    kb_id = identity["kb_id"]
    decided_at = identity["decided_at"]
    if not all(type(value) is str for value in (storage_name, kb_id, decided_at)):
        raise _TargetCorrupt
    display_name = request.display_name or storage_name
    try:
        manifest = KnowledgeBaseManifest(
            kb_id=kb_id,
            storage_name=storage_name,
            display_name=display_name,
            created_at=decided_at,
            created_by=request.decided_by,
            creation_request_id=request.decision_request_id,
        )
    except (TypeError, ValueError) as exc:
        raise _TargetCorrupt from exc
    files = _initial_files(manifest)
    destination = parent / storage_name
    root_candidate_path = transaction / "root-candidate.txt"
    candidate = _candidate(root_candidate_path)
    owner_bytes = _bootstrap_owner_bytes(request.decision_request_id, kb_id)
    if destination.exists():
        _plain_directory(destination)
        existing_manifest = _decode_internal(
            load_kb_manifest,
            _read_bounded(destination / "kb.yaml"),
        )
        assert isinstance(existing_manifest, KnowledgeBaseManifest)
        if existing_manifest != manifest or candidate is None:
            raise _TargetConflict
        if (
            _read_bounded(
                destination
                / ".knowledgeflow"
                / "transactions"
                / "bootstrap-owner.json"
            )
            != owner_bytes
        ):
            raise _TargetCorrupt
        git.verify(
            destination,
            candidate,
            files,
            expected_parent=None,
            exact_tree=True,
            require_current=False,
            verify_worktree=False,
        )
        return destination, manifest, files, candidate

    staging = parent / f".knowledgeflow-staging-{kb_id.removeprefix('kb_')}"
    if staging.exists():
        _safe_rmtree_owned(staging, parent, owner_bytes)
    staging.mkdir(parents=False, exist_ok=False)
    try:
        _create_directories_for_files(staging, files)
        marker = staging / ".knowledgeflow" / "transactions" / "bootstrap-owner.json"
        durability.write_new_file_durable(marker, owner_bytes)
        for relative, body in files.items():
            path = staging.joinpath(*PurePosixPath(relative).parts)
            durability.write_new_file_durable(path, body)
        template = transaction / "git-template"
        _ensure_directory(template)
        if any(template.iterdir()):
            raise _TargetCorrupt
        checkpoint = git.initialize(
            staging,
            files,
            checkpoint_time=decided_at,
            message="Initialize provisional KnowledgeFlow KB\n",
            template_directory=template,
            persist_candidate=lambda value: _persist_candidate(
                root_candidate_path,
                value,
                durability,
            ),
        )
        durability.commit_directory_no_replace(staging, destination)
        return destination, manifest, files, checkpoint.commit
    finally:
        if staging.exists():
            _safe_rmtree_owned(staging, parent, owner_bytes)


def _capture_body(
    run: CurationRunManifest,
    *,
    config_path: Path,
    path_policy: PathPolicy,
) -> bytes | CurationFailure:
    sink = io.BytesIO()
    result = get_capture(
        GetCaptureRequest(
            capture_id=run.source.capture_id,
            version=run.source.capture_version,
            body_sink=sink,
        ),
        config_path=config_path,
        path_policy=path_policy,
    )
    if isinstance(result, FailureResult):
        code = (
            CurationErrorCode.SOURCE_INTEGRITY_FAILED
            if result.error.code is PublicErrorCode.INTEGRITY_CHECK_FAILED
            else CurationErrorCode.SOURCE_NOT_FOUND
        )
        return _failure(code, stage="capture-read")
    if not isinstance(result, GetCaptureResult):
        return _failure(CurationErrorCode.SOURCE_INTEGRITY_FAILED, stage="capture-read")
    metadata = result.capture
    body = sink.getvalue()
    if (
        metadata.capture_id != run.source.capture_id
        or metadata.version != run.source.capture_version
        or metadata.envelope_sha256 != run.source.envelope_sha256
        or metadata.primary_payload_sha256 != run.source.payload_sha256
        or metadata.byte_size != run.source.byte_size
        or hash_bytes(body).sha256 != run.source.payload_sha256
    ):
        return _failure(CurationErrorCode.SOURCE_INTEGRITY_FAILED, stage="capture-read")
    return body


def _route_raw(
    *,
    repository: Path,
    source_request: SourceInspectResult,
    request: TargetDecideRequest,
    decision: TargetDecision,
    identity: Mapping[str, object],
    base_commit: str,
    git: ManagedGit,
    durability: DurabilityBackend,
    config_path: Path,
    path_policy: PathPolicy,
) -> tuple[RawSourceMapping, RouteRecord, str] | CurationFailure:
    body = _capture_body(
        source_request.run,
        config_path=config_path,
        path_policy=path_policy,
    )
    if isinstance(body, CurationFailure):
        return body
    kb_id = identity["kb_id"]
    route_id = identity["route_id"]
    transaction_id = identity["route_transaction_id"]
    routed_at = identity["decided_at"]
    if not all(type(value) is str for value in (kb_id, route_id, transaction_id, routed_at)):
        raise _TargetCorrupt
    digest = source_request.run.source.payload_sha256.removeprefix("sha256:")[:12]
    payload_path = (
        f"raw/text/{source_request.run.source.capture_id}-"
        f"v{source_request.run.source.capture_version:04d}-{digest}.txt"
    )
    mapping_path = payload_path + ".source.yaml"
    mapping = RawSourceMapping(
        route_id=route_id,
        source=source_request.run.source,
        source_reference=source_request.mapping.source_reference,
        target_kb_id=kb_id,
        payload_path=payload_path,
        payload_sha256=source_request.run.source.payload_sha256,
        archived_at=routed_at,
    )
    mapping_bytes = dump_raw_source_mapping(mapping)
    route = RouteRecord(
        route_id=route_id,
        transaction_id=transaction_id,
        source=source_request.run.source,
        target_kb_id=kb_id,
        target_decision_id=decision.target_decision_id,
        processing_authorization_id=(
            source_request.run.processing_authorization.authorization_id
        ),
        authorization_source=request.authorization_source,
        routed_at=routed_at,
        payload_path=payload_path,
        source_mapping_path=mapping_path,
        payload_sha256=source_request.run.source.payload_sha256,
        source_mapping_sha256=hash_bytes(mapping_bytes).sha256,
        managed_ref=MANAGED_REF,
        base_commit=base_commit,
        version_policy_id=VERSION_POLICY_ID,
        version_policy_revision=VERSION_POLICY_REVISION,
    )
    route_path = f".knowledgeflow/routes/{route_id}.yaml"
    route_bytes = dump_route_record(route)
    expected = {
        payload_path: body,
        mapping_path: mapping_bytes,
        route_path: route_bytes,
    }
    transaction = repository / ".knowledgeflow" / "transactions" / transaction_id
    _ensure_directory(transaction)
    files_directory = transaction / "files"
    _ensure_directory(files_directory)
    for index, (relative, contents) in enumerate(expected.items()):
        destination = repository.joinpath(*PurePosixPath(relative).parts)
        _plain_directory(destination.parent)
        temporary = files_directory / f"{index:02d}.tmp"
        _write_new_or_same(temporary, contents, durability)
        durability.commit_file_no_replace_same_volume(
            temporary,
            destination,
            contents,
        )
        _plain_file(destination)
        if destination.read_bytes() != contents:
            raise _TargetCorrupt

    candidate_path = transaction / "candidate-commit.txt"
    candidate = _candidate(candidate_path)
    if candidate is None:
        index_path = transaction / "isolated.index"
        if index_path.exists():
            _plain_file(index_path)
            index_path.unlink()
        checkpoint = git.checkpoint(
            repository,
            expected,
            base_commit=base_commit,
            checkpoint_time=routed_at,
            message="Route exact Capture source into raw storage\n",
            index_path=index_path,
            persist_candidate=lambda value: _persist_candidate(
                candidate_path,
                value,
                durability,
            ),
        )
        result_commit = checkpoint.commit
    else:
        current = git.current_commit(repository)
        if current == candidate:
            git.verify(
                repository,
                candidate,
                expected,
                expected_parent=base_commit,
                exact_tree=False,
            )
        elif current == base_commit:
            git.recover_checkpoint(
                repository,
                expected,
                base_commit=base_commit,
                candidate_commit=candidate,
            )
        else:
            raise ManagedGitConflict("managed ref diverged during route recovery")
        result_commit = candidate

    receipt = _canonical_json(
        {
            "schema": "knowledgeflow.route-receipt",
            "schema_version": 1,
            "route_id": route_id,
            "transaction_id": transaction_id,
            "base_commit": base_commit,
            "result_commit": result_commit,
            "payload_sha256": route.payload_sha256,
            "source_mapping_sha256": route.source_mapping_sha256,
        }
    )
    receipt_path = repository / ".knowledgeflow" / "receipts" / f"{route_id}.json"
    _write_new_or_same(receipt_path, receipt, durability)
    return mapping, route, result_commit


def _bundle_facts(
    *,
    storage_name: str | None,
    route: RouteRecord | None,
    base_commit: str | None,
    result_commit: str | None,
) -> bytes:
    return _canonical_json(
        {
            "schema": "knowledgeflow.target-result-facts",
            "schema_version": 1,
            "storage_name": storage_name,
            "route_id": None if route is None else route.route_id,
            "base_commit": base_commit,
            "result_commit": result_commit,
        }
    )


def _write_target_bundle(
    *,
    layout: _TargetLayout,
    request_bytes: bytes,
    record: TargetDecisionRecord,
    run: CurationRunManifest,
    route: RouteRecord | None,
    storage_name: str | None,
    base_commit: str | None,
    result_commit: str | None,
    durability: DurabilityBackend,
) -> None:
    staging = Path(tempfile.mkdtemp(prefix="target-", dir=layout.staging_root))
    try:
        files = {
            "request.json": request_bytes,
            "target-decision.yaml": dump_target_decision_record(record),
            "run.yaml": dump_curation_run(run),
            "result.json": _bundle_facts(
                storage_name=storage_name,
                route=route,
                base_commit=base_commit,
                result_commit=result_commit,
            ),
        }
        for name, body in files.items():
            durability.write_new_file_durable(staging / name, body)
        durability.commit_directory_no_replace(
            staging,
            layout.targets_root / record.decision_request_id,
        )
    finally:
        if staging.exists():
            _plain_directory(staging)
            if staging.parent.resolve(strict=True) != layout.staging_root.resolve(strict=True):
                raise _TargetCorrupt
            shutil.rmtree(staging)


def _load_verified_target_bundle(
    directory: Path,
    *,
    request_bytes: bytes,
    parent: Path | None,
    git: ManagedGit,
) -> TargetDecideResult:
    # Load basic artifacts first, then obtain the route from the bound KB and
    # verify all versioned bytes before reporting a replay as successful.
    _plain_directory(directory)
    if frozenset(item.name for item in directory.iterdir()) != _TARGET_BUNDLE_FILES:
        raise _TargetCorrupt
    if _read_bounded(directory / "request.json") != request_bytes:
        raise _IdempotencyConflict
    record = _decode_internal(
        load_target_decision_record,
        _read_bounded(directory / "target-decision.yaml"),
    )
    run = _decode_internal(load_curation_run, _read_bounded(directory / "run.yaml"))
    assert isinstance(record, TargetDecisionRecord)
    assert isinstance(run, CurationRunManifest)
    facts = _load_canonical_json(
        _read_bounded(directory / "result.json"),
        {
            "schema",
            "schema_version",
            "storage_name",
            "route_id",
            "base_commit",
            "result_commit",
        },
    )
    if facts["schema"] != "knowledgeflow.target-result-facts" or facts["schema_version"] != 1:
        raise _TargetCorrupt
    if record.decision.choice == "no-target":
        if parent is not None or any(
            facts[name] is not None
            for name in ("storage_name", "route_id", "base_commit", "result_commit")
        ):
            raise _TargetCorrupt
        route = None
    else:
        if parent is None:
            raise _TargetCorrupt
        storage_name = facts["storage_name"]
        route_id = facts["route_id"]
        base_commit = facts["base_commit"]
        result_commit = facts["result_commit"]
        if not all(type(value) is str for value in (storage_name, route_id, base_commit, result_commit)):
            raise _TargetCorrupt
        binding = record.target_binding
        if binding is None:
            raise _TargetCorrupt
        repository = parent / storage_name
        _plain_directory(repository)
        if (
            _read_bounded(
                repository
                / ".knowledgeflow"
                / "transactions"
                / "bootstrap-owner.json"
            )
            != _bootstrap_owner_bytes(record.decision_request_id, binding.kb_id)
        ):
            raise _TargetCorrupt
        manifest = _decode_internal(
            load_kb_manifest,
            _read_bounded(repository / "kb.yaml"),
        )
        assert isinstance(manifest, KnowledgeBaseManifest)
        if (
            manifest.kb_id != binding.kb_id
            or hash_bytes(dump_kb_manifest(manifest)).sha256
            != binding.manifest_sha256
            or base_commit != binding.base_commit
        ):
            raise _TargetCorrupt
        route_path = repository / ".knowledgeflow" / "routes" / f"{route_id}.yaml"
        route = _decode_internal(load_route_record, _read_bounded(route_path))
        assert isinstance(route, RouteRecord)
        mapping_path = repository.joinpath(*PurePosixPath(route.source_mapping_path).parts)
        payload_path = repository.joinpath(*PurePosixPath(route.payload_path).parts)
        mapping_bytes = _read_bounded(mapping_path)
        mapping = _decode_internal(load_raw_source_mapping, mapping_bytes)
        assert isinstance(mapping, RawSourceMapping)
        payload = _read_bounded(payload_path)
        if (
            route.route_id != route_id
            or route.target_kb_id != binding.kb_id
            or route.target_decision_id != record.decision.target_decision_id
            or route.processing_authorization_id
            != record.processing_authorization_id
            or mapping.route_id != route.route_id
            or mapping.source != record.source
            or mapping.target_kb_id != binding.kb_id
            or mapping.payload_path != route.payload_path
            or hash_bytes(mapping_bytes).sha256 != route.source_mapping_sha256
            or route.source_mapping_sha256 != binding.raw_mapping_sha256
            or hash_bytes(payload).sha256 != route.payload_sha256
            or route.managed_ref != binding.managed_ref
            or route.base_commit != binding.base_commit
            or route.version_policy_id != binding.version_policy_id
            or route.version_policy_revision != binding.version_policy_revision
            or result_commit != git.current_commit(repository)
        ):
            raise _TargetCorrupt
        initial_files = _initial_files(manifest)
        git.verify(
            repository,
            base_commit,
            initial_files,
            expected_parent=None,
            exact_tree=True,
            require_current=False,
            verify_worktree=False,
        )
        expected = {
            route.payload_path: payload,
            route.source_mapping_path: mapping_bytes,
            f".knowledgeflow/routes/{route.route_id}.yaml": dump_route_record(route),
        }
        if git.changed_paths(repository, base_commit, result_commit) != frozenset(expected):
            raise _TargetCorrupt
        git.verify(
            repository,
            result_commit,
            expected,
            expected_parent=base_commit,
            exact_tree=False,
        )
        receipt = _load_canonical_json(
            _read_bounded(
                repository
                / ".knowledgeflow"
                / "receipts"
                / f"{route.route_id}.json"
            ),
            {
                "schema",
                "schema_version",
                "route_id",
                "transaction_id",
                "base_commit",
                "result_commit",
                "payload_sha256",
                "source_mapping_sha256",
            },
        )
        if receipt != {
            "schema": "knowledgeflow.route-receipt",
            "schema_version": 1,
            "route_id": route.route_id,
            "transaction_id": route.transaction_id,
            "base_commit": base_commit,
            "result_commit": result_commit,
            "payload_sha256": route.payload_sha256,
            "source_mapping_sha256": route.source_mapping_sha256,
        }:
            raise _TargetCorrupt
    return TargetDecideResult(
        decision_request_id=record.decision_request_id,
        record=record,
        updated_run=run,
        route=route,
        storage_name=facts["storage_name"],
        base_commit=facts["base_commit"],
        result_commit=facts["result_commit"],
        replayed=True,
    )


def target_decide(
    request: TargetDecideRequest,
    *,
    experiment_root: str | os.PathLike[str],
    path_policy: PathPolicy,
    root_policy: KnowledgeBaseRootPolicy | None = None,
    git: ManagedGit | None = None,
    durability: DurabilityBackend | None = None,
    now: Callable[[], datetime] | None = None,
) -> TargetDecideOperationResult:
    """Record one target decision and, when approved, create and route safely."""

    published_kb = False
    try:
        if not isinstance(request, TargetDecideRequest):
            raise TypeError("request must be TargetDecideRequest")
        if not isinstance(path_policy, PathPolicy):
            raise TypeError("path_policy must be PathPolicy")
        selected_git = git or ManagedGit()
        selected_durability = durability or DurabilityBackend()
        if not isinstance(selected_git, ManagedGit):
            raise TypeError("git must be ManagedGit")
        if not isinstance(selected_durability, DurabilityBackend):
            raise TypeError("durability must be DurabilityBackend")
        clock = now or (lambda: datetime.now(timezone.utc))
        layout = _layout(experiment_root)
        source = inspect_source(
            SourceInspectRequest(request_id=request.source_request_id),
            experiment_root=layout.root,
        )
        if not isinstance(source, SourceInspectResult):
            return _failure(
                source.error.code,
                retryable=source.error.retryable,
                stage="source-inspect",
            )
        parent: Path | None = None
        parent_index: int | None = None
        if request.choice == "new-kb":
            if not isinstance(root_policy, KnowledgeBaseRootPolicy):
                return _failure(CurationErrorCode.TARGET_NOT_CONFIRMED, stage="root-policy")
            assert request.kb_parent is not None
            parent_index, parent = root_policy.select(request.kb_parent)
        elif root_policy is not None:
            raise ValueError("no-target does not accept a root policy")
        request_body = _request_bytes(
            request,
            parent_index=parent_index,
            policy=root_policy,
        )
        _prepare_layout(layout)
        destination = layout.targets_root / request.decision_request_id
        lock_path = layout.locks_root / f"{request.decision_request_id}.lock"
        with exclusive_file_lock(lock_path):
            if destination.exists():
                published_kb = request.choice == "new-kb"
                return _load_verified_target_bundle(
                    destination,
                    request_bytes=request_body,
                    parent=parent,
                    git=selected_git,
                )

            transaction = layout.transactions_root / request.decision_request_id
            transaction_created = False
            try:
                transaction.mkdir(parents=False, exist_ok=False)
                transaction_created = True
            except FileExistsError:
                pass
            _plain_directory(transaction)
            transaction_request = transaction / "request.json"
            if transaction_request.exists():
                if _read_bounded(transaction_request) != request_body:
                    raise _IdempotencyConflict
            else:
                if not transaction_created:
                    raise _TargetCorrupt
                selected_durability.write_new_file_durable(
                    transaction_request,
                    request_body,
                )

            if request.choice == "new-kb":
                assert parent is not None
                root_lock = parent / ".knowledgeflow-parent.lock"
                parent_context = exclusive_file_lock(root_lock)
            else:
                parent_context = exclusive_file_lock(
                    layout.locks_root / f"{request.decision_request_id}.work.lock"
                )

            with parent_context:
                identity_path = transaction / "identity.json"
                identity: Mapping[str, object] | None = None
                if identity_path.exists():
                    identity = _load_identity(_read_bounded(identity_path))
                    frozen_name = identity["storage_name"]
                    if parent is not None and type(frozen_name) is str:
                        published_kb = (parent / frozen_name).exists()
                reserved_names: frozenset[str] = frozenset()
                if parent is not None:
                    assert root_policy is not None and parent_index is not None
                    reserved_names = _reserved_storage_names(
                        layout.transactions_root,
                        current_request_id=request.decision_request_id,
                        policy=root_policy,
                        parent_index=parent_index,
                    )
                if identity is not None:
                    frozen_name = identity["storage_name"]
                    if (
                        request.choice == "new-kb"
                        and (
                            type(frozen_name) is not str
                            or frozen_name.casefold() in reserved_names
                        )
                    ):
                        raise _TargetConflict
                else:
                    instant = clock()
                    if not isinstance(instant, datetime):
                        raise TypeError("now must return datetime")
                    if instant.tzinfo is None or instant.utcoffset() is None:
                        raise ValueError("now must return an aware datetime")
                    instant = instant.astimezone(timezone.utc)
                    decided_at = format_utc_milliseconds(instant)
                    storage_name: str | None = None
                    if parent is not None:
                        storage_name = request.storage_name or _next_date_name(
                            parent,
                            instant.astimezone(_fixed_timezone(request.naming_timezone))
                            .date()
                            .isoformat(),
                            reserved_names,
                        )
                        if not _portable_name_is_available(
                            parent,
                            storage_name,
                            reserved_names,
                        ):
                            raise _TargetConflict
                    identity_body = _identity_bytes(
                        request=request,
                        decided_at=decided_at,
                        storage_name=storage_name,
                    )
                    selected_durability.write_new_file_durable(identity_path, identity_body)
                    identity = _load_identity(identity_body)

                assert identity is not None
                if parent is not None:
                    selected_git.require_standalone_parent(parent)

                try:
                    suggestion = (
                        None
                        if request.suggestion_choice is None
                        else TargetSuggestion(
                            choice=request.suggestion_choice,
                            rationale=request.suggestion_rationale,
                            suggested_by=request.suggested_by,
                            suggested_at=identity["decided_at"],
                        )
                    )
                    decision = TargetDecision(
                        target_decision_id=identity["target_decision_id"],
                        choice=request.choice,
                        requested_display_name=request.display_name,
                        target_kb_id=None,
                        decided_by=request.decided_by,
                        decided_at=identity["decided_at"],
                    )
                except (TypeError, ValueError) as exc:
                    raise _TargetCorrupt from exc
                updated_run = replace(source.run, target_decision=decision)

                if request.choice == "no-target":
                    record = TargetDecisionRecord(
                        decision_request_id=request.decision_request_id,
                        source_request_id=request.source_request_id,
                        curation_run_id=source.run.curation_run_id,
                        source=source.run.source,
                        processing_authorization_id=(
                            source.run.processing_authorization.authorization_id
                        ),
                        suggestion=suggestion,
                        decision=decision,
                        root_policy_id=None,
                        root_policy_revision=None,
                        target_storage_name=None,
                        target_binding=None,
                    )
                    _write_target_bundle(
                        layout=layout,
                        request_bytes=request_body,
                        record=record,
                        run=updated_run,
                        route=None,
                        storage_name=None,
                        base_commit=None,
                        result_commit=None,
                        durability=selected_durability,
                    )
                    return TargetDecideResult(
                        request.decision_request_id,
                        record,
                        updated_run,
                        None,
                        None,
                        None,
                        None,
                    )

                assert parent is not None and root_policy is not None
                repository, manifest, _, base_commit = _bootstrap_kb(
                    parent=parent,
                    identity=identity,
                    request=request,
                    git=selected_git,
                    durability=selected_durability,
                    transaction=transaction,
                )
                published_kb = True
                routed = _route_raw(
                    repository=repository,
                    source_request=source,
                    request=request,
                    decision=decision,
                    identity=identity,
                    base_commit=base_commit,
                    git=selected_git,
                    durability=selected_durability,
                    config_path=layout.config_path,
                    path_policy=path_policy,
                )
                if isinstance(routed, CurationFailure):
                    return CurationFailure(routed.error, CurationCommitState.UNKNOWN)
                mapping, route, result_commit = routed
                binding = TargetBinding(
                    kb_id=manifest.kb_id,
                    manifest_sha256=hash_bytes(dump_kb_manifest(manifest)).sha256,
                    raw_mapping_sha256=hash_bytes(dump_raw_source_mapping(mapping)).sha256,
                    managed_ref=MANAGED_REF,
                    base_commit=base_commit,
                    version_policy_id=VERSION_POLICY_ID,
                    version_policy_revision=VERSION_POLICY_REVISION,
                )
                record = TargetDecisionRecord(
                    decision_request_id=request.decision_request_id,
                    source_request_id=request.source_request_id,
                    curation_run_id=source.run.curation_run_id,
                    source=source.run.source,
                    processing_authorization_id=(
                        source.run.processing_authorization.authorization_id
                    ),
                    suggestion=suggestion,
                    decision=decision,
                    root_policy_id=root_policy.policy_id,
                    root_policy_revision=root_policy.revision,
                    target_storage_name=manifest.storage_name,
                    target_binding=binding,
                )
                _write_target_bundle(
                    layout=layout,
                    request_bytes=request_body,
                    record=record,
                    run=updated_run,
                    route=route,
                    storage_name=manifest.storage_name,
                    base_commit=base_commit,
                    result_commit=result_commit,
                    durability=selected_durability,
                )
                return TargetDecideResult(
                    request.decision_request_id,
                    record,
                    updated_run,
                    route,
                    manifest.storage_name,
                    base_commit,
                    result_commit,
                )
    except _IdempotencyConflict:
        return _failure(
            CurationErrorCode.IDEMPOTENCY_CONFLICT,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="target-replay",
        )
    except _TargetConflict:
        return _failure(
            CurationErrorCode.TARGET_CONFLICT,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="target-state",
        )
    except ManagedGitUnavailable:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="version-control",
        )
    except (ManagedGitConflict, ManagedGitIntegrityError):
        return _failure(
            CurationErrorCode.TARGET_CONFLICT,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            stage="managed-ref",
        )
    except ManagedGitError:
        return _failure(
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            retryable=True,
            stage="version-control",
        )
    except (_TargetCorrupt, LockUnavailable):
        return _failure(
            CurationErrorCode.RECOVERY_REQUIRED,
            state=CurationCommitState.UNKNOWN,
            retryable=True,
            stage="target-recovery",
        )
    except (DestinationAlreadyExistsError, DurabilityError, OSError):
        return _failure(
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
            state=(
                CurationCommitState.UNKNOWN
                if published_kb
                else CurationCommitState.NOT_COMMITTED
            ),
            retryable=True,
            stage="target-publish",
        )
    except (TypeError, ValueError):
        return _failure(CurationErrorCode.INVALID_INPUT, stage="validate")


__all__ = [
    "KnowledgeBaseRootPolicy",
    "TargetDecideOperationResult",
    "TargetDecideRequest",
    "TargetDecideResult",
    "target_decide",
]
