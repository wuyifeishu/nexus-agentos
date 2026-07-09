"""测试 A2A 协议 — Task, Message, Handoff, Client, Server。"""

import time

import pytest

from agentos.protocols.a2a import (
    A2AArtifact,
    A2AHandoff,
    A2AMessage,
    A2AServer,
    A2ASession,
    A2ATask,
    DataPart,
    FilePart,
    MessageRole,
    TaskState,
    TextPart,
    new_handoff,
    new_task,
    part_from_dict,
)


class TestA2AParts:
    def test_text_part_roundtrip(self):
        tp = TextPart(text="hello", meta={"lang": "en"})
        d = tp.to_dict()
        assert d["type"] == "text"
        tp2 = TextPart.from_dict(d)
        assert tp2.text == "hello"
        assert tp2.meta == {"lang": "en"}

    def test_file_part_roundtrip(self):
        fp = FilePart(
            url="https://ex.com/f.pdf",
            filename="report.pdf",
            mime_type="application/pdf",
            size=1024,
        )
        d = fp.to_dict()
        fp2 = FilePart.from_dict(d)
        assert fp2.filename == "report.pdf"
        assert fp2.mime_type == "application/pdf"

    def test_data_part_roundtrip(self):
        dp = DataPart(data={"count": 42}, schema_uri="https://schema.org/result")
        d = dp.to_dict()
        dp2 = DataPart.from_dict(d)
        assert dp2.data["count"] == 42

    def test_part_from_dict_dispatcher(self):
        d = {"type": "text", "text": "hi"}
        p = part_from_dict(d)
        assert isinstance(p, TextPart)
        assert p.text == "hi"

        d = {"type": "file", "filename": "x.txt"}
        p = part_from_dict(d)
        assert isinstance(p, FilePart)

        d = {"type": "data", "data": {"a": 1}}
        p = part_from_dict(d)
        assert isinstance(p, DataPart)


class TestA2AArtifact:
    def test_roundtrip(self):
        art = A2AArtifact(
            name="result.json", mime_type="application/json", blob=b'{"a":1}', size=8
        )
        d = art.to_dict()
        art2 = A2AArtifact.from_dict(d)
        assert art2.name == "result.json"
        assert art2.blob == b'{"a":1}'

    def test_url_artifact(self):
        art = A2AArtifact(name="image.png", url="https://cdn.ex/img.png")
        d = art.to_dict()
        assert "url" in d
        art2 = A2AArtifact.from_dict(d)
        assert art2.url == "https://cdn.ex/img.png"


class TestA2AMessage:
    def test_user_text(self):
        msg = A2AMessage.user_text("hello world")
        assert msg.role == MessageRole.USER
        assert len(msg.parts) == 1
        assert msg.parts[0].text == "hello world"

    def test_agent_text(self):
        msg = A2AMessage.agent_text("done")
        assert msg.role == MessageRole.AGENT
        assert msg.get_text() == "done"

    def test_multipart_roundtrip(self):
        msg = A2AMessage(
            role=MessageRole.USER,
            parts=[
                TextPart(text="analyze this"),
                FilePart(filename="data.csv"),
                DataPart(data={"options": {"method": "pca"}}),
            ],
        )
        d = msg.to_dict()
        msg2 = A2AMessage.from_dict(d)
        assert msg2.role == MessageRole.USER
        assert len(msg2.parts) == 3
        assert isinstance(msg2.parts[0], TextPart)
        assert isinstance(msg2.parts[1], FilePart)
        assert isinstance(msg2.parts[2], DataPart)
        assert msg2.get_text() == "analyze this"


class TestA2ATask:
    def test_lifecycle(self):
        task = A2ATask(input=A2AMessage.user_text("do something"))
        assert task.state == TaskState.SUBMITTED

        task.start_working()
        assert task.state == TaskState.WORKING

        task.complete(A2AMessage.agent_text("done"))
        assert task.state == TaskState.COMPLETED
        assert task.output.get_text() == "done"
        assert task.is_terminal()

    def test_fail(self):
        task = A2ATask(input=A2AMessage.user_text("bad"))
        task.start_working()
        task.fail("something went wrong")
        assert task.state == TaskState.FAILED
        assert task.error == "something went wrong"
        assert task.is_terminal()

    def test_cancel(self):
        task = A2ATask()
        assert not task.is_terminal()
        task.cancel()
        assert task.state == TaskState.CANCELLED
        assert task.is_terminal()

    def test_cannot_start_non_submitted(self):
        task = A2ATask()
        task.start_working()
        with pytest.raises(ValueError):
            task.start_working()

    def test_cannot_complete_non_working(self):
        task = A2ATask()
        with pytest.raises(ValueError):
            task.complete()

    def test_cannot_cancel_completed(self):
        task = A2ATask()
        task.start_working()
        task.complete()
        with pytest.raises(ValueError):
            task.cancel()

    def test_artifact_attachment(self):
        task = A2ATask()
        task.add_artifact(A2AArtifact(name="out.csv"))
        task.add_artifact(A2AArtifact(name="out.png"))
        assert len(task.artifacts) == 2

    def test_json_roundtrip(self):
        task = A2ATask(input=A2AMessage.user_text("hello"))
        task.start_working()
        task.complete(A2AMessage.agent_text("result"))
        task.add_artifact(A2AArtifact(name="out.json", blob=b"{}"))

        json_str = task.to_json()
        task2 = A2ATask.from_json(json_str)
        assert task2.task_id == task.task_id
        assert task2.state == TaskState.COMPLETED
        assert task2.input.get_text() == "hello"
        assert task2.artifacts[0].name == "out.json"

    def test_state_history(self):
        task = A2ATask()
        task.start_working()
        task.complete()
        assert len(task._state_history) == 2
        assert task._state_history[0][0] == TaskState.SUBMITTED
        assert task._state_history[1][0] == TaskState.WORKING


