"""
OpenAI-compatible client factory for DeepSeek — and, for the review council, a
second factory for OpenAI proper.

Everything model-facing goes through here so swapping DeepSeek <-> Haiku <->
OpenAI is a base_url/model change in config.py only. The DeepSeek key is read
from the DEEPSEEK_KEY env var (same var name as crypto-market-channel, so the
key you already have is reused verbatim); the OpenAI key from OPENAI_KEY.

Both providers speak the same OpenAI SDK, but they disagree on two request
parameters, so complete() normalises them (see its docstring):
  * newer OpenAI models (gpt-5.x) reject `max_tokens` — they want
    `max_completion_tokens` — and reject any non-default `temperature`;
  * DeepSeek's reasoning model (deepseek-v4-pro) often returns an empty
    `content` with the analysis in `reasoning_content` instead.
Callers of complete() get plain text back and never have to care which
provider or quirk they hit.
"""

from __future__ import annotations

import os
from openai import OpenAI

import config


def get_client() -> OpenAI:
    """Build the DeepSeek client from env + config."""
    return OpenAI(
        api_key=os.environ["DEEPSEEK_KEY"],
        base_url=config.DEEPSEEK_BASE_URL,
    )


def get_openai_client() -> OpenAI:
    """Build the OpenAI client for the review council. Raises KeyError when
    OPENAI_KEY is unset — callers (reviewer._council_clients) catch that and
    fall back to DeepSeek so a missing key degrades gracefully rather than
    crashing the daily review."""
    return OpenAI(
        api_key=os.environ["OPENAI_KEY"],
        base_url=config.OPENAI_BASE_URL,
    )


def _is_openai(client: OpenAI) -> bool:
    """True when `client` points at OpenAI proper rather than a compatible
    provider like DeepSeek. We key off the base_url because the SDK object
    itself doesn't carry a provider label."""
    return "openai.com" in str(client.base_url)


def complete(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float | None = None,
) -> str:
    """Provider-aware one-shot completion used by the review council.

    Normalises the two provider disagreements so callers stay provider-agnostic:
      * OpenAI (gpt-5.x): send `max_completion_tokens`, and OMIT `temperature`
        entirely (these models only accept the default and 400 on anything else).
      * DeepSeek / compatible: send `max_tokens` + `temperature` as usual, and
        fall back to `reasoning_content` when `content` comes back empty (the
        deepseek-v4-pro quirk, same handling as reason()).
    """
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if _is_openai(client):
        kwargs["max_completion_tokens"] = max_tokens
        # temperature deliberately omitted — gpt-5.x rejects non-default values.
    else:
        kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
    msg = client.chat.completions.create(**kwargs).choices[0].message
    content = (msg.content or "").strip()
    if content:
        return content
    return (getattr(msg, "reasoning_content", "") or "").strip()


def chat(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
) -> str:
    """One-shot chat completion returning the assistant text.

    Kept deliberately thin so classifier/synthesizer/discovery share one code
    path and tests can monkeypatch this single function instead of the SDK.
    """
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def reason(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
) -> str:
    """Run a reasoning model (deepseek-v4-pro) and return its analysis.

    deepseek-v4-pro often spends the whole budget on chain-of-thought and returns
    an EMPTY `content` — but the analysis itself lives in `reasoning_content`. So
    we return `content` when present, otherwise fall back to `reasoning_content`.
    Either way the caller gets the model's actual analysis to hand to the writer
    model (deepseek-chat) for publishing.
    """
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    msg = response.choices[0].message
    content = (msg.content or "").strip()
    reasoning = (getattr(msg, "reasoning_content", "") or "").strip()
    return content or reasoning
