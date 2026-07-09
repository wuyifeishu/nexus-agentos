"""Tools module - Fusion toolkit, Risk rating, Base tools, Registry, Function Calling, Generator, Search, Data, HTTP"""

# v1.15.1 - Async tool execution optimization
from agentos.tools.base import (
    BaseTool,
    PermissionLevel,
)
from agentos.tools.base import (
    ToolCall as BaseToolCall,
)
from agentos.tools.base import (
    ToolResult as BaseToolResult,
)

# v1.16.0 - Bridge: ToolRegistry ↔ ToolExecutor
from agentos.tools.bridge import (
    base_tool_to_llm_tool,
    bridge_registry_to_executor,
    make_handler,
)
from agentos.tools.data_tools import (
    CsvTool,
    JsonTool,
)
from agentos.tools.function_calling import (
    ToolCall as FCToolCall,
)
from agentos.tools.function_calling import (
    ToolRegistry as FCToolRegistry,
)
from agentos.tools.function_calling import (
    ToolResult as FCToolResult,
)
from agentos.tools.function_calling import (
    ToolSchema,
)
from agentos.tools.fusion import (
    FusionResult,
    FusionToolkit,
    ToolSpec,
)
from agentos.tools.generator import (
    GeneratedTool,
    OpenAPIToolGenerator,
)
from agentos.tools.http_tools import (
    DownloadTool,
    HttpRequestTool,
)
from agentos.tools.registry import (
    ToolRegistry,
)
from agentos.tools.risk import (
    ToolRiskLevel,
    ToolRiskRating,
    get_risk_preset,
    infer_risk_level,
)

# v1.5.3 - Tool ecosystem expansion
from agentos.tools.search_tools import (
    CodeSearchTool,
    FileSearchTool,
    GrepTool,
)

# v1.15.0 - Tool output validation layer
from agentos.tools.validation import (
    ToolErrorClassifier,
    ToolOutputValidator,
    ValidationIssue,
    ValidationResult,
    ValidationRule,
    ValidationSeverity,
    classify_tool_error,
    validate_tool_output,
)

__all__ = [
    "FusionToolkit",
    "FusionResult",
    "ToolSpec",
    "ToolRiskLevel",
    "ToolRiskRating",
    "get_risk_preset",
    "infer_risk_level",
    "BaseTool",
    "PermissionLevel",
    "BaseToolCall",
    "BaseToolResult",
    "ToolRegistry",
    "ToolSchema",
    "FCToolCall",
    "FCToolResult",
    "FCToolRegistry",
    "OpenAPIToolGenerator",
    "GeneratedTool",
    # v1.5.3
    "GrepTool",
    "FileSearchTool",
    "CodeSearchTool",
    "JsonTool",
    "CsvTool",
    "HttpRequestTool",
    "DownloadTool",
    # v1.15.0
    "ValidationSeverity",
    "ValidationRule",
    "ValidationIssue",
    "ValidationResult",
    "ToolOutputValidator",
    "ToolErrorClassifier",
    "validate_tool_output",
    "classify_tool_error",
    # v1.16.0 - Bridge
    "base_tool_to_llm_tool",
    "make_handler",
    "bridge_registry_to_executor",
]
