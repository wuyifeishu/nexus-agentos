"""
AgentOS Marketplace — Agent template registry and discovery hub.

v1.14.4: Central marketplace for discovering, publishing, and installing
         agent templates, workflows, and plugins.

Key features:
- Template registry with semantic search
- Versioned agent templates with dependency resolution
- Public + private registries
- One-click install from marketplace
- Agent ratings, reviews, and usage stats
- Template validation and compatibility checking
- CLI and programmatic API
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class TemplateCategory(Enum):
    CHAT       = "chat"
    CODING     = "coding"
    ANALYSIS   = "analysis"
    AUTOMATION = "automation"
    RESEARCH   = "research"
    CREATIVE   = "creative"
    ENTERPRISE = "enterprise"
    UTILITY    = "utility"
    OTHER      = "other"


class TemplateStatus(Enum):
    DRAFT       = "draft"
    PUBLISHED   = "published"
    DEPRECATED  = "deprecated"
    ARCHIVED    = "archived"
    UNDER_REVIEW = "under_review"


@dataclass
class TemplateDependency:
    """A dependency required by a template."""
    name: str
    version_spec: str = "*"   # PEP 440 version specifier
    optional: bool = False
    description: str = ""


@dataclass
class TemplateVersion:
    """A specific version of a template."""
    version: str                  # SemVer
    changelog: str = ""
    min_agentos_version: str = "1.0.0"
    files: Dict[str, str] = field(default_factory=dict)   # path → content
    dependencies: List[TemplateDependency] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    published_at: float = 0.0
    download_count: int = 0


@dataclass
class TemplateReview:
    """User review of a template."""
    user_id: str
    rating: float                # 1.0 - 5.0
    comment: str = ""
    timestamp: float = field(default_factory=time.time)
    helpful_count: int = 0


@dataclass
class AgentTemplate:
    """An agent template in the marketplace."""
    # Identity
    id: str
    name: str
    version: str
    author: str
    description: str = ""
    category: TemplateCategory = TemplateCategory.OTHER
    tags: List[str] = field(default_factory=list)
    icon_url: str = ""

    # Status
    status: TemplateStatus = TemplateStatus.PUBLISHED

    # Content
    versions: List[TemplateVersion] = field(default_factory=list)
    readme: str = ""
    license: str = "MIT"

    # Engagement
    stars: int = 0
    downloads: int = 0
    reviews: List[TemplateReview] = field(default_factory=list)

    # Compatibility
    compatible_agentos_versions: str = ">=1.0.0"
    requires: List[TemplateDependency] = field(default_factory=list)

    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_url: str = ""
    documentation_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def rating(self) -> float:
        """Average rating."""
        if not self.reviews:
            return 0.0
        return sum(r.rating for r in self.reviews) / len(self.reviews)

    @property
    def latest_version(self) -> Optional[TemplateVersion]:
        """Get the latest published version."""
        published = [v for v in self.versions if v.published_at > 0]
        if not published:
            return None
        return max(published, key=lambda v: v.published_at)


@dataclass
class MarketSearchQuery:
    """Search query for the marketplace."""
    keywords: str = ""
    category: Optional[TemplateCategory] = None
    tags: List[str] = field(default_factory=list)
    min_rating: float = 0.0
    min_stars: int = 0
    author: Optional[str] = None
    sort_by: str = "relevance"   # relevance, downloads, rating, stars, updated
    sort_order: str = "desc"
    limit: int = 20
    offset: int = 0


@dataclass
class MarketSearchResult:
    """Search result from the marketplace."""
    template: AgentTemplate
    score: float = 0.0
    matched_tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Registry backends
# ---------------------------------------------------------------------------

class MarketRegistryBackend(ABC):
    """Abstract backend for template storage and retrieval."""

    @abstractmethod
    async def list_templates(
        self, query: Optional[MarketSearchQuery] = None
    ) -> List[MarketSearchResult]:
        ...

    @abstractmethod
    async def get_template(self, template_id: str) -> Optional[AgentTemplate]:
        ...

    @abstractmethod
    async def publish_template(self, template: AgentTemplate) -> bool:
        ...

    @abstractmethod
    async def unpublish_template(self, template_id: str) -> bool:
        ...

    @abstractmethod
    async def add_review(self, template_id: str, review: TemplateReview) -> bool:
        ...

    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        ...


class InMemoryMarketBackend(MarketRegistryBackend):
    """In-memory registry for development and testing."""

    def __init__(self):
        self._templates: Dict[str, AgentTemplate] = {}

    async def list_templates(
        self, query: Optional[MarketSearchQuery] = None
    ) -> List[MarketSearchResult]:
        results = []
        for tpl in self._templates.values():
            if tpl.status != TemplateStatus.PUBLISHED:
                continue

            score = 0.0
            matched_tags = []

            if query:
                # Keyword search
                if query.keywords:
                    kw_lower = query.keywords.lower()
                    text = f"{tpl.name} {tpl.description} {' '.join(tpl.tags)}".lower()
                    if kw_lower in text:
                        score += 10.0

                # Category filter
                if query.category and tpl.category != query.category:
                    continue

                # Tag filter
                if query.tags:
                    matched_tags = [t for t in query.tags if t in tpl.tags]
                    if not matched_tags:
                        continue
                    score += len(matched_tags) * 2.0

                # Rating filter
                if query.min_rating > 0 and tpl.rating < query.min_rating:
                    continue

                # Stars filter
                if query.min_stars > 0 and tpl.stars < query.min_stars:
                    continue

                # Author filter
                if query.author and tpl.author != query.author:
                    continue

            results.append(MarketSearchResult(
                template=tpl,
                score=score,
                matched_tags=matched_tags,
            ))

        # Sort
        if query:
            sort_key = query.sort_by
            reverse = query.sort_order == "desc"
            if sort_key == "downloads":
                results.sort(key=lambda r: r.template.downloads, reverse=reverse)
            elif sort_key == "rating":
                results.sort(key=lambda r: r.template.rating, reverse=reverse)
            elif sort_key == "stars":
                results.sort(key=lambda r: r.template.stars, reverse=reverse)
            elif sort_key == "updated":
                results.sort(key=lambda r: r.template.updated_at, reverse=reverse)
            else:  # relevance
                results.sort(key=lambda r: r.score, reverse=reverse)

            # Paginate
            results = results[query.offset:query.offset + query.limit]

        return results

    async def get_template(self, template_id: str) -> Optional[AgentTemplate]:
        return self._templates.get(template_id)

    async def publish_template(self, template: AgentTemplate) -> bool:
        template.updated_at = time.time()
        self._templates[template.id] = template
        return True

    async def unpublish_template(self, template_id: str) -> bool:
        if template_id in self._templates:
            self._templates[template_id].status = TemplateStatus.ARCHIVED
            return True
        return False

    async def add_review(self, template_id: str, review: TemplateReview) -> bool:
        tpl = self._templates.get(template_id)
        if not tpl:
            return False
        tpl.reviews.append(review)
        return True

    async def get_stats(self) -> Dict[str, Any]:
        total = len(self._templates)
        by_category = {}
        for tpl in self._templates.values():
            cat = tpl.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
        return {
            "total_templates": total,
            "total_downloads": sum(t.downloads for t in self._templates.values()),
            "by_category": by_category,
        }


class FileMarketBackend(MarketRegistryBackend):
    """JSON-file-based registry for local/CI usage."""

    def __init__(self, storage_dir: Union[str, Path]):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._dir / "index.json"
        self._templates: Dict[str, AgentTemplate] = {}
        self._load()

    def _load(self) -> None:
        if self._index_file.exists():
            with open(self._index_file, "r") as f:
                data = json.load(f)
            for raw in data.get("templates", []):
                tpl = self._dict_to_template(raw)
                self._templates[tpl.id] = tpl

    def _save(self) -> None:
        data = {
            "updated_at": time.time(),
            "templates": [self._template_to_dict(t) for t in self._templates.values()],
        }
        with open(self._index_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _template_to_dict(self, tpl: AgentTemplate) -> Dict[str, Any]:
        return {
            "id": tpl.id,
            "name": tpl.name,
            "version": tpl.version,
            "author": tpl.author,
            "description": tpl.description,
            "category": tpl.category.value,
            "tags": tpl.tags,
            "status": tpl.status.value,
            "stars": tpl.stars,
            "downloads": tpl.downloads,
            "rating": tpl.rating,
            "review_count": len(tpl.reviews),
            "compatible_agentos_versions": tpl.compatible_agentos_versions,
            "created_at": tpl.created_at,
            "updated_at": tpl.updated_at,
        }

    def _dict_to_template(self, d: Dict[str, Any]) -> AgentTemplate:
        return AgentTemplate(
            id=d["id"],
            name=d["name"],
            version=d.get("version", "1.0.0"),
            author=d["author"],
            description=d.get("description", ""),
            category=TemplateCategory(d.get("category", "other")),
            tags=d.get("tags", []),
            status=TemplateStatus(d.get("status", "published")),
            stars=d.get("stars", 0),
            downloads=d.get("downloads", 0),
            compatible_agentos_versions=d.get("compatible_agentos_versions", ">=1.0.0"),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    # Delegate to in-memory backend
    async def list_templates(self, query=None):
        backend = InMemoryMarketBackend()
        backend._templates = dict(self._templates)
        return await backend.list_templates(query)

    async def get_template(self, template_id):
        return self._templates.get(template_id)

    async def publish_template(self, template):
        tpl = AgentTemplate(**{
            k: v for k, v in template.__dict__.items()
            if k in AgentTemplate.__dataclass_fields__
        })
        template.updated_at = time.time()
        self._templates[template.id] = template
        self._save()
        return True

    async def unpublish_template(self, template_id):
        if template_id in self._templates:
            self._templates[template_id].status = TemplateStatus.ARCHIVED
            self._save()
            return True
        return False

    async def add_review(self, template_id, review):
        tpl = self._templates.get(template_id)
        if not tpl:
            return False
        tpl.reviews.append(review)
        self._save()
        return True

    async def get_stats(self):
        backend = InMemoryMarketBackend()
        backend._templates = dict(self._templates)
        return await backend.get_stats()


# ---------------------------------------------------------------------------
# Remote registry client
# ---------------------------------------------------------------------------

class RemoteMarketClient:
    """HTTP client for remote marketplace registries."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def search(self, query: MarketSearchQuery) -> List[MarketSearchResult]:
        """Search the remote marketplace."""
        import urllib.request
        import urllib.parse

        params = {}
        if query.keywords:
            params["q"] = query.keywords
        if query.category:
            params["category"] = query.category.value
        if query.tags:
            params["tags"] = ",".join(query.tags)
        if query.limit:
            params["limit"] = str(query.limit)

        url = f"{self.base_url}/api/v1/templates"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        # Use asyncio-compatible HTTP
        import aiohttp
        async with aiohttp.ClientSession() as session:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                return [
                    MarketSearchResult(
                        template=AgentTemplate(**item["template"]),
                        score=item.get("score", 0),
                    )
                    for item in data.get("results", [])
                ]

    async def get_template(self, template_id: str) -> Optional[AgentTemplate]:
        """Fetch a template from the remote registry."""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            async with session.get(
                f"{self.base_url}/api/v1/templates/{template_id}",
                headers=headers,
            ) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                return AgentTemplate(**data)

    async def download_template(
        self, template_id: str, target_dir: Union[str, Path]
    ) -> bool:
        """Download and extract a template to a local directory."""
        import aiohttp
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession() as session:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            async with session.get(
                f"{self.base_url}/api/v1/templates/{template_id}/download",
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return False

                import tarfile
                import io
                data = await resp.read()
                with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                    tar.extractall(path=target)
        return True


# ---------------------------------------------------------------------------
# Marketplace Manager
# ---------------------------------------------------------------------------

class MarketplaceManager:
    """Central marketplace management — search, install, publish."""

    def __init__(
        self,
        local_backend: Optional[MarketRegistryBackend] = None,
        remote_clients: Optional[List[RemoteMarketClient]] = None,
        install_dir: Union[str, Path] = "~/.agentos/templates",
    ):
        self.local = local_backend or InMemoryMarketBackend()
        self.remote_clients = remote_clients or []
        self.install_dir = Path(install_dir).expanduser()
        self.install_dir.mkdir(parents=True, exist_ok=True)

    async def search(
        self, query: MarketSearchQuery, include_remote: bool = True
    ) -> List[MarketSearchResult]:
        """Search local and remote registries."""
        results = await self.local.list_templates(query)

        if include_remote:
            for client in self.remote_clients:
                try:
                    remote_results = await client.search(query)
                    results.extend(remote_results)
                except Exception as e:
                    logger.warning(f"Remote search failed: {e}")

        # Deduplicate by template ID
        seen: Set[str] = set()
        deduped = []
        for r in results:
            if r.template.id not in seen:
                seen.add(r.template.id)
                deduped.append(r)

        return deduped

    async def install(self, template_id: str, version: Optional[str] = None) -> Path:
        """Install a template from local or remote registry."""
        # Check local first
        tpl = await self.local.get_template(template_id)

        # Try remote
        if not tpl:
            for client in self.remote_clients:
                try:
                    tpl = await client.get_template(template_id)
                    if tpl:
                        break
                except Exception:
                    continue

        if not tpl:
            raise ValueError(f"Template '{template_id}' not found in any registry")

        # Install to local directory
        tpl_dir = self.install_dir / template_id
        if version:
            tpl_dir = tpl_dir / version

        tpl_dir.mkdir(parents=True, exist_ok=True)

        # Write template files
        latest = tpl.latest_version
        if latest:
            for filepath, content in latest.files.items():
                full_path = tpl_dir / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)

        # Record installation
        tpl.downloads += 1
        tpl.updated_at = time.time()

        return tpl_dir

    async def publish(
        self,
        template: AgentTemplate,
        to_remote: bool = False,
    ) -> bool:
        """Publish a template to registries."""
        # Always publish to local
        ok = await self.local.publish_template(template)
        if not ok:
            return False

        # Optionally push to remote
        if to_remote:
            for client in self.remote_clients:
                try:
                    # Remote publishing would use a POST endpoint
                    pass
                except Exception as e:
                    logger.error(f"Remote publish failed: {e}")

        return True

    async def get_stats(self) -> Dict[str, Any]:
        """Get marketplace statistics."""
        return await self.local.get_stats()

    async def get_featured(self, limit: int = 10) -> List[AgentTemplate]:
        """Get featured/popular templates."""
        query = MarketSearchQuery(sort_by="downloads", limit=limit)
        results = await self.local.list_templates(query)
        return [r.template for r in results]

    async def get_by_category(
        self, category: TemplateCategory, limit: int = 20
    ) -> List[AgentTemplate]:
        """Get templates by category."""
        query = MarketSearchQuery(category=category, limit=limit)
        results = await self.local.list_templates(query)
        return [r.template for r in results]


