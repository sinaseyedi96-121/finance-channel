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
import re

from dotenv import load_dotenv

import analyst
import bubble_index as bubble_index_stage
import chart_generator
import compliance
import config
import discovery as discovery_stage
import earnings_dd as earnings_dd_stage
import grounding
import head_to_head as head_to_head_stage
import hidden_value as hidden_value_stage
import market_cap as market_cap_stage
import reviewer
import scorecard as scorecard_stage
import state_manager as state
import synthesizer
import technicals
import week_ahead as week_ahead_stage
from ingest import (
    business_rss, earnings_calendar, earnings_history, eia_energy, finnhub_news,
    fred_macro, fundamentals, prices, sec_edgar,
)
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

def primary_ticker(item: dict) -> str | None:
    if item.get("ticker"):
        return item["ticker"]
    tickers = (item.get("classification") or {}).get("tickers") or []
    return tickers[0] if tickers else None


def macro_snapshots(frames: dict) -> list[dict]:
    """Compact technical summaries for the macro instruments (S&P/Gold/Silver/Oil)
    the analyst uses as market backdrop. Labelled by their display name."""
    out = []
    for label, sym in config.MACRO_INSTRUMENTS.items():
        df = frames.get(sym)
        if df is not None:
            snap = technicals.summarize(sym, df)
            snap["label"] = label
            out.append(snap)
    return out


# ---- publish helpers --------------------------------------------------

def publish_text(text: str, dry_run: bool) -> dict | None:
    if dry_run:
        print("\n----- DRY RUN TEXT POST -----\n" + text + "\n-----------------------------\n")
        return {"dry_run": True}
    import telegram_publisher
    return telegram_publisher.post_message(text)


def publish_photo(image_path: str, caption: str, dry_run: bool) -> dict | None:
    if dry_run:
        print(f"\n----- DRY RUN CHART POST (chart: {image_path}) -----\n"
              + caption + "\n---------------------------------------------------\n")
        return {"dry_run": True}
    import telegram_publisher
    return telegram_publisher.post_photo(image_path, caption)


