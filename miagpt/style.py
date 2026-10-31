"""Read exported Discord logs and measure how one person types.

Shared by tools/analyze_style.py (prints the numbers) and miagpt/persona_gen.py (writes a persona
from them). Stdlib only, no network, read-only.
"""

from __future__ import annotations

import collections
import json
import random
import re
import statistics
from collections.abc import Sequence
from pathlib import Path

WORD = re.compile(r"[a-z']{2,}")
STOP = {
    "the", "a", "i", "to", "and", "it", "is", "of", "that", "in", "you", "me", "my", "for", "so",
    "on", "but", "was", "have", "this", "be", "with", "your", "its", "im", "we", "they", "he",
    "she", "at", "as", "if", "or", "do", "did", "not", "no", "yeah", "just", "like", "what",
}
CONTRACTIONS = [
    ("im", "i'm"), ("dont", "don't"), ("cant", "can't"), ("thats", "that's"), ("whats", "what's"),
    ("ill", "i'll"), ("youre", "you're"), ("its", "it's"), ("didnt", "didn't"), ("doesnt", "doesn't"),
]
FILLER = re.compile(r"\b(r u|u|ur|idk|rn|lol|tbh|ngl|bc|ty|omg|fr|mhm)\b", re.I)
URL = re.compile(r"https?://\S+")


def load(path: Path) -> list[dict]:
    """Every message in a DiscordChatExporter json export, or every json file in a folder."""
    paths = [path] if path.is_file() else sorted(path.glob("*.json"))
    messages: list[dict] = []
    for file in paths:
        try:
            data = json.loads(file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        channel = (data.get("channel") or {}).get("name") or file.stem
        for msg in data.get("messages") or []:
            author = msg.get("author") or {}
            if not author.get("name"):
                continue
            messages.append({
                "ts": msg.get("timestamp") or "",
                "name": author.get("name") or "",
                "id": str(author.get("id") or ""),
                "nick": author.get("nickname") or "",
                "content": msg.get("content") or "",
                "channel": channel,
            })
    return messages


def authors(messages: list[dict], minimum: int = 1) -> collections.Counter:
    counts: collections.Counter = collections.Counter(m["name"] for m in messages)
    return collections.Counter({k: v for k, v in counts.items() if v >= minimum})


def resolve(messages: list[dict], who: str) -> str | None:
    """Turn a username, user id or nickname into the author name used in the logs."""
    wanted = who.strip().lstrip("@").lower()
    if not wanted:
        return None
    counts = authors(messages)
    for name in counts:
        if name.lower() == wanted:
            return name
    for msg in messages:
        if msg["id"] == wanted or msg["nick"].lower() == wanted:
            return msg["name"]
    partial = [name for name in counts if wanted in name.lower()]
    return sorted(partial, key=lambda n: -counts[n])[0] if partial else None


def texts_for(messages: list[dict], name: str) -> list[dict]:
    """That person's actual words, with timestamps: no empty messages, no bare links."""
    out = []
    for msg in messages:
        if msg["name"] != name:
            continue
        text = msg["content"].strip()
        if not text or URL.sub("", text).strip() == "":
            continue
        out.append({"text": text, "ts": msg["ts"], "channel": msg["channel"]})
    return out


def _flat(item: str | dict) -> str:
    return item["text"] if isinstance(item, dict) else item


def _stamp(item: str | dict) -> str:
    return str(item.get("ts") or "") if isinstance(item, dict) else ""


def stats(items: Sequence[str | dict]) -> dict:
    """The numbers a persona's "how you type" section should be built from."""
    texts = [_flat(i) for i in items]
    lengths = [len(t) for t in texts]
    joined = " ".join(texts)
    words = [w for w in WORD.findall(joined.lower()) if w not in STOP]
    emoji = collections.Counter(ch for t in texts for ch in t if ord(ch) > 0x2000)
    contractions = {}
    for short, long in CONTRACTIONS:
        contractions[f"{short}/{long}"] = [
            len(re.findall(rf"\b{re.escape(short)}\b", joined, re.I)),
            len(re.findall(re.escape(long), joined, re.I)),
        ]
    return {
        "count": len(texts),
        "median_length": int(statistics.median(lengths)) if lengths else 0,
        "mean_length": round(statistics.mean(lengths)) if lengths else 0,
        "p90_length": sorted(lengths)[int(len(lengths) * 0.9)] if lengths else 0,
        "lowercase_start_pct": round(100 * sum(1 for t in texts if t[:1].islower()) / len(texts)),
        "question_pct": round(100 * sum(1 for t in texts if "?" in t) / len(texts)),
        "fullstop_pct": round(100 * sum(1 for t in texts if "." in t) / len(texts)),
        "exclaim_pct": round(100 * sum(1 for t in texts if "!" in t) / len(texts)),
        "multiline_pct": round(100 * sum(1 for t in texts if "\n" in t) / len(texts)),
        "top_words": [w for w, _ in collections.Counter(words).most_common(25)],
        "emoji": [(ch, n) for ch, n in emoji.most_common(12)],
        "contractions": contractions,
        "filler_hits": len(FILLER.findall(joined)),
        "years": dict(sorted(collections.Counter(_stamp(i)[:4] for i in items if _stamp(i)).items())),
    }


def samples(items: Sequence[str | dict], limit: int = 14, seed: int = 7) -> list[str]:
    """A spread of real messages: recent, long, and a random slice, deduped and short."""
    texts = [_flat(i) for i in items]
    if not texts:
        return []
    rng = random.Random(seed)
    picked: list[str] = []
    seen: set[str] = set()

    def take(candidates) -> None:
        for text in candidates:
            if len(picked) >= limit:
                return
            flat = " ".join(text.split())
            if flat in seen or len(flat) < 8:
                continue
            seen.add(flat)
            picked.append(flat[:220])

    take(list(reversed(texts))[:8])
    take(sorted(texts, key=len, reverse=True)[:6])
    take(rng.sample(texts, min(len(texts), 40)))
    return picked


def summary_line(name: str, items: Sequence[str | dict]) -> str:
    stamps = sorted({_stamp(i)[:4] for i in items if _stamp(i)[:4].isdigit()})
    span = f"{stamps[0]}–{stamps[-1]}" if len(stamps) > 1 else (stamps[0] if stamps else "unknown dates")
    return f"{len(items)} messages by {name} ({span})"
