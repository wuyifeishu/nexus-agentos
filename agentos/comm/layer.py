"""
Communication Layer for NexusAgent.

Provides multiple communication patterns for multi-agent systems:
- Blackboard: Shared memory space
- EventBus: Publish-subscribe events
- Mailbox: Direct point-to-point messaging
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Message:
    """
    Communication message.

    Attributes:
        id: Unique identifier
        sender: Sender name
        receiver: Receiver name
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


class Blackboard:
    """
    Shared memory space for agents.

    Agents can read/write to a shared blackboard.
    Useful for collaborative problem solving.

    Usage:
        blackboard = Blackboard()
        blackboard.write("agent1", "status", "working")
        status = blackboard.read("agent1", "status")
    """

    def __init__(self):
        """Initialize blackboard."""
        self._data: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []

    def write(
        self,
        agent_name: str,
        key: str,
        value: Any,
    ) -> None:
        """
        Write to blackboard.

        Args:
            agent_name: Agent name
            key: Data key
            value: Data value
        """
        if agent_name not in self._data:
            self._data[agent_name] = {}

        self._data[agent_name][key] = value

        # Record in history
        self._history.append({
            "agent": agent_name,
            "key": key,
            "value": value,
            "timestamp": time.time(),
        })

    def read(
        self,
        agent_name: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read from blackboard.

        Args:
            agent_name: Agent name
            key: Data key
            default: Default value if not found

        Returns:
            Data value
        """
        if agent_name not in self._data:
            return default

        return self._data[agent_name].get(key, default)

    def read_all(self, key: str) -> dict[str, Any]:
        """
        Read key from all agents.

        Args:
            key: Data key

        Returns:
            Dict of agent_name -> value
        """
        return {
            agent: data.get(key)
            for agent, data in self._data.items()
            if key in data
        }

    def get_agent_data(self, agent_name: str) -> dict[str, Any]:
        """
        Get all data for an agent.

        Args:
            agent_name: Agent name

        Returns:
            Dict of key -> value
        """
        return self._data.get(agent_name, {}).copy()

    def get_history(
        self,
        agent_name: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get write history.

        Args:
            agent_name: Filter by agent (None = all)
            limit: Max results

        Returns:
            List of history entries
        """
        history = self._history

        if agent_name:
            history = [h for h in history if h["agent"] == agent_name]

        return history[-limit:]

    def clear(self, agent_name: Optional[str] = None) -> None:
        """
        Clear blackboard.

        Args:
            agent_name: Clear specific agent (None = all)
        """
        if agent_name:
            self._data.pop(agent_name, None)
        else:
            self._data.clear()


class EventBus:
    """
    Publish-subscribe event system.

    Agents can subscribe to events and publish events.
    Useful for event-driven architectures.

    Usage:
        bus = EventBus()

        # Subscribe
        bus.subscribe("task_completed", callback)

        # Publish
        bus.publish("task_completed", {"task_id": "123"})
    """

    def __init__(self):
        """Initialize event bus."""
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._history: list[dict[str, Any]] = []

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Any], None],
    ) -> None:
        """
        Subscribe to an event.

        Args:
            event_type: Event type
            callback: Callback function
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(callback)

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[Any], None],
    ) -> bool:
        """
        Unsubscribe from an event.

        Args:
            event_type: Event type
            callback: Callback function

        Returns:
            True if unsubscribed, False if not found
        """
        if event_type not in self._subscribers:
            return False

        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            return True

        return False

    def publish(
        self,
        event_type: str,
        data: Any = None,
        sender: str = "",
    ) -> int:
        """
        Publish an event.

        Args:
            event_type: Event type
            data: Event data
            sender: Sender name

        Returns:
            Number of subscribers notified
        """
        # Record in history
        self._history.append({
            "event_type": event_type,
            "data": data,
            "sender": sender,
            "timestamp": time.time(),
        })

        # Notify subscribers
        subscribers = self._subscribers.get(event_type, [])
        for callback in subscribers:
            try:
                callback(data)
            except Exception:
                pass  # Don't let one callback break others

        return len(subscribers)

    async def publish_async(
        self,
        event_type: str,
        data: Any = None,
        sender: str = "",
    ) -> int:
        """
        Publish an event asynchronously.

        Args:
            event_type: Event type
            data: Event data
            sender: Sender name

        Returns:
            Number of subscribers notified
        """
        # Record in history
        self._history.append({
            "event_type": event_type,
            "data": data,
            "sender": sender,
            "timestamp": time.time(),
        })

        # Notify subscribers
        subscribers = self._subscribers.get(event_type, [])
        tasks = []
        for callback in subscribers:
            if asyncio.iscoroutinefunction(callback):
                tasks.append(callback(data))
            else:
                callback(data)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return len(subscribers)

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get event history.

        Args:
            event_type: Filter by event type (None = all)
            limit: Max results

        Returns:
            List of history entries
        """
        history = self._history

        if event_type:
            history = [h for h in history if h["event_type"] == event_type]

        return history[-limit:]

    def clear(self) -> None:
        """Clear event bus."""
        self._subscribers.clear()
        self._history.clear()


