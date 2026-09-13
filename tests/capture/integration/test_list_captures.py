from __future__ import annotations

from datetime import datetime, timezone
import inspect
import io
import os
from pathlib import Path
import tempfile
import unittest

import knowledgeflow_capture
from knowledgeflow_capture.errors import (
    CommittedWriteResult,
    FailureResult,
    ListCapturesResult,
    PublicErrorCode,
    WarningCode,
)
from knowledgeflow_capture.models import (
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
)
from knowledgeflow_capture.operations import (
    _CaptureDependencies,
    _ListCapturesDependencies,
    _capture_text_with_dependencies,
    _list_captures_with_dependencies,
    get_capture,
    list_captures,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store

from .._samples import CAPTURE_ID, PAYLOAD_BYTES


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_MIB = 1024 * 1024
_MAXIMUM = 64 * _MIB


def _capture_id(index: int) -> str:
    return f"cap_01991a7e-7b20-7a31-8d14-{index:012x}"


def _event_id(index: int) -> str:
    return f"evt_01991a7e-7b21-72ae-9ef5-{index:012x}"


def _time(second: int) -> datetime:
    return datetime(2026, 9, 13, 0, 0, second, tzinfo=timezone.utc)


class _GeneratedStream:
    def __init__(self, byte_size: int) -> None:
        self.remaining = byte_size
        self.maximum_read = 0

    def read(self, size: int = -1, /) -> bytes:
        if size <= 0:
            raise AssertionError("list acceptance source received an unbounded read")
        self.maximum_read = max(self.maximum_read, size)
        returned = min(size, self.remaining)
        self.remaining -= returned
        return b"x" * returned


class _RecordingFile:
    def __init__(self, path: Path) -> None:
        self._stream = path.open("rb")
        self.maximum_read = 0
        self.total_read = 0

    def read(self, size: int = -1, /) -> bytes:
        if size < 0:
            raise AssertionError("list preview issued an unbounded read")
        self.maximum_read = max(self.maximum_read, size)
        value = self._stream.read(size)
        self.total_read += len(value)
        return value

    def fileno(self) -> int:
        return self._stream.fileno()

    def __enter__(self) -> _RecordingFile:
        return self

    def __exit__(self, *args: object) -> None:
        self._stream.close()


class ListCapturesIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("C4C list_captures is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.capture_root = self.owned_root / "capture-store"
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.capture_root,
            inline_text_threshold_bytes=4 * _MIB,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)

    def _capture(
        self,
        text: str | object,
        *,
        index: int,
        second: int,
    ) -> Path:
        result = _capture_text_with_dependencies(
            CaptureTextRequest(
                text=text,
                channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            ),
            config_path=self.config_path,
            path_policy=self.policy,
            dependencies=_CaptureDependencies(
                utc_now=lambda: _time(second),
                capture_id_factory=lambda: _capture_id(index),
                event_id_factory=lambda: _event_id(index),
            ),
        )
        self.assertIsInstance(result, CommittedWriteResult)
        return self.capture_root / "items" / "2026" / "09" / _capture_id(index)

    def _list(
        self,
        request: ListCapturesRequest | object | None = None,
        *,
        dependencies: _ListCapturesDependencies | None = None,
        config_path: Path | None = None,
    ) -> ListCapturesResult | FailureResult:
        selected_request = ListCapturesRequest() if request is None else request
        selected_config = self.config_path if config_path is None else config_path
        if dependencies is None:
            return list_captures(
                selected_request,  # type: ignore[arg-type]
                config_path=selected_config,
                path_policy=self.policy,
            )
        return _list_captures_with_dependencies(
            selected_request,  # type: ignore[arg-type]
            config_path=selected_config,
            path_policy=self.policy,
            dependencies=dependencies,
        )

    def _assert_success(
        self,
        result: ListCapturesResult | FailureResult,
    ) -> ListCapturesResult:
        self.assertIsInstance(result, ListCapturesResult)
        success = result
        serialized = success.to_dict()
        self.assertTrue(serialized["ok"])
        self.assertNotIn("commit_state", serialized)
        self.assertNotIn("integrity", serialized)
        self.assertNotIn("total_count", serialized)
        return success

    def _assert_failure(
        self,
        result: ListCapturesResult | FailureResult,
        code: PublicErrorCode,
    ) -> FailureResult:
        self.assertIsInstance(result, FailureResult)
        failure = result
        self.assertEqual(failure.error.code, code)
        self.assertIsNone(failure.commit_state)
        self.assertNotIn("commit_state", failure.to_dict())
        return failure

    def _install_golden_item(self, *, include_v2: bool = False) -> Path:
        item = self.capture_root / "items" / "2026" / "09" / CAPTURE_ID
        version_1 = item / "versions" / "000001"
        (version_1 / "payloads").mkdir(parents=True)
        (item / "events").mkdir()
        (version_1 / "payloads" / "primary.txt").write_bytes(PAYLOAD_BYTES)
        (version_1 / "envelope.yaml").write_bytes(
            (FIXTURES / "envelope-v1.yaml").read_bytes()
        )
        (item / "events" / "evt_01991a7e-7b21-72ae-9ef5-4f45249ad332.yaml").write_bytes(
            (FIXTURES / "capture-event-v1.yaml").read_bytes()
        )
        if include_v2:
            version_2 = item / "versions" / "000002"
            (version_2 / "payloads").mkdir(parents=True)
            (version_2 / "payloads" / "primary.txt").write_bytes(
                (FIXTURES / "payload-v2.txt").read_bytes()
            )
            (version_2 / "envelope.yaml").write_bytes(
                (FIXTURES / "envelope-v2.yaml").read_bytes()
            )
            (item / "events" / "evt_01991a7e-7b22-72ae-9ef5-4f45249ad333.yaml").write_bytes(
                (FIXTURES / "capture-version-appended-event-v1.yaml").read_bytes()
            )
        (item / "capture.yaml").write_bytes(
            (FIXTURES / "capture-state-v1.yaml").read_bytes()
        )
        return item

    def test_list_01_empty_result_and_public_signature(self) -> None:
        result = self._assert_success(self._list())
        self.assertEqual(result.items, ())
        self.assertIsNone(result.next_cursor)
        self.assertEqual(result.warnings, ())
        self.assertEqual(
            tuple(inspect.signature(list_captures).parameters),
            ("request", "config_path", "path_policy"),
        )
        for name in (
            "ListCapturesOperationResult",
            "ListCapturesRequest",
            "ListCapturesResult",
            "list_captures",
        ):
            self.assertTrue(hasattr(knowledgeflow_capture, name))

        self._assert_failure(self._list(object()), PublicErrorCode.INVALID_INPUT)

    def test_list_02_03_10_tie_order_keyset_pages_and_limit_change(self) -> None:
        for index in (1, 2, 3):
            self._capture(str(index), index=index, second=1)

        first = self._assert_success(self._list(ListCapturesRequest(limit=2)))
        self.assertEqual(
            tuple(item.capture_id for item in first.items),
            (_capture_id(3), _capture_id(2)),
        )
        self.assertIsNotNone(first.next_cursor)
        second = self._assert_success(
            self._list(ListCapturesRequest(limit=100, cursor=first.next_cursor))
        )
        self.assertEqual(
            tuple(item.capture_id for item in second.items),
            (_capture_id(1),),
        )
        self.assertIsNone(second.next_cursor)
        self.assertEqual(
            {item.capture_id for item in first.items + second.items},
            {_capture_id(1), _capture_id(2), _capture_id(3)},
        )

    def test_list_04_malformed_cursor_is_invalid_input(self) -> None:
        failure = self._assert_failure(
            self._list(ListCapturesRequest(cursor="not-a-cursor")),
            PublicErrorCode.INVALID_INPUT,
        )
        self.assertNotIn("items", failure.to_dict())

    def test_list_09_cursor_is_bound_to_store_and_query(self) -> None:
        self._capture("one", index=1, second=1)
        self._capture("two", index=2, second=2)
        first = self._assert_success(self._list(ListCapturesRequest(limit=1)))
        self.assertIsNotNone(first.next_cursor)
        self._assert_failure(
            self._list(
                ListCapturesRequest(
                    routing_status="unassigned",
                    cursor=first.next_cursor,
                )
            ),
            PublicErrorCode.INVALID_INPUT,
        )

        other_config = self.owned_root / "other-config" / "config.yaml"
        initialized = init_capture_store(
            config_path=other_config,
            capture_root=self.owned_root / "other-store",
            inline_text_threshold_bytes=4 * _MIB,
            max_text_version_bytes=_MAXIMUM,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)
        self._assert_failure(
            self._list(
                ListCapturesRequest(cursor=first.next_cursor),
                config_path=other_config,
            ),
            PublicErrorCode.INVALID_INPUT,
        )

    def test_list_05_08_17_filter_rebuilds_projection_in_memory_without_writes(self) -> None:
        item = self._capture("inbox", index=1, second=1)
        projection = item / "capture.yaml"
        projection.unlink()
        result = self._assert_success(
            self._list(ListCapturesRequest(routing_status="unassigned"))
        )
        self.assertEqual(tuple(row.capture_id for row in result.items), (_capture_id(1),))
        self.assertEqual(
            tuple(warning.code for warning in result.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )
        self.assertFalse(projection.exists())

        projection.write_bytes(b"schema: knowledgeflow.capture-state\nschema_version: 2\n")
        before = projection.read_bytes()
        self._assert_failure(
            self._list(),
            PublicErrorCode.UNSUPPORTED_STORE_VERSION,
        )
        self.assertEqual(projection.read_bytes(), before)

    def test_list_06_preview_is_exactly_160_unicode_code_points(self) -> None:
        text = ("首行\n🙂e\u0301\r\n" * 40) + "末尾"
        self._capture(text, index=1, second=1)
        result = self._assert_success(self._list())
        self.assertEqual(result.items[0].preview, text[:160])
        self.assertEqual(len(result.items[0].preview), 160)
        self.assertIn("\n", result.items[0].preview)
        self.assertIn("\u0301", result.items[0].preview)

    def test_list_07_11_request_bounds_reject_bool_and_invalid_time_range(self) -> None:
        for limit in (True, False, 0, 101):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    ListCapturesRequest(limit=limit)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ListCapturesRequest(
                created_after="2026-09-13T00:00:02.000Z",
                created_before="2026-09-13T00:00:02.000Z",
            )

    def test_list_11_time_boundaries_are_strict(self) -> None:
        for index, second in ((1, 1), (2, 2), (3, 3)):
            self._capture(str(index), index=index, second=second)
        result = self._assert_success(
            self._list(
                ListCapturesRequest(
                    created_after="2026-09-13T00:00:01.000Z",
                    created_before="2026-09-13T00:00:03.000Z",
                )
            )
        )
        self.assertEqual(tuple(item.capture_id for item in result.items), (_capture_id(2),))

    def test_list_12_two_versions_use_v1_capture_time_and_current_event_update(self) -> None:
        self._install_golden_item(include_v2=True)
        result = self._assert_success(self._list())
        item = result.items[0]
        self.assertEqual(item.current_version, 2)
        self.assertEqual(item.captured_at, "2026-09-02T01:02:03.004Z")
        self.assertEqual(item.updated_at, "2026-09-13T00:00:00.005Z")
        self.assertEqual(
            item.envelope_sha256,
            "sha256:74226c67b1efc60342a6aff3225597e41f690b6583a7d7f8d3b25a580ca7200a",
        )
        self.assertEqual(
            item.preview,
            (FIXTURES / "payload-v2.txt").read_text(encoding="utf-8")[:160],
        )
        self.assertEqual(
            tuple(warning.code for warning in result.warnings),
            (WarningCode.PROJECTION_NEEDS_REBUILD,),
        )

    def test_list_13_unique_uncommitted_tail_is_hidden_and_warned(self) -> None:
        item = self._capture("committed", index=1, second=1)
        tail = item / "versions" / "000002"
        tail.mkdir()
        result = self._assert_success(self._list())
        self.assertEqual(result.items[0].current_version, 1)
        self.assertEqual(result.items[0].preview, "committed")
        self.assertEqual(
            result.warnings[0].to_dict()["details"],
            {"capture_id": _capture_id(1), "version": 2},
        )
        self.assertTrue(tail.is_dir())

    def test_list_14_any_immutable_conflict_fails_the_whole_request(self) -> None:
        self._capture("visible", index=1, second=2)
        damaged = self._capture("outside-filter", index=2, second=1)
        payload = damaged / "versions" / "000001" / "payloads" / "primary.txt"
        payload.write_bytes(payload.read_bytes() + b"x")
        failure = self._assert_failure(
            self._list(
                ListCapturesRequest(
                    created_after="2026-09-13T00:00:01.000Z",
                )
            ),
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )
        self.assertNotIn("items", failure.to_dict())
        self.assertNotIn("next_cursor", failure.to_dict())

    def test_list_15_same_size_body_tamper_is_not_full_attestation(self) -> None:
        item = self._capture("a" * 1000, index=1, second=1)
        payload = item / "versions" / "000001" / "payloads" / "primary.txt"
        body = bytearray(payload.read_bytes())
        body[160] = 0xFF
        payload.write_bytes(body)

        result = self._assert_success(self._list())
        self.assertEqual(result.items[0].preview, "a" * 160)
        sink = io.BytesIO()
        get_result = get_capture(
            GetCaptureRequest(capture_id=_capture_id(1), body_sink=sink),
            config_path=self.config_path,
            path_policy=self.policy,
        )
        self.assertIsInstance(get_result, FailureResult)
        self.assertEqual(
            get_result.error.code,  # type: ignore[union-attr]
            PublicErrorCode.INTEGRITY_CHECK_FAILED,
        )
        self.assertEqual(sink.getvalue(), b"")

    def test_list_16_real_64_mib_body_reads_only_a_bounded_prefix(self) -> None:
        source = _GeneratedStream(_MAXIMUM)
        self._capture(source, index=1, second=1)
        opened: list[_RecordingFile] = []

        def opener(path: Path) -> _RecordingFile:
            stream = _RecordingFile(path)
            opened.append(stream)
            return stream

        result = self._assert_success(
            self._list(
                dependencies=_ListCapturesDependencies(preview_opener=opener)
            )
        )
        self.assertEqual(result.items[0].preview, "x" * 160)
        self.assertEqual(len(opened), 1)
        self.assertLessEqual(opened[0].maximum_read, 640)
        self.assertLessEqual(opened[0].total_read, 640)
        self.assertLessEqual(source.maximum_read, _MIB)

    def test_list_18_multiple_warnings_are_stable_and_page_owned(self) -> None:
        first = self._capture("first", index=2, second=2)
        second = self._capture("second", index=1, second=1)
        (first / "capture.yaml").unlink()
        (second / "capture.yaml").write_bytes(b"known-invalid")
        (second / "versions" / "000002").mkdir()
        result = self._assert_success(self._list())
        warning_keys = tuple(
            (
                warning.details["capture_id"],
                warning.code.value,
                warning.details.get("version", 0),
            )
            for warning in result.warnings
        )
        self.assertEqual(warning_keys, tuple(sorted(warning_keys)))
        self.assertEqual(len(warning_keys), 3)
        returned = {item.capture_id for item in result.items}
        self.assertTrue(all(key[0] in returned for key in warning_keys))
        self.assertNotIn("commit_state", result.to_dict())

    def test_list_19_mutation_between_pages_has_no_snapshot_claim(self) -> None:
        self._capture("old", index=1, second=1)
        self._capture("middle", index=2, second=2)
        first = self._assert_success(self._list(ListCapturesRequest(limit=1)))
        self.assertEqual(first.items[0].capture_id, _capture_id(2))
        self._capture("new", index=3, second=3)

        second = self._assert_success(
            self._list(ListCapturesRequest(limit=100, cursor=first.next_cursor))
        )
        self.assertEqual(tuple(item.capture_id for item in second.items), (_capture_id(1),))
        fresh = self._assert_success(self._list(ListCapturesRequest(limit=1)))
        self.assertEqual(fresh.items[0].capture_id, _capture_id(3))


if __name__ == "__main__":
    unittest.main()
