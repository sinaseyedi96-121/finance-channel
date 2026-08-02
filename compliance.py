"""
Stage 6 — compliance / format layer.

Two jobs:
  1. LINT: reject any generated body that contains buy/sell/entry/stop/target
     language (config.FORBIDDEN_PATTERNS). Descriptive-only framing keeps the
     channel clear of MiFID II / CONSOB territory on repeated public trade recs.
  2. FORMAT: assemble the final Telegram-ready post — header + body + mandatory
     disclaimer footer + channel backlink — with the body HTML-escaped for
     Telegram's HTML parse mode. The footer is appended in code, never left to
     the model to remember.
"""

from __future__ import annotations

import datetime as dt
import html
import re

import config

_COMPILED = [re.compile(p, re.IGNORECASE) for p in config.FORBIDDEN_PATTERNS]


def lint(text: str) -> list[str]:
    """Return the list of forbidden phrases found (empty == clean)."""
    hits: list[str] = []
    for pattern in _COMPILED:
        for match in pattern.finditer(text or ""):
            hits.append(match.group(0))
    return hits


def is_compliant(text: str) -> bool:
    return not lint(text)


def build_header(tickers: list[str] | None, date: dt.date | None = None,
                 label: str | None = None) -> str:
    date = date or dt.date.today()
    tag = label or (" · ".join(f"${t}" for t in tickers) if tickers else "Market")
    return f"📊 {tag} — {date.isoformat()}"


def _footer() -> str:
    footer = config.COMPLIANCE_DISCLAIMER
    if config.CHANNEL_URL:
        footer += f'\n\n<a href="{config.CHANNEL_URL}">{html.escape(config.CHANNEL_NAME)}</a>'
    return footer


def format_post(header: str, body: str) -> str:
    """Assemble a compliant, Telegram-HTML-ready post.

    Raises ValueError if the body contains forbidden language — the caller
    should skip publishing rather than post something non-compliant.
    """
    violations = lint(body)
    if violations:
        raise ValueError(f"compliance violation: {sorted(set(v.lower() for v in violations))}")
    safe_header = html.escape(header)
    safe_body = html.escape(body.strip())
    post = f"<b>{safe_header}</b>\n\n{safe_body}{_footer()}"
    return post[: config.TELEGRAM_MESSAGE_LIMIT]
