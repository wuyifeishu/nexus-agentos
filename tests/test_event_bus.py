"""Tests for agentos.tools.event_bus."""

from agentos.tools.event_bus import Event, EventBus, TopicFilter, get_event_bus


class TestEventBus:
    def test_publish_subscribe(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.data)

        bus.subscribe("test.topic", handler)
        bus.publish("test.topic", "hello")
        assert received == ["hello"]

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.data)

        unsub = bus.subscribe("x", handler)
        bus.publish("x", 1)
        unsub()
        bus.publish("x", 2)
        assert received == [1]

    def test_exact_topic_only(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.topic)

        bus.subscribe("a.b", handler)
        bus.publish("a.b", 1)
        bus.publish("a.c", 2)
        assert received == ["a.b"]

    def test_wildcard_single(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.topic)

        bus.subscribe("agent.*.call", handler)
        bus.publish("agent.tool.call", 1)
        bus.publish("agent.chat.call", 2)
        bus.publish("agent.tool.setup", 3)
        assert len(received) == 2
        assert "agent.tool.call" in received
        assert "agent.chat.call" in received

    def test_wildcard_multi(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.topic)

        bus.subscribe("system.**", handler)
        bus.publish("system.shutdown", 1)
        bus.publish("system.sub.module.init", 2)
        bus.publish("user.login", 3)
        assert len(received) == 2
        assert "system.shutdown" in received
        assert "system.sub.module.init" in received

    def test_multiple_subscribers(self):
        bus = EventBus()
        results = []

        def h1(e): results.append("a")
        def h2(e): results.append("b")

        bus.subscribe("t", h1)
        bus.subscribe("t", h2)
        bus.publish("t")
        assert sorted(results) == ["a", "b"]

    def test_event_source(self):
        bus = EventBus()
        src = None

        def handler(e):
            nonlocal src
            src = e.source

        bus.subscribe("t", handler)
        bus.publish("t", source="agent-42")
        assert src == "agent-42"

    def test_history(self):
        bus = EventBus()
        bus.publish("a", 1)
        bus.publish("b", 2)
        hist = bus.get_history()
        assert len(hist) == 2
        assert hist[0].topic == "a"
        assert hist[1].topic == "b"

    def test_history_limit(self):
        bus = EventBus()
        # Bypass max_history for test
        bus._max_history = 3
        for i in range(5):
            bus.publish("t", i)
        hist = bus.get_history()
        assert len(hist) == 3
        assert hist[0].data == 2

    def test_clear_history(self):
        bus = EventBus()
        bus.publish("a", 1)
        bus.clear_history()
        assert len(bus.get_history()) == 0

    def test_stop_start(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.data)

        bus.subscribe("t", handler)
        bus.stop()
        bus.publish("t", 1)
        assert received == []
        bus.start()
        bus.publish("t", 2)
        assert received == [2]

    def test_subscriber_count(self):
        bus = EventBus()
        bus.subscribe("a", lambda e: None)
        bus.subscribe("b.*", lambda e: None)
        bus.subscribe("b.*", lambda e: None)
        assert bus.subscriber_count() == 3
        assert bus.subscriber_count("b.*") == 2

    def test_stats(self):
        bus = EventBus()
        bus.subscribe("x", lambda e: None)
        bus.publish("x", 42)
        s = bus.stats
        assert s["total_published"] == 1
        assert s["subscriber_count"] == 1

    def test_unsubscribe_bulk(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e.data)

        h1 = bus.subscribe("t", handler)
        h2 = bus.subscribe("t", lambda e: received.append("other"))
        bus.publish("t", 1)
        assert len(received) == 2
        h1()
        bus.publish("t", 2)
        assert received == [1, "other", "other"]


class TestTopicFilter:
    def test_add_evaluate(self):
        tf = TopicFilter()
        tf.add("is_error", lambda e: e.data is not None and "error" in str(e.data))
        tf.add("is_warn", lambda e: e.data is not None and "warn" in str(e.data))

        e = Event("log", "error: something broke")
        assert "is_error" in tf.evaluate(e)
        assert "is_warn" not in tf.evaluate(e)

    def test_remove(self):
        tf = TopicFilter()
        tf.add("x", lambda e: True)
        assert tf.remove("x") is True
        assert tf.remove("x") is False

    def test_evaluate_empty(self):
        tf = TopicFilter()
        assert tf.evaluate(Event("x")) == []


class TestGlobalBus:
    def test_singleton(self):
        b1 = get_event_bus()
        b2 = get_event_bus()
        assert b1 is b2
