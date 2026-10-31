"""Write a persona.md from exported chat logs, with a review loop.

One export or a whole folder of them. Only the chosen person's messages are ever read into it, and if
there's more than fits comfortably in one request the sample is summarised batch by batch first, then
merged into the persona.

    python tools/persona_from_logs.py --logs ~/exports --person sam
    python -c "from miagpt import persona_gen; persona_gen.bootstrap()"
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from . import config, context, llm, prompt, style

SYSTEM = """You write persona files for a Discord bot that speaks in the voice of one real person.

The file you write becomes the bot's system prompt. It is written in the second person: "you are
xbot, an ai copy of sam", never "the bot should".

Rules:
- Output ONLY the markdown file. No preamble, no commentary, no code fences.
- Ground everything in the measured stats and the example messages. Do not invent hobbies, jobs,
  ages, locations or opinions that the messages don't support.
- Where a real fact is missing (pronouns, age, where they're from), write a square-bracket
  placeholder like [pronouns: ?] instead of guessing. Keep placeholders to a handful.
- Keep the person's identity out of it: the file must tell the bot to say plainly that it is an AI
  copy, never to claim to be the real person, and never to give out private details about them.
- Everyone is they/them until told otherwise.
- Quote example messages exactly as given, verbatim, in a section near the end.
- 500-900 words. Short sections, plain language, no tables.

Use exactly these sections, in this order:

# who you are
one short paragraph: the bot's name, that it's an ai copy of <person>, and two or three lines on
who <person> is, only from what the messages show.

# <person>'s names
their username and any nicknames seen, as a bullet list, plus a line telling the bot these are the
same person.

# privacy — hard rule
the never-invent / never-reveal rules, in the bot's own voice.

# how you type
the measured habits as bullets: message length, lowercase, punctuation, contractions they drop,
filler words, emoji habits, typos. Use the numbers you were given; do not round them away.

# how you answer
tone and behaviour, derived from the messages: dry, warm, blunt, teasing, whatever the evidence
shows. Include how to handle being asked if it's real.

# things they've said
6-8 verbatim example messages as bullets, labelled as tone demonstrations, not scripts.

# never repeat yourself
a short paragraph: quote nothing verbatim from this file, reword every reply."""

BATCH_SYSTEM = """You read one batch of a real person's Discord messages and take notes for someone
who is about to write a persona file for a bot that imitates them.

Report only what the text actually shows, in short bullets under these headings:

- how they type: length, casing, punctuation, dropped apostrophes, slang, filler, emoji
- how they sound: tone, teasing, whether they hedge or commit, how they react to being wrong
- topics and running jokes they keep coming back to
- quotes: 5-8 short verbatim lines that carry the voice, each on its own bullet
- boundaries: anything they clearly never say, or would refuse to talk about

Notes only. No persona text, no extra headings, no preamble, under 400 words. Write "nothing
notable" for an empty heading instead of inventing something. Never invent facts about their life."""


def _stats_block(s: dict) -> str:
    top = ", ".join(s["top_words"][:20]) or "(none)"
    emoji = ", ".join(f"{ch} x{n}" for ch, n in s["emoji"]) or "(none)"
    drops = []
    for pair, (short, long) in s["contractions"].items():
        if short + long >= 5:
            drops.append(f'"{pair.split("/")[0]}" {short}x vs "{pair.split("/")[1]}" {long}x')
    years = ", ".join(f"{y}: {n}" for y, n in s["years"].items()) or "unknown"
    return "\n".join([
        f"- messages measured: {s['count']} ({years})",
        f"- length: median {s['median_length']} chars, mean {s['mean_length']}, 90th percentile {s['p90_length']}",
        f"- starts lowercase: {s['lowercase_start_pct']}% of messages",
        f"- contains a question mark: {s['question_pct']}% · full stop: {s['fullstop_pct']}% · exclamation: {s['exclaim_pct']}%",
        f"- multi-line messages: {s['multiline_pct']}%",
        f"- casual filler hits (u, ur, idk, rn, lol, tbh, bc...): {s['filler_hits']}",
        f"- contractions: {'; '.join(drops) if drops else 'none worth noting'}",
        f"- most common words: {top}",
        f"- emoji used: {emoji}",
    ])


def _bot_name(fallback: str) -> str:
    return config.section("bot").get("name") or f"{fallback}bot"


def build_request(name: str, stats: dict, samples: list[str]) -> str:
    examples = "\n".join(f"- {line}" for line in samples) or "- (no examples available)"
    bot_name = _bot_name(name)
    return (
        f"the bot is called {bot_name!r}. the human it copies is {name!r}. never mix the two up: the\n"
        f"bot is an ai copy, and the file must name it {bot_name!r} in '# who you are'.\n\n"
        f"person: {name}\n\n"
        f"measured typing style:\n{_stats_block(stats)}\n\n"
        f"example messages they actually sent (quote from these, verbatim):\n{examples}\n\n"
        f"write the persona file now."
    )


def batch_request(name: str, rows: list[dict], index: int, total: int) -> str:
    channels = sorted({row.get("channel") or "?" for row in rows})
    lines = "\n".join(f"- {row['text']}" for row in rows)
    return (
        f"person: {name}\n"
        f"batch {index} of {total}, from: {', '.join(channels)}\n"
        f"{len(rows)} messages:\n\n{lines}\n\n"
        f"take notes on batch {index} now."
    )


def merge_request(name: str, stats: dict, notes: list[str], quotes: list[str],
                  previous: str = "", feedback: str = "") -> str:
    blocks = "\n\n".join(f"--- notes {i} ---\n{note}" for i, note in enumerate(notes, 1))
    quote_block = "\n".join(f"- {line}" for line in quotes) or "- (none available)"
    bot_name = _bot_name(name)
    request = (
        f"the bot is called {bot_name!r}. the human it copies is {name!r}. never mix the two up: the\n"
        f"bot is an ai copy, and the file must name it {bot_name!r} in '# who you are'.\n\n"
        f"person: {name}\n\n"
        f"measured typing style (exact, counted across every message — trust these over the notes):\n"
        f"{_stats_block(stats)}\n\n"
        f"notes taken from {len(notes)} batches of their messages:\n\n{blocks}\n\n"
        f"real messages they sent, verbatim — quote 6-8 of these in '# things they've said':\n"
        f"{quote_block}\n\n"
        f"write the persona file now. quote only lines from that list or from the notes, verbatim."
    )
    if previous and feedback:
        request += (
            f"\n\nthe current draft is below. rewrite the whole file, applying the user's changes:\n\n"
            f"--- current draft ---\n{previous}\n--- end draft ---\n\n"
            f"changes the user asked for: {feedback}\n\n"
            f"return the complete revised file, markdown only. keep quoting only lines from the list."
        )
    return request


def clean_markdown(text: str) -> str:
    """Strip code fences or a stray preamble the model sometimes adds."""
    text = (text or "").strip()
    if "```" in text:
        parts = text.split("```")
        block = max(parts, key=len).strip()
        if block.lower().startswith(("markdown", "md")):
            block = block.split("\n", 1)[-1].strip()
        text = block
    marker = text.find("# who you are")
    if marker > 0:
        text = text[marker:]
    return text.strip() + "\n"


def _persona_settings() -> dict:
    cfg = config.section("persona")
    return {
        "max_tokens": int(cfg.get("generate_max_tokens", 4000)),
        "effort": str(cfg.get("generate_reasoning_effort", "low")),
        "note_tokens": int(cfg.get("note_max_tokens", 1600)),
        "batch_chars": int(cfg.get("batch_characters", 28_000)),
    }


def draft(name: str, stats: dict, samples: list[str], previous: str = "",
          feedback: str = "") -> str:
    """One model call: the draft, or that draft revised to the user's notes."""
    settings = _persona_settings()
    request = build_request(name, stats, samples)
    if previous and feedback:
        request += (
            f"\n\nthe current draft is below. rewrite the whole file, applying the user's changes:\n\n"
            f"--- current draft ---\n{previous}\n--- end draft ---\n\n"
            f"changes the user asked for: {feedback}\n\n"
            f"return the complete revised file, markdown only."
        )
    content = llm.complete(
        SYSTEM,
        [{"role": "user", "content": request}],
        "persona-gen",
        max_tokens=settings["max_tokens"],
        temperature=0.8,
        effort=settings["effort"],
    )
    return clean_markdown(content)


def batch_notes(name: str, rows: list[dict], index: int, total: int) -> str:
    """Notes from one batch — cheaper than a full persona and nothing is lost to truncation."""
    settings = _persona_settings()
    tokens = settings["note_tokens"]
    note = ""
    for attempt in (1, 2):
        note = llm.complete(
            BATCH_SYSTEM,
            [{"role": "user", "content": batch_request(name, rows, index, total)}],
            f"persona-notes-{index}-{attempt}",
            max_tokens=tokens,
            temperature=0.6,
            effort=settings["effort"],
        ).strip()
        if not llm.last_truncated or not note:
            return note
        tokens *= 2  # cut off mid-note: give it room and try once more
    return note


def merge(name: str, stats: dict, notes: list[str], quotes: list[str],
          previous: str = "", feedback: str = "") -> str:
    settings = _persona_settings()
    content = llm.complete(
        SYSTEM,
        [{"role": "user", "content": merge_request(name, stats, notes, quotes, previous, feedback)}],
        "persona-merge",
        max_tokens=settings["max_tokens"],
        temperature=0.8,
        effort=settings["effort"],
    )
    return clean_markdown(content)


def total_sample_chars(gathered: dict) -> int:
    return sum(len(row["text"]) + 2 for rows in gathered["samples"].values() for row in rows)


def channel_report(gathered: dict) -> str:
    """'general-chat 41k · media 12k' — for the over-budget prompt."""
    parts = []
    for channel, rows in sorted(gathered["samples"].items(), key=lambda kv: -len(kv[1])):
        chars = sum(len(r["text"]) + 2 for r in rows)
        parts.append(f"{channel} {chars // 1000}k")
    return " · ".join(parts) or "(nothing sampled)"


def _notes_path(out: Path) -> Path:
    return out.parent / ".persona-notes.json"


def _load_notes(out: Path, name: str, source: str, count: int) -> list[str] | None:
    path = _notes_path(out)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if (data.get("author"), data.get("source"), data.get("count")) != (name, source, count):
        return None
    notes = [b.get("notes") or "" for b in data.get("batches") or []]
    return [n for n in notes if n] or None


def _save_notes(out: Path, name: str, source: str, count: int, batch_rows: list[list[dict]],
                notes: list[str]) -> None:
    path = _notes_path(out)
    payload = {
        "author": name,
        "source": source,
        "count": count,
        "created": datetime.now().isoformat(timespec="seconds"),
        "batches": [
            {"messages": len(rows), "channels": sorted({r.get("channel") or "?" for r in rows}),
             "notes": note}
            for rows, note in zip(batch_rows, notes)
        ],
    }
    try:
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    except OSError as exc:
        print(f"(couldn't cache notes: {exc})")


def _ask_channels(gathered: dict, ask, echo) -> bool:
    """Let them drop channels. True if anything changed."""
    names = sorted(gathered["samples"])
    echo(f"channels: {', '.join(names)}")
    try:
        reply = ask("drop which? (comma separated, or enter to keep everything) ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    if not reply:
        return False
    drop = {p.strip().lower().lstrip("#") for p in reply.split(",") if p.strip()}
    keep = {c: rows for c, rows in gathered["samples"].items() if c.lower().lstrip("#") not in drop}
    if not keep:
        echo("that would drop everything — keeping the lot")
        return False
    gathered["samples"] = keep
    return True


def interactive(export: Path, who: str | None = None, out: Path | None = None,
                ask=input, echo=print, assume_yes: bool = False, fresh: bool = False) -> int:
    """Generate, review, revise, write. Returns 0 when a persona was written."""
    out = out or prompt.persona_path()
    settings = _persona_settings()

    if not export.exists():
        echo(f"no such file or folder: {export}")
        return 1

    if who:
        # one pass: collect() resolves the name itself (username, nickname or id)
        gathered = style.collect(export, who)
        name = gathered["name"]
        if gathered["count"] == 0:
            counts = style.scan_authors(export)
            if not counts:
                echo(f"no messages found in {export} (export as DiscordChatExporter JSON)")
                return 1
            top = ", ".join(f"{n} ({c})" for n, c in counts.most_common(8))
            echo(f"no messages by {who!r} in those logs. most common authors: {top}")
            return 1
    else:
        counts = style.scan_authors(export)
        if not counts:
            echo(f"no messages found in {export} (export as DiscordChatExporter JSON)")
            return 1
        top = ", ".join(f"{n} ({c})" for n, c in counts.most_common(10))
        echo(f"authors in these logs: {top}")
        try:
            typed = ask("whose messages should the persona be built from? ").strip()
        except (EOFError, KeyboardInterrupt):
            echo("\ncancelled — nothing written")
            return 1
        name = style.resolve_name(counts, typed)
        if not name:
            echo(f"no messages by {typed!r} in those logs.")
            return 1
        gathered = None

    echo("")
    echo(f"reading {len(style.files_in(export))} export(s)...")
    if gathered is None:
        gathered = style.collect(export, name)
    if gathered["count"] == 0:
        echo(f"no usable messages by {name} (empty or link-only)")
        return 1
    if gathered["count"] < 20:
        echo(f"only {gathered['count']} usable messages by {name} — a persona from that will be guesswork.")
        try:
            if ask("carry on anyway? [y/N] ").strip().lower() not in {"y", "yes"}:
                echo("nothing written")
                return 1
        except (EOFError, KeyboardInterrupt):
            echo("\ncancelled — nothing written")
            return 1

    s = style.stats_from(gathered)
    budget_tokens, window, source = context.budget()
    budget_chars = int(budget_tokens * style.CHARS_PER_TOKEN)
    window_text = f"{window} tokens via {source}" if window else "couldn't detect it"
    years = list(s["years"])
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else (years[0] if years else "unknown dates")
    echo(f"{gathered['count']} messages by {name} ({span})")
    echo(f"read {gathered['count']} messages, {gathered['chars']} chars, "
         f"from {len(gathered['channels'])} channel(s)")
    echo(f"model window: {window_text} → budget {budget_tokens} tokens (~{budget_chars // 1000}k chars)")

    if total_sample_chars(gathered) > budget_chars and not assume_yes:
        echo("")
        echo(f"the sample is bigger than one request's budget: {channel_report(gathered)}")
        while True:
            try:
                reply = ask("batch it across several requests [B] · trim channels [t] · quit [q]: ")
            except (EOFError, KeyboardInterrupt):
                echo("\ncancelled — nothing written")
                return 1
            low = reply.strip().lower()
            if low in {"", "b", "batch", "y", "yes"}:
                break
            if low in {"t", "trim"}:
                if not _ask_channels(gathered, ask, echo):
                    continue
                if total_sample_chars(gathered) <= budget_chars:
                    echo("that fits in one request now")
                    break
            elif low in {"q", "quit"}:
                echo("nothing written")
                return 1

    batches = style.batch_samples(gathered, chars_per_batch=settings["batch_chars"])
    quotes = style.samples([row for batch in batches for row in batch], limit=12)
    echo(f"sample: {len(batches)} request(s), {gathered['count']} messages measured")

    notes = None if fresh else _load_notes(out, name, str(export), gathered["count"])
    if notes:
        echo(f"reusing cached notes ({len(notes)} batches) from {_notes_path(out).name}")
        echo("rebuilding the persona from those notes... (one model call)")
        current = merge(name, s, notes, quotes)
        if not current.strip():
            echo(f"couldn't rebuild from the cached notes — delete {_notes_path(out).name} and try again")
            return 1
    elif len(batches) == 1:
        echo("writing a persona draft... (one model call)")
        current = draft(name, s, [row["text"] for row in batches[0]])
        if not current.strip():
            echo(
                "the model returned nothing. if it's a reasoning model it may have spent the whole "
                "token budget thinking — raise [persona] generate_max_tokens in config.toml, "
                "or check [model] base_url / key."
            )
            return 1
    else:
        notes = []
        for index, rows in enumerate(batches, 1):
            echo(f"  batch {index}/{len(batches)}: {len(rows)} messages, "
                 f"{', '.join(sorted({r.get('channel') or '?' for r in rows}))}")
            note = batch_notes(name, rows, index, len(batches))
            if not note:
                echo(f"  batch {index} came back empty — skipping it")
                continue
            notes.append(note)
        if not notes:
            echo("no batch returned anything — check [model] in config.toml")
            return 1
        _save_notes(out, name, str(export), gathered["count"], batches, notes)
        echo("merging the notes into a persona... (one model call)")
        current = merge(name, s, notes, quotes)
        if not current.strip():
            echo("the merge came back empty — the cached notes are kept, re-run to retry")
            return 1

    while True:
        echo("")
        echo("-" * 60)
        echo(current)
        echo("-" * 60)
        if assume_yes:
            break
        try:
            reply = ask(
                "\nkeep this persona?  [y]es · type what to change and it rewrites · "
                "[n] start over · [q]uit: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            echo("\ncancelled — nothing written")
            return 1

        low = reply.lower()
        if low in {"y", "yes", ""}:
            break
        if low in {"q", "quit"}:
            echo("nothing written")
            return 1
        if low in {"n", "no"}:
            feedback = "try a different take: different wording, different emphasis, same facts."
        else:
            feedback = reply
        echo("rewriting...")
        if notes:
            revised = merge(name, s, notes, quotes, previous=current, feedback=feedback)
        else:
            revised = draft(name, s, [row["text"] for row in batches[0]],
                            previous=current, feedback=feedback)
        if not revised.strip():
            echo("the model returned nothing that time — keeping the previous draft")
            continue
        current = revised

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(current, encoding="utf-8")
    relative = out.name if out.parent == config.ROOT else str(out)
    echo(f"\nwrote {relative} ({len(current)} chars) — edit it by hand whenever you like")
    prompt.reset()
    return 0


def bootstrap(out: Path | None = None, ask=input, echo=print) -> bool:
    """Start-up helper: build a persona if there isn't one. True when a persona now exists."""
    out = out or prompt.persona_path()
    path = out
    if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
        return True

    if not sys.stdin.isatty():
        echo(f"no persona at {path}, and there's no terminal to build one in.")
        echo("run this in a terminal:  python tools/persona_from_logs.py")
        echo(f"or copy the template:    cp persona.example.md {path.name}")
        return False

    echo(f"no persona at {path}. build one from message logs?")
    try:
        answer = ask("build it now from exported logs? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        echo("")
        return False
    if answer in {"n", "no"}:
        echo(f"copy persona.example.md to {path.name} and edit it, then start again.")
        return False

    try:
        logs = ask("folder or .json export from DiscordChatExporter: ").strip()
    except (EOFError, KeyboardInterrupt):
        echo("")
        return False
    if not logs:
        echo(f"nothing given — copy persona.example.md to {path.name} and edit it instead.")
        return False

    return interactive(Path(logs).expanduser(), None, out, ask=ask, echo=echo) == 0
