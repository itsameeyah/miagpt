"""`python bot.py --check` — say whether this install can actually start, without logging in."""

from __future__ import annotations

import sys

import requests

from . import config, memory, people, prompt

OK = "ok"
WARN = "warn"
BAD = "fail"


def _mask(token: str) -> str:
    if len(token) <= 12:
        return "*" * len(token)
    return f"{token[:6]}...{token[-4:]}"


def _line(status: str, name: str, detail: str) -> str:
    return f"  {name:<18} {status:<5} {detail}"


def run(probe: bool = True) -> int:
    """Print a report. Returns 0 when the bot could start, 1 when it can't."""
    lines = ["miagpt self-check", ""]
    failures = 0

    # 1. config
    try:
        cfg = config.get()
        command = cfg.get("bot", {}).get("command") or "ask"
        model = cfg.get("model", {}).get("model") or "?"
        lines.append(_line(OK, "config.toml", f"command /{command}, model {model}"))
    except SystemExit as exc:
        lines.append(_line(BAD, "config.toml", str(exc)))
        print("\n".join(lines))
        return 1

    # 2. persona
    path = prompt.persona_path()
    if path.exists():
        text = prompt.persona()
        size = len(text.strip())
        if size < 200:
            lines.append(_line(WARN, "persona.md", f"only {size} chars — it'll have no personality"))
        else:
            lines.append(_line(OK, "persona.md", f"{size} chars"))
    else:
        failures += 1
        lines.append(_line(BAD, "persona.md", "missing — run tools/persona_from_logs.py, or copy the example"))

    # 3. token
    token = config.discord_token()
    if token:
        lines.append(_line(OK, "bot token", _mask(token)))
    else:
        failures += 1
        lines.append(_line(BAD, "bot token", "missing — put MIAGPT_DISCORD_TOKEN=... in .env"))

    # 4. model endpoint
    base = (config.section("model").get("base_url") or "").rstrip("/")
    if not base:
        failures += 1
        lines.append(_line(BAD, "model endpoint", "no [model] base_url"))
    elif not probe:
        lines.append(_line(OK, "model endpoint", base))
    else:
        try:
            resp = requests.get(f"{base}/models", timeout=5)
            if resp.status_code == 401:
                lines.append(_line(WARN, "model endpoint", f"{base} — 401, check MIAGPT_API_KEY"))
            elif resp.status_code >= 400:
                lines.append(_line(WARN, "model endpoint", f"{base} — HTTP {resp.status_code}"))
            else:
                try:
                    count = len(resp.json().get("data") or [])
                    lines.append(_line(OK, "model endpoint", f"{base} ({count} models)"))
                except ValueError:
                    lines.append(_line(OK, "model endpoint", base))
        except requests.RequestException as exc:
            lines.append(_line(WARN, "model endpoint", f"{base} — not reachable ({type(exc).__name__})"))

    # 5. memory
    if memory.enabled():
        entries = memory.load()
        path = config.path_for(config.section("memory").get("file") or "memory.jsonl")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            probe_file = path.with_suffix(".check")
            probe_file.write_text("", encoding="utf-8")
            probe_file.unlink()
            lines.append(_line(OK, "memory", f"{len(entries)} notes, writable"))
        except OSError as exc:
            lines.append(_line(WARN, "memory", f"{len(entries)} notes, not writable ({exc.strerror})"))
    else:
        lines.append(_line(OK, "memory", "off"))

    # 6. people
    if people.enabled():
        count = len(people.index())
        detail = f"{count} people indexed" if count else "on, but nothing indexed yet"
        lines.append(_line(OK if count else WARN, "people", detail))
    else:
        lines.append(_line(OK, "people", "off"))

    # 7. access
    allowed = config.allowed_users()
    lines.append(_line(OK, "access", f"{len(allowed)} allowed user(s)" if allowed else "everyone"))
    lines.append(_line(OK, "python", f"{sys.version.split()[0]} at {sys.executable}"))

    print("\n".join(lines))
    print()
    if failures:
        print(f"{failures} thing(s) to fix before it will start.")
        return 1
    print("looks good — run `python bot.py` to start it.")
    return 0
