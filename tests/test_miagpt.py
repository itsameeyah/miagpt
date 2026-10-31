"""Offline tests for the answer pipeline. No Discord, no network, no model.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

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

from miagpt import brain, config, llm, memory, prompt, selfcheck  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
