"""Windows-local path normalization and trusted capture-root policies."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import ntpath
import os
from pathlib import Path
import re
import stat
import tempfile


class PathPolicyError(ValueError):
    """A path is outside the selected trusted policy boundary."""


PathResolver = Callable[[Path], Path]
MarkerProbe = Callable[[Path], bool]

_LOCAL_DRIVE = re.compile(r"[A-Za-z]:\Z")
_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\", "//?/", "//./")


def normalize_windows_local_absolute_path(value: str | os.PathLike[str]) -> Path:
    """Return a normalized drive-local Windows path without consulting the CWD."""

    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise PathPolicyError("path must be text or a path-like value") from exc
    if type(raw) is not str or raw == "" or "\x00" in raw:
        raise PathPolicyError("path must be non-empty Windows text")
    if raw.startswith(_DEVICE_PREFIXES):
        raise PathPolicyError("Windows device namespace paths are not allowed")

    drive, tail = ntpath.splitdrive(raw)
    if drive.startswith(("\\\\", "//")):
        raise PathPolicyError("UNC paths are not allowed")
    if _LOCAL_DRIVE.fullmatch(drive) is None or not tail.startswith(("\\", "/")):
        raise PathPolicyError("path must be an absolute local-drive Windows path")

    components = re.split(r"[\\/]", tail)
    if ".." in components:
        raise PathPolicyError("parent traversal segments are not allowed")

    normalized_tail = ntpath.normpath(tail)
    normalized = drive.upper() + normalized_tail
    return Path(normalized)


def _default_resolver(path: Path) -> Path:
    return path.resolve(strict=False)


def _default_marker_probe(path: Path) -> bool:
    try:
        result = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISREG(result.st_mode)


def _path_key(path: Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def _is_within(path: Path, parent: Path) -> bool:
    child_key = _path_key(path)
    parent_key = _path_key(parent)
    try:
        return ntpath.commonpath((child_key, parent_key)) == parent_key
    except ValueError:
        return False


def _ancestors_including(path: Path) -> tuple[Path, ...]:
    result: list[Path] = [path]
    result.extend(path.parents)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PathPolicy:
    """Trusted construction-time policy for production or test-owned roots.

    The test-owned allowance is an injected object capability. It is intentionally
    not representable in the local YAML configuration.
    """

    _test_owned_root: Path | None
    _protected_roots: tuple[Path, ...]
    _resolver: PathResolver = field(repr=False, compare=False)
    _marker_probe: MarkerProbe = field(repr=False, compare=False)

    @classmethod
    def production(
        cls,
        *,
        source_root: str | os.PathLike[str],
        system_temp_root: str | os.PathLike[str] | None = None,
        gbrain_roots: Iterable[str | os.PathLike[str]] = (),
        resolver: PathResolver | None = None,
        marker_probe: MarkerProbe | None = None,
    ) -> PathPolicy:
        selected_temp = (
            Path(tempfile.gettempdir())
            if system_temp_root is None
            else system_temp_root
        )
        protected = (
            normalize_windows_local_absolute_path(source_root),
            normalize_windows_local_absolute_path(selected_temp),
            *(
                normalize_windows_local_absolute_path(root)
                for root in gbrain_roots
            ),
        )
        return cls(
            _test_owned_root=None,
            _protected_roots=protected,
            _resolver=resolver or _default_resolver,
            _marker_probe=marker_probe or _default_marker_probe,
        )

    @classmethod
    def test_owned(
        cls,
        owned_root: str | os.PathLike[str],
        *,
        resolver: PathResolver | None = None,
    ) -> PathPolicy:
        return cls(
            _test_owned_root=normalize_windows_local_absolute_path(owned_root),
            _protected_roots=(),
            _resolver=resolver or _default_resolver,
            _marker_probe=_default_marker_probe,
        )

    def _resolve(self, path: Path) -> Path:
        try:
            resolved = self._resolver(path)
        except (OSError, RuntimeError) as exc:
            raise PathPolicyError("path resolution failed") from exc
        try:
            return normalize_windows_local_absolute_path(resolved)
        except PathPolicyError as exc:
            raise PathPolicyError("resolved path is outside local Windows paths") from exc

    def _contains_kb_marker(self, *paths: Path) -> bool:
        seen: set[str] = set()
        for path in paths:
            for ancestor in _ancestors_including(path):
                key = _path_key(ancestor)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    if self._marker_probe(ancestor / "kb.yaml"):
                        return True
                except OSError as exc:
                    raise PathPolicyError("KB ancestor verification failed") from exc
        return False

    def validate_capture_root(
        self,
        value: str | os.PathLike[str],
    ) -> Path:
        """Normalize and validate one Capture Store root without writing to it."""

        candidate = normalize_windows_local_absolute_path(value)
        resolved_candidate = self._resolve(candidate)

        if self._test_owned_root is not None:
            resolved_owner = self._resolve(self._test_owned_root)
            if not _is_within(candidate, self._test_owned_root) or not _is_within(
                resolved_candidate,
                resolved_owner,
            ):
                raise PathPolicyError("capture root escapes the test-owned root")
            return resolved_candidate

        for protected in self._protected_roots:
            resolved_protected = self._resolve(protected)
            if _is_within(candidate, protected) or _is_within(
                resolved_candidate,
                resolved_protected,
            ):
                raise PathPolicyError("capture root is inside a protected directory")

        if self._contains_kb_marker(candidate, resolved_candidate):
            raise PathPolicyError("capture root is inside a knowledge base")
        return resolved_candidate


__all__ = [
    "PathPolicy",
    "PathPolicyError",
    "normalize_windows_local_absolute_path",
]
