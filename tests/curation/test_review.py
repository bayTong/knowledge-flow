from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_curation import (
    DeterministicTestProcessor,
    CandidateDecision,
    MapBuildRequest,
    MapBuildResult,
    MapDecideRequest,
    MapDecisionResult,
    SourcePrepareRequest,
    SourcePrepareResult,
    TargetDecideRequest,
    TargetDecideResult,
    build_map,
    decide_map,
    prepare_source,
    target_decide,
)
from knowledgeflow_curation.review import MapReviewError, load_map_review
from knowledgeflow_curation.cli import _ArgumentError, _budget_limits
from knowledgeflow_curation.errors import CurationErrorCode, CurationFailure
from knowledgeflow_curation.map_operations import _short_line_ranges
from knowledgeflow_curation.processing import (
    ProcessingBudgetLimits,
    ProcessingStage,
    ProcessorCallUsage,
    ProcessorCandidateDraft,
    ProcessorResponse,
)


class _ShortReadingProcessor(DeterministicTestProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    def process(self, request):
        self.requests.append(request)
        assert request.stage is ProcessingStage.GLOBAL_MAP
        exact = next(
            item.reference for item in request.segments if "可核验的原文" in item.body
        )
        return ProcessorResponse(
            candidates=(
                ProcessorCandidateDraft(
                    kind="overview",
                    summary="这份合成材料分为两个部分。",
                    evidence_refs=tuple(item.reference for item in request.segments),
                    provenance="processor-inference",
                    uncertainty="low",
                    markdown_anchor="short-overview",
                ),
                ProcessorCandidateDraft(
                    kind="claim",
                    summary="第一部分含一条可核验的表述。",
                    evidence_refs=(exact,),
                    provenance="source-claim",
                    uncertainty="low",
                    markdown_anchor="short-claim",
                ),
            ),
            usage=ProcessorCallUsage(0, 0, 0, 1, None, None, "stop"),
        )


class MapReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.experiment_root = self.root / "experiment"
        self.policy = PathPolicy.test_owned(self.root)
        self.body = (
            "# 低敏感合成材料\n\n"
            "## 第一部分\n这里有可核验的原文。\n\n"
            "## 第二部分\n另一段用于地图阅读。\n"
        ).encode("utf-8")
        source_path = self.root / "source.md"
        source_path.write_bytes(self.body)
        prepared = prepare_source(
            SourcePrepareRequest(
                request_id="source-review-01",
                source_path=source_path,
                source_reference="synthetic-review",
                expected_sha256=hash_bytes(self.body).sha256,
                expected_byte_size=len(self.body),
                authorized_by="local-user",
                task_ids=("c-t1", "c-t4"),
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(prepared, SourcePrepareResult)
        decided = target_decide(
            TargetDecideRequest(
                decision_request_id="target-review-01",
                source_request_id="source-review-01",
                choice="no-target",
                decided_by="local-user",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            now=lambda: datetime(2026, 10, 28, 1, 2, 3, tzinfo=timezone.utc),
        )
        self.assertIsInstance(decided, TargetDecideResult)
        built = build_map(
            MapBuildRequest(
                request_id="map-review-01",
                source_request_id="source-review-01",
                target_decision_request_id="target-review-01",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=DeterministicTestProcessor(),
            now=lambda: datetime(2026, 10, 28, 1, 2, 4, tzinfo=timezone.utc),
        )
        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)
        self.built = built

    def _load(self):
        return load_map_review(
            experiment_root=self.experiment_root,
            map_directory=self.built.yaml_path.parent,
            path_policy=self.policy,
        )

    def test_review_groups_candidates_and_reopens_exact_source(self) -> None:
        published_markdown = self.built.markdown_path.read_bytes()
        session = self._load()
        self.assertEqual(session.map_sha256, self.built.map_sha256)
        self.assertEqual(len(session.sections), 8)
        self.assertTrue(any(section.candidates for section in session.sections))
        candidate = next(
            item
            for item in session.curation_map.candidates
            if item.evidence_locator_ids
        )
        locator_id = candidate.evidence_locator_ids[0]
        excerpt = session.read_evidence(candidate.candidate_id, locator_id)
        expected = next(
            item for item in session.evidence.locators if item.locator_id == locator_id
        )
        self.assertEqual(
            excerpt.text,
            self.body[
                expected.byte_range.start_byte : expected.byte_range.end_byte
            ].decode("utf-8"),
        )
        self.assertEqual(excerpt.excerpt_sha256, expected.excerpt_sha256)
        self.assertIn("原文第", session.locator_label(locator_id))
        self.assertEqual(
            self.built.markdown_path.read_bytes(), published_markdown
        )

    def test_review_rejects_unrelated_evidence_and_tampered_map(self) -> None:
        session = self._load()
        candidate = next(
            item
            for item in session.curation_map.candidates
            if item.evidence_locator_ids
        )
        with self.assertRaises(MapReviewError):
            session.read_evidence(candidate.candidate_id, "loc_01991a7e-7b27-7a31-8d14-0b8ab6b35428")
        self.built.markdown_path.write_bytes(
            self.built.markdown_path.read_bytes() + b"\nchanged\n"
        )
        with self.assertRaises(MapReviewError):
            self._load()

    def test_review_rejects_map_path_outside_the_experiment_work_root(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        with self.assertRaises(MapReviewError):
            load_map_review(
                experiment_root=self.experiment_root,
                map_directory=outside,
                path_policy=self.policy,
            )

    def test_formal_short_profile_publishes_line_evidence_and_replays(self) -> None:
        request = MapBuildRequest(
            request_id="map-review-short-01",
            source_request_id="source-review-01",
            target_decision_request_id="target-review-01",
            reading_profile="short-ten-section-v1",
        )
        processor = _ShortReadingProcessor()
        first = build_map(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
        )
        self.assertIsInstance(first, MapBuildResult)
        assert isinstance(first, MapBuildResult)
        self.assertEqual(first.curation_map.reading_profile, "short-ten-section-v1")
        self.assertGreater(len(first.curation_map.review_locators), 1)
        self.assertEqual(len(processor.requests), 1)
        self.assertEqual(processor.requests[0].prompt_profile, "cur1d-short-ten-section")
        self.assertIn(
            "never machine references or locator IDs in summary text",
            processor.requests[0].task,
        )
        contract = processor.requests[0].provider_mapping()["output_contract"]
        self.assertEqual(contract["stage_rules"]["focus_topics"], "must be an empty array")
        self.assertEqual(contract["example_json_object"]["focus_topics"], [])
        self.assertIn("## 10. 覆盖报告", first.markdown_path.read_text(encoding="utf-8"))
        session = load_map_review(
            experiment_root=self.experiment_root,
            map_directory=first.yaml_path.parent,
            path_policy=self.policy,
        )
        claim = next(item for item in first.curation_map.candidates if item.kind == "claim")
        excerpt = session.read_evidence(claim.candidate_id, claim.evidence_locator_ids[0])
        self.assertIn("可核验的原文", excerpt.text)
        self.assertFalse(excerpt.whole_source)
        self.assertIn("原文第", session.locator_label(claim.evidence_locator_ids[0]))
        second = build_map(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
        )
        self.assertIsInstance(second, MapBuildResult)
        assert isinstance(second, MapBuildResult)
        self.assertTrue(second.replayed)
        self.assertEqual(first.map_sha256, second.map_sha256)
        self.assertEqual(len(processor.requests), 1)

    def test_short_profile_rejects_insufficient_budget_before_processing(self) -> None:
        processor = _ShortReadingProcessor()
        published_before = set(self.experiment_root.rglob("map.yaml"))
        outcome = build_map(
            MapBuildRequest(
                request_id="map-review-short-budget-01",
                source_request_id="source-review-01",
                target_decision_request_id="target-review-01",
                reading_profile="short-ten-section-v1",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            budget_limits=ProcessingBudgetLimits(max_reasoning_tokens=1),
        )
        self.assertIsInstance(outcome, CurationFailure)
        assert isinstance(outcome, CurationFailure)
        self.assertEqual(outcome.error.code, CurationErrorCode.BUDGET_EXHAUSTED)
        self.assertEqual(processor.requests, [])
        self.assertEqual(set(self.experiment_root.rglob("map.yaml")), published_before)

    def test_short_reading_map_revision_retains_exact_evidence(self) -> None:
        built = build_map(
            MapBuildRequest(
                request_id="map-review-short-revision-01",
                source_request_id="source-review-01",
                target_decision_request_id="target-review-01",
                reading_profile="short-ten-section-v1",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=_ShortReadingProcessor(),
        )
        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)
        original = built.markdown_path.read_bytes()
        claim = next(item for item in built.curation_map.candidates if item.kind == "claim")
        revised = decide_map(
            MapDecideRequest(
                request_id="map-review-short-decision-01",
                source_request_id="source-review-01",
                target_decision_request_id="target-review-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(
                    CandidateDecision(
                        candidate_id=claim.candidate_id,
                        action="modify",
                        replacement_text="用户修正后的明确表述。",
                    ),
                ),
            ),
            experiment_root=self.experiment_root,
        )
        self.assertIsInstance(revised, MapDecisionResult)
        assert isinstance(revised, MapDecisionResult)
        self.assertEqual(built.markdown_path.read_bytes(), original)
        self.assertEqual(revised.revised_map.reading_profile, "short-ten-section-v1")
        self.assertEqual(
            revised.revised_map.review_locators,
            built.curation_map.review_locators,
        )
        changed = next(
            item
            for item in revised.revised_map.candidates
            if item.supersedes == claim.candidate_id
        )
        self.assertEqual(changed.evidence_locator_ids, claim.evidence_locator_ids)

    def test_short_ranges_preserve_utf8_and_crlf_bytes(self) -> None:
        body = "甲\r\n乙乙\n末行".encode("utf-8")
        ranges = _short_line_ranges(body)
        self.assertEqual(
            b"".join(body[item.start_byte : item.end_byte] for item in ranges),
            body,
        )
        self.assertEqual(
            [body[item.start_byte : item.end_byte].decode("utf-8") for item in ranges],
            ["甲\r\n", "乙乙\n", "末行"],
        )

    def test_short_remote_budget_file_requires_all_positive_limits(self) -> None:
        path = self.root / "budget.json"
        defaults = ProcessingBudgetLimits()
        value = {name: getattr(defaults, name) for name in defaults.__slots__}
        value["max_first_work_units"] = 1
        value["max_http_attempts"] = 1
        path.write_text(json.dumps(value), encoding="utf-8")
        parsed = _budget_limits(str(path))
        self.assertEqual(parsed.max_first_work_units, 1)
        self.assertEqual(parsed.max_http_attempts, 1)
        value.pop("max_cost_microusd")
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(_ArgumentError):
            _budget_limits(str(path))


if __name__ == "__main__":
    unittest.main()
