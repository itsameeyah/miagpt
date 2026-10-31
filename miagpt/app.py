"""Discord wiring: the /ask command, channel context, and posting the reply."""

from __future__ import annotations

import logging
from datetime import datetime

import discord

from . import brain, config, prompt

log = logging.getLogger("miagpt.app")

MAX_MESSAGE = 1990  # Discord's hard limit is 2000; leave room for the header


def channel_context(interaction: discord.Interaction) -> str:
    """Everything worth knowing about where this was typed."""
    channel = interaction.channel
    bits: list[str] = []
    guild = getattr(channel, "guild", None)

    if isinstance(channel, discord.DMChannel):
        bits.append("this is a direct message with you")
    else:
        if guild is not None:
            bits.append(f"server: {guild.name}")
        category = getattr(channel, "category", None)
        if category is not None and getattr(category, "name", None):
            bits.append(f"category: {category.name}")
        if getattr(channel, "name", None):
            bits.append(f"channel: #{channel.name}")
        topic = (getattr(channel, "topic", None) or "").strip()
        if topic:
            bits.append(f"channel topic: {topic[:300]}")
        if getattr(channel, "nsfw", False):
            bits.append("marked nsfw")
    bits.append(f"the time for me right now is {datetime.now().strftime('%A %H:%M')}")
    return "\n".join(f"- {bit}" for bit in bits)


def build_command() -> discord.app_commands.Command:
    cfg = config.section("bot")
    name = cfg.get("command") or "ask"
    description = cfg.get("description") or "ask something"

    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @discord.app_commands.command(name=name, description=description)
    @discord.app_commands.describe(text="what you want to ask")
    async def ask(interaction: discord.Interaction, text: str) -> None:
        allowed = config.allowed_users()
        if allowed and str(interaction.user.id) not in allowed:
            await interaction.response.send_message(
                config.reply("not_allowed", "this one's not for you sorry"), ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=False)

        display = getattr(interaction.user, "display_name", interaction.user.name)
        username = interaction.user.name
        who = f"{display} (@{username})" if display.lower() != username.lower() else display

        asked = text
        limit = int(cfg.get("header_question_limit", 300))
        if len(asked) > limit:
            asked = asked[:limit].rsplit(" ", 1)[0] + "..."
        header = (cfg.get("header") or "-# {display} asked: {text}").format(
            display=display, text=asked, username=username
        )

        fixed = brain.canned_reply(text)
        if fixed is not None:
            log.info("canned reply for %r", text)
            await interaction.edit_original_response(
                content=f"{header}\n{fixed}"[:MAX_MESSAGE],
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        channel_id = interaction.channel_id or 0
        session = brain.session_for(channel_id)
        try:
            context = channel_context(interaction)
        except Exception as exc:
            log.warning("channel context failed: %s", exc)
            context = "- a discord channel"

        try:
            reply = brain.answer(text, who, context, session)
        except Exception as exc:
            log.exception("answer failed: %s", exc)
            reply = config.reply("error_reply", "something broke on my end, try again in a sec")

        brain.record(session, who, text, reply)

        await interaction.edit_original_response(
            content=f"{header}\n{reply}"[:MAX_MESSAGE],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    return ask


class Miagpt(discord.Client):
    """A bare client: one slash command, no message events, no privileged intents."""

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.none())
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.tree.add_command(build_command())
        await self.tree.sync()
        log.info("synced global /%s", config.section("bot").get("command") or "ask")

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, getattr(self.user, "id", "?"))


def main() -> None:
    token = config.discord_token()
    if not token:
        raise SystemExit(
            "No bot token. Put MIAGPT_DISCORD_TOKEN=... in .env next to bot.py "
            "(see .env.example) and start again."
        )
    path = prompt.persona_path()
    if not path.exists():
        raise SystemExit(
            f"No persona file at {path}.\n"
            "Copy persona.example.md to persona.md, write your version, then start again:\n"
            f"  cp persona.example.md {path.name}"
        )
    Miagpt().run(token, log_handler=None)
