"""
OpenAI-compatible client factory for DeepSeek.

Everything model-facing goes through here so swapping DeepSeek <-> Haiku <->
OpenAI is a base_url/model change in config.py only. The API key is read from
the DEEPSEEK_KEY env var (same var name as crypto-market-channel, so the key
you already have is reused verbatim).
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
