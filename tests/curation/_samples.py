from __future__ import annotations

from pathlib import Path

from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_curation.codec import (
    curation_map_artifact_sha256,
    dump_curation_map,
    render_curation_map_markdown,
)
from knowledgeflow_curation.contracts import (
    ByteRange,
    CandidateDecision,
    CurationEvidenceRecord,
    CurationMap,
    CurationRunManifest,
    EvidenceLocator,
    KnowledgeBaseManifest,
    MapCandidate,
    MapDecision,
    ProcessingAuthorization,
    ProcessorProfile,
    ProcessorUsage,
    ScopeRecord,
    SegmentRecord,
    SegmentationProfile,
    SourceBinding,
    SourceFileMapping,
    TargetDecision,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOURCE_BYTES = (FIXTURES / "source-v1.md").read_bytes()

CAPTURE_ID = "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
RUN_ID = "run_01991a7e-7b22-7a31-8d14-0b8ab6b35423"
AUTHORIZATION_ID = "auth_01991a7e-7b23-7a31-8d14-0b8ab6b35424"
TARGET_DECISION_ID = "target_01991a7e-7b24-7a31-8d14-0b8ab6b35425"
SEGMENT_1_ID = "seg_01991a7e-7b25-7a31-8d14-0b8ab6b35426"
SEGMENT_2_ID = "seg_01991a7e-7b26-7a31-8d14-0b8ab6b35427"
LOCATOR_ID = "loc_01991a7e-7b27-7a31-8d14-0b8ab6b35428"
MAP_ID = "map_01991a7e-7b28-7a31-8d14-0b8ab6b35429"
CANDIDATE_1_ID = "cand_01991a7e-7b29-7a31-8d14-0b8ab6b3542a"
CANDIDATE_2_ID = "cand_01991a7e-7b2a-7a31-8d14-0b8ab6b3542b"
DECISION_SET_ID = "dset_01991a7e-7b2b-7a31-8d14-0b8ab6b3542c"
KB_ID = "kb_01991a7e-7b2c-7a31-8d14-0b8ab6b3542d"
SOURCE_MAPPING_ID = "smap_01991a7e-7b2e-7a31-8d14-0b8ab6b3542f"

ENVELOPE_SHA256 = "sha256:" + ("1" * 64)
SOURCE_SHA256 = hash_bytes(SOURCE_BYTES).sha256
SECOND_SEGMENT_START = SOURCE_BYTES.index("第二段".encode("utf-8"))
FIRST_TEXT_START = SOURCE_BYTES.index("第一段".encode("utf-8"))
FIRST_TEXT_END = FIRST_TEXT_START + len("第一段🙂。".encode("utf-8"))


def source_binding() -> SourceBinding:
    return SourceBinding(
        capture_id=CAPTURE_ID,
        capture_version=1,
        envelope_sha256=ENVELOPE_SHA256,
        payload_sha256=SOURCE_SHA256,
        byte_size=len(SOURCE_BYTES),
    )


def segmentation_profile() -> SegmentationProfile:
    return SegmentationProfile()


def source_mapping() -> SourceFileMapping:
    return SourceFileMapping(
        source_mapping_id=SOURCE_MAPPING_ID,
        source_reference="fixture-source-v1",
        source_sha256=SOURCE_SHA256,
        source_byte_size=len(SOURCE_BYTES),
        capture=source_binding(),
        mapped_at="2026-10-18T01:02:03.003Z",
    )


def processor_profile() -> ProcessorProfile:
    return ProcessorProfile(
        kind="test-fixture",
        processor_id="cur1-contract-fixture",
        revision=1,
        model_id=None,
        network_allowed=False,
    )


def curation_run() -> CurationRunManifest:
    return CurationRunManifest(
        curation_run_id=RUN_ID,
        source_mapping_id=SOURCE_MAPPING_ID,
        source=source_binding(),
        processing_authorization=ProcessingAuthorization(
            authorization_id=AUTHORIZATION_ID,
            authorized_by="local-user",
            authorized_at="2026-10-18T01:02:03.004Z",
            allowed_range=ByteRange(0, len(SOURCE_BYTES)),
            task_ids=("c-t1", "c-t4"),
            budget_id=None,
        ),
        declared_scope=ByteRange(0, len(SOURCE_BYTES)),
        target_decision=TargetDecision(
            target_decision_id=TARGET_DECISION_ID,
            choice="no-target",
            requested_display_name=None,
            target_kb_id=None,
            decided_by="local-user",
            decided_at="2026-10-18T01:02:03.005Z",
        ),
        segmentation_profile=segmentation_profile(),
        processor_profile=processor_profile(),
        state="authorized",
    )


def scope() -> tuple[ScopeRecord, ...]:
    return (
        ScopeRecord(
            byte_range=ByteRange(0, len(SOURCE_BYTES)),
            status="processed",
        ),
    )


def evidence_record() -> CurationEvidenceRecord:
    source = source_binding()
    return CurationEvidenceRecord(
        curation_run_id=RUN_ID,
        source=source,
        declared_scope=ByteRange(0, len(SOURCE_BYTES)),
        segmentation_profile=segmentation_profile(),
        segments=(
            SegmentRecord(
                segment_id=SEGMENT_1_ID,
                ordinal=0,
                byte_range=ByteRange(0, SECOND_SEGMENT_START),
                start_line=1,
                end_line=4,
                heading_path=("主题",),
                body_sha256=hash_bytes(SOURCE_BYTES[:SECOND_SEGMENT_START]).sha256,
                profile_id="experiment-markdown-blocks",
                profile_revision=1,
            ),
            SegmentRecord(
                segment_id=SEGMENT_2_ID,
                ordinal=1,
                byte_range=ByteRange(SECOND_SEGMENT_START, len(SOURCE_BYTES)),
                start_line=5,
                end_line=5,
                heading_path=("主题",),
                body_sha256=hash_bytes(SOURCE_BYTES[SECOND_SEGMENT_START:]).sha256,
                profile_id="experiment-markdown-blocks",
                profile_revision=1,
            ),
        ),
        scope=scope(),
        locators=(
            EvidenceLocator(
                locator_id=LOCATOR_ID,
                source=source,
                byte_range=ByteRange(FIRST_TEXT_START, FIRST_TEXT_END),
                start_line=3,
                end_line=3,
                excerpt_sha256=hash_bytes(
                    SOURCE_BYTES[FIRST_TEXT_START:FIRST_TEXT_END]
                ).sha256,
            ),
        ),
    )


def curation_map() -> CurationMap:
    return CurationMap(
        map_id=MAP_ID,
        map_version=1,
        curation_run_id=RUN_ID,
        created_at="2026-10-18T01:02:03.006Z",
        source=source_binding(),
        declared_scope=ByteRange(0, len(SOURCE_BYTES)),
        scope=scope(),
        processor_profile=processor_profile(),
        processor_usage=ProcessorUsage(
            call_count=0,
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=12,
        ),
        target_binding=None,
        candidates=(
            MapCandidate(
                candidate_id=CANDIDATE_1_ID,
                kind="overview",
                summary="样本包含一个标题和两段正文。",
                evidence_locator_ids=(LOCATOR_ID,),
                provenance="source-claim",
                uncertainty="none",
                markdown_anchor="candidate-overview",
            ),
            MapCandidate(
                candidate_id=CANDIDATE_2_ID,
                kind="gap",
                summary="本测试夹具不核验样本文字以外的外部事实。",
                evidence_locator_ids=(),
                provenance="processor-inference",
                uncertainty="high",
                markdown_anchor="candidate-external-gap",
            ),
        ),
    )


def map_sha256() -> str:
    value = curation_map()
    return curation_map_artifact_sha256(
        dump_curation_map(value),
        render_curation_map_markdown(value),
    )


def map_decision() -> MapDecision:
    return MapDecision(
        decision_set_id=DECISION_SET_ID,
        version=1,
        map_sha256=map_sha256(),
        outcome="map-closed",
        decided_by="local-user",
        decided_at="2026-10-18T01:02:03.007Z",
        decisions=(
            CandidateDecision(
                candidate_id=CANDIDATE_1_ID,
                action="accept",
            ),
            CandidateDecision(
                candidate_id=CANDIDATE_2_ID,
                action="defer",
            ),
        ),
    )


def kb_manifest() -> KnowledgeBaseManifest:
    return KnowledgeBaseManifest(
        kb_id=KB_ID,
        storage_name="2026-10-18-01",
        display_name="2026-10-18-01",
        created_at="2026-10-18T01:02:03.008Z",
        created_by="local-user",
        creation_request_id="bootstrap-request-01",
    )


__all__ = [
    "AUTHORIZATION_ID",
    "CANDIDATE_1_ID",
    "CANDIDATE_2_ID",
    "CAPTURE_ID",
    "DECISION_SET_ID",
    "FIXTURES",
    "KB_ID",
    "LOCATOR_ID",
    "MAP_ID",
    "RUN_ID",
    "SOURCE_BYTES",
    "SOURCE_MAPPING_ID",
    "SOURCE_SHA256",
    "curation_map",
    "curation_run",
    "evidence_record",
    "kb_manifest",
    "map_decision",
    "map_sha256",
    "processor_profile",
    "scope",
    "segmentation_profile",
    "source_binding",
    "source_mapping",
]
