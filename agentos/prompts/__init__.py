"""AgentOS Prompt Management — v1.2.7 / v1.3.12.

- PromptTemplate: 参数化模板，变量注入 + 版本管理。
- PromptRegistry: 全局注册中心，按名称/标签检索。
- PromptOptimizer: DSPy-inspired 自动提示词优化。
- FewShotSelector: 智能 few-shot 示例选择与格式化。
"""

from agentos.prompts.manager import PromptTemplate, PromptRegistry
from agentos.prompts.optimizer import (
    PromptOptimizer,
    OptimizerConfig,
    OptimizationStrategy,
    OptimizationResult,
    PromptCandidate,
)
from agentos.prompts.few_shot import (
    FewShotSelector,
    Example,
    SelectionStrategy,
    build_examples,
)

__all__ = [
    "PromptTemplate",
    "PromptRegistry",
    "PromptOptimizer",
    "OptimizerConfig",
    "OptimizationStrategy",
    "OptimizationResult",
    "PromptCandidate",
    "FewShotSelector",
    "Example",
    "SelectionStrategy",
    "build_examples",
]
