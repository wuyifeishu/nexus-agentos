"""
v1.9.4: LLM-driven Task Decomposer.

Splits complex tasks into sub-task DAGs with dependencies,
assigning each sub-task to appropriate agent roles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import json as _json


_DECOMPOSE_PROMPT = """You are a task decomposition expert. Given a complex task, break it into
a sequence of sub-tasks that can be executed independently or sequentially.

Input task: {task}
Available agents: {agents}

Output a JSON array of sub-tasks. Each sub-task must have:
- "id": unique short string (e.g. "step_1")
- "title": human-readable title
- "description": what this sub-task should accomplish
- "depends_on": list of sub-task IDs that must complete before this one (empty list if none)
- "agent_hint": which agent role is best suited (from the available list, or "any")
- "expected_output": brief description of expected result

Rules:
1. First sub-tasks should have no dependencies
2. Each sub-task should be independently executable
3. Use at most {max_depth} levels of nesting
4. Sub-tasks should be concrete and actionable

Output ONLY the JSON array, no other text.
JSON:"""


@dataclass
class SubTask:
    """A single sub-task in the decomposition DAG."""

    id: str
    title: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    agent_hint: str = "any"
    expected_output: str = ""
    status: str = "pending"  # pending | running | done | failed
    output: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "depends_on": self.depends_on,
            "agent_hint": self.agent_hint,
            "expected_output": self.expected_output,
            "status": self.status,
        }


@dataclass
class Decomposition:
    """Result of task decomposition."""

    original_task: str
    sub_tasks: list[SubTask] = field(default_factory=list)
    total_steps: int = 0


class TaskDecomposer:
    """LLM-driven task decomposition engine.

    Breaks complex tasks into executable sub-task DAGs.
    """

    def __init__(self, max_depth: int = 4, llm_model: str = "gpt-4o-mini"):
        self.max_depth = max_depth
        self._llm_model = llm_model

    def decompose(
        self,
        task: str,
        agents: list[str] | None = None,
    ) -> Decomposition:
        """Decompose a complex task into sub-tasks.

        Args:
            task: The full task description
            agents: List of available agent names for role assignment

        Returns:
            Decomposition with ordered sub-tasks
        """
        agents_list = agents or ["general"]
        agent_str = ", ".join(agents_list)

        prompt = _DECOMPOSE_PROMPT.format(
            task=task,
            agents=agent_str,
            max_depth=self.max_depth,
        )

        # Try LLM-based decomposition first, fall back to rule-based
        result = self._llm_decompose(prompt)
        if result:
            return result

        return self._fallback_decompose(task, agents_list)

    def _llm_decompose(self, prompt: str) -> Decomposition | None:
        """Use LLM to decompose task. Returns None on failure."""
        try:
            import os
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None

            import requests
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self._llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1000,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return None

            text = resp.json()["choices"][0]["message"]["content"]

            # Extract JSON from response
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                return None

            data = _json.loads(text[start:end])
            sub_tasks = []
            for item in data:
                st = SubTask(
                    id=item.get("id", f"step_{len(sub_tasks)+1}"),
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    depends_on=item.get("depends_on", []),
                    agent_hint=item.get("agent_hint", "any"),
                    expected_output=item.get("expected_output", ""),
                )
                sub_tasks.append(st)

            return Decomposition(
                original_task=prompt,
                sub_tasks=sub_tasks,
                total_steps=len(sub_tasks),
            )
        except Exception:
            return None

    def _fallback_decompose(
        self, task: str, agents: list[str]
    ) -> Decomposition:
        """Rule-based fallback when LLM unavailable.

        Splits on explicit delimiters ('then', 'after', numbered steps)
        or uses keyword-based phase decomposition.
        """
        import re

        # Try to split on explicit markers
        markers = re.split(
            r'(?:Step\s*\d+[.:]\s*|\d+\)\s*|(?:then|之后|然后|接着)[,，\s]*|;\s*)',
            task, flags=re.IGNORECASE,
        )
        markers = [m.strip() for m in markers if m.strip()]

        if len(markers) > 1:
            sub_tasks = []
            for i, desc in enumerate(markers):
                st = SubTask(
                    id=f"step_{i+1}",
                    title=desc[:50],
                    description=desc,
                    depends_on=[f"step_{i}"] if i > 0 else [],
                    agent_hint=agents[0] if agents else "any",
                )
                sub_tasks.append(st)
            return Decomposition(
                original_task=task,
                sub_tasks=sub_tasks,
                total_steps=len(sub_tasks),
            )

        # Single task — keyword-based phase decomposition
        phases = []
        task_lower = task.lower()

        if any(k in task_lower for k in ("search", "find", "search for", "搜索", "查找")):
            phases.append(("search", "Search and gather information"))
        if any(k in task_lower for k in ("analyze", "analysis", "分析", "处理")):
            phases.append(("analyze", "Analyze collected information"))
        if any(k in task_lower for k in ("write", "generate", "create", "写", "生成", "创建")):
            phases.append(("generate", "Generate final output"))
        if any(k in task_lower for k in ("code", "implement", "build", "代码", "实现", "开发")):
            phases.append(("implement", "Implement the solution"))
        if any(k in task_lower for k in ("test", "verify", "validate", "测试", "验证")):
            phases.append(("verify", "Verify and validate results"))

        if not phases:
            phases = [("execute", task)]

        sub_tasks = []
        for i, (pid, desc) in enumerate(phases):
            st = SubTask(
                id=f"phase_{i+1}_{pid}",
                title=pid.capitalize(),
                description=desc,
                depends_on=[sub_tasks[-1].id] if sub_tasks else [],
                agent_hint=agents[0] if agents else "any",
            )
            sub_tasks.append(st)

        return Decomposition(
            original_task=task,
            sub_tasks=sub_tasks,
            total_steps=len(sub_tasks),
        )
