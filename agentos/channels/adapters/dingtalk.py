"""
AgentOS Channels — 钉钉适配器。

Webhook 规范: https://open.dingtalk.com/document/orgapp/receive-message

特性:
  - JSON 报文解析
  - 签名验证（timestamp + sign）
  - access_token 管理
  - 主动推送（工作通知 + 群机器人）
"""

from __future__ import annotations

import json
import time

import httpx

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class DingTalkAdapter(BaseChannelAdapter):
    """钉钉适配器。"""

    channel_type = ChannelType.DINGTALK

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._token: str = ""
        self._token_expires: float = 0

    # ── Webhook ──

    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """验证钉钉签名（timestamp + sign SHA256）。"""
        params = headers.get("x-ding-params", {})
        timestamp = params.get("timestamp", "")
        sign = params.get("sign", "")
        if not sign:
            return True
        computed = self.hmac_sha256(timestamp, self.config.app_secret)
        return computed == sign

    def parse_webhook(
        self, raw_body: bytes, headers: dict
    ) -> ChannelMessage | list[ChannelMessage]:
        data = json.loads(raw_body.decode("utf-8"))
        msg_type_str = data.get("msgtype", "text")
        msg_type_map = {
            "text": MessageType.TEXT,
            "image": MessageType.IMAGE,
            "voice": MessageType.VOICE,
            "video": MessageType.VIDEO,
            "file": MessageType.FILE,
            "link": MessageType.LINK,
        }
        msg_type = msg_type_map.get(msg_type_str, MessageType.TEXT)

        content = ""
        if msg_type_str == "text":
            content = data.get("text", {}).get("content", "")
        elif msg_type_str == "image":
            content = "[图片]"

        return ChannelMessage(
            msg_id=data.get("msgId", data.get("msgid", "")),
            channel=ChannelType.DINGTALK,
            msg_type=msg_type,
            content=content,
            sender_id=data.get("senderStaffId", data.get("senderId", "")),
            sender_name=data.get("senderNick", ""),
            timestamp=float(data.get("createAt", time.time() * 1000)) / 1000,
            conversation_id=data.get("sessionWebhook", ""),
            reply_token="",
            media_url=data.get("image", {}).get("picUrl", ""),
            media_id=data.get("image", {}).get("mediaId", ""),
            extra={
                "robot_code": data.get("robotCode"),
                "chatbot_user_id": data.get("chatbotUserId"),
                "chat_id": data.get("chatId"),
                "is_admin": data.get("isAdmin", False),
                "conversation_type": data.get("conversationType"),
                "at_users": data.get("atUsers", []),
            },
        )

    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        return json.dumps({"msgtype": "text", "text": {"content": reply_text}})

    # ── 主动推送 ──

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        token = await self.get_access_token()
        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        payload = {
            "robotCode": self.config.app_id,
            "userIds": [user_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": content}),
        }
        headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            return ReplyResult(success=resp.status_code == 200, msg_id=str(time.time()))

    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        return await self.send_message(user_id, f"[图片] {image_url}")

    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        return await self.send_message(user_id, f"文件: {filename}\n{file_url}")

    # ── Token ──

    async def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 300:
            return self._token
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        payload = {"appKey": self.config.app_id, "appSecret": self.config.app_secret}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()
            self._token = data["accessToken"]
            self._token_expires = time.time() + data.get("expireIn", 7200)
            return self._token