def grounding_warn(text: str, sources: list, tag: str) -> list[str]:
    """Warn-only grounding check for the weekly/composite posts: log the flags
    (the daily reviewer surfaces them) but don't block the post. The news
    pipeline uses the HARD gate inside run_auto instead."""
    flagged = grounding.verify(text, sources)
    if flagged:
        print(f"[grounding] WARNING {tag}: ungrounded figures {flagged} "
              "(posted anyway — flagged for the reviewer)")
    return flagged


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

    # Price frames for tickers with a relevant item + the macro instruments (so
    # the analyst can relate each item to the broader market).
    wanted = {t for t in (primary_ticker(i) for i in relevant) if t}
    macro_syms = list(config.MACRO_INSTRUMENTS.values())
    frames = prices.fetch_ohlcv(sorted(wanted | set(macro_syms))) if (wanted or macro_syms) else {}
    macro_context = macro_snapshots(frames)

    # Fundamentals are fetched lazily (yfinance .info is slow) — only for the
    # tickers we actually post, cached so a repeat ticker isn't re-fetched.
    fund_cache: dict = {}

    def get_fund(tkr):
        if tkr not in fund_cache:
            got = fundamentals.fetch([tkr])
            fund_cache[tkr] = got[0] if got else None
        return fund_cache[tkr]

    published = 0
    # Daily diversity gate: tickers already covered today (any mode, any run).
    posted_today = state.tickers_posted_today()
    for item in relevant:
        if published >= config.MAX_POSTS_PER_RUN:
            break
        ticker = primary_ticker(item)
        if ticker and posted_today.get(ticker, 0) >= config.MAX_POSTS_PER_TICKER_PER_DAY:
            # A second story on an already-covered name is redundancy, not news
            # — checked BEFORE the model calls so a skipped item costs nothing.
            print(f"[diversity] {ticker} already covered today — skipping {item.get('id')}")
            continue
        df = frames.get(ticker) if ticker else None
        tech = technicals.summarize(ticker, df) if df is not None else None
        fund = get_fund(ticker) if ticker else None

        try:
            # Pro reasons over the item + fundamentals + technicals + macro;
            # Chat writes the caption.
            analysis = analyst.analyze(client, item, tech, fund=fund, macro=macro_context)
            body = synthesizer.synthesize(client, item, tech, analysis)
        except Exception as exc:  # noqa: BLE001
            print(f"[synth] failed for {item.get('id')}: {exc}")
            continue
        if not body.strip():
            # Reasoning model returned no visible answer (budget exhausted or
            # empty completion) — skip rather than post an empty note.
            print(f"[synth] empty body for {item.get('id')}, skipping")
            continue

        # HARD grounding gate: every number in the draft must be traceable to
        # the retrieved data (news text, technicals, fundamentals, macro).
        # One retry with the offending figures named; still failing -> skip.
        sources = [item, tech or {}, fund or {}, macro_context]
        first_flags = grounding.verify(body, sources)
        if first_flags:
            print(f"[grounding] retrying {item.get('id')}: ungrounded {first_flags}")
            try:
                body = synthesizer.synthesize(client, item, tech, analysis,
                                              feedback=grounding.retry_feedback(first_flags))
            except Exception as exc:  # noqa: BLE001
                print(f"[grounding] retry failed for {item.get('id')}: {exc}")
                continue
            still_flagged = grounding.verify(body, sources)
            if not body.strip() or still_flagged:
                print(f"[grounding] SKIPPING {item.get('id')}: still ungrounded "
                      f"after retry: {still_flagged or '(empty rewrite)'}")
                continue

        # Ticker item with price data -> chart + caption. Otherwise text post.
        caption = None
        chart_meta = None
        try:
            if df is not None and tech and tech.get("available"):
                caption = compliance.format_caption(body)
                enriched = technicals.enrich(df)
                levels = technicals.find_key_levels(enriched)
                chart_path = chart_generator.generate_chart(enriched, ticker, levels)
                chart_meta = {
                    "support": levels.get("support"),
                    "resistance": levels.get("resistance"),
                    "support_touches": levels.get("support_touches"),
                    "resistance_touches": levels.get("resistance_touches"),
                    "lookback": levels.get("lookback"),
                    "candles_shown": min(config.CHART_DISPLAY_CANDLES, len(enriched)),
                    "last_price": tech.get("last_price"),
                }
                publish_photo(chart_path, caption, dry_run)
            else:
                header = compliance.build_header([ticker] if ticker else None)
                publish_text(compliance.format_post(header, body), dry_run)
        except ValueError as exc:
            print(f"[format] skipping {item.get('id')}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — a chart/publish failure shouldn't kill the run
            print(f"[publish] failed for {item.get('id')}: {exc}")
            continue
        published += 1
        if ticker:
            posted_today[ticker] = posted_today.get(ticker, 0) + 1
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
                # Full published content + chart metadata: this is what the
                # daily review agent reads (the pipeline's own copy of the
                # channel — the Bot API can't fetch channel history).
                "caption": caption or body,
                "chart": chart_meta,
                "grounding_retry": first_flags or None,
            }
        )
        # Log the call (lean + conviction) for the weekly scorecard.
        if caption and ticker and tech and tech.get("available"):
            lean, conviction = scorecard_stage.parse_verdict(caption)
            if lean:
                setup = tech.get("trade_setup") or {}
                state.add_call(current_state, {
                    "date": dt.date.today().isoformat(),
                    "ticker": ticker,
                    "lean": lean,
                    "conviction": conviction,
                    "price": tech.get("last_price"),
                    "target": setup.get("target") or tech.get("resistance"),
                    "stop": setup.get("stop"),
                })

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

    publish_text(post, dry_run)
    if not dry_run:
        state.set_last_discovery_date(current_state, today.isoformat())
        state.append_post_log(
            {"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "discovery",
             "dry_run": dry_run, "caption": post}
        )
        state.save_state(current_state)
    print("[discovery] done" + (" (dry-run preview)" if dry_run else ""))


