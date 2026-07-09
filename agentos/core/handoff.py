"""
Handoff protocol for NexusAgent.

Provides Swarm-style task transfer between agents.
When an agent cannot handle a request, it can transfer
to another agent that is better suited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

from agentos.core.di import Agent, RunContext

# Type variable for agent
T = TypeVar("T")


@dataclass
class Handoff:
    """
    Represents a handoff request to another agent.

    Usage:
        class SupportAgent(Agent[str, str]):
            async def run(self, ctx: RunContext[str]) -> str | Handoff:
                if "billing" in ctx.deps.lower():
                    return transfer_to(BillingAgent(), ctx.deps)
                return "General support"
    """

    target_agent: Agent[Any, Any]
    input_data: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self):
        """Validate handoff."""
        if self.target_agent is None:
            raise ValueError("target_agent cannot be None")


@dataclass
class HandoffResult:
    """
    Result of a handoff operation.

    Contains:
    - output: The final output from the target agent
    - source_agent: Name of the original agent
    - target_agent: Name of the agent that handled it
    - handoff_chain: List of agents involved
    """

    output: Any
    source_agent: str
    target_agent: str
    handoff_chain: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def transfer_to(agent: Agent[Any, Any], input_data: Any, reason: str = "", **metadata) -> Handoff:
    """
    Create a handoff to another agent.

    Args:
        agent: Target agent to transfer to
        input_data: Data to pass to the target agent
        reason: Reason for the handoff
        **metadata: Additional metadata

    Returns:
        Handoff object

    Usage:
        return transfer_to(BillingAgent(), ctx.deps, reason="Billing question")
    """
    return Handoff(
        target_agent=agent,
        input_data=input_data,
        metadata=metadata,
        reason=reason,
    )


def can_handle(agent: Agent[Any, Any], input_data: Any) -> bool:
    """
    Check if an agent can handle the input.

    This is a helper function that calls the agent's
    can_handle() method if it exists, otherwise returns True.

    Args:
        agent: Agent to check
        input_data: Input data

    Returns:
        True if agent can handle, False otherwise
    """
    if hasattr(agent, "can_handle"):
        return agent.can_handle(input_data)
    return True


async def execute_with_handoff(
    agent: Agent[Any, Any], input_data: Any, max_hops: int = 10, **metadata
) -> HandoffResult | Any:
    """
    Execute an agent with automatic handoff handling.

    If the agent returns a Handoff, automatically execute
    the target agent and return the result.

    Args:
        agent: Starting agent
        input_data: Input data
        max_hops: Maximum number of handoffs
        **metadata: Additional metadata

    Returns:
        HandoffResult if handoffs occurred, otherwise raw output

    Raises:
        RuntimeError: If max_hops exceeded
    """
    current_agent = agent
    current_input = input_data
    handoff_chain = [current_agent.name]

    for hop in range(max_hops):
        # Execute current agent
        result = await current_agent.invoke(current_input, **metadata)

        # Check if result is a handoff
        if isinstance(result, Handoff):
            # Move to next agent
            current_agent = result.target_agent
            current_input = result.input_data
            handoff_chain.append(current_agent.name)

            # Merge metadata
            metadata.update(result.metadata)
        else:
            # No handoff, we're done
            if len(handoff_chain) > 1:
                # Return HandoffResult if we had handoffs
                return HandoffResult(
                    output=result,
                    source_agent=handoff_chain[0],
                    target_agent=handoff_chain[-1],
                    handoff_chain=handoff_chain,
                    metadata=metadata,
                )
            else:
                # No handoffs, return raw output
                return result

    raise RuntimeError(f"Max handoff hops ({max_hops}) exceeded")


class HandoffAwareAgent(Agent[Any, Any]):
    """
    Base class for agents that support handoffs.

    Provides can_handle() method for checking if agent
    can handle input, and run() can return Handoff.
    """

    def can_handle(self, input_data: Any) -> bool:
        """
        Check if this agent can handle the input.

        Override in subclass to add custom logic.

        Args:
            input_data: Input data

        Returns:
            True if can handle, False otherwise
        """
        return True

    async def run(self, ctx: RunContext[Any]) -> Any:
        """
        Main agent logic. Can return Handoff to transfer.

        Override in subclass.
        """
        raise NotImplementedError("Subclass must implement run()")


# ── Auto-generated compat stubs ──
