from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from knowledgeflow_capture.errors import FailureResult
from knowledgeflow_capture.inbox import InboxSession
from knowledgeflow_capture.paths import PathPolicy
from knowledgeflow_capture.store import init_capture_store


FOUR_MIB = 4 * 1024 * 1024


class P0CInboxIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("P0C inbox integration is Windows-first")
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.owned_root = Path(self._temporary.name).resolve()
        self.policy = PathPolicy.test_owned(self.owned_root)
        self.config_path = self.owned_root / "config" / "config.yaml"
        self.store_root = self.owned_root / "capture-store"

    def _initialize(self, *, maximum: int = FOUR_MIB + 1024) -> None:
        initialized = init_capture_store(
            config_path=self.config_path,
            capture_root=self.store_root,
            inline_text_threshold_bytes=min(FOUR_MIB, maximum),
            max_text_version_bytes=maximum,
            path_policy=self.policy,
        )
        self.assertNotIsInstance(initialized, FailureResult)

    def _session(self, *, page_size: int = 2) -> InboxSession:
        return InboxSession(
            config_path=self.config_path,
            path_policy=self.policy,
            page_size=page_size,
        )

    def test_empty_unicode_capture_list_get_append_and_restart_journey(self) -> None:
        self._initialize()
        session = self._session()
        self.assertEqual(session.first_page().page.items, ())

        first_text = "第一版\r\n知识🙂"
        saved = session.capture(first_text)
        self.assertTrue(saved.ok, saved.failure)
        capture_id = saved.receipt.capture_id
        self.assertEqual(saved.receipt.version, 1)

        for text in ("第二条", "第三条"):
            self.assertTrue(session.capture(text).ok)
        first_page = session.first_page().page
        second_page = session.next_page().page
        self.assertEqual(len(first_page.items), 2)
        self.assertTrue(first_page.has_next)
        self.assertEqual(len(second_page.items), 1)
        self.assertTrue(second_page.has_previous)

        read = session.open_capture(capture_id)
        self.assertTrue(read.ok, read.failure)
        self.assertEqual(read.document.text, first_text)
        self.assertEqual(read.document.routing_status, "unassigned")
        self.assertEqual(read.document.trust_status, "unreviewed-capture")

        second_text = first_text + "\r\n续写"
        appended = session.append(
            capture_id=capture_id,
            expected_current_version=read.document.current_version,
            text=second_text,
        )
        self.assertTrue(appended.ok, appended.failure)
        self.assertEqual(appended.receipt.version, 2)
        self.assertEqual(session.open_capture(capture_id).document.text, second_text)
        session.close()

        reopened = self._session()
        reopened_page = reopened.first_page()
        self.assertTrue(reopened_page.ok, reopened_page.failure)
        reopened_read = reopened.open_capture(capture_id)
        self.assertTrue(reopened_read.ok, reopened_read.failure)
        self.assertEqual(reopened_read.document.text, second_text)
        self.assertEqual(reopened_read.document.current_version, 2)

    def test_exact_four_mib_is_saved_and_one_byte_over_is_rejected(self) -> None:
        self._initialize(maximum=FOUR_MIB)
        session = self._session()
        boundary_text = "x" * FOUR_MIB

        saved = session.capture(boundary_text)
        self.assertTrue(saved.ok, saved.failure)
        read = session.open_capture(saved.receipt.capture_id)
        self.assertTrue(read.ok, read.failure)
        self.assertEqual(read.document.byte_size, FOUR_MIB)
        self.assertEqual(read.document.text, boundary_text)

        rejected = session.capture(boundary_text + "x")
        self.assertFalse(rejected.ok)
        self.assertEqual(rejected.failure.code, "text_too_large")
        self.assertEqual(rejected.failure.commit_state, "not-committed")

    def test_two_sessions_surface_real_compare_and_swap_version_conflict(self) -> None:
        self._initialize()
        first_session = self._session()
        saved = first_session.capture("v1")
        self.assertTrue(saved.ok, saved.failure)
        capture_id = saved.receipt.capture_id

        second_session = self._session()
        first_read = first_session.open_capture(capture_id)
        second_read = second_session.open_capture(capture_id)
        self.assertEqual(first_read.document.current_version, 1)
        self.assertEqual(second_read.document.current_version, 1)

        winner = first_session.append(
            capture_id=capture_id,
            expected_current_version=1,
            text="winner-v2",
        )
        loser = second_session.append(
            capture_id=capture_id,
            expected_current_version=1,
            text="loser-v2",
        )

        self.assertTrue(winner.ok, winner.failure)
        self.assertFalse(loser.ok)
        self.assertEqual(loser.failure.code, "version_conflict")
        self.assertEqual(loser.failure.commit_state, "not-committed")
        self.assertEqual(
            first_session.open_capture(capture_id).document.text,
            "winner-v2",
        )

    def test_missing_configuration_shows_guidance_with_zero_filesystem_writes(self) -> None:
        before = tuple(sorted(path.name for path in self.owned_root.iterdir()))
        outcome = self._session().first_page()
        after = tuple(sorted(path.name for path in self.owned_root.iterdir()))

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.failure.code, "config_not_found")
        self.assertEqual(before, after)
        self.assertFalse(self.config_path.exists())
        self.assertFalse(self.store_root.exists())


if __name__ == "__main__":
    unittest.main()