def run_week_ahead(dry_run: bool, force: bool) -> None:
    """Monday 'What To Watch — The Week Ahead': a forward-looking preview
    (upcoming earnings + macro + AI-bubble watch) plus an album of macro charts."""
    current_state = state.load_state()
    today = dt.date.today()
    if not force and today.weekday() != config.WEEK_AHEAD_WEEKDAY:
        print(f"[week_ahead] not scheduled today (weekday {today.weekday()} != {config.WEEK_AHEAD_WEEKDAY})")
        return
    if not force and state.get_marker(current_state, "last_week_ahead") == today.isoformat():
        print("[week_ahead] already ran today")
        return

    client = get_client()
    earnings = earnings_calendar.fetch()
    news = finnhub_news.fetch() + business_rss.fetch()

    # Charts for macro instruments + a core-technicals snapshot for the analyst.
    macro_syms = [config.MACRO_INSTRUMENTS[n] for n in config.WEEK_AHEAD_CHART_INSTRUMENTS]
    frames = prices.fetch_ohlcv(macro_syms + config.CORE_TICKERS)
    macro_snaps = macro_snapshots(frames)
    core_snaps = [technicals.summarize(t, frames[t]) for t in config.CORE_TICKERS if t in frames]

    body = week_ahead_stage.run_week_ahead(client, earnings, macro_snaps, core_snaps, news)
    if not body.strip():
        print("[week_ahead] empty body; skipping")
        return

    # Build the macro-instrument charts for the album.
    chart_paths = []
    for label in config.WEEK_AHEAD_CHART_INSTRUMENTS:
        sym = config.MACRO_INSTRUMENTS[label]
        df = frames.get(sym)
        if df is None:
            continue
        try:
            enriched = technicals.enrich(df)
            levels = technicals.find_key_levels(enriched)
            chart_paths.append(chart_generator.generate_chart(enriched, sym, levels, display_name=label))
        except Exception as exc:  # noqa: BLE001
            print(f"[week_ahead] chart failed for {label}: {exc}")

    caption = compliance.format_caption(body)
    flags = grounding_warn(caption, [earnings, macro_snaps, core_snaps, news], "week_ahead")
    if dry_run:
        print(f"\n----- DRY RUN WEEK-AHEAD (charts: {chart_paths}) -----\n{caption}\n-----\n")
    else:
        import telegram_publisher
        if chart_paths:
            telegram_publisher.post_album(chart_paths, caption[: config.TELEGRAM_CAPTION_LIMIT])
        else:
            telegram_publisher.post_message(caption[: config.TELEGRAM_MESSAGE_LIMIT])

    if not dry_run:
        state.set_marker(current_state, "last_week_ahead", today.isoformat())
        state.append_post_log(
            {"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "week_ahead",
             "dry_run": dry_run, "caption": caption, "grounding_flags": flags or None}
        )
        state.save_state(current_state)
    print("[week_ahead] done" + (" (dry-run preview)" if dry_run else ""))


def _chart_for(ticker: str, frames: dict) -> str | None:
    """Enrich a fetched frame and render its chart; None on failure/no data."""
    df = frames.get(ticker)
    if df is None:
        return None
    try:
        enriched = technicals.enrich(df)
        levels = technicals.find_key_levels(enriched)
        return chart_generator.generate_chart(enriched, ticker, levels)
    except Exception as exc:  # noqa: BLE001
        print(f"[chart] {ticker} failed: {exc}")
        return None


def run_hidden_value(dry_run: bool, force: bool) -> None:
    """Wednesday 'Hidden Value': undervalued + overlooked essential companies
    (rare earths, cooling/power, uranium, grid, copper, water, semi tools),
    reasoned by Pro and written by Chat, with charts for the top names."""
    current_state = state.load_state()
    today = dt.date.today()
    if not force and today.weekday() != config.HIDDEN_VALUE_WEEKDAY:
        print(f"[hidden_value] not scheduled today (weekday {today.weekday()} != {config.HIDDEN_VALUE_WEEKDAY})")
        return
    if not force and state.get_marker(current_state, "last_hidden_value") == today.isoformat():
        print("[hidden_value] already ran today")
        return

    # Dedup the value universe and remember each ticker's sector thesis.
    sector_map, universe = {}, []
    for thesis, tickers in config.VALUE_UNIVERSE.items():
        for t in tickers:
            if t not in sector_map:
                sector_map[t] = thesis
                universe.append(t)

    client = get_client()
    funds = fundamentals.fetch(universe)
    print(f"[hidden_value] fundamentals for {len(funds)}/{len(universe)} names")
    if not funds:
        print("[hidden_value] no fundamentals available; skipping")
        return

    ranked = hidden_value_stage.rank(funds)
    body = hidden_value_stage.run_hidden_value(client, ranked, sector_map)
    if not body.strip():
        print("[hidden_value] empty body; skipping")
        return
    text = compliance.format_message(body)

    # Chart the names the post actually features (writer emits "$TICKER"), so the
    # album matches the writeup. Fall back to top-by-score if none parse.
    featured = []
    for sym in re.findall(r"\$([A-Z]{1,5})", text):
        if sym in sector_map and sym not in featured:
            featured.append(sym)
    chart_syms = (featured or [r["ticker"] for r in ranked])[: config.HIDDEN_VALUE_CHART_TOP]
    frames = prices.fetch_ohlcv(chart_syms)
    chart_paths = [p for p in (_chart_for(t, frames) for t in chart_syms) if p]

    flags = grounding_warn(text, [ranked, sector_map], "hidden_value")
    if dry_run:
        print(f"\n----- DRY RUN HIDDEN VALUE (charts: {chart_paths}) -----\n{text}\n-----\n")
    else:
        import telegram_publisher
        telegram_publisher.post_text(text)
        if chart_paths:
            telegram_publisher.post_album(chart_paths, "💎 Hidden Value — charts for the names above")

    if not dry_run:
        state.set_marker(current_state, "last_hidden_value", today.isoformat())
        state.append_post_log(
            {"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "hidden_value",
             "dry_run": dry_run, "caption": text, "grounding_flags": flags or None}
        )
        state.save_state(current_state)
    print("[hidden_value] done" + (" (dry-run preview)" if dry_run else ""))


