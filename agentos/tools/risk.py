"""
AgentOS v1.1.4 Tool Risk Rating — 工具风险分级。

给每个工具标注低/中/高风险，触发对应级别的 guard 检查。
灵感来自 OpenAI Agents SDK 的 Tool Risk Rating 设计。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolRiskLevel(StrEnum):
    """工具操作风险等级。

    LOW:     只读查询、信息检索，无副作用
    MEDIUM:  写入/修改操作，可逆或有审计
    HIGH:    删除、支付、发消息等不可逆操作
    CRITICAL: 系统级操作（格式化、重置、权限变更）
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ToolRiskRating:
    """工具风险评定元数据。"""

    level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    """风险等级。"""

    reversible: bool = True
    """操作是否可逆。"""

    requires_approval: bool = False
    """是否需要人工审批。"""

    financial_impact: bool = False
    """是否有财务影响。"""

    description: str = ""
    """风险说明。"""

    def requires_user_confirm(self) -> bool:
        """是否需要二次确认。"""
        return (
            self.level in (ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL)
            or self.requires_approval
            or self.financial_impact
        )


# ── 常见操作的风险预设 ──────────────────────────────────────────────────────

RISK_PRESETS: dict[str, ToolRiskRating] = {
    # 只读操作 → LOW
    "list_files": ToolRiskRating(
        level=ToolRiskLevel.LOW, reversible=True, description="只读文件列表"
    ),
    "read_file": ToolRiskRating(
        level=ToolRiskLevel.LOW, reversible=True, description="只读文件内容"
    ),
    "search": ToolRiskRating(level=ToolRiskLevel.LOW, reversible=True, description="搜索查询"),
    "get_current_time": ToolRiskRating(
        level=ToolRiskLevel.LOW, reversible=True, description="读取系统时间"
    ),
    "weather_query": ToolRiskRating(
        level=ToolRiskLevel.LOW, reversible=True, description="天气查询"
    ),
    # 写入操作 → MEDIUM
    "write_file": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=True, description="创建或写入文件"
    ),
    "create_directory": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=True, description="创建目录"
    ),
    "rename_file": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=True, description="重命名文件"
    ),
    "update_config": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=True, description="修改配置"
    ),
    "send_http_request": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=True, description="发送HTTP请求"
    ),
    "install_package": ToolRiskRating(
        level=ToolRiskLevel.MEDIUM, reversible=False, description="安装软件包"
    ),
    # 删除/破坏 → HIGH
    "delete_file": ToolRiskRating(
        level=ToolRiskLevel.HIGH,
        reversible=False,
        requires_approval=True,
        description="删除文件（移入回收站）",
    ),
    "delete_directory": ToolRiskRating(
        level=ToolRiskLevel.HIGH,
        reversible=False,
        requires_approval=True,
        description="删除目录",
    ),
    "truncate_table": ToolRiskRating(
        level=ToolRiskLevel.HIGH,
        reversible=False,
        requires_approval=True,
        description="清空数据库表",
    ),
    "send_message": ToolRiskRating(
        level=ToolRiskLevel.HIGH,
        reversible=False,
        requires_approval=True,
        description="发送消息/通知",
    ),
    # 高风险/财务/系统 → CRITICAL
    "execute_payment": ToolRiskRating(
        level=ToolRiskLevel.CRITICAL,
        reversible=False,
        requires_approval=True,
        financial_impact=True,
        description="执行支付操作",
    ),
    "format_disk": ToolRiskRating(
        level=ToolRiskLevel.CRITICAL,
        reversible=False,
        requires_approval=True,
        description="格式化磁盘",
    ),
    "reset_system": ToolRiskRating(
        level=ToolRiskLevel.CRITICAL,
        reversible=False,
        requires_approval=True,
        description="重置系统",
    ),
    "modify_permissions": ToolRiskRating(
        level=ToolRiskLevel.CRITICAL,
        reversible=True,
        requires_approval=True,
        description="修改系统权限",
    ),
}


def get_risk_preset(tool_name: str) -> ToolRiskRating | None:
    """根据工具名称获取预设风险等级。"""
    return RISK_PRESETS.get(tool_name.lower())


def infer_risk_level(
    tool_name: str,
    tool_description: str = "",
    arguments: dict | None = None,
) -> ToolRiskRating:
    """根据工具名和描述推断风险等级。

    优先使用预设，否则通过关键词推断。
    """
    preset = get_risk_preset(tool_name)
    if preset:
        return preset

    name_lower = tool_name.lower()
    desc_lower = tool_description.lower()

    # Critical keywords
    critical_kw = ["format", "reset", "payment", "root", "sudo", "admin privilege"]
    high_kw = ["delete", "remove", "drop", "purge", "truncate", "send", "publish", "notify"]
    medium_kw = ["write", "create", "update", "modify", "install", "deploy", "execute", "run"]

    all_text = f"{name_lower} {desc_lower}"

    if any(kw in all_text for kw in critical_kw):
        return ToolRiskRating(
            level=ToolRiskLevel.CRITICAL,
            reversible=False,
            requires_approval=True,
            description=f"推断为 CRITICAL: {tool_name}",
        )
    if any(kw in all_text for kw in high_kw):
        return ToolRiskRating(
            level=ToolRiskLevel.HIGH,
            reversible=False,
            requires_approval=True,
            description=f"推断为 HIGH: {tool_name}",
        )
    if any(kw in all_text for kw in medium_kw):
        return ToolRiskRating(
            level=ToolRiskLevel.MEDIUM,
            reversible=True,
            description=f"推断为 MEDIUM: {tool_name}",
        )
    return ToolRiskRating(
        level=ToolRiskLevel.LOW,
        reversible=True,
        description=f"推断为 LOW: {tool_name}",
    )
