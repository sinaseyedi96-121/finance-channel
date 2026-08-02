# AI Stocks Channel

Automated Telegram pipeline covering AI-driven "hype" stocks and their
second-order beneficiaries: news, fundamentals, technicals, and weekly sector
discovery. Same shape as the `crypto-market-channel` and `ai_news` pipelines —
**ingest → classify → technicals → synthesize → compliance → publish**,
scheduled by GitHub Actions with committed JSON state.

All text generation uses **DeepSeek** (OpenAI-compatible): the cheap
`deepseek-chat` for high-volume classification and **`deepseek-v4-pro`
("DeepSeek Pro", a reasoning model)** for deep synthesis and weekly discovery.
Swapping to Haiku/OpenAI is a `base_url` + `model` change in `config.py` only.

> ⚠️ **`deepseek-v4-pro` is a reasoning model.** `max_tokens` caps *reasoning +
> answer combined*, so the synthesis/discovery token budgets are sized with
> headroom (see `SYNTHESIS_MAX_TOKENS` / `DISCOVERY_MAX_TOKENS`). If a budget is
> set too low the visible answer comes back empty; the pipeline guards against
> that by skipping empty bodies rather than posting them.

---

## Pipeline stages

| # | Stage | Module | Model |
|---|-------|--------|-------|
| 1 | Ingest | `ingest/*.py` | — |
| 2 | Classify + relevance gate | `classifier.py` | `deepseek-chat` (cheap) |
| 3 | Technicals | `technicals.py` | — (pandas, no `pandas_ta`) |
| 4 | Deep synthesis | `synthesizer.py` | `deepseek-v4-pro` |
| 5 | Discovery (weekly) | `discovery.py` | `deepseek-v4-pro` |
| 6 | Compliance / format | `compliance.py` | — |
| 7 | Publish | `telegram_publisher.py` | — |

Orchestrated by `main.py`. State lives in committed JSON (`post_history.json`,
`posts_log.jsonl`); ephemeral CI runners have no other memory between runs.

**Grounding rule (non-negotiable):** synthesis and discovery may only state
figures/facts present in the retrieved-data block passed in the prompt. No
numbers from memory, no invented figures, no price targets. Enforced in the
system prompts *and* by only ever showing the model the data block.

**Compliance:** every post gets a disclaimer footer, and `compliance.lint()`
rejects any body containing buy/sell/entry/stop/target language before it can be
published — descriptive-only framing to stay clear of MiFID II / CONSOB territory.

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env          # fill in keys (DEEPSEEK_KEY is already reused from your setup)
.venv/bin/python -m unittest discover -s tests -v     # 22 tests

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
| `SYNTHESIS_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | `deepseek-v4-pro`, 1200 tok (reasoning + answer), temp 0.3. |
| `DISCOVERY_MODEL` / `_MAX_TOKENS` / `_TEMPERATURE` | `deepseek-v4-pro`, 2200 tok, temp 0.4. |

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
| `EMA_PERIODS` | `[20, 50, 200]`. |
| `MACD_FAST` / `MACD_SLOW` / `MACD_SIGNAL` | 12 / 26 / 9. |
| `BB_PERIOD` / `BB_STD` | Bollinger 20-period, 2σ. |

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

### Compliance (`compliance.py`)
| Constant | Meaning |
|----------|---------|
| `FORBIDDEN_PATTERNS` | Regexes the linter rejects (buy/sell/short/long/stop-loss/take-profit/entry price/price target). Benign uses like "long-term" and "short interest" are deliberately allowed. |
| `COMPLIANCE_DISCLAIMER` | Mandatory footer appended in code. |

### Telegram (`telegram_publisher.py`)
| Constant | Meaning |
|----------|---------|
| `TELEGRAM_TOKEN_ENV` / `TELEGRAM_CHANNEL_ENV` | Env var names read at runtime. |
| `TELEGRAM_MESSAGE_LIMIT` | 4096-char hard cap. |
| `CHANNEL_NAME` / `CHANNEL_URL` | Footer backlink (set `CHANNEL_URL` once you have the public link; skipped while empty). |

### Discovery + paths
| Constant | Meaning |
|----------|---------|
| `DISCOVERY_WEEKDAY` | 6 = Sunday. |
| `DISCOVERY_NEWS_LOOKBACK_DAYS` | 7-day context window. |
| `STATE_FILE` / `STAGING_FILE` / `POSTS_LOG_FILE` | `post_history.json` (dedup + filings + last-discovery), `staging.json` (git-ignored), `posts_log.jsonl`. |

---

## Post format

```
📊 $TICKER — YYYY-MM-DD
What happened: <grounded fact, source named>
Why it matters: <synthesis, grounded>
Numbers to know: last price, % change, key technical level, next earnings (if in data)
⚠️ Informational only, not financial advice. …
```

Discovery posts use a `🔭 Worth Watching` header and end with an explicit
"informational starting points, not recommendations" line.

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
