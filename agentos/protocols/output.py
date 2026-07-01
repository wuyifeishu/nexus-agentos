"""
Structured output validation for NexusAgent.

Provides Pydantic-style output validation for agents.
When Agent[Deps, Out] has Out as a Pydantic BaseModel,
the output is automatically validated.
"""

from __future__ import annotations

from typing import Any, TypeVar, Generic, get_type_hints, get_origin, get_args
from dataclasses import dataclass

try:
    from pydantic import BaseModel, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = None
    ValidationError = Exception
    PYDANTIC_AVAILABLE = False

T = TypeVar("T")


if PYDANTIC_AVAILABLE:
    from pydantic import ConfigDict


class StructuredOutput(BaseModel if PYDANTIC_AVAILABLE else object):

    """Agent 结构化输出。"""

    """
    Base class for structured outputs.

    Usage:
        class MyOutput(StructuredOutput):
            answer: str
            confidence: float
            sources: list[str]
    """
    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")


@dataclass
class ValidationResult(Generic[T]):
    """
    Result of output validation.

    Attributes:
        success: Whether validation passed
        output: Validated output (if success)
        error: Validation error (if failed)
    """
    success: bool
    output: T | None = None
    error: str | None = None


class OutputValidator(Generic[T]):
    """
    Validator for structured outputs.

    Usage:
        validator = OutputValidator(MyOutput)
        result = validator.validate({"answer": "42", "confidence": 0.9})
        if result.success:
            output = result.output  # MyOutput instance
    """

    def __init__(self, output_type: type[T]):
        """
        Initialize validator.

        Args:
            output_type: Expected output type
        """
        self.output_type = output_type
        self._is_pydantic = (
            PYDANTIC_AVAILABLE and
            isinstance(output_type, type) and
            issubclass(output_type, BaseModel)
        )

    def validate(self, data: Any) -> ValidationResult[T]:
        """
        Validate data against output type.

        Args:
            data: Data to validate

        Returns:
            ValidationResult with success/error info
        """
        # If not Pydantic, just check type
        if not self._is_pydantic:
            if isinstance(data, self.output_type):
                return ValidationResult(success=True, output=data)
            else:
                return ValidationResult(
                    success=False,
                    error=f"Expected {self.output_type}, got {type(data)}"
                )

        # Pydantic validation
        try:
            if isinstance(data, self.output_type):
                # Already correct type
                return ValidationResult(success=True, output=data)
            elif isinstance(data, dict):
                # Try to construct from dict
                output = self.output_type(**data)
                return ValidationResult(success=True, output=output)
            else:
                # Try model_validate
                output = self.output_type.model_validate(data)
                return ValidationResult(success=True, output=output)
        except ValidationError as e:
            return ValidationResult(success=False, error=str(e))
        except Exception as e:
            return ValidationResult(success=False, error=str(e))

    def validate_or_raise(self, data: Any) -> T:
        """
        Validate data, raise on failure.

        Args:
            data: Data to validate

        Returns:
            Validated output

        Raises:
            ValueError: If validation fails
        """
        result = self.validate(data)
        if not result.success:
            raise ValueError(f"Output validation failed: {result.error}")
        return result.output


def validate_output(output_type: type[T], data: Any) -> ValidationResult[T]:
    """
    Validate data against output type.

    Convenience function wrapping OutputValidator.

    Args:
        output_type: Expected output type
        data: Data to validate

    Returns:
        ValidationResult with success/error info

    Usage:
        result = validate_output(MyOutput, {"answer": "42"})
        if result.success:
            output = result.output
    """
    validator = OutputValidator(output_type)
    return validator.validate(data)


def get_output_type(agent_class: type) -> type | None:
    """
    Extract output type from Agent class.

    Args:
        agent_class: Agent subclass

    Returns:
        Output type if found, None otherwise
    """
    # Check type hints
    hints = get_type_hints(agent_class)
    if 'Out' in hints:
        return hints['Out']

    # Check generic base
    for base in agent_class.__mro__:
        origin = get_origin(base)
        if origin is not None:
            # Check if it's Agent
            from agentos.core.di import Agent
            if issubclass(origin, Agent):
                args = get_args(base)
                if len(args) >= 2:
                    return args[1]

    return None
