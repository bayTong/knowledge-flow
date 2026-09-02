"""Deterministic C1 sample values shared by unit tests."""

from __future__ import annotations


PAYLOAD_TEXT = "知识\r\nidea🙂"
PAYLOAD_BYTES = PAYLOAD_TEXT.encode("utf-8")
PAYLOAD_SHA256 = (
    "sha256:d3f0fb6e5ca5021a950fc93f1deedcc6a5521fd7a69af8d26f7f7452a3008298"
)
SINGLE_PAYLOAD_SET_SHA256 = (
    "sha256:8f112ab0af3a0688c6809595938b35755df53b3129442438f2a513b30270f4fb"
)
REQUEST_FINGERPRINT_SHA256 = (
    "sha256:90c872a3da189be3e748f0c517dc4cfe14434c4537c94a0b40e6d403100ca1db"
)

CAPTURE_ID = "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
EVENT_ID = "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332"


def envelope_without_hash() -> dict[str, object]:
    """Return a fresh, valid Envelope v1 sample without its self-hash."""

    return {
        "schema": "knowledgeflow.capture-envelope",
        "schema_version": 1,
        "capture_id": CAPTURE_ID,
        "event_id": EVENT_ID,
        "version": 1,
        "previous_version": None,
        "received_at": "2026-09-02T01:02:03.001Z",
        "captured_at": "2026-09-02T01:02:03.004Z",
        "actor": {
            "type": "user",
            "actor_id": "local-user",
        },
        "channel": {
            "type": "app",
            "instance_id": "local-desktop",
            "external_ref": "msg-42",
            "source_created_at": "2026-09-02T01:02:03.004Z",
        },
        "idempotency": {
            "scope": "app:local-desktop:capture_text",
            "key_sha256": "sha256:" + ("1" * 64),
            "request_fingerprint_sha256": REQUEST_FINGERPRINT_SHA256,
        },
        "payloads": [
            {
                "payload_id": PAYLOAD_SHA256,
                "ordinal": 0,
                "role": "primary",
                "kind": "text",
                "path": "payloads/primary.txt",
                "original_name": None,
                "media_type": "text/plain; charset=utf-8",
                "encoding": "utf-8",
                "fidelity": "channel-exact",
                "byte_size": len(PAYLOAD_BYTES),
                "sha256": PAYLOAD_SHA256,
            }
        ],
        "payload_set_sha256": SINGLE_PAYLOAD_SET_SHA256,
        "user_intent": {
            "target_kb_id": None,
            "processing_mode": None,
            "requested_new_kb_name": None,
            "evidence": {
                "event_id": EVENT_ID,
                "payload_id": PAYLOAD_SHA256,
            },
        },
        "delivery_requests": [],
        "envelope_serialization": {
            "encoding": "utf-8",
            "line_endings": "lf",
            "bom": False,
            "key_order": "schema-defined",
        },
    }


def envelope_with_placeholder_hash() -> dict[str, object]:
    envelope = envelope_without_hash()
    envelope["envelope_sha256"] = "sha256:" + ("0" * 64)
    return envelope
