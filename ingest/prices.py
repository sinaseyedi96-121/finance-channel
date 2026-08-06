"""
Prices / technicals source: yfinance OHLCV. No API key required.

Returns a dict {symbol: DataFrame} for the technicals stage. This is not a
"news item" source — it feeds the "numbers to know" block and the per-ticker
relevance/technicals lookups, so it returns DataFrames, not staged items.
"""

from __future__ import annotations

import pandas as pd

import config


def fetch_ohlcv(symbols: list[str] | None = None, interval: str | None = None,
                period_days: int | None = None) -> dict[str, pd.DataFrame]:
    """Download OHLCV for each symbol (daily by default). Pass `interval` /
    `period_days` to pull a different granularity, e.g. the short-timeframe
    hourly chart. Missing/failed symbols are simply omitted from the returned
    dict (logged, never raised)."""
    import yfinance as yf

    symbols = symbols or config.ALL_PRICE_SYMBOLS
    interval = interval or config.PRICE_INTERVAL
    period_days = period_days or config.PRICE_LOOKBACK_DAYS
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            df = yf.download(
                symbol,
                period=f"{period_days}d",
                interval=interval,
                auto_adjust=False,
                progress=False,
            )
            if df is None or df.empty:
                print(f"[prices] no data for {symbol}")
                continue
            # yfinance may return a MultiIndex (columns x ticker) for a single
            # symbol depending on version — flatten to plain OHLCV columns.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            out[symbol] = df
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not kill the run
            print(f"[prices] {symbol} failed: {exc}")
    return out
