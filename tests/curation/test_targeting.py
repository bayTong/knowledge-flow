from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import multiprocessing
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.durability import (
    DurabilityBackend,
    DurabilityError,
    DurabilityStage,
)
from knowledgeflow_curation.cli import _run_cli
from knowledgeflow_curation.codec import (
    load_kb_manifest,
    load_raw_source_mapping,
    load_route_record,
    load_target_decision_record,
)
from knowledgeflow_curation.errors import CurationErrorCode, CurationFailure
from knowledgeflow_curation.operations import (
    SourcePrepareRequest,
    SourcePrepareResult,
    prepare_source,
)
from knowledgeflow_curation.targeting import (
    KnowledgeBaseRootPolicy,
    TargetDecideRequest,
    TargetDecideResult,
    target_decide,
)
from knowledgeflow_curation.versioning import (
    MANAGED_REF,
    TECHNICAL_AUTHOR_EMAIL,
    TECHNICAL_AUTHOR_NAME,
    ManagedGit,
    ManagedGitError,
)


class _FailReceiptDurability(DurabilityBackend):
    def write_new_file_durable(self, path, data, **kwargs):
        if "receipts" in Path(path).parts:
            raise DurabilityError(DurabilityStage.FILE_WRITE)
        return super().write_new_file_durable(path, data, **kwargs)


class _FailKbPublishDurability(DurabilityBackend):
    def commit_directory_no_replace(self, source, destination):
        if Path(destination).name == "publish-fault":
            raise DurabilityError(DurabilityStage.RENAME)
        return super().commit_directory_no_replace(source, destination)


class _FailCheckpointGit(ManagedGit):
    def require_standalone_parent(self, parent: Path) -> None:
        self.check_available(parent)

    def checkpoint(self, *args, **kwargs):
        raise ManagedGitError("injected checkpoint failure")


class _TargetTestManagedGit(ManagedGit):
    """Allow valid target tests inside a repository-owned test sandbox."""

    def require_standalone_parent(self, parent: Path) -> None:
        self.check_available(parent)


def _target_test_git(parent: Path) -> ManagedGit:
    if any((candidate / ".git").exists() for candidate in (parent, *parent.parents)):
        return _TargetTestManagedGit()
    return ManagedGit()


def _concurrent_target_worker(
    owned_root: str,
    experiment_root: str,
    kb_parent: str,
    source_request_id: str,
    decision_request_id: str,
    queue,
) -> None:
    policy = PathPolicy.test_owned(Path(owned_root))
    root_policy = KnowledgeBaseRootPolicy(
        policy_id="test-kb-root",
        revision=1,
        allowed_parents=(Path(kb_parent),),
    )
    result = target_decide(
        TargetDecideRequest(
            decision_request_id=decision_request_id,
            source_request_id=source_request_id,
            choice="new-kb",
            decided_by="local-user",
            kb_parent=Path(kb_parent),
        ),
        experiment_root=Path(experiment_root),
        path_policy=policy,
        root_policy=root_policy,
        git=_target_test_git(Path(kb_parent)),
        now=lambda: datetime(
            2026,
            10,
            19,
            1,
            2,
            3,
            4000,
            tzinfo=timezone.utc,
        ),
    )
    queue.put(result.to_dict())


class TargetingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.owned_root = Path(self._temporary.name).resolve()
        self.experiment_root = self.owned_root / "experiment"
        self.kb_parent = self.experiment_root / "kb-root"
        self.kb_parent.mkdir(parents=True)
        self.path_policy = PathPolicy.test_owned(self.owned_root)
        self.root_policy = KnowledgeBaseRootPolicy(
            policy_id="test-kb-root",
            revision=1,
            allowed_parents=(self.kb_parent,),
        )
        self.body = "# 精确来源\n\n第一段。\r\n第二段。\n".encode("utf-8")
        source_path = self.owned_root / "source.md"
        source_path.write_bytes(self.body)
        prepared = prepare_source(
            SourcePrepareRequest(
                request_id="source-01",
                source_path=source_path,
                source_reference="e0-c",
                expected_sha256=hash_bytes(self.body).sha256,
                expected_byte_size=len(self.body),
                authorized_by="local-user",
                task_ids=("c-t1", "c-t4"),
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
        )
        self.assertIsInstance(prepared, SourcePrepareResult)
        self.prepared = prepared

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def _fixed_now() -> datetime:
        return datetime(2026, 10, 19, 1, 2, 3, 4000, tzinfo=timezone.utc)

    def _request(self, **changes: object) -> TargetDecideRequest:
        values: dict[str, object] = {
            "decision_request_id": "target-request-01",
            "source_request_id": "source-01",
            "choice": "new-kb",
            "decided_by": "local-user",
            "kb_parent": self.kb_parent,
            "suggestion_choice": "new-kb",
            "suggestion_rationale": "材料需要独立的 provisional 工作空间。",
            "suggested_by": "local-agent",
        }
        values.update(changes)
        return TargetDecideRequest(**values)

    def _decide(self, request: TargetDecideRequest | None = None, **kwargs: object):
        kwargs.setdefault("git", _target_test_git(self.kb_parent))
        return target_decide(
            request or self._request(),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            root_policy=self.root_policy,
            now=self._fixed_now,
            **kwargs,
        )

    def test_cur1c_01_no_target_records_decision_without_kb_or_git(self) -> None:
        request = self._request(
            choice="no-target",
            kb_parent=None,
            suggestion_choice="new-kb",
        )
        first = target_decide(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            now=self._fixed_now,
        )
        second = target_decide(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(first, TargetDecideResult)
        self.assertIsInstance(second, TargetDecideResult)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertFalse(first.to_dict()["kb_created"])
        self.assertFalse(first.to_dict()["raw_routed"])
        self.assertEqual(tuple(self.kb_parent.iterdir()), ())
        record = load_target_decision_record(
            (
                self.experiment_root
                / "curation-work"
                / "targets"
                / "target-request-01"
                / "target-decision.yaml"
            ).read_bytes()
        )
        self.assertEqual(record.decision.choice, "no-target")
        self.assertEqual(record.suggestion.choice, "new-kb")
        without_git = target_decide(
            self._request(
                decision_request_id="no-target-without-git",
                choice="no-target",
                kb_parent=None,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            git=ManagedGit(binary="definitely-missing-git-executable"),
            now=self._fixed_now,
        )
        self.assertIsInstance(without_git, TargetDecideResult)

    def test_cur1c_02_custom_kb_routes_exact_bytes_and_stays_provisional(self) -> None:
        result = self._decide(
            self._request(storage_name="model-notes", display_name="大模型应用笔记")
        )
        self.assertIsInstance(result, TargetDecideResult)
        assert isinstance(result, TargetDecideResult)
        repository = self.kb_parent / "model-notes"
        manifest = load_kb_manifest((repository / "kb.yaml").read_bytes())
        self.assertEqual(manifest.lifecycle, "provisional")
        self.assertEqual(manifest.wiki_status, "empty")
        self.assertEqual(tuple((repository / "wiki").iterdir()), (repository / "wiki" / ".gitkeep",))
        assert result.route is not None
        payload = repository / Path(result.route.payload_path)
        sidecar = repository / Path(result.route.source_mapping_path)
        route_path = repository / ".knowledgeflow" / "routes" / f"{result.route.route_id}.yaml"
        self.assertEqual(payload.read_bytes(), self.body)
        mapping = load_raw_source_mapping(sidecar.read_bytes())
        route = load_route_record(route_path.read_bytes())
        self.assertEqual(mapping.source, self.prepared.run.source)
        self.assertEqual(route.source_mapping_sha256, hash_bytes(sidecar.read_bytes()).sha256)
        self.assertTrue((repository / ".git").is_dir())
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(repository), "remote"],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout,
            b"",
        )
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(repository), "symbolic-ref", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout.decode().strip(),
            MANAGED_REF,
        )
        identity = subprocess.run(
            ["git", "-C", str(repository), "show", "-s", "--format=%an%x00%ae", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.rstrip(b"\n")
        self.assertEqual(
            identity,
            TECHNICAL_AUTHOR_NAME.encode() + b"\0" + TECHNICAL_AUTHOR_EMAIL.encode(),
        )

    def test_cur1c_03_date_names_are_sequential_and_replay_is_stable(self) -> None:
        first = self._decide()
        self.assertIsInstance(first, TargetDecideResult)
        self.assertEqual(first.storage_name, "2026-10-19-01")
        replay = self._decide()
        self.assertIsInstance(replay, TargetDecideResult)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.record, first.record)

        other_source = self.owned_root / "other.md"
        other_body = b"other source\n"
        other_source.write_bytes(other_body)
        prepared = prepare_source(
            SourcePrepareRequest(
                request_id="source-02",
                source_path=other_source,
                source_reference="e0-l",
                expected_sha256=hash_bytes(other_body).sha256,
                expected_byte_size=len(other_body),
                authorized_by="local-user",
                task_ids=("l-t1",),
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
        )
        self.assertIsInstance(prepared, SourcePrepareResult)
        second = self._decide(
            self._request(
                decision_request_id="target-request-02",
                source_request_id="source-02",
            )
        )
        self.assertIsInstance(second, TargetDecideResult)
        self.assertEqual(second.storage_name, "2026-10-19-02")

    def test_cur1c_04_request_conflict_and_unknown_storage_fail_closed(self) -> None:
        first = self._decide(self._request(storage_name="fixed-name"))
        self.assertIsInstance(first, TargetDecideResult)
        changed = self._decide(
            self._request(storage_name="fixed-name", display_name="different")
        )
        self.assertIsInstance(changed, CurationFailure)
        self.assertEqual(changed.error.code, CurationErrorCode.IDEMPOTENCY_CONFLICT)

        (self.kb_parent / "occupied").mkdir()
        occupied = self._decide(
            self._request(
                decision_request_id="target-request-02",
                storage_name="occupied",
            )
        )
        self.assertIsInstance(occupied, CurationFailure)
        self.assertEqual(occupied.error.code, CurationErrorCode.TARGET_CONFLICT)
        self.assertFalse((self.kb_parent / "occupied" / ".git").exists())

        unknown_transaction = (
            self.experiment_root
            / "curation-work"
            / "target-transactions"
            / "unknown-transaction"
        )
        unknown_transaction.mkdir()
        unowned = self._decide(
            self._request(
                decision_request_id="unknown-transaction",
                storage_name="must-not-exist",
            )
        )
        self.assertIsInstance(unowned, CurationFailure)
        self.assertEqual(unowned.error.code, CurationErrorCode.RECOVERY_REQUIRED)
        self.assertFalse((self.kb_parent / "must-not-exist").exists())

    def test_cur1c_05_outside_policy_and_missing_git_have_no_false_success(self) -> None:
        outside = self.owned_root / "outside"
        outside.mkdir()
        rejected = target_decide(
            self._request(kb_parent=outside),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            root_policy=self.root_policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(rejected, CurationFailure)
        self.assertEqual(rejected.error.code, CurationErrorCode.INVALID_INPUT)
        self.assertEqual(tuple(outside.iterdir()), ())

        unavailable = self._decide(
            self._request(
                decision_request_id="missing-git",
                storage_name="missing-git-reserved",
            ),
            git=_TargetTestManagedGit(binary="definitely-missing-git-executable"),
        )
        self.assertIsInstance(unavailable, CurationFailure)
        self.assertEqual(
            unavailable.error.code,
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
        )
        self.assertFalse((self.kb_parent / "missing-git-reserved").exists())
        reserved = self._decide(
            self._request(
                decision_request_id="missing-git-competitor",
                storage_name="missing-git-reserved",
            )
        )
        self.assertIsInstance(reserved, CurationFailure)
        self.assertEqual(reserved.error.code, CurationErrorCode.TARGET_CONFLICT)

        host_repository = self.owned_root / "host-repository"
        host_repository.mkdir()
        subprocess.run(
            ["git", "-C", str(host_repository), "init", "--quiet"],
            check=True,
        )
        nested_parent = host_repository / "kb-root"
        nested_parent.mkdir()
        nested_policy = KnowledgeBaseRootPolicy(
            policy_id="nested-kb-root",
            revision=1,
            allowed_parents=(nested_parent,),
        )
        nested = target_decide(
            self._request(
                decision_request_id="nested-repository",
                kb_parent=nested_parent,
                storage_name="nested-kb",
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
            root_policy=nested_policy,
            now=self._fixed_now,
        )
        self.assertIsInstance(nested, CurationFailure)
        self.assertEqual(nested.error.code, CurationErrorCode.TARGET_CONFLICT)
        self.assertEqual(nested.to_dict()["commit_state"], "not-committed")
        self.assertFalse((nested_parent / "nested-kb").exists())

    def test_cur1c_06_raw_tamper_and_managed_ref_drift_fail_replay(self) -> None:
        result = self._decide(self._request(storage_name="tamper-check"))
        self.assertIsInstance(result, TargetDecideResult)
        assert isinstance(result, TargetDecideResult) and result.route is not None
        repository = self.kb_parent / "tamper-check"
        owner = (
            repository
            / ".knowledgeflow"
            / "transactions"
            / "bootstrap-owner.json"
        )
        owner_bytes = owner.read_bytes()
        owner.write_bytes(b"{}\n")
        owner_replay = self._decide(self._request(storage_name="tamper-check"))
        self.assertIsInstance(owner_replay, CurationFailure)
        self.assertEqual(
            owner_replay.error.code,
            CurationErrorCode.RECOVERY_REQUIRED,
        )
        owner.write_bytes(owner_bytes)
        payload = repository / Path(result.route.payload_path)
        payload.write_bytes(b"X" + payload.read_bytes()[1:])
        replay = self._decide(self._request(storage_name="tamper-check"))
        self.assertIsInstance(replay, CurationFailure)
        self.assertEqual(replay.error.code, CurationErrorCode.RECOVERY_REQUIRED)

        corrupt_request = self._request(
            decision_request_id="corrupt-record-request",
            storage_name="corrupt-record",
        )
        corrupt = self._decide(corrupt_request)
        self.assertIsInstance(corrupt, TargetDecideResult)
        decision_path = (
            self.experiment_root
            / "curation-work"
            / "targets"
            / "corrupt-record-request"
            / "target-decision.yaml"
        )
        decision_path.write_bytes(b"not: canonical: yaml\n")
        corrupt_replay = self._decide(corrupt_request)
        self.assertIsInstance(corrupt_replay, CurationFailure)
        self.assertEqual(
            corrupt_replay.error.code,
            CurationErrorCode.RECOVERY_REQUIRED,
        )

    def test_cur1c_07_cli_target_decide_is_json_only_and_root_bounded(self) -> None:
        output = io.BytesIO()
        def target_decide_for_cli(request, **kwargs):
            return target_decide(
                request,
                git=_target_test_git(self.kb_parent),
                **kwargs,
            )

        with patch(
            "knowledgeflow_curation.cli.target_decide",
            side_effect=target_decide_for_cli,
        ):
            code = _run_cli(
                (
                    "--experiment-root",
                    str(self.experiment_root),
                    "target",
                    "decide",
                    "--decision-request-id",
                    "cli-target",
                    "--source-request-id",
                    "source-01",
                    "--choice",
                    "new-kb",
                    "--decided-by",
                    "local-user",
                    "--kb-parent",
                    str(self.kb_parent),
                    "--storage-name",
                    "cli-kb",
                ),
                stdout=output,
                path_policy=self.path_policy,
            )
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue().count(b"\n"), 1)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["operation"], "target.decide")
        self.assertEqual(receipt["lifecycle"], "provisional")
        self.assertEqual(receipt["wiki_status"], "empty")

        rejected_output = io.BytesIO()
        rejected_code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "target",
                "decide",
                "--decision-request-id",
                "cli-no-target-invalid-parent",
                "--source-request-id",
                "source-01",
                "--choice",
                "no-target",
                "--decided-by",
                "local-user",
                "--kb-parent",
                str(self.kb_parent),
            ),
            stdout=rejected_output,
            path_policy=self.path_policy,
        )
        self.assertEqual(rejected_code, 2)
        self.assertEqual(
            json.loads(rejected_output.getvalue())["error"]["code"],
            CurationErrorCode.INVALID_INPUT.value,
        )

    def test_cur1c_08_receipt_failure_recovers_without_duplicate_route(self) -> None:
        request = self._request(storage_name="receipt-recovery")
        failed = self._decide(request, durability=_FailReceiptDurability())
        self.assertIsInstance(failed, CurationFailure)
        self.assertEqual(failed.to_dict()["commit_state"], "unknown")
        repository = self.kb_parent / "receipt-recovery"
        self.assertTrue(repository.is_dir())
        first_commit = ManagedGit().current_commit(repository)

        recovered = self._decide(request)
        self.assertIsInstance(recovered, TargetDecideResult)
        assert isinstance(recovered, TargetDecideResult)
        self.assertEqual(recovered.result_commit, first_commit)
        self.assertEqual(
            len(tuple((repository / ".knowledgeflow" / "routes").glob("route_*.yaml"))),
            1,
        )
        self.assertEqual(len(tuple((repository / "raw" / "text").glob("cap_*.txt"))), 1)

    def test_cur1c_09_managed_ref_drift_is_not_reported_as_success(self) -> None:
        request = self._request(storage_name="ref-drift")
        result = self._decide(request)
        self.assertIsInstance(result, TargetDecideResult)
        assert isinstance(result, TargetDecideResult)
        repository = self.kb_parent / "ref-drift"
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "update-ref",
                MANAGED_REF,
                result.base_commit,
                result.result_commit,
            ],
            check=True,
        )
        replay = self._decide(request)
        self.assertIsInstance(replay, CurationFailure)
        self.assertEqual(replay.error.code, CurationErrorCode.RECOVERY_REQUIRED)

    def test_cur1c_10_two_processes_allocate_distinct_same_day_names(self) -> None:
        other_source = self.owned_root / "concurrent.md"
        other_body = b"concurrent source\n"
        other_source.write_bytes(other_body)
        prepared = prepare_source(
            SourcePrepareRequest(
                request_id="source-02",
                source_path=other_source,
                source_reference="e0-l",
                expected_sha256=hash_bytes(other_body).sha256,
                expected_byte_size=len(other_body),
                authorized_by="local-user",
                task_ids=("l-t1",),
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
        )
        self.assertIsInstance(prepared, SourcePrepareResult)
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_target_worker,
                args=(
                    str(self.owned_root),
                    str(self.experiment_root),
                    str(self.kb_parent),
                    source_request,
                    decision_request,
                    queue,
                ),
            )
            for source_request, decision_request in (
                ("source-01", "concurrent-target-01"),
                ("source-02", "concurrent-target-02"),
            )
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(45)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
        receipts = (queue.get(timeout=5), queue.get(timeout=5))
        self.assertTrue(all(receipt["ok"] for receipt in receipts))
        self.assertEqual(
            {receipt["storage_name"] for receipt in receipts},
            {"2026-10-19-01", "2026-10-19-02"},
        )

    def test_cur1c_11_checkpoint_preserves_unrelated_staged_and_unstaged_work(self) -> None:
        result = self._decide(self._request(storage_name="index-isolation"))
        self.assertIsInstance(result, TargetDecideResult)
        assert isinstance(result, TargetDecideResult)
        repository = self.kb_parent / "index-isolation"
        staged = repository / "user-staged.md"
        staged.write_text("user staged\n", encoding="utf-8", newline="\n")
        subprocess.run(
            ["git", "-C", str(repository), "add", "--", "user-staged.md"],
            check=True,
        )
        readme = repository / "README.md"
        readme.write_bytes(readme.read_bytes() + "用户未暂存修改\n".encode("utf-8"))
        replay = self._decide(self._request(storage_name="index-isolation"))
        self.assertIsInstance(replay, TargetDecideResult)
        assert isinstance(replay, TargetDecideResult)
        self.assertTrue(replay.replayed)
        managed_relative = ".knowledgeflow/routes/isolation-proof.txt"
        managed_body = b"managed proof\n"
        managed_path = repository / Path(managed_relative)
        managed_path.write_bytes(managed_body)
        candidates: list[str] = []
        checkpoint = ManagedGit().checkpoint(
            repository,
            {managed_relative: managed_body},
            base_commit=result.result_commit,
            checkpoint_time="2026-10-19T01:02:04.000Z",
            message="Checkpoint isolated managed proof\n",
            index_path=repository / ".knowledgeflow" / "transactions" / "isolation.index",
            persist_candidate=candidates.append,
        )
        self.assertEqual(candidates, [checkpoint.commit])
        staged_names = subprocess.run(
            ["git", "-C", str(repository), "diff", "--cached", "--name-only"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode().splitlines()
        unstaged_names = subprocess.run(
            ["git", "-C", str(repository), "diff", "--name-only"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode().splitlines()
        self.assertIn("user-staged.md", staged_names)
        self.assertIn("README.md", unstaged_names)

    def test_cur1c_12_publish_and_checkpoint_faults_recover_without_false_success(self) -> None:
        publish_request = self._request(storage_name="publish-fault")
        publish_failed = self._decide(
            publish_request,
            durability=_FailKbPublishDurability(),
        )
        self.assertIsInstance(publish_failed, CurationFailure)
        self.assertEqual(
            publish_failed.error.code,
            CurationErrorCode.ATOMIC_PUBLISH_FAILED,
        )
        self.assertEqual(publish_failed.to_dict()["commit_state"], "not-committed")
        self.assertFalse((self.kb_parent / "publish-fault").exists())
        reservation_conflict = self._decide(
            self._request(
                decision_request_id="publish-fault-competitor",
                storage_name="publish-fault",
            )
        )
        self.assertIsInstance(reservation_conflict, CurationFailure)
        self.assertEqual(
            reservation_conflict.error.code,
            CurationErrorCode.TARGET_CONFLICT,
        )
        publish_recovered = self._decide(publish_request)
        self.assertIsInstance(publish_recovered, TargetDecideResult)

        checkpoint_request = self._request(
            decision_request_id="checkpoint-fault-request",
            storage_name="checkpoint-fault",
        )
        checkpoint_failed = self._decide(
            checkpoint_request,
            git=_FailCheckpointGit(),
        )
        self.assertIsInstance(checkpoint_failed, CurationFailure)
        self.assertEqual(
            checkpoint_failed.error.code,
            CurationErrorCode.VERSION_CONTROL_UNAVAILABLE,
        )
        self.assertEqual(checkpoint_failed.to_dict()["commit_state"], "unknown")
        repository = self.kb_parent / "checkpoint-fault"
        self.assertEqual(ManagedGit().current_commit(repository), (
            repository.parent.parent
            / "curation-work"
            / "target-transactions"
            / "checkpoint-fault-request"
            / "root-candidate.txt"
        ).read_text(encoding="ascii").strip())
        checkpoint_recovered = self._decide(checkpoint_request)
        self.assertIsInstance(checkpoint_recovered, TargetDecideResult)


if __name__ == "__main__":
    unittest.main()
