"""
Conviction Scorecard (weekly, Saturday) — the accountability engine.

Every news post carries a Verdict (Bullish/Neutral/Bearish + a 1-10 conviction).
main.py logs each one with the price and levels at post time (state["calls"]).
This module grades the matured calls against current price and produces a weekly
"report card": hit rate, average return, best/worst call — as a bar chart plus a
short Pro-reasoned / Chat-written recap. Trust is the whole point, so the numbers
are computed here, not by the model.
"""

from __future__ import annotations

import datetime as dt
import os
import re

import config
import reviewer
from llm_client import chat, reason

_LEAN_RE = re.compile(r"\b(bullish|bearish|neutral)\b", re.IGNORECASE)
_CONV_RE = re.compile(r"(\d{1,2})\s*/\s*10")


def parse_verdict(caption: str) -> tuple[str | None, int | None]:
    """Pull (lean, conviction) out of a published caption's verdict line."""
    lean = None
    # Prefer a lean near the verdict emoji/word if present.
    tail = caption
    idx = caption.find("Verdict")
    if idx != -1:
        tail = caption[idx:]
    m = _LEAN_RE.search(tail) or _LEAN_RE.search(caption)
    if m:
        lean = m.group(1).lower()
    c = _CONV_RE.search(tail) or _CONV_RE.search(caption)
    conviction = int(c.group(1)) if c else None
    return lean, conviction


def _correct(lean: str, ret_pct: float) -> bool:
    if lean == "bullish":
        return ret_pct > 0
    if lean == "bearish":
        return ret_pct < 0
    return abs(ret_pct) < 3.0            # neutral = "roughly flat" was right


def grade(calls: list, price_map: dict, today: dt.date) -> dict:
    """Grade calls that are matured (>= MIN_AGE days) and within the lookback."""
    graded = []
    for c in calls:
        try:
            d = dt.date.fromisoformat(c["date"])
        except (KeyError, ValueError):
            continue
        age = (today - d).days
        if age < config.SCORECARD_MIN_AGE_DAYS or age > config.SCORECARD_LOOKBACK_DAYS:
            continue
        now = price_map.get(c.get("ticker"))
        entry = c.get("price")
        if not now or not entry:
            continue
        ret = (now / entry - 1) * 100
        lean = c.get("lean") or "neutral"
        graded.append({
            "ticker": c.get("ticker"),
            "lean": lean,
            "conviction": c.get("conviction"),
            "entry": entry,
            "now": round(now, 2),
            "return_pct": round(ret, 2),
            "days": age,
            "correct": _correct(lean, ret),
        })
    n = len(graded)
    hits = sum(1 for g in graded if g["correct"])
    avg = round(sum(g["return_pct"] for g in graded) / n, 2) if n else 0.0
    # Directional return: credit longs with +ret, shorts with -ret.
    dir_returns = [g["return_pct"] if g["lean"] != "bearish" else -g["return_pct"] for g in graded]
    avg_dir = round(sum(dir_returns) / n, 2) if n else 0.0
    return {
        "n": n,
        "hit_rate_pct": round(hits / n * 100, 0) if n else 0.0,
        "avg_move_pct": avg,
        "avg_directional_pct": avg_dir,
        "best": max(graded, key=lambda g: g["return_pct"]) if graded else None,
        "worst": min(graded, key=lambda g: g["return_pct"]) if graded else None,
        "graded": sorted(graded, key=lambda g: g["return_pct"], reverse=True),
    }


