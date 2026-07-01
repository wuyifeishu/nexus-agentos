"""
Slack Channel Adapter — Slack Events API (Bolt for Python).

OAuth 2.0 flow → Bolt App → Socket Mode / HTTP Webhook → ChannelMessage.
"""

from __future__ import annotations

import json
import hmac
import hashlib
import time
from typing import Optional, Callable, Any

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class SlackAdapter(BaseChannelAdapter):
    """Slack Events API adapter.

    Config fields:
        bot_token: Slack Bot User OAuth Token (xoxb-...)
        signing_secret: Slack Signing Secret for request verification
        app_token: Socket Mode app-level token (xapp-...) — optional
        socket_mode: bool — use Socket Mode instead of HTTP webhooks
    """

    CHANNEL_TYPE = ChannelType.SLACK

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._bot_token = config.extra.get("bot_token", "")
        self._signing_secret = config.extra.get("signing_secret", "")
        self._app_token = config.extra.get("app_token", "")
        self._socket_mode = config.extra.get("socket_mode", False)

    # ── Webhook verification ──

    def verify_signature(self, body: bytes, headers: dict) -> bool:
        """Verify Slack request signature (HMAC-SHA256)."""
        timestamp = headers.get("x-slack-request-timestamp", "")
        slack_sig = headers.get("x-slack-signature", "")

        if abs(time.time() - int(timestamp)) > 300:
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode()}"
        computed = "v0=" + hmac.new(
            self._signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, slack_sig)

    # ── Message parsing ──

    async def parse_incoming(self, payload: dict) -> Optional[ChannelMessage]:
        """Parse a Slack event payload into ChannelMessage."""
        event_type = payload.get("type", "")

        # URL verification challenge
        if event_type == "url_verification":
            return ChannelMessage(
                channel_type=ChannelType.SLACK,
                channel_id=self.config.channel_id,
                user_id="system",
                content=payload.get("challenge", ""),
                message_type=MessageType.SYSTEM,
                raw=payload,
                reply_token=payload.get("challenge"),
            )

        # Event callback
        if event_type == "event_callback":
            event = payload.get("event", {})
            return self._parse_event(event)

        return None

    def _parse_event(self, event: dict) -> Optional[ChannelMessage]:
        """Parse a Slack event (message, app_mention, etc.)."""
        event_type = event.get("type", "")
        user = event.get("user", "")
        channel = event.get("channel", "")
        text = event.get("text", "")
        ts = event.get("ts", "")

        # Strip bot mention prefix
        if event_type == "app_mention" and text:
            text = self._strip_mention(text)

        if not text:
            return None

        msg_type = MessageType.TEXT
        return ChannelMessage(
            channel_type=ChannelType.SLACK,
            channel_id=channel,
            user_id=user,
            content=text,
            message_type=msg_type,
            raw=event,
            reply_token=ts,
        )

    def _strip_mention(self, text: str) -> str:
        """Remove <@BOT_ID> prefix from message text."""
        import re
        return re.sub(r"^<@U[A-Z0-9]+>\s*", "", text).strip()

    # ── Reply ──

    async def reply(self, channel_id: str, content: str, **kwargs) -> ReplyResult:
        """Send a message to Slack channel via chat.postMessage."""
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json",
        }
        body = {
            "channel": channel_id,
            "text": content,
        }

        thread_ts = kwargs.get("thread_ts") or kwargs.get("reply_token")
        if thread_ts:
            body["thread_ts"] = thread_ts

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return ReplyResult(success=True, message_id=data.get("ts", ""))
                    return ReplyResult(success=False, error=data.get("error", "unknown"))
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(), headers=headers
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return ReplyResult(success=data.get("ok", False), message_id=data.get("ts", ""))

    async def reply_blocks(
        self, channel_id: str, blocks: list[dict], **kwargs
    ) -> ReplyResult:
        """Send Slack Block Kit message."""
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json",
        }
        body = {"channel": channel_id, "blocks": blocks}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json()
                    return ReplyResult(success=data.get("ok", False), message_id=data.get("ts", ""))
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(), headers=headers
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                return ReplyResult(success=data.get("ok", False), message_id=data.get("ts", ""))
