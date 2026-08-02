"""
Company news source: Finnhub free tier.

Endpoints used:
  /company-news   — headline stream per ticker over a date window
  /news-sentiment — aggregate sentiment score per ticker (attached as context)

Requires FINNHUB_KEY in env. If unset, returns [] (logged) so the pipeline
degrades gracefully instead of crashing.
"""

from __future__ import annotations

import datetime as dt
import os

import requests

import config


def _get(path: str, params: dict, token: str) -> object:
    params = {**params, "token": token}
    resp = requests.get(f"{config.FINNHUB_BASE_URL}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch(tickers: list[str] | None = None) -> list[dict]:
    token = os.environ.get("FINNHUB_KEY")
    if not token:
        print("[finnhub] FINNHUB_KEY unset — skipping company news")
        return []

    tickers = tickers or config.CORE_TICKERS
    today = dt.date.today()
    since = today - dt.timedelta(days=config.FINNHUB_NEWS_LOOKBACK_DAYS)

    items: list[dict] = []
    for ticker in tickers:
        try:
            news = _get(
                "/company-news",
                {"symbol": ticker, "from": since.isoformat(), "to": today.isoformat()},
                token,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[finnhub] {ticker} company-news failed: {exc}")
            continue

        for article in (news or [])[: config.FINNHUB_MAX_ITEMS_PER_TICKER]:
            items.append(
                {
                    "source": "finnhub",
                    "id": str(article.get("id") or article.get("url")),
                    "ticker": ticker,
                    "headline": article.get("headline", ""),
                    "summary": article.get("summary", ""),
                    "url": article.get("url", ""),
                    "published": _iso(article.get("datetime")),
                    "publisher": article.get("source", ""),
                    "kind": "company-news",
                }
            )
    return items


def _iso(epoch: object) -> str:
    try:
        return dt.datetime.utcfromtimestamp(int(epoch)).isoformat() + "Z"
    except (TypeError, ValueError):
        return ""
