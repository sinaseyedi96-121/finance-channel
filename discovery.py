"""
Stage 5 — weekly discovery layer (deepseek-v4-pro).

A reasoning pass over the core tickers' supply chains and sector adjacencies
(power, cooling, chip equipment, memory, defense dual-use), grounded in that
week's retrieved news and filings. Output: "sectors/companies worth researching"
with the reasoning chain shown, explicitly framed as informational starting
points, NOT picks.

Same grounding + compliance discipline as synthesis: reason from the provided
week-in-review block, and never use buy/sell/target language.
"""

from __future__ import annotations

import json

import config
from llm_client import chat, reason

SYSTEM_PROMPT = f"""You are a research analyst producing a weekly "worth watching"
note for a Telegram channel about AI-driven stocks and their second-order
beneficiaries.

You are given a WEEK IN REVIEW block: recent news/filings for the core tickers
and known adjacent sectors. Reason about second-order beneficiaries: who supplies,
powers, cools, or sells equipment to the AI buildout, and which sectors ride the
same trend.

Core tickers: {", ".join(config.CORE_TICKERS)}
Known adjacent sectors: {json.dumps(config.ADJACENT_TICKERS)}

Produce a short note with:
  1. A one-line framing sentence.
  2. 3-5 "worth researching" bullets. Each names a sector or company, and SHOWS
     the reasoning chain (why this week's data points there). You may propose
     names beyond the known adjacency lists if the reasoning supports it.
  3. Close with the explicit line that these are informational starting points
     for the reader's own research, not recommendations.

GROUNDING: base the reasoning on the provided block. You may name a company as a
research starting point based on its business relationship, but do NOT state
specific figures/prices unless they appear in the block.

FORBIDDEN (compliance): no buy/sell/long/short/entry/stop/target language, and
do not tell the reader to trade anything. Descriptive and exploratory only. A
disclaimer footer is added later by code. Keep under 250 words. Plain text."""


def build_week_block(items: list[dict]) -> str:
    trimmed = [
        {
            "ticker": it.get("ticker") or (it.get("classification", {}) or {}).get("tickers"),
            "kind": it.get("kind"),
            "headline": it.get("headline"),
            "summary": (it.get("summary") or "")[:300],
            "source": it.get("source"),
            "published": it.get("published"),
        }
        for it in items
    ]
    return json.dumps({"week_in_review": trimmed}, ensure_ascii=False, indent=2)


ANALYST_SYSTEM = """You are a senior analyst. From the WEEK IN REVIEW (news/filings
for AI names and adjacent sectors), reason about second-order beneficiaries — who
supplies, powers, cools, or sells equipment to the AI buildout — and which sectors
ride or are threatened by the same trend, including AI-bubble/crash risk. Output
tight analytical notes on 3-5 candidate sectors/companies with the reasoning
chain. Ground the reasoning in the provided items; do not invent figures."""


def run_discovery(client, items: list[dict]) -> str:
    block = "WEEK IN REVIEW:\n" + build_week_block(items)
    # Pro reasons over the week; Chat writes the published note.
    brief = reason(
        client,
        model=config.ANALYST_MODEL,
        system=ANALYST_SYSTEM,
        user=block,
        max_tokens=config.ANALYST_MAX_TOKENS,
        temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client,
        model=config.DISCOVERY_MODEL,
        system=SYSTEM_PROMPT,
        user=block + "\n\nANALYST BRIEF:\n" + (brief or "(none)") + "\n\nNow write the note.",
        max_tokens=config.DISCOVERY_MAX_TOKENS,
        temperature=config.DISCOVERY_TEMPERATURE,
    )
