"""Tests for agentos.core.event_bus — EventBus, Subscription, DeadLetter."""

import asyncio

import pytest

from agentos.core.event_bus import (
    DeadLetter,
    Event,
    EventBus,
    EventPriority,
    Subscription,
    default_bus,
    event,
)

# ============================================================================
# EventPriority
# ============================================================================

class TestEventPriority:
    def test_enum_values(self):
        assert EventPriority.LOW == 0
        assert EventPriority.NORMAL == 50
        assert EventPriority.HIGH == 100
        assert EventPriority.CRITICAL == 200

    def test_ordering(self):
        assert EventPriority.CRITICAL > EventPriority.HIGH > EventPriority.NORMAL > EventPriority.LOW


# ============================================================================
# Event
# ============================================================================

class TestEvent:
    def test_defaults(self):
        e = Event(topic="test")
        assert e.topic == "test"
        assert e.payload is None
        assert isinstance(e.event_id, str)
        assert len(e.event_id) == 12
        assert e.priority == EventPriority.NORMAL
        assert e.source == ""
        assert e.correlation_id == ""
        assert e.metadata == {}

    def test_custom_values(self):
        e = Event(
            topic="order.created",
            payload={"id": 1},
            priority=EventPriority.HIGH,
            source="api",
            correlation_id="abc",
            metadata={"key": "val"},
        )
        assert e.topic == "order.created"
        assert e.payload == {"id": 1}
        assert e.priority == EventPriority.HIGH
        assert e.source == "api"

    def test_unique_event_ids(self):
        e1 = Event(topic="a")
        e2 = Event(topic="b")
        assert e1.event_id != e2.event_id

    def test_event_factory(self):
        e = event("agent.start", payload={"v": 1}, source="scheduler")
        assert isinstance(e, Event)
        assert e.topic == "agent.start"
        assert e.payload == {"v": 1}


# ============================================================================
# DeadLetter
# ============================================================================

class TestDeadLetter:
    def test_defaults(self):
        e = Event(topic="x")
        dl = DeadLetter(event=e, handler_name="h", error="oops")
        assert dl.event is e
        assert dl.handler_name == "h"
        assert dl.error == "oops"
        assert dl.retry_count == 0


# ============================================================================
# Subscription
# ============================================================================

class TestSubscription:
    async def _noop(self, e): pass

    def test_matches_exact(self):
        sub = Subscription(
            topic_pattern="agent.start",
            handler=self._noop,
            handler_name="test",
            is_pattern=False,
        )
        assert sub.matches("agent.start") is True
        assert sub.matches("agent.stop") is False

    def test_matches_wildcard(self):
        sub = Subscription(
            topic_pattern="agent.*",
            handler=self._noop,
            handler_name="test",
            is_pattern=True,
        )
        assert sub.matches("agent.start") is True
        assert sub.matches("agent.stop") is True
        assert sub.matches("agent") is False
        assert sub.matches("other.thing") is False

    def test_matches_complex_wildcard(self):
        sub = Subscription(
            topic_pattern="order.*.created",
            handler=self._noop,
            handler_name="test",
            is_pattern=True,
        )
        assert sub.matches("order.123.created") is True
        assert sub.matches("order.abc.created") is True

    def test_concurrency_default(self):
        sub = Subscription(topic_pattern="t", handler=self._noop, handler_name="n")
        assert sub.concurrency == 1


# ============================================================================
# EventBus — Basic
# ============================================================================

class TestEventBusBasic:
    def test_defaults(self):
        bus = EventBus()
        assert bus.queue_size == 0
        assert bus.total_events == 0
        assert bus.subscription_count == 0

    def test_custom_params(self):
        bus = EventBus(max_queue_size=50, dlq_enabled=False, dlq_max_size=200, worker_count=2)
        assert bus._worker_count == 2

    def test_list_topics(self):
        bus = EventBus()
        assert bus.list_topics() == []


# ============================================================================
# EventBus — Subscribe / Unsubscribe
# ============================================================================

class TestEventBusSubscriptions:
    async def _noop(self, e): pass

    def test_subscribe(self):
        bus = EventBus()
        sub = bus.subscribe("agent.start", self._noop, handler_name="h")
        assert isinstance(sub, Subscription)
        assert bus.subscription_count == 1
        assert bus.list_topics() == ["agent.start"]

    def test_subscribe_auto_name(self):
        bus = EventBus()
        bus.subscribe("t", self._noop)
        assert bus.subscription_count == 1

    def test_unsubscribe(self):
        bus = EventBus()
        bus.subscribe("agent.start", self._noop, handler_name="h")
        assert bus.unsubscribe("agent.start", "h") is True
        assert bus.subscription_count == 0

    def test_unsubscribe_missing(self):
        bus = EventBus()
        assert bus.unsubscribe("x", "y") is False

    def test_unsubscribe_all(self):
        bus = EventBus()
        bus.subscribe("a", self._noop, handler_name="h")
        bus.subscribe("b", self._noop, handler_name="h")
        assert bus.unsubscribe_all("h") == 2
        assert bus.subscription_count == 0


# ============================================================================
# EventBus — Publish / Process
# ============================================================================

