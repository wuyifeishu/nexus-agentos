"""
AgentOS v0.70 — Agent能力契约与发现协议。
基因来源: MCP (Model Context Protocol) + OpenAPI Spec

契约系统允许Agent声明自己的能力和限制，其他Agent可以通过
能力匹配引擎找到合适的Agent协作。

契约格式:
- AgentCapability: 单个能力描述（名称、描述、输入输出schema）
- AgentContract: Agent的完整契约（身份、能力列表、QoS、限制）
- CapabilityMatcher: 能力匹配引擎
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Capability Types ────────────────────────────

class CapabilityDomain(str, Enum):

    """能力域枚举。"""

    REASONING = "reasoning"         # 推理分析
    CODING = "coding"               # 代码生成
    SEARCH = "search"               # 信息检索
    EXECUTION = "execution"         # 命令执行
    CREATIVE = "creative"           # 创意生成
    ANALYSIS = "analysis"           # 数据分析
    COORDINATION = "coordination"   # 协调调度


class QoSLevel(str, Enum):

    """服务质量等级。"""

    BEST_EFFORT = "best_effort"     # 尽力而为
    HIGH_AVAILABILITY = "ha"        # 高可用
    LOW_LATENCY = "low_latency"    # 低延迟
    HIGH_ACCURACY = "high_accuracy" # 高准确


@dataclass
class AgentCapability:
    """单个能力声明。"""

    name: str
    description: str
    domain: CapabilityDomain = CapabilityDomain.REASONING
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    max_tokens: int = 8192
    cost_per_call: float = 0.0
    avg_latency_ms: float = 1000.0
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.9  # 0.0 - 1.0
    version: str = "1.0.0"


@dataclass
class AgentContract:
    """Agent完整契约 — 身份 + 能力 + 限制。"""

    agent_id: str
    agent_name: str
    agent_type: str = "general"
    description: str = ""
    capabilities: list[AgentCapability] = field(default_factory=list)
    qos_level: QoSLevel = QoSLevel.BEST_EFFORT
    rate_limit_rpm: int = 60          # 每分钟最大请求数
    max_context_tokens: int = 128000
    supported_languages: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    health_check_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "description": self.description,
            "capabilities": [
                {
                    "name": c.name,
                    "domain": c.domain.value,
                    "description": c.description,
                    "tags": c.tags,
                }
                for c in self.capabilities
            ],
            "qos_level": self.qos_level.value,
            "rate_limit_rpm": self.rate_limit_rpm,
            "max_context_tokens": self.max_context_tokens,
        }

    def has_capability(self, name: str) -> bool:
        return any(c.name == name for c in self.capabilities)

    def has_domain(self, domain: CapabilityDomain) -> bool:
        return any(c.domain == domain for c in self.capabilities)


# ── Capability Matcher ──────────────────────────

@dataclass
class MatchScore:
    """匹配评分结果。"""

    contract: AgentContract
    capability: AgentCapability
    score: float          # 0.0 - 1.0
    match_details: dict[str, float] = field(default_factory=dict)
    rank: int = 0


class CapabilityMatcher:
    """
    能力匹配引擎 — 根据查询找到最合适的Agent。
    支持: 语义匹配、标签匹配、领域匹配、QoS权重。
    """

    def __init__(self, contracts: list[AgentContract] | None = None):
        self._contracts: dict[str, AgentContract] = {}
        if contracts:
            for c in contracts:
                self.register(c)

    def register(self, contract: AgentContract):
        self._contracts[contract.agent_id] = contract

    def unregister(self, agent_id: str):
        self._contracts.pop(agent_id, None)

    def find(
        self,
        query: str,
        domain: CapabilityDomain | None = None,
        min_score: float = 0.3,
        top_k: int = 5,
    ) -> list[MatchScore]:
        """
        根据自然语言查询找到最匹配的Agent。
        """
        results: list[MatchScore] = []

        for contract in self._contracts.values():
            for cap in contract.capabilities:
                if domain and cap.domain != domain:
                    continue

                score = self._compute_match(query, cap, contract)
                if score >= min_score:
                    results.append(MatchScore(
                        contract=contract,
                        capability=cap,
                        score=score,
                        match_details={
                            "text_similarity": self._text_sim(query, cap),
                            "domain_match": 1.0 if domain and cap.domain == domain else 0.5,
                            "tag_overlap": self._tag_overlap(query, cap.tags),
                        },
                    ))

        # Sort by score desc
        results.sort(key=lambda x: x.score, reverse=True)

        # Assign ranks
        for i, r in enumerate(results[:top_k]):
            r.rank = i + 1

        return results[:top_k]

    def find_by_domain(self, domain: CapabilityDomain) -> list[AgentContract]:
        """按领域查找所有Agent。"""
        return [c for c in self._contracts.values() if c.has_domain(domain)]

    def find_by_tag(self, tag: str) -> list[AgentContract]:
        """按标签查找。"""
        return [
            c for c in self._contracts.values()
            if any(tag in cap.tags for cap in c.capabilities)
        ]

    def recommend_for_task(self, task_description: str) -> list[MatchScore]:
        """根据任务描述推荐Agent。"""
        return self.find(query=task_description, top_k=3)

    # ── Internal scoring ─────────────────────────

    def _compute_match(
        self,
        query: str,
        capability: AgentCapability,
        contract: AgentContract,
    ) -> float:
        """综合匹配评分。"""
        scores = []

        # Text similarity (keyword overlap)
        scores.append(self._text_sim(query, capability) * 0.35)

        # Domain match (if query mentions domain keywords)
        domain_hint = self._detect_domain(query)
        if domain_hint and domain_hint == capability.domain:
            scores.append(0.3)
        else:
            scores.append(0.1)

        # Tag overlap
        scores.append(self._tag_overlap(query, capability.tags) * 0.15)

        # QoS bonus
        qos_bonus = {
            QoSLevel.HIGH_ACCURACY: 0.1,
            QoSLevel.LOW_LATENCY: 0.08,
            QoSLevel.HIGH_AVAILABILITY: 0.05,
            QoSLevel.BEST_EFFORT: 0.0,
        }.get(contract.qos_level, 0.0)
        scores.append(qos_bonus)

        # Confidence
        scores.append(capability.confidence * 0.1)

        return min(sum(scores), 1.0)

    def _text_sim(self, query: str, capability: AgentCapability) -> float:
        """关键词重叠相似度。"""
        q_lower = query.lower()
        keywords = set(q_lower.split()) | {q_lower}

        # Capability text
        cap_text = (
            f"{capability.name} {capability.description} "
            f"{' '.join(capability.tags)} {capability.domain.value}"
        ).lower()
        cap_words = set(cap_text.split())

        if not keywords or not cap_words:
            return 0.0

        overlap = len(keywords & cap_words)
        return min(overlap / max(len(keywords), 1), 1.0)

    def _tag_overlap(self, query: str, tags: list[str]) -> float:
        """标签重叠率。"""
        q_lower = query.lower()
        if not tags:
            return 0.0
        hits = sum(1 for tag in tags if tag.lower() in q_lower)
        return hits / len(tags)

    def _detect_domain(self, query: str) -> CapabilityDomain | None:
        """从查询中检测能力域。"""
        q = query.lower()
        domain_keywords = {
            CapabilityDomain.CODING: ["code", "代码", "编程", "开发", "函数", "bug", "debug"],
            CapabilityDomain.SEARCH: ["search", "搜索", "查找", "检索", "资料"],
            CapabilityDomain.ANALYSIS: ["分析", "数据", "统计", "图表", "analysis", "data"],
            CapabilityDomain.CREATIVE: ["写", "创作", "生成", "设计", "创意", "write", "create"],
            CapabilityDomain.EXECUTION: ["运行", "执行", "操作", "命令", "exec", "run"],
            CapabilityDomain.COORDINATION: ["协调", "编排", "调度", "工作流", "orchestrate"],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in q for kw in keywords):
                return domain
        return None


# ── Contract Registry ───────────────────────────

class ContractRegistry:
    """
    契约注册中心 — 分布式Agent能力发现。
    支持心跳检测、自动过期。
    """

    def __init__(self):
        self._contracts: dict[str, AgentContract] = {}
        self._heartbeats: dict[str, float] = {}
        self._matcher = CapabilityMatcher()

    def register(self, contract: AgentContract):
        import time
        self._contracts[contract.agent_id] = contract
        self._heartbeats[contract.agent_id] = time.time()
        self._matcher.register(contract)

    def heartbeat(self, agent_id: str):
        import time
        if agent_id in self._contracts:
            self._heartbeats[agent_id] = time.time()

    def unregister(self, agent_id: str):
        self._contracts.pop(agent_id, None)
        self._heartbeats.pop(agent_id, None)
        self._matcher.unregister(agent_id)

    def prune_stale(self, max_idle_seconds: float = 300.0):
        """移除超时未心跳的Agent。"""
        import time
        now = time.time()
        stale = [
            aid for aid, ts in self._heartbeats.items()
            if now - ts > max_idle_seconds
        ]
        for aid in stale:
            self.unregister(aid)
        return stale

    def find(self, query: str, **kwargs) -> list[MatchScore]:
        return self._matcher.find(query, **kwargs)

    @property
    def active_count(self) -> int:
        return len(self._contracts)

    def list_contracts(self) -> list[AgentContract]:
        return list(self._contracts.values())

    def summary(self) -> str:
        lines = [f"注册Agent: {self.active_count}"]
        for c in self._contracts.values():
            caps = ", ".join(cap.domain.value for cap in c.capabilities)
            lines.append(f"  {c.agent_name} ({c.agent_type}): [{caps}]")
        return "\n".join(lines)
