"""
AgentOS v1.2.2 — A2A (Agent-to-Agent) 协议实现。

基因来源: Google A2A Protocol (agent-to-agent-protocol.google.com)

A2A 协议核心概念:
- Task: 异步工作单元，带状态机 (SUBMITTED→WORKING→COMPLETED/FAILED/CANCELLED)
- Message: 多模态消息，支持 text/file/data parts
- Artifact: 任务产生的输出物，带 MIME 类型
- Handoff: Agent 间任务移交
- Session: 多轮对话上下文

协议层:
- REST: GET/POST /tasks, /tasks/{id}
- Future: WebSocket 推送 (v1.3+)
"""

from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ── 基础枚举 ────────────────────────────────────

class TaskState(str, Enum):

    """A2A 任务状态。"""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PartType(str, Enum):

    """A2A 内容片段类型。"""

    TEXT = "text"
    FILE = "file"
    DATA = "data"


class MessageRole(str, Enum):

    """A2A 消息角色。"""

    USER = "user"
    AGENT = "agent"


# ── Message Parts ──────────────────────────────

@dataclass
class TextPart:
    """文本消息片段。"""
    text: str
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": PartType.TEXT.value, "text": self.text, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "TextPart":
        return cls(text=d.get("text", ""), meta=d.get("meta", {}))


@dataclass
class FilePart:
    """文件引用消息片段。"""
    url: str = ""
    filename: str = ""
    mime_type: str = "application/octet-stream"
    size: int = 0
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": PartType.FILE.value,
            "url": self.url,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": self.size,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilePart":
        return cls(
            url=d.get("url", ""),
            filename=d.get("filename", ""),
            mime_type=d.get("mime_type", "application/octet-stream"),
            size=d.get("size", 0),
            meta=d.get("meta", {}),
        )


@dataclass
class DataPart:
    """结构化数据消息片段。"""
    data: Dict[str, Any] = field(default_factory=dict)
    schema_uri: str = ""
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": PartType.DATA.value,
            "data": self.data,
            "schema_uri": self.schema_uri,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DataPart":
        return cls(
            data=d.get("data", {}),
            schema_uri=d.get("schema_uri", ""),
            meta=d.get("meta", {}),
        )


def part_from_dict(d: dict):
    """从字典反序列化任意 Part。"""
    ptype = d.get("type", "")
    if ptype == PartType.TEXT.value:
        return TextPart.from_dict(d)
    elif ptype == PartType.FILE.value:
        return FilePart.from_dict(d)
    elif ptype == PartType.DATA.value:
        return DataPart.from_dict(d)
    raise ValueError(f"Unknown part type: {ptype}")


# ── A2A Artifact ───────────────────────────────

@dataclass
class A2AArtifact:
    """任务产出物。
    可以是内联数据 (blob) 或外部引用 (url)。
    """
    name: str
    mime_type: str = "application/octet-stream"
    blob: Optional[bytes] = None
    url: str = ""
    size: int = 0
    description: str = ""
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "description": self.description,
            "meta": self.meta,
        }
        if self.url:
            d["url"] = self.url
        if self.blob:
            import base64
            d["blob_base64"] = base64.b64encode(self.blob).decode("ascii")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "A2AArtifact":
        artifact = cls(
            name=d.get("name", ""),
            mime_type=d.get("mime_type", "application/octet-stream"),
            url=d.get("url", ""),
            size=d.get("size", 0),
            description=d.get("description", ""),
            meta=d.get("meta", {}),
        )
        if "blob_base64" in d:
            import base64
            artifact.blob = base64.b64decode(d["blob_base64"])
        return artifact


# ── A2A Message ────────────────────────────────

@dataclass
class A2AMessage:
    """多模态消息。"""
    role: MessageRole = MessageRole.USER
    parts: list = field(default_factory=list)  # List[TextPart|FilePart|DataPart]
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role.value,
            "parts": [p.to_dict() for p in self.parts],
            "timestamp": self.timestamp,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "A2AMessage":
        role = MessageRole(d.get("role", "user"))
        parts = [part_from_dict(p) for p in d.get("parts", [])]
        return cls(
            message_id=d.get("message_id", f"msg-{uuid.uuid4().hex[:8]}"),
            role=role,
            parts=parts,
            timestamp=d.get("timestamp", time.time()),
            meta=d.get("meta", {}),
        )

    @classmethod
    def user_text(cls, text: str) -> "A2AMessage":
        return cls(role=MessageRole.USER, parts=[TextPart(text=text)])

    @classmethod
    def agent_text(cls, text: str) -> "A2AMessage":
        return cls(role=MessageRole.AGENT, parts=[TextPart(text=text)])

    def get_text(self) -> str:
        """提取所有 text parts 拼接。"""
        return " ".join(p.text for p in self.parts if isinstance(p, TextPart))


