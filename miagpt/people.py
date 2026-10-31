"""People lookup: digests of real people, built by tools/people_index.py from exported chat logs.

Optional. If [people] enabled = false, or the directory is empty, every function here no-ops.
"""

from __future__ import annotations

import json
import logging
import re

from . import config

log = logging.getLogger("miagpt.people")

_cache: dict = {"stamp": -1.0, "index": {}, "strong": {}, "weak": {}}


def _dir():
    return config.path_for(config.section("people").get("directory") or "people")


def enabled() -> bool:
    return bool(config.section("people").get("enabled", True))


def blocked() -> set[str]:
    """Names that must never surface, e.g. old names someone no longer uses."""
    return {str(n).lower() for n in (config.section("people").get("blocked") or [])}


def self_names() -> set[str]:
    """Names that are actually the bot's owner — never looked up as separate people."""
    return {str(n).lower() for n in (config.section("people").get("self") or [])}


def names_of(key: str, entry: dict) -> list[str]:
    names = [*(entry.get("usernames") or []), *(entry.get("nicknames") or [])]
    return sorted({n for n in names if len(n) >= 3}, key=len, reverse=True)


def index() -> dict:
    """The people index, re-read whenever people.json changes."""
    if not enabled():
        return {}
    path = _dir() / "people.json"
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _cache["index"]
    if _cache["stamp"] != mtime:
        try:
            _cache["index"] = json.loads(path.read_text(encoding="utf-8"))
            _cache["stamp"] = mtime
            _cache["strong"], _cache["weak"] = {}, {}
        except Exception as exc:
            log.warning("people index unreadable: %s", exc)
    return _cache["index"]


def _alias_maps() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(strong, weak) alias -> keys. Strong = a full username or nickname. Weak = a single word
    lifted out of a nickname, only usable when one person clearly owns it."""
    idx = index()
    if not idx:
        return {}, {}
    if _cache["strong"] or _cache["weak"]:
        return _cache["strong"], _cache["weak"]
    skip = blocked() | self_names()
    strong: dict[str, list[str]] = {}
    weak: dict[str, list[str]] = {}
    for key, entry in idx.items():
        if key.lower() in skip:
            continue
        names = names_of(key, entry)
        if any(n.lower() in blocked() for n in names):
            continue
        for name in names:
            strong.setdefault(name.lower(), [])
            if key not in strong[name.lower()]:
                strong[name.lower()].append(key)
        for nick in entry.get("nicknames") or []:
            for token in re.split(r"[^a-z0-9_]+", str(nick).lower()):
                if len(token) < 3 or token in strong:
                    continue
                weak.setdefault(token, [])
                if key not in weak[token]:
                    weak[token].append(key)
    _cache["strong"], _cache["weak"] = strong, weak
    return strong, weak


def find(text: str, limit: int | None = None) -> list[str]:
    """Which people a message is talking about, most likely first."""
    idx = index()
    if not idx:
        return []
    limit = int(limit or config.section("people").get("max_per_message", 2))
    strong, weak = _alias_maps()
    low = f" {text.lower()} "
    scored: dict[str, tuple[int, int]] = {}

    def count_of(key: str) -> int:
        return int((idx.get(key) or {}).get("count") or 0)

    def note(key: str, tier: int) -> None:
        prev = scored.get(key)
        if prev is None or (tier, -count_of(key)) < (prev[0], -prev[1]):
            scored[key] = (tier, count_of(key))

    for alias, keys in strong.items():
        if re.search(r"(?<![\w@])@?" + re.escape(alias) + r"(?![\w])", low):
            for key in keys:
                note(key, 1)
    for alias, keys in weak.items():
        if not re.search(r"(?<![\w@])@?" + re.escape(alias) + r"(?![\w])", low):
            continue
        if len(keys) == 1:
            note(keys[0], 2)
            continue
        ranked = sorted(keys, key=lambda k: -count_of(k))
        top, second = count_of(ranked[0]), count_of(ranked[1]) if len(ranked) > 1 else 0
        if top >= 3 * max(second, 1) or second < 50:
            note(ranked[0], 2)

    ordered = sorted(scored.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
    picked = [key for key, _ in ordered]
    if len(picked) > 1:  # a bit-part mention isn't worth 1.4k of prompt
        top = count_of(picked[0])
        picked = [k for i, k in enumerate(picked) if i == 0 or count_of(k) >= 0.2 * top]
    return picked[:limit]


def digest(name: str, budget: int | None = None) -> tuple[str, str]:
    """(display title, digest text) for a named person, or ('', '') if we have nothing."""
    idx = index()
    if not idx:
        return "", ""
    low = name.strip().lower().lstrip("@")
    skip = blocked() | self_names()
    match = None
    for key, entry in idx.items():
        if key.lower() in skip:
            continue
        aliases = [n.lower() for n in names_of(key, entry)]
        if key.lower() == low or low in aliases or any(low and low in n for n in aliases):
            match = key
            break
    if match is None:
        return "", ""
    path = _dir() / "messages" / f"{match}.txt"
    if not path.exists():
        return "", ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    title = lines[0].replace("person: ", "").strip() if lines else match
    head = lines[:5]
    samples = [line for line in lines[6:] if line.startswith("- ")]
    budget = int(budget or config.section("people").get("characters", 3200))
    out: list[str] = []
    used = sum(len(line) for line in head)
    for line in samples:
        if used + len(line) > budget:
            break
        out.append(line)
        used += len(line)
    text = "\n".join(head + ([""] if out else []) + out)
    drop = blocked()
    if drop:
        text = "\n".join(line for line in text.splitlines() if not any(b in line.lower() for b in drop))
    return title, text


HEADER = (
    "# what the chat logs say about who you're being asked about\n\n"
    "these are messages they actually sent, pulled from the logs. use them to have an opinion — "
    "hobbies, running jokes, how they talk. do NOT repeat private things: no addresses, schools, "
    "family, health, relationships, money, or anything that reads like it was said in confidence. "
    "if it isn't in here, say you don't know them well.\n\n"
)


def section_for(text: str) -> str:
    """Prompt section for whoever a message is about ('' when nobody matches)."""
    found = find(text)
    if not found:
        return ""
    parts = []
    for i, key in enumerate(found):
        title, body = digest(key, None if i == 0 else 1400)
        if body:
            parts.append(f"## {title}\n\n{body}")
    return HEADER + "\n\n".join(parts) if parts else ""
