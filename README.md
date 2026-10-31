# miagpt

A single Discord slash command that answers in someone's voice.

`/ask what do you think of my minecraft build` → a reply that sounds like the person it's modelled
on, typed the way they type, with their opinions and their running jokes. It's installed to your
**account** rather than a server, so it works in any channel, DM or group DM you can type in.

One small Python service. No database, no queue, no framework: a persona markdown file, a jsonl
memory file, an optional folder of people digests, and any OpenAI-compatible model endpoint behind
it. About 700 lines total, most of it comments.

Made to be copied: rename it, rewrite `persona.md`, point it at your own model, done.

```
bot.py                  entrypoint
config.toml             everything you'd tweak (hot reloads)
persona.example.md      template for the system prompt — copy to persona.md, that one is gitignored
.env                    bot token (never commit)
miagpt/
  config.py             config + .env loading, hot reload
  prompt.py             system prompt assembly
  memory.py             the jsonl memory file
  people.py             optional digests of real people from chat logs
  llm.py                one chat completion + reply clean-up
  brain.py              the answer pipeline (testable without Discord)
  app.py                Discord wiring, /ask command
  selfcheck.py          `bot.py --check`: is this install ready to start?
tools/
  people_index.py       build people digests from DiscordChatExporter json
  digest.py             quick stats over exported logs
  dce_html_to_json.py   convert an HTML export to json
  analyze_style.py      measure how someone types, for the persona file
tests/                  offline tests (no Discord, no network, no model)
install.sh              optional: systemd user service (Linux)
run.sh                  start it in this terminal (macOS / Linux)
run.bat                 same, for Windows (double-clickable)
```

## Quick start

Needs Python 3.11+ and a model endpoint (a local llama.cpp / ollama / LM Studio server is fine and
free).

```bash
git clone https://github.com/itsameeyah/miagpt.git mybot
cd mybot

cp .env.example .env                      # paste your bot token in
cp persona.example.md persona.md          # then rewrite it — this is the personality
$EDITOR config.toml                       # model endpoint + who's allowed to use it

./run.sh                                  # macOS / Linux
run.bat                                   # Windows (or just double-click it)
```

The first run creates `.venv` and installs the two dependencies for you. Then type `/ask hello`
anywhere in Discord. You want `synced global /ask` and `logged in as ...` in the log. Global
command sync can take a minute the first time — reload Discord if it's not in the list yet.

Not sure something's wrong? `./run.sh --check` (or `run.bat --check`) checks the config, persona,
token, model endpoint and memory file without connecting to Discord.

Prefer doing it by hand? It's just Python:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python bot.py                       # Windows: .venv\Scripts\python bot.py
```

## 1. Make the Discord app

1. https://discord.com/developers/applications → **New Application**, name it whatever.
2. **Bot** tab → **Reset Token** → copy it (it only shows once). Put it in `.env`.
3. **Installation** tab → tick **Guild Install** *and* **User Install**, Install Link = Discord
   Provided Link, and make sure the user install includes the `applications.commands` scope.
4. **General Information** → copy the Application ID, then open
   `https://discord.com/oauth2/authorize?client_id=<APP_ID>&integration_type=1&scope=applications.commands`
   and add it to your account. This is the step that makes `/ask` show up everywhere for *you*,
   including DMs with other people.
5. Grab your own user id: Discord settings → Advanced → Developer Mode on, then right-click your
   name → **Copy User ID**. Put it in `[access] allowed_users` if you want to lock the bot to a few
   people.

No privileged intents are needed — it registers one slash command and ignores messages entirely.

## 2. Write the persona

`persona.md` **is** the bot. Everything else is plumbing. Copy `persona.example.md`, then fill in:

- who they are, in a few lines — age, pronouns, what they're into, what they're like
- their names and usernames, so the bot knows who "them" is
- the privacy rules (keep them — see below)
- **how they type**: message length, lowercase or not, apostrophes or not, emoji habits
- how they answer: dry, warm, blunt, chaotic — pick a few behaviours and commit

If you have a channel export, measure the typing section instead of guessing:

```bash
python tools/analyze_style.py export.json their_username
```

It prints median message length, punctuation rates, which contractions they drop, top words and
emoji. Numbers in the persona beat adjectives.

Keep the rule that it never invents private facts about the person it imitates, and that everyone
is they/them until corrected. That's the difference between a fun bit and something that leaks.

## 3. What to edit, and where

| I want to change… | Edit |
| --- | --- |
| personality, tone, what it knows | `persona.md` |
| which model / endpoint | `[model]` in `config.toml` |
| who can use it | `[access] allowed_users` |
| how long a conversation lasts | `[session] minutes_between_messages` |
| how much it remembers | `[memory]` |
| fixed joke answers | `[[canned]]` blocks |
| the "x asked:" line above replies | `[bot] header` |
| what it says when a model call fails | `[bot] error_reply`, `empty_reply` |
| the command's name or description | `[bot] command`, `description` |

`config.toml` and `persona.md` reload while the bot is running — save the file and the next `/ask`
picks it up. Only edits to the Python need a restart.

