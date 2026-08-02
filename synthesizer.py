"""
Stage 4 — deep synthesis with deepseek-v4-pro ("DeepSeek Pro").

Writes the emoji-rich, viral-but-informative Telegram caption that rides
alongside the technical chart: a punchy headline, what happened, the tape read,
and a short "what to watch" (short-term + midterm). No legal disclaimer footer.

GROUNDING RULE (still non-negotiable): the model may only state figures/facts
present in the RETRIEVED DATA block. No numbers from memory, no invented
figures. The technical numbers in the block are the SAME ones drawn on the
chart, so caption and chart always agree.
"""

from __future__ import annotations

import json

import config
from llm_client import chat

SYSTEM_PROMPT = f"""You write punchy, emoji-rich Telegram captions about AI-driven
stocks for a fast, informative markets channel. Each caption rides next to a
technical chart (candles + support/resistance + Bollinger + EMA 20/50/200 + RSI).

Write the caption in this shape (keep it tight — UNDER {config.TELEGRAM_CAPTION_LIMIT - 300} characters total):

1. HEADLINE: one bold, viral, INFORMATIVE line led by an emoji. It must carry the
   single most important fact/number (e.g. the % move, the earnings beat, the
   breakout). Make someone want to read on — but never clickbait a number that
   isn't in the data.
2. 📰 What happened: 1-2 sentences on the news/event, name the source.
3. 📊 The tape: 2-4 quick bullets on the technicals — price vs Bollinger/EMAs,
   RSI (call out overbought/oversold clearly), MACD, and the key support/
   resistance levels. Use emoji markers (🟢🔴🔥✅⚠️📈📉).
4. 👀 What to watch:
   • Short term (next few days): the level or signal that decides the next move.
   • Midterm (weeks–months): the bigger line (e.g. EMA200 / major support).

RULES:
- ONLY use figures present in the RETRIEVED DATA block. If a number (e.g. next
  earnings date) isn't there, don't state it.
- The technical figures you cite MUST match the block (they are on the chart).
- Describe and contextualize freely — you may say a level is being tested, that
  momentum is building/fading, that RSI is stretched. Do NOT append any
  "not financial advice" disclaimer; the channel does not use one.
- Plenty of emojis, but stay readable. Plain text + bullets, no markdown headers."""


def build_data_block(item: dict, tech: dict | None) -> str:
    """The ONLY source of facts the model may quote (technicals match the chart)."""
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


def synthesize(client, item: dict, tech: dict | None) -> str:
    user = "RETRIEVED DATA:\n" + build_data_block(item, tech)
    text = chat(
        client,
        model=config.SYNTHESIS_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=config.SYNTHESIS_MAX_TOKENS,
        temperature=config.SYNTHESIS_TEMPERATURE,
    )
    # A reasoning model can burn the whole budget thinking and return nothing —
    # fall back to the non-reasoning model so a post is never silently dropped.
    if not text.strip():
        text = chat(
            client,
            model=config.SYNTHESIS_FALLBACK_MODEL,
            system=SYSTEM_PROMPT,
            user=user,
            max_tokens=config.SYNTHESIS_FALLBACK_MAX_TOKENS,
            temperature=config.SYNTHESIS_TEMPERATURE,
        )
    return text
