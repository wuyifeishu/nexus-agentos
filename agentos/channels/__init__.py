"""
AgentOS Messaging Channels — Unified multi-channel message gateway.

支持的渠道:
  - wechat-mp   微信公众号
  - wecom       企业微信
  - feishu      飞书
  - dingtalk    钉钉
  - qq          QQ (官方机器人)

架构:
  ChannelMessage (统一消息模型)
      ↓
  BaseChannelAdapter (抽象适配器)
      ↓
  WeChatAdapter / WeComAdapter / FeishuAdapter / DingTalkAdapter / QQAdapter
      ↓
  ChannelRouter (路由 + 会话管理)
      ↓
  Gateway (FastAPI webhook 入口)
      ↓
  Agent Engine (Marvis)
"""

from agentos.channels.base import (
    BaseChannelAdapter,
    ChannelConfig,
    ReplyResult,
)
from agentos.channels.gateway import (
    create_app,
    get_router,
    on_message,
    register_adapter,
)
from agentos.channels.message import (
    ChannelMessage,
    ChannelType,
    ConversationContext,
    MessageType,
)
from agentos.channels.router import ChannelRouter

__all__ = [
    # message
    "ChannelMessage",
    "ChannelType",
    "MessageType",
    "ConversationContext",
    # base
    "BaseChannelAdapter",
    "ChannelConfig",
    "ReplyResult",
    # router
    "ChannelRouter",
    # gateway
    "create_app",
    "on_message",
    "get_router",
    "register_adapter",
]
