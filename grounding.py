"""
Stage 5.5 — mechanical grounding gate.

The prompts already ORDER the models not to invent numbers; this module ENFORCES
it. Every number in a draft caption is extracted and checked against the set of
values actually present in the retrieved data (news text, technical snapshot,
fundamentals, macro context). A number that cannot be traced to the data flags
the draft; the caller retries the writer once with the offending figures named,
then skips the post if it still fails.

Matching is deliberately forgiving about FORMAT (rounding, $/%,/thousands
separators, K/M/B/T suffixes, sign) and strict about SUBSTANCE: "≈$231" grounds
against 231.44, "3.5B" against 3_487_000_000 — but a revenue figure or percent
the data never contained has nothing to match and gets flagged.
"""

from __future__ import annotations

import re

import config

# $1,234.56 / 63.4 / 12% / 3.5B — number with optional thousands separators and
# an optional magnitude suffix (K/M/B/T, incl. "bn"/"tn"/"billion" spelled out).
# The suffix must end the word so the "m" of "3.5 months" is not read as million.
_NUMBER_RE = re.compile(
    r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*"
    r"(?:([kKmMbBtT])(?:r?illion|n)?(?![A-Za-z]))?",
)

_SCALE_EXP = {"k": 3, "m": 6, "b": 9, "t": 12}
# Magnitude scales tried when matching a caption figure against a data value:
# big values quoted compactly ("3.5B" or a bare "3.5" against 3_487_000_000),
# and ratio-vs-percent unit mismatches (0.23 in the data, "23%" in the caption).
_DOWN_SCALES = (1.0, 1e2, 1e3, 1e6, 1e9, 1e12)
_UP_SCALES = (1e2, 1e3)

# Numbers a finance caption may always use without data support: indicator
# parameters that are part of the chart itself (RSI 14/30/70, EMA 20/50/200,
# MACD 12/26, 52-week), hours-in-a-day, and any small integer (ranks, counts,
# conviction 1-10). Years are handled separately.
_WHITELIST = {12, 14, 20, 24, 26, 30, 50, 52, 70, 200}
_YEAR_RANGE = (1990, 2035)


def _parse(match: re.Match) -> tuple[float, int]:
    """Return (value, decimals) for a regex match. A magnitude suffix scales the
    value AND shifts the precision with it: "2.5T" means 2.5e12 known to half of
    0.1e12 — so decimals goes negative and the rounding check stays honest at
    full magnitude."""
    whole = match.group(1).replace(",", "")
    frac = match.group(2) or ""
    value = float(whole + frac)
    decimals = max(0, len(frac) - 1)
    suffix = (match.group(3) or "").lower()
    if suffix:
        exp = _SCALE_EXP[suffix]
        value *= 10 ** exp
        decimals -= exp
    return value, decimals


def extract_numbers(text: str) -> list[tuple[float, int, str]]:
    """All numbers in `text` as (value, decimals, raw_snippet)."""
    out = []
    for m in _NUMBER_RE.finditer(text or ""):
        value, decimals = _parse(m)
        out.append((value, decimals, m.group(0).strip()))
    return out


def allowed_values(sources: list) -> set[float]:
    """Every numeric value reachable in the source data — numeric leaves of
    nested dicts/lists plus numbers parsed out of string fields (headlines and
    summaries carry figures as prose)."""
    found: set[float] = set()

    def walk(node):
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            found.add(float(node))
        elif isinstance(node, str):
            for value, _decimals, _raw in extract_numbers(node):
                found.add(value)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    for source in sources:
        walk(source)
    return found


def _is_whitelisted(value: float, decimals: int) -> bool:
    if decimals == 0:
        if abs(value) <= config.GROUNDING_SMALL_INT_MAX:
            return True
        if value in _WHITELIST:
            return True
        if _YEAR_RANGE[0] <= value <= _YEAR_RANGE[1]:
            return True
    return False


def _matches(value: float, decimals: int, allowed: set[float]) -> bool:
    """True if some allowed value rounds to `value` at the caption's own
    precision (within half a unit of the last quoted digit, so 1.85 grounds
    both "1.8" and "1.9"), at any magnitude scale (3.5B against 3.49e9, "23%"
    against a 0.23 ratio), in either sign, or within the relative tolerance."""
    half_ulp = 0.5 * 10 ** -decimals * 1.000001   # epsilon for float noise
    for a in allowed:
        for candidate in (a, -a):
            scaled_forms = [candidate / s for s in _DOWN_SCALES]
            scaled_forms += [candidate * s for s in _UP_SCALES]
            for scaled in scaled_forms:
                if abs(scaled - value) <= half_ulp:
                    return True
                if value and abs(scaled - value) / abs(value) <= config.GROUNDING_REL_TOL:
                    return True
    return False


def verify(text: str, sources: list) -> list[str]:
    """Return the raw snippets of every ungrounded number in `text` (empty list
    means the draft passed). Disabled via config.GROUNDING_ENABLED."""
    if not config.GROUNDING_ENABLED:
        return []
    allowed = allowed_values(sources)
    flagged = []
    for value, decimals, raw in extract_numbers(text):
        if _is_whitelisted(value, decimals):
            continue
        if _matches(value, decimals, allowed):
            continue
        flagged.append(raw)
    return flagged


def retry_feedback(flagged: list[str]) -> str:
    """The correction note appended to the writer's prompt on the one retry."""
    return (
        "\n\n⚠️ YOUR PREVIOUS DRAFT WAS REJECTED by the grounding check. These "
        f"figures do not exist in the RETRIEVED DATA: {', '.join(flagged)}. "
        "Rewrite the caption using ONLY figures that appear in the data block — "
        "drop any figure you cannot source from it."
    )
