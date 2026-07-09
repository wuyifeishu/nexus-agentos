"""
SkillTool — 将 marketplace skill 包装为 BaseTool，通过 Bridge 注册到 ToolAgent。

每个 skill 的 run(**kwargs) 函数变成 Agent 可直接调用的工具。
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
from collections.abc import Callable

from agentos.tools.base import BaseTool, ToolResult


class SkillTool(BaseTool):
    """将一个 marketplace skill 的 run() 函数包装为 BaseTool。

    skill 的 run(**kwargs) 接收任意关键字参数并返回字符串。
    """

    permission_level = "safe"  # type: ignore

    def __init__(
        self,
        skill_name: str,
        skill_run: Callable[..., str],
        description: str = "",
        parameters: dict | None = None,
    ):
        self._skill_name = skill_name
        self._run_fn = skill_run
        self._description = description
        self._parameters = parameters

    @property
    def name(self) -> str:
        return self._skill_name

    @property
    def description(self) -> str:
        return self._description or f"Execute the '{self._skill_name}' skill."

    @property
    def parameters(self) -> dict:
        if self._parameters:
            return self._parameters
        # Default: accept arbitrary kwargs
        return {
            "type": "object",
            "properties": {
                "kwargs": {
                    "type": "string",
                    "description": "JSON string of keyword arguments to pass to the skill",
                }
            },
        }

    async def execute(self, input_data: dict) -> ToolResult:
        try:
            # If input has 'kwargs', parse as JSON
            if "kwargs" in input_data:
                parsed = json.loads(input_data["kwargs"])
            else:
                parsed = input_data

            result = self._run_fn(**parsed)
            return ToolResult(call_id=self.name, output=str(result))
        except Exception as e:
            return ToolResult(call_id=self.name, error=str(e))


def discover_skills(skills_dir: str = None) -> list[SkillTool]:
    """自动发现 marketplace/skills 下所有 skill 并包装为 SkillTool。

    Args:
        skills_dir: skills 目录路径。默认自动定位。

    Returns:
        SkillTool 实例列表。
    """
    if skills_dir is None:
        # Auto-locate
        agentos_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        skills_dir = os.path.join(agentos_dir, "marketplace", "skills")

    if not os.path.isdir(skills_dir):
        return []

    tools: list[SkillTool] = []

    for entry in sorted(os.listdir(skills_dir)):
        skill_path = os.path.join(skills_dir, entry)
        if not os.path.isdir(skill_path):
            continue

        skill_py = os.path.join(skill_path, f"{entry}.py")
        if not os.path.isfile(skill_py):
            continue

        try:
            # Import the skill module
            spec = importlib.util.spec_from_file_location(
                f"agentos_marketplace_skill_{entry}", skill_py
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)

            run_fn = getattr(mod, "run", None)
            if run_fn is None or not callable(run_fn):
                continue

            # Get docstring as description
            desc = (mod.__doc__ or f"Execute the '{entry}' skill.").strip().split("\n")[0]

            # Try to get parameter schema from function signature
            params = _infer_parameters(run_fn)

            tool = SkillTool(
                skill_name=f"skill_{entry.replace('-', '_')}",
                skill_run=run_fn,
                description=desc,
                parameters=params,
            )
            tools.append(tool)
        except Exception:
            # Skip skills that fail to load
            continue

    return tools


def _infer_parameters(fn: Callable) -> dict:
    """从函数签名推断 JSON Schema 参数定义。"""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return {
            "type": "object",
            "properties": {"kwargs": {"type": "string", "description": "JSON string of arguments"}},
        }

    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        param_type = "string"
        if param.annotation is not inspect.Parameter.empty:
            anno = param.annotation
            if anno is str:
                param_type = "string"
            elif anno is int:
                param_type = "integer"
            elif anno is float:
                param_type = "number"
            elif anno is bool:
                param_type = "boolean"
            elif anno is list:
                param_type = "array"

        properties[name] = {"type": param_type, "description": f"Parameter: {name}"}

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
