"""Controlled, offline Git checkpoints for governed curation artifacts.

The adapter deliberately supports only the small set of local operations needed
by CUR1C.  It never invokes a transport command, never reads the user's Git
identity, and always compares the managed ref before updating it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import unicodedata


MANAGED_REF = "refs/heads/knowledgeflow"
VERSION_POLICY_ID = "knowledgeflow-managed-local-git"
VERSION_POLICY_REVISION = 1
TECHNICAL_AUTHOR_NAME = "KnowledgeFlow"
TECHNICAL_AUTHOR_EMAIL = "knowledgeflow@local.invalid"

_ZERO_SHA1 = "0" * 40
_GIT_MODE = "100644"
_REPARSE_ATTRIBUTE = 0x400


class ManagedGitError(RuntimeError):
    """Base class for path-free controlled Git failures."""


class ManagedGitUnavailable(ManagedGitError):
    """The selected Git executable is absent or cannot run safely."""


class ManagedGitConflict(ManagedGitError):
    """The managed ref or a managed path changed concurrently."""


class ManagedGitIntegrityError(ManagedGitError):
    """The repository does not match the frozen checkpoint policy."""


@dataclass(frozen=True, slots=True)
class ManagedCheckpoint:
    commit: str
    tree: str
    parent: str | None


def _is_reparse(value: os.stat_result) -> bool:
    return bool(getattr(value, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _plain_file(path: Path) -> os.stat_result:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or _is_reparse(value):
        raise ManagedGitIntegrityError("managed path is not a plain file")
    return value


def _plain_directory(path: Path) -> os.stat_result:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or _is_reparse(value):
        raise ManagedGitIntegrityError("managed path is not a plain directory")
    return value


def _relative_path(value: str) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        raise ValueError("managed path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("managed path must not escape the repository")
    if path.parts[0] == ".git":
        raise ValueError("managed path must not enter Git metadata")
    canonical = path.as_posix()
    if canonical != value:
        raise ValueError("managed path must be canonical POSIX text")
    return canonical


def _normalized_paths(values: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError("managed files must be a non-empty mapping")
    result: dict[str, bytes] = {}
    portable: set[str] = set()
    for raw_path, raw_bytes in values.items():
        path = _relative_path(raw_path)
        if not isinstance(raw_bytes, bytes):
            raise TypeError("managed file contents must be bytes")
        key = unicodedata.normalize("NFC", path).casefold()
        if key in portable:
            raise ValueError("managed paths collide under portable normalization")
        portable.add(key)
        result[path] = raw_bytes
    return result


def _git_timestamp(value: str) -> str:
    if type(value) is not str:
        raise ValueError("checkpoint timestamp must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("checkpoint timestamp must be canonical UTC text") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("checkpoint timestamp must use UTC")
    return f"@{int(parsed.timestamp())} +0000"


class ManagedGit:
    """Small allowlisted Git CLI adapter with isolated configuration."""

    def __init__(self, binary: str = "git") -> None:
        if type(binary) is not str or not binary or "\x00" in binary:
            raise ValueError("Git binary must be non-empty text")
        self._binary = binary

    @staticmethod
    def _base_environment() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_LITERAL_PATHSPECS": "1",
                "GIT_PAGER": "cat",
                "GIT_EDITOR": "true",
                "LC_ALL": "C",
                "LANG": "C",
            }
        )
        return environment

    @staticmethod
    def _policy_arguments() -> list[str]:
        return [
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.safecrlf=false",
            "-c",
            "core.filemode=false",
            "-c",
            "core.symlinks=false",
            "-c",
            "core.hooksPath=.knowledgeflow/no-hooks",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "gc.auto=0",
            "-c",
            "credential.helper=",
        ]

    def _run(
        self,
        repository: Path,
        arguments: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        index_path: Path | None = None,
        identity_timestamp: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = self._base_environment()
        if index_path is not None:
            environment["GIT_INDEX_FILE"] = str(index_path)
        if identity_timestamp is not None:
            timestamp = _git_timestamp(identity_timestamp)
            environment.update(
                {
                    "GIT_AUTHOR_NAME": TECHNICAL_AUTHOR_NAME,
                    "GIT_AUTHOR_EMAIL": TECHNICAL_AUTHOR_EMAIL,
                    "GIT_COMMITTER_NAME": TECHNICAL_AUTHOR_NAME,
                    "GIT_COMMITTER_EMAIL": TECHNICAL_AUTHOR_EMAIL,
                    "GIT_AUTHOR_DATE": timestamp,
                    "GIT_COMMITTER_DATE": timestamp,
                }
            )
        command = [self._binary, *self._policy_arguments(), *arguments]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                command,
                cwd=repository,
                env=environment,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
                creationflags=creationflags,
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
            raise ManagedGitUnavailable("controlled Git is unavailable") from exc
        if check and completed.returncode != 0:
            raise ManagedGitError("controlled Git command failed")
        return completed

    def check_available(self, working_directory: Path) -> None:
        _plain_directory(working_directory)
        completed = self._run(working_directory, ("--version",), check=False)
        if completed.returncode != 0 or not completed.stdout.startswith(b"git version "):
            raise ManagedGitUnavailable("controlled Git is unavailable")

    def require_standalone_parent(self, parent: Path) -> None:
        """Reject a target parent that is already inside another worktree."""

        _plain_directory(parent)
        for candidate in (parent, *parent.parents):
            if os.path.lexists(candidate / ".git"):
                raise ManagedGitConflict(
                    "target parent is inside another Git worktree"
                )
        self.check_available(parent)
        completed = self._run(
            parent,
            ("rev-parse", "--show-toplevel"),
            check=False,
        )
        if completed.returncode == 0:
            raise ManagedGitConflict("target parent is inside another Git worktree")
        if completed.stdout.strip() or completed.returncode != 128:
            raise ManagedGitUnavailable("Git worktree boundary cannot be verified")

    def _current_ref(self, repository: Path) -> str | None:
        completed = self._run(
            repository,
            ("rev-parse", "--verify", "--quiet", MANAGED_REF),
            check=False,
        )
        if completed.returncode == 1 and not completed.stdout:
            return None
        if completed.returncode != 0:
            raise ManagedGitIntegrityError("managed ref cannot be read")
        value = completed.stdout.decode("ascii", errors="strict").strip()
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ManagedGitIntegrityError("managed ref is not a SHA-1 object ID")
        return value

    def current_commit(self, repository: Path) -> str:
        value = self._current_ref(repository)
        if value is None:
            raise ManagedGitIntegrityError("managed ref does not exist")
        return value

    def _require_repository_identity(self, repository: Path) -> None:
        _plain_directory(repository)
        _plain_directory(repository / ".git")
        top_level = self._run(
            repository,
            ("rev-parse", "--show-toplevel"),
        ).stdout.decode("utf-8", errors="strict").strip()
        if os.path.normcase(os.path.abspath(top_level)) != os.path.normcase(
            os.path.abspath(repository)
        ):
            raise ManagedGitIntegrityError("managed repository worktree changed")
        bare = self._run(
            repository,
            ("rev-parse", "--is-bare-repository"),
        ).stdout.decode("ascii", errors="strict").strip()
        if bare != "false":
            raise ManagedGitIntegrityError("managed repository became bare")
        symbolic = self._run(repository, ("symbolic-ref", "-q", "HEAD"), check=False)
        if symbolic.returncode != 0 or symbolic.stdout.decode(
            "utf-8", errors="strict"
        ).strip() != MANAGED_REF:
            raise ManagedGitIntegrityError("HEAD is not the managed symbolic ref")
        remotes = self._run(repository, ("remote",)).stdout
        if remotes.strip():
            raise ManagedGitIntegrityError("managed repository has a remote")
        object_format = self._run(
            repository,
            ("rev-parse", "--show-object-format"),
        ).stdout.decode("ascii", errors="strict").strip()
        if object_format != "sha1":
            raise ManagedGitIntegrityError("managed repository object format changed")

    def _tree_entries(
        self,
        repository: Path,
        commit: str,
    ) -> dict[str, tuple[str, str]]:
        output = self._run(
            repository,
            ("ls-tree", "-r", "-z", "--full-tree", commit),
        ).stdout
        result: dict[str, tuple[str, str]] = {}
        for raw_record in output.split(b"\0"):
            if not raw_record:
                continue
            try:
                metadata, raw_path = raw_record.split(b"\t", 1)
                mode, kind, object_id = metadata.decode("ascii").split(" ")
                path = raw_path.decode("utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError) as exc:
                raise ManagedGitIntegrityError("Git tree output is invalid") from exc
            if kind != "blob" or mode != _GIT_MODE:
                raise ManagedGitIntegrityError("managed tree contains a non-regular entry")
            _relative_path(path)
            result[path] = (mode, object_id)
        return result

    def _verify_commit_files(
        self,
        repository: Path,
        commit: str,
        expected_files: Mapping[str, bytes],
        *,
        exact_tree: bool,
        verify_worktree: bool = True,
    ) -> str:
        expected = _normalized_paths(expected_files)
        entries = self._tree_entries(repository, commit)
        if exact_tree and set(entries) != set(expected):
            raise ManagedGitIntegrityError("managed root tree has unexpected paths")
        if not set(expected).issubset(entries):
            raise ManagedGitIntegrityError("managed commit is missing expected paths")
        portable: set[str] = set()
        for path in entries:
            key = unicodedata.normalize("NFC", path).casefold()
            if key in portable:
                raise ManagedGitIntegrityError("Git tree has a portable path collision")
            portable.add(key)
        for path, expected_bytes in expected.items():
            if verify_worktree:
                actual_path = repository.joinpath(*PurePosixPath(path).parts)
                _plain_file(actual_path)
                if actual_path.read_bytes() != expected_bytes:
                    raise ManagedGitIntegrityError(
                        "working tree bytes differ from checkpoint"
                    )
            object_id = entries[path][1]
            blob = self._run(repository, ("cat-file", "blob", object_id)).stdout
            if blob != expected_bytes:
                raise ManagedGitIntegrityError("Git blob differs from checkpoint bytes")
        tree = self._run(repository, ("show", "-s", "--format=%T", commit)).stdout
        value = tree.decode("ascii", errors="strict").strip()
        if len(value) != 40:
            raise ManagedGitIntegrityError("checkpoint tree is invalid")
        return value

    def _verify_parent(
        self,
        repository: Path,
        commit: str,
        expected_parent: str | None,
    ) -> None:
        parents = self._run(repository, ("show", "-s", "--format=%P", commit)).stdout
        values = parents.decode("ascii", errors="strict").strip().split()
        if expected_parent is None:
            if values:
                raise ManagedGitIntegrityError("root checkpoint unexpectedly has a parent")
        elif values != [expected_parent]:
            raise ManagedGitIntegrityError("checkpoint parent does not match the base")

    def _verify_identity(self, repository: Path, commit: str) -> None:
        output = self._run(
            repository,
            ("show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", commit),
        ).stdout.rstrip(b"\n")
        expected = b"\0".join(
            (
                TECHNICAL_AUTHOR_NAME.encode("ascii"),
                TECHNICAL_AUTHOR_EMAIL.encode("ascii"),
                TECHNICAL_AUTHOR_NAME.encode("ascii"),
                TECHNICAL_AUTHOR_EMAIL.encode("ascii"),
            )
        )
        if output != expected:
            raise ManagedGitIntegrityError("checkpoint identity is not controlled")

    def _align_index(
        self,
        repository: Path,
        commit: str,
        paths: Sequence[str],
    ) -> None:
        entries = self._tree_entries(repository, commit)
        for path in paths:
            mode, object_id = entries[path]
            self._run(
                repository,
                ("update-index", "--add", "--cacheinfo", f"{mode},{object_id},{path}"),
            )

    def initialize(
        self,
        repository: Path,
        expected_files: Mapping[str, bytes],
        *,
        checkpoint_time: str,
        message: str,
        template_directory: Path,
        persist_candidate: Callable[[str], None],
    ) -> ManagedCheckpoint:
        expected = _normalized_paths(expected_files)
        _plain_directory(repository)
        _plain_directory(template_directory)
        if (repository / ".git").exists():
            raise ManagedGitConflict("target already contains Git metadata")
        self.check_available(repository)
        self._run(
            repository,
            (
                "init",
                "--quiet",
                "--object-format=sha1",
                "--initial-branch=knowledgeflow",
                f"--template={template_directory}",
                ".",
            ),
        )
        self._run(repository, ("symbolic-ref", "HEAD", MANAGED_REF))
        self._run(repository, ("add", "--", *sorted(expected)))
        tree = self._run(repository, ("write-tree",)).stdout.decode("ascii").strip()
        commit = self._run(
            repository,
            ("commit-tree", tree, "-F", "-"),
            input_bytes=message.encode("utf-8"),
            identity_timestamp=checkpoint_time,
        ).stdout.decode("ascii").strip()
        persist_candidate(commit)
        updated = self._run(
            repository,
            ("update-ref", MANAGED_REF, commit, _ZERO_SHA1),
            check=False,
        )
        if updated.returncode != 0:
            raise ManagedGitConflict("managed ref changed during root checkpoint")
        self.verify(
            repository,
            commit,
            expected,
            expected_parent=None,
            exact_tree=True,
        )
        return ManagedCheckpoint(commit=commit, tree=tree, parent=None)

    def checkpoint(
        self,
        repository: Path,
        expected_files: Mapping[str, bytes],
        *,
        base_commit: str,
        checkpoint_time: str,
        message: str,
        index_path: Path,
        persist_candidate: Callable[[str], None],
    ) -> ManagedCheckpoint:
        expected = _normalized_paths(expected_files)
        self._require_repository_identity(repository)
        if self.current_commit(repository) != base_commit:
            raise ManagedGitConflict("managed ref changed before checkpoint")
        if index_path.exists():
            raise ManagedGitConflict("isolated index path already exists")
        _plain_directory(index_path.parent)
        self._run(
            repository,
            ("read-tree", base_commit),
            index_path=index_path,
        )
        self._run(
            repository,
            ("add", "--", *sorted(expected)),
            index_path=index_path,
        )
        tree = self._run(
            repository,
            ("write-tree",),
            index_path=index_path,
        ).stdout.decode("ascii").strip()
        commit = self._run(
            repository,
            ("commit-tree", tree, "-p", base_commit, "-F", "-"),
            input_bytes=message.encode("utf-8"),
            identity_timestamp=checkpoint_time,
        ).stdout.decode("ascii").strip()
        persist_candidate(commit)
        updated = self._run(
            repository,
            ("update-ref", MANAGED_REF, commit, base_commit),
            check=False,
        )
        if updated.returncode != 0:
            raise ManagedGitConflict("managed ref changed during checkpoint")
        self._align_index(repository, commit, sorted(expected))
        self.verify(
            repository,
            commit,
            expected,
            expected_parent=base_commit,
            exact_tree=False,
        )
        changed = self.changed_paths(repository, base_commit, commit)
        if changed != frozenset(expected):
            raise ManagedGitIntegrityError("checkpoint changed paths outside its batch")
        for path in expected:
            unstaged = self._run(
                repository,
                ("diff", "--quiet", "--", path),
                check=False,
            )
            staged = self._run(
                repository,
                ("diff", "--cached", "--quiet", "--", path),
                check=False,
            )
            if unstaged.returncode != 0 or staged.returncode != 0:
                raise ManagedGitIntegrityError("checkpoint path is not clean")
        return ManagedCheckpoint(commit=commit, tree=tree, parent=base_commit)

    def recover_checkpoint(
        self,
        repository: Path,
        expected_files: Mapping[str, bytes],
        *,
        base_commit: str,
        candidate_commit: str,
    ) -> ManagedCheckpoint:
        expected = _normalized_paths(expected_files)
        self._require_repository_identity(repository)
        self.verify(
            repository,
            candidate_commit,
            expected,
            expected_parent=base_commit,
            exact_tree=False,
            require_current=False,
        )
        if self.changed_paths(repository, base_commit, candidate_commit) != frozenset(
            expected
        ):
            raise ManagedGitIntegrityError("recovery candidate changed other paths")
        current = self._current_ref(repository)
        if current == base_commit:
            updated = self._run(
                repository,
                ("update-ref", MANAGED_REF, candidate_commit, base_commit),
                check=False,
            )
            if updated.returncode != 0:
                raise ManagedGitConflict("managed ref changed during recovery")
        elif current != candidate_commit:
            raise ManagedGitConflict("managed ref diverged from recovery candidate")
        self._align_index(repository, candidate_commit, sorted(expected))
        tree = self._verify_commit_files(
            repository,
            candidate_commit,
            expected,
            exact_tree=False,
        )
        return ManagedCheckpoint(candidate_commit, tree, base_commit)

    def verify(
        self,
        repository: Path,
        commit: str,
        expected_files: Mapping[str, bytes],
        *,
        expected_parent: str | None,
        exact_tree: bool,
        require_current: bool = True,
        verify_worktree: bool = True,
    ) -> None:
        self._require_repository_identity(repository)
        if require_current and self.current_commit(repository) != commit:
            raise ManagedGitIntegrityError("managed ref is not the expected checkpoint")
        self._verify_parent(repository, commit, expected_parent)
        self._verify_identity(repository, commit)
        self._verify_commit_files(
            repository,
            commit,
            expected_files,
            exact_tree=exact_tree,
            verify_worktree=verify_worktree,
        )

    def changed_paths(
        self,
        repository: Path,
        base_commit: str,
        result_commit: str,
    ) -> frozenset[str]:
        output = self._run(
            repository,
            (
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                base_commit,
                result_commit,
            ),
        ).stdout
        try:
            values = {
                _relative_path(item.decode("utf-8", errors="strict"))
                for item in output.split(b"\0")
                if item
            }
        except UnicodeDecodeError as exc:
            raise ManagedGitIntegrityError("checkpoint paths are not UTF-8") from exc
        return frozenset(values)


__all__ = [
    "MANAGED_REF",
    "TECHNICAL_AUTHOR_EMAIL",
    "TECHNICAL_AUTHOR_NAME",
    "VERSION_POLICY_ID",
    "VERSION_POLICY_REVISION",
    "ManagedCheckpoint",
    "ManagedGit",
    "ManagedGitConflict",
    "ManagedGitError",
    "ManagedGitIntegrityError",
    "ManagedGitUnavailable",
]