def scorecard_chart(stats: dict) -> str | None:
    """Horizontal bar chart of per-call directional returns, green=correct."""
    graded = stats.get("graded") or []
    if not graded:
        return None
    import matplotlib.pyplot as plt
    import chart_generator as cg  # reuse the dark theme + PT Serif setup

    rows = sorted(graded, key=lambda g: g["return_pct"])
    # Include each call's age so two same-ticker/same-lean calls read as distinct
    # rows. Critically, plot at explicit NUMERIC y-positions rather than passing
    # the label strings to barh(): duplicate label strings would otherwise be
    # treated as one category, collapsing bars onto a shared row while the value
    # labels below (indexed 0..N-1) spill above the axes.
    labels = [f"${g['ticker']} {g['lean'][:4]}"
              + (f" · {g['days']}d" if g.get("days") is not None else "")
              for g in rows]
    vals = [g["return_pct"] for g in rows]
    colors = [cg.UP if g["correct"] else cg.DOWN for g in rows]
    y = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(11, max(3.5, 0.5 * len(rows) + 1.6)), facecolor=cg.BACKGROUND)
    ax.set_facecolor(cg.PANEL)
    ax.barh(y, vals, color=colors, height=0.62, alpha=0.92)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.axvline(0, color=cg.MUTED, linewidth=0.9)
    for yi, v in zip(y, vals):
        ax.text(v + (0.4 if v >= 0 else -0.4), yi, f"{v:+.1f}%", va="center",
                ha="left" if v >= 0 else "right", color=cg.TEXT, fontsize=9, fontweight="bold")
    ax.set_xlabel("RETURN SINCE CALL (%)", color=cg.MUTED, fontsize=9, fontweight="bold")
    ax.tick_params(colors=cg.MUTED, labelsize=9)
    for s in ax.spines.values():
        s.set_color(cg.GRID)
    ax.grid(True, axis="x", alpha=0.35)
    fig.text(0.06, 0.955, "CONVICTION SCORECARD", color=cg.TEXT, fontsize=18, fontweight="bold")
    fig.text(0.06, 0.91,
             f"{int(stats['n'])} calls · {int(stats['hit_rate_pct'])}% hit rate · "
             f"{stats['avg_directional_pct']:+.1f}% avg (last {config.SCORECARD_LOOKBACK_DAYS}d)",
             color=cg.MUTED, fontsize=10)
    fig.subplots_adjust(left=0.16, right=0.95, top=0.86, bottom=0.12)
    os.makedirs(config.CHART_DIR, exist_ok=True)
    out = os.path.join(config.CHART_DIR, "scorecard.png")
    fig.savefig(out, dpi=config.CHART_DPI, facecolor=cg.BACKGROUND, bbox_inches="tight")
    plt.close(fig)
    return out


WRITER_SYSTEM = """You write the weekly CONVICTION SCORECARD post for a finance
channel — the honest report card on how the channel's own calls played out. You
are given the graded stats (hit rate, average return, best/worst). Emoji-rich,
confident but HONEST (owning misses builds trust).

Shape (under 850 characters):
🏆 CONVICTION SCORECARD — <period>
📊 One line: N calls, hit rate, average move.
🥇 Best call + its return. 🧊 Worst call + its return.
🧠 One line of insight: what the tape rewarded/punished this week.
Keep it grounded in the numbers provided; never invent figures. Plain text, no
markdown headers/asterisks, no disclaimer."""


def run_scorecard(client, stats: dict) -> str:
    import json
    ctx = json.dumps(stats, default=str)
    brief = reason(
        client, model=config.ANALYST_MODEL,
        system="You are a performance analyst. From these graded trade-call stats, "
               "note in 2-4 lines what worked, what didn't, and the honest takeaway. "
               "Use only the provided numbers.",
        user=ctx, max_tokens=config.ANALYST_MAX_TOKENS, temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client, model=config.SYNTHESIS_MODEL, system=WRITER_SYSTEM,
        user="STATS:\n" + ctx + "\n\nANALYST NOTES:\n" + (brief or "(none)")
             + reviewer.notes_block("scorecard") + "\n\nNow write the scorecard post.",
        max_tokens=config.DISCOVERY_MAX_TOKENS, temperature=config.SYNTHESIS_TEMPERATURE,
    )
