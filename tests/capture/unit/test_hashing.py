from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import unittest

from knowledgeflow_capture.hashing import (
    ByteLimitExceeded,
    hash_bytes,
    hash_stream,
    payload_set_canonical_json,
    payload_set_sha256,
    request_fingerprint_canonical_json,
    request_fingerprint_sha256,
    seal_envelope,
    verify_envelope,
)
from knowledgeflow_capture.models import (
    ChannelMetadata,
    PayloadMetadata,
    PayloadSetEntry,
    RequestFingerprint,
    UserIntent,
)
from .._samples import (
    CAPTURE_ID,
    PAYLOAD_BYTES,
    PAYLOAD_SHA256,
    REQUEST_FINGERPRINT_SHA256,
    SINGLE_PAYLOAD_SET_SHA256,
    envelope_without_hash,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture_payload(path: str) -> bytes:
    data = (FIXTURES / path).read_bytes()
    if not data.endswith(b"\n") or data.endswith(b"\n\n"):
        raise AssertionError(f"text fixture {path} must end in exactly one LF")
    return data[:-1]


class ReadSizeTrackingStream(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.request_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.request_sizes.append(size)
        if size < 0:
            raise AssertionError("streaming hash must never request the whole stream")
        return super().read(size)


class HashingTest(unittest.TestCase):
    def test_payload_hashes_exact_bytes_without_normalization(self) -> None:
        stream = ReadSizeTrackingStream(PAYLOAD_BYTES)
        digest = hash_stream(stream, chunk_size=3)

        self.assertEqual(digest.byte_size, 16)
        self.assertEqual(digest.sha256, PAYLOAD_SHA256)
        self.assertGreater(len(stream.request_sizes), 2)
        self.assertNotEqual(hash_bytes(PAYLOAD_BYTES + b"\n").sha256, PAYLOAD_SHA256)

    def test_stream_limit_accepts_exact_boundary_and_rejects_first_excess(self) -> None:
        exact = hash_stream(io.BytesIO(b"1234"), chunk_size=2, maximum_bytes=4)
        self.assertEqual(exact.byte_size, 4)

        with self.assertRaises(ByteLimitExceeded) as raised:
            hash_stream(io.BytesIO(b"12345"), chunk_size=2, maximum_bytes=4)
        self.assertEqual(raised.exception.maximum_bytes, 4)
        self.assertEqual(raised.exception.byte_size, 5)

        oversized = ReadSizeTrackingStream(b"1234567890")
        with self.assertRaises(ByteLimitExceeded) as raised:
            hash_stream(oversized, chunk_size=1024, maximum_bytes=4)
        self.assertEqual(raised.exception.byte_size, 5)
        self.assertEqual(oversized.request_sizes, [5])

    def test_payload_set_sorts_by_ordinal_and_matches_golden_json(self) -> None:
        attachment = PayloadSetEntry(
            ordinal=1,
            role="attachment",
            kind="file",
            media_type="application/octet-stream",
            byte_size=11,
            sha256=(
                "sha256:72be2960332274dc79009b72a4f5f7b0c87aea569484ad4c2de6d96125ca8b5a"
            ),
        )
        primary = PayloadSetEntry(
            ordinal=0,
            role="primary",
            kind="text",
            media_type="text/plain; charset=utf-8",
            byte_size=16,
            sha256=PAYLOAD_SHA256,
        )

        canonical = payload_set_canonical_json((attachment, primary))

        self.assertEqual(canonical, fixture_payload("payload-set-v1.json"))
        self.assertEqual(
            payload_set_sha256((attachment, primary)),
            "sha256:9f8f0424dfc67719829ba14a2d53a193339dad455369f60490911d092f8b177e",
        )

    def test_duplicate_payload_ordinal_is_rejected(self) -> None:
        entry = PayloadSetEntry(
            ordinal=0,
            role="primary",
            kind="text",
            media_type="text/plain",
            byte_size=0,
            sha256="sha256:" + ("0" * 64),
        )
        with self.assertRaises(ValueError):
            payload_set_canonical_json((entry, entry))

    def test_request_fingerprint_matches_golden_and_changes_with_intent(self) -> None:
        request = RequestFingerprint(
            operation="capture_text",
            payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
            channel=ChannelMetadata(
                type="app",
                instance_id="local-desktop",
                external_ref="msg-42",
                source_created_at="2026-09-02T01:02:03.004Z",
            ),
            payload_metadata=(PayloadMetadata(ordinal=0, original_name=None),),
            user_intent=UserIntent(),
        )

        self.assertEqual(
            request_fingerprint_canonical_json(request),
            fixture_payload("request-fingerprint-v1.json"),
        )
        self.assertEqual(request_fingerprint_sha256(request), REQUEST_FINGERPRINT_SHA256)

        changed = replace(
            request,
            user_intent=UserIntent(processing_mode="deep-curation"),
        )
        self.assertNotEqual(
            request_fingerprint_sha256(changed),
            REQUEST_FINGERPRINT_SHA256,
        )

        changed_channel = replace(
            request,
            channel=replace(request.channel, external_ref="msg-43"),
        )
        changed_payload = replace(
            request,
            payload_set_sha256="sha256:" + ("f" * 64),
        )
        self.assertNotEqual(
            request_fingerprint_sha256(changed_channel),
            REQUEST_FINGERPRINT_SHA256,
        )
        self.assertNotEqual(
            request_fingerprint_sha256(changed_payload),
            REQUEST_FINGERPRINT_SHA256,
        )

    def test_append_fingerprint_requires_capture_and_expected_version(self) -> None:
        with self.assertRaises(ValueError):
            RequestFingerprint(
                operation="append_capture_version",
                payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
                channel=ChannelMetadata(type="app", instance_id="local-desktop"),
                payload_metadata=(PayloadMetadata(ordinal=0),),
                user_intent=UserIntent(),
            )

        request = RequestFingerprint(
            operation="append_capture_version",
            payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
            channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            payload_metadata=(PayloadMetadata(ordinal=0),),
            user_intent=UserIntent(),
            capture_id=CAPTURE_ID,
            expected_current_version=1,
        )
        self.assertIn(b'"capture_id":"cap_', request_fingerprint_canonical_json(request))

    def test_envelope_hash_excludes_its_own_field_and_matches_golden(self) -> None:
        original = envelope_without_hash()
        sealed = seal_envelope(original)

        self.assertNotIn("envelope_sha256", original)
        self.assertEqual(
            sealed.sha256,
            "sha256:d060313160f00566464a47a23f37d530a8cd77a100a6efcda591a7224c17515a",
        )
        self.assertTrue(verify_envelope(sealed.envelope))
        self.assertEqual(sealed.yaml_bytes, (FIXTURES / "envelope-v1.yaml").read_bytes())

        changed = dict(sealed.envelope)
        changed["captured_at"] = "2026-09-02T01:02:03.005Z"
        self.assertFalse(verify_envelope(changed))


if __name__ == "__main__":
    unittest.main()
