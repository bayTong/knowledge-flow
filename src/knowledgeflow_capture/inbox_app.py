"""Installed Tk desktop entry for the P0C minimal local inbox."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import sys
from typing import TextIO

from .config import resolve_config_path
from .inbox import (
    InboxDocument,
    InboxFailure,
    InboxNotice,
    InboxPageOutcome,
    InboxReadOutcome,
    InboxSession,
    InboxWriteOutcome,
)
from .runtime import production_path_policy


_HELP = """KnowledgeFlow 最小本地收件箱

用法:
  knowledgeflow-inbox
  knowledgeflow-inbox --config <Windows 本地绝对路径>
  knowledgeflow-inbox --help

默认读取 %LOCALAPPDATA%\\KnowledgeFlow\\config.yaml。
本入口不会初始化、修复或删除 Capture Store，也不需要网络或 GitHub 登录。
"""
_INVALID_ARGUMENTS = "knowledgeflow-inbox: invalid arguments\n"
_INTERNAL_FAILURE = "knowledgeflow-inbox: internal failure\n"


def _write_text(stream: TextIO, value: str) -> None:
    written = stream.write(value)
    if written is not None and written != len(value):
        raise OSError("short text write")
    stream.flush()


def _reconfigure_utf8_text_stream(stream: TextIO) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")


def _parse_arguments(argv: Sequence[str]) -> tuple[bool, Path | None]:
    values = tuple(argv)
    if not values:
        return False, None
    if values == ("--help",):
        return True, None
    if len(values) == 2 and values[0] == "--config":
        return False, resolve_config_path(values[1])
    raise ValueError("invalid arguments")


def _format_notices(notices: tuple[InboxNotice, ...]) -> str:
    return "\n".join(f"⚠ {notice.title}：{notice.message}" for notice in notices)


class _TkInboxWindow:
    """Small Tk view; all persistence remains inside ``InboxSession``."""

    def __init__(
        self,
        root: object,
        session: InboxSession,
        *,
        tk: object,
        ttk: object,
        scrolledtext: object,
        messagebox: object,
    ) -> None:
        self._root = root
        self._session = session
        self._tk = tk
        self._ttk = ttk
        self._messagebox = messagebox
        self._configured_ready = False
        self._draft_capture_id: str | None = None
        self._draft_expected_version: int | None = None
        self._status = tk.StringVar(
            value=(
                "草稿和重试身份只在本次进程中保留；异常退出后不会自动重发，"
                "请先刷新核对。"
            )
        )
        self._page_status = tk.StringVar(value="第 1 页")
        self._detail_meta = tk.StringVar(value="请选择一条 Capture。")
        self._detail_warning = tk.StringVar(value="")
        self._editor_mode = tk.StringVar(value="新建 Capture")
        self._byte_count = tk.StringVar(value="0 UTF-8 字节")

        root.title("KnowledgeFlow 本地收件箱")
        root.geometry("1120x780")
        root.minsize(860, 620)
        root.report_callback_exception = self._report_callback_exception
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build(scrolledtext)
        root.after_idle(self._refresh)

    def _build(self, scrolledtext: object) -> None:
        ttk = self._ttk
        tk = self._tk
        root = self._root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, padding=(12, 10, 12, 6))
        header.grid(row=0, column=0, sticky="nsew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            textvariable=self._status,
            wraplength=850,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="刷新收件箱", command=self._refresh).grid(
            row=0, column=1, padx=(8, 0)
        )
        self._new_button = ttk.Button(
            header,
            text="新建",
            command=self._start_new,
            state="disabled",
        )
        self._new_button.grid(row=0, column=2, padx=(8, 0))

        panes = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        list_frame = ttk.Frame(panes, padding=6)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self._tree = ttk.Treeview(
            list_frame,
            columns=("time", "version", "state", "preview"),
            show="headings",
            selectmode="browse",
        )
        self._tree.heading("time", text="捕获时间")
        self._tree.heading("version", text="版本")
        self._tree.heading("state", text="状态")
        self._tree.heading("preview", text="预览")
        self._tree.column("time", width=145, stretch=False)
        self._tree.column("version", width=50, anchor="center", stretch=False)
        self._tree.column("state", width=105, stretch=False)
        self._tree.column("preview", width=300, stretch=True)
        tree_scroll = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self._tree.yview,
        )
        self._tree.configure(yscrollcommand=tree_scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._open_selected)

        paging = ttk.Frame(list_frame, padding=(0, 8, 0, 0))
        paging.grid(row=1, column=0, columnspan=2, sticky="ew")
        paging.columnconfigure(1, weight=1)
        self._previous_button = ttk.Button(
            paging,
            text="上一页",
            command=self._previous_page,
            state="disabled",
        )
        self._previous_button.grid(row=0, column=0)
        ttk.Label(paging, textvariable=self._page_status, anchor="center").grid(
            row=0, column=1, sticky="ew"
        )
        self._next_button = ttk.Button(
            paging,
            text="下一页",
            command=self._next_page,
            state="disabled",
        )
        self._next_button.grid(row=0, column=2)
        panes.add(list_frame, weight=2)

        right = ttk.Notebook(panes)
        panes.add(right, weight=3)

        detail = ttk.Frame(right, padding=8)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(2, weight=1)
        ttk.Label(
            detail,
            textvariable=self._detail_meta,
            wraplength=600,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            detail,
            textvariable=self._detail_warning,
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(5, 5))
        self._detail_text = scrolledtext.ScrolledText(
            detail,
            wrap=tk.WORD,
            undo=False,
            state="disabled",
        )
        self._detail_text.grid(row=2, column=0, sticky="nsew")
        self._append_button = ttk.Button(
            detail,
            text="以当前完整正文追加新版本",
            command=self._start_append,
            state="disabled",
        )
        self._append_button.grid(row=3, column=0, sticky="e", pady=(8, 0))
        right.add(detail, text="阅读")

        editor = ttk.Frame(right, padding=8)
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(2, weight=1)
        ttk.Label(editor, textvariable=self._editor_mode).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            editor,
            text=(
                "追加会保存一个完整的新版本，不会覆盖历史。当前没有自动草稿恢复。"
            ),
            wraplength=600,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(3, 5))
        self._editor_text = scrolledtext.ScrolledText(
            editor,
            wrap=tk.WORD,
            undo=True,
        )
        self._editor_text.grid(row=2, column=0, sticky="nsew")
        self._editor_text.bind("<<Modified>>", self._editor_modified)

        actions = ttk.Frame(editor, padding=(0, 8, 0, 0))
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self._byte_count).grid(
            row=0, column=0, sticky="w"
        )
        self._abandon_button = ttk.Button(
            actions,
            text="放弃上次请求",
            command=self._abandon_pending,
            state="disabled",
        )
        self._abandon_button.grid(row=0, column=1, padx=(8, 0))
        self._retry_button = ttk.Button(
            actions,
            text="重试上次保存",
            command=self._retry_pending,
            state="disabled",
        )
        self._retry_button.grid(row=0, column=2, padx=(8, 0))
        self._save_button = ttk.Button(
            actions,
            text="保存",
            command=self._save,
        )
        self._save_button.grid(row=0, column=3, padx=(8, 0))
        right.add(editor, text="编写")
        self._notebook = right

    def _report_callback_exception(self, *_ignored: object) -> None:
        self._status.set(
            "本地界面内部失败。未显示 traceback、路径或正文；请停止操作并重新启动。"
        )

    def _failure_text(self, failure: InboxFailure) -> str:
        state = ""
        if failure.commit_state == "unknown":
            state = "（提交状态：结果不明）"
        elif failure.commit_state == "not-committed":
            state = "（提交状态：确认未保存）"
        return f"{failure.title}{state} [{failure.code}]：{failure.message}"

    def _set_status_from_failure(self, failure: InboxFailure) -> None:
        self._status.set(self._failure_text(failure))
        self._sync_pending_controls()

    def _render_page(self, outcome: InboxPageOutcome) -> None:
        if outcome.failure is not None:
            if outcome.failure.code in {
                "config_not_found",
                "config_invalid",
                "unrecognized_existing_directory",
                "unsupported_store_version",
                "config_store_conflict",
                "capture_store_not_initialized",
                "capture_store_unavailable",
                "integrity_check_failed",
                "internal_failure",
            }:
                self._configured_ready = False
            self._set_status_from_failure(outcome.failure)
            return
        page = outcome.page
        if page is None:
            return
        self._configured_ready = True
        for item_id in self._tree.get_children():
            self._tree.delete(item_id)
        for item in page.items:
            preview = " ".join(item.preview.splitlines())
            self._tree.insert(
                "",
                "end",
                iid=item.capture_id,
                values=(
                    item.captured_at,
                    f"v{item.current_version}",
                    "未分配 / 待处理",
                    preview,
                ),
            )
        self._page_status.set(f"第 {page.page_number} 页 · {len(page.items)} 项")
        self._previous_button.configure(
            state="normal" if page.has_previous else "disabled"
        )
        self._next_button.configure(state="normal" if page.has_next else "disabled")
        if outcome.notices:
            self._status.set(_format_notices(outcome.notices))
        elif page.items:
            self._status.set("收件箱已刷新。所有条目均映射为“未分配 / 待处理”。")
        else:
            self._status.set("收件箱为空。可以在“编写”页新建文本 Capture。")
        pending = self._session.pending_state
        if pending is not None and pending.commit_state == "unknown":
            self._status.set(
                "收件箱已刷新；上次写入仍保留为“结果不明”。"
                "可以重试同一请求，或在人工核对后明确放弃。"
            )
        self._sync_pending_controls()

    def _refresh(self) -> None:
        self._render_page(self._session.first_page())

    def _next_page(self) -> None:
        self._render_page(self._session.next_page())

    def _previous_page(self) -> None:
        self._render_page(self._session.previous_page())

    def _open_selected(self, _event: object | None = None) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        self._render_document(self._session.open_capture(selected[0]))

    def _set_widget_text(self, widget: object, value: str, *, readonly: bool) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled" if readonly else "normal")

    def _render_document(self, outcome: InboxReadOutcome) -> None:
        if outcome.failure is not None:
            self._set_status_from_failure(outcome.failure)
            return
        document = outcome.document
        if document is None:
            return
        self._detail_meta.set(
            f"{document.capture_id}\n"
            f"版本 v{document.version}（当前 v{document.current_version}） · "
            f"{document.byte_size} UTF-8 字节 · {document.captured_at}\n"
            f"未分配 / 待处理 · 正文 SHA-256：{document.primary_payload_sha256}"
        )
        self._detail_warning.set(_format_notices(outcome.notices))
        self._set_widget_text(self._detail_text, document.text, readonly=True)
        self._status.set(
            _format_notices(outcome.notices)
            if outcome.notices
            else "正文完整性校验通过。"
        )
        self._sync_pending_controls()

    def _confirm_replace_pending(self) -> bool:
        pending = self._session.pending_state
        if pending is None:
            return True
        if pending.commit_state == "unknown" and not pending.reviewed_after_unknown:
            self._status.set(
                "上次写入结果不明；请先刷新收件箱或重新读取相关 Capture。"
            )
            return False
        confirmed = self._messagebox.askyesno(
            "放弃待重试请求",
            "放弃后会丢失本进程保存的幂等重试身份。若上次结果不明，"
            "再次用新身份保存可能产生重复 Capture。确认继续吗？",
        )
        if not confirmed:
            return False
        failure = self._session.abandon_pending()
        if failure is not None:
            self._set_status_from_failure(failure)
            return False
        return True

    def _start_new(self) -> None:
        if not self._configured_ready:
            self._status.set(
                "本机 Capture 尚未处于可用状态；本界面不会自行初始化或修复。"
            )
            return
        if not self._confirm_replace_pending():
            return
        self._draft_capture_id = None
        self._draft_expected_version = None
        self._editor_mode.set("新建 Capture")
        self._set_widget_text(self._editor_text, "", readonly=False)
        self._notebook.select(1)
        self._editor_text.focus_set()
        self._sync_pending_controls()

    def _start_append(self) -> None:
        if not self._configured_ready:
            self._status.set(
                "本机 Capture 尚未处于可用状态；本界面不会自行初始化或修复。"
            )
            return
        document = self._session.current_document
        if document is None:
            self._status.set("请先从收件箱选择并完整读取一条 Capture。")
            return
        if not self._confirm_replace_pending():
            return
        self._draft_capture_id = document.capture_id
        self._draft_expected_version = document.current_version
        self._editor_mode.set(
            f"追加 {document.capture_id} · 基于当前 v{document.current_version}"
        )
        self._set_widget_text(self._editor_text, document.text, readonly=False)
        self._notebook.select(1)
        self._editor_text.focus_set()
        self._sync_pending_controls()

    def _editor_modified(self, _event: object | None = None) -> None:
        try:
            if not self._editor_text.edit_modified():
                return
            text = self._editor_text.get("1.0", "end-1c")
            self._byte_count.set(f"{len(text.encode('utf-8'))} UTF-8 字节")
            self._editor_text.edit_modified(False)
        except Exception:
            self._byte_count.set("字节数不可用")

    def _save(self) -> None:
        if not self._configured_ready:
            self._status.set(
                "本机 Capture 尚未处于可用状态；本界面不会自行初始化或修复。"
            )
            return
        text = self._editor_text.get("1.0", "end-1c")
        if self._draft_capture_id is None:
            outcome = self._session.capture(text)
        else:
            if self._draft_expected_version is None:
                self._status.set("追加目标状态无效，请重新打开该 Capture。")
                return
            outcome = self._session.append(
                capture_id=self._draft_capture_id,
                expected_current_version=self._draft_expected_version,
                text=text,
            )
        self._render_write(outcome)

    def _retry_pending(self) -> None:
        self._render_write(self._session.retry_pending())

    def _abandon_pending(self) -> None:
        if self._confirm_replace_pending():
            self._status.set(
                "已放弃上次请求的进程内重试身份；再次保存将成为新请求。"
            )
            self._sync_pending_controls()

    def _render_write(self, outcome: InboxWriteOutcome) -> None:
        if outcome.failure is not None:
            self._set_status_from_failure(outcome.failure)
            return
        receipt = outcome.receipt
        if receipt is None:
            return
        self._draft_capture_id = None
        self._draft_expected_version = None
        self._editor_mode.set("新建 Capture")
        self._set_widget_text(self._editor_text, "", readonly=False)
        page_outcome = self._session.first_page()
        self._render_page(page_outcome)
        read_outcome = self._session.open_capture(receipt.capture_id)
        self._render_document(read_outcome)
        status_parts = [f"已提交 {receipt.capture_id} v{receipt.version}。"]
        all_notices = outcome.notices + page_outcome.notices + read_outcome.notices
        if all_notices:
            status_parts.append(_format_notices(all_notices))
        if page_outcome.failure is not None:
            status_parts.append(
                "提交后的收件箱刷新未完成："
                + self._failure_text(page_outcome.failure)
            )
        if read_outcome.failure is not None:
            status_parts.append(
                "提交后的正文回读未完成："
                + self._failure_text(read_outcome.failure)
            )
        self._status.set("\n".join(status_parts))
        self._sync_pending_controls()

    def _sync_pending_controls(self) -> None:
        pending = self._session.pending_state
        self._new_button.configure(
            state="normal" if self._configured_ready else "disabled"
        )
        self._append_button.configure(
            state=(
                "normal"
                if self._configured_ready
                and self._session.current_document is not None
                else "disabled"
            )
        )
        if pending is None:
            self._retry_button.configure(state="disabled")
            self._abandon_button.configure(state="disabled")
            state = "normal" if self._configured_ready else "disabled"
            self._save_button.configure(state=state)
            self._editor_text.configure(state=state)
            return
        self._retry_button.configure(state="normal")
        can_abandon = (
            pending.commit_state != "unknown" or pending.reviewed_after_unknown
        )
        self._abandon_button.configure(state="normal" if can_abandon else "disabled")
        if pending.commit_state == "unknown":
            self._save_button.configure(state="disabled")
            self._editor_text.configure(state="disabled")
        else:
            state = "normal" if self._configured_ready else "disabled"
            self._save_button.configure(state=state)
            self._editor_text.configure(state=state)

    def _on_close(self) -> None:
        try:
            self._set_widget_text(self._detail_text, "", readonly=True)
            self._set_widget_text(self._editor_text, "", readonly=False)
            self._session.close()
        finally:
            self._root.destroy()


def _launch_tk(session: InboxSession) -> int:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    _TkInboxWindow(
        root,
        session,
        tk=tk,
        ttk=ttk,
        scrolledtext=scrolledtext,
        messagebox=messagebox,
    )
    try:
        root.mainloop()
    finally:
        session.close()
    return 0


def _run_inbox(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    path_policy_factory: Callable[[], object] = production_path_policy,
    launcher: Callable[[InboxSession], int] | None = None,
) -> int:
    try:
        help_requested, config_path = _parse_arguments(argv)
    except Exception:
        try:
            _write_text(stderr, _INVALID_ARGUMENTS)
        except Exception:
            pass
        return 2
    if help_requested:
        try:
            _write_text(stdout, _HELP)
            return 0
        except Exception:
            return 1
    session: InboxSession | None = None
    try:
        session = InboxSession(
            config_path=config_path,
            path_policy=path_policy_factory(),
        )
        selected_launcher = launcher or _launch_tk
        result = selected_launcher(session)
        if type(result) is not int:
            raise TypeError("launcher must return an integer")
        return result
    except Exception:
        try:
            _write_text(stderr, _INTERNAL_FAILURE)
        except Exception:
            pass
        return 1
    finally:
        if session is not None:
            session.close()


def main() -> int:
    """Launch the installed production inbox without exposing test policy."""

    try:
        _reconfigure_utf8_text_stream(sys.stdout)
        _reconfigure_utf8_text_stream(sys.stderr)
    except (OSError, TypeError, ValueError):
        try:
            _write_text(sys.stderr, _INTERNAL_FAILURE)
        except Exception:
            pass
        return 1
    return _run_inbox(
        sys.argv[1:],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


__all__: tuple[str, ...] = ()
