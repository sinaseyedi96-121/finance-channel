"""
All adjustable settings live here. Change values below to tune behavior —
nothing else in the codebase should need editing for day-to-day tweaks.

Same convention as the crypto-market-channel and ai_news pipelines: constants
at the top, everything else reads from here. Every constant is documented in
the README.
"""

from __future__ import annotations

# =====================================================================
# WATCHLIST
# =====================================================================

# Primary names every post is allowed to cover. Edit freely — the pipeline
# keys all per-ticker work (prices, technicals, news relevance) off this list.
CORE_TICKERS = [
    "PLTR", "NVDA", "GOOGL", "AMZN", "MSFT",
    "AMD", "AVGO", "SMCI", "TSLA", "META", "MSTR",
]

# Adjacent / second-order sectors riding the same AI trend. Starting
# hypotheses, not final — the weekly discovery layer proposes more over time.
# Grouped by thesis so a discovery post can reason sector-by-sector.
ADJACENT_TICKERS = {
    "defense_dual_use": ["LMT", "RTX", "NOC"],
    "power_energy_for_datacenters": ["VST", "CEG", "NEE"],
    "semi_equipment_memory": ["ASML", "AMAT", "MU"],
}

# Broad-market context. S&P 500 is required so every post can frame a move
# against the tape. yfinance uses the ^GSPC symbol for the index.
INDEX_TICKERS = ["^GSPC"]

# FRED series ids for macro context. Oil is required; the broad dollar index
# is enabled (flip to disabled by deleting the line — nothing else references
# the key directly, everything iterates MACRO_SERIES).
MACRO_SERIES = {
    "oil_wti": "DCOILWTICO",
    "oil_brent": "DCOILBRENTEU",
    "dollar_index": "DTWEXBGS",
}

# Every symbol the price/technicals layer should fetch each run: core names,
# all adjacency members, and the index. De-duplicated, order preserved.
def _all_price_symbols() -> list[str]:
    seen: dict[str, None] = {}
    for sym in CORE_TICKERS:
        seen.setdefault(sym, None)
    for group in ADJACENT_TICKERS.values():
        for sym in group:
            seen.setdefault(sym, None)
    for sym in INDEX_TICKERS:
        seen.setdefault(sym, None)
    return list(seen)

ALL_PRICE_SYMBOLS = _all_price_symbols()

# =====================================================================
# MODELS  (all DeepSeek, OpenAI-compatible client — swap to Haiku/OpenAI
# by changing base_url + model here only, nothing else)
# =====================================================================
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Cheap, high-volume tagging + relevance gate. No synthesis here.
CLASSIFIER_MODEL = "deepseek-chat"
CLASSIFIER_MAX_TOKENS = 220
CLASSIFIER_TEMPERATURE = 0.0            # deterministic tagging

# --- IMPORTANT model note (measured, not assumed) --------------------
# deepseek-v4-pro ("DeepSeek Pro") is a REASONING model: max_tokens caps
# reasoning + answer COMBINED, and on short writing tasks like these captions it
# reasons WITHOUT BOUND — it consumed 2500, then 4000 tokens entirely on
# reasoning and returned an EMPTY answer every time (finish_reason=length). So
# it is unusable as the caption writer at any sane budget. deepseek-chat writes
# the same caption reliably and instantly (finish_reason=stop), so it is the
# primary here. Switch *_MODEL back to "deepseek-v4-pro" only if DeepSeek ships
# a way to cap its reasoning; the empty-answer fallback below will still catch it.
SYNTHESIS_MODEL = "deepseek-chat"
SYNTHESIS_MAX_TOKENS = 900
SYNTHESIS_TEMPERATURE = 0.4
SYNTHESIS_FALLBACK_MODEL = "deepseek-chat"   # used if the primary returns empty
SYNTHESIS_FALLBACK_MAX_TOKENS = 900

# Weekly discovery / sector-adjacency pass (same reasoning-model caveat).
DISCOVERY_MODEL = "deepseek-chat"
DISCOVERY_MAX_TOKENS = 1400
DISCOVERY_TEMPERATURE = 0.4

# =====================================================================
# CLASSIFIER  (stage 2)
# =====================================================================
# Categories the cheap model must choose from when tagging an item.
CATEGORIES = ["earnings", "macro", "filing", "rating", "M&A", "politics", "other"]

# An item must score at least this to clear the relevance bar and be handed
# to synthesis. The classifier returns a 0-5 relevance score.
RELEVANCE_MIN_SCORE = 3

# Hard caps so a busy news day can't blow up API cost or spam the channel.
MAX_ITEMS_TO_CLASSIFY_PER_RUN = 60     # cheap-model calls
MAX_POSTS_PER_RUN = 4                  # deepseek-v4-pro synthesis + published posts

# Business-politics items are only allowed through if the classifier judges
# they plausibly move a CORE/INDEX ticker or a macro series. General politics
# is discarded here (see classifier.py system prompt).

# =====================================================================
# TECHNICALS  (stage 3 — computed manually in pandas, never pandas_ta:
# it breaks on numpy >= 2.0)
# =====================================================================
PRICE_LOOKBACK_DAYS = 400              # enough daily history for EMA(200)
PRICE_INTERVAL = "1d"

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

EMA_PERIODS = [20, 50, 200]

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD = 2

