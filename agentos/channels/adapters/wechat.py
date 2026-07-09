"""
AgentOS Channels — 微信公众号适配器。

Webhook 规范: https://developers.weixin.qq.com/doc/offiaccount/Message_Management/Receiving_standard_messages.html

特性:
  - XML 报文解析
  - SHA1 签名验证
  - 被动回复（在 webhook 响应中同步回复）
  - access_token 管理 + 自动续期
  - 主动推送（客服消息接口）
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx

from agentos.channels.base import (
    BaseChannelAdapter,
    ChannelConfig,
    ReplyResult,
)
from agentos.channels.message import ChannelMessage, ChannelType, MessageType


class WeChatAdapter(BaseChannelAdapter):
    """微信公众号适配器。"""

    channel_type = ChannelType.WECHAT_MP

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._token: str = ""
        self._token_expires: float = 0

    # ── Webhook ──

    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """验证微信签名（SHA1）。"""
        params = headers.get("x-wx-params", {})
        if not params:
            return True  # 无签名时放行（开发模式）
        signature = params.get("signature", "")
        timestamp = str(params.get("timestamp", ""))
        nonce = str(params.get("nonce", ""))
        expected = self.make_signature(self.config.verify_token, timestamp, nonce)
        return signature == expected

    def parse_webhook(
        self, raw_body: bytes, headers: dict
    ) -> ChannelMessage | list[ChannelMessage]:
        """解析微信 XML 报文。"""
        root = ET.fromstring(raw_body.decode("utf-8"))

        msg_type_str = self._xml_text(root, "MsgType") or "text"
        msg_type_map = {
            "text": MessageType.TEXT,
            "image": MessageType.IMAGE,
            "voice": MessageType.VOICE,
            "video": MessageType.VIDEO,
            "location": MessageType.LOCATION,
            "link": MessageType.LINK,
            "event": MessageType.EVENT,
        }
        msg_type = msg_type_map.get(msg_type_str, MessageType.TEXT)

        content = ""
        if msg_type_str == "text":
            content = self._xml_text(root, "Content") or ""
        elif msg_type_str == "image":
            content = "[图片]"
        elif msg_type_str == "voice":
            content = self._xml_text(root, "Recognition") or "[语音]"

        return ChannelMessage(
            msg_id=self._xml_text(root, "MsgId") or "",
            channel=ChannelType.WECHAT_MP,
            msg_type=msg_type,
            content=content,
            sender_id=self._xml_text(root, "FromUserName") or "",
            sender_name="",
            timestamp=float(self._xml_text(root, "CreateTime") or time.time()),
            conversation_id=self._xml_text(root, "FromUserName") or "",
            reply_token="",
            media_url=self._xml_text(root, "PicUrl") or self._xml_text(root, "MediaId") or "",
            media_id=self._xml_text(root, "MediaId") or "",
            extra={
                "to_user": self._xml_text(root, "ToUserName"),
                "msg_type_raw": msg_type_str,
                "event": self._xml_text(root, "Event"),
                "event_key": self._xml_text(root, "EventKey"),
            },
        )

    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        """构建微信被动回复 XML。"""
        to_user = msg.extra.get("to_user", msg.sender_id)
        from_user = msg.sender_id
        create_time = int(time.time())
        return (
            "<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{create_time}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{reply_text}]]></Content>"
            "</xml>"
        )

    # ── 主动推送 ──

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        """发送客服消息。"""
        token = await self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "text": {"content": content},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                return ReplyResult(success=True, msg_id=str(data.get("msgid", "")))
            return ReplyResult(
                success=False, error=f"wechat error {data.get('errcode')}: {data.get('errmsg')}"
            )

    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        token = await self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        payload = {
            "touser": user_id,
            "msgtype": "image",
            "image": {"media_id": image_url},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                return ReplyResult(success=True)
            return ReplyResult(success=False, error=str(data))

    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        await self.get_access_token()
        # 先上传临时素材
        async with httpx.AsyncClient():
            # 简化实现：发文本链接
            return await self.send_message(user_id, f"文件: {filename}\n{file_url}")

    # ── Token ──

    async def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 300:
            return self._token

        url = (
            "https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={self.config.app_id}"
            f"&secret={self.config.app_secret}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            data = resp.json()
            if "access_token" in data:
                self._token = data["access_token"]
                self._token_expires = time.time() + data.get("expires_in", 7200)
                return self._token
            raise RuntimeError(f"wechat token error: {data}")

    # ── Helpers ──

    @staticmethod
    def _xml_text(element: ET.Element, tag: str) -> str | None:
        child = element.find(tag)
        return child.text if child is not None else None
