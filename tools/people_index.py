#!/usr/bin/env python3
"""people_index.py — build a per-person digest out of DiscordChatExporter JSON exports.

    python tools/people_index.py --logs ~/exports [--out people] [--min 15]

Writes:
    <out>/people.json          index: key -> {usernames, nicknames, count, first, last, channels}
    <out>/messages/<key>.txt   a digest of that person's own messages

The digest is deliberately small (a few thousand characters): enough to tell what someone is like,
what they're into and how they type, without pasting a whole chat log into a prompt.

This reads other people's messages. Only run it on logs you're allowed to use, and keep <out> out
of git (the repo's .gitignore already covers people/).
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[a-z']{3,}")
STOP = {
    "the", "and", "you", "that", "for", "with", "have", "this", "but", "not", "are", "was", "what",
    "just", "its", "it's", "like", "your", "you're", "they", "them", "from", "dont", "don't", "can",
    "get", "got", "all", "how", "why", "when", "who", "she", "her", "him", "his", "one", "out",
    "about", "would", "could", "should", "there", "their", "then", "than", "now", "know", "think",
}
MAX_DIGEST_CHARS = 5000
SAMPLE_MESSAGES = 45


def safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-") or "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, required=True, help="folder of DiscordChatExporter .json files")
    ap.add_argument("--out", type=Path, default=ROOT / "people", help="where to write the digests")
    ap.add_argument("--min", type=int, default=15, help="skip people with fewer messages than this")
    args = ap.parse_args()

    if not args.logs.is_dir():
        print(f"not a folder: {args.logs}")
        return 2

    index: dict[str, dict] = {}
    bucket: dict[str, list[dict]] = collections.defaultdict(list)

    for path in sorted(args.logs.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
            continue
        channel = (data.get("channel") or {}).get("name") or path.stem
        guild = (data.get("guild") or {}).get("name") or ""
        for msg in data.get("messages") or []:
            author = msg.get("author") or {}
            name = author.get("name")
            content = (msg.get("content") or "").strip()
            if not name or not content or content.startswith("http"):
                continue
            key = safe(name)
            entry = index.setdefault(key, {
                "usernames": [], "nicknames": [], "count": 0,
                "first": msg.get("timestamp", ""), "last": msg.get("timestamp", ""),
                "channels": [],
            })
            if name not in entry["usernames"]:
                entry["usernames"].append(name)
            nick = (author.get("nickname") or "").strip()
            if nick and nick not in entry["nicknames"]:
                entry["nicknames"].append(nick)
            entry["count"] += 1
            entry["first"] = min(entry["first"], msg.get("timestamp", entry["first"]))
            entry["last"] = max(entry["last"], msg.get("timestamp", entry["last"]))
            label = f"{guild}/{channel}" if guild else channel
            if label not in entry["channels"]:
                entry["channels"].append(label)
            bucket[key].append({"ts": msg.get("timestamp", ""), "text": content, "ch": label})

    (args.out / "messages").mkdir(parents=True, exist_ok=True)
    written = 0
    for key, entry in index.items():
        if entry["count"] < args.min:
            continue
        rows = bucket[key]
        words = collections.Counter(
            w for r in rows for w in WORD.findall(r["text"].lower()) if w not in STOP
        )

        random.seed(7)  # same sample every run, so re-running doesn't churn the digests
        picks: list[dict] = []
        seen: set[str] = set()

        def take(candidates) -> None:
            for row in candidates:
                if len(picks) >= SAMPLE_MESSAGES:
                    return
                if row["text"] in seen or len(row["text"]) < 12:
                    continue
                seen.add(row["text"])
                picks.append(row)

        recent = sorted(rows, key=lambda r: r["ts"], reverse=True)
        take(recent[:20])                                                    # what they're like lately
        take(sorted(rows, key=lambda r: len(r["text"]), reverse=True)[:12])   # their big messages
        take(random.sample(rows, min(len(rows), 20)))                        # a spread from history

        lines = [
            f"person: {entry['usernames'][0]}"
            + (f" (nicknames: {', '.join(entry['nicknames'])})" if entry["nicknames"] else ""),
            f"messages: {entry['count']} from {entry['first'][:10]} to {entry['last'][:10]}",
            f"seen in: {', '.join(entry['channels'][:6])}",
            f"words they use a lot: {', '.join(w for w, _ in words.most_common(25))}",
            "",
            "things they've said:",
        ]
        for row in picks:
            line = f"- {row['ts'][:10]}: {' '.join(row['text'].split())[:220]}"
            if sum(len(existing) for existing in lines) + len(line) > MAX_DIGEST_CHARS:
                break
            lines.append(line)

        (args.out / "messages" / f"{key}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        entry["digest_chars"] = sum(len(line) + 1 for line in lines)
        written += 1

    (args.out / "people.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"indexed {len(index)} people, wrote {written} digests to {args.out}")
    print("top talkers:", ", ".join(
        f"{k}({v['count']})" for k, v in sorted(index.items(), key=lambda kv: -kv[1]["count"])[:8]
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
