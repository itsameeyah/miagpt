#!/usr/bin/env bash
# run.sh — start miagpt in this terminal (macOS / Linux). No systemd, no service.
# First run creates .venv and installs the two dependencies.
#     ./run.sh            start it
#     ./run.sh --check    check the install without starting
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY="${PYTHON:-python3}"

if [[ ! -x .venv/bin/python ]]; then
  echo "first run: creating .venv and installing dependencies"
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

if [[ ! -f .env ]]; then
  echo "no .env found — run: cp .env.example .env  and put your bot token in it" >&2
  exit 1
fi

if [[ ! -f persona.md ]]; then
  echo "no persona.md found — run: cp persona.example.md persona.md  and write yours" >&2
  exit 1
fi

exec .venv/bin/python bot.py "$@"
