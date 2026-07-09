"""Tests for agentos.comm.layer — Blackboard, EventBus, Mailbox, CommunicationLayer."""

import asyncio

from agentos.comm.layer import (
    Blackboard,
    CommunicationLayer,
    EventBus,
    Mailbox,
    Message,
)

# ─── Message ───────────────────────────────────────────────────

class TestMessage:
    def test_defaults(self):
        m = Message()
        assert len(m.id) == 12
        assert m.sender == ""
        assert m.receiver is None
        assert m.content is None
        assert m.metadata == {}
        assert m.timestamp > 0

    def test_custom(self):
        m = Message(
            id="abc", sender="alice", receiver="bob",
            content="hello", metadata={"x": 1}, timestamp=100.0,
        )
        assert m.id == "abc"
        assert m.sender == "alice"
        assert m.receiver == "bob"
        assert m.content == "hello"
        assert m.metadata == {"x": 1}

    def test_to_dict(self):
        m = Message(sender="a", receiver="b", content="hi", timestamp=123.0)
        d = m.to_dict()
        assert d["sender"] == "a"
        assert d["receiver"] == "b"
        assert d["content"] == "hi"
        assert d["timestamp"] == 123.0
        assert "id" in d

    def test_auto_id_unique(self):
        m1 = Message()
        m2 = Message()
        assert m1.id != m2.id


# ─── Blackboard ────────────────────────────────────────────────

class TestBlackboard:
    def test_write_read(self):
        bb = Blackboard()
        bb.write("agent1", "key1", "value1")
        assert bb.read("agent1", "key1") == "value1"

    def test_read_missing_agent(self):
        bb = Blackboard()
        assert bb.read("nobody", "key") is None

    def test_read_missing_key_default(self):
        bb = Blackboard()
        assert bb.read("agent1", "missing", "fallback") == "fallback"

    def test_read_missing_key_none(self):
        bb = Blackboard()
        bb.write("agent1", "k", "v")
        assert bb.read("agent1", "missing") is None

    def test_overwrite(self):
        bb = Blackboard()
        bb.write("agent1", "k", "v1")
        bb.write("agent1", "k", "v2")
        assert bb.read("agent1", "k") == "v2"

    def test_multiple_agents(self):
        bb = Blackboard()
        bb.write("a", "x", 1)
        bb.write("b", "y", 2)
        assert bb.read("a", "x") == 1
        assert bb.read("b", "y") == 2

    def test_read_all(self):
        bb = Blackboard()
        bb.write("a", "status", "ready")
        bb.write("b", "status", "busy")
        bb.write("c", "other", "x")  # no "status" key
        result = bb.read_all("status")
        assert result == {"a": "ready", "b": "busy"}

    def test_read_all_empty(self):
        bb = Blackboard()
        assert bb.read_all("nonexistent") == {}

    def test_get_agent_data(self):
        bb = Blackboard()
        bb.write("agent1", "k1", "v1")
        bb.write("agent1", "k2", "v2")
        data = bb.get_agent_data("agent1")
        assert data == {"k1": "v1", "k2": "v2"}

    def test_get_agent_data_missing(self):
        bb = Blackboard()
        assert bb.get_agent_data("nobody") == {}

    def test_get_agent_data_is_copy(self):
        bb = Blackboard()
        bb.write("a", "k", "v")
        data = bb.get_agent_data("a")
        data["k"] = "mutated"
        assert bb.read("a", "k") == "v"

    def test_history(self):
        bb = Blackboard()
        bb.write("a", "k1", "v1")
        bb.write("a", "k2", "v2")
        bb.write("b", "k3", "v3")
        h = bb.get_history()
        assert len(h) == 3
        assert h[0]["agent"] == "a"

    def test_history_filter_agent(self):
        bb = Blackboard()
        bb.write("a", "k", "v")
        bb.write("b", "k", "v")
        h = bb.get_history(agent_name="a")
        assert len(h) == 1
        assert h[0]["agent"] == "a"

    def test_history_limit(self):
        bb = Blackboard()
        for i in range(5):
            bb.write("a", f"k{i}", i)
        assert len(bb.get_history(limit=3)) == 3

    def test_clear_all(self):
        bb = Blackboard()
        bb.write("a", "k", "v")
        bb.write("b", "k", "v")
        bb.clear()
        assert bb.read("a", "k") is None
        assert bb.get_agent_data("b") == {}

    def test_clear_agent(self):
        bb = Blackboard()
        bb.write("a", "k", "v")
        bb.write("b", "k", "v")
        bb.clear(agent_name="a")
        assert bb.read("a", "k") is None
        assert bb.read("b", "k") == "v"

    def test_clear_missing_agent(self):
        bb = Blackboard()
        bb.clear(agent_name="nobody")  # should not raise


