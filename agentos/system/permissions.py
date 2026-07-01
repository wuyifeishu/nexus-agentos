"""
分层权限系统 — 让 Agent 操作系统的每一步都在受控范围内。

权限层级设计理念:
- 参考 Android 权限模型的分级思想
- 默认最小权限原则 (Principle of Least Privilege)
- 高风险操作需二次确认
- 支持会话级/全局级权限配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Optional, Callable

# ── 权限层级定义 ──────────────────────────────────────────────


class PermissionTier(IntEnum):
    """权限层级，数值越大权限越高。"""
    READ = 0              # 只读访问
    WRITE_SANDBOX = 1     # 沙箱写入
    WRITE_ALL = 2         # 全盘写入
    SHELL_READONLY = 3    # 只读 Shell
    SHELL_STANDARD = 4    # 标准 Shell（超时/目录限制）
    SHELL_FULL = 5        # 全权限 Shell
    BROWSER = 6           # 浏览器自动化
    ADMIN = 7             # 系统管理

    @property
    def label(self) -> str:
        """中文标签，用于 UI 展示。"""
        return {
            0: "只读访问",
            1: "沙箱写入",
            2: "全盘写入",
            3: "只读Shell",
            4: "标准Shell",
            5: "全权限Shell",
            6: "浏览器自动化",
            7: "系统管理",
        }.get(self.value, "未知")


@dataclass
class SystemPermission:
    """单个系统权限定义。"""
    tier: PermissionTier
    resource: str                          # 资源标识，如 "/home/user/*", "apt:install"
    description: str = ""
    requires_confirmation: bool = False    # 是否需要用户二次确认
    rate_limit_per_minute: int = 0         # 0 表示不限


# ── 预设权限策略 ──────────────────────────────────────────────

# 安全模式（默认）: 允许读写但 Shell 受限
SAFE_PERMISSIONS: list[SystemPermission] = [
    SystemPermission(PermissionTier.READ, "*", "读取任意文件"),
    SystemPermission(PermissionTier.WRITE_SANDBOX, "/tmp/agentos/**", "沙箱写入"),
    SystemPermission(PermissionTier.SHELL_READONLY, "ls,cat,head,tail,find,ps,df,du,whoami,pwd,env,echo,date,wc,stat,file,which,uname", "只读 Shell 命令"),
    SystemPermission(PermissionTier.BROWSER, "*", "浏览器自动化", requires_confirmation=True),
]

# 开发模式: 允许写 + 标准 Shell
DEV_PERMISSIONS: list[SystemPermission] = SAFE_PERMISSIONS + [
    SystemPermission(PermissionTier.WRITE_ALL, "/home/**", "用户目录读写"),
    SystemPermission(PermissionTier.SHELL_STANDARD, "*", "标准 Shell（超时60s，沙箱目录）"),
    SystemPermission(PermissionTier.BROWSER, "*", "浏览器自动化"),
]

# 全权限模式: 无限制（高风险，仅限受信环境）
FULL_PERMISSIONS: list[SystemPermission] = [
    SystemPermission(PermissionTier.ADMIN, "*", "完全权限"),
]


# ── 权限上下文 ─────────────────────────────────────────────────


@dataclass
class PermissionContext:
    """权限检查的上下文信息。"""
    session_id: str
    agent_id: str = ""
    user_id: str = ""
    tier: PermissionTier = PermissionTier.READ
    granted_permissions: list[SystemPermission] = field(default_factory=lambda: SAFE_PERMISSIONS.copy())
    # 回调：当需要用户确认时触发
    on_confirm_needed: Optional[Callable[[SystemPermission, str], bool]] = None


class PermissionDenied(Exception):
    """权限拒绝异常。"""
    def __init__(self, required: PermissionTier, resource: str, detail: str = ""):
        self.required = required
        self.resource = resource
        self.detail = detail
        super().__init__(f"权限不足: 需要 {required.name} 访问 {resource}{' — ' + detail if detail else ''}")


# ── 权限管理器 ─────────────────────────────────────────────────


class SystemPermissionManager:
    """系统权限管理器 — 检查、授权、升级、审计。"""

    def __init__(self, default_tier: PermissionTier = PermissionTier.READ):
        self._contexts: dict[str, PermissionContext] = {}
        self._default_tier = default_tier

    # ── 会话管理 ──

    def create_session(
        self,
        session_id: str,
        tier: PermissionTier | None = None,
        permissions: list[SystemPermission] | None = None,
    ) -> PermissionContext:
        """创建权限会话。"""
        ctx = PermissionContext(
            session_id=session_id,
            tier=tier or self._default_tier,
            granted_permissions=permissions or SAFE_PERMISSIONS.copy(),
        )
        self._contexts[session_id] = ctx
        return ctx

    def get_session(self, session_id: str) -> PermissionContext:
        """获取会话，不存在则创建默认会话。"""
        if session_id not in self._contexts:
            return self.create_session(session_id)
        return self._contexts[session_id]

    def close_session(self, session_id: str) -> None:
        self._contexts.pop(session_id, None)

    # ── 权限检查 ──

    def check(self, session_id: str, required_tier: PermissionTier, resource: str) -> bool:
        """检查是否拥有指定资源的权限。"""
        ctx = self.get_session(session_id)

        # 检查是否有匹配的权限
        for perm in ctx.granted_permissions:
            if self._tier_covers(perm.tier, required_tier) and self._resource_matches(perm.resource, resource):
                # 需要确认则触发回调
                if perm.requires_confirmation:
                    if ctx.on_confirm_needed and not ctx.on_confirm_needed(perm, resource):
                        return False
                return True
        return False

    def require(self, session_id: str, required_tier: PermissionTier, resource: str) -> None:
        """要求权限，不满足则抛出 PermissionDenied。"""
        if not self.check(session_id, required_tier, resource):
            ctx = self.get_session(session_id)
            current_max = max((p.tier for p in ctx.granted_permissions), default=PermissionTier.READ)
            raise PermissionDenied(
                required_tier, resource,
                f"当前最高权限: {current_max.name}，需要: {required_tier.name}",
            )

    # ── 权限升级 ──

    def elevate(
        self,
        session_id: str,
        tier: PermissionTier,
        permissions: list[SystemPermission] | None = None,
        require_user_approval: bool = True,
    ) -> bool:
        """升级会话权限级别。"""
        ctx = self.get_session(session_id)

        if require_user_approval:
            # 触发用户确认流程
            if ctx.on_confirm_needed:
                dummy_perm = SystemPermission(tier, "*", f"升级到 {tier.name}")
                if not ctx.on_confirm_needed(dummy_perm, "elevate"):
                    return False

        ctx.tier = tier
        if permissions:
            ctx.granted_permissions = permissions
        return True

    # ── 临时提权（供 ApprovalEngine 审批通过后调用）──

    def escalate(self, session_id: str, tier: PermissionTier, resource: str) -> None:
        """单次临时提权 — 审批通过后临时授予某资源访问权，本会话有效。

        与 elevate 不同：escalate 是细粒度的、单资源、可撤销的临时授权；
        elevate 是整体层级提升。
        """
        ctx = self.get_session(session_id)
        # 添加临时权限（不持久化，仅本会话）
        temp_perm = SystemPermission(
            tier=tier,
            resource=resource,
            description=f"临时授权: {tier.label} → {resource}",
            requires_confirmation=False,  # 已经审批过，无需二次确认
        )
        ctx.granted_permissions.append(temp_perm)

    def revoke_escalation(self, session_id: str, resource: str) -> None:
        """撤销某资源的临时提权。"""
        ctx = self.get_session(session_id)
        ctx.granted_permissions = [
            p for p in ctx.granted_permissions
            if not (p.description.startswith("临时授权:") and p.resource == resource)
        ]

    # ── 预设模式快捷切换 ──

    def set_safe_mode(self, session_id: str) -> None:
        """切换到安全模式。"""
        ctx = self.get_session(session_id)
        ctx.granted_permissions = SAFE_PERMISSIONS.copy()
        ctx.tier = PermissionTier.WRITE_SANDBOX

    def set_dev_mode(self, session_id: str) -> None:
        """切换到开发模式。"""
        ctx = self.get_session(session_id)
        ctx.granted_permissions = DEV_PERMISSIONS.copy()
        ctx.tier = PermissionTier.SHELL_STANDARD

    def set_full_mode(self, session_id: str) -> None:
        """切换到全权限模式（需确认）。"""
        ctx = self.get_session(session_id)
        ctx.granted_permissions = FULL_PERMISSIONS.copy()
        ctx.tier = PermissionTier.ADMIN

    # ── 辅助方法 ──

    @staticmethod
    def _tier_covers(granted: PermissionTier, required: PermissionTier) -> bool:
        """检查授权层级是否覆盖需求层级。"""
        return granted.value >= required.value

    @staticmethod
    def _resource_matches(pattern: str, resource: str) -> bool:
        """简单的资源匹配（支持 * 通配符）。"""
        if pattern == "*":
            return True
        # 支持 ** 递归匹配
        if "**" in pattern:
            prefix = pattern.replace("**", "")
            return resource.startswith(prefix)
        # 支持 * 单层匹配
        if "*" in pattern:
            import fnmatch
            return fnmatch.fnmatch(resource, pattern)
        return resource == pattern or resource.startswith(pattern)
