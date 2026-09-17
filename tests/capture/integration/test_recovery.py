"""C6A ownership, reparse, and identity boundaries for staging recovery."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from knowledgeflow_capture import store as store_module
from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.ids import generate_uuid7
from knowledgeflow_capture.locking import _acquire_capture_write_lock
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import (
    _CaptureTransaction,
    _create_capture_staging,
    _dump_capture_transaction,
    _recover_abandoned_capture_staging,
    init_capture_store,
)


_UUIDS = tuple(
    generate_uuid7(
        unix_ts_ms=1_800_000_001_000 + index,
        random_bytes=bytes([index + 1]) * 10,
    )
    for index in range(6)
)


class BusinessStagingRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C6A staging recovery is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.capture_root = self.owned_root / "capture-store"
        result = init_capture_store(
            config_path=self.owned_root / "config" / "config.yaml",
            capture_root=self.capture_root,
            inline_text_threshold_bytes=128,
            max_text_version_bytes=4096,
            path_policy=PathPolicy.test_owned(self.owned_root),
        )
        self.assertNotIsInstance(result, FailureResult)
        self.backend = DurabilityBackend()

    def _recover(self) -> tuple[str, ...]:
        with _acquire_capture_write_lock(self.capture_root):
            return _recover_abandoned_capture_staging(
                self.capture_root,
                durability=self.backend,
            )

    def test_only_marker_valid_lease_abandoned_fixed_tree_is_removed(self) -> None:
        staging = _create_capture_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: _UUIDS[0],
        )
        staging.lease.release()

        removed = self._recover()

        self.assertEqual(removed, (str(_UUIDS[0]),))
        self.assertFalse(staging.transaction_path.exists())

    def test_legacy_extra_and_identity_changed_trees_remain_untouched(self) -> None:
        staging_root = self.capture_root / ".staging"

        legacy = staging_root / str(_UUIDS[1])
        legacy.mkdir()
        legacy_marker = _dump_capture_transaction(
            _CaptureTransaction(transaction_id=str(_UUIDS[1]))
        )
        (legacy / "transaction.yaml").write_bytes(legacy_marker)

        foreign = _create_capture_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: _UUIDS[2],
        )
        foreign_bytes = b"must never be auto-deleted"
        (foreign.item_path / "foreign.bin").write_bytes(foreign_bytes)
        foreign.lease.release()

        changing = _create_capture_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: _UUIDS[3],
        )
        changing.lease.release()
        original_same_identity = store_module._capture_same_identity

        def report_changed(path: Path, expected: os.stat_result) -> bool:
            if path == changing.transaction_path:
                return False
            return original_same_identity(path, expected)

        with patch(
            "knowledgeflow_capture.store._capture_same_identity",
            side_effect=report_changed,
        ):
            removed = self._recover()

        self.assertEqual(removed, ())
        self.assertEqual((legacy / "transaction.yaml").read_bytes(), legacy_marker)
        self.assertEqual(
            (foreign.item_path / "foreign.bin").read_bytes(),
            foreign_bytes,
        )
        self.assertTrue(changing.marker_path.is_file())
        self.assertTrue(changing.lease_path.is_file())

    def test_real_junction_and_symlink_are_not_followed(self) -> None:
        target = self.owned_root / "outside-staging-target"
        target.mkdir()
        sentinel = target / "sentinel.bin"
        sentinel.write_bytes(b"outside bytes")
        staging_root = self.capture_root / ".staging"

        junction = staging_root / str(_UUIDS[4])
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            self.skipTest(f"cannot create a Windows junction: {created.stderr}")

        symlink = staging_root / str(_UUIDS[5])
        symlink_created = True
        try:
            os.symlink(target, symlink, target_is_directory=True)
        except OSError:
            symlink_created = False

        removed = self._recover()

        self.assertEqual(removed, ())
        self.assertTrue(junction.exists())
        if symlink_created:
            self.assertTrue(symlink.exists())
        self.assertEqual(sentinel.read_bytes(), b"outside bytes")


if __name__ == "__main__":
    unittest.main()
