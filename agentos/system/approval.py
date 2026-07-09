"""
可视化授权引擎 — Agent 主动申请权限，用户可视化审批。

与 permissions.py 的分工:
- permissions.py: 纯程序化权限检查（require/check）
- approval.py:   HITL 授权流程（Agent 发起申请 → 用户审批 → 回调）

流程:
1. Agent 调用 request_approval(tier, resource, reason)
2. 引擎生成 ApprovalTicket，挂起等待
3. 通过 WebSocket 推送给桌面客户端
4. 用户在 UI 点击"同意" / "拒绝" / "拒绝+记住"
5. 回调触发，Agent 继续或拒绝
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from agentos.system.permissions import PermissionTier


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    DENIED_REMEMBER = "denied_remember"  # 拒绝并记住，本次会话不再询问
    TIMEOUT = "timeout"


@dataclass
class ApprovalTicket:
    """授权申请票据。"""

    ticket_id: str
    tier: PermissionTier
    resource: str  # 申请访问的资源路径/命令
    reason: str  # Agent 申请原因（AI 生成的中文说明）
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: str = ""
    session_id: str = ""
    # 回调
    _future: asyncio.Future | None = field(default=None, repr=False)

    def __post_init__(self):
        if self._future is None:
            self._future = asyncio.Future()

    async def wait(self, timeout: float = 60.0) -> ApprovalStatus:
        """等待审批结果。"""
        try:
            return await asyncio.wait_for(asyncio.shield(self._future), timeout=timeout)
        except TimeoutError:
            self.status = ApprovalStatus.TIMEOUT
            self.resolved_at = datetime.now().isoformat()
            return ApprovalStatus.TIMEOUT

    def approve(self) -> None:
        """批准。"""
        self.status = ApprovalStatus.APPROVED
        self.resolved_at = datetime.now().isoformat()
        if self._future and not self._future.done():
            self._future.set_result(ApprovalStatus.APPROVED)

    def deny(self, remember: bool = False) -> None:
        """拒绝。"""
        self.status = ApprovalStatus.DENIED_REMEMBER if remember else ApprovalStatus.DENIED
        self.resolved_at = datetime.now().isoformat()
        if self._future and not self._future.done():
            self._future.set_result(self.status)


class ApprovalEngine:
    """可视化授权引擎 — 管理审批流程。

    用法:
        engine = ApprovalEngine(pm, session_id)
        engine.set_push_callback(send_to_ws)  # 设置推送回调

        # Agent 侧:
        approved = await engine.request(
            PermissionTier.SHELL_STANDARD,
            "rm -rf ./build/",
            "需要清理构建缓存以释放磁盘空间",
        )
        if approved:
            # 执行操作
    """

    def __init__(self, perm_manager, session_id: str):
        self._pm = perm_manager
        self._sid = session_id
        self._push_callback: Callable[[dict], Awaitable[None]] | None = None
        self._pending: dict[str, ApprovalTicket] = {}
        self._denied_remember: set[str] = set()  # 本次会话已记住拒绝的 (tier, pattern)

    def set_push_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """设置推送回调（发送到 WebSocket 客户端）。"""
        self._push_callback = callback

    async def request(
        self, tier: PermissionTier, resource: str, reason: str, timeout: float = 60.0
    ) -> bool:
        """Agent 发起权限申请，返回是否获批。

        如果已有 DENIED_REMEMBER 记录，直接返回 False。
        """
        # 检查是否已记住拒绝
        deny_key = f"{tier.value}:{resource}"
        if deny_key in self._denied_remember:
            return False

        ticket = ApprovalTicket(
            ticket_id=f"approval-{uuid.uuid4().hex[:12]}",
            tier=tier,
            resource=resource,
            reason=reason,
            session_id=self._sid,
        )
        self._pending[ticket.ticket_id] = ticket

        # 推送到客户端
        if self._push_callback:
            try:
                await self._push_callback(
                    {
                        "type": "approval_request",
                        "data": {
                            "ticket_id": ticket.ticket_id,
                            "tier": ticket.tier.value,
                            "tier_label": ticket.tier.label,
                            "resource": ticket.resource,
                            "reason": ticket.reason,
                            "session_id": self._sid,
                            "timeout": timeout,
                        },
                    }
                )
            except Exception:
                pass  # 推送失败不阻塞

        # 等待审批
        result = await ticket.wait(timeout=timeout)

        # 处理记住拒绝
        if result == ApprovalStatus.DENIED_REMEMBER:
            self._denied_remember.add(deny_key)

        # 如果审批通过，临时提升权限
        if result == ApprovalStatus.APPROVED:
            self._pm.escalate(self._sid, tier, resource)

        # 清理
        self._pending.pop(ticket.ticket_id, None)

        return result == ApprovalStatus.APPROVED

    def resolve(self, ticket_id: str, approved: bool, remember: bool = False) -> bool:
        """手动审批票据（从 UI 调用）。"""
        ticket = self._pending.get(ticket_id)
        if not ticket or ticket.status != ApprovalStatus.PENDING:
            return False

        if approved:
            ticket.approve()
        else:
            ticket.deny(remember=remember)
        return True

    def get_pending_tickets(self) -> list[dict]:
        """获取所有待审批票据（供 UI 轮询）。"""
        return [
            {
                "ticket_id": t.ticket_id,
                "tier": t.tier.value,
                "tier_label": t.tier.label,
                "resource": t.resource,
                "reason": t.reason,
                "created_at": t.created_at,
                "timeout_remaining": max(
                    0, 60 - (datetime.now() - datetime.fromisoformat(t.created_at)).total_seconds()
                ),
            }
            for t in self._pending.values()
            if t.status == ApprovalStatus.PENDING
        ]

    def clear_denied(self) -> None:
        """清除本次会话的记住拒绝记录。"""
        self._denied_remember.clear()
