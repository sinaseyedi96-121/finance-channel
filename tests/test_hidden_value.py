from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hidden_value  # noqa: E402
from ingest import fundamentals  # noqa: E402


class HiddenValueTest(unittest.TestCase):
    def test_upside_calc(self):
        self.assertEqual(fundamentals._upside(100, 150), 50.0)
        self.assertIsNone(fundamentals._upside(None, 150))
        self.assertIsNone(fundamentals._upside(0, 150))

    def test_value_score_rewards_upside_and_growth(self):
        low = {"upside_to_target_pct": 10, "revenue_growth_pct": 0}
        high = {"upside_to_target_pct": 80, "revenue_growth_pct": 40}
        self.assertGreater(hidden_value.value_score(high), hidden_value.value_score(low))

    def test_value_score_handles_missing(self):
        # Missing fields must not raise, and count as zero.
        self.assertEqual(hidden_value.value_score({}), 0.0)

    def test_rank_orders_by_score(self):
        rows = [
            {"ticker": "A", "upside_to_target_pct": 5, "revenue_growth_pct": 0},
            {"ticker": "B", "upside_to_target_pct": 90, "revenue_growth_pct": 30},
            {"ticker": "C", "upside_to_target_pct": 40, "revenue_growth_pct": 10},
        ]
        self.assertEqual([r["ticker"] for r in hidden_value.rank(rows)], ["B", "C", "A"])

    def test_context_includes_sector_thesis(self):
        rows = [{"ticker": "MP", "upside_to_target_pct": 80, "revenue_growth_pct": 100}]
        ctx = hidden_value._context(rows, {"MP": "rare_earth_and_critical_minerals"})
        self.assertIn("Magnets", ctx)          # thesis text got attached
        self.assertIn("value_score", ctx)


if __name__ == "__main__":
    unittest.main()