# ─── EventBus ──────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_publish(self):
        eb = EventBus()
        received = []

        def cb(data):
            received.append(data)

        eb.subscribe("evt", cb)
        count = eb.publish("evt", {"x": 1})
        assert count == 1
        assert received == [{"x": 1}]

    def test_publish_no_subscribers(self):
        eb = EventBus()
        count = eb.publish("evt", "data")
        assert count == 0

    def test_unsubscribe_exists(self):
        eb = EventBus()
        received = []

        def cb(data):
            received.append(data)

        eb.subscribe("evt", cb)
        assert eb.unsubscribe("evt", cb) is True
        eb.publish("evt", 42)
        assert received == []

    def test_unsubscribe_missing_event(self):
        eb = EventBus()

        def cb(data):
            pass

        assert eb.unsubscribe("unknown", cb) is False

    def test_unsubscribe_missing_callback(self):
        eb = EventBus()

        def cb1(data):
            pass

        def cb2(data):
            pass

        eb.subscribe("evt", cb1)
        assert eb.unsubscribe("evt", cb2) is False

    def test_multiple_subscribers(self):
        eb = EventBus()
        results = []

        def cb1(data):
            results.append(f"cb1:{data}")

        def cb2(data):
            results.append(f"cb2:{data}")

        eb.subscribe("evt", cb1)
        eb.subscribe("evt", cb2)
        count = eb.publish("evt", "x")
        assert count == 2
        assert len(results) == 2

    def test_callback_exception_handled(self):
        eb = EventBus()
        good = []

        def bad(data):
            raise ValueError("oops")

        def ok(data):
            good.append(data)

        eb.subscribe("evt", bad)
        eb.subscribe("evt", ok)
        count = eb.publish("evt", "val")
        assert count == 2
        assert good == ["val"]

    def test_async_publish_sync_callbacks(self):
        eb = EventBus()
        results = []

        def cb(data):
            results.append(data)

        eb.subscribe("evt", cb)
        count = asyncio.run(eb.publish_async("evt", "async_data"))
        assert count == 1
        assert results == ["async_data"]

    def test_async_publish_mixed_callbacks(self):
        eb = EventBus()
        results = []

        def sync_cb(data):
            results.append(f"sync:{data}")

        async def async_cb(data):
            await asyncio.sleep(0.01)
            results.append(f"async:{data}")

        eb.subscribe("evt", sync_cb)
        eb.subscribe("evt", async_cb)
        count = asyncio.run(eb.publish_async("evt", "x"))
        assert count == 2
        assert len(results) == 2

    def test_async_publish_callback_exception(self):
        eb = EventBus()
        results = []

        async def bad(data):
            raise ValueError("async fail")

        async def ok(data):
            results.append(data)

        eb.subscribe("evt", bad)
        eb.subscribe("evt", ok)
        count = asyncio.run(eb.publish_async("evt", "ok"))
        assert count == 2
        assert results == ["ok"]

    def test_history(self):
        eb = EventBus()
        eb.publish("e1", "d1", sender="s1")
        eb.publish("e2", "d2", sender="s2")
        h = eb.get_history()
        assert len(h) == 2
        assert h[0]["event_type"] == "e1"
        assert h[0]["sender"] == "s1"

    def test_history_filter(self):
        eb = EventBus()
        eb.publish("a", 1)
        eb.publish("b", 2)
        h = eb.get_history(event_type="a")
        assert len(h) == 1
        assert h[0]["event_type"] == "a"

    def test_history_limit(self):
        eb = EventBus()
        for i in range(5):
            eb.publish(f"e{i}", str(i))
        assert len(eb.get_history(limit=3)) == 3

    def test_async_history(self):
        eb = EventBus()
        asyncio.run(eb.publish_async("e", "d", sender="s"))
        h = eb.get_history()
        assert len(h) == 1
        assert h[0]["sender"] == "s"

    def test_clear(self):
        eb = EventBus()
        eb.subscribe("evt", lambda d: None)
        eb.publish("evt", "data")
        eb.clear()
        assert eb.get_history() == []
        assert eb.publish("evt") == 0


