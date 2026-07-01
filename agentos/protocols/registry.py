"""
AgentOS v1.14.0 — A2A Agent Registry（服务发现）。

Agent 注册中心实现:
- 服务注册/注销/心跳
- 能力广播 (Agent Card)
- 服务发现 (按能力/角色查询)
- 健康检查自动摘除
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set


# ── Agent Card ───────────────────────────────


@dataclass
class DiscoveryCapability:
    """服务发现用 Agent 能力描述。

    不同于 protocols.contracts.AgentCapability（面向合约），
    本类面向注册中心发现和匹配。
    """
    name: str                       # 能力名称 (e.g. "code_review", "pdf_parsing")
    description: str = ""
    version: str = "1.0.0"
    input_schema: Optional[Dict[str, Any]] = None
    performance: Dict[str, Any] = field(default_factory=dict)  # 性能指标

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": self.input_schema,
            "performance": self.performance,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoveryCapability":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            version=d.get("version", "1.0.0"),
            input_schema=d.get("input_schema"),
            performance=d.get("performance", {}),
        )


@dataclass
class DiscoveryCard:
    """Agent 发现名片 — 向注册中心声明的自身信息。

    符合 Google A2A AgentCard 规范。
    不同于 protocols.agent_card.AgentCard（面向本地广播），
    本类面向远程注册中心的服务发现。
    """

    agent_id: str
    name: str
    description: str = ""
    url: str = ""                      # Agent 的服务端点
    version: str = "1.0.0"
    capabilities: List[DiscoveryCapability] = field(default_factory=list)
    provider: Dict[str, Any] = field(default_factory=dict)  # 组织/团队信息
    default_input_modes: List[str] = field(default_factory=lambda: ["text"])
    default_output_modes: List[str] = field(default_factory=lambda: ["text"])
    skills: List[Dict[str, Any]] = field(default_factory=list)
    supports_streaming: bool = False
    supports_handoff: bool = True
    max_context_length: int = 128000
    preferred_model: str = ""
    service_tier: str = "standard"      # standard | premium | enterprise
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "provider": self.provider,
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": self.skills,
            "supportsStreaming": self.supports_streaming,
            "supportsHandoff": self.supports_handoff,
            "maxContextLength": self.max_context_length,
            "preferredModel": self.preferred_model,
            "serviceTier": self.service_tier,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoveryCard":
        return cls(
            agent_id=d.get("agent_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            url=d.get("url", ""),
            version=d.get("version", "1.0.0"),
            capabilities=[
                DiscoveryCapability.from_dict(c)
                for c in d.get("capabilities", [])
            ],
            provider=d.get("provider", {}),
            default_input_modes=d.get("defaultInputModes", ["text"]),
            default_output_modes=d.get("defaultOutputModes", ["text"]),
            skills=d.get("skills", []),
            supports_streaming=d.get("supportsStreaming", False),
            supports_handoff=d.get("supportsHandoff", True),
            max_context_length=d.get("maxContextLength", 128000),
            preferred_model=d.get("preferredModel", ""),
            service_tier=d.get("serviceTier", "standard"),
            metadata=d.get("metadata", {}),
        )

    def has_capability(self, cap_name: str) -> bool:
        """检查是否具备某项能力。"""
        return any(c.name == cap_name for c in self.capabilities)


# ── Registry Entry ──────────────────────────


class AgentStatus(str, Enum):
    """Agent 运行状态。"""
    ONLINE = "online"
    BUSY = "busy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass
class RegistryEntry:
    """注册中心中的单条 Agent 记录。"""

    card: DiscoveryCard
    status: AgentStatus = AgentStatus.ONLINE
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    load: float = 0.0              # 0.0~1.0 负载
    task_count: int = 0            # 已完成任务数
    error_count: int = 0
    avg_response_ms: float = 0.0
    tags: List[str] = field(default_factory=list)
    endpoint_health: Dict[str, Any] = field(default_factory=dict)

    def is_healthy(self, heartbeat_timeout: float = 30.0) -> bool:
        """心跳是否正常。"""
        return (time.time() - self.last_heartbeat) < heartbeat_timeout

    @property
    def uptime_seconds(self) -> float:
        """注册后的运行时长。"""
        return time.time() - self.registered_at


# ── Agent Registry ──────────────────────────


class AgentRegistry:
    """A2A Agent 注册中心。

    功能:
    - register: 注册 Agent（带心跳保活）
    - discover: 按能力/角色/标签发现 Agent
    - health_check: 自动摘除失联 Agent
    - subscribe: 订阅注册事件

    Usage:
        registry = AgentRegistry(heartbeat_timeout=30)
        registry.register(agent_card)

        # 发现能处理 code_review 的 Agent
        agents = registry.discover(capability="code_review")

        # 按标签查找
        agents = registry.discover(tags=["production", "high-priority"])
    """

    def __init__(
        self,
        heartbeat_timeout: float = 30.0,
        health_check_interval: float = 10.0,
        auto_cleanup: bool = True,
    ):
        self._entries: Dict[str, RegistryEntry] = {}
        self._capability_index: Dict[str, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._role_index: Dict[str, Set[str]] = {}
        self.heartbeat_timeout = heartbeat_timeout
        self.health_check_interval = health_check_interval
        self.auto_cleanup = auto_cleanup

        # Event subscribers
        self._subscribers: Dict[str, List[Callable]] = {
            "register": [],
            "deregister": [],
            "status_change": [],
            "heartbeat": [],
        }

        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ─────────────────────────────

    async def start(self) -> None:
        """启动注册中心（开始健康检查循环）。"""
        if self._running:
            return
        self._running = True
        if self.auto_cleanup:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self) -> None:
        """停止注册中心。"""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    async def _health_check_loop(self) -> None:
        """后台健康检查循环。"""
        while self._running:
            try:
                self._check_all_health()
            except Exception:
                pass
            await asyncio.sleep(self.health_check_interval)

    def _check_all_health(self) -> None:
        """健康检查：摘除失联 Agent。"""
        to_remove = []
        for agent_id, entry in list(self._entries.items()):
            if entry.status != AgentStatus.OFFLINE and not entry.is_healthy(
                self.heartbeat_timeout
            ):
                self._update_status(agent_id, AgentStatus.OFFLINE)
                to_remove.append(agent_id)

        for agent_id in to_remove:
            self._cleanup_indices(agent_id)

    # ── Registration ─────────────────────────

    def register(
        self,
        card: DiscoveryCard,
        tags: Optional[List[str]] = None,
    ) -> str:
        """注册一个 Agent。

        Args:
            card: Agent 名片
            tags: 自定义标签

        Returns:
            agent_id
        """
        agent_id = card.agent_id
        now = time.time()

        if agent_id in self._entries:
            # Re-registration: update card, refresh heartbeat
            entry = self._entries[agent_id]
            old_status = entry.status
            entry.card = card
            entry.last_heartbeat = now
            entry.tags = tags or entry.tags
            if old_status == AgentStatus.OFFLINE:
                self._update_status(agent_id, AgentStatus.ONLINE)
            return agent_id

        entry = RegistryEntry(
            card=card,
            status=AgentStatus.ONLINE,
            registered_at=now,
            last_heartbeat=now,
            tags=tags or [],
        )
        self._entries[agent_id] = entry
        self._build_indices(agent_id, card, tags or [])
        self._emit("register", {"agent_id": agent_id, "card": card.to_dict()})
        return agent_id

    def deregister(self, agent_id: str) -> bool:
        """注销一个 Agent。"""
        if agent_id not in self._entries:
            return False
        entry = self._entries.pop(agent_id)
        self._cleanup_indices(agent_id)
        self._emit("deregister", {"agent_id": agent_id, "card": entry.card.to_dict()})
        return True

    def heartbeat(self, agent_id: str, load: Optional[float] = None) -> bool:
        """Agent 心跳上报。

        Args:
            agent_id: Agent ID
            load: 当前负载 0.0~1.0

        Returns:
            是否成功
        """
        if agent_id not in self._entries:
            return False
        entry = self._entries[agent_id]
        entry.last_heartbeat = time.time()
        if load is not None:
            entry.load = max(0.0, min(1.0, load))
        if entry.status == AgentStatus.OFFLINE:
            self._update_status(agent_id, AgentStatus.ONLINE)
        self._emit("heartbeat", {"agent_id": agent_id, "load": entry.load})
        return True

    def update_stats(
        self,
        agent_id: str,
        task_count: Optional[int] = None,
        error_count: Optional[int] = None,
        avg_response_ms: Optional[float] = None,
    ) -> bool:
        """更新 Agent 统计信息。"""
        if agent_id not in self._entries:
            return False
        entry = self._entries[agent_id]
        if task_count is not None:
            entry.task_count = task_count
        if error_count is not None:
            entry.error_count = error_count
        if avg_response_ms is not None:
            entry.avg_response_ms = avg_response_ms
        return True

    # ── Discovery ────────────────────────────

    def discover(
        self,
        capability: Optional[str] = None,
        tags: Optional[List[str]] = None,
        role: Optional[str] = None,
        status: Optional[AgentStatus] = None,
        service_tier: Optional[str] = None,
        supports_streaming: Optional[bool] = None,
        min_health: bool = True,
        limit: int = 50,
    ) -> List[RegistryEntry]:
        """服务发现：按条件筛选 Agent。

        Args:
            capability: 按能力名称筛选
            tags: 按标签筛选（AND 逻辑）
            role: 按角色筛选
            status: 按状态筛选
            service_tier: 按服务等级筛选
            supports_streaming: 是否支持流式
            min_health: 仅返回心跳正常的 Agent
            limit: 最大返回数

        Returns:
            匹配的 RegistryEntry 列表
        """
        candidates: Set[str] = set(self._entries.keys())

        # Capability filter
        if capability:
            cap_agents = self._capability_index.get(capability, set())
            candidates &= cap_agents

        # Tag filter (AND)
        if tags:
            for tag in tags:
                tag_agents = self._tag_index.get(tag, set())
                candidates &= tag_agents

        # Role filter
        if role:
            role_agents = self._role_index.get(role, set())
            candidates &= role_agents

        # Collect results
        results = []
        for agent_id in candidates:
            entry = self._entries[agent_id]

            # Status filter
            if status and entry.status != status:
                continue

            # Health filter
            if min_health and not entry.is_healthy(self.heartbeat_timeout):
                continue

            # Service tier filter
            if service_tier and entry.card.service_tier != service_tier:
                continue

            # Streaming filter
            if supports_streaming is not None and \
               entry.card.supports_streaming != supports_streaming:
                continue

            results.append(entry)

        # Sort: online first, then by load (least loaded first)
        status_order = {
            AgentStatus.ONLINE: 0,
            AgentStatus.BUSY: 1,
            AgentStatus.DEGRADED: 2,
            AgentStatus.OFFLINE: 3,
        }
        results.sort(key=lambda e: (status_order.get(e.status, 9), e.load))

        return results[:limit]

    def discover_one(
        self,
        capability: Optional[str] = None,
        load_balanced: bool = True,
        **kwargs,
    ) -> Optional[RegistryEntry]:
        """发现单个最优 Agent。

        Args:
            capability: 按能力筛选
            load_balanced: 是否负载均衡（选负载最低的）
        """
        results = self.discover(
            capability=capability,
            status=AgentStatus.ONLINE,
            min_health=True,
            limit=10,
            **kwargs,
        )
        if not results:
            return None
        if load_balanced:
            # Already sorted by load ascending
            return results[0]
        return results[0]

    def get_agent(self, agent_id: str) -> Optional[RegistryEntry]:
        """按 ID 获取 Agent。"""
        return self._entries.get(agent_id)

    def list_all(self, include_offline: bool = False) -> List[RegistryEntry]:
        """列出所有 Agent。"""
        entries = list(self._entries.values())
        if not include_offline:
            entries = [
                e for e in entries
                if e.status != AgentStatus.OFFLINE
                or e.is_healthy(self.heartbeat_timeout)
            ]
        return entries

    # ── Stats ─────────────────────────────────

    @property
    def total_agents(self) -> int:
        """已注册的 Agent 总数。"""
        return len(self._entries)

    @property
    def online_count(self) -> int:
        """在线 Agent 数。"""
        return sum(
            1 for e in self._entries.values()
            if e.status == AgentStatus.ONLINE and e.is_healthy(self.heartbeat_timeout)
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取注册中心统计。"""
        online = 0
        busy = 0
        degraded = 0
        offline = 0
        for e in self._entries.values():
            if not e.is_healthy(self.heartbeat_timeout):
                offline += 1
            elif e.status == AgentStatus.ONLINE:
                online += 1
            elif e.status == AgentStatus.BUSY:
                busy += 1
            elif e.status == AgentStatus.DEGRADED:
                degraded += 1

        return {
            "total": self.total_agents,
            "online": online,
            "busy": busy,
            "degraded": degraded,
            "offline": offline,
            "capabilities": list(self._capability_index.keys()),
            "tags": list(self._tag_index.keys()),
            "roles": list(self._role_index.keys()),
        }

    # ── Events ────────────────────────────────

    def subscribe(
        self,
        event: str,
        callback: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """订阅注册事件。

        Args:
            event: 'register' | 'deregister' | 'status_change' | 'heartbeat'
            callback: 回调函数，接收事件 dict
        """
        if event in self._subscribers:
            self._subscribers[event].append(callback)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """触发事件。"""
        for cb in self._subscribers.get(event, []):
            try:
                cb(data)
            except Exception:
                pass

    # ── Internal Helpers ─────────────────────

    def _update_status(self, agent_id: str, new_status: AgentStatus) -> None:
        """更新 Agent 状态并触发事件。"""
        if agent_id in self._entries:
            old_status = self._entries[agent_id].status
            self._entries[agent_id].status = new_status
            if old_status != new_status:
                self._emit("status_change", {
                    "agent_id": agent_id,
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                })

    def _build_indices(
        self,
        agent_id: str,
        card: DiscoveryCard,
        tags: List[str],
    ) -> None:
        """构建反向索引。"""
        # Capability index
        for cap in card.capabilities:
            if cap.name not in self._capability_index:
                self._capability_index[cap.name] = set()
            self._capability_index[cap.name].add(agent_id)

        # Tag index
        for tag in tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(agent_id)

        # Role index (from provider)
        role = card.provider.get("role", "")
        if role:
            if role not in self._role_index:
                self._role_index[role] = set()
            self._role_index[role].add(agent_id)

    def _cleanup_indices(self, agent_id: str) -> None:
        """从所有索引中移除 Agent。"""
        for cap_set in self._capability_index.values():
            cap_set.discard(agent_id)
        for tag_set in self._tag_index.values():
            tag_set.discard(agent_id)
        for role_set in self._role_index.values():
            role_set.discard(agent_id)


# ── A2A Registry Bridge ─────────────────────


class A2ARegistryBridge:
    """A2A Registry + A2A Client 桥接。

    自动从 Registry 发现 Agent 并创建 A2A Client。

    Usage:
        bridge = A2ARegistryBridge(registry)
        client = await bridge.get_client(capability="code_review")
        result = await client.send_and_wait_for_reply("Review this code...")
    """

    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._clients: Dict[str, Any] = {}  # agent_id -> A2AClient

    async def get_client(
        self,
        capability: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """获取已发现的 Agent 的 A2A Client。

        Args:
            capability: 按能力发现
            agent_id: 直接指定 Agent ID
        """
        from agentos.protocols.a2a import A2AClient

        if agent_id and agent_id in self._clients:
            return self._clients[agent_id]

        entry = None
        if agent_id:
            entry = self._registry.get_agent(agent_id)
        else:
            entry = self._registry.discover_one(capability=capability, **kwargs)

        if not entry:
            raise RuntimeError(
                f"No available agent found for capability={capability}"
            )

        client = A2AClient(
            base_url=entry.card.url,
            agent_name=entry.card.name,
        )
        self._clients[entry.card.agent_id] = client
        return client

    async def close_all(self) -> None:
        """关闭所有 Client 连接。"""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()

    def invalidate(self, agent_id: str) -> None:
        """使某个 Agent 的缓存 Client 失效。"""
        self._clients.pop(agent_id, None)


# ── 全局单例 ─────────────────────────────────

default_registry = AgentRegistry()
