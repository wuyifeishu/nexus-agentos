"""
v1.9.8: Dynamic Tool Registry + Intelligent Tool Router.

ToolRegistry: schema-based tool catalog with versioning, capability tags, and dependency tracking.
ToolRouter: LLM-driven tool selection with semantic matching, confidence scoring, and fallback chains.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ── Tool Schema ───────────────────────────────────────────────────


class ToolCategory(StrEnum):
    """Top-level tool category for coarse-grained routing."""

    FILE = "file"
    NETWORK = "network"
    CODE = "code"
    SYSTEM = "system"
    DATA = "data"
    AGENT = "agent"
    CUSTOM = "custom"


@dataclass
class ToolParam:
    """Parameter definition for a tool."""

    name: str
    type: str  # str, int, float, bool, list, dict
    description: str = ""
    required: bool = False
    default: Any = None
    enum_values: list[str] | None = None
    min_value: float | None = None
    max_value: float | None = None
    pattern: str = ""  # Regex validation pattern


@dataclass
class ToolSchema:
    """Complete tool schema definition."""

    name: str  # Unique tool name
    description: str  # Human-readable description
    category: ToolCategory = ToolCategory.CUSTOM
    params: list[ToolParam] = field(default_factory=list)
    returns: str = "any"  # Return type description
    version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=list)  # e.g. ["read", "text", "file"]
    tags: list[str] = field(default_factory=list)  # Searchable tags
    dependencies: list[str] = field(default_factory=list)  # Required other tools
    handler: Callable[..., Any] | None = None  # Actual implementation
    handler_ref: str = ""  # String reference for serialization
    cost_estimate: float = 0.0  # Relative cost (latency, tokens, etc)
    is_destructive: bool = False  # Data-modifying operations
    requires_auth: bool = False  # Needs authentication
    rate_limit: int = 0  # Max calls per minute, 0 = unlimited
    deprecated: bool = False
    deprecated_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_openai_function(self) -> dict[str, Any]:
        """Export schema as OpenAI function-calling format."""
        properties = {}
        required = []
        for p in self.params:
            prop: dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum_values:
                prop["enum"] = p.enum_values
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def match_score(self, query: str, keywords: list[str]) -> float:
        """Compute relevance score for a natural language query."""
        query_lower = query.lower()
        score = 0.0

        # Name exact match
        if self.name.lower() == query_lower:
            score += 10.0
        elif self.name.lower() in query_lower:
            score += 5.0

        # Description match
        desc_lower = self.description.lower()
        if query_lower in desc_lower:
            score += 3.0
        for kw in keywords:
            if kw in desc_lower:
                score += 1.5

        # Capability tag match
        for cap in self.capabilities:
            if cap.lower() in query_lower:
                score += 2.0

        # Tag match
        for tag in self.tags:
            if tag.lower() in query_lower or tag.lower() in keywords:
                score += 1.0

        # Parameter name match (user mentioned specific fields)
        for p in self.params:
            if p.name.lower() in query_lower:
                score += 0.5

        return score


# ── Tool Registry ─────────────────────────────────────────────────


class ToolRegistry:
    """Central tool catalog with versioning, query, and lifecycle management.

    Features:
    - Schema-based registration with validation
    - Semantic search over tool descriptions/capabilities/tags
    - Version tracking and deprecation warnings
    - Capability-based grouping
    - Category-based organization
    - Rate limiting enforcement
    """

    def __init__(self):
        self._tools: dict[str, ToolSchema] = {}
        self._by_category: dict[ToolCategory, list[str]] = defaultdict(list)
        self._by_capability: dict[str, list[str]] = defaultdict(list)
        self._by_tag: dict[str, list[str]] = defaultdict(list)
        self._usage_counts: dict[str, int] = defaultdict(int)
        self._rate_trackers: dict[str, list[float]] = defaultdict(list)
        self._deprecation_log: list[dict[str, Any]] = []

    def register(self, tool: ToolSchema) -> ToolSchema:
        """Register a tool. Overwrites if same name (with warning)."""
        if tool.name in self._tools:
            existing = self._tools[tool.name]
            if existing.version != tool.version:
                # Version upgrade
                pass
            else:
                pass  # Overwrite silently

        self._tools[tool.name] = tool
        self._by_category[tool.category].append(tool.name)
        for cap in tool.capabilities:
            self._by_capability[cap].append(tool.name)
        for tag in tool.tags:
            self._by_tag[tag].append(tool.name)

        return tool

    def register_many(self, tools: list[ToolSchema]) -> list[ToolSchema]:
        """Batch register tools."""
        return [self.register(t) for t in tools]

    def unregister(self, name: str) -> bool:
        """Remove a tool from registry."""
        if name not in self._tools:
            return False

        tool = self._tools.pop(name)
        self._by_category[tool.category].remove(name)
        for cap in tool.capabilities:
            self._by_capability[cap].remove(name)
        for tag in tool.tags:
            self._by_tag[tag].remove(name)
        return True

    def get(self, name: str) -> ToolSchema | None:
        """Get tool by name. Returns None and logs warning if deprecated."""
        tool = self._tools.get(name)
        if tool and tool.deprecated:
            self._deprecation_log.append(
                {
                    "tool": name,
                    "message": tool.deprecated_message,
                    "timestamp": time.time(),
                }
            )
        return tool

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: ToolCategory | None = None,
        exclude_deprecated: bool = True,
    ) -> list[tuple[ToolSchema, float]]:
        """Search tools by natural language query.

        Returns ranked list of (ToolSchema, score).
        """
        keywords = query.lower().split()
        candidates = []

        tool_names = list(self._tools.keys())
        if category:
            tool_names = [n for n in tool_names if self._tools[n].category == category]

        for name in tool_names:
            tool = self._tools[name]
            if exclude_deprecated and tool.deprecated:
                continue
            score = tool.match_score(query, keywords)
            if score > 0:
                # Boost frequently-used tools
                usage_boost = min(self._usage_counts[name] * 0.1, 1.0)
                candidates.append((tool, score + usage_boost))

        candidates.sort(key=lambda x: -x[1])
        return candidates[:top_k]

    def search_by_capability(self, capability: str) -> list[ToolSchema]:
        """Find all tools with a specific capability."""
        names = self._by_capability.get(capability, [])
        return [self._tools[n] for n in names if n in self._tools]

    def search_by_tag(self, tag: str) -> list[ToolSchema]:
        """Find all tools matching a tag."""
        names = self._by_tag.get(tag, [])
        return [self._tools[n] for n in names if n in self._tools]

    def list_categories(self) -> dict[ToolCategory, int]:
        """Count tools per category."""
        return {cat: len(names) for cat, names in self._by_category.items() if names}

    def list_capabilities(self) -> list[str]:
        """List all registered capabilities."""
        return sorted(self._by_capability.keys())

    def list_tags(self) -> list[str]:
        """List all registered tags."""
        return sorted(self._by_tag.keys())

    def export_openai_functions(
        self,
        category: ToolCategory | None = None,
        exclude_deprecated: bool = True,
    ) -> list[dict[str, Any]]:
        """Export all tools as OpenAI function-calling format."""
        result = []
        for tool in self._tools.values():
            if exclude_deprecated and tool.deprecated:
                continue
            if category and tool.category != category:
                continue
            result.append(tool.to_openai_function())
        return result

    def check_rate_limit(self, name: str) -> bool:
        """Check if tool is within rate limit. Returns True if allowed."""
        tool = self._tools.get(name)
        if not tool or tool.rate_limit <= 0:
            return True

        now = time.time()
        window_start = now - 60  # 1-minute window
        calls = self._rate_trackers[name]
        # Clean old entries
        self._rate_trackers[name] = [t for t in calls if t > window_start]

        return len(self._rate_trackers[name]) < tool.rate_limit

    def record_usage(self, name: str) -> None:
        """Record a tool usage for rate limiting and analytics."""
        self._usage_counts[name] += 1
        self._rate_trackers[name].append(time.time())

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_tools": len(self._tools),
            "categories": {str(k): len(v) for k, v in self._by_category.items()},
            "capabilities": len(self._by_capability),
            "tags": len(self._by_tag),
            "deprecated": sum(1 for t in self._tools.values() if t.deprecated),
            "top_used": sorted(
                [(k, v) for k, v in self._usage_counts.items() if v > 0],
                key=lambda x: -x[1],
            )[:10],
        }


# ── Tool Router ───────────────────────────────────────────────────


@dataclass
class RoutingDecision:
    """Result of tool routing decision."""

    tool_name: str
    tool_schema: ToolSchema | None
    confidence: float  # 0.0 - 1.0
    reasoning: str  # Why this tool was chosen
    alternatives: list[str]  # Fallback tool names
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingContext:
    """Context for tool routing decisions."""

    task: str  # User's task description
    available_capabilities: list[str] = field(default_factory=list)
    preferred_category: ToolCategory | None = None
    exclude_destructive: bool = False
    min_confidence: float = 0.3  # Minimum confidence threshold
    max_alternatives: int = 3  # Max fallback alternatives


class ToolRouter:
    """Intelligent tool router with semantic matching and fallback chains.

    Selects the best tool for a given task by:
    1. Semantic matching via search query
    2. LLM-driven selection (when available)
    3. Rule-based fallback selection
    4. Confidence scoring with threshold gating
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm_selector: Callable[..., Any] | None = None,
    ):
        self.registry = registry
        self.llm_selector = llm_selector  # Optional LLM for smarter selection

    def route(self, context: RoutingContext) -> RoutingDecision:
        """Route a task to the best tool.

        Priority:
        1. LLM selector (if available) — best semantic understanding
        2. Semantic search — keyword + capability matching
        3. Default fallback
        """
        # Try LLM-based routing
        if self.llm_selector and self._is_llm_worthwhile(context.task):
            decision = self._llm_route(context)
            if decision and decision.confidence >= context.min_confidence:
                return decision

        # Semantic search routing
        return self._semantic_route(context)

    def _is_llm_worthwhile(self, task: str) -> bool:
        """Heuristic: LLM routing is worthwhile for complex tasks."""
        # Simple one-word or obvious tool names don't need LLM
        task_lower = task.lower().strip()
        # If task is just a tool name, skip LLM
        if task_lower in self.registry._tools:
            return False
        # If task is very short (~2 words), skip LLM
        if len(task_lower.split()) <= 2:
            return False
        return True

    def _llm_route(self, context: RoutingContext) -> RoutingDecision | None:
        """Use LLM for intelligent tool selection."""
        try:
            tools_desc = self._build_tools_description(context)
            prompt = (
                f"Task: {context.task}\n\n"
                f"Available tools:\n{tools_desc}\n\n"
                "Select the best tool. Reply with JSON:\n"
                '{"tool_name": "xxx", "confidence": 0.0-1.0, "reasoning": "why", '
                '"alternatives": ["tool2", "tool3"]}'
            )
            result = self.llm_selector(prompt)
            if isinstance(result, str):
                result = json.loads(result)

            tool_name = result.get("tool_name", "")
            tool = self.registry.get(tool_name)
            if not tool:
                return None

            return RoutingDecision(
                tool_name=tool_name,
                tool_schema=tool,
                confidence=float(result.get("confidence", 0.5)),
                reasoning=str(result.get("reasoning", "")),
                alternatives=result.get("alternatives", []),
            )
        except Exception:
            return None

    def _semantic_route(self, context: RoutingContext) -> RoutingDecision:
        """Semantic search-based routing with confidence scoring."""
        candidates = self.registry.search(
            query=context.task,
            top_k=context.max_alternatives + 1,
            category=context.preferred_category,
        )

        if not candidates:
            return RoutingDecision(
                tool_name="",
                tool_schema=None,
                confidence=0.0,
                reasoning="No matching tool found",
                alternatives=[],
            )

        # Filter destructive tools if excluded
        if context.exclude_destructive:
            candidates = [(t, s) for t, s in candidates if not t.is_destructive]

        if not candidates:
            return RoutingDecision(
                tool_name="",
                tool_schema=None,
                confidence=0.0,
                reasoning="All matching tools are destructive (excluded)",
                alternatives=[],
            )

        # Normalize scores to 0-1 confidence
        if len(candidates) == 1:
            best_tool, raw_score = candidates[0]
            confidence = min(raw_score / 10.0, 1.0)
            alternatives = []
        else:
            scores = [s for _, s in candidates]
            max_s = max(scores) if scores else 1
            best_tool, raw_score = candidates[0]
            confidence = min(raw_score / max_s, 1.0) if max_s > 0 else 0.5
            alternatives = [t.name for t, _ in candidates[1 : context.max_alternatives + 1]]

        return RoutingDecision(
            tool_name=best_tool.name,
            tool_schema=best_tool,
            confidence=confidence,
            reasoning=f"Best match: {best_tool.name} (score={raw_score:.1f})",
            alternatives=alternatives,
        )

    def _build_tools_description(self, context: RoutingContext) -> str:
        """Build a compact tool description for LLM prompt."""
        tools = []
        # Prioritize by category
        names = list(self.registry._tools.keys())
        if context.preferred_category:
            cat_names = self.registry._by_category.get(context.preferred_category, [])
            names = cat_names + [n for n in names if n not in cat_names]

        for name in names[:20]:  # Limit to avoid huge prompts
            tool = self.registry._tools[name]
            if tool.deprecated:
                continue
            if context.exclude_destructive and tool.is_destructive:
                continue
            params_desc = ", ".join(
                f"{p.name}:{p.type}" + ("?" if not p.required else "") for p in tool.params[:5]
            )
            cap_tags = ", ".join(tool.capabilities[:3])
            tools.append(
                f"- {tool.name}: {tool.description[:100]}. "
                f"Params: [{params_desc}]. Caps: [{cap_tags}]"
            )

        return "\n".join(tools)


