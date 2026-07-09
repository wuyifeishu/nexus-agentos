"""AgentOS v1.3.9 - Schema Enforcer 模块。

对 Agent 输出执行 Pydantic schema 校验，校验失败时自动修复/重试。
支持 JSON 修复、字段回退、LLM 辅助修正三种修复策略。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class FixStrategy(Enum):
    """修复策略枚举。"""

    JSON_REPAIR = auto()
    FIELD_FALLBACK = auto()
    LLM_ASSISTED = auto()
    RAISE = auto()


@dataclass
class EnforcerResult:
    """校验执行结果。"""

    is_valid: bool
    original_output: Any
    repaired_output: Any | None = None
    errors: list[str] = field(default_factory=list)
    fix_strategy_used: FixStrategy | None = None
    fix_attempts: int = 0


@dataclass
class EnforcerConfig:
    """Schema Enforcer 配置。"""

    max_retries: int = 3
    strategy_order: list[FixStrategy] = field(
        default_factory=lambda: [
            FixStrategy.JSON_REPAIR,
            FixStrategy.FIELD_FALLBACK,
            FixStrategy.LLM_ASSISTED,
        ]
    )
    llm_fix_prompt_template: str = ""
    default_value_fallback: bool = True
    log_rejections: bool = True


@dataclass
class EnforcerStats:
    """校验统计。"""

    total_checks: int = 0
    total_rejections: int = 0
    total_repairs: int = 0
    repairs_by_strategy: dict[str, int] = field(default_factory=dict)


class SchemaEnforcer:
    """对 Agent 输出执行 Pydantic schema 校验与自动修复。

    核心流程：
    1. 尝试直接 model_validate
    2. 失败时按 strategy_order 依次尝试修复
    3. 所有策略耗尽仍失败则降级为 FIELD_FALLBACK（最佳努力）
    """

    def __init__(self, config: EnforcerConfig | None = None):
        self.config = config or EnforcerConfig()
        self.stats = EnforcerStats()

    async def enforce(
        self,
        output: dict | str | Any,
        schema_model: type,
        context: dict | None = None,
    ) -> EnforcerResult:
        """对单次输出执行 schema 校验。"""
        self.stats.total_checks += 1
        errors: list[str] = []

        try:
            validated = schema_model.model_validate(output)
            return EnforcerResult(is_valid=True, original_output=output, repaired_output=validated)
        except Exception as e:
            errors.append(str(e))
            self.stats.total_rejections += 1

        result = EnforcerResult(is_valid=False, original_output=output, errors=errors)

        for attempt in range(self.config.max_retries):
            for strategy in self.config.strategy_order:
                try:
                    repaired = await self._apply_fix(
                        strategy, output, schema_model, errors, context
                    )
                    if repaired is not None:
                        validated = schema_model.model_validate(repaired)
                        self.stats.total_repairs += 1
                        strat_key = strategy.name
                        self.stats.repairs_by_strategy[strat_key] = (
                            self.stats.repairs_by_strategy.get(strat_key, 0) + 1
                        )
                        result.is_valid = True
                        result.repaired_output = validated
                        result.fix_strategy_used = strategy
                        result.fix_attempts = attempt + 1
                        if self.config.log_rejections:
                            logger.info(
                                "Schema fixed via %s (attempt %d/%d)",
                                strategy.name,
                                attempt + 1,
                                self.config.max_retries,
                            )
                        return result
                except Exception as fix_error:
                    errors.append(f"[{strategy.name}] {fix_error}")

        if self.config.default_value_fallback:
            try:
                fallback = self._build_fallback(schema_model)
                self.stats.total_repairs += 1
                self.stats.repairs_by_strategy["FALLBACK"] = (
                    self.stats.repairs_by_strategy.get("FALLBACK", 0) + 1
                )
                result.is_valid = True
                result.repaired_output = fallback
                result.fix_strategy_used = FixStrategy.FIELD_FALLBACK
                result.fix_attempts = self.config.max_retries
                return result
            except Exception:
                pass

        return result

    async def _apply_fix(
        self,
        strategy: FixStrategy,
        output: Any,
        model: type,
        errors: list[str],
        context: dict | None,
    ) -> dict | None:
        if strategy == FixStrategy.JSON_REPAIR:
            return self._json_repair(output)
        elif strategy == FixStrategy.FIELD_FALLBACK:
            return self._field_fallback(output, model, errors)
        elif strategy == FixStrategy.LLM_ASSISTED:
            return await self._llm_fix(output, model, errors, context)
        return None

    def _json_repair(self, output: Any) -> dict | None:
        """尝试修复 JSON 格式问题（尾部逗号、单引号、截断等）。"""
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            s = output.strip()
            # 去除 markdown 代码块包裹
            if s.startswith("```"):
                lines = s.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                s = "\n".join(lines)
            # 修复常见 JSON 问题
            s = s.replace("'", '"')
            # 修复尾部多余逗号
            import re

            s = re.sub(r",(\s*[}\]])", r"\1", s)
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
        return None

    def _field_fallback(self, output: Any, model: type, errors: list[str]) -> dict | None:
        """从原始输出中尽力提取有效字段，缺失字段填默认值。"""
        from pydantic_core import PydanticUndefined

        try:
            if not isinstance(output, dict):
                return None
            fields_info = model.model_fields
            clean: dict = {}
            for key, finfo in fields_info.items():
                if key in output:
                    clean[key] = output[key]
                elif finfo.default is not PydanticUndefined:
                    clean[key] = finfo.default
                elif finfo.default_factory is not None:
                    clean[key] = finfo.default_factory()
            return clean if clean else None
        except Exception:
            return None

    async def _llm_fix(
        self, output: Any, model: type, errors: list[str], context: dict | None
    ) -> dict | None:
        """通过 LLM 辅助修复（调用方需注入 llm_call 回调）。"""
        if self.config.llm_fix_prompt_template:
            logger.warning("LLM-assisted fix requires llm_call callback (not implemented inline).")
        return None

    def _build_fallback(self, model: type) -> Any:
        """使用全默认值构建回退对象。"""
        from pydantic_core import PydanticUndefined

        fields_info = model.model_fields
        kwargs: dict = {}
        for key, finfo in fields_info.items():
            if finfo.default is not PydanticUndefined:
                kwargs[key] = finfo.default
            elif finfo.default_factory is not None:
                kwargs[key] = finfo.default_factory()
            else:
                annotation = finfo.annotation
                origin = getattr(annotation, "__origin__", None)
                if annotation is str:
                    kwargs[key] = ""
                elif annotation is int:
                    kwargs[key] = 0
                elif annotation is float:
                    kwargs[key] = 0.0
                elif annotation is bool:
                    kwargs[key] = False
                elif annotation is list or origin is list:
                    kwargs[key] = []
                elif annotation is dict or origin is dict:
                    kwargs[key] = {}
        return model(**kwargs)

    async def enforce_batch(
        self,
        outputs: list[dict | str],
        schema_model: type,
        context: dict | None = None,
    ) -> list[EnforcerResult]:
        """批量校验，利用异步并发。"""
        tasks = [self.enforce(out, schema_model, context) for out in outputs]
        return await asyncio.gather(*tasks)


__all__ = [
    "SchemaEnforcer",
    "EnforcerConfig",
    "EnforcerResult",
    "EnforcerStats",
    "FixStrategy",
]
