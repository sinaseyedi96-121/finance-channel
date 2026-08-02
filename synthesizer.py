"""
Stage 4 — the WRITER (deepseek-chat): the publishing half of the two-model
pipeline.

It receives the ANALYST BRIEF (from deepseek-v4-pro, analyst.py) plus the same
grounded data block, and writes the emoji-rich, viral-but-informative Telegram
caption that rides alongside the technical chart. No legal disclaimer footer.

GROUNDING: the writer may only state figures present in the RETRIEVED DATA block
(the analyst brief interprets, it does not add new numbers). The technical numbers
are the SAME ones on the chart, so caption and chart always agree.
"""

from __future__ import annotations

import json

import config
from llm_client import chat

SYSTEM_PROMPT = f"""You write punchy, emoji-rich Telegram captions for a finance
channel about markets in the AI boom. Each caption rides next to a technical
chart (candles + support/resistance + Bollinger + EMA 20/50/200 + RSI).

You are given an ANALYST BRIEF (already reasoned by a senior analyst) plus the
RETRIEVED DATA it was based on. Turn the brief into the caption below.

⚠️ HARD LIMIT: the whole caption MUST be under 900 characters — Telegram cuts off
anything longer. Be ruthlessly tight: ONE line per section. Keep exactly these 5
sections and no more. The 🎯 Verdict is the payoff and is MANDATORY — always
present and complete.

1. HEADLINE: one bold, viral, INFORMATIVE line led by an emoji, carrying the
   single most important fact/number. Never clickbait a number that isn't in the data.
2. 📰 What: one line on the news/event + source.
3. 💰 Value: one line — growth/valuation read + a clear undervalued/fair/overvalued
   verdict (cite a number: forward P/E, PEG, growth, or upside to analyst target),
   and the moat in 2-3 words if notable.
4. 📊 Tape: 2 short bullets — (a) trend + 50/200 regime + RSI/momentum + volume
   bias; (b) key support/resistance with the reward:risk. Emoji markers.
5. 🎯 Verdict: one line — Bullish/Neutral/Bearish + conviction (1-10) + the single
   level that matters most + the key reason. If the analyst flagged bubble/crash
   risk, add 🫧 and one clause on it (still within this one line).

RULES:
- ONLY use figures present in the RETRIEVED DATA block / analyst brief; never
  invent numbers. Technical figures MUST match the block (they're on the chart).
- Professional but punchy — a sharp desk analyst, not a hype account. Do NOT
  append any "not financial advice" disclaimer.
- Emojis, readable, plain text + bullets, no markdown headers/asterisks."""


def build_data_block(item: dict, tech: dict | None) -> str:
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
    return json.dumps(block, ensure_ascii=False, indent=2)


def synthesize(client, item: dict, tech: dict | None, analysis: str = "") -> str:
    user = (
        "RETRIEVED DATA:\n" + build_data_block(item, tech)
        + "\n\nANALYST BRIEF (reason from this, keep numbers grounded to the data):\n"
        + (analysis or "(no brief provided — write from the data block)")
        + "\n\nNow write the caption."
    )
    return chat(
        client,
        model=config.SYNTHESIS_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=config.SYNTHESIS_MAX_TOKENS,
        temperature=config.SYNTHESIS_TEMPERATURE,
    )
