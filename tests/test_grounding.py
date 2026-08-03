from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grounding  # noqa: E402

SOURCES = [
    {"headline": "Amazon beats with revenue of $170.0 billion, up 11%",
     "summary": "AWS grew 19% year over year."},
    {"last_price": 231.44, "rsi": 63.4, "pct_change_1d": -1.85,
     "support": 210.5, "resistance": 245.0,
     "risk_reward": {"reward_risk_to_resistance": 2.1},
     "trade_setup": {"stop": 206.29, "target": 245.0}},
    {"market_cap": 2_450_000_000_000, "forward_pe": 32.7, "profit_margin": 0.23},
]


class GroundingTest(unittest.TestCase):
    def flags(self, text: str) -> list:
        return grounding.verify(text, SOURCES)

    # ---- numbers that must PASS ----------------------------------------

    def test_exact_and_rounded_price(self):
        self.assertEqual(self.flags("Holding $231.44, support at 210.5"), [])
        self.assertEqual(self.flags("Holding near $231 with support ~211"), [])

    def test_percent_rounds_either_way(self):
        # 1.85 in the data may legitimately be quoted as 1.8 or 1.9.
        self.assertEqual(self.flags("down 1.9% on the day"), [])
        self.assertEqual(self.flags("down 1.8% on the day"), [])

    def test_magnitude_suffixes(self):
        self.assertEqual(self.flags("market cap $2.45T"), [])
        self.assertEqual(self.flags("cap now $2.5T after the move"), [])
        self.assertEqual(self.flags("revenue of $170B beat"), [])

    def test_ratio_vs_percent_units(self):
        # Data stores the margin as a 0.23 ratio; captions quote 23%.
        self.assertEqual(self.flags("margins at 23%"), [])

    def test_indicator_and_small_int_whitelist(self):
        self.assertEqual(
            self.flags("RSI 14 crossed 70, EMA 20/50/200 stack, conviction 8/10, 52-week high"),
            [])

    def test_number_inside_news_text(self):
        self.assertEqual(self.flags("AWS growth of 19% does the lifting"), [])

    # ---- numbers that must be FLAGGED ----------------------------------

    def test_invented_percent_flagged(self):
        flagged = self.flags("revenue grew 47.3% this quarter")
        self.assertEqual(len(flagged), 1)
        self.assertIn("47.3", flagged[0])

    def test_invented_big_figure_flagged(self):
        flagged = self.flags("a $999B quarter")
        self.assertTrue(any("999" in f for f in flagged))

    def test_months_m_is_not_million(self):
        # "6 months" must not read as 6 million (small-int whitelist covers 6,
        # but only because the m was not consumed as a suffix).
        value, decimals = grounding._parse(next(grounding._NUMBER_RE.finditer("6 months")))
        self.assertEqual(value, 6.0)

    def test_disabled_gate_passes_everything(self):
        import config
        config.GROUNDING_ENABLED = False
        try:
            self.assertEqual(self.flags("made-up 47.3% and $999B"), [])
        finally:
            config.GROUNDING_ENABLED = True

    def test_retry_feedback_names_figures(self):
        note = grounding.retry_feedback(["47.3", "$999B"])
        self.assertIn("47.3", note)
        self.assertIn("$999B", note)


if __name__ == "__main__":
    unittest.main()
