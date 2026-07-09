"""Tests for agentos.tools.file_tools — ReadFileTool, WriteFileTool, ListDirectoryTool."""

import os
import tempfile

import pytest

from agentos.tools.base import PermissionLevel
from agentos.tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def read_tool():
    return ReadFileTool()


@pytest.fixture
def write_tool():
    return WriteFileTool()


@pytest.fixture
def list_tool():
    return ListDirectoryTool()


@pytest.fixture
def temp_text_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Hello, AgentOS!\nLine 2")
    yield f.name
    os.unlink(f.name)


@pytest.fixture
def temp_dir():
    path = tempfile.mkdtemp()
    os.makedirs(os.path.join(path, "subdir"), exist_ok=True)
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("a")
    with open(os.path.join(path, "b.txt"), "w") as f:
        f.write("bb")
    yield path
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ── ReadFileTool Tests ────────────────────────────────────

class TestReadFileTool:
    def test_permission_level(self, read_tool):
        assert read_tool.permission_level == PermissionLevel.SAFE

    def test_parameters_schema(self, read_tool):
        params = read_tool.parameters
        assert params["type"] == "object"
        assert "file_path" in params["properties"]
        assert "file_path" in params["required"]

    @pytest.mark.asyncio
    async def test_read_existing_file(self, read_tool, temp_text_file):
        result = await read_tool.execute({"file_path": temp_text_file})
        assert result.error is None
        assert "Hello, AgentOS!" in result.output
        assert "Line 2" in result.output

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, read_tool):
        result = await read_tool.execute({"file_path": "/nonexistent/file.txt"})
        assert result.error is not None
        assert "File not found" in result.error

    def test_name_and_description(self, read_tool):
        assert read_tool.name == "read_file"
        assert len(read_tool.description) > 0


# ── WriteFileTool Tests ────────────────────────────────────

class TestWriteFileTool:
    def test_permission_level(self, write_tool):
        assert write_tool.permission_level == PermissionLevel.MODERATE

    def test_is_write_operation(self, write_tool):
        assert write_tool.is_write_operation({"file_path": "/tmp/x.txt", "content": "hi"}) is True

    def test_parameters_schema(self, write_tool):
        params = write_tool.parameters
        assert "file_path" in params["properties"]
        assert "content" in params["properties"]

    @pytest.mark.asyncio
    async def test_write_new_file(self, write_tool):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "new.txt")
            result = await write_tool.execute({"file_path": path, "content": "Hello World"})
            assert result.error is None
            assert "Written" in result.output
            assert os.path.isfile(path)
            with open(path) as f:
                assert f.read() == "Hello World"

    @pytest.mark.asyncio
    async def test_write_overwrite_existing(self, write_tool, temp_text_file):
        result = await write_tool.execute({"file_path": temp_text_file, "content": "Overwritten"})
        assert result.error is None
        with open(temp_text_file) as f:
            assert f.read() == "Overwritten"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, write_tool):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "deep", "nested", "file.txt")
            result = await write_tool.execute({"file_path": path, "content": "deep"})
            assert result.error is None
            assert os.path.isfile(path)

    def test_name_and_description(self, write_tool):
        assert write_tool.name == "write_file"
        assert len(write_tool.description) > 0


# ── ListDirectoryTool Tests ────────────────────────────────

class TestListDirectoryTool:
    def test_permission_level(self, list_tool):
        assert list_tool.permission_level == PermissionLevel.SAFE

    def test_parameters_schema(self, list_tool):
        params = list_tool.parameters
        assert "path" in params["properties"]
        assert "path" in params["required"]

    @pytest.mark.asyncio
    async def test_list_directory(self, list_tool, temp_dir):
        result = await list_tool.execute({"path": temp_dir})
        assert result.error is None
        assert "[DIR]" in result.output
        assert "[FILE]" in result.output
        assert "a.txt" in result.output
        assert "b.txt" in result.output
        assert "subdir" in result.output

    @pytest.mark.asyncio
    async def test_list_directory_not_found(self, list_tool):
        result = await list_tool.execute({"path": "/no/such/dir"})
        assert result.error is not None
        assert "Directory not found" in result.error

    def test_name_and_description(self, list_tool):
        assert list_tool.name == "list_directory"
        assert len(list_tool.description) > 0
