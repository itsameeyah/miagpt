"""Model client: one OpenAI-compatible chat completion, plus reply clean-up."""

from __future__ import annotations

import logging
import re

import requests

from . import config

log = logging.getLogger("miagpt.llm")

EMOJI = "\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D"
TRAILING_EMOJI_RE = re.compile(rf"([{EMOJI}]+)\s*$")


def stack_emoji_tail(text: str) -> str:
    """If a reply ends on a single emoji, double it (a lone trailing emoji never happens)."""
    match = TRAILING_EMOJI_RE.search(text)
    if not match:
        return text
    run = match.group(1)
    bases = [c for c in run if c not in "\uFE0F\u200D"]
    if len(bases) != 1:
        return text
    return text[: match.start()] + run * 2 + text[match.end():]


def complete(system: str, messages: list[dict], session_id: str) -> str:
    """One chat completion. Returns "" on failure (the caller has a fallback line)."""
    cfg = config.section("model")
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("no [model] base_url in config.toml")

    headers = {"Content-Type": "application/json"}
    key = config.api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    # Optional: some providers keep a prompt cache per conversation if you send an id header.
    session_header = (cfg.get("session_header") or "").strip()
    if session_header:
        headers[session_header] = session_id
    for name, value in (cfg.get("headers") or {}).items():
        headers[str(name)] = str(value)

    payload = {
        "model": cfg.get("model"),
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": int(cfg.get("max_tokens", 400)),
        "temperature": float(cfg.get("temperature", 1.0)),
    }
    if cfg.get("reasoning_effort"):
        payload["reasoning_effort"] = cfg["reasoning_effort"]

    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=float(cfg.get("timeout_seconds", 45)),
        )
    except requests.RequestException as exc:
        log.warning("api request failed: %s", exc)
        return ""
    if resp.status_code != 200:
        log.warning("api %s: %s", resp.status_code, resp.text[:300])
        return ""

    choice = (resp.json().get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if choice.get("finish_reason") == "length":
        # out of tokens mid-sentence: drop the dangling fragment instead of posting half a word
        cut = max(content.rfind("."), content.rfind("?"), content.rfind("!"), content.rfind(","))
        content = content[:cut].rstrip() if cut > 0 else content.rsplit(" ", 1)[0]
    return content
