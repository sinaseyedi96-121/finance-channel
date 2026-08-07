"""
The REVIEW COUNCIL — the channel's editorial board, run daily after the last
posting slot. It is the loop that makes tomorrow's content better than today's,
with NO human in the seat.

It reads what the channel actually published (posts_log.jsonl carries the full
caption + chart metadata for every post — the pipeline's own copy of the
channel, since the Bot API can't fetch channel history), then convenes a
multi-agent council:

  1. MECHANICAL CHECKS (deterministic, no model): same-ticker repeats in a day,
     category streaks, charts drawn with unvalidated (weak) S/R levels,
     grounding flags, captions near the Telegram limit, missing verdict lines.
     These never get missed and never hallucinate, so they anchor the debate.

  2. FOUR SPECIALISTS critique the same posts from four angles — Copy Editor,
     Growth/Marketing, Compliance/Risk, Data & Chart Integrity — split across
     TWO model families (DeepSeek Pro + OpenAI's gpt-5.6-luna) so a second
     opinion is genuinely independent, not one model agreeing with itself. This
     is ROUND 1 (independent).

  3. ROUND 2 (rebuttal): each specialist re-reads the other three's round-1
     takes and either revises or pushes back. This is the "agents talking to
     each other" step — where Growth's "punchier headline" gets checked against
     Compliance's "don't overstate."

  4. The MODERATOR (DeepSeek Pro) arbitrates the whole debate + the mechanical
     findings, then a cheap distiller emits at most REVIEW_MAX_DIRECTIVES
     directives, EACH TAGGED with the prompt(s) it targets (writer, analyst,
     week_ahead, …), plus code-change notes for anything mechanical
     (market_cap/bubble_index captions aren't LLM-written, so they can't be
     fixed by a directive) and a directive-COMPLIANCE read on whether
     yesterday's directives actually stuck. All of this in the moderator pass —
     no extra model call is spent on compliance tracking.

The tagged directives land in EDITORIAL_NOTES_FILE. Every writer/analyst stage
calls notes_block(target) and gets only the directives meant for it. The full
dated review is committed under reviews/ as the audit trail — including the
code-change notes a maintainer must action by hand.

Graceful degradation is a design goal: if OPENAI_KEY is unset every seat runs
on DeepSeek; if the reader bot can't fetch engagement the council runs on the
log alone; if the moderator's JSON is malformed the distiller falls back to
plain global directives. A broken dependency dulls the loop, it never breaks it.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import config
from llm_client import complete, get_client, get_openai_client

# =====================================================================
# COUNCIL SEATS — one system prompt per critic persona
# =====================================================================
# Every seat reads the same shared context (published posts + mechanical
# findings + any engagement signal) and is asked for SPECIFIC, quotable
# critique aimed at improving the NEXT posts. They are deliberately narrow so
# their concerns don't collapse into one generic "make it better."

_COMMON_TAIL = """
Be concrete and quote the offending post(s). Prioritise the 2-3 issues that
would most improve the NEXT posts; don't pad. If the posts are clean on your
axis, say so plainly rather than inventing problems."""

COPY_EDITOR_SYSTEM = """You are the COPY EDITOR on a finance/markets Telegram
channel (AI-boom era). Judge the WRITING of what was published:
- Headlines that bury the number or the point instead of leading with it.
- Verdicts that hedge ("could go either way") instead of committing.
- Repeated phrasing / emoji patterns across posts (every post opening 🚀, the
  same stock phrases) — the channel starting to read like a template.
- Captions clipped by the length limit, or padding that wastes the limit.
- Clarity: would a smart non-expert follow it on one read?""" + _COMMON_TAIL

GROWTH_SYSTEM = """You are the GROWTH / MARKETING editor on a finance/markets
Telegram channel (AI-boom era). Judge whether the posts GROW the channel:
- Hook strength: does the first line earn the tap, without clickbaiting a
  number that isn't in the data?
- Shareability: would a reader forward this to a group or screenshot it?
- Format variety & mix: are formats/tickers over-represented so the feed feels
  one-note this week? Is there a format (leaderboard, sector read, head-to-head)
  that would have served a story better than another single-name post?
- Cadence: posts bunched or sparse in a way a subscriber would notice.""" + _COMMON_TAIL

COMPLIANCE_SYSTEM = """You are the COMPLIANCE / RISK editor on a finance/markets
Telegram channel (AI-boom era). A mechanical linter already catches explicit
buy/sell/target wording, so DON'T re-flag that — judge what it can't:
- Hype or overreach: certainty the data doesn't support, implied guarantees,
  downplayed risk, a bubble/froth call stated harder than the evidence.
