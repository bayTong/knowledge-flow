"""Small offline, read-only Tk reviewer for a published no-target map."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from knowledgeflow_capture.runtime import production_path_policy

from .contracts import MapCandidate
from .review import MapReviewError, MapReviewSession, VerifiedExcerpt, load_map_review


_PROVENANCE_LABELS = {
    "source-claim": "原文表达",
    "quoted-claim": "原文直接引述",
    "processor-inference": "处理器归纳",
    "user-revision": "用户修订",
    "unverified": "尚未核实",
}
_UNCERTAINTY_LABELS = {
    "none": "未标记",
    "low": "低",
    "medium": "中",
    "high": "高",
    "unknown": "未知",
}
_SCOPE_LABELS = {
    "processed": "已处理",
    "deferred": "已延期",
    "failed": "处理失败",
    "excluded-by-user": "用户排除",
}


def _candidate_title(candidate: MapCandidate) -> str:
    first = candidate.summary.splitlines()[0].strip()
    return first if len(first) <= 18 else first[:17].rstrip() + "…"


def _scope_text(session: MapReviewSession) -> str:
    result = [
        f"来源字节数：{session.curation_map.source.byte_size}",
        "处理范围：",
    ]
    for item in session.curation_map.scope:
        reason = f"；原因：{item.reason}" if item.reason else ""
        result.append(
            f"• {_SCOPE_LABELS[item.status]} [{item.byte_range.start_byte}, "
            f"{item.byte_range.end_byte}){reason}"
        )
    result.append("\n范围完整只说明处理记录覆盖了声明范围，不保证语义零遗漏。")
    return "\n".join(result)


def _run_text(session: MapReviewSession) -> str:
    value = session.curation_map
    usage = value.processor_usage
    return "\n".join(
        (
            f"地图：v{value.map_version}；来源：Capture v{value.source.capture_version}",
            f"处理器：{value.processor_profile.processor_id}",
            f"模型：{value.processor_profile.model_id or '无'}",
            f"调用：{usage.call_count} 次；输入 {usage.input_tokens} token；"
            f"输出 {usage.output_tokens} token",
            f"用时：{usage.elapsed_ms} ms",
            "本界面只读，不会发送模型请求或修改地图、来源和知识库。",
        )
    )


class _TkMapReviewWindow:
    def __init__(self, root: object, session: MapReviewSession) -> None:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk

        self._root = root
        self._session = session
        self._messagebox = messagebox
        self._candidate_by_row: dict[str, MapCandidate] = {}
        self._static_by_row: dict[str, str] = {}
        self._selected_candidate: MapCandidate | None = None
        self._locator_ids: tuple[str, ...] = ()
        self._status = tk.StringVar(value="请选择左侧条目。此窗口只读。")
        self._heading = tk.StringVar(value="策展地图 · 未审核候选")
        self._evidence_meta = tk.StringVar(value="请选择带证据的候选。")

        root.title("KnowledgeFlow · 地图阅读与原文核验")
        root.geometry("1300x760")
        root.minsize(1050, 600)

        header = ttk.Frame(root, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(header, textvariable=self._heading, font=("Segoe UI", 15, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text=(
                f"地图 v{session.curation_map.map_version} · 来源 Capture "
                f"v{session.curation_map.source.capture_version} · "
                "可读视图来自已发布地图；原文点击后重新核验"
            ),
        ).pack(anchor="w", pady=(4, 0))

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = ttk.Frame(panes, padding=(0, 4))
        middle = ttk.Frame(panes, padding=(8, 4))
        right = ttk.Frame(panes, padding=(8, 4))
        panes.add(left, weight=0)
        panes.add(middle, weight=1)
        panes.add(right, weight=1)

        ttk.Label(left, text="阅读目录与条目", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        style = ttk.Style(root)
        style.configure("MapReview.Treeview", font=("Segoe UI", 11), rowheight=26)
        self._tree = ttk.Treeview(
            left, show="tree", selectmode="browse", style="MapReview.Treeview"
        )
        self._tree.column("#0", width=280, minwidth=250, stretch=True)
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._select_row)

        ttk.Label(middle, text="地图内容", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        self._summary = scrolledtext.ScrolledText(
            middle, wrap="word", font=("Segoe UI", 12), padx=12, pady=10
        )
        self._summary.pack(fill="both", expand=True)
        self._summary.configure(state="disabled")

        ttk.Label(right, text="原文证据", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        self._locator_choice = ttk.Combobox(right, state="disabled")
        self._locator_choice.pack(fill="x")
        self._locator_choice.bind("<<ComboboxSelected>>", self._select_locator)
        ttk.Label(right, textvariable=self._evidence_meta, wraplength=520).pack(
            anchor="w", fill="x", pady=(6, 6)
        )
        self._source = scrolledtext.ScrolledText(
            right, wrap="word", font=("Consolas", 11), padx=10, pady=10
        )
        self._source.pack(fill="both", expand=True)
        self._source.configure(state="disabled")

        footer = ttk.Frame(root, padding=(12, 4))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self._status, wraplength=1200).pack(anchor="w")
        self._populate_tree()

    def _set_text(self, widget: object, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _populate_tree(self) -> None:
        for section in self._session.sections:
            parent = self._tree.insert("", "end", text=section.title, open=True)
            if not section.candidates:
                self._static_by_row[parent] = (
                    "本次暂不选库，因此不拟定知识库结构。"
                    if section.title.startswith("8.")
                    and self._session.curation_map.target_binding is None
                    else "本次未形成可支持的候选。"
                )
            for candidate in section.candidates:
                row = self._tree.insert(parent, "end", text=_candidate_title(candidate))
                self._candidate_by_row[row] = candidate
        run = self._tree.insert("", "end", text="9. 处理记录")
        scope = self._tree.insert("", "end", text="10. 覆盖报告")
        self._static_by_row[run] = _run_text(self._session)
        self._static_by_row[scope] = _scope_text(self._session)

    def _clear_evidence(self, message: str) -> None:
        self._locator_ids = ()
        self._locator_choice.configure(state="disabled", values=())
        self._locator_choice.set("")
        self._evidence_meta.set(message)
        self._set_text(self._source, "")

    def _select_row(self, _event: object) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        row = selected[0]
        candidate = self._candidate_by_row.get(row)
        self._selected_candidate = candidate
        if candidate is None:
            self._heading.set(self._tree.item(row, "text"))
            self._set_text(
                self._summary,
                self._static_by_row.get(row, "请选择本节下面的一条候选。"),
            )
            self._clear_evidence("本项没有单独的原文证据。")
            self._status.set("本界面只读；审核决定和修改仍由现有受控操作处理。")
            return
        self._heading.set(self._tree.item(self._tree.parent(row), "text"))
        self._set_text(
            self._summary,
            candidate.summary
            + "\n\n"
            + f"来源属性：{_PROVENANCE_LABELS[candidate.provenance]}"
            + f"  ·  不确定性：{_UNCERTAINTY_LABELS[candidate.uncertainty]}",
        )
        self._locator_ids = candidate.evidence_locator_ids
        if not self._locator_ids:
            self._clear_evidence("此项没有精确证据；请按缺口或组织建议阅读。")
            self._status.set("没有可打开的原文范围。")
            return
        labels = tuple(
            f"证据 {index}/{len(self._locator_ids)} · {self._session.locator_label(item)}"
            for index, item in enumerate(self._locator_ids, 1)
        )
        self._locator_choice.configure(state="readonly", values=labels)
        self._locator_choice.current(0)
        self._open_locator(0)

    def _select_locator(self, _event: object) -> None:
        self._open_locator(self._locator_choice.current())

    def _open_locator(self, index: int) -> None:
        candidate = self._selected_candidate
        if candidate is None or index < 0 or index >= len(self._locator_ids):
            return
        self._clear_source_only()
        self._status.set("正在从精确 Capture 版本核验原文……")
        self._root.update_idletasks()
        try:
            excerpt = self._session.read_evidence(
                candidate.candidate_id, self._locator_ids[index]
            )
        except MapReviewError as exc:
            self._evidence_meta.set("原文未显示：核验失败。")
            self._status.set(str(exc))
            self._messagebox.showerror("原文核验失败", str(exc))
            return
        self._show_excerpt(excerpt)

    def _clear_source_only(self) -> None:
        self._evidence_meta.set("正在核验……")
        self._set_text(self._source, "")

    def _show_excerpt(self, excerpt: VerifiedExcerpt) -> None:
        max_chars = 64 * 1024
        shown = excerpt.text[:max_chars]
        truncated = len(excerpt.text) > max_chars
        span = (
            str(excerpt.start_line)
            if excerpt.start_line == excerpt.end_line
            else f"{excerpt.start_line}–{excerpt.end_line}"
        )
        granularity = "整份来源（证据粒度过粗）" if excerpt.whole_source else "精确范围"
        self._evidence_meta.set(
            f"已核验 · 原文第 {span} 行 · byte [{excerpt.start_byte}, "
            f"{excerpt.end_byte}) · {granularity}"
        )
        if truncated:
            shown += "\n\n[界面只显示前 64 Ki 字符；完整范围已核验，后续需分段定位。]"
        self._set_text(self._source, shown)
        warning = (
            "；Capture 警告：" + "、".join(excerpt.warning_codes)
            if excerpt.warning_codes
            else ""
        )
        self._status.set("原文已按来源版本、字节范围和摘要核验" + warning + "。")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="knowledgeflow-map-review",
        description="只读打开实验根内的无目标策展地图与原文证据。",
    )
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--map-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        session = load_map_review(
            experiment_root=arguments.experiment_root,
            map_directory=arguments.map_dir,
            path_policy=production_path_policy(),
        )
    except (MapReviewError, OSError, RuntimeError) as exc:
        print(f"knowledgeflow-map-review: {exc}", file=sys.stderr)
        return 1
    try:
        import tkinter as tk
    except ImportError as exc:
        print(f"knowledgeflow-map-review: Tk 不可用：{exc}", file=sys.stderr)
        return 1

    try:
        root = tk.Tk()
        _TkMapReviewWindow(root, session)
        root.mainloop()
    except (MapReviewError, OSError, RuntimeError, tk.TclError) as exc:
        print(f"knowledgeflow-map-review: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
