"""
Stage 3.5 — the ANALYST (deepseek-v4-pro, "DeepSeek Pro"): the reasoning half of
the two-model pipeline.

Upgraded to an institutional, Wall-Street-desk framework (inspired by the way
Goldman/Morgan Stanley/Citadel/Bain structure a note): it reads the grounded data
— news, FUNDAMENTALS (valuation, growth, margins, balance sheet, analyst targets,
positioning) and a full multi-timeframe TECHNICAL snapshot — and produces a tight
research brief covering fundamentals, valuation, moat, the technical setup, risk,
catalysts, and a conviction call, always relating the name to the broader market
and AI-bubble/crash risk.

The writer model (deepseek-chat, synthesizer.py) turns this brief into the post.
llm_client.reason() captures v4-pro's analysis from reasoning_content even when
`content` comes back empty.
"""

from __future__ import annotations

import json

import config
from llm_client import reason

SYSTEM_PROMPT = """You are a senior sell-side equity analyst running a desk that
blends fundamental research, valuation, and quantitative technicals — think a
Goldman/Morgan Stanley note crossed with a Citadel technical read. We are in the
AI boom; AI stocks are central, but you cover the whole market.

You are given a RETRIEVED DATA block: a news/event item, FUNDAMENTALS, a
multi-timeframe TECHNICAL snapshot, and MACRO context. Produce a tight, structured
analytical brief (~180-240 words) with these sections (skip one only if the data
is truly absent — never invent it):

1) WHAT HAPPENED — the event and why it matters for this name.
2) FUNDAMENTALS & VALUATION — growth (revenue/earnings), margins, balance sheet
   (debt/equity, ROE), and valuation (forward P/E, PEG, P/B, EV/EBITDA) read
   against the growth; state a verdict: undervalued / fair / overvalued, and cite
   the analyst mean-target upside.
3) MOAT & COMPETITIVE POSITION — rate the moat weak / moderate / strong and say
   why (is it doing something hard-to-replicate?).
4) TECHNICAL SETUP — top-down: daily vs weekly vs monthly trend, the 50/200 EMA
   regime (golden/death cross), RSI/MACD/Bollinger in plain English, volume (are
   buyers or sellers in control), the exact key support/resistance, and the
   reward:risk to resistance.
5) RISK — the main industry/competitive/balance-sheet/macro (beta) risk and a
   realistic worst case. Flag AI-BUBBLE / crash-risk read-through where relevant.
6) CATALYSTS — what could move it over the next few months.
7) CONVICTION — one line: a Bullish / Neutral / Bearish lean with a 1-10 conviction
   and the single most important reason.

GROUNDING (non-negotiable): every NUMBER you state must appear in the data block.
Moat/competitive judgement is qualitative and allowed, but never fabricate figures.
Output plain analytical notes (no emojis/headline — that's the writer's job)."""


def build_data_block(item: dict, tech: dict | None, fund: dict | None = None,
                     macro: list | None = None) -> str:
    block = {
        "news_item": {
            "headline": item.get("headline"),
            "summary": item.get("summary"),
            "source_name": item.get("publisher") or item.get("source"),
            "published": item.get("published"),
            "category": (item.get("classification") or {}).get("category"),
            "tickers": (item.get("classification") or {}).get("tickers")
            or ([item["ticker"]] if item.get("ticker") else []),
        },
        "fundamentals": fund or {"available": False},
        "technical_snapshot": tech or {"available": False},
    }
    if macro:
        block["macro_context"] = macro
    return json.dumps(block, ensure_ascii=False, indent=2, default=str)


def analyze(client, item: dict, tech: dict | None, fund: dict | None = None,
            macro: list | None = None) -> str:
    user = "RETRIEVED DATA:\n" + build_data_block(item, tech, fund, macro)
    return reason(
        client,
        model=config.ANALYST_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=config.ANALYST_MAX_TOKENS,
        temperature=config.ANALYST_TEMPERATURE,
    )
