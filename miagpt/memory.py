"""Long-term memory: a small jsonl file the model writes to with <remember> tags."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger("miagpt.memory")

REMEMBER_RE = re.compile(r"<remember>(.*?)</remember>", re.S | re.I)
RECALL_RE = re.compile(r"<recall\s*/?>", re.I)

RULES = """# memory

you have a memory file. the newest things in it are below. it's your own notes, not part of the
persona file — write whatever's worth keeping across conversations.

- to save something, end your reply with a tag: <remember>short fact</remember>
  one short line, no more than about 140 characters. save things that actually matter later:
  who someone is, what they're into, running jokes, what you agreed or promised, big changes.
  don't save small talk, don't save things already in the list, and don't save private details.
- if you need something older than what's shown (or you're not sure what you already know), reply
  with just <recall> on its own and you'll get the full memory back.
- the tag never appears in what you post. write your normal reply, then the tag at the end."""


def _file() -> Path:
    return config.path_for(config.section("memory").get("file") or "memory.jsonl")


def enabled() -> bool:
    return bool(config.section("memory").get("enabled", True))


def load() -> list[dict]:
    """Every saved note, oldest first. Unreadable lines are skipped, not fatal."""
    path = _file()
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("text"):
            entries.append(item)
    return entries


def save(entries: list[dict]) -> None:
    """Write the file, dropping the oldest entries until the serialised file fits the cap."""
    cap = int(config.section("memory").get("max_file_characters", 10000))
    lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in entries]
    total = sum(len(line.encode("utf-8")) for line in lines)
    while lines and total > cap:
        total -= len(lines[0].encode("utf-8"))
        lines.pop(0)
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(path)


def add(text: str, who: str = "") -> bool:
    """Save one note. Returns False if memory is off, too short, or already known."""
    if not enabled():
        return False
    limit = int(config.section("memory").get("max_entry_characters", 300))
    text = " ".join(text.split())[:limit].strip()
    if len(text) < 4:
        return False
    entries = load()
    if any(e["text"].lower() == text.lower() for e in entries):
        return False
    entries.append({"ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "by": who, "text": text})
    save(entries)
    log.info("memory + %s", text[:80])
    return True


def block(limit: int | None = None) -> tuple[str, int]:
    """(newest entries that fit the budget, how many were left out)."""
    entries = load()
    if not entries:
        return "", 0
    budget = int(limit if limit is not None else config.section("memory").get("inject_characters", 4000))
    chosen: list[str] = []
    used = 0
    for entry in reversed(entries):
        line = f"- {entry.get('ts', '?')} ({entry.get('by') or '?'}): {entry['text']}"
        if used + len(line) > budget and chosen:
            break
        chosen.append(line)
        used += len(line)
    chosen.reverse()
    return "\n".join(chosen), len(entries) - len(chosen)


def strip_tags(text: str) -> str:
    return RECALL_RE.sub("", REMEMBER_RE.sub("", text or "")).strip()
