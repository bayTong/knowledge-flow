"""Subprocess helpers used only by Capture kernel tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from knowledgeflow_capture.locking import (
    _acquire_capture_write_lock,
    acquire_initialization_lock,
)
from knowledgeflow_capture.models import CaptureTextRequest, ChannelMetadata
from knowledgeflow_capture.operations import capture_text
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import (
    _InitFaultPoint,
    _StoreDependencies,
    _init_capture_store_with_dependencies,
    init_capture_store,
)


FAULT_EXIT_CODE = 70


def _write_marker(path: Path) -> None:
    with path.open("xb") as stream:
        stream.write(b"ready")
        stream.flush()


def _exit_at_fault_point() -> None:
    os._exit(FAULT_EXIT_CODE)


def _hold_lock(
    config_path: Path,
    started_path: Path,
    acquired_path: Path,
    release_path: Path,
) -> int:
    _write_marker(started_path)
    with acquire_initialization_lock(config_path):
        _write_marker(acquired_path)
        deadline = time.monotonic() + 30.0
        while not release_path.exists():
            if time.monotonic() >= deadline:
                return 2
            time.sleep(0.01)
    return 0


def _hold_capture_lock(
    capture_root: Path,
    started_path: Path,
    acquired_path: Path,
    release_path: Path,
) -> int:
    _write_marker(started_path)
    with _acquire_capture_write_lock(capture_root):
        _write_marker(acquired_path)
        deadline = time.monotonic() + 30.0
        while not release_path.exists():
            if time.monotonic() >= deadline:
                return 2
            time.sleep(0.01)
    return 0


def _wait_for_gate(gate_path: Path) -> bool:
    deadline = time.monotonic() + 30.0
    while not gate_path.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _init_store(
    owned_root: Path,
    config_path: Path,
    capture_root: Path,
    inline_threshold: int,
    maximum: int,
    started_path: Path,
    gate_path: Path,
    result_path: Path,
) -> int:
    _write_marker(started_path)
    if not _wait_for_gate(gate_path):
        return 2
    result = init_capture_store(
        config_path=config_path,
        capture_root=capture_root,
        inline_text_threshold_bytes=inline_threshold,
        max_text_version_bytes=maximum,
        path_policy=PathPolicy.test_owned(owned_root),
    )
    return _write_result(result, result_path)


def _init_store_fault(
    owned_root: Path,
    config_path: Path,
    capture_root: Path,
    inline_threshold: int,
    maximum: int,
    fault_point: str,
    result_path: Path,
) -> int:
    dependencies = _StoreDependencies(
        fault_point=_InitFaultPoint(fault_point),
        fault_hook=_exit_at_fault_point,
    )
    result = _init_capture_store_with_dependencies(
        config_path=config_path,
        capture_root=capture_root,
        inline_text_threshold_bytes=inline_threshold,
        max_text_version_bytes=maximum,
        path_policy=PathPolicy.test_owned(owned_root),
        dependencies=dependencies,
    )
    return _write_result(result, result_path)


def _capture_text(
    owned_root: Path,
    config_path: Path,
    text: str,
    idempotency_key: str,
    started_path: Path,
    gate_path: Path,
    result_path: Path,
) -> int:
    _write_marker(started_path)
    if not _wait_for_gate(gate_path):
        return 2
    result = capture_text(
        CaptureTextRequest(
            text=text,
            channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            idempotency_key=idempotency_key,
        ),
        config_path=config_path,
        path_policy=PathPolicy.test_owned(owned_root),
    )
    return _write_result(result, result_path)


def _write_result(result: object, result_path: Path) -> int:
    encoded = json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    with result_path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    holder = subparsers.add_parser("hold-lock")
    holder.add_argument("config_path", type=Path)
    holder.add_argument("started_path", type=Path)
    holder.add_argument("acquired_path", type=Path)
    holder.add_argument("release_path", type=Path)
    capture_holder = subparsers.add_parser("hold-capture-lock")
    capture_holder.add_argument("capture_root", type=Path)
    capture_holder.add_argument("started_path", type=Path)
    capture_holder.add_argument("acquired_path", type=Path)
    capture_holder.add_argument("release_path", type=Path)
    initializer = subparsers.add_parser("init-store")
    initializer.add_argument("owned_root", type=Path)
    initializer.add_argument("config_path", type=Path)
    initializer.add_argument("capture_root", type=Path)
    initializer.add_argument("inline_threshold", type=int)
    initializer.add_argument("maximum", type=int)
    initializer.add_argument("started_path", type=Path)
    initializer.add_argument("gate_path", type=Path)
    initializer.add_argument("result_path", type=Path)
    fault_initializer = subparsers.add_parser("init-store-fault")
    fault_initializer.add_argument("owned_root", type=Path)
    fault_initializer.add_argument("config_path", type=Path)
    fault_initializer.add_argument("capture_root", type=Path)
    fault_initializer.add_argument("inline_threshold", type=int)
    fault_initializer.add_argument("maximum", type=int)
    fault_initializer.add_argument("fault_point", type=str)
    fault_initializer.add_argument("result_path", type=Path)
    capturer = subparsers.add_parser("capture-text")
    capturer.add_argument("owned_root", type=Path)
    capturer.add_argument("config_path", type=Path)
    capturer.add_argument("text", type=str)
    capturer.add_argument("idempotency_key", type=str)
    capturer.add_argument("started_path", type=Path)
    capturer.add_argument("gate_path", type=Path)
    capturer.add_argument("result_path", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "hold-lock":
        return _hold_lock(
            arguments.config_path,
            arguments.started_path,
            arguments.acquired_path,
            arguments.release_path,
        )
    if arguments.command == "hold-capture-lock":
        return _hold_capture_lock(
            arguments.capture_root,
            arguments.started_path,
            arguments.acquired_path,
            arguments.release_path,
        )
    if arguments.command == "init-store":
        return _init_store(
            arguments.owned_root,
            arguments.config_path,
            arguments.capture_root,
            arguments.inline_threshold,
            arguments.maximum,
            arguments.started_path,
            arguments.gate_path,
            arguments.result_path,
        )
    if arguments.command == "init-store-fault":
        return _init_store_fault(
            arguments.owned_root,
            arguments.config_path,
            arguments.capture_root,
            arguments.inline_threshold,
            arguments.maximum,
            arguments.fault_point,
            arguments.result_path,
        )
    if arguments.command == "capture-text":
        return _capture_text(
            arguments.owned_root,
            arguments.config_path,
            arguments.text,
            arguments.idempotency_key,
            arguments.started_path,
            arguments.gate_path,
            arguments.result_path,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
