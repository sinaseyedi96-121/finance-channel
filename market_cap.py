"""
Market-Cap Top-20 leaderboard — an EVENT-DRIVEN post.

Checked after each news run, but only published when the top-20 ORDERING
actually changed since the last stored ranking (rank swaps, new entries,
drop-outs). A static leaderboard reposted daily is noise; a reshuffle —
"NVDA overtakes AAPL" — is news. The previous ordering lives in
post_history.json under the "market_cap_top20" marker.

Everything here is mechanical: caps come from yfinance fundamentals, the
caption is assembled from the fetched numbers (no LLM), so there is nothing
to hallucinate and nothing for the grounding gate to check.
"""

from __future__ import annotations

import datetime as dt
import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

import config
from chart_generator import BACKGROUND, PANEL, GRID, TEXT, MUTED, UP, DOWN, EMA_FAST_C, EMA_LONG_C
from ingest import fundamentals


def fetch_ranking() -> list[dict]:
    """Top-N companies by market cap: [{"ticker", "market_cap"}, ...] desc."""
    rows = fundamentals.fetch(config.MARKET_CAP_UNIVERSE)
    with_cap = [r for r in rows if r.get("market_cap")]
    with_cap.sort(key=lambda r: r["market_cap"], reverse=True)
    return [{"ticker": r["ticker"], "market_cap": float(r["market_cap"])}
            for r in with_cap[: config.MARKET_CAP_TOP_N]]


def compare(prev_order: list[str] | None, new_order: list[str]) -> dict | None:
    """Diff two orderings. Returns None when nothing moved (=> don't post).
    Positions are 1-based for display."""
    if prev_order is None:
        return {"initial": True, "moved": [], "entered": [], "exited": []}
    if prev_order == new_order:
        return None
    prev_pos = {t: i + 1 for i, t in enumerate(prev_order)}
    new_pos = {t: i + 1 for i, t in enumerate(new_order)}
    moved = [(t, prev_pos[t], new_pos[t]) for t in new_order
             if t in prev_pos and prev_pos[t] != new_pos[t]]
    return {
        "initial": False,
        "moved": moved,
        "entered": [t for t in new_order if t not in prev_pos],
        "exited": [t for t in prev_order if t not in new_pos],
    }


def _fmt_cap(value: float) -> str:
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    return f"${value / 1e9:.0f}B"


def _mover_mark(ticker: str, changes: dict) -> tuple[str, str] | None:
    """(marker_text, color) for a ticker's rank change, None if unchanged."""
    if ticker in changes["entered"]:
        return "NEW", EMA_LONG_C
    for t, old, new in changes["moved"]:
        if t == ticker:
            delta = old - new                      # up the board = positive
            return (f"+{delta}", UP) if delta > 0 else (f"{delta}", DOWN)
    return None


