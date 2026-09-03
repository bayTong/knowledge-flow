from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from knowledgeflow_capture.errors import PublicErrorCode
from knowledgeflow_capture.manifest import (
    CaptureStoreManifest,
    ManifestLoadError,
    dump_capture_store_manifest,
    load_capture_store_manifest,
    validate_capture_store_manifest,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STORE_ID = "store_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
CREATED_AT = "2026-09-03T01:02:03.004Z"


def valid_mapping() -> dict[str, object]:
    return {
        "schema": "knowledgeflow.capture-store",
        "schema_version": 1,
        "store_id": STORE_ID,
        "layout_version": 1,
        "created_at": CREATED_AT,
    }


class CaptureStoreManifestTest(unittest.TestCase):
    def test_man_01_emitter_and_loader_match_golden_bytes(self) -> None:
        manifest = CaptureStoreManifest(store_id=STORE_ID, created_at=CREATED_AT)
        expected = (FIXTURES / "capture-store-v1.yaml").read_bytes()

        self.assertEqual(dump_capture_store_manifest(manifest), expected)
        self.assertEqual(load_capture_store_manifest(expected), manifest)
        self.assertFalse(expected.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", expected)
        self.assertTrue(expected.endswith(b"\n"))

    def test_man_02_store_id_and_utc_timestamp_are_validated(self) -> None:
        mutations = []
        for store_id in (
            "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421",
            "store_not-a-uuid",
            "store_01991A7E-7B20-7A31-8D14-0B8AB6B35421",
        ):
            value = valid_mapping()
            value["store_id"] = store_id
            mutations.append(value)
        for created_at in (
            "2026-09-03T01:02:03Z",
            "2026-09-03T01:02:03.004+00:00",
            "2026-13-03T01:02:03.004Z",
        ):
            value = valid_mapping()
            value["created_at"] = created_at
            mutations.append(value)

        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ManifestLoadError) as raised:
                validate_capture_store_manifest(value)
            self.assertEqual(
                raised.exception.code,
                PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            )

    def test_man_03_syntax_and_schema_violations_are_rejected(self) -> None:
        duplicate = (
            'schema: "knowledgeflow.capture-store"\n'
            'schema: "knowledgeflow.capture-store"\n'
            "schema_version: 1\n"
        )
        with self.assertRaises(ManifestLoadError) as raised:
            load_capture_store_manifest(duplicate)
        self.assertEqual(
            raised.exception.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )

        mutations = []
        missing = valid_mapping()
        del missing["created_at"]
        mutations.append(missing)
        unknown = valid_mapping()
        unknown["capture_root"] = r"E:\private"
        mutations.append(unknown)
        wrong_type = valid_mapping()
        wrong_type["layout_version"] = "1"
        mutations.append(wrong_type)

        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ManifestLoadError) as raised:
                validate_capture_store_manifest(value)
            self.assertEqual(
                raised.exception.code,
                PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            )

    def test_man_04_unknown_versions_use_dedicated_public_code(self) -> None:
        for field, value in (
            ("schema", "knowledgeflow.capture-store-v2"),
            ("schema_version", 2),
            ("layout_version", 2),
        ):
            document = valid_mapping()
            document[field] = value
            with self.subTest(field=field), self.assertRaises(ManifestLoadError) as raised:
                validate_capture_store_manifest(document)
            self.assertEqual(
                raised.exception.code,
                PublicErrorCode.UNSUPPORTED_STORE_VERSION,
            )

    def test_man_05_noncanonical_manifest_is_rejected_without_rewrite(self) -> None:
        canonical = (FIXTURES / "capture-store-v1.yaml").read_bytes()
        noncanonical = canonical.replace(b"schema_version: 1\n", b"schema_version: 01\n")

        with self.assertRaises(ManifestLoadError) as raised:
            load_capture_store_manifest(noncanonical)
        self.assertEqual(
            raised.exception.code,
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
        )
        self.assertEqual(
            (FIXTURES / "capture-store-v1.yaml").read_bytes(),
            canonical,
        )

    def test_man_06_manifest_contains_only_portable_identity_fields(self) -> None:
        manifest = validate_capture_store_manifest(deepcopy(valid_mapping()))
        emitted = dump_capture_store_manifest(manifest)

        self.assertEqual(
            tuple(manifest.as_mapping()),
            ("schema", "schema_version", "store_id", "layout_version", "created_at"),
        )
        for forbidden in (
            b"capture_root",
            b"E:\\",
            b"username",
            b"hostname",
            b"kb",
            b"gbrain",
            b"item_count",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, emitted.lower())


if __name__ == "__main__":
    unittest.main()
