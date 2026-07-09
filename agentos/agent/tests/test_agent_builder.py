"""Tests for agentos.agent.agent_builder — 100% statement coverage target."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from agentos.agent.agent_builder import (
    _MockProvider,
    build_agent,
    create_provider,
    discover_tools,
)
from agentos.llm.base import MessageRole

# ── helpers ──────────────────────────────────────────────────────


def _make_tool_cls(tool_name: str):
    """Create a concrete BaseTool subclass with the given name."""
    from agentos.tools.base import BaseTool

    class _Tool(BaseTool):
        _tool_name = tool_name

        @property
        def name(self) -> str:
            return self._tool_name

        @property
        def parameters(self) -> dict:
            return {}

        async def execute(self, arguments: dict, sandbox=None):
            from agentos.tools.base import ToolResult

            return ToolResult(success=True, output=tool_name)

    return _Tool


class _ToolMod:
    """Fake module-like object for inspect.getmembers."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


_real_import = importlib.import_module


# ── _MockProvider ────────────────────────────────────────────────


class TestMockProvider:
    def test_provider_name(self):
        mp = _MockProvider()
        assert mp.provider_name == "mock-dev"

    def test_chat_returns_completion(self):
        mp = _MockProvider()
        result = mp.chat([])
        assert result.choices[0].message.content.startswith("Mock provider")
        assert result.model == "mock"

    def test_achat_same_as_chat(self):
        import asyncio

        mp = _MockProvider()
        sync = mp.chat([])
        async_result = asyncio.run(mp.achat([]))
        assert async_result.choices[0].message.content == sync.choices[0].message.content

    def test__make_usage_fields(self):
        mp = _MockProvider()
        result = mp._make("test")
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.usage.total_tokens == 0
        assert result.choices[0].message.role == MessageRole.ASSISTANT
        assert result.choices[0].finish_reason == "stop"


# ── discover_tools ───────────────────────────────────────────────


