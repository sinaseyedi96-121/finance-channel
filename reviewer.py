"""
The REVIEW AGENT — the channel's editor-in-chief, run daily after the last
posting slot.

It reads what the channel actually published (posts_log.jsonl now carries the
full caption + chart metadata for every post — the pipeline's own copy of the
channel content, since the Bot API can't fetch channel history), then:

  1. MECHANICAL CHECKS (deterministic, no model): same-ticker repeats in a day,
     category streaks, charts drawn with unvalidated (weak) S/R levels,
     grounding flags, captions near the Telegram limit, missing verdict lines.
  2. PRO CRITIQUE (deepseek-v4-pro via reason()): reads the posts + the
     mechanical findings like an editor — redundancy, variety, caption quality,
     chart honesty, cadence — and says what should change.
  3. DIRECTIVES (deepseek-chat): distills the critique into at most
     REVIEW_MAX_DIRECTIVES short imperative notes, saved to
     editorial_notes.json. The analyst and writer prompts load these notes on
     every subsequent post — that is the loop that makes tomorrow's content
     better than today's.

The full dated review is committed under reviews/ so improvements that need a
CODE change (not just a prompt nudge) are on record for the maintainer.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import config
from llm_client import chat, reason

REVIEW_SYSTEM = """You are the editor-in-chief of a finance/markets Telegram
channel (AI-boom era: AI stocks central, plus index, commodities, macro and
AI-bubble risk). You are reviewing what the channel ACTUALLY PUBLISHED over the
last few days — full captions plus the metadata of each attached chart — along
with a list of mechanical findings already detected.

Critique like an editor who must keep readers subscribed:
- REDUNDANCY: multiple posts on the same ticker/story that should have been one
  post, or should have taken a different format (e.g. a market-cap leaderboard,
  a sector read) instead of a second look at the same name.
- VARIETY & MIX: categories/formats over-represented or missing; is the channel
  one-note this week?
- CHART HONESTY: levels drawn from few touches, price far from the drawn levels,
  anything a chart-literate reader would call arbitrary.
- CAPTION QUALITY: headlines that bury the number, verdicts that hedge, repeated
  phrasing/emoji patterns across posts, captions clipped by the length limit.
- CADENCE: posts bunched or sparse in a way readers would notice.

