from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from knowledgeflow_curation import (
    ByteRange,
    BudgetExhausted,
    DeepSeekChatProcessor,
    DeepSeekV41TokenizerCounter,
    DeterministicTestProcessor,
    HttpResponse,
    ProcessingBudgetLedger,
    ProcessingBudgetLimits,
    ProcessingStage,
    ProcessorCallError,
    ProcessorCandidateDraft,
    ProcessorRequest,
    ProcessorResponse,
    ProcessorSegment,
    StandardLibraryHttpTransport,
    Utf8ByteUpperBoundTokenCounter,
    execute_processor_request,
)
from knowledgeflow_curation.map_operations import _l1_requests, _target_summary_request
from knowledgeflow_curation.processing import (
    SHORT_READING_PROCESSOR_PROFILE,
    SHORT_READING_PROCESSOR_PROFILE_REVISION,
)


class _FakeTransport:
    def __init__(self, *responses: HttpResponse | ProcessorCallError) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs: object) -> HttpResponse:
        self.calls.append(dict(kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, ProcessorCallError):
            raise response
        return response


def _request(*, thinking: bool = False) -> ProcessorRequest:
    return ProcessorRequest(
        unit_id="l1-001",
        stage=ProcessingStage.L1_WINDOW,
        task="形成有证据约束的窗口候选。",
        segments=(
            ProcessorSegment(
                reference="s000001",
                ordinal=0,
                heading_path=("测试",),
                body="这是低敏感的合成测试正文。",
                locator_id="local-locator-001",
            ),
        ),
        thinking=thinking,
        reasoning_effort="low" if thinking else None,
        max_visible_tokens=128,
        max_reasoning_tokens=64 if thinking else 0,
        planned_input_tokens=64,
    )


def _target_request() -> ProcessorRequest:
    return ProcessorRequest(
        unit_id="target-summary-001",
        stage=ProcessingStage.TARGET_SUMMARY,
        task="Provide a bounded synopsis and target suggestion.",
        segments=(
            ProcessorSegment(
                reference="s000001",
                ordinal=0,
                heading_path=("测试",),
                body="这是低敏感的合成目标建议正文。",
                locator_id="local-target-locator-001",
            ),
        ),
        max_visible_tokens=128,
        planned_input_tokens=64,
    )


def _success_response(
    *,
    evidence_ref: str = "s000001",
    reasoning_tokens: int = 0,
    payload_override: dict[str, object] | None = None,
) -> HttpResponse:
    payload = {
        "schema": "knowledgeflow.processor-result",
        "schema_version": 1,
        "synopsis": None,
        "target_suggestion": None,
        "candidates": [
            {
                "kind": "claim",
                "summary": "该合成正文用于验证严格的处理器返回契约。",
                "evidence_refs": [evidence_ref],
                "provenance": "source-claim",
                "uncertainty": "low",
                "markdown_anchor": "strict-contract",
            }
        ],
        "focus_topics": [],
    }
    if payload_override is not None:
        payload = payload_override
    body = {
        "id": "chatcmpl-test",
        "model": "DeepSeek-V4.1-Flash-1017",
        "system_fingerprint": "fp-test",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            }
        ],
        "usage": {
            "prompt_tokens": 41,
            "completion_tokens": 19,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }
    return HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    )


