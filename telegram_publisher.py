"""
Stage 7 — publish to Telegram via the Bot API directly (no SDK needed for
something this simple, matching the crypto-market-channel style).

Uses the NUMERIC channel id (e.g. -1001234567890), not @username, read from the
TELEGRAM_CHANNEL env var. The bot must be an admin of the channel.
"""

from __future__ import annotations

import os

import requests

import config


def _token() -> str:
    return os.environ[config.TELEGRAM_TOKEN_ENV]


def _chat_id() -> str:
    return os.environ[config.TELEGRAM_CHANNEL_ENV]


def _base_url() -> str:
    return f"https://api.telegram.org/bot{_token()}"


def post_message(text: str) -> dict:
    """Send an HTML-parsed text message to the configured channel. Returns the
    Telegram message object (message_id etc.)."""
    resp = requests.post(
        f"{_base_url()}/sendMessage",
        data={
            "chat_id": _chat_id(),
            "text": text[: config.TELEGRAM_MESSAGE_LIMIT],
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]
