"""
v1.15.1 — 异步工具执行优化：并发控制 + 超时熔断 + 性能监控。

核心功能：
1. 并发执行控制：限制同时执行的工具数量
2. 超时熔断：工具执行超时自动中断
3. 性能监控：记录工具执行时间、成功率
4. 智能重试：根据错误类型自动重试
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from concurrent.futures import TimeoutError as FutureTimeoutError

from .base import BaseTool, ToolResult, ToolCall
from .validation import ToolErrorClassifier, ErrorCategory


class ExecutionStatus(str, Enum):
    """工具执行状态。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CircuitBreakerState(str, Enum):
    """熔断器状态。"""
    CLOSED = "closed"      # 正常状态，允许执行
    OPEN = "open"          # 熔断状态，拒绝执行
    HALF_OPEN = "half_open"  # 半开状态，尝试恢复


@dataclass
class ExecutionMetrics:
    """工具执行性能指标。"""
    tool_name: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_execution_time: float = 0.0
    last_execution_time: float = 0.0
    last_error: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count
    
    @property
    def average_execution_time(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.total_execution_time / self.execution_count
    
    def record_success(self, execution_time: float) -> None:
        self.execution_count += 1
        self.success_count += 1
        self.total_execution_time += execution_time
        self.last_execution_time = execution_time
        self.last_error = None
    
    def record_failure(self, execution_time: float, error: str) -> None:
        self.execution_count += 1
        self.failure_count += 1
        self.total_execution_time += execution_time
        self.last_execution_time = execution_time
        self.last_error = error
    
    def record_timeout(self, execution_time: float) -> None:
        self.execution_count += 1
        self.timeout_count += 1
        self.total_execution_time += execution_time
        self.last_execution_time = execution_time
        self.last_error = "timeout"


@dataclass
class CircuitBreaker:
    """熔断器：防止工具持续失败。"""
    
    failure_threshold: int = 5          # 连续失败次数阈值
    reset_timeout: float = 30.0        # 熔断恢复时间（秒）
    half_open_max_attempts: int = 3    # 半开状态最大尝试次数
    
    _state: CircuitBreakerState = field(default=CircuitBreakerState.CLOSED)
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_attempts: int = 0
    
    def can_execute(self) -> bool:
        """检查是否允许执行。"""
        current_time = time.time()
        
        if self._state == CircuitBreakerState.OPEN:
            # 检查是否应该进入半开状态
            if current_time - self._last_failure_time >= self.reset_timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_attempts = 0
                self._failure_count = 0  # 重置失败计数
                return True
            return False
        
        elif self._state == CircuitBreakerState.HALF_OPEN:
            if self._half_open_attempts >= self.half_open_max_attempts:
                return False
            return True
        
        return True  # CLOSED 状态
    
    def record_success(self) -> None:
        """记录成功执行。"""
        if self._state == CircuitBreakerState.HALF_OPEN:
            # 半开状态成功，恢复正常
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._half_open_attempts = 0
        else:
            self._failure_count = 0
    
    def record_failure(self) -> None:
        """记录失败执行。"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._half_open_attempts += 1
            # 半开状态失败，重新熔断
            if self._half_open_attempts >= self.half_open_max_attempts:
                self._state = CircuitBreakerState.OPEN
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitBreakerState.OPEN
    
    @property
    def state(self) -> CircuitBreakerState:
        return self._state
    
    @property
    def time_until_reset(self) -> float:
        """距离熔断恢复的剩余时间。"""
        if self._state != CircuitBreakerState.OPEN:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self.reset_timeout - elapsed)


class AsyncToolExecutor:
    """异步工具执行器，支持并发控制和熔断。"""
    
    def __init__(
        self,
        max_concurrent: int = 10,
        default_timeout: float = 30.0,
        enable_circuit_breaker: bool = True
    ):
        """
        初始化异步工具执行器。
        
        Args:
            max_concurrent: 最大并发执行数
            default_timeout: 默认执行超时时间（秒）
            enable_circuit_breaker: 是否启用熔断器
        """
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self.enable_circuit_breaker = enable_circuit_breaker
        
        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Set[asyncio.Task] = set()
        
        # 性能监控
        self._metrics: Dict[str, ExecutionMetrics] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # 工具超时配置
        self._tool_timeouts: Dict[str, float] = {}
    
    def set_tool_timeout(self, tool_name: str, timeout: float) -> None:
        """为特定工具设置超时时间。"""
        self._tool_timeouts[tool_name] = timeout
    
    def get_tool_timeout(self, tool_name: str) -> float:
        """获取工具的超时时间。"""
        return self._tool_timeouts.get(tool_name, self.default_timeout)
    
    def _get_or_create_metrics(self, tool_name: str) -> ExecutionMetrics:
        """获取或创建性能指标。"""
        if tool_name not in self._metrics:
            self._metrics[tool_name] = ExecutionMetrics(tool_name=tool_name)
        return self._metrics[tool_name]
    
    def _get_or_create_circuit_breaker(self, tool_name: str) -> CircuitBreaker:
        """获取或创建熔断器。"""
        if tool_name not in self._circuit_breakers:
            self._circuit_breakers[tool_name] = CircuitBreaker()
        return self._circuit_breakers[tool_name]
    
    async def execute(
        self,
        tool: BaseTool,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> ToolResult:
        """
        异步执行工具。
        
        Args:
            tool: 要执行的工具
            arguments: 工具参数
            call_id: 调用ID（可选）
            timeout: 超时时间（可选，覆盖默认值）
        
        Returns:
            ToolResult: 工具执行结果
        """
        if call_id is None:
            call_id = f"call_{int(time.time() * 1000)}"
        
        tool_name = tool.name or tool.__class__.__name__
        
        # 检查熔断器
        if self.enable_circuit_breaker:
            circuit_breaker = self._get_or_create_circuit_breaker(tool_name)
            if not circuit_breaker.can_execute():
                return ToolResult.fail(
                    call_id=call_id,
                    error=f"Circuit breaker is OPEN for tool '{tool_name}'. "
                          f"Try again in {circuit_breaker.time_until_reset:.1f}s."
                )
        
        # 获取超时时间
        exec_timeout = timeout or self.get_tool_timeout(tool_name)
        
        # 获取性能指标
        metrics = self._get_or_create_metrics(tool_name)
        
        # 创建任务
        task = asyncio.create_task(
            self._execute_with_semaphore(
                tool=tool,
                arguments=arguments,
                call_id=call_id,
                timeout=exec_timeout,
                tool_name=tool_name,
                metrics=metrics
            )
        )
        
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        
        try:
            return await task
        except asyncio.CancelledError:
            return ToolResult.fail(call_id=call_id, error="Execution cancelled")
    
    async def _execute_with_semaphore(
        self,
        tool: BaseTool,
        arguments: Dict[str, Any],
        call_id: str,
        timeout: float,
        tool_name: str,
        metrics: ExecutionMetrics
    ) -> ToolResult:
        """使用信号量控制并发执行。"""
        start_time = time.time()
        
        async with self._semaphore:
            try:
                # 执行工具（带超时）
                result = await asyncio.wait_for(
                    tool.execute(arguments),
                    timeout=timeout
                )
                
                execution_time = time.time() - start_time
                
                # 检查结果是否失败
                if result.error is not None:
                    # 工具执行失败
                    metrics.record_failure(execution_time, result.error)
                    if self.enable_circuit_breaker:
                        circuit_breaker = self._get_or_create_circuit_breaker(tool_name)
                        circuit_breaker.record_failure()
                else:
                    # 工具执行成功
                    metrics.record_success(execution_time)
                    if self.enable_circuit_breaker:
                        circuit_breaker = self._get_or_create_circuit_breaker(tool_name)
                        circuit_breaker.record_success()
                
                return result
                
            except asyncio.TimeoutError:
                execution_time = time.time() - start_time
                metrics.record_timeout(execution_time)
                
                if self.enable_circuit_breaker:
                    circuit_breaker = self._get_or_create_circuit_breaker(tool_name)
                    circuit_breaker.record_failure()
                
                return ToolResult.fail(
                    call_id=call_id,
                    error=f"Tool '{tool_name}' execution timed out after {timeout}s"
                )
                
            except Exception as e:
                execution_time = time.time() - start_time
                error_msg = str(e)
                metrics.record_failure(execution_time, error_msg)
                
                if self.enable_circuit_breaker:
                    circuit_breaker = self._get_or_create_circuit_breaker(tool_name)
                    circuit_breaker.record_failure()
                
                return ToolResult.fail(call_id=call_id, error=error_msg)
    
    async def execute_batch(
        self,
        tool_calls: List[Tuple[BaseTool, Dict[str, Any]]],
        max_batch_size: Optional[int] = None,
        timeout_per_tool: Optional[float] = None
    ) -> List[ToolResult]:
        """
        批量执行工具。
        
        Args:
            tool_calls: 工具调用列表 [(tool, arguments), ...]
            max_batch_size: 最大批量大小（None表示无限制）
            timeout_per_tool: 每个工具的超时时间
        
        Returns:
            List[ToolResult]: 工具执行结果列表
        """
        if max_batch_size is not None:
            # 分批执行
            results = []
            for i in range(0, len(tool_calls), max_batch_size):
                batch = tool_calls[i:i + max_batch_size]
                batch_results = await asyncio.gather(*[
                    self.execute(tool, args, timeout=timeout_per_tool)
                    for tool, args in batch
                ])
                results.extend(batch_results)
            return results
        else:
            # 并发执行所有工具
            tasks = [
                self.execute(tool, args, timeout=timeout_per_tool)
                for tool, args in tool_calls
            ]
            return await asyncio.gather(*tasks)
    
    def get_metrics(self, tool_name: Optional[str] = None) -> Dict[str, ExecutionMetrics]:
        """获取性能指标。"""
        if tool_name:
            return {tool_name: self._metrics.get(tool_name)}
        return self._metrics.copy()
    
    def get_circuit_breaker_state(self, tool_name: str) -> Optional[CircuitBreakerState]:
        """获取熔断器状态。"""
        if tool_name in self._circuit_breakers:
            return self._circuit_breakers[tool_name].state
        return None
    
    def reset_circuit_breaker(self, tool_name: str) -> bool:
        """重置指定工具的熔断器。"""
        if tool_name in self._circuit_breakers:
            self._circuit_breakers[tool_name] = CircuitBreaker()
            return True
        return False
    
    def reset_all_circuit_breakers(self) -> None:
        """重置所有熔断器。"""
        self._circuit_breakers.clear()
    
    async def shutdown(self, timeout: float = 5.0) -> None:
        """优雅关闭执行器。"""
        # 取消所有正在执行的任务
        for task in self._active_tasks.copy():
            task.cancel()
        
        # 等待任务完成或超时
        if self._active_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._active_tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                pass
    
    @property
    def active_task_count(self) -> int:
        """当前活跃任务数量。"""
        return len(self._active_tasks)
    
    @property
    def available_slots(self) -> int:
        """可用并发槽位数量。"""
        return self.max_concurrent - self.active_task_count


class SmartRetryExecutor:
    """智能重试执行器：根据错误类型自动重试。"""
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
        retryable_categories: Optional[List[ErrorCategory]] = None
    ):
        """
        初始化智能重试执行器。
        
        Args:
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟（秒）
            backoff_factor: 退避因子
            retryable_categories: 可重试的错误类别
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.backoff_factor = backoff_factor
        
        if retryable_categories is None:
            self.retryable_categories = [
                ErrorCategory.NETWORK,
                ErrorCategory.TIMEOUT,
                ErrorCategory.RATE_LIMIT,
                ErrorCategory.UNKNOWN
            ]
        else:
            self.retryable_categories = retryable_categories
    
    async def execute_with_retry(
        self,
        tool: BaseTool,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
        base_executor: Optional[AsyncToolExecutor] = None
    ) -> ToolResult:
        """
        带智能重试的工具执行。
        
        Args:
            tool: 要执行的工具
            arguments: 工具参数
            call_id: 调用ID
            base_executor: 基础执行器（可选）
        
        Returns:
            ToolResult: 最终执行结果
        """
        if call_id is None:
            call_id = f"retry_{int(time.time() * 1000)}"
        
        if base_executor is None:
            base_executor = AsyncToolExecutor()
        
        last_result = None
        delay = self.retry_delay
        
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # 等待重试延迟
                await asyncio.sleep(delay)
                delay *= self.backoff_factor  # 指数退避
            
            # 执行工具
            result = await base_executor.execute(
                tool=tool,
                arguments=arguments,
                call_id=f"{call_id}_attempt{attempt}"
            )
            
            if result.error is None:
                # 执行成功
                return result
            
            # 检查是否可重试
            last_result = result
            error_category = ToolErrorClassifier.classify(result)
            
            if error_category not in self.retryable_categories:
                # 不可重试的错误
                break
            
            if attempt == self.max_retries:
                # 达到最大重试次数
                break
        
        # 返回最后一次失败的结果
        return last_result or ToolResult.fail(
            call_id=call_id,
            error="Execution failed after retries"
        )


# 便捷函数
async def execute_tool_with_retry(
    tool: BaseTool,
    arguments: Dict[str, Any],
    max_retries: int = 3,
    call_id: Optional[str] = None
) -> ToolResult:
    """
    带重试的工具执行便捷函数。
    
    Args:
        tool: 要执行的工具
        arguments: 工具参数
        max_retries: 最大重试次数
        call_id: 调用ID
    
    Returns:
        ToolResult: 执行结果
    """
    executor = SmartRetryExecutor(max_retries=max_retries)
    return await executor.execute_with_retry(tool, arguments, call_id)


async def execute_tools_concurrently(
    tool_calls: List[Tuple[BaseTool, Dict[str, Any]]],
    max_concurrent: int = 10,
    timeout_per_tool: Optional[float] = None
) -> List[ToolResult]:
    """
    并发执行多个工具的便捷函数。
    
    Args:
        tool_calls: 工具调用列表
        max_concurrent: 最大并发数
        timeout_per_tool: 每个工具的超时时间
    
    Returns:
        List[ToolResult]: 执行结果列表
    """
    executor = AsyncToolExecutor(max_concurrent=max_concurrent)
    return await executor.execute_batch(
        tool_calls=tool_calls,
        timeout_per_tool=timeout_per_tool
    )