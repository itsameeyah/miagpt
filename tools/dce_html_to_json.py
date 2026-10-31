#!/usr/bin/env python3
"""dce_html_to_json.py — convert a DiscordChatExporter HTML export into its JSON shape.

Usage:
    python tools/dce_html_to_json.py <export.html> [more.html ...] [-o outdir]

Writes <outdir>/<same name>.json with {"channel": {...}, "messages": [...]} matching
DiscordChatExporter's Json format closely enough for digest.py and the other tools in this folder.
Stdlib only, no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


def _classes(attrs: dict) -> str:
    return attrs.get("class") or ""


class DceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict] = []
        self.title = ""
        self._cur: dict | None = None
        self._in_content = 0
        self._in_author = False
        self._in_timestamp = False
        self._buf: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _flush(self) -> None:
        if self._cur is None:
            return
        text = re.sub(r"[ \t]+", " ", "".join(self._buf)).strip()
        self._cur["content"] = text
        self.messages.append(self._cur)
        self._cur = None
        self._buf = []

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        cls = _classes(attrs)
        if tag == "div" and "chatlog__message-container" in cls:
            self._flush()
            self._cur = {
                "author": {"name": "", "nickname": None, "id": ""},
                "timestamp": "",
                "content": "",
            }
            return
        if self._cur is None:
            return
        if tag == "span" and "chatlog__author" in cls:
            self._in_author = True
            self._cur["author"]["name"] = (attrs.get("title") or "").split("#")[0] or attrs.get("data-user-id", "")
            self._cur["author"]["id"] = attrs.get("data-user-id") or ""
            # a nickname shows up as data-user-id + the visible text; captured below
            self._buf = []
            return
        if tag == "div" and "chatlog__content" in cls:
            self._in_content += 1
            return
        if tag == "div" and "chatlog__reply" in cls and self._in_content == 0:
            # quoted reply block: skip its text
            self._in_content = -1
            return
        if self._in_content > 0 and tag == "img":
            alt = attrs.get("alt")
            if alt:
                self._buf.append(alt)
            return
        if self._in_content > 0 and tag == "br":
            self._buf.append("\n")
            return
        if tag == "span" and "chatlog__timestamp" in cls:
            self._in_timestamp = True

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if tag == "span" and self._in_author:
            self._in_author = False
            return
        if tag == "div" and self._in_content < 0:
            self._in_content = 0
            return
        if tag == "div" and self._in_content > 0:
            self._in_content -= 1
            return
        if tag == "span" and self._in_timestamp:
            self._in_timestamp = False

    def handle_data(self, data: str) -> None:
        if self._cur is None:
            return
        if self._in_author:
            # visible author text is the nickname when set
            name = data.strip()
            if name and name != self._cur["author"]["name"]:
                self._cur["author"]["nickname"] = name
            return
        if self._in_timestamp and not self._cur["timestamp"]:
            self._cur["timestamp"] = data.strip()
            return
        if self._in_content > 0:
            self._buf.append(data)


def convert(path: Path) -> dict:
    parser = DceParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser._flush()
    stem = path.stem
    channel = {"name": stem, "id": ""}
    match = re.search(r"\[(\d{15,})\]", stem)
    if match:
        channel["id"] = match.group(1)
        channel["name"] = stem.split("[")[0].strip(" -")
    return {
        "channel": channel,
        "messageCount": len(parser.messages),
        "messages": [
            {"author": msg["author"], "timestamp": msg["timestamp"], "content": msg["content"]}
            for msg in parser.messages
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, default=None)
    args = ap.parse_args()

    for path in args.files:
        if path.suffix.lower() != ".html":
            print(f"skip (not html): {path}", file=sys.stderr)
            continue
        data = convert(path)
        outdir = args.outdir or path.parent
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (path.stem + ".json")
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"{path.name} -> {out} ({data['messageCount']} messages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
