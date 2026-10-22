"""Restricted CUR1 command-line entry with one UTF-8 JSON receipt."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence

from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.runtime import production_path_policy

from .contracts import ByteRange, CandidateDecision
from .errors import CurationCommitState, CurationError, CurationErrorCode, CurationFailure
from .operations import (
    EvidenceShowRequest,
    SourceInspectRequest,
    SourcePrepareRequest,
    inspect_source,
    prepare_source,
    show_evidence,
)
from .map_operations import (
    MapBuildRequest,
    MapDecideRequest,
    TargetSuggestRequest,
    build_map,
    close_map,
    decide_map,
    suggest_target,
)
from .processing import (
    DEEPSEEK_DEFAULT_KEY_REFERENCE,
    DEEPSEEK_DEFAULT_MODEL,
    DEEPSEEK_PROVIDER_PROFILE,
    DeepSeekV41TokenizerCounter,
    DeepSeekChatProcessor,
    DeterministicTestProcessor,
    RemoteProcessingAuthorization,
    StandardLibraryHttpTransport,
    Utf8ByteUpperBoundTokenCounter,
)
from .targeting import (
    KnowledgeBaseRootPolicy,
    TargetDecideRequest,
    target_decide,
)


_NEXT_ACTIONS = {
    "invalid_input": "correct_arguments_and_retry",
    "source_not_found": "verify_source_path_or_request_id_and_retry",
    "source_identity_mismatch": "verify_expected_source_identity_before_retry",
    "source_integrity_failed": "stop_and_restore_the_exact_source_or_capture",
    "authorization_required": "record_exact_processing_authorization_before_retry",
    "authorization_scope_mismatch": "correct_authorized_utf8_byte_range_and_retry",
    "unsupported_source": "provide_nonempty_strict_utf8_text_and_retry",
    "locator_invalid": "run_source_inspect_and_select_a_returned_locator",
    "evidence_integrity_failed": "stop_and_restore_verified_source_state",
    "idempotency_conflict": "use_the_original_request_or_a_new_request_id",
    "atomic_publish_failed": "verify_local_storage_then_retry_once",
    "recovery_required": "stop_and_inspect_the_request_bundle_before_retry",
    "target_not_confirmed": "confirm_new_kb_or_no_target_before_retry",
    "target_conflict": "stop_and_inspect_the_target_kb_before_retry",
    "version_control_unavailable": "install_or_restore_local_git_then_retry",
    "processor_output_invalid": "inspect_processor_result_and_do_not_publish",
    "budget_exhausted": "stop_and_review_processing_scope_and_budget",
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

    target = groups.add_parser("target", add_help=False)
    target_commands = target.add_subparsers(dest="action", required=True)
    suggest = target_commands.add_parser("suggest", add_help=False)
    suggest.add_argument("--request-id", required=True)
    suggest.add_argument("--source-request-id", required=True)
    suggest.add_argument("--suggested-by", required=True)
    _add_processor_arguments(suggest)

    decide = target_commands.add_parser("decide", add_help=False)
    decide.add_argument("--decision-request-id", required=True)
    decide.add_argument("--source-request-id", required=True)
    decide.add_argument("--choice", required=True, choices=("new-kb", "no-target"))
    decide.add_argument("--decided-by", required=True)
    decide.add_argument("--kb-parent")
    decide.add_argument("--storage-name")
    decide.add_argument("--display-name")
    decide.add_argument(
        "--authorization-source",
        default="manual-review",
        choices=("explicit-at-capture", "manual-review", "approved-proposal"),
    )
    decide.add_argument("--suggestion-choice", choices=("new-kb", "no-target"))
    decide.add_argument("--suggestion-rationale")
    decide.add_argument("--suggested-by")
    decide.add_argument("--naming-timezone", default="+08:00")

    map_group = groups.add_parser("map", add_help=False)
    map_commands = map_group.add_subparsers(dest="action", required=True)
    build = map_commands.add_parser("build", add_help=False)
    build.add_argument("--request-id", required=True)
    build.add_argument("--source-request-id", required=True)
    build.add_argument("--target-decision-request-id", required=True)
    build.add_argument("--target-suggestion-request-id")
    build.add_argument("--kb-parent")
    _add_processor_arguments(build)

    for action in ("decide", "close"):
        command = map_commands.add_parser(action, add_help=False)
        command.add_argument("--request-id", required=True)
        command.add_argument("--source-request-id", required=True)
        command.add_argument("--target-decision-request-id", required=True)
        command.add_argument("--map-id", required=True)
        command.add_argument("--map-version", required=True, type=int)
        command.add_argument("--decided-by", required=True)
        command.add_argument("--decisions-file", required=True)
        command.add_argument("--kb-parent")
        if action == "decide":
            command.add_argument(
                "--outcome",
                required=True,
                choices=("revision-requested", "change-requested", "deferred"),
            )
    return parser


def _add_processor_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--processor",
        required=True,
        choices=("deterministic-test", "deepseek"),
    )
    parser.add_argument("--model-id", default=DEEPSEEK_DEFAULT_MODEL)
    parser.add_argument("--key-reference", default=DEEPSEEK_DEFAULT_KEY_REFERENCE)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--remote-authorization-id")
    parser.add_argument("--remote-authorized-by")
    parser.add_argument("--remote-authorized-at")
    parser.add_argument("--remote-payload-sha256")
    parser.add_argument("--remote-start-byte", type=int)
    parser.add_argument("--remote-end-byte", type=int)
    parser.add_argument(
        "--tokenizer-profile",
        choices=("deepseek-v41-official", "conservative-utf8"),
    )
    parser.add_argument("--tokenizer-asset")
    parser.add_argument("--tokenizer-asset-sha256")


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


def _processor(arguments: argparse.Namespace):
    if arguments.processor == "deterministic-test":
        if arguments.allow_network:
            raise _ArgumentError("deterministic-test does not accept --allow-network")
        return DeterministicTestProcessor()
    if not arguments.allow_network:
        raise _ArgumentError("deepseek requires explicit --allow-network")
    return DeepSeekChatProcessor(
        transport=StandardLibraryHttpTransport(),
        model_id=arguments.model_id,
        key_reference=arguments.key_reference,
    )


def _token_counter(arguments: argparse.Namespace):
    tokenizer_values = (
        arguments.tokenizer_profile,
        arguments.tokenizer_asset,
        arguments.tokenizer_asset_sha256,
    )
    if arguments.processor == "deterministic-test":
        if any(value is not None for value in tokenizer_values):
            raise _ArgumentError(
                "deterministic-test does not accept tokenizer arguments"
            )
        return Utf8ByteUpperBoundTokenCounter()
    if arguments.tokenizer_profile is None:
        raise _ArgumentError(
            "deepseek requires an explicit --tokenizer-profile"
        )
    if arguments.tokenizer_profile == "conservative-utf8":
        if (
            arguments.tokenizer_asset is not None
            or arguments.tokenizer_asset_sha256 is not None
        ):
            raise _ArgumentError(
                "conservative-utf8 does not accept tokenizer asset arguments"
            )
        return Utf8ByteUpperBoundTokenCounter(model_id=arguments.model_id)
    if (
        arguments.tokenizer_asset is None
        or arguments.tokenizer_asset_sha256 is None
    ):
        raise _ArgumentError(
            "deepseek-v41-official requires an asset path and SHA-256"
        )
    asset_path = Path(arguments.tokenizer_asset)
    if not asset_path.is_absolute():
        raise _ArgumentError("tokenizer asset path must be absolute")
    try:
        return DeepSeekV41TokenizerCounter(
            asset_path=asset_path,
            expected_sha256=arguments.tokenizer_asset_sha256,
            model_id=arguments.model_id,
        )
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
        raise _ArgumentError(
            "verified official tokenizer is unavailable or invalid"
        ) from exc


def _remote_authorization(
    arguments: argparse.Namespace,
) -> RemoteProcessingAuthorization | None:
    values = (
        arguments.remote_authorization_id,
        arguments.remote_authorized_by,
        arguments.remote_authorized_at,
        arguments.remote_payload_sha256,
        arguments.remote_start_byte,
        arguments.remote_end_byte,
    )
    if arguments.processor == "deterministic-test":
        if any(value is not None for value in values):
            raise _ArgumentError(
                "deterministic-test does not accept remote authorization fields"
            )
        return None
    if not all(value is not None for value in values):
        raise _ArgumentError(
            "deepseek requires one exact remote-processing authorization package"
        )
    return RemoteProcessingAuthorization(
        authorization_id=arguments.remote_authorization_id,
        source_request_id=arguments.source_request_id,
        payload_sha256=arguments.remote_payload_sha256,
        allowed_range=ByteRange(
            arguments.remote_start_byte,
            arguments.remote_end_byte,
        ),
        provider_profile=DEEPSEEK_PROVIDER_PROFILE,
        model_id=arguments.model_id,
        authorized_by=arguments.remote_authorized_by,
        authorized_at=arguments.remote_authorized_at,
    )


def _optional_absolute_path(value: str | None, label: str) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise _ArgumentError(f"{label} must be absolute")
    return path


def _load_candidate_decisions(path_value: str) -> tuple[CandidateDecision, ...]:
    path = Path(path_value)
    if not path.is_absolute():
        raise _ArgumentError("decisions file path must be absolute")
    try:
        status = path.lstat()
        if not stat.S_ISREG(status.st_mode) or path.is_symlink():
            raise _ArgumentError("decisions file must be a plain file")
        if status.st_size > 1024 * 1024:
            raise _ArgumentError("decisions file exceeds one MiB")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _ArgumentError("decisions file is not valid UTF-8 JSON") from exc
    if not isinstance(value, list) or not value:
        raise _ArgumentError("decisions file must contain a non-empty JSON array")
    try:
        return tuple(CandidateDecision.from_mapping(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise _ArgumentError("decisions file does not match the v1 contract") from exc


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
    return ("source" in argv and "prepare" in argv) or (
        "target" in argv and any(action in argv for action in ("suggest", "decide"))
    ) or ("map" in argv and any(action in argv for action in ("build", "decide", "close")))


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

        if arguments.group == "target" and arguments.action == "suggest":
            processor = _processor(arguments)
            result = suggest_target(
                TargetSuggestRequest(
                    request_id=arguments.request_id,
                    source_request_id=arguments.source_request_id,
                    suggested_by=arguments.suggested_by,
                ),
                experiment_root=experiment_root,
                path_policy=path_policy,
                processor=processor,
                remote_authorization=_remote_authorization(arguments),
                token_counter=_token_counter(arguments),
            )
            return _emit(stdout, _cli_mapping(result))

        if arguments.group == "target" and arguments.action == "decide":
            root_policy = None
            selected_parent = None
            if arguments.choice == "new-kb":
                if arguments.kb_parent is None:
                    raise _ArgumentError("new-kb requires --kb-parent")
                selected_parent = Path(arguments.kb_parent)
                if not selected_parent.is_absolute():
                    raise _ArgumentError("KB parent must be absolute")
                authorized_parent = experiment_root / "kb-root"
                if (
                    selected_parent.resolve(strict=True)
                    != authorized_parent.resolve(strict=True)
                ):
                    raise _ArgumentError(
                        "experimental KB parent must be <experiment-root>/kb-root"
                    )
                root_policy = KnowledgeBaseRootPolicy(
                    policy_id="cur1-experiment-kb-root",
                    revision=1,
                    allowed_parents=(authorized_parent,),
                )
            elif arguments.kb_parent is not None:
                raise _ArgumentError("no-target does not accept --kb-parent")
            result = target_decide(
                TargetDecideRequest(
                    decision_request_id=arguments.decision_request_id,
                    source_request_id=arguments.source_request_id,
                    choice=arguments.choice,
                    decided_by=arguments.decided_by,
                    kb_parent=selected_parent,
                    storage_name=arguments.storage_name,
                    display_name=arguments.display_name,
                    authorization_source=arguments.authorization_source,
                    suggestion_choice=arguments.suggestion_choice,
                    suggestion_rationale=arguments.suggestion_rationale,
                    suggested_by=arguments.suggested_by,
                    naming_timezone=arguments.naming_timezone,
                ),
                experiment_root=experiment_root,
                path_policy=path_policy,
                root_policy=root_policy,
            )
            return _emit(stdout, _cli_mapping(result))

        if arguments.group == "map" and arguments.action == "build":
            processor = _processor(arguments)
            result = build_map(
                MapBuildRequest(
                    request_id=arguments.request_id,
                    source_request_id=arguments.source_request_id,
                    target_decision_request_id=arguments.target_decision_request_id,
                    kb_parent=_optional_absolute_path(arguments.kb_parent, "KB parent"),
                    target_suggestion_request_id=(
                        arguments.target_suggestion_request_id
                    ),
                ),
                experiment_root=experiment_root,
                path_policy=path_policy,
                processor=processor,
                remote_authorization=_remote_authorization(arguments),
                token_counter=_token_counter(arguments),
            )
            return _emit(stdout, _cli_mapping(result))

        if arguments.group == "map" and arguments.action in {"decide", "close"}:
            outcome = (
                "map-closed" if arguments.action == "close" else arguments.outcome
            )
            request = MapDecideRequest(
                request_id=arguments.request_id,
                source_request_id=arguments.source_request_id,
                target_decision_request_id=arguments.target_decision_request_id,
                map_id=arguments.map_id,
                map_version=arguments.map_version,
                outcome=outcome,
                decided_by=arguments.decided_by,
                decisions=_load_candidate_decisions(arguments.decisions_file),
                kb_parent=_optional_absolute_path(arguments.kb_parent, "KB parent"),
            )
            operation = close_map if arguments.action == "close" else decide_map
            result = operation(request, experiment_root=experiment_root)
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
    """Run the installed CUR1 entry without requiring an account or network."""

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
