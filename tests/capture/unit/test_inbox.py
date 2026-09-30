from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.errors import (
    AppendCaptureVersionResult,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.inbox import InboxOperationBoundary, InboxSession
from knowledgeflow_capture.models import (
    CaptureItemState,
    CaptureListItem,
    CaptureReadMetadata,
    ChannelMetadata,
    UserIntent,
)
from knowledgeflow_capture.paths import PathPolicy

from .._samples import (
    CAPTURE_ID,
    EVENT_ID,
    PAYLOAD_SHA256,
    SINGLE_PAYLOAD_SET_SHA256,
)


CAPTURE_ID_2 = "cap_01991a7e-7b20-7a31-8d14-0b8ab6b35422"
ENVELOPE_SHA256 = "sha256:" + ("a" * 64)
CURSOR = "c1.page." + ("b" * 64)


def _failure(
    code: PublicErrorCode,
    *,
    commit_state: CommitState | None = None,
    retryable: bool = False,
) -> FailureResult:
    return FailureResult(
        error=OperationError(code=code, retryable=retryable),
        commit_state=commit_state,
    )


def _capture_receipt() -> dict[str, object]:
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


def _append_receipt() -> dict[str, object]:
    result = _capture_receipt()
    result["previous_version"] = 1
    result["version"] = 2
    return result


def _item(capture_id: str, timestamp: str) -> CaptureListItem:
    return CaptureListItem(
        capture_id=capture_id,
        current_version=1,
        captured_at=timestamp,
        updated_at=timestamp,
        preview="预览🙂",
        routing_status="unassigned",
        trust_status="unreviewed-capture",
        envelope_sha256=ENVELOPE_SHA256,
    )


def _read_result(body: bytes, *, warning: bool = False) -> GetCaptureResult:
    warnings = (
        (
            OperationWarning(
                code=WarningCode.PROJECTION_NEEDS_REBUILD,
                details={"capture_id": CAPTURE_ID},
            ),
        )
        if warning
        else ()
    )
    return GetCaptureResult(
        body_length_bytes=len(body),
        capture=CaptureReadMetadata(
            capture_id=CAPTURE_ID,
            version=1,
            current_version=1,
            fidelity="channel-exact",
            media_type="text/plain; charset=utf-8",
            encoding="utf-8",
            byte_size=len(body),
            primary_payload_sha256=PAYLOAD_SHA256,
            payload_set_sha256=SINGLE_PAYLOAD_SET_SHA256,
            envelope_sha256=ENVELOPE_SHA256,
            captured_at="2026-10-01T01:02:03.004Z",
            channel=ChannelMetadata(type="app", instance_id="knowledgeflow-inbox"),
            user_intent=UserIntent(processing_mode="capture-only"),
        ),
        item_state=CaptureItemState(),
        warnings=warnings,
    )


class InboxSessionUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0C inbox is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config.yaml"

    def _session(
        self,
        operations: InboxOperationBoundary,
        *,
        keys: list[str] | None = None,
        page_size: int = 25,
    ) -> InboxSession:
        available = iter(keys or ["key-1", "key-2", "key-3"])
        return InboxSession(
            config_path=self.config_path,
            path_policy=self.policy,
            page_size=page_size,
            operations=operations,
            idempotency_key_factory=lambda: next(available),
        )

    def test_config_missing_is_guidance_only_and_does_not_call_writes(self) -> None:
        writes: list[object] = []

        def missing(*_args: object, **_kwargs: object) -> FailureResult:
            return _failure(PublicErrorCode.CONFIG_NOT_FOUND)

        operations = InboxOperationBoundary(
            capture=lambda *args, **kwargs: writes.append((args, kwargs)),
            append=lambda *args, **kwargs: writes.append((args, kwargs)),
            get=missing,
            list=missing,
        )
        outcome = self._session(operations).first_page()

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.failure.code, "config_not_found")
        self.assertEqual(outcome.failure.title, "尚未初始化")
        self.assertEqual(writes, [])
        self.assertFalse(self.config_path.exists())

    def test_stable_pagination_tracks_previous_and_next_without_body_reads(self) -> None:
        cursors: list[str | None] = []

        def listing(request: object, **_kwargs: object) -> ListCapturesResult:
            cursors.append(request.cursor)
            if request.cursor is None:
                return ListCapturesResult(
                    items=(_item(CAPTURE_ID_2, "2026-10-01T02:00:00.000Z"),),
                    next_cursor=CURSOR,
                )
            return ListCapturesResult(
                items=(_item(CAPTURE_ID, "2026-10-01T01:00:00.000Z"),),
                next_cursor=None,
            )

        session = self._session(
            InboxOperationBoundary(list=listing),
            page_size=1,
        )
        first = session.first_page().page
        second = session.next_page().page
        previous = session.previous_page().page

        self.assertEqual(cursors, [None, CURSOR, None])
        self.assertEqual(first.page_number, 1)
        self.assertTrue(first.has_next)
        self.assertEqual(second.page_number, 2)
        self.assertTrue(second.has_previous)
        self.assertEqual(previous.items[0].capture_id, CAPTURE_ID_2)

    def test_read_decodes_complete_unicode_body_and_translates_warning(self) -> None:
        body = "完整正文\r\n🙂".encode("utf-8")

        def reading(request: object, **_kwargs: object) -> GetCaptureResult:
            request.body_sink.write(body)
            return _read_result(body, warning=True)

        outcome = self._session(InboxOperationBoundary(get=reading)).open_capture(
            CAPTURE_ID
        )

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.document.text, "完整正文\r\n🙂")
        self.assertEqual(outcome.document.routing_status, "unassigned")
        self.assertEqual(outcome.document.trust_status, "unreviewed-capture")
        self.assertEqual(outcome.notices[0].code, "projection_needs_rebuild")

    def test_unknown_capture_reuses_exact_request_and_blocks_changed_text(self) -> None:
        requests: list[object] = []

        def capturing(request: object, **_kwargs: object) -> object:
            requests.append(request)
            if len(requests) == 1:
                return _failure(
                    PublicErrorCode.ATOMIC_COMMIT_FAILED,
                    commit_state=CommitState.UNKNOWN,
                    retryable=True,
                )
            return CommittedWriteResult(receipt=_capture_receipt())

        session = self._session(
            InboxOperationBoundary(capture=capturing),
            keys=["stable-key"],
        )
        first = session.capture("私密正文")
        changed = session.capture("另一份正文")
        retried = session.retry_pending()

        self.assertEqual(first.failure.commit_state, "unknown")
        self.assertEqual(changed.failure.code, "pending_unknown_request")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].idempotency_key, requests[1].idempotency_key)
        self.assertEqual(requests[0].text, requests[1].text)
        self.assertEqual(requests[0].user_intent.processing_mode, "capture-only")
        self.assertTrue(retried.ok)
        self.assertIsNone(session.pending_state)
        self.assertNotIn("私密正文", repr(session))

    def test_unexpected_write_failure_is_path_free_and_requires_review(self) -> None:
        def exploding(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError(r"C:\private\秘密正文")

        def empty(*_args: object, **_kwargs: object) -> ListCapturesResult:
            return ListCapturesResult(items=(), next_cursor=None)

        session = self._session(
            InboxOperationBoundary(capture=exploding, list=empty),
        )
        outcome = session.capture("秘密正文")

        self.assertEqual(outcome.failure.commit_state, "unknown")
        self.assertNotIn("private", outcome.failure.message)
        self.assertNotIn("秘密正文", outcome.failure.message)
        self.assertEqual(session.abandon_pending().code, "review_required")
        self.assertTrue(session.first_page().ok)
        self.assertIsNone(session.abandon_pending())
        self.assertIsNone(session.pending_state)

    def test_confirmed_not_committed_edit_gets_a_new_key(self) -> None:
        requests: list[object] = []

        def capturing(request: object, **_kwargs: object) -> FailureResult:
            requests.append(request)
            return _failure(
                PublicErrorCode.INVALID_INPUT,
                commit_state=CommitState.NOT_COMMITTED,
            )

        session = self._session(
            InboxOperationBoundary(capture=capturing),
            keys=["first-key", "second-key"],
        )
        first = session.capture("first")
        second = session.capture("second")

        self.assertEqual(first.failure.commit_state, "not-committed")
        self.assertEqual(second.failure.commit_state, "not-committed")
        self.assertEqual(
            [request.idempotency_key for request in requests],
            ["first-key", "second-key"],
        )

    def test_pre_core_failures_are_known_not_committed(self) -> None:
        calls: list[object] = []
        session = self._session(
            InboxOperationBoundary(
                capture=lambda *args, **kwargs: calls.append((args, kwargs))
            )
        )

        outcome = session.capture("")

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.failure.code, "invalid_input")
        self.assertEqual(outcome.failure.commit_state, "not-committed")
        self.assertEqual(calls, [])

        identity_failure = InboxSession(
            config_path=self.config_path,
            path_policy=self.policy,
            operations=InboxOperationBoundary(
                capture=lambda *args, **kwargs: calls.append((args, kwargs))
            ),
            idempotency_key_factory=lambda: (_ for _ in ()).throw(
                RuntimeError(r"C:\private\identity")
            ),
        ).capture("正文")
        self.assertEqual(identity_failure.failure.code, "request_identity_unavailable")
        self.assertEqual(identity_failure.failure.commit_state, "not-committed")
        self.assertFalse(identity_failure.failure.retry_available)
        self.assertNotIn("private", identity_failure.failure.message)
        self.assertEqual(calls, [])

    def test_append_binds_capture_version_and_surfaces_version_conflict(self) -> None:
        requests: list[object] = []

        def appending(request: object, **_kwargs: object) -> object:
            requests.append(request)
            if len(requests) == 1:
                return _failure(
                    PublicErrorCode.VERSION_CONFLICT,
                    commit_state=CommitState.NOT_COMMITTED,
                )
            return AppendCaptureVersionResult(receipt=_append_receipt())

        session = self._session(InboxOperationBoundary(append=appending))
        conflict = session.append(
            capture_id=CAPTURE_ID,
            expected_current_version=1,
            text="v2",
        )
        retried = session.retry_pending()

        self.assertEqual(conflict.failure.code, "version_conflict")
        self.assertEqual(requests[0].capture_id, CAPTURE_ID)
        self.assertEqual(requests[0].expected_current_version, 1)
        self.assertEqual(requests[0].idempotency_key, requests[1].idempotency_key)
        self.assertTrue(retried.ok)
        self.assertEqual(retried.receipt.version, 2)

    def test_committed_warning_remains_success_and_close_drops_session_state(self) -> None:
        warned = CommittedWriteResult(
            receipt=_capture_receipt(),
            warnings=(
                OperationWarning(code=WarningCode.OUTBOX_NEEDS_REBUILD),
            ),
        )
        session = self._session(
            InboxOperationBoundary(capture=lambda *_args, **_kwargs: warned)
        )
        outcome = session.capture("saved")

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.receipt.commit_state, "committed")
        self.assertEqual(outcome.notices[0].code, "outbox_needs_rebuild")
        session.close()
        self.assertIsNone(session.pending_state)
        with self.assertRaises(RuntimeError):
            session.first_page()


if __name__ == "__main__":
    unittest.main()
