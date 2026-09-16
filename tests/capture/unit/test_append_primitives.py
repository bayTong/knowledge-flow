from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.codec import load_capture_event, load_envelope
from knowledgeflow_capture.durability import DurabilityBackend
from knowledgeflow_capture.hashing import (
    payload_set_sha256,
    request_fingerprint_sha256,
    seal_envelope,
)
from knowledgeflow_capture.ids import generate_uuid7
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    ChannelMetadata,
    PayloadMetadata,
    PayloadSetEntry,
    RequestFingerprint,
    UserIntent,
)
from knowledgeflow_capture.operations import (
    _AppendCommitDisposition,
    _AppendSourceEvidence,
    _AppendTargetAttestation,
    _AppendTargetEvidence,
    _CaptureDependencies,
    _IntegrityFailure,
    _appended_projection,
    _attest_append_candidate_at,
    _build_append_candidate,
    _classify_append_event_evidence,
    _decidable_append_tail_identity,
    _probe_append_source,
    _probe_append_target,
    _write_append_candidate_metadata,
)
from knowledgeflow_capture.store import (
    _CaptureStagingCleanupStatus,
    _cleanup_append_staging,
    _create_append_staging,
)
from .._samples import CAPTURE_ID


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVENT_ID_V2 = "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333"
TRANSACTION_UUID = generate_uuid7(
    unix_ts_ms=1_800_000_000_200,
    random_bytes=b"\x21\x23\x45\x67\x89\xab\xcd\xef\x01\x23",
)


class AppendPrimitiveTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C5A append write primitives are Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.capture_root = Path(self._temporary.name).resolve() / "capture-store"
        self.capture_root.mkdir()
        for name in ("items", ".staging", "journal"):
            (self.capture_root / name).mkdir()
        self.backend = DurabilityBackend(_directory_flusher=lambda _path: True)

    def _candidate(self):
        previous = load_envelope((FIXTURES / "envelope-v1.yaml").read_bytes())
        request = AppendCaptureVersionRequest(
            capture_id=CAPTURE_ID,
            expected_current_version=1,
            text="下一版本正文",
            channel=ChannelMetadata(
                type="app",
                instance_id="local-desktop",
                external_ref="edit-unit",
                source_created_at="2026-09-13T00:00:00.004Z",
            ),
            idempotency_key="append-unit-1",
        )
        staging = _create_append_staging(
            self.capture_root,
            durability=self.backend,
            uuid_factory=lambda: TRANSACTION_UUID,
        )
        payload_digest = self.backend.write_new_utf8_file_durable(
            staging.payload_path,
            request.text,
            maximum_bytes=1024,
            chunk_size=7,
        )
        payload_set_digest = payload_set_sha256(
            (
                PayloadSetEntry(
                    ordinal=0,
                    role="primary",
                    kind="text",
                    media_type="text/plain; charset=utf-8",
                    byte_size=payload_digest.byte_size,
                    sha256=payload_digest.sha256,
                ),
            )
        )
        intent = request.user_intent
        assert isinstance(intent, UserIntent)
        request_digest = request_fingerprint_sha256(
            RequestFingerprint(
                operation="append_capture_version",
                payload_set_sha256=payload_set_digest,
                channel=request.channel,
                payload_metadata=(PayloadMetadata(ordinal=0),),
                user_intent=intent,
                capture_id=request.capture_id,
                expected_current_version=request.expected_current_version,
            )
        )
        samples = iter(
            (
                datetime(2026, 9, 13, 0, 0, 0, 4000, tzinfo=timezone.utc),
                datetime(2026, 9, 13, 0, 0, 0, 5000, tzinfo=timezone.utc),
            )
        )
        dependencies = _CaptureDependencies(
            durability=self.backend,
            utc_now=lambda: next(samples),
            event_id_factory=lambda: EVENT_ID_V2,
        )
        candidate = _build_append_candidate(
            request,
            previous_envelope=previous,
            received_at="2026-09-13T00:00:00.001Z",
            payload_digest=payload_digest,
            payload_set_digest=payload_set_digest,
            request_digest=request_digest,
            dependencies=dependencies,
        )
        return staging, candidate, dependencies

    def test_event_writer_and_full_candidate_attestation_share_strict_codec(self) -> None:
        staging, candidate, dependencies = self._candidate()

        _write_append_candidate_metadata(staging, candidate, dependencies)
        _attest_append_candidate_at(
            staging.version_path,
            staging.event_path(candidate.event_id),
            candidate,
        )
        self.assertEqual(
            load_capture_event(
                staging.event_path(candidate.event_id).read_bytes(),
                envelope=candidate.envelope,
                previous_envelope=candidate.previous_envelope,
            ),
            candidate.event,
        )
        state = _appended_projection(
            candidate,
            verified_at="2026-09-13T00:00:00.006Z",
        )
        self.assertEqual(state["updated_at"], candidate.event["occurred_at"])
        self.assertNotEqual(
            state["updated_at"],
            state["durability"]["verified_at"],
        )

        staging.payload_path.write_bytes(b"same path, wrong bytes")
        with self.assertRaises(_IntegrityFailure):
            _attest_append_candidate_at(
                staging.version_path,
                staging.event_path(candidate.event_id),
                candidate,
            )
        self.assertEqual(
            _cleanup_append_staging(staging, durability=self.backend),
            _CaptureStagingCleanupStatus.REMOVED,
        )

    def test_tail_identity_exists_only_at_the_canonical_decidable_boundary(self) -> None:
        previous = load_envelope((FIXTURES / "envelope-v1.yaml").read_bytes())
        source = (FIXTURES / "envelope-v2.yaml").read_bytes()
        identity = _decidable_append_tail_identity(
            source,
            expected_capture_id=CAPTURE_ID,
            expected_version=2,
            previous_envelope=previous,
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.scope, "app:local-desktop:append_capture_version")
        self.assertEqual(identity.key_sha256, "sha256:" + ("2" * 64))
        self.assertEqual(
            identity.request_fingerprint_sha256,
            "sha256:72efb0b043173a104e0dee5460b0749da7e852604b16915f0016f2c945ea766f",
        )

        anonymous = load_envelope(source)
        anonymous_data = dict(anonymous)
        anonymous_data.pop("envelope_sha256")
        anonymous_data["idempotency"] = None
        anonymous_bytes = seal_envelope(anonymous_data).yaml_bytes
        cases = (
            source[:100],
            source.replace(b"schema_version: 1", b"schema_version: 01"),
            anonymous_bytes,
        )
        for candidate in cases:
            with self.subTest(candidate=candidate[:40]):
                self.assertIsNone(
                    _decidable_append_tail_identity(
                        candidate,
                        expected_capture_id=CAPTURE_ID,
                        expected_version=2,
                        previous_envelope=previous,
                    )
                )
        self.assertIsNone(
            _decidable_append_tail_identity(
                source,
                expected_capture_id=CAPTURE_ID,
                expected_version=3,
                previous_envelope=previous,
            )
        )

    def test_event_rename_evidence_matrix_is_pure_and_conservative(self) -> None:
        cases = (
            (
                False,
                _AppendSourceEvidence.ORIGINAL,
                _AppendTargetEvidence.ABSENT,
                _AppendTargetAttestation.NOT_RUN,
                _AppendCommitDisposition.NOT_COMMITTED,
            ),
            (
                True,
                _AppendSourceEvidence.ORIGINAL,
                _AppendTargetEvidence.ABSENT,
                _AppendTargetAttestation.NOT_RUN,
                _AppendCommitDisposition.NOT_COMMITTED,
            ),
            (
                True,
                _AppendSourceEvidence.ABSENT,
                _AppendTargetEvidence.PRESENT,
                _AppendTargetAttestation.MATCH,
                _AppendCommitDisposition.COMMITTED,
            ),
            (
                True,
                _AppendSourceEvidence.ABSENT,
                _AppendTargetEvidence.UNPROVABLE,
                _AppendTargetAttestation.UNPROVABLE,
                _AppendCommitDisposition.UNKNOWN,
            ),
            (
                True,
                _AppendSourceEvidence.ABSENT,
                _AppendTargetEvidence.PRESENT,
                _AppendTargetAttestation.INVALID,
                _AppendCommitDisposition.INTEGRITY_UNKNOWN,
            ),
            (
                True,
                _AppendSourceEvidence.ORIGINAL,
                _AppendTargetEvidence.PRESENT,
                _AppendTargetAttestation.MATCH,
                _AppendCommitDisposition.UNKNOWN,
            ),
        )
        for rename_attempted, source, target, attestation, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    _classify_append_event_evidence(
                        rename_attempted=rename_attempted,
                        source=source,
                        target=target,
                        target_attestation=attestation,
                    ),
                    expected,
                )

    def test_source_and_target_probes_distinguish_owned_absent_and_other(self) -> None:
        source = self.capture_root / ".staging" / "probe-source.yaml"
        target = self.capture_root / "items" / "probe-target.yaml"
        source.write_bytes(b"owned")
        source_stat = os.stat(source, follow_symlinks=False)
        self.assertEqual(
            _probe_append_source(source, source_stat),
            _AppendSourceEvidence.ORIGINAL,
        )
        self.assertEqual(
            _probe_append_target(target),
            _AppendTargetEvidence.ABSENT,
        )
        moved = source.with_suffix(".moved")
        source.rename(moved)
        source.write_bytes(b"replacement")
        self.assertEqual(
            _probe_append_source(source, source_stat),
            _AppendSourceEvidence.OTHER,
        )
        target.write_bytes(b"present")
        self.assertEqual(
            _probe_append_target(target),
            _AppendTargetEvidence.PRESENT,
        )
        source.unlink()
        self.assertEqual(
            _probe_append_source(source, source_stat),
            _AppendSourceEvidence.ABSENT,
        )


if __name__ == "__main__":
    unittest.main()
