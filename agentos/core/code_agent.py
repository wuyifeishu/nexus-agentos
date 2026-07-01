"""
AgentOS v1.1.9 — CodeAgent 模式。

基因来源: Smolagents CodeAgent (HuggingFace)

CodeAgent 允许 Agent 通过生成和执行 Python 代码来完成子任务，
而非仅调用预定义工具。代码可以调用已注册的 tools + 安全内置函数。

特性:
- 多步执行：生成代码 → 执行 → 观察结果 → 继续
- 安全沙箱：白名单模块、禁止危险操作、超时控制
- Tools 集成：代码中直接调用 `tool_name(args)`
- 内存持久：跨步骤的变量和结果通过 locals 传递
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentos.models.router import ModelRouter


# ── 安全常量 ───────────────────────────────────

DEFAULT_ALLOWED_MODULES = frozenset({
    "math", "json", "re", "datetime", "collections",
    "itertools", "functools", "typing", "dataclasses",
    "decimal", "fractions", "statistics", "random",
    "string", "textwrap", "unicodedata", "hashlib",
    "base64", "binascii", "uuid", "copy", "pprint",
    "enum", "pathlib", "logging", "warnings",
    "csv", "html", "urllib.parse", "xml.etree.ElementTree",
    "operator", "heapq", "bisect", "array",
    "struct", "io", "os.path",
})

FORBIDDEN_CALLS = frozenset({
    "exec", "eval", "compile", "open", "__import__",
    "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars",
    "breakpoint", "input",
    "os", "subprocess", "shutil", "sys",
    "ctypes", "socket", "pickle", "marshal",
    "multiprocessing", "threading", "signal",
})

MAX_OUTPUT_LENGTH = 10000


# ── 数据结构 ───────────────────────────────────

@dataclass
class CodeStep:
    """CodeAgent 单步执行记录。"""

    step: int
    code: str
    result: Any = None
    stdout: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class CodeResult:
    """CodeAgent 执行结果。"""

    success: bool
    final_answer: Any = None
    steps: List[CodeStep] = field(default_factory=list)
    total_duration_ms: float = 0.0
    error: Optional[str] = None


# ── 代码安全检查器 ─────────────────────────────

class CodeGuard(ast.NodeVisitor):
    """Python 代码 AST 安全扫描器，拦截危险操作。"""

    def __init__(self, allowed_modules: frozenset):
        self.allowed_modules = allowed_modules
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in self.allowed_modules:
                self.violations.append(f"import '{alias.name}' not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        base = module.split(".")[0]
        if base not in self.allowed_modules:
            self.violations.append(f"import from '{module}' not allowed")

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                self.violations.append(f"call to '{node.func.id}()' is forbidden")
        elif isinstance(node.func, ast.Attribute):
            parts = []
            curr = node.func
            while isinstance(curr, ast.Attribute):
                parts.append(curr.attr)
                curr = curr.value
            if isinstance(curr, ast.Name):
                full = f"{curr.id}.{'.'.join(reversed(parts))}"
                for forbidden in FORBIDDEN_CALLS:
                    if full.startswith(forbidden):
                        self.violations.append(f"call to '{full}()' is forbidden")
                        break
        self.generic_visit(node)


def scan_code(code: str, allowed_modules: frozenset) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    guard = CodeGuard(allowed_modules)
    guard.visit(tree)
    return guard.violations


# ── 受控执行环境 ───────────────────────────────

def safe_exec(
    code: str,
    tools: Dict[str, Callable],
    state: Dict[str, Any],
    timeout: float,
) -> Tuple[Any, str, Optional[str]]:
    from io import StringIO

    stdout_capture = StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture
    result = None
    error = None

    try:
        exec_globals = {"__builtins__": __builtins__}
        exec_globals.update(tools)
        exec_globals.update({
            "print": lambda *a, **kw: print(*a, **kw),
            "__result__": None,
            "state": state,
        })
        compiled = compile(code, "<code_agent>", "exec")
        exec(compiled, exec_globals)
        result = exec_globals.get("__result__")
        for key in list(exec_globals.keys()):
            if key.startswith("_") or key in tools or key in ("state", "print"):
                continue
            if key not in ("__builtins__",):
                state.setdefault("_vars", {})[key] = exec_globals[key]
    except Exception as e:
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
    finally:
        sys.stdout = old_stdout

    stdout = stdout_capture.getvalue()
    if len(stdout) > MAX_OUTPUT_LENGTH:
        stdout = stdout[:MAX_OUTPUT_LENGTH] + "\n... [truncated]"
    return result, stdout, error


# ── 代码生成 Prompt ─────────────────────────────

CODE_AGENT_SYSTEM_PROMPT = """You are a CodeAgent that solves tasks by writing and executing Python code.

YOU MUST respond ONLY with Python code inside ```python ... ``` blocks.
NO explanations, NO markdown outside the code block. Just the code.

