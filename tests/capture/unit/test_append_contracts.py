from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import io
import inspect
from pathlib import Path
import unittest

import knowledgeflow_capture
from knowledgeflow_capture.codec import (
    SchemaValidationError,
    dump_capture_event,
    dump_capture_state,
    load_capture_event,
    load_capture_state,
    load_envelope,
)
from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CommittedWriteResult,
)
from knowledgeflow_capture.hashing import (
    request_fingerprint_canonical_json,
    request_fingerprint_sha256,
    seal_envelope,
)
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    ChannelMetadata,
    PayloadMetadata,
    RequestFingerprint,
    UserIntent,
    canonical_idempotency_scope,
)
from .._samples import CAPTURE_ID


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAYLOAD_SET_V2 = (
    "sha256:d2e0d440bc85cf5ad3d6acbef45abfe9f48a80ae683fb2b96d5a73767597bcb8"
)
REQUEST_V2 = (
    "sha256:72efb0b043173a104e0dee5460b0749da7e852604b16915f0016f2c945ea766f"
)


def append_channel() -> ChannelMetadata:
    return ChannelMetadata(
        type="app",
        instance_id="local-desktop",
        external_ref="edit-43",
        source_created_at="2026-09-13T00:00:00.004Z",
    )


def append_receipt(*, version: int = 2) -> dict[str, object]:
    return {
        "capture_id": CAPTURE_ID,
        "event_id": "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333",
        "previous_version": version - 1,
        "version": version,
        "primary_payload_sha256": "sha256:" + ("a" * 64),
        "payload_set_sha256": "sha256:" + ("b" * 64),
        "envelope_sha256": "sha256:" + ("c" * 64),
        "durability": "durable",
        "routing_status": "unassigned",
        "trust_status": "unreviewed-capture",
        "gbrain_sync_status": "not-requested",
    }


