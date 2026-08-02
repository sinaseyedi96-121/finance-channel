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

    def _inputs(self, hot: bool):
        if hot:
            return {
                "valuations": [{"forward_pe": 45, "peg": 3.2}, {"forward_pe": 40, "peg": 2.8}],
                "tech_map": {"X": self._tech(80, 130, 100, "up"), "Y": self._tech(78, 140, 100, "up")},
                "concentration": {"spy_ret": 18, "rsp_ret": 2},
                "capex_gdp_pct": 2.4,
                "hy_spread_pct": 2.7,
            }
        return {
            "valuations": [{"forward_pe": 15, "peg": 1.0}, {"forward_pe": 16, "peg": 1.1}],
            "tech_map": {"X": self._tech(35, 95, 100, "down"), "Y": self._tech(30, 90, 100, "down")},
            "concentration": {"spy_ret": -2, "rsp_ret": 1},
            "capex_gdp_pct": 0.5,
            "hy_spread_pct": 7.5,
        }

    def test_frothy_scores_higher_than_cool(self):
        self.assertGreater(bubble_index.compute_index(self._inputs(True))["score"],
                           bubble_index.compute_index(self._inputs(False))["score"])

    def test_index_has_pillars_and_signal(self):
        idx = bubble_index.compute_index(self._inputs(True))
        self.assertIn("label", idx)
        self.assertGreaterEqual(len(idx["pillars"]), 4)
        self.assertIn("red_pillars", idx)
        self.assertIsInstance(idx["bubble_signal"], bool)

    def test_missing_pillars_renormalize(self):
        # Only exuberance available -> still returns a valid index.
        idx = bubble_index.compute_index({"tech_map": {"X": self._tech(60, 110, 100, "up")}})
        self.assertIn("score", idx)
        self.assertEqual([p["name"] for p in idx["pillars"]], ["exuberance"])

    def test_interp_and_credit_inverse(self):
        self.assertEqual(bubble_index._interp(50, [0, 100], [0, 100]), 50)
        # tighter spread -> higher froth
        tight = bubble_index._credit_pillar(2.6)["score"]
        wide = bubble_index._credit_pillar(8.0)["score"]
        self.assertGreater(tight, wide)


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
