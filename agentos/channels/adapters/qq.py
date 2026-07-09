"""
AgentOS Channels — QQ 机器人适配器。

Webhook 规范: https://bot.q.qq.com/wiki/develop/api-v2/

特性:
  - WebSocket 长连接（QQ 官方推荐） + HTTP webhook 双模式
  - JSON 报文解析
  - Bot Token 管理
  - 主动推送 + 被动回复
"""

from __future__ import annotations

import json
import time

import httpx

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class QQAdapter(BaseChannelAdapter):
    """QQ 机器人适配器。"""

    channel_type = ChannelType.QQ

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._token: str = config.bot_token or ""
        self._token_expires: float = float("inf")  # QQ Bot Token 由配置直接提供

    # ── Webhook ──

    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """QQ Bot 暂不强验证签名。"""
        return True

    def parse_webhook(
        self, raw_body: bytes, headers: dict
    ) -> ChannelMessage | list[ChannelMessage]:
        data = json.loads(raw_body.decode("utf-8"))
        op = data.get("op", 0)
        t = data.get("t", "")
        event_data = data.get("d", {})

        # 处理不同类型的 QQ 事件
        if op == 10:
            # Hello 事件
            return ChannelMessage(
                msg_id="hello",
                channel=ChannelType.QQ,
                msg_type=MessageType.EVENT,
                content="hello",
                extra={"op": 10, "heartbeat_interval": event_data.get("heartbeat_interval", 0)},
            )

        if op == 11:
            # Heartbeat ACK
            return ChannelMessage(
                msg_id="heartbeat_ack",
                channel=ChannelType.QQ,
                msg_type=MessageType.EVENT,
                content="heartbeat_ack",
                extra={"op": 11},
            )

        # op == 0: Dispatch 事件
        msg_map = {
            "AT_MESSAGE_CREATE": "text",
            "MESSAGE_CREATE": "text",
            "DIRECT_MESSAGE_CREATE": "text",
            "C2C_MESSAGE_CREATE": "text",
        }
        msg_type_str = msg_map.get(t, "text")
        msg_type_map = {"text": MessageType.TEXT}
        msg_type = msg_type_map.get(msg_type_str, MessageType.TEXT)

        author = event_data.get("author", {})
        content = event_data.get("content", "").strip()

        # 去掉 @机器人 前缀
        if content.startswith("<@"):
            end = content.find(">")
            if end > 0:
                content = content[end + 1 :].strip()

        return ChannelMessage(
            msg_id=event_data.get("id", ""),
            channel=ChannelType.QQ,
            msg_type=msg_type,
            content=content,
            sender_id=author.get("id", ""),
            sender_name=author.get("username", ""),
            timestamp=float(time.time()),
            conversation_id=event_data.get("channel_id", event_data.get("guild_id", "")),
            reply_token="",
            extra={
                "guild_id": event_data.get("guild_id"),
                "channel_id": event_data.get("channel_id"),
                "member": event_data.get("member"),
                "event_type": t,
                "is_group": bool(event_data.get("guild_id")),
            },
        )

    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        return json.dumps(
            {
                "msg_type": 0,
                "content": reply_text,
                "msg_id": msg.msg_id,
                "message_reference": {"message_id": msg.msg_id},
            }
        )

    # ── 主动推送 ──

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        token = await self.get_access_token()
        # QQ Bot 发消息需要知道 channel_id
        channel_id = self.config.extra.get("channel_id", "")
        if not channel_id:
            return ReplyResult(success=False, error="no channel_id in config")

        url = f"https://api.sgroup.qq.com/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {self.config.app_id}.{token}"}
        payload = {"content": content, "msg_type": 0}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            msg_id = data.get("id", "")
            if msg_id:
                return ReplyResult(success=True, msg_id=msg_id)
            return ReplyResult(success=False, error=f"qq error: {data}")

    async def send_c2c_message(self, user_id: str, content: str) -> ReplyResult:
        """发送私聊消息。"""
        token = await self.get_access_token()
        url = f"https://api.sgroup.qq.com/v2/users/{user_id}/messages"
        headers = {"Authorization": f"Bot {self.config.app_id}.{token}"}
        payload = {"content": content, "msg_type": 0}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            data = resp.json()
            return ReplyResult(success="id" in data, msg_id=data.get("id", ""))

    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        return await self.send_message(user_id, f"[图片] {image_url}")

    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        return await self.send_message(user_id, f"文件: {filename}\n{file_url}")

    # ── Token ──

    async def get_access_token(self) -> str:
        return self._token or self.config.bot_token
