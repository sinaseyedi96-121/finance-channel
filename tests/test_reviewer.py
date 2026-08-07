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


class CouncilJSONParsingTest(unittest.TestCase):
    def test_tagged_directives(self):
        out = reviewer._parse_council_json(
            '{"directives": [{"text": "Vary emoji", "targets": ["writer", "analyst"]}],'
            ' "code_changes": [], "compliance": []}')
        self.assertEqual(out["directives"],
                         [{"text": "Vary emoji", "targets": ["writer", "analyst"]}])

    def test_invalid_target_coerced_to_global(self):
        out = reviewer._parse_council_json(
            '{"directives": [{"text": "Fix it", "targets": ["market_cap", "bogus"]}]}')
        # market_cap/bogus aren't valid directive targets -> falls back to global.
        self.assertEqual(out["directives"][0]["targets"], ["global"])

    def test_string_directive_becomes_global(self):
        out = reviewer._parse_council_json('{"directives": ["Just a string"]}')
        self.assertEqual(out["directives"][0],
                         {"text": "Just a string", "targets": ["global"]})

    def test_code_changes_and_compliance(self):
        out = reviewer._parse_council_json(
            '{"directives": [], "code_changes": ["Fix market_cap wording"],'
            ' "compliance": [{"directive": "Vary emoji", "status": "RECURRED"},'
            ' {"directive": "Hedge more", "status": "weird"}]}')
        self.assertEqual(out["code_changes"], ["Fix market_cap wording"])
        # status is lowercased; an unrecognised status is normalised to "n-a".
        self.assertEqual(out["compliance"][0], {"directive": "Vary emoji", "status": "recurred"})
        self.assertEqual(out["compliance"][1]["status"], "n-a")

    def test_malformed_json_falls_back_to_global(self):
        out = reviewer._parse_council_json("no json here:\n- Do A\n- Do B")
        self.assertEqual([d["text"] for d in out["directives"]], ["Do A", "Do B"])
        self.assertTrue(all(d["targets"] == ["global"] for d in out["directives"]))

    def test_directives_capped(self):
        many = json.dumps({"directives": [{"text": f"D{i}", "targets": ["global"]}
                                           for i in range(20)]})
        self.assertEqual(len(reviewer._parse_council_json(many)["directives"]),
                         config.REVIEW_MAX_DIRECTIVES)


class NotesTargetTest(unittest.TestCase):
    """notes_block(target) must return only directives tagged for that target or
    tagged 'global' — this is what routes the right notes to each writer stage."""

    def setUp(self):
        self._orig = config.EDITORIAL_NOTES_FILE
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        config.EDITORIAL_NOTES_FILE = self.path
        with open(self.path, "w") as f:
            json.dump({"date": dt.date.today().isoformat(), "directives": [
                {"text": "Global note", "targets": ["global"]},
                {"text": "Writer note", "targets": ["writer"]},
                {"text": "Week note", "targets": ["week_ahead"]},
            ]}, f)

    def tearDown(self):
        config.EDITORIAL_NOTES_FILE = self._orig
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_writer_sees_global_and_writer(self):
        self.assertEqual(reviewer.load_notes("writer"), ["Global note", "Writer note"])

    def test_week_ahead_sees_global_and_week(self):
        self.assertEqual(reviewer.load_notes("week_ahead"), ["Global note", "Week note"])

    def test_scorecard_sees_only_global(self):
        self.assertEqual(reviewer.load_notes("scorecard"), ["Global note"])

    def test_no_target_returns_all(self):
        self.assertEqual(len(reviewer.load_notes()), 3)

    def test_notes_block_filters(self):
        block = reviewer.notes_block("writer")
        self.assertIn("Writer note", block)
        self.assertIn("Global note", block)
        self.assertNotIn("Week note", block)


if __name__ == "__main__":
    unittest.main()
