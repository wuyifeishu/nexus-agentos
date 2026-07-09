"""Tests for agentos.tools.skill_tool — SkillTool wrapper and discovery."""


import pytest

from agentos.tools.skill_tool import SkillTool, _infer_parameters, discover_skills


def _dummy_run(**kwargs):
    return f"ran with {kwargs}"


class TestSkillTool:
    """SkillTool class tests."""

    def test_construction(self):
        tool = SkillTool(
            skill_name="my_skill",
            skill_run=_dummy_run,
            description="A test skill",
        )
        assert tool.name == "my_skill"
        assert tool.description == "A test skill"
        assert tool.permission_level == "safe"

    def test_construction_minimal(self):
        tool = SkillTool(skill_name="minimal", skill_run=_dummy_run)
        assert tool.name == "minimal"
        assert "minimal" in tool.description

    def test_default_parameters(self):
        tool = SkillTool(skill_name="test", skill_run=_dummy_run)
        params = tool.parameters
        assert params["type"] == "object"
        assert "kwargs" in params["properties"]

    def test_custom_parameters(self):
        custom = {"type": "object", "properties": {"x": {"type": "integer"}}}
        tool = SkillTool(
            skill_name="custom", skill_run=_dummy_run, parameters=custom
        )
        assert tool.parameters == custom

    @pytest.mark.asyncio
    async def test_execute_with_kwargs_json(self):
        tool = SkillTool(skill_name="s", skill_run=_dummy_run)
        result = await tool.execute({"kwargs": '{"x": 1, "y": 2}'})
        assert "ran with" in result.output
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_direct_input(self):
        tool = SkillTool(skill_name="s", skill_run=_dummy_run)
        result = await tool.execute({"x": 42})
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_empty_input(self):
        tool = SkillTool(skill_name="s", skill_run=_dummy_run)
        result = await tool.execute({})
        assert result.error is None
        assert "ran with" in result.output

    @pytest.mark.asyncio
    async def test_execute_exception(self):
        def _fails(**kwargs):
            raise ValueError("broken")

        tool = SkillTool(skill_name="bad", skill_run=_fails)
        result = await tool.execute({"kwargs": '{"x": 1}'})
        assert result.error is not None
        assert "broken" in result.error

    @pytest.mark.asyncio
    async def test_execute_kwargs_invalid_json(self):
        tool = SkillTool(skill_name="s", skill_run=_dummy_run)
        result = await tool.execute({"kwargs": "not json"})
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_output_string(self):
        tool = SkillTool(skill_name="s", skill_run=_dummy_run)
        result = await tool.execute({"kwargs": '{}'})
        assert isinstance(result.output, str)

    @pytest.mark.asyncio
    async def test_execute_result_call_id(self):
        tool = SkillTool(skill_name="my_id", skill_run=_dummy_run)
        result = await tool.execute({"kwargs": '{}'})
        assert result.call_id == "my_id"


class TestSkillToolEdgeCases:
    """Edge case scenarios for SkillTool."""

    @pytest.mark.asyncio
    async def test_execute_with_int_values(self):
        def _int_skill(**kwargs):
            return 42

        tool = SkillTool(skill_name="int", skill_run=_int_skill)
        result = await tool.execute({"kwargs": '{}'})
        assert result.output == "42"

    @pytest.mark.asyncio
    async def test_execute_with_list_values(self):
        def _list_skill(**kwargs):
            return ["a", "b"]

        tool = SkillTool(skill_name="lst", skill_run=_list_skill)
        result = await tool.execute({"kwargs": '{}'})
        assert "a" in result.output


