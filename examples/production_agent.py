"""
Production Agent Example — 使用真实 LLM (DeepSeek/OpenAI) + ToolAgent + Bridged Tools

用法:
  export DEEPSEEK_API_KEY=sk-xxx
  python examples/production_agent.py "列出 /tmp 目录下的所有文件"
  python examples/production_agent.py "读取 /etc/hostname 文件内容"
"""

import json
import os
import sys

from agentos.agent.tool_agent import AgentConfig, ToolAgent, ToolExecutor
from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    Tool,
    ToolCall,
)
from agentos.tools.bridge import bridge_registry_to_executor
from agentos.tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool
from agentos.tools.registry import ToolRegistry

# ── Production Provider: DeepSeek ──

class DeepSeekProvider(LLMProvider):
    """DeepSeek V3 API provider.

    Requires: DEEPSEEK_API_KEY env var
    """

    provider_name = "deepseek"
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: str = "deepseek-chat"):
        super().__init__(model=model)
        self._api_key = os.getenv("DEEPSEEK_API_KEY", "")

    def _messages_to_api(self, messages: list[Message]) -> list[dict]:
        api_msgs = []
        for m in messages:
            entry: dict = {"role": m.role.value}
            if m.content:
                entry["content"] = m.content
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
                entry["content"] = m.content or ""
            api_msgs.append(entry)
        return api_msgs

    def _tools_to_api(self, tools: list[Tool]) -> list[dict]:
        return [t.as_schema() for t in tools]

    def chat(self, messages, **kwargs):
        import urllib.request

        tools_param = kwargs.get("tools", [])
        body = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "stream": False,
        }
        if tools_param:
            body["tools"] = self._tools_to_api(tools_param)

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]
        msg = choice["message"]

        # Parse tool_calls
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                )
                for tc in msg["tool_calls"]
            ]

        return CompletionResult(
            id=data.get("id", ""),
            model=data.get("model", self.model),
            choices=[CompletionChoice(
                index=0,
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=msg.get("content", ""),
                    tool_calls=tool_calls,
                ),
                finish_reason=choice.get("finish_reason", "stop"),
            )],
            usage=CompletionUsage(
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
            ),
        )

    async def achat(self, messages, **kwargs):
        return self.chat(messages, **kwargs)


# ── Factory ──

def create_provider() -> LLMProvider:
    """Auto-detect available LLM provider from env vars."""
    if os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekProvider(model="deepseek-chat")
    if os.getenv("OPENAI_API_KEY"):
        # Fallback: use OpenAI-compatible interface
        class OpenAIProvider(DeepSeekProvider):
            provider_name = "openai"
            API_URL = "https://api.openai.com/v1/chat/completions"
        return OpenAIProvider(model="gpt-4o-mini")
    raise RuntimeError(
        "No LLM API key found. Set DEEPSEEK_API_KEY or OPENAI_API_KEY."
    )


# ── Agent Factory ──

def create_agent(verbose: bool = True) -> ToolAgent:
    """Create a production-ready ToolAgent with file tools."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(WriteFileTool())
    reg.register(ListDirectoryTool())

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    provider = create_provider()

    return ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(max_steps=10, stop_on_error=False),
        system_prompt=(
            "你是一个智能文件操作助手。你可以使用以下工具：\n"
            "- read_file: 读取文件内容\n"
            "- write_file: 写入文件\n"
            "- list_directory: 列出目录内容\n\n"
            "完成任务后给出简洁的中文总结。"
        ),
    )


# ── CLI ──

def main():
    if len(sys.argv) < 2:
        print("Usage: python production_agent.py <task>")
        print("Example: python production_agent.py '列出/tmp目录文件'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(f"Task: {task}\n")

    agent = create_agent(verbose=True)
    result = agent.run(task)

    print(f"\n{'='*60}")
    print(f"Success: {result.success}")
    print(f"Steps:   {result.total_steps}")
    print(f"Tokens:  {result.total_tokens}")
    print(f"Cost:    ${result.total_cost_usd:.6f}")
    print(f"Answer:  {result.final_answer}")
    if result.error:
        print(f"Error:   {result.error}")


if __name__ == "__main__":
    main()
