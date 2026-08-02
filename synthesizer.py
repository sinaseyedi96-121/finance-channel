"""
Stage 4 — deep synthesis with deepseek-v4-pro ("DeepSeek Pro").

Produces the "what happened / why it matters / numbers to know" writeup for
each item that cleared the relevance bar.

GROUNDING RULE (non-negotiable): the model may only state figures and facts
present in the retrieved-data block passed in the prompt. No numbers from
memory, no invented figures, no filled-in price targets. This is enforced two
ways: (1) the system prompt below forbids it in the strongest terms, and (2)
the retrieved-data block is the ONLY source of numbers the model is shown, and
the compliance linter (compliance.py) rejects the output if it smuggles in
buy/sell/target language.
"""

from __future__ import annotations

import json

import config
from llm_client import chat

SYSTEM_PROMPT = """You write concise, factual market notes for a Telegram channel
about AI-driven stocks. You will be given a RETRIEVED DATA block (a news/filing
item plus a technical snapshot of the ticker).

ABSOLUTE GROUNDING RULE — read carefully:
- You may ONLY state figures, prices, percentages, dates, and facts that appear
  verbatim in the RETRIEVED DATA block.
- You must NOT recall any number from your own training/memory.
- If a number is not in the block, do not state it. Say "not disclosed" instead.
- Never invent a price target, valuation, forecast, or earnings figure.

STYLE:
- Structure the note as three short parts:
  1. What happened — the concrete event, and name the source.
  2. Why it matters — brief interpretation, grounded only in the block.
  3. Numbers to know — last price, % change, one key technical level, next
     earnings date IF it is present in the block. Omit any that are absent.
- Neutral, descriptive tone. No hype.

FORBIDDEN (compliance): do NOT use the words buy, sell, long, short, entry,
stop-loss, take-profit, or "price target". Do NOT tell the reader to do anything
with the stock. Describe only. A disclaimer footer is added later by code — do
not write your own.

Keep it under 150 words. Plain text (no markdown headers)."""


def build_data_block(item: dict, tech: dict | None) -> str:
    """The ONLY source of facts the model is allowed to quote."""
    block = {
        "news_item": {
            "headline": item.get("headline"),
            "summary": item.get("summary"),
            "source_name": item.get("publisher") or item.get("source"),
            "url": item.get("url"),
            "published": item.get("published"),
            "category": item.get("classification", {}).get("category"),
            "tickers": item.get("classification", {}).get("tickers") or (
                [item["ticker"]] if item.get("ticker") else []
            ),
        },
        "technical_snapshot": tech or {"available": False},
    }
    return json.dumps(block, ensure_ascii=False, indent=2)


def synthesize(client, item: dict, tech: dict | None) -> str:
    user = "RETRIEVED DATA:\n" + build_data_block(item, tech)
    return chat(
        client,
        model=config.SYNTHESIS_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=config.SYNTHESIS_MAX_TOKENS,
        temperature=config.SYNTHESIS_TEMPERATURE,
    )
