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
from knowledgeflow_capture.models import (
    AppendCaptureVersionRequest,
    CaptureTextRequest,
    ChannelMetadata,
)
from knowledgeflow_capture.operations import (
    _CaptureDependencies,
    _CaptureFaultPoint,
    _append_capture_version_with_dependencies,
    _capture_text_with_dependencies,
    append_capture_version,
    capture_text,
)
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.recovery import (
    _RebuildDependencies,
    _RebuildFaultPoint,
    _rebuild_capture_store_derived_state_with_dependencies,
    rebuild_capture_store_derived_state,
)
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


def _capture_text_c6(
    owned_root: Path,
    config_path: Path,
    text: str,
    idempotency_key: str,
    result_path: Path,
    fault_point: str | None = None,
) -> int:
    request = CaptureTextRequest(
        text=text,
        channel=ChannelMetadata(type="app", instance_id="c6a-fault"),
        idempotency_key=idempotency_key,
    )
    if fault_point is None:
        result = capture_text(
            request,
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
        )
    else:
        result = _capture_text_with_dependencies(
            request,
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
            dependencies=_CaptureDependencies(
                fault_point=_CaptureFaultPoint(fault_point),
                fault_hook=_exit_at_fault_point,
            ),
        )
    return _write_result(result, result_path)


def _append_capture_version_c6(
    owned_root: Path,
    config_path: Path,
    capture_id: str,
    expected_current_version: int,
    text: str,
    idempotency_key: str,
    result_path: Path,
    fault_point: str | None = None,
) -> int:
    request = AppendCaptureVersionRequest(
        capture_id=capture_id,
        expected_current_version=expected_current_version,
        text=text,
        channel=ChannelMetadata(type="app", instance_id="c6a-fault"),
        idempotency_key=idempotency_key,
    )
    if fault_point is None:
        result = append_capture_version(
            request,
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
        )
    else:
        result = _append_capture_version_with_dependencies(
            request,
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
            dependencies=_CaptureDependencies(
                fault_point=_CaptureFaultPoint(fault_point),
                fault_hook=_exit_at_fault_point,
            ),
        )
    return _write_result(result, result_path)


def _rebuild_derived_state_c6(
    owned_root: Path,
    config_path: Path,
    result_path: Path,
    fault_point: str | None = None,
) -> int:
    if fault_point is None:
        result = rebuild_capture_store_derived_state(
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
        )
    else:
        result = _rebuild_capture_store_derived_state_with_dependencies(
            config_path=config_path,
            path_policy=PathPolicy.test_owned(owned_root),
            dependencies=_RebuildDependencies(
                fault_point=_RebuildFaultPoint(fault_point),
                fault_hook=_exit_at_fault_point,
            ),
        )
    return _write_result(result, result_path)


def _capture_text_at_lock_barrier(
    owned_root: Path,
    config_path: Path,
    text: str,
    idempotency_key: str,
    lock_ready_path: Path,
    lock_gate_path: Path,
    result_path: Path,
) -> int:
    """Pause one real Capture transaction immediately before lock acquisition."""

    def acquire_after_barrier(capture_root: Path):
        _write_marker(lock_ready_path)
        if not _wait_for_gate(lock_gate_path):
            raise TimeoutError("capture lock barrier was not released")
        return _acquire_capture_write_lock(capture_root)

    result = _capture_text_with_dependencies(
        CaptureTextRequest(
            text=text,
            channel=ChannelMetadata(type="app", instance_id="local-desktop"),
            idempotency_key=idempotency_key,
        ),
        config_path=config_path,
        path_policy=PathPolicy.test_owned(owned_root),
        dependencies=_CaptureDependencies(lock_factory=acquire_after_barrier),
    )
    return _write_result(result, result_path)


