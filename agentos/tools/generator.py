"""
OpenAPI工具自动生成器 — 从OpenAPI/Swagger spec自动生成Agent工具包装器。
v0.50: 新增模块。将REST API端点自动转换为Agent可调用的ToolCall格式。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass
class GeneratedTool:
    """单个生成的工具描述。"""
    name: str
    description: str
    operation_id: str = ""
    method: str = "GET"
    path: str = ""
    parameters_schema: dict = field(default_factory=dict)
    auth_header: str = ""
    base_url: str = ""

    def to_openai_function(self) -> dict:
        """转换为OpenAI function calling格式。"""
        func = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
            },
        }
        if self.parameters_schema:
            func["function"]["parameters"] = self.parameters_schema
        return func

    def to_tool_dict(self) -> dict:
        """转换为通用工具描述字典。"""
        return {
            "name": self.name,
            "description": self.description,
            "operation_id": self.operation_id,
            "method": self.method,
            "path_template": self.path,
            "parameters": self.parameters_schema,
            "base_url": self.base_url,
            "auth_header": self.auth_header,
        }


class OpenAPIToolGenerator:
    """
    从OpenAPI 3.x / Swagger 2.0 spec生成Agent工具。

    用法:
        gen = OpenAPIToolGenerator("https://api.example.com/openapi.json")
        tools = await gen.generate()
        # tools是GeneratedTool列表，可直接注入Agent context
    """

    PARAM_TYPE_MAP = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "number": {"type": "number"},
        "boolean": {"type": "boolean"},
        "array": {"type": "array", "items": {"type": "string"}},
        "object": {"type": "object"},
    }

    def __init__(self, spec_url: str = "", spec_path: str = "", api_base: str = "",
                 auth_header: str = "Authorization", auth_value: str = ""):
        self.spec_url = spec_url
        self.spec_path = spec_path
        self.api_base = api_base
        self.auth_header = auth_header
        self.auth_value = auth_value
        self._http = httpx.AsyncClient(timeout=30)

    async def load_spec(self) -> dict:
        """加载OpenAPI spec（URL或本地文件）。"""
        if self.spec_url:
            resp = await self._http.get(self.spec_url)
            resp.raise_for_status()
            if self.spec_url.endswith((".yaml", ".yml")):
                return yaml.safe_load(resp.text)
            return resp.json()

        if self.spec_path:
            path = Path(self.spec_path)
            text = path.read_text(encoding="utf-8")
            if path.suffix in (".yaml", ".yml"):
                return yaml.safe_load(text)
            return json.loads(text)

        raise ValueError("spec_url or spec_path required")

    async def generate(self, filter_tag: str = "", max_tools: int = 100) -> list[GeneratedTool]:
        """解析spec并生成工具列表。"""
        spec = await self.load_spec()
        tools: list[GeneratedTool] = []
        base_url = self.api_base or self._extract_base_url(spec)
        paths = spec.get("paths", {})

        for path_url, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue
                if not isinstance(operation, dict):
                    continue

                tags = operation.get("tags", [])
                if filter_tag and filter_tag not in tags:
                    continue

                tool = self._build_tool(path_url, method, operation, base_url)
                tools.append(tool)
                if len(tools) >= max_tools:
                    return tools

        return tools

    def _build_tool(self, path_url: str, method: str, operation: dict,
                    base_url: str) -> GeneratedTool:
        """从单个endpoint构建GeneratedTool。"""
        operation_id = operation.get("operationId", self._generate_operation_id(method, path_url))
        summary = operation.get("summary", "")
        description = operation.get("description", summary or f"{method.upper()} {path_url}")
        tool_name = self._sanitize_name(operation_id)

        schema = self._build_parameters_schema(operation)
        return GeneratedTool(
            name=tool_name,
            description=description,
            operation_id=operation_id,
            method=method.upper(),
            path=path_url,
            parameters_schema=schema,
            base_url=base_url,
            auth_header=self.auth_header,
        )

    def _extract_base_url(self, spec: dict) -> str:
        """提取API base URL。"""
        servers = spec.get("servers", [])
        if servers:
            return servers[0].get("url", "")
        host = spec.get("host", "")
        base_path = spec.get("basePath", "")
        schemes = spec.get("schemes", ["https"])
        if host:
            return f"{schemes[0]}://{host}{base_path}"
        return ""

    def _build_parameters_schema(self, operation: dict) -> dict:
        """构建parameters JSON Schema。"""
        properties: dict[str, Any] = {}
        required: list[str] = []

        # 路径/查询/header参数
        for param in operation.get("parameters", []):
            name = param["name"]
            schema = param.get("schema", {})
            param_type = schema.get("type") or param.get("type", "string")
            properties[name] = self.PARAM_TYPE_MAP.get(param_type, {"type": "string"})
            description = param.get("description", "")
            if description:
                properties[name]["description"] = description
            if param.get("required"):
                required.append(name)

        # requestBody (POST/PUT/PATCH)
        request_body = operation.get("requestBody", {})
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        json_schema = json_content.get("schema", {})
        if json_schema.get("properties"):
            for prop_name, prop_schema in json_schema["properties"].items():
                properties[prop_name] = prop_schema
            if json_schema.get("required"):
                required.extend(json_schema["required"])

        if not properties:
            return {}

        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    @staticmethod
    def _sanitize_name(operation_id: str) -> str:
        """清理operationId为合法的函数名。"""
        name = re.sub(r"[^a-zA-Z0-9_]", "_", operation_id)
        name = re.sub(r"_{2,}", "_", name)
        name = name.strip("_").lower()
        if not name[0].isalpha() and name[0] != "_":
            name = "tool_" + name
        return name[:64]

    @staticmethod
    def _generate_operation_id(method: str, path: str) -> str:
        """无operationId时从method+path生成。"""
        clean = re.sub(r"[{}]", "", path).replace("/", "_").strip("_")
        clean = re.sub(r"[^a-zA-Z0-9_]", "_", clean)
        return f"{method.lower()}_{clean}"

    async def invoke(self, tool: GeneratedTool, params: dict) -> dict:
        """执行生成的工具调用。"""
        url = tool.base_url.rstrip("/") + tool.path
        # 替换路径参数
        for key, val in params.items():
            placeholder = "{" + key + "}"
            if placeholder in url:
                url = url.replace(placeholder, str(val))
                params = {k: v for k, v in params.items() if k != key}

        headers = {}
        if tool.auth_header:
            headers[tool.auth_header] = self.auth_value

        if tool.method == "GET":
            resp = await self._http.get(url, params=params, headers=headers)
        else:
            headers.setdefault("Content-Type", "application/json")
            resp = await self._http.request(
                tool.method, url, json=params, headers=headers
            )

        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._http.aclose()
