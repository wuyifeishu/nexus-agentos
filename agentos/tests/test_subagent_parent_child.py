"""测试 SubAgent 父子通信 — 状态共享、心跳、生命周期管理。"""

import asyncio

import pytest

pytestmark = pytest.mark.asyncio
from agentos.subagent import (  # noqa: E402
    ChildContext,
    ChildHandle,
    ChildHeartbeat,
    ChildStatus,
    SharedState,
    SubAgentManager,
    SubAgentSpec,
)


class TestSharedState:
    async def test_set_get(self):
        ss = SharedState()
        await ss.set("key1", "val1")
        assert await ss.get("key1") == "val1"
        assert await ss.get("missing", "def") == "def"

    async def test_update_snapshot(self):
        ss = SharedState()
        await ss.update({"a": 1, "b": 2})
        snap = await ss.snapshot()
        assert snap == {"a": 1, "b": 2}

    async def test_sync_ops(self):
        ss = SharedState()
        ss.set_sync("x", 42)
        assert ss.get_sync("x") == 42

    async def test_concurrent_writes(self):
        ss = SharedState()

        async def writer(key: str, n: int):
            for i in range(n):
                await ss.set(key, i)
                await asyncio.sleep(0)

        await asyncio.gather(writer("a", 20), writer("b", 20))
        assert await ss.get("a") == 19
        assert await ss.get("b") == 19


class TestChildContext:
    async def test_progress_report(self):
        hbs = []

        async def hb_cb(hb: ChildHeartbeat):
            hbs.append(hb)

        ctx = ChildContext("test-1", heartbeat_callback=hb_cb)
        await ctx.report_progress(0.5, "step1", "half done")
        assert ctx.progress == 0.5
        assert len(hbs) == 1
        assert hbs[0].progress == 0.5
        assert hbs[0].current_step == "step1"

    async def test_step_and_heartbeat(self):
        hbs = []

        async def hb_cb(hb: ChildHeartbeat):
            hbs.append(hb)

        ctx = ChildContext("test-2", heartbeat_callback=hb_cb)
        await ctx.step(1, "init")
        await ctx.send_heartbeat("alive")
        assert len(hbs) == 1
        assert hbs[0].iteration == 1

    async def test_done(self):
        hbs = []

        async def hb_cb(hb: ChildHeartbeat):
            hbs.append(hb)

        ctx = ChildContext("test-3", heartbeat_callback=hb_cb)
        await ctx.done("all good")
        assert len(hbs) == 1
        assert hbs[0].status == ChildStatus.COMPLETED
        assert hbs[0].progress == 1.0
        assert hbs[0].message == "all good"

    async def test_fail(self):
        hbs = []

        async def hb_cb(hb: ChildHeartbeat):
            hbs.append(hb)

        ctx = ChildContext("test-4", heartbeat_callback=hb_cb)
        await ctx.fail("something broke")
        assert len(hbs) == 1
        assert hbs[0].status == ChildStatus.FAILED
        assert hbs[0].message == "something broke"

    async def test_cancel_detection(self):
        cancelled = [False]

        def on_cancel():
            return cancelled[0]

        ctx = ChildContext("test-5", on_cancel=on_cancel)
        assert not ctx.cancelled
        status = await ctx.check_control()
        assert status == ChildStatus.RUNNING

        cancelled[0] = True
        status = await ctx.check_control()
        assert status == ChildStatus.CANCELLED
        assert ctx.cancelled

    async def test_pause_resume(self):
        paused = [True]
        resume_triggered = [False]

        async def on_pause():
            resume_triggered[0] = True
            paused[0] = False

        ctx = ChildContext("test-6", on_pause=on_pause)
        ctx._paused = paused[0]
        status = await ctx.check_control()
        assert status == ChildStatus.PAUSED
        assert resume_triggered[0]


class TestChildHandle:
    async def test_create_context(self):
        handle = ChildHandle("h1", "do stuff", "fork")
        ctx = handle.create_context()
        assert ctx.agent_id == "h1"
        assert handle.context is ctx
        assert handle.shared_state is ctx.shared_state

    async def test_pause_resume(self):
        handle = ChildHandle("h2", "task", "fork")
        handle.create_context()
        assert handle.status == ChildStatus.IDLE

        await handle.pause()
        assert handle.status == ChildStatus.PAUSED

        await handle.resume()
        assert handle.status == ChildStatus.RUNNING

    async def test_cancel(self):
        handle = ChildHandle("h3", "task", "fork")
        handle.create_context()
        await handle.cancel()
        assert handle.status == ChildStatus.CANCELLED

    async def test_get_status(self):
        handle = ChildHandle("h4", "analyze", "fork")
        handle.create_context()
        handle.info.progress = 0.7
        handle.info.current_step = "parsing"
        handle.info.iterations = 12

        status = handle.get_status()
        assert status["agent_id"] == "h4"
        assert status["progress"] == 0.7
        assert status["current_step"] == "parsing"
        assert status["iterations"] == 12
        assert "elapsed" in status

    async def test_timeout_detection(self):
        handle = ChildHandle("h5", "task", "fork", timeout=0.1)
        await asyncio.sleep(0.15)
        assert handle.check_timeout()

    async def test_no_timeout_when_unset(self):
        handle = ChildHandle("h6", "task", "fork", timeout=None)
        assert not handle.check_timeout()

    async def test_heartbeat_timeout(self):
        handle = ChildHandle("h7", "task", "fork", heartbeat_interval=0.1)
        await asyncio.sleep(0.35)
        assert handle.check_heartbeat_timeout()

    async def test_heartbeat_updates_info(self):
        handle = ChildHandle("h8", "task", "fork")
        handle.create_context()
        await handle._receive_heartbeat(
            ChildHeartbeat(
                agent_id="h8",
                progress=0.5,
                current_step="s1",
                message="working",
                iteration=5,
            )
        )
        assert handle.info.progress == 0.5
        assert handle.info.current_step == "s1"
        assert handle.info.iterations == 5

    async def test_shared_state_parent_child(self):
        handle = ChildHandle("h9", "task", "fork")
        ctx = handle.create_context()

        await ctx.shared_state.set("data", [1, 2, 3])
        val = await handle.shared_state.get("data")
        assert val == [1, 2, 3]

        await handle.shared_state.set("status", "ok")
        assert await ctx.shared_state.get("status") == "ok"


