"""
AI Bubble Index (weekly, Friday) — a proprietary froth gauge for the AI leadership.

A 0-100 composite built from grounded technicals across config.BUBBLE_INDEX_TICKERS:
  • momentum      — average RSI (hot = frothy)
  • extension     — average % above the 200-day EMA (stretched = frothy)
  • band position — average position inside the Bollinger channel (near upper = frothy)
  • breadth       — share of names in a weekly uptrend
Rendered as a meter, with a short Pro-reasoned / Chat-written read. The number is
computed here (not by the model), so it's a real, repeatable index.
"""

from __future__ import annotations

import json
import os

import config
from llm_client import chat, reason

ZONES = [
    (0, 35, "COOL / WASHED OUT", "#31D09D"),
    (35, 55, "BALANCED", "#8FD14F"),
    (55, 70, "WARM / EXTENDED", "#F4C95D"),
    (70, 85, "FROTHY", "#FF9F45"),
    (85, 101, "EUPHORIC / BUBBLE", "#FF5A7A"),
]


def _clip(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def compute_index(tech_map: dict) -> dict:
    """tech_map: {ticker: technicals.summarize(...)} for the AI leaders."""
    rsis, exts, bbpos, up = [], [], [], 0
    n = 0
    for t in tech_map.values():
        if not t or not t.get("available"):
            continue
        n += 1
        price = t.get("last_price")
        ema200 = t.get("ema200")
        if t.get("rsi") is not None:
            rsis.append(t["rsi"])
        if price and ema200:
            exts.append((price / ema200 - 1) * 100)
        bu, bl = t.get("bb_upper"), t.get("bb_lower")
        if price and bu and bl and bu > bl:
            bbpos.append(_clip((price - bl) / (bu - bl) * 100))
        if (t.get("trend_multi_timeframe") or {}).get("weekly") == "up":
            up += 1
    if n == 0:
        return {}
    avg_rsi = sum(rsis) / len(rsis) if rsis else 50
    avg_ext = sum(exts) / len(exts) if exts else 0
    avg_bb = sum(bbpos) / len(bbpos) if bbpos else 50
    breadth = up / n * 100
    # scale each to 0-100 "froth"
    s_rsi = _clip(avg_rsi)                       # RSI already 0-100
    s_ext = _clip(50 + avg_ext * 1.5)            # +33% above 200EMA ≈ 100
    s_bb = _clip(avg_bb)
    s_breadth = _clip(breadth)
    score = round(0.30 * s_rsi + 0.30 * s_ext + 0.20 * s_bb + 0.20 * s_breadth, 0)
    label = next(z[2] for z in ZONES if z[0] <= score < z[1])
    return {
        "score": score,
        "label": label,
        "n": n,
        "components": {
            "avg_rsi": round(avg_rsi, 1),
            "avg_pct_above_200ema": round(avg_ext, 1),
            "avg_bollinger_position": round(avg_bb, 0),
            "pct_weekly_uptrend": round(breadth, 0),
        },
    }


def gauge_chart(index: dict) -> str | None:
    if not index:
        return None
    import matplotlib.pyplot as plt
    import chart_generator as cg

    score = index["score"]
    fig, ax = plt.subplots(figsize=(11, 4.4), facecolor=cg.BACKGROUND)
    ax.set_facecolor(cg.BACKGROUND)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis("off")
    for lo, hi, _lab, color in ZONES:
        ax.barh(0.5, hi - lo, left=lo, height=0.28, color=color, alpha=0.9)
    # marker
    ax.plot([score, score], [0.30, 0.70], color=cg.TEXT, linewidth=3, zorder=5)
    ax.scatter([score], [0.5], color=cg.TEXT, s=60, zorder=6)
    for x in (0, 25, 50, 75, 100):
        ax.text(x, 0.16, str(x), color=cg.MUTED, fontsize=9, ha="center")
    # No emoji in chart text — PT Serif has no emoji glyphs (they render as tofu).
    fig.text(0.5, 0.90, "AI BUBBLE INDEX", color=cg.TEXT, fontsize=20,
             fontweight="bold", ha="center")
    fig.text(0.5, 0.70, f"{int(score)} / 100 · {index['label']}", color=cg.TEXT,
             fontsize=15, fontweight="bold", ha="center")
    c = index["components"]
    fig.text(0.5, 0.06,
             f"avg RSI {c['avg_rsi']} · {c['avg_pct_above_200ema']:+.0f}% vs 200EMA · "
             f"BB pos {int(c['avg_bollinger_position'])} · {int(c['pct_weekly_uptrend'])}% in weekly uptrend",
             color=cg.MUTED, fontsize=10, ha="center")
    fig.subplots_adjust(left=0.06, right=0.94, top=0.62, bottom=0.2)
    os.makedirs(config.CHART_DIR, exist_ok=True)
    out = os.path.join(config.CHART_DIR, "bubble_index.png")
    fig.savefig(out, dpi=config.CHART_DPI, facecolor=cg.BACKGROUND, bbox_inches="tight")
    plt.close(fig)
    return out


WRITER_SYSTEM = """You write the weekly AI BUBBLE INDEX post for a finance channel.
You are given the computed index (0-100), its zone label, and the components, plus
which names are most stretched. Emoji-rich, sharp, and honest.

Shape (under 850 characters):
🫧 AI BUBBLE INDEX — <score>/100 (<zone>)
📊 One line reading the components (RSI, extension vs 200EMA, breadth).
🔥 Which names look most stretched vs which look reasonable.
🧠 One honest line: froth vs fundamentals — is this euphoria or justified?
GROUNDING: use only the provided numbers; never invent figures. Plain text, no
markdown headers/asterisks, no disclaimer."""


def run_bubble_index(client, index: dict, tech_map: dict) -> str:
    stretched = sorted(
        [{"ticker": k, "rsi": v.get("rsi"),
          "pct_above_200ema": round((v["last_price"] / v["ema200"] - 1) * 100, 1)
          if v.get("last_price") and v.get("ema200") else None}
         for k, v in tech_map.items() if v and v.get("available")],
        key=lambda d: d["rsi"] or 0, reverse=True,
    )
    ctx = json.dumps({"index": index, "names": stretched}, default=str)
    brief = reason(
        client, model=config.ANALYST_MODEL,
        system="You are a markets strategist. From this AI-froth index and the per-name "
               "stretch data, note in 2-4 lines how frothy the AI leadership is, which "
               "names are most/least stretched, and whether it's euphoria or justified. "
               "Use only the provided numbers.",
        user=ctx, max_tokens=config.ANALYST_MAX_TOKENS, temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client, model=config.SYNTHESIS_MODEL, system=WRITER_SYSTEM,
        user="INDEX:\n" + ctx + "\n\nANALYST NOTES:\n" + (brief or "(none)")
             + "\n\nNow write the post.",
        max_tokens=config.DISCOVERY_MAX_TOKENS, temperature=config.SYNTHESIS_TEMPERATURE,
    )
