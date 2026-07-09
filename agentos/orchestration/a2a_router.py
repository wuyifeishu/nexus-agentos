"""
A2A协议路由 — 跨框架Agent互操作。
基因来源: Google ADK A2A Protocol
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """任务状态枚举。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentCard:
    """Agent名片 — A2A协议中Agent互相发现的基础。"""

    id: str
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    endpoint: str = ""
    protocol_version: str = "1.0"


@dataclass
class Task:
    """结构化任务 — A2A协议的任务定义。"""

    id: str
    description: str
    input_data: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class TaskResult:
    """Result of an A2A routed task execution."""

    task_id: str
    output: str
    artifacts: list[str] = field(default_factory=list)
    error: str | None = None


class A2ARouter:
    """
    A2A协议路由 — 让不同框架构建的Agent相互通信。

    核心流程:
    1. Agent Card 注册 → 互相发现
    2. Task 委派 → 结构化任务传递
    3. Message 协商 → 多轮异步通信
    4. Artifact 返回 → 产物传递
    """

    def __init__(self):
        self.local_agents: dict[str, AgentCard] = {}
        self.remote_agents: dict[str, AgentCard] = {}
        self._task_results: dict[str, TaskResult] = {}

    def register(self, card: AgentCard) -> None:
        """Register an agent card (compliance test entry point)."""
        self.local_agents[card.id] = card

    def register_local(self, card: AgentCard):
        self.local_agents[card.id] = card

    def discover_remote(self, cards: list[AgentCard]):
        for card in cards:
            self.remote_agents[card.id] = card

    def find_agent(self, capability: str) -> AgentCard | None:
        """按能力查找Agent。"""
        all_agents = {**self.local_agents, **self.remote_agents}
        for agent in all_agents.values():
            if capability.lower() in [c.lower() for c in agent.capabilities]:
                return agent
        return None

    def delegate(self, task: Task, agent_id: str | None = None) -> TaskResult:
        """
        任务委派。实际生产环境中会通过A2A协议异步调用远程Agent。
        当前为本地模拟实现。
        """
        task.status = TaskStatus.IN_PROGRESS

        # 模拟异步执行
        result = TaskResult(
            task_id=task.id,
            output=f"Agent {agent_id or 'unknown'} processed: {task.description}",
        )
        task.status = TaskStatus.COMPLETED
        self._task_results[task.id] = result
        return result

    def list_agents(self) -> list[AgentCard]:
        return list(self.local_agents.values()) + list(self.remote_agents.values())
