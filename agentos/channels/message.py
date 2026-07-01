"""
AgentOS Channels — 统一消息模型与渠道协议。

所有渠道（微信/企业微信/飞书/钉钉/QQ）的消息
均归一化为 ChannelMessage，确保 Agent Engine 零差异处理。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChannelType(str, Enum):
    """渠道类型标识。"""
    WECHAT_MP = "wechat-mp"          # 微信公众号
    WECOM = "wecom"                  # 企业微信
    FEISHU = "feishu"                # 飞书
    DINGTALK = "dingtalk"            # 钉钉
    QQ = "qq"                        # QQ 机器人
    SLACK = "slack"                  # Slack
    DISCORD = "discord"              # Discord
    TELEGRAM = "telegram"            # Telegram
    WHATSAPP = "whatsapp"            # WhatsApp Business
    LINE = "line"                    # LINE Messaging
    WEB = "web"                      # Web 端
    MOBILE = "mobile"                # 移动端


class MessageType(str, Enum):
    """消息类型。"""
    TEXT = "text"                    # 文本
    IMAGE = "image"                  # 图片
    VOICE = "voice"                  # 语音
    VIDEO = "video"                  # 视频
    FILE = "file"                    # 文件
    LOCATION = "location"            # 位置
    LINK = "link"                    # 链接
    EVENT = "event"                  # 事件（关注/点击菜单等）
    MINIPROGRAM = "miniprogram"      # 小程序卡片


@dataclass
class ConversationContext:
    """会话上下文 — 跨渠道统一。"""
    channel: ChannelType
    user_id: str                     # 渠道内用户唯一标识
    session_id: str                  # AgentOS 内会话 ID
    channel_config: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)  # 最近 N 轮对话


@dataclass
class ChannelMessage:
    """统一消息模型 — 所有渠道归一化为此格式。

    设计原则:
      - 字段命名中性，不偏袒任何渠道
      - 渠道特有数据塞入 extra
      - Agent Engine 只看本模型，不感知渠道差异
    """

    msg_id: str                      # 渠道内消息唯一 ID
    channel: ChannelType             # 来源渠道
    msg_type: MessageType = MessageType.TEXT
    content: str = ""                # 文本内容（image/voice 等为 media_url）
    sender_id: str = ""              # 发送者 ID
    sender_name: str = ""            # 发送者昵称
    timestamp: float = field(default_factory=time.time)
    conversation_id: str = ""        # 渠道内会话/群 ID
    reply_token: str = ""            # 渠道回复令牌（用于被动回复）
    session_id: str = ""             # AgentOS 会话 ID
    media_url: str = ""              # 多媒体 URL
    media_id: str = ""               # 渠道媒体 ID（用于下载）
    extra: dict = field(default_factory=dict)  # 渠道特有字段

    @property
    def is_from_mobile(self) -> bool:
        """是否来自移动端渠道。"""
        return self.channel in (ChannelType.MOBILE, ChannelType.WECHAT_MP, ChannelType.QQ)

    @property
    def is_group_chat(self) -> bool:
        """是否群聊消息。"""
        return self.extra.get("is_group", False)

    @property
    def display_source(self) -> str:
        """人类可读的来源标识。"""
        labels = {
            ChannelType.WECHAT_MP: "微信",
            ChannelType.WECOM: "企业微信",
            ChannelType.FEISHU: "飞书",
            ChannelType.DINGTALK: "钉钉",
            ChannelType.QQ: "QQ",
            ChannelType.WEB: "Web",
            ChannelType.MOBILE: "手机",
        }
        return labels.get(self.channel, self.channel.value)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "channel": self.channel.value,
            "msg_type": self.msg_type.value,
            "content": self.content,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "media_url": self.media_url,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelMessage":
        return cls(
            msg_id=d.get("msg_id", ""),
            channel=ChannelType(d.get("channel", "web")),
            msg_type=MessageType(d.get("msg_type", "text")),
            content=d.get("content", ""),
            sender_id=d.get("sender_id", ""),
            sender_name=d.get("sender_name", ""),
            timestamp=d.get("timestamp", time.time()),
            conversation_id=d.get("conversation_id", ""),
            reply_token=d.get("reply_token", ""),
            session_id=d.get("session_id", ""),
            media_url=d.get("media_url", ""),
            media_id=d.get("media_id", ""),
            extra=d.get("extra", {}),
        )
