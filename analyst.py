"""
Stage 3.5 — the ANALYST (deepseek-v4-pro, "DeepSeek Pro"): the reasoning half of
the two-model pipeline.

It reads the grounded data (news + chart technicals + macro context) and produces
a tight analytical brief: what the news means for the stock AND the broader
market, how any political/macro angle feeds through, the key technical levels,
momentum, and — a first-class concern for this channel — AI-bubble / crash risk.

The writer model (deepseek-chat, in synthesizer.py) turns this brief into the
published caption. See llm_client.reason() for why we can rely on v4-pro here
even though its `content` is often empty (we fall back to `reasoning_content`).
"""

from __future__ import annotations

import json

import config
from llm_client import reason

SYSTEM_PROMPT = """You are a senior markets analyst for a finance channel. We are in
the AI boom, so AI stocks are the center of gravity — but you cover the broad
market: the index, commodities, macro, and politics, and how they interconnect.

You are given a RETRIEVED DATA block (a news/filing/macro item + a technical
snapshot). Produce a SHORT analytical brief (tight bullet notes, ~120-180 words)
that the writer will turn into a post. Cover, only where relevant:
- What happened and what it actually means for this name.
- The read-through to the BROADER market and the AI trade specifically.
- Any political / macro / commodity channel that transmits to the tape.
- The technical picture: trend, momentum (RSI/MACD), and the key support/
  resistance levels that decide the next move (short term) and the bigger line
  (midterm, e.g. EMA200).
- AI-BUBBLE / CRASH RISK: if the item bears on valuations, concentration, capex
  sustainability, or a possible correction, say so plainly and proportionately.
  Don't force a bubble angle where there isn't one; do flag it where there is.

GROUNDING: use ONLY figures present in the data block. Never invent numbers.
Output the brief as plain analytical notes (no headline, no emojis — that's the
writer's job)."""


def build_data_block(item: dict, tech: dict | None, macro: list | None = None) -> str:
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
        "technical_snapshot": tech or {"available": False},
    }
    if macro:
        block["macro_context"] = macro
    return json.dumps(block, ensure_ascii=False, indent=2)


def analyze(client, item: dict, tech: dict | None, macro: list | None = None) -> str:
    user = "RETRIEVED DATA:\n" + build_data_block(item, tech, macro)
    return reason(
        client,
        model=config.ANALYST_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=config.ANALYST_MAX_TOKENS,
        temperature=config.ANALYST_TEMPERATURE,
    )
