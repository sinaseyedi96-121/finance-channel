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
# This is a FINANCE / markets channel. We're in the AI boom, so AI stocks are
# the center of gravity and the most important names — but coverage is broad:
# the index, commodities, macro, and especially AI-bubble / crash-risk analysis.

# Primary names every post is allowed to cover. Edit freely — the pipeline
# keys all per-ticker work (prices, technicals, news relevance) off this list.
CORE_TICKERS = [
    "PLTR", "NVDA", "GOOGL", "AMZN", "MSFT",
    "AMD", "AVGO", "SMCI", "TSLA", "META", "MSTR",
]

# Broad-market instruments (index + commodities) that get their own charts —
# the macro backdrop for the AI trade. yfinance symbols; the label is the chart
# title. Futures symbols (=F) give continuous daily history.
MACRO_INSTRUMENTS = {
    "S&P 500": "^GSPC",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Oil (WTI)": "CL=F",
}

# Adjacent / second-order sectors riding the same AI trend. Starting
# hypotheses, not final — the weekly discovery layer proposes more over time.
# Grouped by thesis so a discovery post can reason sector-by-sector.
ADJACENT_TICKERS = {
    "defense_dual_use": ["LMT", "RTX", "NOC"],
    "power_energy_for_datacenters": ["VST", "CEG", "NEE"],
    "semi_equipment_memory": ["ASML", "AMAT", "MU"],
}

