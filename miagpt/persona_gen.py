"""Write a persona.md from exported chat logs, with a review loop.

The model gets measured typing stats plus real example messages, and writes the persona file. You
read the draft in the terminal, keep it, or say what to change and it rewrites.

    python tools/persona_from_logs.py --logs ~/exports --person sam
    python -c "from miagpt import persona_gen; persona_gen.bootstrap()"
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import config, llm, prompt, style

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


def _stats_block(s: dict) -> str:
    top = ", ".join(s["top_words"][:20]) or "(none)"
    emoji = ", ".join(f"{ch} x{n}" for ch, n in s["emoji"]) or "(none)"
    drops = []
    for pair, (short, long) in s["contractions"].items():
        if short + long >= 5:
            drops.append(f'"{short}" {short}x vs "{long}" {long}x')
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


def build_request(name: str, stats: dict, samples: list[str]) -> str:
    examples = "\n".join(f"- {line}" for line in samples) or "- (no examples available)"
    bot_name = config.section("bot").get("name") or f"{name}bot"
    return (
        f"the bot is called {bot_name!r}. the human it copies is {name!r}. never mix the two up: the\n"
        f"bot is an ai copy, and the file must name it {bot_name!r} in '# who you are'.\n\n"
        f"person: {name}\n\n"
        f"measured typing style:\n{_stats_block(stats)}\n\n"
        f"example messages they actually sent (quote from these, verbatim):\n{examples}\n\n"
        f"write the persona file now."
    )


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


def draft(name: str, stats: dict, samples: list[str], previous: str = "",
          feedback: str = "") -> str:
    """One model call: the draft, or that draft revised to the user's notes."""
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
        max_tokens=int(config.section("persona").get("generate_max_tokens", 4000)),
        temperature=0.8,
        effort=str(config.section("persona").get("generate_reasoning_effort", "low")),
    )
    return clean_markdown(content)


def interactive(export: Path, who: str | None = None, out: Path | None = None,
                ask=input, echo=print, assume_yes: bool = False) -> int:
    """Generate, review, revise, write. Returns 0 when a persona was written."""
    out = out or prompt.persona_path()

    if not export.exists():
        echo(f"no such file or folder: {export}")
        return 1

    messages = style.load(export)
    if not messages:
        echo(f"no messages found in {export} (export as DiscordChatExporter JSON)")
        return 1

    counts = style.authors(messages)
    if who:
        resolved = style.resolve(messages, who)
        if not resolved:
            top = ", ".join(f"{n} ({c})" for n, c in counts.most_common(8))
            echo(f"no messages by {who!r} in those logs. most common authors: {top}")
            return 1
        name = resolved
    else:
        top = ", ".join(f"{n} ({c})" for n, c in counts.most_common(10))
        echo(f"authors in these logs: {top}")
        try:
            typed = ask("whose messages should the persona be built from? ").strip()
        except (EOFError, KeyboardInterrupt):
            echo("\ncancelled — nothing written")
            return 1
        resolved = style.resolve(messages, typed)
        if not resolved:
            echo(f"no messages by {typed!r} in those logs.")
            return 1
        name = resolved

    texts = style.texts_for(messages, name)
    if len(texts) < 20:
        echo(f"only {len(texts)} usable messages by {name} — a persona from that will be guesswork.")
        try:
            if ask("carry on anyway? [y/N] ").strip().lower() not in {"y", "yes"}:
                echo("nothing written")
                return 1
        except (EOFError, KeyboardInterrupt):
            echo("\ncancelled — nothing written")
            return 1

    s = style.stats(texts)
    picked = style.samples(texts)
    echo("")
    echo(style.summary_line(name, texts))
    echo(f"reading {s['median_length']}-char median messages, {s['lowercase_start_pct']}% starting lowercase")
    echo("writing a persona draft... (one model call)")

    current = draft(name, s, picked)
    if not current.strip():
        echo(
            "the model returned nothing. if it's a reasoning model it may have spent the whole "
            "token budget thinking — raise [persona] generate_max_tokens in config.toml, "
            "or check [model] base_url / key."
        )
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
        revised = draft(name, s, picked, previous=current, feedback=feedback)
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
