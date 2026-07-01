"""
AgentOS Skill Marketplace — Multi-format skill registry & discovery + ecosystem bridge.

兼容格式:
  - agentos    原生 AgentOS Skill（entrypoint + tools）
  - openclaw   OpenClaw 社区 Skill（自动适配）
  - mcp        MCP 协议 Skill（stdio/sse 代理）
  - generic    通用 Python 包 Skill
  - claude-code Claude Code 扩展 → 自动转换
  - cursor      Cursor 规则 → 自动转换
  - custom-gpt  Custom GPT 指令 → 自动转换
  - langchain   LangChain 工具 → 自动转换

导入源:
  - openclaw: OpenClawCommunity → 14+ skills
  - hf://     HuggingFace repos
  - github:// Arbitrary GitHub repos
  - claude://  Claude Code extension ID
  - cursor://  Cursor rule path
  - gpt://     Custom GPT ID

CLI 入口:
  agentos marketplace search <query>     搜索技能市场
  agentos marketplace install <name|path|url>  安装技能
  agentos marketplace bridge <format> <source>  桥接外部生态
  agentos marketplace list               列出已安装
  agentos marketplace info <name>        查看详情
  agentos marketplace update <name>      更新技能
  agentos marketplace uninstall <name>   卸载技能
"""

from agentos.marketplace.manifest import SkillManifest, SkillFormat, ToolDef
from agentos.marketplace.registry import SkillRegistry, SearchResult, InstallResult
from agentos.marketplace.importer import (
    OpenClawImporter,
    HuggingFaceImporter,
    GitHubImporter,
    UnifiedImporter,
    RemoteSkill,
)
from agentos.marketplace.bridge import (
    EcosystemBridge,
    EcosystemFormat,
    BridgeResult,
    BridgeBatchResult,
    ClaudeCodeAdapter,
    CursorAdapter,
    CustomGPTAdapter,
    LangChainAdapter,
    AdapterFactory,
)

__all__ = [
    "SkillManifest", "SkillFormat", "ToolDef",
    "SkillRegistry", "SearchResult", "InstallResult",
    "OpenClawImporter", "HuggingFaceImporter", "GitHubImporter",
    "UnifiedImporter", "RemoteSkill",
    # Ecosystem Bridge v1.9.0
    "EcosystemBridge", "EcosystemFormat", "BridgeResult", "BridgeBatchResult",
    "ClaudeCodeAdapter", "CursorAdapter", "CustomGPTAdapter", "LangChainAdapter",
    "AdapterFactory",
]
