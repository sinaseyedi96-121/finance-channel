from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_cap  # noqa: E402


def _ranked(order: list[str]) -> list[dict]:
    return [{"ticker": t, "market_cap": (len(order) - i) * 1e11 + 1e12}
            for i, t in enumerate(order)]


class CompareTest(unittest.TestCase):
    def test_first_run_is_initial(self):
        changes = market_cap.compare(None, ["AAPL", "MSFT"])
        self.assertTrue(changes["initial"])

    def test_unchanged_returns_none(self):
        self.assertIsNone(market_cap.compare(["AAPL", "MSFT"], ["AAPL", "MSFT"]))

    def test_swap_detected(self):
        changes = market_cap.compare(["AAPL", "NVDA", "MSFT"], ["NVDA", "AAPL", "MSFT"])
        self.assertIn(("NVDA", 2, 1), changes["moved"])
        self.assertIn(("AAPL", 1, 2), changes["moved"])

    def test_entry_and_exit(self):
        changes = market_cap.compare(["AAPL", "KO"], ["AAPL", "PLTR"])
        self.assertEqual(changes["entered"], ["PLTR"])
        self.assertEqual(changes["exited"], ["KO"])


class CaptionChartTest(unittest.TestCase):
    def test_caption_names_the_move(self):
        ranked = _ranked(["NVDA", "AAPL", "MSFT"])
        changes = market_cap.compare(["AAPL", "NVDA", "MSFT"], ["NVDA", "AAPL", "MSFT"])
        caption = market_cap.build_caption(ranked, changes)
        self.assertIn("NVDA #2→#1", caption)
        self.assertIn("🥇 NVDA", caption)

    def test_caption_numbers_come_from_data(self):
        ranked = _ranked(["NVDA", "AAPL", "MSFT"])
        caption = market_cap.build_caption(
            ranked, {"initial": True, "moved": [], "entered": [], "exited": []})
        self.assertIn("$1.30T", caption)          # top cap: 1e12 + 3e11

    def test_chart_writes_png(self):
        order = [f"T{i:02d}" for i in range(20)]
        ranked = _ranked(order)
        changes = market_cap.compare(order[1:] + [order[0]], order)
        path = market_cap.ranking_chart(ranked, changes)
        try:
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 1000)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
