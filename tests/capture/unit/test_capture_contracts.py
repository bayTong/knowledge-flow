from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import unittest

from knowledgeflow_capture.codec import (
    CaptureEventReferenceError,
    NonCanonicalYamlError,
    SchemaValidationError,
    dump_capture_event,
    dump_capture_state,
    load_capture_event,
    load_capture_state,
    validate_capture_event,
    validate_capture_state,
    validate_envelope,
)
from knowledgeflow_capture.hashing import (
    IDEMPOTENCY_KEY_DOMAIN,
    idempotency_key_sha256,
    request_fingerprint_sha256,
    seal_envelope,
)
from knowledgeflow_capture.models import (
    CaptureTextRequest,
    ChannelMetadata,
    PayloadMetadata,
    RequestFingerprint,
    UserIntent,
    canonical_idempotency_scope,
    format_utc_milliseconds,
)
from .._samples import (
    CAPTURE_ID,
    EVENT_ID,
    SINGLE_PAYLOAD_SET_SHA256,
    envelope_with_placeholder_hash,
    envelope_without_hash,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ENVELOPE_SHA256 = (
    "sha256:d060313160f00566464a47a23f37d530a8cd77a100a6efcda591a7224c17515a"
)


def capture_event() -> dict[str, object]:
    return {
        "schema": "knowledgeflow.capture-event",
        "schema_version": 1,
        "event_id": EVENT_ID,
        "event_type": "capture.created",
        "capture_id": CAPTURE_ID,
        "version": 1,
        "envelope_sha256": ENVELOPE_SHA256,
        "occurred_at": "2026-09-02T01:02:03.005Z",
        "actor": {"type": "user", "actor_id": "local-user"},
    }


def capture_state() -> dict[str, object]:
    return {
        "schema": "knowledgeflow.capture-state",
        "schema_version": 1,
        "capture_id": CAPTURE_ID,
        "current_version": 1,
        "current_envelope_sha256": ENVELOPE_SHA256,
        "durability": {
            "status": "durable",
            "verified_at": "2026-09-02T01:02:03.006Z",
        },
        "routing": {"status": "unassigned", "target_kb_ids": []},
        "trust": {"status": "unreviewed-capture"},
        "gbrain": {
            "sync_status": "not-requested",
            "source_id": None,
            "page_slug": None,
            "mirrored_version": None,
            "mirrored_envelope_sha256": None,
        },
        "backup": {
            "git_status": "uncommitted",
            "commit": None,
            "remote_status": "not-requested",
        },
        "updated_at": "2026-09-02T01:02:03.006Z",
    }


class CaptureContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope = seal_envelope(envelope_without_hash()).envelope

    def test_ct_20_contract_event_and_projection_match_golden_bytes(self) -> None:
        event_golden = (FIXTURES / "capture-event-v1.yaml").read_bytes()
        state_golden = (FIXTURES / "capture-state-v1.yaml").read_bytes()

        self.assertEqual(
            dump_capture_event(capture_event(), envelope=self.envelope),
            event_golden,
        )
        self.assertEqual(
            load_capture_event(event_golden, envelope=self.envelope),
            capture_event(),
        )
        self.assertEqual(
            dump_capture_state(capture_state(), envelope=self.envelope),
            state_golden,
        )
        self.assertEqual(
            load_capture_state(state_golden, envelope=self.envelope),
            capture_state(),
        )
        for golden in (event_golden, state_golden):
            self.assertFalse(golden.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", golden)
            self.assertTrue(golden.endswith(b"\n"))
            self.assertFalse(golden.endswith(b"\n\n"))

    def test_ct_20_21_contract_event_schema_and_references_are_strict(self) -> None:
        schema_mutations = []
        for field_name in tuple(capture_event()):
            missing = capture_event()
            del missing[field_name]
            schema_mutations.append(missing)
        wrong_type = capture_event()
        wrong_type["version"] = True
        schema_mutations.append(wrong_type)
        future_event = capture_event()
        future_event["event_type"] = "capture.updated"
        schema_mutations.append(future_event)
        forged_actor = capture_event()
        forged_actor["actor"]["actor_id"] = "caller-controlled"
        schema_mutations.append(forged_actor)
        unknown_actor_field = capture_event()
        unknown_actor_field["actor"]["display_name"] = "caller-controlled"
        schema_mutations.append(unknown_actor_field)

        for event in schema_mutations:
            with self.subTest(event=event), self.assertRaises(SchemaValidationError):
                validate_capture_event(event, envelope=self.envelope)

        for field_name, value in (
            ("event_id", "evt_01991a7e-7b21-72ae-9ef5-4f45249ad333"),
            ("capture_id", "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35422"),
            ("envelope_sha256", "sha256:" + ("f" * 64)),
        ):
            event = capture_event()
            event[field_name] = value
            with self.subTest(field=field_name), self.assertRaises(
                CaptureEventReferenceError
            ):
                validate_capture_event(event, envelope=self.envelope)

    def test_event_and_projection_require_canonical_source_bytes(self) -> None:
        event_golden = (FIXTURES / "capture-event-v1.yaml").read_bytes()
        state_golden = (FIXTURES / "capture-state-v1.yaml").read_bytes()
        for loader, golden in (
            (load_capture_event, event_golden),
            (load_capture_state, state_golden),
        ):
            noncanonical = golden.replace(b"schema_version: 1\n", b"schema_version: 01\n")
            with self.subTest(loader=loader), self.assertRaises(NonCanonicalYamlError):
                loader(noncanonical, envelope=self.envelope)

    def test_ct_22_contract_projection_is_complete_fixed_and_uses_one_time(self) -> None:
        structural_mutations = []
        missing = capture_state()
        del missing["backup"]
        structural_mutations.append(missing)
        unknown = capture_state()
        unknown["model_summary"] = "must not enter projection"
        structural_mutations.append(unknown)
        nested_unknown = capture_state()
        nested_unknown["routing"]["proposal"] = "must not enter projection"
        structural_mutations.append(nested_unknown)
        for state in structural_mutations:
            with self.subTest(state=state), self.assertRaises(SchemaValidationError):
                validate_capture_state(state, envelope=self.envelope)

        for path, value in (
            (("current_version",), 2),
            (("durability", "status"), "pending"),
            (("routing", "status"), "assigned"),
            (("routing", "target_kb_ids"), ["kb-private"]),
            (("trust", "status"), "trusted"),
            (("gbrain", "sync_status"), "pending"),
            (("backup", "git_status"), "committed"),
            (("updated_at",), "2026-09-02T01:02:03.007Z"),
        ):
            state = capture_state()
            target = state
            for segment in path[:-1]:
                target = target[segment]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(SchemaValidationError):
                validate_capture_state(state, envelope=self.envelope)

        wrong_reference = capture_state()
        wrong_reference["current_envelope_sha256"] = "sha256:" + ("f" * 64)
        with self.assertRaises(SchemaValidationError):
            validate_capture_state(wrong_reference, envelope=self.envelope)

    def test_ct_16_envelope_channel_actor_and_times_are_validated(self) -> None:
        invalid_values = []
        for field_name in ("received_at", "captured_at"):
            value = envelope_with_placeholder_hash()
            value[field_name] = "2026-09-02T01:02:03Z"
            invalid_values.append(value)
        invalid_source_time = envelope_with_placeholder_hash()
        invalid_source_time["channel"]["source_created_at"] = "2026-02-30T01:02:03.004Z"
        invalid_values.append(invalid_source_time)
        invalid_scope = envelope_with_placeholder_hash()
        invalid_scope["idempotency"]["scope"] = "app:another:capture_text"
        invalid_values.append(invalid_scope)
        forged_actor = envelope_with_placeholder_hash()
        forged_actor["actor"]["type"] = "service"
        invalid_values.append(forged_actor)

        for envelope in invalid_values:
            with self.subTest(envelope=envelope), self.assertRaises(
                SchemaValidationError
            ):
                validate_envelope(envelope)

    def test_ct_16_channel_token_reference_and_time_boundaries(self) -> None:
        exact = ChannelMetadata(
            type="a" * 64,
            instance_id="0._-" * 16,
            external_ref="é" * 1024,
            source_created_at="2026-09-02T01:02:03.004Z",
        )
        self.assertEqual(len(exact.external_ref.encode("utf-8")), 2048)

        for field_name, value in (
            ("type", ""),
            ("type", "A"),
            ("type", "app:local"),
            ("type", "app/local"),
            ("type", "应用"),
            ("type", "a" * 65),
            ("instance_id", "local desktop"),
            ("instance_id", "local\\desktop"),
        ):
            values = {"type": "app", "instance_id": "local-desktop"}
            values[field_name] = value
            with self.subTest(field=field_name, value=value), self.assertRaises(ValueError):
                ChannelMetadata(**values)

        with self.assertRaises(ValueError):
            ChannelMetadata(
                type="app",
                instance_id="local-desktop",
                external_ref=("é" * 1024) + "x",
            )
        for timestamp in (
            "2026-09-02T01:02:03Z",
            "2026-09-02T01:02:03.004+00:00",
            "2026-13-02T01:02:03.004Z",
        ):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                ChannelMetadata(
                    type="app",
                    instance_id="local-desktop",
                    source_created_at=timestamp,
                )

    def test_capture_text_request_surface_normalizes_omissions_and_rejects_overrides(self) -> None:
        channel = ChannelMetadata(type="app", instance_id="local-desktop")
        omitted = CaptureTextRequest(text=" \n", channel=channel)
        explicit = CaptureTextRequest(
            text=" \n",
            channel=ChannelMetadata(
                type="app",
                instance_id="local-desktop",
                external_ref=None,
                source_created_at=None,
            ),
            idempotency_key=None,
            user_intent=UserIntent(
                target_kb_id=None,
                processing_mode=None,
                requested_new_kb_name=None,
            ),
        )
        self.assertEqual(
            tuple(field.name for field in fields(CaptureTextRequest)),
            ("text", "channel", "idempotency_key", "user_intent"),
        )
        self.assertEqual(omitted.channel, explicit.channel)
        self.assertEqual(omitted.user_intent, explicit.user_intent)
        self.assertIs(omitted.text.__class__, str)
        self.assertIsInstance(
            CaptureTextRequest(text=io.BytesIO(b"text"), channel=channel).text,
            io.BytesIO,
        )

        for text in ("", "\ufeffprivate", b"direct-bytes"):
            with self.subTest(text=text), self.assertRaises((TypeError, ValueError)):
                CaptureTextRequest(text=text, channel=channel)
        with self.assertRaises(TypeError):
            CaptureTextRequest(
                **{
                    "text": "private",
                    "channel": channel,
                    "actor": {"type": "user", "actor_id": "attacker"},
                }
            )
        for key in ("", "é" * 256 + "x", 42):
            with self.subTest(key=key), self.assertRaises((TypeError, ValueError)):
                CaptureTextRequest(
                    text="private",
                    channel=channel,
                    idempotency_key=key,
                )

    def test_ct_11_contract_scope_key_digest_and_fingerprint_are_canonical(self) -> None:
        channel = ChannelMetadata(type="app", instance_id="local-desktop")
        self.assertEqual(
            canonical_idempotency_scope(channel, "capture_text"),
            "app:local-desktop:capture_text",
        )
        self.assertEqual(
            IDEMPOTENCY_KEY_DOMAIN,
            b"knowledgeflow.idempotency-key.v1\n",
        )
        self.assertEqual(
            idempotency_key_sha256("save-42"),
            "sha256:7abf493c572df85e3b8458dbbf94da71eb90d5b92f7bb2d39ce3ef2b7753fef2",
        )
        self.assertEqual(len(("é" * 256).encode("utf-8")), 512)
        idempotency_key_sha256("é" * 256)
        for key in ("", "é" * 256 + "x", 42):
            with self.subTest(key=key), self.assertRaises((TypeError, ValueError)):
                idempotency_key_sha256(key)
        for operation in ("Capture_Text", "capture:text", "delete"):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                canonical_idempotency_scope(channel, operation)

        omitted = CaptureTextRequest(text="body", channel=channel)
        explicit = CaptureTextRequest(
            text="body",
            channel=ChannelMetadata(
                type="app",
                instance_id="local-desktop",
                external_ref=None,
                source_created_at=None,
            ),
            user_intent=UserIntent(),
        )
        fingerprints = []
        for request in (omitted, explicit):
            fingerprints.append(
                request_fingerprint_sha256(
                    RequestFingerprint(
                        operation="capture_text",
                        payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
                        channel=request.channel,
                        payload_metadata=(PayloadMetadata(ordinal=0),),
                        user_intent=request.user_intent,
                    )
                )
            )
        self.assertEqual(fingerprints[0], fingerprints[1])

    def test_utc_millisecond_formatter_uses_aware_time_and_truncates_submilliseconds(self) -> None:
        local_time = datetime(
            2026,
            9,
            2,
            6,
            32,
            3,
            456789,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        )
        self.assertEqual(
            format_utc_milliseconds(local_time),
            "2026-09-02T01:02:03.456Z",
        )
        with self.assertRaises(TypeError):
            format_utc_milliseconds(datetime(2026, 9, 2, 1, 2, 3))


if __name__ == "__main__":
    unittest.main()
