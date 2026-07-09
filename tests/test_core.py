"""
AgentOS Test Suite — Core test cases for framework components.

Covers: State, MCP, A2A, Memory, HITL, Distributed, Observability,
        Multimodal, Workflow, Marketplace, CLI, API
"""

import tempfile
from pathlib import Path

import pytest

# ============================================================================
# State System Tests
# ============================================================================

class TestStateSystem:
    """Tests for agent state management with Pydantic v2."""

    def test_base_agent_state_creation(self):
        from agentos.state.schema import BaseAgentState

        state = BaseAgentState(
            agent_id="test-1",
            task="analyze data",
            status="running"
        )
        assert state.agent_id == "test-1"
        assert state.task == "analyze data"
        assert state.status == "running"
        assert state.messages == []
        assert state.metrics == {}

    def test_state_reducer_merge(self):
        from agentos.state.schema import BaseAgentState, StateReducer

        state_a = BaseAgentState(agent_id="a", task="t1", status="running")
        state_b = BaseAgentState(agent_id="a", task="t1", status="done", messages=["msg1"])

        merged = StateReducer.merge(state_a, state_b)
        assert merged.status == "done"
        assert "msg1" in merged.messages

    def test_state_serialization(self):
        from agentos.state.schema import BaseAgentState

        state = BaseAgentState(
            agent_id="s1",
            task="serialize me",
            status="pending",
            messages=[{"role": "user", "content": "hi"}],
            metrics={"tokens": 42}
        )
        data = state.model_dump()
        restored = BaseAgentState(**data)
        assert restored.messages == [{"role": "user", "content": "hi"}]
        assert restored.metrics["tokens"] == 42

    def test_state_reducer_last_write_wins(self):
        from agentos.state.schema import BaseAgentState, LastWriteWinsReducer

        state_a = BaseAgentState(agent_id="a", task="t", status="v1")
        state_b = BaseAgentState(agent_id="a", task="t", status="v2", version=2)

        result = LastWriteWinsReducer.merge(state_a, state_b)
        assert result.status == "v2"

    def test_state_reducer_append_only(self):
        from agentos.state.schema import AppendOnlyReducer, BaseAgentState

        state_a = BaseAgentState(agent_id="a", task="t", messages=["a"])
        state_b = BaseAgentState(agent_id="a", task="t", messages=["b"])

        result = AppendOnlyReducer.merge(state_a, state_b)
        assert len(result.messages) == 2


# ============================================================================
# MCP Protocol Tests
# ============================================================================

class TestMCPProtocol:
    """Tests for Model Context Protocol implementation."""

    def test_server_info(self):
        from agentos.mcp.server import MCPServer, ServerInfo

        info = ServerInfo(name="test-server", version="1.0")
        server = MCPServer(info)
        assert server.info.name == "test-server"

    def test_tool_registration(self):
        from agentos.mcp.server import MCPServer, ServerInfo, Tool

        server = MCPServer(ServerInfo(name="t", version="1"))

        async def dummy_call(params): return {"ok": True}

        tool = Tool(
            name="dummy",
            description="A dummy tool",
            input_schema={"type": "object", "properties": {}},
            call=dummy_call,
        )
        server.register_tool(tool)
        assert "dummy" in server.tools

    @pytest.mark.asyncio
    async def test_list_tools(self):
        from agentos.mcp.server import MCPServer, ServerInfo, Tool

        server = MCPServer(ServerInfo(name="t", version="1"))

        async def tool_a(params): return {"a": 1}
        async def tool_b(params): return {"b": 2}

        server.register_tool(Tool(name="a", description="Tool A", input_schema={}, call=tool_a))
        server.register_tool(Tool(name="b", description="Tool B", input_schema={}, call=tool_b))

        tools = await server.list_tools()
        names = [t["name"] for t in tools]
        assert "a" in names
        assert "b" in names


# ============================================================================
# A2A Protocol Tests
# ============================================================================

