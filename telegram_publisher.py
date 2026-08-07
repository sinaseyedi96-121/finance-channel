"""
Stage 7 — publish to Telegram via the Bot API directly (no SDK needed for
something this simple, matching the crypto-market-channel style).

Uses the NUMERIC channel id (e.g. -1001234567890), not @username, read from the
TELEGRAM_CHANNEL env var. The bot must be an admin of the channel.
"""

from __future__ import annotations

import json
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


def post_text(text: str) -> dict:
    """Send a PLAIN-text message (no parse_mode) — safe for free-form writeups
    containing <, >, & that would break HTML parsing."""
    resp = requests.post(
        f"{_base_url()}/sendMessage",
        data={
            "chat_id": _chat_id(),
            "text": text[: config.TELEGRAM_MESSAGE_LIMIT],
            "disable_web_page_preview": "true",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]


def post_photo(image_path: str, caption: str, parse_mode: str | None = None) -> dict:
    """Send a chart image with a caption. Plain text by default; pass
    parse_mode="HTML" for captions built with compliance.format_caption_with_detail
    (already sized in decoded-text space) — naive truncation here would otherwise
    slice mid-tag/mid-entity and break Telegram's HTML parser, so we only clip
    blindly on the plain-text path."""
    if not parse_mode:
        caption = caption[: config.TELEGRAM_CAPTION_LIMIT]
    data = {"chat_id": _chat_id(), "caption": caption}
    if parse_mode:
        data["parse_mode"] = parse_mode
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{_base_url()}/sendPhoto",
            data=data,
            files={"photo": f},
            timeout=45,
        )
    resp.raise_for_status()
    return resp.json()["result"]


def post_album(image_paths: list, caption: str = "", parse_mode: str | None = None) -> dict:
    """Send up to 10 charts as one media-group album; caption rides on the first
    image. See post_photo for why blind truncation is skipped on the HTML path."""
    if not parse_mode:
        caption = caption[: config.TELEGRAM_CAPTION_LIMIT]
    media = []
    files = {}
    try:
        for i, path in enumerate(image_paths[:10]):
            key = f"chart{i}"
            item = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and caption:
                item["caption"] = caption
                if parse_mode:
                    item["parse_mode"] = parse_mode
            media.append(item)
            files[key] = open(path, "rb")
        resp = requests.post(
            f"{_base_url()}/sendMediaGroup",
            data={"chat_id": _chat_id(), "media": json.dumps(media)},
            files=files,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["result"][0]
    finally:
        for fh in files.values():
            fh.close()
