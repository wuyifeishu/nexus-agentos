"""
v1.15.1 测试：异步工具执行优化
"""

import asyncio
import time

import pytest

from agentos.tools.async_executor import (
    AsyncToolExecutor,
    CircuitBreaker,
    CircuitBreakerState,
    ExecutionMetrics,
    SmartRetryExecutor,
    execute_tool_with_retry,
    execute_tools_concurrently,
)
from agentos.tools.base import BaseTool, ToolResult


class MockTool(BaseTool):
    """模拟工具用于测试。"""

    def __init__(self, name: str = "mock_tool", delay: float = 0.1, fail: bool = False):
        self.name = name
        self.delay = delay
        self.fail = fail
        self.execution_count = 0

    @property
    def parameters(self) -> dict:
        return {"test_param": {"type": "string", "description": "Test parameter"}}

    async def execute(self, arguments: dict) -> ToolResult:
        """模拟工具执行。"""
        self.execution_count += 1
        await asyncio.sleep(self.delay)

        if self.fail:
            return ToolResult.fail(
                call_id=arguments.get("call_id", "test"),
                error="Mock tool failed"
            )

        return ToolResult.ok(
            call_id=arguments.get("call_id", "test"),
            output=f"Mock tool executed with {arguments}"
        )


class TestExecutionMetrics:
    """测试执行指标。"""

    def test_initial_state(self):
        """测试初始状态。"""
        metrics = ExecutionMetrics(tool_name="test_tool")
        assert metrics.tool_name == "test_tool"
        assert metrics.execution_count == 0
        assert metrics.success_rate == 0.0
        assert metrics.average_execution_time == 0.0

    def test_record_success(self):
        """测试记录成功。"""
        metrics = ExecutionMetrics(tool_name="test_tool")
        metrics.record_success(1.5)

        assert metrics.execution_count == 1
        assert metrics.success_count == 1
        assert metrics.failure_count == 0
        assert metrics.timeout_count == 0
        assert metrics.total_execution_time == 1.5
        assert metrics.last_execution_time == 1.5
        assert metrics.last_error is None
        assert metrics.success_rate == 1.0
        assert metrics.average_execution_time == 1.5

    def test_record_failure(self):
        """测试记录失败。"""
        metrics = ExecutionMetrics(tool_name="test_tool")
        metrics.record_failure(2.0, "Test error")

        assert metrics.execution_count == 1
        assert metrics.success_count == 0
        assert metrics.failure_count == 1
        assert metrics.timeout_count == 0
        assert metrics.total_execution_time == 2.0
        assert metrics.last_execution_time == 2.0
        assert metrics.last_error == "Test error"
        assert metrics.success_rate == 0.0
        assert metrics.average_execution_time == 2.0

    def test_record_timeout(self):
        """测试记录超时。"""
        metrics = ExecutionMetrics(tool_name="test_tool")
        metrics.record_timeout(3.0)

        assert metrics.execution_count == 1
        assert metrics.success_count == 0
        assert metrics.failure_count == 0
        assert metrics.timeout_count == 1
        assert metrics.total_execution_time == 3.0
        assert metrics.last_execution_time == 3.0
        assert metrics.last_error == "timeout"
        assert metrics.success_rate == 0.0
        assert metrics.average_execution_time == 3.0


class TestCircuitBreaker:
    """测试熔断器。"""

    def test_initial_state(self):
        """测试初始状态。"""
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_execute() is True

    def test_record_failure_and_open(self):
        """测试记录失败并熔断。"""
        cb = CircuitBreaker(failure_threshold=3)

        # 记录2次失败
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_execute() is True

        # 第3次失败触发熔断
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.can_execute() is False

    def test_time_until_reset(self):
        """测试熔断恢复时间。"""
        cb = CircuitBreaker(reset_timeout=10.0)

        # 触发熔断
        for _ in range(5):
            cb.record_failure()

        assert cb.state == CircuitBreakerState.OPEN
        time_remaining = cb.time_until_reset
        assert 0 <= time_remaining <= 10.0

    def test_half_open_recovery(self):
        """测试半开状态恢复。"""
        cb = CircuitBreaker(reset_timeout=0.1)  # 短超时便于测试

        # 触发熔断
        for _ in range(5):
            cb.record_failure()

        assert cb.state == CircuitBreakerState.OPEN

        # 等待恢复
        time.sleep(0.15)

        # 应该进入半开状态
        assert cb.can_execute() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # 半开状态成功，恢复正常
        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_half_open_failure(self):
        """测试半开状态失败。"""
        cb = CircuitBreaker(reset_timeout=0.2, half_open_max_attempts=2)  # 增加超时时间

        # 触发熔断
        for _ in range(5):
            cb.record_failure()

        # 等待恢复进入半开状态
        time.sleep(0.25)  # 确保超过超时时间

        # 调用 can_execute 触发状态转换
        can_execute = cb.can_execute()
        assert can_execute is True  # 应该允许执行
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # 第一次失败
        cb.record_failure()
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # 第二次失败，重新熔断
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN


