"""
AI Bubble Index (weekly, Friday) — a multi-pillar froth gauge.

Methodology blends the professional frameworks:
  • Fidelity's "5 signs" — valuation vs history/dot-com, capex sustainability,
    concentration, rate regime.
  • Exponential View / boomorbubble.ai gauges — economic strain (AI capex / GDP),
    valuation heat, funding quality; "2 red pillars = bubble conditions".
  • CEPR / AI Bubble Monitor — valuation, concentration, momentum (RSI/vol),
    systemic risk; a multi-signal composite.

Five pillars, each scored 0-100 (higher = frothier) with a green/amber/red status:
  1. valuation      — avg forward P/E + PEG of the AI leaders
  2. concentration  — cap-weight vs equal-weight S&P (SPY vs RSP, 6m)
  3. exuberance     — price momentum: RSI, % above 200EMA, Bollinger pos, breadth
  4. capex_gdp      — AI capex as a % of US GDP (economic strain)
  5. credit         — high-yield credit spread (tight = complacency/systemic froth)

The composite is the weighted average over whichever pillars have data (weights
renormalize). Numbers are computed here, not by the model, so it's a real,
repeatable index. compute_index() is pure (testable); main.py gathers the inputs.
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
_STATUS_COLOR = {"green": "#31D09D", "amber": "#F4C95D", "red": "#FF5A7A"}


def _clip(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _interp(x, xs, ys):
    """Piecewise-linear map of x through the (xs, ys) breakpoints."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _status(score: float) -> str:
    return "green" if score < 45 else "amber" if score < 68 else "red"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---- pillars (each returns dict or None) -----------------------------

def _valuation_pillar(valuations: list) -> dict | None:
    fpes = [v.get("forward_pe") for v in valuations if (v.get("forward_pe") or 0) > 0]
    pegs = [v.get("peg") for v in valuations if (v.get("peg") or 0) > 0]
    avg_fpe = _mean(fpes)
    if avg_fpe is None:
        return None
    score = _interp(avg_fpe, [15, 25, 35, 50], [20, 50, 80, 98])
    avg_peg = _mean(pegs)
    if avg_peg is not None:
        score = 0.8 * score + 0.2 * _interp(avg_peg, [1, 2, 3, 4], [30, 55, 80, 95])
    detail = f"avg fwd P/E {avg_fpe:.0f}" + (f", PEG {avg_peg:.1f}" if avg_peg else "")
    return {"score": round(score), "detail": detail}


def _concentration_pillar(spy_ret, rsp_ret) -> dict | None:
    if spy_ret is None or rsp_ret is None:
        return None
    spread = spy_ret - rsp_ret
    score = _interp(spread, [-2, 0, 6, 12, 20], [25, 40, 65, 82, 95])
    return {"score": round(score),
            "detail": f"SPY {spy_ret:+.0f}% vs RSP {rsp_ret:+.0f}% (6m breadth)"}


def _exuberance_pillar(tech_map: dict) -> dict | None:
    rsis, exts, bbpos, up, n = [], [], [], 0, 0
    for t in tech_map.values():
        if not t or not t.get("available"):
            continue
        n += 1
        price, ema200 = t.get("last_price"), t.get("ema200")
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
        return None
    avg_rsi = _mean(rsis) or 50
    avg_ext = _mean(exts) or 0
    avg_bb = _mean(bbpos) or 50
    breadth = up / n * 100
    score = 0.30 * _clip(avg_rsi) + 0.30 * _clip(50 + avg_ext * 1.5) + 0.20 * _clip(avg_bb) + 0.20 * breadth
    return {"score": round(score),
            "detail": f"avg RSI {avg_rsi:.0f}, {avg_ext:+.0f}% vs 200EMA, {breadth:.0f}% wkly up",
            "extra": {"avg_rsi": round(avg_rsi, 1), "avg_pct_above_200ema": round(avg_ext, 1),
                      "pct_weekly_uptrend": round(breadth, 0)}}


def _capex_gdp_pillar(capex_gdp_pct) -> dict | None:
    if capex_gdp_pct is None:
        return None
    score = _interp(capex_gdp_pct, [0.4, 0.8, 1.2, 2.0, 3.0], [25, 45, 62, 85, 98])
    return {"score": round(score), "detail": f"AI capex ≈ {capex_gdp_pct:.1f}% of US GDP"}


def _credit_pillar(hy_spread_pct) -> dict | None:
    if hy_spread_pct is None:
        return None
    # Inverse: a TIGHT spread = complacency / risk-on = frothy; wide = stress.
    score = _interp(hy_spread_pct, [2.5, 3.5, 5, 7, 9], [85, 68, 50, 30, 18])
    return {"score": round(score), "detail": f"high-yield spread {hy_spread_pct:.1f}%"}


def compute_index(inputs: dict) -> dict:
    """Build the multi-pillar index from gathered inputs (see module docstring)."""
    raw = {
        "valuation": _valuation_pillar(inputs.get("valuations") or []),
        "concentration": _concentration_pillar(
            (inputs.get("concentration") or {}).get("spy_ret"),
            (inputs.get("concentration") or {}).get("rsp_ret")),
        "exuberance": _exuberance_pillar(inputs.get("tech_map") or {}),
        "capex_gdp": _capex_gdp_pillar(inputs.get("capex_gdp_pct")),
        "credit": _credit_pillar(inputs.get("hy_spread_pct")),
    }
    pillars, wsum, sscore = [], 0.0, 0.0
    for name, p in raw.items():
        if not p:
            continue
        w = config.BUBBLE_PILLAR_WEIGHTS.get(name, 0)
        status = _status(p["score"])
        pillars.append({"name": name, "score": p["score"], "status": status,
                        "detail": p["detail"], "weight": w})
        wsum += w
        sscore += w * p["score"]
    if not pillars:
        return {}
    score = round(sscore / wsum)
    label = next(z[2] for z in ZONES if z[0] <= score < z[1])
    red = sum(1 for p in pillars if p["status"] == "red")
    exu = raw.get("exuberance") or {}
    return {
        "score": score,
        "label": label,
        "red_pillars": red,
        "bubble_signal": red >= 2,     # boomorbubble rule: 2 red pillars = bubble conditions
        "pillars": pillars,
        "components": exu.get("extra", {}),
    }


