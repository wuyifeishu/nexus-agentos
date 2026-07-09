"""Test AgentLoop — core agent execution loop with reflection, HITL, checkpoints, swarm."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.core.loop import (
    AgentLoop,
    AgentResult,
    HumanInterruptNeeded,
    LoopConfig,
    LoopState,
    MaxIterationsExceeded,
    ReflectionResult,
    StepResult,
    StepTimeoutError,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def loop_cfg():
    return LoopConfig(
        max_iterations=5,
        max_retries_per_step=1,
        enable_reflection=False,
        enable_self_critique=False,
        enable_human_in_the_loop=False,
        enable_checkpoints=False,
        enable_cost_tracking=False,
        auto_select_model=False,
        enable_swarm=False,
    )


@pytest.fixture
def mock_router():
    router = AsyncMock()
    router.model_type = "text"
    router.current_model = "test-model"
    return router


@pytest.fixture
def mock_tool_registry():
    reg = AsyncMock()
    reg.get_schemas_for_model = MagicMock(return_value=[])
    reg.execute_batch = AsyncMock(return_value=[])
    reg.get = MagicMock(return_value=None)
    return reg


@pytest.fixture
def mock_ctx_mgr():
    mgr = AsyncMock()
    mgr._messages = []
    mgr.current_task = "test task"
    mgr.step_count = 0
    return mgr


@pytest.fixture
def loop(mock_router, mock_tool_registry, mock_ctx_mgr, loop_cfg):
    cost_tracker = MagicMock()
    cost_tracker.total_cost = 0.0
    return AgentLoop(
        model_router=mock_router,
        tool_registry=mock_tool_registry,
        context_manager=mock_ctx_mgr,
        config=loop_cfg,
        cost_tracker=cost_tracker,
    )


# ============================================================================
# LoopState / AgentResult / LoopConfig / StepResult
# ============================================================================

class TestLoopState:
    def test_all_states(self):
        assert LoopState.RUNNING.value == "running"
        assert LoopState.COMPLETED.value == "completed"
        assert LoopState.FAILED.value == "failed"
        assert LoopState.CANCELLED.value == "cancelled"


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult(output="done", iterations=10)
        assert r.output == "done"
        assert r.iterations == 10
        assert r.tokens_used == {}
        assert r.cost_usd == 0.0
        assert r.tool_calls_total == 0
        assert r.swarm_result is None
        assert r.cache_hit is False

    def test_full_result(self):
        r = AgentResult(output="ok", iterations=3, cost_usd=0.05, tool_calls_total=5,
                        human_interrupts=2, final_state=LoopState.COMPLETED)
        assert r.cost_usd == 0.05
        assert r.human_interrupts == 2


class TestLoopConfig:
    def test_defaults(self):
        c = LoopConfig()
        assert c.max_iterations == 100
        assert c.step_timeout_seconds == 120
        assert c.enable_reflection is True
        assert c.enable_cost_tracking is True
        assert c.max_parallel_agents == 4
        assert c.auto_page_threshold == 0.85

    def test_custom(self):
        c = LoopConfig(max_iterations=50, enable_streaming=True, enable_swarm=True)
        assert c.max_iterations == 50
        assert c.enable_streaming is True


class TestStepResult:
    def test_terminal(self):
        r = StepResult(content="hello", is_terminal=True)
        assert r.content == "hello"
        assert r.is_terminal is True

    def test_non_terminal_with_tools(self):
        r = StepResult(content="", is_terminal=False, tool_results=[{"name": "search"}])
        assert r.tool_results == [{"name": "search"}]


# ============================================================================
# ReflectionResult
# ============================================================================

class TestReflectionResult:
    def test_creation(self):
        r = ReflectionResult(0.8, ["issue1"], ["sug1"], True, "new plan")
        assert r.quality_score == 0.8
        assert len(r.issues) == 1
        assert r.should_continue is True
        assert r.new_plan == "new plan"

    def test_defaults(self):
        r = ReflectionResult(0.5, [], [], False)
        assert r.new_plan is None


# ============================================================================
# AgentLoop construction
# ============================================================================

class TestAgentLoopInit:
    def test_uses_default_config(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr)
        assert loop.config.max_iterations == 100

    def test_custom_config(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        cfg = LoopConfig(max_iterations=3)
        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr, config=cfg)
        assert loop.config.max_iterations == 3

    def test_accepts_all_optional_params(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        loop = AgentLoop(
            mock_router, mock_tool_registry, mock_ctx_mgr,
            sandbox_manager=MagicMock(),
            tracer=MagicMock(),
            checkpoint_store=AsyncMock(),
            cost_tracker=MagicMock(),
            metrics_collector=MagicMock(),
            cost_analytics=MagicMock(),
            audit_logger=MagicMock(),
            rate_limiter=MagicMock(),
            on_iteration=lambda i, r: None,
            on_stream=lambda c: None,
            on_human_interrupt=lambda m, c: None,
            on_reflection=lambda r: None,
        )
        assert loop.sandbox_manager is not None
        assert loop.rate_limiter is not None

    def test_cancel_sets_flag(self, loop):
        loop.cancel()
        assert loop._cancelled is True

    def test_set_auto_paging(self, loop):
        called = []

        def cb(ratio):
            called.append(ratio)

        loop.set_auto_paging(cb)
        assert loop._auto_page_callback is cb


# ============================================================================
# Complexity estimation
# ============================================================================

class TestComplexityEstimation:
    def test_simple_task_scores_low(self, loop):
        score = loop._estimate_complexity("hello world")
        assert score < 0.3

    def test_complex_task_scores_high(self, loop):
        score = loop._estimate_complexity("分析架构设计然后实现优化")
        assert score > 0.4

    def test_security_task_scores_high(self, loop):
        score = loop._estimate_complexity("deploy 安全 review")
        assert score > 0.3

    def test_very_long_task(self, loop):
        score = loop._estimate_complexity("x" * 3000)
        assert score >= 0.3

    def test_max_score_is_one(self, loop):
        score = loop._estimate_complexity("分析对比设计架构 review refactor 实现优化诊断 troubleshoot debug deploy migrate 安全 security " * 10)
        assert score <= 1.0


# ============================================================================
# High risk detection
# ============================================================================

class TestHighRiskDetection:
    def test_delete_is_risky(self, loop):
        from unittest.mock import MagicMock
        tc = MagicMock()
        tc.name = "delete_file"
        assert loop._is_high_risk(tc) is True

    def test_read_is_not_risky(self, loop):
        from unittest.mock import MagicMock
        tc = MagicMock()
        tc.name = "read_file"
        assert loop._is_high_risk(tc) is False

    def test_sudo_is_risky(self, loop):
        from unittest.mock import MagicMock
        tc = MagicMock()
        tc.name = "sudo_exec"
        assert loop._is_high_risk(tc) is True

    def test_dict_input(self, loop):
        tc = {"name": "kill_process"}
        assert loop._is_high_risk(tc) is True

    def test_safe_tool(self, loop):
        tc = {"name": "search_docs"}
        assert loop._is_high_risk(tc) is False


# ============================================================================
# Tool call grouping
# ============================================================================

class TestToolCallGrouping:
    def test_empty(self, loop):
        assert loop._group_independent_calls([]) == []

    def test_single(self, loop):
        from unittest.mock import MagicMock
        tc = MagicMock()
        tc.name = "search"
        result = loop._group_independent_calls([tc])
        assert len(result) == 1
        assert result[0] == [tc]

    def test_multiple_independent(self, loop):
        from unittest.mock import MagicMock
        t1 = MagicMock()
        t1.name = "search"
        t2 = MagicMock()
        t2.name = "read"
        # No conflicts, both in same group (independent = can run together)
        mock_search = MagicMock()
        mock_search.is_write_operation.return_value = False
        mock_read = MagicMock()
        mock_read.is_write_operation.return_value = False
        loop.tool_registry.get = MagicMock(side_effect=[mock_search, mock_read])

        result = loop._group_independent_calls([t1, t2])
        assert len(result) == 1
        assert len(result[0]) == 2


# ============================================================================
# Run with first-step terminal response
# ============================================================================

class TestRunQuickTerminal:
    @pytest.mark.asyncio
    async def test_model_returns_text_no_tool_calls(self, loop, mock_router, mock_ctx_mgr):
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.content = "Hello, world!"
        mock_resp.tool_calls = []
        mock_resp.usage = None
        mock_router.call = AsyncMock(return_value=mock_resp)

        result = await loop.run("say hello", session_id="s1")
        assert result.output == "Hello, world!"
        assert result.iterations == 1
        assert result.final_state == LoopState.COMPLETED

    @pytest.mark.asyncio
    async def test_run_with_tool_calls(self, loop, mock_router, mock_tool_registry, mock_ctx_mgr):
        from unittest.mock import MagicMock

        resp1 = MagicMock()
        resp1.tool_calls = [MagicMock()]
        resp1.content = ""
        resp1.tool_calls[0].name = "search"
        resp1.usage = None

        mock_tool_registry.execute_batch = AsyncMock(return_value=[{"result": "found"}])
        # Second call returns terminal
        resp2 = MagicMock()
        resp2.content = "Final answer"
        resp2.tool_calls = []
        resp2.usage = None

        mock_router.call = AsyncMock(side_effect=[resp1, resp2])

        result = await loop.run("search something", session_id="s2")
        assert result.output == "Final answer"
        assert result.iterations == 2
        assert result.tool_calls_total == 1


# ============================================================================
# MaxIterationsExceeded
# ============================================================================

class TestMaxIterations:
    @pytest.mark.asyncio
    async def test_raises_after_max(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        cfg = LoopConfig(max_iterations=2, enable_reflection=False, enable_self_critique=False,
                         enable_checkpoints=False, auto_select_model=False, enable_cost_tracking=False)
        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr, config=cfg)

        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.tool_calls = []  # terminal, so 1 iter... wait, terminal means it completes at iter 1
        resp.content = "done"
        resp.usage = None
        mock_router.call = AsyncMock(return_value=resp)

        # With terminal response at iter 1, it won't exceed. Let's make it non-terminal forever.
        resp.tool_calls = [MagicMock()]
        resp.tool_calls[0].name = "search"
        mock_router.call = AsyncMock(return_value=resp)
        mock_tool_registry.execute_batch = AsyncMock(return_value=[{"r": "x"}])

        with pytest.raises(MaxIterationsExceeded):
            await loop.run("infinite", session_id="s3")


# ============================================================================
# StepTimeoutError
# ============================================================================

class TestStepTimeout:
    @pytest.mark.asyncio
    async def test_returns_failed_on_timeout(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        cfg = LoopConfig(max_iterations=2, step_timeout_seconds=0.001, max_retries_per_step=0,
                         enable_reflection=False, auto_select_model=False, enable_checkpoints=False,
                         enable_cost_tracking=False)
        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr, config=cfg)

        async def slow_call(ctx):
            await asyncio.sleep(10)
            from unittest.mock import MagicMock
            return MagicMock()

        mock_router.call = slow_call

        result = await loop.run("slow", session_id="s4")
        assert result.final_state == LoopState.FAILED
        assert "timeout" in str(result.error).lower()


# ============================================================================
# HumanInterruptNeeded exception
# ============================================================================

class TestHumanInterrupt:
    def test_exception_creation(self):
        e = HumanInterruptNeeded("approve delete", {"file": "/tmp/x"})
        assert str(e) == "approve delete"
        assert e.context == {"file": "/tmp/x"}

    def test_exception_no_context(self):
        e = HumanInterruptNeeded("need input")
        assert e.context == {}


# ============================================================================
# Checkpoint paths
# ============================================================================

class TestCheckpoints:
    @pytest.mark.asyncio
    async def test_save_checkpoint_after_multiple_steps(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        cfg = LoopConfig(max_iterations=3, enable_checkpoints=True, checkpoint_interval=1,
                         enable_reflection=False, auto_select_model=False, enable_cost_tracking=False)
        store = AsyncMock()
        store.save = AsyncMock()
        store.load = AsyncMock(return_value=None)

        from unittest.mock import MagicMock
        resp_with_tools = MagicMock()
        resp_with_tools.content = "calling tool"
        resp_with_tools.tool_calls = [MagicMock()]
        resp_with_tools.usage = None

        resp_terminal = MagicMock()
        resp_terminal.content = "done"
        resp_terminal.tool_calls = []
        resp_terminal.usage = None

        mock_router.call = AsyncMock(side_effect=[resp_with_tools, resp_terminal])

        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr, config=cfg, checkpoint_store=store)
        await loop.run("task", session_id="ckpt-test")

        assert store.save.await_count >= 1

    @pytest.mark.asyncio
    async def test_checkpoint_disabled_does_not_call_store(self, mock_router, mock_tool_registry, mock_ctx_mgr):
        cfg = LoopConfig(enable_checkpoints=False, auto_select_model=False, enable_reflection=False, enable_cost_tracking=False)
        store = AsyncMock()

        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.content = "ok"
        resp.tool_calls = []
        resp.usage = None
        mock_router.call = AsyncMock(return_value=resp)

        loop = AgentLoop(mock_router, mock_tool_registry, mock_ctx_mgr, config=cfg, checkpoint_store=store)
        await loop.run("task", session_id="no-ckpt")

        store.save.assert_not_awaited()


# ============================================================================
# Swarm path
# ============================================================================

class TestSwarm:
    @pytest.mark.asyncio
    async def test_run_swarm_no_roles_returns_failed(self, loop):
        result = await loop.run_swarm("task", roles=None)
        assert result.final_state == LoopState.FAILED
        assert "No roles" in result.error


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    def test_step_timeout_error(self):
        e = StepTimeoutError("step 1 timeout")
        assert "step 1" in str(e)

    @pytest.mark.asyncio
    async def test_context_manager_gets_initialized(self, loop, mock_ctx_mgr):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.content = "ok"
        resp.tool_calls = []
        resp.usage = None
        loop.model_router.call = AsyncMock(return_value=resp)

        await loop.run("task", session_id="session-xyz")
        mock_ctx_mgr.init_session.assert_called_once_with("session-xyz", "task")