class Mailbox:
    """
    Point-to-point messaging system.

    Agents have mailboxes and can send/receive messages.
    Useful for direct communication.

    Usage:
        mailbox = Mailbox()
        mailbox.send("agent1", "agent2", "Hello")
        messages = mailbox.receive("agent2")
    """

    def __init__(self):
        """Initialize mailbox system."""
        self._mailboxes: dict[str, list[Message]] = {}
        self._sent: list[Message] = []

    def send(
        self,
        sender: str,
        receiver: str,
        content: Any,
        **metadata
    ) -> Message:
        """
        Send a message.

        Args:
            sender: Sender name
            receiver: Receiver name
            content: Message content
            **metadata: Additional metadata

        Returns:
            Created Message
        """
        message = Message(
            sender=sender,
            receiver=receiver,
            content=content,
            metadata=metadata,
        )

        # Add to receiver's mailbox
        if receiver not in self._mailboxes:
            self._mailboxes[receiver] = []

        self._mailboxes[receiver].append(message)
        self._sent.append(message)

        return message

    def receive(
        self,
        receiver: str,
        limit: int = 100,
    ) -> list[Message]:
        """
        Receive messages.

        Args:
            receiver: Receiver name
            limit: Max messages

        Returns:
            List of messages
        """
        messages = self._mailboxes.get(receiver, [])
        return messages[:limit]

    def receive_and_clear(
        self,
        receiver: str,
        limit: int = 100,
    ) -> list[Message]:
        """
        Receive and clear messages.

        Args:
            receiver: Receiver name
            limit: Max messages

        Returns:
            List of messages
        """
        messages = self._mailboxes.get(receiver, [])[:limit]
        self._mailboxes[receiver] = self._mailboxes.get(receiver, [])[limit:]
        return messages

    def get_sent(
        self,
        sender: Optional[str] = None,
        limit: int = 100,
    ) -> list[Message]:
        """
        Get sent messages.

        Args:
            sender: Filter by sender (None = all)
            limit: Max results

        Returns:
            List of messages
        """
        sent = self._sent

        if sender:
            sent = [m for m in sent if m.sender == sender]

        return sent[-limit:]

    def clear(self, receiver: Optional[str] = None) -> None:
        """
        Clear mailboxes.

        Args:
            receiver: Clear specific receiver (None = all)
        """
        if receiver:
            self._mailboxes.pop(receiver, None)
        else:
            self._mailboxes.clear()


class CommunicationLayer:
    """
    Unified communication layer.

    Combines Blackboard, EventBus, and Mailbox into
    a single interface.

    Usage:
        comm = CommunicationLayer()

        # Use blackboard
        comm.blackboard.write("agent1", "status", "working")

        # Use event bus
        comm.event_bus.subscribe("task_completed", callback)

        # Use mailbox
        comm.mailbox.send("agent1", "agent2", "Hello")
    """

    def __init__(self):
        """Initialize communication layer."""
        self.blackboard = Blackboard()
        self.event_bus = EventBus()
        self.mailbox = Mailbox()

    def clear(self) -> None:
        """Clear all communication channels."""
        self.blackboard.clear()
        self.event_bus.clear()
        self.mailbox.clear()
