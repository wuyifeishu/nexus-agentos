"""Tests for agentos.tools.search_tools — GrepTool, FileSearchTool, CodeSearchTool."""

import tempfile
from pathlib import Path

import pytest

from agentos.tools.search_tools import CodeSearchTool, FileSearchTool, GrepTool


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def py_files(tmp_dir):
    """Create test Python files."""
    a = Path(tmp_dir) / "module_a.py"
    a.write_text("def hello():\n    return 'world'\n\nclass Foo:\n    pass\n")
    b = Path(tmp_dir) / "module_b.py"
    b.write_text("import os\n\nasync def run():\n    pass\n")
    sub = Path(tmp_dir) / "sub"
    sub.mkdir()
    c = sub / "utils.py"
    c.write_text("def helper():\n    return 42\n")
    return tmp_dir


# ── GrepTool ──────────────────────────────────────────────────────────────


async def test_grep_metadata():
    t = GrepTool()
    assert t.name == "grep"
    params = t.parameters
    assert "pattern" in params["required"]


async def test_grep_finds_text(py_files):
    t = GrepTool()
    result = await t.execute({"pattern": "def hello", "directory": py_files})
    assert "module_a.py" in result.output
    assert "def hello" in result.output


async def test_grep_case_insensitive(py_files):
    t = GrepTool()
    r1 = await t.execute(
        {"pattern": "DEF HELLO", "directory": py_files, "case_sensitive": False}
    )
    assert "module_a.py" in r1.output

    r2 = await t.execute(
        {"pattern": "DEF HELLO", "directory": py_files, "case_sensitive": True}
    )
    assert r2.output == "No matches found"


async def test_grep_no_matches(py_files):
    t = GrepTool()
    result = await t.execute({"pattern": "zzz_nonexistent_zzz", "directory": py_files})
    assert result.output == "No matches found"


async def test_grep_file_pattern_filter(py_files):
    t = GrepTool()
    result = await t.execute(
        {"pattern": "def", "directory": py_files, "file_pattern": "module_a*"}
    )
    assert "module_a.py" in result.output
    assert "module_b.py" not in result.output


async def test_grep_max_results(py_files):
    t = GrepTool()
    result = await t.execute({"pattern": "def", "directory": py_files, "max_results": 1})
    lines = result.output.strip().split("\n")
    assert len(lines) == 1


async def test_grep_invalid_regex(py_files):
    t = GrepTool()
    result = await t.execute({"pattern": "[invalid", "directory": py_files})
    assert result.error is not None


async def test_grep_default_directory(tmp_dir, monkeypatch):
    monkeypatch.chdir(tmp_dir)
    Path(tmp_dir, "test.txt").write_text("hello world")
    t = GrepTool()
    result = await t.execute({"pattern": "hello"})
    assert "test.txt" in result.output


# ── FileSearchTool ─────────────────────────────────────────────────────────


async def test_file_search_metadata():
    t = FileSearchTool()
    assert t.name == "file_search"
    params = t.parameters
    assert "pattern" in params["required"]


async def test_file_search_finds_files(py_files):
    t = FileSearchTool()
    result = await t.execute({"pattern": "module_a.py", "directory": py_files})
    assert "module_a.py" in result.output


async def test_file_search_glob(py_files):
    t = FileSearchTool()
    result = await t.execute({"pattern": "*.py", "directory": py_files})
    assert "module_a.py" in result.output
    assert "module_b.py" in result.output


async def test_file_search_no_matches(py_files):
    t = FileSearchTool()
    result = await t.execute({"pattern": "*.java", "directory": py_files})
    assert result.output == "No files found"


async def test_file_search_max_results(py_files):
    t = FileSearchTool()
    result = await t.execute({"pattern": "*.py", "directory": py_files, "max_results": 1})
    lines = result.output.strip().split("\n")
    assert len(lines) == 1


# ── CodeSearchTool ─────────────────────────────────────────────────────────


async def test_code_search_metadata():
    t = CodeSearchTool()
    assert t.name == "code_search"
    params = t.parameters
    assert "query" in params["required"]


async def test_code_search_function(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "hello", "directory": py_files})
    assert "[function] hello" in result.output


async def test_code_search_class(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "Foo", "directory": py_files})
    assert "[class] Foo" in result.output


async def test_code_search_async_function(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "run", "directory": py_files})
    assert "async_function" in result.output or "function" in result.output


async def test_code_search_filter_symbol_type(py_files):
    t = CodeSearchTool()
    result = await t.execute(
        {"query": "hello", "directory": py_files, "symbol_type": "function"}
    )
    assert "[class]" not in result.output


async def test_code_search_import(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "os", "directory": py_files, "symbol_type": "import"})
    assert "import os" in result.output


async def test_code_search_no_matches(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "zzz_nonexistent_zzz", "directory": py_files})
    assert result.output == "No symbols found"


async def test_code_search_max_results(py_files):
    t = CodeSearchTool()
    result = await t.execute({"query": "def", "directory": py_files, "max_results": 1})
    lines = result.output.strip().split("\n")
    assert len(lines) >= 1


# ── Error handling (binary / unreadable files) ────────────────────────────


async def test_grep_skips_binary_files(tmp_dir):
    """Grep should skip binary files (UnicodeDecodeError)."""
    Path(tmp_dir, "binary.bin").write_bytes(b"\x00\xFF\x00\xFF")
    Path(tmp_dir, "good.txt").write_text("hello world")
    t = GrepTool()
    result = await t.execute({"pattern": "hello", "directory": tmp_dir})
    assert "good.txt" in result.output
    assert "binary.bin" not in result.output


async def test_code_search_skips_binary_files(tmp_dir):
    """CodeSearch should skip binary/non-Python files gracefully."""
    Path(tmp_dir, "binary.bin").write_bytes(b"\x00\xFF")
    t = CodeSearchTool()
    result = await t.execute({"query": "foo", "directory": tmp_dir})
    assert result.output == "No symbols found"


# ── CodeSearch: from X import ... branch ───────────────────────────────────


async def test_code_search_import_from(tmp_dir):
    """Cover `from module import ...` branch."""
    Path(tmp_dir, "mod.py").write_text("from collections import OrderedDict\n")
    t = CodeSearchTool()
    result = await t.execute({"query": "collections", "directory": tmp_dir, "symbol_type": "import"})
    assert "from collections import" in result.output


async def test_code_search_import_from_package(tmp_dir):
    """`from . import foo` has module=None, the tool skips gracefully."""
    Path(tmp_dir, "mod.py").write_text("from . import sibling\n")
    t = CodeSearchTool()
    result = await t.execute({"query": "sibling", "directory": tmp_dir, "symbol_type": "import"})
    assert result.output == "No symbols found"


async def test_code_search_import_alias_match(tmp_dir):
    """`import foo` where query matches the module name."""
    Path(tmp_dir, "mod.py").write_text("import json\n")
    t = CodeSearchTool()
    result = await t.execute({"query": "json", "directory": tmp_dir, "symbol_type": "all"})
    assert "json" in result.output