def ranking_chart(ranked: list[dict], changes: dict) -> str:
    """Horizontal bar leaderboard in the house style. One hue for the bars
    (magnitude); rank moves carried by explicit text markers (+2 / -1 / NEW),
    never by color alone."""
    os.makedirs(config.CHART_DIR, exist_ok=True)
    out_path = os.path.join(config.CHART_DIR, "market_cap_top20.png")

    tickers = [r["ticker"] for r in ranked]
    caps_t = [r["market_cap"] / 1e12 for r in ranked]

    fig, ax = plt.subplots(figsize=(10.5, 11.5))
    fig.patch.set_facecolor(BACKGROUND)
    ax.set_facecolor(PANEL)

    y = range(len(ranked))
    ax.barh(y, caps_t, height=0.62, color=EMA_FAST_C, alpha=0.78, zorder=2)
    ax.invert_yaxis()                              # rank 1 on top

    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{i + 1:>2}  {t}" for i, t in enumerate(tickers)],
                       color=TEXT, fontsize=11, fontweight="bold")
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.set_xlabel("MARKET CAP · USD TRILLIONS", color=MUTED, fontsize=9, fontweight="bold")
    ax.grid(axis="x", color=GRID, linestyle="--", alpha=0.45, zorder=0)
    ax.grid(axis="y", visible=False)
    for spine in ax.spines.values():
        spine.set_color(GRID)

    x_pad = max(caps_t) * 0.012
    for i, row in enumerate(ranked):
        label = _fmt_cap(row["market_cap"])
        ax.text(caps_t[i] + x_pad, i, label, va="center", ha="left",
                color=TEXT, fontsize=10)
        mark = _mover_mark(row["ticker"], changes)
        if mark and not changes["initial"]:
            text, color = mark
            ax.text(caps_t[i] + x_pad + max(caps_t) * 0.085, i, text,
                    va="center", ha="left", color=color, fontsize=10, fontweight="bold")
    ax.set_xlim(0, max(caps_t) * 1.22)             # room for the labels

    as_of = dt.date.today().isoformat()
    fig.subplots_adjust(left=0.14, right=0.96, top=0.90, bottom=0.06)
    fig.text(0.14, 0.965, "MARKET CAP TOP 20", color=TEXT, fontsize=20,
             fontweight="bold", ha="left", va="center")
    subtitle = ("INAUGURAL LEADERBOARD" if changes["initial"]
                else "RANKING RESHUFFLE — moves marked")
    fig.text(0.14, 0.925, subtitle, color=MUTED, fontsize=10, ha="left", va="center")
    fig.text(0.96, 0.965, "LEADERBOARD", color=EMA_FAST_C, fontsize=9,
             fontweight="bold", ha="right", va="center")
    fig.text(0.96, 0.925, f"AS OF {as_of}  ·  YFINANCE", color=MUTED, fontsize=9,
             ha="right", va="center")

    fig.savefig(out_path, dpi=config.CHART_DPI, facecolor=BACKGROUND, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _detail_tickers(changes: dict) -> list[str]:
    """Tickers worth a one-line fundamentals blurb in the expandable detail:
    every entrant/exit, plus the movers already called out in the visible
    caption (build_caption shows at most the first 6)."""
    moved = [t for t, _old, _new in changes["moved"][:6]]
    tickers, seen = [], set()
    for t in changes["entered"] + changes["exited"] + moved:
        if t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def _blurb(row: dict) -> str:
    """One mechanical line of context for a ticker, straight from fundamentals —
    whatever fields are available (yfinance coverage varies by name)."""
    parts = []
    if row.get("sector"):
        parts.append(row["sector"])
    if row.get("trailing_pe"):
        parts.append(f"P/E {row['trailing_pe']:.0f}")
    if row.get("revenue_growth_pct") is not None:
        parts.append(f"rev {row['revenue_growth_pct']:+.0f}%")
    if row.get("pct_of_52w_range") is not None:
        parts.append(f"{row['pct_of_52w_range']:.0f}% of 52w range")
    return " · ".join(parts)


def build_detail(changes: dict) -> str:
    """Expandable-quote detail for the leaderboard caption: one mechanical line
    per notable mover, sourced straight from fetched fundamentals — same
    "nothing to hallucinate" guarantee as the rest of this file, no LLM call."""
    if changes["initial"]:
        return ""
    tickers = _detail_tickers(changes)
    if not tickers:
        return ""
    rows = {r["ticker"]: r for r in fundamentals.fetch(tickers)}
    lines = []
    for t in tickers:
        row = rows.get(t)
        blurb = _blurb(row) if row else ""
        if not blurb:
            continue
        tag = "NEW" if t in changes["entered"] else ("OUT" if t in changes["exited"] else "MOVED")
        lines.append(f"{t} ({tag}): {blurb}")
    return "\n".join(lines)


def build_caption(ranked: list[dict], changes: dict) -> str:
    """Mechanical caption — every figure comes straight from the fetched caps."""
    top3 = "  ".join(
        f"{medal} {r['ticker']} {_fmt_cap(r['market_cap'])}"
        for medal, r in zip(("🥇", "🥈", "🥉"), ranked[:3])
    )
    lines = ["🏆 Market Cap Top 20 — " +
             ("the inaugural leaderboard" if changes["initial"] else "ranking reshuffle"),
             top3]
    if changes["moved"]:
        pos = {r["ticker"]: i + 1 for i, r in enumerate(ranked)}
        moves = []
        for t, old, new in changes["moved"][:6]:
            note = f"{t} #{old}→#{new}"
            if new < old:
                overtaken = next((x["ticker"] for x in ranked if pos[x["ticker"]] == new + 1), None)
                if overtaken:
                    note += f" (past {overtaken})"
            moves.append(note)
        lines.append("🔀 Moves: " + " · ".join(moves))
    if changes["entered"]:
        lines.append("🆕 In: " + ", ".join(changes["entered"]))
    if changes["exited"]:
        lines.append("👋 Out: " + ", ".join(changes["exited"]))
    lines.append(f"📊 Top-20 combined: {_fmt_cap(sum(r['market_cap'] for r in ranked))}")
    return "\n".join(lines)
