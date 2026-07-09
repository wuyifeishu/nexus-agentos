"""
四级上下文压缩 — Claude Code核心工程洞察。
基因来源: Claude Code的s06 Context Compression
"""

from __future__ import annotations

from agentos.core.context import AgentContext, Message


class ContextCompressor:
    """
    四级上下文压缩 — 不是一刀切截断，而是分层渐进式压缩。

    L1 滑动窗口: 保留最近N轮对话
    L2 工具结果摘要: 长输出→结构化摘要
    L3 语义压缩: LLM压缩历史并保留关键信息
    L4 文件系统卸载: 关键信息写入磁盘按需读取
    """

    def __init__(
        self,
        window_size: int = 50,
        max_tool_output_chars: int = 2000,
        target_tokens: int = 100_000,
    ):
        self.window_size = window_size
        self.max_tool_output_chars = max_tool_output_chars
        self.target_tokens = target_tokens

    def compress(self, context: AgentContext) -> AgentContext:
        """渐进式压缩上下文到合理大小。"""

        # L1: 滑动窗口
        if len(context.messages) > self.window_size:
            context.messages = self._apply_sliding_window(context.messages)

        # L2: 工具结果摘要
        context.messages = self._summarize_tool_outputs(context.messages)

        # L3: 语义压缩（需要调用LLM，留接口）
        if self._estimate_tokens(context) > self.target_tokens:
            context = self._semantic_compress_stub(context)

        return context

    def _apply_sliding_window(self, messages: list[Message]) -> list[Message]:
        """L1: 保留system消息 + 最近N条消息。"""
        system_msgs = [m for m in messages if m.role == "system"]
        others = [m for m in messages if m.role != "system"]
        return system_msgs + others[-self.window_size :]

    def _summarize_tool_outputs(self, messages: list[Message]) -> list[Message]:
        """L2: 截断过长的工具输出。"""
        for msg in messages:
            if msg.role == "tool" and len(msg.content) > self.max_tool_output_chars:
                truncated = msg.content[: self.max_tool_output_chars]
                msg.content = (
                    truncated
                    + f"\n... [truncated {len(msg.content) - self.max_tool_output_chars} chars]"
                )
        return messages

    def _semantic_compress_stub(self, context: AgentContext) -> AgentContext:
        """L3: 语义压缩（当前为stub，实际使用时需调用轻量模型）。"""
        # TODO: 调用轻量模型压缩历史消息
        return context

    def _estimate_tokens(self, context: AgentContext) -> int:
        """粗略估算token数。"""
        total = 0
        for msg in context.messages:
            total += len(msg.content) // 4
        return total
