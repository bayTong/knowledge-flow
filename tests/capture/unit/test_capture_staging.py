from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.ids import generate_uuid7
from knowledgeflow_capture.store import (
    _CaptureStagingCleanupStatus,
    _cleanup_capture_staging,
    _create_capture_staging,
    _load_capture_transaction,
)


_TRANSACTION_UUID = generate_uuid7(
    unix_ts_ms=1_800_000_000_000,
    random_bytes=b"\x01\x23\x45\x67\x89\xab\xcd\xef\x01\x23",
)


class CaptureStagingTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C3B staging contract is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.capture_root = Path(self._temporary.name).resolve() / "capture-store"
        self.capture_root.mkdir()
        for name in ("items", ".staging", "journal"):
            (self.capture_root / name).mkdir()
        self.backend = DurabilityBackend(_directory_flusher=lambda _path: True)

    def _create(self):
        staging = _create_capture_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: _TRANSACTION_UUID,
        )
        self.addCleanup(
            _cleanup_capture_staging,
            staging,
            durability=self.backend,
        )
        return staging

    def test_t0_marker_proves_ownership_before_request_fingerprint_exists(self) -> None:
        staging = self._create()
        expected_marker = (
            'schema: "knowledgeflow.capture-transaction"\n'
            "schema_version: 1\n"
            f'transaction_id: "{_TRANSACTION_UUID}"\n'
            'operation: "capture_text"\n'
        ).encode("utf-8")

        self.assertEqual(
            staging.transaction_path,
            self.capture_root / ".staging" / str(_TRANSACTION_UUID),
        )
        self.assertEqual(staging.marker_path.read_bytes(), expected_marker)
        marker = _load_capture_transaction(expected_marker)
        self.assertEqual(marker.transaction_id, str(_TRANSACTION_UUID))
        self.assertNotIn(b"request_fingerprint", expected_marker)
        self.assertNotIn(b"idempotency", expected_marker)

    def test_t0_creates_only_the_fixed_capture_item_skeleton(self) -> None:
        staging = self._create()

        self.assertEqual(
            sorted(path.name for path in staging.transaction_path.iterdir()),
            ["active.lock", "item", "transaction.yaml"],
        )
        self.assertEqual(
            sorted(path.name for path in staging.item_path.iterdir()),
            ["events", "versions"],
        )
        self.assertEqual(
            sorted(path.name for path in staging.version_path.iterdir()),
            ["payloads"],
        )
        self.assertEqual(staging.payload_path, staging.version_path / "payloads" / "primary.txt")
        self.assertFalse(staging.payload_path.exists())

    def test_ct_24_cleanup_removes_only_the_exact_owned_staging(self) -> None:
        unknown = self.capture_root / ".staging" / "unknown-transaction"
        unknown.mkdir()
        unknown_bytes = b"must remain byte-for-byte"
        (unknown / "sentinel.bin").write_bytes(unknown_bytes)
        c2_residue = self.capture_root.parent / ".knowledgeflow-init-unknown"
        c2_residue.mkdir()
        (c2_residue / "sentinel.bin").write_bytes(unknown_bytes)
        staging = self._create()
        self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            "owned payload",
            maximum_bytes=64,
            chunk_size=4,
        )

        status = _cleanup_capture_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REMOVED)
        self.assertFalse(staging.transaction_path.exists())
        self.assertEqual((unknown / "sentinel.bin").read_bytes(), unknown_bytes)
        self.assertEqual((c2_residue / "sentinel.bin").read_bytes(), unknown_bytes)

    def test_cleanup_refuses_unknown_content_inside_owned_tree(self) -> None:
        staging = self._create()
        unknown = staging.item_path / "foreign.bin"
        unknown_bytes = b"not created by the capture transaction"
        unknown.write_bytes(unknown_bytes)

        status = _cleanup_capture_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REFUSED)
        self.assertEqual(unknown.read_bytes(), unknown_bytes)
        self.assertTrue(staging.marker_path.is_file())

    def test_post_commit_cleanup_cannot_remove_or_invert_committed_item(self) -> None:
        staging = self._create()
        self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            "committed payload",
            maximum_bytes=64,
            chunk_size=4,
        )
        final_parent = self.capture_root / "items" / "2027" / "01"
        final_parent.mkdir(parents=True)
        final_item = final_parent / "cap_committed-proof"
        self.backend.commit_directory_no_replace(staging.item_path, final_item)

        status = _cleanup_capture_staging(staging, durability=self.backend)

        self.assertEqual(status, _CaptureStagingCleanupStatus.REMOVED)
        self.assertEqual(
            (final_item / "versions" / "000001" / "payloads" / "primary.txt").read_bytes(),
            b"committed payload",
        )

    def test_cleanup_failure_is_reported_as_disposition_after_commit(self) -> None:
        staging = self._create()
        final_parent = self.capture_root / "items" / "2027" / "02"
        final_parent.mkdir(parents=True)
        final_item = final_parent / "cap_cleanup-failure-proof"
        self.backend.commit_directory_no_replace(staging.item_path, final_item)

        def fail_flush(_path: Path) -> bool:
            raise OSError("injected cleanup metadata failure")

        status = _cleanup_capture_staging(
            staging,
            durability=DurabilityBackend(_directory_flusher=fail_flush),
        )

        self.assertEqual(status, _CaptureStagingCleanupStatus.FAILED)
        self.assertTrue(final_item.is_dir())

    def test_cleanup_is_idempotent_after_owned_staging_is_removed(self) -> None:
        staging = self._create()
        self.assertEqual(
            _cleanup_capture_staging(staging, durability=self.backend),
            _CaptureStagingCleanupStatus.REMOVED,
        )
        self.assertEqual(
            _cleanup_capture_staging(staging, durability=self.backend),
            _CaptureStagingCleanupStatus.ALREADY_ABSENT,
        )


if __name__ == "__main__":
    unittest.main()
