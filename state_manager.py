"""
Tiny JSON-file state store, committed back to the repo after each run — same
persistence pattern as the crypto-market-channel / ai_news pipelines (GitHub
Actions runners are ephemeral, so these files are the only memory between runs).

State shape (post_history.json):
{
  "posted_ids": ["<source>:<id>", ...],   # dedup keys for published items
  "seen_filings": {"NVDA": ["<accession>", ...]},
  "last_discovery": "2026-08-02"
}
"""

from __future__ import annotations

import json
import os

import config


# ---- generic load/save ------------------------------------------------

def load_state() -> dict:
    if not os.path.exists(config.STATE_FILE):
        return {}
    with open(config.STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


# ---- published-item dedup --------------------------------------------

def dedup_key(item: dict) -> str:
    """Stable per-item key used for dedup across runs."""
    return f"{item.get('source', '?')}:{item.get('id', '')}"


def already_posted(state: dict, item: dict) -> bool:
    return dedup_key(item) in set(state.get("posted_ids", []))


def mark_posted(state: dict, item: dict) -> None:
    posted = state.setdefault("posted_ids", [])
    key = dedup_key(item)
    if key not in posted:
        posted.append(key)
    # Keep the list from growing unbounded; the tail is the recent history
    # that actually matters for dedup.
    if len(posted) > 5000:
        del posted[:-5000]


# ---- SEC filing tracking ---------------------------------------------

def filing_seen(state: dict, ticker: str, accession: str) -> bool:
    return accession in set(state.get("seen_filings", {}).get(ticker, []))


def mark_filing_seen(state: dict, ticker: str, accession: str) -> None:
    seen = state.setdefault("seen_filings", {}).setdefault(ticker, [])
    if accession not in seen:
        seen.append(accession)
    if len(seen) > 100:
        del seen[:-100]


# ---- discovery cadence ------------------------------------------------

def last_discovery_date(state: dict) -> str | None:
    return state.get("last_discovery")


def set_last_discovery_date(state: dict, date_iso: str) -> None:
    state["last_discovery"] = date_iso


def get_marker(state: dict, key: str) -> str | None:
    """Generic once-per-day marker (e.g. 'last_week_ahead')."""
    return state.get(key)


def set_marker(state: dict, key: str, date_iso: str) -> None:
    state[key] = date_iso


# ---- call log (for the conviction scorecard) -------------------------

def add_call(state: dict, call: dict) -> None:
    """Record a published call (ticker, lean, conviction, price, levels) so the
    weekly scorecard can grade how it played out."""
    calls = state.setdefault("calls", [])
    calls.append(call)
    if len(calls) > 500:
        del calls[:-500]


def get_calls(state: dict) -> list:
    return state.get("calls", [])


# ---- published-post log ----------------------------------------------

def tickers_posted_today(today_iso: str | None = None) -> dict:
    """Ticker -> count of published (non-dry-run) posts logged for the given
    UTC day, across every run and mode. Drives the daily diversity gate."""
    import datetime as dt
    day = today_iso or dt.datetime.utcnow().date().isoformat()
    counts: dict[str, int] = {}
    if not os.path.exists(config.POSTS_LOG_FILE):
        return counts
    with open(config.POSTS_LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("dry_run") or not entry.get("ticker"):
                continue
            if str(entry.get("ts", "")).startswith(day):
                counts[entry["ticker"]] = counts.get(entry["ticker"], 0) + 1
    return counts


def append_post_log(entry: dict) -> None:
    """Append one JSONL record. Best-effort: never break a run over logging."""
    try:
        with open(config.POSTS_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"Could not append to posts log: {exc}")


# ---- staging ----------------------------------------------------------

def save_staging(items: list[dict]) -> None:
    with open(config.STAGING_FILE, "w") as f:
        json.dump(items, f, indent=2)


def load_staging() -> list[dict]:
    if not os.path.exists(config.STAGING_FILE):
        return []
    with open(config.STAGING_FILE, "r") as f:
        return json.load(f)