# ─── Mailbox ───────────────────────────────────────────────────

class TestMailbox:
    def test_send_receive(self):
        mb = Mailbox()
        msg = mb.send("alice", "bob", "hello")
        assert msg.sender == "alice"
        assert msg.receiver == "bob"
        assert msg.content == "hello"
        received = mb.receive("bob")
        assert len(received) == 1
        assert received[0].content == "hello"

    def test_receive_empty(self):
        mb = Mailbox()
        assert mb.receive("nobody") == []

    def test_receive_limit(self):
        mb = Mailbox()
        for i in range(5):
            mb.send("a", "b", f"msg{i}")
        assert len(mb.receive("b", limit=3)) == 3

    def test_receive_and_clear(self):
        mb = Mailbox()
        mb.send("a", "b", "m1")
        mb.send("a", "b", "m2")
        rcvd = mb.receive_and_clear("b")
        assert len(rcvd) == 2
        assert mb.receive("b") == []

    def test_receive_and_clear_limit(self):
        mb = Mailbox()
        for i in range(3):
            mb.send("a", "b", f"msg{i}")
        rcvd = mb.receive_and_clear("b", limit=2)
        assert len(rcvd) == 2
        remaining = mb.receive("b")
        assert len(remaining) == 1

    def test_send_with_metadata(self):
        mb = Mailbox()
        msg = mb.send("a", "b", "content", priority="high", tag="urgent")
        assert msg.metadata == {"priority": "high", "tag": "urgent"}

    def test_get_sent_all(self):
        mb = Mailbox()
        mb.send("a", "x", "msg1")
        mb.send("b", "y", "msg2")
        sent = mb.get_sent()
        assert len(sent) == 2

    def test_get_sent_filter(self):
        mb = Mailbox()
        mb.send("a", "x", "m1")
        mb.send("b", "y", "m2")
        sent = mb.get_sent(sender="a")
        assert len(sent) == 1
        assert sent[0].sender == "a"

    def test_get_sent_limit(self):
        mb = Mailbox()
        for i in range(5):
            mb.send("a", "b", f"m{i}")
        assert len(mb.get_sent(limit=3)) == 3

    def test_clear_all(self):
        mb = Mailbox()
        mb.send("a", "b", "msg")
        mb.clear()
        assert mb.receive("b") == []

    def test_clear_receiver(self):
        mb = Mailbox()
        mb.send("a", "b", "m1")
        mb.send("a", "c", "m2")
        mb.clear(receiver="b")
        assert mb.receive("b") == []
        assert len(mb.receive("c")) == 1

    def test_multiple_senders(self):
        mb = Mailbox()
        mb.send("a", "b", "m1")
        mb.send("c", "b", "m2")
        received = mb.receive("b")
        assert len(received) == 2
        assert {r.sender for r in received} == {"a", "c"}


# ─── CommunicationLayer ────────────────────────────────────────

class TestCommunicationLayer:
    def test_composition(self):
        cl = CommunicationLayer()
        assert isinstance(cl.blackboard, Blackboard)
        assert isinstance(cl.event_bus, EventBus)
        assert isinstance(cl.mailbox, Mailbox)

    def test_blackboard_through_layer(self):
        cl = CommunicationLayer()
        cl.blackboard.write("agent1", "status", "ready")
        assert cl.blackboard.read("agent1", "status") == "ready"

    def test_event_bus_through_layer(self):
        cl = CommunicationLayer()
        received = []

        def cb(data):
            received.append(data)

        cl.event_bus.subscribe("evt", cb)
        cl.event_bus.publish("evt", "data")
        assert received == ["data"]

    def test_mailbox_through_layer(self):
        cl = CommunicationLayer()
        cl.mailbox.send("a", "b", "msg")
        assert len(cl.mailbox.receive("b")) == 1

    def test_clear_all(self):
        cl = CommunicationLayer()
        cl.blackboard.write("a", "k", "v")
        cl.mailbox.send("a", "b", "msg")

        def cb(d):
            pass

        cl.event_bus.subscribe("evt", cb)
        cl.event_bus.publish("evt", "data")

        cl.clear()
        assert cl.blackboard.read("a", "k") is None
        assert cl.mailbox.receive("b") == []
        assert cl.event_bus.get_history() == []
