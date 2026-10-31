#!/usr/bin/env python3
"""digest.py — turn a folder of DiscordChatExporter exports into facts worth knowing.

Usage:
    python tools/digest.py <folder> [--user <discord name or id>] [--min 20]

Accepts the JSON exports (DiscordChatExporter "Json" format). For every author it reports how many
messages they sent across the folder, their top words, and their longest few messages, which is
enough to spot hobbies, running jokes and how someone types. With --user it prints that person's own
messages so you can write a profile entry for the persona.

No network, no model calls, read-only.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

WORD = re.compile(r"[a-z']{3,}")


def iter_messages(folder: Path):
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            print(f"  ! skipped {path.name}: {exc}", file=sys.stderr)
            continue
        channel = (data.get("channel") or {}).get("name") or path.stem
        for msg in data.get("messages") or []:
            author = msg.get("author") or {}
            yield channel, author.get("id"), author.get("name"), msg.get("content") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--user", help="discord username or id to dump in full")
    ap.add_argument("--min", type=int, default=20, help="minimum messages to report an author")
    ap.add_argument("--long", type=int, default=12, help="how many long messages to show")
    args = ap.parse_args()

    if not args.folder.is_dir():
        print(f"not a folder: {args.folder}", file=sys.stderr)
        return 2

    counts: collections.Counter = collections.Counter()
    ids: dict[str, str] = {}
    words: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    longs: dict[str, list[str]] = collections.defaultdict(list)
    channels: collections.Counter = collections.Counter()

    for channel, uid, name, content in iter_messages(args.folder):
        if not name:
            continue
        counts[name] += 1
        ids[name] = uid or ""
        channels[channel] += 1
        if content and not content.startswith("http"):
            words[name].update(WORD.findall(content.lower()))
            if len(content) > 60:
                longs[name].append(content)

    print(f"folder: {args.folder}")
    print(f"channels: {len(channels)}  messages: {sum(counts.values())}  people: {len(counts)}\n")

    if args.user:
        key = next((n for n in counts if n.lower() == args.user.lower() or ids.get(n) == args.user), None)
        if key is None:
            print(f"no such author: {args.user}", file=sys.stderr)
            return 1
        print(f"=== {key} ({ids[key]}) — {counts[key]} messages")
        print("top words:", ", ".join(w for w, _ in words[key].most_common(25)))
        print(f"\nlongest {args.long} messages:")
        for line in sorted(longs[key], key=len, reverse=True)[: args.long]:
            print("  •", line.replace("\n", " / ")[:300])
        return 0

    for name, n in counts.most_common():
        if n < args.min:
            continue
        top = ", ".join(w for w, _ in words[name].most_common(10))
        print(f"{n:6}  {name:<22} {ids[name]:<20} {top[:90]}")

    print("\nrun again with --user <name> to dump one person's messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
