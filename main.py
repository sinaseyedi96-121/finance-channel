"""
Orchestrator: ingest -> classify -> technicals -> synthesize -> compliance ->
publish, with a separate weekly discovery mode. Scheduled by GitHub Actions;
state (post_history.json) is committed back after each run.

Usage:
    python main.py --mode auto        # standard news cycle (default)
    python main.py --mode discovery   # weekly discovery layer
    python main.py --dry-run          # run everything, print instead of posting
    python main.py --force            # ignore the discovery weekday gate

If TELEGRAM_TOKEN / TELEGRAM_CHANNEL are unset (channel not wired up yet), the
run auto-switches to dry-run so it never crashes on a missing secret.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os

from dotenv import load_dotenv

import compliance
import config
import discovery as discovery_stage
import state_manager as state
import synthesizer
import technicals
from ingest import business_rss, eia_energy, finnhub_news, fred_macro, prices, sec_edgar
from llm_client import get_client

load_dotenv()


# ---- ingest -----------------------------------------------------------

def ingest_all() -> list[dict]:
    """Pull raw items from every news/filing/macro source. Prices are fetched
    separately (they feed technicals, not the news stream)."""
    items: list[dict] = []
    items += finnhub_news.fetch()
    items += sec_edgar.fetch()
    items += fred_macro.fetch()
    items += eia_energy.fetch()
    items += business_rss.fetch()
    print(f"[ingest] {len(items)} raw items from all sources")
    return items


def dedup_new(current_state: dict, items: list[dict]) -> list[dict]:
    """Drop items already posted, and SEC filings already seen."""
    fresh: list[dict] = []
    for item in items:
        if state.already_posted(current_state, item):
            continue
        if item.get("kind") == "filing":
            if state.filing_seen(current_state, item.get("ticker", ""), item.get("accession", "")):
                continue
        fresh.append(item)
    print(f"[dedup] {len(fresh)} new items after dedup")
    return fresh


# ---- technicals -------------------------------------------------------

def build_tech_index() -> dict[str, dict]:
    """{symbol: technical-summary} for every tracked symbol."""
    ohlcv = prices.fetch_ohlcv()
    return {sym: technicals.summarize(sym, df) for sym, df in ohlcv.items()}


def primary_ticker(item: dict) -> str | None:
    if item.get("ticker"):
        return item["ticker"]
    tickers = (item.get("classification") or {}).get("tickers") or []
    return tickers[0] if tickers else None


# ---- publish helper ---------------------------------------------------

def publish(text: str, dry_run: bool) -> dict | None:
    if dry_run:
        print("\n----- DRY RUN POST -----\n" + text + "\n------------------------\n")
        return {"dry_run": True}
    import telegram_publisher
    return telegram_publisher.post_message(text)


# ---- modes ------------------------------------------------------------

def run_auto(dry_run: bool) -> None:
    current_state = state.load_state()
    client = get_client()

    raw = ingest_all()
    state.save_staging(raw)
    fresh = dedup_new(current_state, raw)
    if not fresh:
        print("[auto] nothing new to classify")
        return

    from classifier import classify_items
    relevant = classify_items(client, fresh)
    print(f"[classify] {len(relevant)} items cleared the relevance bar")
    if not relevant:
        return

    tech_index = build_tech_index()

    published = 0
    for item in relevant:
        if published >= config.MAX_POSTS_PER_RUN:
            break
        ticker = primary_ticker(item)
        tech = tech_index.get(ticker) if ticker else None
        try:
            body = synthesizer.synthesize(client, item, tech)
        except Exception as exc:  # noqa: BLE001
            print(f"[synth] failed for {item.get('id')}: {exc}")
            continue
        if not body.strip():
            # Reasoning model returned no visible answer (budget exhausted or
            # empty completion) — skip rather than post an empty note.
            print(f"[synth] empty body for {item.get('id')}, skipping")
            continue

        header = compliance.build_header([ticker] if ticker else None)
        try:
            post = compliance.format_post(header, body)
        except ValueError as exc:
            # Non-compliant output — skip rather than publish, and log it.
            print(f"[compliance] skipping {item.get('id')}: {exc}")
            state.append_post_log({"skipped": True, "reason": str(exc), "id": item.get("id")})
            continue

        publish(post, dry_run)
        published += 1
        # Dry-run is a pure preview: never mutate committed dedup state, so a
        # real run later still posts these once the channel is wired up.
        if dry_run:
            continue
        state.mark_posted(current_state, item)
        if item.get("kind") == "filing":
            state.mark_filing_seen(current_state, item.get("ticker", ""), item.get("accession", ""))
        state.append_post_log(
            {
                "ts": dt.datetime.utcnow().isoformat() + "Z",
                "mode": "auto",
                "ticker": ticker,
                "category": (item.get("classification") or {}).get("category"),
                "id": item.get("id"),
                "dry_run": dry_run,
            }
        )

    print(f"[auto] {'previewed' if dry_run else 'published'} {published} post(s)")
    if not dry_run:
        state.save_state(current_state)


def run_discovery(dry_run: bool, force: bool) -> None:
    current_state = state.load_state()
    today = dt.date.today()
    if not force and today.weekday() != config.DISCOVERY_WEEKDAY:
        print(f"[discovery] not scheduled today (weekday {today.weekday()} != {config.DISCOVERY_WEEKDAY})")
        return
    if not force and state.last_discovery_date(current_state) == today.isoformat():
        print("[discovery] already ran today")
        return

    client = get_client()
    # Reuse the news/filing sources for the week-in-review context.
    week_items = finnhub_news.fetch() + sec_edgar.fetch()
    if not week_items:
        print("[discovery] no context items available; skipping")
        return

    body = discovery_stage.run_discovery(client, week_items)
    if not body.strip():
        print("[discovery] empty body from model; skipping")
        return
    header = compliance.build_header(None, label="🔭 Worth Watching")
    try:
        post = compliance.format_post(header, body)
    except ValueError as exc:
        print(f"[discovery] non-compliant output, not posting: {exc}")
        return

    publish(post, dry_run)
    if not dry_run:
        state.set_last_discovery_date(current_state, today.isoformat())
        state.append_post_log(
            {"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "discovery", "dry_run": dry_run}
        )
        state.save_state(current_state)
    print("[discovery] done" + (" (dry-run preview)" if dry_run else ""))


# ---- entrypoint -------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="auto", choices=["auto", "discovery"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    # Auto-fallback to dry-run if the channel isn't wired up yet.
    dry_run = args.dry_run or not (
        os.environ.get(config.TELEGRAM_TOKEN_ENV) and os.environ.get(config.TELEGRAM_CHANNEL_ENV)
    )
    if dry_run and not args.dry_run:
        print("[main] TELEGRAM_TOKEN/TELEGRAM_CHANNEL unset — running in dry-run mode")

    if args.mode == "discovery":
        run_discovery(dry_run, args.force)
    else:
        run_auto(dry_run)


if __name__ == "__main__":
    main()
