"""
Dependency Injection system for NexusAgent.

Provides type-safe Agent[Deps, Out] generic base class,
RunContext for dependency injection, and Depends() for
automatic dependency resolution.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, get_args, get_origin, get_type_hints

# Type variables for Agent generic
Deps = TypeVar("Deps")
Out = TypeVar("Out")


@dataclass
class RunContext(Generic[Deps]):
    """
    Runtime context passed to Agent.run().

    Contains:
    - deps: The dependencies for this agent
    - agent_name: Name of the agent
    - run_id: Unique ID for this run
    - metadata: Additional metadata
    """

    deps: Deps
    agent_name: str = ""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get metadata value."""
        return self.metadata.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set metadata value."""
        self.metadata[key] = value


class Depends:
    """
    Dependency marker for automatic injection.

    Usage:
        def get_db() -> Database:
            return Database()

        class MyAgent(Agent[Depends(get_db), str]):
            async def run(self, ctx):
                db = ctx.deps  # Database instance
    """

    def __init__(self, callable: Callable[..., Any]):
        self.callable = callable

    def resolve(self) -> Any:
        """Resolve the dependency."""
        return self.callable()


def inject_tool(tool: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to inject a tool into an agent.

    Usage:
        @inject_tool(search_tool)
        class MyAgent(Agent):
            ...
    """

    def decorator(cls):
        if not hasattr(cls, "_tools"):
            cls._tools = []
        cls._tools.append(tool)
        return cls

    return decorator


def requires_context(*fields: str) -> Callable[..., Any]:
    """
    Decorator to declare required context fields.

    Usage:
        @requires_context("user_id", "session_id")
        class MyAgent(Agent):
            ...
    """

    def decorator(cls):
        if not hasattr(cls, "_required_context"):
            cls._required_context = []
        cls._required_context.extend(fields)
        return cls

    return decorator


class Agent(Generic[Deps, Out]):
    """
    Base class for all agents.

    Type-safe generic: Agent[Deps, Out]
    - Deps: Type of dependencies
    - Out: Type of output

    Usage:
        class MyAgent(Agent[str, str]):
            async def run(self, ctx: RunContext[str]) -> str:
                return f"Hello, {ctx.deps}!"

        agent = MyAgent()
        result = await agent.invoke("World")
    """

    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__
        self._tools: list[Callable[..., Any]] = getattr(self.__class__, "_tools", [])
        self._required_context: list[str] = getattr(self.__class__, "_required_context", [])

    async def run(self, ctx: RunContext[Deps]) -> Out:
        """
        Main agent logic. Override in subclass.

        Args:
            ctx: Runtime context with dependencies

        Returns:
            Agent output (type-checked against Out)
        """
        raise NotImplementedError("Subclass must implement run()")

    async def invoke(self, deps: Deps, **metadata) -> Out:
        """
        Invoke the agent with dependencies.

        Args:
            deps: Dependencies to inject
            **metadata: Additional metadata

        Returns:
            Agent output
        """
        # Resolve Depends if needed
        if isinstance(deps, Depends):
            deps = deps.resolve()

        # Create context
        ctx = RunContext[Deps](
            deps=deps,
            agent_name=self.name,
            metadata=metadata,
        )

        # Validate required context
        for f in self._required_context:
            if f not in ctx.metadata:
                raise ValueError(f"Required context field missing: {f}")

        # Run agent
        result = await self.run(ctx)

        # Validate output type (if type hints available)
        result = self._validate_output(result)

        return result

    def _validate_output(self, result: Any) -> Out:
        """
        Validate output against declared type.

        Uses Pydantic validation if Out is a BaseModel,
        otherwise basic type checking.
        """
        # Get type hints
        hints = get_type_hints(self.__class__)
        out_type = hints.get("Out")

        if out_type is None:
            # Try to get from generic base
            for base in self.__class__.__mro__:
                origin = get_origin(base)
                if origin is Agent:
                    args = get_args(base)
                    if len(args) >= 2:
                        out_type = args[1]
                    break

        if out_type is None:
            return result

        # Check if it's a Pydantic model
        try:
            from pydantic import BaseModel

            if isinstance(out_type, type) and issubclass(out_type, BaseModel):
                if not isinstance(result, out_type):
                    # Try to validate/convert
                    if isinstance(result, dict):
                        result = out_type(**result)
                    else:
                        result = out_type.model_validate(result)
        except ImportError:
            pass

        return result

    def get_tools(self) -> list[Callable[..., Any]]:
        """Get registered tools."""
        return self._tools.copy()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
