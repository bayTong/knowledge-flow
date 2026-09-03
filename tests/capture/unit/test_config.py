from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from knowledgeflow_capture.config import (
    ConfigLoadError,
    dump_local_config,
    parse_local_config,
    read_local_config_file,
    resolve_config_path,
)
from knowledgeflow_capture.errors import PublicErrorCode
from knowledgeflow_capture.paths import PathPolicy


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OWNED_ROOT = Path(r"C:\KnowledgeFlowTests\owned")
CAPTURE_ROOT = OWNED_ROOT / "capture-store"


def _identity(path: Path) -> Path:
    return path


class LocalConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PathPolicy.test_owned(OWNED_ROOT, resolver=_identity)

    def test_cfg_01_default_missing_returns_code_without_scanning(self) -> None:
        expected = Path(r"C:\Users\tester\AppData\Local\KnowledgeFlow\config.yaml")
        with patch.dict(
            os.environ,
            {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"},
            clear=True,
        ):
            resolved = resolve_config_path()
        self.assertEqual(resolved, expected)

        reads: list[Path] = []

        def missing(path: Path) -> bytes:
            reads.append(path)
            raise FileNotFoundError

        with self.assertRaises(ConfigLoadError) as raised:
            read_local_config_file(resolved, path_policy=self.policy, reader=missing)

        self.assertEqual(raised.exception.code, PublicErrorCode.CONFIG_NOT_FOUND)
        self.assertEqual(reads, [expected])

        with patch.dict(os.environ, {}, clear=True), self.assertRaises(
            ConfigLoadError
        ) as missing_environment:
            resolve_config_path()
        self.assertEqual(
            missing_environment.exception.code,
            PublicErrorCode.CONFIG_NOT_FOUND,
        )

    def test_cfg_02_explicit_absolute_path_is_used_exactly(self) -> None:
        explicit = Path(r"D:\KnowledgeFlowConfig\capture.yaml")
        self.assertEqual(
            resolve_config_path(
                explicit,
                local_app_data=Path(r"C:\ignored"),
            ),
            explicit,
        )

    def test_cfg_03_relative_config_paths_are_rejected(self) -> None:
        for value in (Path("config.yaml"), Path(r"configs\capture.yaml"), Path("C:config.yaml")):
            with self.subTest(value=value), self.assertRaises(ConfigLoadError) as raised:
                resolve_config_path(value)
            self.assertEqual(raised.exception.code, PublicErrorCode.CONFIG_INVALID)

    def test_cfg_07_unknown_duplicate_and_wrong_version_are_invalid(self) -> None:
        cases = {
            "unknown-field": (
                'schema: "knowledgeflow.local-config"\n'
                "schema_version: 1\n"
                "capture:\n"
                f'  root: "{str(CAPTURE_ROOT).replace(chr(92), chr(92) * 2)}"\n'
                "  inline_text_threshold_bytes: 4194304\n"
                "  max_text_version_bytes: 67108864\n"
                'secret: "not-allowed"\n'
            ),
            "duplicate-key": (
                'schema: "knowledgeflow.local-config"\n'
                'schema: "knowledgeflow.local-config"\n'
                "schema_version: 1\n"
                "capture: {}\n"
            ),
            "wrong-version": (
                'schema: "knowledgeflow.local-config"\n'
                "schema_version: 2\n"
                "capture: {}\n"
            ),
        }

        for name, source in cases.items():
            with self.subTest(name=name), self.assertRaises(ConfigLoadError) as raised:
                parse_local_config(source, path_policy=self.policy)
            self.assertEqual(raised.exception.code, PublicErrorCode.CONFIG_INVALID)

    def test_cfg_08_threshold_relationship_is_strict(self) -> None:
        template = (
            'schema: "knowledgeflow.local-config"\n'
            "schema_version: 1\n"
            "capture:\n"
            f'  root: "{str(CAPTURE_ROOT).replace(chr(92), chr(92) * 2)}"\n'
            "  inline_text_threshold_bytes: {inline}\n"
            "  max_text_version_bytes: {maximum}\n"
        )
        for inline, maximum in ((0, 1), (-1, 1), (2, 1), (True, 2)):
            source = template.format(
                inline=str(inline).lower(),
                maximum=maximum,
            )
            with self.subTest(inline=inline, maximum=maximum), self.assertRaises(
                ConfigLoadError
            ) as raised:
                parse_local_config(source, path_policy=self.policy)
            self.assertEqual(raised.exception.code, PublicErrorCode.CONFIG_INVALID)

    def test_cfg_09_noncanonical_input_loads_and_dump_matches_golden(self) -> None:
        noncanonical = (
            "schema: knowledgeflow.local-config\n"
            "schema_version: 1\n"
            "capture:\n"
            f"    root: {CAPTURE_ROOT}\n"
            "    inline_text_threshold_bytes: 4194304\n"
            "    max_text_version_bytes: 67108864\n"
        )

        config = parse_local_config(noncanonical, path_policy=self.policy)
        expected = (FIXTURES / "local-config-v1.yaml").read_bytes()

        self.assertEqual(config.capture.root, CAPTURE_ROOT)
        self.assertEqual(dump_local_config(config), expected)
        self.assertNotIn(b"\r", expected)
        self.assertTrue(expected.endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
