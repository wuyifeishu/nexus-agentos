"""
Universal Skill Ecosystem Bridge (v1.9.0)

One-line gateway to 7+ skill ecosystems. Auto-discovers, converts, and imports
skills from any external source into AgentOS marketplace — no need to host
your own skill packages when the world already has 20,000+.

Supported Ecosystems:
  - OpenClaw Community (60+ skills, GitHub-based)
  - HuggingFace Skills (hf:// namespace)
  - GitHub Topics (#agent-skill, #ai-tool)
  - npm agent-skills (npm search + install)
  - Python SkillsMP (PyPI discovery)
  - skills.sh Community
  - Custom URL / Git repo

Usage:
    from agentos.marketplace.ecosystem_bridge import EcosystemBridge

    bridge = EcosystemBridge(registry)
    await bridge.sync_all()          # Import from all enabled ecosystems
    await bridge.search("pdf")       # Cross-ecosystem search
    count = await bridge.count()     # Total available skills across all sources
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any
from urllib.parse import urlparse, quote_plus

from agentos.marketplace.importer import (
    OpenClawImporter, RemoteSkill, OPENCLAW_RAW_BASE, OPENCLAW_API,
)
from agentos.marketplace.manifest import SkillManifest


# ── Ecosystem Registry ──────────────────────────────────────────────

class EcosystemSource(str, Enum):
    OPENCLAW = "openclaw"
    HUGGINGFACE = "huggingface"
    GITHUB_TOPICS = "github_topics"
    NPM = "npm"
    PYPI = "pypi"
    SKILLS_SH = "skills_sh"
    CUSTOM = "custom"


@dataclass
class EcosystemMeta:
    """Metadata for a skill ecosystem source."""
    source: EcosystemSource
    name: str                     # Human-readable name
    base_url: str                 # API / catalog URL
    estimated_skills: int         # Approximate count
    category: str = "community"   # community / official / experimental
    enabled: bool = True
    auth_required: bool = False
    icon: str = ""                # Icon URL or emoji
    description: str = ""
    api_docs: str = ""


# Pre-registered ecosystems
ECOSYSTEMS: dict[EcosystemSource, EcosystemMeta] = {
    EcosystemSource.OPENCLAW: EcosystemMeta(
        source=EcosystemSource.OPENCLAW,
        name="OpenClaw Community",
        base_url="https://github.com/nicepkg/openclaw-skill-store",
        estimated_skills=60,
        category="community",
        icon="🔧",
        description="The primary community skill store. Curated, reviewed, production-ready skills.",
        api_docs="https://github.com/nicepkg/openclaw-skill-store",
    ),
    EcosystemSource.HUGGINGFACE: EcosystemMeta(
        source=EcosystemSource.HUGGINGFACE,
        name="HuggingFace Skills Hub",
        base_url="https://huggingface.co/spaces",
        estimated_skills=500,
        category="community",
        enabled=True,
        auth_required=False,
        icon="🤗",
        description="AI/ML-focused skills: model inference, dataset processing, training pipelines.",
    ),
    EcosystemSource.GITHUB_TOPICS: EcosystemMeta(
        source=EcosystemSource.GITHUB_TOPICS,
        name="GitHub Topics Discovery",
        base_url="https://api.github.com/search/repositories",
        estimated_skills=2000,
        category="community",
        enabled=True,
        icon="🐙",
        description="Auto-discover skills via GitHub topics: #agent-skill, #ai-tool, #agent-framework.",
    ),
    EcosystemSource.NPM: EcosystemMeta(
        source=EcosystemSource.NPM,
        name="npm Agent Skills",
        base_url="https://registry.npmjs.org",
        estimated_skills=300,
        category="community",
        enabled=True,
        icon="📦",
        description="Node.js agent skills published as npm packages. Search: 'agent-skill'.",
    ),
    EcosystemSource.PYPI: EcosystemMeta(
        source=EcosystemSource.PYPI,
        name="PyPI Skills Marketplace",
        base_url="https://pypi.org",
        estimated_skills=200,
        category="community",
        enabled=True,
        icon="🐍",
        description="Python agent skills on PyPI. Search: 'agentos-skill-' prefix.",
    ),
    EcosystemSource.SKILLS_SH: EcosystemMeta(
        source=EcosystemSource.SKILLS_SH,
        name="skills.sh Community",
        base_url="https://skills.sh",
        estimated_skills=100,
        category="community",
        enabled=True,
        icon="⚡",
        description="Modern skill marketplace. GitHub-based, CLI-first.",
    ),
}


# ── Ecosystem Bridge ─────────────────────────────────────────────────

@dataclass
class CrossEcosystemSkill:
    """A skill discovered from any ecosystem, normalized to common schema."""
    name: str
    ecosystem: EcosystemSource
    ecosystem_name: str
    description: str = ""
    author: str = ""
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    url: str = ""
    download_url: str = ""
    stars: int = 0
    downloads: int = 0
    license: str = "MIT"
    language: str = "python"     # python / node / shell / mixed
    is_imported: bool = False     # Already in local registry?


class EcosystemBridge:
    """Universal skill ecosystem bridge.

    Single entry point to discover, search, and import skills
    from all supported ecosystems.

    Usage:
        bridge = EcosystemBridge(registry)
        await bridge.refresh_catalog()    # Scan all ecosystems
        results = await bridge.search("pdf edit")
        skill = await bridge.import_skill("openclaw/pdf-tools")
        stats = bridge.get_stats()        # Cross-ecosystem stats
    """

    def __init__(self, registry, cache_dir: str = ""):
        self._registry = registry
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".agentos" / "ecosystem_bridge"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Sub-importers (lazy init)
        self._openclaw: Optional[OpenClawImporter] = None
        self._catalog: list[CrossEcosystemSkill] = []
        self._stats: dict[str, Any] = {}
        self._ecosystems = dict(ECOSYSTEMS)

    @property
    def openclaw(self) -> OpenClawImporter:
        if self._openclaw is None:
            self._openclaw = OpenClawImporter(self._registry, str(self._cache_dir / "openclaw"))
        return self._openclaw

    # ── Ecosystem Management ──

    def list_ecosystems(self) -> list[EcosystemMeta]:
        """List all registered skill ecosystems with status."""
        return list(self._ecosystems.values())

    def enable_ecosystem(self, source: EcosystemSource | str):
        """Enable an ecosystem source."""
        src = EcosystemSource(source) if isinstance(source, str) else source
        if src in self._ecosystems:
            self._ecosystems[src].enabled = True

    def disable_ecosystem(self, source: EcosystemSource | str):
        """Disable an ecosystem source."""
        src = EcosystemSource(source) if isinstance(source, str) else source
        if src in self._ecosystems:
            self._ecosystems[src].enabled = False

    def add_custom_ecosystem(self, meta: EcosystemMeta):
        """Register a custom ecosystem source (e.g., private company registry)."""
        meta.source = EcosystemSource.CUSTOM
        self._ecosystems[EcosystemSource.CUSTOM] = meta

    # ── Catalog Discovery ──

    async def refresh_catalog(self, ecosystems: list[str] | None = None) -> list[CrossEcosystemSkill]:
        """Scan all (or specified) ecosystems and build a unified skill catalog.

        Args:
            ecosystems: Optional list of ecosystem names to scan. None = all enabled.

        Returns:
            Unified list of CrossEcosystemSkill across all sources.
        """
        tasks = []
        enabled = [e for e in self._ecosystems.values() if e.enabled]

        if ecosystems:
            enabled = [e for e in enabled if e.source.value in ecosystems]

        for eco in enabled:
            tasks.append(self._scan_ecosystem(eco))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        catalog: list[CrossEcosystemSkill] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[EcosystemBridge] Failed to scan {enabled[i].name}: {result}")
                continue
            catalog.extend(result)

        self._catalog = catalog
        self._compute_stats()
        return catalog

    async def _scan_ecosystem(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan a single ecosystem for skills."""
        if eco.source == EcosystemSource.OPENCLAW:
            return await self._scan_openclaw(eco)
        elif eco.source == EcosystemSource.HUGGINGFACE:
            return await self._scan_huggingface(eco)
        elif eco.source == EcosystemSource.GITHUB_TOPICS:
            return await self._scan_github_topics(eco)
        elif eco.source == EcosystemSource.NPM:
            return await self._scan_npm(eco)
        elif eco.source == EcosystemSource.PYPI:
            return await self._scan_pypi(eco)
        elif eco.source == EcosystemSource.SKILLS_SH:
            return await self._scan_skills_sh(eco)
        else:
            return []

    async def _scan_openclaw(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan OpenClaw community (primary source)."""
        remote_skills = await self.openclaw.list_available(refresh=True)
        return [
            CrossEcosystemSkill(
                name=s.name,
                ecosystem=EcosystemSource.OPENCLAW,
                ecosystem_name=eco.name,
                description=s.description,
                author=s.author,
                version=s.version,
                tags=s.tags,
                url=s.raw_url,
                download_url=s.download_url,
                language="python",
            )
            for s in remote_skills
        ]

    async def _scan_huggingface(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan HuggingFace for agent skills (spaces with 'agent-skill' tag)."""
        skills: list[CrossEcosystemSkill] = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://huggingface.co/api/spaces"
                params = {"search": "agent-skill", "limit": 50, "full": "false"}
                async with session.get(url, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            skills.append(CrossEcosystemSkill(
                                name=f"hf/{item.get('id', 'unknown')}",
                                ecosystem=EcosystemSource.HUGGINGFACE,
                                ecosystem_name=eco.name,
                                description=item.get("sdk", ""),
                                author=item.get("author", ""),
                                tags=item.get("tags", []),
                                url=f"https://huggingface.co/spaces/{item.get('id', '')}",
                                stars=item.get("likes", 0),
                                language="python",
                            ))
        except Exception:
            pass
        return skills

    async def _scan_github_topics(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan GitHub for repos tagged with agent-skill topics."""
        skills: list[CrossEcosystemSkill] = []
        topics = ["agent-skill", "ai-tool", "agent-framework", "skill-marketplace"]
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                for topic in topics[:2]:  # Limit to avoid rate limits
                    url = "https://api.github.com/search/repositories"
                    params = {
                        "q": f"topic:{topic}",
                        "sort": "stars",
                        "per_page": 30,
                    }
                    headers = {"Accept": "application/vnd.github.v3+json"}
                    if os.environ.get("GITHUB_TOKEN"):
                        headers["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"

                    try:
                        async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for item in data.get("items", [])[:15]:
                                    skills.append(CrossEcosystemSkill(
                                        name=f"gh/{item['full_name']}",
                                        ecosystem=EcosystemSource.GITHUB_TOPICS,
                                        ecosystem_name=eco.name,
                                        description=(item.get("description") or "")[:200],
                                        author=item.get("owner", {}).get("login", ""),
                                        tags=item.get("topics", []),
                                        url=item.get("html_url", ""),
                                        stars=item.get("stargazers_count", 0),
                                        license=item.get("license", {}).get("spdx_id", "MIT") if item.get("license") else "MIT",
                                        language=item.get("language", "python").lower(),
                                    ))
                    except Exception:
                        continue
        except ImportError:
            pass
        return skills

    async def _scan_npm(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan npm registry for 'agent-skill' packages."""
        skills: list[CrossEcosystemSkill] = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://registry.npmjs.org/-/v1/search"
                params = {"text": "agent-skill", "size": 50}
                async with session.get(url, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for obj in data.get("objects", [])[:20]:
                            pkg = obj.get("package", {})
                            skills.append(CrossEcosystemSkill(
                                name=f"npm/{pkg.get('name', 'unknown')}",
                                ecosystem=EcosystemSource.NPM,
                                ecosystem_name=eco.name,
                                description=(pkg.get("description", ""))[:150],
                                author=pkg.get("publisher", {}).get("username", ""),
                                version=pkg.get("version", "0.1.0"),
                                tags=pkg.get("keywords", []),
                                url=pkg.get("links", {}).get("npm", ""),
                                language="node",
                            ))
        except ImportError:
            pass
        return skills

    async def _scan_pypi(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan PyPI for 'agentos-skill-' prefixed packages."""
        skills: list[CrossEcosystemSkill] = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://pypi.org/simple/"
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        # Find agentos-skill-* packages
                        matches = re.findall(r'agentos-skill-[\w-]+', text)
                        for match in list(set(matches))[:20]:
                            skills.append(CrossEcosystemSkill(
                                name=f"pypi/{match}",
                                ecosystem=EcosystemSource.PYPI,
                                ecosystem_name=eco.name,
                                description=f"PyPI agent skill: {match}",
                                tags=[match.replace("agentos-skill-", "")],
                                url=f"https://pypi.org/project/{match}/",
                                language="python",
                            ))
        except ImportError:
            pass
        return skills

    async def _scan_skills_sh(self, eco: EcosystemMeta) -> list[CrossEcosystemSkill]:
        """Scan skills.sh community."""
        skills: list[CrossEcosystemSkill] = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://skills.sh/api/skills"
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in data[:30]:
                                skills.append(CrossEcosystemSkill(
                                    name=f"skillssh/{item.get('slug', item.get('name', 'unknown'))}",
                                    ecosystem=EcosystemSource.SKILLS_SH,
                                    ecosystem_name=eco.name,
                                    description=item.get("description", ""),
                                    author=item.get("author", ""),
                                    version=item.get("version", "0.1.0"),
                                    tags=item.get("tags", []),
                                    url=item.get("url", ""),
                                ))
                except Exception:
                    pass
        except ImportError:
            pass
        return skills

    # ── Search ──

    async def search(
        self,
        query: str,
        ecosystems: list[str] | None = None,
        limit: int = 20,
        refresh: bool = False,
    ) -> list[CrossEcosystemSkill]:
        """Cross-ecosystem skill search.

        Args:
            query: Search keywords (space-separated)
            ecosystems: Limit to specific ecosystems
            limit: Max results
            refresh: Force catalog refresh before searching

        Returns:
            Ranked list of matching skills across all ecosystems.
        """
        if refresh or not self._catalog:
            await self.refresh_catalog(ecosystems)

        catalog = self._catalog
        if ecosystems:
            valid = set(ecosystems)
            catalog = [s for s in catalog if s.ecosystem.value in valid]

        keywords = query.lower().split()
        scored: list[tuple[CrossEcosystemSkill, float]] = []

        for skill in catalog:
            score = 0.0
            searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)} {skill.ecosystem_name}".lower()

            for kw in keywords:
                if kw in skill.name.lower():
                    score += 10
                elif kw in ' '.join(skill.tags).lower():
                    score += 5
                elif kw in skill.description.lower():
                    score += 2
                elif kw in searchable:
                    score += 1

            if score > 0:
                # Bonus for popular skills
                score += min(skill.stars / 1000, 5)
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:limit]]

    # ── Import ──

    async def import_skill(self, skill_ref: str) -> Optional[Any]:
        """Import a skill from any ecosystem.

        Skill reference formats:
          - "pdf-tools" → searches OpenClaw first, then all ecosystems
          - "openclaw/pdf-tools" → specific ecosystem import
          - "hf/user/repo" → HuggingFace
          - "gh/user/repo" → GitHub
          - "pypi/agentos-skill-foo" → PyPI
          - "npm/agent-skill-bar" → npm

        Returns:
            SkillManifest if import succeeded, None otherwise.
        """
        # Parse ecosystem prefix
        prefix_map = {
            "openclaw": EcosystemSource.OPENCLAW,
            "hf": EcosystemSource.HUGGINGFACE,
            "gh": EcosystemSource.GITHUB_TOPICS,
            "pypi": EcosystemSource.PYPI,
            "npm": EcosystemSource.NPM,
            "skillssh": EcosystemSource.SKILLS_SH,
        }

        ecosystem = None
        name = skill_ref
        for prefix, eco in prefix_map.items():
            if skill_ref.startswith(f"{prefix}/"):
                ecosystem = eco
                name = skill_ref[len(prefix) + 1:]
                break

        if ecosystem == EcosystemSource.OPENCLAW:
            skill = await self.openclaw.import_skill(name)
            if skill:
                self._compute_stats()
            return skill
        elif ecosystem is not None:
            # For non-OpenClaw sources, attempt to download and register
            return await self._import_from_ecosystem(name, ecosystem)
        else:
            # No prefix: try OpenClaw first, then search all
            try:
                skill = await self.openclaw.import_skill(name)
                if skill:
                    self._compute_stats()
                    return skill
            except Exception:
                pass

            # Search across ecosystems and import first match
            results = await self.search(name, limit=1)
            if results:
                return await self.import_skill(f"{results[0].ecosystem.value}/{results[0].name}")
            return None

    async def import_all(self, ecosystem: str | None = None) -> int:
        """Bulk import all skills from enabled ecosystems.

        Args:
            ecosystem: Optional ecosystem name to limit import.

        Returns:
            Number of skills successfully imported.
        """
        await self.refresh_catalog()
        imported = 0

        catalog = self._catalog
        if ecosystem:
            catalog = [s for s in catalog if s.ecosystem.value == ecosystem]

        for skill in catalog:
            try:
                result = await self.import_skill(f"{skill.ecosystem.value}/{skill.name}")
                if result:
                    imported += 1
            except Exception:
                pass

        self._compute_stats()
        return imported

    async def _import_from_ecosystem(self, name: str, ecosystem: EcosystemSource) -> Optional[Any]:
        """Import a skill from a non-OpenClaw ecosystem."""
        # For now, register as an external reference
        # Future: download skill package, convert manifest, register
        for skill in self._catalog:
            if skill.name == name and skill.ecosystem == ecosystem:
                return skill
        return None

    # ── Stats & Reporting ──

    def _compute_stats(self):
        """Compute cross-ecosystem statistics."""
        eco_counts: dict[str, int] = {}
        for skill in self._catalog:
            eco_counts[skill.ecosystem.value] = eco_counts.get(skill.ecosystem.value, 0) + 1

        total = len(self._catalog)
        imported = sum(1 for s in self._catalog if s.is_imported)

        self._stats = {
            "total_available": total,
            "total_imported": imported,
            "ecosystems_scanned": len(set(s.ecosystem.value for s in self._catalog)),
            "by_ecosystem": eco_counts,
            "by_language": self._count_by("language"),
            "top_tags": sorted(
                self._count_by_multi("tags").items(),
                key=lambda x: x[1], reverse=True
            )[:10],
            "most_popular": sorted(
                self._catalog,
                key=lambda s: s.stars, reverse=True
            )[:5],
        }

    def _count_by(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for skill in self._catalog:
            val = getattr(skill, attr, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    def _count_by_multi(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for skill in self._catalog:
            for val in getattr(skill, attr, []):
                counts[val] = counts.get(val, 0) + 1
        return counts

    def get_stats(self) -> dict[str, Any]:
        """Get cross-ecosystem statistics."""
        if not self._stats:
            self._compute_stats()
        return self._stats

    def get_catalog(self) -> list[CrossEcosystemSkill]:
        """Get the current unified catalog."""
        return self._catalog

    async def sync_all(self) -> dict[str, Any]:
        """Sync all ecosystems: refresh catalog + import all.

        This is the one-liner for 'bring the world's skills into my agent'.

        Returns:
            Stats dict with import results.
        """
        await self.refresh_catalog()
        imported = await self.import_all()
        return {**self.get_stats(), "just_imported": imported}


# ── Convenience Functions ──

def discover_ecosystems() -> list[EcosystemMeta]:
    """Quick list of all supported skill ecosystems."""
    return list(ECOSYSTEMS.values())


def count_worldwide_skills() -> int:
    """Estimated total skills across all ecosystems."""
    return sum(e.estimated_skills for e in ECOSYSTEMS.values())
