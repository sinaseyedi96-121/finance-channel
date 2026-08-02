"""
Macro source: FRED (oil WTI/Brent + broad dollar index).

Uses the official FRED API when FRED_API_KEY is set; otherwise falls back to
the keyless fredgraph CSV endpoint (same trick as crypto-market-channel), so
this source works with zero secrets configured.

Returns one item per series carrying the latest value and 1-observation change,
as a compact macro-context block for synthesis grounding.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import os

import requests

import config


def _fetch_api(series_id: str, api_key: str) -> list[tuple[str, float]]:
    start = (dt.date.today() - dt.timedelta(days=config.FRED_LOOKBACK_DAYS)).isoformat()
    resp = requests.get(
        config.FRED_API_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=20,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    return [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (".", "", None)]


def _fetch_csv(series_id: str) -> list[tuple[str, float]]:
    resp = requests.get(config.FRED_CSV_URL, params={"id": series_id}, timeout=20)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    out: list[tuple[str, float]] = []
    for row in rows[1:]:  # skip header
        if len(row) < 2 or row[1] in (".", "", None):
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:
            continue
    # Keep only the recent tail so a "change" is a recent change.
    return out[-config.FRED_LOOKBACK_DAYS:]


def latest(series_id: str) -> float | None:
    """Latest observation of a FRED series (keyless CSV endpoint). None on failure.
    Used by the bubble index for GDP and the high-yield credit spread."""
    try:
        resp = requests.get(config.FRED_CSV_URL, params={"id": series_id}, timeout=20)
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)[1:]
        for date, value in reversed([(r[0], r[1]) for r in rows if len(r) >= 2]):
            if value not in (".", "", None):
                return float(value)
    except Exception as exc:  # noqa: BLE001
        print(f"[fred] latest({series_id}) failed: {exc}")
    return None


def fetch() -> list[dict]:
    api_key = os.environ.get("FRED_API_KEY")
    items: list[dict] = []
    for label, series_id in config.MACRO_SERIES.items():
        try:
            series = _fetch_api(series_id, api_key) if api_key else _fetch_csv(series_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[fred] {label} ({series_id}) failed: {exc}")
            continue
        if not series:
            continue
        latest_date, latest_val = series[-1]
        prev_val = series[-2][1] if len(series) >= 2 else latest_val
        pct = (latest_val / prev_val - 1) * 100 if prev_val else 0.0
        items.append(
            {
                "source": "fred",
                "id": f"{series_id}:{latest_date}",
                "ticker": None,
                "headline": f"{label} = {latest_val:g} ({pct:+.2f}%)",
                "summary": f"FRED {series_id} latest observation {latest_date}",
                "url": f"https://fred.stlouisfed.org/series/{series_id}",
                "published": latest_date,
                "series": series_id,
                "label": label,
                "value": latest_val,
                "pct_change": round(pct, 2),
                "kind": "macro",
            }
        )
    return items
