"""
Skill Store Server — Web-based skill marketplace with embedded browser support.
Serves a local web UI that lists skills from multiple sources (OpenClaw, ClawHub,
SkillsMP, LobeHub, etc.) and provides one-click install via the marketplace importer.

Architecture:
  - FastAPI server (localhost:18900 by default)
  - Web UI with embedded iframe links to external skill stores
  - REST API: GET /api/skills, POST /api/install, GET /api/sources
  - WebSocket for real-time install progress

Usage:
    agentos skill-store                # Start skill store server
    agentos skill-store --port 18900   # Custom port
    agentos skill-store --open         # Auto-open in browser

Requirements: pip install fastapi uvicorn aiohttp
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

try:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


# ── Constants ──
DEFAULT_PORT = 18900
STATIC_DIR = Path(__file__).parent / "static"

SKILL_SOURCES: list[dict] = [
    {
        "id": "openclaw",
        "name": "OpenClaw Skill Store",
        "url": "https://github.com/nicepkg/openclaw-skill-store",
        "web_url": "https://github.com/nicepkg/openclaw-skill-store/tree/main/skills",
        "description": "OpenClaw 官方社区技能商店，14+ 核心技能",
        "skill_count": "14+",
        "icon": "openclaw",
        "tags": ["官方", "社区", "文档处理"],
        "installable": True,
        "source_type": "openclaw",
    },
    {
        "id": "clawhub",
        "name": "ClawHub",
        "url": "https://github.com/clawhub-community/skills",
        "web_url": "https://github.com/clawhub-community/skills",
        "description": "ClawHub 社区技能聚合，5,700+ 技能",
        "skill_count": "5,700+",
        "icon": "clawhub",
        "tags": ["社区", "聚合", "高质量"],
        "installable": False,
        "source_type": "github",
    },
    {
        "id": "skillsmp",
        "name": "SkillsMP",
        "url": "https://skills.mp/",
        "web_url": "https://skills.mp/",
        "description": "技能界的 Google，164 万技能文件索引",
        "skill_count": "164万+",
        "icon": "skillsmp",
        "tags": ["索引", "搜索", "规模最大"],
        "installable": False,
        "source_type": "web",
    },
    {
        "id": "lobehub",
        "name": "LobeHub Skills",
        "url": "https://lobehub.com/skills",
        "web_url": "https://lobehub.com/skills",
        "description": "LobeHub 生态精品技能平台，28 万+",
        "skill_count": "28万+",
        "icon": "lobehub",
        "tags": ["精品", "集成", "多模态"],
        "installable": False,
        "source_type": "web",
    },
    {
        "id": "skillhub",
        "name": "SkillHub Club",
        "url": "https://skillhub.club/",
        "web_url": "https://skillhub.club/",
        "description": "AI 评分驱动的品质筛选市集",
        "skill_count": "1.6万+",
        "icon": "skillhub",
        "tags": ["品质", "AI评分", "精选"],
        "installable": False,
        "source_type": "web",
    },
    {
        "id": "skills_sh",
        "name": "skills.sh",
        "url": "https://skills.sh/",
        "web_url": "https://skills.sh/",
        "description": "Vercel Labs 运营，npx skills add 一键安装",
        "skill_count": "67万+",
        "icon": "skills_sh",
        "tags": ["一键安装", "CLI", "多平台"],
        "installable": False,
        "source_type": "web",
    },
    {
        "id": "awesome_agent_skills",
        "name": "awesome-agent-skills",
        "url": "https://github.com/nicepkg/awesome-agent-skills",
        "web_url": "https://github.com/nicepkg/awesome-agent-skills",
        "description": "人工审核的优质技能合集，380+ 精选",
        "skill_count": "380+",
        "icon": "awesome",
        "tags": ["人工审核", "安全", "精选"],
        "installable": False,
        "source_type": "github",
    },
]

# Known OpenClaw skills (from importer catalog + community)
OPENCLAW_SKILLS: list[dict] = [
    {
        "name": "skill-creator",
        "description": "Create new skills from templates",
        "tags": ["meta", "development"],
    },
    {
        "name": "pdf-tools",
        "description": "PDF manipulation, merge, split, extract text",
        "tags": ["document", "pdf"],
    },
    {
        "name": "xlsx-tools",
        "description": "Excel/Spreadsheet creation and editing",
        "tags": ["document", "excel"],
    },
    {"name": "docx-tools", "description": "Word document processing", "tags": ["document", "word"]},
    {
        "name": "pptx-tools",
        "description": "PowerPoint presentation generation",
        "tags": ["document", "ppt"],
    },
    {
        "name": "image-tools",
        "description": "Image processing, resize, convert, OCR",
        "tags": ["media", "image"],
    },
    {
        "name": "web-search",
        "description": "Advanced web search with multiple engines",
        "tags": ["search", "web"],
    },
    {
        "name": "browser-automation",
        "description": "Browser automation with Playwright",
        "tags": ["browser", "automation"],
    },
    {
        "name": "code-review",
        "description": "Automated code review and suggestions",
        "tags": ["code", "quality"],
    },
    {
        "name": "git-tools",
        "description": "Git workflow automation and helpers",
        "tags": ["git", "devops"],
    },
    {
        "name": "file-organizer",
        "description": "Automated file organization and cleanup",
        "tags": ["files", "automation"],
    },
    {
        "name": "data-analysis",
        "description": "Data analysis and visualization",
        "tags": ["data", "analytics"],
    },
    {
        "name": "api-tester",
        "description": "API testing and documentation generation",
        "tags": ["api", "testing"],
    },
    {
        "name": "markdown-tools",
        "description": "Markdown editing, preview, and conversion",
        "tags": ["document", "markdown"],
    },
]


# ── Server ──


def create_app() -> FastAPI:
    """Create the FastAPI application for the skill store."""
    app = FastAPI(title="NexusAgentOS Skill Store", version="1.7.5")

    # ── API Routes ──

    @app.get("/api/sources")
    async def list_sources():
        """List all skill sources (marketplaces)."""
        return JSONResponse(SKILL_SOURCES)

    @app.get("/api/skills")
    async def list_skills(source: str = "openclaw", search: str = ""):
        """List skills from a specific source."""
        if source == "openclaw":
            skills = OPENCLAW_SKILLS
            if search:
                skills = [
                    s
                    for s in skills
                    if search.lower() in s["name"].lower()
                    or search.lower() in s["description"].lower()
                    or any(search.lower() in t.lower() for t in s.get("tags", []))
                ]
            return JSONResponse(
                {
                    "source": "openclaw",
                    "source_name": "OpenClaw Skill Store",
                    "total": len(skills),
                    "skills": skills,
                }
            )
        return JSONResponse(
            {
                "source": source,
                "total": 0,
                "skills": [],
                "message": f"Source '{source}' is not locally installable. Open the marketplace URL to browse.",
            }
        )

    @app.post("/api/install")
    async def install_skill(skill_name: str, source: str = "openclaw"):
        """Install a skill from a source. Uses the marketplace importer."""
        try:
            # Add agentos to path
            agentos_root = str(Path(__file__).parent.parent.parent)
            if agentos_root not in sys.path:
                sys.path.insert(0, agentos_root)

            from agentos.marketplace.importer import OpenClawImporter
            from agentos.marketplace.registry import SkillRegistry

            install_dir = Path.home() / ".agentos" / "skills"
            registry = SkillRegistry(install_dir=str(install_dir))

            if source == "openclaw":
                importer = OpenClawImporter(registry)
                skill = await importer.import_skill(skill_name)
                if skill:
                    return JSONResponse(
                        {
                            "status": "installed",
                            "skill": skill_name,
                            "path": (
                                str(skill.path)
                                if hasattr(skill, "path")
                                else str(install_dir / skill_name)
                            ),
                        }
                    )
                return JSONResponse(
                    {
                        "status": "failed",
                        "skill": skill_name,
                        "error": "Skill not found in OpenClaw store",
                    },
                    status_code=404,
                )

            return JSONResponse(
                {
                    "status": "not_installable",
                    "skill": skill_name,
                    "message": f"Source '{source}' requires manual installation.",
                }
            )
        except Exception as e:
            return JSONResponse(
                {
                    "status": "error",
                    "skill": skill_name,
                    "error": str(e),
                },
                status_code=500,
            )

    @app.post("/api/install-all")
    async def install_all(source: str = "openclaw"):
        """Batch install all skills from a source."""
        try:
            agentos_root = str(Path(__file__).parent.parent.parent)
            if agentos_root not in sys.path:
                sys.path.insert(0, agentos_root)

            from agentos.marketplace.importer import OpenClawImporter
            from agentos.marketplace.registry import SkillRegistry

            install_dir = Path.home() / ".agentos" / "skills"
            registry = SkillRegistry(install_dir=str(install_dir))

            if source == "openclaw":
                importer = OpenClawImporter(registry)
                results = await importer.import_all()
                return JSONResponse(
                    {
                        "status": "completed",
                        "total": len(results),
                        "installed": [r.get("name", "") for r in results],
                        "failed": [],
                    }
                )

            return JSONResponse(
                {"status": "error", "error": f"Cannot batch install from {source}"}, status_code=400
            )
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "1.7.5"}

    # ── Static Files ──
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the skill store web UI."""
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path), media_type="text/html")
        return HTMLResponse(_FALLBACK_HTML)

    return app


