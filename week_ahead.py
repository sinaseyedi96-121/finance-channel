"""
Weekly "What To Watch — The Week Ahead" post (Mondays).

Forward-looking: what big news/events are coming this week and what to keep an
eye on. Two-model pipeline like the news posts — deepseek-v4-pro reasons over the
week's setup (upcoming earnings, macro instruments, notable news, AI-bubble
watch), then deepseek-chat writes the published post. It is paired with an album
of macro instrument charts (S&P 500, Gold, Silver, Oil) in main.py.
"""

from __future__ import annotations

import json

import config
from llm_client import chat, reason

ANALYST_SYSTEM = """You are a senior markets analyst writing the analytical basis
for a finance channel's WEEK AHEAD preview. We are in the AI boom; AI stocks are
central, but cover the whole market.

You are given: the upcoming EARNINGS this week, current TECHNICALS for macro
instruments (S&P 500, Gold, Silver, Oil), technicals for the core AI names, and
recent NOTABLE NEWS. Reason into a tight brief (~150-220 words) covering:
- The big scheduled events this week (earnings, and any macro read-through).
- What to keep an eye on: names/levels sitting at a decision point (near key
  support/resistance, stretched RSI), and what a break/bounce would signal.
- The macro backdrop (index/commodities) and what it implies for risk appetite.
- AI-BUBBLE / CRASH WATCH: an honest read on froth vs. fundamentals right now —
  concentration, valuations, capex — proportionate to the actual data.

GROUNDING: use only the numbers provided. No invented figures. Output plain
analytical notes (no emojis/headline — the writer adds those)."""

WRITER_SYSTEM = """You write the WEEK AHEAD post for a finance-in-the-AI-boom
Telegram channel, from a senior analyst's brief. Emoji-rich, punchy, informative.

⚠️ HARD LIMIT: the shape below (before any ===MORE===) MUST be under 950
characters (it's a chart-album caption — anything longer is cut off). Be
ruthlessly concise; every section must fit, especially the last one. Drop
detail before you drop a section.

Shape (tight):
📅 THE WEEK AHEAD — <one-line hook>
🗓️ Calendar: the key earnings/events this week (days if given), 1-2 lines.
👀 Watch: 2-3 bullets — names/levels at decision points + what a break/bounce means.
🌍 Macro: one line on S&P/Gold/Oil & risk appetite.
🫧 Bubble watch: one honest line on froth vs fundamentals.

OPTIONAL DEPTH: after the shape above, on its own line write exactly ===MORE===
then 3-5 sentences of the grounded detail you had to cut for space — the fuller
per-earnings context, additional watch levels, or a deeper macro/bubble read.
This rides in a collapsed "Show more" box on Telegram: bonus depth for readers
who tap in, never required — the shape above must stand alone and complete
without it. Omit ===MORE=== entirely if you have nothing worth adding.

RULES: only use figures from the provided context; do not invent numbers. No
"not financial advice" disclaimer. Plain text + bullets, no markdown headers."""


def _context(earnings: list, macro_snaps: list, core_snaps: list, news: list) -> str:
    return json.dumps(
        {
            "upcoming_earnings": earnings,
            "macro_instruments": macro_snaps,
            "core_technicals": core_snaps,
            "notable_news": [
                {"headline": n.get("headline"), "source": n.get("source"),
                 "category": (n.get("classification") or {}).get("category")}
                for n in (news or [])[:12]
            ],
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def run_week_ahead(client, earnings: list, macro_snaps: list,
                   core_snaps: list, news: list) -> str:
    context = _context(earnings, macro_snaps, core_snaps, news)
    brief = reason(
        client,
        model=config.ANALYST_MODEL,
        system=ANALYST_SYSTEM,
        user="WEEK CONTEXT:\n" + context,
        max_tokens=config.ANALYST_MAX_TOKENS,
        temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client,
        model=config.SYNTHESIS_MODEL,
        system=WRITER_SYSTEM,
        user=("WEEK CONTEXT:\n" + context
              + "\n\nANALYST BRIEF:\n" + (brief or "(none)")
              + "\n\nNow write the Week Ahead post."),
        max_tokens=config.DISCOVERY_MAX_TOKENS,
        temperature=config.SYNTHESIS_TEMPERATURE,
    )
