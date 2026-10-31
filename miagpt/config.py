"""Config loading with hot reload.

Everything tweakable lives in config.toml next to the bot. This module reads it, remembers the
file's mtime, and re-reads when it changes, so most edits apply without restarting.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("MIAGPT_CONFIG", str(ROOT / "config.toml")))
ENV_PATH = Path(os.getenv("MIAGPT_ENV", str(ROOT / ".env")))

_cache: dict = {"mtime": -1.0, "cfg": {}}


def _read_env_file() -> dict[str, str]:
    """Tiny .env reader — KEY=value per line, # comments, quotes optional."""
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get() -> dict:
    """The parsed config, re-read whenever config.toml changes."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _cache["mtime"] != mtime:
        try:
            raw = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SystemExit(f"No config at {CONFIG_PATH}. Run the bot from the repo directory.")
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"{CONFIG_PATH} is not valid TOML: {exc}")
        _cache.update({"mtime": mtime, "cfg": raw})
    return _cache["cfg"]


def section(name: str) -> dict:
    return get().get(name) or {}


def path_for(value: str) -> Path:
    """Resolve a configured path relative to the project directory."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else ROOT / p


def discord_token() -> str:
    token = os.getenv("MIAGPT_DISCORD_TOKEN", "").strip()
    if token:
        return token
    return _read_env_file().get("MIAGPT_DISCORD_TOKEN", "").strip()


def api_key() -> str:
    """Model API key, or "" for local endpoints that don't need one."""
    env_name = (section("model").get("api_key_env") or "MIAGPT_API_KEY").strip()
    return os.getenv(env_name, "").strip() or _read_env_file().get(env_name, "").strip()


def allowed_users() -> set[str]:
    """Discord user ids allowed to use the command. Empty set = everyone."""
    return {str(u) for u in (section("access").get("allowed_users") or []) if str(u).strip()}


def canned_replies() -> dict[str, str]:
    """Flatten the [[canned]] blocks into {normalised phrase: reply}."""
    table: dict[str, str] = {}
    for block in get().get("canned") or []:
        reply_text = (block.get("reply") or "").strip()
        for phrase in block.get("when") or []:
            table[normalise(phrase)] = reply_text
    return table


def reply(key: str, default: str = "", **fields: object) -> str:
    """A message string from [bot], with any {placeholders} filled in."""
    value = str(section("bot").get(key) or default)
    if not fields:
        return value
    try:
        return value.format(**fields)
    except (KeyError, IndexError, ValueError):
        return value


def self_names() -> set[str]:
    """Names that mean the bot itself, so it never looks them up as other people."""
    cfg = section("bot")
    names = {str(cfg.get("name") or "").lower(), "bot"}
    names |= {str(n).lower() for n in (cfg.get("aliases") or [])}
    return {n for n in names if n}


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse spaces — for matching canned replies."""
    keep = "".join(c if c.isalnum() or c == " " else " " for c in text.lower())
    return " ".join(keep.split())
