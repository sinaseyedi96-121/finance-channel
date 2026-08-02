from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chart_generator  # noqa: E402
import technicals  # noqa: E402


def _ohlcv(n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = np.cumsum(rng.normal(0, 1, n)) + 200
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    high = close + np.abs(rng.normal(0, 1, n))
    low = close - np.abs(rng.normal(0, 1, n))
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close,
         "Volume": rng.integers(1e6, 5e6, n)},
        index=idx,
    )


class ChartTest(unittest.TestCase):
    def test_enrich_adds_columns(self):
        enriched = technicals.enrich(_ohlcv())
        for col in ("ema_fast", "ema_slow", "ema_long", "rsi", "bb_upper", "atr"):
            self.assertIn(col, enriched.columns)

    def test_find_key_levels(self):
        levels = technicals.find_key_levels(technicals.enrich(_ohlcv()))
        self.assertLess(levels["support"], levels["resistance"])

    def test_generate_chart_writes_png(self):
        enriched = technicals.enrich(_ohlcv())
        levels = technicals.find_key_levels(enriched)
        path = chart_generator.generate_chart(enriched, "TEST", levels)
        try:
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 1000)  # a real image, not empty
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