Be specific and quote the offending posts. End with the 3-5 changes that would
most improve the NEXT posts."""

DIRECTIVES_SYSTEM = f"""You turn an editor's critique into machine-usable notes.
Output STRICT JSON, nothing else: {{"directives": ["...", ...]}} with at most
{config.REVIEW_MAX_DIRECTIVES} entries. Each directive: one imperative sentence,
under 160 characters, concrete enough that a caption-writing model can obey it
directly (e.g. "Vary headline emoji — last 4 posts all opened with 🚨").
Only include directives about content/format/style the WRITER or ANALYST can
act on per-post; drop anything requiring a code change."""


# ---- reading the log --------------------------------------------------

def load_recent_posts(days: int = config.REVIEW_LOOKBACK_DAYS) -> list[dict]:
    """Published (non-dry-run) log entries from the last `days` UTC days."""
    if not os.path.exists(config.POSTS_LOG_FILE):
        return []
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    out = []
    with open(config.POSTS_LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("dry_run"):
                continue
            try:
                ts = dt.datetime.fromisoformat(entry.get("ts", "").replace("Z", ""))
            except ValueError:
                continue
            if ts >= cutoff:
                out.append(entry)
    return out


# ---- mechanical checks ------------------------------------------------

def mechanical_findings(entries: list[dict]) -> list[str]:
    """Deterministic problems — found without a model, so never missed."""
    findings: list[str] = []

    # Same ticker covered more than once in a UTC day.
    per_day: dict[tuple, int] = {}
    for e in entries:
        if e.get("ticker"):
            key = (e["ts"][:10], e["ticker"])
            per_day[key] = per_day.get(key, 0) + 1
    for (day, ticker), n in sorted(per_day.items()):
        if n > 1:
            findings.append(f"{ticker} was covered {n} times on {day} — "
                            "should have been one post or a different format.")

    # Category streaks among news posts.
    cats = [e.get("category") for e in entries if e.get("mode") == "auto" and e.get("category")]
    streak, prev = 1, None
    for c in cats:
        streak = streak + 1 if c == prev else 1
        if streak >= 3:
            findings.append(f"3+ consecutive '{c}' news posts — the mix is one-note.")
            streak = 1
        prev = c

    for e in entries:
        chart = e.get("chart") or {}
        for side in ("support", "resistance"):
            touches = chart.get(f"{side}_touches")
            if touches is not None and touches < config.MIN_LEVEL_TOUCHES:
                findings.append(
                    f"{e.get('ticker') or e.get('mode')} chart ({e['ts'][:10]}) drew a "
                    f"{side} line from only {touches} touch(es) — weak level.")
        if e.get("grounding_flags"):
            findings.append(
                f"{e.get('ticker') or e.get('mode')} post ({e['ts'][:10]}) carried "
                f"ungrounded figures: {e['grounding_flags']}.")
        caption = e.get("caption") or ""
        if caption:
            if len(caption) > config.TELEGRAM_CAPTION_LIMIT * 0.95:
                findings.append(
                    f"{e.get('ticker') or e.get('mode')} caption ({e['ts'][:10]}) is at "
                    f"{len(caption)} chars — brushing the Telegram limit, risks clipping.")
            if e.get("mode") == "auto" and "🎯" not in caption:
                findings.append(
                    f"{e.get('ticker')} news caption ({e['ts'][:10]}) has no 🎯 Verdict line.")
    return findings


# ---- the review -------------------------------------------------------

def _posts_digest(entries: list[dict]) -> str:
    """Compact JSON the models read — captions in full, metadata trimmed."""
    slim = []
    for e in entries:
        slim.append({k: v for k, v in e.items() if k in
                     ("ts", "mode", "ticker", "category", "caption", "chart",
                      "grounding_flags", "pair", "score")})
    return json.dumps(slim, ensure_ascii=False, indent=1)


def run_review(client, entries: list[dict], findings: list[str]) -> tuple[str, list[str]]:
    """Pro critiques, Chat distills. Returns (critique_text, directives)."""
    user = ("PUBLISHED POSTS (most recent last):\n" + _posts_digest(entries)
            + "\n\nMECHANICAL FINDINGS already detected:\n"
            + ("\n".join(f"- {f}" for f in findings) if findings else "(none)"))
    critique = reason(
        client, model=config.ANALYST_MODEL, system=REVIEW_SYSTEM, user=user,
        max_tokens=config.REVIEW_MAX_TOKENS, temperature=config.REVIEW_TEMPERATURE,
    )
    raw = chat(
        client, model=config.SYNTHESIS_MODEL, system=DIRECTIVES_SYSTEM,
        user="EDITOR'S CRITIQUE:\n" + critique,
        max_tokens=500, temperature=0.2,
    )
    directives = _parse_directives(raw)
    return critique, directives


def _parse_directives(raw: str) -> list[str]:
    """Strict-JSON parse with a bullet-lines fallback (models sometimes wrap
    JSON in fences or slip into prose)."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        parsed = json.loads(text[text.find("{"): text.rfind("}") + 1])
        directives = [str(d).strip() for d in parsed.get("directives", []) if str(d).strip()]
    except (json.JSONDecodeError, ValueError):
        directives = [line.lstrip("-•* ").strip() for line in raw.splitlines()
                      if line.strip().startswith(("-", "•", "*"))]
    return directives[: config.REVIEW_MAX_DIRECTIVES]


# ---- persistence ------------------------------------------------------

def save_review(date_iso: str, entries: list[dict], findings: list[str],
                critique: str, directives: list[str]) -> str:
    os.makedirs(config.REVIEWS_DIR, exist_ok=True)
    path = os.path.join(config.REVIEWS_DIR, f"REVIEW-{date_iso}.md")
    with open(path, "w") as f:
        f.write(f"# Channel review — {date_iso}\n\n"
                f"{len(entries)} post(s) reviewed "
                f"(last {config.REVIEW_LOOKBACK_DAYS} days).\n\n"
                "## Mechanical findings\n\n"
                + ("\n".join(f"- {x}" for x in findings) if findings else "None.")
                + "\n\n## Editor's critique\n\n" + critique.strip()
                + "\n\n## Directives carried into future prompts\n\n"
                + ("\n".join(f"- {x}" for x in directives) if directives else "None.")
                + "\n")
    with open(config.EDITORIAL_NOTES_FILE, "w") as f:
        json.dump({"date": date_iso, "directives": directives}, f, indent=2)
    return path


def load_notes() -> list[str]:
    """Directives from the latest review, for prompt injection. Empty when the
    file is missing or stale — old guidance must not haunt the channel."""
    if not os.path.exists(config.EDITORIAL_NOTES_FILE):
        return []
    try:
        with open(config.EDITORIAL_NOTES_FILE, "r") as f:
            data = json.load(f)
        note_date = dt.date.fromisoformat(data.get("date", ""))
    except (json.JSONDecodeError, ValueError, OSError):
        return []
    if (dt.date.today() - note_date).days > config.REVIEW_NOTES_MAX_AGE_DAYS:
        return []
    return [str(d) for d in data.get("directives", [])]


def notes_block() -> str:
    """The prompt block appended to the analyst/writer user messages ('' when
    there are no fresh notes)."""
    notes = load_notes()
    if not notes:
        return ""
    return ("\n\nEDITOR'S NOTES from the channel's latest self-review — obey them:\n"
            + "\n".join(f"- {n}" for n in notes))
