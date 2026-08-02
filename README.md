# Finance AAR — markets in the AI boom

Automated Telegram pipeline for a **finance / markets channel**. We're in the AI
boom, so AI stocks are the center of gravity and the most important names — but
coverage is broad: the index, commodities, macro, and especially **AI-bubble /
crash-risk analysis**. Same shape as the `crypto-market-channel` / `ai_news`
pipelines — **ingest → classify → analyze → chart + caption → publish**,
scheduled by GitHub Actions with committed JSON state.

Each news post is a **crypto-style technical chart** (candles + support/resistance
+ Bollinger + EMA 20/50/200 + RSI panel, in PT Serif) with a **viral, emoji-rich
caption**: headline → what happened → the tape → what to watch (short / midterm)
→ a bubble-risk line when relevant. No disclaimer footer (owner's choice — toggle
in `config.py`).

### Two-model pipeline: Pro reasons, Chat writes
Text generation uses **DeepSeek** (OpenAI-compatible) with both models working
together, as intended:

- **`deepseek-v4-pro` ("DeepSeek Pro") = the ANALYST.** It reasons over the news +
  chart technicals + macro/politics and relates them to the stock and the broader
  market, incl. AI-bubble/crash risk (`analyst.py`).
- **`deepseek-chat` = the WRITER.** It turns the analyst's brief into the published
  caption/post reliably and fast (`synthesizer.py`).

> ⚠️ **The trick that makes v4-pro usable.** `deepseek-v4-pro` often spends its
> whole `max_tokens` on chain-of-thought and returns an **empty `content`**
> (measured: 2500 then 4000 tokens, all reasoning, `finish_reason=length`). But
> the analysis itself lives in `reasoning_content` — so `llm_client.reason()`
> returns `content` when present and falls back to `reasoning_content`. Either way
> we capture Pro's analysis and hand it to Chat to publish. That's why the reasoning
> model is used for analysis but never as the final writer.

---

## Pipeline stages

| # | Stage | Module | Model |
|---|-------|--------|-------|
| 1 | Ingest | `ingest/*.py` | — |
| 2 | Classify + relevance gate | `classifier.py` | `deepseek-chat` (cheap) |
| 3 | Technicals + S/R levels | `technicals.py` | — (pandas, no `pandas_ta`) |
| 4 | Analyze (reason) | `analyst.py` | `deepseek-v4-pro` |
| 5 | Caption / post (write) | `synthesizer.py` · `discovery.py` · `week_ahead.py` | `deepseek-chat` |
| 6 | Chart render | `chart_generator.py` | — (mplfinance, PT Serif) |
| 7 | Format | `compliance.py` | — |
| 8 | Publish (photo / album / text) | `telegram_publisher.py` | — |

Orchestrated by `main.py` (`--mode auto` / `discovery` / `week_ahead` /
`hidden_value`). Hidden Value adds an `ingest/fundamentals.py` (yfinance valuation
metrics) + `hidden_value.py` stage. State lives in committed JSON
(`post_history.json`, `posts_log.jsonl`); ephemeral CI runners have no other memory
between runs.

**Eight post types:**
- **News** (3×/day) — institutional chart + caption per relevant item: fundamentals
  + valuation verdict + moat + multi-timeframe technicals + a conviction call, and
  a ⚙️ entry/stop/target line when the setup is clean (bubble-risk items included).
- **Earnings Deep-Dive** (daily check) — JPMorgan-style pre-earnings brief when a
  core name reports soon: beat/miss history, expected move, bull/bear, setup.
- **Head-to-Head** (Thursdays) — two rivals compared (AMD vs NVDA, ASML vs AMAT…),
  a clear winner; album of both charts.
- **AI Bubble Index** (Fridays) — proprietary 0-100 froth gauge (avg RSI + %>200EMA
  + Bollinger position + weekly-uptrend breadth) as a meter + read.
- **Conviction Scorecard** (Saturdays) — grades the last 30d of calls vs current
  price: hit rate, avg return, best/worst, as a bar chart. The accountability engine.
- **Week Ahead** (Mondays) — forward preview (earnings + macro + bubble watch) as
  an album of macro charts (S&P 500, Gold, Silver, Oil).
