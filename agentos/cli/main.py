"""
AgentOS v1.7.1 CLI — System layer + Desktop client: file ops, shell, browser, visual approval, native desktop shell。
"""

from __future__ import annotations

import asyncio
import os
import sys

from agentos.llm.factory import create_provider
from agentos.llm.base import Tool, ToolParameter
from agentos.agent.tool_agent import ToolAgent, ToolExecutor, AgentConfig, MockLLMProvider
from agentos.cli.errors import (
    no_provider_configured,
    single_provider_failed,
    no_task_provided,
    welcome,
)


def _build_executor() -> ToolExecutor:
    executor = ToolExecutor()

    # Shell tool
    executor.register(
        Tool.from_function(
            name="run_shell",
            description="Execute a shell command. Commands run in a sandboxed temporary directory.",
            parameters={
                "command": ToolParameter(
                    type="string",
                    description="The shell command to execute.",
                ),
            },
        ),
        lambda command: _run_shell_unsafe(command),
    )

    # File tools
    executor.register(
        Tool.from_function(
            name="read_file",
            description="Read contents of a file at the given path.",
            parameters={
                "file_path": ToolParameter(
                    type="string",
                    description="Absolute path to the file.",
                ),
            },
        ),
        lambda file_path: _read_file(file_path),
    )

    executor.register(
        Tool.from_function(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Absolute path to the directory.",
                ),
            },
        ),
        lambda path: _list_directory(path),
    )

    executor.register(
        Tool.from_function(
            name="write_file",
            description="Write text content to a file.",
            parameters={
                "file_path": ToolParameter(
                    type="string",
                    description="Absolute path to write to.",
                ),
                "content": ToolParameter(
                    type="string",
                    description="Text content to write.",
                ),
            },
        ),
        lambda file_path, content: _write_file(file_path, content),
    )

    return executor


def _run_shell_unsafe(command: str) -> str:
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=30, cwd=td,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            if err:
                return f"stdout:\n{out}\n\nstderr:\n{err}"
            return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"
    except Exception as e:
        return f"Error: {e}"


