"""LLM Provider base interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract base class for LLM providers (OpenAI, Anthropic, etc.)."""

    @abstractmethod
    async def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def generate_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Stream a response from the LLM."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model name used by this provider."""
        ...