- Missing/insufficient hedging where a claim is genuinely uncertain.
- Anything that would embarrass the channel if the call aged badly.
Frame fixes as tone/hedging directives a writer can obey, not legal boilerplate.""" + _COMMON_TAIL

DATA_INTEGRITY_SYSTEM = """You are the DATA & CHART INTEGRITY editor on a
finance/markets Telegram channel (AI-boom era). The mechanical findings list
already DETECTED weak levels / ungrounded figures — your job is to INTERPRET
them and catch what deterministic checks can't:
- Numbers stated with more precision or confidence than the source supports.
- Support/resistance or technical claims a chart-literate reader would call
  arbitrary (few touches, price far from the drawn level).
- Stale figures, or a caption and its chart implying different things.
- Claims that read as grounded but aren't traceable to the retrieved data.""" + _COMMON_TAIL

ROLE_SYSTEMS = {
    "copy_editor": COPY_EDITOR_SYSTEM,
    "growth": GROWTH_SYSTEM,
    "compliance": COMPLIANCE_SYSTEM,
    "data_integrity": DATA_INTEGRITY_SYSTEM,
}

ROLE_LABELS = {
    "copy_editor": "Copy Editor",
    "growth": "Growth / Marketing",
    "compliance": "Compliance / Risk",
    "data_integrity": "Data & Chart Integrity",
}

MODERATOR_SYSTEM = f"""You are the EDITOR-IN-CHIEF chairing a daily review of a
finance/markets Telegram channel (AI-boom era). Four specialist editors — Copy,
Growth, Compliance, and Data Integrity — have critiqued the last few days of
posts over two rounds (an independent pass, then a rebuttal pass where they saw
each other). You are given their full debate, the deterministic mechanical
findings, any reader-engagement signal, and YESTERDAY's directives.

Arbitrate like an editor-in-chief who must keep readers subscribed AND keep the
channel honest:
- Resolve the disagreements. Where Growth and Compliance pull against each
  other (punchier vs. safer), make the call and say why.
- Weight the mechanical findings heavily — they are certain, not opinions.
- Separate what a WRITER/ANALYST prompt can fix (tone, structure, variety,
  hedging, headline discipline) from what needs a CODE change (the mechanical
  market_cap / bubble_index captions, chart-drawing logic, new formats).
- Judge whether yesterday's directives were followed: did the flagged problem
  recur in today's posts, or is it resolved?

End with the {config.REVIEW_MAX_DIRECTIVES} or fewer changes that would most
improve the next posts, each aimed at a specific stage. Be specific enough that
a caption-writing model could obey each one directly."""

DISTILLER_SYSTEM = f"""You convert an editor-in-chief's arbitration into
machine-usable notes. Output STRICT JSON and nothing else:

{{"directives": [{{"text": "...", "targets": ["writer", "analyst"]}}, ...],
  "code_changes": ["..."],
  "compliance": [{{"directive": "<prior directive text>", "status": "resolved|recurred|n-a"}}]}}

Rules:
- At most {config.REVIEW_MAX_DIRECTIVES} directives. Each `text` is one
  imperative sentence under 160 chars, concrete enough for a writer model to
  obey (e.g. "Vary the opening emoji — last 4 posts all opened with 🚨").
- `targets` is a NON-EMPTY subset of: {config.DIRECTIVE_TARGETS}. Use "global"
  for anything that should reach every writer/analyst. NEVER target
  market_cap or bubble_index — their captions are mechanical.
- `code_changes`: anything requiring a code edit (mechanical caption wording,
  chart logic, a missing format). One short line each; [] if none.
- `compliance`: one entry per directive you were shown from YESTERDAY, marking
  whether today's posts show it was followed. [] if there were none."""


# =====================================================================
# READING THE LOG  (deterministic; no model)
# =====================================================================

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


# =====================================================================
# MECHANICAL CHECKS  (deterministic; the anchor for the debate)
# =====================================================================

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


# =====================================================================
# THE COUNCIL
# =====================================================================

def _posts_digest(entries: list[dict]) -> str:
    """Compact JSON the models read — captions in full, metadata trimmed."""
    slim = []
    for e in entries:
        slim.append({k: v for k, v in e.items() if k in
                     ("ts", "mode", "ticker", "category", "caption", "detail",
                      "chart", "grounding_flags", "pair", "score")})
    return json.dumps(slim, ensure_ascii=False, indent=1)


