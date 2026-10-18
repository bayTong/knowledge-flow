from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_curation.codec import (
    NonCanonicalYamlError,
    SchemaValidationError,
    YamlSyntaxGateError,
    curation_map_artifact_sha256,
    dump_curation_evidence,
    dump_curation_map,
    dump_curation_run,
    dump_kb_manifest,
    dump_map_decision,
    dump_source_mapping,
    load_curation_evidence,
    load_curation_map,
    load_curation_run,
    load_kb_manifest,
    load_map_decision,
    load_source_mapping,
    map_decision_sha256,
    render_curation_map_markdown,
)
from knowledgeflow_curation.contracts import (
    ByteRange,
    CandidateDecision,
    CurationEvidenceRecord,
    CurationOperation,
    EvidenceLocator,
    MapCandidate,
    ProcessingAuthorization,
    ProcessorProfile,
    ScopeRecord,
    SegmentRecord,
    SegmentationProfile,
    SourceBinding,
    TargetDecision,
)
from knowledgeflow_curation.errors import (
    CurationCommitState,
    CurationError,
    CurationErrorCode,
    CurationFailure,
)
from tests.curation._samples import (
    CANDIDATE_1_ID,
    CAPTURE_ID,
    LOCATOR_ID,
    SOURCE_BYTES,
    curation_map,
    curation_run,
    evidence_record,
    kb_manifest,
    map_decision,
    source_mapping,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CurationContractTest(unittest.TestCase):
    def _assert_canonical_bytes(self, value: bytes) -> None:
        self.assertFalse(value.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", value)
        self.assertTrue(value.endswith(b"\n"))
        self.assertFalse(value.endswith(b"\n\n"))

    def test_cur1a_01_source_mapping_and_run_match_golden(self) -> None:
        mapping_golden = (FIXTURES / "source-mapping-v1.yaml").read_bytes()
        golden = (FIXTURES / "curation-run-v1.yaml").read_bytes()
        self.assertEqual(dump_source_mapping(source_mapping()), mapping_golden)
        self.assertEqual(load_source_mapping(mapping_golden), source_mapping())
        self.assertEqual(dump_curation_run(curation_run()), golden)
        self.assertEqual(load_curation_run(golden), curation_run())
        curation_run().validate_source_mapping(source_mapping())
        self._assert_canonical_bytes(mapping_golden)
        self._assert_canonical_bytes(golden)

    def test_cur1a_02_evidence_record_matches_golden_and_round_trips(self) -> None:
        golden = (FIXTURES / "curation-evidence-v1.yaml").read_bytes()
        self.assertEqual(dump_curation_evidence(evidence_record()), golden)
        self.assertEqual(load_curation_evidence(golden), evidence_record())
        evidence_record().validate_against_run(curation_run())
        with self.assertRaises(ValueError):
            evidence_record().validate_against_run(
                replace(curation_run(), declared_scope=ByteRange(1, len(SOURCE_BYTES)))
            )
        self._assert_canonical_bytes(golden)

    def test_cur1a_03_map_views_match_golden_and_share_one_hash(self) -> None:
        yaml_golden = (FIXTURES / "curation-map-v1.yaml").read_bytes()
        markdown_golden = (FIXTURES / "curation-map-v1.md").read_bytes()
        value = curation_map()

        self.assertEqual(dump_curation_map(value), yaml_golden)
        self.assertEqual(render_curation_map_markdown(value), markdown_golden)
        self.assertEqual(load_curation_map(yaml_golden), value)
        self.assertEqual(
            curation_map_artifact_sha256(yaml_golden, markdown_golden),
            "sha256:5e6783fb8d1617904a28e1a62cc9337ee265322177524bbbcc752a3bc7f716d1",
        )
        self._assert_canonical_bytes(yaml_golden)
        self._assert_canonical_bytes(markdown_golden)

    def test_cur1a_04_map_decision_matches_golden_and_exact_byte_hash(self) -> None:
        golden = (FIXTURES / "curation-map-decision-v1.yaml").read_bytes()
        value = map_decision()
        self.assertEqual(dump_map_decision(value), golden)
        self.assertEqual(load_map_decision(golden), value)
        self.assertEqual(
            map_decision_sha256(value),
            "sha256:e91c2728cb005d59956b37b7509024af7cf83ec7e78ab0ee379fd96c6e120768",
        )
        self.assertEqual(map_decision_sha256(value), hash_bytes(golden).sha256)
        value.validate_against(curation_map(), value.map_sha256)
        with self.assertRaises(ValueError):
            value.validate_against(curation_map(), "sha256:" + ("f" * 64))

    def test_cur1a_05_kb_manifest_is_provisional_and_matches_golden(self) -> None:
        golden = (FIXTURES / "kb-manifest-v1.yaml").read_bytes()
        value = kb_manifest()
        self.assertEqual(dump_kb_manifest(value), golden)
        self.assertEqual(load_kb_manifest(golden), value)
        self.assertEqual(value.lifecycle, "provisional")
        self.assertEqual(value.trusted_visibility, "none")
        self.assertFalse(value.gbrain_federated)
        self._assert_canonical_bytes(golden)

    def test_cur1a_06_canonical_and_safe_yaml_boundaries_are_enforced(self) -> None:
        golden = (FIXTURES / "curation-run-v1.yaml").read_bytes()
        noncanonical = golden.replace(b"schema_version: 1\n", b"schema_version: 01\n")
        with self.assertRaises(NonCanonicalYamlError):
            load_curation_run(noncanonical)
        with self.assertRaises(YamlSyntaxGateError):
            load_curation_run(b"schema: &shared value\n")
        with self.assertRaises(YamlSyntaxGateError):
            load_curation_run(b"\xef\xbb\xbf" + golden)

    def test_cur1a_07_schema_rejects_missing_unknown_and_wrong_types(self) -> None:
        golden = (FIXTURES / "curation-run-v1.yaml").read_bytes()
        mutations = (
            golden.replace(b'state: "authorized"\n', b""),
            golden + b"unknown_field: true\n",
            golden.replace(b"schema_version: 1\n", b'schema_version: "1"\n'),
            golden.replace(b"schema_version: 1\n", b"schema_version: true\n"),
        )
        for value in mutations:
            with self.subTest(value=value[-40:]), self.assertRaises(
                SchemaValidationError
            ):
                load_curation_run(value)

    def test_cur1a_08_source_and_processing_authorization_are_exact(self) -> None:
        source = curation_run().source
        with self.assertRaises(ValueError):
            SourceBinding(
                capture_id=CAPTURE_ID,
                capture_version=1,
                envelope_sha256=source.envelope_sha256,
                payload_sha256="sha256:not-a-digest",
                byte_size=len(SOURCE_BYTES),
            )
        with self.assertRaises(ValueError):
            replace(source_mapping(), source_byte_size=len(SOURCE_BYTES) + 1)
        with self.assertRaises(ValueError):
            curation_run().validate_source_mapping(
                replace(
                    source_mapping(),
                    source_mapping_id=(
                        "smap_01991a7e-7b2f-7a31-8d14-0b8ab6b35430"
                    ),
                )
            )
        with self.assertRaises(ValueError):
            ProcessingAuthorization(
                authorization_id=(
                    "auth_01991a7e-7b23-7a31-8d14-0b8ab6b35424"
                ),
                authorized_by="local-user",
                authorized_at="2026-10-18T01:02:03.004Z",
                allowed_range=ByteRange(0, len(SOURCE_BYTES)),
                task_ids=("c-t1", "c-t1"),
            )
        outside = replace(
            curation_run().processing_authorization,
            allowed_range=ByteRange(0, len(SOURCE_BYTES) + 1),
        )
        with self.assertRaises(ValueError):
            replace(curation_run(), processing_authorization=outside)
        with self.assertRaises(ValueError):
            replace(
                curation_run(),
                declared_scope=ByteRange(1, len(SOURCE_BYTES) + 1),
            )

    def test_cur1a_09_target_and_processing_permissions_stay_separate(self) -> None:
        self.assertEqual(
            [item.value for item in CurationOperation],
            [
                "source.prepare",
                "source.inspect",
                "evidence.show",
                "target.decide",
                "map.build",
                "map.decide",
                "map.close",
            ],
        )
        new_kb = TargetDecision(
            target_decision_id=(
                "target_01991a7e-7b24-7a31-8d14-0b8ab6b35425"
            ),
            choice="new-kb",
            requested_display_name="示例库",
            target_kb_id=None,
            decided_by="local-user",
            decided_at="2026-10-18T01:02:03.005Z",
        )
        self.assertEqual(new_kb.choice, "new-kb")
        self.assertNotIn("trusted_write", curation_run().as_mapping())
        with self.assertRaises(ValueError):
            replace(new_kb, choice="no-target")
        with self.assertRaises(ValueError):
            replace(
                new_kb,
                target_kb_id="kb_01991a7e-7b2c-7a31-8d14-0b8ab6b3542d",
            )

    def test_cur1a_10_segmentation_and_processor_profiles_are_bounded(self) -> None:
        self.assertEqual(SegmentationProfile().target_bytes, 16 * 1024)
        self.assertEqual(SegmentationProfile().maximum_bytes, 32 * 1024)
        for options in (
            {"target_bytes": 8192},
            {"maximum_bytes": 65536},
            {"overlap_bytes": 1},
            {"revision": 2},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                SegmentationProfile(**options)
        with self.assertRaises(ValueError):
            ProcessorProfile(
                kind="test-fixture",
                processor_id="fixture",
                revision=1,
                model_id="remote-model",
                network_allowed=True,
            )
        with self.assertRaises(ValueError):
            replace(curation_map().scope[0], status="deferred", reason="line 1\nline 2")

    def test_cur1a_11_segments_and_scope_must_cover_the_declared_range(self) -> None:
        evidence = evidence_record()
        second = evidence.segments[1]
        gap = replace(second, byte_range=ByteRange(29, len(SOURCE_BYTES)))
        with self.assertRaises(ValueError):
            replace(evidence, segments=(evidence.segments[0], gap))
        incomplete_scope = (
            ScopeRecord(ByteRange(0, len(SOURCE_BYTES) - 1), "processed"),
        )
        with self.assertRaises(ValueError):
            replace(evidence, scope=incomplete_scope)

    def test_cur1a_12_locators_bind_exact_source_range_and_excerpt(self) -> None:
        evidence = evidence_record()
        locator = evidence.locators[0]
        changed_source = replace(
            locator.source,
            payload_sha256="sha256:" + ("f" * 64),
        )
        changed_locator = replace(locator, source=changed_source)
        with self.assertRaises(ValueError):
            replace(evidence, locators=(changed_locator,))
        with self.assertRaises(ValueError):
            EvidenceLocator(
                locator_id=LOCATOR_ID,
                source=locator.source,
                byte_range=ByteRange(0, len(SOURCE_BYTES) + 1),
                start_line=1,
                end_line=1,
                excerpt_sha256=locator.excerpt_sha256,
            )

    def test_cur1a_13_map_references_only_declared_evidence(self) -> None:
        value = curation_map()
        value.validate_against(evidence_record())
        value.validate_against_run(curation_run())
        unknown = "loc_01991a7e-7b2d-7a31-8d14-0b8ab6b3542e"
        changed = replace(
            value.candidates[0],
            evidence_locator_ids=(unknown,),
        )
        with self.assertRaises(ValueError):
            replace(value, candidates=(changed, value.candidates[1])).validate_against(
                evidence_record()
            )
        with self.assertRaises(ValueError):
            MapCandidate(
                candidate_id=CANDIDATE_1_ID,
                kind="claim",
                summary="没有证据的具体主张",
                evidence_locator_ids=(),
                provenance="source-claim",
                uncertainty="none",
                markdown_anchor="claim-without-evidence",
            )
        changed_processor = replace(
            curation_run(),
            processor_profile=ProcessorProfile(
                kind="mechanical",
                processor_id="different-processor",
                revision=1,
                model_id=None,
                network_allowed=False,
            ),
        )
        with self.assertRaises(ValueError):
            value.validate_against_run(changed_processor)

    def test_cur1a_14_contract_values_are_immutable_and_versions_are_explicit(self) -> None:
        value = curation_map()
        with self.assertRaises(FrozenInstanceError):
            value.map_version = 2
        revised = replace(value, map_version=2)
        self.assertEqual(value.map_version, 1)
        self.assertEqual(revised.map_version, 2)
        self.assertNotIn("outcome", value.as_mapping())
        modified = CandidateDecision(
            candidate_id=CANDIDATE_1_ID,
            action="modify",
            replacement_text="用户修改后的候选",
        )
        self.assertEqual(modified.action, "modify")
        with self.assertRaises(ValueError):
            replace(modified, replacement_text=None)

    def test_cur1a_15_errors_are_stable_bounded_and_honest_about_commit_state(self) -> None:
        error = CurationError(
            code=CurationErrorCode.INVALID_INPUT,
            retryable=False,
            details={"stage": "validate", "observed_bytes": 42},
        )
        self.assertEqual(error.to_dict()["message"], "curation request input is invalid")
        not_committed = CurationFailure(
            error,
            CurationCommitState.NOT_COMMITTED,
        ).to_dict()
        unknown = CurationFailure(error, CurationCommitState.UNKNOWN).to_dict()
        self.assertFalse(not_committed["saved"])
        self.assertNotIn("saved", unknown)
        with self.assertRaises(ValueError):
            CurationFailure(error, CurationCommitState.COMMITTED)
        with self.assertRaises(ValueError):
            CurationError(
                code=CurationErrorCode.INVALID_INPUT,
                retryable=False,
                details={"source_text": "must never be echoed"},
            )


if __name__ == "__main__":
    unittest.main()
