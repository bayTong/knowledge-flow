from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture import (
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    capture_text,
    get_capture,
    list_captures,
)
from knowledgeflow_capture.errors import (
    CommittedWriteResult,
    FailureResult,
    GetCaptureResult,
    ListCapturesResult,
)
from knowledgeflow_capture.hashing import DEFAULT_CHUNK_SIZE
from knowledgeflow_capture.models import CaptureListItem
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


_MIB = 1024 * 1024
_INLINE_THRESHOLD = 4 * _MIB
_MAXIMUM = 64 * _MIB
_STABLE_RECEIPT_FIELDS = (
    "capture_id",
    "event_id",
    "version",
    "primary_payload_sha256",
    "payload_set_sha256",
    "envelope_sha256",
)


class _GeneratedUtf8Stream:
    """Generate an ASCII UTF-8 body while proving all reads are bounded."""

    def __init__(self, byte_size: int) -> None:
        self._remaining = byte_size
        self.total_bytes_returned = 0
        self.maximum_read = 0
        self.eof_reads = 0

    def read(self, size: int = -1, /) -> bytes:
        if size <= 0:
            raise AssertionError("C4V source received an unbounded read")
        self.maximum_read = max(self.maximum_read, size)
        if self._remaining == 0:
            self.eof_reads += 1
            return b""
        returned = min(size, self._remaining)
        self._remaining -= returned
        self.total_bytes_returned += returned
        return b"x" * returned