def _shared_context(entries: list[dict], findings: list[str],
                    engagement: list[dict] | None) -> str:
    """The context block every seat reads: the posts, the mechanical findings,
    and (best-effort) reader engagement. Built once, shared by all seats so
    their critiques are strictly comparable."""
    parts = ["PUBLISHED POSTS (most recent last):\n" + _posts_digest(entries),
             "\n\nMECHANICAL FINDINGS already detected (certain — weigh heavily):\n"
             + ("\n".join(f"- {f}" for f in findings) if findings else "(none)")]
    if engagement:
        parts.append("\n\nREADER ENGAGEMENT (best-effort reaction counts; may be "
                     "partial — treat as a weak signal, not ground truth):\n"
                     + json.dumps(engagement, ensure_ascii=False, indent=1))
    return "".join(parts)


def _council_clients() -> tuple[object, object | None]:
    """(deepseek_client, openai_client|None). DeepSeek is required; OpenAI is
    optional — a missing OPENAI_KEY (local dry-runs) yields None and every seat
    falls back to DeepSeek, so the council still runs, just single-provider."""
    ds = get_client()
    try:
        oa = get_openai_client()
    except KeyError:
        oa = None
    return ds, oa


def _openai_roles_today(day: int) -> list[str]:
    """Which seats sit on OpenAI (Luna) today. Swapped odd/even day so no seat
    is permanently tied to one model family."""
    return (config.COUNCIL_OPENAI_ROLES_EVEN if day % 2 == 0
            else config.COUNCIL_OPENAI_ROLES_ODD)


def _seat_model(role: str, day: int, ds, oa) -> tuple[object, str, str]:
    """Resolve (client, model, human_label) for a seat on a given day."""
    if oa is not None and role in _openai_roles_today(day):
        return oa, config.GPT_MODEL, config.GPT_MODEL
    return ds, config.ANALYST_MODEL, config.ANALYST_MODEL


def _run_round(context: str, day: int, ds, oa,
               peers: dict[str, str] | None = None) -> dict[str, str]:
    """Run every specialist seat once over `context`. When `peers` is given
    (round 2), each seat also sees the OTHER seats' round-1 takes and is asked
    to revise or rebut."""
    out: dict[str, str] = {}
    for role in config.COUNCIL_ROLES:
        client, model, _label = _seat_model(role, day, ds, oa)
        if peers is None:
            user = context + "\n\nGive your critique now."
        else:
            others = "\n\n".join(
                f"--- {ROLE_LABELS[r]} said ---\n{peers[r]}"
                for r in config.COUNCIL_ROLES if r != role and peers.get(r))
            user = (context
                    + "\n\nYour fellow editors' first-round takes:\n" + others
                    + "\n\nRevise your own critique or push back on a specific "
                      "point they made. Keep only what still holds; be brief.")
        try:
            out[role] = complete(
                client, model=model, system=ROLE_SYSTEMS[role], user=user,
                max_tokens=config.COUNCIL_SPECIALIST_MAX_TOKENS,
                temperature=config.COUNCIL_SPECIALIST_TEMPERATURE,
            )
        except Exception as exc:  # noqa: BLE001 — one seat failing must not sink the review
            out[role] = f"(seat unavailable: {exc})"
    return out


def _moderate(context: str, round1: dict, round2: dict,
              prev_directives: list[str], ds) -> str:
    """The editor-in-chief's prose arbitration (DeepSeek Pro)."""
    debate = []
    for role in config.COUNCIL_ROLES:
        debate.append(f"=== {ROLE_LABELS[role]} — round 1 ===\n{round1.get(role, '')}")
        if round2.get(role):
            debate.append(f"=== {ROLE_LABELS[role]} — round 2 (rebuttal) ===\n{round2[role]}")
    prev = ("\n".join(f"- {d}" for d in prev_directives) if prev_directives
            else "(none — this is a fresh start)")
    user = (context
            + "\n\nTHE COUNCIL DEBATE:\n" + "\n\n".join(debate)
            + "\n\nYESTERDAY'S DIRECTIVES (judge whether today's posts followed them):\n"
            + prev
            + "\n\nNow arbitrate and give your ruling.")
    return complete(ds, model=config.ANALYST_MODEL, system=MODERATOR_SYSTEM,
                    user=user, max_tokens=config.REVIEW_MAX_TOKENS,
                    temperature=config.REVIEW_TEMPERATURE)


