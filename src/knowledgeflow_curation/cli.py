"""Restricted CUR1B command-line entry with one UTF-8 JSON receipt."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.runtime import production_path_policy

from .contracts import ByteRange
from .errors import CurationCommitState, CurationError, CurationErrorCode, CurationFailure
from .operations import (
    EvidenceShowRequest,
    SourceInspectRequest,
    SourcePrepareRequest,
    inspect_source,
    prepare_source,
    show_evidence,
)


_NEXT_ACTIONS = {
    "invalid_input": "correct_arguments_and_retry",
    "source_not_found": "verify_source_path_or_request_id_and_retry",
    "source_identity_mismatch": "verify_expected_source_identity_before_retry",
    "source_integrity_failed": "stop_and_restore_the_exact_source_or_capture",
    "authorization_scope_mismatch": "correct_authorized_utf8_byte_range_and_retry",
    "unsupported_source": "provide_nonempty_strict_utf8_text_and_retry",
    "locator_invalid": "run_source_inspect_and_select_a_returned_locator",
    "evidence_integrity_failed": "stop_and_restore_verified_source_state",
    "idempotency_conflict": "use_the_original_request_or_a_new_request_id",
    "atomic_publish_failed": "verify_local_storage_then_retry_once",
    "recovery_required": "stop_and_inspect_the_request_bundle_before_retry",
}


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="knowledgeflow-curation", add_help=False)
    parser.add_argument("--experiment-root", required=True)
    groups = parser.add_subparsers(dest="group", required=True)

    source = groups.add_parser("source", add_help=False)
    source_commands = source.add_subparsers(dest="action", required=True)
    prepare = source_commands.add_parser("prepare", add_help=False)
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--source-reference", required=True)
    prepare.add_argument("--expected-sha256", required=True)
    prepare.add_argument("--expected-bytes", required=True, type=int)
    prepare.add_argument("--request-id", required=True)
    prepare.add_argument("--authorized-by", required=True)
    prepare.add_argument("--task-id", required=True, action="append")
    prepare.add_argument("--budget-id")
    prepare.add_argument("--authorized-start-byte", type=int)
    prepare.add_argument("--authorized-end-byte", type=int)
    prepare.add_argument("--declared-start-byte", type=int)
    prepare.add_argument("--declared-end-byte", type=int)

    inspect = source_commands.add_parser("inspect", add_help=False)
    inspect.add_argument("--request-id", required=True)

    evidence = groups.add_parser("evidence", add_help=False)
    evidence_commands = evidence.add_subparsers(dest="action", required=True)
    show = evidence_commands.add_parser("show", add_help=False)
    show.add_argument("--request-id", required=True)
    show.add_argument("--locator-id", required=True)
    show.add_argument("--output", required=True)
    return parser


def _optional_range(
    start: int | None,
    end: int | None,
    label: str,
) -> ByteRange | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise _ArgumentError(f"{label} requires both start and end")
    return ByteRange(start, end)


def _failure(*, write: bool, stage: str) -> CurationFailure:
    return CurationFailure(
        CurationError(
            code=CurationErrorCode.INVALID_INPUT,
            retryable=False,
            details={"stage": stage},
        ),
        CurationCommitState.NOT_COMMITTED if write else None,
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _emit(stdout: object, value: object) -> int:
    stream = getattr(stdout, "buffer", stdout)
    data = _json_bytes(value)
    written = stream.write(data)
    if written is not None and written != len(data):
        raise OSError("short stdout write")
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()
    return 0 if isinstance(value, dict) and value.get("ok") is True else 2


def _cli_mapping(result: object) -> dict[str, object]:
    value = result.to_dict()
    if value.get("ok") is False:
        error = value.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        value["next_action"] = _NEXT_ACTIONS.get(
            code,
            "stop_and_inspect_the_failure_before_retry",
        )
    return value


def _write_output_new(path_value: str, body: bytes) -> None:
    path = Path(path_value)
    if not path.is_absolute():
        raise _ArgumentError("output path must be absolute")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise _ArgumentError("output parent must be a directory")
    selected = parent / path.name
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(selected, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            remaining = memoryview(body)
            while remaining:
                written = stream.write(remaining)
                if written is None or written <= 0:
                    raise OSError("short output write")
                remaining = remaining[written:]
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise _ArgumentError("output path already exists") from exc
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                selected.unlink()
            except OSError:
                pass
        raise


def _recognized_write(argv: Sequence[str]) -> bool:
    return "source" in argv and "prepare" in argv


def _run_cli(
    argv: Sequence[str],
    *,
    stdout: object,
    path_policy: PathPolicy,
) -> int:
    write = _recognized_write(argv)
    try:
        if not isinstance(path_policy, PathPolicy):
            raise _ArgumentError("invalid path policy")
        arguments = _parser().parse_args(list(argv))
        experiment_root = Path(arguments.experiment_root)
        if not experiment_root.is_absolute():
            raise _ArgumentError("experiment root must be absolute")

        if arguments.group == "source" and arguments.action == "prepare":
            authorized_range = _optional_range(
                arguments.authorized_start_byte,
                arguments.authorized_end_byte,
                "authorized range",
            )
            declared_scope = _optional_range(
                arguments.declared_start_byte,
                arguments.declared_end_byte,
                "declared scope",
            )
            result = prepare_source(
                SourcePrepareRequest(
                    request_id=arguments.request_id,
                    source_path=Path(arguments.source),
                    source_reference=arguments.source_reference,
                    expected_sha256=arguments.expected_sha256,
                    expected_byte_size=arguments.expected_bytes,
                    authorized_by=arguments.authorized_by,
                    task_ids=tuple(arguments.task_id),
                    authorized_range=authorized_range,
                    declared_scope=declared_scope,
                    budget_id=arguments.budget_id,
                ),
                experiment_root=experiment_root,
                path_policy=path_policy,
            )
            return _emit(stdout, _cli_mapping(result))

        if arguments.group == "source" and arguments.action == "inspect":
            result = inspect_source(
                SourceInspectRequest(request_id=arguments.request_id),
                experiment_root=experiment_root,
            )
            return _emit(stdout, _cli_mapping(result))

        if arguments.group == "evidence" and arguments.action == "show":
            body = io.BytesIO()
            result = show_evidence(
                EvidenceShowRequest(
                    request_id=arguments.request_id,
                    locator_id=arguments.locator_id,
                    body_sink=body,
                ),
                experiment_root=experiment_root,
                path_policy=path_policy,
            )
            if result.to_dict().get("ok") is True:
                _write_output_new(arguments.output, body.getvalue())
            return _emit(stdout, _cli_mapping(result))
        raise _ArgumentError("unsupported operation")
    except (_ArgumentError, TypeError, ValueError):
        return _emit(
            stdout,
            _cli_mapping(_failure(write=write, stage="cli-arguments")),
        )
    except OSError:
        result = CurationFailure(
            CurationError(
                code=CurationErrorCode.ATOMIC_PUBLISH_FAILED,
                retryable=True,
                details={"stage": "cli-output"},
            )
        )
        return _emit(stdout, _cli_mapping(result))


def main() -> int:
    """Run the installed CUR1B entry without requiring an account or network."""

    stdout = getattr(sys.stdout, "buffer", sys.stdout)
    try:
        return _run_cli(
            sys.argv[1:],
            stdout=stdout,
            path_policy=production_path_policy(),
        )
    except Exception:
        try:
            return _emit(
                stdout,
                _cli_mapping(CurationFailure(
                    CurationError(
                        code=CurationErrorCode.ATOMIC_PUBLISH_FAILED,
                        retryable=False,
                        details={"stage": "cli-internal"},
                    )
                )),
            )
        except Exception:
            return 3


__all__: tuple[str, ...] = ()
