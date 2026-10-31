"""System prompt assembly: persona file + memory + people + where-am-I + who's asking."""

from __future__ import annotations

import logging

from . import config, memory, people

log = logging.getLogger("miagpt.prompt")

_cache: dict = {"mtime": -1.0, "text": ""}

PRONOUN_RULES = (
    "- everyone is they/them until you're told otherwise. never guess from a name, how someone\n"
    "  types, or what you assume.\n"
    "- if someone corrects you about their pronouns (or someone else's), save it with\n"
    "  <remember>who uses what</remember> so you don't get it wrong again. don't make a thing of it,\n"
    "  just take it and use the right one from then on."
)

LOOKUP_HINT = (
    "if someone asks about a person and you don't have their logs in front of you, reply with\n"
    "just <lookup>their name</lookup> and you'll get what you need to answer with.\n\n"
)

TAG_HINT = (
    "reply with just the message, then on a new line the tag if you have something worth saving.\n"
    'e.g. "mhm sounds right 😭\\n<remember>ben finally bought a wii u</remember>"'
)


def persona() -> str:
    """The persona markdown, re-read whenever the file changes."""
    path = config.path_for(config.section("persona").get("file") or "persona.md")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _cache["text"]
    if _cache["mtime"] != mtime:
        try:
            _cache.update({"mtime": mtime, "text": path.read_text(encoding="utf-8")})
            log.info("persona reloaded (%d chars)", len(_cache["text"]))
        except OSError as exc:
            log.warning("persona unreadable: %s", exc)
    return _cache["text"]


def persona_path():
    return config.path_for(config.section("persona").get("file") or "persona.md")


def reset() -> None:
    """Forget the cached persona text, so the next build() re-reads the file."""
    _cache.update({"mtime": -1.0, "text": ""})


def build(context: str, who: str, memory_text: str, omitted: int, people_section: str) -> str:
    """Assemble the full system prompt for one message."""
    memory_block = memory_text or "(nothing saved yet)"
    if omitted:
        memory_block += f"\n\n({omitted} older notes not shown — reply <recall> if you need them)"

    return (
        f"{persona()}\n\n"
        f"{memory.RULES}\n\n"
        f"## what you already remember\n\n{memory_block}\n\n"
        f"{people_section}"
        f"{'' if not people_section else chr(10) + chr(10)}"
        f"# pronouns\n\n{PRONOUN_RULES}\n\n"
        f"# where you are right now\n\n{context}\n"
        f"- {who} is the one asking (that's their server display name plus their discord username —"
        f" same person, the nickname just changes per server)\n\n"
        f"{LOOKUP_HINT}"
        f"{TAG_HINT}"
    )


def with_lookup(context: str, who: str, memory_text: str, omitted: int, people_section: str,
                wanted: str) -> str:
    """The same prompt plus one person's digest, or "" when there's nothing on them."""
    title, body = people.digest(wanted)
    if not body:
        return ""
    base = build(context, who, memory_text, omitted, people_section)
    return f"{base}\n\n{people.HEADER}## {title}\n\n{body}"
