"""
DataValidator — schema-based data validation with custom rules.

Supports:
    - Type validation (str, int, float, bool, list, dict)
    - Required/optional fields
    - Nullable fields
    - Min/max for numbers and strings
    - Enum (allowed values)
    - Regex pattern matching
    - Nested object validation
    - List item validation
    - Custom validator functions
    - Human-readable error messages
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# ============================================================================
# Schema definition
# ============================================================================

class Field:
    """A single field definition within a schema."""

    def __init__(
        self,
        field_type: type,
        required: bool = True,
        nullable: bool = False,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        enum: Optional[List[Any]] = None,
        pattern: Optional[str] = None,
        custom: Optional[Callable[[Any], Optional[str]]] = None,
        # Nesting
        nested: Optional[Dict[str, "Field"]] = None,
        items: Optional["Field"] = None,
    ):
        self.field_type = field_type
        self.required = required
        self.nullable = nullable
        self.min_value = min_value
        self.max_value = max_value
        self.min_length = min_length
        self.max_length = max_length
        self.enum = enum
        self.pattern = re.compile(pattern) if pattern else None
        self.custom = custom
        self.nested = nested
        self.items = items


# ============================================================================
# Validator
# ============================================================================

class ValidationError(Exception):
    """Raised when validation fails. Carries a list of error messages."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


class DataValidator:
    """Schema-based data validator.

    Usage:
        schema = {
            "name": Field(str, min_length=1, max_length=100),
            "age": Field(int, min_value=0, max_value=150),
            "email": Field(str, pattern=r"^[^@]+@[^@]+\.[^@]+$"),
            "tags": Field(list, items=Field(str)),
        }

        validator = DataValidator(schema)
        result = validator.validate(data)
        if result:
            ... # use result
    """

    def __init__(self, schema: Dict[str, Field]):
        self._schema = schema

    def validate(self, data: dict) -> dict:
        """Validate data against schema. Returns cleaned data or raises ValidationError."""
        errors = []
        cleaned = self._validate_dict(data, self._schema, "", errors)
        if errors:
            raise ValidationError(errors)
        return cleaned

    def is_valid(self, data: dict) -> bool:
        """Check if data is valid without raising."""
        try:
            self.validate(data)
            return True
        except ValidationError:
            return False

    def errors(self, data: dict) -> List[str]:
        """Return list of validation error messages."""
        errors_list: List[str] = []
        self._validate_dict(data, self._schema, "", errors_list)
        return errors_list

    # ---------- Internal ----------

    def _validate_dict(self, data: dict, schema: Dict[str, Field], path: str, errors: List[str]) -> dict:
        if not isinstance(data, dict):
            errors.append(f"{path or '(root)'}: expected dict, got {type(data).__name__}")
            return {}

        result = {}

        # Check required fields
        for name, field in schema.items():
            fpath = f"{path}.{name}" if path else name
            if name not in data:
                if field.required:
                    errors.append(f"{fpath}: required field missing")
                continue

            value = data[name]
            validated = self._validate_value(value, field, fpath, errors)
            if validated is not None or field.nullable:
                result[name] = validated

        # Warn about unknown fields (can be made strict later)
        return result

    def _validate_value(self, value: Any, field: Field, path: str, errors: List[str]) -> Any:
        # Nullable check
        if value is None:
            if not field.nullable:
                errors.append(f"{path}: value is None but field is not nullable")
                return None
            return None

        # Type check
        if not isinstance(value, field.field_type):
            errors.append(f"{path}: expected {field.field_type.__name__}, got {type(value).__name__}")
            return None

        # Min/max for numbers
        if field.field_type in (int, float):
            if field.min_value is not None and value < field.min_value:
                errors.append(f"{path}: value {value} < min {field.min_value}")
            if field.max_value is not None and value > field.max_value:
                errors.append(f"{path}: value {value} > max {field.max_value}")

        # Length for strings
        if field.field_type is str:
            if field.min_length is not None and len(value) < field.min_length:
                errors.append(f"{path}: length {len(value)} < min {field.min_length}")
            if field.max_length is not None and len(value) > field.max_length:
                errors.append(f"{path}: length {len(value)} > max {field.max_length}")

        # Enum
        if field.enum is not None and value not in field.enum:
            errors.append(f"{path}: {value!r} not in {field.enum}")

        # Pattern (regex)
        if field.pattern and not field.pattern.search(str(value)):
            errors.append(f"{path}: {value!r} does not match pattern")

        # Nested object
        if field.nested and isinstance(value, dict):
            value = self._validate_dict(value, field.nested, path, errors)

        # List items
        if field.items and isinstance(value, list):
            value = self._validate_list(value, field.items, path, errors)

        # Custom validator
        if field.custom:
            msg = field.custom(value)
            if msg:
                errors.append(f"{path}: {msg}")

        return value

    def _validate_list(self, data: list, item_field: Field, path: str, errors: List[str]) -> list:
        result = []
        for i, item in enumerate(data):
            item_path = f"{path}[{i}]"
            validated = self._validate_value(item, item_field, item_path, errors)
            result.append(validated)
        return result