def _append_capture_version_at_lock_barrier(
    owned_root: Path,
    config_path: Path,
    capture_id: str,
    expected_current_version: int,
    text: str,
    idempotency_key: str,
    lock_ready_path: Path,
    lock_gate_path: Path,
    result_path: Path,
) -> int:
    """Pause one real append transaction immediately before lock acquisition."""

    def acquire_after_barrier(capture_root: Path):
        _write_marker(lock_ready_path)
        if not _wait_for_gate(lock_gate_path):
            raise TimeoutError("append lock barrier was not released")
        return _acquire_capture_write_lock(capture_root)

    result = _append_capture_version_with_dependencies(
        AppendCaptureVersionRequest(
            capture_id=capture_id,
            expected_current_version=expected_current_version,
            text=text,
            channel=ChannelMetadata(type="app", instance_id="c5v-acceptance"),
            idempotency_key=idempotency_key,
        ),
        config_path=config_path,
        path_policy=PathPolicy.test_owned(owned_root),
        dependencies=_CaptureDependencies(lock_factory=acquire_after_barrier),
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
    barrier_capturer = subparsers.add_parser("capture-text-lock-barrier")
    barrier_capturer.add_argument("owned_root", type=Path)
    barrier_capturer.add_argument("config_path", type=Path)
    barrier_capturer.add_argument("text", type=str)
    barrier_capturer.add_argument("idempotency_key", type=str)
    barrier_capturer.add_argument("lock_ready_path", type=Path)
    barrier_capturer.add_argument("lock_gate_path", type=Path)
    barrier_capturer.add_argument("result_path", type=Path)
    barrier_appender = subparsers.add_parser(
        "append-capture-version-lock-barrier"
    )
    barrier_appender.add_argument("owned_root", type=Path)
    barrier_appender.add_argument("config_path", type=Path)
    barrier_appender.add_argument("capture_id", type=str)
    barrier_appender.add_argument("expected_current_version", type=int)
    barrier_appender.add_argument("text", type=str)
    barrier_appender.add_argument("idempotency_key", type=str)
    barrier_appender.add_argument("lock_ready_path", type=Path)
    barrier_appender.add_argument("lock_gate_path", type=Path)
    barrier_appender.add_argument("result_path", type=Path)
    c6_capturer = subparsers.add_parser("capture-text-c6")
    c6_capturer.add_argument("owned_root", type=Path)
    c6_capturer.add_argument("config_path", type=Path)
    c6_capturer.add_argument("text", type=str)
    c6_capturer.add_argument("idempotency_key", type=str)
    c6_capturer.add_argument("result_path", type=Path)
    c6_capturer.add_argument("--fault-point", type=str)
    c6_appender = subparsers.add_parser("append-capture-version-c6")
    c6_appender.add_argument("owned_root", type=Path)
    c6_appender.add_argument("config_path", type=Path)
    c6_appender.add_argument("capture_id", type=str)
    c6_appender.add_argument("expected_current_version", type=int)
    c6_appender.add_argument("text", type=str)
    c6_appender.add_argument("idempotency_key", type=str)
    c6_appender.add_argument("result_path", type=Path)
    c6_appender.add_argument("--fault-point", type=str)
    c6_rebuilder = subparsers.add_parser("rebuild-derived-state-c6")
    c6_rebuilder.add_argument("owned_root", type=Path)
    c6_rebuilder.add_argument("config_path", type=Path)
    c6_rebuilder.add_argument("result_path", type=Path)
    c6_rebuilder.add_argument("--fault-point", type=str)
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
    if arguments.command == "capture-text-lock-barrier":
        return _capture_text_at_lock_barrier(
            arguments.owned_root,
            arguments.config_path,
            arguments.text,
            arguments.idempotency_key,
            arguments.lock_ready_path,
            arguments.lock_gate_path,
            arguments.result_path,
        )
    if arguments.command == "append-capture-version-lock-barrier":
        return _append_capture_version_at_lock_barrier(
            arguments.owned_root,
            arguments.config_path,
            arguments.capture_id,
            arguments.expected_current_version,
            arguments.text,
            arguments.idempotency_key,
            arguments.lock_ready_path,
            arguments.lock_gate_path,
            arguments.result_path,
        )
    if arguments.command == "capture-text-c6":
        return _capture_text_c6(
            arguments.owned_root,
            arguments.config_path,
            arguments.text,
            arguments.idempotency_key,
            arguments.result_path,
            arguments.fault_point,
        )
    if arguments.command == "append-capture-version-c6":
        return _append_capture_version_c6(
            arguments.owned_root,
            arguments.config_path,
            arguments.capture_id,
            arguments.expected_current_version,
            arguments.text,
            arguments.idempotency_key,
            arguments.result_path,
            arguments.fault_point,
        )
    if arguments.command == "rebuild-derived-state-c6":
        return _rebuild_derived_state_c6(
            arguments.owned_root,
            arguments.config_path,
            arguments.result_path,
            arguments.fault_point,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
