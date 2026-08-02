"""
Technical indicators computed manually in pandas.

Deliberately NOT using pandas_ta — it breaks on numpy >= 2.0. Everything here
is plain pandas/numpy so it runs on the CI Python (3.12) and a local 3.9 venv.

Input is an OHLCV DataFrame (columns: Open, High, Low, Close, Volume) indexed
by date, oldest first — exactly what ingest/prices.py returns from yfinance.
"""

from __future__ import annotations

import pandas as pd

import config


def rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EMA with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    # When there are no losses in the window, RSI is 100 by definition.
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


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def summarize(symbol: str, df: pd.DataFrame) -> dict:
    """Compact latest-value snapshot for the synthesis grounding block.

    Only returns numbers actually derived from the passed data — the synthesis
    stage is forbidden from inventing figures, so this is the authoritative
    source it quotes from.
    """
    if df is None or df.empty or "Close" not in df:
        return {"symbol": symbol, "available": False}

    close = df["Close"].astype(float)
    last = close.iloc[-1]
    prev = close.iloc[-2] if len(close) >= 2 else last
    pct_change = (last / prev - 1) * 100 if prev else 0.0

    rsi_series = rsi(close)
    macd_line, signal_line, hist = macd(close)
    upper, middle, lower = bollinger(close)

    emas = {f"ema{p}": _round(ema(close, p).iloc[-1]) for p in config.EMA_PERIODS}

    latest_rsi = _round(rsi_series.iloc[-1])
    rsi_state = "neutral"
    if latest_rsi is not None:
        if latest_rsi >= config.RSI_OVERBOUGHT:
            rsi_state = "overbought"
        elif latest_rsi <= config.RSI_OVERSOLD:
            rsi_state = "oversold"

    return {
        "symbol": symbol,
        "available": True,
        "as_of": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
        "last_price": _round(last),
        "pct_change_1d": _round(pct_change),
        "rsi": latest_rsi,
        "rsi_state": rsi_state,
        **emas,
        "macd": _round(macd_line.iloc[-1], 4),
        "macd_signal": _round(signal_line.iloc[-1], 4),
        "macd_hist": _round(hist.iloc[-1], 4),
        "bb_upper": _round(upper.iloc[-1]),
        "bb_lower": _round(lower.iloc[-1]),
    }
