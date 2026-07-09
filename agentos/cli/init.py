"""
`agentos init` — 交互式配置向导。

功能：
  - 检测当前配置状态
  - 引导选择 Provider + 输入 API Key
  - 写入 ~/.agentos/config.yaml
  - 可选写入 .env 文件（当前或全局）

命令：
  agentos init                 # 交互式引导
  agentos init --quick         # 跳过问答，直接生成 .env.example
  agentos init --reset         # 重置配置
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".agentos"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
        "default_model": "gpt-4o-mini",
        "env_var": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "website": "https://platform.openai.com/api-keys",
        "cost": "低 ~ 中",
    },
    "deepseek": {
        "label": "DeepSeek",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "key_prefix": "sk-",
        "website": "https://platform.deepseek.com/api_keys",
        "cost": "低",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "models": ["claude-sonnet-4", "claude-haiku-3-5", "claude-opus-4"],
        "default_model": "claude-sonnet-4",
        "env_var": "ANTHROPIC_API_KEY",
        "key_prefix": "sk-ant-",
        "website": "https://console.anthropic.com/keys",
        "cost": "中 ~ 高",
    },
}


def _detect_current_config() -> dict:
    """检测当前环境的配置状态。"""
    config = {"providers": {}, "configured_providers": [], "active": None}

    for name, info in PROVIDERS.items():
        key = os.environ.get(info["env_var"]) or ""
        masked = key[:8] + "..." + key[-4:] if len(key) > 20 else ""
        config["providers"][name] = {
            "env_set": bool(key),
            "key_preview": masked,
        }
        if key:
            config["configured_providers"].append(name)

    # Check config file
    if CONFIG_FILE.exists():
        config["config_file_exists"] = True
        try:
            content = CONFIG_FILE.read_text()
            for name in PROVIDERS:
                if f"{PROVIDERS[name]['env_var']}:" in content:
                    config["providers"][name]["in_config"] = True
        except Exception:
            pass

    # Determine active provider
    for name in ["openai", "deepseek", "anthropic"]:
        if config["providers"][name]["env_set"] or config["providers"].get(name, {}).get(
            "in_config"
        ):
            config["active"] = name
            break

    return config


def _print_banner():
    """打印欢迎横幅。"""
    from agentos import __version__

    print("\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║        Nexus AgentOS v{__version__:8s}        ║")
    print("  ║        交互式配置向导                        ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()


def _print_status(config: dict):
    """打印当前配置状态。"""
    print("  ── 当前环境检测 ──")
    print()
    for name, info in config["providers"].items():
        p = PROVIDERS[name]
        status = "✅" if info["env_set"] else "⬜"
        key_info = info.get("key_preview", "") or "未配置"
        in_config = " (配置文件)" if info.get("in_config") else ""
        print(f"    {status}  {p['label']:20s}  {key_info:25s}{in_config}")
    print()


def _select_provider() -> str:
    """交互选择 Provider。"""
    print("  ── 选择 LLM 服务商 ──")
    print()
    names = list(PROVIDERS.keys())
    for i, name in enumerate(names, 1):
        p = PROVIDERS[name]
        print(f"    [{i}] {p['label']:20s} 模型: {p['default_model']:15s} 成本: {p['cost']}")
    print()

    while True:
        try:
            choice = input("  请选择 (1-3) [1]: ").strip()
            if not choice:
                return "openai"
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        except ValueError:
            pass
        print("  输入无效，请输入数字 1-3。")


def _input_api_key(provider_name: str) -> str | None:
    """交互输入 API Key。"""
    p = PROVIDERS[provider_name]
    print()
    print(f"  ── 配置 {p['label']} API Key ──")
    print()
    print(f"  ① 打开 {p['website']}")
    print("  ② 创建或复制一个 API Key")
    print("  ③ 粘贴到下方（输入后按回车）")
    print()

    existing = os.environ.get(p["env_var"], "")
    if existing:
        preview = existing[:8] + "..." + existing[-4:] if len(existing) > 20 else existing
        use_existing = (
            input(f"  检测到环境变量已设置 ({preview})，直接使用？(Y/n): ").strip().lower()
        )
        if use_existing in ("", "y", "yes"):
            return existing

    while True:
        key = input(f"  请输入 {p['label']} API Key: ").strip()
        if not key:
            print("  API Key 不能为空。输入 q 取消。")
            continue
        if key.lower() == "q":
            return None
        # Basic validation
        prefix = p["key_prefix"]
        if prefix and not key.startswith(prefix):
            warn = (
                input(f"  警告：{p['label']} 的 Key 通常以 '{prefix}' 开头，" f"确认继续？(y/N): ")
                .strip()
                .lower()
            )
            if warn not in ("y", "yes"):
                continue
        return key


def _test_connection(provider_name: str, api_key: str) -> bool:
    """测试 API 连接（发一条最轻的请求）。"""
    p = PROVIDERS[provider_name]
    print(f"\n  正在测试 {p['label']} API 连接...", end=" ")

    try:
        if provider_name == "openai":
            import httpx

            resp = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                print("✅ 成功")
                return True
            elif resp.status_code == 401:
                print("❌ Key 无效（401 Unauthorized）")
                return False
            else:
                print(f"⚠️  返回 {resp.status_code}，Key 格式正确但不一定可用")
                return True
        elif provider_name == "deepseek":
            import httpx

            resp = httpx.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                print("✅ 成功")
                return True
            elif resp.status_code == 401:
                print("❌ Key 无效（401）")
                return False
            else:
                print(f"⚠️  返回 {resp.status_code}")
                return True
        elif provider_name == "anthropic":
            import httpx

            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=10,
            )
            if resp.status_code == 200:
                print("✅ 成功")
                return True
            elif resp.status_code == 401:
                print("❌ Key 无效（401）")
                return False
            else:
                print(f"⚠️  返回 {resp.status_code}")
                return True
    except Exception as e:
        print(f"⚠️  连接异常: {e}")
        return False
    return False


def _save_config(provider_name: str, api_key: str):
    """保存配置到 ~/.agentos/config.yaml。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    env_var = PROVIDERS[provider_name]["env_var"]

    # Save .env file
    env_content = f"# Nexus AgentOS — {PROVIDERS[provider_name]['label']} 配置\n"
    env_content += f"{env_var}={api_key}\n\n"
    env_content += "# 可选：配置多个 Provider 以实现自动回退\n"
    env_content += "# OPENAI_API_KEY=sk-xxx\n"
    env_content += "# DEEPSEEK_API_KEY=sk-xxx\n"
    env_content += "# ANTHROPIC_API_KEY=sk-ant-xxx\n"
    ENV_FILE.write_text(env_content)

    # Save config.yaml
    config = {
        "version": "1.4.0",
        "active_provider": provider_name,
        "providers": {
            provider_name: {
                "env_var": env_var,
            }
        },
    }
    import yaml

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    print("\n  ✅ 配置已保存")
    print(f"     {CONFIG_FILE}")
    print(f"     {ENV_FILE}")


