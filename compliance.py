"""
Stage 6 — format layer (formerly "compliance").

The channel is personal/informational and, by the owner's choice, does NOT
append a legal disclaimer footer and does NOT run the descriptive-only linter.
Both are kept here behind config toggles (DISCLAIMER_ENABLED / LINT_ENABLED) so
they can be switched back on later (e.g. if the channel monetizes) without a
code change.

Outputs:
  * format_caption(body)   — photo caption (plain text + emojis), capped at the
    Telegram caption limit. Used for the chart posts.
  * format_post(header, body) — HTML text message. Used for the weekly discovery
    post (no chart).
  * format_caption_with_detail(body, detail) — HTML photo/album caption: the
    visible body plus an optional <blockquote expandable> holding extra detail
    (mover context, fuller reasoning) that Telegram folds behind "Show more".
    Both halves count against the same caption budget, so the detail is clipped
    to whatever room is left after the visible body.
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


def _clip(text: str, limit: int) -> str:
    """Trim to `limit` (inclusive of the ellipsis we add), cutting at a line/word
    boundary so we never leave a sentence chopped mid-word."""
    if len(text) <= limit:
        return text
    ell = " …"
    window = text[: max(0, limit - len(ell))]
    cut = window.rfind("\n")
    if cut < len(window) * 0.6:           # no good line break near the end — try a space
        cut = window.rfind(" ")
    return (window[:cut] if cut > 0 else window).rstrip() + ell


DETAIL_MARKER = "===MORE==="


def split_detail(text: str) -> tuple[str, str | None]:
    """Split a writer's raw output on DETAIL_MARKER into (visible, detail).
    detail is None when the marker is absent (writer had nothing extra to add,
    or is a stage that doesn't know the contract) — always safe to call."""
    if DETAIL_MARKER not in text:
        return text, None
    visible, _, detail = text.partition(DETAIL_MARKER)
    detail = detail.strip()
    return visible.strip(), (detail or None)


def format_caption_with_detail(body: str, detail: str | None = None) -> str:
    """HTML photo/album caption: visible body + optional expandable blockquote.

    The visible body is never truncated to make room for detail — detail only
    fills whatever budget is left over, and is dropped entirely if there isn't
    enough of it to be worth showing.
    """
    violations = lint(body) + lint(detail or "")
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    disclaimer = _disclaimer()
    visible = _clip(_strip_markdown(body).strip(), config.TELEGRAM_CAPTION_LIMIT - len(disclaimer))
    caption = html.escape(visible) + html.escape(disclaimer)
    remaining = config.TELEGRAM_CAPTION_LIMIT - len(disclaimer) - len(visible)
    detail = _strip_markdown(detail).strip() if detail else ""
    if detail and remaining > 40:
        detail = _clip(detail, remaining)
        caption += f"\n\n<blockquote expandable>{html.escape(detail)}</blockquote>"
    return caption


def format_caption(body: str) -> str:
    """Photo caption: plain text + emojis, optional lint/disclaimer, hard-capped.

    Raises ValueError only if linting is ON and the body trips a pattern.
    """
    violations = lint(body)
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    disclaimer = _disclaimer()
    caption = _strip_markdown(body).strip()
    return _clip(caption, config.TELEGRAM_CAPTION_LIMIT - len(disclaimer)) + disclaimer


def format_post(header: str, body: str, detail: str | None = None) -> str:
    """HTML text message (discovery, and non-chart news items). Body is
    HTML-escaped; optional detail rides in an expandable blockquote, budgeted
    from the (roomier) message limit rather than the caption limit."""
    violations = lint(body) + lint(detail or "")
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    disclaimer = _disclaimer()
    head = f"<b>{html.escape(header)}</b>\n\n"
    budget = config.TELEGRAM_MESSAGE_LIMIT - len(head) - len(disclaimer)
    visible = _clip(body.strip(), budget)
    post = head + html.escape(visible) + html.escape(disclaimer)
    remaining = budget - len(visible)
    detail = detail.strip() if detail else ""
    if detail and remaining > 40:
        detail = _clip(detail, remaining)
        post += f"\n\n<blockquote expandable>{html.escape(detail)}</blockquote>"
    return post


def format_message(body: str) -> str:
    """Plain-text message (emoji, no HTML/markdown), clipped to the message limit.

    Used for long free-form writeups (e.g. Hidden Value) that contain characters
    like <, >, & which would break Telegram's HTML parser — so these are sent with
    no parse_mode.
    """
    violations = lint(body)
    if violations:
        raise ValueError(f"lint violation: {sorted(set(v.lower() for v in violations))}")
    disclaimer = _disclaimer()
    text = _strip_markdown(body).strip()
    return _clip(text, config.TELEGRAM_MESSAGE_LIMIT - len(disclaimer)) + disclaimer