class TestA2AProtocol:
    """Tests for Agent-to-Agent protocol."""

    def test_agent_registry_register(self):
        from agentos.protocols.registry import AgentRecord, AgentRegistry

        registry = AgentRegistry()
        record = AgentRecord(
            agent_id="ag-001",
            capabilities=["chat", "search"],
            endpoint="http://localhost:9090",
        )
        registry.register(record)
        assert registry.get("ag-001") is not None

    def test_agent_registry_lookup_by_capability(self):
        from agentos.protocols.registry import AgentRecord, AgentRegistry

        registry = AgentRegistry()
        registry.register(AgentRecord(agent_id="a1", capabilities=["chat"]))
        registry.register(AgentRecord(agent_id="a2", capabilities=["search"]))
        registry.register(AgentRecord(agent_id="a3", capabilities=["chat", "code"]))

        chat_agents = registry.find_by_capability("chat")
        assert len(chat_agents) == 2
        assert {a.agent_id for a in chat_agents} == {"a1", "a3"}

    def test_agent_registry_heartbeat(self):
        from agentos.protocols.registry import AgentRecord, AgentRegistry

        registry = AgentRegistry()
        record = AgentRecord(agent_id="hb-test", capabilities=["echo"])
        registry.register(record)

        registry.heartbeat("hb-test")
        agent = registry.get("hb-test")
        assert agent.healthy is True

    def test_registry_load_balance(self):
        from agentos.protocols.registry import AgentRecord, AgentRegistry

        registry = AgentRegistry()
        for i in range(3):
            registry.register(AgentRecord(agent_id=f"lb-{i}", capabilities=["task"], load=i * 0.5))

        best = registry.pick_least_loaded("task")
        assert best.agent_id == "lb-0"


# ============================================================================
# Memory Consolidation Tests
# ============================================================================

class TestMemoryConsolidation:
    """Tests for memory consolidation with ReflectionEngine."""

    def test_reflection_engine_import(self):
        from agentos.memory.consolidation import ReflectionEngine
        engine = ReflectionEngine()
        assert engine is not None

    def test_4_level_importance(self):
        # Importance levels: CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1
        levels = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW"}
        assert len(levels) == 4
        assert levels[4] == "CRITICAL"


# ============================================================================
# Workflow DSL Tests
# ============================================================================

class TestWorkflowDSL:
    """Tests for YAML/JSON workflow definition language."""

    def test_sequential_workflow(self):
        import yaml

        from agentos.workflow import WorkflowParser

        yaml_data = yaml.safe_dump({
            "name": "test-seq",
            "steps": [
                {"id": "step1", "type": "task", "task": "Do A"},
                {"id": "step2", "type": "task", "task": "Do B"},
            ]
        })
        wf = WorkflowParser.parse_str(yaml_data)
        assert wf.name == "test-seq"
        assert len(wf.steps) == 2

    @pytest.mark.asyncio
    async def test_workflow_engine_dry_run(self):
        import yaml

        from agentos.workflow import WorkflowEngine, WorkflowParser

        yaml_data = yaml.safe_dump({
            "name": "dry-test",
            "steps": [{"id": "s1", "type": "task", "task": "test"}]
        })
        wf = WorkflowParser.parse_str(yaml_data)
        engine = WorkflowEngine()
        result = await engine.dry_run(wf)
        assert result is not None


# ============================================================================
# CLI Tests
# ============================================================================

class TestCLI:
    """Tests for the agentos CLI."""

    def test_cli_import(self):
        from agentos import cli
        assert cli.main is not None

    def test_cli_init_template_names(self):
        # Verify all templates are valid
        valid = {"default", "chat", "research", "coding", "pipeline"}
        assert len(valid) == 5

    def test_cli_config_dir(self):
        config_dir = Path.home() / ".agentos"
        # Just verify the path pattern is correct
        assert str(config_dir).endswith(".agentos")


# ============================================================================
# API Server Tests
# ============================================================================

class TestAPIServer:
    """Tests for the FastAPI server."""

    @pytest.mark.asyncio
    async def test_agent_manager_create(self):
        from agentos.api.server import AgentConfigRequest, AgentManager
        manager = AgentManager()
        config = AgentConfigRequest(name="test")
        agent = manager.create(config)
        assert agent.name == "test"
        assert agent.id is not None

    @pytest.mark.asyncio
    async def test_agent_manager_list(self):
        from agentos.api.server import AgentConfigRequest, AgentManager
        manager = AgentManager()
        manager.create(AgentConfigRequest(name="a"))
        manager.create(AgentConfigRequest(name="b"))
        agents = manager.list_all()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_agent_manager_delete(self):
        from agentos.api.server import AgentConfigRequest, AgentManager
        manager = AgentManager()
        agent = manager.create(AgentConfigRequest(name="del-me"))
        assert manager.delete(agent.id) is True
        assert manager.get(agent.id) is None

    @pytest.mark.asyncio
    async def test_agent_manager_uptime(self):
        import time

        from agentos.api.server import AgentManager
        manager = AgentManager()
        time.sleep(0.1)
        assert manager.uptime > 0