# ── A2A Task ───────────────────────────────────

@dataclass
class A2ATask:
    """A2A 异步任务。

    状态机: SUBMITTED → WORKING → COMPLETED / FAILED / CANCELLED
    """
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    state: TaskState = TaskState.SUBMITTED
    input: A2AMessage | None = None
    output: A2AMessage | None = None
    artifacts: List[A2AArtifact] = field(default_factory=list)
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    _created: float = field(default_factory=time.time)
    _updated: float = field(default_factory=time.time)
    _state_history: List[tuple] = field(default_factory=list)  # [(state, timestamp)]

    def start_working(self) -> None:
        """SUBMITTED → WORKING"""
        if self.state != TaskState.SUBMITTED:
            raise ValueError(f"Cannot start from state {self.state}")
        self._transition(TaskState.WORKING)

    def complete(self, output: A2AMessage | None = None) -> None:
        """WORKING → COMPLETED"""
        if self.state != TaskState.WORKING:
            raise ValueError(f"Cannot complete from state {self.state}")
        self.output = output
        self.error = None
        self._transition(TaskState.COMPLETED)

    def fail(self, error: str) -> None:
        """任何状态 → FAILED"""
        self.error = error
        self._transition(TaskState.FAILED)

    def cancel(self) -> None:
        """SUBMITTED/WORKING → CANCELLED"""
        if self.state not in (TaskState.SUBMITTED, TaskState.WORKING):
            raise ValueError(f"Cannot cancel from state {self.state}")
        self._transition(TaskState.CANCELLED)

    def add_artifact(self, artifact: A2AArtifact) -> None:
        self.artifacts.append(artifact)

    def is_terminal(self) -> bool:
        return self.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)

    def _transition(self, new_state: TaskState) -> None:
        self._state_history.append((self.state, self._updated))
        self.state = new_state
        self._updated = time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "input": self.input.to_dict() if self.input else None,
            "output": self.output.to_dict() if self.output else None,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "error": self.error,
            "meta": self.meta,
            "created": self._created,
            "updated": self._updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "A2ATask":
        task = cls(
            task_id=d.get("task_id", f"task-{uuid.uuid4().hex[:8]}"),
            state=TaskState(d.get("state", "submitted")),
            error=d.get("error"),
            meta=d.get("meta", {}),
            _created=d.get("created", time.time()),
            _updated=d.get("updated", time.time()),
        )
        if d.get("input"):
            task.input = A2AMessage.from_dict(d["input"])
        if d.get("output"):
            task.output = A2AMessage.from_dict(d["output"])
        task.artifacts = [A2AArtifact.from_dict(a) for a in d.get("artifacts", [])]
        return task

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "A2ATask":
        return cls.from_dict(json.loads(json_str))


# ── A2A Handoff ────────────────────────────────

@dataclass
class A2AHandoff:
    """Agent 间任务移交请求。"""
    handoff_id: str = field(default_factory=lambda: f"hoff-{uuid.uuid4().hex[:8]}")
    source_agent: str = ""
    target_agent: str = ""
    task: A2ATask | None = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "handoff_id": self.handoff_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "task": self.task.to_dict() if self.task else None,
            "reason": self.reason,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "A2AHandoff":
        task = None
        if d.get("task"):
            task = A2ATask.from_dict(d["task"])
        return cls(
            handoff_id=d.get("handoff_id", f"hoff-{uuid.uuid4().hex[:8]}"),
            source_agent=d.get("source_agent", ""),
            target_agent=d.get("target_agent", ""),
            task=task,
            reason=d.get("reason", ""),
            metadata=d.get("metadata", {}),
            timestamp=d.get("timestamp", time.time()),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "A2AHandoff":
        return cls.from_dict(json.loads(json_str))


# ── A2A Session ────────────────────────────────

@dataclass
class A2ASession:
    """A2A 会话上下文。"""
    session_id: str = field(default_factory=lambda: f"sess-{uuid.uuid4().hex[:8]}")
    history: List[A2AMessage] = field(default_factory=list)
    tasks: List[A2ATask] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    def add_message(self, msg: A2AMessage) -> None:
        self.history.append(msg)

    def add_task(self, task: A2ATask) -> None:
        self.tasks.append(task)

    def get_last_n_messages(self, n: int = 10) -> List[A2AMessage]:
        return self.history[-n:]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "history": [m.to_dict() for m in self.history],
            "tasks": [t.to_dict() for t in self.tasks],
            "metadata": self.metadata,
            "created": self.created,
        }


# ── A2A Client ─────────────────────────────────

