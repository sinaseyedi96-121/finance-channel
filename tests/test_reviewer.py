from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import reviewer  # noqa: E402


def _entry(**kw) -> dict:
    base = {"ts": "2026-08-03T15:00:00Z", "mode": "auto", "ticker": "NVDA",
            "category": "earnings", "caption": "🚀 headline\n🎯 Verdict: Bullish"}
    base.update(kw)
    return base


class MechanicalFindingsTest(unittest.TestCase):
    def test_same_ticker_twice_a_day(self):
        findings = reviewer.mechanical_findings(
            [_entry(ticker="AMZN"), _entry(ticker="AMZN", ts="2026-08-03T15:31:00Z")])
        self.assertTrue(any("AMZN" in f and "2 times" in f for f in findings))

    def test_weak_level_flagged(self):
        findings = reviewer.mechanical_findings(
            [_entry(chart={"resistance_touches": 1, "support_touches": 4})])
        self.assertTrue(any("resistance" in f and "weak" in f for f in findings))
        self.assertFalse(any("support line" in f for f in findings))

    def test_grounding_flags_surfaced(self):
        findings = reviewer.mechanical_findings([_entry(grounding_flags=["47.3%"])])
        self.assertTrue(any("ungrounded" in f for f in findings))

    def test_missing_verdict(self):
        findings = reviewer.mechanical_findings([_entry(caption="🚀 just a headline")])
        self.assertTrue(any("Verdict" in f for f in findings))

    def test_clean_posts_produce_nothing(self):
        findings = reviewer.mechanical_findings(
            [_entry(), _entry(ticker="AMD", ts="2026-08-03T16:00:00Z", category="rating")])
        self.assertEqual(findings, [])


class DirectiveParsingTest(unittest.TestCase):
    def test_strict_json(self):
        out = reviewer._parse_directives('{"directives": ["Do A", "Do B"]}')
        self.assertEqual(out, ["Do A", "Do B"])

    def test_fenced_json(self):
        out = reviewer._parse_directives('```json\n{"directives": ["Do A"]}\n```')
        self.assertEqual(out, ["Do A"])

    def test_bullet_fallback(self):
        out = reviewer._parse_directives("Here you go:\n- Do A\n- Do B")
        self.assertEqual(out, ["Do A", "Do B"])

    def test_capped_at_max(self):
        many = json.dumps({"directives": [f"D{i}" for i in range(20)]})
        self.assertEqual(len(reviewer._parse_directives(many)), config.REVIEW_MAX_DIRECTIVES)


class NotesTest(unittest.TestCase):
    def setUp(self):
        self._orig = config.EDITORIAL_NOTES_FILE
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)
        config.EDITORIAL_NOTES_FILE = self.path

    def tearDown(self):
        config.EDITORIAL_NOTES_FILE = self._orig
        if os.path.exists(self.path):
            os.remove(self.path)

    def _write(self, date: str, directives: list) -> None:
        with open(self.path, "w") as f:
            json.dump({"date": date, "directives": directives}, f)

    def test_missing_file_is_empty(self):
        self.assertEqual(reviewer.load_notes(), [])
        self.assertEqual(reviewer.notes_block(), "")

    def test_fresh_notes_load(self):
        self._write(dt.date.today().isoformat(), ["Vary the emoji"])
        self.assertEqual(reviewer.load_notes(), ["Vary the emoji"])
        self.assertIn("Vary the emoji", reviewer.notes_block())

    def test_stale_notes_ignored(self):
        old = (dt.date.today() - dt.timedelta(days=config.REVIEW_NOTES_MAX_AGE_DAYS + 1))
        self._write(old.isoformat(), ["Old advice"])
        self.assertEqual(reviewer.load_notes(), [])


if __name__ == "__main__":
    unittest.main()
