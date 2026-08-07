"""
Head-to-Head (weekly, Thursday) — two rivals compared side by side.

Rotates through config.HEAD_TO_HEAD_PAIRS (one pair per ISO week). Pro compares
the two on valuation, growth, margins, moat, and the technical setup and calls a
winner; Chat writes the post. Published as an album of both charts + the caption.
"""

from __future__ import annotations

import datetime as dt
import json

import config
import reviewer
from llm_client import chat, reason


def pick_pair(today: dt.date | None = None) -> tuple[str, str]:
    today = today or dt.date.today()
    week = today.isocalendar()[1]
    return config.HEAD_TO_HEAD_PAIRS[week % len(config.HEAD_TO_HEAD_PAIRS)]


ANALYST_SYSTEM = """You are a senior equity analyst writing a head-to-head compare
note for two rival stocks. You are given each name's FUNDAMENTALS and a
multi-timeframe TECHNICAL snapshot. Compare them on: valuation (forward P/E, PEG,
P/B, EV/EBITDA vs growth), growth & margins, balance sheet, competitive MOAT, and
the technical setup (trend, 50/200 regime, RSI, key levels, reward:risk). Then
declare which is the stronger BUY right now and WHY, and note for whom the other
might still fit. GROUNDING: only use numbers in the data; never invent figures.
Output tight analytical notes."""

WRITER_SYSTEM = """You write the weekly HEAD-TO-HEAD post for a finance channel,
from a senior analyst's compare brief. Emoji-rich, punchy, decisive.

Shape (under 950 characters):
⚔️ HEAD-TO-HEAD — $A vs $B
📊 Valuation: one line comparing the two (cite numbers).
📈 Growth & moat: one line.
🎯 Technicals: one line — which has the cleaner setup + key levels.
🏆 Winner: $X — one-line reason + a conviction (1-10). Note who $Y still suits.
RULES: only figures from the provided data; never invent numbers. Plain text +
bullets, no markdown headers/asterisks, no disclaimer."""


def _fmt(side: dict) -> dict:
    return {"ticker": side["ticker"], "fundamentals": side.get("fund"),
            "technicals": side.get("tech")}


def run_head_to_head(client, a: dict, b: dict) -> str:
    ctx = "TWO NAMES:\n" + json.dumps({"A": _fmt(a), "B": _fmt(b)},
                                      ensure_ascii=False, indent=2, default=str)
    brief = reason(
        client, model=config.ANALYST_MODEL, system=ANALYST_SYSTEM, user=ctx,
        max_tokens=config.ANALYST_MAX_TOKENS, temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client, model=config.SYNTHESIS_MODEL, system=WRITER_SYSTEM,
        user=ctx + "\n\nANALYST BRIEF:\n" + (brief or "(none)")
        + reviewer.notes_block("head_to_head") + "\n\nNow write the post.",
        max_tokens=config.DISCOVERY_MAX_TOKENS, temperature=config.SYNTHESIS_TEMPERATURE,
    )