def _weekly_gate(current_state, weekday: int, marker: str, name: str, force: bool):
    """Shared weekday + once-per-day gate for the weekly posts. Returns today's
    date if the run should proceed, else None."""
    today = dt.date.today()
    if not force and today.weekday() != weekday:
        print(f"[{name}] not scheduled today (weekday {today.weekday()} != {weekday})")
        return None
    if not force and state.get_marker(current_state, marker) == today.isoformat():
        print(f"[{name}] already ran today")
        return None
    return today


def run_scorecard(dry_run: bool, force: bool) -> None:
    """Saturday Conviction Scorecard: grade the last month of calls + report card."""
    current_state = state.load_state()
    today = _weekly_gate(current_state, config.SCORECARD_WEEKDAY, "last_scorecard", "scorecard", force)
    if today is None:
        return
    calls = state.get_calls(current_state)
    tickers = sorted({c.get("ticker") for c in calls if c.get("ticker")})
    if not tickers:
        print("[scorecard] no calls logged yet; skipping")
        return
    frames = prices.fetch_ohlcv(tickers)
    price_map = {t: float(df["Close"].iloc[-1]) for t, df in frames.items() if df is not None and not df.empty}
    stats = scorecard_stage.grade(calls, price_map, today)
    if not stats.get("n"):
        print("[scorecard] no matured calls to grade; skipping")
        return
    client = get_client()
    text = compliance.format_message(scorecard_stage.run_scorecard(client, stats))
    chart = scorecard_stage.scorecard_chart(stats)
    flags = grounding_warn(text, [stats], "scorecard")
    if dry_run:
        print(f"\n----- DRY RUN SCORECARD (chart: {chart}) -----\n{text}\n-----\n")
    else:
        import telegram_publisher
        if chart:
            telegram_publisher.post_photo(chart, text[: config.TELEGRAM_CAPTION_LIMIT])
        else:
            telegram_publisher.post_text(text)
        state.set_marker(current_state, "last_scorecard", today.isoformat())
        state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "scorecard",
                               "caption": text, "grounding_flags": flags or None})
        state.save_state(current_state)
    print("[scorecard] done" + (" (dry-run preview)" if dry_run else ""))


def run_head_to_head(dry_run: bool, force: bool) -> None:
    """Thursday Head-to-Head: two rivals compared, both charts + verdict."""
    current_state = state.load_state()
    today = _weekly_gate(current_state, config.HEAD_TO_HEAD_WEEKDAY, "last_head_to_head", "head_to_head", force)
    if today is None:
        return
    a, b = head_to_head_stage.pick_pair(today)
    frames = prices.fetch_ohlcv([a, b])
    sides = []
    for t in (a, b):
        df = frames.get(t)
        sides.append({"ticker": t,
                      "tech": technicals.summarize(t, df) if df is not None else None,
                      "fund": (fundamentals.fetch([t]) or [None])[0]})
    client = get_client()
    body = head_to_head_stage.run_head_to_head(client, sides[0], sides[1])
    if not body.strip():
        print("[head_to_head] empty body; skipping")
        return
    caption = compliance.format_caption(body)
    charts = [p for p in (_chart_for(a, frames), _chart_for(b, frames)) if p]
    flags = grounding_warn(caption, sides, "head_to_head")
    if dry_run:
        print(f"\n----- DRY RUN HEAD-TO-HEAD {a} vs {b} (charts: {charts}) -----\n{caption}\n-----\n")
    else:
        import telegram_publisher
        if charts:
            telegram_publisher.post_album(charts, caption)
        else:
            telegram_publisher.post_text(caption)
        state.set_marker(current_state, "last_head_to_head", today.isoformat())
        state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "head_to_head",
                               "pair": f"{a}/{b}", "caption": caption,
                               "grounding_flags": flags or None})
        state.save_state(current_state)
    print(f"[head_to_head] done ({a} vs {b})" + (" (dry-run preview)" if dry_run else ""))


