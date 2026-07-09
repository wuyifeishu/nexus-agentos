"""
AgentOS Skill Marketplace Server (v1.8.1).

FastAPI server serving:
  - /api/skills/installed  — list all 64+ installed skills
  - /api/skills/search     — search by name/description/tag
  - /api/skills/{name}     — get skill detail
  - /api/ecosystems        — external ecosystem links
  - /                     — marketplace web UI (static page)

Also serves built-in MCP info: /api/mcp/servers, /api/mcp/tools
"""

from __future__ import annotations

from pathlib import Path

# ── FastAPI app ──
try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:
    FastAPI = object  # type: ignore

from agentos.marketplace.registry import SkillRegistry

STATIC_DIR = Path(__file__).parent / "static"


def create_marketplace_app() -> FastAPI:
    """Create and configure the marketplace FastAPI application."""

    if FastAPI is object:
        raise RuntimeError("FastAPI not installed. Run: pip install fastapi uvicorn")

    app = FastAPI(
        title="AgentOS Skill Marketplace",
        version="1.8.1",
        description="Browse, search, and install skills. Compatible with OpenClaw/MCP ecosystem.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    registry = SkillRegistry()

    # ── Static files ─────────────────────────

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve marketplace web UI."""
        html_path = STATIC_DIR / "marketplace.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8")
            return HTMLResponse(content)
        return HTMLResponse("<h1>Marketplace UI not found</h1>", status_code=404)

    # ── Skill APIs ───────────────────────────

    @app.get("/api/skills/installed")
    async def list_installed():
        """List all installed skills with metadata."""
        skills = registry.list_installed()
        return {
            "count": len(skills),
            "skills": [
                {
                    "name": s.name,
                    "version": s.version,
                    "description": s.description,
                    "author": s.author,
                    "tags": s.tags,
                    "category": s.category,
                    "source": s.source,
                    "format": s.format,
                    "entrypoint": s.entrypoint,
                    "installed_at": getattr(s, "installed_at", None),
                }
                for s in skills
            ],
        }

    @app.get("/api/skills/search")
    async def search_skills(q: str = Query("", description="Search query"), limit: int = Query(50)):
        """Search installed skills by name/description/tag."""
        skills = registry.list_installed()
        q_lower = q.lower()
        results = []
        for s in skills:
            if (
                q_lower in (s.name or "").lower()
                or q_lower in (s.description or "").lower()
                or any(q_lower in (t or "").lower() for t in (s.tags or []))
            ):
                results.append(
                    {
                        "name": s.name,
                        "version": s.version,
                        "description": s.description,
                        "tags": s.tags,
                        "category": s.category,
                    }
                )
                if len(results) >= limit:
                    break
        return {"query": q, "count": len(results), "results": results}

    @app.get("/api/skills/{name}")
    async def get_skill(name: str):
        """Get detailed info for a specific skill."""
        skill = registry.get_installed(name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        return {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "author": skill.author,
            "tags": skill.tags,
            "category": skill.category,
            "source": skill.source,
            "format": skill.format,
            "entrypoint": skill.entrypoint,
            "tools": [t.to_dict() if hasattr(t, "to_dict") else t for t in (skill.tools or [])],
            "dependencies": skill.dependencies,
            "installed_at": getattr(skill, "installed_at", None),
        }

    # ── Ecosystem API ────────────────────────

    @app.get("/api/ecosystems")
    async def list_ecosystems():
        """List external skill ecosystems compatible with AgentOS."""
        return {
            "ecosystems": [
                {
                    "name": "OpenClaw Skill Store",
                    "url": "https://github.com/nicepkg/openclaw-skill-store",
                    "skill_count": "13,700+",
                    "format": "openclaw",
                    "description": "Largest community-driven skill ecosystem",
                    "badge": "github",
                },
                {
                    "name": "ClawHub",
                    "url": "https://clawhub.eu.org/",
                    "skill_count": "curated",
                    "format": "openclaw",
                    "description": "Curated high-quality OpenClaw skills",
                },
                {
                    "name": "Skills Marketplace",
                    "url": "https://skills.sh/",
                    "skill_count": "multi-framework",
                    "format": "openclaw/agentos",
                    "description": "Cross-framework skill discovery platform",
                },
                {
                    "name": "MCP Servers",
                    "url": "https://github.com/modelcontextprotocol/servers",
                    "skill_count": "2,000+",
                    "format": "mcp",
                    "description": "Official MCP server registry",
                },
                {
                    "name": "LobeHub Plugins",
                    "url": "https://lobehub.com/plugins",
                    "skill_count": "356+",
                    "format": "lobehub",
                    "description": "LobeChat plugin ecosystem, adaptable to AgentOS",
                },
                {
                    "name": "Awesome Agent Skills",
                    "url": "https://github.com/topics/agent-skills",
                    "skill_count": "curated",
                    "format": "multi",
                    "description": "Community curated list of agent skills",
                },
            ]
        }

    # ── MCP Info API ─────────────────────────

    @app.get("/api/mcp/servers")
    async def mcp_servers():
        """List built-in MCP servers and their tools."""
        try:
            from agentos.mcp.builtin_servers import create_default_registry

            reg = create_default_registry()
            return {
                "servers": [
                    {
                        "name": name,
                        "tool_count": len(reg._servers[name].get_tools()),
                        "tools": [
                            {"name": t["name"], "description": t["description"]}
                            for t in reg._servers[name].get_tools()
                        ],
                    }
                    for name in reg.server_names
                ],
                "total_tools": reg.tool_count,
            }
        except Exception as e:
            return {"error": str(e), "servers": []}

    return app


def start_marketplace_server(host: str = "0.0.0.0", port: int = 8910) -> None:
    """Start the marketplace server (blocking)."""
    import uvicorn

    app = create_marketplace_app()
    print("\n  AgentOS Skill Marketplace")
    print(f"  Local:  http://{host}:{port}")
    print(f"  Skills: {len(SkillRegistry().list_installed())} installed")
    print()
    uvicorn.run(app, host=host, port=port, log_level="info")