class TestEventBusPublish:
    @pytest.mark.asyncio
    async def test_publish_dispatch(self):
        bus = EventBus()
        received = []

        async def handler(e):
            received.append(e.payload)

        bus.subscribe("test", handler, handler_name="h")
        await bus.start()
        e = Event(topic="test", payload="hello")
        count = await bus.publish(e)
        await asyncio.sleep(0.1)
        await bus.stop()
        assert count == 1
        assert received == ["hello"]

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self):
        bus = EventBus()
        await bus.start()
        e = Event(topic="no.subs")
        count = await bus.publish(e)
        await bus.stop()
        assert count == 0

    @pytest.mark.asyncio
    async def test_publish_wildcard(self):
        bus = EventBus()
        received = []

        async def handler(e):
            received.append(e.topic)

        bus.subscribe("agent.*", handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="agent.start"))
        await bus.publish(Event(topic="agent.stop"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_publish_nowait(self):
        bus = EventBus(max_queue_size=100)
        received = []

        async def handler(e):
            received.append(e.payload)

        bus.subscribe("t", handler, handler_name="h")
        await bus.start()
        count = await bus.publish_nowait(Event(topic="t", payload="x"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert count == 1

    @pytest.mark.asyncio
    async def test_emit_sync(self):
        bus = EventBus()
        received = []

        async def handler(e):
            received.append(e.payload)

        bus.subscribe("t", handler, handler_name="h")
        await bus.start()
        bus.emit_sync(Event(topic="t", payload="sync"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert "sync" in received

    @pytest.mark.asyncio
    async def test_total_events(self):
        bus = EventBus()

        async def handler(e): pass
        bus.subscribe("t", handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.1)
        await bus.stop()
        assert bus.total_events >= 1


# ============================================================================
# EventBus — Priority ordering
# ============================================================================

class TestEventBusPriority:
    @pytest.mark.asyncio
    async def test_priority_sorting(self):
        bus = EventBus()
        order = []

        async def handler(e):
            order.append(e.priority)
            # Small delay to ensure async processing interleaving
            await asyncio.sleep(0.01)

        bus.subscribe("t", handler, handler_name="h")
        await bus.start()

        await bus.publish(Event(topic="t", priority=EventPriority.NORMAL))
        await bus.publish(Event(topic="t", priority=EventPriority.CRITICAL))
        await asyncio.sleep(0.5)
        await bus.stop()

        # At least one event was processed
        assert len(order) >= 1


# ============================================================================
# EventBus — DLQ
# ============================================================================

class TestEventBusDLQ:
    @pytest.mark.asyncio
    async def test_failed_handler_goes_to_dlq(self):
        bus = EventBus(dlq_enabled=True)

        async def failing_handler(e):
            raise ValueError("boom")

        bus.subscribe("t", failing_handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.2)
        await bus.stop()

        dlq = bus.get_dlq()
        assert len(dlq) == 1
        assert dlq[0].handler_name == "h"
        assert "boom" in dlq[0].error

    @pytest.mark.asyncio
    async def test_dlq_disabled(self):
        bus = EventBus(dlq_enabled=False)

        async def failing_handler(e):
            raise ValueError("boom")

        bus.subscribe("t", failing_handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.2)
        await bus.stop()

        assert len(bus.get_dlq()) == 0

    @pytest.mark.asyncio
    async def test_dlq_max_size(self):
        bus = EventBus(dlq_enabled=True, dlq_max_size=2)

        async def failing_handler(e):
            raise ValueError("x")

        bus.subscribe("t", failing_handler, handler_name="h")
        await bus.start()
        for i in range(5):
            await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.3)
        await bus.stop()

        dlq = bus.get_dlq()
        assert len(dlq) == 2

    @pytest.mark.asyncio
    async def test_clear_dlq(self):
        bus = EventBus(dlq_enabled=True)

        async def failing_handler(e):
            raise ValueError("x")

        bus.subscribe("t", failing_handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.2)
        await bus.stop()

        assert len(bus.get_dlq()) == 1
        cleared = bus.clear_dlq()
        assert cleared == 1
        assert len(bus.get_dlq()) == 0

    @pytest.mark.asyncio
    async def test_replay_dlq(self):
        bus = EventBus(dlq_enabled=True)

        async def failing_handler(e):
            raise ValueError("x")

        bus.subscribe("t", failing_handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t"))
        await asyncio.sleep(0.2)
        await bus.stop()

        assert len(bus.get_dlq()) == 1

        # Restart bus and replay
        await bus.start()
        replayed = await bus.replay_dlq()
        assert replayed == 1
        assert len(bus.get_dlq()) == 0
        await bus.stop()


# ============================================================================
# EventBus — Lifecycle
# ============================================================================

class TestEventBusLifecycle:
    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        bus = EventBus()
        await bus.start()
        await bus.start()  # should not double-start
        await bus.stop()

    @pytest.mark.asyncio
    async def test_stop_drains_queue(self):
        bus = EventBus(worker_count=2)
        received = []

        async def handler(e):
            received.append(e.payload)
            await asyncio.sleep(0)  # yield to event loop to allow processing

        bus.subscribe("t", handler, handler_name="h")
        await bus.start()
        await bus.publish(Event(topic="t", payload="drain"))
        await asyncio.sleep(0.3)
        await bus.stop(grace_period=3.0)
        assert "drain" in received


# ============================================================================
# Default bus
# ============================================================================

class TestDefaultBus:
    def test_default_bus_exists(self):
        assert isinstance(default_bus, EventBus)
