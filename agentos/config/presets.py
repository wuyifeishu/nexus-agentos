"""
Config Presets — Ready-to-use configuration profiles for common AgentOS scenarios.

Each preset provides sensible defaults for specific use cases:
development, production, testing, and budget-constrained environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentOSPreset:
    """A named preset configuration for AgentOS."""

    name: str
    description: str
    model: str = "gpt-4o-mini"
    max_iterations: int = 10
    temperature: float = 0.7
    enable_cache: bool = True
    enable_rate_limit: bool = True
    enable_guardrails: bool = False
    enable_streaming: bool = False
    enable_cost_tracking: bool = True
    memory_window_size: int = 20
    max_retries: int = 3
    log_level: str = "INFO"


PRESETS: dict[str, AgentOSPreset] = {
    "development": AgentOSPreset(
        name="development",
        description="Local development with verbose logging, guardrails disabled, and GPT-4o-mini for fast iteration.",
        model="gpt-4o-mini",
        max_iterations=15,
        temperature=0.8,
        enable_cache=True,
        enable_rate_limit=False,
        enable_guardrails=False,
        enable_streaming=True,
        enable_cost_tracking=True,
        memory_window_size=30,
        max_retries=2,
        log_level="DEBUG",
    ),
    "production": AgentOSPreset(
        name="production",
        description="Production deployment with guardrails, rate limiting, and cost tracking. Uses GPT-4o for reliability.",
        model="gpt-4o",
        max_iterations=20,
        temperature=0.3,
        enable_cache=True,
        enable_rate_limit=True,
        enable_guardrails=True,
        enable_streaming=False,
        enable_cost_tracking=True,
        memory_window_size=50,
        max_retries=5,
        log_level="WARNING",
    ),
    "testing": AgentOSPreset(
        name="testing",
        description="Testing environment with determinism (temperature=0), guardrails off, and mock-friendly settings.",
        model="gpt-4o-mini",
        max_iterations=5,
        temperature=0.0,
        enable_cache=False,
        enable_rate_limit=False,
        enable_guardrails=False,
        enable_streaming=False,
        enable_cost_tracking=False,
        memory_window_size=10,
        max_retries=1,
        log_level="ERROR",
    ),
    "budget": AgentOSPreset(
        name="budget",
        description="Cost-optimized: GPT-4o-mini, minimal iterations, aggressive caching, rate limits enabled.",
        model="gpt-4o-mini",
        max_iterations=5,
        temperature=0.5,
        enable_cache=True,
        enable_rate_limit=True,
        enable_guardrails=True,
        enable_streaming=False,
        enable_cost_tracking=True,
        memory_window_size=10,
        max_retries=2,
        log_level="WARNING",
    ),
    "creative": AgentOSPreset(
        name="creative",
        description="Creative mode: high temperature, streaming, Claude 3.5 Sonnet for nuanced output.",
        model="claude-3.5-sonnet",
        max_iterations=12,
        temperature=0.95,
        enable_cache=True,
        enable_rate_limit=False,
        enable_guardrails=False,
        enable_streaming=True,
        enable_cost_tracking=True,
        memory_window_size=25,
        max_retries=3,
        log_level="INFO",
    ),
    "deep_research": AgentOSPreset(
        name="deep_research",
        description="Deep research: Claude 3 Opus, many iterations, large memory window, guardrails off for exploration.",
        model="claude-3-opus",
        max_iterations=30,
        temperature=0.4,
        enable_cache=True,
        enable_rate_limit=True,
        enable_guardrails=False,
        enable_streaming=False,
        enable_cost_tracking=True,
        memory_window_size=80,
        max_retries=5,
        log_level="INFO",
    ),
    "gemini_fast": AgentOSPreset(
        name="gemini_fast",
        description="High-speed: Gemini 2.0 Flash, many iterations, streaming enabled, minimal cost.",
        model="gemini-2.0-flash",
        max_iterations=25,
        temperature=0.7,
        enable_cache=True,
        enable_rate_limit=True,
        enable_guardrails=True,
        enable_streaming=True,
        enable_cost_tracking=True,
        memory_window_size=40,
        max_retries=4,
        log_level="INFO",
    ),
    "gemini_pro": AgentOSPreset(
        name="gemini_pro",
        description="Gemini Pro with 2M context: massive memory window, guardrails enabled, streaming.",
        model="gemini-1.5-pro",
        max_iterations=20,
        temperature=0.5,
        enable_cache=True,
        enable_rate_limit=True,
        enable_guardrails=True,
        enable_streaming=True,
        enable_cost_tracking=True,
        memory_window_size=100,
        max_retries=4,
        log_level="INFO",
    ),
}


def get_preset(name: str) -> Optional[AgentOSPreset]:
    """Get a preset by name. Returns None if not found."""
    return PRESETS.get(name.lower())


def list_presets() -> list[AgentOSPreset]:
    """List all available presets."""
    return list(PRESETS.values())


def get_preset_names() -> list[str]:
    """List all preset names."""
    return list(PRESETS.keys())


def apply_preset(preset_name: str, config: dict) -> dict:
    """
    Apply a preset to an existing config dict.

    Only overrides keys present in the preset; preserves all other keys.

    Args:
        preset_name: Name of the preset to apply.
        config: Existing configuration dict.

    Returns:
        Updated configuration dict.
    """
    preset = get_preset(preset_name)
    if not preset:
        raise ValueError(
            f"Unknown preset: '{preset_name}'. Available: {list(PRESETS.keys())}"
        )

    mapping = {
        "model": "model",
        "max_iterations": "max_iterations",
        "temperature": "temperature",
        "enable_cache": "enable_cache",
        "enable_rate_limit": "enable_rate_limit",
        "enable_guardrails": "enable_guardrails",
        "enable_streaming": "enable_streaming",
        "enable_cost_tracking": "enable_cost_tracking",
        "memory_window_size": "memory_window_size",
        "max_retries": "max_retries",
        "log_level": "log_level",
    }

    for preset_key, config_key in mapping.items():
        config[config_key] = getattr(preset, preset_key)

    return config
