from __future__ import annotations

import unittest

from knowledgeflow_capture.errors import (
    CauseCode,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
    WarningCode,
)
from .._samples import (
    CAPTURE_ID,
    EVENT_ID,
    PAYLOAD_SHA256,
    SINGLE_PAYLOAD_SET_SHA256,
)


ENVELOPE_SHA256 = (
    "sha256:d060313160f00566464a47a23f37d530a8cd77a100a6efcda591a7224c17515a"
)


def capture_text_receipt() -> dict[str, object]:
    return {
        "capture_id": CAPTURE_ID,
        "event_id": EVENT_ID,
        "version": 1,
        "primary_payload_sha256": PAYLOAD_SHA256,
        "payload_set_sha256": SINGLE_PAYLOAD_SET_SHA256,
        "envelope_sha256": ENVELOPE_SHA256,
        "durability": "durable",
        "routing_status": "unassigned",
        "trust_status": "unreviewed-capture",
        "gbrain_sync_status": "not-requested",
    }


class ErrorModelTest(unittest.TestCase):
    def test_integrity_failure_has_stable_public_and_diagnostic_layers(self) -> None:
        result = FailureResult(
            error=OperationError(
                code=PublicErrorCode.INTEGRITY_CHECK_FAILED,
                cause_code=CauseCode.PAYLOAD_HASH_MISMATCH,
                retryable=False,
            ),
            commit_state=CommitState.NOT_COMMITTED,
        )

        self.assertEqual(
            result.to_dict(),
            {
                "ok": False,
                "commit_state": "not-committed",
                "error": {
                    "code": "integrity_check_failed",
                    "cause_code": "payload_hash_mismatch",
                    "message": "stored data failed integrity verification",
                    "retryable": False,
                    "details": {},
                },
            },
        )

    def test_config_codes_are_distinct_and_deprecated_code_is_absent(self) -> None:
        self.assertEqual(PublicErrorCode.CONFIG_NOT_FOUND, "config_not_found")
        self.assertEqual(PublicErrorCode.CONFIG_INVALID, "config_invalid")
        self.assertEqual(
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            "unrecognized_existing_directory",
        )
        self.assertEqual(
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
            "unsupported_store_version",
        )
        self.assertEqual(
            PublicErrorCode.CONFIG_STORE_CONFLICT,
            "config_store_conflict",
        )
        with self.assertRaises(ValueError):
            PublicErrorCode("capture_root_not_configured")

    def test_c2_initialization_codes_have_stable_safe_messages(self) -> None:
        for code in (
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY,
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
            PublicErrorCode.CONFIG_STORE_CONFLICT,
        ):
            with self.subTest(code=code):
                serialized = OperationError(code=code, retryable=False).to_dict()
                self.assertEqual(serialized["code"], code.value)
                self.assertIsInstance(serialized["message"], str)
                self.assertNotIn("\\", serialized["message"])
                self.assertNotIn("/", serialized["message"])

    def test_public_error_without_lower_cause_serializes_null(self) -> None:
        error = OperationError(
            code=PublicErrorCode.VERSION_CONFLICT,
            retryable=False,
            details={"current_version": 3, "expected_current_version": 2},
        )

        self.assertIsNone(error.to_dict()["cause_code"])

    def test_projection_failure_is_committed_success_warning(self) -> None:
        result = CommittedWriteResult(
            receipt=capture_text_receipt(),
            warnings=(
                OperationWarning(code=WarningCode.PROJECTION_NEEDS_REBUILD),
            ),
        )

        self.assertEqual(
            result.to_dict(),
            {
                "ok": True,
                "saved": True,
                "commit_state": "committed",
                **capture_text_receipt(),
                "warnings": [
                    {
                        "code": "projection_needs_rebuild",
                        "message": "capture state projection needs rebuild",
                        "details": {},
                    }
                ],
            },
        )
        clean = CommittedWriteResult(receipt=capture_text_receipt()).to_dict()
        warned = result.to_dict()
        self.assertEqual(
            {key: value for key, value in clean.items() if key != "warnings"},
            {key: value for key, value in warned.items() if key != "warnings"},
        )

    def test_capture_text_receipt_requires_exact_operation_fields(self) -> None:
        expected = capture_text_receipt()
        self.assertEqual(
            CommittedWriteResult(receipt=expected).to_dict(),
            {
                "ok": True,
                "saved": True,
                "commit_state": "committed",
                **expected,
                "warnings": [],
            },
        )

        for missing_field in tuple(expected):
            incomplete = dict(expected)
            del incomplete[missing_field]
            with self.subTest(missing=missing_field), self.assertRaises(ValueError):
                CommittedWriteResult(receipt=incomplete)

        extra = dict(expected)
        extra["previous_version"] = None
        with self.assertRaises(ValueError):
            CommittedWriteResult(receipt=extra)

        wrong_version = dict(expected)
        wrong_version["version"] = 2
        with self.assertRaises(ValueError):
            CommittedWriteResult(receipt=wrong_version)

    def test_all_public_error_messages_are_exact_contract_values(self) -> None:
        expected = {
            PublicErrorCode.CONFIG_NOT_FOUND: "capture configuration was not found",
            PublicErrorCode.CONFIG_INVALID: "capture configuration is invalid",
            PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY: (
                "existing directory is not a recognized capture store"
            ),
            PublicErrorCode.UNSUPPORTED_STORE_VERSION: (
                "capture store schema or layout version is unsupported"
            ),
            PublicErrorCode.CONFIG_STORE_CONFLICT: (
                "capture configuration conflicts with the requested store"
            ),
            PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED: (
                "capture store is not initialized"
            ),
            PublicErrorCode.CAPTURE_STORE_UNAVAILABLE: "capture store is unavailable",
            PublicErrorCode.INVALID_INPUT: "request input is invalid",
            PublicErrorCode.TEXT_TOO_LARGE: "text exceeds the configured safety limit",
            PublicErrorCode.CAPTURE_NOT_FOUND: "capture was not found",
            PublicErrorCode.VERSION_NOT_FOUND: "capture version was not found",
            PublicErrorCode.VERSION_CONFLICT: "capture version changed since it was read",
            PublicErrorCode.IDEMPOTENCY_CONFLICT: (
                "idempotency key refers to a different request"
            ),
            PublicErrorCode.INTEGRITY_CHECK_FAILED: (
                "stored data failed integrity verification"
            ),
            PublicErrorCode.ATOMIC_COMMIT_FAILED: "atomic capture commit failed",
        }
        self.assertEqual(
            {
                code: OperationError(code=code, retryable=False).message
                for code in PublicErrorCode
                if code is not PublicErrorCode.INTEGRITY_CHECK_FAILED
            },
            {
                code: message
                for code, message in expected.items()
                if code is not PublicErrorCode.INTEGRITY_CHECK_FAILED
            },
        )
        self.assertEqual(
            OperationError(
                code=PublicErrorCode.INTEGRITY_CHECK_FAILED,
                cause_code=CauseCode.EVENT_MISSING,
                retryable=False,
            ).message,
            expected[PublicErrorCode.INTEGRITY_CHECK_FAILED],
        )

    def test_capture_event_integrity_causes_map_only_to_public_integrity_error(self) -> None:
        for cause in (
            CauseCode.EVENT_MISSING,
            CauseCode.EVENT_SCHEMA_INVALID,
            CauseCode.EVENT_REFERENCE_MISMATCH,
        ):
            with self.subTest(cause=cause):
                error = OperationError(
                    code=PublicErrorCode.INTEGRITY_CHECK_FAILED,
                    cause_code=cause,
                    retryable=False,
                )
                self.assertEqual(error.to_dict()["cause_code"], cause.value)
                with self.assertRaises(ValueError):
                    OperationError(
                        code=PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                        cause_code=cause,
                        retryable=False,
                    )

    def test_unknown_commit_is_failure_but_never_claims_saved_false(self) -> None:
        result = FailureResult(
            error=OperationError(
                code=PublicErrorCode.ATOMIC_COMMIT_FAILED,
                retryable=True,
            ),
            commit_state=CommitState.UNKNOWN,
        ).to_dict()

        self.assertEqual(result["commit_state"], "unknown")
        self.assertNotIn("saved", result)

    def test_failure_cannot_claim_committed(self) -> None:
        with self.assertRaises(ValueError):
            FailureResult(
                error=OperationError(
                    code=PublicErrorCode.ATOMIC_COMMIT_FAILED,
                    retryable=True,
                ),
                commit_state=CommitState.COMMITTED,
            )

    def test_internal_integrity_and_post_commit_causes_cannot_escape_mapping(self) -> None:
        with self.assertRaises(ValueError):
            OperationError(
                code=PublicErrorCode.INVALID_INPUT,
                cause_code=CauseCode.PAYLOAD_HASH_MISMATCH,
                retryable=False,
            )
        with self.assertRaises(ValueError):
            OperationError(
                code=PublicErrorCode.INTEGRITY_CHECK_FAILED,
                retryable=False,
            )
        with self.assertRaises(ValueError):
            OperationError(
                code=PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                cause_code=CauseCode.PROJECTION_UPDATE_FAILED,
                retryable=True,
            )

    def test_diagnostics_reject_sensitive_fields_and_paths(self) -> None:
        unsafe_details = (
            {"text": "private note"},
            {"payload_text": "private note"},
            {"preview": "private note"},
            {"text_preview": "private note"},
            {"idempotency_key": "raw-key"},
            {"idempotencyKey": "raw-key"},
            {"credentials": "secret"},
            {"reason": "private note"},
            {"path": r"E:\Private\note.txt"},
            {"location": r"E:\Private\note.txt"},
            {"location": r"failed at E:\Private\note.txt"},
            {"location": "failed at /home/private/note.txt"},
        )
        for details in unsafe_details:
            with self.subTest(details=details), self.assertRaises(ValueError):
                OperationError(
                    code=PublicErrorCode.INVALID_INPUT,
                    retryable=False,
                    details=details,
                )

    def test_diagnostics_accept_only_typed_allowlisted_fields(self) -> None:
        error = OperationError(
            code=PublicErrorCode.VERSION_CONFLICT,
            retryable=False,
            details={
                "stage": "version-check",
                "current_version": 3,
                "expected_current_version": 2,
            },
        )

        self.assertEqual(
            error.to_dict()["details"],
            {
                "stage": "version-check",
                "current_version": 3,
                "expected_current_version": 2,
            },
        )
        for details in (
            {"stage": "contains private note"},
            {"stage": r"E:\Private\note.txt"},
            {"current_version": True},
            {"observed_bytes": -1},
            {"maximum_bytes": "64"},
            {"stage": {"text": "private note"}},
        ):
            with self.subTest(details=details), self.assertRaises(ValueError):
                OperationError(
                    code=PublicErrorCode.INVALID_INPUT,
                    retryable=False,
                    details=details,
                )

    def test_r03f_cleanup_stage_is_a_safe_typed_diagnostic_token(self) -> None:
        error = OperationError(
            code=PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
            retryable=False,
            details={
                "stage": "file-readback",
                "cleanup_stage": "transaction-cleanup-identity",
            },
        )

        self.assertEqual(
            error.to_dict()["details"],
            {
                "stage": "file-readback",
                "cleanup_stage": "transaction-cleanup-identity",
            },
        )
        for cleanup_stage in (
            "contains private note",
            r"E:\Private\note.txt",
            "/home/private/note.txt",
            {"text": "private note"},
            32,
        ):
            with self.subTest(cleanup_stage=cleanup_stage), self.assertRaises(
                ValueError
            ):
                OperationError(
                    code=PublicErrorCode.CAPTURE_STORE_UNAVAILABLE,
                    retryable=False,
                    details={"cleanup_stage": cleanup_stage},
                )

    def test_receipt_cannot_override_reserved_or_embed_payload_text(self) -> None:
        for receipt in (
            {"ok": False},
            {"text": "private note"},
            {"payload_text": "private note"},
            {"reason": "private note"},
            {"capture_id": "private note"},
            {"version": True},
        ):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                CommittedWriteResult(receipt=receipt)


if __name__ == "__main__":
    unittest.main()
