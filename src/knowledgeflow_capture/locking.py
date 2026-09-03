"""Windows kernel lock for Capture Store initialization."""

from __future__ import annotations

from collections.abc import Callable
import errno
import math
import os
from pathlib import Path
import stat
import time
from typing import BinaryIO

from .errors import OperationError, PublicErrorCode
from .paths import PathPolicyError, normalize_windows_local_absolute_path

try:
    import msvcrt
except ModuleNotFoundError:  # pragma: no cover - exercised only off Windows
    msvcrt = None


DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
_DEFAULT_POLL_INTERVAL_SECONDS = 0.05
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_Clock = Callable[[], float]
_Sleeper = Callable[[float], None]


class InitializationLockError(RuntimeError):
    """A safe, path-free failure to acquire or release the initialization lock."""

    def __init__(self, *, retryable: bool) -> None:
        self.code = PublicErrorCode.CAPTURE_STORE_UNAVAILABLE
        self.retryable = retryable
        super().__init__("capture initialization lock is unavailable")

    def to_operation_error(self) -> OperationError:
        return OperationError(code=self.code, retryable=self.retryable)


class InitializationLock:
    """One acquired byte-range lock; closing the handle releases it in the OS."""

    __slots__ = ("config_path", "lock_path", "_stream")

    def __init__(
        self,
        *,
        config_path: Path,
        lock_path: Path,
        stream: BinaryIO,
    ) -> None:
        self.config_path = config_path
        self.lock_path = lock_path
        self._stream: BinaryIO | None = stream

    @property
    def is_held(self) -> bool:
        return self._stream is not None

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        release_failed = False
        try:
            stream.seek(0)
            if msvcrt is None:  # pragma: no cover - guarded during acquisition
                release_failed = True
            else:
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            release_failed = True
        finally:
            try:
                stream.close()
            except OSError:
                release_failed = True
        if release_failed:
            raise InitializationLockError(retryable=False)

    def __enter__(self) -> InitializationLock:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            self.release()
        except InitializationLockError:
            if exc_type is None:
                raise
        return False


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _lstat_if_present(path: Path) -> os.stat_result | None:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_plain_directory(path: Path) -> None:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise InitializationLockError(retryable=False) from exc
    if not stat.S_ISDIR(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise InitializationLockError(retryable=False)


def _require_optional_plain_file(path: Path) -> None:
    try:
        path_stat = _lstat_if_present(path)
    except OSError as exc:
        raise InitializationLockError(retryable=False) from exc
    if path_stat is None:
        return
    if not stat.S_ISREG(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise InitializationLockError(retryable=False)


def _resolve_config_lock_domain(config_path: str | os.PathLike[str]) -> Path:
    try:
        normalized = normalize_windows_local_absolute_path(config_path)
        _require_plain_directory(normalized.parent)
        resolved_parent = normalized.parent.resolve(strict=True)
        resolved = normalize_windows_local_absolute_path(
            resolved_parent / normalized.name
        )
        _require_optional_plain_file(resolved)
        return resolved
    except InitializationLockError:
        raise
    except PathPolicyError as exc:
        raise InitializationLockError(retryable=False) from exc
    except (OSError, RuntimeError) as exc:
        raise InitializationLockError(retryable=False) from exc


def initialization_lock_path(
    config_path: str | os.PathLike[str],
) -> Path:
    """Return the persistent lock-file path for a resolved configuration path."""

    resolved = _resolve_config_lock_domain(config_path)
    return Path(f"{resolved}.init.lock")


def _open_lock_file(lock_path: Path) -> BinaryIO:
    _require_optional_plain_file(lock_path)
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        handle_stat = os.fstat(descriptor)
        path_stat = os.stat(lock_path, follow_symlinks=False)
        same_identity = (
            handle_stat.st_dev == path_stat.st_dev
            and handle_stat.st_ino == path_stat.st_ino
        )
        if (
            not stat.S_ISREG(handle_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or _is_reparse_point(path_stat)
            or not same_identity
        ):
            raise InitializationLockError(retryable=False)
        return os.fdopen(descriptor, "r+b", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise


def _known_lock_contention(exc: OSError) -> bool:
    if getattr(exc, "winerror", None) in {32, 33}:
        return True
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


def _wait_or_timeout(
    *,
    deadline: float,
    poll_interval_seconds: float,
    clock: _Clock,
    sleeper: _Sleeper,
) -> None:
    remaining = deadline - clock()
    if remaining <= 0:
        raise InitializationLockError(retryable=True)
    sleeper(min(poll_interval_seconds, remaining))


def _acquire_initialization_lock(
    config_path: str | os.PathLike[str],
    *,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    _clock: _Clock = time.monotonic,
    _sleeper: _Sleeper = time.sleep,
) -> InitializationLock:
    """Internal acquisition entry point with deterministic test timing hooks."""

    if msvcrt is None:
        raise InitializationLockError(retryable=False)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise ValueError("timeout_seconds must be a finite non-negative number")
    if (
        isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, (int, float))
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
    ):
        raise ValueError("poll_interval_seconds must be a finite positive number")

    resolved_config = _resolve_config_lock_domain(config_path)
    lock_path = Path(f"{resolved_config}.init.lock")
    deadline = _clock() + float(timeout_seconds)
    stream: BinaryIO | None = None

    while stream is None:
        try:
            stream = _open_lock_file(lock_path)
        except InitializationLockError:
            raise
        except OSError as exc:
            if not _known_lock_contention(exc):
                raise InitializationLockError(retryable=False) from exc
            _wait_or_timeout(
                deadline=deadline,
                poll_interval_seconds=float(poll_interval_seconds),
                clock=_clock,
                sleeper=_sleeper,
            )

    try:
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return InitializationLock(
                    config_path=resolved_config,
                    lock_path=lock_path,
                    stream=stream,
                )
            except OSError as exc:
                if not _known_lock_contention(exc):
                    raise InitializationLockError(retryable=False) from exc
                _wait_or_timeout(
                    deadline=deadline,
                    poll_interval_seconds=float(poll_interval_seconds),
                    clock=_clock,
                    sleeper=_sleeper,
                )
    except BaseException:
        stream.close()
        raise


def acquire_initialization_lock(
    config_path: str | os.PathLike[str],
) -> InitializationLock:
    """Acquire the production initialization lock with the fixed 10-second wait."""

    return _acquire_initialization_lock(config_path)


__all__ = [
    "DEFAULT_LOCK_TIMEOUT_SECONDS",
    "InitializationLock",
    "InitializationLockError",
    "acquire_initialization_lock",
    "initialization_lock_path",
]
