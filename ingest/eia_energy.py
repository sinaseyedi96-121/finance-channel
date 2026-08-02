"""
Energy source: EIA API — finer-grained energy data, used as a fallback / cross-
check for oil when FRED is thin. Requires EIA_API_KEY; returns [] (logged) if
unset so it is purely additive.
"""

from __future__ import annotations

import os

import requests

import config


def fetch() -> list[dict]:
    api_key = os.environ.get("EIA_API_KEY")
    if not api_key:
        print("[eia] EIA_API_KEY unset — skipping (FRED covers oil)")
        return []

    series = config.EIA_WTI_SERIES
    try:
        resp = requests.get(
            f"{config.EIA_BASE_URL}/seriesid/{series}",
            params={"api_key": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
    except Exception as exc:  # noqa: BLE001
        print(f"[eia] {series} failed: {exc}")
        return []

    if not data:
        return []
    latest = data[0]
    period = latest.get("period", "")
    value = latest.get("value")
    return [
        {
            "source": "eia",
            "id": f"{series}:{period}",
            "ticker": None,
            "headline": f"EIA WTI spot = {value} ({period})",
            "summary": f"EIA series {series}",
            "url": "https://www.eia.gov/petroleum/",
            "published": period,
            "series": series,
            "value": value,
            "kind": "macro",
        }
    ]
