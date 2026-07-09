"""
Nexus AgentOS — LLM Provider 端到端示例 v1.3.36。
演示：OpenAI / DeepSeek / Anthropic 多 Provider + Function Calling + 流式。

运行:
    export OPENAI_API_KEY="sk-..."
    python examples/llm_chat_demo.py

多 Provider:
    python examples/llm_chat_demo.py --provider deepseek

Function Calling:
    python examples/llm_chat_demo.py --mode functions
"""

from __future__ import annotations

import argparse
import json
import os

from agentos.llm import Message, MessageRole, Tool, ToolParameter, create_provider


def run_chat(provider_name: str, model: str, prompt: str) -> None:
    """单轮对话示例。"""
    provider = create_provider(provider_name, model=model)

    messages = [
        Message(
            role=MessageRole.SYSTEM,
            content="You are a helpful coding assistant. Answer in Chinese.",
        ),
        Message(role=MessageRole.USER, content=prompt),
    ]

    result = provider.chat(messages, temperature=0.7, max_tokens=1024)

    print(
        f"[provider: {provider.provider_name}] [model: {result.model}] "
        f"[tokens: {result.usage.total_tokens}] [cost: ${result.usage.cost_usd:.6f}]\n"
    )
    print(result.choices[0].message.content)

    if result.usage.total_tokens > 0:
        print(
            f"\n---\nprompt={result.usage.prompt_tokens} | completion={result.usage.completion_tokens}"
        )


def run_multi_turn(provider_name: str, model: str) -> None:
    """多轮对话示例。"""
    provider = create_provider(provider_name, model=model)

    history: list[Message] = [
        Message(role=MessageRole.SYSTEM, content="你是一个幽默的助手，用简短中文回答。"),
    ]

    turns = [
        "用一句话解释什么是 Agent 框架",
        "它和 LangChain 有什么区别？",
        "那你推荐哪个？",
    ]

    for i, prompt in enumerate(turns):
        history.append(Message(role=MessageRole.USER, content=prompt))
        result = provider.chat(history, temperature=0.8, max_tokens=200)
        reply = result.choices[0].message.content
        history.append(Message(role=MessageRole.ASSISTANT, content=reply))

        print(f"[turn {i+1}] user:  {prompt}")
        print(f"[turn {i+1}] agent: {reply}")
        print(
            f"          tokens: {result.usage.total_tokens}, cost: ${result.usage.cost_usd:.6f}\n"
        )


def run_streaming(provider_name: str, model: str) -> None:
    """流式输出示例。"""
    provider = create_provider(provider_name, model=model)

    messages = [
        Message(role=MessageRole.SYSTEM, content="You are a poet. Write in Chinese."),
        Message(role=MessageRole.USER, content="写一首关于程序员日常的四行诗"),
    ]

    print("[streaming] ", end="", flush=True)
    for chunk in provider.stream(messages, temperature=0.9, max_tokens=200):
        print(chunk.content, end="", flush=True)
    print()


def run_function_calling(provider_name: str, model: str) -> None:
    """Function Calling 示例。"""

    tools = [
        Tool.from_function(
            "get_weather",
            "获取指定城市的天气信息",
            {
                "city": ToolParameter(
                    type="string", description="城市名称，如 Beijing", required=True
                ),
                "unit": ToolParameter(
                    type="string", description="温度单位", enum=["celsius", "fahrenheit"]
                ),
            },
            required=["city"],
        ),
        Tool.from_function(
            "calculate",
            "执行数学计算",
            {
                "expression": ToolParameter(
                    type="string", description="数学表达式，如 '2+3*4'", required=True
                ),
            },
            required=["expression"],
        ),
    ]

    provider = create_provider(provider_name, model=model)

    messages = [
        Message(role=MessageRole.SYSTEM, content="你是一个助手，可以使用函数来获取天气和做计算。"),
        Message(role=MessageRole.USER, content="北京现在天气怎么样？顺便帮我算一下 123 * 456"),
    ]

    result = provider.chat(messages, temperature=0.0, max_tokens=512, tools=tools)
    choice = result.choices[0]

    print(f"[provider: {provider.provider_name}] [model: {result.model}]")
    print(f"[finish_reason: {choice.finish_reason}]\n")

    if choice.message.content:
        print(f"Text: {choice.message.content}\n")

    if choice.message.tool_calls:
        print(f"Tool calls requested ({len(choice.message.tool_calls)}):")
        for tc in choice.message.tool_calls:
            print(f"  -> {tc.name}({tc.arguments})")

        # Simulate tool execution
        messages.append(choice.message)
        for tc in choice.message.tool_calls:
            if tc.name == "get_weather":
                tool_result = json.dumps(
                    {"city": "Beijing", "temperature": 22, "condition": "Sunny", "unit": "celsius"}
                )
            elif tc.name == "calculate":
                expr = tc.parsed_arguments.get("expression", "")
                tool_result = str(eval(expr))
            else:
                tool_result = "{}"
            messages.append(Message(role=MessageRole.TOOL, content=tool_result, tool_call_id=tc.id))

        # Second round with tool results
        result2 = provider.chat(messages, temperature=0.0, max_tokens=512, tools=tools)
        print(f"\n[final response] {result2.choices[0].message.content}")


def main():
    parser = argparse.ArgumentParser(description="Nexus AgentOS LLM Chat Demo")
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "deepseek", "anthropic"],
        help="LLM provider (default: openai)",
    )
    parser.add_argument("--model", default="", help="model name (uses provider default if empty)")
    parser.add_argument(
        "--prompt", default="用 Python 写一个冒泡排序函数", help="single-turn prompt"
    )
    parser.add_argument(
        "--mode",
        choices=["chat", "multi", "stream", "functions", "all"],
        default="all",
        help="demo mode (default: all)",
    )

    args = parser.parse_args()

    # Early validation
    env_key = f"{args.provider.upper()}_API_KEY"
    if not os.getenv(env_key):
        print(f"Warning: {env_key} not set. Provider may fail if API key is required.\n")

    if args.mode in ("chat", "all"):
        print("=== 单轮对话 ===")
        run_chat(args.provider, args.model, args.prompt)

    if args.mode in ("multi", "all"):
        print("\n=== 多轮对话 ===")
        run_multi_turn(args.provider, args.model)

    if args.mode in ("stream", "all"):
        print("\n=== 流式输出 ===")
        run_streaming(args.provider, args.model)

    if args.mode in ("functions", "all"):
        print("\n=== Function Calling ===")
        run_function_calling(args.provider, args.model)


if __name__ == "__main__":
    main()
