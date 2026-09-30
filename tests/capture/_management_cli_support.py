"""Test-only subprocess entry for an installed P0B management package."""

from __future__ import annotations

from pathlib import Path
import sys

from knowledgeflow_capture.management_cli import (
    _execute_management_operation,
    _run_management_cli,
)
from knowledgeflow_capture.paths import PathPolicy


def main() -> int:
    if len(sys.argv) < 3:
        return 70
    owned_root = Path(sys.argv[1])
    return _run_management_cli(
        sys.argv[2:],
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
        path_policy=PathPolicy.test_owned(owned_root),
        executor=_execute_management_operation,
    )


if __name__ == "__main__":
    raise SystemExit(main())
