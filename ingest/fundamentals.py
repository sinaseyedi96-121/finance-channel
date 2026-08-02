"""
Fundamentals source: yfinance company info (valuation metrics + analyst targets).

Feeds the weekly "Hidden Value" post. For each ticker it returns the numbers a
value analyst needs to judge whether a name looks cheap versus its fundamentals /
analyst view: price, mean analyst target (and implied upside), P/E (trailing &
forward), PEG, P/B, margins, growth, market cap, and the sector/industry.

yfinance's per-ticker info call is slow and occasionally flaky, so each ticker is
fetched defensively — a failure is logged and skipped, never raised.
"""

from __future__ import annotations


def _upside(price, target):
    if price and target and price > 0:
        return round((target / price - 1) * 100, 1)
    return None


def fetch(tickers: list) -> list[dict]:
    import yfinance as yf

    out: list[dict] = []
    for t in tickers:
        try:
            info = yf.Ticker(t).get_info()
        except Exception as exc:  # noqa: BLE001
            print(f"[fundamentals] {t} failed: {exc}")
            continue
        if not info:
            continue
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        target = info.get("targetMeanPrice")
        hi52, lo52 = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
        pos52 = None
        if price and hi52 and lo52 and hi52 > lo52:
            pos52 = round((price - lo52) / (hi52 - lo52) * 100, 0)  # 0=52w low, 100=52w high
        out.append(
            {
                "ticker": t,
                "name": info.get("shortName") or info.get("longName") or t,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "price": price,
                "target_mean": target,
                "target_high": info.get("targetHighPrice"),
                "target_low": info.get("targetLowPrice"),
                "upside_to_target_pct": _upside(price, target),
                "analyst_reco": info.get("recommendationKey"),
                "num_analysts": info.get("numberOfAnalystOpinions"),
                "trailing_pe": _round(info.get("trailingPE")),
                "forward_pe": _round(info.get("forwardPE")),
                "peg": _round(info.get("pegRatio")),
                "price_to_book": _round(info.get("priceToBook")),
                "ev_to_ebitda": _round(info.get("enterpriseToEbitda")),
                "market_cap": info.get("marketCap"),
                "profit_margin_pct": _pct(info.get("profitMargins")),
                "gross_margin_pct": _pct(info.get("grossMargins")),
                "revenue_growth_pct": _pct(info.get("revenueGrowth")),
                "earnings_growth_pct": _pct(info.get("earningsGrowth")),
                "ebitda_margin_pct": _pct(info.get("ebitdaMargins")),
                "debt_to_equity": _round(info.get("debtToEquity")),
                "return_on_equity_pct": _pct(info.get("returnOnEquity")),
                "beta": _round(info.get("beta")),
                "dividend_yield_pct": _pct(info.get("dividendYield") if (info.get("dividendYield") or 0) < 1 else (info.get("dividendYield") or 0) / 100),
                "pct_of_52w_range": pos52,     # 0 = at 52w low, 100 = at 52w high
                "short_pct_float": _pct(info.get("shortPercentOfFloat")),
                "held_pct_institutions": _pct(info.get("heldPercentInstitutions")),
            }
        )
    return out


def _round(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _pct(v):
    try:
        return round(float(v) * 100, 1)
    except (TypeError, ValueError):
        return None
