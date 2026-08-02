"""
Forward earnings calendar (Finnhub free tier /calendar/earnings) — feeds the
weekly week-ahead post with "who reports this week". Requires FINNHUB_KEY; returns
[] (logged) if unset.
"""

from __future__ import annotations

import datetime as dt
import os

import requests

import config


def fetch(tickers: list | None = None, days: int | None = None) -> list[dict]:
    token = os.environ.get("FINNHUB_KEY")
    if not token:
        print("[earnings] FINNHUB_KEY unset — skipping earnings calendar")
        return []

    tickers = set(tickers or config.CORE_TICKERS)
    days = days or config.WEEK_AHEAD_EARNINGS_DAYS
    today = dt.date.today()
    to = today + dt.timedelta(days=days)
    try:
        resp = requests.get(
            f"{config.FINNHUB_BASE_URL}/calendar/earnings",
            params={"from": today.isoformat(), "to": to.isoformat(), "token": token},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json().get("earningsCalendar", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[earnings] calendar failed: {exc}")
        return []

    out = []
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if sym not in tickers:
            continue
        out.append(
            {
                "ticker": sym,
                "date": row.get("date"),
                "hour": row.get("hour"),          # bmo / amc / dmh
                "eps_estimate": row.get("epsEstimate"),
                "revenue_estimate": row.get("revenueEstimate"),
            }
        )
    out.sort(key=lambda r: r.get("date") or "")
    return out