class ProcessingTest(unittest.TestCase):
    def test_short_reading_profile_uses_one_bounded_json_response(self) -> None:
        request = replace(
            _request(thinking=True),
            unit_id="short-map-001",
            stage=ProcessingStage.GLOBAL_MAP,
            prompt_profile=SHORT_READING_PROCESSOR_PROFILE,
            prompt_profile_revision=SHORT_READING_PROCESSOR_PROFILE_REVISION,
        )
        transport = _FakeTransport(_success_response(reasoning_tokens=3))
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "synthetic-key"},
        )
        response = processor.process(request)
        self.assertEqual(len(response.candidates), 1)
        self.assertEqual(response.focus_topics, ())
        sent = json.loads(transport.calls[0]["body"])
        payload = json.loads(sent["messages"][1]["content"])
        self.assertEqual(payload["profile"], SHORT_READING_PROCESSOR_PROFILE)
        self.assertEqual(payload["output_contract"]["stage_rules"]["focus_topics"], "must be an empty array")
        self.assertNotIn(b"synthetic-key", transport.calls[0]["body"])

    def test_cur1d_01_deterministic_processor_is_offline_and_evidence_bound(self) -> None:
        processor = DeterministicTestProcessor()
        response = processor.process(_request())

        self.assertFalse(processor.profile.network_allowed)
        self.assertIsNone(processor.key_reference)
        self.assertEqual(response.candidates[0].evidence_refs, ("s000001",))

    def test_cur1d_02_deepseek_request_is_explicit_and_excludes_local_identity(self) -> None:
        transport = _FakeTransport(_success_response(reasoning_tokens=3))
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret-test-key"},
        )

        result = processor.process(_request(thinking=True))

        self.assertEqual(result.usage.visible_output_tokens, 16)
        self.assertEqual(result.usage.reasoning_tokens, 3)
        call = transport.calls[0]
        request_body = call["body"]
        assert isinstance(request_body, bytes)
        parsed = json.loads(request_body)
        self.assertEqual(parsed["model"], "deepseek-flash")
        self.assertEqual(parsed["thinking"], {"type": "enabled"})
        self.assertEqual(parsed["reasoning_effort"], "low")
        self.assertEqual(parsed["max_tokens"], 192)
        self.assertNotIn(b"secret-test-key", request_body)
        self.assertNotIn(b"local-locator-001", request_body)
        self.assertNotIn(b"capture_id", request_body)
        provider_payload = json.loads(parsed["messages"][1]["content"])
        contract = provider_payload["output_contract"]
        self.assertEqual(provider_payload["profile_revision"], 2)
        self.assertEqual(contract["format"], "json")
        self.assertFalse(contract["additional_fields_allowed"])
        self.assertTrue(contract["example_values_are_shape_only"])
        self.assertEqual(
            contract["exact_top_level_fields"],
            [
                "schema",
                "schema_version",
                "synopsis",
                "target_suggestion",
                "candidates",
                "focus_topics",
            ],
        )
        self.assertEqual(
            contract["example_json_object"]["candidates"][0]["evidence_refs"],
            ["s000001"],
        )
        target_body = json.loads(processor.request_bytes(_target_request()))
        target_payload = json.loads(target_body["messages"][1]["content"])
        target_contract = target_payload["output_contract"]
        self.assertEqual(
            target_contract["stage_rules"],
            {
                "synopsis": "required non-blank text",
                "target_suggestion": "required object",
                "candidates": "must be an empty array",
                "focus_topics": "must be an empty array",
            },
        )
        self.assertEqual(
            target_contract["example_json_object"]["target_suggestion"]["choice"],
            "new-kb",
        )
        target_transport = _FakeTransport(
            _success_response(
                payload_override=target_contract["example_json_object"],
            )
        )
        target_processor = DeepSeekChatProcessor(
            transport=target_transport,
            environment={"DEEPSEEK_API_KEY": "target-secret"},
        )
        target_result = target_processor.process(_target_request())
        self.assertEqual(target_result.target_choice, "new-kb")
        self.assertEqual(target_result.candidates, ())
        headers = call["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers["authorization"], "Bearer secret-test-key")

    def test_cur1d_03_non_thinking_is_sent_explicitly(self) -> None:
        transport = _FakeTransport(_success_response())
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )

        processor.process(_request())

        body = json.loads(transport.calls[0]["body"])
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", body)

    def test_cur1d_04_invalid_output_is_classified_without_persisting_content(self) -> None:
        transport = _FakeTransport(
            HttpResponse(status=200, headers={}, body=b"not-json"),
            _success_response(),
        )
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        ledger = ProcessingBudgetLedger()

        with self.assertRaises(ProcessorCallError) as raised:
            execute_processor_request(processor, _request(), ledger)

        self.assertTrue(raised.exception.unknown_usage)
        self.assertEqual(raised.exception.http_status, 200)
        diagnostic = raised.exception.diagnostic
        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertEqual(diagnostic.code, "outer-json-invalid")
        self.assertEqual(diagnostic.response_bytes, len(b"not-json"))
        self.assertIsNone(diagnostic.usage)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(ledger.http_attempts, 1)
        self.assertEqual(ledger.input_tokens, 64)
        self.assertEqual(ledger.visible_output_tokens, 128)

        marker = "untrusted-model-text-must-not-be-persisted"
        invalid_payload = {
            "schema": "knowledgeflow.processor-result",
            "schema_version": 1,
            "synopsis": marker,
        }
        observed_transport = _FakeTransport(
            _success_response(payload_override=invalid_payload),
        )
        observed_processor = DeepSeekChatProcessor(
            transport=observed_transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        observed_ledger = ProcessingBudgetLedger()

        with self.assertRaises(ProcessorCallError) as observed_raised:
            execute_processor_request(
                observed_processor,
                _request(),
                observed_ledger,
            )

        self.assertFalse(observed_raised.exception.unknown_usage)
        observed = observed_raised.exception.diagnostic
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.code, "payload-fields-invalid")
        self.assertIsNotNone(observed.usage)
        self.assertNotIn(marker, json.dumps(observed.as_mapping()))
        self.assertEqual(observed_ledger.input_tokens, 41)
        self.assertEqual(observed_ledger.visible_output_tokens, 19)
        self.assertEqual(observed_ledger.reasoning_tokens, 0)

    def test_cur1d_05_retryable_http_reuses_exact_request_bytes(self) -> None:
        transport = _FakeTransport(
            HttpResponse(status=429, headers={"retry-after": "1"}, body=b"{}"),
            _success_response(),
        )
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        ledger = ProcessingBudgetLedger()
        delays: list[float] = []

        executed = execute_processor_request(
            processor,
            _request(),
            ledger,
            sleeper=delays.append,
        )

        self.assertEqual([item.status for item in executed.attempts], ["unknown", "succeeded"])
        self.assertEqual(delays, [1.0])
        self.assertEqual(transport.calls[0]["body"], transport.calls[1]["body"])
        self.assertEqual(ledger.first_work_units, 1)
        self.assertEqual(ledger.http_attempts, 2)
        self.assertEqual(ledger.input_tokens, 105)
        self.assertEqual(ledger.visible_output_tokens, 147)

    def test_cur1d_06_nonretryable_http_stops_after_one_attempt(self) -> None:
        transport = _FakeTransport(
            HttpResponse(status=401, headers={}, body=b"{}"),
            _success_response(),
        )
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )

        ledger = ProcessingBudgetLedger()
        with self.assertRaises(ProcessorCallError) as raised:
            execute_processor_request(processor, _request(), ledger)

        self.assertFalse(raised.exception.retryable)
        self.assertTrue(raised.exception.unknown_usage)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(ledger.input_tokens, 64)
        self.assertEqual(ledger.visible_output_tokens, 128)

    def test_cur1d_07_budget_stops_before_transport(self) -> None:
        transport = _FakeTransport(_success_response())
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        limits = ProcessingBudgetLimits(
            max_first_work_units=1,
            max_http_attempts=1,
            max_input_tokens=63,
            max_visible_output_tokens=128,
            max_reasoning_tokens=1,
            max_cost_microusd=2_000_000,
            input_microusd_per_million=300_000,
            output_microusd_per_million=1_200_000,
        )

        with self.assertRaises(BudgetExhausted):
            execute_processor_request(
                processor,
                _request(),
                ProcessingBudgetLedger(limits),
            )

        self.assertEqual(transport.calls, [])

    def test_cur1d_08_stage_and_evidence_contracts_are_rejected_locally(self) -> None:
        request = _request()
        response = ProcessorResponse(
            candidates=(
                ProcessorCandidateDraft(
                    kind="claim",
                    summary="越权候选。",
                    evidence_refs=("s999999",),
                    provenance="source-claim",
                    uncertainty="low",
                    markdown_anchor="unauthorized-evidence",
                ),
            ),
            usage=DeterministicTestProcessor().process(request).usage,
        )

        with self.assertRaisesRegex(ValueError, "unauthorized evidence"):
            response.validate_against(request)

        target = _target_request()
        target_response = ProcessorResponse(
            candidates=(
                ProcessorCandidateDraft(
                    kind="claim",
                    summary="目标建议阶段不应夹带地图候选。",
                    evidence_refs=("s000001",),
                    provenance="source-claim",
                    uncertainty="low",
                    markdown_anchor="target-map-field",
                ),
            ),
            synopsis="合成梗概。",
            target_choice="new-kb",
            target_rationale="合成理由。",
            usage=DeterministicTestProcessor().process(target).usage,
        )
        with self.assertRaisesRegex(ValueError, "map-only fields"):
            target_response.validate_against(target)

    def test_cur1d_09_clear_presend_failure_may_retry(self) -> None:
        transport = _FakeTransport(
            ProcessorCallError(
                "connect failed",
                retryable=True,
                request_sent=False,
                unknown_usage=False,
            ),
            _success_response(),
        )
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )

        executed = execute_processor_request(
            processor,
            _request(),
            ProcessingBudgetLedger(),
            sleeper=lambda _seconds: None,
        )

        self.assertEqual([item.status for item in executed.attempts], ["failed", "succeeded"])
        self.assertEqual(len(transport.calls), 2)

    def test_cur1d_10_postsend_timeout_is_unknown_and_never_retried(self) -> None:
        transport = _FakeTransport(
            ProcessorCallError(
                "read timed out",
                retryable=False,
                request_sent=True,
                unknown_usage=True,
            ),
            _success_response(),
        )
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        ledger = ProcessingBudgetLedger()

        with self.assertRaises(ProcessorCallError):
            execute_processor_request(processor, _request(), ledger)

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(ledger.http_attempts, 1)
        self.assertEqual(ledger.input_tokens, 64)

    def test_cur1d_11_source_claim_without_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires evidence"):
            ProcessorCandidateDraft(
                kind="claim",
                summary="没有证据的来源主张。",
                evidence_refs=(),
                provenance="source-claim",
                uncertainty="unknown",
                markdown_anchor="unsupported-claim",
            )

    def test_cur1d_12_actual_reasoning_cannot_exceed_request_limit(self) -> None:
        transport = _FakeTransport(_success_response(reasoning_tokens=3))
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )

        with self.assertRaisesRegex(BudgetExhausted, "reasoning output"):
            execute_processor_request(processor, _request(), ProcessingBudgetLedger())

    def test_cur1d_13_transport_total_deadline_precedes_another_blocking_read(self) -> None:
        class _Socket:
            def __init__(self) -> None:
                self.timeouts: list[float] = []

            def settimeout(self, value: float) -> None:
                self.timeouts.append(value)

        class _Response:
            status = 200

            @staticmethod
            def getheaders() -> list[tuple[str, str]]:
                return []

            @staticmethod
            def read(_size: int) -> bytes:
                raise AssertionError("deadline must be checked before another read")

        class _Connection:
            instance: "_Connection | None" = None

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.sock = _Socket()
                self.closed = False
                _Connection.instance = self

            def connect(self) -> None:
                return None

            def request(self, *_args: object, **_kwargs: object) -> None:
                return None

            def getresponse(self) -> _Response:
                return _Response()

            def close(self) -> None:
                self.closed = True

        with (
            mock.patch(
                "knowledgeflow_curation.processing.http.client.HTTPSConnection",
                _Connection,
            ),
            mock.patch(
                "knowledgeflow_curation.processing.time.monotonic",
                side_effect=(0.0, 0.0, 0.0, 901.0),
            ),
        ):
            with self.assertRaises(ProcessorCallError) as raised:
                StandardLibraryHttpTransport().post(
                    url="https://api.deepseek.com/chat/completions",
                    headers={"content-type": "application/json"},
                    body=b"{}",
                    connect_timeout_seconds=15,
                    first_data_timeout_seconds=300,
                    total_timeout_seconds=900,
                )

        self.assertTrue(raised.exception.request_sent)
        self.assertTrue(raised.exception.unknown_usage)
        assert _Connection.instance is not None
        self.assertTrue(_Connection.instance.closed)
        self.assertEqual(_Connection.instance.sock.timeouts, [15, 300])

    def test_cur1d_14_global_retry_budget_is_independent_of_unused_work_units(self) -> None:
        responses: list[HttpResponse | ProcessorCallError] = []
        for _index in range(6):
            responses.extend(
                (
                    HttpResponse(status=429, headers={}, body=b"{}"),
                    HttpResponse(status=503, headers={}, body=b"{}"),
                    _success_response(),
                )
            )
        responses.append(HttpResponse(status=429, headers={}, body=b"{}"))
        transport = _FakeTransport(*responses)
        processor = DeepSeekChatProcessor(
            transport=transport,
            environment={"DEEPSEEK_API_KEY": "secret"},
        )
        ledger = ProcessingBudgetLedger()

        for _index in range(6):
            execute_processor_request(
                processor,
                _request(),
                ledger,
                sleeper=lambda _seconds: None,
            )

        with self.assertRaisesRegex(BudgetExhausted, "approved budget"):
            execute_processor_request(
                processor,
                _request(),
                ledger,
                sleeper=lambda _seconds: None,
            )

        self.assertEqual(ledger.first_work_units, 7)
        self.assertEqual(ledger.http_attempts, 19)
        self.assertEqual(ledger.http_attempts - ledger.first_work_units, 12)
        self.assertEqual(len(transport.calls), 19)

    def test_cur1d_r1b_01_official_tokenizer_binds_asset_runtime_model_and_request(self) -> None:
        observed: dict[str, object] = {}

        class _Tokenizer:
            @staticmethod
            def from_str(value: str) -> object:
                observed["asset"] = value
                return object()

        class _Encoding:
            def with_tokenizer(self, tokenizer: object) -> "_Encoding":
                observed["tokenizer"] = tokenizer
                return self

            def encode(self, conversation: object) -> list[int]:
                observed["conversation"] = conversation
                return list(range(17))

        class _Options:
            def with_model_alias(
                self,
                model_id: str,
                model_version: object,
            ) -> "_Options":
                observed["model_alias"] = (model_id, model_version)
                return self

        class _ChatRequest:
            def __init__(self, body: object) -> None:
                observed["request_body"] = body
                self.body = body

            def convert(self, options: object) -> object:
                observed["options"] = options
                return SimpleNamespace(conversation=self.body)

        model_version = object()
        recipe = SimpleNamespace(
            __version__="0.2.0",
            Tokenizer=_Tokenizer,
            DeepseekV41Encoding=_Encoding,
            ChatCompletionRequest=_ChatRequest,
            ConversionOptions=_Options,
            ModelVersion=SimpleNamespace(DeepseekV41Flash=model_version),
        )
        body = b'{"synthetic":"tokenizer"}'
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary).resolve() / "tokenizer.json"
            asset.write_bytes(body)
            counter = DeepSeekV41TokenizerCounter(
                asset_path=asset,
                expected_sha256=digest,
                recipe_module=recipe,
            )

            count = counter.count_request(_request(thinking=True))

        self.assertEqual(count, 17)
        self.assertEqual(observed["asset"], body.decode("utf-8"))
        self.assertEqual(observed["model_alias"], ("deepseek-flash", model_version))
        request_body = observed["request_body"]
        assert isinstance(request_body, dict)
        self.assertEqual(request_body["model"], "deepseek-flash")
        self.assertEqual(request_body["thinking"], {"type": "enabled"})
        self.assertEqual(request_body["reasoning_effort"], "low")
        self.assertEqual(request_body["max_tokens"], 192)
        reference_processor = DeepSeekChatProcessor(
            transport=_FakeTransport(),
            environment={"DEEPSEEK_API_KEY": "unused-test-key"},
        )
        self.assertEqual(
            Utf8ByteUpperBoundTokenCounter(
                model_id="deepseek-flash"
            ).count_request(_request(thinking=True)),
            len(reference_processor.request_bytes(_request(thinking=True))),
        )
        self.assertEqual(
            counter.profile_mapping(),
            {
                "profile_id": "deepseek-v41-official-tokenizer",
                "revision": 1,
                "mode": "model-prompt-estimate",
                "model_id": "deepseek-flash",
                "implementation": "deepseek-recipe",
                "implementation_version": "0.2.0",
                "asset_source": (
                    "deepseek-ai/deepseek-recipe@0.2.0:"
                    "static/tokenizers/v41/tokenizer.json"
                ),
                "asset_sha256": digest,
            },
        )

    def test_cur1d_r1b_02_official_tokenizer_rejects_unverified_inputs(self) -> None:
        recipe = SimpleNamespace(__version__="0.2.0")
        body = b"{}"
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary).resolve() / "tokenizer.json"
            asset.write_bytes(body)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                DeepSeekV41TokenizerCounter(
                    asset_path=asset,
                    expected_sha256="sha256:" + "0" * 64,
                    recipe_module=recipe,
                )

            incompatible = SimpleNamespace(__version__="0.3.0")
            digest = "sha256:" + hashlib.sha256(body).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "version"):
                DeepSeekV41TokenizerCounter(
                    asset_path=asset,
                    expected_sha256=digest,
                    recipe_module=incompatible,
                )

    def test_cur1d_r1b_03_l1_windows_preserve_top_level_heading_trees(self) -> None:
        segments = tuple(
            ProcessorSegment(
                reference=f"s{index:06d}",
                ordinal=index - 1,
                heading_path=heading_path,
                body=f"合成正文 {index}",
                locator_id=f"locator-{index:03d}",
            )
            for index, heading_path in enumerate(
                (("A",), ("A", "A1"), ("B",), ("B", "B1")),
                1,
            )
        )

        windows = _l1_requests(segments, Utf8ByteUpperBoundTokenCounter())

        self.assertEqual(
            [[item.reference for item in unit.segments] for unit in windows],
            [["s000001", "s000002"], ["s000003", "s000004"]],
        )
        self.assertTrue(all(unit.planned_input_tokens <= 32_768 for unit in windows))

    def test_cur1d_r1b_04_l1_windows_split_at_target_and_reject_oversize_segment(self) -> None:
        counter = Utf8ByteUpperBoundTokenCounter()
        segments = tuple(
            ProcessorSegment(
                reference=f"s{index:06d}",
                ordinal=index - 1,
                heading_path=("A",),
                body=character * 13_000,
                locator_id=f"locator-{index:03d}",
            )
            for index, character in enumerate(("a", "b", "c"), 1)
        )

        windows = _l1_requests(segments, counter)

        self.assertEqual(len(windows), 3)
        self.assertTrue(all(unit.planned_input_tokens <= 32_768 for unit in windows))
        oversized = ProcessorSegment(
            reference="s999999",
            ordinal=999_998,
            heading_path=("A",),
            body="z" * 33_000,
            locator_id="locator-oversized",
        )
        with self.assertRaisesRegex(BudgetExhausted, "one Segment"):
            _l1_requests((oversized,), counter)

    def test_cur1d_r2_01_target_summary_keeps_beginning_middle_end_anchors(self) -> None:
        segments = tuple(
            ProcessorSegment(
                reference=f"s{index + 1:06d}",
                ordinal=index,
                heading_path=(f"Part {index + 1}",),
                body=chr(ord("a") + index) * 20_000,
                locator_id=f"locator-{index + 1:03d}",
                byte_range=ByteRange(index * 20_000, (index + 1) * 20_000),
            )
            for index in range(5)
        )

        request = _target_summary_request(
            segments,
            Utf8ByteUpperBoundTokenCounter(model_id="deepseek-flash"),
        )

        self.assertEqual(
            [item.reference for item in request.segments],
            ["s000001", "s000003", "s000005"],
        )
        self.assertLessEqual(request.planned_input_tokens, 16_384)
        self.assertTrue(all(len(item.body.encode("utf-8")) <= 2_048 for item in request.segments))
        self.assertEqual(request.segments[0].byte_range, ByteRange(0, 2_048))
        assert request.segments[1].byte_range is not None
        self.assertGreater(request.segments[1].byte_range.start_byte, 40_000)
        self.assertLess(request.segments[1].byte_range.end_byte, 60_000)
        self.assertEqual(request.segments[2].byte_range, ByteRange(97_952, 100_000))

        two_segment_request = _target_summary_request(
            segments[:2],
            Utf8ByteUpperBoundTokenCounter(model_id="deepseek-flash"),
        )
        self.assertEqual(
            [item.reference for item in two_segment_request.segments],
            ["s000001", "s000002"],
        )
        self.assertEqual(
            two_segment_request.segments[0].byte_range,
            ByteRange(0, 2_048),
        )
        self.assertEqual(
            two_segment_request.segments[1].byte_range,
            ByteRange(37_952, 40_000),
        )

    def test_cur1d_r2_02_one_large_segment_is_sampled_without_claiming_full_body(self) -> None:
        segment = ProcessorSegment(
            reference="s000001",
            ordinal=0,
            heading_path=("Long source",),
            body="文" * 8_000,
            locator_id="locator-001",
            byte_range=ByteRange(0, 24_000),
        )

        request = _target_summary_request(
            (segment,),
            Utf8ByteUpperBoundTokenCounter(model_id="deepseek-flash"),
        )

        self.assertEqual(len(request.segments), 1)
        self.assertLess(len(request.segments[0].body.encode("utf-8")), 24_000)
        self.assertLessEqual(request.planned_input_tokens, 16_384)


if __name__ == "__main__":
    unittest.main()