# "Hidden Value" universe: critically-important-but-often-overlooked sectors that
# the AI / electrification / energy build-out actually runs on — rare earths &
# critical minerals, data-center cooling & power delivery, uranium/nuclear, grid,
# copper, water, and semi picks-and-shovels. The weekly Hidden Value post reasons
# over these names' FUNDAMENTALS to surface ones that look undervalued vs their
# price and/or whose structural importance the market underappreciates. Edit freely.
VALUE_UNIVERSE = {
    "rare_earth_and_critical_minerals": ["MP", "ALB", "UUUU", "LAC", "TMC"],
    "data_center_cooling_and_power": ["VRT", "NVT", "ETN"],
    "uranium_and_nuclear": ["CCJ", "LEU", "UEC", "SMR"],
    "grid_and_electrification": ["PWR", "GEV", "AGX"],
    "copper_and_industrial_metals": ["FCX", "SCCO"],
    "water_infrastructure": ["XYL", "WTRG"],
    "semi_equipment_and_materials": ["LRCX", "KLAC", "ENTG"],
    "quantum_computing": ["IONQ", "RGTI", "QBTS", "QUBT"],
    "defense_and_military": ["LMT", "RTX", "NOC", "KTOS", "AVAV"],
    # "Irreplaceable" moats — companies doing something no one else can at scale
    # (EUV litho, leading-edge foundry, chip-design EDA, unique x86+GPU, CPU IP).
    "irreplaceable_moats": ["ASML", "TSM", "SNPS", "CDNS", "AMD", "ARM"],
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
# all adjacency members, the index, and the macro instruments. De-duplicated,
# order preserved.
def _all_price_symbols() -> list[str]:
    seen: dict[str, None] = {}
    for sym in CORE_TICKERS:
        seen.setdefault(sym, None)
    for group in ADJACENT_TICKERS.values():
        for sym in group:
            seen.setdefault(sym, None)
    for sym in INDEX_TICKERS:
        seen.setdefault(sym, None)
    for sym in MACRO_INSTRUMENTS.values():
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

# --- Two-model pipeline: Pro reasons, Chat writes --------------------
# ANALYST = deepseek-v4-pro ("DeepSeek Pro"): the reasoning model. It analyzes
# the news + chart technicals + macro/politics and relates them to the stock and
# the broader market (incl. AI-bubble / crash risk). Measured quirk: v4-pro often
# spends its whole budget on chain-of-thought and returns an EMPTY `content` —
# but the analysis lives in `reasoning_content`, which llm_client.reason() returns
# as a fallback. So we always get its analysis.
# WRITER = deepseek-chat: takes the analyst brief + grounded data and writes the
# final publishable caption/post reliably and fast.
ANALYST_MODEL = "deepseek-v4-pro"
ANALYST_MAX_TOKENS = 3000
ANALYST_TEMPERATURE = 0.3

SYNTHESIS_MODEL = "deepseek-chat"            # writer
SYNTHESIS_MAX_TOKENS = 900
SYNTHESIS_TEMPERATURE = 0.4

DISCOVERY_MODEL = "deepseek-chat"            # writer (discovery reuses ANALYST_MODEL to reason)
DISCOVERY_MAX_TOKENS = 1400
DISCOVERY_TEMPERATURE = 0.4

# =====================================================================
# CLASSIFIER  (stage 2)
# =====================================================================
# Categories the cheap model must choose from when tagging an item.
# "bubble_risk" captures AI-bubble / crash / correction / overvaluation narratives —
# a first-class theme for this channel, not noise to discard.
CATEGORIES = ["earnings", "macro", "filing", "rating", "M&A", "politics",
              "bubble_risk", "commodities", "other"]

# An item must score at least this to clear the relevance bar and be handed
# to synthesis. The classifier returns a 0-5 relevance score.
RELEVANCE_MIN_SCORE = 3

# Hard caps so a busy news day can't blow up API cost or spam the channel.
MAX_ITEMS_TO_CLASSIFY_PER_RUN = 60     # cheap-model calls
MAX_POSTS_PER_RUN = 4                  # deepseek-v4-pro synthesis + published posts

# Diversity gate: at most this many news posts about the SAME ticker per UTC day
# (counted across all runs via posts_log.jsonl). Stops the "two AMZN posts in a
# row" pattern — a second story on an already-covered name waits for tomorrow.
MAX_POSTS_PER_TICKER_PER_DAY = 1

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
# Render the SAME window the S/R levels are computed over (LEVEL_LOOKBACK), so
# every pivot behind a drawn line is visible and the level reads as earned.
# (Was 120 — the reviewer flagged that the tighter crop made levels look arbitrary.)
CHART_DISPLAY_CANDLES = 180
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
CHANNEL_NAME = "Finance AAR"
CHANNEL_URL = "https://t.me/finance_arr"

# =====================================================================
# DISCOVERY  (stage 5 — weekly)
# =====================================================================
DISCOVERY_WEEKDAY = 6                  # Sunday (Monday=0 .. Sunday=6)
DISCOVERY_NEWS_LOOKBACK_DAYS = 7

# =====================================================================
# WEEK AHEAD  (weekly "what to watch", Monday) — forward-looking preview
# =====================================================================
WEEK_AHEAD_WEEKDAY = 0                 # Monday
WEEK_AHEAD_EARNINGS_DAYS = 7           # look this many days forward for earnings
# Macro instruments charted in the week-ahead album (subset of MACRO_INSTRUMENTS).
WEEK_AHEAD_CHART_INSTRUMENTS = ["S&P 500", "Gold", "Silver", "Oil (WTI)"]

# =====================================================================
# CONVICTION SCORECARD  (weekly, Saturday) — accountability / track record
# =====================================================================
SCORECARD_WEEKDAY = 5                  # Saturday
SCORECARD_LOOKBACK_DAYS = 30           # rolling window of calls to grade
SCORECARD_MIN_AGE_DAYS = 3             # a call must be this old to be graded

# =====================================================================
# HEAD-TO-HEAD  (weekly, Thursday) — two rivals compared
# =====================================================================
HEAD_TO_HEAD_WEEKDAY = 3               # Thursday
# Rotation of rival pairs; one pair per week (ISO week number picks the pair).
HEAD_TO_HEAD_PAIRS = [
    ("AMD", "NVDA"),
    ("ASML", "AMAT"),
    ("MSFT", "GOOGL"),
    ("PLTR", "SNOW"),
    ("TSM", "INTC"),
    ("VRT", "ETN"),
    ("CCJ", "LEU"),
]

# =====================================================================
# EARNINGS DEEP-DIVE  (daily check) — pre-earnings brief for core names
# =====================================================================
# Runs daily; posts a deep-dive when a CORE ticker reports within this window.
EARNINGS_DD_WINDOW_DAYS = 2
EARNINGS_HISTORY_QUARTERS = 4          # beat/miss history to show

# =====================================================================
# AI BUBBLE INDEX  (weekly, Friday) — proprietary froth gauge
# =====================================================================
BUBBLE_INDEX_WEEKDAY = 4               # Friday
# Names the froth gauge is computed across (the AI leadership).
BUBBLE_INDEX_TICKERS = ["NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD", "AVGO", "PLTR"]

# Multi-pillar AI Bubble Index (methodology blends Fidelity's 5 signs, Exponential
# View's boomorbubble.ai gauges, and CEPR/AI-Bubble-Monitor). Each pillar scores
# 0-100 froth; the composite is their weighted average (weights renormalize over
# whichever pillars have data). Edit weights to taste — they should sum to ~1.
BUBBLE_PILLAR_WEIGHTS = {
    "valuation": 0.28,        # avg forward P/E + PEG of the AI leaders (Fidelity/EV "valuation heat")
    "concentration": 0.18,    # cap-weight vs equal-weight S&P (Mag7 dominance / breadth)
    "exuberance": 0.20,       # price momentum: RSI, % above 200EMA, Bollinger pos, breadth (CEPR)
    "capex_gdp": 0.22,        # AI capex / US GDP (Exponential View "economic strain")
    "credit": 0.12,           # high-yield credit spread (tight = complacency/systemic froth)
}
BUBBLE_CONCENTRATION_PAIR = ("SPY", "RSP")   # cap-weight vs equal-weight S&P 500
BUBBLE_CONCENTRATION_LOOKBACK = 126          # ~6 months of trading days
# Hyperscaler + AI infra annual capex estimate (USD). Update as it grows — Goldman
# projects ~$1T by ~2027; ~$500B is the 2026 run-rate. Drives the economic-strain pillar.
BUBBLE_AI_CAPEX_ANNUAL_USD = 500e9
FRED_GDP_SERIES = "GDP"                       # US nominal GDP, $ billions, quarterly
FRED_HY_SPREAD_SERIES = "BAMLH0A0HYM2"        # ICE BofA US High Yield OAS, %

# =====================================================================
# HIDDEN VALUE  (weekly, Wednesday) — undervalued + overlooked essentials
# =====================================================================
HIDDEN_VALUE_WEEKDAY = 2               # Wednesday
HIDDEN_VALUE_MAX_NAMES = 5             # how many names the post introduces
HIDDEN_VALUE_CHART_TOP = 5            # max charts in the album (the names the post features)
# Names whose analyst mean target sits at least this far above price are treated
# as showing a clear "fundamental value > current price" signal in the shortlist.
HIDDEN_VALUE_MIN_UPSIDE_PCT = 15.0

# =====================================================================
# GROUNDING GATE  (stage 5.5 — mechanical, grounding.py)
# =====================================================================
# Every number in a draft caption must be traceable to the retrieved data
# (news text, technicals, fundamentals, macro). One retry with the offending
# figures named; still failing -> the post is skipped, never published.
GROUNDING_ENABLED = True
GROUNDING_REL_TOL = 0.015              # 1.5% relative slack for rounding drift
GROUNDING_SMALL_INT_MAX = 10           # bare ints <= this are always allowed
                                       # (ranks, counts, conviction 1-10)

# =====================================================================
# MARKET CAP RANKING  (event-driven) — top-20 leaderboard, posts ONLY on change
# =====================================================================
# Checked after each news run; the chart is only posted when the top-20
# ORDERING actually changed since the last stored ranking (a static leaderboard
# is noise). Universe is deliberately wider than 20 so entries/exits register.
MARKET_CAP_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA",
    "BRK-B", "TSM", "LLY", "WMT", "JPM", "V", "MA", "XOM", "UNH",
    "ORCL", "COST", "PG", "HD", "JNJ", "NFLX", "BAC", "CRM", "ASML",
    "AMD", "KO", "CVX", "PLTR",
]
MARKET_CAP_TOP_N = 20

