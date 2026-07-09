"""
AgentOS v1.2.0 — Agent Card 服务发现协议。

基因来源: Google A2A (Agent-to-Agent) Agent Card 规范

Agent Card 是标准化的 Agent 自描述卡片，支持:
- 发布/发现: Agent 发布自身能力，其他 Agent 按需发现
- 能力匹配: 按 domain / capability / keyword 搜索匹配
- 本地+远程: 文件系统本地发现 + HTTP 端点远程发现
- JSON 序列化: 完整的 export/import 往返，兼容 A2A 生态
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ── AgentCard ───────────────────────────────────


@dataclass
class AgentCard:
    """Agent 自描述卡片，A2A 兼容。

    使用方式:
        card = AgentCard(
            name="data-analyzer",
            description="数据分析Agent，支持SQL/Pandas/可视化",
            version="1.0.0",
            url="http://localhost:8000/agent",
            capabilities=["analysis", "coding"],
            skills=["sql-query", "pandas-transform", "chart-generate"],
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        )
    """

    name: str
    description: str
    version: str
    url: str = ""
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """导出为字典，保留所有字段（含空值）。"""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """从字典重建 AgentCard。"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> AgentCard:
        """从 JSON 字符串重建。"""
        return cls.from_dict(json.loads(json_str))

    def matches_query(self, query: str) -> bool:
        """模糊匹配：检查 query 是否命中 name/description/skills/tags。"""
        q = query.lower()
        if q in self.name.lower():
            return True
        if q in self.description.lower():
            return True
        for skill in self.skills:
            if q in skill.lower():
                return True
        for tag in self.tags:
            if q in tag.lower():
                return True
        return False

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def has_skill(self, skill: str) -> bool:
        return skill in self.skills

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags


# ── AgentCardRegistry ───────────────────────────


@dataclass
class AgentCardRegistry:
    """Agent Card 注册中心。

    支持注册、注销、搜索、过滤。
    """

    cards: dict[str, AgentCard] = field(default_factory=dict)

    def register(self, card: AgentCard) -> None:
        """注册一张 Agent Card（同名覆盖）。"""
        self.cards[card.name] = card

    def unregister(self, name: str) -> AgentCard | None:
        """注销并返回被移除的卡片，不存在返回 None。"""
        return self.cards.pop(name, None)

    def get(self, name: str) -> AgentCard | None:
        """按名称查找。"""
        return self.cards.get(name)

    def list_all(self) -> list[AgentCard]:
        """列出所有注册的卡片。"""
        return list(self.cards.values())

    def find_by_query(self, query: str) -> list[AgentCard]:
        """按关键词搜索（匹配 name/description/skills/tags）。"""
        return [c for c in self.cards.values() if c.matches_query(query)]

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        """按能力关键词查找。"""
        return [c for c in self.cards.values() if c.has_capability(capability)]

    def find_by_skill(self, skill: str) -> list[AgentCard]:
        """按技能关键词查找。"""
        return [c for c in self.cards.values() if c.has_skill(skill)]

    def find_by_tag(self, tag: str) -> list[AgentCard]:
        """按标签查找。"""
        return [c for c in self.cards.values() if c.has_tag(tag)]

    def export_all(self, filepath: str) -> None:
        """将所有卡片导出到 JSON 文件。"""
        data = {name: card.to_dict() for name, card in self.cards.items()}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_from_file(self, filepath: str) -> int:
        """从 JSON 文件导入卡片到注册中心，返回导入数量。"""
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for name, card_data in data.items():
            self.cards[name] = AgentCard.from_dict(card_data)
            count += 1
        return count

    @classmethod
    def from_file(cls, filepath: str) -> AgentCardRegistry:
        """从 JSON 文件创建注册中心。"""
        reg = cls()
        reg.import_from_file(filepath)
        return reg

    def __len__(self) -> int:
        return len(self.cards)

    def __contains__(self, name: str) -> bool:
        return name in self.cards


# ── AgentCardDiscovery (远程发现) ───────────────


class AgentCardDiscovery:
    """Agent Card 远程发现器。

    通过 HTTP GET 获取远程 Agent 的 /agent-card 端点。
    """

    @staticmethod
    async def fetch(url: str, timeout: float = 10.0) -> AgentCard | None:
        """从远程 URL 获取 AgentCard JSON 并解析。

        默认期望端点返回 {"name":..., "description":..., ...}

        Args:
            url: Agent Card 端点 URL（如 http://host:8000/agent-card）
            timeout: 请求超时（秒）

        Returns:
            AgentCard 实例，失败返回 None
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return AgentCard.from_json(resp.text)
        except Exception:
            return None

    @staticmethod
    async def fetch_all(urls: list[str], timeout: float = 10.0) -> dict[str, AgentCard | None]:
        """并发获取多个 Agent Card。

        Args:
            urls: Agent Card 端点 URL 列表
            timeout: 单个请求超时（秒）

        Returns:
            {url: AgentCard 或 None} 字典
        """
        import asyncio

        results = await asyncio.gather(
            *(AgentCardDiscovery.fetch(url, timeout) for url in urls),
            return_exceptions=True,
        )
        return {url: (None if isinstance(r, Exception) else r) for url, r in zip(urls, results)}


# ── 便捷函数 ───────────────────────────────────


def create_card(
    name: str,
    description: str,
    version: str = "1.0.0",
    url: str = "",
    capabilities: list[str] | None = None,
    skills: list[str] | None = None,
    **metadata,
) -> AgentCard:
    """快速创建 AgentCard 的便捷函数。"""
    return AgentCard(
        name=name,
        description=description,
        version=version,
        url=url,
        capabilities=capabilities or [],
        skills=skills or [],
        metadata=metadata,
    )


def discover_local(directory: str, pattern: str = "agent-card*.json") -> list[AgentCard]:
    """从本地目录发现 AgentCard JSON 文件。

    Args:
        directory: 扫描目录
        pattern: 文件名 glob pattern（仅支持简单前缀/后缀匹配）

    Returns:
        发现的 AgentCard 列表
    """
    import fnmatch
    import os

    cards: list[AgentCard] = []
    try:
        for fname in os.listdir(directory):
            if fnmatch.fnmatch(fname, pattern):
                fpath = os.path.join(directory, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        cards.append(AgentCard.from_json(f.read()))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return cards
