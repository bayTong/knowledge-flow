"""C7V-only subprocess entry for deterministic CLI concurrency acceptance."""

from __future__ import annotations

from pathlib import Path
import sys
import time


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from knowledgeflow_capture.cli import _execute_operation, _run_cli
from knowledgeflow_capture.paths import PathPolicy


_BARRIER_TIMEOUT_SECONDS = 30.0


def _write_marker(path: Path) -> None:
    with path.open("xb") as stream:
        stream.write(b"ready")
        stream.flush()


def _wait_for_gate(path: Path) -> None:
    deadline = time.monotonic() + _BARRIER_TIMEOUT_SECONDS
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("CLI acceptance barrier was not released")
        time.sleep(0.01)


def main() -> int:
    if len(sys.argv) < 5:
        return 70

    owned_root = Path(sys.argv[1])
    ready_path = Path(sys.argv[2])
    gate_path = Path(sys.argv[3])

    def execute_after_barrier(
        operation: str,
        request: object,
        *,
        config_path: Path | None,
        path_policy: PathPolicy,
    ) -> object:
        _write_marker(ready_path)
        _wait_for_gate(gate_path)
        return _execute_operation(
            operation,
            request,
            config_path=config_path,
            path_policy=path_policy,
        )

    return _run_cli(
        sys.argv[4:],
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
        path_policy=PathPolicy.test_owned(owned_root),
        executor=execute_after_barrier,
    )


if __name__ == "__main__":
    raise SystemExit(main())
