from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import technicals  # noqa: E402


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": [1_000] * len(closes),
        },
        index=idx,
    )


class TechnicalsTest(unittest.TestCase):
    def test_rsi_all_gains_is_100(self):
        rising = list(range(1, 40))
        rsi = technicals.rsi(_frame(rising)["Close"])
        self.assertAlmostEqual(rsi.iloc[-1], 100.0, places=1)

    def test_rsi_within_bounds(self):
        rng = np.random.default_rng(0)
        walk = np.cumsum(rng.normal(0, 1, 300)) + 100
        rsi = technicals.rsi(pd.Series(walk)).dropna()
        self.assertTrue((rsi >= 0).all() and (rsi <= 100).all())

    def test_ema_tracks_constant_series(self):
        const = [50.0] * 60
        self.assertAlmostEqual(technicals.ema(_frame(const)["Close"], 20).iloc[-1], 50.0, places=6)

    def test_bollinger_ordering(self):
        rng = np.random.default_rng(1)
        closes = list(np.cumsum(rng.normal(0, 1, 100)) + 100)
        upper, middle, lower = technicals.bollinger(_frame(closes)["Close"])
        self.assertGreaterEqual(upper.iloc[-1], middle.iloc[-1])
        self.assertGreaterEqual(middle.iloc[-1], lower.iloc[-1])

    def test_summarize_only_returns_derived_numbers(self):
        closes = [100 + i for i in range(250)]
        summary = technicals.summarize("TEST", _frame(closes))
        self.assertTrue(summary["available"])
        self.assertEqual(summary["symbol"], "TEST")
        self.assertAlmostEqual(summary["last_price"], 349.0, places=2)
        self.assertIn(summary["rsi_state"], {"neutral", "overbought", "oversold"})
        self.assertIsNotNone(summary["ema200"])

    def test_summarize_handles_empty(self):
        summary = technicals.summarize("NONE", pd.DataFrame())
        self.assertFalse(summary["available"])


if __name__ == "__main__":
    unittest.main()
