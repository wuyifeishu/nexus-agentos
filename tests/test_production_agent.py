"""
ProductionAgent 集成测试 — 验证生产级 Agent 的完整生命周期。
"""

import os
import tempfile

from agentos.agent.production_agent import AgentResult, ProductionAgent
from agentos.agent.tool_agent import MockLLMProvider


def test_production_agent_instantiation():
    """验证 ProductionAgent 可以正常实例化并注册所有工具。"""
    agent = ProductionAgent(include_skills=True)
    tool_count = agent.get_tool_count()
    assert tool_count >= 8, f"Expected >= 8 tools, got {tool_count}"

    tools = agent.list_tools()
    skill_tools = [t for t in tools if t.startswith("skill_")]
    assert len(skill_tools) >= 8, f"Expected >= 8 skills, got {len(skill_tools)}: {skill_tools}"


def test_production_agent_run_with_mock():
    """验证 Agent 通过 Mock LLM 执行完整任务流。"""
    from agentos.agent.agent_builder import _MockProvider

    agent = ProductionAgent(
        provider=_MockProvider(),
        include_skills=True,
    )

    result = agent.run("列出当前目录的文件")
    assert result.success, f"Agent failed: {result.error}"
    assert result.output, "Should have output"
    assert result.total_steps >= 1


def test_production_agent_skill_invocation():
    """验证 Agent 能通过 Mock 调用真实 Skill。"""
    agent = ProductionAgent(include_skills=True)

    # Inject Mock provider that calls encryption skill
    agent._agent._provider = MockLLMProvider([
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "hash", "text": "hello", "algorithm": "md5"},
            tool_call_id="tc_1",
        ),
        MockLLMProvider.text_response("哈希计算完成。"),
    ])

    result = agent.run("计算 hello 的 MD5")
    assert result.success, f"Agent failed: {result.error}"
    assert result.total_steps >= 2


def test_production_agent_csv_workflow():
    """端到端: Agent 读取 CSV 文件并分析。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("product,price,qty\nApple,1.5,100\nBanana,0.8,200\nOrange,2.0,50\n")
        tmp = f.name

    try:
        agent = ProductionAgent(include_skills=True)
        agent._agent._provider = MockLLMProvider([
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
            MockLLMProvider.text_response(
                "CSV 分析完成: 共 3 种产品，总价值 $385.00，Orange 单价最高。"
            ),
        ])

        result = agent.run("分析这个 CSV 文件的销售数据")
        assert result.success, f"Agent failed: {result.error}"
        assert "Orange" in result.output or "385" in result.output
        assert result.total_steps >= 2
    finally:
        os.unlink(tmp)


def test_production_agent_error_handling():
    """验证 Agent 优雅处理不存在文件等错误。"""
    agent = ProductionAgent(include_skills=True)
    agent._agent._provider = MockLLMProvider([
        MockLLMProvider.tool_response(
            "skill_csv_toolkit",
            {"action": "stats", "file_path": "/nonexistent/dead.csv"},
            tool_call_id="tc_1",
        ),
        MockLLMProvider.text_response("抱歉，文件不存在，无法分析。"),
    ])

    result = agent.run("分析 dead.csv")
    assert result.success, f"Agent should not crash. Output: {result.error}"


def test_production_agent_result_structure():
    """验证 AgentResult 包含所有必要字段。"""
    from agentos.agent.agent_builder import _MockProvider

    agent = ProductionAgent(provider=_MockProvider())
    result = agent.run("hello")

    assert isinstance(result, AgentResult)
    assert isinstance(result.success, bool)
    assert isinstance(result.output, str)
    assert isinstance(result.total_steps, int)
    assert isinstance(result.total_latency_ms, (int, float))
    assert isinstance(result.tool_calls, int)


def test_production_agent_without_skills():
    """验证不带 Skill 的 Agent 仍然可用。"""
    agent = ProductionAgent(include_skills=False)
    tools = agent.list_tools()
    skill_tools = [t for t in tools if t.startswith("skill_")]
    assert len(skill_tools) == 0, f"Should have no skills: {skill_tools}"
    assert len(tools) >= 1, "Should have at least base tools"


def test_production_agent_multi_step():
    """验证多步工具链式调用。"""
    agent = ProductionAgent(include_skills=True)
    agent._agent._provider = MockLLMProvider([
        # Step 1: hash
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "hash", "text": "secret", "algorithm": "sha256"},
            tool_call_id="tc_1",
        ),
        # Step 2: base64
        MockLLMProvider.tool_response(
            "skill_encryption",
            {"action": "base64_encode", "text": "hashed_value"},
            tool_call_id="tc_2",
        ),
        MockLLMProvider.text_response("加密完成: SHA256 + Base64。"),
    ])

    result = agent.run("先 SHA256 再 base64 编码 secret")
    assert result.success, f"Agent failed: {result.error}"
    assert result.total_steps >= 3  # 2 tool calls + 1 text
