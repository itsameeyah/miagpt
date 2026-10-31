"""The answer pipeline — no Discord imports, so it can be tested on its own."""

from __future__ import annotations

import logging
import re
import time
import uuid

from . import config, llm, memory, people, prompt

log = logging.getLogger("miagpt.brain")

LOOKUP_RE = re.compile(r"<lookup>(.*?)</lookup>", re.S | re.I)
DONT_KNOW_RE = re.compile(r"(idk|don'?t know|dont know|no clue|not sure who|never heard)", re.I)
COMMON = {
    "the", "and", "you", "that", "for", "with", "have", "this", "but", "not", "are", "was", "what",
    "who", "why", "how", "when", "where", "your", "youre", "they", "them", "she", "her", "him", "his",
    "think", "about", "know", "like", "just", "dont", "does", "did", "can", "could", "would", "should",
    "there", "their", "then", "than", "now", "get", "got", "all", "one", "out", "yes", "yeah", "lol",
}

_sessions: dict[int, dict] = {}


def session_for(channel_id: int) -> dict:
    """Rolling per-channel conversation; a gap longer than the config window starts a new one."""
    cfg = config.section("session")
    gap = float(cfg.get("minutes_between_messages", 15)) * 60
    now = time.time()
    sess = _sessions.get(channel_id)
    if sess and now - sess["last"] <= gap:
        sess["last"] = now
        return sess
    sess = {"last": now, "msgs": [], "sid": f"miagpt-{channel_id}-{uuid.uuid4().hex[:8]}"}
    _sessions[channel_id] = sess
    keep = int(cfg.get("max_channels", 500))
    if len(_sessions) > keep:
        for key in sorted(_sessions, key=lambda k: _sessions[k]["last"])[: max(1, keep // 5)]:
            _sessions.pop(key, None)
    return sess


def canned_reply(text: str) -> str | None:
    """A fixed answer from config, or None to ask the model."""
    return config.canned_replies().get(config.normalise(text))


def remember_from(reply: str, who: str) -> None:
    for fact in memory.REMEMBER_RE.findall(reply):
        memory.add(fact, who)


def answer(text: str, who: str, context: str, session: dict) -> str:
    """Produce the reply text for one message."""
    memory_text, omitted = memory.block()
    people_section = people.section_for(text) if people.enabled() else ""
    system = prompt.build(context, who, memory_text, omitted, people_section)
    history = [*session["msgs"], {"role": "user", "content": f"{who}: {text}"}]

    content = llm.complete(system, history, session["sid"])

    # asked about someone it doesn't have loaded: fetch their digest and try again
    if content and LOOKUP_RE.search(content):
        wanted = LOOKUP_RE.findall(content)[0].strip()
        patched = prompt.with_lookup(context, who, memory_text, omitted, people_section, wanted)
        if patched:
            log.info("lookup %s", wanted)
            content = llm.complete(patched, history, session["sid"])
        else:
            log.info("lookup %s -> nothing", wanted)
            content = LOOKUP_RE.sub("", content).strip() or config.reply(
                "unknown_person", "idk i dont really know {name} tbh", name=wanted
            )
    content = LOOKUP_RE.sub("", content or "")

    # it shrugged at a name: go and look that person up instead of leaving it at idk
    if not people_section and content and DONT_KNOW_RE.search(content):
        skip = COMMON | config.self_names() | {"miagpt"}
        for token in re.findall(r"[a-z0-9_]{3,}", text.lower()):
            if token in skip:
                continue
            patched = prompt.with_lookup(context, who, memory_text, omitted, people_section, token)
            if patched:
                log.info("auto-lookup %s", token)
                content = llm.complete(patched, history, session["sid"])
                break

    # it wants the rest of the memory
    if content and memory.RECALL_RE.search(content):
        full, _ = memory.block(int(config.section("memory").get("max_file_characters", 10000)))
        system_full = prompt.build(context, who, full, 0, people_section)
        log.info("recall requested")
        content = llm.complete(system_full, history, session["sid"])
        if not content or memory.RECALL_RE.search(content):
            content = config.reply("nothing_saved", "idk i checked my notes and theres nothing useful in there")

    remember_from(content or "", who)
    content = memory.strip_tags(content)

    if not content:
        return config.reply("empty_reply", "idk i got nothing for that one")
    if len(content) > 900:  # a chat message, not an essay
        content = content[:900].rsplit(" ", 1)[0] + "..."
    content = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    return llm.stack_emoji_tail(content)


def record(session: dict, who: str, text: str, reply: str) -> None:
    """Keep the exchange in the rolling conversation, trimmed to the configured depth."""
    turns = int(config.section("session").get("turns", 6))
    session["msgs"] = [
        *session["msgs"],
        {"role": "user", "content": f"{who}: {text}"},
        {"role": "assistant", "content": reply},
    ][-turns * 2:]
    session["last"] = time.time()
