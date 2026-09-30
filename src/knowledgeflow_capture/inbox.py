"""Thin, local-only inbox adapter over the four public Capture operations.

This module deliberately contains no Store parsing, transaction logic, network
access, telemetry, or persistent draft storage. Text and idempotency keys live
only in the current process and are never included in public presentation
objects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import io
import os
from typing import Literal
from uuid import uuid4

from .errors import (
    AppendCaptureVersionResult,
    CommitState,
    CommittedWriteResult,
    FailureResult,
    OperationError,
    OperationWarning,
    PublicErrorCode,
    WarningCode,
)
from .models import (
    AppendCaptureVersionRequest,
    CaptureListItem,
    CaptureTextRequest,
    ChannelMetadata,
    GetCaptureRequest,
    ListCapturesRequest,
    UserIntent,
)
from .operations import (
    append_capture_version,
    capture_text,
    get_capture,
    list_captures,
)
from .paths import PathPolicy


NoticeLevel = Literal["info", "success", "warning", "error"]
PendingOperation = Literal["capture_text", "append_capture_version"]

_CHANNEL = ChannelMetadata(type="app", instance_id="knowledgeflow-inbox")
_CAPTURE_ONLY = UserIntent(processing_mode="capture-only")
_GENERIC_INTERNAL_MESSAGE = (
    "本地操作未能返回可验证结果。正文仍保留在本次界面进程中；"
    "写入请求必须按“结果不明”处理。"
)


@dataclass(frozen=True, slots=True)
class InboxNotice:
    """Path-free, body-free information suitable for direct UI display."""

    level: NoticeLevel
    code: str
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class InboxFailure:
    """One user-actionable failure without exception or filesystem detail."""

    code: str
    title: str
    message: str
    commit_state: str | None = None
    retryable: bool = False
    retry_available: bool = False


@dataclass(frozen=True, slots=True)
class InboxEntry:
    capture_id: str
    current_version: int
    captured_at: str
    updated_at: str
    preview: str
    routing_status: str
    trust_status: str
    envelope_sha256: str


@dataclass(frozen=True, slots=True)
class InboxPage:
    items: tuple[InboxEntry, ...]
    page_number: int
    has_previous: bool
    has_next: bool


@dataclass(frozen=True, slots=True)
class InboxDocument:
    capture_id: str
    version: int
    current_version: int
    captured_at: str
    byte_size: int
    primary_payload_sha256: str
    envelope_sha256: str
    routing_status: str
    trust_status: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class InboxWriteReceipt:
    operation: PendingOperation
    capture_id: str
    version: int
    commit_state: str


@dataclass(frozen=True, slots=True)
class InboxPendingState:
    """Safe summary of a pending request; text and idempotency key are omitted."""

    operation: PendingOperation
    capture_id: str | None
    expected_current_version: int | None
    commit_state: str | None
    reviewed_after_unknown: bool


@dataclass(frozen=True, slots=True)
class InboxPageOutcome:
    page: InboxPage | None = None
    notices: tuple[InboxNotice, ...] = ()
    failure: InboxFailure | None = None

    @property
    def ok(self) -> bool:
        return self.page is not None and self.failure is None


@dataclass(frozen=True, slots=True)
class InboxReadOutcome:
    document: InboxDocument | None = None
    notices: tuple[InboxNotice, ...] = ()
    failure: InboxFailure | None = None

    @property
    def ok(self) -> bool:
        return self.document is not None and self.failure is None


@dataclass(frozen=True, slots=True)
class InboxWriteOutcome:
    receipt: InboxWriteReceipt | None = None
    notices: tuple[InboxNotice, ...] = ()
    failure: InboxFailure | None = None

    @property
    def ok(self) -> bool:
        return self.receipt is not None and self.failure is None


@dataclass(frozen=True, slots=True)
class InboxOperationBoundary:
    """Injectable one-to-one binding to the four public operations."""

    capture: Callable[..., object] = capture_text
    append: Callable[..., object] = append_capture_version
    get: Callable[..., object] = get_capture
    list: Callable[..., object] = list_captures


@dataclass(slots=True)
class _PendingWrite:
    operation: PendingOperation
    text: str = field(repr=False)
    idempotency_key: str = field(repr=False)
    capture_id: str | None = None
    expected_current_version: int | None = None
    commit_state: str | None = None
    reviewed_after_unknown: bool = False

    def safe_state(self) -> InboxPendingState:
        return InboxPendingState(
            operation=self.operation,
            capture_id=self.capture_id,
            expected_current_version=self.expected_current_version,
            commit_state=self.commit_state,
            reviewed_after_unknown=self.reviewed_after_unknown,
        )


def _new_idempotency_key() -> str:
    return f"knowledgeflow-inbox-{uuid4().hex}"


_ERROR_COPY: Mapping[PublicErrorCode, tuple[str, str]] = {
    PublicErrorCode.CONFIG_NOT_FOUND: (
        "尚未初始化",
        "未找到本机 Capture 配置。请关闭收件箱并使用独立管理入口完成初始化；"
        "本界面不会自行创建目录或配置。",
    ),
    PublicErrorCode.CONFIG_INVALID: (
        "配置不可用",
        "本机 Capture 配置无效。请停止使用并通过管理流程检查配置。",
    ),
    PublicErrorCode.UNRECOGNIZED_EXISTING_DIRECTORY: (
        "Store 无法识别",
        "目标目录不是可识别的 Capture Store；本界面不会修改或清理它。",
    ),
    PublicErrorCode.UNSUPPORTED_STORE_VERSION: (
        "Store 版本不受支持",
        "当前程序不能安全打开该 Store。请停止使用并执行受控迁移或升级。",
    ),
    PublicErrorCode.CONFIG_STORE_CONFLICT: (
        "配置与 Store 冲突",
        "配置指向的 Store 与其身份不一致。请停止使用并通过管理流程核对。",
    ),
    PublicErrorCode.CAPTURE_STORE_NOT_INITIALIZED: (
        "Store 尚未初始化",
        "配置存在，但 Capture Store 尚未完成初始化。本界面不会自动修复。",
    ),
    PublicErrorCode.CAPTURE_STORE_UNAVAILABLE: (
        "Store 暂不可用",
        "无法安全访问本机 Capture Store。请检查磁盘状态后再重试。",
    ),
    PublicErrorCode.INVALID_INPUT: (
        "输入无效",
        "请求内容不符合当前文本捕获约束。请检查正文后重新提交。",
    ),
    PublicErrorCode.TEXT_TOO_LARGE: (
        "正文过大",
        "正文超过当前 Store 的单版本安全上限，未保存。",
    ),
    PublicErrorCode.CAPTURE_NOT_FOUND: (
        "Capture 不存在",
        "找不到该 Capture。请刷新收件箱后重新选择。",
    ),
    PublicErrorCode.VERSION_NOT_FOUND: (
        "版本不存在",
        "找不到请求的 Capture 版本。请刷新并重新打开该条目。",
    ),
    PublicErrorCode.VERSION_CONFLICT: (
        "版本已变化",
        "其他写入已产生更新版本，本次内容没有覆盖旧版本。请刷新、核对后再追加。",
    ),
    PublicErrorCode.IDEMPOTENCY_CONFLICT: (
        "重试身份冲突",
        "同一重试身份对应了不同请求。请保留当前内容并停止重复提交，随后人工核对。",
    ),
    PublicErrorCode.INTEGRITY_CHECK_FAILED: (
        "完整性校验失败",
        "规范事实未通过完整性校验。请立即停止写入并使用受控维护流程检查。",
    ),
    PublicErrorCode.ATOMIC_COMMIT_FAILED: (
        "原子提交失败",
        "写入没有形成可确认成功的提交。请按下方提交状态决定是否重试。",
    ),
    PublicErrorCode.OUTPUT_WRITE_FAILED: (
        "正文读取失败",
        "已验证正文无法交付给界面。Store 原件未因此改变，可以重试读取。",
    ),
}

_WARNING_COPY: Mapping[WarningCode, tuple[str, str]] = {
    WarningCode.PROJECTION_NEEDS_REBUILD: (
        "列表投影需要重建",
        "规范原件仍是权威事实，但派生列表需要维护。停止继续写入并使用受控重建流程。",
    ),
    WarningCode.OUTBOX_NEEDS_REBUILD: (
        "待处理投影需要重建",
        "Capture 已提交，但派生待处理视图需要维护。不要把此警告理解为正文未保存。",
    ),
    WarningCode.INCOMPLETE_VERSION_IGNORED: (
        "未完成版本尾部已忽略",
        "读取使用了最后一个完整提交版本。请停止继续写入并检查崩溃恢复状态。",
    ),
}


def _warning_notices(
    warnings: tuple[OperationWarning, ...],
) -> tuple[InboxNotice, ...]:
    result: list[InboxNotice] = []
    for warning in warnings:
        title, message = _WARNING_COPY[warning.code]
        result.append(
            InboxNotice(
                level="warning",
                code=warning.code.value,
                title=title,
                message=message,
            )
        )
    return tuple(result)


def _failure_from_result(
    result: FailureResult,
    *,
    retry_available: bool,
) -> InboxFailure:
    title, message = _ERROR_COPY[result.error.code]
    commit_state = result.commit_state.value if result.commit_state else None
    if commit_state == CommitState.UNKNOWN.value:
        title = "保存结果不明"
        message = (
            "无法证明本次写入是否已提交。当前正文与重试身份仍保留在本进程中；"
            "请优先使用“重试上次保存”复用完全相同的请求，或先刷新核对。"
        )
    elif commit_state == CommitState.NOT_COMMITTED.value:
        message = f"{message} 提交状态：确认未保存。"
    return InboxFailure(
        code=result.error.code.value,
        title=title,
        message=message,
        commit_state=commit_state,
        retryable=result.error.retryable or commit_state == CommitState.UNKNOWN.value,
        retry_available=retry_available,
    )


def _internal_failure(*, write: bool) -> InboxFailure:
    return InboxFailure(
        code="internal_failure",
        title="本地界面内部失败",
        message=(
            _GENERIC_INTERNAL_MESSAGE
            if write
            else "本地操作未能返回可验证结果。未显示异常细节，请停止操作后重试。"
        ),
        commit_state=CommitState.UNKNOWN.value if write else None,
        retryable=write,
        retry_available=write,
    )


def _entry(item: CaptureListItem) -> InboxEntry:
    return InboxEntry(
        capture_id=item.capture_id,
        current_version=item.current_version,
        captured_at=item.captured_at,
        updated_at=item.updated_at,
        preview=item.preview,
        routing_status=item.routing_status,
        trust_status=item.trust_status,
        envelope_sha256=item.envelope_sha256,
    )


class InboxSession:
    """One process-local inbox session with bounded idempotent retry state."""

    def __init__(
        self,
        *,
        config_path: str | os.PathLike[str] | None,
        path_policy: PathPolicy,
        page_size: int = 25,
        operations: InboxOperationBoundary | None = None,
        idempotency_key_factory: Callable[[], str] = _new_idempotency_key,
    ) -> None:
        if not isinstance(path_policy, PathPolicy):
            raise TypeError("path_policy must be PathPolicy")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be from 1 through 100")
        if not callable(idempotency_key_factory):
            raise TypeError("idempotency_key_factory must be callable")
        self._config_path = config_path
        self._path_policy = path_policy
        self._page_size = page_size
        self._operations = operations or InboxOperationBoundary()
        self._idempotency_key_factory = idempotency_key_factory
        self._cursor: str | None = None
        self._previous_cursors: tuple[str | None, ...] = ()
        self._next_cursor: str | None = None
        self._last_page: InboxPage | None = None
        self._current_document: InboxDocument | None = None
        self._pending: _PendingWrite | None = None
        self._closed = False

    @property
    def pending_state(self) -> InboxPendingState | None:
        return self._pending.safe_state() if self._pending is not None else None

    @property
    def current_document(self) -> InboxDocument | None:
        return self._current_document

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("inbox session is closed")

    def close(self) -> None:
        """Drop process-held text and retry references; this is not secure erase."""

        self._pending = None
        self._current_document = None
        self._last_page = None
        self._closed = True

    def first_page(self) -> InboxPageOutcome:
        self._ensure_open()
        return self._load_page(cursor=None, previous=())

    def next_page(self) -> InboxPageOutcome:
        self._ensure_open()
        if self._next_cursor is None:
            return InboxPageOutcome(page=self._last_page)
        return self._load_page(
            cursor=self._next_cursor,
            previous=(*self._previous_cursors, self._cursor),
        )

    def previous_page(self) -> InboxPageOutcome:
        self._ensure_open()
        if not self._previous_cursors:
            return InboxPageOutcome(page=self._last_page)
        return self._load_page(
            cursor=self._previous_cursors[-1],
            previous=self._previous_cursors[:-1],
        )

    def _load_page(
        self,
        *,
        cursor: str | None,
        previous: tuple[str | None, ...],
    ) -> InboxPageOutcome:
        try:
            result = self._operations.list(
                ListCapturesRequest(
                    routing_status="unassigned",
                    limit=self._page_size,
                    cursor=cursor,
                ),
                config_path=self._config_path,
                path_policy=self._path_policy,
            )
        except Exception:
            return InboxPageOutcome(failure=_internal_failure(write=False))
        if isinstance(result, FailureResult):
            return InboxPageOutcome(
                failure=_failure_from_result(result, retry_available=False)
            )
        try:
            items = tuple(_entry(item) for item in result.items)
            notices = _warning_notices(result.warnings)
            page = InboxPage(
                items=items,
                page_number=len(previous) + 1,
                has_previous=bool(previous),
                has_next=result.next_cursor is not None,
            )
        except Exception:
            return InboxPageOutcome(failure=_internal_failure(write=False))
        self._cursor = cursor
        self._previous_cursors = previous
        self._next_cursor = result.next_cursor
        self._last_page = page
        if (
            self._pending is not None
            and self._pending.commit_state == CommitState.UNKNOWN.value
        ):
            self._pending.reviewed_after_unknown = True
        return InboxPageOutcome(page=page, notices=notices)

    def open_capture(
        self,
        capture_id: str,
        *,
        version: int | None = None,
    ) -> InboxReadOutcome:
        self._ensure_open()
        sink = io.BytesIO()
        try:
            request = GetCaptureRequest(
                capture_id=capture_id,
                version=version,
                body_sink=sink,
            )
            result = self._operations.get(
                request,
                config_path=self._config_path,
                path_policy=self._path_policy,
            )
        except Exception:
            sink.close()
            return InboxReadOutcome(failure=_internal_failure(write=False))
        if isinstance(result, FailureResult):
            sink.close()
            return InboxReadOutcome(
                failure=_failure_from_result(result, retry_available=False)
            )
        try:
            body = sink.getvalue()
            text = body.decode("utf-8", errors="strict")
            metadata = result.capture
            document = InboxDocument(
                capture_id=metadata.capture_id,
                version=metadata.version,
                current_version=metadata.current_version,
                captured_at=metadata.captured_at,
                byte_size=metadata.byte_size,
                primary_payload_sha256=metadata.primary_payload_sha256,
                envelope_sha256=metadata.envelope_sha256,
                routing_status=result.item_state.routing_status,
                trust_status=result.item_state.trust_status,
                text=text,
            )
            notices = _warning_notices(result.warnings)
        except Exception:
            return InboxReadOutcome(failure=_internal_failure(write=False))
        finally:
            sink.close()
        self._current_document = document
        if (
            self._pending is not None
            and self._pending.commit_state == CommitState.UNKNOWN.value
        ):
            self._pending.reviewed_after_unknown = True
        return InboxReadOutcome(document=document, notices=notices)

    def capture(self, text: str) -> InboxWriteOutcome:
        self._ensure_open()
        selected, failure = self._select_pending(
            operation="capture_text",
            text=text,
            capture_id=None,
            expected_current_version=None,
        )
        if failure is not None:
            return InboxWriteOutcome(failure=failure)
        assert selected is not None
        return self._execute_pending(selected)

    def append(
        self,
        *,
        capture_id: str,
        expected_current_version: int,
        text: str,
    ) -> InboxWriteOutcome:
        self._ensure_open()
        selected, failure = self._select_pending(
            operation="append_capture_version",
            text=text,
            capture_id=capture_id,
            expected_current_version=expected_current_version,
        )
        if failure is not None:
            return InboxWriteOutcome(failure=failure)
        assert selected is not None
        return self._execute_pending(selected)

    def retry_pending(self) -> InboxWriteOutcome:
        self._ensure_open()
        if self._pending is None:
            return InboxWriteOutcome(
                failure=InboxFailure(
                    code="no_pending_request",
                    title="没有可重试请求",
                    message="当前进程中没有保留待重试的写入请求。",
                )
            )
        return self._execute_pending(self._pending)

    def abandon_pending(self) -> InboxFailure | None:
        """Forget a request only after an unknown result has been reviewed."""

        self._ensure_open()
        if self._pending is None:
            return None
        if (
            self._pending.commit_state == CommitState.UNKNOWN.value
            and not self._pending.reviewed_after_unknown
        ):
            return InboxFailure(
                code="review_required",
                title="请先刷新核对",
                message=(
                    "该写入结果仍不明确。请先刷新收件箱或重新读取相关 Capture，"
                    "再决定是否放弃同一身份的安全重试。"
                ),
                commit_state=CommitState.UNKNOWN.value,
                retry_available=True,
            )
        self._pending = None
        return None

    def _select_pending(
        self,
        *,
        operation: PendingOperation,
        text: str,
        capture_id: str | None,
        expected_current_version: int | None,
    ) -> tuple[_PendingWrite | None, InboxFailure | None]:
        if type(text) is not str:
            return None, InboxFailure(
                code="invalid_input",
                title="输入无效",
                message="正文必须是文本。",
                commit_state=CommitState.NOT_COMMITTED.value,
            )
        current = self._pending
        same_request = (
            current is not None
            and current.operation == operation
            and current.text == text
            and current.capture_id == capture_id
            and current.expected_current_version == expected_current_version
        )
        if same_request:
            return current, None
        if current is not None and current.commit_state == CommitState.UNKNOWN.value:
            return None, InboxFailure(
                code="pending_unknown_request",
                title="存在结果不明的写入",
                message=(
                    "不能用新正文或新目标替换尚未核实的请求。请重试原请求，"
                    "或先刷新核对后明确放弃。"
                ),
                commit_state=CommitState.UNKNOWN.value,
                retryable=True,
                retry_available=True,
            )
        try:
            key = self._idempotency_key_factory()
            if type(key) is not str or not key:
                raise ValueError("invalid key")
        except Exception:
            return None, InboxFailure(
                code="request_identity_unavailable",
                title="无法创建请求身份",
                message=(
                    "尚未调用 Capture 写入操作，提交状态：确认未保存。"
                    "请保留正文并重新启动本地收件箱。"
                ),
                commit_state=CommitState.NOT_COMMITTED.value,
            )
        pending = _PendingWrite(
            operation=operation,
            text=text,
            idempotency_key=key,
            capture_id=capture_id,
            expected_current_version=expected_current_version,
        )
        self._pending = pending
        return pending, None

    def _execute_pending(self, pending: _PendingWrite) -> InboxWriteOutcome:
        try:
            if pending.operation == "capture_text":
                request = CaptureTextRequest(
                    text=pending.text,
                    channel=_CHANNEL,
                    idempotency_key=pending.idempotency_key,
                    user_intent=_CAPTURE_ONLY,
                )
                expected_type: type[object] = CommittedWriteResult
            else:
                if (
                    pending.capture_id is None
                    or pending.expected_current_version is None
                ):
                    raise TypeError("append pending state is incomplete")
                request = AppendCaptureVersionRequest(
                    capture_id=pending.capture_id,
                    expected_current_version=pending.expected_current_version,
                    text=pending.text,
                    channel=_CHANNEL,
                    idempotency_key=pending.idempotency_key,
                    user_intent=_CAPTURE_ONLY,
                )
                expected_type = AppendCaptureVersionResult
        except (TypeError, ValueError):
            pending.commit_state = CommitState.NOT_COMMITTED.value
            return InboxWriteOutcome(
                failure=_failure_from_result(
                    FailureResult(
                        error=OperationError(
                            code=PublicErrorCode.INVALID_INPUT,
                            retryable=False,
                        ),
                        commit_state=CommitState.NOT_COMMITTED,
                    ),
                    retry_available=True,
                )
            )

        try:
            if pending.operation == "capture_text":
                result = self._operations.capture(
                    request,
                    config_path=self._config_path,
                    path_policy=self._path_policy,
                )
            else:
                result = self._operations.append(
                    request,
                    config_path=self._config_path,
                    path_policy=self._path_policy,
                )
        except Exception:
            pending.commit_state = CommitState.UNKNOWN.value
            pending.reviewed_after_unknown = False
            return InboxWriteOutcome(failure=_internal_failure(write=True))

        if isinstance(result, FailureResult):
            pending.commit_state = (
                result.commit_state.value
                if result.commit_state is not None
                else CommitState.UNKNOWN.value
            )
            if pending.commit_state == CommitState.UNKNOWN.value:
                pending.reviewed_after_unknown = False
            return InboxWriteOutcome(
                failure=_failure_from_result(result, retry_available=True)
            )
        if not isinstance(result, expected_type):
            pending.commit_state = CommitState.UNKNOWN.value
            pending.reviewed_after_unknown = False
            return InboxWriteOutcome(failure=_internal_failure(write=True))
        try:
            capture_id = result.receipt["capture_id"]
            version = result.receipt["version"]
            if type(capture_id) is not str or type(version) is not int:
                raise TypeError("invalid receipt")
            receipt = InboxWriteReceipt(
                operation=pending.operation,
                capture_id=capture_id,
                version=version,
                commit_state=CommitState.COMMITTED.value,
            )
            notices = _warning_notices(result.warnings)
        except Exception:
            pending.commit_state = CommitState.UNKNOWN.value
            pending.reviewed_after_unknown = False
            return InboxWriteOutcome(failure=_internal_failure(write=True))
        self._pending = None
        return InboxWriteOutcome(receipt=receipt, notices=notices)


__all__ = [
    "InboxDocument",
    "InboxEntry",
    "InboxFailure",
    "InboxNotice",
    "InboxOperationBoundary",
    "InboxPage",
    "InboxPageOutcome",
    "InboxPendingState",
    "InboxReadOutcome",
    "InboxSession",
    "InboxWriteOutcome",
    "InboxWriteReceipt",
]
