"""Machine-local Capture Store configuration parsing and canonical emission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path

from .codec import (
    MappingSchema,
    ScalarSchema,
    SchemaField,
    SchemaValidationError,
    ValueSchema,
    YamlSyntaxGateError,
    dump_restricted_yaml,
    load_restricted_yaml,
)
from .errors import PublicErrorCode
from .paths import (
    PathPolicy,
    PathPolicyError,
    normalize_windows_local_absolute_path,
)


LOCAL_CONFIG_SCHEMA = "knowledgeflow.local-config"
LOCAL_CONFIG_SCHEMA_VERSION = 1
DEFAULT_INLINE_TEXT_THRESHOLD_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TEXT_VERSION_BYTES = 64 * 1024 * 1024


class ConfigLoadError(ValueError):
    """A stable public classification for configuration loading failures."""

    def __init__(self, code: PublicErrorCode) -> None:
        normalized = PublicErrorCode(code)
        if normalized not in {
            PublicErrorCode.CONFIG_NOT_FOUND,
            PublicErrorCode.CONFIG_INVALID,
        }:
            raise ValueError("invalid configuration error code")
        self.code = normalized
        super().__init__(normalized.value)


def _field(name: str, schema: ValueSchema) -> SchemaField:
    return SchemaField(name, schema)


def _validate_thresholds(value: object, path: str) -> None:
    capture = value
    if not isinstance(capture, Mapping):
        raise SchemaValidationError(f"{path} must be a mapping")
    if capture["inline_text_threshold_bytes"] > capture["max_text_version_bytes"]:
        raise SchemaValidationError(
            f"{path}.inline_text_threshold_bytes must not exceed the maximum"
        )


_CAPTURE_CONFIG_SCHEMA_V1 = MappingSchema(
    (
        _field("root", ScalarSchema(str, nonempty=True)),
        _field("inline_text_threshold_bytes", ScalarSchema(int, minimum=1)),
        _field("max_text_version_bytes", ScalarSchema(int, minimum=1)),
    ),
    validator=_validate_thresholds,
)

LOCAL_CONFIG_SCHEMA_V1 = MappingSchema(
    (
        _field(
            "schema",
            ScalarSchema(str, allowed_values=(LOCAL_CONFIG_SCHEMA,)),
        ),
        _field(
            "schema_version",
            ScalarSchema(int, allowed_values=(LOCAL_CONFIG_SCHEMA_VERSION,)),
        ),
        _field("capture", _CAPTURE_CONFIG_SCHEMA_V1),
    )
)


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    root: Path
    inline_text_threshold_bytes: int
    max_text_version_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("root must be a pathlib.Path")
        normalized_root = normalize_windows_local_absolute_path(self.root)
        object.__setattr__(self, "root", normalized_root)
        if type(self.inline_text_threshold_bytes) is not int or (
            self.inline_text_threshold_bytes <= 0
        ):
            raise ValueError("inline threshold must be a positive integer")
        if type(self.max_text_version_bytes) is not int or (
            self.max_text_version_bytes <= 0
        ):
            raise ValueError("maximum threshold must be a positive integer")
        if self.inline_text_threshold_bytes > self.max_text_version_bytes:
            raise ValueError("inline threshold must not exceed maximum threshold")

    def as_mapping(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "inline_text_threshold_bytes": self.inline_text_threshold_bytes,
            "max_text_version_bytes": self.max_text_version_bytes,
        }


@dataclass(frozen=True, slots=True)
class LocalConfig:
    capture: CaptureConfig

    def __post_init__(self) -> None:
        if not isinstance(self.capture, CaptureConfig):
            raise TypeError("capture must be CaptureConfig")

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": LOCAL_CONFIG_SCHEMA,
            "schema_version": LOCAL_CONFIG_SCHEMA_VERSION,
            "capture": self.capture.as_mapping(),
        }


def create_local_config(
    *,
    root: str | os.PathLike[str],
    inline_text_threshold_bytes: int,
    max_text_version_bytes: int,
    path_policy: PathPolicy,
) -> LocalConfig:
    """Construct a config only after applying the trusted root policy."""

    if not isinstance(path_policy, PathPolicy):
        raise TypeError("path_policy must be a trusted PathPolicy")
    try:
        normalized_root = path_policy.validate_capture_root(root)
        return LocalConfig(
            capture=CaptureConfig(
                root=normalized_root,
                inline_text_threshold_bytes=inline_text_threshold_bytes,
                max_text_version_bytes=max_text_version_bytes,
            )
        )
    except (PathPolicyError, TypeError, ValueError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc


def parse_local_config(
    source: str | bytes | bytearray | memoryview,
    *,
    path_policy: PathPolicy,
) -> LocalConfig:
    """Load safe config YAML; canonical source bytes are not required."""

    if not isinstance(path_policy, PathPolicy):
        raise TypeError("path_policy must be a trusted PathPolicy")
    try:
        normalized = load_restricted_yaml(source, LOCAL_CONFIG_SCHEMA_V1)
        capture = normalized["capture"]
        return create_local_config(
            root=capture["root"],
            inline_text_threshold_bytes=capture["inline_text_threshold_bytes"],
            max_text_version_bytes=capture["max_text_version_bytes"],
            path_policy=path_policy,
        )
    except ConfigLoadError:
        raise
    except (YamlSyntaxGateError, SchemaValidationError) as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc


def dump_local_config(config: LocalConfig) -> bytes:
    """Return canonical config bytes without writing them to the filesystem."""

    if not isinstance(config, LocalConfig):
        raise TypeError("config must be LocalConfig")
    return dump_restricted_yaml(config.as_mapping(), LOCAL_CONFIG_SCHEMA_V1)


def resolve_config_path(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    local_app_data: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the explicit path or the Windows LOCALAPPDATA default."""

    try:
        if explicit_path is not None:
            return normalize_windows_local_absolute_path(explicit_path)

        selected_base = (
            local_app_data
            if local_app_data is not None
            else os.environ.get("LOCALAPPDATA")
        )
        if selected_base is None:
            raise ConfigLoadError(PublicErrorCode.CONFIG_NOT_FOUND)
        base = normalize_windows_local_absolute_path(selected_base)
        return normalize_windows_local_absolute_path(
            base / "KnowledgeFlow" / "config.yaml"
        )
    except ConfigLoadError:
        raise
    except PathPolicyError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc


ConfigReader = Callable[[Path], bytes]


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def read_local_config_file(
    config_path: str | os.PathLike[str],
    *,
    path_policy: PathPolicy,
    reader: ConfigReader | None = None,
) -> LocalConfig:
    """Read exactly one selected config file without searching other locations."""

    try:
        selected_path = normalize_windows_local_absolute_path(config_path)
    except PathPolicyError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc

    try:
        source = (reader or _read_bytes)(selected_path)
    except FileNotFoundError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_NOT_FOUND) from exc
    except OSError as exc:
        raise ConfigLoadError(PublicErrorCode.CONFIG_INVALID) from exc
    return parse_local_config(source, path_policy=path_policy)


__all__ = [
    "CaptureConfig",
    "ConfigLoadError",
    "DEFAULT_INLINE_TEXT_THRESHOLD_BYTES",
    "DEFAULT_MAX_TEXT_VERSION_BYTES",
    "LOCAL_CONFIG_SCHEMA",
    "LOCAL_CONFIG_SCHEMA_V1",
    "LOCAL_CONFIG_SCHEMA_VERSION",
    "LocalConfig",
    "create_local_config",
    "dump_local_config",
    "parse_local_config",
    "read_local_config_file",
    "resolve_config_path",
]
