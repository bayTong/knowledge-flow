from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from knowledgeflow_capture.codec import (
    CaptureEventReferenceError,
    SchemaValidationError,
    dump_capture_event,
    dump_envelope,
    load_capture_event,
    load_envelope,
    validate_capture_event,
    validate_capture_state,
)
from knowledgeflow_capture.hashing import hash_bytes, verify_envelope
from knowledgeflow_capture.store import (
    _CaptureVersionChainError,
    _build_capture_version_chain,
    _parse_capture_version_directory_name,
    _rebuild_capture_read_state,
    _warnings_for_capture_version_chain,
)
from .._samples import CAPTURE_ID


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class CaptureVersionGoldenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope_1_bytes = (FIXTURES / "envelope-v1.yaml").read_bytes()
        self.envelope_2_bytes = (FIXTURES / "envelope-v2.yaml").read_bytes()
        self.event_1_bytes = (FIXTURES / "capture-event-v1.yaml").read_bytes()
        self.event_2_bytes = (
            FIXTURES / "capture-version-appended-event-v1.yaml"
        ).read_bytes()
        self.envelope_1 = load_envelope(self.envelope_1_bytes)
        self.envelope_2 = load_envelope(self.envelope_2_bytes)
        self.event_1 = load_capture_event(
            self.event_1_bytes,
            envelope=self.envelope_1,
        )
        self.event_2 = load_capture_event(
            self.event_2_bytes,
            envelope=self.envelope_2,
            previous_envelope=self.envelope_1,
        )

    def test_two_version_envelope_event_and_payload_are_real_golden_bytes(self) -> None:
        payload = (FIXTURES / "payload-v2.txt").read_bytes()
        self.assertEqual(
            hash_bytes(payload).sha256,
            "sha256:46dfe923de44197882c79f26f96d9d4845a299ed99880601652833233fb5080e",
        )
        self.assertEqual(len(payload), 25)
        self.assertTrue(verify_envelope(self.envelope_1))
        self.assertTrue(verify_envelope(self.envelope_2))
        self.assertEqual(dump_envelope(self.envelope_2), self.envelope_2_bytes)
        self.assertEqual(
            dump_capture_event(
                self.event_2,
                envelope=self.envelope_2,
                previous_envelope=self.envelope_1,
            ),
            self.event_2_bytes,
        )
        self.assertEqual(
            dump_capture_event(self.event_1, envelope=self.envelope_1),
            self.event_1_bytes,
        )

    def test_appended_event_schema_and_both_envelope_references_are_strict(self) -> None:
        for field_name in (
            "previous_version",
            "previous_envelope_sha256",
        ):
            event = deepcopy(self.event_2)
            del event[field_name]
            with self.subTest(missing=field_name), self.assertRaises(
                SchemaValidationError
            ):
                validate_capture_event(
                    event,
                    envelope=self.envelope_2,
                    previous_envelope=self.envelope_1,
                )

        for field_name, value in (
            ("version", 1),
            ("version", True),
            ("version", 1000000),
            ("previous_version", 2),
        ):
            event = deepcopy(self.event_2)
            event[field_name] = value
            with self.subTest(field=field_name, value=value), self.assertRaises(
                SchemaValidationError
            ):
                validate_capture_event(
                    event,
                    envelope=self.envelope_2,
                    previous_envelope=self.envelope_1,
                )

        for field_name, value in (
            ("previous_envelope_sha256", "sha256:" + ("f" * 64)),
            ("envelope_sha256", "sha256:" + ("e" * 64)),
        ):
            event = deepcopy(self.event_2)
            event[field_name] = value
            with self.subTest(field=field_name), self.assertRaises(
                CaptureEventReferenceError
            ):
                validate_capture_event(
                    event,
                    envelope=self.envelope_2,
                    previous_envelope=self.envelope_1,
                )

        with self.assertRaises(CaptureEventReferenceError):
            validate_capture_event(
                self.event_2,
                envelope=self.envelope_2,
                previous_envelope=None,
            )

    def test_created_event_cannot_accept_appended_fields_and_projection_stays_c3(self) -> None:
        mixed = deepcopy(self.event_1)
        mixed["previous_version"] = 0
        with self.assertRaises(SchemaValidationError):
            validate_capture_event(mixed, envelope=self.envelope_1)

        projection = {
            "schema": "knowledgeflow.capture-state",
            "schema_version": 1,
            "capture_id": CAPTURE_ID,
            "current_version": 2,
            "current_envelope_sha256": self.envelope_2["envelope_sha256"],
            "durability": {
                "status": "durable",
                "verified_at": "2026-09-13T00:00:00.005Z",
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
            "updated_at": "2026-09-13T00:00:00.005Z",
        }
        with self.assertRaises(SchemaValidationError):
            validate_capture_state(projection, envelope=self.envelope_2)


class CaptureVersionChainPrimitiveTest(unittest.TestCase):
    def setUp(self) -> None:
        envelope_1 = load_envelope((FIXTURES / "envelope-v1.yaml").read_bytes())
        envelope_2 = load_envelope((FIXTURES / "envelope-v2.yaml").read_bytes())
        event_1 = load_capture_event(
            (FIXTURES / "capture-event-v1.yaml").read_bytes(),
            envelope=envelope_1,
        )
        event_2 = load_capture_event(
            (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes(),
            envelope=envelope_2,
            previous_envelope=envelope_1,
        )
        self.envelopes = {1: envelope_1, 2: envelope_2}
        self.events = (event_1, event_2)

    def build(
        self,
        *,
        names: tuple[str, ...] = ("000001", "000002"),
        envelopes: dict[int, object] | None = None,
        events: tuple[object, ...] | None = None,
    ):
        return _build_capture_version_chain(
            capture_id=CAPTURE_ID,
            version_directory_names=names,
            envelopes_by_version=self.envelopes if envelopes is None else envelopes,
            events=self.events if events is None else events,
        )

    def test_six_digit_version_parser_is_exact(self) -> None:
        self.assertEqual(_parse_capture_version_directory_name("000001"), 1)
        self.assertEqual(_parse_capture_version_directory_name("999999"), 999999)
        for value in ("000000", "1", "0000001", "０００００１", True):
            with self.subTest(value=value), self.assertRaises(
                _CaptureVersionChainError
            ):
                _parse_capture_version_directory_name(value)

    def test_two_version_chain_and_in_memory_state_use_immutable_sources(self) -> None:
        chain = self.build()
        state = _rebuild_capture_read_state(chain)

        self.assertEqual(chain.current_version, 2)
        self.assertIsNone(chain.incomplete_version)
        self.assertEqual(state.capture_id, CAPTURE_ID)
        self.assertEqual(state.current_version, 2)
        self.assertEqual(
            state.current_envelope_sha256,
            self.envelopes[2]["envelope_sha256"],
        )
        self.assertEqual(state.captured_at, self.envelopes[1]["captured_at"])
        self.assertEqual(state.updated_at, self.events[1]["occurred_at"])
        self.assertEqual(state.routing_status, "unassigned")
        self.assertEqual(state.trust_status, "unreviewed-capture")
        self.assertEqual(_warnings_for_capture_version_chain(chain), ())

    def test_single_version_chain_is_a_complete_readable_prefix(self) -> None:
        chain = self.build(
            names=("000001",),
            envelopes={1: self.envelopes[1]},
            events=(self.events[0],),
        )

        self.assertEqual(chain.current_version, 1)
        self.assertIsNone(chain.incomplete_version)
        self.assertEqual(chain.version(1).envelope, self.envelopes[1])
        self.assertIsNone(chain.version(2))
        self.assertEqual(_warnings_for_capture_version_chain(chain), ())

    def test_exactly_one_next_version_without_event_is_an_ignored_tail(self) -> None:
        chain = self.build(names=("000001", "000002", "000003"))
        self.assertEqual(chain.current_version, 2)
        self.assertEqual(chain.incomplete_version, 3)
        self.assertEqual(
            tuple(warning.to_dict() for warning in _warnings_for_capture_version_chain(chain)),
            (
                {
                    "code": "incomplete_version_ignored",
                    "message": "incomplete capture version was ignored",
                    "details": {"capture_id": CAPTURE_ID, "version": 3},
                },
            ),
        )

    def test_gaps_multiple_tails_or_orphan_and_duplicate_events_fail_closed(self) -> None:
        invalid_cases = (
            {"names": ("000001", "000002", "000004")},
            {"names": ("000001", "000002", "000003", "000004")},
            {
                "names": ("000001",),
                "envelopes": {1: self.envelopes[1]},
                "events": self.events,
            },
            {"events": self.events + (self.events[1],)},
            {
                "events": (self.events[0],),
                "envelopes": {1: self.envelopes[1], 2: self.envelopes[2]},
                "names": ("000001", "000002", "000003"),
            },
        )
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaises(
                _CaptureVersionChainError
            ):
                self.build(**values)

    def test_event_reference_mismatch_or_missing_committed_envelope_fails(self) -> None:
        forged_event = deepcopy(self.events[1])
        forged_event["previous_envelope_sha256"] = "sha256:" + ("f" * 64)
        with self.assertRaises(_CaptureVersionChainError):
            self.build(events=(self.events[0], forged_event))

        with self.assertRaises(_CaptureVersionChainError):
            self.build(envelopes={1: self.envelopes[1]})


if __name__ == "__main__":
    unittest.main()
