"""Tests for agentos.tools.data_tools — JsonTool, CsvTool."""

import json
import os
import tempfile

import pytest

from agentos.tools.data_tools import CsvTool, JsonTool

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def json_tool():
    return JsonTool()


@pytest.fixture
def csv_tool():
    return CsvTool()


@pytest.fixture
def temp_json_file():
    data = {"name": "Alice", "age": 30, "tags": ["dev", "python"]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
    yield f.name
    os.unlink(f.name)


@pytest.fixture
def temp_csv_file():
    content = "name,age,city\nAlice,30,NYC\nBob,25,LA\nCarol,35,NYC\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(content)
    yield f.name
    os.unlink(f.name)


# ── JsonTool Tests ─────────────────────────────────────────

class TestJsonTool:
    @pytest.mark.asyncio
    async def test_parse_dict(self, json_tool):
        result = await json_tool.execute({"action": "parse", "input": '{"a": 1, "b": 2}'})
        assert result.error is None
        assert "dict" in result.output
        assert "Keys" in result.output

    @pytest.mark.asyncio
    async def test_parse_list(self, json_tool):
        result = await json_tool.execute({"action": "parse", "input": '[1, 2, 3]'})
        assert result.error is None
        assert "list" in result.output

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, json_tool):
        result = await json_tool.execute({"action": "parse", "input": "not json"})
        assert result.error is not None
        assert "JSON parse error" in result.error

    @pytest.mark.asyncio
    async def test_format(self, json_tool):
        result = await json_tool.execute({"action": "format", "input": '{"b":2,"a":1}'})
        assert result.error is None
        data = json.loads(result.output)
        assert data == {"b": 2, "a": 1}

    @pytest.mark.asyncio
    async def test_format_custom_indent(self, json_tool):
        result = await json_tool.execute({"action": "format", "input": '{"a": 1}', "indent": 4})
        assert result.error is None
        assert "    " in result.output

    @pytest.mark.asyncio
    async def test_query_root(self, json_tool):
        result = await json_tool.execute({"action": "query", "input": '{"x": 10}'})
        assert result.error is None
        assert "10" in result.output

    @pytest.mark.asyncio
    async def test_query_dict_path(self, json_tool):
        result = await json_tool.execute({
            "action": "query",
            "input": '{"store": {"book": {"title": "Python"}}}',
            "jsonpath": "$.store.book.title"
        })
        assert result.error is None
        assert "Python" in result.output

    @pytest.mark.asyncio
    async def test_query_array_index(self, json_tool):
        result = await json_tool.execute({
            "action": "query",
            "input": '{"items": ["a", "b", "c"]}',
            "jsonpath": "$.items.1"
        })
        assert result.error is None
        assert "b" in result.output

    @pytest.mark.asyncio
    async def test_query_missing_key(self, json_tool):
        result = await json_tool.execute({
            "action": "query",
            "input": '{"a": 1}',
            "jsonpath": "$.b"
        })
        assert result.error is None
        assert "null" in result.output

    @pytest.mark.asyncio
    async def test_query_nested_array(self, json_tool):
        result = await json_tool.execute({
            "action": "query",
            "input": '{"data": [[1,2],[3,4]]}',
            "jsonpath": "$.data.0.1"
        })
        assert result.error is None
        assert "2" in result.output

    @pytest.mark.asyncio
    async def test_validate_valid(self, json_tool):
        result = await json_tool.execute({"action": "validate", "input": '{"ok": true}'})
        assert result.error is None
        assert "Valid JSON" in result.output

    @pytest.mark.asyncio
    async def test_validate_invalid(self, json_tool):
        result = await json_tool.execute({"action": "validate", "input": "{{bad"})
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_unknown_action(self, json_tool):
        result = await json_tool.execute({"action": "delete", "input": "{}"})
        assert result.error is not None
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_parse_from_file(self, json_tool, temp_json_file):
        result = await json_tool.execute({"action": "parse", "input": temp_json_file})
        assert result.error is None
        assert "Alice" in result.output

    @pytest.mark.asyncio
    async def test_query_from_file(self, json_tool, temp_json_file):
        result = await json_tool.execute({
            "action": "query",
            "input": temp_json_file,
            "jsonpath": "$.tags.0"
        })
        assert result.error is None
        assert "dev" in result.output

    @pytest.mark.asyncio
    async def test_file_not_found(self, json_tool):
        result = await json_tool.execute({"action": "parse", "input": "/nonexistent/file.json"})
        assert result.error is not None
        assert "JSON parse error" in result.error  # falls through to parse attempt

    @pytest.mark.asyncio
    async def test_query_bracket_notation(self, json_tool):
        result = await json_tool.execute({
            "action": "query",
            "input": '{"arr": [10, 20, 30]}',
            "jsonpath": "$.arr[2]"
        })
        assert result.error is None
        assert "30" in result.output

    def test_parameters_schema(self, json_tool):
        params = json_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert "input" in params["properties"]

    def test_name_and_description(self, json_tool):
        assert json_tool.name == "json_tool"
        assert len(json_tool.description) > 0


# ── CsvTool Tests ──────────────────────────────────────────

class TestCsvTool:
    @pytest.mark.asyncio
    async def test_read_csv_string(self, csv_tool):
        csv_data = "a,b,c\n1,2,3\n4,5,6"
        result = await csv_tool.execute({"action": "read", "input": csv_data})
        assert result.error is None
        assert "a" in result.output
        assert "1" in result.output

    @pytest.mark.asyncio
    async def test_read_csv_file(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "read", "input": temp_csv_file})
        assert result.error is None
        assert "name" in result.output
        assert "Alice" in result.output

    @pytest.mark.asyncio
    async def test_read_with_limit(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "read", "input": temp_csv_file, "limit": 1})
        assert result.error is None
        assert "Alice" in result.output
        assert "Bob" not in result.output

    @pytest.mark.asyncio
    async def test_stats(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "stats", "input": temp_csv_file})
        assert result.error is None
        assert "Columns" in result.output
        assert "city" in result.output

    @pytest.mark.asyncio
    async def test_query_with_columns(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "query", "input": temp_csv_file, "columns": "name,age"})
        assert result.error is None
        assert "Alice" in result.output
        assert "30" in result.output

    @pytest.mark.asyncio
    async def test_query_all_columns(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "query", "input": temp_csv_file})
        assert result.error is None
        assert "name=" in result.output
        assert "city=" in result.output

    @pytest.mark.asyncio
    async def test_invalid_csv(self, csv_tool):
        result = await csv_tool.execute({"action": "read", "input": "not,csv\nunbalanced"})
        assert result.error is None  # csv.reader is lenient, DictReader may produce partial
        # It won't error, just might produce partial rows

    @pytest.mark.asyncio
    async def test_unknown_action(self, csv_tool):
        result = await csv_tool.execute({"action": "delete", "input": "a,b\n1,2"})
        assert result.error is not None
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_file_not_found(self, csv_tool):
        result = await csv_tool.execute({"action": "read", "input": "/no/file.csv"})
        # Not a file, treated as inline CSV string — will try to parse
        assert result.error is None  # "/no/file.csv" is treated as inline CSV text

    @pytest.mark.asyncio
    async def test_stats_unique_values(self, csv_tool, temp_csv_file):
        result = await csv_tool.execute({"action": "stats", "input": temp_csv_file, "limit": 50})
        assert result.error is None
        assert "unique values" in result.output

    def test_parameters_schema(self, csv_tool):
        params = csv_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert "input" in params["properties"]

    def test_name_and_description(self, csv_tool):
        assert csv_tool.name == "csv_tool"
        assert len(csv_tool.description) > 0