## 4. Model endpoints

Anything that speaks OpenAI `/chat/completions`:

```toml
base_url = "http://127.0.0.1:8080/v1"        # llama.cpp server, model = "qwen3"
base_url = "http://127.0.0.1:11434/v1"       # ollama
base_url = "http://127.0.0.1:1234/v1"        # lm studio
base_url = "https://openrouter.ai/api/v1"    # needs MIAGPT_API_KEY in .env
base_url = "https://api.openai.com/v1"       # needs MIAGPT_API_KEY in .env
```

Local models need no key — leave `MIAGPT_API_KEY` empty. If the model doesn't support
`reasoning_effort`, delete that line. `max_tokens` is small on purpose: chat messages, not essays.

## 5. Memory

On by default. The model writes notes to `memory.jsonl` with `<remember>` tags and gets the newest
4k characters back on every message, so it accumulates running jokes and who's who without a
database. Caps live in `[memory]`. It also has `<recall>` for pulling the older end back when the
file outgrows the injection budget, and `[bot] nothing_saved` for when there's still nothing.

`memory.jsonl` is gitignored. It's the bot's own notes about your friends — keep it local.

## 6. Optional: people digests

Lets it answer "what do you think of jamie" using things jamie actually said, instead of making
something up. Export a channel with
[DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) as **JSON**, then:

```bash
python tools/people_index.py --logs ~/path/to/exports
```

That writes `people/people.json` plus one small digest per person. Re-run after exporting more
logs. Don't want it? It's off by default (`[people] enabled = false`).

**Only do this with logs you're allowed to use, and get people's consent.** The digests are other
people's words; `people/` is gitignored for that reason and should never be committed or published.

Two hard filters run before anything reaches the prompt:

- `[people] blocked` — names that must never surface, e.g. a name someone no longer uses.
- `[people] self` — names that are you, so the bot doesn't look its own owner up as a stranger.

## 7. Keeping it running (optional)

None of this is required. Running `run.sh` / `run.bat` in a terminal is a perfectly good way to
keep a personal bot up — close the window and it stops.

**Linux** — systemd user service, starts at login and restarts on crash:

```bash
./install.sh              # makes .venv if needed, writes ~/.config/systemd/user/miagpt.service
systemctl --user status miagpt
journalctl --user -u miagpt -f
./install.sh --uninstall  # stop and remove it
```

To keep it alive after you log out: `loginctl enable-linger $USER`.

**Windows** — two options, no service needed:

- put a shortcut to `run.bat` in your startup folder (Win+R → `shell:startup`);
- or Task Scheduler → Create Task → trigger "At log on" → action "Start a program" → your
  `run.bat`. The Settings tab has "restart if the task fails", which is the closest thing to
  `Restart=on-failure`.

**macOS** — leave `./run.sh` in a terminal or a `tmux` session. For login start-up, a launchd
plist in `~/Library/LaunchAgents` with `ProgramArguments` = `.venv/bin/python bot.py` and
`WorkingDirectory` = the project folder does the same job.

The bot only ever makes outbound connections, so no ports or firewall rules are involved on any OS.

## 8. Tests

```bash
python -m unittest discover -s tests -v
```

Offline: no Discord, no network, no model. They cover canned replies, the model pipeline, memory
caps and the prompt assembly.

## Troubleshooting

- **`/ask` doesn't appear.** Global sync takes a minute; reload Discord (Ctrl+R). Check the app has
  the `applications.commands` scope in *both* installs, and that you added it to your account with
  the `integration_type=1` link from step 1.4.
- **`401` / empty replies.** Check `MIAGPT_API_KEY` and `base_url`; watch the log for the API's
  error body, which is logged at warning level.
- **Replies are one word, or cut off.** `max_tokens` is too low, or the model is stopping early.
- **It doesn't sound like them.** The persona file is the whole personality. Add real specifics
  (opinions, phrases, what they'd refuse to talk about) and measure the typing section.
- **It answers as the wrong person in DMs.** Add the names it might be called to `[bot] aliases`
  and to `[people] self`.
- **Windows: `python` is not recognised.** Install Python 3.11+ from python.org and tick "Add
  python.exe to PATH", or use the `py` launcher: `py -3 -m venv .venv`.
- **Windows: the window flashes shut.** `run.bat` pauses on errors; if you ran `bot.py` directly,
  start it from a terminal so you can read what it said. `run.bat --check` also reports the problem
  without connecting.

## Notes for whoever inherits this

- It's a **clone**, not the person. When asked, it says so plainly instead of pretending to be the
  real account. Don't strip that out — it's what makes the joke land without being creepy.
- If you fork this for someone who hasn't agreed to it, you're the one being creepy. Ask first.
- Everything opinionated (canned answers, emoji rules, tone) is plain text in `persona.md` and
  `config.toml`. Nothing is hardcoded in the Python beyond the pipeline itself.

## Licence

Apache-2.0 — see `LICENSE`. Do what you like with it; if you fork it and ship it, keep the notice.
