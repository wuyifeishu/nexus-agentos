"""
WhatsApp Channel Adapter — WhatsApp Business Cloud API.

Meta Developer App → Phone Number ID + Access Token → webhook → ChannelMessage.
"""

from __future__ import annotations

import json

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class WhatsAppAdapter(BaseChannelAdapter):
    """WhatsApp Business Cloud API adapter.

    Config fields:
        access_token: Meta permanent page access token
        phone_number_id: WhatsApp Business phone number ID
        verify_token: Webhook verify token (for Meta handshake)
        app_secret: Meta App secret (for payload signing, optional)
        business_id: WhatsApp Business Account ID
    """

    CHANNEL_TYPE = ChannelType.WHATSAPP
    API_BASE = "https://graph.facebook.com/v19.0"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._access_token = config.extra.get("access_token", "")
        self._phone_number_id = config.extra.get("phone_number_id", "")
        self._verify_token = config.extra.get("verify_token", "")
        self._app_secret = config.extra.get("app_secret", "")
        self._business_id = config.extra.get("business_id", "")

    # ── Webhook verification ──

    def verify_webhook(self, query_params: dict) -> tuple[bool, str]:
        """Handle Meta webhook verification challenge.

        Returns (verified, challenge_token).
        """
        mode = query_params.get("hub.mode", "")
        token = query_params.get("hub.verify_token", "")
        challenge = query_params.get("hub.challenge", "")

        if mode == "subscribe" and token == self._verify_token:
            return True, challenge
        return False, ""

    # ── Message parsing ──

    async def parse_incoming(self, payload: dict) -> ChannelMessage | None:
        """Parse WhatsApp webhook payload into ChannelMessage."""
        entries = payload.get("entry", [])

        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # Messages
                messages = value.get("messages", [])
                for msg in messages:
                    return self._parse_message(msg, value)

                # Status updates
                statuses = value.get("statuses", [])
                for status in statuses:
                    return ChannelMessage(
                        channel_type=ChannelType.WHATSAPP,
                        channel_id=status.get("recipient_id", ""),
                        user_id=status.get("recipient_id", ""),
                        content=f"Message status: {status.get('status', 'unknown')}",
                        message_type=MessageType.SYSTEM,
                        raw=status,
                        metadata={"status": status.get("status")},
                    )

        return None

    def _parse_message(self, msg: dict, value: dict) -> ChannelMessage | None:
        """Parse a WhatsApp message object."""
        msg_type = msg.get("type", "text")
        user_phone = msg.get("from", "")
        msg_id = msg.get("id", "")

        content = ""
        mtype = MessageType.TEXT
        metadata = {
            "phone": user_phone,
            "display_name": value.get("contacts", [{}])[0].get("profile", {}).get("name", ""),
        }

        if msg_type == "text":
            content = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            content = msg.get("image", {}).get("caption", "[Image]")
            mtype = MessageType.IMAGE
            metadata["media_id"] = msg.get("image", {}).get("id", "")
        elif msg_type == "audio":
            content = "[Voice message]"
            mtype = MessageType.VOICE
            metadata["media_id"] = msg.get("audio", {}).get("id", "")
        elif msg_type == "video":
            content = msg.get("video", {}).get("caption", "[Video]")
            mtype = MessageType.VIDEO
        elif msg_type == "document":
            content = msg.get("document", {}).get("caption", "[Document]")
            mtype = MessageType.FILE
            metadata["file_name"] = msg.get("document", {}).get("filename", "")
        elif msg_type == "location":
            loc = msg.get("location", {})
            content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
            mtype = MessageType.LOCATION
        elif msg_type == "button":
            content = msg.get("button", {}).get("text", "")
            mtype = MessageType.INTERACTIVE
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                content = interactive.get("button_reply", {}).get("id", "")
            else:
                content = interactive.get("list_reply", {}).get("id", "")
            mtype = MessageType.INTERACTIVE
        else:
            content = f"[{msg_type}]"

        return ChannelMessage(
            channel_type=ChannelType.WHATSAPP,
            channel_id=user_phone,
            user_id=user_phone,
            content=content,
            message_type=mtype,
            raw=msg,
            reply_token=msg_id,
            metadata=metadata,
        )

    # ── Reply ──

    async def reply(self, channel_id: str, content: str, **kwargs) -> ReplyResult:
        """Send a text message via WhatsApp Cloud API."""
        return await self._send_msg(
            channel_id,
            {
                "type": "text",
                "text": {"body": content, "preview_url": False},
            },
        )

    async def reply_template(
        self,
        channel_id: str,
        template_name: str,
        language_code: str = "en",
        components: list = None,
        **kwargs,
    ) -> ReplyResult:
        """Send a WhatsApp message template."""
        body = {
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            body["template"]["components"] = components
        return await self._send_msg(channel_id, body)

    async def reply_interactive(
        self,
        channel_id: str,
        body_text: str,
        buttons: list[dict],
        **kwargs,
    ) -> ReplyResult:
        """Send an interactive message with reply buttons.

        buttons = [{"id": "yes", "title": "Yes"}, ...]
        """
        button_list = [
            {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons[:3]
        ]
        return await self._send_msg(
            channel_id,
            {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {"buttons": button_list},
                },
            },
        )

    async def reply_image(
        self, channel_id: str, image_url: str, caption: str = "", **kwargs
    ) -> ReplyResult:
        """Send an image."""
        return await self._send_msg(
            channel_id,
            {
                "type": "image",
                "image": {"link": image_url, "caption": caption},
            },
        )

    # ── API Helper ──

    async def _send_msg(self, to: str, msg_data: dict) -> ReplyResult:
        """Send message via WhatsApp Cloud API."""
        url = f"{self.API_BASE}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            **msg_data,
        }

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json()
                    wa_id = data.get("messages", [{}])[0].get("id", "")
                    if wa_id:
                        return ReplyResult(success=True, message_id=wa_id)
                    return ReplyResult(
                        success=False,
                        error=data.get("error", {}).get("message", "unknown"),
                    )
        except ImportError:
            import urllib.request

            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                wa_id = data.get("messages", [{}])[0].get("id", "")
                return ReplyResult(success=True, message_id=wa_id)

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        url = f"{self.API_BASE}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    return resp.status == 200
        except ImportError:
            import urllib.request

            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req) as resp:
                return resp.status == 200
