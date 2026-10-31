#!/usr/bin/env python3
"""miagpt entrypoint.

    python bot.py            start the bot (Windows: run.bat)
    python bot.py --check    say whether this install can start, without logging in
    python -m miagpt         same as bot.py

Everything you'd normally change lives in config.toml and persona.md.
"""

from __future__ import annotations

import logging
import sys

from miagpt.app import main

if __name__ == "__main__":
    checking = "--check" in sys.argv[1:]
    logging.basicConfig(
        level=logging.WARNING if checking else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if checking:
        from miagpt.selfcheck import run

        raise SystemExit(run())
    main()
