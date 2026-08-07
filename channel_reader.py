"""
Best-effort reader for channel ENGAGEMENT — the phase-2 seed that lets the
review council learn from what readers actually respond to, not only from what
the critic models think is good.

A SECOND bot (@finance_aar_reader_bot, token in FINANCE_AAR_READER_BOT) that is
an admin of the channel receives reaction updates. This module polls getUpdates
for reaction counts on recent posts and hands them to reviewer.run_review as a
weak signal.

HARD LIMITS — read before trusting this (and why it is only a *seed*):
  * The Bot API cannot fetch channel history. getUpdates only returns updates
    the bot has not yet consumed, buffered for ~24h. In a stateless cron this
    means we see whatever reactions happened to arrive in the window — partial,
    never a full backfill. (Full view/read counts need an MTProto USER session,
    e.g. Telethon — out of scope, intentionally.)
  * It requires the reader bot to be a channel admin AND reactions to be enabled
    on the channel, with allowed_updates including message_reaction_count.
  * Every failure path returns [] so the council falls back to running on
    posts_log.jsonl exactly as before. This must NEVER break the daily review.

Because of all that, the council is told to treat these counts as a weak signal,
not ground truth (see reviewer._shared_context).
"""

from __future__ import annotations

import os

import requests

import config

_API = "https://api.telegram.org/bot{token}/{method}"
# Poll must opt in to reaction updates — they're off by default in getUpdates.
_ALLOWED_UPDATES = ["channel_post", "message_reaction", "message_reaction_count"]
_MAX_POSTS = 20


def _token() -> str | None:
    return os.environ.get(config.READER_BOT_TOKEN_ENV) or None


def _get_updates(token: str) -> list[dict]:
    resp = requests.post(
        _API.format(token=token, method="getUpdates"),
        json={"allowed_updates": _ALLOWED_UPDATES, "timeout": 0, "limit": 100},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("result", []) if payload.get("ok") else []


def _summarise(updates: list[dict]) -> list[dict]:
    """Fold raw updates into one row per message: an optional text excerpt (from
    any channel_post we happened to catch) plus reaction totals (from
    message_reaction_count updates)."""
    excerpts: dict[int, str] = {}
    reactions: dict[int, list[dict]] = {}

    for upd in updates:
        post = upd.get("channel_post")
        if post and post.get("message_id"):
            text = (post.get("caption") or post.get("text") or "").strip()
            if text:
                excerpts[post["message_id"]] = text[:120]

        rc = upd.get("message_reaction_count")
        if rc and rc.get("message_id"):
            rows = [{"emoji": (r.get("type") or {}).get("emoji") or "?",
                     "count": int(r.get("total_count") or 0)}
                    for r in rc.get("reactions", [])]
            if rows:
                reactions[rc["message_id"]] = rows

    out = []
    for mid, rows in reactions.items():
        out.append({
            "message_id": mid,
            "excerpt": excerpts.get(mid, ""),
            "total_reactions": sum(r["count"] for r in rows),
            "reactions": sorted(rows, key=lambda r: r["count"], reverse=True),
        })
    out.sort(key=lambda e: e["total_reactions"], reverse=True)
    return out[:_MAX_POSTS]


def fetch_engagement() -> list[dict]:
    """Best-effort reaction signal for recent posts. Returns [] on any missing
    token, network error, or empty poll — never raises, so the council degrades
    to log-only cleanly."""
    if not config.CHANNEL_ENGAGEMENT_ENABLED:
        return []
    token = _token()
    if not token:
        return []
    try:
        updates = _get_updates(token)
        return _summarise(updates)
    except Exception as exc:  # noqa: BLE001 — engagement is optional; log and move on
        print(f"[channel_reader] engagement unavailable: {exc}")
        return []