def run_earnings_dd(dry_run: bool, force: bool) -> None:
    """Daily check: post an earnings deep-dive when a core name reports soon."""
    current_state = state.load_state()
    upcoming = earnings_calendar.fetch(config.CORE_TICKERS, days=config.EARNINGS_DD_WINDOW_DAYS)
    if not upcoming:
        print("[earnings_dd] no core names reporting in window")
        return
    done = set(state.get_marker(current_state, "earnings_dd_done") or [])
    entry = next((e for e in upcoming if f"{e['ticker']}:{e['date']}" not in done), None)
    if entry is None and not force:
        print("[earnings_dd] all upcoming already covered")
        return
    entry = entry or upcoming[0]
    ticker = entry["ticker"]
    frames = prices.fetch_ohlcv([ticker])
    df = frames.get(ticker)
    tech = technicals.summarize(ticker, df) if df is not None else None
    fund = (fundamentals.fetch([ticker]) or [None])[0]
    history = earnings_history.fetch(ticker)
    client = get_client()
    body = earnings_dd_stage.run_earnings_dd(client, ticker, entry, history, fund, tech)
    if not body.strip():
        print("[earnings_dd] empty body; skipping")
        return
    caption = compliance.format_caption(body)
    chart = _chart_for(ticker, frames)
    flags = grounding_warn(caption, [entry, history, fund or {}, tech or {}], "earnings_dd")
    if dry_run:
        print(f"\n----- DRY RUN EARNINGS DD {ticker} (chart: {chart}) -----\n{caption}\n-----\n")
    else:
        import telegram_publisher
        if chart:
            telegram_publisher.post_photo(chart, caption)
        else:
            telegram_publisher.post_text(caption)
        done.add(f"{ticker}:{entry['date']}")
        state.set_marker(current_state, "earnings_dd_done", sorted(done)[-50:])
        state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "earnings_dd",
                               "ticker": ticker, "caption": caption,
                               "grounding_flags": flags or None})
        state.save_state(current_state)
    print(f"[earnings_dd] done ({ticker})" + (" (dry-run preview)" if dry_run else ""))


def run_bubble_index(dry_run: bool, force: bool) -> None:
    """Friday AI Bubble Index: proprietary froth gauge + read."""
    current_state = state.load_state()
    today = _weekly_gate(current_state, config.BUBBLE_INDEX_WEEKDAY, "last_bubble_index", "bubble_index", force)
    if today is None:
        return
    conc_a, conc_b = config.BUBBLE_CONCENTRATION_PAIR
    frames = prices.fetch_ohlcv(config.BUBBLE_INDEX_TICKERS + [conc_a, conc_b])
    tech_map = {t: technicals.summarize(t, frames[t]) for t in config.BUBBLE_INDEX_TICKERS if t in frames}

    def _ret6(sym):
        df = frames.get(sym)
        n = config.BUBBLE_CONCENTRATION_LOOKBACK
        if df is None or len(df) <= n:
            return None
        c = df["Close"].astype(float)
        return (c.iloc[-1] / c.iloc[-n] - 1) * 100

    gdp_b = fred_macro.latest(config.FRED_GDP_SERIES)          # US nominal GDP, $ billions
    capex_gdp_pct = (config.BUBBLE_AI_CAPEX_ANNUAL_USD / (gdp_b * 1e9) * 100) if gdp_b else None
    inputs = {
        "valuations": fundamentals.fetch(config.BUBBLE_INDEX_TICKERS),
        "tech_map": tech_map,
        "concentration": {"spy_ret": _ret6(conc_a), "rsp_ret": _ret6(conc_b)},
        "capex_gdp_pct": capex_gdp_pct,
        "hy_spread_pct": fred_macro.latest(config.FRED_HY_SPREAD_SERIES),
    }
    index = bubble_index_stage.compute_index(inputs)
    if not index:
        print("[bubble_index] no data; skipping")
        return
    client = get_client()
    text = compliance.format_message(bubble_index_stage.run_bubble_index(client, index))
    gauge = bubble_index_stage.gauge_chart(index)
    flags = grounding_warn(text, [index], "bubble_index")
    if dry_run:
        print(f"\n----- DRY RUN BUBBLE INDEX {index['score']}/100 {index['label']} (chart: {gauge}) -----\n{text}\n-----\n")
    else:
        import telegram_publisher
        if gauge:
            telegram_publisher.post_photo(gauge, text[: config.TELEGRAM_CAPTION_LIMIT])
        else:
            telegram_publisher.post_text(text)
        state.set_marker(current_state, "last_bubble_index", today.isoformat())
        state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "bubble_index",
                               "score": index["score"], "caption": text,
                               "grounding_flags": flags or None})
        state.save_state(current_state)
    print(f"[bubble_index] done ({index['score']}/100)" + (" (dry-run preview)" if dry_run else ""))


