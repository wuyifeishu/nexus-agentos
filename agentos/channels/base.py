"""
AgentOS Channels — 基础适配器协议。

所有渠道适配器均实现本协议，确保 MessageGateway 零差异调用。
"""

from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agentos.channels.message import ChannelMessage, ChannelType


@dataclass
class ChannelConfig:
    """渠道配置。"""

    channel: ChannelType
    enabled: bool = False
    webhook_path: str = ""  # 接收 webhook 的 URL 路径
    webhook_port: int = 8080
    verify_token: str = ""  # 签名校验 token
    app_id: str = ""
    app_secret: str = ""
    encoding_aes_key: str = ""  # 加解密 key（微信系）
    corp_id: str = ""
    agent_id: str = ""
    bot_app_id: str = ""
    bot_token: str = ""
    bot_secret: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel.value,
            "enabled": self.enabled,
            "webhook_path": self.webhook_path,
            "webhook_port": self.webhook_port,
            "app_id": self.app_id,
        }


@dataclass
class ReplyResult:
    """回复结果。"""

    success: bool
    msg_id: str = ""
    error: str = ""


CallbackType = Callable[[ChannelMessage], Awaitable[str | None]]
"""消息回调: 接收 ChannelMessage，返回可选的同步回复文本。"""


class BaseChannelAdapter(ABC):
    """渠道适配器基类。

    每个渠道适配器负责:
      1. 接收 webhook → 验证签名 → 解析为 ChannelMessage
      2. 将 Agent Engine 的回复发送回渠道
      3. Token 管理与自动续期
    """

    channel_type: ChannelType
    config: ChannelConfig
    _on_message: CallbackType | None = None

    def __init__(self, config: ChannelConfig):
        self.config = config

    def set_callback(self, cb: CallbackType):
        """设置收到消息时的回调。"""
        self._on_message = cb

    # ── Webhook 入口 ──

    @abstractmethod
    def verify_signature(self, raw_body: bytes, headers: dict) -> bool:
        """验证 webhook 签名。返回 True 表示验证通过。"""
        ...

    @abstractmethod
    def parse_webhook(
        self, raw_body: bytes, headers: dict
    ) -> ChannelMessage | list[ChannelMessage]:
        """解析 webhook 原始报文为 ChannelMessage(s)。"""
        ...

    # ── 被动回复（同步，在 webhook 响应中返回）──

    @abstractmethod
    def build_reply(self, msg: ChannelMessage, reply_text: str) -> str:
        """构建被动回复报文（xml/json）。"""
        ...

    # ── 主动推送（异步，通过 API 发送）──

    @abstractmethod
    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> ReplyResult:
        """主动推送消息到用户。"""
        ...

    @abstractmethod
    async def send_image(self, user_id: str, image_url: str) -> ReplyResult:
        """推送图片。"""
        ...

    @abstractmethod
    async def send_file(self, user_id: str, file_url: str, filename: str) -> ReplyResult:
        """推送文件。"""
        ...

    # ── Token 管理 ──

    @abstractmethod
    async def get_access_token(self) -> str:
        """获取/刷新 access_token。"""
        ...

    # ── 工具方法 ──

    @staticmethod
    def make_signature(token: str, timestamp: str, nonce: str, *args: str) -> str:
        """通用签名算法（微信/企微/飞书/钉钉均适用）。"""
        parts = sorted([token, timestamp, nonce] + list(args))
        return hashlib.sha1("".join(parts).encode()).hexdigest()

    @staticmethod
    def hmac_sha256(key: str, data: str) -> str:
        return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()
