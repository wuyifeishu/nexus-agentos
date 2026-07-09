"""
集成测试: ToolAgent + 真实 Skill 端到端验证。

验证 Agent 可以发现、调用真实 skill，并正确处理返回值。
"""

import json
import os
import tempfile

from agentos.agent.agent_builder import build_agent
from agentos.agent.tool_agent import MockLLMProvider


def test_agent_can_call_skill_encryption():
    """Agent 调用 encryption skill 计算 hash。"""
    agent = build_agent(
        discover_all=False,
        include_skills=True,
        tools=[],
        verbose=False,
    )

    # Mock: agent calls skill_encryption then finishes
    agent._provider = MockLLMProvider([
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "hash", "text": "hello world", "algorithm": "sha256"},
            tool_call_id="tc_1",
        ),
        MockLLMProvider.text_response(
            "SHA256 哈希已计算完成。"
        ),
    ])

    result = agent.run("帮我计算 hello world 的 SHA256 哈希")
    assert result.success, f"Agent failed: {result.error}"
    assert result.total_steps >= 2


def test_agent_can_call_skill_json():
    """Agent 调用 json-toolkit 解析 JSON 文件。"""
    # Create test data
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}, f)
        tmp = f.name

    try:
        agent = build_agent(
            discover_all=False,
            include_skills=True,
            tools=[],
            verbose=False,
        )

        agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_json_toolkit",
                {"action": "query", "file_path": tmp, "query": "users.0.name"},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.text_response("查询结果: Alice"),
        ])

        result = agent.run("查询 JSON 文件中第一个用户的名字")
        assert result.success, f"Agent failed: {result.error}"
        assert result.total_steps >= 2
    finally:
        os.unlink(tmp)


def test_agent_can_call_skill_csv():
    """Agent 调用 csv-toolkit 分析 CSV 文件。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("name,age,score\nAlice,30,85\nBob,25,92\nCharlie,35,78\n")
        tmp = f.name

    try:
        agent = build_agent(
            discover_all=False,
            include_skills=True,
            tools=[],
            verbose=False,
        )

        agent._provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "skill_csv_toolkit",
                {"action": "headers", "file_path": tmp},
                tool_call_id="tc_1",
            ),
            MockLLMProvider.tool_response(
                "skill_csv_toolkit",
                {"action": "stats", "file_path": tmp},
                tool_call_id="tc_2",
            ),
            MockLLMProvider.text_response("CSV 分析完成：共 3 行，age 平均 30，score 平均 85。"),
        ])

        result = agent.run("分析这个 CSV 文件")
        assert result.success, f"Agent failed: {result.error}"
        assert result.total_steps >= 2
    finally:
        os.unlink(tmp)


def test_agent_multi_skill_chain():
    """Agent 链式调用多个不同 skill。"""
    agent = build_agent(
        discover_all=False,
        include_skills=True,
        tools=[],
        verbose=False,
    )

    agent._provider = MockLLMProvider([
        # Step 1: hash something
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "hash", "text": "data", "algorithm": "sha256"},
            tool_call_id="tc_1",
        ),
        # Step 2: encode
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "base64_encode", "text": "result"},
            tool_call_id="tc_2",
        ),
        MockLLMProvider.text_response("加密和编码已完成。"),
    ])

    result = agent.run("先计算哈希再 base64 编码")
    assert result.success, f"Agent failed: {result.error}"
    assert result.total_steps >= 2


def test_agent_handles_skill_error():
    """Agent 处理 skill 报错不崩溃。"""
    agent = build_agent(
        discover_all=False,
        include_skills=True,
        tools=[],
        verbose=False,
    )

    agent._provider = MockLLMProvider([
        MockLLMProvider.tool_response(
            "skill_csv_toolkit",
            {"action": "stats", "file_path": "/nonexistent/file.csv"},
            tool_call_id="tc_1",
        ),
        MockLLMProvider.text_response("文件不存在，无法分析。"),
    ])

    result = agent.run("分析不存在的 CSV 文件")
    assert result.success, f"Agent crashed: {result.error}"
    assert result.total_steps >= 1


def test_agent_skill_schema_correctness():
    """验证 skill 的 JSON schema 对 LLM 友好。"""
    agent = build_agent(
        discover_all=False,
        include_skills=True,
        tools=[],
        verbose=False,
    )
    schemas = agent._executor.get_schemas()

    # Find skill schemas with proper parameters
    skill_schemas = [s for s in schemas if s.function.name.startswith("skill_")]
    assert len(skill_schemas) >= 8, f"Expected at least 8 skills, got {len(skill_schemas)}"

    for s in skill_schemas:
        schema = s.as_schema()
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert "properties" in fn["parameters"]


def test_skill_actual_execution():
    """测试 skill 真实执行（encryption — 纯本地，不依赖网络）。"""
    import importlib
    import os
    import sys

    base = os.path.join(os.path.dirname(__file__), "..", "agentos", "marketplace", "skills")

    # Test encryption
    skill_py = os.path.join(base, "encryption", "encryption.py")
    spec = importlib.util.spec_from_file_location("test_enc", skill_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_enc"] = mod
    spec.loader.exec_module(mod)

    r1 = mod.run(action="hash", text="test", algorithm="md5")
    assert "MD5" in r1, f"Hash failed: {r1}"

    r2 = mod.run(action="base64_encode", text="hello")
    assert r2 == "aGVsbG8=", f"Base64 failed: {r2}"

    r3 = mod.run(action="uuid")
    assert "UUID" in r3, f"UUID failed: {r3}"


def test_csv_skill_actual_execution():
    """测试 csv-toolkit 真实执行。"""
    import importlib
    import os
    import sys
    import tempfile

    base = os.path.join(os.path.dirname(__file__), "..", "agentos", "marketplace", "skills")
    skill_py = os.path.join(base, "csv-toolkit", "csv-toolkit.py")
    spec = importlib.util.spec_from_file_location("test_csv", skill_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_csv"] = mod
    spec.loader.exec_module(mod)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("name,age\nAlice,30\nBob,25\n")
        tmp = f.name

    try:
        r = mod.run(action="headers", file_path=tmp)
        assert "name" in r and "age" in r, f"Headers failed: {r}"

        r2 = mod.run(action="stats", file_path=tmp)
        assert "行数: 2" in r2, f"Stats failed: {r2}"

        r3 = mod.run(action="filter", file_path=tmp, query="age > 27")
        assert "Alice" in r3, f"Filter failed: {r3}"
    finally:
        os.unlink(tmp)


def test_markdown_skill_actual_execution():
    """测试 markdown-toolkit 真实执行。"""
    import importlib
    import os
    import sys
    import tempfile

    base = os.path.join(os.path.dirname(__file__), "..", "agentos", "marketplace", "skills")
    skill_py = os.path.join(base, "markdown-toolkit", "markdown-toolkit.py")
    spec = importlib.util.spec_from_file_location("test_md", skill_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_md"] = mod
    spec.loader.exec_module(mod)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Title\n## Section 1\ntext\n## Section 2\nmore **bold** text\n")
        tmp = f.name

    try:
        r = mod.run(action="headings", file_path=tmp)
        assert "Section 1" in r, f"Heading failed: {r}"

        r2 = mod.run(action="stats", file_path=tmp)
        assert "行数" in r2, f"Stats failed: {r2}"
    finally:
        os.unlink(tmp)
