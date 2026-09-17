from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.ids import generate_uuid7
from knowledgeflow_capture import store as store_module
from knowledgeflow_capture.store import (
    _CaptureStagingCleanupStatus,
    _cleanup_append_staging,
    _create_append_staging,
    _load_capture_transaction,
)


_TRANSACTION_UUID = generate_uuid7(
    unix_ts_ms=1_800_000_000_100,
    random_bytes=b"\x11\x23\x45\x67\x89\xab\xcd\xef\x01\x23",
)
_EVENT_ID = "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333"


class NonSeekableStream:
    def __init__(self, value: bytes) -> None:
        self._stream = io.BytesIO(value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.read_sizes.append(size)
        return self._stream.read(size)


class AppendStagingTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C5A staging contract is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.capture_root = Path(self._temporary.name).resolve() / "capture-store"
        self.capture_root.mkdir()
        for name in ("items", ".staging", "journal"):
            (self.capture_root / name).mkdir()
        self.backend = DurabilityBackend(_directory_flusher=lambda _path: True)

    def _create(self):
        staging = _create_append_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: _TRANSACTION_UUID,
        )
        self.addCleanup(
            _cleanup_append_staging,
            staging,
            durability=self.backend,
        )
        return staging

    def test_app_02_marker_is_durable_before_fixed_append_tree_is_created(self) -> None:
        original_create = store_module._capture_create_directory
        observed: list[Path] = []

        def checked_create(path: Path, durability: DurabilityBackend) -> None:
            transaction_path = path
            while transaction_path.parent.name != ".staging":
                transaction_path = transaction_path.parent
            marker_path = transaction_path / "transaction.yaml"
            marker = _load_capture_transaction(marker_path.read_bytes())
            self.assertEqual(marker.operation, "append_capture_version")
            observed.append(path)
            original_create(path, durability)

        with patch(
            "knowledgeflow_capture.store._capture_create_directory",
            side_effect=checked_create,
        ):
            staging = self._create()

        expected_marker = (
            'schema: "knowledgeflow.capture-transaction"\n'
            "schema_version: 1\n"
            f'transaction_id: "{_TRANSACTION_UUID}"\n'
            'operation: "append_capture_version"\n'
        ).encode("utf-8")
        self.assertEqual(staging.marker_path.read_bytes(), expected_marker)
        self.assertEqual(
            sorted(path.name for path in staging.transaction_path.iterdir()),
            ["active.lock", "events", "transaction.yaml", "version"],
        )
        self.assertEqual(
            sorted(path.name for path in staging.version_path.iterdir()),
            ["payloads"],
        )
        self.assertEqual(
            observed,
            [
                staging.version_path,
                staging.version_path / "payloads",
                staging.events_path,
            ],
        )

    def test_app_02_nonseekable_utf8_body_is_bounded_and_byte_exact(self) -> None:
        staging = self._create()
        payload = ("开头\r\n🙂结尾 " * 1000).encode("utf-8")
        source = NonSeekableStream(payload)

        digest = self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            source,
            maximum_bytes=len(payload),
            chunk_size=257,
        )

        self.assertEqual(staging.payload_path.read_bytes(), payload)
        self.assertEqual(digest.byte_size, len(payload))
        self.assertTrue(source.read_sizes)
        self.assertTrue(all(0 < size <= 257 for size in source.read_sizes))
        self.assertEqual(
            _cleanup_append_staging(staging, durability=self.backend),
            _CaptureStagingCleanupStatus.REMOVED,
        )

    def test_cleanup_accepts_version_and_event_partial_renames_without_touching_targets(self) -> None:
        staging = self._create()
        self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            "candidate body",
            maximum_bytes=64,
            chunk_size=8,
        )
        self.backend.write_new_file_durable(
            staging.version_path / "envelope.yaml",
            b"candidate envelope",
        )
        staged_event = staging.event_path(_EVENT_ID)
        self.backend.write_new_file_durable(staged_event, b"candidate event")
        final_version = self.capture_root / "items" / "tail-version"
        final_event = self.capture_root / "items" / f"{_EVENT_ID}.yaml"
        os.rename(staging.version_path, final_version)
        os.rename(staged_event, final_event)

        status = _cleanup_append_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REMOVED)
        self.assertFalse(staging.transaction_path.exists())
        self.assertEqual(
            (final_version / "payloads" / "primary.txt").read_text("utf-8"),
            "candidate body",
        )
        self.assertEqual(final_event.read_bytes(), b"candidate event")

    def test_cleanup_refuses_extra_marker_mismatch_and_second_event(self) -> None:
        mutators = (
            lambda staging: (staging.transaction_path / "foreign.bin").write_bytes(b"x"),
            lambda staging: staging.marker_path.write_bytes(
                staging.marker_path.read_bytes().replace(
                    b'operation: "append_capture_version"',
                    b'operation: "capture_text"',
                )
            ),
            lambda staging: (
                staging.event_path(_EVENT_ID).write_bytes(b"first"),
                staging.event_path(
                    "evt_01991a7e-7b23-72ae-9ef5-4f45249ad334"
                ).write_bytes(b"second"),
            ),
        )
        for index, mutate in enumerate(mutators):
            with self.subTest(case=index):
                staging = self._create()
                mutate(staging)
                self.assertEqual(
                    _cleanup_append_staging(staging, durability=self.backend),
                    _CaptureStagingCleanupStatus.REFUSED,
                )
                self.assertTrue(staging.transaction_path.exists())
                # Make the deterministic transaction ID available to the next case.
                for child in sorted(
                    staging.transaction_path.rglob("*"),
                    key=lambda path: len(path.parts),
                    reverse=True,
                ):
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                staging.transaction_path.rmdir()

    def test_cleanup_refuses_identity_replacement_after_tree_scan(self) -> None:
        staging = self._create()
        self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            "owned",
            maximum_bytes=16,
            chunk_size=4,
        )
        original_safe_tree = store_module._safe_append_staging_tree

        def replace_after_scan(value):
            result = original_safe_tree(value)
            staging.payload_path.unlink()
            staging.payload_path.write_text("replacement", encoding="utf-8")
            return result

        with patch(
            "knowledgeflow_capture.store._safe_append_staging_tree",
            side_effect=replace_after_scan,
        ):
            status = _cleanup_append_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REFUSED)
        self.assertEqual(staging.payload_path.read_text("utf-8"), "replacement")
        self.assertTrue(staging.marker_path.exists())

    def test_cleanup_refuses_reparse_version_without_following_it(self) -> None:
        staging = self._create()
        sentinel = staging.version_path / "payloads" / "sentinel.bin"
        sentinel.write_bytes(b"must remain")
        original_lstat = store_module._capture_lstat_if_present

        def report_version_as_reparse(path: Path):
            value = original_lstat(path)
            if path == staging.version_path and value is not None:
                return SimpleNamespace(
                    st_mode=value.st_mode,
                    st_dev=value.st_dev,
                    st_ino=value.st_ino,
                    st_file_attributes=0x400,
                )
            return value

        with patch(
            "knowledgeflow_capture.store._capture_lstat_if_present",
            side_effect=report_version_as_reparse,
        ):
            status = _cleanup_append_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REFUSED)
        self.assertEqual(sentinel.read_bytes(), b"must remain")


if __name__ == "__main__":
    unittest.main()
