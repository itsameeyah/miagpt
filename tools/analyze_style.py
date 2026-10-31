#!/usr/bin/env python3
"""analyze_style.py — measure how someone types, so a persona can describe it accurately.

    python tools/analyze_style.py export.json <discord username> [--since 2026-01]

Reads a DiscordChatExporter JSON export (or the output of dce_html_to_json.py) and prints, for that
author: message count, median length, punctuation habits, which contractions they drop, their most
common words and their most-used emoji. Copy the numbers into the persona's "how you type" section,
or skip this and let tools/persona_from_logs.py write the whole file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miagpt import style  # noqa: E402


def show(label: str, items: list[dict]) -> None:
    s = style.stats(items)
    emoji = ", ".join(f"{ch} x{n}" for ch, n in s["emoji"]) or "(none)"
    drops = "; ".join(
        f'"{pair.split("/")[0]}" {counts[0]} vs "{pair.split("/")[1]}" {counts[1]}'
        for pair, counts in s["contractions"].items()
        if sum(counts) >= 5
    )
    print(f"\n[{label}]")
    print(f"  n={s['count']}  median={s['median_length']}  mean={s['mean_length']}  p90={s['p90_length']}")
    print(f"  lowercase start {s['lowercase_start_pct']}% | ? {s['question_pct']}% "
          f"| . {s['fullstop_pct']}% | ! {s['exclaim_pct']}% | multiline {s['multiline_pct']}%")
    print(f"  contractions: {drops or '(none notable)'}")
    print(f"  filler hits: {s['filler_hits']}")
    print(f"  top words: {', '.join(s['top_words'][:20])}")
    print(f"  emoji: {emoji}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path, help="DiscordChatExporter json export")
    ap.add_argument("username", help="the author to measure")
    ap.add_argument("--since", default="", help="only count messages after this ISO date, e.g. 2026-01")
    args = ap.parse_args()

    messages = style.load(args.export)
    if not messages:
        print(f"no messages in {args.export}", file=sys.stderr)
        return 2

    name = style.resolve(messages, args.username)
    if not name:
        top = ", ".join(f"{n} ({c})" for n, c in style.authors(messages).most_common(8))
        print(f"no author matching {args.username!r}. in there: {top}", file=sys.stderr)
        return 1

    items = style.texts_for(messages, name)
    if args.since:
        items = [i for i in items if i["ts"] >= args.since]
    if not items:
        print(f"no messages by {name} after {args.since}", file=sys.stderr)
        return 1

    print(style.summary_line(name, items))
    show("all" if not args.since else f"since {args.since}", items)
    print("\nwant a whole persona written from this?  python tools/persona_from_logs.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
