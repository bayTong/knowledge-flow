from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from knowledgeflow_capture.codec import (
    NonCanonicalYamlError,
    SchemaValidationError,
    YamlSyntaxGateError,
    dump_envelope,
    load_envelope,
    parse_restricted_yaml,
    validate_envelope,
)
from knowledgeflow_capture.hashing import seal_envelope
from .._samples import envelope_with_placeholder_hash, envelope_without_hash


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class RestrictedYamlCodecTest(unittest.TestCase):
    def test_syntax_gate_rejects_disallowed_yaml_features(self) -> None:
        cases = {
            "duplicate-key": "a: 1\na: 2\n",
            "anchor": "a: &shared 1\n",
            "alias": "a: &shared 1\nb: *shared\n",
            "tag": "a: !!str value\n",
            "merge-key": "a:\n  <<: {b: 1}\n",
            "multi-document": "---\na: 1\n---\nb: 2\n",
            "float": "a: 1.5\n",
            "timestamp": "a: 2026-09-02\n",
            "binary": "a: !!binary SGVsbG8=\n",
            "non-string-key": "1: value\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name), self.assertRaises(YamlSyntaxGateError):
                parse_restricted_yaml(source)

    def test_syntax_safe_document_can_still_fail_envelope_schema(self) -> None:
        safe = parse_restricted_yaml('schema: "knowledgeflow.capture-envelope"\nschema_version: 1\n')
        with self.assertRaises(SchemaValidationError):
            validate_envelope(safe)

    def test_schema_rejects_missing_wrong_unknown_and_invalid_enum(self) -> None:
        mutations = []

        missing = envelope_with_placeholder_hash()
        del missing["version"]
        mutations.append(missing)

        wrong_type = envelope_with_placeholder_hash()
        wrong_type["version"] = "1"
        mutations.append(wrong_type)

        unknown = envelope_with_placeholder_hash()
        unknown["model_summary"] = "must not enter envelope"
        mutations.append(unknown)

        unknown_version = envelope_with_placeholder_hash()
        unknown_version["schema_version"] = 2
        mutations.append(unknown_version)

        invalid_enum = envelope_with_placeholder_hash()
        invalid_enum["payloads"][0]["fidelity"] = "approximately-same"
        mutations.append(invalid_enum)

        for document in mutations:
            with self.subTest(document=document), self.assertRaises(
                SchemaValidationError
            ):
                validate_envelope(document)

    def test_schema_distinguishes_bool_from_integer(self) -> None:
        document = envelope_with_placeholder_hash()
        document["version"] = True
        with self.assertRaises(SchemaValidationError):
            validate_envelope(document)

    def test_deterministic_emitter_matches_golden_contract(self) -> None:
        sealed = seal_envelope(envelope_without_hash())
        expected = (FIXTURES / "envelope-v1.yaml").read_bytes()

        self.assertEqual(sealed.yaml_bytes, expected)
        self.assertFalse(expected.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", expected)
        self.assertTrue(expected.endswith(b"\n"))
        self.assertFalse(expected.endswith(b"\n\n"))
        self.assertNotIn(b"\n\n", expected)

    def test_canonical_load_round_trips_and_rejects_noncanonical_bytes(self) -> None:
        golden = (FIXTURES / "envelope-v1.yaml").read_bytes()
        loaded = load_envelope(golden, require_canonical=True)
        self.assertEqual(dump_envelope(loaded), golden)

        noncanonical = golden.replace(b"schema_version: 1\n", b"schema_version: 01\n")
        with self.assertRaises(NonCanonicalYamlError):
            load_envelope(noncanonical, require_canonical=True)

    def test_bom_is_rejected_before_parsing(self) -> None:
        with self.assertRaises(YamlSyntaxGateError):
            parse_restricted_yaml(b"\xef\xbb\xbf" + b'a: "value"\n')

    def test_payload_invariants_are_schema_validated(self) -> None:
        duplicate_primary = envelope_with_placeholder_hash()
        duplicate_primary["payloads"].append(
            deepcopy(duplicate_primary["payloads"][0])
        )
        with self.assertRaises(SchemaValidationError):
            validate_envelope(duplicate_primary)

        mismatched_identity = envelope_with_placeholder_hash()
        mismatched_identity["payloads"][0]["payload_id"] = "sha256:" + ("f" * 64)
        with self.assertRaises(SchemaValidationError):
            validate_envelope(mismatched_identity)


if __name__ == "__main__":
    unittest.main()
