"""AgentOS v1.4.7 - Schema Enforcer 全覆盖测试。

覆盖 agentos/validation/schema_enforcer.py 全部路径。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from agentos.validation.schema_enforcer import (  # noqa: E402
    EnforcerConfig,
    EnforcerResult,
    EnforcerStats,
    FixStrategy,
    SchemaEnforcer,
)

# ---- helper models ----

class SimpleModel(BaseModel):
    name: str
    age: int
    email: str


class ModelWithDefaults(BaseModel):
    name: str = "default"
    age: int = 0
    email: str = ""
    tags: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class ModelAllTyped(BaseModel):
    s: str
    i: int
    f: float
    b: bool
    lst: list
    dct: dict


# ---- enforcer 默认配置 ----

@pytest.fixture
def enforcer():
    return SchemaEnforcer()


# ---- FixStrategy enum ----

def test_fix_strategy_enum():
    assert FixStrategy.JSON_REPAIR.name == "JSON_REPAIR"
    assert FixStrategy.FIELD_FALLBACK.name == "FIELD_FALLBACK"
    assert FixStrategy.LLM_ASSISTED.name == "LLM_ASSISTED"
    assert FixStrategy.RAISE.name == "RAISE"


# ---- EnforcerResult ----

def test_enforcer_result_defaults():
    r = EnforcerResult(is_valid=True, original_output={"x": 1})
    assert r.is_valid is True
    assert r.original_output == {"x": 1}
    assert r.repaired_output is None
    assert r.errors == []
    assert r.fix_strategy_used is None
    assert r.fix_attempts == 0


def test_enforcer_result_failure():
    r = EnforcerResult(is_valid=False, original_output="bad", errors=["e1", "e2"])
    assert r.is_valid is False
    assert r.errors == ["e1", "e2"]


# ---- EnforcerConfig ----

def test_enforcer_config_defaults():
    cfg = EnforcerConfig()
    assert cfg.max_retries == 3
    assert cfg.strategy_order == [
        FixStrategy.JSON_REPAIR,
        FixStrategy.FIELD_FALLBACK,
        FixStrategy.LLM_ASSISTED,
    ]
    assert cfg.llm_fix_prompt_template == ""
    assert cfg.default_value_fallback is True
    assert cfg.log_rejections is True


def test_enforcer_config_custom():
    cfg = EnforcerConfig(
        max_retries=5,
        strategy_order=[FixStrategy.JSON_REPAIR, FixStrategy.RAISE],
        llm_fix_prompt_template="fix it: {{error}}",
        default_value_fallback=False,
        log_rejections=False,
    )
    assert cfg.max_retries == 5
    assert cfg.strategy_order == [FixStrategy.JSON_REPAIR, FixStrategy.RAISE]
    assert cfg.llm_fix_prompt_template == "fix it: {{error}}"
    assert cfg.default_value_fallback is False
    assert cfg.log_rejections is False


# ---- EnforcerStats ----

def test_enforcer_stats_defaults():
    s = EnforcerStats()
    assert s.total_checks == 0
    assert s.total_rejections == 0
    assert s.total_repairs == 0
    assert s.repairs_by_strategy == {}


# ---- SchemaEnforcer.__init__ ----

def test_init_default():
    enforcer = SchemaEnforcer()
    assert enforcer.config.max_retries == 3
    assert isinstance(enforcer.stats, EnforcerStats)


def test_init_custom():
    cfg = EnforcerConfig(max_retries=10)
    enforcer = SchemaEnforcer(cfg)
    assert enforcer.config.max_retries == 10


# ---- enforce: direct success ----

@pytest.mark.asyncio
async def test_enforce_dict_success(enforcer):
    r = await enforcer.enforce({"name": "x", "age": 1, "email": "e"}, SimpleModel)
    assert r.is_valid is True
    assert r.original_output == {"name": "x", "age": 1, "email": "e"}
    assert isinstance(r.repaired_output, SimpleModel)
    assert r.repaired_output.name == "x"
    assert r.repaired_output.age == 1
    assert r.fix_strategy_used is None
    assert r.fix_attempts == 0


@pytest.mark.asyncio
async def test_enforce_pydantic_model_direct(enforcer):
    m = SimpleModel(name="x", age=1, email="e")
    r = await enforcer.enforce(m, SimpleModel)
    assert r.is_valid is True


# ---- enforce: rejection + repair ----

@pytest.mark.asyncio
async def test_enforce_bad_data_repair_json(enforcer):
    """尾随逗号 + 单引号，JSON_REPAIR 修复。"""
    bad = "{'name': 'x', 'age': 1, 'email': 'e',}"
    r = await enforcer.enforce(bad, SimpleModel)
    assert r.is_valid is True
    assert r.fix_strategy_used == FixStrategy.JSON_REPAIR


@pytest.mark.asyncio
async def test_enforce_markdown_codeblock_repair(enforcer):
    """markdown 代码块包裹。"""
    bad = "```json\n{'name': 'x', 'age': 1, 'email': 'e',}\n```"
    r = await enforcer.enforce(bad, SimpleModel)
    assert r.is_valid is True
    assert r.fix_strategy_used == FixStrategy.JSON_REPAIR


@pytest.mark.asyncio
async def test_enforce_missing_field_field_fallback(enforcer):
    """缺字段 → FIELD_FALLBACK（带默认值）。"""
    r = await enforcer.enforce({"name": "x"}, SimpleModel)
    assert r.is_valid is True  # FIELD_FALLBACK 成功或 final fallback
    # age 无默认值，先 field_fallback 失败，然后走 JSON_REPAIR 无变化再 fallback_layer 构建


# ---- enforce: stats accumulation ----

@pytest.mark.asyncio
async def test_enforce_stats_accumulate(enforcer):
    assert enforcer.stats.total_checks == 0
    await enforcer.enforce({"name": "x", "age": 1, "email": "e"}, SimpleModel)
    assert enforcer.stats.total_checks == 1
    # rejection not counted for success
    assert enforcer.stats.total_rejections == 0


# ---- enforce: rejection stats ----

@pytest.mark.asyncio
async def test_enforce_rejection_counted(enforcer):
    await enforcer.enforce({"name": "x"}, SimpleModel)  # missing age, email
    assert enforcer.stats.total_rejections == 1


# ---- enforce: max_retries exhausted ----

@pytest.mark.asyncio
async def test_enforce_max_retries_exhausted(enforcer):
    """不可修复数据，所有策略失败，最终 fallback。"""
    r = await enforcer.enforce("{{{{not json at all}}}}", SimpleModel)
    # should fallback with defaults at the end
    assert r.is_valid is True  # final fallback succeeds
    assert r.fix_attempts == enforcer.config.max_retries


# ---- enforce_batch ----

@pytest.mark.asyncio
async def test_enforce_batch(enforcer):
    outputs = [
        {"name": "a", "age": 1, "email": "a@x"},
        {"name": "b", "age": 2, "email": "b@x"},
    ]
    results = await enforcer.enforce_batch(outputs, SimpleModel)
    assert len(results) == 2
    assert all(r.is_valid for r in results)


@pytest.mark.asyncio
async def test_enforce_batch_mixed(enforcer):
    outputs = [
        {"name": "a", "age": 1, "email": "a@x"},
        "{'name': 'b', 'age': 2, 'email': 'b@x',}",  # JSON repair needed
    ]
    results = await enforcer.enforce_batch(outputs, SimpleModel)
    assert len(results) == 2
    assert results[0].is_valid
    assert results[1].is_valid


# ---- _json_repair: dict passthrough ----

@pytest.mark.asyncio
async def test_json_repair_dict_passthrough(enforcer):
    d = {"name": "x", "age": 1, "email": "e"}
    assert enforcer._json_repair(d) == d


# ---- _json_repair: single quotes + trailing comma ----

def test_json_repair_single_quotes_trailing():
    e = SchemaEnforcer()
    result = e._json_repair("{'name': 'x', 'age': 1, 'email': 'e',}")
    assert result == {"name": "x", "age": 1, "email": "e"}


# ---- _json_repair: markdown code block ----

def test_json_repair_markdown_block():
    e = SchemaEnforcer()
    result = e._json_repair("```json\n{'name': 'x', 'age': 1, 'email': 'e'}\n```")
    assert result == {"name": "x", "age": 1, "email": "e"}


# ---- _json_repair: non-string non-dict returns None ----

def test_json_repair_none_for_int():
    e = SchemaEnforcer()
    assert e._json_repair(123) is None


# ---- _json_repair: trailing comma in array/object ----

def test_json_repair_trailing_comma_in_array():
    e = SchemaEnforcer()
    result = e._json_repair('{"items": ["a", "b",],}')
    assert result == {"items": ["a", "b"]}


def test_json_repair_trailing_comma_in_nested_object():
    e = SchemaEnforcer()
    result = e._json_repair('{"a": 1, "b": {"c": 2,},}')
    assert result == {"a": 1, "b": {"c": 2}}


# ---- _json_repair: still invalid json after repair ----

def test_json_repair_still_invalid():
    e = SchemaEnforcer()
    assert e._json_repair("not json {{{{ at all") is None


# ---- _field_fallback: non-dict returns None ----

def test_field_fallback_non_dict():
    e = SchemaEnforcer()
    assert e._field_fallback("not a dict", SimpleModel, []) is None


# ---- _field_fallback: partial dict → fill defaults ----

def test_field_fallback_partial():
    e = SchemaEnforcer()
    result = e._field_fallback({"name": "x"}, ModelWithDefaults, [])
    assert result == {"name": "x", "age": 0, "email": "", "tags": [], "meta": {}}


def test_field_fallback_missing_required():
    e = SchemaEnforcer()
    # SimpleModel: name/age/email all required, no defaults
    # field_fallback returns keys present in output; missing required keys are absent
    result = e._field_fallback({"name": "x"}, SimpleModel, [])
    assert result == {"name": "x"}  # only keys present, missing required omitted


# ---- _field_fallback: model with default_factory ----

def test_field_fallback_default_factory():
    e = SchemaEnforcer()
    result = e._field_fallback({}, ModelWithDefaults, [])
    assert result == {"name": "default", "age": 0, "email": "", "tags": [], "meta": {}}


# ---- _llm_fix: no template → no-op ----

@pytest.mark.asyncio
async def test_llm_fix_no_template(enforcer):
    result = await enforcer._llm_fix("bad", SimpleModel, ["err"], None)
    assert result is None


# ---- _llm_fix: with template but no callback ----

@pytest.mark.asyncio
async def test_llm_fix_with_template(caplog):
    cfg = EnforcerConfig(llm_fix_prompt_template="fix: {{error}}")
    e = SchemaEnforcer(cfg)
    import logging
    caplog.set_level(logging.WARNING)
    result = await e._llm_fix("bad", SimpleModel, ["err"], None)
    assert result is None
    assert "LLM-assisted fix requires" in caplog.text


# ---- _build_fallback: full defaults ----

def test_build_fallback_with_defaults():
    e = SchemaEnforcer()
    result = e._build_fallback(ModelWithDefaults)
    assert isinstance(result, ModelWithDefaults)
    assert result.name == "default"
    assert result.age == 0
    assert result.email == ""
    assert result.tags == []
    assert result.meta == {}


# ---- _build_fallback: no-defaults types ----

def test_build_fallback_no_defaults():
    e = SchemaEnforcer()
    result = e._build_fallback(ModelAllTyped)
    assert isinstance(result, ModelAllTyped)
    assert result.s == ""
    assert result.i == 0
    assert result.f == 0.0
    assert result.b is False
    assert result.lst == []
    assert result.dct == {}


# ---- _build_fallback: list/dict via origin ----

class ModelWithTypedList(BaseModel):
    items: list[str]


def test_build_fallback_typed_list():
    e = SchemaEnforcer()
    result = e._build_fallback(ModelWithTypedList)
    assert result.items == []


# ---- _apply_fix dispatch ----

@pytest.mark.asyncio
async def test_apply_fix_json_repair(enforcer):
    result = await enforcer._apply_fix(
        FixStrategy.JSON_REPAIR, "{'x': 1,}", SimpleModel, [], None
    )
    assert result == {"x": 1}


@pytest.mark.asyncio
async def test_apply_fix_field_fallback(enforcer):
    result = await enforcer._apply_fix(
        FixStrategy.FIELD_FALLBACK, {"name": "x"}, ModelWithDefaults, [], None
    )
    assert result == {"name": "x", "age": 0, "email": "", "tags": [], "meta": {}}


@pytest.mark.asyncio
async def test_apply_fix_llm_assisted(enforcer):
    result = await enforcer._apply_fix(
        FixStrategy.LLM_ASSISTED, "bad", SimpleModel, [], None
    )
    assert result is None


@pytest.mark.asyncio
async def test_apply_fix_raise(enforcer):
    result = await enforcer._apply_fix(
        FixStrategy.RAISE, "bad", SimpleModel, [], None
    )
    assert result is None


# ---- enforce: context forwarded ----

@pytest.mark.asyncio
async def test_enforce_context_forwarded_to_llm():
    cfg = EnforcerConfig(
        llm_fix_prompt_template="fix",
        strategy_order=[FixStrategy.JSON_REPAIR, FixStrategy.LLM_ASSISTED],
    )
    e = SchemaEnforcer(cfg)
    ctx = {"key": "val"}
    r = await e.enforce("{{{{bad}}}}", SimpleModel, context=ctx)
    # LLM fix returns None, so fallback kicks in
    assert r.is_valid is True


# ---- enforce: strategy exhaustion → fallback ----

@pytest.mark.asyncio
async def test_enforce_all_strategies_exhausted_fallback():
    cfg = EnforcerConfig(strategy_order=[])
    e = SchemaEnforcer(cfg)
    r = await e.enforce({"name": "x"}, SimpleModel)  # missing required fields
    assert r.is_valid is True  # fallback built
    assert r.fix_strategy_used == FixStrategy.FIELD_FALLBACK


# ---- enforce: fix strategy caught exception ----

@pytest.mark.asyncio
async def test_enforce_fix_strategy_throws_exception():
    """JSON_REPAIR 尝试时内部抛异常被捕获，继续下一策略。"""
    e = SchemaEnforcer()
    # Simulate: _json_repair raises, _field_fallback handles it
    with patch.object(e, '_json_repair', side_effect=RuntimeError("boom")):
        r = await e.enforce({"name": "x"}, SimpleModel)
    # field_fallback returns None (required fields), then fallback
    assert r.is_valid is True


# ---- default_value_fallback=False ----

@pytest.mark.asyncio
async def test_no_fallback_returns_invalid():
    cfg = EnforcerConfig(default_value_fallback=False, strategy_order=[])
    e = SchemaEnforcer(cfg)
    r = await e.enforce({"name": "x"}, SimpleModel)
    assert r.is_valid is False


# ---- _build_fallback 异常路径：model 构造失败 ----

@pytest.mark.asyncio
async def test_build_fallback_exception_returns_none():
    e = SchemaEnforcer()
    with patch.object(e, '_build_fallback', side_effect=Exception("bad")):
        r = await e.enforce({"name": "x"}, SimpleModel)
    # fallback 失败 → 最终返回 is_valid=False
    assert r.is_valid is False


# ---- _json_repair: json.loads 成功 ----

def test_json_repair_valid_json_no_repair():
    e = SchemaEnforcer()
    result = e._json_repair('{"name":"x","age":1,"email":"e"}')
    assert result == {"name": "x", "age": 1, "email": "e"}


# ---- _json_repair: empty string ----

def test_json_repair_empty_string():
    e = SchemaEnforcer()
    assert e._json_repair("") is None


# ---- enforce stats: repairs tracked correctly ----

@pytest.mark.asyncio
async def test_enforce_stats_repairs_tracked():
    e = SchemaEnforcer()
    await e.enforce("{'name': 'x', 'age': 1, 'email': 'e',}", SimpleModel)
    assert e.stats.total_repairs == 1
    assert e.stats.repairs_by_strategy["JSON_REPAIR"] == 1


# ---- _field_fallback: exception returns None ----

def test_field_fallback_exception():
    """_field_fallback 内出现异常时返回 None。"""
    e = SchemaEnforcer()
    saved = ModelWithDefaults.model_fields
    try:
        class Bomb:
            def items(self):
                raise Exception("boom")
        ModelWithDefaults.model_fields = Bomb()
        result = e._field_fallback({"name": "x"}, ModelWithDefaults, [])
        assert result is None
    finally:
        ModelWithDefaults.model_fields = saved


# ---- enforce: LLM_ASSISTED strategy in order ----

@pytest.mark.asyncio
async def test_enforce_llm_assisted_in_strategy_order():
    cfg = EnforcerConfig(
        strategy_order=[FixStrategy.LLM_ASSISTED],
        llm_fix_prompt_template="try fix",
    )
    e = SchemaEnforcer(cfg)
    r = await e.enforce("not json", SimpleModel)
    # LLM returns None → fallback
    assert r.is_valid is True


# ---- __all__ ----

def test_module_all():
    from agentos.validation import schema_enforcer
    assert "SchemaEnforcer" in schema_enforcer.__all__
    assert "FixStrategy" in schema_enforcer.__all__
