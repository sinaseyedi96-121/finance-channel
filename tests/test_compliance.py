from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance  # noqa: E402
import config  # noqa: E402


class FormatTest(unittest.TestCase):
    def test_lint_off_by_default(self):
        # Channel runs with LINT_ENABLED False — nothing is rejected.
        self.assertFalse(config.LINT_ENABLED)
        self.assertTrue(compliance.is_compliant("you should buy this now"))

    def test_scan_still_detects_when_forced(self):
        # The underlying scanner works regardless of the toggle.
        self.assertTrue(compliance.lint("time to buy", enabled=True))
        self.assertEqual(compliance.lint("time to buy", enabled=False), [])

    def test_caption_no_disclaimer_by_default(self):
        self.assertFalse(config.DISCLAIMER_ENABLED)
        cap = compliance.format_caption("🚀 NVDA rips +5% today")
        self.assertNotIn("not financial advice", cap.lower())
        self.assertIn("🚀", cap)

    def test_caption_capped_at_limit(self):
        cap = compliance.format_caption("x" * 5000)
        self.assertLessEqual(len(cap), config.TELEGRAM_CAPTION_LIMIT)

    def test_caption_strips_markdown_bold(self):
        cap = compliance.format_caption("🔥 **MSFT Surges** and __holds__ ## Header")
        self.assertNotIn("**", cap)
        self.assertNotIn("__", cap)
        self.assertIn("MSFT Surges", cap)
        self.assertIn("Header", cap)

    def test_disclaimer_appended_when_enabled(self):
        orig = config.DISCLAIMER_ENABLED
        config.DISCLAIMER_ENABLED = True
        try:
            cap = compliance.format_caption("NVDA update")
            self.assertIn("not financial advice", cap.lower())
        finally:
            config.DISCLAIMER_ENABLED = orig

    def test_format_post_escapes_html(self):
        post = compliance.format_post("Header", "earnings <up> & steady")
        self.assertIn("&lt;up&gt;", post)
        self.assertIn("&amp;", post)
        self.assertIn("<b>", post)


if __name__ == "__main__":
    unittest.main()
