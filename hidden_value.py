"""
Weekly "Hidden Value" post (Wednesdays).

Surfaces companies that look FUNDAMENTALLY UNDERVALUED versus their price and/or
whose structural importance the market underappreciates — the picks-and-shovels
of the AI / electrification / energy build-out: rare earths & critical minerals,
data-center cooling & power, uranium/nuclear, grid, copper, water, semi equipment.

Two-model pipeline: deepseek-v4-pro reasons over the candidates' FUNDAMENTALS
(valuation vs growth, analyst upside, margins) + each sector's structural thesis
and picks the strongest cases; deepseek-chat writes the post. All figures are
grounded in the fetched fundamentals (ingest/fundamentals.py).
"""

from __future__ import annotations

import json

import config
from llm_client import chat, reason

# Why each overlooked sector actually matters — handed to the analyst as the
# structural backdrop so the "why it's essential" reasoning stays concrete.
SECTOR_THESES = {
    "rare_earth_and_critical_minerals":
        "Magnets/motors for EVs, robotics, defense and wind; supply is concentrated "
        "outside the West, so domestic/allied producers are strategically critical.",
    "data_center_cooling_and_power":
        "AI compute density is bottlenecked by heat and power delivery; cooling and "
        "power-distribution vendors sell into every data-center build.",
    "uranium_and_nuclear":
        "AI data centers need firm 24/7 baseload; nuclear is the cleanest fit, and "
        "uranium supply is tight after years of underinvestment.",
    "grid_and_electrification":
        "Electrification + AI load growth strain aging grids; transmission, "
        "substations and grid equipment are the hard bottleneck.",
    "copper_and_industrial_metals":
        "Copper is the metal of electrification (grids, EVs, data centers) with a "
        "structural supply deficit looming.",
    "water_infrastructure":
        "Data centers and industry are water-intensive; water treatment/management "
        "is an under-owned, essential utility layer.",
    "semi_equipment_and_materials":
        "The tools and materials every chip is made with — picks-and-shovels of the "
        "AI compute supply chain.",
    "quantum_computing":
        "The next compute paradigm after AI — early, speculative, but a handful of "
        "names own real hardware/IP; asymmetric optionality if it inflects.",
    "defense_and_military":
        "Rearmament + drones/autonomy + space; multi-year government backlogs make "
        "revenue unusually visible, and some capabilities are single-source.",
    "irreplaceable_moats":
        "Companies doing something no one else can at scale — EUV lithography (ASML), "
        "leading-edge foundry (TSM), chip-design EDA duopoly (SNPS/CDNS), unique "
        "x86+GPU (AMD), CPU IP everywhere (ARM). Structurally un-substitutable.",
}

ANALYST_SYSTEM = """You are a value + thematic equity analyst. You are given
FUNDAMENTALS for a pool of critically-important-but-often-overlooked companies
(each tagged with its sector and that sector's structural thesis).

Find the names with the strongest case that FUNDAMENTAL VALUE EXCEEDS the current
price, and/or whose structural importance the market underappreciates. Reason
concretely per candidate:
- Valuation vs quality/growth: forward P/E, PEG, P/B against revenue growth and
  margins — is it cheap for what it is?
- Analyst mean target vs price (upside %): the market's own implied re-rating.
- Why the SECTOR is essential and overlooked (use the provided thesis), and what
  catalyst could close the gap.
Pick the best 4-6 and rank them. Be honest about risk (e.g. negative margins,
speculative pre-revenue). GROUNDING: use only the numbers provided; never invent
figures. Output tight analytical notes per pick (name, the value signal, the why)."""

WRITER_SYSTEM = """You write the weekly "HIDDEN VALUE" post for a finance-in-the-
AI-boom Telegram channel, from a senior analyst's brief. The angle: undervalued +
overlooked companies the AI/energy build-out actually runs on, and WHY they could
re-rate higher.

Shape (emoji-rich, punchy, but substantive — this is a reasoning post):
💎 HIDDEN VALUE — <one-line hook on the theme>
Then 4-5 entries, each:
  <emoji> $TICKER — Company (sector)
  • What they do & why they're essential/overlooked (1 line)
  • The value signal: cheap vs target/growth (cite the numbers — upside to target,
    forward P/E, growth, margins)
  • Why it could go up (the catalyst/re-rating case)
Close with one honest line on risk.

RULES: use ONLY figures from the provided context; never invent numbers. Keep it
under 2600 characters. Plain text + bullets, no markdown headers/asterisks. Frame
as the bull-case thesis and what to research — informative, not a directive."""


def value_score(row: dict) -> float:
    """Deterministic shortlist score: analyst upside to target, lightly rewarding
    revenue growth. Used to rank candidates and pick which get charts."""
    up = row.get("upside_to_target_pct") or 0.0
    growth = row.get("revenue_growth_pct") or 0.0
    return up + 0.2 * min(max(growth, 0.0), 60.0)


def rank(fundamentals: list[dict]) -> list[dict]:
    return sorted(fundamentals, key=value_score, reverse=True)


def _context(ranked: list[dict], sector_map: dict) -> str:
    enriched = []
    for row in ranked:
        thesis_key = sector_map.get(row["ticker"], "")
        enriched.append({
            **row,
            "sector_thesis": SECTOR_THESES.get(thesis_key, ""),
            "value_score": round(value_score(row), 1),
        })
    return json.dumps({"candidates": enriched}, ensure_ascii=False, indent=2, default=str)


def run_hidden_value(client, ranked: list[dict], sector_map: dict) -> str:
    # Focus the reasoning on the strongest ~10 by score to keep it grounded.
    shortlist = ranked[:10]
    context = "CANDIDATE FUNDAMENTALS:\n" + _context(shortlist, sector_map)
    brief = reason(
        client,
        model=config.ANALYST_MODEL,
        system=ANALYST_SYSTEM,
        user=context,
        max_tokens=config.ANALYST_MAX_TOKENS,
        temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client,
        model=config.SYNTHESIS_MODEL,
        system=WRITER_SYSTEM,
        user=context + "\n\nANALYST BRIEF:\n" + (brief or "(none)")
        + f"\n\nNow write the Hidden Value post introducing the best "
          f"{config.HIDDEN_VALUE_MAX_NAMES} names.",
        max_tokens=config.DISCOVERY_MAX_TOKENS,
        temperature=config.SYNTHESIS_TEMPERATURE,
    )