# ---- chart -----------------------------------------------------------

def gauge_chart(index: dict) -> str | None:
    if not index:
        return None
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    import chart_generator as cg

    score = index["score"]
    pillars = index["pillars"]
    fig = plt.figure(figsize=(11, 6.4), facecolor=cg.BACKGROUND)
    gs = GridSpec(2, 1, height_ratios=[1.0, 1.5], hspace=0.5)

    ax = fig.add_subplot(gs[0]); ax.set_facecolor(cg.BACKGROUND)
    ax.set_xlim(0, 100); ax.set_ylim(0, 1); ax.axis("off")
    for lo, hi, _l, color in ZONES:
        ax.barh(0.5, hi - lo, left=lo, height=0.30, color=color, alpha=0.9)
    ax.plot([score, score], [0.28, 0.72], color=cg.TEXT, linewidth=3, zorder=5)
    ax.scatter([score], [0.5], color=cg.TEXT, s=70, zorder=6)
    for x in (0, 25, 50, 75, 100):
        ax.text(x, 0.05, str(x), color=cg.MUTED, fontsize=9, ha="center")

    axp = fig.add_subplot(gs[1]); axp.set_facecolor(cg.BACKGROUND)
    axp.set_xlim(0, 100)
    names = [p["name"].replace("_", "/").title() for p in pillars]
    vals = [p["score"] for p in pillars]
    colors = [_STATUS_COLOR[p["status"]] for p in pillars]
    axp.barh(names, vals, color=colors, height=0.6, alpha=0.92)
    for y, p in enumerate(pillars):
        axp.text(min(p["score"] + 1.5, 99), y, f" {p['score']}  {p['detail']}",
                 va="center", ha="left", color=cg.TEXT, fontsize=8.5)
    axp.set_xlim(0, 100)
    axp.tick_params(colors=cg.MUTED, labelsize=9)
    for s in axp.spines.values():
        s.set_color(cg.GRID)
    axp.grid(True, axis="x", alpha=0.3)

    fig.text(0.5, 0.955, "AI BUBBLE INDEX", color=cg.TEXT, fontsize=19, fontweight="bold", ha="center")
    signal = f" · {index['red_pillars']} red pillar(s)" + (" · BUBBLE SIGNAL" if index["bubble_signal"] else "")
    fig.text(0.5, 0.905, f"{int(score)} / 100 · {index['label']}{signal}",
             color=cg.TEXT, fontsize=13, fontweight="bold", ha="center")
    fig.subplots_adjust(left=0.16, right=0.96, top=0.87, bottom=0.08)
    os.makedirs(config.CHART_DIR, exist_ok=True)
    out = os.path.join(config.CHART_DIR, "bubble_index.png")
    fig.savefig(out, dpi=config.CHART_DPI, facecolor=cg.BACKGROUND, bbox_inches="tight")
    plt.close(fig)
    return out


# ---- write-up (Pro reasons, Chat writes) -----------------------------

WRITER_SYSTEM = """You write the weekly AI BUBBLE INDEX post for a finance channel.
You are given a MULTI-PILLAR index (0-100 composite + a green/amber/red status per
pillar: valuation, concentration, exuberance, capex/GDP, credit) and the "2 red =
bubble" flag. Emoji-rich, sharp, honest.

Shape (under 900 characters):
🫧 AI BUBBLE INDEX — <score>/100 (<zone>)
📊 One line summarizing the composite + how many pillars are red.
🔴/🟡/🟢 2-3 lines calling out the hottest pillars and the coolest, with their
   numbers (e.g. valuation avg fwd P/E, capex/GDP %, credit spread, concentration).
🧠 One honest line: is this euphoria or a justified build-out?
GROUNDING: use only the provided numbers; never invent figures. Plain text, no
markdown headers/asterisks, no disclaimer."""


def run_bubble_index(client, index: dict) -> str:
    ctx = json.dumps(index, default=str)
    brief = reason(
        client, model=config.ANALYST_MODEL,
        system="You are a markets strategist. From this multi-pillar AI bubble index, "
               "note in 2-4 lines: the overall froth level, which pillars are hottest vs "
               "coolest and why, and whether it reads as euphoria or a justified build-out. "
               "Reference Fidelity/Exponential-View style reasoning. Use only the numbers given.",
        user=ctx, max_tokens=config.ANALYST_MAX_TOKENS, temperature=config.ANALYST_TEMPERATURE,
    )
    return chat(
        client, model=config.SYNTHESIS_MODEL, system=WRITER_SYSTEM,
        user="INDEX:\n" + ctx + "\n\nANALYST NOTES:\n" + (brief or "(none)")
             + "\n\nNow write the post.",
        max_tokens=config.DISCOVERY_MAX_TOKENS, temperature=config.SYNTHESIS_TEMPERATURE,
    )
