from __future__ import annotations

import base64
import hashlib
import json
import unittest

from knowledgeflow_capture.codec import (
    CAPTURE_LIST_CURSOR_DOMAIN,
    CAPTURE_LIST_QUERY_DOMAIN,
    capture_list_query_canonical_json,
    capture_list_query_sha256,
    decode_capture_list_cursor,
    encode_capture_list_cursor,
)
from knowledgeflow_capture.models import ListCapturesRequest
from .._samples import CAPTURE_ID


STORE_ID = "store_01991a7e-7b20-7a31-8d14-0b8ab6b35421"
STORE_ID_2 = "store_01991a7e-7b20-7a31-8d14-0b8ab6b35422"
CAPTURED_AT = "2026-09-02T01:02:03.004Z"
QUERY_JSON = (
    b'{"routing_status":null,"created_after":null,"created_before":null,'
    b'"order":"captured_at-desc,capture_id-desc"}'
)
QUERY_SHA256 = (
    "sha256:554a421919399cb741a607178d99c3a9a96aec6665933d058417fa57b0864c87"
)
CURSOR_TOKEN = (
    "c1.eyJzY2hlbWEiOiJrbm93bGVkZ2VmbG93LmNhcHR1cmUtbGlzdC1jdXJzb3IiLCJzY2hl"
    "bWFfdmVyc2lvbiI6MSwic3RvcmVfaWQiOiJzdG9yZV8wMTk5MWE3ZS03YjIwLTdhMzEtOGQx"
    "NC0wYjhhYjZiMzU0MjEiLCJxdWVyeV9zaGEyNTYiOiJzaGEyNTY6NTU0YTQyMTkxOTM5OWNi"
    "NzQxYTYwNzE3OGQ5OWMzYTlhOTZhZWM2NjY1OTMzZDA1ODQxN2ZhNTdiMDg2NGM4NyIsImxh"
    "c3RfY2FwdHVyZWRfYXQiOiIyMDI2LTA5LTAyVDAxOjAyOjAzLjAwNFoiLCJsYXN0X2NhcHR1"
    "cmVfaWQiOiJjYXBfMDE5OTFhN2UtN2IyMC03YTMxLThkMTQtMGI4YWI2YjM1NDIxIn0."
    "315dab231b854ecb1fc608d65d0e48039f2a6b708861b93382e4540fd03d105e"
)


def signed_cursor_token(payload: bytes) -> str:
    payload_segment = base64.urlsafe_b64encode(payload).rstrip(b"=")
    checksum = hashlib.sha256(CAPTURE_LIST_CURSOR_DOMAIN + payload).hexdigest()
    return "c1." + payload_segment.decode("ascii") + "." + checksum


class CaptureListCursorCodecTest(unittest.TestCase):
    def test_query_fingerprint_and_cursor_match_fixed_canonical_bytes(self) -> None:
        request = ListCapturesRequest()

        self.assertEqual(
            CAPTURE_LIST_QUERY_DOMAIN,
            b"knowledgeflow.capture-list-query.v1\n",
        )
        self.assertEqual(
            CAPTURE_LIST_CURSOR_DOMAIN,
            b"knowledgeflow.capture-list-cursor.v1\n",
        )
        self.assertEqual(capture_list_query_canonical_json(request), QUERY_JSON)
        self.assertEqual(capture_list_query_sha256(request), QUERY_SHA256)
        self.assertEqual(
            encode_capture_list_cursor(
                store_id=STORE_ID,
                request=request,
                last_captured_at=CAPTURED_AT,
                last_capture_id=CAPTURE_ID,
            ),
            CURSOR_TOKEN,
        )

        decoded = decode_capture_list_cursor(
            CURSOR_TOKEN,
            store_id=STORE_ID,
            request=request,
        )
        self.assertEqual(decoded.store_id, STORE_ID)
        self.assertEqual(decoded.query_sha256, QUERY_SHA256)
        self.assertEqual(decoded.last_captured_at, CAPTURED_AT)
        self.assertEqual(decoded.last_capture_id, CAPTURE_ID)

    def test_limit_is_not_bound_but_store_and_query_are_bound(self) -> None:
        token = encode_capture_list_cursor(
            store_id=STORE_ID,
            request=ListCapturesRequest(limit=1),
            last_captured_at=CAPTURED_AT,
            last_capture_id=CAPTURE_ID,
        )
        decode_capture_list_cursor(
            token,
            store_id=STORE_ID,
            request=ListCapturesRequest(limit=100),
        )

        for store_id, request in (
            (STORE_ID_2, ListCapturesRequest()),
            (STORE_ID, ListCapturesRequest(routing_status="unassigned")),
            (
                STORE_ID,
                ListCapturesRequest(
                    created_after="2026-09-01T00:00:00.000Z"
                ),
            ),
        ):
            with self.subTest(store_id=store_id, request=request), self.assertRaises(
                ValueError
            ):
                decode_capture_list_cursor(
                    token,
                    store_id=store_id,
                    request=request,
                )

    def test_malformed_tampered_and_noncanonical_tokens_are_rejected(self) -> None:
        prefix, payload_segment, checksum = CURSOR_TOKEN.split(".")
        tampered_checksum = checksum[:-1] + ("0" if checksum[-1] != "0" else "1")

        payload = base64.urlsafe_b64decode(payload_segment + "==")
        parsed = json.loads(payload)
        noncanonical_payload = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        duplicate_key_payload = (
            b'{"schema":"knowledgeflow.capture-list-cursor",' + payload[1:]
        )
        unknown_field_payload = payload[:-1] + b',"unknown":null}'

        invalid_tokens = (
            "",
            "c2." + payload_segment + "." + checksum,
            prefix + "." + payload_segment + "=." + checksum,
            prefix + "." + payload_segment + "." + tampered_checksum,
            CURSOR_TOKEN + "\n",
            signed_cursor_token(noncanonical_payload),
            signed_cursor_token(duplicate_key_payload),
            signed_cursor_token(unknown_field_payload),
        )
        for token in invalid_tokens:
            with self.subTest(token=token[:24]), self.assertRaises(ValueError):
                decode_capture_list_cursor(
                    token,
                    store_id=STORE_ID,
                    request=ListCapturesRequest(),
                )

    def test_cursor_boundaries_validate_typed_ids_and_canonical_time(self) -> None:
        invalid_values = (
            {"store_id": "store_invalid"},
            {"last_capture_id": "cap_invalid"},
            {"last_captured_at": "2026-09-02T01:02:03Z"},
        )
        base = {
            "store_id": STORE_ID,
            "request": ListCapturesRequest(),
            "last_captured_at": CAPTURED_AT,
            "last_capture_id": CAPTURE_ID,
        }
        for changes in invalid_values:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                encode_capture_list_cursor(**{**base, **changes})


if __name__ == "__main__":
    unittest.main()
