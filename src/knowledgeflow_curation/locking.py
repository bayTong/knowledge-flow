"""Small cross-process locks for CUR1C target and repository transactions."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
import time
from typing import Iterator


_REPARSE_ATTRIBUTE = 0x400


class LockUnavailable(TimeoutError):
    """A bounded lock acquisition did not succeed."""


def _is_reparse(value: os.stat_result) -> bool:
    return bool(getattr(value, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _require_plain_directory(path: Path) -> None:
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or _is_reparse(value):
        raise OSError("lock parent is not a plain directory")


def _open_lock(path: Path) -> int:
    _require_plain_directory(path.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        linked = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or _is_reparse(linked)
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise OSError("lock path is not a stable plain file")
        if opened.st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _try_lock(descriptor: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, 13, 36}:
                return False
            raise

    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(
    path: str | os.PathLike[str],
    *,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Hold one bounded, non-inheritable inter-process file lock."""

    if type(timeout_seconds) not in {int, float} or timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    if type(poll_seconds) not in {int, float} or poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    selected = Path(path)
    descriptor = _open_lock(selected)
    acquired = False
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        while not acquired:
            acquired = _try_lock(descriptor)
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise LockUnavailable("lock acquisition timed out")
            time.sleep(min(float(poll_seconds), max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            _unlock(descriptor)
        os.close(descriptor)


__all__ = ["LockUnavailable", "exclusive_file_lock"]