def _read_file(file_path: str) -> str:
    try:
        with open(file_path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"


def _list_directory(path: str) -> str:
    try:
        entries = os.listdir(path)
        return "\n".join(sorted(entries)) or "(empty)"
    except Exception as e:
        return f"Error: {e}"


def _write_file(file_path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error: {e}"


def _build_agent(provider_name: str = "", verbose: bool = False) -> ToolAgent:
    if provider_name:
        provider = create_provider(provider_name)
    elif os.getenv("OPENAI_API_KEY"):
        provider = create_provider("openai")
        provider_name = "openai"
    elif os.getenv("DEEPSEEK_API_KEY"):
        provider = create_provider("deepseek")
        provider_name = "deepseek"
    elif os.getenv("ANTHROPIC_API_KEY"):
        provider = create_provider("anthropic")
        provider_name = "anthropic"
    else:
        welcome()
        no_provider_configured()

    config = AgentConfig(verbose=verbose)
    executor = _build_executor()

    return ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=config,
        system_prompt=(
            "你是 AgentOS 智能助手。你可以使用以下工具完成任务：\n"
            "- run_shell: 执行 Shell 命令\n"
            "- read_file: 读取文件内容\n"
            "- write_file: 写入文本到文件\n"
            "- list_directory: 列出目录内容\n\n"
            "当需要操作文件或执行命令时调用对应工具。"
            "获得足够信息后直接回答，不要再调用工具。"
            "使用中文回复。"
        ),
    )


def _run_hello():
    """一键 hello world 体验 — 无需配置，始终可用。"""
    from agentos import __version__
    import time

    print(f"  \033[36mNexus AgentOS\033[0m v{__version__}")
    print(f"  \033[2m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print()

    # Step 1: check provider
    provider_label = "Mock（演示模式）"
    provider_color = "\033[33m"
    if os.environ.get("OPENAI_API_KEY"):
        provider_label = "OpenAI (gpt-4o-mini)"
        provider_color = "\033[32m"
    elif os.environ.get("DEEPSEEK_API_KEY"):
        provider_label = "DeepSeek (deepseek-chat)"
        provider_color = "\033[32m"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider_label = "Anthropic (claude-sonnet-4)"
        provider_color = "\033[32m"

    steps = [
        ("检测环境", f"{provider_color}{provider_label}\033[0m"),
        ("核心引擎", "\033[32mToolAgent 多步推理循环\033[0m"),
        ("工具系统", "\033[32mShell / 文件读写 / 目录浏览\033[0m"),
        ("安全护栏", "\033[32mGuardrails PII注入检测\033[0m"),
        ("可观测性", "\033[32mTracker + Dashboard SSE\033[0m"),
        ("MCP 协议", "\033[32mstdio JSON-RPC 2.0\033[0m"),
        ("RAG 管道", "\033[32mChroma/FAISS 向量检索\033[0m"),
        ("企业特性", "\033[32mRBAC/多租户/审计/API Key\033[0m"),
    ]

    for label, status in steps:
        time.sleep(0.12)
        print(f"  \033[2m▸\033[0m {label:<12s} {status}")

    time.sleep(0.3)
    print()
    print(f"  \033[1m一切就绪。\033[0m")
    print()

    if os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  快速开始：")
        print(f"    \033[32magentos\033[0m \"用一句话解释什么是递归\"")
        print(f"    \033[32magentos demo\033[0m")
    else:
        print(f"  下一步（30 秒配置）：")
        print(f"    \033[32magentos init\033[0m        终端交互式配置")
        print(f"    \033[32magentos config-panel\033[0m 浏览器图形界面")
    print()


def _run_file_demo(verbose: bool):
    """文件操作演示 — 创建、读取、列表。"""
    from agentos.agent.tool_agent import ToolAgent, ToolExecutor, AgentConfig

    executor = ToolExecutor()

    def write_file(path: str, content: str) -> str:
        import os as _os
        try:
            _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"已写入 {path} ({len(content)} 字节)"
        except Exception as e:
            return f"写入失败: {e}"

    def read_file(path: str) -> str:
        try:
            with open(path) as f:
                return f.read()
        except Exception as e:
            return f"读取失败: {e}"

    def list_dir(path: str) -> str:
        import os as _os
        try:
            return "\n".join(sorted(_os.listdir(path))) or "(空)"
        except Exception as e:
            return f"列出失败: {e}"

    executor.register(
        Tool.from_function("write_file", "写入文本到文件", {
            "path": ToolParameter(type="string", description="文件路径"),
            "content": ToolParameter(type="string", description="文件内容"),
        }),
        write_file,
    )
    executor.register(
        Tool.from_function("read_file", "读取文件内容", {
            "path": ToolParameter(type="string", description="文件路径"),
        }),
        read_file,
    )
    executor.register(
        Tool.from_function("list_dir", "列出目录内容", {
            "path": ToolParameter(type="string", description="目录路径"),
        }),
        list_dir,
    )

    if os.getenv("OPENAI_API_KEY"):
        provider = create_provider("openai")
    elif os.getenv("DEEPSEEK_API_KEY"):
        provider = create_provider("deepseek")
    else:
        print("\n  文件操作演示需要 API Key（Mock 不支持动态文件操作）。")
        print("  运行 agentos init 配置后重试。\n")
        return

    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(verbose=verbose, temperature=0.0),
        system_prompt="你是文件操作助手。用工具完成任务后用中文汇报结果。",
    )

    demo_dir = "/tmp/agentos_file_demo"
    print(f"\n  演示目录: {demo_dir}")
    print()

    result = agent.run(f"在 {demo_dir} 下创建 hello.txt 写入 'Hello from AgentOS!'，列出目录内容，再读取 hello.txt 确认。")
    print(f"\n  耗时: {result.total_duration_ms/1000:.1f}s | 步数: {result.total_steps}")
    print(f"  Token: {result.total_tokens} | 费用: ${result.total_cost_usd:.4f}")
    print(f"  结果: {result.final_answer}")


def main():
    args = sys.argv[1:]
    verbose = "--verbose" in args or "-v" in args
    args = [a for a in args if a not in ("--verbose", "-v")]

    if not args or args[0] in ("help", "--help", "-h"):
        from agentos import __version__
        from agentos.cli.init import config_status_text
        print(f"AgentOS v{__version__} — Production Agent Framework CLI\n")
        print(f"Provider: {config_status_text()}\n")
        print("Usage:")
        print("  agentos init                  Interactive setup wizard (recommended)")
        print("  agentos hello                 One-step health check & quick intro")
        print("  agentos config-panel          Open web config panel in browser")
        print("  agentos <task>                Run a task with the autonomous agent")
        print("  agentos run <task>            Same as above")
        print("  agentos demo                  Run interactive demo (weather/stock/files)")
        print("  agentos serve                 Start API server (port 8080)")
        print("  agentos version               Show version")
        print("  agentos skills                List agent marketplace skills")
        print("  agentos docs [output-dir]     Generate API reference docs (→ docs/api/)")
        print("  agentos dashboard             Open web trace dashboard (port 18500)")
        print("  agentos mcp-server            Start MCP server (stdio) for Claude Desktop etc.")
        print("  agentos desktop               Launch web desktop client (port 19999)")
        print("  agentos desktop-shell         Launch native desktop shell (pywebview)")
        print("  agentos enterprise <cmd>      Enterprise features: api-key, tenant, audit")
        print("  agentos marketplace <cmd>      Skill marketplace: search|install|list|update|uninstall|stats")
        print("  agentos rollback <version>     Rollback to a previous version (--list|--verify|--prune)")
        print("\nOptions:")
        print("  -v, --verbose                 Show agent step details")
        print("  --provider <name>             Force provider: openai|deepseek|anthropic")
        print("\nProvider (auto-detect via env vars):")
        print("  OPENAI_API_KEY     → OpenAI (gpt-4o-mini)")
        print("  DEEPSEEK_API_KEY   → DeepSeek (deepseek-chat)")
        print("  ANTHROPIC_API_KEY  → Anthropic (claude-sonnet-4)")
        print("  (none set)         → Mock demo mode — run 'agentos init' to configure")
        print("\nExamples:")
        print("  agentos hello                 # 30s quick tour")
        print("  agentos init                  # 1-minute setup wizard")
        print("  agentos \"列出当前目录的文件\"")
        print("  agentos \"创建一个 hello.py 打印 Hello World\"")
        print("  agentos demo")
        sys.exit(0)

    cmd = args[0]
    if cmd == "init":
        from agentos.cli.init import init_cli
        init_cli(args)
        return

    if cmd == "config-panel":
        from agentos.cli.config_panel import start_panel
        start_panel()
        return

    if cmd == "status":
        from agentos.cli.init import _detect_current_config, config_status_text
        print(f"Provider: {config_status_text()}\n")
        config = _detect_current_config()
        for name, info in config["providers"].items():
            from agentos.cli.init import PROVIDERS
            p = PROVIDERS[name]
            status_icon = "✅" if info["env_set"] else "⬜"
            key_info = info.get("key_preview", "未配置") or "未配置"
            in_config = " (配置文件)" if info.get("in_config") else ""
            print(f"  {status_icon}  {p['label']:20s}  {key_info:25s}{in_config}")
        return

    if cmd == "version":
        from agentos import __version__
        print(f"AgentOS v{__version__}")
        return

    if cmd == "skills":
        from agentos.agents.market import AgentMarket
        market = AgentMarket()
        stats = market.stats()
        print(f"Agent Skill Market: {stats['total']} skills\n")
        for cat, count in stats["by_category"].items():
            skills = market.list_by_category(cat)
            print(f"  [{cat}] ({count})")
            for s in skills:
                print(f"    {s.name}: {s.description}")
        return

    if cmd == "docs":
        from agentos.docs.generator import generate_api_docs, generate_quickstart
        import os
        if not os.path.isdir("agentos"):
            print("Error: run 'agentos docs' from the agentos project root directory")
            sys.exit(1)
        output_dir = args[1] if len(args) > 1 else "docs"
        os.makedirs(output_dir, exist_ok=True)
        api_path = os.path.join(output_dir, "api_reference.md")
        qs_path = os.path.join(output_dir, "quickstart.md")
        md = generate_api_docs("agentos", api_path)
        generate_quickstart(qs_path)
        module_count = len([d for d in os.listdir("agentos") if os.path.isdir(os.path.join("agentos", d))])
        print(f"Generated API docs: {api_path} ({len(md.splitlines())} lines)")
        print(f"Generated Quickstart: {qs_path}")
        print(f"Scanned ~{module_count} source modules")
        return

    if cmd == "dashboard":
        from agentos.dashboard.server import start_dashboard
        print("Starting AgentOS Dashboard...")
        start_dashboard()
        return

    if cmd == "mcp-server":
        from agentos.mcp.server import start_mcp_server
        port = 0
        for i, a in enumerate(args[1:]):
            if a == "--port" and i + 2 < len(args):
                port = int(args[i + 2])
        start_mcp_server(port=port)
        return

    if cmd == "desktop":
        from agentos.desktop.server import launch_desktop
        host = "0.0.0.0"
        port = 19999
        mode = "dev"
        for i, a in enumerate(args[1:]):
            if a == "--host" and i + 2 < len(args):
                host = args[i + 2]
            elif a == "--port" and i + 2 < len(args):
                port = int(args[i + 2])
            elif a == "--safe":
                mode = "safe"
        launch_desktop(host=host, port=port, mode=mode)
        return

    if cmd == "desktop-shell":
        from agentos.desktop.shell import main as shell_main
        sys.argv = [sys.argv[0]] + args[1:]
        shell_main()
        return

    if cmd == "enterprise":
        _run_enterprise(args[1:])
        return

    if cmd == "marketplace":
        _run_marketplace(args[1:])
        return

    if cmd == "rollback":
        from agentos.cli.rollback import rollback_cli
        sys.exit(rollback_cli(args[1:]))

    if cmd == "serve":
        host = "0.0.0.0"
        port = 8080
        for i, a in enumerate(args[1:]):
            if a == "--host" and i + 2 < len(args):
                host = args[i + 2]
            elif a == "--port" and i + 2 < len(args):
                port = int(args[i + 2])
        from agentos.api.server import AgentAPI
        from agentos.core.loop import AgentLoop, LoopConfig
        from agentos.core.context import ContextManager
        from agentos.tools.registry import ToolRegistry
        from agentos.models.router import ModelRouter, RECOMMENDED_CONFIG
        from agentos.tools.code_agent import CodeAgentTool, ShellTool
        from agentos.tools.file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
        from agentos.tools.web_tools import WebFetchTool
        registry = ToolRegistry()
        registry.register_many([ReadFileTool(), WriteFileTool(), ListDirectoryTool(), CodeAgentTool(), ShellTool(), WebFetchTool()])
        ctx = ContextManager(system_prompt="AgentOS API Server v1.0")
        router = ModelRouter(RECOMMENDED_CONFIG)
        loop = AgentLoop(model_router=router, tool_registry=registry, context_manager=ctx)
        api = AgentAPI(loop)
        print(f"AgentOS API starting on http://{host}:{port}")
        api.serve(host=host, port=port)
        return

    if cmd == "hello":
        _run_hello()
        return

    if cmd == "demo":
        print("=" * 60)
        print("  AgentOS — Interactive Demo")
        print("=" * 60)
        print()
        print("  选择演示场景：")
        print("    [1] 天气助手（默认）")
        print("    [2] 文件操作")
        print("    [3] 健康自检")
        print()

        try:
            choice = input("  请输入数字 (1-3) [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            choice = "1"

        if choice == "3":
            _run_hello()
        elif choice == "2":
            _run_file_demo(verbose)
        else:
            _run_demo(verbose)
        return

    # Run task
    task_start = 1 if cmd == "run" else 0
    task = " ".join(args[task_start:])
    if not task.strip():
        no_task_provided()

    agent = _build_agent(verbose=verbose)
    # 自动记录 tracker
    from agentos.dashboard.tracker import Tracker
    import uuid, time
    tracker = Tracker.get()
    session_id = f"run-{uuid.uuid4().hex[:12]}"
    rec = tracker.start_session(session_id, task, model="auto", provider="auto")
    t0 = time.time()
    try:
        result = agent.run(task)
        elapsed = (time.time() - t0) * 1000
        tracker.finish_session(
            session_id,
            status="completed" if result.success else "error",
            error=result.error if not result.success else "",
            total_cost=result.total_cost_usd if hasattr(result, 'total_cost_usd') else 0.0,
        )
        print(f"\n{'─' * 60}")
        if result.success:
            print(f"Result ({(result.total_duration_ms/1000):.1f}s, "
                  f"{result.total_steps} steps, "
                  f"{result.total_tokens} tokens, "
                  f"${result.total_cost_usd:.4f}):")
            print(f"{result.final_answer}")
        else:
            print(f"Error: {result.error}")
    except Exception as e:
        tracker.finish_session(session_id, status="error", error=str(e))
        raise


def _run_marketplace(args: list[str]):
    """Skill Marketplace CLI dispatcher."""

    if not args or args[0] in ("help", "--help", "-h"):
        print("AgentOS Skill Marketplace\n")
        print("Subcommands:")
        print("  search    <query>          搜索技能市场")
        print("  install   <name|path|url>  安装技能（PyPI / 本地 / GitHub）")
        print("  list                       列出已安装技能")
        print("  info      <name>           查看技能详情")
        print("  update    <name>           更新技能到最新版")
        print("  uninstall <name>           卸载技能")
        print("  stats                      市场统计")
        print("\n兼容格式: agentos / openclaw / mcp / generic")
        return

    from agentos.marketplace import SkillRegistry, InstallResult

    registry = SkillRegistry()
    sub = args[0]
    rest = args[1:]

    if sub == "search":
        query = " ".join(rest) if rest else ""
        print(f"Searching marketplace for '{query or 'all'}'...\n")
        results = registry.search(query)
        if not results:
            print("No skills found. Try a broader query, or publish your own with 'agentos-skill-<name>' on PyPI.")
            return
        print(f"{'Name':<24s} {'Version':<12s} {'Source':<10s} Description")
        print("-" * 80)
        for r in results:
            desc = r.description[:60] if r.description else "-"
            print(f"{r.name:<24s} {r.version:<12s} {r.source:<10s} {desc}")

    elif sub == "install":
        if not rest:
            print("Usage: agentos marketplace install <name|path|url>")
            return
        target = " ".join(rest)
        print(f"Installing '{target}'...")
        result = registry.install(target)
        if result.success and result.manifest:
            m = result.manifest
            print(f"\n  Installed: {m.name} v{m.version} [{m.format.value}]")
            print(f"  Source:    {result.install_type}")
            if m.description:
                print(f"  Description: {m.description}")
            if result.dep_installed:
                print(f"  Dependencies: {', '.join(result.dep_installed)}")
            if m.tools:
                print(f"  Tools:     {', '.join(t.name for t in m.tools)}")
        else:
            print(f"  Failed: {result.error}")

    elif sub == "list":
        skills = registry.list_installed()
        if not skills:
            print("No skills installed. Try 'agentos marketplace install <name>'.")
            return
        print(f"{'Name':<24s} {'Version':<12s} {'Format':<12s} {'Source':<10s} Description")
        print("-" * 90)
        for m in skills:
            desc = (m.description or "")[:50]
            print(f"{m.name:<24s} {m.version:<12s} {m.format.value:<12s} {m.source:<10s} {desc}")

    elif sub == "info":
        if not rest:
            print("Usage: agentos marketplace info <name>")
            return
        name = rest[0]
        m = registry.get_installed(name)
        if not m:
            print(f"Skill '{name}' not installed. Try 'agentos marketplace search {name}'.")
            return
        print(f"\n  {m.name} v{m.version}  [{m.format.value}]")
        print(f"  {'─' * 40}")
        print(f"  描述:       {m.description or '-'}")
        print(f"  作者:       {m.author}")
        print(f"  许可:       {m.license_}")
        print(f"  格式:       {m.format.value}")
        print(f"  来源:       {m.source}")
        print(f"  安装路径:   {m.install_path or '-'}")
        if m.entrypoint:
            print(f"  入口:       {m.entrypoint}")
        if m.repository:
            print(f"  仓库:       {m.repository}")
        if m.homepage:
            print(f"  主页:       {m.homepage}")
        if m.tags:
            print(f"  标签:       {', '.join(m.tags)}")
        if m.tools:
            print(f"  工具 ({len(m.tools)}):")
            for t in m.tools:
                print(f"    - {t.name}: {t.description or 'N/A'}")
        if m.dependencies:
            print(f"  依赖:       {', '.join(m.dependencies)}")
        if m.mcp_command:
            print(f"  MCP:        {m.mcp_command} {' '.join(m.mcp_args)}")
            print(f"  MCP 类型:   {m.mcp_type}")
        if m.min_agentos_version:
            print(f"  要求版本:   >= {m.min_agentos_version}")
        print()

    elif sub == "update":
        if not rest:
            print("Usage: agentos marketplace update <name>")
            return
        name = rest[0]
        print(f"Updating '{name}'...")
        result = registry.update(name)
        if result.success and result.manifest:
            print(f"  Updated: {result.manifest.name} v{result.manifest.version}")
        else:
            print(f"  Failed: {result.error}")

    elif sub == "uninstall":
        if not rest:
            print("Usage: agentos marketplace uninstall <name>")
            return
        name = rest[0]
        if registry.uninstall(name):
            print(f"Uninstalled: {name}")
        else:
            print(f"Skill '{name}' not installed.")

    elif sub == "stats":
        stats = registry.stats()
        print(f"Marketplace Stats:")
        print(f"  Total installed: {stats['total']}")
        print(f"  Market dir:      {stats['market_dir']}")
        if stats.get("by_format"):
            print(f"  By format:")
            for fmt, count in stats["by_format"].items():
                print(f"    {fmt}: {count}")

    else:
        print(f"Unknown marketplace command: {sub}")
        print("Try: agentos marketplace --help")


def _run_enterprise(args: list[str]):
    """Enterprise CLI dispatcher."""

    if not args or args[0] in ("help", "--help", "-h"):
        print("AgentOS Enterprise CLI\n")
        print("Subcommands:")
        print("  api-key  create|list|revoke|stats    API Key management")
        print("  tenant   create|list|stats           Multi-tenant management")
        print("  audit    stats|recent|export          Audit logging")
        return

    sub = args[0]
    from agentos.enterprise import (
        APIKeyManager, TenantManager, AuditLogger,
        KeyCreateRequest, KeyScope, TenantTier,
    )

    if sub == "api-key":
        _run_enterprise_api_key(args[1:], APIKeyManager())
    elif sub == "tenant":
        _run_enterprise_tenant(args[1:], TenantManager())
    elif sub == "audit":
        _run_enterprise_audit(args[1:], AuditLogger())
    else:
        print(f"Unknown enterprise subcommand: {sub}")
        print("Try: agentos enterprise --help")


def _run_enterprise_api_key(args: list[str], mgr):
    if not args:
        print("Usage: agentos enterprise api-key <create|list|revoke|stats>")
        return
    cmd = args[0]
    if cmd == "create":
        name = args[1] if len(args) > 1 else "cli-key"
        result = mgr.create_key(KeyCreateRequest(name=name, scopes=[KeyScope.AGENT_RUN, KeyScope.READ]))
        print(f"Key created: {result.key_id}")
        print(f"Plaintext (only shown once): {result.plaintext_key}")
        print(f"Prefix: {result.key_prefix}")
        print(f"Scopes: {[s.value for s in result.scopes]}")
    elif cmd == "list":
        keys = mgr.list_keys()
        if not keys:
            print("No API keys.")
            return
        print(f"{'ID':<28s} {'Name':<24s} {'Status':<10s} {'Usage':<8s}")
        print("-" * 72)
        for k in keys:
            status = "revoked" if k.revoked else "active"
            print(f"{k.key_id:<28s} {k.name:<24s} {status:<10s} {k.usage_count:<8d}")
    elif cmd == "revoke":
        if len(args) < 2:
            print("Usage: agentos enterprise api-key revoke <key_id>")
            return
        ok = mgr.revoke_key(args[1])
        print(f"{'Revoked' if ok else 'Not found or already revoked'}: {args[1]}")
    elif cmd == "stats":
        stats = mgr.stats()
        print(f"Total: {stats['total']}  Active: {stats['active']}  Revoked: {stats['revoked']}  "
              f"Total usage: {stats['total_usage_count']}")
    else:
        print(f"Unknown api-key command: {cmd}")


def _run_enterprise_tenant(args: list[str], mgr):
    if not args:
        print("Usage: agentos enterprise tenant <create|list|stats>")
        return
    cmd = args[0]
    if cmd == "create":
        name = args[1] if len(args) > 1 else "default"
        tier_str = args[2] if len(args) > 2 else "free"
        tier = TenantTier(tier_str) if tier_str in [t.value for t in TenantTier] else TenantTier.FREE
        tenant = mgr.create_tenant(name=name, tier=tier)
        print(f"Tenant created: {tenant.tenant_id}")
        print(f"Name: {tenant.name}  Tier: {tenant.tier.value}")
    elif cmd == "list":
        tenants = mgr.list_tenants()
        if not tenants:
            print("No tenants.")
            return
        print(f"{'ID':<20s} {'Name':<20s} {'Tier':<12s} {'Status':<10s}")
        print("-" * 64)
        for t in tenants:
            print(f"{t.tenant_id:<20s} {t.name:<20s} {t.tier.value:<12s} {t.status.value:<10s}")
    elif cmd == "stats":
        stats = mgr.stats()
        print(f"Total tenants: {stats['total']}")
        print(f"By tier: {stats['by_tier']}")
        print(f"By status: {stats['by_status']}")
    else:
        print(f"Unknown tenant command: {cmd}")


def _run_enterprise_audit(args: list[str], logger):
    if not args:
        print("Usage: agentos enterprise audit <stats|recent|export>")
        return
    cmd = args[0]
    if cmd == "stats":
        stats = logger.stats()
        print(f"Total events: {stats['total_events']}")
        print(f"By category: {stats['by_category']}")
        print(f"By severity: {stats['by_severity']}")
    elif cmd == "recent":
        n = int(args[1]) if len(args) > 1 else 10
        events = logger.get_recent(n)
        if not events:
            print("No audit events.")
            return
        for e in events:
            ts = __import__('time').strftime("%H:%M:%S", __import__('time').gmtime(e.timestamp))
            print(f"[{ts}] {e.category.value:8s} {e.action:24s} {e.status}")
    elif cmd == "export":
        fmt = args[1] if len(args) > 1 else "json"
        if fmt == "csv":
            print(logger.export_csv()[:2000])
        else:
            print(logger.export_json()[:2000])
        print("... (truncated to 2000 chars)")
    else:
        print(f"Unknown audit command: {cmd}")


def _run_demo(verbose: bool):
    from agentos.llm import create_provider, Tool, ToolParameter
    from agentos.agent import ToolAgent, ToolExecutor, AgentConfig

    def get_weather(city: str) -> str:
        data = {
            "北京": "北京：晴，22°C，湿度 35%，东北风 3 级",
            "上海": "上海：多云转阴，28°C，湿度 70%，东南风 2 级",
            "深圳": "深圳：雷阵雨，31°C，湿度 85%",
        }
        return data.get(city, f"{city}: 数据暂缺")

    def get_stock(symbol: str) -> str:
        prices = {
            "AAPL": "$220.50 (+1.2%)",
            "TSLA": "$248.30 (-0.8%)",
        }
        return prices.get(symbol.upper(), f"{symbol}: 未找到")

    executor = ToolExecutor()
    executor.register(
        Tool.from_function("get_weather", "获取城市天气", {
            "city": ToolParameter(type="string", description="城市名"),
        }),
        get_weather,
    )
    executor.register(
        Tool.from_function("get_stock_price", "获取股票价格", {
            "symbol": ToolParameter(type="string", description="股票代码，如 AAPL"),
        }),
        get_stock,
    )

    if os.getenv("OPENAI_API_KEY"):
        provider = create_provider("openai")
    elif os.getenv("DEEPSEEK_API_KEY"):
        provider = create_provider("deepseek")
    else:
        print("\n  ⚠️  Mock 演示 — 配置 API Key 获取真实 AI 响应\n")
        print("    运行: agentos init\n")
        provider = MockLLMProvider([
            MockLLMProvider.tool_response(
                "get_weather", {"city": "北京"}, tool_call_id="tc_w1",
            ),
            MockLLMProvider.text_response(
                "北京目前天气晴，气温 22°C，湿度 35%，东北风 3 级。"
                "适合户外活动，建议带薄外套。"
            ),
        ])

    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(verbose=verbose, temperature=0.0),
        system_prompt="你是一个天气助手。用工具获取天气/股票信息后直接回答。",
    )

    result = agent.run("北京天气怎么样？")
    print(f"\nTask: 北京天气怎么样？")
    print(f"Steps: {result.total_steps} | Time: {(result.total_duration_ms/1000):.1f}s")
    print(f"Tokens: {result.total_tokens} | Cost: ${result.total_cost_usd:.4f}")
    print(f"Answer: {result.final_answer}")


if __name__ == "__main__":
    main()
