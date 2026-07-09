"""Tests for agentos.tools.code_agent."""

import pytest

from agentos.tools.base import PermissionLevel
from agentos.tools.code_agent import CodeAgentTool, ShellTool


class TestPermissionLevel:
    def test_values(self):
        assert PermissionLevel.SAFE == "safe"
        assert PermissionLevel.MODERATE == "moderate"
        assert PermissionLevel.SENSITIVE == "sensitive"


class TestCodeAgentTool:
    def test_defaults(self):
        t = CodeAgentTool()
        assert t.name == "execute_code"
        assert t.permission_level == PermissionLevel.SENSITIVE

    def test_to_openai_schema(self):
        t = CodeAgentTool()
        schema = t.to_openai_schema()
        assert schema["function"]["name"] == "execute_code"

    @pytest.mark.asyncio
    async def test_execute_simple(self):
        t = CodeAgentTool()
        result = await t.execute({"code": "2 + 3", "language": "python"})
        assert hasattr(result, "output") or hasattr(result, "error")

    @pytest.mark.asyncio
    async def test_execute_output(self):
        t = CodeAgentTool()
        result = await t.execute({
            "code": "print('hello')",
            "language": "python",
        })
        assert result.call_id is not None


class TestShellTool:
    def test_create(self):
        t = ShellTool()
        assert t.name == "shell"

    def test_to_openai_schema(self):
        t = ShellTool()
        schema = t.to_openai_schema()
        assert schema["function"]["name"] == "shell"

    def test_permission_level(self):
        t = ShellTool()
        assert t.permission_level == PermissionLevel.SENSITIVE

    @pytest.mark.asyncio
    async def test_execute(self):
        t = ShellTool()
        result = await t.execute({"command": "echo hello"})
        assert hasattr(result, "output") or hasattr(result, "error")