class A2AClient:
    """A2A 协议客户端。

    向远程 Agent 发送任务，查询状态，获取结果。

    v1.3.13: 重试 + 认证头 + 流式订阅 + 持久化连接池。
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        auth_token: str = "",
        agent_name: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.auth_token = auth_token
        self.agent_name = agent_name
        self._client: Any = None

    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": f"AgentOS-A2A/{self.agent_name}" if self.agent_name else "AgentOS-A2A"}
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        return h

    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._headers(),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _retry(self, coro, *args, **kwargs):
        import asyncio
        import httpx
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                return await coro(*args, **kwargs)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_backoff * (2 ** attempt))
        raise last_exc  # type: ignore

    async def send_task(self, task: A2ATask) -> A2ATask:
        """POST /tasks — 提交任务，返回带有 server 分配的 task_id 的任务。"""
        client = await self._get_client()

        async def _do():
            resp = await client.post(f"{self.base_url}/tasks", json=task.to_dict())
            resp.raise_for_status()
            return A2ATask.from_dict(resp.json())

        return await self._retry(_do)

    async def get_task(self, task_id: str) -> Optional[A2ATask]:
        """GET /tasks/{id} — 查询任务状态和结果。"""
        import httpx
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/tasks/{task_id}")
            resp.raise_for_status()
            return A2ATask.from_dict(resp.json())
        except Exception:
            return None

    async def cancel_task(self, task_id: str) -> bool:
        """DELETE /tasks/{id} — 取消任务。"""
        import httpx
        client = await self._get_client()
        try:
            resp = await client.delete(f"{self.base_url}/tasks/{task_id}")
            return resp.status_code < 400
        except Exception:
            return False

    async def handoff(self, handoff: A2AHandoff) -> bool:
        """POST /handoff — 移交任务到另一个 Agent。"""
        client = await self._get_client()
        try:
            resp = await client.post(f"{self.base_url}/handoff", json=handoff.to_dict())
            return resp.status_code < 400
        except Exception:
            return False

    async def wait_for_completion(
        self,
        task_id: str,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> A2ATask:
        """轮询等待任务完成。"""
        import asyncio
        elapsed = 0.0
        while elapsed < max_wait:
            task = await self.get_task(task_id)
            if task is None:
                raise RuntimeError(f"Task {task_id} not found")
            if task.is_terminal():
                return task
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"Task {task_id} did not complete within {max_wait}s")

    async def send_and_wait_for_reply(
        self,
        text: str,
        target_agent: str = "",
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> str:
        """便捷方法：发送文本任务并等待回复文本。"""
        task = new_task(text, target_agent=target_agent)
        task = await self.send_task(task)
        result = await self.wait_for_completion(task.task_id, poll_interval, max_wait)
        if result.output:
            return result.output.get_text()
        if result.error:
            return f"[Error] {result.error}"
        return ""

    async def subscribe_task_stream(
        self,
        task_id: str,
        on_event: Callable[[dict], Any] | None = None,
    ) -> None:
        """SSE streaming subscribe: 连接到服务端 SSE 端点监听任务事件。"""
        import httpx
        client = await self._get_client()
        async with client.stream("GET", f"{self.base_url}/tasks/{task_id}/stream") as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    msg, buffer = buffer.split("\n\n", 1)
                    event_data: dict[str, str] = {}
                    for line in msg.split("\n"):
                        if line.startswith("event: "):
                            event_data["event"] = line[7:]
                        elif line.startswith("data: "):
                            event_data["data"] = line[6:]
                    if on_event:
                        on_event(event_data)


# ── A2A Server ─────────────────────────────────

class A2AServer:
    """A2A 协议服务端。

    接收并处理 Agent 间任务请求。

    使用方式:
        server = A2AServer()
        server.register_handler("my-agent", my_handler)
        # 集成到 FastAPI:
        app = FastAPI()
        server.mount_routes(app)
    """

    def __init__(
        self,
        task_store=None,
        stream_manager=None,
        require_auth: bool = False,
        auth_tokens: List[str] | None = None,
    ):
        self._handlers: Dict[str, Callable] = {}
        self._task_store = task_store
        self._stream_manager = stream_manager
        self.require_auth = require_auth
        self.auth_tokens: set[str] = set(auth_tokens or [])
        self._default_store_created = False

    def _ensure_store(self):
        if self._task_store is None:
            from agentos.protocols.a2a_store import InMemoryTaskStore
            self._task_store = InMemoryTaskStore()
            self._default_store_created = True

    @property
    def task_store(self):
        self._ensure_store()
        return self._task_store

    def register_handler(
        self,
        agent_name: str,
        handler: Callable,
    ) -> None:
        """注册 Agent 处理函数。

        handler 签名: async def handler(task: A2ATask) -> A2AMessage
        """
        self._handlers[agent_name] = handler

    async def process_task(self, body: dict, auth_token: str = "") -> dict:
        """处理传入任务：解析、执行 handler、返回。"""
        self._ensure_store()

        if self.require_auth and auth_token not in self.auth_tokens:
            task = A2ATask.from_dict(body)
            task.fail("Unauthorized: invalid or missing A2A auth token")
            self._task_store.save_task(task)
            return task.to_dict()

        task = A2ATask.from_dict(body)
        old_state = task.state
        self._task_store.save_task(task)

        target = body.get("meta", {}).get("target_agent", "")
        handler = self._handlers.get(target)

        if not handler and target:
            task.fail(f"No handler for agent '{target}'")
        elif not handler:
            task.fail("No target agent specified in meta")
        else:
            try:
                task.start_working()
                if self._stream_manager:
                    await self._stream_manager.notify_state_change(task, old_state)
                result = handler(task)
                import inspect
                if inspect.isawaitable(result):
                    output = await result
                else:
                    output = result
                task.complete(output)
            except Exception as e:
                task.fail(str(e))

        if self._stream_manager:
            await self._stream_manager.notify_state_change(task, old_state)
        self._task_store.save_task(task)
        return task.to_dict()

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        return self.task_store.get_task(task_id)

    def list_tasks(self, state: TaskState | None = None) -> list[A2ATask]:
        return self.task_store.list_tasks(state=state)

    def cleanup_old(self, max_age_seconds: float = 3600.0) -> int:
        return self.task_store.cleanup_terminal(max_age_seconds)

    # ── FastAPI 路由构建器 ─────────────────────

    def mount_routes(self, app, prefix: str = "") -> None:
        """将 A2A 标准路由挂载到 FastAPI/Starlette app 上。

        路由:
            POST   {prefix}/tasks           — 创建任务
            GET    {prefix}/tasks           — 列出任务
            GET    {prefix}/tasks/{id}      — 获取任务
            DELETE {prefix}/tasks/{id}      — 取消任务
            GET    {prefix}/tasks/{id}/stream — SSE 事件流
            POST   {prefix}/handoff         — 任务移交
        """
        try:
            from fastapi import FastAPI, Request, HTTPException
            from starlette.responses import StreamingResponse
        except ImportError:
            raise ImportError("FastAPI and Starlette are required for mount_routes()")

        server = self

        @app.post(f"{prefix}/tasks")
        async def create_task(request: Request):
            body = await request.json()
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            return await server.process_task(body, auth_token=token)

        @app.get(f"{prefix}/tasks")
        async def list_tasks_endpoint(state: str = ""):
            task_state = TaskState(state) if state else None
            tasks = server.list_tasks(state=task_state)
            return [t.to_dict() for t in tasks]

        @app.get(f"{prefix}/tasks/{{task_id}}")
        async def get_task_endpoint(task_id: str):
            task = server.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task.to_dict()

        @app.delete(f"{prefix}/tasks/{{task_id}}")
        async def cancel_task_endpoint(task_id: str):
            task = server.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            if task.is_terminal():
                raise HTTPException(status_code=400, detail="Task already terminal")
            task.cancel()
            server._task_store.save_task(task)
            return {"status": "cancelled", "task_id": task_id}

        @app.get(f"{prefix}/tasks/{{task_id}}/stream")
        async def stream_task(task_id: str):
            if server._stream_manager is None:
                raise HTTPException(status_code=501, detail="Streaming not enabled")

            async def event_generator():
                stream = server._stream_manager
                session = stream.get_session(task_id)
                if session is None:
                    yield f"event: error\ndata: {{\"error\": \"Session not found\"}}\n\n"
                    return
                sub = session.subscribe()
                try:
                    async for evt in session.iter_events(sub):
                        yield session.to_sse(evt)
                except Exception:
                    pass

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.post(f"{prefix}/handoff")
        async def handoff_endpoint(request: Request):
            body = await request.json()
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if server.require_auth and token not in server.auth_tokens:
                raise HTTPException(status_code=401, detail="Unauthorized")
            handoff = A2AHandoff.from_dict(body)
            if handoff.task:
                server._task_store.save_task(handoff.task)
            return {"status": "received", "handoff_id": handoff.handoff_id}


# ── 便捷函数 ───────────────────────────────────

def new_task(text: str, target_agent: str = "", **meta) -> A2ATask:
    """快速创建一个文本任务。"""
    return A2ATask(
        input=A2AMessage.user_text(text),
        meta={"target_agent": target_agent, **meta},
    )


def new_handoff(
    task: A2ATask,
    source: str,
    target: str,
    reason: str = "",
) -> A2AHandoff:
    """快速创建 Handoff。"""
    return A2AHandoff(
        source_agent=source,
        target_agent=target,
        task=task,
        reason=reason,
    )
