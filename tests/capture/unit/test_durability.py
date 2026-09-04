from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.config import (
    create_local_config,
    dump_local_config,
    parse_local_config,
)
from knowledgeflow_capture.durability import (
    DestinationAlreadyExistsError,
    DirectoryFlushStatus,
    DurabilityBackend,
    DurabilityError,
    DurabilityStage,
    FileCommitDisposition,
)
from knowledgeflow_capture.errors import PublicErrorCode
from knowledgeflow_capture.manifest import load_capture_store_manifest
from knowledgeflow_capture.paths import PathPolicy


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


class _TrackedFile:
    def __init__(self, path: Path, events: list[str]) -> None:
        self._stream = path.open("xb")
        self._events = events

    def __enter__(self) -> _TrackedFile:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.close()
        return False

    def write(self, data: object) -> int:
        written = self._stream.write(data)
        self._events.append("write")
        return written

    def flush(self) -> None:
        self._stream.flush()
        self._events.append("flush")

    def fileno(self) -> int:
        return self._stream.fileno()

    def close(self) -> None:
        self._stream.close()
        self._events.append("close")


class DurabilityBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C2B-1 no-overwrite rename contract is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()

    def test_dur_01_write_fsync_close_readback_and_strict_validation(self) -> None:
        expected = (_FIXTURE_ROOT / "capture-store-v1.yaml").read_bytes()
        target = self.root / "manifest.tmp"
        events: list[str] = []

        def open_new(path: Path) -> _TrackedFile:
            events.append("open")
            return _TrackedFile(path, events)

        def fsync(descriptor: int) -> None:
            events.append("fsync")
            os.fsync(descriptor)

        def read_bytes(path: Path) -> bytes:
            events.append("readback")
            return path.read_bytes()

        def validate(data: bytes) -> object:
            events.append("validate")
            return load_capture_store_manifest(data)

        def flush_directory(_path: Path) -> bool:
            events.append("directory-flush")
            return True

        backend = DurabilityBackend(
            _fsync=fsync,
            _read_bytes=read_bytes,
            _open_new=open_new,
            _directory_flusher=flush_directory,
        )

        status = backend.write_new_file_durable(
            target,
            expected,
            validator=validate,
        )

        self.assertEqual(status, DirectoryFlushStatus.FLUSHED)
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual(
            events,
            [
                "open",
                "write",
                "flush",
                "fsync",
                "close",
                "readback",
                "validate",
                "directory-flush",
            ],
        )

        failed_target = self.root / "fsync-failure.tmp"
        validated = False

        def fail_fsync(_descriptor: int) -> None:
            raise OSError("injected fsync failure")

        def must_not_validate(_data: bytes) -> None:
            nonlocal validated
            validated = True

        failing_backend = DurabilityBackend(
            _fsync=fail_fsync,
            _directory_flusher=lambda _path: True,
        )
        with self.assertRaises(DurabilityError) as raised:
            failing_backend.write_new_file_durable(
                failed_target,
                expected,
                validator=must_not_validate,
            )
        self.assertEqual(raised.exception.stage, DurabilityStage.FILE_FSYNC)
        self.assertEqual(raised.exception.code, PublicErrorCode.CAPTURE_STORE_UNAVAILABLE)
        self.assertFalse(raised.exception.retryable)
        self.assertFalse(validated)

        readback_target = self.root / "readback-failure.tmp"
        directory_flush_attempted = False

        def corrupt_readback(path: Path) -> bytes:
            return path.read_bytes() + b"corrupt"

        def record_directory_flush(_path: Path) -> bool:
            nonlocal directory_flush_attempted
            directory_flush_attempted = True
            return True

        readback_backend = DurabilityBackend(
            _read_bytes=corrupt_readback,
            _directory_flusher=record_directory_flush,
        )
        with self.assertRaises(DurabilityError) as raised:
            readback_backend.write_new_file_durable(readback_target, expected)
        self.assertEqual(raised.exception.stage, DurabilityStage.FILE_READBACK)
        self.assertFalse(directory_flush_attempted)

        validation_target = self.root / "validation-failure.tmp"
        validation_backend = DurabilityBackend(
            _directory_flusher=record_directory_flush,
        )

        def reject_validation(_data: bytes) -> None:
            raise ValueError

        with self.assertRaises(DurabilityError) as raised:
            validation_backend.write_new_file_durable(
                validation_target,
                expected,
                validator=reject_validation,
            )
        self.assertEqual(raised.exception.stage, DurabilityStage.FILE_VALIDATE)
        self.assertFalse(directory_flush_attempted)

    def test_dur_02_same_volume_directory_rename_never_overwrites(self) -> None:
        backend = DurabilityBackend(_directory_flusher=lambda _path: True)
        transaction = self.root / "transaction"
        transaction.mkdir()
        source = transaction / "source"
        source.mkdir()
        (source / "sentinel.txt").write_bytes(b"source")
        destination = self.root / "destination"

        status = backend.commit_directory_no_replace(source, destination)

        self.assertEqual(status, DirectoryFlushStatus.FLUSHED)
        self.assertFalse(source.exists())
        self.assertEqual((destination / "sentinel.txt").read_bytes(), b"source")

        second_source = transaction / "second-source"
        second_source.mkdir()
        (second_source / "sentinel.txt").write_bytes(b"new")
        existing_destination = self.root / "existing-destination"
        existing_destination.mkdir()
        (existing_destination / "sentinel.txt").write_bytes(b"existing")

        with self.assertRaises(DestinationAlreadyExistsError):
            backend.commit_directory_no_replace(second_source, existing_destination)

        self.assertEqual((second_source / "sentinel.txt").read_bytes(), b"new")
        self.assertEqual(
            (existing_destination / "sentinel.txt").read_bytes(),
            b"existing",
        )

        raced_source = transaction / "raced-source"
        raced_source.mkdir()
        (raced_source / "sentinel.txt").write_bytes(b"candidate")
        raced_destination = self.root / "raced-destination"

        def destination_appears(_source: Path, destination_path: Path) -> None:
            destination_path.mkdir()
            (destination_path / "sentinel.txt").write_bytes(b"external")
            raise FileExistsError

        racing_backend = DurabilityBackend(
            _rename=destination_appears,
            _directory_flusher=lambda _path: True,
        )
        with self.assertRaises(DestinationAlreadyExistsError):
            racing_backend.commit_directory_no_replace(
                raced_source,
                raced_destination,
            )
        self.assertEqual((raced_source / "sentinel.txt").read_bytes(), b"candidate")
        self.assertEqual(
            (raced_destination / "sentinel.txt").read_bytes(),
            b"external",
        )

    def test_dur_03_config_connection_accepts_exact_race_only(self) -> None:
        policy = PathPolicy.test_owned(self.root)
        config = create_local_config(
            root=self.root / "candidate-root",
            inline_text_threshold_bytes=4 * 1024 * 1024,
            max_text_version_bytes=64 * 1024 * 1024,
            path_policy=policy,
        )
        expected = dump_local_config(config)

        def validate(data: bytes) -> object:
            return parse_local_config(data, path_policy=policy)

        backend = DurabilityBackend(_directory_flusher=lambda _path: True)

        created_source = self.root / "created.tmp"
        created_destination = self.root / "created.yaml"
        backend.write_new_file_durable(created_source, expected, validator=validate)
        self.assertEqual(
            backend.commit_file_no_replace(
                created_source,
                created_destination,
                expected,
                validator=validate,
            ),
            FileCommitDisposition.CREATED,
        )
        self.assertFalse(created_source.exists())
        self.assertEqual(created_destination.read_bytes(), expected)

        matching_source = self.root / "matching.tmp"
        matching_destination = self.root / "matching.yaml"
        backend.write_new_file_durable(matching_source, expected, validator=validate)
        matching_destination.write_bytes(expected)
        self.assertEqual(
            backend.commit_file_no_replace(
                matching_source,
                matching_destination,
                expected,
                validator=validate,
            ),
            FileCommitDisposition.ALREADY_PRESENT,
        )
        self.assertFalse(matching_source.exists())
        self.assertEqual(matching_destination.read_bytes(), expected)

        conflicting_source = self.root / "conflicting.tmp"
        conflicting_destination = self.root / "conflicting.yaml"
        backend.write_new_file_durable(conflicting_source, expected, validator=validate)
        conflicting_destination.write_bytes(b"external-content")

        with self.assertRaises(DestinationAlreadyExistsError):
            backend.commit_file_no_replace(
                conflicting_source,
                conflicting_destination,
                expected,
                validator=validate,
            )

        self.assertEqual(conflicting_source.read_bytes(), expected)
        self.assertEqual(conflicting_destination.read_bytes(), b"external-content")

        raced_matching_source = self.root / "raced-matching.tmp"
        raced_matching_destination = self.root / "raced-matching.yaml"
        backend.write_new_file_durable(
            raced_matching_source,
            expected,
            validator=validate,
        )

        def matching_destination_appears(_source: Path, destination: Path) -> None:
            destination.write_bytes(expected)
            raise FileExistsError

        matching_race_backend = DurabilityBackend(
            _rename=matching_destination_appears,
            _directory_flusher=lambda _path: True,
        )
        self.assertEqual(
            matching_race_backend.commit_file_no_replace(
                raced_matching_source,
                raced_matching_destination,
                expected,
                validator=validate,
            ),
            FileCommitDisposition.ALREADY_PRESENT,
        )
        self.assertFalse(raced_matching_source.exists())
        self.assertEqual(raced_matching_destination.read_bytes(), expected)

        raced_conflicting_source = self.root / "raced-conflicting.tmp"
        raced_conflicting_destination = self.root / "raced-conflicting.yaml"
        backend.write_new_file_durable(
            raced_conflicting_source,
            expected,
            validator=validate,
        )

        def conflicting_destination_appears(_source: Path, destination: Path) -> None:
            destination.write_bytes(b"external-race")
            raise FileExistsError

        conflicting_race_backend = DurabilityBackend(
            _rename=conflicting_destination_appears,
            _directory_flusher=lambda _path: True,
        )
        with self.assertRaises(DestinationAlreadyExistsError):
            conflicting_race_backend.commit_file_no_replace(
                raced_conflicting_source,
                raced_conflicting_destination,
                expected,
                validator=validate,
            )
        self.assertEqual(raced_conflicting_source.read_bytes(), expected)
        self.assertEqual(
            raced_conflicting_destination.read_bytes(),
            b"external-race",
        )

    def test_dur_04_directory_flush_reports_support_and_unexpected_failures(self) -> None:
        calls: list[Path] = []

        def supported(path: Path) -> bool:
            calls.append(path)
            return True

        supported_backend = DurabilityBackend(_directory_flusher=supported)
        self.assertEqual(
            supported_backend.flush_directory_metadata(self.root),
            DirectoryFlushStatus.FLUSHED,
        )
        self.assertEqual(calls, [self.root])

        unsupported_backend = DurabilityBackend(_directory_flusher=None)
        self.assertEqual(
            unsupported_backend.flush_directory_metadata(self.root),
            DirectoryFlushStatus.UNSUPPORTED,
        )
        self.assertEqual(
            DurabilityBackend().flush_directory_metadata(self.root),
            DirectoryFlushStatus.UNSUPPORTED,
        )

        def unexpected_failure(_path: Path) -> bool:
            raise OSError("injected directory flush failure")

        failing_backend = DurabilityBackend(_directory_flusher=unexpected_failure)
        with self.assertRaises(DurabilityError) as raised:
            failing_backend.flush_directory_metadata(self.root)
        self.assertEqual(raised.exception.stage, DurabilityStage.DIRECTORY_METADATA)
        self.assertEqual(
            raised.exception.to_operation_error().to_dict(),
            {
                "code": "capture_store_unavailable",
                "cause_code": None,
                "message": "capture store is unavailable",
                "retryable": False,
                "details": {"stage": "directory-metadata"},
            },
        )

    def test_dur_05_before_flush_callback_runs_after_write_before_flush(self) -> None:
        expected = b"durable payload with fault hook"
        target = self.root / "before-flush.tmp"
        events: list[str] = []

        def open_new(path: Path) -> _TrackedFile:
            events.append("open")
            return _TrackedFile(path, events)

        def before_flush(path: Path) -> None:
            events.append("before-flush")
            self.assertEqual(path, target)

        def fsync(descriptor: int) -> None:
            events.append("fsync")
            os.fsync(descriptor)

        def read_bytes(path: Path) -> bytes:
            events.append("readback")
            return path.read_bytes()

        def flush_directory(_path: Path) -> bool:
            events.append("directory-flush")
            return True

        backend = DurabilityBackend(
            _fsync=fsync,
            _read_bytes=read_bytes,
            _open_new=open_new,
            _directory_flusher=flush_directory,
        )

        status = backend.write_new_file_durable(
            target,
            expected,
            _before_flush=before_flush,
        )

        self.assertEqual(status, DirectoryFlushStatus.FLUSHED)
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual(
            events,
            [
                "open",
                "write",
                "before-flush",
                "flush",
                "fsync",
                "close",
                "readback",
                "directory-flush",
            ],
        )


if __name__ == "__main__":
    unittest.main()
