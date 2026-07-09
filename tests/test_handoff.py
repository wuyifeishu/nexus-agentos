"""Test Handoff — Swarm-style agent-to-agent task transfer protocol."""

from __future__ import annotations

import pytest

from agentos.core.di import RunContext
from agentos.core.handoff import (
    Handoff,
    HandoffAwareAgent,
    HandoffResult,
    can_handle,
    execute_with_handoff,
    transfer_to,
)

# ============================================================================
# Minimal agent stubs
# ============================================================================

class StubAgent:
    """Minimal Agent stub for handoff testing."""
    name: str = "stub"

    def __init__(self, name="stub", can_handle_result=True, response="default"):
        self.name = name
        self._can_handle = can_handle_result
        self._response = response

    async def invoke(self, input_data, **metadata):
        return self._response

    def can_handle(self, input_data):
        return self._can_handle


class ChainAgent(StubAgent):
    """Agent that returns a Handoff to another agent."""
    def __init__(self, name, handoff_target, name_for_target="target"):
        super().__init__(name=name)
        self._handoff_target = handoff_target

    async def invoke(self, input_data, **metadata):
        return transfer_to(
            self._handoff_target,
            input_data,
            reason=f"{self.name} delegates",
        )


# ============================================================================
# Handoff dataclass
# ============================================================================

class TestHandoff:
    def test_creation(self):
        target = StubAgent(name="target")
        h = Handoff(target_agent=target, input_data="hello", reason="test")
        assert h.target_agent == target
        assert h.input_data == "hello"
        assert h.reason == "test"
        assert h.metadata == {}

    def test_creation_with_metadata(self):
        target = StubAgent(name="target")
        h = Handoff(target_agent=target, input_data=42, metadata={"key": "val"})
        assert h.metadata == {"key": "val"}

    def test_none_target_raises(self):
        with pytest.raises(ValueError, match="target_agent"):
            Handoff(target_agent=None, input_data="x")


# ============================================================================
# HandoffResult dataclass
# ============================================================================

class TestHandoffResult:
    def test_creation(self):
        r = HandoffResult(
            output="done",
            source_agent="a",
            target_agent="b",
            handoff_chain=["a", "b"],
            metadata={"hop": 1},
        )
        assert r.output == "done"
        assert r.source_agent == "a"
        assert r.target_agent == "b"
        assert r.handoff_chain == ["a", "b"]

    def test_defaults(self):
        r = HandoffResult(output="ok", source_agent="src", target_agent="tgt")
        assert r.handoff_chain == []
        assert r.metadata == {}


# ============================================================================
# transfer_to helper
# ============================================================================

class TestTransferTo:
    def test_returns_handoff(self):
        target = StubAgent(name="billing")
        result = transfer_to(target, "invoice #42", reason="billing", priority="high")
        assert isinstance(result, Handoff)
        assert result.target_agent == target
        assert result.input_data == "invoice #42"
        assert result.reason == "billing"
        assert result.metadata == {"priority": "high"}


# ============================================================================
# can_handle helper
# ============================================================================

class TestCanHandle:
    def test_returns_true_when_agent_has_method(self):
        a = StubAgent(can_handle_result=True)
        assert can_handle(a, "anything") is True

    def test_returns_false_when_agent_rejects(self):
        a = StubAgent(can_handle_result=False)
        assert can_handle(a, "anything") is False

    def test_returns_true_when_no_can_handle_method(self):
        class NoCanHandle:
            name = "noop"
        a = NoCanHandle()
        assert can_handle(a, "anything") is True


# ============================================================================
# execute_with_handoff — basic (no handoff)
# ============================================================================

class TestExecuteWithHandoffBasic:
    @pytest.mark.asyncio
    async def test_returns_raw_output_when_no_handoff(self):
        """No handoff — returns the agent's raw output."""
        agent = StubAgent(name="simple", response="direct output")
        result = await execute_with_handoff(agent, "task")
        assert result == "direct output"

    @pytest.mark.asyncio
    async def test_returns_handoff_result_for_single_hop(self):
        """Single handoff → HandoffResult with chain and final output."""
        target = StubAgent(name="target", response="final answer")
        source = ChainAgent(name="source", handoff_target=target)
        result = await execute_with_handoff(source, "task")
        assert isinstance(result, HandoffResult)
        assert result.output == "final answer"
        assert result.handoff_chain == ["source", "target"]
        assert result.source_agent == "source"
        assert result.target_agent == "target"

    @pytest.mark.asyncio
    async def test_multi_hop(self):
        """Multi-hop handoff → full chain reflected in HandoffResult."""
        c = StubAgent(name="c", response="deep result")
        b = ChainAgent(name="b", handoff_target=c)
        a = ChainAgent(name="a", handoff_target=b)
        result = await execute_with_handoff(a, "task")
        assert isinstance(result, HandoffResult)
        assert result.output == "deep result"
        assert result.handoff_chain == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_max_hops_exceeded(self):
        """Exceeding max_hops raises RuntimeError."""
        d = StubAgent(name="d", response="end")
        c = ChainAgent(name="c", handoff_target=d)
        b = ChainAgent(name="b", handoff_target=c)
        a = ChainAgent(name="a", handoff_target=b)
        with pytest.raises(RuntimeError, match="Max handoff"):
            await execute_with_handoff(a, "task", max_hops=2)

    @pytest.mark.asyncio
    async def test_metadata_merges_across_hops(self):
        """Metadata from handoffs should be merged into the final result."""

        class InnerMeta:
            name = "inner"

            async def invoke(self, input_data, **metadata):
                return "done"

        class MetaAgent:
            name = "meta"

            async def invoke(self, input_data, **metadata):
                return transfer_to(
                    InnerMeta(),
                    input_data,
                    extra_key="extra_val",
                )

        result = await execute_with_handoff(MetaAgent(), "task", initial_meta="init")
        assert isinstance(result, HandoffResult)
        assert result.output == "done"
        assert result.metadata.get("extra_key") == "extra_val"
        assert result.metadata.get("initial_meta") == "init"


# ============================================================================
# HandoffAwareAgent base class
# ============================================================================

class TestHandoffAwareAgent:
    def test_can_handle_defaults_true(self):
        agent = HandoffAwareAgent(name="aware")
        assert agent.can_handle("anything") is True

    def test_run_raises_not_implemented(self):
        agent = HandoffAwareAgent(name="aware")
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.run(agent.run(RunContext(deps={"data": "x"})))

    def test_can_handle_override(self):
        class Picky(HandoffAwareAgent):
            name = "picky"
            def can_handle(self, input_data):
                return "billing" in str(input_data)

        agent = Picky()
        assert agent.can_handle("billing question") is True
        assert agent.can_handle("support question") is False
