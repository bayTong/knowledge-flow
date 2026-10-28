"""Read-only review of a published no-target map and its exact source evidence.

This view does not rewrite the hashed map.md artifact. It keeps the v1 map
validator and the existing Capture-backed evidence operation as authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path

from knowledgeflow_capture import GetCaptureRequest, GetCaptureResult, get_capture
from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.hashing import hash_bytes
from knowledgeflow_capture.paths import PathPolicy

from .contracts import CurationEvidenceRecord, CurationMap, EvidenceLocator, MapCandidate
from .errors import CurationFailure
from .map_operations import _load_map_version
from .operations import (
    EvidenceShowRequest,
    EvidenceShowResult,
    SourceInspectRequest,
    SourceInspectResult,
    inspect_source,
    show_evidence,
)


class MapReviewError(ValueError):
    """The requested review cannot establish a verified map/source binding."""


_SECTION_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1. 全景概括", ("overview",)),
    ("2. 材料结构与提取层次", ("structure",)),
    ("3. 核心概念与实体", ("concept",)),
    ("4. 关系清单", ("relationship",)),
    ("5. 原文主张与叙述", ("claim",)),
    ("6. 争议与不确定性", ("dispute", "limitation")),
    ("7. 缺口分析", ("gap",)),
    ("8. 组织建议", ("organization",)),
)


@dataclass(frozen=True, slots=True)
class ReviewSection:
    title: str
    candidates: tuple[MapCandidate, ...]


@dataclass(frozen=True, slots=True)
class VerifiedExcerpt:
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    excerpt_sha256: str
    whole_source: bool
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MapReviewSession:
    curation_map: CurationMap
    evidence: CurationEvidenceRecord
    map_sha256: str
    source_request_id: str
    experiment_root: Path
    path_policy: PathPolicy
    source_warning_codes: tuple[str, ...]

    def _locator(self, locator_id: str) -> EvidenceLocator:
        for locator in (*self.evidence.locators, *self.curation_map.review_locators):
            if locator.locator_id == locator_id:
                return locator
        raise MapReviewError("地图引用的证据范围不存在。")

    @property
    def sections(self) -> tuple[ReviewSection, ...]:
        return tuple(
            ReviewSection(
                title=title,
                candidates=tuple(
                    item
                    for item in self.curation_map.candidates
                    if item.kind in kinds
                ),
            )
            for title, kinds in _SECTION_ORDER
        )

    def candidate(self, candidate_id: str) -> MapCandidate:
        for item in self.curation_map.candidates:
            if item.candidate_id == candidate_id:
                return item
        raise MapReviewError("地图中没有该候选条目。")

    def locator_label(self, locator_id: str) -> str:
        locator = self._locator(locator_id)
        span = (
            str(locator.start_line)
            if locator.start_line == locator.end_line
            else f"{locator.start_line}–{locator.end_line}"
        )
        return f"原文第 {span} 行"

    def _read_review_locator(self, locator: EvidenceLocator) -> VerifiedExcerpt:
        sink = io.BytesIO()
        read = get_capture(
            GetCaptureRequest(
                capture_id=locator.source.capture_id,
                version=locator.source.capture_version,
                body_sink=sink,
            ),
            config_path=self.experiment_root / "capture-config.yaml",
            path_policy=self.path_policy,
        )
        if isinstance(read, FailureResult) or not isinstance(read, GetCaptureResult):
            raise MapReviewError("原文 Capture 版本无法通过核验。")
        metadata = read.capture
        source = locator.source
        if (
            metadata.capture_id != source.capture_id
            or metadata.version != source.capture_version
            or metadata.envelope_sha256 != source.envelope_sha256
            or metadata.primary_payload_sha256 != source.payload_sha256
            or metadata.byte_size != source.byte_size
        ):
            raise MapReviewError("原文版本与地图来源身份不一致。")
        body = sink.getvalue()
        if len(body) != source.byte_size or hash_bytes(body).sha256 != source.payload_sha256:
            raise MapReviewError("原文完整性无法通过核验。")
        start = locator.byte_range.start_byte
        end = locator.byte_range.end_byte
        excerpt = body[start:end]
        if end > len(body) or hash_bytes(excerpt).sha256 != locator.excerpt_sha256:
            raise MapReviewError("这条行级证据与原文不一致。")
        try:
            text = excerpt.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MapReviewError("这条证据不是完整的 UTF-8 文本。") from exc
        if (
            body.count(b"\n", 0, start) + 1 != locator.start_line
            or body.count(b"\n", 0, end - 1) + 1 != locator.end_line
        ):
            raise MapReviewError("证据显示行号与原文不一致。")
        return VerifiedExcerpt(
            text=text,
            start_line=locator.start_line,
            end_line=locator.end_line,
            start_byte=start,
            end_byte=end,
            excerpt_sha256=locator.excerpt_sha256,
            whole_source=start == 0 and end == source.byte_size,
            warning_codes=tuple(
                sorted(
                    set(self.source_warning_codes)
                    | {item.code.value for item in read.warnings}
                )
            ),
        )

    def read_evidence(self, candidate_id: str, locator_id: str) -> VerifiedExcerpt:
        candidate = self.candidate(candidate_id)
        if locator_id not in candidate.evidence_locator_ids:
            raise MapReviewError("这条证据不属于当前候选。")
        locator = self._locator(locator_id)
        if locator in self.curation_map.review_locators:
            return self._read_review_locator(locator)
        sink = io.BytesIO()
        result = show_evidence(
            EvidenceShowRequest(
                request_id=self.source_request_id,
                locator_id=locator_id,
                body_sink=sink,
            ),
            experiment_root=self.experiment_root,
            path_policy=self.path_policy,
        )
        if isinstance(result, CurationFailure):
            raise MapReviewError(f"原文核验失败：{result.error.code.value}。")
        if not isinstance(result, EvidenceShowResult):
            raise MapReviewError("原文核验没有返回可用结果。")
        locator = result.locator
        if (
            result.curation_run_id != self.curation_map.curation_run_id
            or locator.source != self.curation_map.source
        ):
            raise MapReviewError("证据与当前地图的来源版本不一致。")
        try:
            text = sink.getvalue().decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MapReviewError("证据不是完整的 UTF-8 文本。") from exc
        return VerifiedExcerpt(
            text=text,
            start_line=locator.start_line,
            end_line=locator.end_line,
            start_byte=locator.byte_range.start_byte,
            end_byte=locator.byte_range.end_byte,
            excerpt_sha256=locator.excerpt_sha256,
            whole_source=(
                locator.byte_range.start_byte == 0
                and locator.byte_range.end_byte == self.curation_map.source.byte_size
            ),
            warning_codes=result.capture_warning_codes,
        )


def load_map_review(
    *,
    experiment_root: str | Path,
    map_directory: str | Path,
    path_policy: PathPolicy,
) -> MapReviewSession:
    """Load an immutable no-target map without changing its published files."""

    if not isinstance(path_policy, PathPolicy):
        raise MapReviewError("路径策略无效。")
    try:
        root = Path(experiment_root).resolve(strict=True)
        directory = Path(map_directory).resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise MapReviewError("实验根或地图目录无法读取。") from exc
    if not root.is_dir() or not directory.is_dir():
        raise MapReviewError("实验根或地图目录不存在。")
    if not directory.is_relative_to(root / "curation-work"):
        raise MapReviewError("本批只读取该实验根内的无目标地图。")
    try:
        curation_map, _, _, map_sha256 = _load_map_version(directory)
        if curation_map.target_binding is not None:
            raise MapReviewError("本批只支持暂不选库的地图阅读。")
        expected = (
            root
            / "curation-work"
            / curation_map.curation_run_id
            / "curation-maps"
            / curation_map.map_id
            / f"v{curation_map.map_version:04d}"
        )
        if directory != expected:
            raise MapReviewError("地图目录与已发布身份不一致。")
        run_path = directory / "run.json"
        if run_path.stat().st_size > 2 * 1024 * 1024:
            raise MapReviewError("地图运行记录超出读取上限。")
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if not isinstance(run, dict):
            raise MapReviewError("地图运行记录无效。")
        source_request_id = run.get("source_request_id")
        if (
            not isinstance(source_request_id, str)
            or run.get("curation_run_id") != curation_map.curation_run_id
            or run.get("map_id") != curation_map.map_id
            or run.get("map_version") != curation_map.map_version
            or run.get("map_sha256") != map_sha256
        ):
            raise MapReviewError("地图运行记录与已发布版本不一致。")
        source = inspect_source(
            SourceInspectRequest(request_id=source_request_id),
            experiment_root=root,
        )
        if not isinstance(source, SourceInspectResult):
            raise MapReviewError("来源记录无法通过核验。")
        curation_map.validate_against(source.evidence)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, MapReviewError):
            raise
        raise MapReviewError("地图或来源记录无法通过核验。") from exc
    return MapReviewSession(
        curation_map=curation_map,
        evidence=source.evidence,
        map_sha256=map_sha256,
        source_request_id=source_request_id,
        experiment_root=root,
        path_policy=path_policy,
        source_warning_codes=source.capture_warning_codes,
    )


__all__ = [
    "MapReviewError",
    "MapReviewSession",
    "ReviewSection",
    "VerifiedExcerpt",
    "load_map_review",
]
