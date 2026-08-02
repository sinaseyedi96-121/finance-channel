"""
Filings source: SEC EDGAR. Free, no key. Requires a descriptive User-Agent.

Two-step:
  1. ticker -> CIK via the public company_tickers.json map (cached in-process).
  2. recent filings via the per-company submissions feed, filtered to the forms
     of interest (10-Q / 10-K / 8-K) within the lookback window.

New-vs-seen dedup (by accession number) is handled by the caller through
state_manager.filing_seen / mark_filing_seen.
"""

from __future__ import annotations

import datetime as dt
import os

import requests

import config

_CIK_CACHE: dict[str, str] | None = None


def _headers() -> dict:
    ua = os.environ.get("SEC_USER_AGENT", config.SEC_USER_AGENT_DEFAULT)
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _ticker_to_cik() -> dict[str, str]:
    """Load and cache the ticker -> zero-padded-CIK map."""
    global _CIK_CACHE
    if _CIK_CACHE is not None:
        return _CIK_CACHE
    try:
        resp = requests.get(config.SEC_COMPANY_TICKERS_URL, headers=_headers(), timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        # File is a dict of {"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}
        _CIK_CACHE = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in raw.values()
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[sec] could not load ticker->CIK map: {exc}")
        _CIK_CACHE = {}
    return _CIK_CACHE


def fetch(tickers: list[str] | None = None) -> list[dict]:
    tickers = tickers or config.CORE_TICKERS
    cik_map = _ticker_to_cik()
    cutoff = dt.date.today() - dt.timedelta(days=config.SEC_LOOKBACK_DAYS)

    items: list[dict] = []
    for ticker in tickers:
        cik = cik_map.get(ticker.upper())
        if not cik:
            continue
        try:
            url = config.SEC_SUBMISSIONS_URL.format(cik=cik)
            resp = requests.get(url, headers=_headers(), timeout=20)
            resp.raise_for_status()
            recent = resp.json().get("filings", {}).get("recent", {})
        except Exception as exc:  # noqa: BLE001
            print(f"[sec] {ticker} submissions failed: {exc}")
            continue

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        for i, form in enumerate(forms):
            if form not in config.SEC_FORMS_OF_INTEREST:
                continue
            filing_date = dates[i] if i < len(dates) else ""
            try:
                if filing_date and dt.date.fromisoformat(filing_date) < cutoff:
                    continue
            except ValueError:
                pass
            accession = accessions[i] if i < len(accessions) else ""
            doc = docs[i] if i < len(docs) else ""
            accession_nodash = accession.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{doc}"
                if doc else ""
            )
            items.append(
                {
                    "source": "sec",
                    "id": accession,
                    "ticker": ticker,
                    "headline": f"{ticker} filed {form}",
                    "summary": f"{form} filed {filing_date}",
                    "url": filing_url,
                    "published": filing_date,
                    "form": form,
                    "accession": accession,
                    "kind": "filing",
                }
            )
    return items
