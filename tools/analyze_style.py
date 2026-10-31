#!/usr/bin/env python3
"""analyze_style.py — measure how someone types, so the persona file can describe it accurately.

Usage:
    python tools/analyze_style.py export.json <discord username> [--since 2026-01]

Reads one DiscordChatExporter JSON export (or the output of dce_html_to_json.py) and prints, for
that author: message count, median/mean length, punctuation habits, which contractions they drop,
their most common words and their most-used emoji. Copy the interesting numbers into the persona's
"how you type" section.

No network, no model calls, read-only.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
from pathlib import Path

STOP = {
    "the", "a", "i", "to", "and", "it", "is", "of", "that", "in", "you", "me", "my", "for", "so",
    "on", "but", "was", "have", "this", "be", "with", "your", "its", "im",
}
CONTRACTIONS = [("im", "i'm"), ("dont", "don't"), ("cant", "can't"), ("thats", "that's"),
                ("whats", "what's"), ("ill", "i'll"), ("youre", "you're"), ("its", "it's")]
FILLER = r"\b(r u|u|ur|idk|rn|lol|tbh|ngl|bc|ty|omg|fr|mhm)\b"


def stats(name: str, rows: list[str]) -> None:
    lengths = [len(c) for c in rows]
    joined = " ".join(rows)
    lowercase = sum(1 for c in rows if c[:1].islower())
    questions = sum(1 for c in rows if "?" in c)
    fullstops = sum(1 for c in rows if "." in c)
    exclaims = sum(1 for c in rows if "!" in c)
    print(f"\n[{name}] n={len(rows)} median={statistics.median(lengths):.0f} "
          f"mean={statistics.mean(lengths):.0f} p90={sorted(lengths)[int(len(lengths) * 0.9)]}")
    print(f"  lowercase start {lowercase * 100 // len(rows)}% | ? {questions * 100 // len(rows)}% "
          f"| . {fullstops * 100 // len(rows)}% | ! {exclaims * 100 // len(rows)}%")
    apostrophes = {
        short: len(re.findall(rf"\b{re.escape(short)}\b", joined, re.I))
        for short, _ in CONTRACTIONS
    }
    apostrophes.update({
        long: len(re.findall(re.escape(long), joined, re.I)) for _, long in CONTRACTIONS
    })
    print("  apostrophes:", apostrophes)
    words = re.findall(r"[a-z']{2,}", joined.lower())
    top = collections.Counter(w for w in words if w not in STOP).most_common(22)
    print("  top words:", ", ".join(f"{w}({n})" for w, n in top))
    print("  filler:", len(re.findall(FILLER, joined, re.I)), "hits")
    emoji = collections.Counter(ch for c in rows for ch in c if ord(ch) > 0x2000)
    print("  emoji:", ", ".join(f"{ch}({n})" for ch, n in emoji.most_common(12)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path, help="DiscordChatExporter json export")
    ap.add_argument("username", help="the author to measure")
    ap.add_argument("--since", default="", help="only messages after this ISO date, e.g. 2026-01")
    args = ap.parse_args()

    try:
        data = json.loads(args.export.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        print(f"can't read {args.export}: {exc}", file=sys.stderr)
        return 2

    rows = [
        m["content"] for m in data.get("messages") or []
        if (m.get("author") or {}).get("name") == args.username
        and (m.get("content") or "").strip()
        and not m["content"].startswith("http")
        and (not args.since or (m.get("timestamp") or "") >= args.since)
    ]
    if not rows:
        print(f"no messages by {args.username} in {args.export}", file=sys.stderr)
        return 1

    print(f"messages: {len(rows)}")
    by_year: dict[str, list[str]] = collections.defaultdict(list)
    for m in data["messages"]:
        if (m.get("author") or {}).get("name") == args.username and (m.get("content") or "").strip():
            by_year[(m.get("timestamp") or "")[:4]].append(m["content"])
    for year in sorted(by_year):
        print(f"  {year}: {len(by_year[year])}")

    stats("all" if not args.since else f"since {args.since}", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
