"""
AgentOS CLI — 友好错误提示。

所有面向用户的错误信息统一由本模块生成，
确保错误可读、有引导、有修复建议。
"""

from __future__ import annotations

import os
import sys


def _dim(text: str) -> str:
    """终端灰色文字。"""
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


# ── 错误场景定义 ──────────────────────────────────────────


def no_provider_configured():
    """当没有任何 LLM Provider 配置 API Key 时。"""
    print()
    print(f"  {_red('✗')}  {_bold('未检测到 LLM API Key')}")
    print()
    print("    AgentOS 需要至少一个 LLM 服务商的 API Key 才能运行。")
    print()
    print("    支持的服务商：")
    print(f"      {_cyan('OpenAI')}   — gpt-4o-mini / gpt-4o / o3-mini")
    print(f"      {_cyan('DeepSeek')} — deepseek-chat / deepseek-reasoner")
    print(f"      {_cyan('Anthropic')}— claude-sonnet-4 / claude-opus-4")
    print()
    print(f"  {_bold('快速配置（推荐）：')}")
    print(f"    {_green('$ agentos init')}")
    print()
    print("  或手动设置环境变量：")
    print("    export OPENAI_API_KEY=sk-xxx")
    print()
    sys.exit(1)


def single_provider_failed(provider_name: str, error: str = ""):
    """单一 Provider API 调用失败。"""
    print()
    print(f"  {_red('✗')}  {_bold(provider_name)} API 调用失败")
    if error:
        print(f"    {_dim(error)}")
    print()
    print("    常见原因：")
    print(f"    1. API Key 过期或无效 → 运行 {_green('agentos init')} 重新配置")
    print("    2. 网络不通 → 检查代理/防火墙设置")
    print("    3. 余额不足 → 检查服务商账户余额")
    print()
    print("    或切换到其他 Provider：")
    print("    export OPENAI_API_KEY=sk-xxx   # 备用")
    print()
    sys.exit(1)


def all_providers_failed(failures: list[tuple[str, str]]):
    """所有已配置 Provider 都调用失败。"""
    print()
    print(f"  {_red('✗')}  {_bold('所有已配置的 LLM 服务商均调用失败')}")
    print()
    print("    失败列表：")
    for name, err in failures:
        print(f"      - {_yellow(name)}: {_dim(err)}")
    print()
    print("    建议：")
    print(f"    1. 运行 {_green('agentos init')} 重新配置 API Key")
    print("    2. 检查网络连接和代理设置")
    print("    3. 检查各服务商账户余额")
    print()
    sys.exit(1)


def no_task_provided():
    """没有提供任务描述。"""
    print()
    print(f"  {_yellow('!')}  请提供任务描述。")
    print()
    print("    用法：")
    print(f"      {_green('agentos run')} \"列出当前目录的文件\"")
    print(f"      {_green('agentos')} \"写一个 Python 脚本用于...\"")
    print()
    print("    更多帮助：")
    print(f"      {_green('agentos --help')}")
    print(f"      {_green('agentos demo')}      # 运行天气演示")
    print(f"      {_green('agentos hello')}     # 一分钟快速体验")
    print()
    sys.exit(1)


def feature_disabled(feature: str, mode: str = "当前运行模式"):
    """功能在当前模式下不可用。"""
    print()
    print(f"  {_yellow('!')}  {_bold(feature)} 在{mode}下暂不可用")
    print()
    print("    如需完整功能，请在桌面端运行 AgentOS。")
    print()


def import_error(module: str):
    """依赖缺失。"""
    print()
    print(f"  {_red('✗')}  缺少依赖：{_bold(module)}")
    print()
    print(f"    修复：pip install nexus-agentos[{module}]")
    print("    或：pip install nexus-agentos[all]")
    print()


def config_error(message: str):
    """配置格式错误。"""
    print()
    print(f"  {_red('✗')}  配置错误")
    print(f"    {_dim(message)}")
    print()
    print(f"    运行 {_green('agentos init')} 可自动修复配置。")
    print()
    sys.exit(1)


def tool_execution_failed(tool_name: str, error: str):
    """工具执行失败。"""
    print()
    print(f"  {_yellow('!')}  工具 {_yellow(tool_name)} 执行失败")
    print(f"    {_dim(error)}")
    print()


def welcome():
    """打印欢迎信息。"""
    from agentos import __version__

    print(f"  {_cyan('Nexus AgentOS')} v{__version__}")
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"):
        print(f"  {_green('●')} 已配置 API Key，可以直接使用。")
    else:
        print(f"  {_yellow('●')} 尚未配置 API Key，运行 agentos init 开始配置。")
    print()
