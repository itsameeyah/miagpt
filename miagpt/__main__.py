"""`python -m miagpt` — same as running bot.py."""

import logging

from .app import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
