"""Batch 2 Skills — 12 个新增 Skill 的单元测试和 Agent 集成测试。"""

import importlib.util
import os
import sys
import tempfile


def _load_skill(name):
    base = os.path.join(os.path.dirname(__file__), "..", "agentos", "marketplace", "skills")
    skill_py = os.path.join(base, name, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"test_{name}", skill_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"test_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestGit:
    def test_git_status(self):
        mod = _load_skill("git")
        r = mod.run(action="status")
        assert "git" in r.lower() or "No output" in r or "not installed" in r.lower()


class TestDocker:
    def test_docker_ps(self):
        mod = _load_skill("docker")
        r = mod.run(action="ps")
        assert isinstance(r, str) and len(r) > 0


class TestSummarize:
    def test_word_count(self):
        mod = _load_skill("summarize")
        r = mod.run(action="word_count", text="Hello world. This is a test.")
        assert "Words:" in r

    def test_extract_keywords(self):
        mod = _load_skill("summarize")
        r = mod.run(action="extract_keywords", text="machine learning artificial intelligence neural networks deep learning")
        assert "learning" in r.lower()

    def test_summarize(self):
        mod = _load_skill("summarize")
        text = "Python is a programming language. " * 10 + "It is widely used. " * 5
        r = mod.run(action="summarize", text=text)
        assert len(r) < len(text)

    def test_bullet_points(self):
        mod = _load_skill("summarize")
        r = mod.run(action="bullet_points", text="This is a very important first observation. This is a second critical finding. This is a third major insight. This is a fourth key takeaway.")
        assert "- " in r


class TestCodeReview:
    def test_lines(self):
        mod = _load_skill("code-review")
        r = mod.run(action="lines", code="def foo():\n    pass\n\n# comment\nprint('hi')")
        assert "Total:" in r

    def test_functions(self):
        mod = _load_skill("code-review")
        r = mod.run(action="functions", code="def foo():\n    pass\n\ndef bar():\n    pass\n\nclass MyClass:\n    pass")
        assert "foo" in r and "bar" in r and "MyClass" in r

    def test_imports(self):
        mod = _load_skill("code-review")
        r = mod.run(action="imports", code="import os\nfrom pathlib import Path\nimport sys")
        assert "os" in r and "pathlib" in r

    def test_overview(self):
        mod = _load_skill("code-review")
        r = mod.run(action="overview", code="import os\n\ndef foo():\n    return 1\n")
        assert "lines" in r.lower()


class TestTaskManager:
    def test_add_and_list(self):
        mod = _load_skill("task-manager")
        mod.run(action="add", title="Test task 1")
        mod.run(action="add", title="Test task 2")
        r = mod.run(action="list")
        assert "Test task 1" in r

    def test_done(self):
        mod = _load_skill("task-manager")
        add_r = mod.run(action="add", title="Task to complete")
        # Extract task ID from "Added: #N ..." output
        task_id = add_r.split("#")[1].split()[0]
        r = mod.run(action="done", task_id=int(task_id))
        assert "Done" in r

    def test_search(self):
        mod = _load_skill("task-manager")
        mod.run(action="add", title="Searchable task")
        r = mod.run(action="search", title="Searchable")
        assert "Searchable" in r

    def test_clear_done(self):
        mod = _load_skill("task-manager")
        add_r = mod.run(action="add", title="Task to complete")
        task_id = add_r.split("#")[1].split()[0]
        mod.run(action="done", task_id=int(task_id))
        r = mod.run(action="clear_done")
        assert "Cleared" in r or "remaining" in r


class TestDatabase:
    def test_tables(self):
        mod = _load_skill("database")
        r = mod.run(action="tables", db_path=":memory:")
        assert "No tables" in r

    def test_create_and_query(self):
        mod = _load_skill("database")
        mod.run(action="create_table", db_path=":memory:", query="CREATE TABLE users (id INTEGER, name TEXT)")
        r = mod.run(action="tables", db_path=":memory:")
        assert "users" in r

    def test_insert_and_query(self):
        mod = _load_skill("database")
        mod.run(action="create_table", db_path=":memory:", query="CREATE TABLE test (id INTEGER, value TEXT)")
        mod.run(action="insert", db_path=":memory:", query="INSERT INTO test VALUES (1, 'hello')")
        r = mod.run(action="query", db_path=":memory:", query="SELECT * FROM test")
        assert "hello" in r


class TestSpreadsheet:
    def test_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,age\nAlice,30\nBob,25\n")
            tmp = f.name
        try:
            mod = _load_skill("spreadsheet")
            r = mod.run(action="read", file_path=tmp)
            assert "Alice" in r
        finally:
            os.unlink(tmp)

    def test_filter(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,score\nAlice,90\nBob,60\nCharlie,95\n")
            tmp = f.name
        try:
            mod = _load_skill("spreadsheet")
            r = mod.run(action="filter", file_path=tmp, column="name", condition="bo")
            assert "Bob" in r and "Alice" not in r
        finally:
            os.unlink(tmp)

    def test_sort(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,age\nAlice,30\nBob,25\nCharlie,35\n")
            tmp = f.name
        try:
            mod = _load_skill("spreadsheet")
            r = mod.run(action="sort", file_path=tmp, sort_by="age")
            assert "Bob" in r
            bob_idx = r.index("Bob")
            alice_idx = r.index("Alice")
            assert bob_idx < alice_idx, "Should be sorted ascending by age"
        finally:
            os.unlink(tmp)

    def test_aggregate(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,score\nAlice,90\nBob,60\nCharlie,95\n")
            tmp = f.name
        try:
            mod = _load_skill("spreadsheet")
            r = mod.run(action="aggregate", file_path=tmp, column="score", aggregate="avg")
            assert "81" in r
            r2 = mod.run(action="aggregate", file_path=tmp, column="score", aggregate="sum")
            assert "245" in r2
        finally:
            os.unlink(tmp)


class TestBackup:
    def test_list_empty(self):
        mod = _load_skill("backup")
        r = mod.run(action="list_backups")
        assert isinstance(r, str)


class TestHealthcheck:
    def test_all(self):
        mod = _load_skill("healthcheck")
        r = mod.run(action="all")
        assert "Disk" in r or "Memory" in r or "CPU" in r

    def test_disk(self):
        mod = _load_skill("healthcheck")
        r = mod.run(action="disk")
        assert "Disk" in r or "GB" in r


class TestDocx:
    def test_not_found(self):
        mod = _load_skill("docx")
        r = mod.run(action="read", file_path="/nonexistent/dead.docx")
        assert "not found" in r.lower() or "not installed" in r.lower()


class TestPdf:
    def test_not_found(self):
        mod = _load_skill("pdf")
        r = mod.run(action="read", file_path="/nonexistent/dead.pdf")
        assert "not found" in r.lower() or "not installed" in r.lower()


class TestXlsx:
    def test_not_found(self):
        mod = _load_skill("xlsx")
        r = mod.run(action="read", file_path="/nonexistent/dead.xlsx")
        assert "not found" in r.lower() or "not installed" in r.lower()


class TestAgentIntegration:
    """验证 ProductionAgent 可以调用新增 skill。"""
    def test_agent_uses_summarize(self):
        from agentos.agent.production_agent import ProductionAgent
        from agentos.agent.tool_agent import MockLLMProvider

        agent = ProductionAgent(include_skills=True)
        agent._agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_summarize",
                {"action": "summarize", "text": "Long text. " * 50},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.text_response("Summary: This is about long texts."),
        ])

        result = agent.run("Summarize this long text")
        assert result.success

    def test_agent_uses_task_manager(self):
        from agentos.agent.production_agent import ProductionAgent
        from agentos.agent.tool_agent import MockLLMProvider

        agent = ProductionAgent(include_skills=True)
        agent._agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_task_manager",
                {"action": "add", "title": "Buy milk"},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.text_response("Task added successfully."),
        ])

        result = agent.run("Add a task 'Buy milk'")
        assert result.success

    def test_agent_uses_code_review(self):
        from agentos.agent.production_agent import ProductionAgent
        from agentos.agent.tool_agent import MockLLMProvider

        agent = ProductionAgent(include_skills=True)
        agent._agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_code_review",
                {"action": "overview", "code": "def foo():\n    return 1"},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.text_response("Code review: 3 lines, 1 function."),
        ])

        result = agent.run("Review this code")
        assert result.success

    def test_agent_uses_database(self):
        from agentos.agent.production_agent import ProductionAgent
        from agentos.agent.tool_agent import MockLLMProvider

        agent = ProductionAgent(include_skills=True)
        agent._agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_database",
                {"action": "query", "db_path": ":memory:", "query": "SELECT 1"},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.text_response("Query result: 1"),
        ])

        result = agent.run("Query the database")
        assert result.success
