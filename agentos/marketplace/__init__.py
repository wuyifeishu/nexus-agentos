"""
AgentOS Skill Marketplace — Multi-format skill registry & discovery.

兼容格式:
  - agentos    原生 AgentOS Skill（entrypoint + tools）
  - openclaw   OpenClaw 社区 Skill（自动适配）
  - mcp        MCP 协议 Skill（stdio/sse 代理）
  - generic    通用 Python 包 Skill

导入源:
  - openclaw: OpenClawCommunity → 14+ skills
  - hf://     HuggingFace repos
  - github:// Arbitrary GitHub repos

CLI 入口:
  agentos marketplace search <query>     搜索技能市场
  agentos marketplace install <name|path|url>  安装技能
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

__all__ = [
    "SkillManifest", "SkillFormat", "ToolDef",
    "SkillRegistry", "SearchResult", "InstallResult",
    "OpenClawImporter", "HuggingFaceImporter", "GitHubImporter",
    "UnifiedImporter", "RemoteSkill",
]
