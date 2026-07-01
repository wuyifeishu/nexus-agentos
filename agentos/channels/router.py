"""
AgentOS Channels — 消息路由引擎。

负责:
  1. 根据 webhook URL 路径匹配目标渠道适配器
  2. 维持渠道适配器实例注册表
  3. 提供统一的 send_message 接口（自动路由到正确渠道）
"""

from __future__ import annotations

import time
from typing import Optional

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, ConversationContext


class ChannelRouter:
    """多渠道路由器 — 注册/查找/分发。

    每个渠道适配器以 webhook_path 或 channel_type 注册。
    收到消息时按 path 匹配 > channel_type 匹配 > 默认适配器的顺序查找。
    """

    def __init__(self):
        self._adapters: dict[str, BaseChannelAdapter] = {}       # webhook_path → adapter
        self._by_channel: dict[ChannelType, BaseChannelAdapter] = {}
        self._default: Optional[BaseChannelAdapter] = None
        self._contexts: dict[str, ConversationContext] = {}      # session_id → context

    # ── 注册 ──

    def register(self, adapter: BaseChannelAdapter, webhook_path: str = "") -> None:
        """注册一个渠道适配器。"""
        channel = adapter.channel_type
        self._by_channel[channel] = adapter
        if webhook_path:
            self._adapters[webhook_path] = adapter
            adapter.config.webhook_path = webhook_path
        if len(self._adapters) == 1:
            self._default = adapter

    def unregister(self, channel: ChannelType) -> None:
        """注销渠道适配器。"""
        adapter = self._by_channel.pop(channel, None)
        if adapter:
            paths_to_remove = [p for p, a in self._adapters.items() if a == adapter]
            for p in paths_to_remove:
                del self._adapters[p]
            if self._default == adapter:
                self._default = next(iter(self._adapters.values()), None)

    # ── 查找 ──

    def find(self, webhook_path: str = "", channel: Optional[ChannelType] = None) -> Optional[BaseChannelAdapter]:
        """按路径或渠道类型查找适配器。"""
        if webhook_path and webhook_path in self._adapters:
            return self._adapters[webhook_path]
        if channel and channel in self._by_channel:
            return self._by_channel[channel]
        return self._default

    def get(self, channel: ChannelType) -> Optional[BaseChannelAdapter]:
        """按渠道类型获取适配器。"""
        return self._by_channel.get(channel)

    # ── 会话管理 ──

    def get_context(self, msg: ChannelMessage) -> ConversationContext:
        """获取或创建会话上下文。"""
        sid = msg.session_id or msg.sender_id
        if sid in self._contexts:
            ctx = self._contexts[sid]
            ctx.history.append({"role": "user", "content": msg.content, "timestamp": msg.timestamp})
            if len(ctx.history) > 50:
                ctx.history = ctx.history[-50:]
            return ctx

        ctx = ConversationContext(
            channel=msg.channel,
            user_id=msg.sender_id,
            session_id=sid,
            channel_config={"conversation_id": msg.conversation_id},
            metadata={"first_message_at": time.time()},
        )
        ctx.history.append({"role": "user", "content": msg.content, "timestamp": msg.timestamp})
        self._contexts[sid] = ctx
        return ctx

    def update_context(self, session_id: str, reply_text: str) -> None:
        """将 Agent 回复记录到会话上下文。"""
        if session_id in self._contexts:
            self._contexts[session_id].history.append({
                "role": "assistant",
                "content": reply_text,
                "timestamp": time.time(),
            })

    # ── 统一发送 ──

    async def send(self, channel: ChannelType, user_id: str, content: str,
                   msg_type: str = "text") -> ReplyResult:
        """统一发送接口 — 自动路由到目标渠道适配器。"""
        adapter = self._by_channel.get(channel)
        if not adapter:
            return ReplyResult(success=False, error=f"No adapter for {channel.value}")
        return await adapter.send_message(user_id, content, msg_type)

    async def broadcast(self, content: str, msg_type: str = "text",
                        exclude: Optional[ChannelType] = None) -> list[ReplyResult]:
        """向所有已注册渠道广播消息。"""
        results = []
        for channel, adapter in self._by_channel.items():
            if channel == exclude:
                continue
            results.append(ReplyResult(success=False, error=f"broadcast to {channel.value} requires explicit user_id"))
        return results

    # ── 状态 ──

    @property
    def active_channels(self) -> list[dict]:
        return [
            {
                "channel": a.channel_type.value,
                "webhook_path": a.config.webhook_path,
                "enabled": a.config.enabled,
            }
            for a in self._by_channel.values()
        ]

    @property
    def active_count(self) -> int:
        return sum(1 for a in self._by_channel.values() if a.config.enabled)
