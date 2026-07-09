"""
E2E Test: ToolAgent + ToolRegistry Bridge + Mock LLM

Validates the production execution pipeline:
  ToolRegistry (BaseTool) → Bridge → ToolExecutor → ToolAgent → Mock LLM
"""

import json
import os
import tempfile

from agentos.agent.tool_agent import AgentConfig, ToolAgent, ToolExecutor
from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    ToolCall,
)
from agentos.tools.bridge import bridge_registry_to_executor
from agentos.tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool
from agentos.tools.registry import ToolRegistry


class E2EMockProvider(LLMProvider):
    """Mock LLM that simulates tool-using behavior."""

    provider_name = "e2e-test"

    def __init__(self, plan: list[dict]):
        """
        plan: list of dicts with keys:
          - tool_calls: list of (name, args) tuples
          - content: final text answer
        """
        super().__init__(model="mock")
        self._plan = plan
        self._step = 0

    def _make(self, content="", tool_calls=None, finish="stop"):
        if tool_calls:
            finish = "tool_calls"
        return CompletionResult(
            choices=[CompletionChoice(
                index=0,
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish,
            )],
            usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="mock",
        )

    def chat(self, messages, **kwargs):
        if self._step >= len(self._plan):
            return self._make(content="Done.")
        step = self._plan[self._step]
        self._step += 1

        if "tool_calls" in step:
            calls = []
            for i, (name, args_dict) in enumerate(step["tool_calls"]):
                calls.append(ToolCall(
                    id=f"tc_{self._step}_{i}",
                    name=name,
                    arguments=json.dumps(args_dict),
                ))
            return self._make(tool_calls=calls)
        else:
            return self._make(content=step.get("content", "Done."))

    async def achat(self, messages, **kwargs):
        return self.chat(messages, **kwargs)


def test_read_file_tool():
    """Test: Agent reads a file using read_file tool."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello, AgentOS!")
        tmp_path = f.name

    try:
        provider = E2EMockProvider([
            {"tool_calls": [("read_file", {"file_path": tmp_path})]},
            {"content": "文件内容: Hello, AgentOS!"},
        ])
        agent = ToolAgent(
            provider=provider,
            tool_executor=executor,
            config=AgentConfig(max_steps=3, stop_on_error=False),
        )
        result = agent.run("读取测试文件")
        assert result.success, f"Agent failed: {result.error}"
        assert result.total_steps == 2
        assert "Hello" in result.final_answer
    finally:
        os.unlink(tmp_path)


def test_write_then_read():
    """Test: Agent writes a file then reads it back."""
    reg = ToolRegistry()
    reg.register(WriteFileTool())
    reg.register(ReadFileTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    tmp_path = "/tmp/agentos_test_write_read.txt"
    try:
        provider = E2EMockProvider([
            {"tool_calls": [("write_file", {"file_path": tmp_path, "content": "Written by AgentOS"})]},
            {"tool_calls": [("read_file", {"file_path": tmp_path})]},
            {"content": "写入并读取成功。"},
        ])
        agent = ToolAgent(
            provider=provider,
            tool_executor=executor,
            config=AgentConfig(max_steps=5, stop_on_error=False),
        )
        result = agent.run("写入文件后读取")
        assert result.success, f"Agent failed: {result.error}"
        assert result.total_steps == 3
        assert "成功" in result.final_answer or "写入" in result.final_answer
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_list_directory():
    """Test: Agent lists a directory."""
    reg = ToolRegistry()
    reg.register(ListDirectoryTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    provider = E2EMockProvider([
        {"tool_calls": [("list_directory", {"path": "/tmp"})]},
        {"content": "/tmp 目录列表已获取。"},
    ])
    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(max_steps=3, stop_on_error=False),
    )
    result = agent.run("列出 /tmp 目录")
    assert result.success, f"Agent failed: {result.error}"
    assert result.total_steps == 2


def test_multi_tool_parallel():
    """Test: Agent calls multiple tools in one step."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(ListDirectoryTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Multi-tool test")
        tmp_path = f.name

    try:
        provider = E2EMockProvider([
            {
                "tool_calls": [
                    ("read_file", {"file_path": tmp_path}),
                    ("list_directory", {"path": "/tmp"}),
                ]
            },
            {"content": "两个工具调用完成。"},
        ])
        agent = ToolAgent(
            provider=provider,
            tool_executor=executor,
            config=AgentConfig(max_steps=3, stop_on_error=False),
        )
        result = agent.run("同时读取文件并列出目录")
        assert result.success, f"Agent failed: {result.error}"
        assert result.total_steps == 2
    finally:
        os.unlink(tmp_path)


def test_error_handling():
    """Test: Agent handles tool errors gracefully."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    provider = E2EMockProvider([
        {"tool_calls": [("read_file", {"file_path": "/nonexistent/file.txt"})]},
        {"content": "文件不存在，无法读取。"},
    ])
    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(max_steps=3, stop_on_error=False),
    )
    result = agent.run("读取不存在的文件")
    # Should not crash; agent handles error and continues
    assert result.success, f"Agent crashed on error: {result.error}"
    assert result.total_steps == 2


def test_bridge_tool_schema():
    """Test: Bridge produces correct LLM Tool schemas."""
    from agentos.tools.bridge import base_tool_to_llm_tool

    tool = base_tool_to_llm_tool(ReadFileTool())
    schema = tool.as_schema()

    assert schema["function"]["name"] == "read_file"
    assert "file_path" in schema["function"]["parameters"]["properties"]
    assert "file_path" in schema["function"]["parameters"]["required"]
