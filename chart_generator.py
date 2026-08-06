"""
Render a social-first technical chart for a stock — candles + Bollinger Bands +
EMA 20/50/200 + pivot support/resistance + an RSI panel with 30/70 lines.

Ported from the crypto channel's chart_generator so the two channels read
identically. Input is an *enriched* daily OHLCV DataFrame (technicals.enrich)
plus the levels dict from technicals.find_key_levels.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import mplfinance as mpf

import config

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_FAMILY = "PT Serif"
for _font_file in ("PTSerif-Regular.ttf", "PTSerif-Bold.ttf"):
    fm.fontManager.addfont(os.path.join(FONT_DIR, _font_file))
# Set unconditionally (exactly as the crypto channel does) so the charts render
# in PT Serif, not the matplotlib default sans-serif.
plt.rcParams["font.family"] = FONT_FAMILY

BACKGROUND = "#08111F"
PANEL = "#0D192A"
GRID = "#26364B"
TEXT = "#E8EEF7"
MUTED = "#8EA0B8"
UP = "#00C2A8"
DOWN = "#FF5A7A"
EMA_FAST_C = "#31B7FF"
EMA_SLOW_C = "#B98CFF"
EMA_LONG_C = "#F4C95D"
BB = "#8292A8"
SUPPORT = "#31D09D"
RESISTANCE = "#FF7A90"


def _style():
    market_colors = mpf.make_marketcolors(
        up=UP, down=DOWN, edge="inherit", wick="inherit", volume="inherit"
    )
    return mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=market_colors,
        facecolor=PANEL,
        figcolor=BACKGROUND,
        gridcolor=GRID,
        gridstyle="--",
        y_on_right=True,
        rc={
            "axes.edgecolor": GRID,
            "axes.labelcolor": MUTED,
            "font.family": FONT_FAMILY,   # mpf's rc overrides global rcParams during plot
            "font.size": 10,
            "text.color": TEXT,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
        },
    )


def _compact_number(value: float, _position=None) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _headline(last, levels: dict) -> str:
    price = float(last["Close"])
    zone = float(levels.get("zone_width", 0))
    if price > levels["resistance"] + zone:
        return "RESISTANCE BREAKOUT"
    if price < levels["support"] - zone:
        return "SUPPORT BREAKDOWN"
    if last["ema_fast"] > last["ema_slow"] and price > last["ema_slow"]:
        return "BULLISH MOMENTUM"
    if last["ema_fast"] < last["ema_slow"] and price < last["ema_slow"]:
        return "BEARS IN CONTROL"
    return "DECISION ZONE"


def _price_label(ax, value: float, label: str, color: str) -> None:
    # Anchored near the LEFT edge, over the older candles — the right edge is
    # the most recent price action and a label box sitting there covers it up.
    ax.text(
        0.008, value, f" {label}  {value:,.2f} ",
        transform=ax.get_yaxis_transform(),
        ha="left", va="center", color=TEXT, fontsize=9, fontweight="bold",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": color, "edgecolor": color, "alpha": 0.88},
        zorder=8,
    )


def generate_chart(df, ticker: str, levels: dict, display_name: str | None = None,
                   timeframe_label: str = config.LONG_TF_LABEL,
                   display_candles: int | None = None) -> str:
    """Render the technical chart and return the saved PNG path. `df` must be
    enriched (technicals.enrich). `display_name` overrides the chart title for
    non-ticker instruments (e.g. "Gold" instead of "$GC=F"). `timeframe_label`
    is shown in the header (e.g. "DAILY" or "HOURLY"); `display_candles`
    overrides how many trailing candles are rendered (defaults to
    config.CHART_DISPLAY_CANDLES)."""
    os.makedirs(config.CHART_DIR, exist_ok=True)
    safe = ticker.replace("^", "").replace("=", "_").replace("/", "_")
    out_path = os.path.join(config.CHART_DIR, f"{safe}_{timeframe_label.lower()}.png")
    display = df.tail(display_candles or config.CHART_DISPLAY_CANDLES).copy()

    add_plots = [
        mpf.make_addplot(display["bb_upper"], color=BB, width=0.7, linestyle="--", alpha=0.65),
        mpf.make_addplot(display["bb_lower"], color=BB, width=0.7, linestyle="--", alpha=0.65),
        mpf.make_addplot(display["ema_fast"], color=EMA_FAST_C, width=1.4),
        mpf.make_addplot(display["ema_slow"], color=EMA_SLOW_C, width=1.4),
        mpf.make_addplot(display["ema_long"], color=EMA_LONG_C, width=1.2, alpha=0.9),
    ]

    # A level is only drawn SOLID when enough pivots actually touched it; a
    # single-touch fallback (range high/low) renders dashed and thinner so the
    # chart never oversells an unvalidated line as real resistance/support.
    solid_support = levels.get("support_touches", 1) >= config.MIN_LEVEL_TOUCHES
    solid_resistance = levels.get("resistance_touches", 1) >= config.MIN_LEVEL_TOUCHES
    hlines = {
        "hlines": [levels["support"], levels["resistance"]],
        "colors": [SUPPORT, RESISTANCE],
        "linestyle": ["-" if solid_support else "--", "-" if solid_resistance else "--"],
        "linewidths": [1.4 if solid_support else 0.9, 1.4 if solid_resistance else 0.9],
        "alpha": 0.9,
    }

    has_volume = bool(display["Volume"].abs().sum())
    rsi_panel = 2 if has_volume else 1
    add_plots.append(mpf.make_addplot(display["rsi"], panel=rsi_panel, color=EMA_SLOW_C, width=1.3))
    panel_ratios = (4.2, 1.0, 1.6) if has_volume else (4.2, 1.6)

    fig, axes = mpf.plot(
        display,
        type="candle",
        style=_style(),
        addplot=add_plots,
        hlines=hlines,
        volume=has_volume,
        panel_ratios=panel_ratios,
        figratio=(16, 10),
        figscale=1.15,
        datetime_format="%b %d" if timeframe_label == config.LONG_TF_LABEL else "%b %d %H:%M",
        xrotation=0,
        returnfig=True,
        warn_too_much_data=500,
    )

    price_ax = axes[0]
    volume_ax = axes[2] if has_volume else None
    rsi_ax = axes[rsi_panel * 2]
    fig.patch.set_facecolor(BACKGROUND)
    price_ax.set_facecolor(PANEL)
    rsi_ax.set_facecolor(PANEL)
    if volume_ax is not None:
        volume_ax.set_facecolor(PANEL)

    x_values = range(len(display))
    price_ax.fill_between(
        x_values,
        display["bb_lower"].to_numpy(dtype=float),
        display["bb_upper"].to_numpy(dtype=float),
        color=BB, alpha=0.055, zorder=0,
    )

    # Zone shading is reserved for validated levels — shading a weak line would
    # visually promote it back to "real".
    zone_width = float(levels.get("zone_width", 0))
    if zone_width and solid_support:
        price_ax.axhspan(levels["support"] - zone_width, levels["support"] + zone_width,
                         color=SUPPORT, alpha=0.055, zorder=0)
    if zone_width and solid_resistance:
        price_ax.axhspan(levels["resistance"] - zone_width, levels["resistance"] + zone_width,
                         color=RESISTANCE, alpha=0.055, zorder=0)

    last = display.iloc[-1]
    current_price = float(last["Close"])
    sup_label = (f"SUPPORT x{levels.get('support_touches', 1)}"
                 if solid_support else "SUPPORT (weak)")
    res_label = (f"RESISTANCE x{levels.get('resistance_touches', 1)}"
                 if solid_resistance else "RESISTANCE (weak)")
    _price_label(price_ax, levels["support"], sup_label, SUPPORT)
    _price_label(price_ax, levels["resistance"], res_label, RESISTANCE)

    rsi_values = display["rsi"].to_numpy(dtype=float)
    rsi_ax.set_ylim(0, 100)
    rsi_ax.set_yticks([30, 50, 70])
    rsi_ax.fill_between(x_values, rsi_values, 0, color=EMA_SLOW_C, alpha=0.16, zorder=1)
    rsi_ax.axhline(70, color=DOWN, linewidth=0.9, linestyle="--", alpha=0.55)
    rsi_ax.axhline(30, color=UP, linewidth=0.9, linestyle="--", alpha=0.55)
    rsi_ax.set_ylabel(f"RSI {config.RSI_PERIOD}", color=MUTED, fontsize=9, fontweight="bold", labelpad=14)
    last_rsi = float(last["rsi"])
    rsi_ax.text(
        0.992, last_rsi, f" {last_rsi:.1f} ",
        transform=rsi_ax.get_yaxis_transform(),
        ha="right", va="center", color=TEXT, fontsize=8.5, fontweight="bold",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": EMA_SLOW_C, "edgecolor": EMA_SLOW_C, "alpha": 0.88},
        zorder=8,
    )

    legend = [
        Line2D([0], [0], color=EMA_FAST_C, lw=2, label=f"EMA {config.EMA_FAST}"),
        Line2D([0], [0], color=EMA_SLOW_C, lw=2, label=f"EMA {config.EMA_SLOW}"),
        Line2D([0], [0], color=EMA_LONG_C, lw=2, label=f"EMA {config.EMA_PERIODS[-1]}"),
        Line2D([0], [0], color=BB, lw=1, ls="--", label="Bollinger"),
    ]
    # Reserve an empty headroom band above the data, then park the legend in it:
    # every plotted series (candles, EMAs, bands) and every S/R line sits at or
    # below the old y-max, so nothing can run through the legend. (Anchoring the
    # legend outside the axes is not an option — mpf panels ignore
    # subplots_adjust and it collides with the figure-level stats text.)
    ymin, ymax = price_ax.get_ylim()
    price_ax.set_ylim(ymin, ymax + 0.12 * (ymax - ymin))
    # Upper RIGHT, not left — the S/R price labels now live on the left (see
    # _price_label), and a resistance line sitting near the top of the range
    # would otherwise run straight through the legend.
    price_ax.legend(handles=legend, loc="upper right", ncol=4, frameon=False,
                    labelcolor=MUTED, fontsize=9, handlelength=2.0, columnspacing=1.2)

    price_ax.set_ylabel("PRICE · USD", color=MUTED, fontsize=9, fontweight="bold", labelpad=14)
    if volume_ax is not None:
        volume_ax.set_ylabel("VOLUME", color=MUTED, fontsize=9, fontweight="bold", labelpad=14)
        volume_ax.yaxis.set_major_formatter(FuncFormatter(_compact_number))
    for ax in filter(None, (price_ax, volume_ax, rsi_ax)):
        ax.grid(True, alpha=0.45)
        ax.tick_params(axis="both", labelsize=9)

    # Sub-daily timeframes need the hour, not just the date, to read as "as of".
    as_of = str(display.index[-1])[: 10 if timeframe_label == config.LONG_TF_LABEL else 16]
    stats = (
        f"{_headline(last, levels)}     CLOSE  {current_price:,.2f}     "
        f"RSI  {last['rsi']:.1f}     ATR  {last['atr_pct']:.2f}%     "
        f"BB WIDTH  {last['bb_width_pct']:.2f}%"
    )

    title = display_name if display_name else f"${ticker}"
    fig.subplots_adjust(left=0.075, right=0.93, top=0.82, bottom=0.12, hspace=0.08)
    fig.text(0.075, 0.94, f"{title}  ·  {timeframe_label}", color=TEXT, fontsize=22,
             fontweight="bold", ha="left", va="center")
    fig.text(0.075, 0.895, stats, color=MUTED, fontsize=10, ha="left", va="center")
    fig.text(0.925, 0.94, "TECHNICAL SNAPSHOT", color=EMA_FAST_C, fontsize=9,
             fontweight="bold", ha="right", va="center")
    fig.text(0.925, 0.895, f"AS OF {as_of}  ·  YFINANCE", color=MUTED, fontsize=9,
             ha="right", va="center")
    fig.text(0.925, 0.035,
             f"Levels: {levels.get('lookback', len(df))} candles · pivot clusters "
             f"(solid = {config.MIN_LEVEL_TOUCHES}+ touches)",
             color=MUTED, fontsize=8, ha="right")

    fig.savefig(out_path, dpi=config.CHART_DPI, facecolor=BACKGROUND, bbox_inches="tight")
    plt.close(fig)
    return out_path
