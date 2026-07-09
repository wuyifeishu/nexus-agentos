"""AgentOS Security — Sandbox, Guardrails, Safety.

v1.9.9: Security guardrails with input/output filtering, PII detection, content safety.
"""

from agentos.security.auditor import (
    AuditFinding,
    AuditReport,
    SecurityAuditor,
)
from agentos.security.guard import (
    ContentSafetyFilter,
    GuardAction,
    GuardChainResult,
    GuardPipeline,
    GuardResult,
    InputGuard,
    OutputGuard,
    PIIDetector,
    Severity,
    create_permissive_guard,
    create_strict_guard,
)
from agentos.security.sandbox import (
    LLMSafetyAnalyzer,
    RiskLevel,
    SafetyReport,
    Sandbox,
    SandboxManager,
)
from agentos.security.sandbox_executor import (
    DockerSandbox,
    ProcessSandbox,
    SandboxExecutor,
    SandboxMode,
    SandboxResult,
)

__all__ = [
    # Sandbox
    "SandboxExecutor",
    "SandboxMode",
    "SandboxResult",
    "ProcessSandbox",
    "DockerSandbox",
    # Guardrails (v1.9.9)
    "GuardPipeline",
    "InputGuard",
    "OutputGuard",
    "PIIDetector",
    "ContentSafetyFilter",
    "GuardChainResult",
    "GuardResult",
    "GuardAction",
    "Severity",
    "create_strict_guard",
    "create_permissive_guard",
    # Sandbox management
    "SandboxManager",
    "Sandbox",
    "SafetyReport",
    "RiskLevel",
    "LLMSafetyAnalyzer",
    # Auditor
    "SecurityAuditor",
    "AuditFinding",
    "AuditReport",
]