# Two EMAs drawn on the chart as fast/slow (EMA200 is added as a third,
# longer-term line for the "few months" view).
EMA_FAST = 20
EMA_SLOW = 50

ATR_PERIOD = 14                        # volatility, also sizes the S/R cluster tolerance
TREND_SLOPE_LOOKBACK = 5               # candles used to confirm EMA direction

# ---- Support / resistance (pivot-cluster detection, ported from crypto) ----
LEVEL_LOOKBACK = 180                   # ~9 months of daily candles
PIVOT_WINDOW = 3                       # candles required on each side of a pivot
MIN_LEVEL_TOUCHES = 2                  # repeated touches make a level "real"
LEVEL_CLUSTER_ATR_MULTIPLIER = 0.40    # merge nearby pivots into one level

# ---- Chart (crypto-style technical image) ----
CHART_DIR = "charts"
CHART_DISPLAY_CANDLES = 120            # compute on full history, render recent window
CHART_DPI = 160

# =====================================================================
# INGEST  (stage 1 — one module per source under ingest/)
# =====================================================================

# ---- Finnhub (company news + news sentiment), free tier ----
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_NEWS_LOOKBACK_DAYS = 2         # /company-news window per run
FINNHUB_MAX_ITEMS_PER_TICKER = 8

# ---- SEC EDGAR full-text search (10-Q / 10-K / 8-K), free, no key ----
# efts is the full-text search backend behind https://efts.sec.gov/LATEST/search-index
SEC_FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
# Per-company submission feed (most recent filings), keyed by zero-padded CIK.
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FORMS_OF_INTEREST = ["10-Q", "10-K", "8-K"]
SEC_LOOKBACK_DAYS = 3
# SEC requires a descriptive User-Agent with contact info on every request.
# Override via the SEC_USER_AGENT env var; this is the fallback default.
SEC_USER_AGENT_DEFAULT = "ai-stocks-channel research bot (contact: set SEC_USER_AGENT env)"

# ---- FRED (oil + dollar index) ----
# Official API is used when FRED_API_KEY is set; otherwise the keyless CSV
# download endpoint is used as a fallback (same approach as crypto-market-channel).
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_LOOKBACK_DAYS = 14

# ---- EIA (finer-grained energy data, fallback for oil) ----
EIA_BASE_URL = "https://api.eia.gov/v2"
# WTI spot, daily. Only queried when EIA_API_KEY is set.
EIA_WTI_SERIES = "PET.RWTC.D"

# ---- Business RSS (market-moving politics/macro) ----
# Fed through the classifier with a strict filter: only items that plausibly
# move CORE/INDEX tickers or a macro series survive; general politics is dropped.
RSS_FEEDS = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "ap_business": "https://rsshub.app/apnews/topics/business",
}
RSS_MAX_ITEMS_PER_FEED = 15

# =====================================================================
# FORMAT  (stage 6 — was "compliance")
# =====================================================================
# The channel is personal/informational and does NOT append a legal disclaimer
# footer (owner's choice). Flip DISCLAIMER_ENABLED back on if that ever changes.
DISCLAIMER_ENABLED = False
DISCLAIMER_TEXT = (
    "\n\n⚠️ Informational only, not financial advice."
)

# The old descriptive-only linter is kept but OFF by default — the channel wants
# a clear, punchy read of what's happening. Flip LINT_ENABLED on to reject the
# patterns below (e.g. if you later monetize and want to avoid trade-rec framing).
LINT_ENABLED = False
FORBIDDEN_PATTERNS = [
    r"\bbuy\b", r"\bsell\b",
    r"\bstop[-\s]?loss\b", r"\btake[-\s]?profit\b",
    r"\bprice\s+target\b",
]

# =====================================================================
# TELEGRAM  (stage 7)
# =====================================================================
# Use the numeric channel ID (e.g. -1001234567890), not @username, so the bot
# posts even if the public username later changes. Read from env at runtime.
TELEGRAM_TOKEN_ENV = "TELEGRAM_TOKEN"
TELEGRAM_CHANNEL_ENV = "TELEGRAM_CHANNEL"
TELEGRAM_MESSAGE_LIMIT = 4096          # Telegram hard cap on text messages
TELEGRAM_CAPTION_LIMIT = 1024          # Telegram hard cap on photo captions

# Channel display name + link, appended as a clickable footer so forwarded
# posts still drive back to the source. Fill CHANNEL_URL once you have the
# public link; leave as-is until then (footer link is skipped if empty).
CHANNEL_NAME = "AI Stocks"
CHANNEL_URL = ""                       # e.g. "https://t.me/your_channel"

# =====================================================================
# DISCOVERY  (stage 5 — weekly)
# =====================================================================
DISCOVERY_WEEKDAY = 6                  # Sunday (Monday=0 .. Sunday=6)
DISCOVERY_NEWS_LOOKBACK_DAYS = 7

# =====================================================================
# PATHS  (committed JSON state — the only memory between ephemeral CI runs)
# =====================================================================
STATE_FILE = "post_history.json"       # posted-item dedup + last-seen filing ids
STAGING_FILE = "staging.json"          # raw ingested items awaiting classify/synth
POSTS_LOG_FILE = "posts_log.jsonl"     # append-only log of what was published
