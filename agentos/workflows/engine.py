"""
AgentOS v0.20 预设工作流模板。
开箱即用的 Agent 协作模式。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkflowType(StrEnum):
    """工作流类型枚举。"""

    CODE_REVIEW = "code_review"
    RESEARCH = "research"
    DEBATE = "debate"
    QA = "qa"
    CUSTOM = "custom"


@dataclass
class WorkflowStep:
    """工作流步骤定义。"""

    agent_role: str
    instruction: str
    input_from: int | None = None  # 上一步的index，None=原始输入
    parallel: bool = False


@dataclass
class Workflow:
    """预设工作流定义。"""

    name: str
    workflow_type: WorkflowType
    steps: list[WorkflowStep]
    max_rounds: int = 5
    auto_merge: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 内置工作流 ──────────────────────────────────

CODE_REVIEW = Workflow(
    name="代码审查",
    workflow_type=WorkflowType.CODE_REVIEW,
    steps=[
        WorkflowStep("architect", "审查代码架构和设计模式"),
        WorkflowStep("security_expert", "审查安全漏洞和注入风险"),
        WorkflowStep("performance_expert", "审查性能瓶颈和资源消耗"),
        WorkflowStep("reviewer", "综合以上意见，输出最终审查报告"),
    ],
    max_rounds=1,
)


RESEARCH = Workflow(
    name="深度调研",
    workflow_type=WorkflowType.RESEARCH,
    steps=[
        WorkflowStep("researcher", "搜索并收集相关资料", parallel=False),
        WorkflowStep("analyst", "分析数据并提取关键insights", input_from=0),
        WorkflowStep("synthesizer", "综合所有发现，撰写调研报告", input_from=1),
    ],
    max_rounds=1,
)


DEBATE = Workflow(
    name="辩证讨论",
    workflow_type=WorkflowType.DEBATE,
    steps=[
        WorkflowStep("proponent", "提出论点并给出论据"),
        WorkflowStep("opponent", "反驳对方论点，指出逻辑漏洞", input_from=0),
        WorkflowStep("judge", "综合双方观点，给出平衡结论", input_from=1),
    ],
    max_rounds=3,
)


QA = Workflow(
    name="智能问答",
    workflow_type=WorkflowType.QA,
    steps=[
        WorkflowStep("retriever", "从知识库检索相关信息"),
        WorkflowStep("reasoner", "基于检索结果进行推理回答", input_from=0),
        WorkflowStep("verifier", "验证答案准确性并修正", input_from=1),
    ],
    max_rounds=2,
)


BUILTIN_WORKFLOWS: dict[WorkflowType, Workflow] = {
    WorkflowType.CODE_REVIEW: CODE_REVIEW,
    WorkflowType.RESEARCH: RESEARCH,
    WorkflowType.DEBATE: DEBATE,
    WorkflowType.QA: QA,
}


class WorkflowEngine:
    """工作流引擎 — 按预设步骤调度多个Agent协作。"""

    def __init__(self, workflow: Workflow, agent_factory: Callable[[str], Any]):
        self.workflow = workflow
        self.agent_factory = agent_factory
        self._results: dict[int, Any] = {}

    async def execute(self, input_text: str, context: dict | None = None) -> str:
        """执行工作流。"""

        last_output = input_text
        for round_idx in range(self.workflow.max_rounds):
            for step_idx, step in enumerate(self.workflow.steps):
                if step.input_from is not None:
                    feed = self._results.get(step.input_from, input_text)
                else:
                    feed = input_text if round_idx == 0 else last_output

                agent = self.agent_factory(step.agent_role)
                full_prompt = f"""你是一名{step.agent_role}。

输入内容:
{feed}

任务:
{step.instruction}

请直接给出你的分析和结论。"""

                result = await agent.run(full_prompt, context=context or {})
                self._results[step_idx] = result.get("output", str(result))
                last_output = self._results[step_idx]

            if self.workflow.auto_merge:
                break  # 单轮工作流

        if self.workflow.auto_merge:
            return self._results.get(len(self.workflow.steps) - 1, last_output)

        return last_output
