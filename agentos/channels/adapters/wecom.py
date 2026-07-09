"""
AgentOS Channels — 企业微信适配器。

Webhook 规范: https://developer.work.weixin.qq.com/document/path/90238

特性:
  - XML/JSON 双报文解析
  - SHA1 签名验证
  - 被动回复 + 主动群机器人 webhook 推送
  - access_token 自动续期
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET

import httpx

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class WeComAdapter(BaseChannelAdapter):
    """企业微信适配器。"""

    channel_type = ChannelType.WECOM

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._token: str = ""
        self._token_expires: float = 0

    # ── Webhook ──

    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """验证企微签名。"""
        params = headers.get("x-wx-params", {})
        msg_signature = params.get("msg_signature", "")
        timestamp = str(params.get("timestamp", ""))
        nonce = str(params.get("nonce", ""))
        signature = self.make_signature(self.config.verify_token, timestamp, nonce, "")
        return msg_signature == signature

    def parse_webhook(
        self, raw_body: bytes, headers: dict
    ) -> ChannelMessage | list[ChannelMessage]:
        text = raw_body.decode("utf-8")
        data = json.loads(text) if text.strip().startswith("{") else self._parse_xml(text)
        msg_type_str = data.get("MsgType", data.get("msgtype", "text"))
        msg_type_map = {
            "text": MessageType.TEXT,
            "image": MessageType.IMAGE,
            "voice": MessageType.VOICE,
            "video": MessageType.VIDEO,
            "file": MessageType.FILE,
            "event": MessageType.EVENT,
        }
        msg_type = msg_type_map.get(msg_type_str, MessageType.TEXT)
        content = ""
        if msg_type_str == "text":
            content = data.get("Content", data.get("text", {}).get("content", ""))
        elif msg_type_str == "image":
            content = "[图片]"

        return ChannelMessage(
            msg_id=data.get("MsgId", "") or "",
            channel=ChannelType.WECOM,
            msg_type=msg_type,
            content=content,
            sender_id=data.get("FromUserName", data.get("UserID", "")),
            sender_name=data.get("Name", ""),
            timestamp=float(data.get("CreateTime", time.time())),
            conversation_id=data.get("ChatId", data.get("FromUserName", "")),
            media_url=data.get("PicUrl", ""),
            media_id=data.get("MediaId", ""),
            extra={
                "to_user": data.get("ToUserName"),
                "agent_id": data.get("AgentID"),
                "msg_type_raw": msg_type_str,
                "webhook_url": data.get("WebhookUrl", ""),
                "chat_type": data.get("ChatType", "single"),
            },
        )

    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        if msg.extra.get("webhook_url"):
            return json.dumps({"msgtype": "text", "text": {"content": reply_text}})
        to_user = msg.extra.get("to_user", msg.sender_id)
        create_time = int(time.time())
        return (
            "<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{msg.sender_id}]]></FromUserName>"
            f"<CreateTime>{create_time}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{reply_text}]]></Content>"
            "</xml>"
        )

    # ── 主动推送（群机器人 webhook 或应用消息）──

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        # 如果有 webhook_url 则走群机器人推送
        webhook_url = self.config.extra.get("webhook_url", "")
        if webhook_url:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    webhook_url,
                    json={
                        "msgtype": "text",
                        "text": {"content": content},
                    },
                    timeout=10,
                )
                return ReplyResult(success=resp.status_code == 200)

        token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(self.config.agent_id or 0),
            "text": {"content": content},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                return ReplyResult(success=True, msg_id=data.get("msgid", ""))
            return ReplyResult(
                success=False, error=f"wecom error {data.get('errcode')}: {data.get('errmsg')}"
            )

    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "image",
            "agentid": int(self.config.agent_id or 0),
            "image": {"media_id": image_url},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            return ReplyResult(success=resp.json().get("errcode") == 0)

    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        token = await self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "file",
            "agentid": int(self.config.agent_id or 0),
            "file": {"media_id": file_url},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            return ReplyResult(success=resp.json().get("errcode") == 0)

    # ── Token ──

    async def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 300:
            return self._token
        url = (
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={self.config.corp_id}"
            f"&corpsecret={self.config.app_secret}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 7200)
            return self._token

    @staticmethod
    def _parse_xml(xml_str: str) -> dict:
        root = ET.fromstring(xml_str)
        return {child.tag: child.text for child in root}
