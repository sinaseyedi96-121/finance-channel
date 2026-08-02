"""
Market-moving-politics source: general business RSS (Reuters Business, AP
Business). These carry a lot of noise, so they are staged with kind="rss" and
the classifier applies a STRICT filter downstream: an item survives only if it
plausibly moves a CORE/INDEX ticker or a macro series; general politics is
dropped. No filtering opinion is baked in here — this module only fetches.
"""

from __future__ import annotations

import config


def fetch() -> list[dict]:
    import feedparser

    items: list[dict] = []
    for name, url in config.RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[rss] {name} failed: {exc}")
            continue
        for entry in feed.entries[: config.RSS_MAX_ITEMS_PER_FEED]:
            items.append(
                {
                    "source": f"rss:{name}",
                    "id": entry.get("id") or entry.get("link", ""),
                    "ticker": None,
                    "headline": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "kind": "rss",
                }
            )
    return items
