"""
Background Task Manager — submit tasks, poll progress, retrieve results.

v1.11.0: Long-running task support with persistent state, progress milestones,
and agent supervision trees.
"""

from agentos.background.task_manager import (
    BackgroundTaskManager,
    BackgroundTask,
    BackgroundTaskStatus,
    BackgroundTaskConfig,
    TaskProgress,
    ProgressPhase,
)

from agentos.background.supervisor import (
    AgentSupervisor,
    SupervisedAgent,
    SupervisorConfig,
    AgentQuota,
    SupervisionEvent,
    SupervisionEventType,
)

__all__ = [
    "BackgroundTaskManager",
    "BackgroundTask",
    "BackgroundTaskStatus",
    "BackgroundTaskConfig",
    "TaskProgress",
    "ProgressPhase",
    "AgentSupervisor",
    "SupervisedAgent",
    "SupervisorConfig",
    "AgentQuota",
    "SupervisionEvent",
    "SupervisionEventType",
]
