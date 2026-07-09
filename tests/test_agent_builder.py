"""
Tests: AgentBuilder — automatic tool discovery, bridge, and agent construction.
"""

import json
import os
import tempfile

from agentos.agent.agent_builder import build_agent, discover_tools
from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    ToolCall,
)


class StepMockProvider(LLMProvider):
    """Step-based mock provider for testing multi-turn agent flows."""

    provider_name = "step-mock"

    def __init__(self, responses: list[dict]):
        """
        responses: list of {"content": str | None, "tool_calls": list[tuple] | None}
        """
        super().__init__(model="mock")
        self._responses = responses
        self._step = 0

    def chat(self, messages, **kwargs):
        if self._step >= len(self._responses):
            return CompletionResult(
                choices=[CompletionChoice(index=0,
                    message=Message(role=MessageRole.ASSISTANT, content="Done."),
                    finish_reason="stop")],
                usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model="mock")
        r = self._responses[self._step]
        self._step += 1

        tool_calls = None
        if r.get("tool_calls"):
            tool_calls = [
                ToolCall(id=f"tc_{self._step}_{i}", name=name, arguments=json.dumps(args))
                for i, (name, args) in enumerate(r["tool_calls"])
            ]
        return CompletionResult(
            choices=[CompletionChoice(index=0,
                message=Message(role=MessageRole.ASSISTANT,
                    content=r.get("content", ""), tool_calls=tool_calls),
                finish_reason="tool_calls" if tool_calls else "stop")],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="mock")

    async def achat(self, messages, **kwargs):
        return self.chat(messages, **kwargs)


# ── Tests ──

def test_discover_all_tools():
    """All 13 BaseTool subclasses should be discovered."""
    tools = discover_tools()
    names = {t.name for t in tools}
    required = {"read_file", "write_file", "list_directory", "grep",
                "file_search", "code_search", "web_fetch", "http_request",
                "download_file", "json_tool", "csv_tool", "execute_code", "shell"}
    assert required.issubset(names), f"Missing: {required - names}"


def test_build_with_all_tools():
    """Agent builder registers all discovered tools."""
    agent = build_agent(discover_all=True, verbose=False)
    schemas = agent._executor.get_schemas()
    assert len(schemas) >= 13


def test_build_with_custom_tools():
    """Agent builder with explicit tool list."""
    from agentos.tools.file_tools import ReadFileTool, WriteFileTool
    agent = build_agent(
        tools=[ReadFileTool(), WriteFileTool()],
        discover_all=False,
        include_skills=False,
        verbose=False,
    )
    schemas = agent._executor.get_schemas()
    names = {s.function.name for s in schemas}
    assert names == {"read_file", "write_file"}


def test_custom_system_prompt():
    """Custom system prompt is applied."""
    prompt = "You are a pirate assistant. Arrr!"
    agent = build_agent(system_prompt=prompt, discover_all=False, include_skills=False, tools=[], verbose=False)
    assert agent._system_prompt == prompt


def test_multi_tool_agent_flow():
    """Agent uses multiple different tools in sequence."""
    from agentos.tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("multi-tool test content")
        tmp_path = f.name

    try:
        provider = StepMockProvider([
            {"tool_calls": [("list_directory", {"path": "/tmp"})]},
            {"tool_calls": [("read_file", {"file_path": tmp_path})]},
            {"content": "目录已列出，文件内容已读取。"},
        ])
        agent = build_agent(
            tools=[ReadFileTool(), WriteFileTool(), ListDirectoryTool()],
            provider=provider,
            discover_all=False,
            verbose=False,
        )
        result = agent.run("列出/tmp并读取测试文件")
        assert result.success
        assert result.total_steps == 3
    finally:
        os.unlink(tmp_path)


def test_search_tools_integration():
    """Grep and file_search tools work through bridge."""
    import tempfile

    from agentos.tools.search_tools import FileSearchTool, GrepTool

    # Create a test directory with some files
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "test_a.py"), "w") as f:
            f.write("def hello():\n    print('hello world')\n")
        with open(os.path.join(tmpdir, "test_b.py"), "w") as f:
            f.write("def goodbye():\n    print('goodbye')\n")

        provider = StepMockProvider([
            {"tool_calls": [("grep", {"pattern": "def hello", "directory": tmpdir})]},
            {"tool_calls": [("file_search", {"pattern": "*.py", "directory": tmpdir})]},
            {"content": "搜索完成。"},
        ])
        agent = build_agent(
            tools=[GrepTool(), FileSearchTool()],
            provider=provider,
            discover_all=False,
            verbose=False,
        )
        result = agent.run("搜索 hello 函数和所有 Python 文件")
        assert result.success
        assert result.total_steps == 3


def test_code_tools_integration():
    """execute_code and shell tools work through bridge."""
    from agentos.tools.code_agent import CodeAgentTool, ShellTool

    provider = StepMockProvider([
        {"tool_calls": [("execute_code", {"code": "print(2+2)"})]},
        {"tool_calls": [("shell", {"command": "echo hello"})]},
        {"content": "代码和命令执行完成。"},
    ])
    agent = build_agent(
        tools=[CodeAgentTool(), ShellTool()],
        provider=provider,
        discover_all=False,
        verbose=False,
    )
    result = agent.run("执行两段代码")
    assert result.success
    assert result.total_steps == 3


def test_web_tools_integration():
    """web_fetch and http_request tools work through bridge."""
    from agentos.tools.http_tools import HttpRequestTool
    from agentos.tools.web_tools import WebFetchTool

    provider = StepMockProvider([
        {"tool_calls": [("http_request",
            {"url": "https://httpbin.org/get", "method": "GET"})]},
        {"content": "HTTP请求完成。"},
    ])
    agent = build_agent(
        tools=[WebFetchTool(), HttpRequestTool()],
        provider=provider,
        discover_all=False,
        verbose=False,
    )
    result = agent.run("发送HTTP请求")
    assert result.success
    assert result.total_steps == 2


def test_data_tools_integration():
    """json_tool and csv_tool work through bridge."""
    from agentos.tools.data_tools import CsvTool, JsonTool

    provider = StepMockProvider([
        {"tool_calls": [("json_tool", {"operation": "parse", "input": '{"a": 1}'})]},
        {"content": "JSON解析完成。"},
    ])
    agent = build_agent(
        tools=[JsonTool(), CsvTool()],
        provider=provider,
        discover_all=False,
        verbose=False,
    )
    result = agent.run("解析JSON")
    assert result.success
    assert result.total_steps == 2


def test_provider_autodetect_mock():
    """Without API key, falls back to mock provider."""
    agent = build_agent(discover_all=False, tools=[], verbose=False)
    assert "mock" in agent._provider.provider_name


def test_max_steps_config():
    """max_steps is respected."""
    agent = build_agent(max_steps=3, discover_all=False, tools=[], verbose=False)
    assert agent._config.max_steps == 3
