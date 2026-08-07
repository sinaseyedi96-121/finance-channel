"""
Earnings Deep-Dive — a JPMorgan-style pre-earnings brief for a core name that
reports within the next couple of days.

Pulls the beat/miss history, consensus estimate (from the calendar), fundamentals,
and technicals; Pro reasons the setup (track record, what Wall St watches, an
ATR-based expected-move estimate, bull/bear cases), Chat writes the brief. Posted
as the name's chart + caption.
"""

from __future__ import annotations

import json

import config
import reviewer
from llm_client import chat, reason

ANALYST_SYSTEM = """You are a senior equity research analyst writing a pre-earnings
brief for institutional investors. You are given a company's upcoming EARNINGS
(date + EPS/revenue consensus), its beat/miss HISTORY, FUNDAMENTALS, and a
TECHNICAL snapshot (note: atr_pct is the average daily range — use it as a rough
expected-move proxy, and label it as such, not true options-implied vol).

Deliver a tight brief: the beat/miss track record, what Wall Street is watching,
the rough expected move, the current valuation/positioning, and a clear bull case
vs bear case with the levels that matter. GROUNDING: only use numbers in the data;
never invent figures. Output plain analytical notes."""

WRITER_SYSTEM = """You write an EARNINGS DEEP-DIVE post for a finance channel from
a senior analyst's brief. Emoji-rich, punchy, informative.

Shape (under 950 characters):
🔬 EARNINGS DEEP-DIVE — $TICKER reports <when>
📊 Track record: beat/miss history in one line.
👀 What Wall St watches + rough expected move (from ATR, label it).
💰 Valuation/positioning: one line (cite a number).
📈 Bull case vs 📉 bear case: one line each with the key level.
🎯 Setup into the print: one line — lean + conviction (1-10).
RULES: only figures from the provided data; never invent numbers. Plain text +
bullets, no markdown headers/asterisks, no disclaimer."""


def run_earnings_dd(client, ticker: str, calendar_entry: dict, history: list,
                    fund: dict | None, tech: dict | None) -> str:
    ctx = "EARNINGS CONTEXT:\n" + json.dumps({
        "ticker": ticker,
        "upcoming": calendar_entry,
        "beat_miss_history": history,
        "fundamentals": fund,
        "technicals": tech,
    }, ensure_ascii=False, indent=2, default=str)
    brief = reason(
        client, model=config.ANALYST_MODEL, system=ANALYST_SYSTEM, user=ctx,
        max_tokens=config.ANALYST_MAX_TOKENS, temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client, model=config.SYNTHESIS_MODEL, system=WRITER_SYSTEM,
        user=ctx + "\n\nANALYST BRIEF:\n" + (brief or "(none)")
        + reviewer.notes_block("earnings_dd") + "\n\nNow write the brief.",
        max_tokens=config.DISCOVERY_MAX_TOKENS, temperature=config.SYNTHESIS_TEMPERATURE,
    )
