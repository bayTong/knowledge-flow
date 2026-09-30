from __future__ import annotations

import json
import unittest

from knowledgeflow_capture.ids import generate_job_id, generate_store_id
from knowledgeflow_capture.management import (
    BackupFileRecord,
    BackupManifestLoadError,
    CAPTURE_BACKUP_SCHEMA,
    CaptureBackupManifest,
    _snapshot_sha256,
    dump_capture_backup_manifest,
    load_capture_backup_manifest,
)
from knowledgeflow_capture.errors import PublicErrorCode


class CaptureBackupManifestTest(unittest.TestCase):
    def _manifest(self) -> CaptureBackupManifest:
        directories = (".staging", "items", "journal")
        files = (
            BackupFileRecord(
                relative_path="capture-store.yaml",
                byte_size=17,
                sha256="sha256:" + ("1" * 64),
            ),
        )
        return CaptureBackupManifest(
            backup_id=generate_job_id(),
            created_at="2026-09-30T01:02:03.004Z",
            store_id=generate_store_id(),
            inline_text_threshold_bytes=4 * 1024 * 1024,
            max_text_version_bytes=64 * 1024 * 1024,
            directories=directories,
            files=files,
            snapshot_sha256=_snapshot_sha256(directories, files),
        )

    def test_manifest_round_trip_is_canonical_and_path_relative(self) -> None:
        manifest = self._manifest()
        source = dump_capture_backup_manifest(manifest)

        self.assertEqual(load_capture_backup_manifest(source), manifest)
        self.assertTrue(source.endswith(b"\n"))
        self.assertNotIn(b"C:\\", source)
        self.assertIn(CAPTURE_BACKUP_SCHEMA.encode("ascii"), source)

    def test_noncanonical_or_duplicate_json_is_rejected(self) -> None:
        source = dump_capture_backup_manifest(self._manifest())
        noncanonical = source.replace(b'"backup_id":', b'"backup_id" :', 1)
        with self.assertRaises(BackupManifestLoadError) as noncanonical_error:
            load_capture_backup_manifest(noncanonical)
        self.assertEqual(
            noncanonical_error.exception.code,
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

        duplicate = source.replace(
            b'"backup_id":',
            b'"backup_id":"job_00000000-0000-7000-8000-000000000000",'
            b'"backup_id":',
            1,
        )
        with self.assertRaises(BackupManifestLoadError):
            load_capture_backup_manifest(duplicate)

    def test_unknown_schema_version_is_classified_separately(self) -> None:
        parsed = json.loads(
            dump_capture_backup_manifest(self._manifest()).decode("utf-8")
        )
        parsed["schema_version"] = 2
        source = (
            json.dumps(
                parsed,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        with self.assertRaises(BackupManifestLoadError) as raised:
            load_capture_backup_manifest(source)
        self.assertEqual(
            raised.exception.code,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )

        parsed = json.loads(
            dump_capture_backup_manifest(self._manifest()).decode("utf-8")
        )
        parsed.pop("schema_version")
        malformed = (
            json.dumps(
                parsed,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with self.assertRaises(BackupManifestLoadError) as malformed_error:
            load_capture_backup_manifest(malformed)
        self.assertEqual(
            malformed_error.exception.code,
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )

    def test_boolean_counts_and_snapshot_tampering_are_rejected(self) -> None:
        parsed = json.loads(
            dump_capture_backup_manifest(self._manifest()).decode("utf-8")
        )
        parsed["snapshot"]["file_count"] = True
        source = (
            json.dumps(
                parsed,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with self.assertRaises(BackupManifestLoadError):
            load_capture_backup_manifest(source)

        parsed = json.loads(
            dump_capture_backup_manifest(self._manifest()).decode("utf-8")
        )
        parsed["snapshot"]["files"][0]["byte_size"] += 1
        source = (
            json.dumps(
                parsed,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with self.assertRaises(BackupManifestLoadError):
            load_capture_backup_manifest(source)


if __name__ == "__main__":
    unittest.main()
