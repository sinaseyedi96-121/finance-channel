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
anything longer, so be concise and make every section fit, especially the last
one. Drop detail before you drop a section.

1. HEADLINE: one bold, viral, INFORMATIVE line led by an emoji, carrying the
   single most important fact/number. Make someone want to read on — never
   clickbait a number that isn't in the data.
2. 📰 What happened: 1-2 sentences on the news/event, name the source.
3. 📊 The tape: 2-4 quick bullets — price vs Bollinger/EMAs, RSI (call out
   overbought/oversold), MACD, and key support/resistance. Emoji markers
   (🟢🔴🔥✅⚠️📈📉).
4. 👀 What to watch:
   • Short term (next few days): the level/signal that decides the next move.
   • Midterm (weeks–months): the bigger line (EMA200 / major support).
5. If the analyst flagged AI-bubble / crash risk, include ONE clear line on it
   (🫧 or ⚠️). Don't invent a bubble angle the analyst didn't raise.

RULES:
- ONLY use figures present in the RETRIEVED DATA block. The brief interprets —
  it does not license new numbers.
- Technical figures MUST match the block (they're on the chart).
- Describe and contextualize freely (levels tested, momentum building/fading,
  RSI stretched). Do NOT append any "not financial advice" disclaimer.
- Plenty of emojis, readable, plain text + bullets, no markdown headers."""


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
