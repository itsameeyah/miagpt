# miagpt

A Discord slash command that answers in someone's voice.

`/ask what do you think of my build` → a reply that sounds like the person it's modelled on, typed
the way they type. Installed to your **account**, so it works in any channel, DM or group DM you can
type in. One small Python program: a persona markdown file, a jsonl memory file, and any
OpenAI-compatible model endpoint behind it.

## What you need

- Python 3.11 or newer (`python3 --version`)
- a Discord application with a bot token
- a model endpoint — a local llama.cpp / ollama / LM Studio server, or a hosted API

## 1. Get it

```bash
git clone https://github.com/itsameeyah/miagpt.git mybot
cd mybot
```

## 2. Make the Discord app

1. https://discord.com/developers/applications → **New Application**, name it whatever.
2. **Bot** tab → **Reset Token** → copy the token (it only shows once).
3. **Installation** tab → tick **Guild Install** *and* **User Install**, Install Link = Discord
   Provided Link, and give the user install the `applications.commands` scope.
4. **General Information** → copy the Application ID, then open
   `https://discord.com/oauth2/authorize?client_id=<APP_ID>&integration_type=1&scope=applications.commands`
   and add it to your account. This is what makes `/ask` show up everywhere for you.
5. Optional: your own user id (Discord settings → Advanced → Developer Mode, right-click your name →
   **Copy User ID**) goes in `[access] allowed_users` if you want to lock the bot to certain people.

No privileged intents are needed.

## 3. Configure

```bash
cp .env.example .env                      # paste your bot token in here
cp persona.example.md persona.md          # write the personality here
```

No persona yet? Skip the second line: on first start the bot asks for a folder of exported chat
logs, picks out one person's messages, writes a persona from them and prints it. `y` keeps it;
anything else you type is treated as a change request and it rewrites. Same thing on demand:

```bash
python tools/persona_from_logs.py --logs ~/exports --person sam
```

Point `--logs` at a folder and it reads every export in there. Only that person's messages are sent
to the model, and if there's more than one request's worth it summarises them in batches first, then
merges the notes into the persona. If the sample is bigger than half the model's context window (or
100k tokens, whichever is smaller) it tells you and asks before spending the requests.

Then edit:

| I want to change… | Edit |
| --- | --- |
| which model / endpoint | `[model]` in `config.toml` |
| who can use it | `[access] allowed_users` |
| how long a conversation lasts | `[session] minutes_between_messages` |
| how much it remembers | `[memory]` |
| fixed joke answers | `[[canned]]` blocks |
| the "x asked:" line above replies | `[bot] header` |
| the command's name or description | `[bot] command`, `description` |
| the personality | `persona.md` |

`config.toml` and `persona.md` reload while the bot is running. Python changes need a restart.

## 4. Run it

```bash
./run.sh          # macOS / Linux
run.bat           # Windows, or just double-click it
```

The first run creates `.venv` and installs the dependencies. Then type `/ask hello` anywhere in
Discord. You should see `synced global /ask` and `logged in as ...` in the log — global command sync
can take a minute the first time, so reload Discord if `/ask` isn't in the list yet.

Check an install without connecting:

```bash
./run.sh --check     # Windows: run.bat --check
```

By hand, if you'd rather:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python bot.py                        # Windows: .venv\Scripts\python bot.py
```

## 5. Model endpoints

Anything that speaks OpenAI `/chat/completions`:

```toml
base_url = "http://127.0.0.1:8080/v1"        # llama.cpp server, model = "qwen3"
base_url = "http://127.0.0.1:11434/v1"       # ollama
base_url = "http://127.0.0.1:1234/v1"        # lm studio
base_url = "https://openrouter.ai/api/v1"    # needs MIAGPT_API_KEY in .env
base_url = "https://api.openai.com/v1"       # needs MIAGPT_API_KEY in .env
```

Local models need no key. If the model doesn't support `reasoning_effort`, delete that line.

## 6. Keep it running (optional)

Running `run.sh` / `run.bat` in a terminal is enough to use it.

**Linux** — systemd user service, starts at login and restarts on crash:

```bash
./install.sh
systemctl --user status miagpt
journalctl --user -u miagpt -f
./install.sh --uninstall
```

**Windows** — shortcut to `run.bat` in `shell:startup` (Win+R → `shell:startup`), or Task
Scheduler → Create Task → "At log on" → Start a program → `run.bat`. Task Scheduler's Settings tab
has "restart if the task fails".

**macOS** — leave `./run.sh` in a terminal or `tmux`, or add a launchd plist in
`~/Library/LaunchAgents` with `ProgramArguments` = `.venv/bin/python bot.py` and `WorkingDirectory`
= the project folder.

## 7. Extras

**Memory** — on by default. The bot saves notes to `memory.jsonl` with `<remember>` tags and gets the
newest 4k characters back each message. Caps are in `[memory]`; set `enabled = false` to turn it off.

**People digests** — lets it answer "what do you think of jamie" from things jamie actually said.
Export a channel with [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) as
**JSON**, then:

```bash
python tools/people_index.py --logs ~/path/to/exports
python tools/analyze_style.py export.json their_username    # the typing numbers on their own
```

Set `[people] enabled = true` to use them. `[people] blocked` hides names that must never surface,
`[people] self` marks names that are you.

## Troubleshooting

- **`/ask` doesn't appear.** Reload Discord. Check the app has `applications.commands` in both
  installs, and that you added it to your account with the `integration_type=1` link from step 2.4.
- **401s or empty replies.** Check `MIAGPT_API_KEY` and `base_url`; the API's error body is logged.
- **Replies are one word or cut off.** Raise `max_tokens`.
- **It doesn't sound like them.** Rewrite `persona.md` with specifics — phrases, opinions, what
  they'd refuse to talk about.
- **Windows: `python` is not recognised.** Install Python 3.11+ from python.org and tick "Add
  python.exe to PATH", or use `py -3`.
- **Windows: the window flashes shut.** `run.bat` pauses on errors; `run.bat --check` reports the
  problem first.

## Licence

Apache-2.0.
