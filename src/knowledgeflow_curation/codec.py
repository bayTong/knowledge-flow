"""Safe canonical codecs for the bounded CUR-MVP-1 contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json

from knowledgeflow_capture.codec import (
    NonCanonicalYamlError,
    SchemaValidationError,
    ValueSchema,
    YamlSyntaxGateError,
    dump_restricted_yaml,
    load_restricted_yaml,
)

from .contracts import (
    CurationEvidenceRecord,
    CurationMap,
    CurationRunManifest,
    KnowledgeBaseManifest,
    MapDecision,
    RawSourceMapping,
    RouteRecord,
    SHORT_READING_PROFILE,
    SourceFileMapping,
    TargetDecisionRecord,
)


CURATION_MAP_HASH_DOMAIN = b"knowledgeflow.curation-map.v1\n"


@dataclass(frozen=True, slots=True)
class _ContractSchema(ValueSchema):
    loader: Callable[[object], object]
    label: str

    def normalize(self, value: object, path: str) -> object:
        try:
            contract = self.loader(value)
            mapping = contract.as_mapping()
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"{path} does not satisfy the {self.label} contract"
            ) from exc
        if not isinstance(mapping, Mapping):
            raise SchemaValidationError(
                f"{path} {self.label} normalization did not produce a mapping"
            )
        return mapping


_RUN_SCHEMA = _ContractSchema(
    CurationRunManifest.from_mapping,
    "CUR1 run manifest",
)
_EVIDENCE_SCHEMA = _ContractSchema(
    CurationEvidenceRecord.from_mapping,
    "CUR1 experimental evidence record",
)
_MAP_SCHEMA = _ContractSchema(
    CurationMap.from_mapping,
    "curation map v1",
)
_DECISION_SCHEMA = _ContractSchema(
    MapDecision.from_mapping,
    "curation map decision v1",
)
_KB_MANIFEST_SCHEMA = _ContractSchema(
    KnowledgeBaseManifest.from_mapping,
    "provisional KB manifest v1",
)
_SOURCE_MAPPING_SCHEMA = _ContractSchema(
    SourceFileMapping.from_mapping,
    "CUR1 source mapping v1",
)
_RAW_SOURCE_MAPPING_SCHEMA = _ContractSchema(
    RawSourceMapping.from_mapping,
    "raw source mapping v1",
)
_ROUTE_RECORD_SCHEMA = _ContractSchema(
    RouteRecord.from_mapping,
    "route record v1",
)
_TARGET_DECISION_RECORD_SCHEMA = _ContractSchema(
    TargetDecisionRecord.from_mapping,
    "target decision record v1",
)


def _dump_contract(value: object, expected_type: type, schema: ValueSchema) -> bytes:
    if not isinstance(value, expected_type):
        raise TypeError(f"value must be {expected_type.__name__}")
    return dump_restricted_yaml(value.as_mapping(), schema)


def _load_contract(
    source: str | bytes | bytearray | memoryview,
    schema: ValueSchema,
    loader: Callable[[object], object],
) -> object:
    normalized = load_restricted_yaml(
        source,
        schema,
        require_canonical=True,
    )
    return loader(normalized)


def dump_curation_run(value: CurationRunManifest) -> bytes:
    return _dump_contract(value, CurationRunManifest, _RUN_SCHEMA)


def load_curation_run(
    source: str | bytes | bytearray | memoryview,
) -> CurationRunManifest:
    return _load_contract(source, _RUN_SCHEMA, CurationRunManifest.from_mapping)


def dump_source_mapping(value: SourceFileMapping) -> bytes:
    return _dump_contract(value, SourceFileMapping, _SOURCE_MAPPING_SCHEMA)


def load_source_mapping(
    source: str | bytes | bytearray | memoryview,
) -> SourceFileMapping:
    return _load_contract(
        source,
        _SOURCE_MAPPING_SCHEMA,
        SourceFileMapping.from_mapping,
    )


def dump_raw_source_mapping(value: RawSourceMapping) -> bytes:
    return _dump_contract(
        value,
        RawSourceMapping,
        _RAW_SOURCE_MAPPING_SCHEMA,
    )


def load_raw_source_mapping(
    source: str | bytes | bytearray | memoryview,
) -> RawSourceMapping:
    return _load_contract(
        source,
        _RAW_SOURCE_MAPPING_SCHEMA,
        RawSourceMapping.from_mapping,
    )


def dump_route_record(value: RouteRecord) -> bytes:
    return _dump_contract(value, RouteRecord, _ROUTE_RECORD_SCHEMA)


def load_route_record(
    source: str | bytes | bytearray | memoryview,
) -> RouteRecord:
    return _load_contract(source, _ROUTE_RECORD_SCHEMA, RouteRecord.from_mapping)


def dump_target_decision_record(value: TargetDecisionRecord) -> bytes:
    return _dump_contract(
        value,
        TargetDecisionRecord,
        _TARGET_DECISION_RECORD_SCHEMA,
    )


def load_target_decision_record(
    source: str | bytes | bytearray | memoryview,
) -> TargetDecisionRecord:
    return _load_contract(
        source,
        _TARGET_DECISION_RECORD_SCHEMA,
        TargetDecisionRecord.from_mapping,
    )


def dump_curation_evidence(value: CurationEvidenceRecord) -> bytes:
    return _dump_contract(value, CurationEvidenceRecord, _EVIDENCE_SCHEMA)


def load_curation_evidence(
    source: str | bytes | bytearray | memoryview,
) -> CurationEvidenceRecord:
    return _load_contract(
        source,
        _EVIDENCE_SCHEMA,
        CurationEvidenceRecord.from_mapping,
    )


def dump_curation_map(value: CurationMap) -> bytes:
    return _dump_contract(value, CurationMap, _MAP_SCHEMA)


def load_curation_map(
    source: str | bytes | bytearray | memoryview,
) -> CurationMap:
    return _load_contract(source, _MAP_SCHEMA, CurationMap.from_mapping)


def dump_map_decision(value: MapDecision) -> bytes:
    return _dump_contract(value, MapDecision, _DECISION_SCHEMA)


def load_map_decision(
    source: str | bytes | bytearray | memoryview,
) -> MapDecision:
    return _load_contract(source, _DECISION_SCHEMA, MapDecision.from_mapping)


def dump_kb_manifest(value: KnowledgeBaseManifest) -> bytes:
    return _dump_contract(value, KnowledgeBaseManifest, _KB_MANIFEST_SCHEMA)


def load_kb_manifest(
    source: str | bytes | bytearray | memoryview,
) -> KnowledgeBaseManifest:
    return _load_contract(
        source,
        _KB_MANIFEST_SCHEMA,
        KnowledgeBaseManifest.from_mapping,
    )


def _quoted_markdown(value: str) -> list[str]:
    return ["> " + line if line else ">" for line in value.split("\n")]


_SHORT_READING_SECTIONS = (
    ("1. 全景概括", ("overview",)),
    ("2. 本次提取层次", ("structure",)),
    ("3. 核心概念与实体", ("concept",)),
    ("4. 关系清单", ("relationship",)),
    ("5. 原文主张与叙述", ("claim",)),
    ("6. 不确定标记", ("dispute", "limitation")),
    ("7. 缺口分析", ("gap",)),
    ("8. SCHEMA／组织建议", ("organization",)),
)
_READING_PROVENANCE = {
    "source-claim": "原文表达",
    "quoted-claim": "原文直接引述",
    "processor-inference": "处理器归纳",
    "user-revision": "用户修订",
    "unverified": "尚未核实",
}
_READING_UNCERTAINTY = {
    "none": "未标记",
    "low": "低",
    "medium": "中",
    "high": "高",
    "unknown": "未知",
}


def _render_short_reading_map(value: CurationMap) -> bytes:
    source = value.source
    locators = {item.locator_id: item for item in value.review_locators}
    lines = [
        "# 策展地图 · 阅读版",
        "",
        "> 以下内容是待审候选，不是已批准的可信知识。具体说法请打开原文证据核对。",
        "",
    ]
    for title, kinds in _SHORT_READING_SECTIONS:
        lines.extend((f"## {title}", ""))
        selected = [item for item in value.candidates if item.kind in kinds]
        if not selected:
            if title.startswith("8.") and value.target_binding is None:
                lines.append("本次暂不选库，因此不拟定知识库结构。")
            else:
                lines.append("本次未形成可支持的候选。")
            lines.append("")
            continue
        for index, candidate in enumerate(selected, 1):
            lines.extend((f"### 候选 {index}", "", *_quoted_markdown(candidate.summary), ""))
            selected_locators = sorted(
                (
                    locators[item]
                    for item in candidate.evidence_locator_ids
                    if item in locators
                ),
                key=lambda item: item.byte_range.start_byte,
            )
            merged: list[tuple[int, int, int]] = []
            for locator in selected_locators:
                if merged and merged[-1][2] == locator.byte_range.start_byte:
                    start_line, _end_line, _end_byte = merged[-1]
                    merged[-1] = (
                        start_line,
                        locator.end_line,
                        locator.byte_range.end_byte,
                    )
                else:
                    merged.append(
                        (
                            locator.start_line,
                            locator.end_line,
                            locator.byte_range.end_byte,
                        )
                    )
            spans = [
                (
                    f"原文第 {start} 行"
                    if start == end
                    else f"原文第 {start}–{end} 行"
                )
                for start, end, _end_byte in merged
            ]
            if len(selected_locators) != len(candidate.evidence_locator_ids):
                spans.append("来源证据（见来源记录）")
            lines.append(
                "证据：" + ("、".join(spans) if spans else "此项没有精确证据")
            )
            lines.append(
                "属性："
                + _READING_PROVENANCE[candidate.provenance]
                + "；不确定性："
                + _READING_UNCERTAINTY[candidate.uncertainty]
            )
            lines.extend(
                (
                    "",
                    "<details><summary>审核编号</summary>",
                    "",
                    f"候选：`{candidate.candidate_id}`；证据："
                    + ("、".join(f"`{item}`" for item in candidate.evidence_locator_ids) or "无"),
                    "",
                    "</details>",
                    "",
                )
            )
    profile = value.processor_profile
    usage = value.processor_usage
    lines.extend(
        (
            "## 9. 处理记录",
            "",
            f"- 地图：`{value.map_id}` / v{value.map_version}；运行：`{value.curation_run_id}`",
            f"- 来源：Capture `{source.capture_id}` / v{source.capture_version}；{source.byte_size} bytes",
            f"- 创建时间：`{value.created_at}`",
            f"- 处理器：`{profile.processor_id}` / r{profile.revision}；模型：`{profile.model_id or '无'}`",
            f"- 调用：{usage.call_count} 次；输入 {usage.input_tokens} token；输出 {usage.output_tokens} token；用时 {usage.elapsed_ms} ms",
        )
    )
    if usage.cost_currency is not None:
        lines.append(
            f"- 外部费用：{usage.cost_minor_units} {usage.cost_currency} 最小货币单位"
        )
    lines.extend(
        (
            "",
            "## 10. 覆盖报告",
            "",
            f"- 声明范围：byte [{value.declared_scope.start_byte}, {value.declared_scope.end_byte})",
        )
    )
    for item in value.scope:
        reason = f"；原因：{item.reason}" if item.reason else ""
        lines.append(
            f"- `{item.status}`：byte [{item.byte_range.start_byte}, {item.byte_range.end_byte}){reason}"
        )
    lines.extend(("", "机械范围完整不保证语义零遗漏；原文证据与未决项仍需人工核查。"))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_curation_map_markdown(value: CurationMap) -> bytes:
    """Render a readable view containing no facts absent from ``map.yaml``."""

    if not isinstance(value, CurationMap):
        raise TypeError("value must be CurationMap")
    if value.reading_profile == SHORT_READING_PROFILE:
        return _render_short_reading_map(value)

    source = value.source
    target = value.target_binding.kb_id if value.target_binding is not None else "暂未绑定"
    lines = [
        "# 策展地图",
        "",
        "## 身份",
        "",
        f"- 地图：`{value.map_id}` / v{value.map_version}",
        f"- 运行：`{value.curation_run_id}`",
        f"- 创建时间：`{value.created_at}`",
        f"- 来源：`{source.capture_id}` / v{source.capture_version}",
        f"- Payload：`{source.payload_sha256}` / {source.byte_size} bytes",
        f"- 目标知识库：`{target}`",
        "",
        "## 处理范围",
        "",
        (
            f"- 声明范围：`[{value.declared_scope.start_byte}, "
            f"{value.declared_scope.end_byte})`"
        ),
    ]
    for item in value.scope:
        reason = f"；原因：{item.reason}" if item.reason is not None else ""
        lines.append(
            f"- `{item.status}`：`[{item.byte_range.start_byte}, "
            f"{item.byte_range.end_byte})`{reason}"
        )

    profile = value.processor_profile
    usage = value.processor_usage
    lines.extend(
        [
            "",
            "## 处理器与成本",
            "",
            f"- 处理器：`{profile.kind}` / `{profile.processor_id}` / r{profile.revision}",
            f"- 模型：`{profile.model_id or '无'}`",
            f"- 使用网络：`{'是' if profile.network_allowed else '否'}`",
            f"- 调用次数：{usage.call_count}",
            f"- Token：输入 {usage.input_tokens} / 输出 {usage.output_tokens}",
            f"- 用时：{usage.elapsed_ms} ms",
        ]
    )
    if usage.cost_currency is None:
        lines.append("- 外部费用：未发生或不适用")
    else:
        lines.append(
            f"- 外部费用：{usage.cost_minor_units} {usage.cost_currency} 最小货币单位"
        )

    lines.extend(["", "## 候选", ""])
    for candidate in value.candidates:
        lines.extend(
            [
                f"### {candidate.markdown_anchor}",
                "",
                f"- 候选 ID：`{candidate.candidate_id}`",
                f"- 类型：`{candidate.kind}`",
                f"- 来源属性：`{candidate.provenance}`",
                f"- 不确定性：`{candidate.uncertainty}`",
                "- 证据："
                + (
                    "、".join(f"`{item}`" for item in candidate.evidence_locator_ids)
                    if candidate.evidence_locator_ids
                    else "无精确 locator；必须按类型解释为缺口或组织建议"
                ),
                f"- 替代自：`{candidate.supersedes or '无'}`",
                "",
                "摘要：",
                "",
                *_quoted_markdown(candidate.summary),
                "",
            ]
        )

    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def curation_map_artifact_sha256(
    map_yaml: bytes | bytearray | memoryview,
    map_markdown: bytes | bytearray | memoryview,
) -> str:
    """Hash the ordered two-file map artifact without self-reference."""

    if not isinstance(map_yaml, (bytes, bytearray, memoryview)):
        raise TypeError("map_yaml must be bytes-like")
    if not isinstance(map_markdown, (bytes, bytearray, memoryview)):
        raise TypeError("map_markdown must be bytes-like")
    manifest = [
        {"path": "map.yaml", "sha256": _sha256(bytes(map_yaml))},
        {"path": "map.md", "sha256": _sha256(bytes(map_markdown))},
    ]
    return _sha256(CURATION_MAP_HASH_DOMAIN + _compact_json_bytes(manifest))


def map_decision_sha256(value: MapDecision) -> str:
    if not isinstance(value, MapDecision):
        raise TypeError("value must be MapDecision")
    return _sha256(dump_map_decision(value))


__all__ = [
    "CURATION_MAP_HASH_DOMAIN",
    "NonCanonicalYamlError",
    "SchemaValidationError",
    "YamlSyntaxGateError",
    "curation_map_artifact_sha256",
    "dump_curation_evidence",
    "dump_curation_map",
    "dump_curation_run",
    "dump_kb_manifest",
    "dump_map_decision",
    "dump_raw_source_mapping",
    "dump_route_record",
    "dump_source_mapping",
    "dump_target_decision_record",
    "load_curation_evidence",
    "load_curation_map",
    "load_curation_run",
    "load_kb_manifest",
    "load_map_decision",
    "load_raw_source_mapping",
    "load_route_record",
    "load_source_mapping",
    "load_target_decision_record",
    "map_decision_sha256",
    "render_curation_map_markdown",
]