class TestDiscoverTools:
    def test_empty_package(self):
        with patch("importlib.import_module") as mock_import, patch(
            "pkgutil.iter_modules", return_value=[]
        ):
            mock_module = MagicMock()
            mock_module.__file__ = "/fake/agentos/tools/__init__.py"
            mock_import.return_value = mock_module
            result = discover_tools("agentos.tools")
        assert result == []

    def test_skip_underscore_module(self):
        """Use real temp package — coverage tracks _-prefixed module skip."""
        import sys

        _tmp_root = "/home/marvis/Marvis/User/oAN1i2Yfn4aIvXkoz-oN0h5oHcb4/workspace/conv_19f08962d4e_9d1241f0e39e/temp"
        sys.path.insert(0, _tmp_root)
        try:
            result = discover_tools("_fake_pkg")
        finally:
            sys.path.remove(_tmp_root)
        # _underscore module skipped; bad_import skipped; real_one from real_tool.py only
        names = [t.name for t in result]
        assert "real_one" in names
        # _underscore directory is not a module, so it shouldn't appear
        for t in result:
            assert not t.name.startswith("_")

    def test_import_error_skipped(self):
        """Use real temp package with a module that raises on import."""
        import sys

        _tmp_root = "/home/marvis/Marvis/User/oAN1i2Yfn4aIvXkoz-oN0h5oHcb4/workspace/conv_19f08962d4e_9d1241f0e39e/temp"
        sys.path.insert(0, _tmp_root)
        try:
            result = discover_tools("_fake_pkg")
        finally:
            sys.path.remove(_tmp_root)
        # bad_import.py raises ImportError at module level → skipped gracefully
        # real_tool.py provides real_one → should be present
        names = [t.name for t in result]
        assert "real_one" in names

    def test_skip_base_class_itself(self):
        from agentos.tools.base import BaseTool

        fake_tool_cls = _make_tool_cls("fake_tool")
        fake_mod = _ToolMod(FakeTool=fake_tool_cls, BaseTool=BaseTool)
        pkg = MagicMock()
        pkg.__file__ = "/fake/agentos/tools/__init__.py"

        def side_effect(name):
            if name == "agentos.tools":
                return pkg
            if name == "agentos.tools.fake_mod":
                return fake_mod
            if name.startswith("agentos.tools."):
                raise ImportError(f"mocked: {name}")
            return _real_import(name)

        with patch("importlib.import_module", side_effect=side_effect), patch(
            "pkgutil.iter_modules",
            return_value=[("fake_mod", "fake_mod", False)],
        ):
            result = discover_tools("agentos.tools")

        assert len(result) == 1
        assert result[0].name == "fake_tool"

    def test_skip_no_name_attr(self):
        from agentos.tools.base import BaseTool

        class NoNameTool(BaseTool):
            name = None  # triggers: getattr(obj, "name", None) is None

            @property
            def parameters(self) -> dict:
                return {}

            async def execute(self, arguments: dict, sandbox=None):
                from agentos.tools.base import ToolResult
                return ToolResult(success=True, output="")

        mod = _ToolMod(NoNameTool=NoNameTool)
        pkg = MagicMock()
        pkg.__file__ = "/fake/agentos/tools/__init__.py"

        def side_effect(name):
            if name == "agentos.tools":
                return pkg
            if name == "agentos.tools.fake_mod":
                return mod
            if name.startswith("agentos.tools."):
                raise ImportError(f"mocked: {name}")
            return _real_import(name)

        with patch("importlib.import_module", side_effect=side_effect), patch(
            "pkgutil.iter_modules",
            return_value=[("fake_mod", "fake_mod", False)],
        ):
            result = discover_tools("agentos.tools")

        assert result == []

    def test_skip_duplicate_class(self):
        """Use real temp package — two modules export same tool name, deduped."""
        import sys

        _tmp_root = "/home/marvis/Marvis/User/oAN1i2Yfn4aIvXkoz-oN0h5oHcb4/workspace/conv_19f08962d4e_9d1241f0e39e/temp"
        sys.path.insert(0, _tmp_root)
        try:
            result = discover_tools("_fake_pkg")
        finally:
            sys.path.remove(_tmp_root)
        # real_tool.py and real_tool2.py both export RealTool(name='real_one')
        # → only one instance returned
        names = [t.name for t in result]
        assert names.count("real_one") == 1
        assert "real_one" in names

    def test_instantiation_error_skipped(self):
        from agentos.tools.base import BaseTool

        class CrashTool(BaseTool):
            _name = "crash"

            @property
            def name(self) -> str:
                return self._name

            @property
            def parameters(self) -> dict:
                return {}

            def __init__(self):
                raise RuntimeError("oops")

            async def execute(self, arguments: dict, sandbox=None):
                from agentos.tools.base import ToolResult
                return ToolResult(success=True, output="")

        mod = _ToolMod(CrashTool=CrashTool)
        pkg = MagicMock()
        pkg.__file__ = "/fake/agentos/tools/__init__.py"

        def side_effect(name):
            if name == "agentos.tools":
                return pkg
            if name == "agentos.tools.fake_mod":
                return mod
            if name.startswith("agentos.tools."):
                raise ImportError(f"mocked: {name}")
            return _real_import(name)

        with patch("importlib.import_module", side_effect=side_effect), patch(
            "pkgutil.iter_modules",
            return_value=[("fake_mod", "fake_mod", False)],
        ):
            result = discover_tools("agentos.tools")

        assert result == []


# ── create_provider ──────────────────────────────────────────────


class TestCreateProvider:
    def test_deepseek_api_key(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False):
            with patch(
                "agentos.llm.providers.deepseek.DeepSeekProvider"
            ) as mock_cls:
                mock_cls.return_value = "deepseek_inst"
                result = create_provider()
        assert result == "deepseek_inst"
        mock_cls.assert_called_once_with(model="deepseek-chat")

    def test_openai_api_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}):
                with patch(
                    "agentos.llm.providers.openai.OpenAIProvider"
                ) as mock_cls:
                    mock_cls.return_value = "openai_inst"
                    result = create_provider()
        assert result == "openai_inst"
        mock_cls.assert_called_once_with(model="gpt-4o-mini")

    def test_anthropic_api_key(self):
        env = {"ANTHROPIC_API_KEY": "sk-test"}
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "agentos.llm.providers.anthropic.AnthropicProvider"
            ) as mock_cls:
                mock_cls.return_value = "anthropic_inst"
                result = create_provider()
        assert result == "anthropic_inst"
        mock_cls.assert_called_once_with(model="claude-3-5-sonnet-20241022")

    def test_mock_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            result = create_provider()
        assert isinstance(result, _MockProvider)


