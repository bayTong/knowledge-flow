"""Trusted runtime construction shared by installed local entry points."""

from __future__ import annotations

from pathlib import Path

from .paths import PathPolicy


def production_source_root() -> Path:
    """Return the package root, or the repository root in a ``src`` checkout."""

    package_root = Path(__file__).resolve(strict=True).parent
    repository_root = package_root.parent.parent
    if (
        package_root.parent.name.casefold() == "src"
        and (repository_root / "pyproject.toml").is_file()
    ):
        return repository_root
    return package_root


def production_path_policy() -> PathPolicy:
    """Build the fixed production path policy without caller-controlled roots."""

    return PathPolicy.production(source_root=production_source_root())


__all__ = ["production_path_policy", "production_source_root"]
