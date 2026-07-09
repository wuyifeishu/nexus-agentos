"""Tests for agentos.core.context — ContextManager and related types."""

from agentos.core.context import (
    AgentContext,
    ContextManager,
    Message,
    ToolCall,
    ToolResult,
)


class TestToolCall:
    def test_create(self):
        tc = ToolCall(name="search", arguments={"q": "test"})
        assert tc.name == "search"
        assert tc.arguments == {"q": "test"}


class TestToolResult:
    def test_ok(self):
        tr = ToolResult(call_id="c1", output="result")
        assert not tr.is_error

    def test_error(self):
        tr = ToolResult(call_id="c1", error="fail")
        assert tr.is_error

    def test_defaults(self):
        tr = ToolResult(call_id="c2")
        assert tr.output is None
        assert tr.error is None
        assert tr.exit_code is None


class TestMessage:
    def test_user_message(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.tool_calls is None

    def test_tool_message(self):
        m = Message(role="tool", content="ok", tool_call_id="c1")
        assert m.tool_call_id == "c1"

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(name="calc", arguments={"expr": "1+1"})
        m = Message(role="assistant", content="", tool_calls=[tc])
        assert len(m.tool_calls) == 1


class TestAgentContext:
    def test_default_model(self):
        ctx = AgentContext(messages=[])
        assert ctx.model_type == "openai"

    def test_with_tools(self):
        ctx = AgentContext(messages=[], tools=[{"name": "search"}], model_type="anthropic")
        assert len(ctx.tools) == 1
        assert ctx.model_type == "anthropic"


class TestContextManager:
    def test_init_no_system_prompt(self):
        cm = ContextManager()
        assert cm.message_count == 0
        assert cm.step_count == 0

    def test_init_with_system_prompt(self):
        cm = ContextManager(system_prompt="You are helpful")
        assert cm.system_prompt == "You are helpful"

    def test_init_session(self):
        cm = ContextManager(system_prompt="sys")
        import asyncio
        asyncio.run(cm.init_session("s1", "do stuff"))
        assert cm.session_id == "s1"
        assert cm.current_task == "do stuff"
        assert cm.message_count == 2  # system + user

    def test_build_context_increments_step(self):
        cm = ContextManager()
        cm.build_context()
        assert cm.step_count == 1
        cm.build_context()
        assert cm.step_count == 2

    def test_build_context_respects_max_history(self):
        cm = ContextManager(max_history=2)
        import asyncio
        asyncio.run(cm.init_session("s1", "task"))
        cm.add_user_message("m1")
        cm.add_user_message("m2")
        cm.add_user_message("m3")
        ctx = cm.build_context()
        assert len(ctx.messages) == 2

    def test_add_user_message(self):
        cm = ContextManager()
        cm.add_user_message("hi")
        assert cm.message_count == 1

    def test_add_assistant_message(self):
        cm = ContextManager()
        cm.add_assistant_message("response")
        assert cm.message_count == 1

    def test_add_assistant_with_tool_calls(self):
        cm = ContextManager()
        tc = ToolCall(name="search", arguments={})
        cm.add_assistant_message("", tool_calls=[tc])
        assert cm.message_count == 1

    def test_append_tool_results(self):
        cm = ContextManager()
        cm.append_tool_results([
            ToolResult(call_id="c1", output="ok"),
            ToolResult(call_id="c2", error="fail"),
        ])
        assert cm.message_count == 2

    def test_update_plan(self):
        cm = ContextManager()
        cm.update_plan("new strategy")
        assert cm.plan == "new strategy"
        assert cm.message_count == 1

    def test_estimate_context_usage_empty(self):
        cm = ContextManager()
        assert cm.estimate_context_usage() == 0.0

    def test_estimate_context_usage(self):
        cm = ContextManager(max_history=100)
        cm.add_user_message("a" * 400)  # ~100 tokens
        usage = cm.estimate_context_usage()
        assert 0.0 < usage <= 1.0

    def test_estimated_tokens(self):
        cm = ContextManager()
        cm.add_user_message("abcd")  # 4 chars => 1 token
        assert cm.estimated_tokens == 1

    def test_full_lifecycle(self):
        cm = ContextManager(system_prompt="You are an agent", max_history=10)
        import asyncio
        asyncio.run(cm.init_session("s1", "analyze data"))
        cm.add_assistant_message("thinking...", tool_calls=[ToolCall("search", {"q": "data"})])
        cm.append_tool_results([ToolResult(call_id="c1", output="found results")])
        cm.add_assistant_message("answer")

        ctx = cm.build_context()
        assert cm.step_count == 1
        assert cm.message_count == 5
        assert len(ctx.messages) <= 10

    def test_session_resets_on_new_init(self):
        cm = ContextManager()
        import asyncio
        asyncio.run(cm.init_session("s1", "task1"))
        cm.add_user_message("extra")
        assert cm.message_count == 2  # user task + user extra (no system prompt)

        asyncio.run(cm.init_session("s2", "task2"))
        assert cm.message_count == 1  # reset: only user task, no system prompt
        assert cm.session_id == "s2"
        assert cm.step_count == 0