# ── build_agent ──────────────────────────────────────────────────


class TestBuildAgent:
    def test_minimal(self):
        agent = build_agent(discover_all=False)
        assert agent is not None

    def test_custom_system_prompt(self):
        agent = build_agent(
            system_prompt="自定义提示词",
            discover_all=False,
        )
        assert agent._system_prompt == "自定义提示词"

    def test_auto_system_prompt_with_tools(self):
        my_tool_cls = _make_tool_cls("my_tool")
        agent = build_agent(
            tools=[my_tool_cls()],
            discover_all=False,
        )
        assert "my_tool" in agent._system_prompt

    def test_auto_system_prompt_no_tools(self):
        agent = build_agent(
            tools=[],
            discover_all=False,
            include_skills=False,
        )
        assert "无" in agent._system_prompt

    def test_manual_provider(self):
        mp = _MockProvider()
        agent = build_agent(
            provider=mp,
            discover_all=False,
        )
        assert agent._provider is mp

    def test_manual_tools(self):
        t1_cls = _make_tool_cls("t1")
        t1 = t1_cls()
        agent = build_agent(
            tools=[t1],
            discover_all=False,
        )
        schemas = agent._executor.get_schemas()
        names = [s.function.name for s in schemas]
        assert "t1" in names

    def test_discover_all_true(self):
        with patch(
            "agentos.agent.agent_builder.discover_tools", return_value=[]
        ) as mock_dt:
            agent = build_agent(discover_all=True)
        mock_dt.assert_called_once()
        assert agent is not None

    def test_discover_all_false_no_tools(self):
        agent = build_agent(discover_all=False)
        assert agent is not None

    def test_include_skills_success(self):
        with patch(
            "agentos.tools.skill_tool.discover_skills",
            return_value=[],
        ) as mock_ds:
            agent = build_agent(
                discover_all=False,
                include_skills=True,
            )
        mock_ds.assert_called_once()
        assert agent is not None

    def test_include_skills_error_swallowed(self):
        with patch(
            "agentos.tools.skill_tool.discover_skills",
            side_effect=ImportError("no module"),
        ):
            agent = build_agent(
                discover_all=False,
                include_skills=True,
            )
        assert agent is not None

    def test_include_skills_false(self):
        with patch(
            "agentos.tools.skill_tool.discover_skills"
        ) as mock_ds:
            agent = build_agent(
                discover_all=False,
                include_skills=False,
            )
        mock_ds.assert_not_called()
        assert agent is not None

    def test_skills_with_existing_tools(self):
        t2_cls = _make_tool_cls("t2")
        fake_skill = MagicMock()
        fake_skill.name = "skill_a"

        with patch(
            "agentos.tools.skill_tool.discover_skills",
            return_value=[fake_skill],
        ):
            agent = build_agent(
                tools=[t2_cls()],
                discover_all=False,
                include_skills=True,
            )
        names = [s.function.name for s in agent._executor.get_schemas()]
        assert "t2" in names
        assert "skill_a" in names

    def test_skills_with_no_existing_tools(self):
        fake_skill = MagicMock()
        fake_skill.name = "skill_b"

        with patch(
            "agentos.tools.skill_tool.discover_skills",
            return_value=[fake_skill],
        ):
            agent = build_agent(
                tools=None,
                discover_all=False,
                include_skills=True,
            )
        names = [s.function.name for s in agent._executor.get_schemas()]
        assert "skill_b" in names

    def test_verbose_flag(self):
        agent = build_agent(
            discover_all=False,
            verbose=True,
        )
        assert agent._config.verbose is True

    def test_max_steps_default(self):
        agent = build_agent(discover_all=False)
        assert agent._config.max_steps == 10

    def test_max_steps_custom(self):
        agent = build_agent(
            discover_all=False,
            max_steps=5,
        )
        assert agent._config.max_steps == 5
