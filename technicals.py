"""
Technical indicators computed manually in pandas.

Deliberately NOT using pandas_ta — it breaks on numpy >= 2.0. Everything here
is plain pandas/numpy so it runs on the CI Python (3.12) and a local 3.9 venv.

Input is an OHLCV DataFrame (columns: Open, High, Low, Close, Volume) indexed
by date, oldest first — exactly what ingest/prices.py returns from yfinance.

Two layers:
  * bare series helpers (rsi/ema/macd/bollinger) — the numbers.
  * enrich() + find_key_levels() + summarize() — the chart-ready DataFrame,
    pivot-cluster support/resistance, and a compact grounding block for the
    caption model. Support/resistance detection is ported from the crypto
    channel's indicators.py so the charts read identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config


# ---------------------------------------------------------------------
# bare series helpers
# ---------------------------------------------------------------------

def rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, min_periods=period, adjust=False).mean()


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    fast = ema(close, config.MACD_FAST)
    slow = ema(close, config.MACD_SLOW)
    macd_line = fast - slow
    signal_line = macd_line.ewm(
        span=config.MACD_SIGNAL, min_periods=config.MACD_SIGNAL, adjust=False
    ).mean()
    return macd_line, signal_line, macd_line - signal_line


def bollinger(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, middle/SMA, lower)."""
    middle = close.rolling(config.BB_PERIOD).mean()
    std = close.rolling(config.BB_PERIOD).std(ddof=0)
    upper = middle + config.BB_STD * std
    lower = middle - config.BB_STD * std
    return upper, middle, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = config.ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# ---------------------------------------------------------------------
# enriched frame (adds all indicator columns the chart draws)
# ---------------------------------------------------------------------