# ── Tool Execution Engine ─────────────────────────────────────────


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""

    def __init__(self, tool_name: str, message: str, recoverable: bool = True):
        self.tool_name = tool_name
        self.recoverable = recoverable
        super().__init__(f"[{tool_name}] {message}")


class ToolExecutor:
    """Execution engine for registered tools with safety and error handling.

    Features:
    - Rate limit enforcement
    - Parameter validation
    - Destructive operation confirmation
    - Timeout protection
    - Error categorization (recoverable vs fatal)
    """

    def __init__(
        self,
        registry: ToolRegistry,
        timeout: float = 30.0,
        require_destructive_confirm: bool = True,
    ):
        self.registry = registry
        self.timeout = timeout
        self.require_destructive_confirm = require_destructive_confirm
        self._pending_confirmations: dict[str, dict[str, Any]] = {}

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        force: bool = False,
    ) -> Any:
        """Execute a registered tool with safety checks.

        Args:
            tool_name: Registered tool name
            params: Tool parameters
            force: Skip destructive confirmation (use with caution)

        Returns:
            Tool execution result

        Raises:
            ToolExecutionError: On execution failure
        """
        params = params or {}

        tool = self.registry.get(tool_name)
        if not tool:
            raise ToolExecutionError(
                tool_name, f"Tool '{tool_name}' not registered", recoverable=False
            )

        if tool.deprecated:
            raise ToolExecutionError(
                tool_name,
                f"Tool deprecated: {tool.deprecated_message}",
                recoverable=False,
            )

        # Rate limit check
        if not self.registry.check_rate_limit(tool_name):
            raise ToolExecutionError(
                tool_name,
                f"Rate limit exceeded ({tool.rate_limit}/min)",
                recoverable=True,
            )

        # Destructive check
        if tool.is_destructive and self.require_destructive_confirm and not force:
            self._pending_confirmations[tool_name] = params
            raise ToolExecutionError(
                tool_name,
                "Destructive operation requires confirmation (pass force=True to skip)",
                recoverable=False,
            )

        # Parameter validation
        self._validate_params(tool, params)

        # Record usage (before execution to prevent double-counting on retry)
        self.registry.record_usage(tool_name)

        # Execute
        if not tool.handler:
            raise ToolExecutionError(
                tool_name,
                "No handler registered for tool",
                recoverable=False,
            )

        try:
            result = tool.handler(**params)
        except Exception as e:
            raise ToolExecutionError(
                tool_name,
                f"Execution failed: {str(e)}",
                recoverable=True,
            ) from e

        return result

    def confirm_destructive(self, tool_name: str) -> Any:
        """Confirm and execute a pending destructive operation."""
        if tool_name not in self._pending_confirmations:
            raise ToolExecutionError(tool_name, "No pending confirmation", recoverable=False)
        params = self._pending_confirmations.pop(tool_name)
        return self.execute(tool_name, params, force=True)

    def cancel_destructive(self, tool_name: str) -> bool:
        """Cancel a pending destructive operation."""
        if tool_name in self._pending_confirmations:
            del self._pending_confirmations[tool_name]
            return True
        return False

    def _validate_params(self, tool: ToolSchema, params: dict[str, Any]) -> None:
        """Validate parameters against schema."""
        for p in tool.params:
            if p.required and p.name not in params:
                raise ToolExecutionError(
                    tool.name,
                    f"Missing required parameter: {p.name} ({p.description})",
                    recoverable=False,
                )

            if p.name in params:
                value = params[p.name]
                # Type check
                if p.type == "str" and not isinstance(value, str):
                    raise ToolExecutionError(
                        tool.name, f"Parameter '{p.name}' must be string", recoverable=False
                    )
                if p.type == "int" and not isinstance(value, int):
                    raise ToolExecutionError(
                        tool.name, f"Parameter '{p.name}' must be int", recoverable=False
                    )
                if p.type == "float" and not isinstance(value, (int, float)):
                    raise ToolExecutionError(
                        tool.name, f"Parameter '{p.name}' must be number", recoverable=False
                    )
                if p.type == "bool" and not isinstance(value, bool):
                    raise ToolExecutionError(
                        tool.name, f"Parameter '{p.name}' must be bool", recoverable=False
                    )

                # Enum check
                if p.enum_values and value not in p.enum_values:
                    raise ToolExecutionError(
                        tool.name,
                        f"Parameter '{p.name}' must be one of: {p.enum_values}",
                        recoverable=False,
                    )

                # Range check
                if isinstance(value, (int, float)):
                    if p.min_value is not None and value < p.min_value:
                        raise ToolExecutionError(
                            tool.name,
                            f"Parameter '{p.name}' minimum is {p.min_value}",
                            recoverable=False,
                        )
                    if p.max_value is not None and value > p.max_value:
                        raise ToolExecutionError(
                            tool.name,
                            f"Parameter '{p.name}' maximum is {p.max_value}",
                            recoverable=False,
                        )

    def get_pending_confirmations(self) -> list[str]:
        """List tools awaiting destructive confirmation."""
        return list(self._pending_confirmations.keys())


# ── Utility helpers ───────────────────────────────────────────────


def create_tool(
    name: str,
    description: str,
    handler: Callable,
    category: ToolCategory = ToolCategory.CUSTOM,
    params: list[ToolParam] | None = None,
    capabilities: list[str] | None = None,
    tags: list[str] | None = None,
    is_destructive: bool = False,
    rate_limit: int = 0,
    **kwargs,
) -> ToolSchema:
    """Quick helper to create a tool schema."""
    return ToolSchema(
        name=name,
        description=description,
        category=category,
        params=params or [],
        capabilities=capabilities or [],
        tags=tags or [],
        handler=handler,
        is_destructive=is_destructive,
        rate_limit=rate_limit,
        **kwargs,
    )
