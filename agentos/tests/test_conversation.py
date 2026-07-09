"""Tests for agentos.conversation.conversation."""

from __future__ import annotations

import pytest

from agentos.conversation.conversation import (
    ConversationConfig,
    ConversationManager,
    MessageRole,
    TrimStrategy,
)


@pytest.fixture
def conv():
    return ConversationManager(ConversationConfig(max_messages=10, max_tokens=100000))


def test_add_message(conv):
    """添加单条消息。"""
    msg = conv.add("user", "Hello")
    assert msg.role == MessageRole.USER
    assert msg.content == "Hello"
    assert conv.message_count == 1


def test_add_many(conv):
    """批量添加消息。"""
    msgs = conv.add_many([("user", "Hi"), ("assistant", "Hello there")])
    assert len(msgs) == 2
    assert conv.message_count == 2


def test_get_context(conv):
    """获取 OpenAI 兼容上下文。"""
    conv.add("system", "You are helpful.")
    conv.add("user", "Question?")
    ctx = conv.get_context()
    assert len(ctx) == 2
    assert ctx[0]["role"] == "system"
    assert ctx[1]["role"] == "user"


def test_fifo_trim(conv):
    """FIFO 裁剪：超出 max_messages 时移除最旧消息。"""
    conv.config.max_messages = 5
    conv.config.preserve_last_n = 2
    for i in range(10):
        conv.add("user", f"msg{i}")
    assert conv.message_count <= 5


def test_preserve_system(conv):
    """裁剪时保留 system 消息。"""
    conv.config.max_messages = 4
    conv.config.preserve_last_n = 1
    conv.config.preserve_system = True
    conv.add("system", "System prompt")
    for i in range(8):
        conv.add("user", f"msg{i}")
    system_msgs = [m for m in conv._messages if m.role == MessageRole.SYSTEM]
    assert len(system_msgs) >= 1
    assert system_msgs[0].content == "System prompt"


def test_token_tracking(conv):
    """token 统计。"""
    conv.add("user", "A" * 300)
    assert conv.token_count > 50


def test_fork_and_switch(conv):
    """对话分支：fork -> switch -> 验证。"""
    conv.add("user", "msg1")
    conv.add("assistant", "reply1")
    snapshot = conv.fork("test-branch")
    assert snapshot.label == "test-branch"

    conv.add("user", "msg2")
    assert conv.message_count == 3

    conv.switch_branch(snapshot.snapshot_id)
    assert conv.message_count == 2


def test_fork_branch_not_found(conv):
    """切换不存在分支抛出 KeyError。"""
    with pytest.raises(KeyError):
        conv.switch_branch("nonexistent")


def test_merge_branch_append(conv):
    """合并分支（追加模式）。"""
    conv.add("user", "msg1")
    snapshot = conv.fork("side")
    conv.add("user", "msg2")
    conv.add("user", "msg3")
    conv.merge_branch(snapshot.snapshot_id, strategy="append")
    assert conv.message_count >= 3


def test_clear(conv):
    """清空对话。"""
    conv.add_many([("user", "a"), ("assistant", "b"), ("user", "c")])
    conv.clear()
    assert conv.message_count == 0
    assert conv.token_count == 0


def test_clear_keep_system(conv):
    """清空但保留 system 消息。"""
    conv.add("system", "sys")
    conv.add("user", "q")
    conv.add("assistant", "a")
    conv.clear(keep_system=True)
    assert conv.message_count == 1
    assert conv._messages[0].content == "sys"


def test_stats_tracking(conv):
    """统计数据正确累加。"""
    conv.add("user", "hello world")
    conv.add("assistant", "hi there")
    assert conv.stats.total_messages == 2
    assert conv.stats.total_tokens > 0
    assert conv.stats.oldest_timestamp > 0


def test_message_id_unique(conv):
    """每条消息 ID 唯一。"""
    msgs = conv.add_many([("user", f"msg{i}") for i in range(5)])
    ids = {m.message_id for m in msgs}
    assert len(ids) == 5


def test_empty_context(conv):
    """空对话上下文。"""
    ctx = conv.get_context()
    assert ctx == []


def test_get_system_prompt(conv):
    """提取 system prompt。"""
    conv.add("system", "Be concise.")
    conv.add("user", "Q")
    assert conv.get_system_prompt() == "Be concise."


def test_importance_weighted_trim():
    """重要性加权裁剪。"""
    cfg = ConversationConfig(
        max_messages=5, trim_strategy=TrimStrategy.IMPORTANCE_WEIGHTED, preserve_last_n=2
    )
    c = ConversationManager(cfg)
    for i in range(10):
        m = c.add("user", f"msg{i}")
        m.importance = float(i % 3)
    assert c.message_count <= 5


def test_trim_stats_increment(conv):
    """裁剪后 trim_count 递增。"""
    conv.config.max_messages = 3
    conv.config.preserve_last_n = 1
    for i in range(8):
        conv.add("user", f"msg{i}")
    assert conv.stats.trim_count > 0
