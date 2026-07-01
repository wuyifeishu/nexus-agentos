"""
WebSocket 双向流式通信 — Agent 实时交互层。

基于 websockets 库，提供 Agent 与客户端之间的全双工实时通信。
支持流式进度报告、Agent 状态广播、父子 Agent 监控、暂停/恢复/取消。

协议（JSON，双向）:

    Client → Server:
        {"type": "run",      "task": "...", "session_id": "..."}
        {"type": "cancel",   "session_id": "..."}
        {"type": "pause",    "session_id": "..."}
        {"type": "resume",   "session_id": "..."}
        {"type": "ping"}

    Server → Client:
        {"type": "token",        "text": "...", "seq": N}
        {"type": "progress",     "value": 0.5, "step": "..."}
        {"type": "tool_call",    "name": "...", "args": {...}}
        {"type": "tool_result",  "name": "...", "result": ...}
        {"type": "status",       "status": "running"|"paused"|"..."}
        {"type": "done",         "output": "...", "iterations": N}
        {"type": "error",        "message": "..."}
        {"type": "heartbeat"}
        {"type": "child_update", "agent_id": "...", "status": "..."}

使用示例::

    from agentos.api.websocket import AgentWebSocket, serve_ws

    mgr = SubAgentManager()

    async def my_run(spec, ctx):
        await ctx.report_progress(0.5, "thinking")
        return "answer", 1

    ws = AgentWebSocket(manager=mgr, run_func=my_run)
    await serve_ws(ws.handler, port=8765)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

import websockets
from websockets.server import WebSocketServerProtocol

from agentos.subagent.manager import SubAgentManager, SubAgentSpec, SubAgentResult
from agentos.subagent.parent_child import ChildContext, ChildHandle, ChildStatus


# ──────────────────────────────────────────────
# 消息协议
# ──────────────────────────────────────────────


class WSMsgType(str, Enum):
    """WebSocket 消息类型。"""
    # Client → Server
    RUN = "run"
    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"
    PING = "ping"

    # Server → Client
    TOKEN = "token"
    PROGRESS = "progress"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATUS = "status"
    DONE = "done"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    CHILD_UPDATE = "child_update"


@dataclass
class WSMessage:
    """WebSocket 消息体。"""
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: str | bytes) -> "WSMessage":
        payload = json.loads(raw if isinstance(raw, str) else raw.decode())
        return cls(
            type=payload.get("type", ""),
            data={k: v for k, v in payload.items() if k != "type"},
        )

    def serialize(self) -> str:
        return json.dumps({"type": self.type, **self.data}, ensure_ascii=False)

    # ── 工厂方法 ──────────────────────────

    @classmethod
    def token(cls, text: str, seq: int = 0) -> "WSMessage":
        return cls(WSMsgType.TOKEN, {"text": text, "seq": seq})

    @classmethod
    def progress(cls, value: float, step: str = "", agent_id: str = "") -> "WSMessage":
        return cls(WSMsgType.PROGRESS, {"value": value, "step": step, "agent_id": agent_id})

    @classmethod
    def tool_call(cls, name: str, args: dict) -> "WSMessage":
        return cls(WSMsgType.TOOL_CALL, {"name": name, "args": args})

    @classmethod
    def tool_result(cls, name: str, result: Any) -> "WSMessage":
        return cls(WSMsgType.TOOL_RESULT, {"name": name, "result": result})

    @classmethod
    def status(cls, status: str, agent_id: str = "") -> "WSMessage":
        return cls(WSMsgType.STATUS, {"status": status, "agent_id": agent_id})

    @classmethod
    def done(cls, output: str, iterations: int = 0, agent_id: str = "") -> "WSMessage":
        return cls(WSMsgType.DONE, {"output": output, "iterations": iterations, "agent_id": agent_id})

    @classmethod
    def error(cls, message: str, code: str = "UNKNOWN") -> "WSMessage":
        return cls(WSMsgType.ERROR, {"message": message, "code": code})

    @classmethod
    def heartbeat(cls) -> "WSMessage":
        return cls(WSMsgType.HEARTBEAT, {"ts": time.time()})

    @classmethod
    def child_update(cls, agent_id: str, status: str, progress: float = 0, step: str = "") -> "WSMessage":
        return cls(WSMsgType.CHILD_UPDATE, {
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "step": step,
        })


# ──────────────────────────────────────────────
# 会话管理
# ──────────────────────────────────────────────


@dataclass
class WSSession:
    """单个 WebSocket 连接的会话。"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    connected_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    running_task: asyncio.Task | None = None
    running_handle: ChildHandle | None = None
    poll_task: asyncio.Task | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_busy(self) -> bool:
        return self.running_task is not None and not self.running_task.done()

    def touch(self):
        self.last_active = time.time()


# ──────────────────────────────────────────────
# WebSocket Agent 核心
# ──────────────────────────────────────────────


