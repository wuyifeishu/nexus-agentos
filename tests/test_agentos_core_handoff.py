"""Tests for agentos.core.handoff — Swarm-style task transfer."""

from __future__ import annotations

import pytest

from agentos.core.di import Agent, RunContext
from agentos.core.handoff import (
    Handoff,
    HandoffAwareAgent,
    HandoffResult,
    can_handle,
    execute_with_handoff,
    transfer_to,
)

# ============================================================================
# Minimal Agent Stubs
# ============================================================================

class MinimalAgent(Agent[str, str]):
    """Simple agent for testing handoff."""
    _required_context: list[str] = []

    def __init__(self, name="minimal", response="done"):
        self.name = name
        self._response = response

    async def run(self, ctx: RunContext[str]) -> str:
        return self._response


class CanHandleAgent(Agent[str, str]):
    """Agent with custom can_handle logic."""
    _required_context: list[str] = []

    def __init__(self, name="capable", domain="general"):
        self.name = name
        self._domain = domain

    def can_handle(self, input_data):
        return input_data == self._domain

    async def run(self, ctx: RunContext[str]) -> str:
        return f"handled {self._domain}"


class HandoffAgent(Agent[str, str]):
    """Agent that always performs a handoff."""
    _required_context: list[str] = []

    def __init__(self, target, name="router"):
        self.name = name
        self._target = target

    async def run(self, ctx: RunContext[str]) -> str | Handoff:
        return transfer_to(self._target, ctx.deps, reason="routing")


# ============================================================================
# Handoff
# ============================================================================

class TestHandoff:
    def test_create_handoff(self):
        target = MinimalAgent()
        h = Handoff(target_agent=target, input_data="hello", reason="test")
        assert h.target_agent is target
        assert h.input_data == "hello"
        assert h.reason == "test"

    def test_none_target_agent_raises(self):
        with pytest.raises(ValueError, match="target_agent cannot be None"):
            Handoff(target_agent=None, input_data="test")

    def test_metadata_passed(self):
        target = MinimalAgent()
        h = Handoff(target_agent=target, input_data="x", metadata={"key": "val"})
        assert h.metadata["key"] == "val"

    def test_default_values(self):
        target = MinimalAgent()
        h = Handoff(target_agent=target, input_data="x")
        assert h.reason == ""
        assert h.metadata == {}


# ============================================================================
# HandoffResult
# ============================================================================

class TestHandoffResult:
    def test_create_result(self):
        result = HandoffResult(
            output="done",
            source_agent="src",
            target_agent="tgt",
            handoff_chain=["src", "tgt"],
        )
        assert result.output == "done"
        assert result.source_agent == "src"
        assert result.target_agent == "tgt"
        assert result.handoff_chain == ["src", "tgt"]

    def test_default_chain(self):
        result = HandoffResult(output="ok", source_agent="a", target_agent="b")
        assert result.handoff_chain == []


# ============================================================================
# transfer_to
# ============================================================================

class TestTransferTo:
    def test_returns_handoff(self):
        target = MinimalAgent()
        result = transfer_to(target, "input", reason="because")
        assert isinstance(result, Handoff)
        assert result.target_agent is target
        assert result.input_data == "input"
        assert result.reason == "because"

    def test_with_metadata(self):
        target = MinimalAgent()
        result = transfer_to(target, "input", reason="test", prio="high")
        assert result.metadata["prio"] == "high"


# ============================================================================
# can_handle
# ============================================================================

class TestCanHandle:
    def test_agent_with_can_handle_matching(self):
        agent = CanHandleAgent(domain="billing")
        assert can_handle(agent, "billing") is True

    def test_agent_with_can_handle_mismatch(self):
        agent = CanHandleAgent(domain="billing")
        assert can_handle(agent, "support") is False

    def test_agent_without_can_handle(self):
        agent = MinimalAgent()
        assert can_handle(agent, "anything") is True


# ============================================================================
# execute_with_handoff
# ============================================================================

class TestExecuteWithHandoff:
    @pytest.mark.asyncio
    async def test_direct_result_no_handoff(self):
        agent = MinimalAgent(response="hello world")
        result = await execute_with_handoff(agent, "anything")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_single_handoff(self):
        target = MinimalAgent(response="routed result")
        router = HandoffAgent(target=target)
        result = await execute_with_handoff(router, "request")
        assert isinstance(result, HandoffResult)
        assert result.output == "routed result"
        assert result.source_agent == "router"
        assert result.target_agent == "minimal"
        assert len(result.handoff_chain) >= 2

    @pytest.mark.asyncio
    async def test_multi_hop_handoff(self):
        agent_c = MinimalAgent(name="agent_c", response="final")
        agent_b = HandoffAgent(target=agent_c, name="agent_b")
        agent_a = HandoffAgent(target=agent_b, name="agent_a")
        result = await execute_with_handoff(agent_a, "start")
        assert isinstance(result, HandoffResult)
        assert result.output == "final"
        assert result.source_agent == "agent_a"
        assert result.target_agent == "agent_c"
        assert result.handoff_chain == ["agent_a", "agent_b", "agent_c"]

    @pytest.mark.asyncio
    async def test_max_hops_exceeded(self):
        # Circular reference: a → b → c → a
        agent_c = MinimalAgent(name="agent_c", response="loop")
        agent_b = HandoffAgent(target=agent_c, name="agent_b")
        agent_a = HandoffAgent(target=agent_b, name="agent_a")
        # Redefine agent_c to handoff back to agent_a
        class LoopingAgent(Agent[str, str]):
            _required_context: list[str] = []

            def __init__(self):
                self.name = "agent_c"

            async def run(self, ctx: RunContext[str]) -> Handoff:
                return transfer_to(agent_a, ctx.deps, reason="loop")

        agent_c = LoopingAgent()
        agent_b._target = agent_c

        with pytest.raises(RuntimeError, match="Max handoff hops"):
            await execute_with_handoff(agent_a, "start", max_hops=5)


# ============================================================================
# HandoffAwareAgent
# ============================================================================

class TestHandoffAwareAgent:
    def test_can_handle_default(self):
        agent = HandoffAwareAgent()
        agent.name = "test"
        assert agent.can_handle("anything") is True

    @pytest.mark.asyncio
    async def test_run_raises_not_implemented(self):
        agent = HandoffAwareAgent()
        agent.name = "test"
        with pytest.raises(NotImplementedError):
            await agent.run(RunContext(deps="test"))
