"""
AgentOS v1.14.2 — Dynamic HITL UI (Gradio-based Approval Dashboard).

受 LangGraph Studio / AutoGen UI 启发，在已有 HITL 审批引擎之上
增加 Gradio 驱动的响应式审批面板。Agent 遇到高风险操作时，
自动弹出 Web UI 而非阻塞终端。

Core features:
- GradioApp: 一键启动的审批 Dashboard
- ApprovalQueue: 实时审批队列，WebSocket 推送
- AgentStatusPanel: Agent 状态监控面板
- ApprovalCard: 可定制的审批卡片组件
- HistoryView: 审批历史追溯
- PolicyEditor: 可视化策略编辑器

与 hitl/approver.py 的关系:
- approver.py: 审批引擎（决策逻辑、风险评级、策略执行）
- gradio_ui.py: 交互层（Web UI、实时推送、可视化配置）
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import (
    Any,
)

# ── UI Data Models ──────────────────────────


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RiskLevelUI(StrEnum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ApprovalRequestUI:
    """UI 层的审批请求，与底层 HITL 解耦。"""

    request_id: str = field(default_factory=lambda: f"apr-{uuid.uuid4().hex[:8]}")
    agent_name: str = ""
    action: str = ""  # 人类可读的操作描述
    details: str = ""  # 详细说明
    risk_level: RiskLevelUI = RiskLevelUI.MEDIUM
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 超时自动拒绝
    source_file: str = ""  # 触发操作的文件/代码位置
    metadata: dict[str, Any] = field(default_factory=dict)
    # Callback when approved/denied
    on_decision: Callable | None = None

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at


@dataclass
class ApprovalHistory:
    """审批历史记录。"""

    request: ApprovalRequestUI
    decision: ApprovalStatus
    decided_by: str = "user"  # "user" | "auto" | "timeout"
    reason: str = ""
    decided_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request.request_id,
            "action": self.request.action,
            "risk_level": self.request.risk_level.value,
            "decision": self.decision.value,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "created_at": self.request.created_at,
            "decided_at": self.decided_at,
            "elapsed_ms": int((self.decided_at - self.request.created_at) * 1000),
        }


@dataclass
class AgentStatusSnapshot:
    """Agent 运行状态快照。"""

    agent_id: str = ""
    agent_name: str = ""
    status: str = "idle"  # idle | running | waiting_approval | paused | error
    current_task: str = ""
    elapsed_seconds: float = 0.0
    pending_approvals: int = 0
    memory_fragments: int = 0
    last_error: str = ""


# ── Approval Queue ─────────────────────────


class ApprovalQueue:
    """线程安全的审批队列，支持 WebSocket 推送通知。

    在 Gradio UI 与 Agent HITL 引擎之间架设实时通信桥梁。
    """

    def __init__(self, max_size: int = 100, default_timeout: float = 300.0):
        self._queue: queue.Queue = queue.Queue(maxsize=max_size)
        self._pending: dict[str, ApprovalRequestUI] = {}
        self._history: list[ApprovalHistory] = []
        self._subscribers: list[Callable] = []  # WebSocket callbacks
        self._default_timeout = default_timeout
        self._lock = threading.Lock()

    def submit(self, request: ApprovalRequestUI) -> str:
        """提交审批请求。注册到队列并通知订阅者。"""
        if request.expires_at <= 0:
            request.expires_at = time.time() + self._default_timeout

        with self._lock:
            self._pending[request.request_id] = request

        self._notify_subscribers(
            {
                "event": "new_request",
                "request_id": request.request_id,
                "action": request.action,
                "risk_level": request.risk_level.value,
                "pending_count": len(self._pending),
            }
        )

        return request.request_id

    def decide(self, request_id: str, approved: bool, reason: str = "") -> ApprovalHistory | None:
        """处理审批决定。"""
        with self._lock:
            request = self._pending.pop(request_id, None)

        if request is None:
            return None

        decision = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        history = ApprovalHistory(
            request=request,
            decision=decision,
            reason=reason,
        )

        # Trigger callback
        if request.on_decision:
            try:
                request.on_decision(approved, reason)
            except Exception:
                pass

        with self._lock:
            self._history.append(history)

        self._notify_subscribers(
            {
                "event": "decision",
                "request_id": request_id,
                "approved": approved,
                "reason": reason,
                "pending_count": len(self._pending),
            }
        )

        return history

    def approve_all(self) -> int:
        """批量批准所有待处理请求。"""
        ids = list(self._pending.keys())
        for rid in ids:
            self.decide(rid, True, "batch_approve")
        return len(ids)

    def deny_all(self) -> int:
        """批量拒绝所有待处理请求。"""
        ids = list(self._pending.keys())
        for rid in ids:
            self.decide(rid, False, "batch_deny")
        return len(ids)

    def check_timeouts(self) -> int:
        """检查并自动拒绝超时请求。"""
        time.time()
        expired_ids = []
        with self._lock:
            for rid, req in self._pending.items():
                if req.is_expired:
                    expired_ids.append(rid)

        for rid in expired_ids:
            history = self.decide(rid, False, "timeout")
            if history:
                history.decided_by = "timeout"

        return len(expired_ids)

    @property
    def pending_requests(self) -> list[ApprovalRequestUI]:
        with self._lock:
            return list(self._pending.values())

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def recent_history(self, limit: int = 50) -> list[ApprovalHistory]:
        with self._lock:
            return self._history[-limit:]

    def subscribe(self, callback: Callable) -> None:
        """注册 WebSocket 通知回调。"""
        self._subscribers.append(callback)

    def _notify_subscribers(self, data: dict) -> None:
        for cb in self._subscribers:
            try:
                cb(data)
            except Exception:
                pass


# ── Gradio Approval Dashboard ──────────────


class ApprovalDashboard:
    """Gradio 驱动的审批面板。

    核心布局:
    - 顶部: Agent 状态栏
    - 左侧: 待审批队列
    - 右侧: 审批详情 + 历史
    - 底部: 批量操作按钮

    Usage:
        dashboard = ApprovalDashboard(queue, port=7860)
        dashboard.launch()
    """

    def __init__(
        self,
        approval_queue: ApprovalQueue,
        port: int = 7860,
        title: str = "AgentOS — HITL Approval Dashboard",
        theme: str = "soft",
        auto_launch: bool = True,
    ):
        self._queue = approval_queue
        self._port = port
        self._title = title
        self._theme = theme
        self._auto_launch = auto_launch
        self._app = None
        self._agent_statuses: dict[str, AgentStatusSnapshot] = {}
        self._selected_request_id: str = ""

    def launch(self, share: bool = False) -> Any:
        """启动 Gradio 面板。

        返回 Gradio Blocks 实例，可在 Jupyter 中内嵌或独立运行。
        """
        try:
            import gradio as gr
        except ImportError:
            raise ImportError(
                "Gradio is required for ApprovalDashboard. " "Install with: pip install gradio>=4.0"
            )

        with gr.Blocks(title=self._title, theme=self._theme) as app:
            self._app = app
            self._build_ui(app)

        if self._auto_launch:
            app.launch(
                server_port=self._port,
                share=share,
                prevent_thread_lock=False,
            )

        return app

    def _build_ui(self, app: Any) -> None:
        """构建完整 UI 布局。"""
        import gradio as gr

        # ── Header ──
        gr.Markdown(f"# {self._title}\n" f"### Real-time Human-in-the-Loop Approval Dashboard")

        # ── Agent Status Bar ──
        with gr.Row():
            self._agent_status_display = gr.HTML(
                value=self._render_agent_status_bar(),
                every=3.0,
            )

        # ── Main Layout ──
        with gr.Row():
            # Left: Pending Queue
            with gr.Column(scale=1):
                gr.Markdown("### Pending Approvals")
                self._queue_list = gr.HTML(
                    value=self._render_pending_queue(),
                    every=2.0,
                )
                with gr.Row():
                    self._btn_approve_all = gr.Button("Approve All", variant="primary", size="sm")
                    self._btn_deny_all = gr.Button("Deny All", variant="stop", size="sm")

            # Right: Detail + History
            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.TabItem("Approval Detail"):
                        self._detail_view = gr.HTML(
                            value="<p>Select a request from the queue...</p>"
                        )
                        with gr.Row():
                            self._btn_approve = gr.Button("Approve", variant="primary")
                            self._btn_deny = gr.Button("Deny", variant="stop")
                        self._reason_input = gr.Textbox(
                            label="Reason (optional)",
                            placeholder="Why this decision...",
                        )

                    with gr.TabItem("History"):
                        self._history_view = gr.HTML(
                            value=self._render_history(),
                            every=3.0,
                        )

                    with gr.TabItem("Policy"):
                        self._policy_view = gr.HTML(value=self._render_policy_editor())

            # ── Event Handlers ──
            self._btn_approve.click(
                fn=self._handle_approve,
                inputs=[self._reason_input],
                outputs=[self._detail_view, self._queue_list, self._history_view],
            )
            self._btn_deny.click(
                fn=self._handle_deny,
                inputs=[self._reason_input],
                outputs=[self._detail_view, self._queue_list, self._history_view],
            )
            self._btn_approve_all.click(
                fn=lambda: self._queue.approve_all(),
                outputs=[],
            )
            self._btn_deny_all.click(
                fn=lambda: self._queue.deny_all(),
                outputs=[],
            )

    def _handle_approve(self, reason: str) -> tuple[str, str, str]:
        if not self._selected_request_id:
            return self._detail_view, self._queue_list, self._history_view
        self._queue.decide(self._selected_request_id, True, reason)
        self._selected_request_id = ""
        return (
            "<p>Select a request from the queue...</p>",
            self._render_pending_queue(),
            self._render_history(),
        )

    def _handle_deny(self, reason: str) -> tuple[str, str, str]:
        if not self._selected_request_id:
            return self._detail_view, self._queue_list, self._history_view
        self._queue.decide(self._selected_request_id, False, reason)
        self._selected_request_id = ""
        return (
            "<p>Select a request from the queue...</p>",
            self._render_pending_queue(),
            self._render_history(),
        )

    def update_agent_status(self, snapshot: AgentStatusSnapshot) -> None:
        """更新 Agent 状态（由外部 Agent loop 调用）。"""
        self._agent_statuses[snapshot.agent_id] = snapshot

    def _render_agent_status_bar(self) -> str:
        """渲染 Agent 状态栏 HTML。"""
        if not self._agent_statuses:
            return (
                '<div style="padding:12px;background:#f0f0f0;border-radius:8px;">'
                '<span style="color:#888;">No agents connected</span></div>'
            )

        rows = []
        for agent_id, snap in self._agent_statuses.items():
            status_color = {
                "idle": "#4CAF50",
                "running": "#2196F3",
                "waiting_approval": "#FF9800",
                "paused": "#9E9E9E",
                "error": "#F44336",
            }.get(snap.status, "#9E9E9E")

            rows.append(
                f'<div style="display:inline-block;margin:4px 8px;padding:8px 12px;'
                f'background:#fff;border-radius:6px;border-left:4px solid {status_color};">'
                f"<b>{snap.agent_name}</b> "
                f'<span style="color:{status_color};">● {snap.status}</span> '
                f"| {snap.current_task[:30]} "
                f"| {snap.pending_approvals} pending"
                f"</div>"
            )

        return (
            '<div style="padding:12px;background:#f0f0f0;border-radius:8px;">'
            + "".join(rows)
            + "</div>"
        )

    def _render_pending_queue(self) -> str:
        """渲染待处理队列 HTML。"""
        pending = self._queue.pending_requests
        if not pending:
            return '<p style="color:#888;">No pending approvals</p>'

        risk_colors = {
            "safe": "#4CAF50",
            "low": "#8BC34A",
            "medium": "#FF9800",
            "high": "#F44336",
            "critical": "#B71C1C",
        }

        cards = []
        for req in pending:
            color = risk_colors.get(req.risk_level.value, "#999")
            elapsed = int(req.elapsed_seconds)
            cards.append(
                f"<div onclick=\"selectRequest('{req.request_id}')\" "
                f'style="cursor:pointer;margin:6px 0;padding:10px;'
                f"background:#fff;border-radius:6px;"
                f'border-left:4px solid {color};">'
                f'<div style="font-weight:bold;">{req.action[:60]}</div>'
                f'<div style="color:{color};font-size:0.85em;">'
                f"Risk: {req.risk_level.value} | Agent: {req.agent_name} | "
                f"{elapsed}s ago</div>"
                f"</div>"
            )

        return "".join(cards)

    def _render_history(self) -> str:
        """渲染审批历史。"""
        history = self._queue.recent_history(limit=30)
        if not history:
            return "<p>No history yet</p>"

        rows = ["<table style='width:100%;border-collapse:collapse;'>"]
        rows.append(
            "<tr style='background:#eee;'><th>Time</th><th>Action</th>"
            "<th>Decision</th><th>By</th><th>Latency</th></tr>"
        )
        for h in reversed(history):
            dt = datetime.fromtimestamp(h.decided_at).strftime("%H:%M:%S")
            decision_color = "#4CAF50" if h.decision == ApprovalStatus.APPROVED else "#F44336"
            rows.append(
                f"<tr><td>{dt}</td>"
                f"<td>{h.request.action[:40]}</td>"
                f"<td style='color:{decision_color};font-weight:bold;'>"
                f"{h.decision.value}</td>"
                f"<td>{h.decided_by}</td>"
                f"<td>{h.decided_at - h.request.created_at:.1f}s</td></tr>"
            )
        rows.append("</table>")
        return "".join(rows)

    def _render_policy_editor(self) -> str:
        """渲染策略编辑器（占位，可扩展为交互式表单）。"""
        return """
        <div style="padding:16px;">
        <h3>Approval Policy</h3>
        <p>Configure auto-approval thresholds by risk level:</p>
        <ul>
        <li><b>Safe/Low:</b> Auto-approve</li>
        <li><b>Medium:</b> Ask if confidence &lt; 90%</li>
        <li><b>High:</b> Always ask</li>
        <li><b>Critical:</b> Always ask + require 2FA</li>
        </ul>
        <p><i>Interactive policy editor coming in v1.14.3</i></p>
        </div>
        """

    @property
    def queue(self) -> ApprovalQueue:
        return self._queue


# ── Agent Integration Bridge ────────────────


class HITLUIBridge:
    """连接 Agent HITL 引擎与 Gradio UI 的桥梁。

    在 Agent loop 中使用:
        bridge = HITLUIBridge(queue, agent_id)
        bridge.send_approval_request(action="Delete file X", risk_level="high")
        # UI 弹出审批卡片，Agent 在此阻塞等待结果
        approved = await bridge.wait_for_decision(timeout=60)
    """

    def __init__(
        self,
        approval_queue: ApprovalQueue,
        agent_id: str = "",
        agent_name: str = "",
    ):
        self._queue = approval_queue
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._decision_events: dict[str, asyncio.Event] = {}
        self._decision_results: dict[str, tuple[bool, str]] = {}

    async def send_approval_request(
        self,
        action: str,
        details: str = "",
        risk_level: str = "medium",
        source_file: str = "",
        timeout: float = 300.0,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """发送审批请求到 UI，阻塞等待用户决定。

        Returns:
            (approved: bool, reason: str)
        """
        event = asyncio.Event()
        request_id = f"apr-{uuid.uuid4().hex[:8]}"
        self._decision_events[request_id] = event

        def on_decision(approved: bool, reason: str) -> None:
            self._decision_results[request_id] = (approved, reason)
            event.set()

        request = ApprovalRequestUI(
            request_id=request_id,
            agent_name=self.agent_name,
            action=action,
            details=details,
            risk_level=RiskLevelUI(risk_level),
            expires_at=time.time() + timeout,
            source_file=source_file,
            metadata=metadata or {},
            on_decision=on_decision,
        )

        self._queue.submit(request)

        # 等待用户决定或超时
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            result = self._decision_results.pop(request_id, (False, "timeout"))
            self._decision_events.pop(request_id, None)
            return result
        except TimeoutError:
            self._queue.decide(request_id, False, "timeout")
            self._decision_events.pop(request_id, None)
            return (False, "timeout")


# ── Quick Launch ────────────────────────────


def create_hitl_dashboard(
    port: int = 7860,
    theme: str = "soft",
    share: bool = False,
) -> tuple[ApprovalDashboard, ApprovalQueue]:
    """一键创建并启动 HITL 审批面板。

    Usage:
        dashboard, queue = create_hitl_dashboard(port=7860)
        # Agent 代码中:
        bridge = HITLUIBridge(queue, agent_name="FileAgent")
        approved, reason = await bridge.send_approval_request(
            action="Delete 50 files in /tmp/",
            risk_level="high",
        )
    """
    queue = ApprovalQueue()
    dashboard = ApprovalDashboard(
        approval_queue=queue,
        port=port,
        theme=theme,
        auto_launch=True,
    )

    # 在后台线程启动 Gradio
    thread = threading.Thread(
        target=dashboard.launch,
        kwargs={"share": share},
        daemon=True,
    )
    thread.start()

    return dashboard, queue