def run_market_cap(dry_run: bool, force: bool) -> None:
    """Top-20 market-cap leaderboard — checked after each news run, but posted
    ONLY when the top-20 ordering changed (or on the inaugural run)."""
    current_state = state.load_state()
    today = dt.date.today()
    if not force and state.get_marker(current_state, "last_market_cap") == today.isoformat():
        print("[market_cap] already posted today")
        return
    ranked = market_cap_stage.fetch_ranking()
    if len(ranked) < config.MARKET_CAP_TOP_N:
        print(f"[market_cap] only {len(ranked)} caps available; skipping")
        return
    new_order = [r["ticker"] for r in ranked]
    prev_order = state.get_marker(current_state, "market_cap_top20")
    changes = market_cap_stage.compare(prev_order, new_order)
    if changes is None:
        print("[market_cap] top-20 ordering unchanged — nothing to post")
        return
    chart = market_cap_stage.ranking_chart(ranked, changes)
    caption = market_cap_stage.build_caption(ranked, changes)
    publish_photo(chart, caption, dry_run)
    if not dry_run:
        state.set_marker(current_state, "market_cap_top20", new_order)
        state.set_marker(current_state, "last_market_cap", today.isoformat())
        state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "market_cap",
                               "caption": caption,
                               "moves": len(changes["moved"]) + len(changes["entered"])})
        state.save_state(current_state)
    print("[market_cap] done" + (" (dry-run preview)" if dry_run else ""))


def run_review(dry_run: bool, force: bool) -> None:
    """Daily editor-in-chief: review everything the channel published, then
    refresh editorial_notes.json — the directives every subsequent analyst/
    writer prompt obeys. The full review is committed under reviews/."""
    current_state = state.load_state()
    today = dt.date.today()
    if not force and state.get_marker(current_state, "last_review") == today.isoformat():
        print("[review] already ran today")
        return
    entries = reviewer.load_recent_posts()
    if not entries:
        print("[review] nothing published in the review window; skipping")
        return
    findings = reviewer.mechanical_findings(entries)
    print(f"[review] {len(entries)} post(s), {len(findings)} mechanical finding(s)")
    for f in findings:
        print(f"  - {f}")
    client = get_client()
    critique, directives = reviewer.run_review(client, entries, findings)
    if dry_run:
        print(f"\n----- DRY RUN REVIEW -----\n{critique}\n\nDIRECTIVES: {directives}\n-----\n")
        return
    path = reviewer.save_review(today.isoformat(), entries, findings, critique, directives)
    state.set_marker(current_state, "last_review", today.isoformat())
    state.append_post_log({"ts": dt.datetime.utcnow().isoformat() + "Z", "mode": "review",
                           "findings": len(findings), "directives": len(directives)})
    state.save_state(current_state)
    print(f"[review] saved {path}; {len(directives)} directive(s) now steer future posts")


# ---- entrypoint -------------------------------------------------------

_MODES = {
    "auto": lambda d, f: run_auto(d),
    "discovery": run_discovery,
    "week_ahead": run_week_ahead,
    "hidden_value": run_hidden_value,
    "scorecard": run_scorecard,
    "head_to_head": run_head_to_head,
    "earnings_dd": run_earnings_dd,
    "bubble_index": run_bubble_index,
    "market_cap": run_market_cap,
    "review": run_review,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="auto", choices=list(_MODES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    # Auto-fallback to dry-run if the channel isn't wired up yet.
    dry_run = args.dry_run or not (
        os.environ.get(config.TELEGRAM_TOKEN_ENV) and os.environ.get(config.TELEGRAM_CHANNEL_ENV)
    )
    if dry_run and not args.dry_run:
        print("[main] TELEGRAM_TOKEN/TELEGRAM_CHANNEL unset — running in dry-run mode")

    _MODES[args.mode](dry_run, args.force)


if __name__ == "__main__":
    main()
