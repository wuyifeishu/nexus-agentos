"""
Tool-Using Agent 端到端示例: 天气助手 Agent。

演示:
    - 定义工具(get_weather, get_stock_price)
    - 注册到 ToolExecutor
    - ToolAgent 多步推理
    - 成本追踪

运行:
    python agentos/agent/examples/weather_agent.py
"""

from agentos.llm import create_provider
from agentos.llm.base import Tool, ToolParameter
from agentos.agent import ToolAgent, ToolExecutor, AgentConfig


# ── 模拟工具 ──────────────────────────────────────────────────────

def get_weather(city: str) -> str:
    """获取指定城市的天气信息（模拟）。"""
    data = {
        "北京": "北京：晴，22°C，湿度 35%，东北风 3 级",
        "上海": "上海：多云转阴，28°C，湿度 70%，东南风 2 级",
        "深圳": "深圳：雷阵雨，31°C，湿度 85%，无持续风向",
        "东京": "东京：小雨，19°C，湿度 65%",
        "纽约": "纽约：晴，25°C，湿度 40%",
    }
    return data.get(city, f"{city}: 数据暂缺，建议稍后重试")


def get_stock_price(symbol: str) -> str:
    """获取股票价格（模拟）。"""
    prices = {
        "AAPL": "$220.50 (+1.2%)",
        "TSLA": "$248.30 (-0.8%)",
        "GOOGL": "$185.20 (+2.1%)",
        "BABA": "$78.90 (+0.5%)",
    }
    return prices.get(symbol.upper(), f"{symbol}: 未找到符号")


# ── 工具定义 ──────────────────────────────────────────────────────

weather_tool = Tool.from_function(
    name="get_weather",
    description="获取指定城市的天气信息",
    parameters={
        "city": ToolParameter(type="string", description="城市名称，如 北京、上海"),
    },
)

stock_tool = Tool.from_function(
    name="get_stock_price",
    description="获取指定股票的最新价格",
    parameters={
        "symbol": ToolParameter(type="string", description="股票代码，如 AAPL、TSLA"),
    },
)


def main():
    # 初始化
    provider = create_provider("openai")
    executor = ToolExecutor()
    executor.register(weather_tool, get_weather)
    executor.register(stock_tool, get_stock_price)

    agent = ToolAgent(provider, executor, config=AgentConfig(verbose=True))

    print("=" * 60)
    print("  任务: 北京天气怎么样？顺便查下 AAPL")
    print("=" * 60)

    result = agent.run("北京天气怎么样？顺便查一下 AAPL 股价")

    print(f"\n{'=' * 60}")
    print(f"  ✓ 完成: {result.final_answer}")
    print(f"  步数: {result.total_steps}")
    print(f"  Token: {result.total_tokens}")
    print(f"  成本: ${result.total_cost_usd:.6f}")
    print(f"  耗时: {result.total_duration_ms:.0f}ms")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