class TestAsyncToolExecutor:
    """测试异步工具执行器。"""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """测试基本执行。"""
        executor = AsyncToolExecutor(max_concurrent=5)
        tool = MockTool()

        result = await executor.execute(tool, {"test": "data"})

        assert result.error is None
        assert result.output.startswith("Mock tool executed")
        assert tool.execution_count == 1

        # 检查指标
        metrics = executor.get_metrics("mock_tool")
        assert metrics is not None
        assert metrics["mock_tool"].execution_count == 1
        assert metrics["mock_tool"].success_count == 1

    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        """测试并发限制。"""
        executor = AsyncToolExecutor(max_concurrent=2)

        # 创建多个慢速工具
        tools = [MockTool(delay=0.2) for _ in range(5)]

        start_time = time.time()
        results = await asyncio.gather(*[
            executor.execute(tool, {"index": i})
            for i, tool in enumerate(tools)
        ])
        end_time = time.time()

        assert len(results) == 5
        assert all(r.error is None for r in results)

        # 由于并发限制为2，执行时间应该大于 0.2 * (5/2) = 0.5秒
        assert end_time - start_time > 0.5

    @pytest.mark.asyncio
    async def test_timeout(self):
        """测试超时。"""
        executor = AsyncToolExecutor(default_timeout=0.1)
        tool = MockTool(delay=0.3)  # 比超时时间长

        result = await executor.execute(tool, {})

        assert result.error is not None
        assert "timed out" in result.error

        # 检查指标
        metrics = executor.get_metrics("mock_tool")
        assert metrics["mock_tool"].timeout_count == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker(self):
        """测试熔断器。"""
        executor = AsyncToolExecutor(enable_circuit_breaker=True)
        tool = MockTool(fail=True)  # 总是失败

        # 执行多次，触发熔断
        for i in range(6):
            result = await executor.execute(tool, {"attempt": i})
            assert result.error is not None

        # 检查熔断器状态
        state = executor.get_circuit_breaker_state("mock_tool")
        assert state == CircuitBreakerState.OPEN

        # 再次执行应该被熔断器拒绝
        result = await executor.execute(tool, {"attempt": 6})
        assert "Circuit breaker is OPEN" in result.error

    @pytest.mark.asyncio
    async def test_batch_execution(self):
        """测试批量执行。"""
        executor = AsyncToolExecutor(max_concurrent=3)

        # 创建工具调用列表
        tool_calls = [
            (MockTool(name=f"tool_{i}"), {"index": i})
            for i in range(5)
        ]

        results = await executor.execute_batch(tool_calls)

        assert len(results) == 5
        assert all(r.error is None for r in results)

        # 检查所有工具的指标
        metrics = executor.get_metrics()
        assert len(metrics) == 5
        for i in range(5):
            assert f"tool_{i}" in metrics

    @pytest.mark.asyncio
    async def test_tool_specific_timeout(self):
        """测试工具特定超时。"""
        executor = AsyncToolExecutor(default_timeout=1.0)

        # 为特定工具设置短超时
        executor.set_tool_timeout("fast_tool", 0.1)
        executor.set_tool_timeout("slow_tool", 0.1)  # 设置短超时，让慢速工具超时

        # 快速工具应该成功
        fast_tool = MockTool(name="fast_tool", delay=0.05)
        result = await executor.execute(fast_tool, {})
        assert result.error is None

        # 慢速工具应该超时
        slow_tool = MockTool(name="slow_tool", delay=0.3)
        result = await executor.execute(slow_tool, {})
        assert result.error is not None
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """测试优雅关闭。"""
        executor = AsyncToolExecutor(max_concurrent=2)

        # 启动一些长时间运行的任务
        long_tool = MockTool(delay=1.0)
        tasks = [
            asyncio.create_task(executor.execute(long_tool, {"task": i}))
            for i in range(3)
        ]

        # 等待任务开始
        await asyncio.sleep(0.1)

        # 关闭执行器
        await executor.shutdown(timeout=0.5)

        # 检查任务状态
        for task in tasks:
            if not task.done():
                task.cancel()

        # 执行器应该已关闭
        assert executor.active_task_count == 0


