"""Offline tests for the answer pipeline. No Discord, no network, no model.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="miagpt-tests-"))
PERSONA = TMP / "persona.md"
MEMORY = TMP / "memory.jsonl"
CONFIG = TMP / "config.toml"

PERSONA.write_text("# who you are\n\nyou are testbot, an ai version of a test person.\n", encoding="utf-8")
CONFIG.write_text(
    f"""
[bot]
name = "testbot"
aliases = ["tb"]
command = "ask"
header = "-# {{display}} asked: {{text}}"
header_question_limit = 20
error_reply = "oops"
empty_reply = "nothing"
unknown_person = "who is {{name}}"
nothing_saved = "no notes"
not_allowed = "nope"

[model]
base_url = "http://127.0.0.1:9/v1"
model = "test"
max_tokens = 50
temperature = 0.5
timeout_seconds = 1

[session]
minutes_between_messages = 15
turns = 2
max_channels = 10

[memory]
enabled = true
file = "{MEMORY}"
inject_characters = 1000
max_file_characters = 600
max_entry_characters = 60

[people]
enabled = false

[persona]
file = "{PERSONA}"

[access]
allowed_users = []

[[canned]]
when = ["what day is it"]
reply = "YOUR LAST"
""",
    encoding="utf-8",
)

# config.py reads these paths at import time, so set them before importing the package.
os.environ["MIAGPT_CONFIG"] = str(CONFIG)
os.environ["MIAGPT_ENV"] = str(TMP / "does-not-exist.env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miagpt import (  # noqa: E402
    brain, config, context, llm, memory, persona_gen, prompt, selfcheck, style,
)


class AnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        MEMORY.unlink(missing_ok=True)
        brain._sessions.clear()
        self._real_complete = llm.complete

    def tearDown(self) -> None:
        llm.complete = self._real_complete

    def fake(self, reply: str) -> None:
        brain.llm.complete = lambda system, messages, session_id: reply

    def answer(self, text: str = "hello") -> str:
        session = brain.session_for(1)
        return brain.answer(text, "someone (@someone)", "- a test channel", session)

    def test_canned_reply_is_matched_loosely(self):
        self.assertEqual(brain.canned_reply("What day is it???"), "YOUR LAST")
        self.assertIsNone(brain.canned_reply("what day is it tomorrow"))

    def test_plain_reply_and_memory_tag(self):
        self.fake("hi there <remember>likes bunnies</remember>")
        self.assertEqual(self.answer(), "hi there")
        notes = [e["text"] for e in memory.load()]
        self.assertEqual(notes, ["likes bunnies"])

    def test_trailing_emoji_gets_doubled(self):
        self.fake("ok 😭")
        self.assertEqual(self.answer(), "ok 😭😭")
        self.assertEqual(llm.stack_emoji_tail("ok 😭😭"), "ok 😭😭")
        self.assertEqual(llm.stack_emoji_tail("no emoji here"), "no emoji here")

    def test_lookup_with_no_digest_uses_config_line(self):
        self.fake("<lookup>nobody at all</lookup>")
        self.assertEqual(self.answer("who is nobody"), "who is nobody at all")

    def test_recall_with_nothing_older_uses_config_line(self):
        self.fake("<recall>")
        self.assertEqual(self.answer(), "no notes")

    def test_empty_model_reply_uses_config_line(self):
        self.fake("")
        self.assertEqual(self.answer(), "nothing")

    def test_long_reply_is_trimmed_to_a_chat_message(self):
        self.fake("word " * 400)
        reply = self.answer()
        self.assertLessEqual(len(reply), 903)
        self.assertTrue(reply.endswith("..."))

    def test_history_is_recorded_and_trimmed(self):
        self.fake("one")
        session = brain.session_for(2)
        brain.record(session, "someone", "hi", "one")
        brain.record(session, "someone", "hi again", "two")
        brain.record(session, "someone", "third", "three")
        self.assertEqual(len(session["msgs"]), 4)  # turns = 2 -> two exchanges
        self.assertEqual(session["msgs"][-1], {"role": "assistant", "content": "three"})

    def test_session_rolls_over_after_the_gap(self):
        brain._sessions.clear()
        first = brain.session_for(3)
        first["last"] -= 16 * 60
        second = brain.session_for(3)
        self.assertNotEqual(first["sid"], second["sid"])


class MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        MEMORY.unlink(missing_ok=True)

    def test_duplicate_notes_are_ignored(self):
        self.assertTrue(memory.add("the sky is blue"))
        self.assertFalse(memory.add("the sky is blue"))

    def test_entry_is_capped(self):
        memory.add("x" * 200)
        self.assertEqual(len(memory.load()[0]["text"]), 60)

    def test_file_is_capped_and_drops_oldest(self):
        for i in range(20):
            memory.add(f"note number {i} padded out to take up room")
        self.assertLessEqual(len(memory.load()), 6)
        self.assertIn("note number 19", memory.load()[-1]["text"])

    def test_block_reports_what_did_not_fit(self):
        for i in range(6):
            memory.add(f"fact {i} " + "y" * 40)
        text, omitted = memory.block(120)
        self.assertIn("fact 5", text)
        self.assertGreater(omitted, 0)


class PromptTests(unittest.TestCase):
    def test_prompt_contains_persona_memory_and_context(self):
        memory.add("likes bunnies")
        text = prompt.build("- channel: #general", "sam (@sam)", "likes bunnies", 0, "")
        self.assertIn("you are testbot", text)
        self.assertIn("channel: #general", text)
        self.assertIn("sam (@sam)", text)
        self.assertIn("likes bunnies", text)
        self.assertIn("they/them", text)

    def test_lookup_without_digest_builds_nothing(self):
        self.assertEqual(prompt.with_lookup("- x", "sam", "", 0, "", "nobody"), "")


class ConfigTests(unittest.TestCase):
    def test_reply_placeholders(self):
        self.assertEqual(config.reply("unknown_person", "?", name="sam"), "who is sam")
        self.assertEqual(config.reply("empty_reply", "?"), "nothing")

    def test_self_names_include_bot_name_and_aliases(self):
        self.assertEqual(config.self_names(), {"testbot", "tb", "bot"})

    def test_missing_placeholder_is_left_alone(self):
        self.assertEqual(config.reply("unknown_person", "?", other="sam"), "who is {name}")


class SelfcheckTests(unittest.TestCase):
    def report(self) -> tuple[int, str]:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = selfcheck.run(probe=False)
        return code, buffer.getvalue()

    def test_missing_token_is_reported(self):
        import os

        os.environ.pop("MIAGPT_DISCORD_TOKEN", None)
        code, output = self.report()
        self.assertEqual(code, 1)
        self.assertIn("bot token", output)
        self.assertIn("config.toml", output)
        self.assertIn("persona.md", output)

    def test_ready_install_passes(self):
        import os

        os.environ["MIAGPT_DISCORD_TOKEN"] = "fake-token-value-1234"
        try:
            code, output = self.report()
        finally:
            os.environ.pop("MIAGPT_DISCORD_TOKEN", None)
        self.assertEqual(code, 0, output)
        self.assertIn("looks good", output)


EXPORT = TMP / "export.json"
EXPORT.write_text(json.dumps({
    "channel": {"name": "general"},
    "messages": [
        *[
            {
                "author": {"name": "sam", "nickname": "sammers", "id": "42"},
                "timestamp": f"2026-01-{i % 28 + 1:02d}T12:00:00+00:00",
                "content": f"hello there number {i}, this is a test message of mine",
            }
            for i in range(30)
        ],
        {
            "author": {"name": "other", "nickname": "", "id": "43"},
            "timestamp": "2026-01-03T12:00:00+00:00",
            "content": "not sam talking",
        },
    ],
}), encoding="utf-8")


class StyleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.messages = style.load(EXPORT)

    def test_resolves_name_nickname_and_id(self):
        self.assertEqual(style.resolve(self.messages, "sam"), "sam")
        self.assertEqual(style.resolve(self.messages, "@SAM"), "sam")
        self.assertEqual(style.resolve(self.messages, "42"), "sam")
        self.assertEqual(style.resolve(self.messages, "sammers"), "sam")
        self.assertIsNone(style.resolve(self.messages, "nobody"))

    def test_texts_are_only_that_person(self):
        texts = style.texts_for(self.messages, "sam")
        self.assertEqual(len(texts), 30)
        self.assertTrue(all("not sam" not in t["text"] for t in texts))
        self.assertTrue(all(t["ts"].startswith("2026-01") for t in texts))

    def test_drops_link_only_messages(self):
        messages = [
            {"name": "sam", "content": "https://example.com", "ts": "", "id": "", "nick": "", "channel": ""},
            {"name": "sam", "content": "have a look https://example.com", "ts": "", "id": "", "nick": "", "channel": ""},
        ]
        self.assertEqual(len(style.texts_for(messages, "sam")), 1)

    def test_stats_are_measured_not_guessed(self):
        s = style.stats(["hello there friend", "HI THIS IS SHOUTING"])
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["median_length"], 18)
        self.assertEqual(s["lowercase_start_pct"], 50)
        self.assertEqual(s["exclaim_pct"], 0)

    def test_dates_come_from_timestamps_not_message_text(self):
        items = style.texts_for(self.messages, "sam")
        s = style.stats(items)
        self.assertEqual(list(s["years"]), ["2026"])
        self.assertIn("2026", style.summary_line("sam", items))

    def test_samples_are_unique_and_capped(self):
        picked = style.samples(style.texts_for(self.messages, "sam"), limit=5)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(set(picked)), 5)


class PersonaGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.out = TMP / "generated_persona.md"
        self.out.unlink(missing_ok=True)
        (TMP / ".persona-notes.json").unlink(missing_ok=True)
        self._real_complete = llm.complete
        self.calls: list[dict] = []

    def tearDown(self) -> None:
        llm.complete = self._real_complete
        self.out.unlink(missing_ok=True)

    def fake_model(self, *replies: str):
        def complete(system, messages, session_id, max_tokens=None, temperature=None, effort=None):
            self.calls.append({"system": system, "messages": messages,
                               "max_tokens": max_tokens, "effort": effort})
            return replies[min(len(self.calls) - 1, len(replies) - 1)]

        llm.complete = complete

    def run_gen(self, answers: list[str], **kwargs) -> int:
        iterator = iter(answers)

        def ask(_="") -> str:
            return next(iterator)

        return persona_gen.interactive(
            EXPORT, "sam", self.out, ask=ask, echo=lambda *a, **k: None, **kwargs
        )

    def test_clean_markdown_strips_fences_and_preamble(self):
        messy = "Sure! Here's the file:\n```markdown\n# who you are\nyou are x.\n```"
        self.assertEqual(persona_gen.clean_markdown(messy), "# who you are\nyou are x.\n")

    def test_draft_asks_for_a_long_enough_reply(self):
        self.fake_model("# who you are\nhatted.")
        persona_gen.draft("sam", style.stats(style.texts_for(style.load(EXPORT), "sam")), ["hi"])
        self.assertEqual(self.calls[0]["max_tokens"], 4000)
        self.assertEqual(self.calls[0]["effort"], "low")
        request = self.calls[0]["messages"][0]["content"]
        self.assertIn("testbot", request)   # bot name comes from [bot] name
        self.assertIn("sam", request)
        self.assertIn("hi", request)        # example messages are included
        self.assertIn("median", request)    # and the measured stats

    def test_accepting_writes_the_persona(self):
        self.fake_model("# who you are\nyou are sambot.")
        self.assertEqual(self.run_gen(["y"]), 0)
        self.assertIn("you are sambot", self.out.read_text(encoding="utf-8"))

    def test_yes_flag_skips_the_question(self):
        self.fake_model("# who you are\nyou are sambot.")
        self.assertEqual(self.run_gen([], assume_yes=True), 0)
        self.assertTrue(self.out.exists())

    def test_revision_is_sent_back_to_the_model(self):
        self.fake_model("# who you are\nfirst try.", "# who you are\nsecond try.")
        self.assertEqual(self.run_gen(["make it meaner", "y"]), 0)
        self.assertEqual(len(self.calls), 2)
        second_request = self.calls[1]["messages"][0]["content"]
        self.assertIn("make it meaner", second_request)
        self.assertIn("first try", second_request)
        self.assertIn("second try", self.out.read_text(encoding="utf-8"))

    def test_quitting_writes_nothing(self):
        self.fake_model("# who you are\nnope.")
        self.assertEqual(self.run_gen(["q"]), 1)
        self.assertFalse(self.out.exists())

    def test_unknown_person_writes_nothing(self):
        self.fake_model("# who you are\nnope.")
        code = persona_gen.interactive(EXPORT, "ghost", self.out, ask=input, echo=lambda *a, **k: None)
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())

    def test_bootstrap_is_a_no_op_when_a_persona_exists(self):
        existing = TMP / "existing_persona.md"
        existing.write_text("# who you are\nfine.", encoding="utf-8")
        self.assertTrue(persona_gen.bootstrap(existing, echo=lambda *a, **k: None))


class ContextTests(unittest.TestCase):
    """The window probe: config wins, then the three flavours of endpoint, then unknown."""

    class Resp:
        def __init__(self, data, status=200):
            self._data = data
            self.status_code = status

        def json(self):
            return self._data

    def setUp(self) -> None:
        self._get = context.requests.get
        self._post = context.requests.post
        self.addCleanup(self.restore)
        self._cfg = config._cache["cfg"]

    def restore(self) -> None:
        context.requests.get = self._get
        context.requests.post = self._post
        if "context_window" in self._cfg.get("model", {}):
            del self._cfg["model"]["context_window"]

    def test_config_override_wins(self):
        self._cfg["model"]["context_window"] = 32768
        self.assertEqual(context.probe(), (32768, "[model] context_window"))

    def test_llamacpp_props(self):
        context.requests.get = lambda url, **k: self.Resp(
            {"default_generation_settings": {"n_ctx": 8192}}
        ) if url.endswith("/props") else self.Resp({}, status=404)
        self.assertEqual(context.probe(), (8192, "GET /props"))

    def test_openai_style_models_endpoint(self):
        def get(url, **k):
            if url.endswith("/models"):
                return self.Resp({"data": [{"id": "test", "context_length": 200_000}]})
            return self.Resp({}, status=404)

        context.requests.get = get
        self.assertEqual(context.probe(), (200_000, "GET /models"))

    def test_llamacpp_router_args_are_parsed(self):
        def get(url, **k):
            if url.endswith("/models"):
                return self.Resp({"data": [{"id": "test", "status": {
                    "args": ["llama-server", "--ctx-size", "131072"]}}]})
            return self.Resp({}, status=404)

        context.requests.get = get
        self.assertEqual(context.probe(), (131072, "GET /models"))

    def test_ollama_show(self):
        context.requests.get = lambda url, **k: self.Resp({}, status=404)
        context.requests.post = lambda url, **k: self.Resp(
            {"model_info": {"general.architecture": "llama", "llama.context_length": 4096}}
        )
        self.assertEqual(context.probe(), (4096, "POST /api/show"))

    def test_unknown_is_honest(self):
        context.requests.get = lambda url, **k: self.Resp({}, status=404)
        context.requests.post = lambda url, **k: self.Resp({}, status=404)
        self.assertEqual(context.probe(), (None, "unknown"))
        self.assertEqual(context.budget(), (100_000, None, "unknown"))

    def test_budget_is_half_the_window_or_the_ceiling(self):
        self._cfg["model"]["context_window"] = 131072
        self.assertEqual(context.budget()[0], 65_536)      # half of 131072
        self._cfg["model"]["context_window"] = 400_000
        self.assertEqual(context.budget()[0], 100_000)     # capped


class CollectTests(unittest.TestCase):
    def test_streaming_collect_matches_plain_stats(self):
        gathered = style.collect(EXPORT, "sam")
        plain = style.stats(style.texts_for(style.load(EXPORT), "sam"))
        streamed = style.stats_from(gathered)
        for key in ("count", "median_length", "mean_length", "p90_length",
                    "lowercase_start_pct", "question_pct", "exclaim_pct", "multiline_pct",
                    "filler_hits", "top_words", "years"):
            self.assertEqual(streamed[key], plain[key], key)

    def test_collect_only_keeps_the_named_person(self):
        gathered = style.collect(EXPORT, "sam")
        self.assertEqual(gathered["count"], 30)
        self.assertEqual(gathered["total_seen"], 31)   # everything scanned
        self.assertEqual(list(gathered["channels"]), ["general"])

    def test_collect_scans_a_folder(self):
        folder = TMP / "exports"
        folder.mkdir(exist_ok=True)
        one = folder / "a.json"
        two = folder / "b.json"
        one.write_text(EXPORT.read_text(encoding="utf-8"), encoding="utf-8")
        data = json.loads(EXPORT.read_text(encoding="utf-8"))
        data["channel"]["name"] = "second"
        two.write_text(json.dumps(data), encoding="utf-8")
        gathered = style.collect(folder, "sam")
        self.assertEqual(gathered["count"], 60)
        self.assertEqual(sorted(gathered["channels"]), ["general", "second"])


class BatchTests(unittest.TestCase):
    def test_batches_cover_every_sample_and_respect_the_size(self):
        gathered = style.collect(EXPORT, "sam")
        batches = style.batch_samples(gathered, chars_per_batch=400)
        rows = [row for batch in batches for row in batch]
        self.assertEqual(len(rows), sum(len(v) for v in gathered["samples"].values()))
        self.assertGreater(len(batches), 1)
        for batch in batches:
            self.assertLessEqual(sum(len(r["text"]) + 2 for r in batch), 400)

    def test_batches_mix_channels(self):
        gathered = {"samples": {
            "a": [{"text": "a" * 20, "ts": "2026-01-01", "channel": "a"} for _ in range(5)],
            "b": [{"text": "b" * 20, "ts": "2026-01-02", "channel": "b"} for _ in range(5)],
        }}
        batches = style.batch_samples(gathered, chars_per_batch=200)
        self.assertTrue(all(len({r["channel"] for r in batch}) == 2 for batch in batches[:-1]))


class PersonaGenBatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.out = TMP / "batched_persona.md"
        self.notes = TMP / ".persona-notes.json"
        self.out.unlink(missing_ok=True)
        self.notes.unlink(missing_ok=True)
        self._real_complete = llm.complete
        self._cfg = config._cache["cfg"]
        self._persona_cfg = dict(self._cfg.get("persona") or {})
        self.calls: list[dict] = []

    def tearDown(self) -> None:
        llm.complete = self._real_complete
        self.out.unlink(missing_ok=True)
        self.notes.unlink(missing_ok=True)
        self._cfg["persona"] = self._persona_cfg

    def fake_model(self, *replies: str):
        def complete(system, messages, session_id, max_tokens=None, temperature=None, effort=None):
            self.calls.append({"session": session_id, "messages": messages})
            return replies[min(len(self.calls) - 1, len(replies) - 1)]

        llm.complete = complete

    def run_gen(self, answers: list[str], **kwargs) -> int:
        iterator = iter(answers)

        def ask(_="") -> str:
            return next(iterator)

        return persona_gen.interactive(
            EXPORT, "sam", self.out, ask=ask, echo=lambda *a, **k: None, **kwargs
        )

    def test_many_messages_are_batched_then_merged(self):
        self._cfg["persona"]["batch_characters"] = 300
        self.fake_model("notes one", "notes two", "notes three", "# who you are\nmerged.")
        self.assertEqual(self.run_gen(["y"]), 0)
        batch_calls = [c for c in self.calls if c["session"].startswith("persona-notes")]
        self.assertGreater(len(batch_calls), 1)
        self.assertEqual(self.calls[-1]["session"], "persona-merge")
        self.assertIn("merged", self.out.read_text(encoding="utf-8"))
        self.assertTrue(self.notes.exists())
        cached = json.loads(self.notes.read_text(encoding="utf-8"))
        self.assertEqual(cached["author"], "sam")
        self.assertGreater(len(cached["batches"]), 1)

    def test_cached_notes_skip_the_batches(self):
        self._cfg["persona"]["batch_characters"] = 300
        self.fake_model("notes", "# who you are\nfirst.")
        self.assertEqual(self.run_gen(["y"]), 0)
        self.calls.clear()
        self.fake_model("# who you are\nsecond.")
        self.assertEqual(self.run_gen(["y"]), 0)
        self.assertEqual([c["session"] for c in self.calls], ["persona-merge"])
        self.assertIn("second", self.out.read_text(encoding="utf-8"))

    def test_truncated_notes_are_retried_with_more_room(self):
        rows = [{"text": "hello there", "ts": "2026-01-01", "channel": "general"}]
        budget: list[int | None] = []
        replies = iter(["cut off mid", "full notes about how they type"])

        def complete(system, messages, session_id, max_tokens=None, temperature=None, effort=None):
            budget.append(max_tokens)
            llm.last_truncated = len(budget) == 1   # first attempt ran out of tokens
            return next(replies)

        llm.complete = complete
        note = persona_gen.batch_notes("sam", rows, 1, 1)
        self.assertEqual(note, "full notes about how they type")
        self.assertEqual(len(budget), 2)
        self.assertGreater(int(budget[1] or 0), int(budget[0] or 0))

    def test_over_budget_asks_and_batches(self):
        self._cfg["persona"]["batch_characters"] = 300
        self._cfg["model"]["context_window"] = 400          # 200 token budget ≈ 700 chars
        try:
            self.fake_model("notes a", "notes b", "notes c", "# who you are\nbatched.")
            self.assertEqual(self.run_gen(["b", "y"]), 0)
        finally:
            del self._cfg["model"]["context_window"]
        self.assertIn("batched", self.out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
