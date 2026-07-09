"""
Nexus AgentOS — LLM 快速入门示例 v1.3.36。
5 行代码启动 LLM 调用，支持多 Provider 与 Function Calling。

运行:
    export OPENAI_API_KEY="sk-..."
    python examples/llm_quickstart.py
"""

from agentos.llm import Message, MessageRole, create_provider

# 1. 创建 Provider（一行切换 OpenAI/DeepSeek/Anthropic）
provider = create_provider("openai", model="gpt-4o-mini")

# 2. 构建消息
messages = [
    Message(role=MessageRole.SYSTEM, content="用一句话回答，不要啰嗦。"),
    Message(role=MessageRole.USER, content="什么是 Nexus AgentOS？"),
]

# 3. 同步调用
result = provider.chat(messages, temperature=0.5, max_tokens=200)
print(f"[{result.model}] {result.choices[0].message.content}")
print(f"Tokens: {result.usage.total_tokens}, Cost: ${result.usage.cost_usd:.6f}")

# 4. 换 DeepSeek（只需改 provider name + 设置 DEEPSEEK_API_KEY）
# provider = create_provider("deepseek")
# provider = create_provider("anthropic")