- **Hidden Value** (Wednesdays) — undervalued + critically-important-but-overlooked
  essentials (rare earths, cooling/power, uranium, grid, copper, water, semi tools,
  quantum, defense, irreplaceable moats) reasoned over their **fundamentals**.
- **Discovery** (Sundays) — second-order beneficiaries "worth watching" note.

**Grounding rule (non-negotiable):** the writer may only state figures present in
the retrieved-data block — and those technical numbers are the *same ones drawn
on the chart*, so caption and chart always agree. The analyst brief interprets;
it does not license new numbers.

**Format layer (`compliance.py`):** no disclaimer and no linter by default
(`DISCLAIMER_ENABLED` / `LINT_ENABLED` are `False`; flip on to reintroduce
trade-rec-safe framing). Strips stray markdown and clips long captions at a line
boundary (never mid-word).

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env          # fill in keys (DEEPSEEK_KEY is already reused from your setup)
.venv/bin/python -m unittest discover -s tests -v     # 45 tests

# Preview without posting (also the automatic mode until Telegram is configured):
.venv/bin/python main.py --mode auto --dry-run
.venv/bin/python main.py --mode discovery --dry-run --force
```

If `TELEGRAM_TOKEN` / `TELEGRAM_CHANNEL` are unset, every run **auto-falls back
to dry-run** and never mutates committed state — so nothing is "consumed" before
the channel is wired up.

### `main.py` flags
| Flag | Effect |
|------|--------|
| `--mode auto` | Standard news cycle (default). |
| `--mode discovery` | Weekly "worth watching" pass (gated to Sunday unless `--force`). |
| `--mode week_ahead` | Monday week-ahead preview + macro chart album (gated to Monday unless `--force`). |
| `--mode hidden_value` | Wednesday undervalued/overlooked-essentials post + charts. |
| `--mode head_to_head` | Thursday two-rival compare (rotates pairs). |
| `--mode bubble_index` | Friday AI-froth gauge. |
| `--mode scorecard` | Saturday call track-record report card. |
| `--mode earnings_dd` | Daily — posts a pre-earnings brief when a core name reports soon. |
| `--dry-run` | Run everything, print posts instead of publishing; **no state written**. |
| `--force` | Ignore the weekday/coverage gate. |

---

## Environment / secrets

Local: `.env` (git-ignored). CI: repo **Secrets** with the same names.

| Var | Required | Purpose | If unset |
|-----|----------|---------|----------|
| `DEEPSEEK_KEY` | ✅ | DeepSeek API key (reused from `crypto-market-channel`). | pipeline can't run |
| `TELEGRAM_TOKEN` | for posting | Bot token. | run auto-switches to dry-run |
| `TELEGRAM_CHANNEL` | for posting | **Numeric** channel id (e.g. `-1001234567890`), not `@username`. | run auto-switches to dry-run |
| `FINNHUB_KEY` | optional | Finnhub free tier company news. | company-news source skipped |
| `FRED_API_KEY` | optional | Official FRED API. | keyless FRED CSV fallback used |
| `EIA_API_KEY` | optional | EIA energy cross-check. | EIA source skipped (FRED covers oil) |
| `SEC_USER_AGENT` | recommended | Descriptive UA SEC requires (`name email`). | generic default UA (may be throttled) |

The bot must be an **admin** of the channel it posts to.

---

## Constants reference (every script's knobs)

All live at the top of **`config.py`**. Nothing else needs editing for tuning.

### Watchlist
| Constant | Meaning |
|----------|---------|
| `CORE_TICKERS` | Primary AI names every post may cover: PLTR, NVDA, GOOGL, AMZN, MSFT, AMD, AVGO, SMCI, TSLA, META, MSTR. |
| `MACRO_INSTRUMENTS` | Index + commodities that get their own charts: S&P 500 (`^GSPC`), Gold (`GC=F`), Silver (`SI=F`), Oil (`CL=F`). Label = chart title. |
| `VALUE_UNIVERSE` | Overlooked-but-essential sectors the Hidden Value post reasons over: rare earths/critical minerals, data-center cooling & power, uranium/nuclear, grid, copper, water, semi equipment. |
| `HIDDEN_VALUE_WEEKDAY` / `_MAX_NAMES` / `_CHART_TOP` / `_MIN_UPSIDE_PCT` | Wednesday; how many names to feature/chart; the analyst-upside threshold for the shortlist. |
| `ADJACENT_TICKERS` | Second-order sector groups (`defense_dual_use`, `power_energy_for_datacenters`, `semi_equipment_memory`). Discovery expands these over time. |
| `INDEX_TICKERS` | Broad-market context — `^GSPC` (S&P 500). |
| `MACRO_SERIES` | FRED series ids: `oil_wti`, `oil_brent`, `dollar_index` (enabled). Delete a line to disable a series. |
| `ALL_PRICE_SYMBOLS` | Derived: every symbol the price/technicals layer fetches (deduped). |

### Models
| Constant | Meaning |
|----------|---------|
| `DEEPSEEK_BASE_URL` | OpenAI-compatible endpoint. Change this + the model names to swap providers. |
| `CLASSIFIER_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | Cheap tagging model (`deepseek-chat`), 220 tok, temp 0. |
| `ANALYST_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | The reasoner (`deepseek-v4-pro`), 3000 tok, temp 0.3. See the model note above. |
| `SYNTHESIS_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | The writer (`deepseek-chat`), 900 tok, temp 0.4. |
| `DISCOVERY_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | Discovery/week-ahead writer (`deepseek-chat`), 1400 tok, temp 0.4. |

### Classifier
| Constant | Meaning |
|----------|---------|
| `CATEGORIES` | Allowed tags: earnings / macro / filing / rating / M&A / politics / **bubble_risk** / commodities / other. |
| `WEEK_AHEAD_WEEKDAY` / `WEEK_AHEAD_EARNINGS_DAYS` / `WEEK_AHEAD_CHART_INSTRUMENTS` | Monday; 7-day earnings lookahead; which macro charts go in the album. |
| `RELEVANCE_MIN_SCORE` | Minimum 0–5 score to clear the relevance bar (default 3). |
| `MAX_ITEMS_TO_CLASSIFY_PER_RUN` | Cheap-model call cap per run (60). |
| `MAX_POSTS_PER_RUN` | Max synthesized + published posts per run (4). |

### Technicals (`technicals.py`)
| Constant | Meaning |
|----------|---------|
| `PRICE_LOOKBACK_DAYS` / `PRICE_INTERVAL` | yfinance history window (400d) and interval (`1d`). |
| `RSI_PERIOD` / `RSI_OVERBOUGHT` / `RSI_OVERSOLD` | Wilder RSI period 14; 70/30 bands. |
| `EMA_PERIODS` | `[20, 50, 200]` (summary); `EMA_FAST` / `EMA_SLOW` are the two drawn thick on the chart. |
| `MACD_FAST` / `MACD_SLOW` / `MACD_SIGNAL` | 12 / 26 / 9. |
| `BB_PERIOD` / `BB_STD` | Bollinger 20-period, 2σ. |
| `ATR_PERIOD` / `TREND_SLOPE_LOOKBACK` | ATR 14; EMA-slope confirmation window 5. |
| `LEVEL_LOOKBACK` / `PIVOT_WINDOW` / `MIN_LEVEL_TOUCHES` / `LEVEL_CLUSTER_ATR_MULTIPLIER` | Pivot-cluster support/resistance detection (180 candles, 3-bar pivots, ≥2 touches, ATR×0.4 merge). |

### Chart (`chart_generator.py`)
| Constant | Meaning |
|----------|---------|
| `CHART_DIR` / `CHART_DPI` | Output dir (`charts/`, git-ignored) and image DPI (160). |
| `CHART_DISPLAY_CANDLES` | Render the recent 120 candles (indicators computed on full history). |

### Ingest (`ingest/*.py`)
| Constant | Meaning |
|----------|---------|
| `FINNHUB_BASE_URL` / `FINNHUB_NEWS_LOOKBACK_DAYS` / `FINNHUB_MAX_ITEMS_PER_TICKER` | Finnhub endpoint, 2-day window, ≤8 items/ticker. |
| `SEC_FULLTEXT_SEARCH_URL` / `SEC_SUBMISSIONS_URL` / `SEC_COMPANY_TICKERS_URL` | SEC EDGAR endpoints. |
| `SEC_FORMS_OF_INTEREST` | `10-Q`, `10-K`, `8-K`. |
| `SEC_LOOKBACK_DAYS` / `SEC_USER_AGENT_DEFAULT` | Filing window (3d); UA fallback. |
| `FRED_API_URL` / `FRED_CSV_URL` / `FRED_LOOKBACK_DAYS` | FRED API + keyless CSV fallback; 14-day tail. |
| `EIA_BASE_URL` / `EIA_WTI_SERIES` | EIA endpoint + WTI series. |
| `RSS_FEEDS` / `RSS_MAX_ITEMS_PER_FEED` | Business RSS sources; ≤15 items/feed. Strictly filtered by the classifier. |

### Format (`compliance.py`)
| Constant | Meaning |
|----------|---------|
| `DISCLAIMER_ENABLED` / `DISCLAIMER_TEXT` | Disclaimer footer — **off** by default. |
| `LINT_ENABLED` / `FORBIDDEN_PATTERNS` | Buy/sell/stop/target linter — **off** by default; flip on to reject those patterns. |

### Telegram (`telegram_publisher.py`)
| Constant | Meaning |
|----------|---------|
| `TELEGRAM_TOKEN_ENV` / `TELEGRAM_CHANNEL_ENV` | Env var names read at runtime. |
| `TELEGRAM_MESSAGE_LIMIT` / `TELEGRAM_CAPTION_LIMIT` | 4096-char text cap / 1024-char photo-caption cap. |
| `CHANNEL_NAME` / `CHANNEL_URL` | Optional footer backlink (skipped while empty). |

### Discovery + paths
| Constant | Meaning |
|----------|---------|
| `DISCOVERY_WEEKDAY` | 6 = Sunday. |
| `DISCOVERY_NEWS_LOOKBACK_DAYS` | 7-day context window. |
| `STATE_FILE` / `STAGING_FILE` / `POSTS_LOG_FILE` | `post_history.json` (dedup + filings + last-discovery), `staging.json` (git-ignored), `posts_log.jsonl`. |

---

## Post format

Each news post is a **photo (technical chart) + caption**. The chart shows
candles, EMA 20/50/200, Bollinger Bands, pivot support/resistance (labelled
lines + zones), a volume panel, and an RSI panel with 30/70 lines. The caption:

```
🚀 <viral, informative emoji headline carrying the key number>

📰 What happened: <grounded fact, source named>

📊 The tape:
• price vs Bollinger / EMAs  • RSI (overbought/oversold called out)  • MACD  • support/resistance

👀 What to watch:
• Short term (days): the level that decides the next move
• Midterm (weeks–months): the bigger line (e.g. EMA200 / major support)
```

No disclaimer footer. Discovery posts are text with a `🔭 Worth Watching` header.

---

## Scheduling (GitHub Actions)

- **`.github/workflows/post_update.yml`** — news cycle **3×/day, Mon–Fri**
  (~08:30 / 12:30 / 16:15 ET). Times are UTC aligned to EDT; shift each cron
  +1h during EST if you want to hold the ET slot exactly. Runs tests, then the
  pipeline, then commits updated state with a rebase-retry push loop.
- **`.github/workflows/discovery.yml`** — **weekly, Sunday ~13:00 ET** discovery pass.

Both support `workflow_dispatch` with a `dry_run` toggle (and `force` for discovery).

**Add these repo Secrets before enabling:** `DEEPSEEK_KEY`, `TELEGRAM_TOKEN`,
`TELEGRAM_CHANNEL`, and optionally `FINNHUB_KEY`, `FRED_API_KEY`, `EIA_API_KEY`,
`SEC_USER_AGENT`.

---

## Still to provide

- **Telegram channel** (numeric id) + **bot token** — until then the pipeline
  runs and previews in dry-run automatically.
- Optional: `FINNHUB_KEY` (unlocks company-news headlines — the richest news
  source; currently only SEC/FRED/RSS feed the stream).
