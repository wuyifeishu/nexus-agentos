"""
Telegram Channel Adapter — Telegram Bot API.

BotFather token → long-polling / webhook → ChannelMessage.
"""

from __future__ import annotations

import json
from typing import Optional, Any

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class TelegramAdapter(BaseChannelAdapter):
    """Telegram Bot API adapter.

    Config fields:
        bot_token: Telegram bot token from @BotFather
        webhook_url: HTTPS webhook URL (leave empty for long-polling)
        allowed_chats: list of chat IDs (empty = all)
        parse_mode: "HTML" | "MarkdownV2" | None
    """

    CHANNEL_TYPE = ChannelType.TELEGRAM

    # Telegram API base URL
    API_BASE = "https://api.telegram.org"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._bot_token = config.extra.get("bot_token", "")
        self._webhook_url = config.extra.get("webhook_url", "")
        self._allowed_chats = config.extra.get("allowed_chats", [])
        self._parse_mode = config.extra.get("parse_mode", "")

    @property
    def _api(self) -> str:
        return f"{self.API_BASE}/bot{self._bot_token}"

    # ── Message parsing ──

    async def parse_incoming(self, payload: dict) -> Optional[ChannelMessage]:
        """Parse Telegram Update into ChannelMessage."""
        if "message" in payload:
            return self._parse_message(payload["message"])
        elif "callback_query" in payload:
            return self._parse_callback(payload["callback_query"])
        elif "inline_query" in payload:
            return self._parse_inline(payload["inline_query"])
        return None

    def _parse_message(self, msg: dict) -> Optional[ChannelMessage]:
        """Parse a Telegram Message object."""
        chat = msg.get("chat", {})
        user = msg.get("from", {})
        chat_id = str(chat.get("id", ""))
        user_id = str(user.get("id", ""))

        if self._allowed_chats and chat_id not in self._allowed_chats:
            return None

        content = ""
        msg_type = MessageType.TEXT
        metadata = {
            "chat_type": chat.get("type", "private"),
            "chat_title": chat.get("title", ""),
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
        }

        if "text" in msg:
            content = msg["text"]
        elif "photo" in msg:
            content = msg.get("caption", "[Photo]")
            msg_type = MessageType.IMAGE
            metadata["file_id"] = msg["photo"][-1]["file_id"]
        elif "document" in msg:
            content = msg.get("caption", "[Document]")
            msg_type = MessageType.FILE
            metadata["file_id"] = msg["document"]["file_id"]
            metadata["file_name"] = msg["document"].get("file_name", "")
        elif "voice" in msg:
            content = "[Voice message]"
            msg_type = MessageType.VOICE
        elif "video" in msg:
            content = msg.get("caption", "[Video]")
            msg_type = MessageType.VIDEO
        elif "sticker" in msg:
            content = f"[Sticker: {msg['sticker'].get('emoji', '')}]"
            msg_type = MessageType.TEXT
        else:
            return None

        return ChannelMessage(
            channel_type=ChannelType.TELEGRAM,
            channel_id=chat_id,
            user_id=user_id,
            content=content,
            message_type=msg_type,
            raw=msg,
            reply_token=str(msg.get("message_id", "")),
            metadata=metadata,
        )

    def _parse_callback(self, cb: dict) -> Optional[ChannelMessage]:
        """Parse callback query (inline button press)."""
        user = cb.get("from", {})
        msg = cb.get("message", {})
        return ChannelMessage(
            channel_type=ChannelType.TELEGRAM,
            channel_id=str(msg.get("chat", {}).get("id", "")),
            user_id=str(user.get("id", "")),
            content=cb.get("data", ""),
            message_type=MessageType.INTERACTIVE,
            raw=cb,
            reply_token=cb.get("id", ""),
        )

    def _parse_inline(self, inline: dict) -> Optional[ChannelMessage]:
        """Parse inline query."""
        user = inline.get("from", {})
        return ChannelMessage(
            channel_type=ChannelType.TELEGRAM,
            channel_id="inline",
            user_id=str(user.get("id", "")),
            content=inline.get("query", ""),
            message_type=MessageType.COMMAND,
            raw=inline,
            reply_token=inline.get("id", ""),
        )

    # ── Reply ──

    async def reply(self, channel_id: str, content: str, **kwargs) -> ReplyResult:
        """Send message via sendMessage."""
        return await self._api_call("sendMessage", {
            "chat_id": channel_id,
            "text": content,
            "parse_mode": self._parse_mode,
            "reply_to_message_id": kwargs.get("reply_token"),
        })

    async def reply_inline_keyboard(
        self, channel_id: str, text: str,
        buttons: list[list[dict]], **kwargs,
    ) -> ReplyResult:
        """Send message with inline keyboard buttons.

        buttons = [[{"text": "Yes", "callback_data": "yes"}], ...]
        """
        return await self._api_call("sendMessage", {
            "chat_id": channel_id,
            "text": text,
            "parse_mode": self._parse_mode,
            "reply_markup": json.dumps({"inline_keyboard": buttons}),
        })

    async def reply_photo(
        self, channel_id: str, photo_url: str, caption: str = "", **kwargs
    ) -> ReplyResult:
        """Send a photo."""
        return await self._api_call("sendPhoto", {
            "chat_id": channel_id,
            "photo": photo_url,
            "caption": caption,
        })

    async def answer_callback(self, callback_query_id: str, text: str = "") -> ReplyResult:
        """Answer a callback query (dismiss loading spinner)."""
        return await self._api_call("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text": text,
        })

    # ── Internal ──

    async def _api_call(self, method: str, params: dict) -> ReplyResult:
        """Call Telegram Bot API."""
        url = f"{self._api}/{method}"

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return ReplyResult(
                            success=True,
                            message_id=str(data.get("result", {}).get("message_id", "")),
                        )
                    return ReplyResult(
                        success=False,
                        error=data.get("description", "unknown"),
                    )
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                url, data=json.dumps(params).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return ReplyResult(
                    success=data.get("ok", False),
                    message_id=str(data.get("result", {}).get("message_id", "")),
                )

    # ── Webhook ──

    async def set_webhook(self, url: str) -> bool:
        """Register webhook URL with Telegram."""
        result = await self._api_call("setWebhook", {"url": url})
        return result.success

    async def delete_webhook(self) -> bool:
        """Remove webhook (switch to long-polling)."""
        result = await self._api_call("deleteWebhook", {})
        return result.success
