# AI Stocks Channel

Automated Telegram pipeline covering AI-driven "hype" stocks and their
second-order beneficiaries: news, fundamentals, technicals, and weekly sector
discovery. Same shape as the `crypto-market-channel` and `ai_news` pipelines —
**ingest → classify → technicals → chart + caption → publish**, scheduled by
GitHub Actions with committed JSON state.

Each news post is a **crypto-style technical chart** (candles + support/resistance
+ Bollinger + EMA 20/50/200 + RSI panel) with a **viral, emoji-rich caption**:
headline → what happened → the tape read → what to watch (short-term / midterm).
No legal disclaimer footer (owner's choice — toggle in `config.py`).

Text generation uses **DeepSeek** (OpenAI-compatible). Swapping to Haiku/OpenAI
is a `base_url` + `model` change in `config.py` only.

> ⚠️ **Why captions use `deepseek-chat`, not `deepseek-v4-pro`.** `deepseek-v4-pro`
> ("DeepSeek Pro") is a *reasoning* model: `max_tokens` caps reasoning + answer
> combined, and on short writing tasks it reasons **without bound** — measured, it
> consumed 2500 then 4000 tokens *entirely on reasoning* and returned an **empty
> answer every time** (`finish_reason=length`). So it's unusable as the caption
> writer at any sane budget. `deepseek-chat` writes the same caption reliably and
> instantly (`finish_reason=stop`). The model names live in `config.py`; there's
> also an empty-answer fallback to `deepseek-chat` in `synthesizer.py` if you ever
> switch the primary back.

---

## Pipeline stages

| # | Stage | Module | Model |
|---|-------|--------|-------|
| 1 | Ingest | `ingest/*.py` | — |
| 2 | Classify + relevance gate | `classifier.py` | `deepseek-chat` (cheap) |
| 3 | Technicals + S/R levels | `technicals.py` | — (pandas, no `pandas_ta`) |
| 4 | Caption synthesis | `synthesizer.py` | `deepseek-chat` |
| 5 | Chart render | `chart_generator.py` | — (mplfinance) |
| 6 | Discovery (weekly) | `discovery.py` | `deepseek-chat` |
| 7 | Format | `compliance.py` | — |
| 8 | Publish (photo + caption) | `telegram_publisher.py` | — |

Orchestrated by `main.py`. State lives in committed JSON (`post_history.json`,
`posts_log.jsonl`); ephemeral CI runners have no other memory between runs.

**Grounding rule (non-negotiable):** the caption may only state figures/facts
present in the retrieved-data block passed in the prompt — and the technical
numbers in that block are the *same ones drawn on the chart*, so caption and
chart always agree. No numbers from memory, no invented figures.

**Format layer (`compliance.py`):** appends no disclaimer and runs no linter by
default (`DISCLAIMER_ENABLED` / `LINT_ENABLED` are `False`). Both can be switched
back on in `config.py` if the channel ever monetizes and wants trade-rec-safe
framing. It also strips stray markdown (`**bold**`) since captions post as plain text.

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env          # fill in keys (DEEPSEEK_KEY is already reused from your setup)
.venv/bin/python -m unittest discover -s tests -v     # 25 tests

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
| `--dry-run` | Run everything, print posts instead of publishing; **no state written**. |
| `--force` | Ignore the discovery weekday gate. |

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
| `CORE_TICKERS` | Primary names every post may cover: PLTR, NVDA, GOOGL, AMZN, MSFT, AMD, AVGO, SMCI, TSLA, META, MSTR. |
| `ADJACENT_TICKERS` | Second-order sector groups (`defense_dual_use`, `power_energy_for_datacenters`, `semi_equipment_memory`). Discovery expands these over time. |
| `INDEX_TICKERS` | Broad-market context — `^GSPC` (S&P 500). |
| `MACRO_SERIES` | FRED series ids: `oil_wti`, `oil_brent`, `dollar_index` (enabled). Delete a line to disable a series. |
| `ALL_PRICE_SYMBOLS` | Derived: every symbol the price/technicals layer fetches (deduped). |

### Models
| Constant | Meaning |
|----------|---------|
| `DEEPSEEK_BASE_URL` | OpenAI-compatible endpoint. Change this + the model names to swap providers. |
| `CLASSIFIER_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | Cheap tagging model (`deepseek-chat`), 220 tok, temp 0. |
| `SYNTHESIS_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | Caption writer (`deepseek-chat`), 900 tok, temp 0.4. See the model note above for why not `deepseek-v4-pro`. |
| `SYNTHESIS_FALLBACK_MODEL` / `_MAX_TOKENS` | Used if the primary returns empty (`deepseek-chat`, 900 tok). |
| `DISCOVERY_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | `deepseek-chat`, 1400 tok, temp 0.4. |

### Classifier
| Constant | Meaning |
|----------|---------|
| `CATEGORIES` | Allowed tags: earnings / macro / filing / rating / M&A / politics / other. |
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
