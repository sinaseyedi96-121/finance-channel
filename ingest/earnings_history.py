"""
Earnings beat/miss history (Finnhub /stock/earnings) — the last N quarters of
actual vs estimate EPS, for the earnings deep-dive. Requires FINNHUB_KEY.
"""

from __future__ import annotations

import os

import requests

import config


def fetch(ticker: str, quarters: int | None = None) -> list[dict]:
    token = os.environ.get("FINNHUB_KEY")
    if not token:
        return []
    quarters = quarters or config.EARNINGS_HISTORY_QUARTERS
    try:
        resp = requests.get(
            f"{config.FINNHUB_BASE_URL}/stock/earnings",
            params={"symbol": ticker, "limit": quarters, "token": token},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json() or []
    except Exception as exc:  # noqa: BLE001
        print(f"[earnings_history] {ticker} failed: {exc}")
        return []
    out = []
    for r in rows[:quarters]:
        actual, est = r.get("actual"), r.get("estimate")
        out.append({
            "period": r.get("period"),
            "actual_eps": actual,
            "estimate_eps": est,
            "surprise_pct": r.get("surprisePercent"),
            "beat": (actual is not None and est is not None and actual >= est),
        })
    return out
