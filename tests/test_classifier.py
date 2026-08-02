from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classifier  # noqa: E402
import config  # noqa: E402


class ClassifierParseTest(unittest.TestCase):
    def test_parse_plain_json(self):
        out = classifier.parse_classification(
            '{"tickers": ["NVDA"], "category": "earnings", "relevance": 5, "reason": "beat"}'
        )
        self.assertEqual(out["tickers"], ["NVDA"])
        self.assertEqual(out["category"], "earnings")
        self.assertEqual(out["relevance"], 5)

    def test_parse_fenced_json(self):
        out = classifier.parse_classification(
            '```json\n{"tickers": [], "category": "macro", "relevance": 2, "reason": "oil"}\n```'
        )
        self.assertEqual(out["category"], "macro")
        self.assertEqual(out["relevance"], 2)

    def test_parse_garbage_is_safe(self):
        out = classifier.parse_classification("I could not decide.")
        self.assertEqual(out["relevance"], 0)
        self.assertEqual(out["tickers"], [])

    def test_relevance_gate(self):
        self.assertTrue(classifier.passes_relevance({"relevance": config.RELEVANCE_MIN_SCORE}))
        self.assertFalse(classifier.passes_relevance({"relevance": config.RELEVANCE_MIN_SCORE - 1}))

    def test_classify_items_filters_and_sorts(self):
        # Monkeypatch the single LLM entrypoint — no network needed.
        replies = iter(
            [
                '{"tickers":["NVDA"],"category":"earnings","relevance":5,"reason":"x"}',
                '{"tickers":[],"category":"politics","relevance":0,"reason":"noise"}',
                '{"tickers":["PLTR"],"category":"rating","relevance":4,"reason":"y"}',
            ]
        )
        classifier.chat = lambda *a, **k: next(replies)  # type: ignore
        items = [
            {"id": "1", "headline": "NVDA earnings"},
            {"id": "2", "headline": "random politics"},
            {"id": "3", "headline": "PLTR upgrade"},
        ]
        out = classifier.classify_items(client=None, items=items)
        self.assertEqual([i["id"] for i in out], ["1", "3"])  # noise dropped, sorted by relevance
        self.assertEqual(out[0]["classification"]["relevance"], 5)


if __name__ == "__main__":
    unittest.main()
