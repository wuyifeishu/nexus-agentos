"""
Discord Channel Adapter — Discord.py Gateway.

Bot Token + Intents → Gateway connection → on_message → ChannelMessage.
"""

from __future__ import annotations

import json

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class DiscordAdapter(BaseChannelAdapter):
    """Discord Bot adapter (Gateway Intents).

    Config fields:
        bot_token: Discord bot token
        guild_ids: list of guild/servers to monitor (empty = all)
        command_prefix: bot command prefix (default "!")
        dm_enabled: allow DM messages (default True)
    """

    CHANNEL_TYPE = ChannelType.DISCORD

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._bot_token = config.extra.get("bot_token", "")
        self._guild_ids = config.extra.get("guild_ids", [])
        self._command_prefix = config.extra.get("command_prefix", "!")
        self._dm_enabled = config.extra.get("dm_enabled", True)

    # ── Message parsing ──

    async def parse_incoming(self, payload: dict) -> ChannelMessage | None:
        """Parse Discord gateway message event into ChannelMessage."""
        event_type = payload.get("t", "")  # Gateway event type
        data = payload.get("d", {})

        if event_type == "MESSAGE_CREATE":
            return self._parse_message(data)
        elif event_type == "INTERACTION_CREATE":
            return self._parse_interaction(data)
        elif event_type == "READY":
            return ChannelMessage(
                channel_type=ChannelType.DISCORD,
                channel_id="system",
                user_id="system",
                content=f"Bot ready (guilds: {len(data.get('guilds', []))})",
                message_type=MessageType.SYSTEM,
                raw=payload,
            )

        return None

    def _parse_message(self, data: dict) -> ChannelMessage | None:
        """Parse a Discord Message Create event."""
        author = data.get("author", {})
        if author.get("bot", False):
            return None  # Ignore other bots

        content = data.get("content", "")
        if not content.strip():
            return None

        user_id = author.get("id", "")
        channel_id = data.get("channel_id", "")
        guild_id = data.get("guild_id", "")

        # DM check
        if not guild_id and not self._dm_enabled:
            return None

        # Guild filter
        if guild_id and self._guild_ids and guild_id not in self._guild_ids:
            return None

        # Strip command prefix
        stripped = content
        if content.startswith(self._command_prefix):
            stripped = content[len(self._command_prefix) :]
            msg_type = MessageType.COMMAND
        else:
            msg_type = MessageType.TEXT

        return ChannelMessage(
            channel_type=ChannelType.DISCORD,
            channel_id=channel_id,
            user_id=user_id,
            content=stripped.strip(),
            message_type=msg_type,
            raw=data,
            reply_token=data.get("id", ""),
            metadata={
                "guild_id": guild_id,
                "username": author.get("username", ""),
                "display_name": data.get("member", {}).get("nick", author.get("username", "")),
                "attachments": [a.get("url") for a in data.get("attachments", [])],
            },
        )

    def _parse_interaction(self, data: dict) -> ChannelMessage | None:
        """Parse Discord slash command interaction."""
        interaction_data = data.get("data", {})
        command_name = interaction_data.get("name", "")

        user = data.get("user", {}) or data.get("member", {}).get("user", {})
        user_id = user.get("id", "")
        channel_id = data.get("channel_id", "")

        return ChannelMessage(
            channel_type=ChannelType.DISCORD,
            channel_id=channel_id,
            user_id=user_id,
            content=f"/{command_name} "
            + " ".join(
                f"{o.get('name')}:{o.get('value')}" for o in interaction_data.get("options", [])
            ),
            message_type=MessageType.COMMAND,
            raw=data,
            reply_token=data.get("token", ""),
        )

    # ── Reply ──

    async def reply(self, channel_id: str, content: str, **kwargs) -> ReplyResult:
        """Send message to Discord channel via REST API."""
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self._bot_token}",
            "Content-Type": "application/json",
        }
        body = {"content": content[:2000]}

        if kwargs.get("embed"):
            body["embeds"] = [kwargs["embed"]]

        # Interaction follow-up
        interaction_token = kwargs.get("interaction_token") or kwargs.get("reply_token")
        if interaction_token:
            url = f"https://discord.com/api/v10/webhooks/{self._bot_token}/{interaction_token}"

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json()
                    return ReplyResult(success=True, message_id=data.get("id", ""))
        except ImportError:
            import urllib.request

            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return ReplyResult(success=True, message_id=data.get("id", ""))

    async def reply_embed(
        self,
        channel_id: str,
        title: str,
        description: str,
        color: int = 0x5865F2,
        fields: list = None,
        **kwargs,
    ) -> ReplyResult:
        """Send a Discord embed message."""
        embed = {
            "title": title,
            "description": description,
            "color": color,
        }
        if fields:
            embed["fields"] = fields
        return await self.reply(channel_id, "", embed=embed, **kwargs)
