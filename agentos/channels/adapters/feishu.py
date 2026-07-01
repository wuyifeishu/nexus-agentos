"""
AgentOS Channels — 飞书适配器。

Webhook 规范: https://open.feishu.cn/document/server-docs/im-v1/message-content-description

特性:
  - JSON 报文解析
  - 应用 Token + tenant access token 双 token 管理
  - 卡片消息支持
  - 消息回复（被动 + 主动）
"""

from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class FeishuAdapter(BaseChannelAdapter):
    """飞书适配器。"""

    channel_type = ChannelType.FEISHU

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._app_token: str = ""
        self._tenant_token: str = ""
        self._token_expires: float = 0

    # ── Webhook ──

    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """飞书不要求 webhook 签名验证（在事件订阅 URL 验证时完成）。"""
        return True

    def parse_webhook(self, raw_body: bytes, headers: dict) -> ChannelMessage | list[ChannelMessage]:
        data = json.loads(raw_body.decode("utf-8"))
        # 飞书事件格式: {"schema": "2.0", "header": {...}, "event": {...}}
        event = data.get("event", data)
        header = data.get("header", {})

        # 处理 URL 验证
        if data.get("type") == "url_verification":
            return ChannelMessage(
                msg_id="url_verify",
                channel=ChannelType.FEISHU,
                msg_type=MessageType.EVENT,
                content=data.get("challenge", ""),
                reply_token=data.get("token", ""),
                extra={"is_challenge": True, "challenge": data.get("challenge", "")},
            )

        msg_type_str = event.get("message", {}).get("message_type", "text")
        msg_type_map = {
            "text": MessageType.TEXT, "image": MessageType.IMAGE,
            "audio": MessageType.VOICE, "media": MessageType.FILE,
            "file": MessageType.FILE, "post": MessageType.TEXT,
        }
        msg_type = msg_type_map.get(msg_type_str, MessageType.TEXT)

        message = event.get("message", {})
        content = ""
        if msg_type_str == "text":
            content = json.loads(message.get("content", "{}")).get("text", "")
        elif msg_type_str == "post":
            content = str(message.get("content", ""))[:200]

        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        return ChannelMessage(
            msg_id=header.get("event_id", event.get("message", {}).get("message_id", "")),
            channel=ChannelType.FEISHU,
            msg_type=msg_type,
            content=content,
            sender_id=sender_id,
            sender_name="",
            timestamp=float(header.get("create_time", str(int(time.time() * 1000)))) / 1000,
            conversation_id=event.get("message", {}).get("chat_id", ""),
            reply_token=event.get("message", {}).get("message_id", ""),
            media_url=message.get("image_key", ""),
            extra={
                "tenant_key": header.get("tenant_key"),
                "event_type": header.get("event_type"),
                "chat_type": event.get("message", {}).get("chat_type", "p2p"),
                "root_id": event.get("message", {}).get("root_id"),
                "parent_id": event.get("message", {}).get("parent_id"),
            },
        )

    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        return json.dumps({
            "msg_type": "text",
            "content": json.dumps({"text": reply_text}),
        })

    # ── 主动推送 ──

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        token = await self.get_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        payload = {
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params={"receive_id_type": "open_id"}, json=payload, headers=headers, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                return ReplyResult(success=True, msg_id=data.get("data", {}).get("message_id", ""))
            return ReplyResult(success=False, error=f"feishu error {data.get('code')}: {data.get('msg')}")

    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        token = await self.get_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        payload = {
            "receive_id": user_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_url}),
        }
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params={"receive_id_type": "open_id"}, json=payload, headers=headers, timeout=10)
            return ReplyResult(success=resp.json().get("code") == 0)

    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        token = await self.get_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        payload = {
            "receive_id": user_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_url}),
        }
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params={"receive_id_type": "open_id"}, json=payload, headers=headers, timeout=10)
            return ReplyResult(success=resp.json().get("code") == 0)

    # ── Token ──

    async def get_access_token(self) -> str:
        if self._tenant_token and time.time() < self._token_expires - 300:
            return self._tenant_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()
            self._tenant_token = data["tenant_access_token"]
            self._token_expires = time.time() + data.get("expire", 7200)
            return self._tenant_token
