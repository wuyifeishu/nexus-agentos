"""Tests for agentos.tools.generator."""

import json
import os
import tempfile

import pytest

from agentos.tools.generator import (
    GeneratedTool,
    OpenAPIToolGenerator,
)


class TestGeneratedTool:
    def test_create(self):
        gt = GeneratedTool(
            name="listPets",
            description="List all pets",
            method="GET",
            path="/pets",
        )
        assert gt.name == "listPets"
        assert gt.method == "GET"
        assert gt.path == "/pets"

    def test_to_openai_function_no_params(self):
        gt = GeneratedTool(name="health", description="Health check")
        func = gt.to_openai_function()
        assert func["function"]["name"] == "health"
        assert "parameters" not in func["function"]

    def test_to_openai_function_with_params(self):
        gt = GeneratedTool(
            name="search",
            description="Search",
            parameters_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        )
        func = gt.to_openai_function()
        assert func["function"]["parameters"]["required"] == ["q"]

    def test_to_tool_dict(self):
        gt = GeneratedTool(
            name="getUser",
            description="Get user",
            operation_id="getUser_v1",
            method="GET",
            path="/users/{id}",
            base_url="https://api.example.com",
            auth_header="X-API-Key",
        )
        d = gt.to_tool_dict()
        assert d["name"] == "getUser"
        assert d["method"] == "GET"
        assert d["path_template"] == "/users/{id}"
        assert d["base_url"] == "https://api.example.com"
        assert d["auth_header"] == "X-API-Key"


class TestOpenAPIToolGenerator:
    def test_create_with_url(self):
        gen = OpenAPIToolGenerator(spec_url="https://api.example.com/openapi.json")
        assert gen.spec_url == "https://api.example.com/openapi.json"

    def test_create_with_path(self):
        gen = OpenAPIToolGenerator(spec_path="/tmp/openapi.yaml", api_base="https://api.example.com")
        assert gen.spec_path == "/tmp/openapi.yaml"
        assert gen.api_base == "https://api.example.com"

    def test_create_with_auth(self):
        gen = OpenAPIToolGenerator(auth_header="X-Token", auth_value="secret123")
        assert gen.auth_header == "X-Token"

    def test_param_type_map(self):
        assert OpenAPIToolGenerator.PARAM_TYPE_MAP["string"] == {"type": "string"}
        assert OpenAPIToolGenerator.PARAM_TYPE_MAP["integer"] == {"type": "integer"}
        assert OpenAPIToolGenerator.PARAM_TYPE_MAP["boolean"] == {"type": "boolean"}

    def test_sanitize_name(self):
        assert OpenAPIToolGenerator._sanitize_name("listPets") == "listpets"
        assert OpenAPIToolGenerator._sanitize_name("get_user.v1") == "get_user_v1"

    def test_generate_operation_id(self):
        op_id = OpenAPIToolGenerator._generate_operation_id("GET", "/users/{id}")
        assert "users" in op_id
        assert op_id.startswith("get_")

    def test_build_tool_get(self):
        gen = OpenAPIToolGenerator(api_base="https://api.example.com")
        operation = {
            "operationId": "listPets",
            "summary": "List pets",
            "parameters": [
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            ],
        }
        tool = gen._build_tool("/pets", "GET", operation, "https://api.example.com")
        assert tool.name == "listpets"
        assert tool.method == "GET"
        assert tool.path == "/pets"
        assert tool.base_url == "https://api.example.com"
        assert "limit" in str(tool.parameters_schema)

    def test_build_tool_post(self):
        gen = OpenAPIToolGenerator()
        operation = {
            "operationId": "createPet",
            "summary": "Create pet",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        }
                    }
                }
            },
        }
        tool = gen._build_tool("/pets", "POST", operation, "")
        assert tool.method == "POST"
        assert "name" in str(tool.parameters_schema)

    def test_build_parameters_empty(self):
        gen = OpenAPIToolGenerator()
        schema = gen._build_parameters_schema({"operationId": "ping"})
        assert schema == {}

    def test_extract_base_url_from_servers(self):
        gen = OpenAPIToolGenerator()
        spec = {"servers": [{"url": "https://api.example.com/v1"}]}
        url = gen._extract_base_url(spec)
        assert url == "https://api.example.com/v1"

    def test_extract_base_url_from_swagger2(self):
        gen = OpenAPIToolGenerator()
        spec = {"host": "api.example.com", "basePath": "/v1", "schemes": ["https"]}
        url = gen._extract_base_url(spec)
        assert url == "https://api.example.com/v1"

    @pytest.mark.asyncio
    async def test_load_spec_from_file(self):
        spec_data = {"openapi": "3.0.0", "info": {"title": "Test"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spec_data, f)
            tmp = f.name
        try:
            gen = OpenAPIToolGenerator(spec_path=tmp)
            spec = await gen.load_spec()
            assert spec["info"]["title"] == "Test"
        finally:
            os.unlink(tmp)

    @pytest.mark.asyncio
    async def test_generate_from_file(self):
        petstore = {
            "openapi": "3.0.0",
            "info": {"title": "Petstore", "version": "1.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "summary": "List all pets",
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        ],
                    },
                }
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(petstore, f)
            tmp = f.name
        try:
            gen = OpenAPIToolGenerator(spec_path=tmp)
            tools = await gen.generate()
            assert len(tools) == 1
            assert tools[0].name == "listpets"
        finally:
            os.unlink(tmp)
