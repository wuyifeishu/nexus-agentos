"""
Swarm Coordinator for NexusAgent.

Multi-agent coordination system with different topologies:
- Star: Central coordinator
- Ring: Circular message passing
- Mesh: All-to-all communication
- Tree: Hierarchical structure
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from agentos.core.di import Agent, RunContext


class SwarmTopology(str, Enum):
    """Swarm topology types."""
    STAR = "star"     # Central coordinator
    RING = "ring"     # Circular message passing
    MESH = "mesh"     # All-to-all communication
    TREE = "tree"     # Hierarchical structure


@dataclass
class AgentRole:
    """Agent 角色定义。"""
    name: str
    goal: str
    backstory: str = ""
    tools: list[str] = field(default_factory=list)
    model: str = "auto"
    temperature: float = 0.7
    allow_delegation: bool = True
    verbose: bool = False


class MessageBus:
    """Agent 间消息总线 — 黑板模式。"""

    def __init__(self):
        self._messages: list[dict] = []
        self._subscribers: dict[str, list[Callable]] = {}
        self._shared_memory: dict[str, Any] = {}

    def publish(self, sender: str, topic: str, data: dict):
        msg = {"sender": sender, "topic": topic, "data": data}
        self._messages.append(msg)
        if topic in self._subscribers:
            for cb in self._subscribers[topic]:
                cb(msg)

    def subscribe(self, topic: str, callback: Callable):
        self._subscribers.setdefault(topic, []).append(callback)

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def shared_memory(self) -> dict[str, Any]:
        return self._shared_memory


@dataclass
class SwarmMessage:
    """
    Message in swarm communication.

    Attributes:
        id: Unique identifier
        sender: Sender agent name
        receiver: Receiver agent name (None = broadcast)
        content: Message content
        metadata: Additional metadata
        timestamp: Message timestamp
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""
    receiver: Optional[str] = None
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class SwarmResult:
    """
    Result of swarm execution.

    Attributes:
        id: Unique identifier
        topology: Swarm topology
        outputs: Agent outputs
        messages: Communication messages
        duration: Execution duration
        success: Whether execution succeeded
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    topology: SwarmTopology = SwarmTopology.STAR
    outputs: dict[str, Any] = field(default_factory=dict)
    messages: list[SwarmMessage] = field(default_factory=list)
    duration: float = 0.0
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "topology": self.topology.value,
            "outputs": self.outputs,
            "messages": [m.to_dict() for m in self.messages],
            "duration": self.duration,
            "success": self.success,
        }


class SwarmCoordinator:
    """
    Multi-agent coordination system.

    Coordinates multiple agents using different topologies:
    - Star: Central coordinator routes all messages
    - Ring: Agents pass messages in circular order
    - Mesh: All agents can communicate with each other
    - Tree: Hierarchical parent-child structure

    Usage:
        coordinator = SwarmCoordinator(topology=SwarmTopology.STAR)
        coordinator.register(agent1)
        coordinator.register(agent2)

        result = await coordinator.execute("task")
    """

    def __init__(
        self,
        topology: SwarmTopology = SwarmTopology.STAR,
        max_rounds: int = 10,
    ):
        """
        Initialize swarm coordinator.

        Args:
            topology: Swarm topology
            max_rounds: Maximum communication rounds
        """
        self.topology = topology
        self.max_rounds = max_rounds
        self._agents: dict[str, Agent[Any, Any]] = {}
        self._message_queue: list[SwarmMessage] = []

    def register(self, agent: Agent[Any, Any]) -> None:
        """
        Register an agent.

        Args:
            agent: Agent to register
        """
        self._agents[agent.name] = agent

    def unregister(self, agent_name: str) -> bool:
        """
        Unregister an agent.

        Args:
            agent_name: Agent name

        Returns:
            True if unregistered, False if not found
        """
        if agent_name in self._agents:
            del self._agents[agent_name]
            return True
        return False

    def get_agent(self, agent_name: str) -> Optional[Agent[Any, Any]]:
        """
        Get an agent by name.

        Args:
            agent_name: Agent name

        Returns:
            Agent if found, None otherwise
        """
        return self._agents.get(agent_name)

    def list_agents(self) -> list[str]:
        """
        List all registered agents.

        Returns:
            List of agent names
        """
        return list(self._agents.keys())

    async def execute(
        self,
        task: Any,
        **metadata
    ) -> SwarmResult:
        """
        Execute task using swarm.

        Args:
            task: Task to execute
            **metadata: Additional metadata

        Returns:
            SwarmResult
        """
        start_time = time.time()

        if self.topology == SwarmTopology.STAR:
            result = await self._execute_star(task, metadata)
        elif self.topology == SwarmTopology.RING:
            result = await self._execute_ring(task, metadata)
        elif self.topology == SwarmTopology.MESH:
            result = await self._execute_mesh(task, metadata)
        elif self.topology == SwarmTopology.TREE:
            result = await self._execute_tree(task, metadata)
        else:
            raise ValueError(f"Unknown topology: {self.topology}")

        result.duration = time.time() - start_time

        return result

    async def _execute_star(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        """Star topology: central coordinator."""
        result = SwarmResult(topology=SwarmTopology.STAR)

        # Coordinator broadcasts task to all agents
        for agent_name, agent in self._agents.items():
            try:
                # Send task to agent
                message = SwarmMessage(
                    sender="coordinator",
                    receiver=agent_name,
                    content=task,
                    metadata=metadata,
                )
                result.messages.append(message)

                # Execute agent
                output = await agent.invoke(task, **metadata)
                result.outputs[agent_name] = output

                # Agent responds to coordinator
                response = SwarmMessage(
                    sender=agent_name,
                    receiver="coordinator",
                    content=output,
                )
                result.messages.append(response)
            except Exception as e:
                result.outputs[agent_name] = {"error": str(e)}
                result.success = False

        return result

    async def _execute_ring(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        """Ring topology: circular message passing."""
        result = SwarmResult(topology=SwarmTopology.RING)
        agent_names = list(self._agents.keys())

        if not agent_names:
            return result

        current_input = task

        # Pass message around the ring
        for i, agent_name in enumerate(agent_names):
            agent = self._agents[agent_name]
            next_agent = agent_names[(i + 1) % len(agent_names)]

            try:
                # Execute agent
                output = await agent.invoke(current_input, **metadata)
                result.outputs[agent_name] = output

                # Message to next agent
                message = SwarmMessage(
                    sender=agent_name,
                    receiver=next_agent,
                    content=output,
                )
                result.messages.append(message)

                # Output becomes next input
                current_input = output
            except Exception as e:
                result.outputs[agent_name] = {"error": str(e)}
                result.success = False

        return result

    async def _execute_mesh(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        """Mesh topology: all-to-all communication."""
        result = SwarmResult(topology=SwarmTopology.MESH)

        # All agents execute task in parallel
        tasks = []
        for agent_name, agent in self._agents.items():
            tasks.append(self._execute_agent_mesh(agent, task, metadata, result))

        await asyncio.gather(*tasks, return_exceptions=True)

        # Broadcast results to all agents
        for sender_name, output in result.outputs.items():
            for receiver_name in self._agents.keys():
                if sender_name != receiver_name:
                    message = SwarmMessage(
                        sender=sender_name,
                        receiver=receiver_name,
                        content=output,
                    )
                    result.messages.append(message)

        return result

    async def _execute_agent_mesh(
        self,
        agent: Agent[Any, Any],
        task: Any,
        metadata: dict[str, Any],
        result: SwarmResult,
    ) -> None:
        """Execute agent in mesh topology."""
        try:
            output = await agent.invoke(task, **metadata)
            result.outputs[agent.name] = output
        except Exception as e:
            result.outputs[agent.name] = {"error": str(e)}
            result.success = False

    async def _execute_tree(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        """Tree topology: hierarchical structure."""
        result = SwarmResult(topology=SwarmTopology.TREE)
        agent_names = list(self._agents.keys())

        if not agent_names:
            return result

        # Root agent (first) executes task
        root_name = agent_names[0]
        root_agent = self._agents[root_name]

        try:
            root_output = await root_agent.invoke(task, **metadata)
            result.outputs[root_name] = root_output
        except Exception as e:
            result.outputs[root_name] = {"error": str(e)}
            result.success = False
            return result

        # Distribute to children
        children = agent_names[1:]
        for child_name in children:
            child_agent = self._agents[child_name]

            # Message from root to child
            message = SwarmMessage(
                sender=root_name,
                receiver=child_name,
                content=root_output,
            )
            result.messages.append(message)

            try:
                child_output = await child_agent.invoke(root_output, **metadata)
                result.outputs[child_name] = child_output

                # Response from child to root
                response = SwarmMessage(
                    sender=child_name,
                    receiver=root_name,
                    content=child_output,
                )
                result.messages.append(response)
            except Exception as e:
                result.outputs[child_name] = {"error": str(e)}
                result.success = False

        return result

    def send_message(
        self,
        sender: str,
        receiver: Optional[str],
        content: Any,
        **metadata
    ) -> SwarmMessage:
        """
        Send a message in the swarm.

        Args:
            sender: Sender agent name
            receiver: Receiver agent name (None = broadcast)
            content: Message content
            **metadata: Additional metadata

        Returns:
            Created SwarmMessage
        """
        message = SwarmMessage(
            sender=sender,
            receiver=receiver,
            content=content,
            metadata=metadata,
        )
        self._message_queue.append(message)
        return message

    def get_messages(
        self,
        receiver: Optional[str] = None,
    ) -> list[SwarmMessage]:
        """
        Get messages for an agent.

        Args:
            receiver: Receiver name (None = all)

        Returns:
            List of messages
        """
        if receiver:
            return [
                m for m in self._message_queue
                if m.receiver == receiver or m.receiver is None
            ]
        return self._message_queue.copy()

    def clear_messages(self) -> None:
        """Clear message queue."""
        self._message_queue.clear()
