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
        with self.assertRaises(ValueError):
            PublicErrorCode("capture_root_not_configured")

    def test_public_error_without_lower_cause_serializes_null(self) -> None:
        error = OperationError(
            code=PublicErrorCode.VERSION_CONFLICT,
            retryable=False,
            details={"current_version": 3, "expected_current_version": 2},
        )

        self.assertIsNone(error.to_dict()["cause_code"])

    def test_projection_failure_is_committed_success_warning(self) -> None:
        result = CommittedWriteResult(
            receipt={"capture_id": "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421"},
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
                "capture_id": "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35421",
                "warnings": [
                    {
                        "code": "projection_needs_rebuild",
                        "message": "capture state projection needs rebuild",
                        "details": {},
                    }
                ],
            },
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
            {"preview": "private note"},
            {"idempotency_key": "raw-key"},
            {"idempotencyKey": "raw-key"},
            {"credentials": "secret"},
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

    def test_receipt_cannot_override_reserved_or_embed_payload_text(self) -> None:
        for receipt in ({"ok": False}, {"text": "private note"}):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                CommittedWriteResult(receipt=receipt)


if __name__ == "__main__":
    unittest.main()