# =====================================================================
# REVIEW AGENT  (daily, reviewer.py) — the channel's editor-in-chief loop
# =====================================================================
# Reads the posts log (full captions + chart metadata, i.e. what the channel
# actually published), runs deterministic checks, has Pro critique the output,
# and writes EDITORIAL_NOTES_FILE — short directives the analyst and writer
# prompts obey on every subsequent post. Full reviews land in REVIEWS_DIR.
REVIEW_LOOKBACK_DAYS = 3               # posts window the reviewer considers
REVIEW_MAX_DIRECTIVES = 5              # directives carried into future prompts
REVIEW_NOTES_MAX_AGE_DAYS = 7          # stale notes are ignored, not obeyed
REVIEWS_DIR = "reviews"
EDITORIAL_NOTES_FILE = "editorial_notes.json"
REVIEW_MAX_TOKENS = 3000               # Pro critique budget
REVIEW_TEMPERATURE = 0.3

# =====================================================================
# PATHS  (committed JSON state — the only memory between ephemeral CI runs)
# =====================================================================
STATE_FILE = "post_history.json"       # posted-item dedup + last-seen filing ids
STAGING_FILE = "staging.json"          # raw ingested items awaiting classify/synth
POSTS_LOG_FILE = "posts_log.jsonl"     # append-only log of what was published
