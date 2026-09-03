from __future__ import annotations

from pathlib import Path
import unittest

from knowledgeflow_capture.paths import (
    PathPolicy,
    PathPolicyError,
    normalize_windows_local_absolute_path,
)


def _identity(path: Path) -> Path:
    return path


class PathPolicyTest(unittest.TestCase):
    def test_cfg_04_source_tree_is_rejected_without_prefix_false_positive(self) -> None:
        policy = PathPolicy.production(
            source_root=Path(r"C:\repo\knowledge-flow"),
            system_temp_root=Path(r"C:\Temp"),
            resolver=_identity,
        )

        with self.assertRaises(PathPolicyError):
            policy.validate_capture_root(Path(r"C:\repo\knowledge-flow\capture-store"))

        sibling = Path(r"C:\repo\knowledge-flow-data\capture-store")
        self.assertEqual(policy.validate_capture_root(sibling), sibling)

    def test_cfg_05_temp_gbrain_and_kb_ancestors_are_rejected(self) -> None:
        kb_marker = Path(r"D:\Vault\kb.yaml")

        def marker_probe(path: Path) -> bool:
            return str(path).casefold() == str(kb_marker).casefold()

        policy = PathPolicy.production(
            source_root=Path(r"C:\repo\knowledge-flow"),
            system_temp_root=Path(r"C:\Temp"),
            gbrain_roots=(Path(r"E:\Workstation\code\_space\gbrain-master"),),
            resolver=_identity,
            marker_probe=marker_probe,
        )
        cases = (
            Path(r"C:\Temp\capture-store"),
            Path(r"E:\Workstation\code\_space\gbrain-master\data"),
            Path(r"D:\Vault\capture-store"),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(PathPolicyError):
                policy.validate_capture_root(candidate)

    def test_cfg_05_unreadable_kb_ancestor_check_fails_closed(self) -> None:
        def denied(_path: Path) -> bool:
            raise PermissionError

        policy = PathPolicy.production(
            source_root=Path(r"C:\repo\knowledge-flow"),
            system_temp_root=Path(r"C:\Temp"),
            resolver=_identity,
            marker_probe=denied,
        )

        with self.assertRaises(PathPolicyError):
            policy.validate_capture_root(Path(r"D:\Private\capture-store"))

    def test_cfg_06_relative_parent_unc_and_device_paths_are_rejected(self) -> None:
        cases = (
            "capture-store",
            r"C:relative\capture-store",
            r"C:\safe\..\capture-store",
            r"\\server\share\capture-store",
            r"\\?\C:\capture-store",
            r"\\.\C:\capture-store",
        )
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(PathPolicyError):
                normalize_windows_local_absolute_path(candidate)

    def test_cfg_06_test_policy_rejects_reparse_escape_and_sibling(self) -> None:
        owned = Path(r"C:\KnowledgeFlowTests\owned")
        linked = owned / "link" / "capture-store"

        def resolver(path: Path) -> Path:
            if str(path).casefold() == str(linked).casefold():
                return Path(r"D:\escaped\capture-store")
            return path

        policy = PathPolicy.test_owned(owned, resolver=resolver)

        with self.assertRaises(PathPolicyError):
            policy.validate_capture_root(linked)
        with self.assertRaises(PathPolicyError):
            policy.validate_capture_root(Path(r"C:\KnowledgeFlowTests\owned-sibling\store"))

        allowed = owned / "direct" / "capture-store"
        self.assertEqual(policy.validate_capture_root(allowed), allowed)


if __name__ == "__main__":
    unittest.main()
