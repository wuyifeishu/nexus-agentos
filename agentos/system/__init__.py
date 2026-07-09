"""
System Operations Layer — 系统底层操作模块 (v1.7.1)
让 Agent 拥有真正的"手"，像用户一样操作系统资源。

核心设计:
- 分层授权: 每层操作需要对应权限级别，不越权
- 可视化审批: Agent 主动申请授权 → 用户点击同意/拒绝（P0 增强）
- 可审计: 所有操作记录到 AuditLogger
- 可沙箱: 高风险操作默认在沙箱内执行

权限层级 (由低到高):
  READ           — 只读（文件读取/目录列表/进程查看）
  WRITE_SANDBOX  — 沙箱写入（仅限指定目录）
  WRITE_ALL      — 全盘写入（危险，需明确授权）
  SHELL_READONLY — 只读 Shell 命令
  SHELL_STANDARD — 标准 Shell（超时/目录限制）
  SHELL_FULL     — 全权限 Shell（需二次确认）
  BROWSER        — 浏览器自动化
  ADMIN          — 系统管理（安装/卸载/配置）
"""

from agentos.system.approval import (
    ApprovalEngine,
    ApprovalStatus,
    ApprovalTicket,
)
from agentos.system.browser import (
    BrowserAction,
    BrowserResult,
    BrowserSession,
    CDPBrowser,
)
from agentos.system.file_ops import (
    FileListing,
    FileOperator,
    FileOpResult,
)
from agentos.system.permissions import (
    PermissionContext,
    PermissionDenied,
    PermissionTier,
    SystemPermission,
    SystemPermissionManager,
)
from agentos.system.shell_exec import (
    ShellExecutor,
    ShellPolicy,
    ShellResult,
    ShellSandbox,
)

__all__ = [
    # Permissions
    "SystemPermission",
    "PermissionTier",
    "PermissionContext",
    "PermissionDenied",
    "SystemPermissionManager",
    # File Ops
    "FileOperator",
    "FileOpResult",
    "FileListing",
    # Shell
    "ShellExecutor",
    "ShellResult",
    "ShellSandbox",
    "ShellPolicy",
    # Browser
    "BrowserSession",
    "BrowserAction",
    "BrowserResult",
    "CDPBrowser",
    # Approval
    "ApprovalEngine",
    "ApprovalTicket",
    "ApprovalStatus",
]