def _show_completion_message(provider_name: str):
    """显示配置完成后引导。"""
    p = PROVIDERS[provider_name]

    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║   ✅  配置就绪！                            ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()
    print(f"  当前已配置: {p['label']} ({p['default_model']})")
    print()
    print("  ── 快速开始 ──")
    print()
    print("  # 运行任务")
    print('  agentos "列出当前目录的文件"')
    print()
    print("  # 运行端到端示例")
    print('  python -m examples.multi_agent_research --topic "量子计算"')
    print()
    if provider_name != "openai":
        print(f"  # 指定使用 {p['label']}")
        print(f'  agentos --provider {provider_name} "写一个 Python 爬虫"')
    print()
    print("  ── 多 Provider 配置（可选） ──")
    print()
    print(f"  编辑 {ENV_FILE}，添加其他 API Key 即可实现自动回退:")
    print("    OPENAI_API_KEY=sk-xxx         # 默认使用")
    print("    DEEPSEEK_API_KEY=sk-xxx       # 回退 1")
    print("    ANTHROPIC_API_KEY=sk-ant-xxx  # 回退 2")
    print()
    print("  重新运行 agentos init 修改配置。")
    print("  或 agentos config-panel 打开浏览器版配置面板。")


# ── 配置加载接口 ────────────────────────────────────────────


def load_config() -> dict:
    """加载 ~/.agentos/config.yaml 和环境变量。

    Returns:
        dict: 包含 providers 和 active_provider 的配置字典。
    """
    config = {"providers": {}, "active_provider": None}

    # 1. Load env vars
    for name, info in PROVIDERS.items():
        key = os.environ.get(info["env_var"])
        if key:
            config["providers"][name] = key

    # 2. Load config file
    if CONFIG_FILE.exists():
        try:
            import yaml

            raw = yaml.safe_load(CONFIG_FILE.read_text())
            if raw and "providers" in raw:
                for name, pcfg in raw["providers"].items():
                    if name in PROVIDERS and name not in config["providers"]:
                        env_var = pcfg.get("env_var", PROVIDERS[name]["env_var"])
                        # Try to load from .env
                        if ENV_FILE.exists():
                            for line in ENV_FILE.read_text().splitlines():
                                if line.startswith(env_var + "="):
                                    val = line.split("=", 1)[1].strip()
                                    if val and val != "sk-xxx":
                                        config["providers"][name] = val
                                        break
            if raw and "active_provider" in raw:
                config["active_provider"] = raw["active_provider"]
        except Exception:
            pass

    # 3. Determine active
    for name in ["openai", "deepseek", "anthropic"]:
        if config["providers"].get(name):
            config["active_provider"] = config.get("active_provider") or name
            break

    return config


