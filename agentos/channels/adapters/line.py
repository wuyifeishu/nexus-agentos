"""
LINE Channel Adapter — LINE Messaging API.

LINE Developers Console → Channel Access Token + Channel Secret → webhook → ChannelMessage.
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
from typing import Optional

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class LINEAdapter(BaseChannelAdapter):
    """LINE Messaging API adapter.

    Config fields:
        channel_access_token: LINE channel access token (long-lived)
        channel_secret: LINE channel secret (for signature verification)
        reply_retry_limit: max reply attempts (default 1)
    """

    CHANNEL_TYPE = ChannelType.LINE
    API_BASE = "https://api.line.me/v2"
    API_DATA = "https://api-data.line.me/v2"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._access_token = config.extra.get("channel_access_token", "")
        self._channel_secret = config.extra.get("channel_secret", "")
        self._retry_limit = config.extra.get("reply_retry_limit", 1)

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    # ── Signature verification ──

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify LINE webhook signature (HMAC-SHA256 base64)."""
        computed = base64.b64encode(
            hmac.new(
                self._channel_secret.encode(),
                body,
                hashlib.sha256,
            ).digest()
        ).decode()
        return hmac.compare_digest(computed, signature)

    # ── Message parsing ──

    async def parse_incoming(self, payload: dict) -> Optional[ChannelMessage]:
        """Parse LINE webhook events into ChannelMessage."""
        events = payload.get("events", [])
        if not events:
            return None

        event = events[0]
        event_type = event.get("type", "")

        if event_type == "message":
            return self._parse_message(event)
        elif event_type == "postback":
            return self._parse_postback(event)
        elif event_type == "follow":
            return self._parse_follow(event)
        elif event_type == "unfollow":
            return ChannelMessage(
                channel_type=ChannelType.LINE,
                channel_id=event.get("source", {}).get("userId", ""),
                user_id=event.get("source", {}).get("userId", ""),
                content="unfollow",
                message_type=MessageType.SYSTEM,
                raw=event,
            )

        return None

    def _parse_message(self, event: dict) -> Optional[ChannelMessage]:
        """Parse a LINE message event."""
        source = event.get("source", {})
        user_id = source.get("userId", "")
        group_id = source.get("groupId", "")
        room_id = source.get("roomId", "")
        channel_id = group_id or room_id or user_id

        msg = event.get("message", {})
        msg_type = msg.get("type", "text")

        content = ""
        mtype = MessageType.TEXT
        metadata = {
            "source_type": source.get("type", "user"),
            "group_id": group_id,
            "room_id": room_id,
            "display_name": "",  # Filled via profile API if needed
        }

        if msg_type == "text":
            content = msg.get("text", "")
        elif msg_type == "image":
            content = "[Image]"
            mtype = MessageType.IMAGE
            metadata["message_id"] = msg.get("id", "")
        elif msg_type == "video":
            content = "[Video]"
            mtype = MessageType.VIDEO
        elif msg_type == "audio":
            content = "[Voice message]"
            mtype = MessageType.VOICE
        elif msg_type == "file":
            content = f"[File: {msg.get('fileName', 'unknown')}]"
            mtype = MessageType.FILE
            metadata["file_name"] = msg.get("fileName", "")
            metadata["file_size"] = msg.get("fileSize", 0)
        elif msg_type == "location":
            content = f"[Location: {msg.get('title', '')} {msg.get('address', '')}]"
            mtype = MessageType.LOCATION
        elif msg_type == "sticker":
            content = f"[Sticker: {msg.get('packageId')}/{msg.get('stickerId')}]"
        else:
            content = f"[{msg_type}]"

        return ChannelMessage(
            channel_type=ChannelType.LINE,
            channel_id=channel_id,
            user_id=user_id,
            content=content,
            message_type=mtype,
            raw=event,
            reply_token=event.get("replyToken", ""),
            metadata=metadata,
        )

    def _parse_postback(self, event: dict) -> Optional[ChannelMessage]:
        """Parse LINE postback event (rich menu, button tap)."""
        source = event.get("source", {})
        data = event.get("postback", {}).get("data", "")
        params = event.get("postback", {}).get("params", {})

        return ChannelMessage(
            channel_type=ChannelType.LINE,
            channel_id=source.get("userId", ""),
            user_id=source.get("userId", ""),
            content=data,
            message_type=MessageType.INTERACTIVE,
            raw=event,
            reply_token=event.get("replyToken", ""),
            metadata={"postback_params": params},
        )

    def _parse_follow(self, event: dict) -> ChannelMessage:
        """Parse LINE follow event."""
        source = event.get("source", {})
        return ChannelMessage(
            channel_type=ChannelType.LINE,
            channel_id=source.get("userId", ""),
            user_id=source.get("userId", ""),
            content="follow",
            message_type=MessageType.SYSTEM,
            raw=event,
        )

    # ── Reply ──

    async def reply(self, channel_id: str, content: str, **kwargs) -> ReplyResult:
        """Send a reply text message."""
        reply_token = kwargs.get("reply_token", "")
        if not reply_token:
            return ReplyResult(success=False, error="reply_token required")

        return await self._api_reply(reply_token, [
            {"type": "text", "text": content[:5000]},
        ])

    async def reply_flex(
        self, channel_id: str, alt_text: str,
        contents: dict, **kwargs,
    ) -> ReplyResult:
        """Send a LINE Flex Message (bubble/carousel)."""
        reply_token = kwargs.get("reply_token", "")
        if not reply_token:
            return ReplyResult(success=False, error="reply_token required")

        return await self._api_reply(reply_token, [
            {"type": "flex", "altText": alt_text, "contents": contents},
        ])

    async def reply_quick_reply(
        self, channel_id: str, text: str,
        items: list[dict], **kwargs,
    ) -> ReplyResult:
        """Send text with quick reply buttons.

        items = [{"type": "action", "action": {"type": "message", "label": "Yes", "text": "Yes"}}, ...]
        """
        reply_token = kwargs.get("reply_token", "")
        if not reply_token:
            return ReplyResult(success=False, error="reply_token required")

        return await self._api_reply(reply_token, [
            {
                "type": "text",
                "text": text[:5000],
                "quickReply": {"items": items[:13]},
            },
        ])

    async def push_message(
        self, user_id: str, messages: list[dict],
    ) -> ReplyResult:
        """Push a message to a user (outside reply window)."""
        return await self._api_push(user_id, messages)

    async def multicast(
        self, user_ids: list[str], messages: list[dict],
    ) -> ReplyResult:
        """Send the same message to up to 500 users."""
        return await self._api_call(
            f"{self.API_BASE}/bot/message/multicast",
            {"to": user_ids[:500], "messages": messages},
            method="POST",
        )

    # ── Profile ──

    async def get_profile(self, user_id: str) -> Optional[dict]:
        """Get LINE user profile."""
        result = await self._api_call(
            f"{self.API_BASE}/bot/profile/{user_id}",
            method="GET",
        )
        if result.success:
            return result.raw
        return None

    # ── Rich Menu ──

    async def set_default_rich_menu(self, rich_menu_id: str) -> bool:
        """Set the default rich menu for all users."""
        result = await self._api_call(
            f"{self.API_BASE}/bot/user/all/richmenu/{rich_menu_id}",
            method="POST",
        )
        return result.success

    # ── Internal API ──

    async def _api_reply(self, reply_token: str, messages: list) -> ReplyResult:
        """Send a reply via reply API."""
        return await self._api_call(
            f"{self.API_BASE}/bot/message/reply",
            {"replyToken": reply_token, "messages": messages},
            method="POST",
        )

    async def _api_push(self, user_id: str, messages: list) -> ReplyResult:
        """Send a push message."""
        return await self._api_call(
            f"{self.API_BASE}/bot/message/push",
            {"to": user_id, "messages": messages},
            method="POST",
        )

    async def _api_call(
        self, url: str, body: dict = None, method: str = "POST",
    ) -> ReplyResult:
        """Generic LINE API call."""
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=headers) as resp:
                        data = await resp.json()
                        return ReplyResult(success=True, raw=data)
                else:
                    async with session.post(url, headers=headers, json=body) as resp:
                        data = await resp.json()
                        if resp.status == 200:
                            return ReplyResult(success=True, message_id="ok", raw=data)
                        return ReplyResult(
                            success=False,
                            error=data.get("message", "unknown"),
                        )
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode() if body else None,
                headers=headers,
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return ReplyResult(success=True, message_id="ok", raw=data)
