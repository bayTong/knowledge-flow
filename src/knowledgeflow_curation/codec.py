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
    SourceFileMapping,
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


def render_curation_map_markdown(value: CurationMap) -> bytes:
    """Render a readable view containing no facts absent from ``map.yaml``."""

    if not isinstance(value, CurationMap):
        raise TypeError("value must be CurationMap")

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
    "dump_source_mapping",
    "load_curation_evidence",
    "load_curation_map",
    "load_curation_run",
    "load_kb_manifest",
    "load_map_decision",
    "load_source_mapping",
    "map_decision_sha256",
    "render_curation_map_markdown",
]