def config_status_text() -> str:
    """返回一行配置状态文本，给 CLI help 用。"""
    config = load_config()
    if config["active_provider"]:
        name = config["active_provider"]
        label = PROVIDERS.get(name, {}).get("label", name)
        return f"✅ {label} 已配置"
    return "⬜ 未配置（运行 agentos init）"


# ── CLI ────────────────────────────────────────────────────


def init_cli(args: list[str]):
    """CLI 入口。"""
    quick = "--quick" in args
    reset = "--reset" in args

    if reset:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        if ENV_FILE.exists():
            ENV_FILE.unlink()
        print("  ✅ 配置已重置。运行 agentos init 重新配置。")
        return

    if quick:
        # Quick mode: just create .env.example in current directory
        example_path = Path.cwd() / ".env.example"
        content = """# Nexus AgentOS 配置示例
# 复制为 .env 并填入你的 API Key
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
"""
        example_path.write_text(content)
        print(f"  已生成 {example_path}")
        print("  复制为 .env 并填入你的 API Key 即可使用。")
        return

    # Interactive mode
    _print_banner()
    current = _detect_current_config()
    _print_status(current)

    if current["configured_providers"]:
        print("  检测到已有 API Key 配置。")
        reconfig = input("  是否重新配置？(y/N): ").strip().lower()
        if reconfig not in ("y", "yes"):
            _show_completion_message(current["active"] or current["configured_providers"][0])
            return

    provider = _select_provider()
    api_key = _input_api_key(provider)
    if api_key is None:
        print("  配置已取消。")
        return

    test_result = _test_connection(provider, api_key)
    if test_result is False:
        retry = input("  Key 验证失败，重试？(Y/n): ").strip().lower()
        if retry not in ("", "y", "yes"):
            print("  配置已取消。")
            return
        # Try again recursively for simplicity
        return init_cli(args)

    _save_config(provider, api_key)
    _show_completion_message(provider)


# ── 项目脚手架（兼容旧接口） ──────────────────────────────────

TEMPLATES = {
    "default": {
        "agentos.yaml": """\
# AgentOS v0.80 配置文件
version: "0.80.0"

models:
  primary:
    provider: openai
    model_name: gpt-4o-mini
    temperature: 0.7
    max_tokens: 4096

loop:
  max_iterations: 10
  step_timeout: 120

observability:
  tracer:
    enabled: true
    level: info
""",
        "main.py": """\
\"""AgentOS — 我的 Agent 应用入口。\"""

from agentos import AgentLoop, LoopConfig


def main():
    loop = AgentLoop(LoopConfig(max_iterations=5))
    result = loop.run("你好，世界！")
    print(result.output)


if __name__ == "__main__":
    main()
""",
        ".env.example": """\
# AgentOS 环境变量
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
GEMINI_API_KEY=AIza-xxx
""",
    },
    "minimal": {
        "agentos.yaml": """\
version: "0.80.0"
models:
  primary:
    provider: openai
    model_name: gpt-4o-mini
""",
        "main.py": """\
from agentos import AgentLoop, LoopConfig

loop = AgentLoop(LoopConfig(max_iterations=3))
result = loop.run("你好，世界！")
print(result.output)
""",
    },
}


def scaffold(project_dir: str, template: str = "default") -> list[str]:
    """初始化 AgentOS 项目脚手架。

    Args:
        project_dir: 项目根目录路径。
        template: 模板名称（"default" 或 "minimal"）。

    Returns:
        创建的文件路径列表。
    """
    files = TEMPLATES.get(template, TEMPLATES["default"])
    project_path = Path(project_dir).resolve()
    project_path.mkdir(parents=True, exist_ok=True)

    created = []
    for filename, content in files.items():
        filepath = project_path / filename
        if filepath.exists():
            continue
        with open(filepath, "w") as f:
            f.write(content)
        created.append(str(filepath))

    return created


if __name__ == "__main__":
    init_cli(sys.argv[1:])
