"""Durable file writes and Windows no-overwrite rename primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
import errno
import os
from pathlib import Path
import stat
from typing import BinaryIO

from .errors import OperationError, PublicErrorCode


_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_FileValidator = Callable[[bytes], object]
_FileFsync = Callable[[int], None]
_FileReader = Callable[[Path], bytes]
_FileBeforeFlush = Callable[[Path], None]
_NewFileOpener = Callable[[Path], BinaryIO]
_Rename = Callable[[Path, Path], None]
_Unlink = Callable[[Path], None]
_DirectoryFlusher = Callable[[Path], bool]


class DurabilityStage(StrEnum):
    FILE_WRITE = "file-write"
    FILE_FSYNC = "file-fsync"
    FILE_READBACK = "file-readback"
    FILE_VALIDATE = "file-validate"
    RENAME = "rename"
    CLEANUP = "cleanup"
    DIRECTORY_METADATA = "directory-metadata"


class DirectoryFlushStatus(StrEnum):
    FLUSHED = "flushed"
    UNSUPPORTED = "unsupported"


class FileCommitDisposition(StrEnum):
    CREATED = "created"
    ALREADY_PRESENT = "already-present"


class DurabilityError(RuntimeError):
    """An I/O or verification failure safe to map across the operation boundary."""

    def __init__(self, stage: DurabilityStage) -> None:
        self.code = PublicErrorCode.CAPTURE_STORE_UNAVAILABLE
        self.retryable = False
        self.stage = DurabilityStage(stage)
        super().__init__("capture store durability operation failed")

    def to_operation_error(self) -> OperationError:
        return OperationError(
            code=self.code,
            retryable=self.retryable,
            details={"stage": self.stage.value},
        )


class DestinationAlreadyExistsError(RuntimeError):
    """A no-overwrite destination appeared and must be classified by the caller."""

    def __init__(self) -> None:
        super().__init__("no-overwrite destination already exists")


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _lstat_if_present(path: Path) -> os.stat_result | None:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_plain_directory(path: Path, stage: DurabilityStage) -> os.stat_result:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DurabilityError(stage) from exc
    if not stat.S_ISDIR(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise DurabilityError(stage)
    return path_stat


def _require_plain_file(path: Path, stage: DurabilityStage) -> os.stat_result:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DurabilityError(stage) from exc
    if not stat.S_ISREG(path_stat.st_mode) or _is_reparse_point(path_stat):
        raise DurabilityError(stage)
    return path_stat


def _default_open_new(path: Path) -> BinaryIO:
    return path.open("xb")


def _default_read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _default_unlink(path: Path) -> None:
    path.unlink()


def _posix_directory_flusher(path: Path) -> bool:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        unsupported_codes = {
            errno.EBADF,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if exc.errno in unsupported_codes:
            return False
        raise
    finally:
        os.close(descriptor)
    return True


def _platform_directory_flusher() -> _DirectoryFlusher | None:
    if os.name == "nt":
        return None
    return _posix_directory_flusher


@dataclass(frozen=True, slots=True)
class DurabilityBackend:
    """Small injectable boundary around filesystem durability operations."""

    _fsync: _FileFsync = field(default=os.fsync, repr=False, compare=False)
    _read_bytes: _FileReader = field(
        default=_default_read_bytes,
        repr=False,
        compare=False,
    )
    _open_new: _NewFileOpener = field(
        default=_default_open_new,
        repr=False,
        compare=False,
    )
    _rename: _Rename = field(default=os.rename, repr=False, compare=False)
    _unlink: _Unlink = field(default=_default_unlink, repr=False, compare=False)
    _directory_flusher: _DirectoryFlusher | None = field(
        default_factory=_platform_directory_flusher,
        repr=False,
        compare=False,
    )

    def flush_directory_metadata(self, path: str | os.PathLike[str]) -> DirectoryFlushStatus:
        directory = Path(path)
        _require_plain_directory(directory, DurabilityStage.DIRECTORY_METADATA)
        if self._directory_flusher is None:
            return DirectoryFlushStatus.UNSUPPORTED
        try:
            supported = self._directory_flusher(directory)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.DIRECTORY_METADATA) from exc
        if type(supported) is not bool:
            raise DurabilityError(DurabilityStage.DIRECTORY_METADATA)
        if supported:
            return DirectoryFlushStatus.FLUSHED
        return DirectoryFlushStatus.UNSUPPORTED

    def _verify_file(
        self,
        path: Path,
        expected_bytes: bytes,
        validator: _FileValidator | None,
    ) -> None:
        _require_plain_file(path, DurabilityStage.FILE_READBACK)
        try:
            actual = self._read_bytes(path)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.FILE_READBACK) from exc
        if type(actual) is not bytes or actual != expected_bytes:
            raise DurabilityError(DurabilityStage.FILE_READBACK)
        if validator is not None:
            try:
                validator(actual)
            except Exception as exc:
                raise DurabilityError(DurabilityStage.FILE_VALIDATE) from exc

    def write_new_file_durable(
        self,
        path: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        validator: _FileValidator | None = None,
        _before_flush: _FileBeforeFlush | None = None,
    ) -> DirectoryFlushStatus:
        """Exclusively create, fsync, close, reread, and validate one exact file.

        ``_before_flush`` is an internal-only hook invoked once all bytes have
        been handed to the stream but before the application buffer is flushed;
        production callers must keep it unset.
        """

        target = Path(path)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        expected_bytes = bytes(data)
        _require_plain_directory(target.parent, DurabilityStage.FILE_WRITE)
        try:
            existing = _lstat_if_present(target)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.FILE_WRITE) from exc
        if existing is not None:
            raise DestinationAlreadyExistsError

        try:
            with self._open_new(target) as stream:
                remaining = memoryview(expected_bytes)
                while remaining:
                    written = stream.write(remaining)
                    if written is None or written <= 0:
                        raise OSError("short write")
                    remaining = remaining[written:]
                if _before_flush is not None:
                    _before_flush(target)
                stream.flush()
                try:
                    self._fsync(stream.fileno())
                except OSError as exc:
                    raise DurabilityError(DurabilityStage.FILE_FSYNC) from exc
        except FileExistsError as exc:
            raise DestinationAlreadyExistsError from exc
        except DestinationAlreadyExistsError:
            raise
        except DurabilityError:
            raise
        except OSError as exc:
            raise DurabilityError(DurabilityStage.FILE_WRITE) from exc

        self._verify_file(target, expected_bytes, validator)
        return self.flush_directory_metadata(target.parent)

    def _classify_existing_file(
        self,
        *,
        source: Path,
        destination: Path,
        expected_bytes: bytes,
        validator: _FileValidator | None,
    ) -> FileCommitDisposition:
        try:
            destination_stat = _lstat_if_present(destination)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.FILE_READBACK) from exc
        if (
            destination_stat is None
            or not stat.S_ISREG(destination_stat.st_mode)
            or _is_reparse_point(destination_stat)
        ):
            raise DestinationAlreadyExistsError
        try:
            actual = self._read_bytes(destination)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.FILE_READBACK) from exc
        if type(actual) is not bytes or actual != expected_bytes:
            raise DestinationAlreadyExistsError
        if validator is not None:
            try:
                validator(actual)
            except Exception as exc:
                raise DestinationAlreadyExistsError from exc
        try:
            self._unlink(source)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.CLEANUP) from exc
        self.flush_directory_metadata(destination.parent)
        return FileCommitDisposition.ALREADY_PRESENT

    def commit_file_no_replace(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        expected_bytes: bytes | bytearray | memoryview,
        *,
        validator: _FileValidator | None = None,
    ) -> FileCommitDisposition:
        """Atomically connect a verified temp file without replacing a destination."""

        source_path = Path(source)
        destination_path = Path(destination)
        if not isinstance(expected_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("expected_bytes must be bytes-like")
        expected = bytes(expected_bytes)
        source_parent = _require_plain_directory(
            source_path.parent,
            DurabilityStage.RENAME,
        )
        destination_parent = _require_plain_directory(
            destination_path.parent,
            DurabilityStage.RENAME,
        )
        if (
            source_parent.st_dev != destination_parent.st_dev
            or source_parent.st_ino != destination_parent.st_ino
        ):
            raise DurabilityError(DurabilityStage.RENAME)
        self._verify_file(source_path, expected, validator)

        try:
            destination_stat = _lstat_if_present(destination_path)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.RENAME) from exc
        if destination_stat is not None:
            return self._classify_existing_file(
                source=source_path,
                destination=destination_path,
                expected_bytes=expected,
                validator=validator,
            )

        if os.name != "nt":
            raise DurabilityError(DurabilityStage.RENAME)
        try:
            self._rename(source_path, destination_path)
        except OSError as exc:
            try:
                destination_appeared = _lstat_if_present(destination_path) is not None
            except OSError as probe_exc:
                raise DurabilityError(DurabilityStage.RENAME) from probe_exc
            if destination_appeared:
                return self._classify_existing_file(
                    source=source_path,
                    destination=destination_path,
                    expected_bytes=expected,
                    validator=validator,
                )
            raise DurabilityError(DurabilityStage.RENAME) from exc

        self._verify_file(destination_path, expected, validator)
        self.flush_directory_metadata(destination_path.parent)
        return FileCommitDisposition.CREATED

    def commit_directory_no_replace(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> DirectoryFlushStatus:
        """Rename a complete directory on the same volume without replacement."""

        source_path = Path(source)
        destination_path = Path(destination)
        source_stat = _require_plain_directory(source_path, DurabilityStage.RENAME)
        destination_parent_stat = _require_plain_directory(
            destination_path.parent,
            DurabilityStage.RENAME,
        )
        if source_stat.st_dev != destination_parent_stat.st_dev:
            raise DurabilityError(DurabilityStage.RENAME)
        try:
            destination_stat = _lstat_if_present(destination_path)
        except OSError as exc:
            raise DurabilityError(DurabilityStage.RENAME) from exc
        if destination_stat is not None:
            raise DestinationAlreadyExistsError
        if os.name != "nt":
            raise DurabilityError(DurabilityStage.RENAME)
        try:
            self._rename(source_path, destination_path)
        except OSError as exc:
            try:
                destination_appeared = _lstat_if_present(destination_path) is not None
            except OSError as probe_exc:
                raise DurabilityError(DurabilityStage.RENAME) from probe_exc
            if destination_appeared:
                raise DestinationAlreadyExistsError from exc
            raise DurabilityError(DurabilityStage.RENAME) from exc
        _require_plain_directory(destination_path, DurabilityStage.RENAME)
        return self.flush_directory_metadata(destination_path.parent)


__all__ = [
    "DestinationAlreadyExistsError",
    "DirectoryFlushStatus",
    "DurabilityBackend",
    "DurabilityError",
    "DurabilityStage",
    "FileCommitDisposition",
]
