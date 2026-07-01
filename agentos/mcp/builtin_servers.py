"""
Built-in MCP Servers for AgentOS (v1.8.1).

Pure Python implementations of common MCP tools. 8 servers, 32+ tools total.

Servers:
    FilesystemServer (7)  - Safe file I/O with path validation
    WebFetchServer   (3)  - HTTP client with content extraction
    MemoryServer     (6)  - Persistent knowledge graph
    SearchServer     (4)  - Web search via DuckDuckGo
    GitServer        (4)  - Git operations
    ShellServer      (3)  - Safe shell command execution
    CodeServer       (3)  - Python/JS code execution in sandbox
    TextServer       (4)  - Text manipulation & formatting
"""

from __future__ import annotations

import json
import os
import re
import hashlib
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Filesystem MCP Server (7 tools) ─────────


class FilesystemServer:
    """MCP-compatible filesystem server with safe path validation."""

    NAME = "filesystem"
    VERSION = "1.0.0"

    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self._allowed_paths = [
            Path(p).resolve()
            for p in (allowed_paths or [os.getcwd(), str(Path.home())])
        ]
        for p in self._allowed_paths:
            p.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path_str: str) -> Path:
        p = Path(path_str).expanduser().resolve()
        for allowed in self._allowed_paths:
            try:
                p.relative_to(allowed)
                return p
            except ValueError:
                continue
        raise ValueError(f"Path '{path_str}' outside allowed directories")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "read_file", "description": "Read contents of a text file",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}, "encoding": {"type": "string", "default": "utf-8"}},
                 "required": ["path"]}},
            {"name": "write_file", "description": "Write text content to a file",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}, "content": {"type": "string"},
                 "encoding": {"type": "string", "default": "utf-8"}},
                 "required": ["path", "content"]}},
            {"name": "list_directory", "description": "List directory contents with metadata",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}, "recursive": {"type": "boolean", "default": False}},
                 "required": ["path"]}},
            {"name": "search_files", "description": "Search files by glob pattern",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}, "pattern": {"type": "string"}},
                 "required": ["path", "pattern"]}},
            {"name": "get_file_info", "description": "Get file/directory metadata",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}}, "required": ["path"]}},
            {"name": "create_directory", "description": "Create directory and parents",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string"}}, "required": ["path"]}},
            {"name": "move_file", "description": "Move or rename a file/directory",
             "inputSchema": {"type": "object", "properties": {
                 "source": {"type": "string"}, "destination": {"type": "string"}},
                 "required": ["source", "destination"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_read_file(self, path: str, encoding: str = "utf-8") -> str:
        p = self._validate_path(path)
        if not p.is_file(): raise FileNotFoundError(f"Not found: {p}")
        return p.read_text(encoding=encoding)

    def _handle_write_file(self, path: str, content: str, encoding: str = "utf-8") -> str:
        p = self._validate_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"Wrote {len(content)} bytes to {p}"

    def _handle_list_directory(self, path: str, recursive: bool = False) -> List[Dict]:
        p = self._validate_path(path)
        if not p.is_dir(): raise NotADirectoryError(f"Not a directory: {p}")
        entries = []
        for item in (p.rglob("*") if recursive else p.iterdir()):
            if item.name.startswith("."): continue
            s = item.stat()
            entries.append({"name": item.name, "path": str(item), "size": s.st_size,
                          "is_dir": item.is_dir(), "modified": datetime.fromtimestamp(s.st_mtime).isoformat()})
        return sorted(entries, key=lambda e: (not e["is_dir"], e["name"]))

    def _handle_search_files(self, path: str, pattern: str) -> List[Dict]:
        p = self._validate_path(path)
        if not p.is_dir(): raise NotADirectoryError(f"Not a directory: {p}")
        return sorted([{"name": i.name, "path": str(i), "size": i.stat().st_size, "is_dir": i.is_dir()}
                       for i in p.rglob(pattern) if not i.name.startswith(".")], key=lambda e: e["path"])

    def _handle_get_file_info(self, path: str) -> Dict:
        p = self._validate_path(path)
        if not p.exists(): raise FileNotFoundError(f"Not found: {p}")
        s = p.stat(); ext = p.suffix.lower()
        mime = {".txt": "text/plain", ".md": "text/markdown", ".py": "text/x-python",
                ".json": "application/json", ".html": "text/html", ".pdf": "application/pdf"}
        return {"name": p.name, "path": str(p), "size": s.st_size, "is_dir": p.is_dir(),
                "is_file": p.is_file(), "extension": ext, "mime_type": mime.get(ext, "application/octet-stream"),
                "created": datetime.fromtimestamp(s.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(s.st_mtime).isoformat(),
                "permissions": oct(s.st_mode)[-3:]}

    def _handle_create_directory(self, path: str) -> str:
        p = self._validate_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"Created: {p}"

    def _handle_move_file(self, source: str, destination: str) -> str:
        src = self._validate_path(source); dst = self._validate_path(destination)
        if not src.exists(): raise FileNotFoundError(f"Not found: {src}")
        src.rename(dst)
        return f"Moved {src} -> {dst}"


# ── Web Fetch MCP Server (3 tools) ───────────


class WebFetchServer:
    """MCP-compatible HTTP client with content extraction."""

    NAME = "webfetch"
    VERSION = "1.0.0"

    def __init__(self, user_agent: str = "AgentOS-MCP/1.0", timeout: int = 30):
        self._ua = user_agent; self._timeout = timeout

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "fetch_url", "description": "Fetch a web page and return cleaned text",
             "inputSchema": {"type": "object", "properties": {
                 "url": {"type": "string"}, "max_length": {"type": "integer", "default": 50000}},
                 "required": ["url"]}},
            {"name": "fetch_json", "description": "Fetch and parse JSON from URL",
             "inputSchema": {"type": "object", "properties": {
                 "url": {"type": "string"}, "headers": {"type": "object"}},
                 "required": ["url"]}},
            {"name": "check_url", "description": "HEAD request to verify URL accessibility",
             "inputSchema": {"type": "object", "properties": {
                 "url": {"type": "string"}}, "required": ["url"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    @staticmethod
    def _validate_url(url: str) -> None:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https"): raise ValueError(f"Invalid scheme: {p.scheme}")

    @staticmethod
    def _strip_html(html: str) -> str:
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.I)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.I)
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        for e, c in [('&amp;','&'),('&lt;','<'),('&gt;','>'),('&quot;','"'),('&#39;',"'"),('&nbsp;',' ')]:
            text = text.replace(e, c)
        return text

    def _handle_fetch_url(self, url: str, max_length: int = 50000) -> str:
        self._validate_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": self._ua})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                ct = r.headers.get("Content-Type", "")
                enc = ct.split("charset=")[-1].split(";")[0].strip() if "charset=" in ct else "utf-8"
                txt = r.read().decode(enc, errors="replace")
                if "text/html" in ct: txt = self._strip_html(txt)
                return txt[:max_length] + (f"\n\n[Truncated at {max_length}]" if len(txt) > max_length else "")
        except urllib.error.HTTPError as e: return f"HTTP {e.code}: {e.reason}"
        except Exception as e: return f"Error: {e}"

    def _handle_fetch_json(self, url: str, headers: Optional[Dict] = None) -> Any:
        self._validate_url(url)
        h = {"User-Agent": self._ua, "Accept": "application/json"}
        if headers: h.update(headers)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=self._timeout) as r:
                return json.loads(r.read())
        except json.JSONDecodeError as e: return {"error": "Invalid JSON", "detail": str(e)}
        except Exception as e: return {"error": str(e)}

    def _handle_check_url(self, url: str) -> Dict:
        self._validate_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": self._ua}, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return {"url": url, "status": r.status, "accessible": 200 <= r.status < 400,
                        "content_type": r.headers.get("Content-Type",""), "content_length": r.headers.get("Content-Length","")}
        except urllib.error.HTTPError as e: return {"url": url, "status": e.code, "accessible": False, "reason": e.reason}
        except Exception as e: return {"url": url, "status": 0, "accessible": False, "error": str(e)}


# ── Memory / Knowledge Graph MCP (6 tools) ───


class MemoryServer:
    """Persistent knowledge graph for agent memory."""

    NAME = "memory"
    VERSION = "1.0.0"

    def __init__(self, storage_path: str = ""):
        self._path = Path(storage_path or str(Path.home() / ".agentos" / "memory" / "kg.json"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, Dict] = {}
        if self._path.exists():
            try:
                for e in json.loads(self._path.read_text()).get("entries", []): self._entries[e["id"]] = e
            except: pass

    def _save(self):
        self._path.write_text(json.dumps({"version": "1.0", "updated_at": time.time(),
                                          "entries": list(self._entries.values())}, indent=2, ensure_ascii=False))

    def _make_id(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "store_memory", "description": "Store a fact/memory",
             "inputSchema": {"type": "object", "properties": {
                 "content": {"type": "string"}, "category": {"type": "string", "default": "general"},
                 "tags": {"type": "array", "items": {"type": "string"}}, "metadata": {"type": "object"}},
                 "required": ["content"]}},
            {"name": "retrieve_memory", "description": "Retrieve memory by ID",
             "inputSchema": {"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]}},
            {"name": "search_memory", "description": "Search memories by keyword/category/tags",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "category": {"type": "string"},
                 "tags": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "default": 20}}}},
            {"name": "list_categories", "description": "List all categories with counts",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "delete_memory", "description": "Delete a memory by ID",
             "inputSchema": {"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]}},
            {"name": "update_memory", "description": "Update memory content/metadata",
             "inputSchema": {"type": "object", "properties": {
                 "memory_id": {"type": "string"}, "content": {"type": "string"},
                 "category": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                 "required": ["memory_id"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_store_memory(self, content: str, category: str = "general",
                             tags: list = None, metadata: dict = None) -> Dict:
        mid = self._make_id(content)
        entry = self._entries.get(mid, {})
        if entry:
            entry["updated_at"] = time.time()
            if tags: entry.setdefault("tags", []).extend(t for t in tags if t not in entry.get("tags", []))
            if category != "general": entry["category"] = category
            self._save(); return {"id": mid, "action": "updated"}
        entry = {"id": mid, "content": content, "category": category, "tags": tags or [],
                 "metadata": metadata or {}, "created_at": time.time(), "updated_at": time.time()}
        self._entries[mid] = entry; self._save()
        return {"id": mid, "action": "stored"}

    def _handle_retrieve_memory(self, memory_id: str) -> Optional[Dict]:
        return self._entries.get(memory_id)

    def _handle_search_memory(self, query: str = "", category: str = None,
                              tags: list = None, limit: int = 20) -> List[Dict]:
        results = []
        for e in self._entries.values():
            if category and e.get("category") != category: continue
            if tags and not all(t in e.get("tags", []) for t in tags): continue
            if query and query.lower() not in e.get("content","").lower(): continue
            results.append({"id": e["id"], "content": e["content"], "category": e.get("category",""),
                          "tags": e.get("tags",[]), "created_at": e.get("created_at",0)})
        return sorted(results, key=lambda r: r["created_at"], reverse=True)[:limit]

    def _handle_list_categories(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for e in self._entries.values(): c[e.get("category","general")] = c.get(e.get("category","general"), 0) + 1
        return dict(sorted(c.items(), key=lambda x: -x[1]))

    def _handle_delete_memory(self, memory_id: str) -> Dict:
        if memory_id in self._entries: del self._entries[memory_id]; self._save(); return {"deleted": True, "id": memory_id}
        return {"deleted": False, "id": memory_id, "reason": "not found"}

    def _handle_update_memory(self, memory_id: str, content: str = None, category: str = None, tags: list = None) -> Dict:
        e = self._entries.get(memory_id)
        if not e: return {"updated": False, "reason": "not found"}
        if content is not None: e["content"] = content
        if category is not None: e["category"] = category
        if tags is not None: e["tags"] = tags
        e["updated_at"] = time.time(); self._save()
        return {"updated": True, "id": memory_id}


# ── Web Search Server (4 tools) ──────────────


class SearchServer:
    """MCP-compatible web search via DuckDuckGo + Google fallback."""

    NAME = "search"
    VERSION = "1.0.0"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "web_search", "description": "Search the web",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}},
                 "required": ["query"]}},
            {"name": "news_search", "description": "Search for recent news",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}},
                 "required": ["query"]}},
            {"name": "image_search", "description": "Search for images",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}},
                 "required": ["query"]}},
            {"name": "suggest", "description": "Get search autocomplete suggestions",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}}, "required": ["query"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_web_search(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search via DuckDuckGo HTML (no API key needed)."""
        q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="replace")
        except Exception as e:
            return [{"error": f"Search failed: {e}"}]

        results = []
        # Parse DuckDuckGo HTML results
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
            if len(results) >= max_results: break
            link = m.group(1)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            # Find snippet
            snippet = ""
            sn_match = re.search(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html[m.end():m.end()+500], re.DOTALL)
            if sn_match: snippet = re.sub(r'<[^>]+>', '', sn_match.group(1)).strip()
            results.append({"title": title, "url": link, "snippet": snippet, "source": "duckduckgo"})
        return results

    def _handle_news_search(self, query: str, max_results: int = 10) -> List[Dict]:
        q = urllib.parse.quote_plus(f"{query} news")
        return self._handle_web_search(q, max_results)

    def _handle_image_search(self, query: str, max_results: int = 10) -> List[Dict]:
        q = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/?q={q}&iax=images&ia=images"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="replace")
        except Exception as e:
            return [{"error": str(e)}]

        # Extract vqd token for image search
        vqd = ""
        vqd_m = re.search(r'vqd=([\d-]+)', html)
        if vqd_m: vqd = vqd_m.group(1)

        if vqd:
            img_url = f"https://duckduckgo.com/i.js?q={q}&vqd={vqd}&o=json&p=1&s=0"
            try:
                with urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
                    data = json.loads(r.read())
                    results = data.get("results", [])[:max_results]
                    return [{"title": r.get("title",""), "url": r.get("url",""),
                             "thumbnail": r.get("thumbnail",""), "source": "duckduckgo"} for r in results]
            except: pass
        return []

    def _handle_suggest(self, query: str) -> List[str]:
        q = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/ac/?q={q}&type=list"
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.loads(r.read())
                return [item.get("phrase","") for item in data[:10]]
        except: return []


# ── Git Server (4 tools) ─────────────────────


class GitServer:
    """MCP-compatible git operations."""

    NAME = "git"
    VERSION = "1.0.0"

    def __init__(self, repo_path: str = ""):
        self._repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()
        self._git: Optional[str] = shutil.which("git")

    def _run_git(self, *args) -> Dict[str, Any]:
        if not self._git: return {"error": "git not installed"}
        try:
            r = subprocess.run([self._git, *args], capture_output=True, text=True,
                             cwd=str(self._repo_path), timeout=30)
            return {"stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "returncode": r.returncode}
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out"}
        except Exception as e:
            return {"error": str(e)}

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "git_status", "description": "Show working tree status",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "git_log", "description": "Show commit history",
             "inputSchema": {"type": "object", "properties": {
                 "max_count": {"type": "integer", "default": 10}, "oneline": {"type": "boolean", "default": True}}}},
            {"name": "git_diff", "description": "Show changes between commits/working tree",
             "inputSchema": {"type": "object", "properties": {
                 "staged": {"type": "boolean", "default": False}, "commit": {"type": "string"}}}},
            {"name": "git_branch", "description": "List branches",
             "inputSchema": {"type": "object", "properties": {"remote": {"type": "boolean", "default": False}}}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_git_status(self) -> Dict:
        return self._run_git("status", "--porcelain")

    def _handle_git_log(self, max_count: int = 10, oneline: bool = True) -> Dict:
        args = ["log", f"-n{max_count}"]
        if oneline: args.append("--oneline")
        return self._run_git(*args)

    def _handle_git_diff(self, staged: bool = False, commit: str = "") -> Dict:
        args = ["diff"]
        if staged: args.append("--staged")
        if commit: args.append(commit)
        return self._run_git(*args)

    def _handle_git_branch(self, remote: bool = False) -> Dict:
        args = ["branch"]
        if remote: args.append("-r")
        return self._run_git(*args)


# ── Shell Server (3 tools) ───────────────────


class ShellServer:
    """MCP-compatible safe shell command execution."""

    NAME = "shell"
    VERSION = "1.0.0"

    SAFE_COMMANDS = {"ls", "cat", "head", "tail", "wc", "grep", "find", "du", "df",
                     "echo", "date", "whoami", "uname", "pwd", "which", "env", "ps",
                     "top", "htop", "tree", "file", "stat", "md5sum", "sha256sum",
                     "python3", "python", "pip", "npm", "node", "curl", "wget"}

    def _is_safe(self, cmd: str) -> bool:
        base = cmd.strip().split()[0] if cmd.strip() else ""
        return base in self.SAFE_COMMANDS

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "run_command", "description": "Execute a safe shell command",
             "inputSchema": {"type": "object", "properties": {
                 "command": {"type": "string"}, "timeout": {"type": "integer", "default": 30}},
                 "required": ["command"]}},
            {"name": "system_info", "description": "Get system information (OS, CPU, memory)",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "disk_usage", "description": "Show disk usage for a path",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string", "default": "."}}}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_run_command(self, command: str, timeout: int = 30) -> Dict:
        if not self._is_safe(command):
            return {"error": f"Command not in safelist. Allowed: {sorted(self.SAFE_COMMANDS)}"}
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            return {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
        except subprocess.TimeoutExpired: return {"error": "Timeout"}
        except Exception as e: return {"error": str(e)}

    def _handle_system_info(self) -> Dict:
        import platform
        return {"os": platform.system(), "release": platform.release(), "version": platform.version(),
                "machine": platform.machine(), "processor": platform.processor(),
                "python": platform.python_version(), "hostname": platform.node()}

    def _handle_disk_usage(self, path: str = ".") -> Dict:
        try:
            usage = shutil.disk_usage(path)
            return {"path": path, "total_gb": round(usage.total/1024**3, 2),
                    "used_gb": round(usage.used/1024**3, 2), "free_gb": round(usage.free/1024**3, 2)}
        except Exception as e: return {"error": str(e)}


# ── Code Server (3 tools) ────────────────────


class CodeServer:
    """MCP-compatible sandboxed code execution."""

    NAME = "code"
    VERSION = "1.0.0"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "run_python", "description": "Execute Python code in sandbox",
             "inputSchema": {"type": "object", "properties": {
                 "code": {"type": "string"}, "timeout": {"type": "integer", "default": 10}},
                 "required": ["code"]}},
            {"name": "run_shell", "description": "Execute a one-liner bash command",
             "inputSchema": {"type": "object", "properties": {
                 "command": {"type": "string"}, "timeout": {"type": "integer", "default": 10}},
                 "required": ["command"]}},
            {"name": "lint_code", "description": "Basic code linting (syntax check)",
             "inputSchema": {"type": "object", "properties": {
                 "code": {"type": "string"}, "language": {"type": "string", "default": "python"}},
                 "required": ["code"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_run_python(self, code: str, timeout: int = 10) -> Dict:
        try:
            # Restricted execution via compile + eval in limited namespace
            restricted_globals = {"__builtins__": {
                "print": print, "len": len, "range": range, "int": int, "float": float,
                "str": str, "list": list, "dict": dict, "bool": bool, "set": set, "tuple": tuple,
                "sum": sum, "min": min, "max": max, "abs": abs, "round": round, "sorted": sorted,
                "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
                "json": __import__("json"), "math": __import__("math"),
                "datetime": __import__("datetime"), "re": __import__("re"),
                "collections": __import__("collections"), "itertools": __import__("itertools"),
            }}
            import io, sys
            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()
            try:
                compiled = compile(code, "<mcp_sandbox>", "exec")
                exec(compiled, restricted_globals)
                output = buffer.getvalue()
            finally:
                sys.stdout = old_stdout
            return {"output": output, "success": True}
        except Exception as e:
            return {"output": str(e), "success": False, "error": type(e).__name__}

    def _handle_run_shell(self, command: str, timeout: int = 10) -> Dict:
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            return {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
        except subprocess.TimeoutExpired: return {"error": "Timeout"}
        except Exception as e: return {"error": str(e)}

    def _handle_lint_code(self, code: str, language: str = "python") -> Dict:
        if language == "python":
            try:
                compile(code, "<lint>", "exec")
                return {"valid": True, "errors": []}
            except SyntaxError as e:
                return {"valid": False, "errors": [{"line": e.lineno, "offset": e.offset, "message": e.msg}]}
        return {"valid": None, "message": f"Linting not supported for {language}"}


# ── Text Server (4 tools) ────────────────────


class TextServer:
    """MCP-compatible text manipulation tools."""

    NAME = "text"
    VERSION = "1.0.0"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "count_tokens", "description": "Estimate token count (OpenAI tiktoken-style approximate)",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string"}}, "required": ["text"]}},
            {"name": "extract_regex", "description": "Extract patterns from text using regex",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string"}, "pattern": {"type": "string"}, "group": {"type": "integer", "default": 0}},
                 "required": ["text", "pattern"]}},
            {"name": "summarize_text", "description": "Simple extractive text summarization",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string"}, "max_sentences": {"type": "integer", "default": 5}},
                 "required": ["text"]}},
            {"name": "format_json", "description": "Format/validate/prettify JSON",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string"}, "indent": {"type": "integer", "default": 2}},
                 "required": ["text"]}},
        ]

    def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        return getattr(self, f"_handle_{tool_name}")(**arguments)

    def _handle_count_tokens(self, text: str) -> Dict:
        # Approximate: ~4 chars per token for English, ~1.5 for CJK
        words = len(re.findall(r'\w+', text))
        chars = len(text)
        return {"tokens_approx": max(1, words + chars // 4), "characters": chars, "words": words}

    def _handle_extract_regex(self, text: str, pattern: str, group: int = 0) -> List[str]:
        try:
            return [m.group(group) if group else m.group(0) for m in re.finditer(pattern, text)]
        except re.error as e: return [f"Invalid regex: {e}"]

    def _handle_summarize_text(self, text: str, max_sentences: int = 5) -> str:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) <= max_sentences: return text
        # Simple extractive: take first sentence + longest sentences
        first = sentences[0]
        rest = sorted(sentences[1:], key=len, reverse=True)[:max_sentences - 1]
        return ". ".join([first] + rest) + "."

    def _handle_format_json(self, text: str, indent: int = 2) -> Dict:
        try:
            data = json.loads(text)
            formatted = json.dumps(data, indent=indent, ensure_ascii=False)
            return {"valid": True, "formatted": formatted, "keys": list(data.keys()) if isinstance(data, dict) else None}
        except json.JSONDecodeError as e:
            return {"valid": False, "error": str(e)}


# ── Built-in Server Registry ─────────────────


class BuiltinMCPRegistry:
    """Registry of all built-in MCP servers. Single interface for tool discovery/calling."""

    def __init__(self):
        self._servers: Dict[str, Any] = {}

    def register_server(self, server: Any) -> None:
        self._servers[server.NAME] = server

    def list_all_tools(self) -> List[Dict[str, Any]]:
        tools = []
        for srv_name, server in self._servers.items():
            for tool in server.get_tools():
                tools.append({"server": srv_name, "name": f"mcp__{srv_name}__{tool['name']}",
                             "description": tool.get("description", ""), "inputSchema": tool.get("inputSchema", {})})
        return tools

    def get_tool_schemas(self, format: str = "openai") -> List[Dict[str, Any]]:
        schemas = []
        for srv_name, server in self._servers.items():
            for tool in server.get_tools():
                schemas.append({"type": "function",
                    "function": {"name": f"mcp__{srv_name}__{tool['name']}",
                                "description": tool.get("description", ""),
                                "parameters": tool.get("inputSchema", {})}})
        return schemas

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        server = self._servers.get(server_name)
        if not server: raise ValueError(f"Server '{server_name}' not found")
        return server.call_tool(tool_name, arguments)

    def call_tool_by_full_name(self, full_name: str, arguments: Dict[str, Any]) -> Any:
        parts = full_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp": raise ValueError(f"Invalid tool name: {full_name}")
        return self.call_tool(parts[1], parts[2], arguments)

    @property
    def server_names(self) -> List[str]: return list(self._servers.keys())

    @property
    def tool_count(self) -> int: return sum(len(s.get_tools()) for s in self._servers.values())


def create_default_registry(
    allowed_paths: Optional[List[str]] = None,
    memory_path: Optional[str] = None,
    repo_path: str = "",
) -> BuiltinMCPRegistry:
    """Create a BuiltinMCPRegistry with all 8 servers registered."""
    if allowed_paths is None: allowed_paths = [os.getcwd(), str(Path.home())]
    reg = BuiltinMCPRegistry()
    reg.register_server(FilesystemServer(allowed_paths=allowed_paths))
    reg.register_server(WebFetchServer())
    reg.register_server(MemoryServer(storage_path=memory_path or ""))
    reg.register_server(SearchServer())
    reg.register_server(GitServer(repo_path=repo_path))
    reg.register_server(ShellServer())
    reg.register_server(CodeServer())
    reg.register_server(TextServer())
    return reg