class TestInferParameters:
    """_infer_parameters function tests."""

    def test_simple_function(self):
        def fn(x: int, y: str = "default"):
            pass

        params = _infer_parameters(fn)
        assert params["type"] == "object"
        assert params["properties"]["x"]["type"] == "integer"
        assert params["properties"]["y"]["type"] == "string"
        assert params["required"] == ["x"]

    def test_all_types(self):
        def fn(
            s: str, i: int, f: float, b: bool, lst: list
        ):
            pass

        params = _infer_parameters(fn)
        assert params["properties"]["s"]["type"] == "string"
        assert params["properties"]["i"]["type"] == "integer"
        assert params["properties"]["f"]["type"] == "number"
        assert params["properties"]["b"]["type"] == "boolean"
        assert params["properties"]["lst"]["type"] == "array"

    def test_all_optional(self):
        def fn(a: int = 0, b: str = "x"):
            pass

        params = _infer_parameters(fn)
        assert params["required"] == []

    def test_all_required(self):
        def fn(a: int, b: str):
            pass

        params = _infer_parameters(fn)
        assert params["required"] == ["a", "b"]

    def test_skip_self(self):
        class C:
            def method(self, x: int):
                pass

        params = _infer_parameters(C().method)
        assert "self" not in params["properties"]
        assert "x" in params["properties"]
        assert params["required"] == ["x"]

    def test_skip_cls(self):
        def fn(cls, x: str):
            pass

        params = _infer_parameters(fn)
        assert "cls" not in params["properties"]
        assert "x" in params["properties"]

    def test_no_annotation(self):
        def fn(a, b: int = 5):
            pass

        params = _infer_parameters(fn)
        assert params["properties"]["a"]["type"] == "string"
        assert params["properties"]["b"]["type"] == "integer"
        assert params["required"] == ["a"]

    def test_print_has_signature(self):
        """print() has a real signature — verify it's extracted properly."""
        params = _infer_parameters(print)
        assert params["type"] == "object"
        # print has *args and other kwargs, at least 'args' should be parsed
        assert "args" in params["properties"] or "sep" in params["properties"]

    def test_empty_function(self):
        def fn():
            pass

        params = _infer_parameters(fn)
        assert params["type"] == "object"
        assert params["properties"] == {}


class TestDiscoverSkills:
    """discover_skills function tests."""

    def test_nonexistent_dir(self):
        result = discover_skills("/tmp/nonexistent_skills_dir_xyz")
        assert result == []

    def test_not_a_directory(self, tmp_path):
        f = tmp_path / "notadir.txt"
        f.write_text("hello")
        result = discover_skills(str(f))
        assert result == []

    def test_empty_directory(self, tmp_path):
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_discover_single_skill(self, tmp_path):
        skill_dir = tmp_path / "echo"
        skill_dir.mkdir()
        skill_file = skill_dir / "echo.py"
        skill_file.write_text("""
\"\"\"Echo skill - repeats input.\"\"\"

def run(message: str, times: int = 1) -> str:
    return message * times
""")

        tools = discover_skills(str(tmp_path))
        assert len(tools) == 1
        tool = tools[0]
        assert "echo" in tool.name
        assert "message" in tool.parameters["properties"]

    def test_discover_multiple_skills(self, tmp_path):
        for name in ["alpha", "beta"]:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            (skill_dir / f"{name}.py").write_text("""
def run(text: str) -> str:
    return text.upper()
""")

        tools = discover_skills(str(tmp_path))
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "skill_alpha" in names
        assert "skill_beta" in names

    def test_skip_non_directory_entries(self, tmp_path):
        (tmp_path / "not_skill.py").write_text("def run(): pass")
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_skip_missing_py_file(self, tmp_path):
        d = tmp_path / "ghost"
        d.mkdir()
        # No .py file
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_skip_no_run_function(self, tmp_path):
        skill_dir = tmp_path / "nofunc"
        skill_dir.mkdir()
        (skill_dir / "nofunc.py").write_text("x = 1")
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_skip_non_callable_run(self, tmp_path):
        skill_dir = tmp_path / "badfunc"
        skill_dir.mkdir()
        (skill_dir / "badfunc.py").write_text("run = 42")
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_import_error_graceful(self, tmp_path):
        skill_dir = tmp_path / "badimport"
        skill_dir.mkdir()
        (skill_dir / "badimport.py").write_text("import nonexistent_module_xyz")
        result = discover_skills(str(tmp_path))
        assert result == []

    def test_auto_locate_default_dir(self):
        """discover_skills without args uses auto-location."""
        # This should not crash
        result = discover_skills()
        assert isinstance(result, list)