class TestA2AHandoff:
    def test_roundtrip(self):
        task = A2ATask(input=A2AMessage.user_text("do x"))
        ho = A2AHandoff(
            source_agent="coordinator",
            target_agent="worker",
            task=task,
            reason="delegation",
        )
        d = ho.to_dict()
        ho2 = A2AHandoff.from_dict(d)
        assert ho2.source_agent == "coordinator"
        assert ho2.target_agent == "worker"
        assert ho2.task.task_id == task.task_id
        assert ho2.reason == "delegation"

    def test_json_roundtrip(self):
        task = A2ATask(input=A2AMessage.user_text("test"))
        ho = A2AHandoff(source_agent="a", target_agent="b", task=task)
        ho2 = A2AHandoff.from_json(ho.to_json())
        assert ho2.source_agent == "a"
        assert ho2.handoff_id == ho.handoff_id


class TestA2ASession:
    def test_basic(self):
        sess = A2ASession()
        sess.add_message(A2AMessage.user_text("hi"))
        sess.add_message(A2AMessage.agent_text("hello"))
        sess.add_task(A2ATask())
        assert len(sess.history) == 2
        assert len(sess.tasks) == 1

    def test_get_last_n(self):
        sess = A2ASession()
        for i in range(5):
            sess.add_message(A2AMessage.user_text(f"msg{i}"))
        last3 = sess.get_last_n_messages(3)
        assert len(last3) == 3
        assert last3[-1].get_text() == "msg4"


class TestA2Server:
    @pytest.mark.asyncio
    async def test_process_task_success(self):
        server = A2AServer()

        async def handler(task: A2ATask):
            return A2AMessage.agent_text(f"processed: {task.input.get_text()}")

        server.register_handler("worker", handler)
        task = new_task("hello test", target_agent="worker")
        result = await server.process_task(task.to_dict())
        assert result["state"] == "completed"
        assert "processed: hello test" in result["output"]["parts"][0]["text"]

    @pytest.mark.asyncio
    async def test_process_task_no_handler(self):
        server = A2AServer()
        task = new_task("hello", target_agent="nonexistent")
        result = await server.process_task(task.to_dict())
        assert result["state"] == "failed"
        assert "No handler" in result["error"]

    @pytest.mark.asyncio
    async def test_process_task_handler_error(self):
        server = A2AServer()

        async def bad_handler(task):
            raise ValueError("simulated error")

        server.register_handler("bad", bad_handler)
        task = new_task("test", target_agent="bad")
        result = await server.process_task(task.to_dict())
        assert result["state"] == "failed"
        assert "simulated error" in result["error"]

    def test_get_task(self):
        from agentos.protocols.a2a_store import InMemoryTaskStore

        store = InMemoryTaskStore()
        server = A2AServer(task_store=store)
        task = A2ATask(task_id="task-001")
        store.save_task(task)
        assert server.get_task("task-001").task_id == "task-001"
        assert server.get_task("nonexistent") is None

    def test_list_tasks_by_state(self):
        from agentos.protocols.a2a_store import InMemoryTaskStore

        store = InMemoryTaskStore()
        server = A2AServer(task_store=store)
        t1 = A2ATask(task_id="t1")
        t2 = A2ATask(task_id="t2")
        t2.start_working()
        t2.complete()
        t3 = A2ATask(task_id="t3")
        t3.fail("err")
        for t in [t1, t2, t3]:
            store.save_task(t)
        assert len(server.list_tasks()) == 3
        assert len(server.list_tasks(TaskState.COMPLETED)) == 1
        assert len(server.list_tasks(TaskState.FAILED)) == 1

    def test_cleanup(self):
        from agentos.protocols.a2a_store import InMemoryTaskStore

        store = InMemoryTaskStore()
        server = A2AServer(task_store=store)
        old = A2ATask(task_id="old")
        old.start_working()
        old.complete()
        old._updated = time.time() - 4000  # fake old
        fresh = A2ATask(task_id="fresh")
        store.save_task(old)
        store.save_task(fresh)
        n = server.cleanup_old(max_age_seconds=3600)
        assert n == 1
        assert store.get_task("old") is None
        assert store.get_task("fresh") is not None


class TestConvenience:
    def test_new_task(self):
        t = new_task("my task", target_agent="worker", priority="high")
        assert t.input.get_text() == "my task"
        assert t.meta["target_agent"] == "worker"
        assert t.meta["priority"] == "high"

    def test_new_handoff(self):
        t = new_task("delegate me")
        ho = new_handoff(t, source="a", target="b", reason="overload")
        assert ho.source_agent == "a"
        assert ho.target_agent == "b"
        assert ho.reason == "overload"