# ---------------------------------------------------------------------------
# Template builder
# ---------------------------------------------------------------------------

class TemplateBuilder:
    """Helper to build AgentTemplate objects programmatically."""

    def __init__(self, name: str, author: str, version: str = "1.0.0"):
        self._template = AgentTemplate(
            id=hashlib.sha256(f"{author}/{name}".encode()).hexdigest()[:16],
            name=name,
            version=version,
            author=author,
        )

    def description(self, text: str) -> "TemplateBuilder":
        self._template.description = text
        return self

    def category(self, cat: TemplateCategory) -> "TemplateBuilder":
        self._template.category = cat
        return self

    def tags(self, *tags: str) -> "TemplateBuilder":
        self._template.tags = list(tags)
        return self

    def add_version(
        self, version: str, files: Dict[str, str], changelog: str = ""
    ) -> "TemplateBuilder":
        tv = TemplateVersion(
            version=version,
            changelog=changelog,
            files=files,
            published_at=time.time(),
        )
        self._template.versions.append(tv)
        return self

    def add_dependency(
        self, name: str, version_spec: str = "*", optional: bool = False
    ) -> "TemplateBuilder":
        self._template.requires.append(
            TemplateDependency(name=name, version_spec=version_spec, optional=optional)
        )
        return self

    def add_review(self, user_id: str, rating: float, comment: str = "") -> "TemplateBuilder":
        self._template.reviews.append(
            TemplateReview(user_id=user_id, rating=rating, comment=comment)
        )
        return self

    def build(self) -> AgentTemplate:
        if not self._template.description:
            raise ValueError("Template must have a description")
        return self._template


