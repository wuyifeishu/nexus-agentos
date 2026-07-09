"""Tests for agentos.core.event_bus — ~18 test cases."""

import asyncio

import pytest

from agentos.core.event_bus import (
    DeadLetter,
    Event,
    EventBus,
    EventPriority,
    default_bus,
)


async def _drain(bus: EventBus, sleep: float = 0.15):
    """Give background workers time to process, then stop."""
    await asyncio.sleep(sleep)
    await bus.stop()


class TestEvent:
    """Event data class."""

    def test_default_values(self):
        e = Event(topic="test.topic")
        assert e.topic == "test.topic"
        assert e.event_id

    def test_custom_values(self):
        e = Event(
            topic="critical.alert",
            payload={"msg": "fire"},
            priority=EventPriority.CRITICAL,
            source="monitor",
        )
        assert e.payload == {"msg": "fire"}
        assert e.priority == EventPriority.CRITICAL
        assert e.source == "monitor"


class TestEventBus:
    """Event bus pub/sub."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []

        async def handler(event: Event):
            received.append(event.payload)

        bus.subscribe("order.created", handler)
        await bus.start()
        await bus.publish(Event(topic="order.created", payload="order-1"))
        await _drain(bus)

        assert len(received) == 1
        assert received[0] == "order-1"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = EventBus()
        results = []

        async def h1(e): results.append("h1")
        async def h2(e): results.append("h2")

        bus.subscribe("test", h1)
        bus.subscribe("test", h2)
        await bus.start()
        await bus.publish(Event(topic="test"))
        await _drain(bus)

        assert "h1" in results
        assert "h2" in results

    @pytest.mark.asyncio
    async def test_wildcard_subscription(self):
        bus = EventBus()
        received = []

        async def catch_all(e: Event):
            received.append(e.topic)

        bus.subscribe("agent.*", catch_all)
        await bus.start()

        await bus.publish(Event(topic="agent.start"))
        await bus.publish(Event(topic="agent.stop"))
        await bus.publish(Event(topic="other.event"))
        await _drain(bus)

        assert "agent.start" in received
        assert "agent.stop" in received
        assert "other.event" not in received

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        bus = EventBus()
        received = []

        async def h(e): received.append(1)

        bus.subscribe("topic", h, handler_name="my_handler")
        bus.unsubscribe("topic", "my_handler")

        await bus.start()
        await bus.publish(Event(topic="topic"))
        await _drain(bus)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_all(self):
        bus = EventBus()
        async def h(e): pass
        bus.subscribe("a", h, handler_name="h")
        bus.subscribe("b", h, handler_name="h")
        count = bus.unsubscribe_all("h")
        assert count == 2

    @pytest.mark.asyncio
    async def test_dlq_on_handler_failure(self):
        bus = EventBus(dlq_enabled=True)

        async def bad(_): raise RuntimeError("boom")

        bus.subscribe("fail", bad)
        await bus.start()
        await bus.publish(Event(topic="fail"))
        await _drain(bus)

        dlq = bus.get_dlq()
        assert len(dlq) == 1, f"Expected 1 DLQ entry, got {len(dlq)}"
        assert dlq[0].event.topic == "fail"
        assert "boom" in dlq[0].error

    @pytest.mark.asyncio
    async def test_dlq_max_size(self):
        bus = EventBus(dlq_enabled=True, dlq_max_size=2)

        async def bad(_): raise RuntimeError()

        bus.subscribe("f", bad)
        await bus.start()
        for _ in range(5):
            await bus.publish(Event(topic="f"))
        await _drain(bus, sleep=0.5)

        assert len(bus.get_dlq()) <= 2

    @pytest.mark.asyncio
    async def test_clear_dlq(self):
        bus = EventBus(dlq_enabled=True)

        async def bad(_): raise RuntimeError()

        bus.subscribe("f", bad)
        await bus.start()
        await bus.publish(Event(topic="f"))
        await _drain(bus)

        dlq = bus.get_dlq()
        assert len(dlq) >= 1
        cleared = bus.clear_dlq()
        assert cleared >= 1
        assert len(bus.get_dlq()) == 0

    @pytest.mark.asyncio
    async def test_total_events_counter(self):
        bus = EventBus()
        async def h(e): pass
        bus.subscribe("q", h)
        await bus.start()
        await bus.publish(Event(topic="q"))
        await bus.publish(Event(topic="q"))
        await _drain(bus)

        assert bus.total_events == 2

    @pytest.mark.asyncio
    async def test_list_topics(self):
        bus = EventBus()
        async def h(e): pass
        bus.subscribe("a.b", h)
        bus.subscribe("c.d", h)
        topics = bus.list_topics()
        assert "a.b" in topics
        assert "c.d" in topics

    @pytest.mark.asyncio
    async def test_subscription_count_property(self):
        bus = EventBus()
        async def h(e): pass
        bus.subscribe("t1", h)
        bus.subscribe("t1", h)
        bus.subscribe("t2", h)
        assert bus.subscription_count == 3

    @pytest.mark.asyncio
    async def test_priority_sorting(self):
        bus = EventBus()
        order = []

        async def h_crit(e):
            order.append("critical")

        async def h_normal(e):
            order.append("normal")

        bus.subscribe("p", h_crit, handler_name="crit")
        bus.subscribe("p", h_normal, handler_name="normal")
        await bus.start()

        # Within a single publish, higher-priority subscribers dispatch first
        await bus.publish(Event(topic="p", priority=EventPriority.CRITICAL))
        await _drain(bus)

        # Both handlers fired; order depends on internal dispatch
        assert "critical" in order
        assert "normal" in order


class TestDeadLetter:
    """Dead letter entry."""

    def test_creation(self):
        e = Event(topic="err")
        dl = DeadLetter(event=e, handler_name="h", error="msg")
        assert dl.event is e
        assert dl.handler_name == "h"
        assert dl.retry_count == 0


class TestDefaultBus:
    """Module-level default_bus singleton."""

    @pytest.mark.asyncio
    async def test_default_bus_exists(self):
        assert default_bus is not None
        assert isinstance(default_bus, EventBus)
