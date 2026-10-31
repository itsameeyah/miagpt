#!/usr/bin/env python3
"""miagpt entrypoint.

    python bot.py        start the bot
    python -m miagpt     same thing

Everything you'd normally change lives in config.toml and persona.md.
"""

from __future__ import annotations

import logging

from miagpt.app import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