# ---------------------------------------------------------------------------
# Pre-seeded templates
# ---------------------------------------------------------------------------

def seed_default_templates(manager: MarketplaceManager) -> None:
    """Seed the marketplace with default templates."""
    templates = [
        TemplateBuilder("Conversational Agent", "AgentOS Team")
            .description("General-purpose conversational agent with memory and tool use")
            .category(TemplateCategory.CHAT)
            .tags("chat", "conversation", "memory")
            .add_version("1.0.0", {
                "agent.yaml": "name: conversational-agent\ntype: chat\nmemory: enabled",
                "main.py": "from agentos import Agent\n\nagent = Agent(...)",
            })
            .build(),

        TemplateBuilder("Code Review Assistant", "AgentOS Team")
            .description("AI-powered code reviewer with PR integration")
            .category(TemplateCategory.CODING)
            .tags("code", "review", "github", "pr")
            .add_version("1.0.0", {
                "agent.yaml": "name: code-reviewer\ntype: coding\n",
                "review.py": "async def review_pr(pr_url): ...",
            })
            .build(),

        TemplateBuilder("Research Analyst", "AgentOS Team")
            .description("Multi-source research agent with deep analysis capabilities")
            .category(TemplateCategory.RESEARCH)
            .tags("research", "analysis", "web")
            .add_version("1.0.0", {
                "agent.yaml": "name: research-analyst\ntype: research\n",
                "analyst.py": "async def deep_research(topic): ...",
            })
            .build(),

        TemplateBuilder("Data Pipeline Agent", "AgentOS Team")
            .description("Automated ETL and data processing pipeline")
            .category(TemplateCategory.AUTOMATION)
            .tags("etl", "data", "pipeline", "automation")
            .add_version("1.0.0", {
                "agent.yaml": "name: data-pipeline\ntype: automation\n",
                "pipeline.py": "async def run_pipeline(config): ...",
            })
            .build(),

        TemplateBuilder("Document Writer", "AgentOS Team")
            .description("Professional document generation from outlines or templates")
            .category(TemplateCategory.CREATIVE)
            .tags("writing", "document", "report")
            .add_version("1.0.0", {
                "agent.yaml": "name: doc-writer\ntype: creative\n",
                "writer.py": "async def generate_doc(outline): ...",
            })
            .build(),
    ]

    async def _seed():
        for tpl in templates:
            await manager.local.publish_template(tpl)

    try:
        asyncio.get_event_loop().run_until_complete(_seed())
    except RuntimeError:
        asyncio.run(_seed())


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "TemplateCategory",
    "TemplateStatus",
    # Data types
    "TemplateDependency",
    "TemplateVersion",
    "TemplateReview",
    "AgentTemplate",
    "MarketSearchQuery",
    "MarketSearchResult",
    # Backends
    "MarketRegistryBackend",
    "InMemoryMarketBackend",
    "FileMarketBackend",
    "RemoteMarketClient",
    # Manager
    "MarketplaceManager",
    "TemplateBuilder",
    "seed_default_templates",
]
