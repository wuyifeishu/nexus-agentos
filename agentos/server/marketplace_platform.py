"""
AgentOS Skill Marketplace Platform (v1.8.1)  # noqa: E501

Full-stack developer marketplace:
  - User registration & JWT authentication
  - Skill upload with manifest validation
  - Automated security scanning (dangerous imports, shell injection, obfuscation)
  - Admin review queue (approve/reject with reason)
  - Public skill browsing with search/filter
  - Skill download & version management
  - GitHub-style developer profiles

Tech: FastAPI + SQLite + JWT + bcrypt
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import jwt as pyjwt

try:
    from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from fastapi.staticfiles import StaticFiles
except ImportError:
    raise RuntimeError("FastAPI, pyjwt required. Run: pip install fastapi uvicorn pyjwt")

try:
    import bcrypt
except ImportError:
    bcrypt = None

STATIC_DIR = Path(__file__).parent / "static"
PLATFORM_DIR = Path.home() / ".agentos" / "marketplace"
PLATFORM_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = PLATFORM_DIR / "platform.db"
UPLOAD_DIR = PLATFORM_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.environ.get("MARKETPLACE_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


# ── Database ─────────────────────────────────


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        avatar_url TEXT,
        github_username TEXT,
        role TEXT DEFAULT 'developer',
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        version TEXT NOT NULL DEFAULT '0.1.0',
        description TEXT,
        category TEXT DEFAULT 'uncategorized',
        tags TEXT DEFAULT '[]',
        format TEXT DEFAULT 'agentos',
        entrypoint TEXT,
        manifest_json TEXT,
        file_path TEXT,
        file_size INTEGER,
        file_hash TEXT,
        download_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        security_score INTEGER,
        security_report TEXT,
        review_comment TEXT,
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, author_id)
    );
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id INTEGER NOT NULL REFERENCES skills(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        rating INTEGER CHECK(rating >= 1 AND rating <= 5),
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS api_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL,
        name TEXT,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Ensure admin user exists
    admin = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not admin:
        _hash = _hash_password("admin123")
        db.execute(
            "INSERT INTO users (username, email, password_hash, role, is_admin) VALUES (?,?,?,?,?)",
            ("admin", "admin@agentos.dev", _hash, "admin", 1),
        )
    db.commit()
    db.close()


def _hash_password(password: str) -> str:
    if bcrypt:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return hashlib.sha256(f"agentos:{password}".encode()).hexdigest()


def _verify_password(password: str, password_hash: str) -> bool:
    if bcrypt and password_hash.startswith("$2"):
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    return _hash_password(password) == password_hash


# ── Security Scanner ─────────────────────────


class SecurityScanner:
    """Scans uploaded skill packages for security issues."""

    DANGEROUS_IMPORTS = {
        "os.system",
        "subprocess",
        "eval(",
        "exec(",
        "compile(",
        "__import__",
        "importlib",
        "builtins",
        "ctypes",
        "socket",
        "requests",
        "urllib",
        "http.client",
        "shutil.rmtree",
        "shutil.copy",
        "pathlib.Path.unlink",
        "pickle",
        "marshal",
        "dill",
    }

    DANGEROUS_SHELL = {
        " rm ",
        "rm -rf",
        "sudo ",
        "chmod 777",
        "chown ",
        " | sh",
        " | bash",
        "$(",
        "`",
        "; rm",
        "wget ",
        "curl ",
        "/dev/null",
        "> /etc/",
        "> ~/.ssh/",
    }

    OBFUSCATION_SIGNALS = {
        "base64.b64decode",
        "base64.b64encode",
        "exec(base64",
        "decode('utf-8')",
        "eval(compile",
        "globals()",
        "__builtins__",
        "lambda.*exec",
        "lambda.*eval",
        "getattr.*__",
    }

    @classmethod
    def scan_zip(cls, zip_path: str) -> dict[str, Any]:
        """Scan a skill zip package and return security report."""
        findings = []
        score = 100
        files_scanned = 0
        total_size = 0

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    total_size += info.file_size
                    name = info.filename.lower()

                    # Skip binary files
                    if any(
                        name.endswith(ext)
                        for ext in (".pyc", ".so", ".dll", ".exe", ".png", ".jpg", ".ico")
                    ):
                        continue

                    try:
                        content = zf.read(info.filename).decode("utf-8", errors="replace")
                        files_scanned += 1
                    except Exception:
                        continue

                    content.split("\n")

                    # Check for dangerous imports
                    for imp in cls.DANGEROUS_IMPORTS:
                        if imp in content:
                            findings.append(
                                {
                                    "file": info.filename,
                                    "severity": "high",
                                    "rule": f"dangerous_import:{imp}",
                                    "line": content.find(imp),
                                }
                            )
                            score -= 20

                    # Check for shell injection
                    for pat in cls.DANGEROUS_SHELL:
                        if pat in content:
                            findings.append(
                                {
                                    "file": info.filename,
                                    "severity": "critical",
                                    "rule": f"shell_injection:{pat.strip()}",
                                }
                            )
                            score -= 30

                    # Check for obfuscation
                    for pat in cls.OBFUSCATION_SIGNALS:
                        if re.search(pat, content):
                            findings.append(
                                {
                                    "file": info.filename,
                                    "severity": "medium",
                                    "rule": f"obfuscation:{pat}",
                                }
                            )
                            score -= 15

                    # Check for hardcoded secrets
                    if re.search(
                        r'(api_key|secret|password|token)\s*[:=]\s*["\'][a-zA-Z0-9_\-]{20,}',
                        content,
                    ):
                        findings.append(
                            {"file": info.filename, "severity": "high", "rule": "hardcoded_secret"}
                        )
                        score -= 25
        except zipfile.BadZipFile:
            return {"score": 0, "findings": [{"severity": "critical", "rule": "invalid_zip"}]}

        return {
            "score": max(0, score),
            "findings": findings,
            "files_scanned": files_scanned,
            "total_size": total_size,
            "risk_level": (
                "low"
                if score >= 80
                else "medium" if score >= 50 else "high" if score >= 20 else "critical"
            ),
        }

    @classmethod
    def validate_manifest(cls, manifest: dict) -> list[str]:
        """Validate skill manifest structure. Returns list of errors."""
        errors = []
        required = ["name", "version", "description"]
        for field in required:
            if not manifest.get(field):
                errors.append(f"Missing required field: {field}")

        if "name" in manifest:
            name = manifest["name"]
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]*$", name):
                errors.append(
                    f"Invalid skill name: {name}. Use alphanumeric, hyphens, underscores."
                )

        if "version" in manifest:
            version = manifest["version"]
            if not re.match(r"^\d+\.\d+\.\d+$", version):
                errors.append(f"Invalid version format: {version}. Use semver (e.g., 0.1.0).")

        return errors


# ── Auth Utilities ───────────────────────────

security_scheme = HTTPBearer(auto_error=False)


def create_token(user_id: int, username: str, is_admin: bool) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (payload["user_id"],)).fetchone()
    db.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)


async def get_admin_user(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


# ── FastAPI App ──────────────────────────────


def create_marketplace_app() -> FastAPI:
    init_db()

    app = FastAPI(
        title="AgentOS Skill Marketplace",
        version="1.8.1",
        description="Open developer marketplace for AgentOS skills. Upload, review, and discover AI agent skills.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Web UI ──
    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        html_path = STATIC_DIR / "platform.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Marketplace Platform</h1>", status_code=404)

    # ── Auth Endpoints ──

    @app.post("/api/auth/register")
    async def register(
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        display_name: str = Form(""),
    ):
        if len(password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        if not re.match(r"^[a-zA-Z0-9_]{3,30}$", username):
            raise HTTPException(400, "Username: 3-30 chars, alphanumeric/underscore")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=? OR email=?", (username, email)
        ).fetchone()
        if existing:
            db.close()
            raise HTTPException(409, "Username or email already exists")

        pw_hash = _hash_password(password)
        try:
            db.execute(
                "INSERT INTO users (username, email, password_hash, display_name) VALUES (?,?,?,?)",
                (username, email, pw_hash, display_name or username),
            )
            db.commit()
            user_id = db.lastrowid
        finally:
            db.close()

        token = create_token(user_id, username, False)
        return {
            "token": token,
            "user": {"id": user_id, "username": username, "email": email, "is_admin": False},
        }

    @app.post("/api/auth/login")
    async def login(username: str = Form(...), password: str = Form(...)):
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (username, username)
        ).fetchone()
        if not user or not _verify_password(password, user["password_hash"]):
            db.close()
            raise HTTPException(401, "Invalid credentials")
        db.close()

        token = create_token(user["id"], user["username"], bool(user["is_admin"]))
        return {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "display_name": user["display_name"],
                "is_admin": bool(user["is_admin"]),
                "github_username": user["github_username"],
            },
        }

    @app.get("/api/auth/me")
    async def me(user: dict = Depends(get_current_user)):
        return {"user": {k: v for k, v in user.items() if k != "password_hash"}}

    # ── Skill Upload ──

    @app.post("/api/skills/upload")
    async def upload_skill(
        file: UploadFile = File(...),
        name: str = Form(""),
        version: str = Form("0.1.0"),
        description: str = Form(""),
        category: str = Form("uncategorized"),
        tags: str = Form("[]"),
        user: dict = Depends(get_current_user),
    ):
        """Upload a skill package (.zip containing skill files + manifest.json)."""
        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(400, "Only .zip files are accepted")

        # Save uploaded file
        ts = int(time.time())
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename)
        file_id = f"{user['id']}_{ts}_{safe_name}"
        file_path = UPLOAD_DIR / file_id
        content = await file.read()
        file_path.write_bytes(content)

        # Validate zip
        if not zipfile.is_zipfile(str(file_path)):
            file_path.unlink()
            raise HTTPException(400, "Invalid zip file")

        # Extract and validate manifest
        manifest = {}
        with zipfile.ZipFile(str(file_path)) as zf:
            if "skill.yaml" in zf.namelist():
                manifest_text = zf.read("skill.yaml").decode("utf-8")
                manifest = _parse_yaml_simple(manifest_text)
            elif "skill.json" in zf.namelist():
                manifest = json.loads(zf.read("skill.json"))
            elif "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json"))

        # Use form fields as fallback
        skill_name = manifest.get("name") or name or file.filename.replace(".zip", "")
        skill_version = manifest.get("version") or version
        skill_desc = manifest.get("description") or description
        skill_category = manifest.get("category") or category
        skill_tags = manifest.get("tags", []) if isinstance(manifest.get("tags"), list) else []

        # Use form tags if manifest has none
        if not skill_tags:
            try:
                skill_tags = json.loads(tags) if isinstance(tags, str) else tags
            except json.JSONDecodeError:
                skill_tags = []

        # Validate
        manifest_errors = SecurityScanner.validate_manifest(
            {
                "name": skill_name,
                "version": skill_version,
                "description": skill_desc,
            }
        )
        if manifest_errors:
            file_path.unlink()
            raise HTTPException(400, f"Manifest validation failed: {'; '.join(manifest_errors)}")

        # Security scan
        security = SecurityScanner.scan_zip(str(file_path))
        auto_status = "published" if security["risk_level"] == "low" else "flagged"
        if security["score"] <= 20:
            auto_status = "rejected"
            file_path.unlink()
            raise HTTPException(
                400,
                f"Security scan failed (score: {security['score']}/100). "
                f"Risk: {security['risk_level']}. Findings: {len(security['findings'])}",
            )

        # Compute hash
        file_hash = hashlib.sha256(content).hexdigest()

        db = get_db()
        try:
            db.execute(
                """INSERT INTO skills (author_id, name, version, description, category, tags,
                   format, entrypoint, manifest_json, file_path, file_size, file_hash,
                   status, security_score, security_report)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user["id"],
                    skill_name,
                    skill_version,
                    skill_desc,
                    skill_category,
                    json.dumps(skill_tags),
                    manifest.get("format", "agentos"),
                    manifest.get("entrypoint", ""),
                    json.dumps(manifest, ensure_ascii=False),
                    str(file_path.absolute()),
                    os.path.getsize(str(file_path)),
                    file_hash,
                    auto_status,
                    security["score"],
                    json.dumps(security, ensure_ascii=False),
                ),
            )
            db.commit()
            skill_id = db.lastrowid
        except sqlite3.IntegrityError:
            file_path.unlink()
            db.close()
            raise HTTPException(409, "You already have a skill with this name")
        db.close()

        return {
            "id": skill_id,
            "name": skill_name,
            "version": skill_version,
            "status": auto_status,
            "security_score": security["score"],
            "risk_level": security["risk_level"],
            "findings_count": len(security["findings"]),
        }

    # ── Public Browse ──

    @app.get("/api/skills")
    async def list_skills(
        q: str = Query(""),
        category: str = Query(""),
        status: str = Query("published"),
        sort: str = Query("downloads"),
        page: int = Query(1),
        limit: int = Query(30),
    ):
        db = get_db()
        where = ["s.status = ?"]
        params: list = [status]

        if q:
            where.append("(s.name LIKE ? OR s.description LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if category:
            where.append("s.category = ?")
            params.append(category)

        order = "s.download_count DESC" if sort == "downloads" else "s.created_at DESC"
        offset = (page - 1) * limit

        skills = db.execute(
            f"""SELECT s.*, u.username as author_name, u.display_name as author_display
                FROM skills s JOIN users u ON s.author_id = u.id
                WHERE {' AND '.join(where)}
                ORDER BY {order}
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        total = db.execute(
            f"SELECT COUNT(*) FROM skills s WHERE {' AND '.join(where)}", params
        ).fetchone()[0]
        db.close()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "skills": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "version": s["version"],
                    "description": s["description"],
                    "category": s["category"],
                    "tags": json.loads(s["tags"]),
                    "format": s["format"],
                    "download_count": s["download_count"],
                    "status": s["status"],
                    "security_score": s["security_score"],
                    "author": {"username": s["author_name"], "display_name": s["author_display"]},
                    "created_at": s["created_at"],
                }
                for s in skills
            ],
        }

    @app.get("/api/skills/{skill_id}")
    async def get_skill_detail(skill_id: int):
        db = get_db()
        skill = db.execute(
            """SELECT s.*, u.username as author_name, u.display_name as author_display
               FROM skills s JOIN users u ON s.author_id = u.id
               WHERE s.id = ? AND s.status = 'published'""",
            (skill_id,),
        ).fetchone()
        if not skill:
            db.close()
            raise HTTPException(404, "Skill not found")

        # Get review stats
        review_stats = db.execute(
            "SELECT COUNT(*) as count, AVG(rating) as avg_rating FROM reviews WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        db.close()

        return {
            "id": skill["id"],
            "name": skill["name"],
            "version": skill["version"],
            "description": skill["description"],
            "category": skill["category"],
            "tags": json.loads(skill["tags"]),
            "format": skill["format"],
            "entrypoint": skill["entrypoint"],
            "manifest": json.loads(skill["manifest_json"] or "{}"),
            "download_count": skill["download_count"],
            "status": skill["status"],
            "security_score": skill["security_score"],
            "author": {"username": skill["author_name"], "display_name": skill["author_display"]},
            "created_at": skill["created_at"],
            "reviews": {
                "count": review_stats["count"] or 0,
                "avg_rating": round(review_stats["avg_rating"] or 0, 1),
            },
        }

    # ── Download ──

    @app.get("/api/skills/{skill_id}/download")
    async def download_skill(skill_id: int):
        db = get_db()
        skill = db.execute(
            "SELECT * FROM skills WHERE id = ? AND status = 'published'", (skill_id,)
        ).fetchone()
        if not skill:
            db.close()
            raise HTTPException(404, "Skill not found")

        db.execute(
            "UPDATE skills SET download_count = download_count + 1 WHERE id = ?", (skill_id,)
        )
        db.commit()
        db.close()

        file_path = Path(skill["file_path"])
        if not file_path.exists():
            raise HTTPException(404, "Skill file not found on server")

        return FileResponse(
            path=str(file_path),
            filename=f"{skill['name']}-{skill['version']}.zip",
            media_type="application/zip",
        )

    # ── Admin: Review Queue ──

    @app.get("/api/admin/review-queue")
    async def review_queue(user: dict = Depends(get_admin_user)):
        db = get_db()
        skills = db.execute("""SELECT s.*, u.username as author_name
               FROM skills s JOIN users u ON s.author_id = u.id
               WHERE s.status IN ('pending', 'flagged')
               ORDER BY s.created_at DESC""").fetchall()
        db.close()
        return {
            "count": len(skills),
            "skills": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "version": s["version"],
                    "description": s["description"],
                    "category": s["category"],
                    "status": s["status"],
                    "security_score": s["security_score"],
                    "security_report": json.loads(s["security_report"] or "{}"),
                    "author": s["author_name"],
                    "created_at": s["created_at"],
                }
                for s in skills
            ],
        }

    @app.post("/api/admin/review/{skill_id}")
    async def review_skill(
        skill_id: int,
        action: str = Form(...),  # "approve" or "reject"
        comment: str = Form(""),
        user: dict = Depends(get_admin_user),
    ):
        if action not in ("approve", "reject"):
            raise HTTPException(400, "Action must be 'approve' or 'reject'")

        db = get_db()
        skill = db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if not skill:
            db.close()
            raise HTTPException(404, "Skill not found")

        new_status = "published" if action == "approve" else "rejected"
        db.execute(
            "UPDATE skills SET status=?, review_comment=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_status, comment, user["id"], skill_id),
        )
        db.commit()
        db.close()

        return {"id": skill_id, "status": new_status, "action": action}

    # ── Categories ──

    @app.get("/api/categories")
    async def list_categories():
        db = get_db()
        cats = db.execute(
            "SELECT category, COUNT(*) as count FROM skills WHERE status='published' GROUP BY category ORDER BY count DESC"  # noqa: E501
        ).fetchall()
        db.close()
        return {"categories": [{"name": c["category"], "count": c["count"]} for c in cats]}

    # ── Developer Profile ──

    @app.get("/api/developers/{username}")
    async def developer_profile(username: str):
        db = get_db()
        user = db.execute(
            "SELECT id, username, display_name, avatar_url, github_username, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not user:
            db.close()
            raise HTTPException(404, "Developer not found")

        skills = db.execute(
            "SELECT id, name, version, description, category, tags, download_count, status, created_at FROM skills WHERE author_id = ? AND status = 'published' ORDER BY download_count DESC",  # noqa: E501
            (user["id"],),
        ).fetchall()
        db.close()

        return {
            "developer": dict(user),
            "skills": [dict(s) for s in skills],
            "total_skills": len(skills),
            "total_downloads": sum(s["download_count"] for s in skills),
        }

    # ── My Skills ──

    @app.get("/api/my/skills")
    async def my_skills(user: dict = Depends(get_current_user)):
        db = get_db()
        skills = db.execute(
            "SELECT * FROM skills WHERE author_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
        db.close()
        return {"skills": [dict(s) for s in skills]}

    # ── Health ──

    @app.get("/api/health")
    async def health_check():
        db = get_db()
        skill_count = db.execute("SELECT COUNT(*) FROM skills WHERE status='published'").fetchone()[
            0
        ]
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        db.close()
        return {
            "status": "healthy",
            "version": "1.8.1",
            "published_skills": skill_count,
            "registered_developers": user_count,
        }

    return app


def _parse_yaml_simple(text: str) -> dict[str, Any]:
    """Simple YAML parser for skill manifests. Handles basic key: value + lists."""
    result: dict[str, Any] = {}
    current_key = None
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and not stripped.startswith("- "):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val:
                result[key] = val
            else:
                result[key] = []
                current_key = key
        elif stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip('"').strip("'")
            result[current_key].append(item)
    return result


def start_marketplace_platform(host: str = "0.0.0.0", port: int = 8911) -> None:
    """Start the marketplace platform server (blocking)."""
    import uvicorn

    app = create_marketplace_app()
    print("\n  AgentOS Skill Marketplace Platform v1.8.1")
    print(f"  Local:  http://{host}:{port}")
    print("  Admin:  admin / admin123")
    print("  Upload: POST /api/skills/upload  |  Browse: GET /api/skills")
    print()
    uvicorn.run(app, host=host, port=port, log_level="info")
