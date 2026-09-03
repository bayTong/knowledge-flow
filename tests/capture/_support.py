"""Subprocess helpers used only by Capture kernel tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from knowledgeflow_capture.locking import acquire_initialization_lock


def _write_marker(path: Path) -> None:
    with path.open("xb") as stream:
        stream.write(b"ready")
        stream.flush()


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    holder = subparsers.add_parser("hold-lock")
    holder.add_argument("config_path", type=Path)
    holder.add_argument("started_path", type=Path)
    holder.add_argument("acquired_path", type=Path)
    holder.add_argument("release_path", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "hold-lock":
        return _hold_lock(
            arguments.config_path,
            arguments.started_path,
            arguments.acquired_path,
            arguments.release_path,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
