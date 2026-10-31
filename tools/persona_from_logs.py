#!/usr/bin/env python3
"""persona_from_logs.py — write a persona.md from exported Discord chat logs.

    python tools/persona_from_logs.py --logs ~/exports --person sam
    python tools/persona_from_logs.py                 # asks for both

Reads one person's messages out of DiscordChatExporter JSON exports, measures how they type, and
hands that to the model configured in config.toml. The draft is printed so you can keep it, or say
what to change and it rewrites. Nothing is written until you say yes.

Also runs automatically on start-up when persona.md is missing or empty.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miagpt import persona_gen, prompt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, help="folder of DiscordChatExporter .json exports, or one file")
    ap.add_argument("--person", help="username, nickname or user id to read out of the logs")
    ap.add_argument("--out", type=Path, help="where to write it (default: the persona path in config.toml)")
    ap.add_argument("--yes", action="store_true", help="accept the first draft without asking")
    args = ap.parse_args()

    logs = args.logs
    if logs is None:
        try:
            typed = input("folder or .json export from DiscordChatExporter: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\ncancelled — nothing written")
            return 1
        if not typed:
            print("nothing given — nothing written")
            return 1
        logs = Path(typed)

    out = args.out or prompt.persona_path()
    return persona_gen.interactive(logs.expanduser(), args.person, out, assume_yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
