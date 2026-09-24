"""Test-only subprocess entry for the private Capture CLI runner."""

from __future__ import annotations

from pathlib import Path
import sys


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from knowledgeflow_capture.cli import _execute_operation, _run_cli
from knowledgeflow_capture.paths import PathPolicy


def main() -> int:
    if len(sys.argv) < 3:
        return 70
    owned_root = Path(sys.argv[1])
    return _run_cli(
        sys.argv[2:],
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
        path_policy=PathPolicy.test_owned(owned_root),
        executor=_execute_operation,
    )


if __name__ == "__main__":
    raise SystemExit(main())
