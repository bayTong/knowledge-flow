from __future__ import annotations

from dataclasses import fields
import io
import unittest

import knowledgeflow_capture
from knowledgeflow_capture.errors import (
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.models import (
    CaptureItemState,
    CaptureListItem,
    CaptureReadMetadata,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
)
from .._samples import CAPTURE_ID, PAYLOAD_SHA256, SINGLE_PAYLOAD_SET_SHA256


CAPTURE_ID_2 = "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35422"
ENVELOPE_SHA256 = "sha256:" + ("a" * 64)


def read_metadata(*, capture_id: str = CAPTURE_ID) -> CaptureReadMetadata:
    return CaptureReadMetadata(
        capture_id=capture_id,
        version=1,
        current_version=2,
        fidelity="channel-exact",
        media_type="text/plain; charset=utf-8",
        encoding="utf-8",
        byte_size=16,
        primary_payload_sha256=PAYLOAD_SHA256,
        payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
        envelope_sha256=ENVELOPE_SHA256,
        captured_at="2026-09-02T01:02:03.004Z",
        channel=ChannelMetadata(
            type="app",
            instance_id="local-desktop",
            external_ref="must-not-leak",
            source_created_at="2026-09-02T01:02:03.004Z",
        ),
        user_intent=UserIntent(),
    )


def list_item(
    capture_id: str,
    *,
    captured_at: str = "2026-09-02T01:02:03.004Z",
) -> CaptureListItem:
    return CaptureListItem(
        capture_id=capture_id,
        current_version=2,
        captured_at=captured_at,
        updated_at="2026-09-13T00:00:00.005Z",
        preview="第一行\n🙂",
        routing_status="unassigned",
        trust_status="unreviewed-capture",
        envelope_sha256=ENVELOPE_SHA256,
    )


class ReadRequestModelTest(unittest.TestCase):
    def test_c4_read_contracts_are_public(self) -> None:
        for name in (
            "GetCaptureOperationResult",
            "GetCaptureRequest",
            "GetCaptureResult",
            "ListCapturesOperationResult",
            "ListCapturesRequest",
            "ListCapturesResult",
            "get_capture",
            "list_captures",
        ):
            with self.subTest(public=name):
                self.assertTrue(hasattr(knowledgeflow_capture, name))
                self.assertIn(name, knowledgeflow_capture.__all__)

    def test_get_request_has_only_contract_fields_and_validates_version(self) -> None:
        sink = io.BytesIO()
        request = GetCaptureRequest(
            capture_id=CAPTURE_ID,
            version=None,
            body_sink=sink,
        )

        self.assertEqual(
            tuple(field.name for field in fields(GetCaptureRequest)),
            ("capture_id", "version", "body_sink"),
        )
        self.assertIs(request.body_sink, sink)
        self.assertIsNone(request.version)
        for version in (1, 999999):
            self.assertEqual(
                GetCaptureRequest(
                    capture_id=CAPTURE_ID,
                    version=version,
                    body_sink=io.BytesIO(),
                ).version,
                version,
            )
        for version in (True, 0, 1000000, "1"):
            with self.subTest(version=version), self.assertRaises(
                (TypeError, ValueError)
            ):
                GetCaptureRequest(
                    capture_id=CAPTURE_ID,
                    version=version,
                    body_sink=io.BytesIO(),
                )
        with self.assertRaises((TypeError, ValueError)):
            GetCaptureRequest(
                capture_id="cap_not-an-id",
                version=None,
                body_sink=io.BytesIO(),
            )
        with self.assertRaises(TypeError):
            GetCaptureRequest(
                capture_id=CAPTURE_ID,
                version=None,
                body_sink=object(),
            )

    def test_list_request_normalizes_defaults_and_rejects_invalid_filters(self) -> None:
        request = ListCapturesRequest()
        self.assertEqual(
            request.as_query_mapping(),
            {
                "routing_status": None,
                "created_after": None,
                "created_before": None,
                "order": "captured_at-desc,capture_id-desc",
            },
        )
        self.assertEqual(request.limit, 50)
        self.assertIsNone(request.cursor)

        bounded = ListCapturesRequest(
            routing_status="unassigned",
            created_after="2026-09-01T00:00:00.000Z",
            created_before="2026-09-02T00:00:00.000Z",
            limit=100,
            cursor="c1.payload.checksum",
        )
        self.assertEqual(bounded.limit, 100)

        invalid_requests = (
            {"routing_status": "assigned"},
            {"created_after": "2026-09-01T00:00:00Z"},
            {
                "created_after": "2026-09-02T00:00:00.000Z",
                "created_before": "2026-09-02T00:00:00.000Z",
            },
            {"limit": 0},
            {"limit": 101},
            {"limit": True},
            {"cursor": ""},
            {"cursor": 42},
        )
        for values in invalid_requests:
            with self.subTest(values=values), self.assertRaises(
                (TypeError, ValueError)
            ):
                ListCapturesRequest(**values)


class ReadResultModelTest(unittest.TestCase):
    def test_get_result_has_exact_metadata_only_shape(self) -> None:
        metadata = read_metadata()
        warning = OperationWarning(
            code=WarningCode.PROJECTION_NEEDS_REBUILD,
            details={"capture_id": CAPTURE_ID},
        )
        result = GetCaptureResult(
            body_length_bytes=16,
            capture=metadata,
            item_state=CaptureItemState(),
            warnings=(warning,),
        ).to_dict()

        self.assertEqual(
            result,
            {
                "ok": True,
                "body_length_bytes": 16,
                "capture": {
                    "capture_id": CAPTURE_ID,
                    "version": 1,
                    "current_version": 2,
                    "fidelity": "channel-exact",
                    "media_type": "text/plain; charset=utf-8",
                    "encoding": "utf-8",
                    "byte_size": 16,
                    "primary_payload_sha256": PAYLOAD_SHA256,
                    "payload_set_sha256": SINGLE_PAYLOAD_SET_SHA256,
                    "envelope_sha256": ENVELOPE_SHA256,
                    "captured_at": "2026-09-02T01:02:03.004Z",
                    "channel": {
                        "type": "app",
                        "instance_id": "local-desktop",
                    },
                    "user_intent": {
                        "target_kb_id": None,
                        "processing_mode": None,
                        "requested_new_kb_name": None,
                    },
                },
                "item_state": {
                    "routing_status": "unassigned",
                    "trust_status": "unreviewed-capture",
                },
                "integrity": "verified",
                "warnings": [warning.to_dict()],
            },
        )
        self.assertNotIn("text", result)
        self.assertNotIn("commit_state", result)

        with self.assertRaises(ValueError):
            GetCaptureResult(
                body_length_bytes=15,
                capture=metadata,
                item_state=CaptureItemState(),
            )

    def test_list_result_requires_stable_item_order_and_sorts_warnings(self) -> None:
        first = list_item(CAPTURE_ID_2)
        second = list_item(CAPTURE_ID)
        warnings = (
            OperationWarning(
                code=WarningCode.PROJECTION_NEEDS_REBUILD,
                details={"capture_id": CAPTURE_ID_2},
            ),
            OperationWarning(
                code=WarningCode.INCOMPLETE_VERSION_IGNORED,
                details={"capture_id": CAPTURE_ID, "version": 3},
            ),
        )
        result = ListCapturesResult(
            items=(first, second),
            next_cursor=None,
            warnings=warnings,
        ).to_dict()

        self.assertEqual(
            [item["capture_id"] for item in result["items"]],
            [CAPTURE_ID_2, CAPTURE_ID],
        )
        self.assertEqual(
            [item["details"]["capture_id"] for item in result["warnings"]],
            [CAPTURE_ID, CAPTURE_ID_2],
        )
        self.assertNotIn("commit_state", result)

        with self.assertRaises(ValueError):
            ListCapturesResult(items=(second, first), next_cursor=None)

    def test_read_warning_and_output_error_shapes_are_strict(self) -> None:
        warning = OperationWarning(
            code=WarningCode.INCOMPLETE_VERSION_IGNORED,
            details={"capture_id": CAPTURE_ID, "version": 3},
        )
        self.assertEqual(
            warning.to_dict(),
            {
                "code": "incomplete_version_ignored",
                "message": "incomplete capture version was ignored",
                "details": {"capture_id": CAPTURE_ID, "version": 3},
            },
        )
        for details in ({}, {"capture_id": CAPTURE_ID}, {"version": 3}):
            with self.subTest(details=details), self.assertRaises(ValueError):
                OperationWarning(
                    code=WarningCode.INCOMPLETE_VERSION_IGNORED,
                    details=details,
                )

        error = OperationError(
            code=PublicErrorCode.OUTPUT_WRITE_FAILED,
            retryable=True,
        )
        self.assertEqual(error.message, "capture body output failed")
        failure = FailureResult(error=error).to_dict()
        self.assertNotIn("commit_state", failure)
        self.assertNotIn("saved", failure)


if __name__ == "__main__":
    unittest.main()
