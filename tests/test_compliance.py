from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance  # noqa: E402
import config  # noqa: E402


class ComplianceTest(unittest.TestCase):
    def test_clean_text_passes(self):
        text = "NVDA reported revenue growth. The stock closed near its 50-day average."
        self.assertTrue(compliance.is_compliant(text))
        self.assertEqual(compliance.lint(text), [])

    def test_buy_sell_flagged(self):
        for bad in ["You should buy NVDA", "time to sell", "strong buy rating"]:
            self.assertFalse(compliance.is_compliant(bad), bad)

    def test_stop_and_target_flagged(self):
        self.assertFalse(compliance.is_compliant("set a stop-loss at 100"))
        self.assertFalse(compliance.is_compliant("price target of 200"))
        self.assertFalse(compliance.is_compliant("entry price 150"))

    def test_benign_long_short_not_over_flagged(self):
        # "long-term" and "short interest" are legitimate descriptive usage.
        self.assertTrue(compliance.is_compliant("a long-term uptrend"))
        self.assertTrue(compliance.is_compliant("short interest rose this week"))

    def test_format_post_appends_footer_and_escapes(self):
        post = compliance.format_post("NVDA — 2026-08-02", "Revenue rose. Facts only.")
        self.assertIn("<b>", post)
        self.assertIn(config.COMPLIANCE_DISCLAIMER.strip().split("\n")[0][:20], post)

    def test_format_post_rejects_violation(self):
        with self.assertRaises(ValueError):
            compliance.format_post("H", "You should buy this now")

    def test_html_escape_in_body(self):
        post = compliance.format_post("H", "earnings <up> & steady")
        self.assertIn("&lt;up&gt;", post)
        self.assertIn("&amp;", post)


if __name__ == "__main__":
    unittest.main()