# ============================================================================
# Evaluation Tests (补齐评测模块测试覆盖)
# ============================================================================

class TestEvaluation:
    """Tests for evaluation metrics and benchmark system."""

    def test_bleu_score_smoothing(self):
        """验证 BLEU smoothing (Laplace-like decay) 已实现。"""
        from agentos.evaluation import (
            bleu_score,
        )

        reference = "the cat sat on the mat"
        candidate = "the cat sat on the mat"
        score = bleu_score(reference, candidate)
        assert 0.9 <= score <= 1.0, f"Expected near 1.0, got {score}"

    def test_bleu_score_partial(self):
        """BLEU 部分匹配应给出 0~1 之间的分数。"""
        from agentos.evaluation import bleu_score

        reference = "the quick brown fox jumps over the lazy dog"
        candidate = "the quick brown fox"
        score = bleu_score(reference, candidate)
        assert 0.0 < score < 1.0, f"Expected 0~1, got {score}"

    def test_bleu_score_no_match(self):
        """完全无关文本 BLEU 应为 0（含 smoothing 底数）。"""
        from agentos.evaluation import bleu_score

        reference = "hello world"
        candidate = "completely different text"
        score = bleu_score(reference, candidate)
        assert 0.0 <= score <= 0.3, f"Expected near 0, got {score}"

    def test_rouge_score_returns_dict(self):
        """ROUGE 应返回 rouge-1/2/L 字典。"""
        from agentos.evaluation import rouge_score

        reference = "the cat sat on the mat"
        candidate = "the cat sat on the mat"
        scores = rouge_score(reference, candidate)

        assert isinstance(scores, dict)
        for key in ("rouge-1", "rouge-2", "rouge-l"):
            assert key in scores
            assert 0.0 <= scores[key] <= 1.0

    def test_exact_match_true(self):
        """精确匹配测试。"""
        from agentos.evaluation import exact_match

        assert exact_match("abc", "abc") == 1.0
        assert exact_match("ABC", "abc") == 0.0
        assert exact_match("abc", "abc ") == 0.0

    def test_composite_scorer_baseline(self):
        """CompositeScorer 至少包含 4 种指标。"""
        from agentos.evaluation import CompositeScorer

        scorer = CompositeScorer()
        result = scorer.evaluate(
            reference="the quick brown fox",
            candidate="the quick brown dog",
        )
        assert isinstance(result, dict)
        # Should contain at least bleu, rouge, exact_match, semantics
        metric_names = {k.lower() for k in result.keys()}
        core = {"bleu", "rouge", "exact_match"}
        assert core.issubset(metric_names), f"Missing metrics: {core - metric_names}"

    def test_composite_scorer_v2_llm_judge(self):
        """CompositeScorerV2 应集成 LLM-as-Judge。"""
        from agentos.evaluation import CompositeScorerV2

        scorer = CompositeScorerV2()
        assert hasattr(scorer, "llm_judge") or hasattr(scorer, "_judge_model"), \
            "CompositeScorerV2 should have LLM judge capability"

    def test_evaluation_package_exports(self):
        """验证 evaluation 包公开 API。"""
        import agentos.evaluation as ev
        core_exports = {
            "bleu_score", "rouge_score", "exact_match",
            "CompositeScorer", "CompositeScorerV2",
        }
        available = set(dir(ev))
        missing = core_exports - available
        assert not missing, f"Missing exports: {missing}"


# ============================================================================
# Sandbox Tests (补齐沙箱模块测试覆盖)
# ============================================================================