Available tools (callable as functions):
{tools_description}

To output the final answer, assign it to the variable `__result__`.
You can store persistent data in the `state` dict.

Example:
```python
# Use tools
data = web_search("Python 3.12 release date")
# Compute
result = len(data)
# Return
__result__ = f"Found {{result}} results"
```

Now solve the following task. ONLY output the code block."""


# ── CodeAgent ───────────────────────────────────

class CodeAgent:
    """代码执行型 Agent。"""

    def __init__(
        self,
        tools: List[Callable] | None = None,
        model: str = "gpt-4o",
        max_steps: int = 10,
        timeout_per_step: float = 30.0,
        allowed_modules: frozenset = DEFAULT_ALLOWED_MODULES,
    ):
        self.model = model
        self.max_steps = max_steps
        self.timeout_per_step = timeout_per_step
        self.allowed_modules = allowed_modules
        self._tools: Dict[str, Callable] = {}
        if tools:
            for tool in tools:
                self._tools[tool.__name__] = tool

    @property
    def tools(self) -> Dict[str, Callable]:
        return self._tools

    def _tools_description(self) -> str:
        lines = []
        for name, fn in self._tools.items():
            sig = str(inspect.signature(fn))
            doc = (inspect.getdoc(fn) or "No description").split("\n")[0]
            lines.append(f"  {name}{sig}: {doc}")
        return "\n".join(lines) if lines else "  (no tools available)"

    async def run(self, task: str, state: Dict[str, Any] | None = None) -> CodeResult:
        if state is None:
            state = {"_vars": {}}
        tools_desc = self._tools_description()
        steps: List[CodeStep] = []
        total_start = asyncio.get_event_loop().time()

        for step_num in range(1, self.max_steps + 1):
            if step_num == 1:
                user_prompt = task
            else:
                last = steps[-1]
                if last.error:
                    feedback = f"Error: {last.error}"
                else:
                    rp = str(last.result)[:500] if last.result is not None else "None"
                    op = last.stdout[:500] if last.stdout else ""
                    feedback = f"Output: {op}\nResult: {rp}"
                user_prompt = f"Step {step_num}: Continue.\nPrevious result:\n{feedback}\n\nTask: {task}"

            router = ModelRouter()
            try:
                response = await router.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": CODE_AGENT_SYSTEM_PROMPT.format(tools_description=tools_desc)},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=2048,
                )
            except Exception as e:
                return CodeResult(
                    success=False, steps=steps,
                    total_duration_ms=(asyncio.get_event_loop().time() - total_start) * 1000,
                    error=f"LLM error: {e}",
                )

            code = self._extract_code(response.content)
            if not code:
                if steps:
                    return CodeResult(
                        success=True, final_answer=steps[-1].result, steps=steps,
                        total_duration_ms=(asyncio.get_event_loop().time() - total_start) * 1000,
                    )
                continue

            violations = scan_code(code, self.allowed_modules)
            if violations:
                steps.append(CodeStep(step=step_num, code=code,
                            error=f"Security violation: {'; '.join(violations)}"))
                continue

            step_start = asyncio.get_event_loop().time()
            try:
                loop = asyncio.get_event_loop()
                result, stdout, error = await asyncio.wait_for(
                    loop.run_in_executor(None, safe_exec, code, self._tools, state, self.timeout_per_step),
                    timeout=self.timeout_per_step + 5,
                )
            except asyncio.TimeoutError:
                result, stdout, error = None, "", "TimeoutError: exceeded limit"

            step_duration = (asyncio.get_event_loop().time() - step_start) * 1000
            cs = CodeStep(step=step_num, code=code, result=result, stdout=stdout, error=error, duration_ms=step_duration)
            steps.append(cs)

            if error:
                continue

            if "__result__" in code or (result is not None and "__result__" in code):
                return CodeResult(
                    success=True, final_answer=result, steps=steps,
                    total_duration_ms=(asyncio.get_event_loop().time() - total_start) * 1000,
                )

            # heuristic: non-trivial result without error = likely done
            if result is not None and step_num >= 1:
                return CodeResult(
                    success=True, final_answer=result, steps=steps,
                    total_duration_ms=(asyncio.get_event_loop().time() - total_start) * 1000,
                )

        return CodeResult(
            success=False, final_answer=steps[-1].result if steps else None, steps=steps,
            total_duration_ms=(asyncio.get_event_loop().time() - total_start) * 1000,
            error=f"Max steps ({self.max_steps}) reached",
        )

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        if "```python" in content:
            parts = content.split("```python", 1)
            if len(parts) > 1:
                return parts[1].split("```", 1)[0].strip()
        if "```" in content:
            parts = content.split("```", 1)
            if len(parts) > 1:
                return parts[1].split("```", 1)[0].strip()
        if "print(" in content or "def " in content or "result" in content:
            return content.strip()
        return None
