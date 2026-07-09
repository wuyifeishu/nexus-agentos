"""Tests for agentos.tools.data_validator."""

import pytest

from agentos.tools.data_validator import DataValidator, Field, ValidationError


class TestBasicValidation:
    def test_simple_valid(self):
        schema = {"name": Field(str), "age": Field(int)}
        v = DataValidator(schema)
        result = v.validate({"name": "Alice", "age": 30})
        assert result["name"] == "Alice"
        assert result["age"] == 30

    def test_type_mismatch(self):
        schema = {"age": Field(int)}
        v = DataValidator(schema)
        with pytest.raises(ValidationError) as exc:
            v.validate({"age": "thirty"})
        assert "expected int" in exc.value.errors[0]

    def test_required_missing(self):
        schema = {"name": Field(str, required=True)}
        v = DataValidator(schema)
        with pytest.raises(ValidationError) as exc:
            v.validate({})
        assert "required" in exc.value.errors[0]

    def test_optional_field(self):
        schema = {"name": Field(str, required=False)}
        v = DataValidator(schema)
        result = v.validate({})
        assert "name" not in result

    def test_nullable(self):
        schema = {"nickname": Field(str, nullable=True)}
        v = DataValidator(schema)
        result = v.validate({"nickname": None})
        assert result["nickname"] is None

    def test_not_nullable(self):
        schema = {"name": Field(str)}
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"name": None})

    def test_min_value(self):
        schema = {"score": Field(int, min_value=0)}
        v = DataValidator(schema)
        assert v.validate({"score": 10})
        with pytest.raises(ValidationError):
            v.validate({"score": -5})

    def test_max_value(self):
        schema = {"score": Field(int, max_value=100)}
        v = DataValidator(schema)
        assert v.validate({"score": 100})
        with pytest.raises(ValidationError):
            v.validate({"score": 101})

    def test_min_length(self):
        schema = {"name": Field(str, min_length=2)}
        v = DataValidator(schema)
        assert v.validate({"name": "Al"})
        with pytest.raises(ValidationError):
            v.validate({"name": "A"})

    def test_max_length(self):
        schema = {"name": Field(str, max_length=5)}
        v = DataValidator(schema)
        assert v.validate({"name": "Alice"})
        with pytest.raises(ValidationError):
            v.validate({"name": "LongName"})


class TestEnum:
    def test_valid_enum(self):
        schema = {"status": Field(str, enum=["active", "inactive", "pending"])}
        v = DataValidator(schema)
        assert v.validate({"status": "active"})

    def test_invalid_enum(self):
        schema = {"status": Field(str, enum=["active", "inactive"])}
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"status": "deleted"})


class TestPattern:
    def test_valid_pattern(self):
        schema = {"email": Field(str, pattern=r"^[^@]+@[^@]+\.[^@]+$")}
        v = DataValidator(schema)
        assert v.validate({"email": "alice@example.com"})

    def test_invalid_pattern(self):
        schema = {"email": Field(str, pattern=r"^[^@]+@[^@]+\.[^@]+$")}
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"email": "not-an-email"})


class TestNested:
    def test_nested_object(self):
        schema = {
            "user": Field(
                dict,
                nested={
                    "name": Field(str),
                    "email": Field(str),
                },
            )
        }
        v = DataValidator(schema)
        result = v.validate({"user": {"name": "Alice", "email": "alice@example.com"}})
        assert result["user"]["name"] == "Alice"

    def test_nested_invalid(self):
        schema = {
            "user": Field(
                dict,
                nested={
                    "age": Field(int),
                },
            )
        }
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"user": {"age": "not-int"}})


class TestListItems:
    def test_list_of_strings(self):
        schema = {"tags": Field(list, items=Field(str))}
        v = DataValidator(schema)
        result = v.validate({"tags": ["python", "ai", "agent"]})
        assert result["tags"] == ["python", "ai", "agent"]

    def test_list_item_type_mismatch(self):
        schema = {"scores": Field(list, items=Field(int))}
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"scores": [1, 2, "three"]})


class TestCustomValidator:
    def test_custom_pass(self):
        def must_be_even(val):
            if val % 2 != 0:
                return "must be even"
            return None

        schema = {"value": Field(int, custom=must_be_even)}
        v = DataValidator(schema)
        assert v.validate({"value": 4})

    def test_custom_fail(self):
        def must_be_even(val):
            if val % 2 != 0:
                return "must be even"
            return None

        schema = {"value": Field(int, custom=must_be_even)}
        v = DataValidator(schema)
        with pytest.raises(ValidationError) as exc:
            v.validate({"value": 3})
        assert "must be even" in exc.value.errors[0]


class TestIsValidAndErrors:
    def test_is_valid_true(self):
        schema = {"name": Field(str)}
        v = DataValidator(schema)
        assert v.is_valid({"name": "Alice"})

    def test_is_valid_false(self):
        schema = {"name": Field(str)}
        v = DataValidator(schema)
        assert not v.is_valid({"name": 123})

    def test_errors_list(self):
        schema = {"name": Field(str, min_length=5), "age": Field(int, min_value=18)}
        v = DataValidator(schema)
        errors = v.errors({"name": "A", "age": 10})
        assert len(errors) == 2

    def test_errors_empty(self):
        schema = {"name": Field(str)}
        v = DataValidator(schema)
        errors = v.errors({"name": "Alice"})
        assert errors == []


class TestFloat:
    def test_float_min_max(self):
        schema = {"price": Field(float, min_value=0.0, max_value=999.99)}
        v = DataValidator(schema)
        assert v.validate({"price": 49.99})
        with pytest.raises(ValidationError):
            v.validate({"price": -1.0})


class TestBool:
    def test_bool_no_constraints(self):
        schema = {"active": Field(bool)}
        v = DataValidator(schema)
        assert v.validate({"active": True})
        assert v.validate({"active": False})

    def test_bool_wrong_type(self):
        schema = {"active": Field(bool)}
        v = DataValidator(schema)
        with pytest.raises(ValidationError):
            v.validate({"active": "yes"})


class TestComplexSchema:
    def test_complex_valid(self):
        schema = {
            "id": Field(int, min_value=1),
            "name": Field(str, min_length=1, max_length=50),
            "email": Field(str, pattern=r"^[^@]+@[^@]+\.[^@]+$"),
            "tags": Field(list, required=False, items=Field(str, min_length=1)),
            "metadata": Field(dict, required=False, nested={"source": Field(str)}),
        }
        v = DataValidator(schema)
        result = v.validate({
            "id": 42,
            "name": "Alice",
            "email": "alice@example.com",
            "tags": ["dev", "ml"],
            "metadata": {"source": "web"},
        })
        assert result["id"] == 42