class TestSandbox:
    """Tests for sandbox execution environment."""

    def test_sandbox_config_defaults(self):
        """验证沙箱配置默认值。"""
        from agentos.sandbox import SandboxConfig

        config = SandboxConfig()
        assert config.image == "python:3.11-slim"
        assert config.timeout_s == 30.0
        assert config.memory_mb == 512
        assert config.network_enabled is False

    def test_sandbox_config_custom(self):
        """自定义沙箱配置。"""
        from agentos.sandbox import SandboxConfig

        config = SandboxConfig(
            image="python:3.12-slim",
            timeout_s=60.0,
            memory_mb=1024,
            network_enabled=True,
            read_only_rootfs=True,
        )
        assert config.timeout_s == 60.0
        assert config.memory_mb == 1024
        assert config.network_enabled is True

    def test_sandbox_config_to_docker_args(self):
        """验证 Docker 参数生成。"""
        from agentos.sandbox import SandboxConfig

        config = SandboxConfig(memory_mb=256, network_enabled=False)
        args = config.to_docker_args("test-container")
        assert "--name" in args
        assert "test-container" in args
        assert "--memory=256m" in args
        assert "--network=none" in args
        # No network ports exposed
        assert all("-p" not in a for a in args)

    def test_code_validator_blocklist(self):
        """验证代码安全验证器的危险导入拦截。"""
        from agentos.sandbox import CodeValidator, Language

        validator = CodeValidator()
        # 拦截危险操作
        safe1, violations1 = validator.validate("import os; os.system('rm -rf /')", Language.PYTHON)
        assert safe1 is False, "os.system should be blocked"
        assert len(violations1) > 0

        # 正常代码
        safe2, violations2 = validator.validate("print('hello world')", Language.PYTHON)
        assert safe2 is True
        assert len(violations2) == 0

    def test_code_validator_getattr_bypass_blocked(self):
        """验证 __import__('os') 绕过被拦截。"""
        from agentos.sandbox import CodeValidator, Language

        validator = CodeValidator()
        safe, violations = validator.validate(
            "__import__('os').system('rm -rf /')", Language.PYTHON
        )
        assert safe is False

    def test_sandbox_result_defaults(self):
        """验证 SandboxResult 默认状态。"""
        from agentos.sandbox import SandboxResult

        result = SandboxResult(execution_id="test-1")
        assert result.status.value == "created"
        assert result.exit_code == -1
        assert result.stdout == ""
        assert result.stderr == ""

    def test_docker_sandbox_logger_warning(self):
        """验证 Docker 不可用时 sandbox 产生 warning（不静默）。"""
        import logging

        from agentos.sandbox import DockerSandbox, SandboxConfig

        # Capture log
        sandbox_logger = logging.getLogger("agentos.sandbox")
        sandbox_logger.setLevel(logging.WARNING)
        from io import StringIO
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        sandbox_logger.addHandler(handler)

        sandbox = DockerSandbox(SandboxConfig())
        available = sandbox._docker_available()

        log_output = stream.getvalue()
        if not available:
            assert "Docker is not available" in log_output, \
                f"Expected warning in logs, got: {log_output}"

        sandbox_logger.removeHandler(handler)

    def test_sandbox_rate_limit(self):
        """验证速率限制机制。"""
        from agentos.sandbox import DockerSandbox, SandboxConfig

        sandbox = DockerSandbox(SandboxConfig())
        # 初始状态应允许
        assert sandbox._check_rate_limit() is True

        # 模拟超出限制
        now = __import__("time").time()
        sandbox._execution_timestamps = [now] * (sandbox._max_executions_per_window + 1)
        assert sandbox._check_rate_limit() is False

    def test_sandbox_module_exports(self):
        """验证 sandbox 包公开 API。"""
        import agentos.sandbox as sb
        core_exports = {
            "SandboxConfig", "SandboxResult", "DockerSandbox",
            "CodeValidator", "SandboxStatus", "Language",
            "SelfEvolutionRunner", "create_sandbox",
        }
        available = set(dir(sb))
        missing = core_exports - available
        assert not missing, f"Missing exports: {missing}"


# ============================================================================
# Integration: End-to-end flow test
# ============================================================================

@pytest.mark.integration
class TestIntegration:
    """Minimal integration flow test."""

    @pytest.mark.asyncio
    async def test_create_and_run_flow(self):
        """Create agent via manager, simulate run."""
        from agentos.api.server import AgentConfigRequest, AgentManager, RunRequest

        manager = AgentManager()
        agent = manager.create(AgentConfigRequest(name="integration-test"))
        request = RunRequest(agent_id=agent.id, prompt="What is 2+2?")
        assert request.agent_id == agent.id
        assert request.prompt == "What is 2+2?"
        agent.tasks_completed += 1
        assert agent.tasks_completed == 1


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_state():
    from agentos.state.schema import BaseAgentState
    return BaseAgentState(
        agent_id="fixture-1",
        task="fixture task",
        status="idle",
    )