def _distill(moderator: str, prev_directives: list[str], ds) -> dict:
    """Turn the moderator's prose into tagged directives + code-change notes +
    directive-compliance, in ONE cheap call (deepseek-chat)."""
    prev = ("\n".join(f"- {d}" for d in prev_directives) if prev_directives
            else "(none)")
    raw = complete(
        ds, model=config.SYNTHESIS_MODEL, system=DISTILLER_SYSTEM,
        user=("EDITOR-IN-CHIEF'S RULING:\n" + moderator
              + "\n\nYESTERDAY'S DIRECTIVES (fill the `compliance` array from these):\n"
              + prev),
        max_tokens=800, temperature=0.2,
    )
    return _parse_council_json(raw)


def run_review(client, entries: list[dict], findings: list[str],
               engagement: list[dict] | None = None,
               day: int | None = None) -> dict:
    """Convene the full council and return a structured result.

    `client` is the DeepSeek client (as the old single-pass reviewer took); the
    OpenAI client is built internally and is optional. `day` (an ordinal int)
    drives the provider rotation and defaults to today — exposed so a caller or
    test can pin it.
    """
    day = day if day is not None else dt.date.today().toordinal()
    ds = client
    _ds2, oa = _council_clients()          # reuse `client` for DeepSeek; only need oa
    prev_directives = load_notes()          # what we told the writers yesterday

    context = _shared_context(entries, findings, engagement)
    round1 = _run_round(context, day, ds, oa)
    round2 = _run_round(context, day, ds, oa, peers=round1) if config.COUNCIL_ROUND2_ENABLED else {}
    moderator = _moderate(context, round1, round2, prev_directives, ds)
    distilled = _distill(moderator, prev_directives, ds)

    return {
        "day": day,
        "seat_models": {role: _seat_model(role, day, ds, oa)[2]
                        for role in config.COUNCIL_ROLES},
        "round1": round1,
        "round2": round2,
        "moderator": moderator,
        "directives": distilled["directives"],
        "code_changes": distilled["code_changes"],
        "compliance": distilled["compliance"],
    }


# =====================================================================
# PARSING
# =====================================================================

def _parse_directives(raw: str) -> list[str]:
    """Strict-JSON parse of a flat {"directives": [str, ...]} with a bullet-lines
    fallback (models sometimes wrap JSON in fences or slip into prose). Returns
    plain strings — the legacy shape, still used as the distiller's last-ditch
    fallback and by the directive-parsing tests."""
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


def _coerce_targets(raw_targets) -> list[str]:
    """Keep only recognised targets; default to ['global'] when none survive so
    a mistagged directive still reaches the writers rather than vanishing."""
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    targets = [t for t in (raw_targets or []) if t in config.DIRECTIVE_TARGETS]
    return targets or ["global"]


