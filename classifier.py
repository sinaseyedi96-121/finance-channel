"""
Stage 2 — cheap-model classification + relevance gate.

High volume, low cost: the cheap model (deepseek-chat) tags each staged item
with ticker(s), a category, and a 0-5 relevance score. No synthesis happens
here. Items that clear config.RELEVANCE_MIN_SCORE are passed on to synthesis.

Strict politics filter: RSS/politics items only survive if the model judges
they plausibly move a CORE/INDEX ticker or a macro series. That judgement is
requested explicitly in the system prompt below.
"""

from __future__ import annotations

import json

import config
from llm_client import chat

SYSTEM_PROMPT = f"""You are a fast news triage classifier for a FINANCE / markets
channel. We are in the AI boom, so AI stocks are the center of gravity and the
most important names — but coverage is broad: the index, commodities, macro, and
especially AI-BUBBLE / CRASH-RISK narratives (froth, valuations, concentration,
capex sustainability, "the market will crash" analysis). Those are first-class,
not noise.

Core (AI) tickers: {", ".join(config.CORE_TICKERS)}
Index + commodities: {", ".join(config.MACRO_INSTRUMENTS.keys())}
Adjacent sectors: {", ".join(config.ADJACENT_TICKERS.keys())}
Macro series tracked: {", ".join(config.MACRO_SERIES.keys())}

Reply with ONLY a JSON object, no prose, with these keys:
  "tickers":   array of core tickers the item bears on (may be empty)
  "category":  one of {config.CATEGORIES}
  "relevance": integer 0-5 (0 = irrelevant, 5 = clearly market-moving / high-signal)
  "reason":    one short sentence

Score >= {config.RELEVANCE_MIN_SCORE} when the item is high-signal for markets:
a core-ticker mover, an index/commodity/macro mover, OR a substantive AI-bubble /
crash-risk / market-correction analysis (tag those "bubble_risk"). General
politics with no market channel gets 0-1. Do not inflate scores."""


def build_user_prompt(item: dict) -> str:
    return json.dumps(
        {
            "source": item.get("source"),
            "kind": item.get("kind"),
            "ticker_hint": item.get("ticker"),
            "headline": item.get("headline"),
            "summary": (item.get("summary") or "")[:600],
        },
        ensure_ascii=False,
    )


def parse_classification(text: str) -> dict:
    """Robustly pull the JSON object out of a model reply."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {"tickers": [], "category": "other", "relevance": 0, "reason": "unparseable"}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"tickers": [], "category": "other", "relevance": 0, "reason": "unparseable"}
    return {
        "tickers": list(data.get("tickers") or []),
        "category": data.get("category", "other"),
        "relevance": int(data.get("relevance", 0) or 0),
        "reason": str(data.get("reason", "")),
    }


def passes_relevance(classification: dict) -> bool:
    return int(classification.get("relevance", 0)) >= config.RELEVANCE_MIN_SCORE


def classify_items(client, items: list[dict]) -> list[dict]:
    """Return the subset of items that clear the relevance bar, each with a
    'classification' field attached. Caps total calls at the configured limit."""
    passed: list[dict] = []
    for item in items[: config.MAX_ITEMS_TO_CLASSIFY_PER_RUN]:
        try:
            reply = chat(
                client,
                model=config.CLASSIFIER_MODEL,
                system=SYSTEM_PROMPT,
                user=build_user_prompt(item),
                max_tokens=config.CLASSIFIER_MAX_TOKENS,
                temperature=config.CLASSIFIER_TEMPERATURE,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[classify] call failed for {item.get('id')}: {exc}")
            continue
        classification = parse_classification(reply)
        if passes_relevance(classification):
            item = {**item, "classification": classification}
            passed.append(item)
    # Highest-relevance first so the per-run post cap keeps the best items.
    passed.sort(key=lambda i: i["classification"]["relevance"], reverse=True)
    return passed