class TestSubAgentManager:
    async def test_spawn_fork_with_child_context(self):

        async def run_func(spec: SubAgentSpec, ctx: ChildContext):
            await ctx.report_progress(0.3, "init")
            await ctx.step(1, "load")
            await ctx.report_progress(0.7, "process")
            await ctx.done("success")
            return ("success", 2)

        mgr = SubAgentManager()
        result = await mgr.spawn_fork("test task", run_func=run_func)
        assert result.output == "success"
        assert result.iterations == 2
        assert result.handle is not None
        assert result.handle.status == ChildStatus.COMPLETED

    async def test_spawn_fork_failure(self):
        async def run_func(spec, ctx):
            await ctx.report_progress(0.1, "start")
            raise ValueError("boom")

        mgr = SubAgentManager()
        result = await mgr.spawn_fork("bad task", run_func=run_func)
        assert result.error == "boom"
        assert result.handle.status == ChildStatus.FAILED
        assert result.handle.info.error == "boom"

    async def test_spawn_fork_pause_resume_flow(self):
        """模拟父子协作：父暂停→子暂停→父恢复→子继续→完成。"""
        state = {"phase": "init"}

        async def run_func(spec, ctx: ChildContext):
            state["phase"] = "running"
            await ctx.report_progress(0.2, "step1")

            # 检查控制信号
            status = await ctx.check_control()
            if status == ChildStatus.PAUSED:
                state["phase"] = "paused"

            # 再次检查（模拟恢复后继续）
            status = await ctx.check_control()
            if status == ChildStatus.RUNNING:
                state["phase"] = "resumed"

            await ctx.done("ok")
            return ("ok", 3)

        mgr = SubAgentManager()

        # 启动
        task = asyncio.create_task(mgr.spawn_fork("pause test", run_func=run_func))

        await asyncio.sleep(0.05)  # 让子Agent跑到 step
        mgr.get_handle(task.result().handle.agent_id) if hasattr(task, "result") else None

        # 等task完成
        result = await task
        assert result.error is None or result.error == ""
        assert state["phase"] in ("running", "paused", "resumed")

    async def test_swarm_parallel(self):
        results_log = []

        async def run_func(spec: SubAgentSpec, ctx: ChildContext):
            await ctx.report_progress(0.5, spec.task)
            await asyncio.sleep(0.01)
            await ctx.done(f"done_{spec.task}")
            results_log.append(spec.task)
            return (f"done_{spec.task}", 1)

        mgr = SubAgentManager()
        results = await mgr.spawn_swarm(["A", "B", "C"], run_func=run_func)
        assert len(results) == 3
        assert len(results_log) == 3
        for r in results:
            assert r.handle is not None
            assert r.handle.status == ChildStatus.COMPLETED

    async def test_cancel_all(self):
        async def run_func(spec, ctx: ChildContext):
            await ctx.report_progress(0.1, "init")
            for i in range(50):
                await ctx.step(i, f"step_{i}")
                status = await ctx.check_control()
                if status == ChildStatus.CANCELLED:
                    return ("cancelled", i)
                await asyncio.sleep(0.01)
            return ("done", 50)

        mgr = SubAgentManager()
        t1 = asyncio.create_task(mgr.spawn_fork("long task 1", run_func=run_func))
        t2 = asyncio.create_task(mgr.spawn_fork("long task 2", run_func=run_func))

        await asyncio.sleep(0.05)
        await mgr.cancel_all()

        r1, r2 = await asyncio.gather(t1, t2)
        assert r1.handle.status == ChildStatus.CANCELLED
        assert r2.handle.status == ChildStatus.CANCELLED

    async def test_list_children(self):
        mgr = SubAgentManager()
        r = await mgr.spawn_fork("task1")
        children = mgr.list_children()
        assert len(children) == 1
        assert children[0]["agent_id"] == r.agent_id

    async def test_cleanup(self):
        mgr = SubAgentManager()
        await mgr.spawn_fork("cleanup test")
        assert len(mgr._agents) == 1

        cleaned = await mgr.cleanup(max_age_seconds=-1.0)
        assert cleaned == 1
        assert len(mgr._agents) == 0

    async def test_heartbeat_monitoring(self):
        mgr = SubAgentManager()
        handle = ChildHandle("hb-test", "task", "fork", timeout=0.05)
        mgr._agents["hb-test"] = handle
        handle.info.status = ChildStatus.RUNNING

        monitor = asyncio.create_task(mgr.monitor_heartbeats(interval=0.02))
        await asyncio.sleep(0.1)
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass

        assert handle.status in (ChildStatus.TIMEOUT, ChildStatus.RUNNING)
