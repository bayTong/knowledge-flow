"""UUIDv7 identifiers owned by the curation package."""

from __future__ import annotations

from knowledgeflow_capture.ids import generate_uuid7


_PREFIXES = frozenset(
    {
        "auth_",
        "cand_",
        "dset_",
        "kb_",
        "loc_",
        "map_",
        "run_",
        "seg_",
        "smap_",
        "target_",
    }
)


def generate_curation_id(prefix: str) -> str:
    """Generate one typed UUIDv7 for a known curation identity kind."""

    if prefix not in _PREFIXES:
        raise ValueError("unknown curation ID prefix")
    return prefix + str(generate_uuid7())


__all__ = ["generate_curation_id"]
