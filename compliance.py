"""
Stage 6 — format layer (formerly "compliance").

The channel is personal/informational and, by the owner's choice, does NOT
append a legal disclaimer footer and does NOT run the descriptive-only linter.
Both are kept here behind config toggles (DISCLAIMER_ENABLED / LINT_ENABLED) so
they can be switched back on later (e.g. if the channel monetizes) without a
code change.

Two outputs:
  * format_caption(body)   — photo caption (plain text + emojis), capped at the
    Telegram caption limit. Used for the chart posts.
  * format_post(header, body) — HTML text message. Used for the weekly discovery
    post (no chart).
"""

from __future__ import annotations

import datetime as dt
import html
import re

import config

_COMPILED = [re.compile(p, re.IGNORECASE) for p in config.FORBIDDEN_PATTERNS]


def _scan(text: str) -> list[str]:
    """Always scans, regardless of the toggle (used by tests + optional gate)."""
    hits: list[str] = []
    for pattern in _COMPILED:
        hits.extend(m.group(0) for m in pattern.finditer(text or ""))
    return hits


def lint(text: str, enabled: bool | None = None) -> list[str]:
    """Return forbidden-phrase hits when linting is enabled, else []."""
    if enabled is None:
        enabled = config.LINT_ENABLED
    return _scan(text) if enabled else []


def is_compliant(text: str) -> bool:
    return not lint(text)


def _disclaimer() -> str:
    return config.DISCLAIMER_TEXT if config.DISCLAIMER_ENABLED else ""


def build_header(tickers: list | None, date: dt.date | None = None,
                 label: str | None = None) -> str:
    date = date or dt.date.today()
    tag = label or (" · ".join(f"${t}" for t in tickers) if tickers else "Market")
    return f"📊 {tag} — {date.isoformat()}"


def _strip_markdown(text: str) -> str:
    """Captions are sent as plain text (no parse_mode), so markdown emphasis
    markers would show literally. Remove **bold** / __underline__ / stray `#`."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    return text


def format_caption(body: str) -> str:
    """Photo caption: plain text + emojis, optional lint/disclaimer, hard-capped.

    Raises ValueError only if linting is ON and the body trips a pattern.
    """
    violations = lint(body)
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    caption = _strip_markdown(body).strip() + _disclaimer()
    return caption[: config.TELEGRAM_CAPTION_LIMIT]


def format_post(header: str, body: str) -> str:
    """HTML text message (discovery). Body is HTML-escaped for Telegram."""
    violations = lint(body)
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    post = f"<b>{html.escape(header)}</b>\n\n{html.escape(body.strip())}{_disclaimer()}"
    return post[: config.TELEGRAM_MESSAGE_LIMIT]
