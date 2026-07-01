"""
AgentOS v0.80 统一配置系统。
v0.80新增: BenchmarkCfg。
v0.70基线: PluginsCfg, GeminiCfg, ContractsCfg, OrchestratorCfg, ScorerCfg。
v0.60基线: GuardrailsCfg, RateLimitCfg, StateMachineCfg, ResilienceCfg。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


@dataclass
class ModelConfig:
    """LLM 模型配置。"""

    default: str = "deepseek-v3.1"
    fallback_chain: list[str] = field(default_factory=lambda: ["kimi-k2.6", "qwen-3.6-plus"])
    auto_select: bool = True
    max_retries: int = 3
    request_timeout: int = 120
    api_base: str = ""
    api_key: str = ""


@dataclass
class LoopCfg:
    """Agent 主循环配置。"""

    max_iterations: int = 100
    max_retries_per_step: int = 2
    step_timeout_seconds: int = 120
    enable_streaming: bool = False
    enable_checkpoints: bool = True
    checkpoint_interval: int = 5


@dataclass
class MemoryCfg:
    """记忆系统配置。"""
    short_term_capacity: int = 50
    long_term_enabled: bool = True
    long_term_max_entries: int = 100000
    vector_dim: int = 1536
    vector_backend: str = "faiss"
    vector_persist_dir: str = "./vector_data"
    compression_interval: int = 20


@dataclass
class SecurityCfg:
    """安全策略配置。"""
    sandbox_enabled: bool = False
    sandbox_image: str = "agentos-sandbox:latest"
    max_file_size_mb: int = 100
    allowed_paths: list[str] = field(default_factory=lambda: [".", "/tmp/agentos"])


@dataclass
class ObservabilityCfg:
    """可观测性配置。"""
    tracer_enabled: bool = True
    tracer_backend: str = "console"
    langsmith_api_key: str = ""
    log_level: str = "INFO"


@dataclass
class MCPServersCfg:
    """MCP 服务器列表配置。"""
    servers: list[dict] = field(default_factory=list)


@dataclass
class ReflectionCfg:
    """反思循环配置。"""
    enabled: bool = True
    frequency: int = 3
    max_loops: int = 3
    enable_self_critique: bool = True


@dataclass
class CostCfg:
    """成本控制配置。"""
    enabled: bool = True
    budget_limit: float = 0.0
    warn_threshold: float = 0.8


@dataclass
class FeedbackCfg:
    """反馈回路配置。"""
    enabled: bool = True
    human_in_the_loop: bool = False
    approval_trigger: str = "high_risk"
    storage_path: str = "./feedback_data.jsonl"


@dataclass
class APICfg:
    """API 服务配置。"""
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class SwarmCfg:
    """Swarm 多 Agent 协作配置。"""
    enabled: bool = True
    topology: str = "sequential"  # sequential|parallel|debate|hierarchical|broadcast
    max_parallel_agents: int = 4
    enable_communication: bool = True
    enable_blackboard: bool = True


@dataclass
class QueueCfg:
    """任务队列配置。"""
    enabled: bool = False
    backend: str = "memory"  # memory|redis
    redis_url: str = "redis://localhost:6379/0"
    concurrency: int = 4
    max_retries: int = 3
    retry_backoff: str = "exponential"  # exponential|linear|fixed


@dataclass
class CacheCfg:
    """语义缓存配置。"""
    enabled: bool = True
    lru_size: int = 500
    semantic_enabled: bool = True
    similarity_threshold: float = 0.92
    default_ttl: float = 3600


@dataclass
class ExperimentCfg:
    """A/B 实验配置。"""
    enabled: bool = False
    auto_evaluator: str = "llm_judge"
    trials_per_variant: int = 3
    shuffle_trials: bool = True


@dataclass
class MultimodalCfg:
    """多模态处理配置。"""
    enabled: bool = True
    max_image_size: int = 2048
    whisper_model: str = "base"
    document_parser: str = "auto"  # auto|PyPDF2|unstructured


@dataclass
class MCPServerCfg:
    """MCP 服务端配置。"""
    enabled: bool = False
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 9000
    server_name: str = "AgentOS-MCP-Server"


@dataclass
class GuardrailsCfg:
    """安全护栏配置。"""
    enabled: bool = True
    block_pii: bool = True
    block_injection: bool = True
    moderation_threshold: str = "medium"


@dataclass
class RateLimitCfg:
    """限流配置。"""
    enabled: bool = True
    strategy: str = "token_bucket"
    max_requests: int = 60
    per_seconds: float = 60.0
    burst_size: int = 10
    max_concurrent: int = 5
    queue_timeout: float = 30.0


@dataclass
class StateMachineCfg:
    """状态机配置。"""
    max_thinking_time: float = 300.0
    max_acting_time: float = 120.0
    max_observing_time: float = 60.0
    max_total_time: float = 3600.0
    auto_recover: bool = True


@dataclass
class ResilienceCfg:
    """弹性容错配置。"""
    retry_max: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    circuit_failure_threshold: int = 5
    circuit_timeout: float = 30.0


# ── v0.70 新增配置段 ────────────────────────────────────────────────────

@dataclass
class PluginsCfg:
    """插件系统配置。"""
    enabled: bool = True
    plugins_dir: str = "./plugins"
    auto_discover: bool = True
    hot_reload: bool = False
    max_plugins: int = 50


@dataclass
class GeminiCfg:
    """Gemini 模型配置。"""
    enabled: bool = True
    api_key: str = ""
    default_model: str = "gemini-2.5-flash"
    vision_enabled: bool = True
    max_image_size: int = 4096
    safety_threshold: str = "BLOCK_ONLY_HIGH"


@dataclass
class ContractsCfg:
    """能力契约配置。"""
    enabled: bool = True
    auto_discover: bool = True
    heartbeat_interval: float = 30.0
    stale_timeout: float = 300.0
    max_registered: int = 100


@dataclass
class OrchestratorCfg:
    """编排器配置。"""
    enabled: bool = True
    global_timeout: float = 300.0
    default_retries: int = 3
    max_concurrent_tools: int = 10
    dag_export_dir: str = "./dags"


@dataclass
class ScorerCfg:
    """评分器配置。"""
    enabled: bool = True
    strategy: str = "composite"
    pass_threshold: float = 0.6
    enable_semantic: bool = True


# ── v0.80 新增配置段 ────────────────────────────────────────────────────

@dataclass
class BenchmarkCfg:
    """性能基准配置。"""
    enabled: bool = True
    output_dir: str = "./benchmarks"
    warmup_iterations: int = 3
    measure_iterations: int = 10
    concurrency_levels: list[int] = field(default_factory=lambda: [1, 4, 8])
    timeout_per_run: float = 30.0


@dataclass
class HealthCfg:
    """健康检查配置。"""
    readiness_enabled: bool = True
    liveness_enabled: bool = True
    disk_threshold_mb: int = 100
    memory_threshold_mb: int = 50


@dataclass
class AuditCfg:
    """安全审计配置。"""
    enabled: bool = False
    severity_threshold: str = "medium"
    report_format: str = "markdown"
    auto_scan_on_startup: bool = False


@dataclass
class DeployCfg:
    """部署配置。"""
    base_image: str = "python:3.11-slim"
    port: int = 8000
    workers: int = 4
    healthcheck_endpoint: str = "/health"


@dataclass
class MiddlewareCfg:
    """中间件配置。"""
    cors_enabled: bool = True
    cors_origins: list = field(default_factory=lambda: ["*"])
    auth_enabled: bool = False
    request_logging: bool = True
    rate_limit_rpm: int = 0


@dataclass
class AgentOSConfig:
    """AgentOS v0.90 总配置。"""

    model: ModelConfig = field(default_factory=ModelConfig)
    loop: LoopCfg = field(default_factory=LoopCfg)
    memory: MemoryCfg = field(default_factory=MemoryCfg)
    security: SecurityCfg = field(default_factory=SecurityCfg)
    observability: ObservabilityCfg = field(default_factory=ObservabilityCfg)
    mcp: MCPServersCfg = field(default_factory=MCPServersCfg)
    reflection: ReflectionCfg = field(default_factory=ReflectionCfg)
    cost: CostCfg = field(default_factory=CostCfg)
    feedback: FeedbackCfg = field(default_factory=FeedbackCfg)
    api: APICfg = field(default_factory=APICfg)
    swarm: SwarmCfg = field(default_factory=SwarmCfg)
    queue: QueueCfg = field(default_factory=QueueCfg)
    cache: CacheCfg = field(default_factory=CacheCfg)
    experiment: ExperimentCfg = field(default_factory=ExperimentCfg)
    multimodal: MultimodalCfg = field(default_factory=MultimodalCfg)
    mcp_server: MCPServerCfg = field(default_factory=MCPServerCfg)
    guardrails: GuardrailsCfg = field(default_factory=GuardrailsCfg)
    rate_limit: RateLimitCfg = field(default_factory=RateLimitCfg)
    state_machine: StateMachineCfg = field(default_factory=StateMachineCfg)
    resilience: ResilienceCfg = field(default_factory=ResilienceCfg)
    plugins: PluginsCfg = field(default_factory=PluginsCfg)
    gemini: GeminiCfg = field(default_factory=GeminiCfg)
    contracts: ContractsCfg = field(default_factory=ContractsCfg)
    orchestrator: OrchestratorCfg = field(default_factory=OrchestratorCfg)
    scorer: ScorerCfg = field(default_factory=ScorerCfg)
    benchmark: BenchmarkCfg = field(default_factory=BenchmarkCfg)
    health: HealthCfg = field(default_factory=HealthCfg)
    audit: AuditCfg = field(default_factory=AuditCfg)
    deploy: DeployCfg = field(default_factory=DeployCfg)
    middleware: MiddlewareCfg = field(default_factory=MiddlewareCfg)
    version: str = "0.90.0"

    def to_dict(self) -> dict:
        result = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if hasattr(val, "__dataclass_fields__"):
                result[f.name] = {ff.name: getattr(val, ff.name) for ff in fields(val)}
            else:
                result[f.name] = val
        return result


def load_config(path: str | None = None) -> AgentOSConfig:
    config = AgentOSConfig()
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
            _merge(config, data)
        except ImportError:
            pass
        except Exception:
            pass
    _override_from_env(config)
    return config


def _merge(config: AgentOSConfig, data: dict):
    for key, val in data.items():
        if hasattr(config, key):
            section = getattr(config, key)
            if hasattr(section, "__dataclass_fields__") and isinstance(val, dict):
                for sk, sv in val.items():
                    if hasattr(section, sk):
                        setattr(section, sk, sv)
            else:
                setattr(config, key, val)


def _override_from_env(config: AgentOSConfig):
    env_map = {
        "AGENTOS_MODEL": ("model", "default"),
        "AGENTOS_MAX_ITERATIONS": ("loop", "max_iterations"),
        "AGENTOS_ENABLE_STREAMING": ("loop", "enable_streaming"),
        "AGENTOS_LOG_LEVEL": ("observability", "log_level"),
        "AGENTOS_BUDGET_LIMIT": ("cost", "budget_limit"),
        "AGENTOS_ENABLE_REFLECTION": ("reflection", "enabled"),
        "AGENTOS_ENABLE_COST_TRACKING": ("cost", "enabled"),
        "AGENTOS_API_PORT": ("api", "port"),
        "AGENTOS_SWARM_TOPOLOGY": ("swarm", "topology"),
        "AGENTOS_SWARM_MAX_PARALLEL": ("swarm", "max_parallel_agents"),
        "AGENTOS_CACHE_LRU_SIZE": ("cache", "lru_size"),
        "AGENTOS_CACHE_SEMANTIC": ("cache", "semantic_enabled"),
        "AGENTOS_QUEUE_CONCURRENCY": ("queue", "concurrency"),
        "AGENTOS_MCP_SERVER_PORT": ("mcp_server", "port"),
        "AGENTOS_PLUGINS_DIR": ("plugins", "plugins_dir"),
        "AGENTOS_PLUGINS_HOT_RELOAD": ("plugins", "hot_reload"),
        "AGENTOS_GEMINI_API_KEY": ("gemini", "api_key"),
        "AGENTOS_GEMINI_MODEL": ("gemini", "default_model"),
        "AGENTOS_CONTRACTS_ENABLED": ("contracts", "enabled"),
        "AGENTOS_ORCHESTRATOR_TIMEOUT": ("orchestrator", "global_timeout"),
        "AGENTOS_SCORER_STRATEGY": ("scorer", "strategy"),
        "AGENTOS_SCORER_THRESHOLD": ("scorer", "pass_threshold"),
    }
    for env_key, (section, field_name) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            sec = getattr(config, section)
            default_type = type(getattr(type(sec)(), field_name, ""))
            if default_type is bool:
                val_typed = val.lower() in ("1", "true", "yes")
            elif default_type is float:
                val_typed = float(val)
            elif default_type is int:
                val_typed = int(val)
            else:
                val_typed = val
            setattr(sec, field_name, val_typed)
