from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from knowledgeflow_capture.durability import DurabilityBackend, DurabilityError, DurabilityStage
from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_curation import (
    ByteRange,
    CandidateDecision,
    CurationErrorCode,
    CurationFailure,
    DeterministicTestProcessor,
    KnowledgeBaseRootPolicy,
    MapBuildRequest,
    MapBuildResult,
    MapDecideRequest,
    MapDecisionResult,
    ProcessingBudgetLimits,
    ProcessorCallUsage,
    ProcessorCallError,
    ProcessorProfile,
    ProcessorCandidateDraft,
    ProcessorResponse,
    RemoteProcessingAuthorization,
    SourcePrepareRequest,
    SourcePrepareResult,
    TargetDecideRequest,
    TargetDecideResult,
    TargetSuggestRequest,
    TargetSuggestResult,
    Utf8ByteUpperBoundTokenCounter,
    build_map,
    close_map,
    decide_map,
    load_curation_map,
    prepare_source,
    suggest_target,
    target_decide,
)
from knowledgeflow_curation.cli import _run_cli
from knowledgeflow_curation.versioning import ManagedGit


class _CountingProcessor:
    def __init__(self) -> None:
        self.delegate = DeterministicTestProcessor()
        self.calls = 0

    @property
    def profile(self):
        return self.delegate.profile

    @property
    def provider_profile(self):
        return self.delegate.provider_profile

    @property
    def key_reference(self):
        return self.delegate.key_reference

    def process(self, request):
        self.calls += 1
        return self.delegate.process(request)


class _InvalidEvidenceProcessor(_CountingProcessor):
    def process(self, request):
        self.calls += 1
        valid = self.delegate.process(request)
        if not valid.candidates:
            return valid
        return ProcessorResponse(
            candidates=(
                ProcessorCandidateDraft(
                    kind="claim",
                    summary="引用了不在请求内的证据。",
                    evidence_refs=("s999999",),
                    provenance="source-claim",
                    uncertainty="low",
                    markdown_anchor="invalid-evidence",
                ),
            ),
            usage=valid.usage,
        )


class _IncompleteTargetProcessor(_CountingProcessor):
    def process(self, request):
        self.calls += 1
        valid = self.delegate.process(request)
        return ProcessorResponse(candidates=(), usage=valid.usage)


class _AuthorizedRemoteProcessor(_CountingProcessor):
    def __init__(self) -> None:
        super().__init__()
        self._profile = ProcessorProfile(
            kind="remote-api",
            processor_id="test-remote-provider",
            revision=1,
            model_id="test-model-v1",
            network_allowed=True,
        )

    @property
    def profile(self):
        return self._profile

    @property
    def provider_profile(self):
        return "test-remote-provider"

    @property
    def key_reference(self):
        return "TEST_REMOTE_API_KEY"


class _MeteredAuthorizedRemoteProcessor(_AuthorizedRemoteProcessor):
    def process(self, request):
        response = super().process(request)
        return ProcessorResponse(
            candidates=response.candidates,
            usage=ProcessorCallUsage(
                input_tokens=100,
                visible_output_tokens=10,
                reasoning_tokens=0,
                elapsed_ms=5,
                response_model="test-model-v1",
                system_fingerprint="test-fingerprint",
                finish_reason="stop",
            ),
            synopsis=response.synopsis,
            target_choice=response.target_choice,
            target_rationale=response.target_rationale,
            focus_topics=response.focus_topics,
        )


class _FailMapPublishDurability(DurabilityBackend):
    def commit_directory_no_replace(self, source, destination):
        if Path(destination).name.startswith("map_"):
            raise DurabilityError(DurabilityStage.RENAME)
        return super().commit_directory_no_replace(source, destination)


class _InterruptingProcessor(_CountingProcessor):
    def process(self, request):
        self.calls += 1
        raise KeyboardInterrupt("simulated process termination")


class _PostSendUnknownProcessor(_CountingProcessor):
    def process(self, request):
        self.calls += 1
        raise ProcessorCallError(
            "simulated post-send timeout",
            retryable=False,
            request_sent=True,
            unknown_usage=True,
        )


class _PreSendRetryProcessor(_CountingProcessor):
    def process(self, request):
        self.calls += 1
        raise ProcessorCallError(
            "simulated pre-send connection failure",
            retryable=True,
            request_sent=False,
            unknown_usage=False,
        )


class _FailFirstUnitRecordDurability(DurabilityBackend):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "failed", False)

    def write_new_file_durable(self, path, payload, **kwargs):
        if Path(path).name == "unit-l1-001.json" and not self.failed:
            object.__setattr__(self, "failed", True)
            raise DurabilityError(DurabilityStage.FILE_WRITE)
        return super().write_new_file_durable(path, payload, **kwargs)


class _FailOnceMapReceiptDurability(DurabilityBackend):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "failed", False)

    def write_new_file_durable(self, path, payload, **kwargs):
        selected = Path(path)
        if (
            not self.failed
            and selected.parent.name == "receipts"
            and selected.name.startswith("map-")
        ):
            object.__setattr__(self, "failed", True)
            raise DurabilityError(DurabilityStage.FILE_WRITE)
        return super().write_new_file_durable(path, payload, **kwargs)


class _FailOnceMapPublishManifestDurability(DurabilityBackend):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "failed", False)

    def write_new_file_durable(self, path, payload, **kwargs):
        selected = Path(path)
        if (
            not self.failed
            and selected.name == "publish.json"
            and selected.parent.name.startswith("map-")
        ):
            object.__setattr__(self, "failed", True)
            raise DurabilityError(DurabilityStage.FILE_WRITE)
        return super().write_new_file_durable(path, payload, **kwargs)


class _MapTestManagedGit(ManagedGit):
    """Keep map tests runnable when the test sandbox itself is a Git worktree."""

    def require_standalone_parent(self, parent: Path) -> None:
        self.check_available(parent)


def _map_test_git(parent: Path) -> ManagedGit:
    if any((candidate / ".git").exists() for candidate in (parent, *parent.parents)):
        return _MapTestManagedGit()
    return ManagedGit()


class MapOperationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.owned_root = Path(self._temporary.name).resolve()
        self.experiment_root = self.owned_root / "experiment"
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.body = (
            "# 合成材料\n\n"
            "## 第一部分\n\n这是用于离线编排测试的低敏感正文。\n\n"
            "## 第二部分\n\n这里检查证据定位、地图版本和人工决定。\n"
        ).encode("utf-8")
        source_path = self.owned_root / "source.md"
        source_path.write_bytes(self.body)
        prepared = prepare_source(
            SourcePrepareRequest(
                request_id="source-map-01",
                source_path=source_path,
                source_reference="synthetic-cur1d",
                expected_sha256=hash_bytes(self.body).sha256,
                expected_byte_size=len(self.body),
                authorized_by="local-user",
                task_ids=("c-t1", "c-t4"),
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(prepared, SourcePrepareResult)
        self.prepared = prepared

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def _fixed_now() -> datetime:
        return datetime(2026, 10, 21, 1, 2, 3, 4000, tzinfo=timezone.utc)

    def _no_target(self) -> TargetDecideResult:
        result = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="no-target",
                decided_by="local-user",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(result, TargetDecideResult)
        assert isinstance(result, TargetDecideResult)
        return result

    def _target_kb(self) -> tuple[Path, TargetDecideResult, Path]:
        kb_parent = self.experiment_root / "kb-root"
        kb_parent.mkdir(parents=True)
        root_policy = KnowledgeBaseRootPolicy(
            policy_id="test-kb-root",
            revision=1,
            allowed_parents=(kb_parent,),
        )
        target = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="new-kb",
                decided_by="local-user",
                kb_parent=kb_parent,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            root_policy=root_policy,
            git=_map_test_git(kb_parent),
            now=self._fixed_now,
        )
        self.assertIsInstance(target, TargetDecideResult)
        assert isinstance(target, TargetDecideResult)
        assert target.storage_name is not None
        return kb_parent, target, kb_parent / target.storage_name

    def _build(
        self,
        *,
        processor=None,
        request_id: str = "map-build-01",
        kb_parent: Path | None = None,
        **kwargs: object,
    ):
        return build_map(
            MapBuildRequest(
                request_id=request_id,
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                kb_parent=kb_parent,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor or DeterministicTestProcessor(),
            now=self._fixed_now,
            **kwargs,
        )

    def test_cur1d_09_target_suggestion_waits_for_human_and_is_replayable(self) -> None:
        processor = _CountingProcessor()
        request = TargetSuggestRequest(
            request_id="target-suggest-01",
            source_request_id="source-map-01",
            suggested_by="local-agent",
        )

        first = suggest_target(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            now=self._fixed_now,
        )
        second = suggest_target(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            now=self._fixed_now,
        )

        self.assertIsInstance(first, TargetSuggestResult)
        self.assertIsInstance(second, TargetSuggestResult)
        assert isinstance(first, TargetSuggestResult)
        assert isinstance(second, TargetSuggestResult)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(processor.calls, 1)
        self.assertTrue(first.to_dict()["requires_human_confirmation"])
        self.assertFalse(first.to_dict()["target_decision_recorded"])
        self.assertFalse(first.to_dict()["kb_created"])
        self.assertFalse((self.experiment_root / "curation-work" / "targets").exists())

    def test_cur1d_10_incomplete_target_suggestion_fails_without_target_side_effect(self) -> None:
        result = suggest_target(
            TargetSuggestRequest(
                request_id="target-suggest-invalid",
                source_request_id="source-map-01",
                suggested_by="local-agent",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=_IncompleteTargetProcessor(),
            now=self._fixed_now,
        )

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.PROCESSOR_OUTPUT_INVALID)
        self.assertFalse((self.experiment_root / "curation-work" / "targets").exists())

    def test_cur1d_11_no_target_map_is_atomic_replayable_and_does_not_write_wiki(self) -> None:
        self._no_target()
        processor = _CountingProcessor()

        first = self._build(processor=processor)
        second = self._build(processor=processor)

        self.assertIsInstance(first, MapBuildResult)
        self.assertIsInstance(second, MapBuildResult)
        assert isinstance(first, MapBuildResult)
        assert isinstance(second, MapBuildResult)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(processor.calls, 3)
        self.assertEqual(first.map_sha256, second.map_sha256)
        self.assertEqual(first.curation_map.processor_usage.call_count, 3)
        self.assertEqual(first.yaml_path.parent, first.markdown_path.parent)
        run = json.loads(first.run_record_path.read_text(encoding="utf-8"))
        self.assertEqual(run["state"], "map-ready")
        self.assertFalse(run["wiki_written"])
        self.assertEqual(
            run["token_counter_profile"],
            {
                "profile_id": "utf8-byte-upper-bound",
                "revision": 1,
                "mode": "conservative-byte-estimate",
                "model_id": None,
                "implementation": "python-stdlib",
                "implementation_version": None,
                "asset_source": None,
                "asset_sha256": None,
            },
        )
        self.assertEqual(
            run["processing_window_profile"]["grouping"],
            "contiguous-segments-within-one-top-level-heading-tree",
        )
        self.assertIn("heading_paths", run["work_units"][0])
        self.assertEqual(run["work_units"][0]["heading_tree_root"], "合成材料")
        self.assertIn("thinking", run["work_units"][0])
        self.assertIn("segment_references", run["work_units"][0])
        self.assertFalse(any(path.name == "wiki" for path in self.experiment_root.rglob("*")))

    def test_cur1d_11a_remote_processor_requires_exact_external_authorization(self) -> None:
        self._no_target()
        processor = _AuthorizedRemoteProcessor()

        missing = self._build(processor=processor)

        self.assertIsInstance(missing, CurationFailure)
        self.assertEqual(missing.error.code, CurationErrorCode.AUTHORIZATION_REQUIRED)
        self.assertEqual(processor.calls, 0)

        mismatched = self._build(
            processor=processor,
            remote_authorization=RemoteProcessingAuthorization(
                authorization_id="remote-auth-mismatch",
                source_request_id="source-map-01",
                payload_sha256="sha256:" + "0" * 64,
                allowed_range=ByteRange(0, len(self.body)),
                provider_profile="test-remote-provider",
                model_id="test-model-v1",
                authorized_by="local-user",
                authorized_at="2026-10-21T01:02:03.004Z",
            ),
        )

        self.assertIsInstance(mismatched, CurationFailure)
        self.assertEqual(
            mismatched.error.code,
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH,
        )
        self.assertEqual(processor.calls, 0)

        authorization = RemoteProcessingAuthorization(
            authorization_id="remote-auth-01",
            source_request_id="source-map-01",
            payload_sha256=self.prepared.run.source.payload_sha256,
            allowed_range=ByteRange(0, len(self.body)),
            provider_profile="test-remote-provider",
            model_id="test-model-v1",
            authorized_by="local-user",
            authorized_at="2026-10-21T01:02:03.004Z",
        )
        unbound_counter = self._build(
            processor=processor,
            remote_authorization=authorization,
        )
        mismatched_counter = self._build(
            processor=processor,
            remote_authorization=authorization,
            token_counter=Utf8ByteUpperBoundTokenCounter(
                model_id="different-model"
            ),
        )

        self.assertIsInstance(unbound_counter, CurationFailure)
        self.assertIsInstance(mismatched_counter, CurationFailure)
        self.assertEqual(
            unbound_counter.error.code,
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
        )
        self.assertEqual(
            mismatched_counter.error.code,
            CurationErrorCode.PROCESSOR_OUTPUT_INVALID,
        )
        self.assertEqual(processor.calls, 0)

        accepted = self._build(
            processor=processor,
            remote_authorization=authorization,
            token_counter=Utf8ByteUpperBoundTokenCounter(
                model_id="test-model-v1"
            ),
        )

        self.assertIsInstance(accepted, MapBuildResult)
        assert isinstance(accepted, MapBuildResult)
        run = json.loads(accepted.run_record_path.read_text(encoding="utf-8"))
        self.assertEqual(
            run["remote_authorization"]["authorization_id"],
            "remote-auth-01",
        )

    def test_cur1d_r1v_04_target_suggestion_and_map_share_one_budget(self) -> None:
        processor = _AuthorizedRemoteProcessor()
        counter = Utf8ByteUpperBoundTokenCounter(model_id="test-model-v1")
        authorization = RemoteProcessingAuthorization(
            authorization_id="remote-auth-shared-budget",
            source_request_id="source-map-01",
            payload_sha256=self.prepared.run.source.payload_sha256,
            allowed_range=ByteRange(0, len(self.body)),
            provider_profile="test-remote-provider",
            model_id="test-model-v1",
            authorized_by="local-user",
            authorized_at="2026-10-21T01:02:03.004Z",
        )
        limits = ProcessingBudgetLimits(
            max_first_work_units=3,
            max_http_attempts=4,
            max_retry_attempts=1,
            max_input_tokens=100_000,
            max_visible_output_tokens=20_000,
            max_reasoning_tokens=20_000,
            max_cost_microusd=2_000_000,
            input_microusd_per_million=300_000,
            output_microusd_per_million=1_200_000,
        )
        suggestion = suggest_target(
            TargetSuggestRequest(
                request_id="r1v-budget-suggestion",
                source_request_id="source-map-01",
                suggested_by="local-agent",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            budget_limits=limits,
            now=self._fixed_now,
        )
        self.assertIsInstance(suggestion, TargetSuggestResult)
        assert isinstance(suggestion, TargetSuggestResult)
        target = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="no-target",
                decided_by="local-user",
                suggestion_choice=suggestion.suggestion_choice,
                suggestion_rationale=suggestion.suggestion_rationale,
                suggested_by=suggestion.suggested_by,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(target, TargetDecideResult)

        unlinked = self._build(
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            budget_limits=limits,
        )
        self.assertIsInstance(unlinked, CurationFailure)
        self.assertEqual(
            unlinked.error.code,
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH,
        )
        self.assertEqual(processor.calls, 1)

        linked = build_map(
            MapBuildRequest(
                request_id="map-build-shared-budget",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                target_suggestion_request_id="r1v-budget-suggestion",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            budget_limits=limits,
            now=self._fixed_now,
        )

        self.assertIsInstance(linked, CurationFailure)
        self.assertEqual(linked.error.code, CurationErrorCode.BUDGET_EXHAUSTED)
        self.assertEqual(processor.calls, 3)

    def test_cur1d_r1v_05_tampered_suggestion_budget_is_rejected_before_map_calls(self) -> None:
        processor = _MeteredAuthorizedRemoteProcessor()
        counter = Utf8ByteUpperBoundTokenCounter(model_id="test-model-v1")
        authorization = RemoteProcessingAuthorization(
            authorization_id="remote-auth-tamper-budget",
            source_request_id="source-map-01",
            payload_sha256=self.prepared.run.source.payload_sha256,
            allowed_range=ByteRange(0, len(self.body)),
            provider_profile="test-remote-provider",
            model_id="test-model-v1",
            authorized_by="local-user",
            authorized_at="2026-10-21T01:02:03.004Z",
        )
        suggestion = suggest_target(
            TargetSuggestRequest(
                request_id="r1v-tampered-suggestion",
                source_request_id="source-map-01",
                suggested_by="local-agent",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            now=self._fixed_now,
        )
        self.assertIsInstance(suggestion, TargetSuggestResult)
        assert isinstance(suggestion, TargetSuggestResult)
        target = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="no-target",
                decided_by="local-user",
                suggestion_choice=suggestion.suggestion_choice,
                suggestion_rationale=suggestion.suggestion_rationale,
                suggested_by=suggestion.suggested_by,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(target, TargetDecideResult)

        value = json.loads(suggestion.result_path.read_text(encoding="utf-8"))
        value["usage"]["input_tokens"] = 0
        value["usage"]["visible_output_tokens"] = 0
        value["budget"]["input_tokens"] = 0
        value["budget"]["visible_output_tokens"] = 0
        value["budget"]["cost_microusd"] = 0
        suggestion.result_path.write_bytes(
            (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        )

        result = build_map(
            MapBuildRequest(
                request_id="map-build-tampered-suggestion",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                target_suggestion_request_id="r1v-tampered-suggestion",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            now=self._fixed_now,
        )

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(
            result.error.code,
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH,
        )
        self.assertEqual(processor.calls, 1)

    def test_cur1d_r1v_06_clean_checkout_rebuilds_remote_suggestion_map(self) -> None:
        processor = _AuthorizedRemoteProcessor()
        counter = Utf8ByteUpperBoundTokenCounter(model_id="test-model-v1")
        authorization = RemoteProcessingAuthorization(
            authorization_id="remote-auth-clean-rebuild",
            source_request_id="source-map-01",
            payload_sha256=self.prepared.run.source.payload_sha256,
            allowed_range=ByteRange(0, len(self.body)),
            provider_profile="test-remote-provider",
            model_id="test-model-v1",
            authorized_by="local-user",
            authorized_at="2026-10-21T01:02:03.004Z",
        )
        suggestion = suggest_target(
            TargetSuggestRequest(
                request_id="r1v-clean-suggestion",
                source_request_id="source-map-01",
                suggested_by="local-agent",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            now=self._fixed_now,
        )
        self.assertIsInstance(suggestion, TargetSuggestResult)
        assert isinstance(suggestion, TargetSuggestResult)
        kb_parent = self.experiment_root / "kb-root"
        kb_parent.mkdir(parents=True)
        root_policy = KnowledgeBaseRootPolicy(
            policy_id="test-kb-root",
            revision=1,
            allowed_parents=(kb_parent,),
        )
        target = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="new-kb",
                decided_by="local-user",
                kb_parent=kb_parent,
                suggestion_choice=suggestion.suggestion_choice,
                suggestion_rationale=suggestion.suggestion_rationale,
                suggested_by=suggestion.suggested_by,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            root_policy=root_policy,
            git=_map_test_git(kb_parent),
            now=self._fixed_now,
        )
        self.assertIsInstance(target, TargetDecideResult)
        assert isinstance(target, TargetDecideResult)
        assert target.storage_name is not None
        repository = kb_parent / target.storage_name
        request = MapBuildRequest(
            request_id="map-build-remote-clean",
            source_request_id="source-map-01",
            target_decision_request_id="target-map-01",
            kb_parent=kb_parent,
            target_suggestion_request_id="r1v-clean-suggestion",
        )
        built = build_map(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=processor,
            remote_authorization=authorization,
            token_counter=counter,
            now=self._fixed_now,
        )
        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)

        shutil.rmtree(
            repository
            / ".knowledgeflow"
            / "transactions"
            / "map-map-build-remote-clean"
        )
        (
            repository
            / ".knowledgeflow"
            / "receipts"
            / "map-map-build-remote-clean.json"
        ).unlink()
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-remote-clean"
        )
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "target-suggestion-r1v-clean-suggestion"
        )
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "target-suggestions"
            / "r1v-clean-suggestion"
        )

        recovery_processor = _AuthorizedRemoteProcessor()
        recovered = build_map(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            processor=recovery_processor,
            remote_authorization=authorization,
            token_counter=counter,
            now=self._fixed_now,
        )

        self.assertIsInstance(recovered, MapBuildResult)
        assert isinstance(recovered, MapBuildResult)
        self.assertTrue(recovered.replayed)
        self.assertEqual(recovery_processor.calls, 0)
        self.assertEqual(recovered.result_commit, built.result_commit)

    def test_cur1d_11b_replayed_unit_budget_cannot_be_reduced(self) -> None:
        self._no_target()
        processor = _CountingProcessor()
        built = self._build(processor=processor)
        self.assertIsInstance(built, MapBuildResult)
        calls = processor.calls
        unit_path = (
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-01"
            / "unit-l1-001.json"
        )
        unit = json.loads(unit_path.read_text(encoding="utf-8"))
        unit["budget_after"]["http_attempts"] = 0
        unit_path.write_text(
            json.dumps(unit, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

        replay = self._build(processor=processor)

        self.assertIsInstance(replay, CurationFailure)
        self.assertEqual(replay.error.code, CurationErrorCode.PROCESSOR_OUTPUT_INVALID)
        self.assertEqual(processor.calls, calls)

    def test_cur1d_11c_reserved_attempt_without_result_is_never_resent(self) -> None:
        self._no_target()
        interrupted = _InterruptingProcessor()

        with self.assertRaises(KeyboardInterrupt):
            self._build(processor=interrupted)

        transaction = (
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-01"
        )
        reservation = transaction / "attempt-l1-001-01-reserved.json"
        result_path = transaction / "attempt-l1-001-01-result.json"
        self.assertTrue(reservation.is_file())
        self.assertFalse(result_path.exists())

        replacement = _CountingProcessor()
        recovered = self._build(processor=replacement)
        replayed = self._build(processor=replacement)

        self.assertIsInstance(recovered, CurationFailure)
        self.assertIsInstance(replayed, CurationFailure)
        self.assertEqual(replacement.calls, 0)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["unknown_usage"])
        self.assertTrue(result["recovered_after_interruption"])
        self.assertEqual(result["budget_after"]["http_attempts"], 1)

    def test_cur1d_11d_durable_success_is_replayed_without_duplicate_call(self) -> None:
        self._no_target()
        first_processor = _CountingProcessor()
        durability = _FailFirstUnitRecordDurability()

        failed = self._build(
            processor=first_processor,
            durability=durability,
        )

        self.assertIsInstance(failed, CurationFailure)
        self.assertEqual(first_processor.calls, 1)
        transaction = (
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-01"
        )
        self.assertTrue((transaction / "attempt-l1-001-01-result.json").is_file())
        self.assertFalse((transaction / "unit-l1-001.json").exists())

        replay_processor = _CountingProcessor()
        completed = self._build(
            processor=replay_processor,
            durability=durability,
        )

        self.assertIsInstance(completed, MapBuildResult)
        self.assertEqual(replay_processor.calls, 2)
        unit = json.loads(
            (transaction / "unit-l1-001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(unit["attempts"][0]["status"], "succeeded")

    def test_cur1d_11e_terminal_unknown_attempt_is_not_resent(self) -> None:
        self._no_target()
        failing = _PostSendUnknownProcessor()

        first = self._build(processor=failing)

        self.assertIsInstance(first, CurationFailure)
        self.assertEqual(failing.calls, 1)
        replacement = _CountingProcessor()
        replay = self._build(processor=replacement)

        self.assertIsInstance(replay, CurationFailure)
        self.assertEqual(replacement.calls, 0)

    def test_cur1d_11f_durable_retry_result_resumes_at_next_attempt(self) -> None:
        self._no_target()
        first_processor = _PreSendRetryProcessor()

        with self.assertRaises(KeyboardInterrupt):
            self._build(
                processor=first_processor,
                sleeper=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
            )

        self.assertEqual(first_processor.calls, 1)
        replay_processor = _CountingProcessor()
        completed = self._build(
            processor=replay_processor,
            sleeper=lambda _seconds: None,
        )

        self.assertIsInstance(completed, MapBuildResult)
        self.assertEqual(replay_processor.calls, 3)
        transaction = (
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-01"
        )
        unit = json.loads(
            (transaction / "unit-l1-001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["status"] for item in unit["attempts"]],
            ["failed", "succeeded"],
        )
        self.assertEqual(unit["budget_after"]["first_work_units"], 1)
        self.assertEqual(unit["budget_after"]["http_attempts"], 2)
        self.assertEqual(completed.curation_map.processor_usage.call_count, 4)

    def test_cur1d_12_user_modification_creates_immutable_v2(self) -> None:
        self._no_target()
        built = self._build()
        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)
        original_yaml = built.yaml_path.read_bytes()
        selected = built.curation_map.candidates[0]

        decided = decide_map(
            MapDecideRequest(
                request_id="map-decision-01",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(
                    CandidateDecision(
                        candidate_id=selected.candidate_id,
                        action="modify",
                        replacement_text="由用户修订并保留原始证据绑定的候选。",
                    ),
                ),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(decided, MapDecisionResult)
        assert isinstance(decided, MapDecisionResult)
        self.assertEqual(built.yaml_path.read_bytes(), original_yaml)
        self.assertEqual(decided.revised_map.map_version, 2)
        revised = next(
            item
            for item in decided.revised_map.candidates
            if item.supersedes == selected.candidate_id
        )
        self.assertEqual(revised.provenance, "user-revision")
        self.assertEqual(revised.summary, "由用户修订并保留原始证据绑定的候选。")
        revised_path = built.yaml_path.parent.parent / "v0002" / "map.yaml"
        self.assertTrue(revised_path.is_file())
        revised_bytes = revised_path.read_bytes()

        conflict = decide_map(
            MapDecideRequest(
                request_id="map-decision-conflict",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(
                    CandidateDecision(
                        candidate_id=selected.candidate_id,
                        action="modify",
                        replacement_text="另一份相互冲突的 v2 文本。",
                    ),
                ),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(conflict, CurationFailure)
        self.assertEqual(conflict.error.code, CurationErrorCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(revised_path.read_bytes(), revised_bytes)

    def test_cur1d_13_old_candidate_decision_cannot_close_revised_map(self) -> None:
        self._no_target()
        built = self._build()
        assert isinstance(built, MapBuildResult)
        selected = built.curation_map.candidates[0]
        revision = decide_map(
            MapDecideRequest(
                request_id="map-revise-01",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(CandidateDecision(selected.candidate_id, "modify", "修订文本。"),),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        assert isinstance(revision, MapDecisionResult)

        stale = close_map(
            MapDecideRequest(
                request_id="map-close-stale",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=2,
                outcome="map-closed",
                decided_by="local-user",
                decisions=tuple(
                    CandidateDecision(item.candidate_id, "accept")
                    for item in built.curation_map.candidates
                ),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(stale, CurationFailure)
        self.assertEqual(stale.error.code, CurationErrorCode.INVALID_INPUT)

    def test_cur1d_14_map_close_decides_every_v2_candidate_without_wiki_write(self) -> None:
        self._no_target()
        built = self._build()
        assert isinstance(built, MapBuildResult)
        selected = built.curation_map.candidates[0]
        revision = decide_map(
            MapDecideRequest(
                request_id="map-revise-close",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(CandidateDecision(selected.candidate_id, "modify", "确认后的替代文本。"),),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        assert isinstance(revision, MapDecisionResult)
        assert revision.revised_map is not None

        close_request = MapDecideRequest(
            request_id="map-close-02",
            source_request_id="source-map-01",
            target_decision_request_id="target-map-01",
            map_id=built.curation_map.map_id,
            map_version=2,
            outcome="map-closed",
            decided_by="local-user",
            decisions=tuple(
                CandidateDecision(item.candidate_id, "accept")
                for item in revision.revised_map.candidates
            ),
        )
        closed = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        replayed = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(closed, MapDecisionResult)
        self.assertIsInstance(replayed, MapDecisionResult)
        self.assertEqual(closed.state, "map-closed")
        self.assertFalse(closed.replayed)
        self.assertTrue(replayed.replayed)
        self.assertFalse(closed.to_dict()["wiki_written"])

    def test_cur1d_15_tampered_markdown_blocks_decision(self) -> None:
        self._no_target()
        built = self._build()
        assert isinstance(built, MapBuildResult)
        built.markdown_path.write_text("tampered\n", encoding="utf-8")

        result = decide_map(
            MapDecideRequest(
                request_id="tampered-map-decision",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="deferred",
                decided_by="local-user",
                decisions=(CandidateDecision(built.curation_map.candidates[0].candidate_id, "defer"),),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.INVALID_INPUT)

    def test_cur1d_16_invalid_processor_evidence_fails_before_map_publish(self) -> None:
        self._no_target()
        result = self._build(processor=_InvalidEvidenceProcessor())

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.PROCESSOR_OUTPUT_INVALID)
        maps = tuple(self.experiment_root.rglob("map.yaml"))
        self.assertEqual(maps, ())

    def test_cur1d_17_budget_exhaustion_preserves_units_but_publishes_no_map(self) -> None:
        self._no_target()
        limits = ProcessingBudgetLimits(
            max_first_work_units=1,
            max_http_attempts=1,
            max_input_tokens=1_000_000,
            max_visible_output_tokens=20_000,
            max_reasoning_tokens=20_000,
            max_cost_microusd=2_000_000,
            input_microusd_per_million=300_000,
            output_microusd_per_million=1_200_000,
        )

        result = self._build(budget_limits=limits)

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.BUDGET_EXHAUSTED)
        self.assertEqual(tuple(self.experiment_root.rglob("map.yaml")), ())
        self.assertTrue(
            (
                self.experiment_root
                / "curation-work"
                / "map-transactions"
                / "map-build-01"
                / "unit-l1-001.json"
            ).is_file()
        )
        stop_records = tuple(
            (
                self.experiment_root
                / "curation-work"
                / "map-transactions"
                / "map-build-01"
            ).glob("stop-*.json")
        )
        self.assertEqual(len(stop_records), 1)
        stop = json.loads(stop_records[0].read_text(encoding="utf-8"))
        self.assertEqual(stop["error_code"], "budget_exhausted")
        self.assertFalse(stop["map_published"])
        self.assertEqual({item["status"] for item in stop["scope"]}, {"processed"})

    def test_cur1d_18_publish_fault_does_not_leave_discoverable_map(self) -> None:
        self._no_target()

        result = self._build(durability=_FailMapPublishDurability())

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.ATOMIC_PUBLISH_FAILED)
        self.assertEqual(tuple(self.experiment_root.rglob("map.yaml")), ())

    def test_cur1d_19_target_map_uses_proposals_checkpoint_and_leaves_wiki_empty(self) -> None:
        kb_parent = self.experiment_root / "kb-root"
        kb_parent.mkdir(parents=True)
        root_policy = KnowledgeBaseRootPolicy(
            policy_id="test-kb-root",
            revision=1,
            allowed_parents=(kb_parent,),
        )
        target = target_decide(
            TargetDecideRequest(
                decision_request_id="target-map-01",
                source_request_id="source-map-01",
                choice="new-kb",
                decided_by="local-user",
                kb_parent=kb_parent,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
            root_policy=root_policy,
            git=_map_test_git(kb_parent),
            now=self._fixed_now,
        )
        self.assertIsInstance(target, TargetDecideResult)
        assert isinstance(target, TargetDecideResult)

        built = self._build(kb_parent=kb_parent)

        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)
        self.assertIsNotNone(built.result_commit)
        self.assertIn("proposals", built.yaml_path.parts)
        repository = kb_parent / target.storage_name
        wiki_files = tuple(path for path in (repository / "wiki").rglob("*") if path.is_file())
        self.assertEqual([path.name for path in wiki_files], [".gitkeep"])
        close_request = MapDecideRequest(
            request_id="target-map-close",
            source_request_id="source-map-01",
            target_decision_request_id="target-map-01",
            map_id=built.curation_map.map_id,
            map_version=1,
            outcome="map-closed",
            decided_by="local-user",
            decisions=tuple(
                CandidateDecision(item.candidate_id, "accept")
                for item in built.curation_map.candidates
            ),
            kb_parent=kb_parent,
        )

        first_close = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        second_close = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(first_close, MapDecisionResult)
        self.assertIsInstance(second_close, MapDecisionResult)
        assert isinstance(first_close, MapDecisionResult)
        assert isinstance(second_close, MapDecisionResult)
        self.assertFalse(first_close.replayed)
        self.assertTrue(second_close.replayed)
        self.assertIsNotNone(first_close.result_commit)
        wiki_files = tuple(path for path in (repository / "wiki").rglob("*") if path.is_file())
        self.assertEqual([path.name for path in wiki_files], [".gitkeep"])

    def test_cur1d_r1c_01_target_decision_sidecar_and_receipt_close_one_checkpoint(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        built = self._build(kb_parent=kb_parent)
        self.assertIsInstance(built, MapBuildResult)
        assert isinstance(built, MapBuildResult)
        closed = close_map(
            MapDecideRequest(
                request_id="r1c-close-sidecar",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="map-closed",
                decided_by="local-user",
                decisions=tuple(
                    CandidateDecision(item.candidate_id, "accept")
                    for item in built.curation_map.candidates
                ),
                kb_parent=kb_parent,
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(closed, MapDecisionResult)
        assert isinstance(closed, MapDecisionResult)
        self.assertEqual(closed.run_record_path.name, "v0001.run.json")
        sidecar = json.loads(closed.run_record_path.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["decision_sha256"], closed.decision_sha256)
        self.assertEqual(sidecar["map_binding"]["map_sha256"], built.map_sha256)
        self.assertEqual(sidecar["base_commit"], built.result_commit)
        self.assertEqual(
            sidecar["target_binding"]["kb_id"],
            built.curation_map.target_binding.kb_id,
        )
        self.assertNotIn("result_commit", sidecar)
        changed = ManagedGit().changed_paths(
            repository,
            built.result_commit,
            closed.result_commit,
        )
        self.assertEqual(
            changed,
            frozenset(
                {
                    closed.decision_path.relative_to(repository).as_posix(),
                    closed.run_record_path.relative_to(repository).as_posix(),
                }
            ),
        )
        self.assertTrue(
            (
                repository
                / ".knowledgeflow"
                / "receipts"
                / "decision-r1c-close-sidecar.json"
            ).is_file()
        )
        self.assertFalse(
            (
                self.experiment_root
                / "curation-work"
                / ".map-receipts"
                / "decision-r1c-close-sidecar.json"
            ).exists()
        )

    def test_cur1d_r1c_02_no_target_revision_publishes_decision_pair_and_map_together(self) -> None:
        self._no_target()
        built = self._build()
        assert isinstance(built, MapBuildResult)
        selected = built.curation_map.candidates[0]
        revised = decide_map(
            MapDecideRequest(
                request_id="r1c-no-target-revision",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=built.curation_map.map_id,
                map_version=1,
                outcome="revision-requested",
                decided_by="local-user",
                decisions=(
                    CandidateDecision(selected.candidate_id, "modify", "R1C 用户修订。"),
                ),
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(revised, MapDecisionResult)
        assert isinstance(revised, MapDecisionResult)
        self.assertTrue(revised.decision_path.is_file())
        self.assertTrue(revised.run_record_path.is_file())
        self.assertIsNotNone(revised.revised_map)
        transaction = (
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "decision-r1c-no-target-revision"
        )
        publish = json.loads((transaction / "publish.json").read_text(encoding="utf-8"))
        published_paths = {item["path"] for item in publish["files"]}
        self.assertIn(
            f"decisions/{revised.decision.decision_set_id}/v0001.yaml",
            published_paths,
        )
        self.assertIn(
            f"decisions/{revised.decision.decision_set_id}/v0001.run.json",
            published_paths,
        )
        self.assertIn("v0002/map.yaml", published_paths)
        self.assertTrue((transaction / "complete.json").is_file())
        self.assertTrue(
            (
                self.experiment_root
                / "curation-work"
                / ".map-receipts"
                / "decision-r1c-no-target-revision.json"
            ).is_file()
        )

    def test_cur1d_r1c_03_commit_without_receipt_blocks_new_work_then_recovers(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        durability = _FailOnceMapReceiptDurability()
        failed = self._build(kb_parent=kb_parent, durability=durability)

        self.assertIsInstance(failed, CurationFailure)
        self.assertEqual(failed.error.code, CurationErrorCode.ATOMIC_PUBLISH_FAILED)
        identity = json.loads(
            (
                self.experiment_root
                / "curation-work"
                / "map-transactions"
                / "map-build-01"
                / "identity.json"
            ).read_text(encoding="utf-8")
        )
        map_path = (
            repository
            / "proposals"
            / "curation-maps"
            / identity["map_id"]
            / "v0001"
            / "map.yaml"
        )
        published_map = load_curation_map(map_path.read_bytes())
        blocked = close_map(
            MapDecideRequest(
                request_id="r1c-blocked-close",
                source_request_id="source-map-01",
                target_decision_request_id="target-map-01",
                map_id=published_map.map_id,
                map_version=1,
                outcome="map-closed",
                decided_by="local-user",
                decisions=tuple(
                    CandidateDecision(item.candidate_id, "accept")
                    for item in published_map.candidates
                ),
                kb_parent=kb_parent,
            ),
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        self.assertIsInstance(blocked, CurationFailure)
        self.assertEqual(blocked.error.code, CurationErrorCode.RECOVERY_REQUIRED)

        recovered = self._build(kb_parent=kb_parent, durability=durability)

        self.assertIsInstance(recovered, MapBuildResult)
        assert isinstance(recovered, MapBuildResult)
        self.assertTrue(recovered.replayed)
        target_transaction = (
            repository
            / ".knowledgeflow"
            / "transactions"
            / "map-map-build-01"
        )
        self.assertTrue((target_transaction / "complete.json").is_file())
        self.assertTrue(
            (
                repository
                / ".knowledgeflow"
                / "receipts"
                / "map-map-build-01.json"
            ).is_file()
        )

    def test_cur1d_r1v_02_pending_target_transaction_blocks_before_processing(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        pending = (
            repository
            / ".knowledgeflow"
            / "transactions"
            / "decision-other-pending"
        )
        pending.mkdir()
        (pending / "publish.json").write_text("{}\n", encoding="utf-8")
        processor = _CountingProcessor()

        result = self._build(kb_parent=kb_parent, processor=processor)

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.RECOVERY_REQUIRED)
        self.assertEqual(processor.calls, 0)

    def test_cur1d_r1v_03_lost_local_journal_never_reprocesses_pending_publish(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        pending = (
            repository
            / ".knowledgeflow"
            / "transactions"
            / "map-map-build-01"
        )
        pending.mkdir()
        (pending / "publish.json").write_text("{}\n", encoding="utf-8")
        processor = _CountingProcessor()

        result = self._build(kb_parent=kb_parent, processor=processor)

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.RECOVERY_REQUIRED)
        self.assertEqual(processor.calls, 0)

    def test_cur1d_r1c_04_clean_checkout_rebuilds_map_and_decision_receipts(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        built = self._build(kb_parent=kb_parent)
        assert isinstance(built, MapBuildResult)
        close_request = MapDecideRequest(
            request_id="r1c-clean-close",
            source_request_id="source-map-01",
            target_decision_request_id="target-map-01",
            map_id=built.curation_map.map_id,
            map_version=1,
            outcome="map-closed",
            decided_by="local-user",
            decisions=tuple(
                CandidateDecision(item.candidate_id, "accept")
                for item in built.curation_map.candidates
            ),
            kb_parent=kb_parent,
        )
        closed = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        assert isinstance(closed, MapDecisionResult)
        transactions = repository / ".knowledgeflow" / "transactions"
        receipts = repository / ".knowledgeflow" / "receipts"
        shutil.rmtree(transactions / "map-map-build-01")
        shutil.rmtree(transactions / "decision-r1c-clean-close")
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "map-build-01"
        )
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "decision-r1c-clean-close"
        )
        (receipts / "map-map-build-01.json").unlink()
        (receipts / "decision-r1c-clean-close.json").unlink()

        recovery_processor = _CountingProcessor()
        rebuilt_map = self._build(
            kb_parent=kb_parent,
            processor=recovery_processor,
        )
        rebuilt_decision = close_map(
            close_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(rebuilt_map, MapBuildResult)
        self.assertIsInstance(rebuilt_decision, MapDecisionResult)
        assert isinstance(rebuilt_map, MapBuildResult)
        assert isinstance(rebuilt_decision, MapDecisionResult)
        self.assertTrue(rebuilt_map.replayed)
        self.assertTrue(rebuilt_decision.replayed)
        self.assertEqual(recovery_processor.calls, 0)
        self.assertEqual(rebuilt_map.result_commit, built.result_commit)
        self.assertEqual(rebuilt_decision.result_commit, closed.result_commit)
        self.assertTrue((receipts / "map-map-build-01.json").is_file())
        self.assertTrue((receipts / "decision-r1c-clean-close.json").is_file())

    def test_cur1d_r1v_01_clean_checkout_rebuilds_modified_decision_receipt(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        built = self._build(kb_parent=kb_parent)
        assert isinstance(built, MapBuildResult)
        selected = built.curation_map.candidates[0]
        decision_request = MapDecideRequest(
            request_id="r1v-clean-revision",
            source_request_id="source-map-01",
            target_decision_request_id="target-map-01",
            map_id=built.curation_map.map_id,
            map_version=1,
            outcome="revision-requested",
            decided_by="local-user",
            decisions=(
                CandidateDecision(
                    selected.candidate_id,
                    "modify",
                    "R1V clean-checkout user revision.",
                ),
            ),
            kb_parent=kb_parent,
        )
        first = decide_map(
            decision_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )
        self.assertIsInstance(first, MapDecisionResult)
        assert isinstance(first, MapDecisionResult)
        self.assertIsNotNone(first.revised_map)

        shutil.rmtree(
            repository
            / ".knowledgeflow"
            / "transactions"
            / "decision-r1v-clean-revision"
        )
        shutil.rmtree(
            self.experiment_root
            / "curation-work"
            / "map-transactions"
            / "decision-r1v-clean-revision"
        )
        receipt = (
            repository
            / ".knowledgeflow"
            / "receipts"
            / "decision-r1v-clean-revision.json"
        )
        receipt.unlink()

        recovered = decide_map(
            decision_request,
            experiment_root=self.experiment_root,
            now=self._fixed_now,
        )

        self.assertIsInstance(recovered, MapDecisionResult)
        assert isinstance(recovered, MapDecisionResult)
        self.assertTrue(recovered.replayed)
        self.assertEqual(recovered.result_commit, first.result_commit)
        self.assertEqual(recovered.revised_map, first.revised_map)
        self.assertTrue(receipt.is_file())

    def test_cur1d_r1c_05_unknown_target_path_overlap_is_rejected(self) -> None:
        kb_parent, target, repository = self._target_kb()
        first = self._build(
            kb_parent=kb_parent,
            durability=_FailOnceMapPublishManifestDurability(),
        )
        self.assertIsInstance(first, CurationFailure)
        identity = json.loads(
            (
                self.experiment_root
                / "curation-work"
                / "map-transactions"
                / "map-build-01"
                / "identity.json"
            ).read_text(encoding="utf-8")
        )
        overlap = (
            repository
            / "proposals"
            / "curation-maps"
            / identity["map_id"]
            / "v0001"
            / "map.yaml"
        )
        overlap.parent.mkdir(parents=True)
        overlap.write_bytes(b"user-owned-overlap\n")

        result = self._build(kb_parent=kb_parent)

        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(result.error.code, CurationErrorCode.TARGET_CONFLICT)
        self.assertEqual(overlap.read_bytes(), b"user-owned-overlap\n")
        self.assertEqual(ManagedGit().current_commit(repository), target.result_commit)

    def test_cur1d_r1c_06_unrelated_staged_and_unstaged_changes_are_preserved(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        user_note = repository / "user-note.md"
        user_note.write_text("staged version\n", encoding="utf-8")
        subprocess.run(
            ("git", "add", "--", "user-note.md"),
            cwd=repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        user_note.write_text("unstaged version\n", encoding="utf-8")

        built = self._build(kb_parent=kb_parent)

        self.assertIsInstance(built, MapBuildResult)
        staged = subprocess.run(
            ("git", "diff", "--cached", "--name-only"),
            cwd=repository,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode("utf-8").splitlines()
        unstaged = subprocess.run(
            ("git", "diff", "--name-only"),
            cwd=repository,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode("utf-8").splitlines()
        self.assertIn("user-note.md", staged)
        self.assertIn("user-note.md", unstaged)
        self.assertEqual(user_note.read_text(encoding="utf-8"), "unstaged version\n")

    def test_cur1d_r1c_07_receipt_rebuild_rejects_modified_checkpoint_bytes(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        built = self._build(kb_parent=kb_parent)
        assert isinstance(built, MapBuildResult)
        shutil.rmtree(
            repository
            / ".knowledgeflow"
            / "transactions"
            / "map-map-build-01"
        )
        (
            repository
            / ".knowledgeflow"
            / "receipts"
            / "map-map-build-01.json"
        ).unlink()
        built.markdown_path.write_text("unknown later change\n", encoding="utf-8")

        replay = self._build(kb_parent=kb_parent)

        self.assertIsInstance(replay, CurationFailure)
        self.assertEqual(replay.error.code, CurationErrorCode.TARGET_CONFLICT)
        self.assertEqual(
            built.markdown_path.read_text(encoding="utf-8"),
            "unknown later change\n",
        )

    def test_cur1d_r1c_08_concurrent_decisions_serialize_on_one_kb_lock(self) -> None:
        kb_parent, _target, repository = self._target_kb()
        built = self._build(kb_parent=kb_parent)
        assert isinstance(built, MapBuildResult)

        def close_with(request_id: str) -> MapDecisionResult | CurationFailure:
            return close_map(
                MapDecideRequest(
                    request_id=request_id,
                    source_request_id="source-map-01",
                    target_decision_request_id="target-map-01",
                    map_id=built.curation_map.map_id,
                    map_version=1,
                    outcome="map-closed",
                    decided_by="local-user",
                    decisions=tuple(
                        CandidateDecision(item.candidate_id, "accept")
                        for item in built.curation_map.candidates
                    ),
                    kb_parent=kb_parent,
                ),
                experiment_root=self.experiment_root,
                now=self._fixed_now,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(close_with, "r1c-concurrent-a")
            second_future = executor.submit(close_with, "r1c-concurrent-b")
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)

        self.assertIsInstance(first, MapDecisionResult)
        self.assertIsInstance(second, MapDecisionResult)
        assert isinstance(first, MapDecisionResult)
        assert isinstance(second, MapDecisionResult)
        self.assertNotEqual(first.result_commit, second.result_commit)
        current = ManagedGit().current_commit(repository)
        commits = {first.result_commit, second.result_commit}
        self.assertIn(current, commits)
        ancestor = next(item for item in commits if item != current)
        self.assertTrue(ManagedGit().is_ancestor(repository, ancestor, current))

    def test_cur1d_20_cli_suggest_build_and_close_emit_json_receipts(self) -> None:
        suggestion_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "target",
                "suggest",
                "--request-id",
                "cli-target-suggest",
                "--source-request-id",
                "source-map-01",
                "--suggested-by",
                "local-agent",
                "--processor",
                "deterministic-test",
            ),
            stdout=suggestion_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        suggestion_stdout.seek(0)
        self.assertEqual(json.loads(suggestion_stdout.read())["operation"], "target.suggest")

        self._no_target()
        build_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "map",
                "build",
                "--request-id",
                "cli-map-build",
                "--source-request-id",
                "source-map-01",
                "--target-decision-request-id",
                "target-map-01",
                "--processor",
                "deterministic-test",
            ),
            stdout=build_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        build_stdout.seek(0)
        built = json.loads(build_stdout.read())
        decisions_path = self.owned_root / "decisions.json"
        decisions_path.write_text(
            json.dumps(
                [
                    {
                        "candidate_id": item["candidate_id"],
                        "action": "accept",
                        "replacement_text": None,
                    }
                    for item in load_curation_map(
                        Path(built["map_yaml_path"]).read_bytes()
                    ).as_mapping()["candidates"]
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        close_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "map",
                "close",
                "--request-id",
                "cli-map-close",
                "--source-request-id",
                "source-map-01",
                "--target-decision-request-id",
                "target-map-01",
                "--map-id",
                built["map_id"],
                "--map-version",
                "1",
                "--decided-by",
                "local-user",
                "--decisions-file",
                str(decisions_path),
            ),
            stdout=close_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        close_stdout.seek(0)
        self.assertEqual(json.loads(close_stdout.read())["state"], "map-closed")

    def test_cur1d_r1b_05_remote_cli_never_silently_selects_a_tokenizer(self) -> None:
        stdout = io.BytesIO()

        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "target",
                "suggest",
                "--request-id",
                "cli-missing-tokenizer",
                "--source-request-id",
                "source-map-01",
                "--suggested-by",
                "local-agent",
                "--processor",
                "deepseek",
                "--allow-network",
                "--remote-authorization-id",
                "remote-auth-cli",
                "--remote-authorized-by",
                "local-user",
                "--remote-authorized-at",
                "2026-10-21T01:02:03.004Z",
                "--remote-payload-sha256",
                self.prepared.run.source.payload_sha256,
                "--remote-start-byte",
                "0",
                "--remote-end-byte",
                str(len(self.body)),
            ),
            stdout=stdout,
            path_policy=self.policy,
        )

        self.assertEqual(code, 2)
        receipt = json.loads(stdout.getvalue())
        self.assertEqual(receipt["error"]["code"], "invalid_input")
        self.assertEqual(receipt["error"]["details"]["stage"], "cli-arguments")
        self.assertFalse(
            (
                self.experiment_root
                / "curation-work"
                / "target-suggestions"
                / "cli-missing-tokenizer"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()
