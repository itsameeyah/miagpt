"""Work out how much context the configured model has, so we don't overfill it.

There is no standard field for this, so try the usual suspects in order and give up honestly:

    1. [model] context_window in config.toml   (always wins)
    2. GET /props            llama.cpp        -> default_generation_settings.n_ctx
    3. GET /v1/models        OpenRouter, vLLM, llama.cpp-router
                                              -> context_length / max_model_len / --ctx-size
    4. POST /api/show        ollama           -> model_info.<arch>.context_length

Unknown is a valid answer: callers fall back to the configured ceiling and say so.
"""

from __future__ import annotations

import logging

import requests

from . import config

log = logging.getLogger("miagpt.context")


def _root(base: str) -> str:
    return base[:-3] if base.endswith("/v1") else base


def _from_props(base: str, timeout: float) -> int | None:
    try:
        data = requests.get(f"{_root(base)}/props", timeout=timeout).json()
    except Exception:
        return None
    settings = data.get("default_generation_settings") or {}
    for value in (settings.get("n_ctx"), data.get("n_ctx")):
        if isinstance(value, int) and value > 0:
            return value
    return None


def _from_models(base: str, model: str | None, timeout: float) -> int | None:
    try:
        entries = requests.get(f"{base}/models", timeout=timeout).json().get("data") or []
    except Exception:
        return None
    if not entries:
        return None
    entry = next((e for e in entries if e.get("id") == model), entries[0])
    for value in (entry.get("context_length"), entry.get("max_model_len"), entry.get("n_ctx")):
        if isinstance(value, int) and value > 0:
            return value
    meta = entry.get("meta") or {}
    for value in (meta.get("n_ctx_train"), meta.get("n_ctx")):
        if isinstance(value, int) and value > 0:
            return value
    args = ((entry.get("status") or {}).get("args") or [])
    for flag in ("--ctx-size", "-c"):
        if flag in args:
            index = args.index(flag)
            if index + 1 < len(args):
                try:
                    return int(args[index + 1])
                except ValueError:
                    pass
    return None


def _from_ollama(base: str, model: str | None, timeout: float) -> int | None:
    if not model:
        return None
    try:
        data = requests.post(
            f"{_root(base)}/api/show", json={"model": model}, timeout=timeout
        ).json()
    except Exception:
        return None
    for key, value in (data.get("model_info") or {}).items():
        if key.endswith("context_length") and isinstance(value, int) and value > 0:
            return value
    return None


def probe(timeout: float = 4.0) -> tuple[int | None, str]:
    """(context window in tokens, where it came from) — (None, "unknown") if we can't tell."""
    cfg = config.section("model")
    override = cfg.get("context_window")
    if isinstance(override, int) and override > 0:
        return override, "[model] context_window"

    base = (cfg.get("base_url") or "").rstrip("/")
    model = cfg.get("model")
    if not base:
        return None, "unknown"

    value = _from_props(base, timeout)
    if value:
        return value, "GET /props"
    value = _from_models(base, model, timeout)
    if value:
        return value, "GET /models"
    value = _from_ollama(base, model, timeout)
    if value:
        return value, "POST /api/show"
    return None, "unknown"


def budget(ceiling: int = 100_000, share: float = 0.5) -> tuple[int, int | None, str]:
    """(token budget, detected window or None, source).

    The budget is half the model's window or the ceiling, whichever is smaller.
    """
    window, source = probe()
    if window:
        return min(int(window * share), ceiling), window, source
    return ceiling, None, source
