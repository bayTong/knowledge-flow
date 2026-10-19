"""Deterministic, offline segmentation and exact Evidence locator creation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import re

from knowledgeflow_capture.hashing import hash_bytes

from .contracts import (
    ByteRange,
    CurationEvidenceRecord,
    CurationRunManifest,
    EvidenceLocator,
    ScopeRecord,
    SegmentRecord,
)
from .ids import generate_curation_id


_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MAX_HEADING_BYTES = 512

IdFactory = Callable[[str], str]


def _line_spans(source: bytes) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(source):
        newline = source.find(b"\n", start)
        end = len(source) if newline < 0 else newline + 1
        spans.append((start, end))
        start = end
    return tuple(spans)


def _line_text(source: bytes, start: int, end: int) -> str:
    return source[start:end].decode("utf-8", errors="strict").rstrip("\r\n")


def _markdown_boundaries(
    source: bytes,
    spans: Sequence[tuple[int, int]],
) -> tuple[frozenset[int], tuple[tuple[int, tuple[str, ...]], ...]]:
    preferred: set[int] = {0, len(source)}
    heading_events: list[tuple[int, tuple[str, ...]]] = []
    headings: list[str] = []
    fence_character: str | None = None
    fence_length = 0

    for start, end in spans:
        text = _line_text(source, start, end)
        fence = _FENCE.match(text)
        if fence_character is not None:
            stripped = text.lstrip(" ")
            if (
                len(text) - len(stripped) <= 3
                and re.fullmatch(
                    re.escape(fence_character)
                    + "{"
                    + str(fence_length)
                    + ",}[ \\t]*",
                    stripped,
                )
                is not None
            ):
                fence_character = None
                fence_length = 0
                preferred.add(end)
            continue

        if fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            preferred.add(start)
            continue

        heading = _HEADING.match(text)
        if heading is not None:
            level = len(heading.group(1))
            label = heading.group(2).strip()
            if label and len(label.encode("utf-8")) <= _MAX_HEADING_BYTES:
                del headings[level - 1 :]
                headings.append(label)
                heading_events.append((start, tuple(headings)))
            preferred.add(start)
        if not text.strip():
            preferred.add(end)

    return frozenset(preferred), tuple(heading_events)


def _is_utf8_boundary(source: bytes, offset: int) -> bool:
    return offset == 0 or offset == len(source) or source[offset] & 0xC0 != 0x80


def _bounded_character_boundary(source: bytes, start: int, maximum: int) -> int:
    candidate = maximum
    while candidate > start and not _is_utf8_boundary(source, candidate):
        candidate -= 1
    if candidate <= start:
        raise ValueError("no UTF-8 character boundary fits the segment limit")
    return candidate


def _choose_end(
    source: bytes,
    *,
    start: int,
    scope_end: int,
    target_bytes: int,
    maximum_bytes: int,
    preferred: frozenset[int],
    line_ends: frozenset[int],
) -> int:
    if scope_end - start <= target_bytes:
        return scope_end
    target = min(scope_end, start + target_bytes)
    maximum = min(scope_end, start + maximum_bytes)

    before = [value for value in preferred if start < value <= target]
    if before:
        return max(before)
    after = [value for value in preferred if target < value <= maximum]
    if after:
        return min(after)
    line_before = [value for value in line_ends if start < value <= maximum]
    if line_before:
        return max(line_before)
    return _bounded_character_boundary(source, start, maximum)


def _line_number_at_start(source: bytes, offset: int) -> int:
    return source.count(b"\n", 0, offset) + 1


def _line_number_at_end(source: bytes, start: int, end: int) -> int:
    if end <= start:
        raise ValueError("segment must not be empty")
    return source.count(b"\n", 0, end - 1) + 1


def _heading_at(
    events: Sequence[tuple[int, tuple[str, ...]]],
    offset: int,
) -> tuple[str, ...]:
    selected: tuple[str, ...] = ()
    for position, path in events:
        if position > offset:
            break
        selected = path
    return selected


def _validate_scope_bytes(source: bytes, byte_range: ByteRange) -> None:
    if byte_range.end_byte > len(source):
        raise ValueError("declared scope exceeds source bytes")
    if not _is_utf8_boundary(source, byte_range.start_byte) or not _is_utf8_boundary(
        source,
        byte_range.end_byte,
    ):
        raise ValueError("declared scope must use UTF-8 character boundaries")


def build_evidence_record(
    source: bytes,
    run: CurationRunManifest,
    *,
    scope: Sequence[ScopeRecord] | None = None,
    id_factory: IdFactory = generate_curation_id,
) -> CurationEvidenceRecord:
    """Build the CUR1B raw Segment layer and one exact locator per Segment."""

    if type(source) is not bytes or not source:
        raise ValueError("source must be non-empty bytes")
    if not isinstance(run, CurationRunManifest):
        raise TypeError("run must be CurationRunManifest")
    source.decode("utf-8", errors="strict")
    if len(source) != run.source.byte_size:
        raise ValueError("source byte size does not match the run")
    if hash_bytes(source).sha256 != run.source.payload_sha256:
        raise ValueError("source digest does not match the run")

    declared = run.declared_scope
    _validate_scope_bytes(source, declared)
    spans = _line_spans(source)
    preferred, heading_events = _markdown_boundaries(source, spans)
    line_ends = frozenset(end for _start, end in spans)
    profile = run.segmentation_profile

    ranges: list[ByteRange] = []
    cursor = declared.start_byte
    while cursor < declared.end_byte:
        end = _choose_end(
            source,
            start=cursor,
            scope_end=declared.end_byte,
            target_bytes=profile.target_bytes,
            maximum_bytes=profile.maximum_bytes,
            preferred=preferred,
            line_ends=line_ends,
        )
        ranges.append(ByteRange(cursor, end))
        cursor = end

    segments: list[SegmentRecord] = []
    locators: list[EvidenceLocator] = []
    for ordinal, byte_range in enumerate(ranges):
        body = source[byte_range.start_byte : byte_range.end_byte]
        digest = hash_bytes(body).sha256
        start_line = _line_number_at_start(source, byte_range.start_byte)
        end_line = _line_number_at_end(
            source,
            byte_range.start_byte,
            byte_range.end_byte,
        )
        segments.append(
            SegmentRecord(
                segment_id=id_factory("seg_"),
                ordinal=ordinal,
                byte_range=byte_range,
                start_line=start_line,
                end_line=end_line,
                heading_path=_heading_at(heading_events, byte_range.start_byte),
                body_sha256=digest,
                profile_id=profile.profile_id,
                profile_revision=profile.revision,
            )
        )
        locators.append(
            EvidenceLocator(
                locator_id=id_factory("loc_"),
                source=run.source,
                byte_range=byte_range,
                start_line=start_line,
                end_line=end_line,
                excerpt_sha256=digest,
            )
        )

    selected_scope = (
        tuple(scope)
        if scope is not None
        else (ScopeRecord(declared, "processed"),)
    )
    evidence = CurationEvidenceRecord(
        curation_run_id=run.curation_run_id,
        source=run.source,
        declared_scope=declared,
        segmentation_profile=profile,
        segments=tuple(segments),
        scope=selected_scope,
        locators=tuple(locators),
    )
    evidence.validate_against_run(run)
    return evidence


def deterministic_segment_fingerprint(
    evidence: CurationEvidenceRecord,
) -> tuple[tuple[object, ...], ...]:
    """Return ID-free ordered facts used by the CUR1B double-run check."""

    if not isinstance(evidence, CurationEvidenceRecord):
        raise TypeError("evidence must be CurationEvidenceRecord")
    return tuple(
        (
            item.ordinal,
            item.byte_range.start_byte,
            item.byte_range.end_byte,
            item.start_line,
            item.end_line,
            item.heading_path,
            item.body_sha256,
            item.profile_id,
            item.profile_revision,
        )
        for item in evidence.segments
    )


__all__ = ["build_evidence_record", "deterministic_segment_fingerprint"]