# ── Fallback HTML (when static/index.html is missing) ──
_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NexusAgentOS Skill Store</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
  .subtitle { color: #8b949e; margin-bottom: 2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
  .card h2 { font-size: 1rem; color: var(--accent); margin-bottom: 0.5rem; }
  .card p { font-size: 0.875rem; color: #8b949e; margin-bottom: 0.75rem; }
  .tags { display: flex; gap: 0.375rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
  .btn-primary { background: #238636; border-color: #238636; color: #fff; }
  .btn-outline { background: transparent; color: var(--text); }
  .btn-outline:hover { background: #30363d; }
  .count { font-size: 0.75rem; color: #8b949e; }
</style>
</head>
<body>
<h1>NexusAgentOS Skill Store</h1>
<p class="subtitle">从社区市场发现和安装技能。启动完整 UI：pip install textual && agentos tui --market</p>
<div class="grid" id="sources"></div>
<script>
  fetch('/api/sources').then(r => r.json()).then(sources => {
    const grid = document.getElementById('sources');
    sources.forEach(s => {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<h2>${s.name} <span class="count">(${s.skill_count})</span></h2>
        <p>${s.description}</p>
        <div class="tags">${s.tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>
        ${s.installable
          ? `<button class="btn btn-primary" onclick="installAll('${s.id}')">安装全部</button>`
          : `<a href="${s.web_url}" target="_blank" class="btn btn-outline">打开市场</a>`}`;
      grid.appendChild(card);
    });
  });
  function installAll(src) {
    fetch('/api/install-all?source=' + src, { method: 'POST' })
      .then(r => r.json()).then(d => alert('安装完成: ' + d.installed?.length + ' 个技能'));
  }
</script>
</body>
</html>"""


# ── Entry Point ──


def launch_skill_store(
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    open_browser: bool = False,
) -> None:
    """Launch the skill store web server.

    Args:
        port: HTTP port to listen on.
        host: Host to bind to.
        open_browser: Auto-open in system browser.
    """
    if not FASTAPI_AVAILABLE:
        print("ERROR: fastapi/uvicorn not installed. Run: pip install fastapi uvicorn")
        return

    app = create_app()

    url = f"http://{host}:{port}"
    print(f"NexusAgentOS Skill Store starting at {url}")

    if open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NexusAgentOS Skill Store Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--open", action="store_true", dest="open_browser", help="Open in browser")
    args = parser.parse_args()
    launch_skill_store(port=args.port, host=args.host, open_browser=args.open_browser)
