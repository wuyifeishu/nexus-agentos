"""Tests for agentos.validation.schema_enforcer."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field
from agentos.validation.schema_enforcer import (
    SchemaEnforcer,
    EnforcerConfig,
    EnforcerResult,
    FixStrategy,
)


class SimpleOutput(BaseModel):
    """测试用简单输出 schema。"""

    name: str
    score: float
    category: str = "general"


class NestedOutput(BaseModel):
    """测试用嵌套输出 schema。"""

    title: str
    items: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


@pytest.fixture
def enforcer():
    return SchemaEnforcer()


@pytest.mark.asyncio
async def test_valid_output_passes(enforcer):
    """合法输出直接通过。"""
    output = {"name": "task1", "score": 0.95, "category": "code"}
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.fix_attempts == 0
    assert result.repaired_output.name == "task1"


@pytest.mark.asyncio
async def test_missing_field_fallback(enforcer):
    """缺失字段使用默认值回退。"""
    output = {"name": "task2", "score": 0.88}
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.repaired_output.category == "general"


@pytest.mark.asyncio
async def test_json_string_repair(enforcer):
    """JSON 字符串格式自动修复。"""
    output = '{"name": "task3", "score": 0.75,}'
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.repaired_output.name == "task3"


@pytest.mark.asyncio
async def test_json_markdown_codeblock_repair(enforcer):
    """Markdown 代码块包裹的 JSON 自动修复。"""
    output = '```json\n{"name": "task4", "score": 0.65}\n```'
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.repaired_output.name == "task4"


@pytest.mark.asyncio
async def test_single_quote_json_repair(enforcer):
    """单引号 JSON 自动修复。"""
    output = "{'name': 'task5', 'score': 0.55}"
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.repaired_output.name == "task5"


@pytest.mark.asyncio
async def test_extra_field_ok(enforcer):
    """多余字段不影响校验。"""
    output = {"name": "task6", "score": 0.45, "extra_field": "ignored"}
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid


@pytest.mark.asyncio
async def test_completely_invalid_full_fallback(enforcer):
    """完全无效时全默认值回退。"""
    output = {"wrong": "oops"}
    result = await enforcer.enforce(output, SimpleOutput)
    assert result.is_valid
    assert result.repaired_output.name == ""


@pytest.mark.asyncio
async def test_nested_output(enforcer):
    """嵌套 schema 校验。"""
    output = {"title": "report", "items": [{"a": 1}], "meta": {"page": 1}}
    result = await enforcer.enforce(output, NestedOutput)
    assert result.is_valid
    assert result.repaired_output.items == [{"a": 1}]


@pytest.mark.asyncio
async def test_stats_tracking(enforcer):
    """校验统计正确累加。"""
    await enforcer.enforce({"name": "x", "score": 1.0}, SimpleOutput)
    await enforcer.enforce({"bad": True}, SimpleOutput)
    assert enforcer.stats.total_checks == 2
    assert enforcer.stats.total_rejections == 1
    assert enforcer.stats.total_repairs >= 1


@pytest.mark.asyncio
async def test_enforce_batch(enforcer):
    """批量校验。"""
    outputs = [
        {"name": "b1", "score": 0.9},
        {"name": "b2", "score": 0.8},
        {"name": "b3", "score": 0.7},
    ]
    results = await enforcer.enforce_batch(outputs, SimpleOutput)
    assert len(results) == 3
    assert all(r.is_valid for r in results)


@pytest.mark.asyncio
async def test_fix_strategy_order_respected():
    """自定义策略顺序生效。"""
    config = EnforcerConfig(
        strategy_order=[FixStrategy.FIELD_FALLBACK, FixStrategy.JSON_REPAIR],
        max_retries=1,
    )
    enf = SchemaEnforcer(config)
    output = "{'name': 's', 'score': 0.3,}"
    result = await enf.enforce(output, SimpleOutput)
    assert result.is_valid
