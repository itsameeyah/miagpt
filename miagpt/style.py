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
        if msg["id"] == wanted or msg["nick"] == wanted:
            return msg["name"]
    return resolve_name(counts, wanted)


def resolve_name(counts: collections.Counter, who: str) -> str | None:
    """Same, but from a name -> message count map (streaming path, no messages in memory)."""
    wanted = who.strip().lstrip("@").lower()
    if not wanted:
        return None
    for name in counts:
        if name.lower() == wanted:
            return name
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


# --------------------------------------------------------------------------------------------
# Streaming collection: a folder of exports can be hundreds of MB, and we only ever want one
# person's lines. Everything below keeps bounded memory and exact aggregates.
# --------------------------------------------------------------------------------------------

CHARS_PER_TOKEN = 3.5  # rough for English chat; used only for budgeting, never for billing


def estimate_tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


def files_in(path: Path) -> list[Path]:
    """One export, or every .json in a folder."""
    return [path] if path.is_file() else sorted(path.glob("*.json"))


def scan_authors(path: Path) -> collections.Counter:
    """Author -> message count, without holding the exports in memory."""
    counts: collections.Counter = collections.Counter()
    for file in files_in(path):
        try:
            data = json.loads(file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for msg in data.get("messages") or []:
            name = (msg.get("author") or {}).get("name")
            if name:
                counts[name] += 1
    return counts


def collect(path: Path, name: str, per_channel_cap: int = 400) -> dict:
    """Stream the exports, keep only `name`'s messages, aggregate as we go.

    `name` can be a username, a nickname or a user id — the first author that matches wins and is
    reported back in ``gathered["name"]``.

    Returns exact counts plus a bounded per-channel sample of that person's messages.
    """
    wanted = name.strip().lstrip("@").lower()
    matched: str | None = None

    def is_target(author: dict) -> bool:
        return (
            (author.get("name") or "").lower() == wanted
            or str(author.get("id") or "") == wanted
            or (author.get("nickname") or "").lower() == wanted
        )

    rng = random.Random(7)
    samples: dict[str, list[dict]] = collections.defaultdict(list)
    seen_per_channel: collections.Counter = collections.Counter()
    channels: collections.Counter = collections.Counter()
    years: collections.Counter = collections.Counter()
    words: collections.Counter = collections.Counter()
    emoji: collections.Counter = collections.Counter()
    contractions = {f"{s}/{long}": [0, 0] for s, long in CONTRACTIONS}
    counts = {"total": 0, "kept": 0, "chars": 0, "lowercase": 0, "question": 0,
              "fullstop": 0, "exclaim": 0, "multiline": 0, "filler": 0}
    lengths: list[int] = []
    files = files_in(path)

    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        channel = (data.get("channel") or {}).get("name") or file.stem
        for msg in data.get("messages") or []:
            author = msg.get("author") or {}
            if not author.get("name"):
                continue
            counts["total"] += 1
            if not is_target(author):
                continue
            matched = matched or author["name"]
            text = (msg.get("content") or "").strip()
            if not text or URL.sub("", text).strip() == "":
                continue
            ts = msg.get("timestamp") or ""
            counts["kept"] += 1
            counts["chars"] += len(text)
            counts["lowercase"] += 1 if text[:1].islower() else 0
            counts["question"] += 1 if "?" in text else 0
            counts["fullstop"] += 1 if "." in text else 0
            counts["exclaim"] += 1 if "!" in text else 0
            counts["multiline"] += 1 if "\n" in text else 0
            counts["filler"] += len(FILLER.findall(text))
            channels[channel] += 1
            years[ts[:4]] += 1
            lengths.append(len(text))
            words.update(w for w in WORD.findall(text.lower()) if w not in STOP)
            emoji.update(ch for ch in text if ord(ch) > 0x2000)
            for short, long in CONTRACTIONS:
                key = f"{short}/{long}"
                contractions[key][0] += len(re.findall(rf"\b{re.escape(short)}\b", text, re.I))
                contractions[key][1] += len(re.findall(re.escape(long), text, re.I))

            # bounded reservoir per channel, so a huge channel can't swamp the sample
            bucket = samples[channel]
            seen_per_channel[channel] += 1
            seen = seen_per_channel[channel]
            if len(bucket) < per_channel_cap:
                bucket.append({"text": text, "ts": ts, "channel": channel})
            else:
                j = rng.randrange(seen)
                if j < per_channel_cap:
                    bucket[j] = {"text": text, "ts": ts, "channel": channel}

    return {
        "name": matched or name,
        "files": len(files),
        "count": counts["kept"],
        "total_seen": counts["total"],
        "chars": counts["chars"],
        "lengths": lengths,
        "punctuation": {k: counts[k] for k in ("lowercase", "question", "fullstop", "exclaim", "multiline")},
        "filler_hits": counts["filler"],
        "words": words,
        "emoji": emoji,
        "contractions": contractions,
        "channels": channels,
        "years": +years,
        "samples": {ch: rows for ch, rows in samples.items() if rows},
    }


def stats_from(gathered: dict) -> dict:
    """The same shape as stats(), built from a collect() result."""
    n = gathered["count"]
    lengths = sorted(gathered["lengths"])
    p = gathered["punctuation"]
    pct = (lambda value: round(100 * value / n)) if n else (lambda value: 0)
    return {
        "count": n,
        "median_length": int(statistics.median(lengths)) if lengths else 0,
        "mean_length": round(statistics.mean(lengths)) if lengths else 0,
        "p90_length": lengths[int(len(lengths) * 0.9)] if lengths else 0,
        "lowercase_start_pct": pct(p["lowercase"]),
        "question_pct": pct(p["question"]),
        "fullstop_pct": pct(p["fullstop"]),
        "exclaim_pct": pct(p["exclaim"]),
        "multiline_pct": pct(p["multiline"]),
        "top_words": [w for w, _ in gathered["words"].most_common(25)],
        "emoji": [(ch, c) for ch, c in gathered["emoji"].most_common(12)],
        "contractions": {k: tuple(v) for k, v in gathered["contractions"].items()},
        "filler_hits": gathered["filler_hits"],
        "years": dict(sorted((y, c) for y, c in gathered["years"].items() if y)),
    }


def batch_samples(gathered: dict, chars_per_batch: int = 28_000) -> list[list[dict]]:
    """Split the collected sample into batches small enough for one request.

    Round-robin across channels so every batch sees a mix instead of one loud channel.
    """
    queues = {}
    for channel, rows in gathered["samples"].items():
        rows = sorted(rows, key=lambda r: r["ts"])
        queues[channel] = list(rows)
    batches: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    while any(queues.values()):
        for channel in list(queues):
            queue = queues[channel]
            if not queue:
                continue
            row = queue.pop(0)
            size = len(row["text"]) + 2
            if current and used + size > chars_per_batch:
                batches.append(current)
                current, used = [], 0
            current.append(row)
            used += size
        if not any(queues.values()) and current:
            batches.append(current)
            current, used = [], 0
    if current:
        batches.append(current)
    return batches
