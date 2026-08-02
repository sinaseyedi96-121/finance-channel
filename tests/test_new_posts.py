from __future__ import annotations

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bubble_index  # noqa: E402
import head_to_head  # noqa: E402
import scorecard  # noqa: E402
import technicals  # noqa: E402


class ScorecardTest(unittest.TestCase):
    def test_parse_verdict(self):
        cap = "🎯 Verdict: Bullish (8/10). Key level $213. 🫧 crash risk low."
        lean, conv = scorecard.parse_verdict(cap)
        self.assertEqual(lean, "bullish")
        self.assertEqual(conv, 8)

    def test_parse_verdict_missing(self):
        lean, conv = scorecard.parse_verdict("no verdict here")
        self.assertIsNone(lean)
        self.assertIsNone(conv)

    def test_correct_direction(self):
        self.assertTrue(scorecard._correct("bullish", 5))
        self.assertFalse(scorecard._correct("bullish", -5))
        self.assertTrue(scorecard._correct("bearish", -5))
        self.assertTrue(scorecard._correct("neutral", 1))

    def test_grade_computes_hit_rate(self):
        today = dt.date(2026, 8, 2)
        old = (today - dt.timedelta(days=10)).isoformat()
        calls = [
            {"ticker": "A", "lean": "bullish", "price": 100, "date": old},   # now 110 -> correct
            {"ticker": "B", "lean": "bearish", "price": 100, "date": old},   # now 110 -> wrong
        ]
        stats = scorecard.grade(calls, {"A": 110, "B": 110}, today)
        self.assertEqual(stats["n"], 2)
        self.assertEqual(stats["hit_rate_pct"], 50.0)

    def test_grade_skips_immature(self):
        today = dt.date(2026, 8, 2)
        calls = [{"ticker": "A", "lean": "bullish", "price": 100, "date": today.isoformat()}]
        self.assertEqual(scorecard.grade(calls, {"A": 110}, today)["n"], 0)


class HeadToHeadTest(unittest.TestCase):
    def test_pick_pair_is_stable_and_valid(self):
        pair = head_to_head.pick_pair(dt.date(2026, 8, 6))
        self.assertIn(pair, head_to_head.config.HEAD_TO_HEAD_PAIRS)
        # same week -> same pair
        self.assertEqual(pair, head_to_head.pick_pair(dt.date(2026, 8, 6)))


class BubbleIndexTest(unittest.TestCase):
    def _tech(self, rsi, price, ema200, weekly):
        return {"available": True, "rsi": rsi, "last_price": price, "ema200": ema200,
                "bb_upper": price * 1.1, "bb_lower": price * 0.9,
                "trend_multi_timeframe": {"weekly": weekly}}

    def test_frothy_scores_higher_than_cool(self):
        hot = {"X": self._tech(80, 130, 100, "up"), "Y": self._tech(78, 140, 100, "up")}
        cool = {"X": self._tech(35, 95, 100, "down"), "Y": self._tech(30, 90, 100, "down")}
        self.assertGreater(bubble_index.compute_index(hot)["score"],
                           bubble_index.compute_index(cool)["score"])

    def test_index_has_label_and_components(self):
        idx = bubble_index.compute_index({"X": self._tech(60, 110, 100, "up")})
        self.assertIn("label", idx)
        self.assertIn("avg_rsi", idx["components"])


class TradeSetupTest(unittest.TestCase):
    def test_setup_emitted_when_clean(self):
        s = technicals.trade_setup(100, 95, 115, {"weekly": "up", "monthly": "up"})
        self.assertTrue(s)
        self.assertEqual(s["target"], 115)
        self.assertGreaterEqual(s["reward_risk"], 1.5)

    def test_setup_muddy_returns_empty(self):
        # reward:risk below 1.5 -> no setup
        self.assertEqual(technicals.trade_setup(100, 95, 101, {"weekly": "up"}), {})
        # both HTFs down -> no setup
        self.assertEqual(technicals.trade_setup(100, 90, 130, {"weekly": "down", "monthly": "down"}), {})


if __name__ == "__main__":
    unittest.main()
