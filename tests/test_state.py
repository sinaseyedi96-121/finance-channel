from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import state_manager as state  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = config.STATE_FILE
        config.STATE_FILE = os.path.join(self.tmp.name, "post_history.json")

    def tearDown(self):
        config.STATE_FILE = self._orig
        self.tmp.cleanup()

    def test_dedup_roundtrip(self):
        s = state.load_state()
        item = {"source": "finnhub", "id": "abc"}
        self.assertFalse(state.already_posted(s, item))
        state.mark_posted(s, item)
        self.assertTrue(state.already_posted(s, item))
        state.save_state(s)
        self.assertTrue(state.already_posted(state.load_state(), item))

    def test_filing_tracking(self):
        s = {}
        self.assertFalse(state.filing_seen(s, "NVDA", "0001-23"))
        state.mark_filing_seen(s, "NVDA", "0001-23")
        self.assertTrue(state.filing_seen(s, "NVDA", "0001-23"))

    def test_posted_ids_capped(self):
        s = {}
        for i in range(5200):
            state.mark_posted(s, {"source": "x", "id": str(i)})
        self.assertLessEqual(len(s["posted_ids"]), 5000)
        # Most recent survive.
        self.assertTrue(state.already_posted(s, {"source": "x", "id": "5199"}))

    def test_discovery_date(self):
        s = {}
        self.assertIsNone(state.last_discovery_date(s))
        state.set_last_discovery_date(s, "2026-08-02")
        self.assertEqual(state.last_discovery_date(s), "2026-08-02")


if __name__ == "__main__":
    unittest.main()