def _parse_council_json(raw: str) -> dict:
    """Parse the distiller's JSON into {directives, code_changes, compliance}.

    directives -> [{"text", "targets"}], targets validated against
    DIRECTIVE_TARGETS. On malformed JSON, degrade to plain global directives via
    _parse_directives so the loop still produces *something* usable."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        parsed = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return {"directives": [{"text": d, "targets": ["global"]}
                               for d in _parse_directives(raw)],
                "code_changes": [], "compliance": []}

    directives = []
    for item in parsed.get("directives", []):
        if isinstance(item, str):
            txt, targets = item.strip(), ["global"]
        else:
            txt = str(item.get("text") or item.get("directive") or "").strip()
            targets = _coerce_targets(item.get("targets"))
        if txt:
            directives.append({"text": txt, "targets": targets})

    code_changes = [str(c).strip() for c in parsed.get("code_changes", []) if str(c).strip()]

    compliance = []
    for item in parsed.get("compliance", []):
        if not isinstance(item, dict):
            continue
        d = str(item.get("directive") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if status not in ("resolved", "recurred", "n-a"):
            status = "n-a"
        if d:
            compliance.append({"directive": d, "status": status})

    return {"directives": directives[: config.REVIEW_MAX_DIRECTIVES],
            "code_changes": code_changes, "compliance": compliance}


# =====================================================================
# PERSISTENCE
# =====================================================================

def save_review(date_iso: str, entries: list[dict], findings: list[str],
                result: dict) -> str:
    """Write the human-readable review (the audit trail) under reviews/ and the
    machine-readable tagged directives to EDITORIAL_NOTES_FILE."""
    os.makedirs(config.REVIEWS_DIR, exist_ok=True)
    path = os.path.join(config.REVIEWS_DIR, f"REVIEW-{date_iso}.md")

    seats = result.get("seat_models", {})
    lines = [f"# Channel review — {date_iso}\n",
             f"{len(entries)} post(s) reviewed (last {config.REVIEW_LOOKBACK_DAYS} days). "
             f"Council seats today: "
             + ", ".join(f"{ROLE_LABELS[r]} → {seats.get(r, '?')}"
                         for r in config.COUNCIL_ROLES) + "\n",
             "## Mechanical findings\n",
             ("\n".join(f"- {x}" for x in findings) if findings else "None.") + "\n"]

    lines.append("## Council debate\n")
    for role in config.COUNCIL_ROLES:
        lines.append(f"### {ROLE_LABELS[role]} — round 1\n")
        lines.append((result.get("round1", {}).get(role) or "(no input)").strip() + "\n")
        r2 = result.get("round2", {}).get(role)
        if r2:
            lines.append(f"### {ROLE_LABELS[role]} — round 2 (rebuttal)\n")
            lines.append(r2.strip() + "\n")

    lines.append("## Editor-in-chief's ruling\n")
    lines.append((result.get("moderator") or "").strip() + "\n")

    compliance = result.get("compliance") or []
    lines.append("## Directive compliance (did yesterday's notes stick?)\n")
    lines.append(("\n".join(f"- [{c['status']}] {c['directive']}" for c in compliance)
                  if compliance else "No prior directives to check.") + "\n")

    code_changes = result.get("code_changes") or []
    lines.append("## Needs a CODE change (not a prompt fix — for the maintainer)\n")
    lines.append(("\n".join(f"- {c}" for c in code_changes) if code_changes else "None.") + "\n")

    directives = result.get("directives") or []
    lines.append("## Directives carried into future prompts\n")
    lines.append(("\n".join(f"- [{', '.join(d['targets'])}] {d['text']}" for d in directives)
                  if directives else "None.") + "\n")

    with open(path, "w") as f:
        f.write("\n".join(lines))

    with open(config.EDITORIAL_NOTES_FILE, "w") as f:
        json.dump({"date": date_iso, "directives": directives}, f, indent=2)
    return path


# =====================================================================
# NOTES — read back into the writer/analyst prompts
# =====================================================================

def _load_notes_raw() -> tuple[list, bool]:
    """(directives, fresh?). directives is whatever the file holds (tagged dicts
    or legacy strings); fresh is False when the file is missing, unreadable, or
    older than REVIEW_NOTES_MAX_AGE_DAYS — stale guidance must not haunt the
    channel."""
    if not os.path.exists(config.EDITORIAL_NOTES_FILE):
        return [], False
    try:
        with open(config.EDITORIAL_NOTES_FILE, "r") as f:
            data = json.load(f)
        note_date = dt.date.fromisoformat(data.get("date", ""))
    except (json.JSONDecodeError, ValueError, OSError):
        return [], False
    if (dt.date.today() - note_date).days > config.REVIEW_NOTES_MAX_AGE_DAYS:
        return [], False
    return data.get("directives", []), True


def load_notes(target: str | None = None) -> list[str]:
    """Directive TEXTS from the latest review, for prompt injection.

    Handles both the tagged format ([{"text", "targets"}]) and the legacy flat
    format ([str, ...], treated as global). With `target` given, returns only
    directives tagged for that target or "global"; with no target, returns all.
    Empty when the file is missing or stale.
    """
    directives, fresh = _load_notes_raw()
    if not fresh:
        return []
    out = []
    for d in directives:
        if isinstance(d, str):
            text, targets = d, ["global"]
        else:
            text = str(d.get("text") or "").strip()
            targets = d.get("targets") or ["global"]
        if not text:
            continue
        if target is None or target in targets or "global" in targets:
            out.append(text)
    return out


def notes_block(target: str | None = None) -> str:
    """The prompt block appended to a stage's user message ('' when there are no
    fresh notes for that target)."""
    notes = load_notes(target)
    if not notes:
        return ""
    return ("\n\nEDITOR'S NOTES from the channel's latest self-review — obey them:\n"
            + "\n".join(f"- {n}" for n in notes))