class _DigestSink:
    """Consume a body without retaining it and record the public write pattern."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.byte_size = 0
        self.maximum_write = 0
        self.close_calls = 0
        self.flush_calls = 0

    def write(self, value: bytes) -> int:
        if type(value) is not bytes:
            raise AssertionError("C4V sink must receive bytes")
        self._digest.update(value)
        self.byte_size += len(value)
        self.maximum_write = max(self.maximum_write, len(value))
        return len(value)

    def close(self) -> None:
        self.close_calls += 1

    def flush(self) -> None:
        self.flush_calls += 1

    @property
    def sha256(self) -> str:
        return "sha256:" + self._digest.hexdigest()


class ReadAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C4V read acceptance is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=_INLINE_THRESHOLD,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)

    def _capture(
        self,
        text: str | object,
        *,
        idempotency_key: str,
    ) -> CommittedWriteResult:
        result = capture_text(
            CaptureTextRequest(
                text=text,
                channel=ChannelMetadata(type="app", instance_id="c4v-acceptance"),
                idempotency_key=idempotency_key,
            ),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, CommittedWriteResult)
        return result

    def _list(
        self,
        request: ListCapturesRequest,
    ) -> ListCapturesResult:
        result = list_captures(
            request,
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(result, ListCapturesResult)
        return result

    def _all_pages(self, *, limit: int) -> tuple[CaptureListItem, ...]:
        items: list[CaptureListItem] = []
        cursors: set[str] = set()
        cursor: str | None = None
        while True:
            result = self._list(ListCapturesRequest(limit=limit, cursor=cursor))
            items.extend(result.items)
            if result.next_cursor is None:
                return tuple(items)
            self.assertNotIn(result.next_cursor, cursors)
            cursors.add(result.next_cursor)
            cursor = result.next_cursor
            self.assertLessEqual(len(cursors), 100)

    def test_c4v_real_4_and_64_mib_public_write_list_get_round_trip(self) -> None:
        accepted: dict[str, tuple[int, dict[str, object]]] = {}
        for label, byte_size in (("4-mib", _INLINE_THRESHOLD), ("64-mib", _MAXIMUM)):
            with self.subTest(label=label):
                source = _GeneratedUtf8Stream(byte_size)
                written = self._capture(source, idempotency_key=f"c4v-{label}")
                receipt = written.to_dict()
                capture_id = receipt["capture_id"]
                self.assertIsInstance(capture_id, str)
                accepted[capture_id] = (byte_size, receipt)
                self.assertEqual(source.total_bytes_returned, byte_size)
                self.assertEqual(source.eof_reads, 1)
                self.assertLessEqual(source.maximum_read, DEFAULT_CHUNK_SIZE)

        listed = self._list(ListCapturesRequest(limit=10))
        self.assertEqual(
            {item.capture_id for item in listed.items},
            set(accepted),
        )
        self.assertIsNone(listed.next_cursor)
        self.assertEqual(listed.warnings, ())

        for item in listed.items:
            byte_size, receipt = accepted[item.capture_id]
            self.assertEqual(item.current_version, 1)
            self.assertEqual(item.preview, "x" * 160)
            self.assertEqual(item.envelope_sha256, receipt["envelope_sha256"])

            sink = _DigestSink()
            read = get_capture(
                GetCaptureRequest(capture_id=item.capture_id, body_sink=sink),
                config_path=self.config_path,
                path_policy=self.policy,
            )
            self.assertIsInstance(read, GetCaptureResult)
            self.assertEqual(read.body_length_bytes, byte_size)
            self.assertEqual(read.capture.byte_size, byte_size)
            self.assertEqual(
                read.capture.primary_payload_sha256,
                receipt["primary_payload_sha256"],
            )
            self.assertEqual(
                read.capture.payload_set_sha256,
                receipt["payload_set_sha256"],
            )
            self.assertEqual(
                read.capture.envelope_sha256,
                receipt["envelope_sha256"],
            )
            self.assertEqual(sink.byte_size, byte_size)
            self.assertEqual(sink.sha256, receipt["primary_payload_sha256"])
            self.assertLessEqual(sink.maximum_write, DEFAULT_CHUNK_SIZE)
            self.assertEqual(sink.close_calls, 0)
            self.assertEqual(sink.flush_calls, 0)

        original_4_mib = next(
            receipt
            for byte_size, receipt in accepted.values()
            if byte_size == _INLINE_THRESHOLD
        )
        retry_source = _GeneratedUtf8Stream(_INLINE_THRESHOLD)
        retried = self._capture(retry_source, idempotency_key="c4v-4-mib").to_dict()
        for field in _STABLE_RECEIPT_FIELDS:
            self.assertEqual(retried[field], original_4_mib[field])
        self.assertEqual(retry_source.total_bytes_returned, _INLINE_THRESHOLD)
        self.assertEqual(retry_source.eof_reads, 1)
        self.assertLessEqual(retry_source.maximum_read, DEFAULT_CHUNK_SIZE)

    def test_c4v_static_pages_and_controlled_creation_use_keyset_boundaries(self) -> None:
        original_ids: set[str] = set()
        for index in range(7):
            capture_id = self._capture(
                f"page body {index}",
                idempotency_key=f"c4v-page-{index}",
            ).to_dict()["capture_id"]
            self.assertIsInstance(capture_id, str)
            original_ids.add(capture_id)
        static_items = self._all_pages(limit=2)
        static_ids = tuple(item.capture_id for item in static_items)
        self.assertEqual(len(static_ids), len(set(static_ids)))
        self.assertEqual(set(static_ids), original_ids)
        self.assertEqual(
            tuple(item.sort_key for item in static_items),
            tuple(sorted((item.sort_key for item in static_items), reverse=True)),
        )

        first = self._list(ListCapturesRequest(limit=3))
        self.assertIsNotNone(first.next_cursor)
        boundary = first.items[-1].sort_key
        created = self._capture(
            "created between pages",
            idempotency_key="c4v-between-pages",
        ).to_dict()
        created_id = created["capture_id"]
        self.assertIsInstance(created_id, str)

        continuation: list[CaptureListItem] = []
        cursor = first.next_cursor
        continuation_cursors: set[str] = set()
        while cursor is not None:
            self.assertNotIn(cursor, continuation_cursors)
            continuation_cursors.add(cursor)
            page = self._list(ListCapturesRequest(limit=2, cursor=cursor))
            continuation.extend(page.items)
            cursor = page.next_cursor
            self.assertLessEqual(len(continuation_cursors), 100)

        first_ids = {item.capture_id for item in first.items}
        continuation_ids = tuple(item.capture_id for item in continuation)
        self.assertTrue(first_ids.isdisjoint(continuation_ids))
        self.assertEqual(len(continuation_ids), len(set(continuation_ids)))
        self.assertTrue(all(item.sort_key < boundary for item in continuation))
        self.assertNotIn(created_id, continuation_ids)
        self.assertEqual(first_ids | set(continuation_ids), original_ids)

        fresh_items = self._all_pages(limit=4)
        fresh_ids = {item.capture_id for item in fresh_items}
        self.assertEqual(fresh_ids, original_ids | {created_id})
        expected_continuation = {
            item.capture_id for item in fresh_items if item.sort_key < boundary
        }
        self.assertEqual(set(continuation_ids), expected_continuation)


if __name__ == "__main__":
    unittest.main()
