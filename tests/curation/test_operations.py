from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.ids import generate_capture_id
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_curation import (
    ByteRange,
    CurationErrorCode,
    CurationFailure,
    CurationRunManifest,
    EvidenceShowRequest,
    ProcessingAuthorization,
    ProcessorProfile,
    ScopeRecord,
    SegmentationProfile,
    SourceBinding,
    SourceInspectRequest,
    SourcePrepareRequest,
    SourcePrepareResult,
    build_evidence_record,
    deterministic_segment_fingerprint,
    inspect_source,
    prepare_source,
    show_evidence,
)
from knowledgeflow_curation.cli import _run_cli
from knowledgeflow_curation.ids import generate_curation_id
from tests.curation._samples import curation_map, curation_run


def _run_for_bytes(
    source: bytes,
    *,
    authorized: ByteRange | None = None,
    declared: ByteRange | None = None,
) -> CurationRunManifest:
    full = ByteRange(0, len(source))
    selected_authorized = authorized or full
    selected_declared = declared or selected_authorized
    return CurationRunManifest(
        curation_run_id=generate_curation_id("run_"),
        source_mapping_id=generate_curation_id("smap_"),
        source=SourceBinding(
            capture_id=generate_capture_id(),
            capture_version=1,
            envelope_sha256="sha256:" + ("1" * 64),
            payload_sha256=hash_bytes(source).sha256,
            byte_size=len(source),
        ),
        processing_authorization=ProcessingAuthorization(
            authorization_id=generate_curation_id("auth_"),
            authorized_by="local-user",
            authorized_at="2026-10-18T01:02:03.000Z",
            allowed_range=selected_authorized,
            task_ids=("c-t1",),
        ),
        declared_scope=selected_declared,
        target_decision=None,
        segmentation_profile=SegmentationProfile(),
        processor_profile=ProcessorProfile(
            kind="mechanical",
            processor_id="cur1b-test",
            revision=1,
            model_id=None,
            network_allowed=False,
        ),
    )


class CurationSegmentationTest(unittest.TestCase):
    def test_cur1b_01_target_can_be_undecided_before_cur1c(self) -> None:
        undecided = replace(curation_run(), target_decision=None)
        self.assertIsNone(undecided.target_decision)
        self.assertIsNone(undecided.as_mapping()["target_decision"])
        with self.assertRaises(ValueError):
            curation_map().validate_against_run(undecided)

    def test_cur1b_02_markdown_segmentation_is_exact_and_deterministic(self) -> None:
        section = (
            "## 中文小节\r\n\r\n"
            "组合字符 e\u0301 和普通正文。\r\n"
            "| 列一 | 列二 |\r\n"
            "| --- | --- |\r\n"
            "| A | B |\r\n\r\n"
            "```python\r\n"
            "print('空行不会结束代码块')\r\n\r\n"
            "```   \r\n"
        ).encode("utf-8")
        source = b"# Root\r\n\r\n" + (section * 260) + b"no trailing newline"
        run = _run_for_bytes(source)
        first = build_evidence_record(source, run)
        second = build_evidence_record(source, run)

        self.assertEqual(
            deterministic_segment_fingerprint(first),
            deterministic_segment_fingerprint(second),
        )
        self.assertNotEqual(
            tuple(item.segment_id for item in first.segments),
            tuple(item.segment_id for item in second.segments),
        )
        self.assertEqual(first.segments[0].heading_path, ("Root",))
        self.assertEqual(first.segments[0].byte_range.start_byte, 0)
        self.assertEqual(first.segments[-1].byte_range.end_byte, len(source))
        for item in first.segments:
            body = source[item.byte_range.start_byte : item.byte_range.end_byte]
            self.assertLessEqual(len(body), 32 * 1024)
            self.assertEqual(hash_bytes(body).sha256, item.body_sha256)
            body.decode("utf-8", errors="strict")

    def test_cur1b_03_long_line_splits_only_at_utf8_boundaries(self) -> None:
        source = (("汉e\u0301" * 20000) + "终").encode("utf-8")
        evidence = build_evidence_record(source, _run_for_bytes(source))
        self.assertGreater(len(evidence.segments), 1)
        self.assertEqual(evidence.segments[-1].byte_range.end_byte, len(source))
        for item in evidence.segments:
            body = source[item.byte_range.start_byte : item.byte_range.end_byte]
            self.assertLessEqual(len(body), 32 * 1024)
            body.decode("utf-8", errors="strict")

    def test_cur1b_04_range_ledger_accepts_exact_mixed_statuses(self) -> None:
        source = b"abcdefghij"
        run = _run_for_bytes(source)
        scope = (
            ScopeRecord(ByteRange(0, 3), "processed"),
            ScopeRecord(ByteRange(3, 7), "deferred", "budget-boundary"),
            ScopeRecord(ByteRange(7, 10), "failed", "processor-error"),
        )
        evidence = build_evidence_record(source, run, scope=scope)
        self.assertEqual(evidence.scope, scope)
        with self.assertRaises(ValueError):
            build_evidence_record(source, run, scope=(scope[0], scope[2]))


class CurationOperationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.owned_root = Path(self._temporary.name).resolve()
        self.experiment_root = self.owned_root / "experiment"
        self.policy = PathPolicy.test_owned(self.owned_root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _write_source(self, name: str, body: bytes) -> Path:
        path = self.owned_root / name
        path.write_bytes(body)
        return path

    def _request(
        self,
        source_path: Path,
        body: bytes,
        *,
        request_id: str = "cur1b-request-01",
        **kwargs: object,
    ) -> SourcePrepareRequest:
        return SourcePrepareRequest(
            request_id=request_id,
            source_path=source_path,
            source_reference="e0-f",
            expected_sha256=hash_bytes(body).sha256,
            expected_byte_size=len(body),
            authorized_by="local-user",
            task_ids=("c-t1", "c-t4"),
            **kwargs,
        )

    def _prepare(self, body: bytes, **kwargs: object) -> SourcePrepareResult:
        source = self._write_source("source.md", body)
        result = prepare_source(
            self._request(source, body, **kwargs),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, SourcePrepareResult)
        assert isinstance(result, SourcePrepareResult)
        return result

    def test_cur1b_05_prepare_inspect_and_show_exact_evidence(self) -> None:
        body = "# 标题\n\n第一段。\n\n第二段，无尾随换行".encode("utf-8")
        prepared = self._prepare(body)
        receipt = prepared.to_dict()
        self.assertEqual(receipt["commit_state"], "committed")
        self.assertFalse(receipt["target_decision_recorded"])
        self.assertEqual(receipt["scope_summary"]["outside_declared_scope_bytes"], 0)
        self.assertFalse(prepared.replayed)

        inspected = inspect_source(
            SourceInspectRequest(request_id="cur1b-request-01"),
            experiment_root=self.experiment_root,
        )
        self.assertTrue(inspected.to_dict()["ok"])
        self.assertEqual(inspected.run, prepared.run)

        for locator in prepared.evidence.locators:
            sink = io.BytesIO()
            shown = show_evidence(
                EvidenceShowRequest(
                    request_id="cur1b-request-01",
                    locator_id=locator.locator_id,
                    body_sink=sink,
                ),
                experiment_root=self.experiment_root,
                path_policy=self.policy,
            )
            self.assertTrue(shown.to_dict()["ok"])
            self.assertEqual(
                sink.getvalue(),
                body[locator.byte_range.start_byte : locator.byte_range.end_byte],
            )

    def test_cur1b_06_identical_retry_reuses_capture_and_work_bundle(self) -> None:
        body = b"# Stable\n\nbody\n"
        source = self._write_source("source.md", body)
        request = self._request(source, body)
        first = prepare_source(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        second = prepare_source(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(first, SourcePrepareResult)
        self.assertIsInstance(second, SourcePrepareResult)
        assert isinstance(first, SourcePrepareResult)
        assert isinstance(second, SourcePrepareResult)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.mapping, second.mapping)
        self.assertEqual(first.run, second.run)
        self.assertEqual(first.evidence, second.evidence)

    def test_cur1b_07_same_request_id_with_different_identity_conflicts(self) -> None:
        first_body = b"first\n"
        first_path = self._write_source("first.md", first_body)
        first = prepare_source(
            self._request(first_path, first_body),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(first, SourcePrepareResult)
        second_body = b"second\n"
        second_path = self._write_source("second.md", second_body)
        second = prepare_source(
            self._request(second_path, second_body),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(second, CurationFailure)
        assert isinstance(second, CurationFailure)
        self.assertEqual(second.error.code, CurationErrorCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(second.to_dict()["commit_state"], "not-committed")

    def test_cur1b_08_identity_mismatch_and_invalid_utf8_do_not_publish(self) -> None:
        body = b"actual\n"
        source = self._write_source("mismatch.md", body)
        mismatch_request = replace(
            self._request(source, body, request_id="mismatch-request"),
            expected_sha256="sha256:" + ("f" * 64),
        )
        mismatch = prepare_source(
            mismatch_request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(mismatch, CurationFailure)
        self.assertEqual(
            mismatch.error.code,
            CurationErrorCode.SOURCE_IDENTITY_MISMATCH,
        )
        self.assertFalse(
            (self.experiment_root / "curation-work" / "requests" / "mismatch-request").exists()
        )

        invalid = b"valid-prefix\n\xff"
        invalid_path = self._write_source("invalid.md", invalid)
        rejected = prepare_source(
            self._request(invalid_path, invalid, request_id="invalid-utf8-request"),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(rejected, CurationFailure)
        self.assertEqual(rejected.error.code, CurationErrorCode.UNSUPPORTED_SOURCE)
        self.assertEqual(rejected.to_dict()["commit_state"], "not-committed")

    def test_cur1b_09_invalid_unicode_scope_boundary_is_rejected_precommit(self) -> None:
        body = "汉字".encode("utf-8")
        source = self._write_source("unicode.md", body)
        request = self._request(
            source,
            body,
            request_id="bad-boundary-request",
            authorized_range=ByteRange(1, len(body)),
            declared_scope=ByteRange(1, len(body)),
        )
        result = prepare_source(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, CurationFailure)
        self.assertEqual(
            result.error.code,
            CurationErrorCode.AUTHORIZATION_SCOPE_MISMATCH,
        )
        self.assertEqual(result.to_dict()["commit_state"], "not-committed")

    def test_cur1b_10_deleted_derived_bundle_rebuilds_same_ordered_facts(self) -> None:
        body = (("## Part\n\n" + ("内容。" * 3000) + "\n\n") * 4).encode("utf-8")
        source = self._write_source("rebuild.md", body)
        request = self._request(source, body, request_id="rebuild-request")
        first = prepare_source(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(first, SourcePrepareResult)
        assert isinstance(first, SourcePrepareResult)
        derived = self.experiment_root / "curation-work" / "requests" / "rebuild-request"
        shutil.rmtree(derived)
        second = prepare_source(
            request,
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(second, SourcePrepareResult)
        assert isinstance(second, SourcePrepareResult)
        self.assertEqual(first.mapping.capture, second.mapping.capture)
        self.assertEqual(
            deterministic_segment_fingerprint(first.evidence),
            deterministic_segment_fingerprint(second.evidence),
        )
        self.assertNotEqual(first.run.curation_run_id, second.run.curation_run_id)

    def test_cur1b_11_bundle_tampering_and_unknown_locator_fail_closed(self) -> None:
        body = b"# Evidence\n\nexact bytes\n"
        prepared = self._prepare(body)
        missing_sink = io.BytesIO()
        missing = show_evidence(
            EvidenceShowRequest(
                request_id="cur1b-request-01",
                locator_id=generate_curation_id("loc_"),
                body_sink=missing_sink,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(missing, CurationFailure)
        self.assertEqual(missing.error.code, CurationErrorCode.LOCATOR_INVALID)
        self.assertEqual(missing_sink.getvalue(), b"")

        evidence_path = (
            self.experiment_root
            / "curation-work"
            / "requests"
            / "cur1b-request-01"
            / "evidence.yaml"
        )
        tampered = evidence_path.read_bytes().replace(
            prepared.evidence.segments[0].body_sha256.encode("ascii"),
            ("sha256:" + ("f" * 64)).encode("ascii"),
            1,
        )
        evidence_path.write_bytes(tampered)
        inspected = inspect_source(
            SourceInspectRequest(request_id="cur1b-request-01"),
            experiment_root=self.experiment_root,
        )
        self.assertIsInstance(inspected, CurationFailure)
        self.assertEqual(
            inspected.error.code,
            CurationErrorCode.SOURCE_INTEGRITY_FAILED,
        )

    def test_cur1b_12_cli_prepare_inspect_and_evidence_show_are_json_only(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(
            'knowledgeflow-curation = "knowledgeflow_curation.cli:main"',
            pyproject,
        )
        body = "# CLI\n\n证据\n".encode("utf-8")
        source = self._write_source("cli.md", body)
        prepare_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "source",
                "prepare",
                "--source",
                str(source),
                "--source-reference",
                "e0-f",
                "--expected-sha256",
                hash_bytes(body).sha256,
                "--expected-bytes",
                str(len(body)),
                "--request-id",
                "cli-request",
                "--authorized-by",
                "local-user",
                "--task-id",
                "c-t1",
            ),
            stdout=prepare_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        self.assertEqual(prepare_stdout.getvalue().count(b"\n"), 1)
        prepared_receipt = json.loads(prepare_stdout.getvalue())
        self.assertEqual(prepared_receipt["operation"], "source.prepare")

        inspect_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "source",
                "inspect",
                "--request-id",
                "cli-request",
            ),
            stdout=inspect_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        inspect_receipt = json.loads(inspect_stdout.getvalue())
        self.assertEqual(inspect_receipt["operation"], "source.inspect")
        locator_id = inspect_receipt["locators"][0]["locator_id"]
        output = self.owned_root / "excerpt.md"
        show_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "evidence",
                "show",
                "--request-id",
                "cli-request",
                "--locator-id",
                locator_id,
                "--output",
                str(output),
            ),
            stdout=show_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(show_stdout.getvalue())["operation"], "evidence.show")
        self.assertEqual(output.read_bytes(), body)

        second_stdout = io.BytesIO()
        code = _run_cli(
            (
                "--experiment-root",
                str(self.experiment_root),
                "evidence",
                "show",
                "--request-id",
                "cli-request",
                "--locator-id",
                locator_id,
                "--output",
                str(output),
            ),
            stdout=second_stdout,
            path_policy=self.policy,
        )
        self.assertEqual(code, 2)
        failure_receipt = json.loads(second_stdout.getvalue())
        self.assertFalse(failure_receipt["ok"])
        self.assertEqual(
            failure_receipt["next_action"],
            "correct_arguments_and_retry",
        )

    def test_cur1b_13_wrong_capture_version_fails_before_output(self) -> None:
        body = b"# Version\n\nonly v1 exists\n"
        prepared = self._prepare(body)
        bundle = (
            self.experiment_root
            / "curation-work"
            / "requests"
            / "cur1b-request-01"
        )
        for name in ("source-mapping.yaml", "run.yaml", "evidence.yaml"):
            path = bundle / name
            path.write_bytes(
                path.read_bytes().replace(
                    b"capture_version: 1\n",
                    b"capture_version: 2\n",
                )
            )
        inspected = inspect_source(
            SourceInspectRequest(request_id="cur1b-request-01"),
            experiment_root=self.experiment_root,
        )
        self.assertTrue(inspected.to_dict()["ok"])
        sink = io.BytesIO()
        shown = show_evidence(
            EvidenceShowRequest(
                request_id="cur1b-request-01",
                locator_id=prepared.evidence.locators[0].locator_id,
                body_sink=sink,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(shown, CurationFailure)
        self.assertEqual(shown.error.code, CurationErrorCode.SOURCE_NOT_FOUND)
        self.assertEqual(sink.getvalue(), b"")

    def test_cur1b_14_payload_hash_change_fails_before_output(self) -> None:
        body = b"# Payload\n\nexact body\n"
        prepared = self._prepare(body)
        matches = tuple(
            (self.experiment_root / "capture-store").glob(
                f"items/*/*/{prepared.mapping.capture.capture_id}"
            )
        )
        self.assertEqual(len(matches), 1)
        payload = matches[0] / "versions" / "000001" / "payloads" / "primary.txt"
        payload.write_bytes(b"X" + payload.read_bytes()[1:])
        sink = io.BytesIO()
        shown = show_evidence(
            EvidenceShowRequest(
                request_id="cur1b-request-01",
                locator_id=prepared.evidence.locators[0].locator_id,
                body_sink=sink,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.policy,
        )
        self.assertIsInstance(shown, CurationFailure)
        self.assertEqual(
            shown.error.code,
            CurationErrorCode.SOURCE_INTEGRITY_FAILED,
        )
        self.assertEqual(sink.getvalue(), b"")


if __name__ == "__main__":
    unittest.main()