class AppendContractTest(unittest.TestCase):
    def test_app_01_public_types_and_c5b_operation_are_published(self) -> None:
        for name in (
            "AppendCaptureVersionOperationResult",
            "AppendCaptureVersionRequest",
            "AppendCaptureVersionResult",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(knowledgeflow_capture, name))
                self.assertIn(name, knowledgeflow_capture.__all__)
        self.assertTrue(hasattr(knowledgeflow_capture, "append_capture_version"))
        self.assertIn("append_capture_version", knowledgeflow_capture.__all__)
        parameters = inspect.signature(
            knowledgeflow_capture.append_capture_version
        ).parameters
        self.assertEqual(
            tuple(parameters),
            ("request", "config_path", "path_policy"),
        )
        self.assertEqual(parameters["request"].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        self.assertEqual(parameters["config_path"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(parameters["path_policy"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_app_01_request_is_exact_keyword_only_frozen_and_slotted(self) -> None:
        request = AppendCaptureVersionRequest(
            capture_id=CAPTURE_ID,
            expected_current_version=1,
            text="完整新正文",
            channel=append_channel(),
            idempotency_key="append-43",
        )
        self.assertEqual(
            tuple(field.name for field in fields(AppendCaptureVersionRequest)),
            (
                "capture_id",
                "expected_current_version",
                "text",
                "channel",
                "idempotency_key",
                "user_intent",
            ),
        )
        self.assertEqual(request.user_intent, UserIntent())
        self.assertFalse(hasattr(request, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            request.expected_current_version = 2  # type: ignore[misc]
        with self.assertRaises(TypeError):
            AppendCaptureVersionRequest(  # type: ignore[misc]
                CAPTURE_ID,
                1,
                "body",
                append_channel(),
                "append-43",
            )

    def test_app_01_request_rejects_bad_identity_key_version_and_text(self) -> None:
        base = {
            "capture_id": CAPTURE_ID,
            "expected_current_version": 1,
            "text": "body",
            "channel": append_channel(),
            "idempotency_key": "append-43",
        }
        for field_name, value in (
            ("capture_id", "cap_not-a-uuid"),
            ("expected_current_version", True),
            ("expected_current_version", 0),
            ("expected_current_version", 999999),
            ("expected_current_version", "1"),
            ("idempotency_key", ""),
            ("idempotency_key", None),
            ("text", ""),
            ("text", "\ufeffbody"),
            ("text", b"raw-bytes"),
        ):
            values = dict(base)
            values[field_name] = value
            with self.subTest(field=field_name, value=value), self.assertRaises(
                (TypeError, ValueError)
            ):
                AppendCaptureVersionRequest(**values)
        with self.assertRaises(TypeError):
            AppendCaptureVersionRequest(
                capture_id=CAPTURE_ID,
                expected_current_version=1,
                text="body",
                channel=append_channel(),
            )
        stream = io.BytesIO("流正文".encode("utf-8"))
        self.assertIs(
            AppendCaptureVersionRequest(
                capture_id=CAPTURE_ID,
                expected_current_version=999998,
                text=stream,
                channel=append_channel(),
                idempotency_key="append-max",
            ).text,
            stream,
        )

    def test_app_03_omitted_intent_scope_key_and_fingerprint_match_golden(self) -> None:
        omitted = AppendCaptureVersionRequest(
            capture_id=CAPTURE_ID,
            expected_current_version=1,
            text="body",
            channel=append_channel(),
            idempotency_key="append-43",
        )
        explicit = AppendCaptureVersionRequest(
            capture_id=CAPTURE_ID,
            expected_current_version=1,
            text="body",
            channel=append_channel(),
            idempotency_key="append-43",
            user_intent=UserIntent(
                target_kb_id=None,
                processing_mode=None,
                requested_new_kb_name=None,
            ),
        )
        self.assertEqual(omitted.user_intent, explicit.user_intent)
        self.assertEqual(
            canonical_idempotency_scope(
                omitted.channel,
                "append_capture_version",
            ),
            "app:local-desktop:append_capture_version",
        )
        digests = []
        golden = (FIXTURES / "request-fingerprint-append-v1.json").read_bytes()
        self.assertTrue(golden.endswith(b"\n"))
        self.assertFalse(golden.endswith(b"\n\n"))
        for request in (omitted, explicit):
            fingerprint = RequestFingerprint(
                operation="append_capture_version",
                payload_set_sha256=PAYLOAD_SET_V2,
                channel=request.channel,
                payload_metadata=(PayloadMetadata(ordinal=0),),
                user_intent=request.user_intent,
                capture_id=request.capture_id,
                expected_current_version=request.expected_current_version,
            )
            self.assertEqual(
                request_fingerprint_canonical_json(fingerprint),
                golden[:-1],
            )
            digests.append(request_fingerprint_sha256(fingerprint))
        self.assertEqual(digests, [REQUEST_V2, REQUEST_V2])

    def test_append_result_is_independent_and_exact(self) -> None:
        result = AppendCaptureVersionResult(receipt=append_receipt())
        self.assertEqual(
            result.to_dict(),
            {
                "ok": True,
                "saved": True,
                "commit_state": "committed",
                **append_receipt(),
                "warnings": [],
            },
        )
        for mutation in (
            {**append_receipt(), "previous_version": 2},
            {**append_receipt(), "version": 1, "previous_version": 0},
            {**append_receipt(), "version": 1000000, "previous_version": 999999},
            {key: value for key, value in append_receipt().items() if key != "previous_version"},
            {**append_receipt(), "body": "must never enter a receipt"},
        ):
            with self.subTest(receipt=mutation), self.assertRaises(ValueError):
                AppendCaptureVersionResult(receipt=mutation)
        with self.assertRaises(ValueError):
            CommittedWriteResult(receipt=append_receipt())

    def test_v2_projection_matches_golden_and_requires_immutable_context(self) -> None:
        envelope_1 = load_envelope((FIXTURES / "envelope-v1.yaml").read_bytes())
        envelope_2 = load_envelope((FIXTURES / "envelope-v2.yaml").read_bytes())
        event_2 = load_capture_event(
            (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes(),
            envelope=envelope_2,
            previous_envelope=envelope_1,
        )
        state_bytes = (FIXTURES / "capture-state-v2.yaml").read_bytes()
        state = load_capture_state(
            state_bytes,
            envelope=envelope_2,
            current_event=event_2,
            previous_envelope=envelope_1,
        )
        self.assertEqual(
            dump_capture_state(
                state,
                envelope=envelope_2,
                current_event=event_2,
                previous_envelope=envelope_1,
            ),
            state_bytes,
        )
        self.assertNotEqual(
            state["updated_at"],
            state["durability"]["verified_at"],
        )
        with self.assertRaises(SchemaValidationError):
            load_capture_state(state_bytes, envelope=envelope_2)
        changed = dict(state)
        changed["updated_at"] = "2026-09-13T00:00:00.006Z"
        with self.assertRaises(SchemaValidationError):
            dump_capture_state(
                changed,
                envelope=envelope_2,
                current_event=event_2,
                previous_envelope=envelope_1,
            )

    def test_projection_and_event_v1_version_upper_bound_is_999999(self) -> None:
        original_1 = load_envelope((FIXTURES / "envelope-v1.yaml").read_bytes())
        original_2 = load_envelope((FIXTURES / "envelope-v2.yaml").read_bytes())
        previous_data = dict(original_1)
        previous_data.pop("envelope_sha256")
        previous_data["version"] = 999998
        previous_data["previous_version"] = 999997
        previous = seal_envelope(previous_data).envelope
        current_data = dict(original_2)
        current_data.pop("envelope_sha256")
        current_data["version"] = 999999
        current_data["previous_version"] = 999998
        current = seal_envelope(current_data).envelope
        event = {
            "schema": "knowledgeflow.capture-event",
            "schema_version": 1,
            "event_id": current["event_id"],
            "event_type": "capture.version-appended",
            "capture_id": CAPTURE_ID,
            "version": 999999,
            "previous_version": 999998,
            "previous_envelope_sha256": previous["envelope_sha256"],
            "envelope_sha256": current["envelope_sha256"],
            "occurred_at": "2026-09-13T00:00:00.005Z",
            "actor": current["actor"],
        }
        dump_capture_event(
            event,
            envelope=current,
            previous_envelope=previous,
        )
        state = load_capture_state(
            (FIXTURES / "capture-state-v2.yaml").read_bytes(),
            envelope=original_2,
            current_event=load_capture_event(
                (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes(),
                envelope=original_2,
                previous_envelope=original_1,
            ),
            previous_envelope=original_1,
        )
        state["current_version"] = 999999
        state["current_envelope_sha256"] = current["envelope_sha256"]
        dump_capture_state(
            state,
            envelope=current,
            current_event=event,
            previous_envelope=previous,
        )
        state["current_version"] = 1000000
        with self.assertRaises(SchemaValidationError):
            dump_capture_state(
                state,
                envelope=current,
                current_event=event,
                previous_envelope=previous,
            )


if __name__ == "__main__":
    unittest.main()