class TestSmartRetryExecutor:
    """测试智能重试执行器。"""

    @pytest.mark.asyncio
    async def test_success_without_retry(self):
        """测试成功执行无需重试。"""
        retry_executor = SmartRetryExecutor(max_retries=3)
        tool = MockTool()  # 正常工具

        result = await retry_executor.execute_with_retry(
            tool=tool,
            arguments={"test": "data"}
        )

        assert result.error is None
        assert tool.execution_count == 1  # 只执行一次

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """测试失败时重试。"""
        retry_executor = SmartRetryExecutor(max_retries=2)

        # 创建失败2次后成功的工具
        fail_count = 0
        class FlakyTool(BaseTool):
            @property
            def parameters(self) -> dict:
                return {}

            async def execute(self, arguments):
                nonlocal fail_count
                fail_count += 1
                await asyncio.sleep(0.05)
                if fail_count <= 2:
                    return ToolResult.fail(call_id="test", error="Flaky")
                return ToolResult.ok(call_id="test", output="ok")

        tool = FlakyTool()
        result = await retry_executor.execute_with_retry(tool, {})

        assert result.error is None
        assert fail_count == 3  # 失败2次 + 成功1次

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """测试超过最大重试次数。"""
        retry_executor = SmartRetryExecutor(max_retries=2)
        tool = MockTool(fail=True)  # 总是失败

        result = await retry_executor.execute_with_retry(tool, {})

        assert result.error is not None
        assert tool.execution_count == 3  # 初始 + 2次重试

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """测试指数退避。"""
        retry_executor = SmartRetryExecutor(
            max_retries=2,
            retry_delay=0.1,
            backoff_factor=2.0
        )

        execution_times = []
        class TimingTool(BaseTool):
            @property
            def parameters(self) -> dict:
                return {}

            async def execute(self, arguments):
                execution_times.append(time.time())
                await asyncio.sleep(0.01)
                return ToolResult.fail(call_id="test", error="Always fail")

        tool = TimingTool()
        await retry_executor.execute_with_retry(tool, {})

        # 检查执行时间间隔
        assert len(execution_times) == 3  # 初始 + 2次重试

        # 计算间隔
        intervals = [
            execution_times[i+1] - execution_times[i]
            for i in range(len(execution_times)-1)
        ]

        # 间隔应该接近 0.1 和 0.2 秒（考虑误差）
        assert 0.09 <= intervals[0] <= 0.15
        assert 0.19 <= intervals[1] <= 0.25


class TestConvenienceFunctions:
    """测试便捷函数。"""

    @pytest.mark.asyncio
    async def test_execute_tool_with_retry(self):
        """测试带重试的工具执行函数。"""
        # 创建失败1次后成功的工具
        fail_once = [True]
        class RetryTool(BaseTool):
            @property
            def parameters(self) -> dict:
                return {}

            async def execute(self, arguments):
                await asyncio.sleep(0.05)
                if fail_once[0]:
                    fail_once[0] = False
                    return ToolResult.fail(call_id="test", error="First fail")
                return ToolResult.ok(call_id="test", output="ok")

        tool = RetryTool()
        result = await execute_tool_with_retry(tool, {}, max_retries=3)

        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_tools_concurrently(self):
        """测试并发执行工具函数。"""
        # 创建多个工具
        tools = [MockTool(delay=0.1) for _ in range(3)]
        tool_calls = [(tool, {"index": i}) for i, tool in enumerate(tools)]

        results = await execute_tools_concurrently(
            tool_calls=tool_calls,
            max_concurrent=2
        )

        assert len(results) == 3
        assert all(r.error is None for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