def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with ema_fast/slow/long, rsi, macd, bollinger, atr columns."""
    df = df.copy()
    close = df["Close"].astype(float)
    df["ema_fast"] = ema(close, config.EMA_FAST)
    df["ema_slow"] = ema(close, config.EMA_SLOW)
    df["ema_long"] = ema(close, config.EMA_PERIODS[-1])   # EMA200 for the months view
    df["rsi"] = rsi(close)
    macd_line, signal_line, hist = macd(close)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd_line, signal_line, hist
    upper, mid, lower = bollinger(close)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = upper, mid, lower
    df["atr"] = atr(df["High"].astype(float), df["Low"].astype(float), close)
    df["atr_pct"] = df["atr"] / close * 100
    df["bb_width_pct"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100
    return df


# ---------------------------------------------------------------------
# support / resistance via pivot clustering (ported from crypto indicators.py)
# ---------------------------------------------------------------------

@dataclass
class _LevelCluster:
    values: list = field(default_factory=list)
    positions: list = field(default_factory=list)

    @property
    def center(self) -> float:
        return sum(self.values) / len(self.values)

    @property
    def touches(self) -> int:
        return len(self.values)

    @property
    def last_position(self) -> int:
        return max(self.positions)


def _cluster_pivots(points: list, tolerance: float) -> list:
    clusters: list = []
    for value, position in sorted(points):
        nearest = min(clusters, key=lambda c: abs(c.center - value), default=None)
        if nearest is not None and abs(nearest.center - value) <= tolerance:
            nearest.values.append(value)
            nearest.positions.append(position)
        else:
            clusters.append(_LevelCluster([value], [position]))
    return clusters


def _pick_level(clusters: list, current_price: float, side: str, sample_size: int):
    if side == "support":
        eligible = [c for c in clusters if c.center < current_price]
    else:
        eligible = [c for c in clusters if c.center > current_price]
    repeated = [c for c in eligible if c.touches >= config.MIN_LEVEL_TOUCHES]
    candidates = repeated or eligible
    if not candidates:
        return None

    def score(cluster) -> float:
        recency = cluster.last_position / max(sample_size - 1, 1)
        distance_pct = abs(cluster.center - current_price) / current_price
        return cluster.touches + 0.75 * recency - 5 * distance_pct

    return max(candidates, key=score)


def find_key_levels(df: pd.DataFrame, lookback: int = config.LEVEL_LOOKBACK) -> dict:
    """Nearest significant support/resistance from repeated pivots. `df` must be
    enriched (needs the 'atr' column)."""
    recent = df.tail(lookback)
    window = config.PIVOT_WINDOW * 2 + 1
    if len(recent) < window:
        # Not enough history — fall back to the visible high/low range.
        current = float(recent["Close"].iloc[-1])
        return {
            "support": round(float(recent["Low"].min()), 2),
            "resistance": round(float(recent["High"].max()), 2),
            "support_touches": 1, "resistance_touches": 1,
            "lookback": len(recent), "zone_width": round(current * 0.01, 2),
        }

    pivot_highs = recent["High"].eq(recent["High"].rolling(window, center=True).max())
    pivot_lows = recent["Low"].eq(recent["Low"].rolling(window, center=True).min())
    high_points = [(float(recent["High"].iloc[i]), i) for i in range(len(recent)) if pivot_highs.iloc[i]]
    low_points = [(float(recent["Low"].iloc[i]), i) for i in range(len(recent)) if pivot_lows.iloc[i]]

    current_price = float(recent["Close"].iloc[-1])
    current_atr = float(recent["atr"].iloc[-1]) if not pd.isna(recent["atr"].iloc[-1]) else current_price * 0.01
    tolerance = max(current_atr * config.LEVEL_CLUSTER_ATR_MULTIPLIER, current_price * 0.003)

    high_clusters = _cluster_pivots(high_points, tolerance)
    low_clusters = _cluster_pivots(low_points, tolerance)
    support = _pick_level(low_clusters, current_price, "support", len(recent))
    resistance = _pick_level(high_clusters, current_price, "resistance", len(recent))

    return {
        "support": round(support.center if support else float(recent["Low"].min()), 2),
        "resistance": round(resistance.center if resistance else float(recent["High"].max()), 2),
        "support_touches": support.touches if support else 1,
        "resistance_touches": resistance.touches if resistance else 1,
        "lookback": len(recent),
        "zone_width": round(tolerance, 2),
    }


def trend_state(df: pd.DataFrame) -> str:
    """Short human-readable trend classification from EMA alignment + slope."""
    last = df.iloc[-1]
    earlier = df.iloc[-1 - min(config.TREND_SLOPE_LOOKBACK, len(df) - 1)]
    fast_rising = last["ema_fast"] > earlier["ema_fast"]
    if last["ema_fast"] > last["ema_slow"] and last["Close"] > last["ema_slow"] and fast_rising:
        return "bullish"
    if last["ema_fast"] < last["ema_slow"] and last["Close"] < last["ema_slow"] and not fast_rising:
        return "bearish"
    return "mixed/transitioning"


# ---------------------------------------------------------------------
# compact grounding snapshot for the caption model
# ---------------------------------------------------------------------

def _round(value, digits: int = 2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def summarize(symbol: str, df: pd.DataFrame) -> dict:
    """Latest-value snapshot for the caption grounding block. Only returns
    numbers derived from the passed data — the caption model quotes from here."""
    if df is None or df.empty or "Close" not in df:
        return {"symbol": symbol, "available": False}

    enriched = enrich(df)
    close = enriched["Close"].astype(float)
    last = close.iloc[-1]
    prev = close.iloc[-2] if len(close) >= 2 else last
    pct_change = (last / prev - 1) * 100 if prev else 0.0
    latest_rsi = _round(enriched["rsi"].iloc[-1])

    rsi_state = "neutral"
    if latest_rsi is not None:
        if latest_rsi >= config.RSI_OVERBOUGHT:
            rsi_state = "overbought"
        elif latest_rsi <= config.RSI_OVERSOLD:
            rsi_state = "oversold"

    emas = {f"ema{p}": _round(ema(close, p).iloc[-1]) for p in config.EMA_PERIODS}

    try:
        levels = find_key_levels(enriched)
    except Exception:  # noqa: BLE001
        levels = {}

    return {
        "symbol": symbol,
        "available": True,
        "as_of": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
        "last_price": _round(last),
        "pct_change_1d": _round(pct_change),
        "rsi": latest_rsi,
        "rsi_state": rsi_state,
        "trend": trend_state(enriched),
        **emas,
        "macd_hist": _round(enriched["macd_hist"].iloc[-1], 4),
        "bb_upper": _round(enriched["bb_upper"].iloc[-1]),
        "bb_lower": _round(enriched["bb_lower"].iloc[-1]),
        "support": levels.get("support"),
        "resistance": levels.get("resistance"),
        "atr_pct": _round(enriched["atr_pct"].iloc[-1]),
    }