class AgentWebSocket:
    """Agent WebSocket 服务。

    Args:
        manager: SubAgentManager 实例
        run_func: 自定义执行函数 (spec, ctx) -> (output, iterations)
        heartbeat_interval: WebSocket 心跳间隔（秒）
        poll_interval: 子 Agent 状态轮询间隔（秒）
        max_message_size: 最大消息大小（字节）
    """

    def __init__(
        self,
        manager: SubAgentManager | None = None,
        run_func: Callable[[SubAgentSpec, ChildContext], Awaitable[tuple[str, int]]] | None = None,
        heartbeat_interval: float = 15.0,
        poll_interval: float = 0.5,
        max_message_size: int = 2 ** 20,
    ):
        self._mgr = manager or SubAgentManager()
        self._run = run_func
        self._heartbeat_interval = heartbeat_interval
        self._poll_interval = poll_interval
        self._max_message_size = max_message_size
        self._sessions: dict[str, WSSession] = {}
        self._conn_session: dict[WebSocketServerProtocol, str] = {}

    # ── 主 handler ────────────────────────

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        """单连接 handler。"""
        session = WSSession()
        self._sessions[session.session_id] = session
        self._conn_session[websocket] = session.session_id

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))

        try:
            await self._send(websocket, WSMessage.status("connected", session.session_id))

            async for raw in websocket:
                session.touch()
                try:
                    msg = WSMessage.parse(raw)
                    await self._dispatch(websocket, session, msg)
                except json.JSONDecodeError:
                    await self._send(websocket, WSMessage.error("Invalid JSON", "PARSE_ERROR"))
                except Exception as e:
                    await self._send(websocket, WSMessage.error(str(e)))

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self._cleanup_session(websocket, session)

    # ── 消息分发 ──────────────────────────

    async def _dispatch(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        handlers: dict[str, Callable] = {
            WSMsgType.RUN: self._handle_run,
            WSMsgType.CANCEL: self._handle_cancel,
            WSMsgType.PAUSE: self._handle_pause,
            WSMsgType.RESUME: self._handle_resume,
            WSMsgType.PING: self._handle_ping,
        }

        handler = handlers.get(msg.type)
        if handler:
            await handler(ws, session, msg)
        else:
            await self._send(ws, WSMessage.error(f"Unknown type: {msg.type}", "UNKNOWN_TYPE"))

    # ── run ───────────────────────────────

    async def _handle_run(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        if session.is_busy:
            await self._send(ws, WSMessage.error("Session busy", "BUSY"))
            return

        task = msg.data.get("task", "")
        if not task:
            await self._send(ws, WSMessage.error("Missing 'task'", "INVALID"))
            return

        await self._send(ws, WSMessage.status("running", session.session_id))

        session.running_task = asyncio.create_task(
            self._run_agent(session, task)
        )
        session.poll_task = asyncio.create_task(
            self._poll_agent(ws, session)
        )

        try:
            await session.running_task
        except asyncio.CancelledError:
            await self._send(ws, WSMessage.status("cancelled", session.session_id))
            return

    async def _run_agent(self, session: WSSession, task: str) -> None:
        """启动 Agent 并在完成后推送结果。"""
        async def capturing_run(spec: SubAgentSpec, ctx: ChildContext) -> tuple[str, int]:
            if self._run:
                return await self._run(spec, ctx)
            # 默认 fallback
            await ctx.report_progress(0.5, "processing")
            await ctx.report_progress(1.0, "done")
            return f"Agent received: {task}", 1

        result = await self._mgr.spawn_fork(task=task, run_func=capturing_run)
        session.running_handle = self._mgr.get_handle(result.agent_id)

        # 停止轮询
        if session.poll_task and not session.poll_task.done():
            session.poll_task.cancel()

        # 确定最终状态并发送
        if result.error:
            await self.broadcast_to_session(session, WSMessage.error(result.error))
            await self.broadcast_to_session(session, WSMessage.status("failed", result.agent_id))
        else:
            await self.broadcast_to_session(session, WSMessage.done(
                output=result.output,
                iterations=result.iterations,
                agent_id=result.agent_id,
            ))
            await self.broadcast_to_session(session, WSMessage.status("completed", result.agent_id))

    async def _poll_agent(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
    ) -> None:
        """轮询子 Agent 状态并流式推送进度。"""
        try:
            last_progress = -1.0
            last_step = ""
            while session.running_task and not session.running_task.done():
                handle = session.running_handle
                if handle is None:
                    # spawn_fork 尚未返回，检查 manager 中是否有新 agent
                    children = self._mgr.list_children()
                    if children:
                        latest = children[-1]
                        sid = latest.get("agent_id", "")
                        handle = self._mgr.get_handle(sid)
                        if handle and handle.status not in (ChildStatus.IDLE,):
                            session.running_handle = handle

                if handle:
                    cur_progress = handle.info.progress
                    cur_step = handle.info.current_step
                    if cur_progress != last_progress or cur_step != last_step:
                        await self._send(ws, WSMessage.progress(
                            value=cur_progress,
                            step=cur_step,
                            agent_id=handle.agent_id,
                        ))
                        last_progress = cur_progress
                        last_step = cur_step

                    # 推送状态变化
                    if handle.status == ChildStatus.FAILED:
                        await self._send(ws, WSMessage.error(
                            handle.info.error or "Agent failed",
                        ))
                        break
                    elif handle.status == ChildStatus.CANCELLED:
                        break

                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass

    # ── cancel / pause / resume ───────────

    async def _handle_cancel(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        if session.running_handle:
            await session.running_handle.cancel()
        if session.running_task and not session.running_task.done():
            session.running_task.cancel()
        if session.poll_task and not session.poll_task.done():
            session.poll_task.cancel()
        await self._send(ws, WSMessage.status("cancelled", session.session_id))

    async def _handle_pause(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        if session.running_handle:
            await session.running_handle.pause()
            await self._send(ws, WSMessage.status("paused", session.session_id))
        else:
            await self._send(ws, WSMessage.error("No agent to pause", "IDLE"))

    async def _handle_resume(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        if session.running_handle:
            await session.running_handle.resume()
            await self._send(ws, WSMessage.status("running", session.session_id))
        else:
            await self._send(ws, WSMessage.error("No agent to resume", "IDLE"))

    async def _handle_ping(
        self,
        ws: WebSocketServerProtocol,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        await self._send(ws, WSMessage.heartbeat())

    # ── 心跳与广播 ────────────────────────

    async def _heartbeat_loop(self, ws: WebSocketServerProtocol) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                await self._send(ws, WSMessage.heartbeat())
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    async def broadcast(self, msg: WSMessage, exclude_session: str = "") -> None:
        """向所有连接的客户端广播。"""
        dead: list[WebSocketServerProtocol] = []
        for ws, sid in list(self._conn_session.items()):
            if sid == exclude_session:
                continue
            try:
                await ws.send(msg.serialize())
            except websockets.exceptions.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            await self._cleanup_ws(ws)

    async def broadcast_to_session(
        self,
        session: WSSession,
        msg: WSMessage,
    ) -> None:
        """向指定会话对应的 WebSocket 发送消息。"""
        for ws, sid in self._conn_session.items():
            if sid == session.session_id:
                try:
                    await ws.send(msg.serialize())
                except websockets.exceptions.ConnectionClosed:
                    pass
                return

    async def broadcast_child_status(self) -> None:
        """广播所有子 Agent 状态。"""
        children = self._mgr.list_children()
        for child in children:
            await self.broadcast(WSMessage.child_update(
                agent_id=child.get("agent_id", ""),
                status=child.get("status", "unknown"),
                progress=child.get("progress", 0),
                step=child.get("current_step", ""),
            ))

    # ── 辅助 ──────────────────────────────

    async def _send(self, ws: WebSocketServerProtocol, msg: WSMessage) -> None:
        try:
            await ws.send(msg.serialize())
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _cleanup_session(
        self, ws: WebSocketServerProtocol, session: WSSession
    ) -> None:
        if session.running_task and not session.running_task.done():
            session.running_task.cancel()
        if session.poll_task and not session.poll_task.done():
            session.poll_task.cancel()
        self._conn_session.pop(ws, None)
        self._sessions.pop(session.session_id, None)

    async def _cleanup_ws(self, ws: WebSocketServerProtocol) -> None:
        sid = self._conn_session.pop(ws, None)
        if sid:
            session = self._sessions.pop(sid, None)
            if session:
                if session.running_task and not session.running_task.done():
                    session.running_task.cancel()
                if session.poll_task and not session.poll_task.done():
                    session.poll_task.cancel()

    # ── 属性 ──────────────────────────────

    @property
    def manager(self) -> SubAgentManager:
        return self._mgr

    @property
    def active_connections(self) -> int:
        return len(self._conn_session)

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)


# ──────────────────────────────────────────────
# 便捷启动
# ──────────────────────────────────────────────


async def serve_ws(
    ws_handler,
    host: str = "0.0.0.0",
    port: int = 8765,
    **kwargs,
):
    """启动 WebSocket 服务。

    Args:
        ws_handler: AgentWebSocket.handler 或兼容的 coroutine handler
        host: 监听地址
        port: 监听端口

    Example::

        mgr = SubAgentManager()
        ws = AgentWebSocket(manager=mgr)
        await serve_ws(ws.handler, port=8765)
    """
    async with websockets.serve(
        ws_handler,
        host=host,
        port=port,
        max_size=kwargs.pop("max_size", 2 ** 20),
        ping_interval=kwargs.pop("ping_interval", 20),
        **kwargs,
    ):
        print(f"WebSocket server listening on ws://{host}:{port}")
        await asyncio.Future()  # run forever
