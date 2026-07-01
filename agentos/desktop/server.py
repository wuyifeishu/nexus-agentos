"""
Desktop Server — AgentOS 桌面客户端后端 v1.7.1。

功能:
- FastAPI HTTP API（文件浏览、Shell 执行、Agent 对话、授权审批）
- WebSocket 实时推送（含可视化授权卡片）
- 静态文件服务（前端 SPA）
- System 模块集成（权限分层 + 可视化授权审批引擎）
"""

from __future__ import annotations

import os
import json
import uuid
from dataclasses import dataclass
from typing import Optional

from agentos.system.permissions import (
    SystemPermissionManager,
    PermissionTier,
    SAFE_PERMISSIONS,
    DEV_PERMISSIONS,
)
from agentos.system.file_ops import FileOperator, FileOpResult
from agentos.system.shell_exec import ShellExecutor
from agentos.system.approval import ApprovalEngine
from agentos.enterprise.api_keys import (
    APIKeyManager, KeyScope, KeyCreateRequest, APIKey,
)
from agentos.cli.config_panel import CONFIG_DIR, CONFIG_FILE, ENV_FILE

APP_VERSION = "1.7.1"


@dataclass
class DesktopConfig:
    host: str = "0.0.0.0"
    port: int = 19999
    auto_open: bool = True
    permission_mode: str = "dev"
    static_dir: str = ""
    debug: bool = False


class DesktopServer:

    def __init__(self, config: DesktopConfig | None = None):
        self._config = config or DesktopConfig()
        self._pm = SystemPermissionManager()
        self._sid = f"desktop-{uuid.uuid4().hex[:8]}"

        if self._config.permission_mode == "safe":
            self._pm.set_safe_mode(self._sid)
        else:
            self._pm.set_dev_mode(self._sid)

        self._approval = ApprovalEngine(self._pm, self._sid)
        self._key_mgr = APIKeyManager()
        self.file_op = FileOperator(self._pm, self._sid)
        self.shell_exec = ShellExecutor(self._pm, self._sid)
        self._ws_clients: list = []

        if self._config.static_dir and os.path.isdir(self._config.static_dir):
            self._static_dir = self._config.static_dir
        else:
            self._static_dir = os.path.join(os.path.dirname(__file__), "static")

    def build_app(self):
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse, HTMLResponse

        app = FastAPI(title="AgentOS Desktop", version=APP_VERSION, docs_url=None, redoc_url=None)

        async def push_approval(data: dict) -> None:
            await self._broadcast(data)
        self._approval.set_push_callback(push_approval)

        # ── WebSocket ──
        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await ws.accept()
            self._ws_clients.append(ws)
            try:
                await ws.send_json({
                    "type": "connected",
                    "session_id": self._sid,
                    "permission_mode": self._config.permission_mode,
                    "work_dir": os.getcwd(),
                    "version": APP_VERSION,
                })
                while True:
                    data = await ws.receive_json()
                    resp = await self._handle_ws_message(data)
                    await ws.send_json(resp)
            except WebSocketDisconnect:
                pass
            finally:
                self._ws_clients.remove(ws)

        # ── REST ──
        @app.get("/api/status")
        async def api_status():
            return {
                "version": APP_VERSION,
                "session_id": self._sid,
                "permission_mode": self._config.permission_mode,
                "pid": os.getpid(),
                "work_dir": os.getcwd(),
            }

        @app.get("/api/fs/list")
        async def api_list_dir(path: str = "/home"):
            return self._file_result_to_dict(self.file_op.list_dir(path, show_hidden=False))

        @app.get("/api/fs/read")
        async def api_read_file(path: str):
            return self._file_result_to_dict(self.file_op.read(path))

        @app.post("/api/fs/write")
        async def api_write_file(data: dict):
            return self._file_result_to_dict(self.file_op.write(data.get("path", ""), data.get("content", "")))

        @app.post("/api/fs/mkdir")
        async def api_mkdir(data: dict):
            return self._file_result_to_dict(self.file_op.mkdir(data.get("path", "")))

        @app.post("/api/fs/delete")
        async def api_delete(data: dict):
            return self._file_result_to_dict(self.file_op.delete(data.get("path", "")))

        @app.get("/api/fs/search")
        async def api_search(path: str, pattern: str = "*"):
            return self._file_result_to_dict(self.file_op.search(path, pattern))

        @app.post("/api/shell")
        async def api_shell(data: dict):
            tier_map = {
                "readonly": PermissionTier.SHELL_READONLY,
                "standard": PermissionTier.SHELL_STANDARD,
                "full": PermissionTier.SHELL_FULL,
            }
            tier = tier_map.get(data.get("tier", "standard"), PermissionTier.SHELL_STANDARD)
            result = self.shell_exec.execute_checked(data.get("command", ""), tier)
            return {
                "success": result.success, "command": result.command,
                "stdout": result.stdout, "stderr": result.stderr,
                "exit_code": result.exit_code, "duration_ms": result.duration_ms,
                "timeout": result.timeout, "error": result.error,
            }

        @app.post("/api/permission/mode")
        async def api_set_permission(data: dict):
            mode = data.get("mode", "safe")
            if mode == "dev":
                self._pm.set_dev_mode(self._sid)
            elif mode == "full":
                self._pm.set_full_mode(self._sid)
            else:
                self._pm.set_safe_mode(self._sid)
            self._config.permission_mode = mode
            await self._broadcast({"type": "permission_changed", "mode": mode})
            return {"mode": mode}

        # ── 可视化授权审批 API ──
        @app.get("/api/approval/pending")
        async def api_pending():
            return {"tickets": self._approval.get_pending_tickets()}

        @app.post("/api/approval/resolve")
        async def api_resolve(data: dict):
            ticket_id = data.get("ticket_id", "")
            approved = data.get("approved", False)
            remember = data.get("remember", False)
            ok = self._approval.resolve(ticket_id, approved, remember)
            status = "approved" if approved else ("denied_remember" if remember else "denied")
            if ok:
                await self._broadcast({
                    "type": "approval_resolved",
                    "data": {"ticket_id": ticket_id, "status": status},
                })
            return {"success": ok, "ticket_id": ticket_id, "status": status}

        # ── API Key 管理 API ──
        @app.get("/api/apikeys")
        async def api_list_keys():
            keys = self._key_mgr.list_keys()
            return {
                "keys": [
                    {
                        "key_id": k.key_id,
                        "key_prefix": k.key_prefix,
                        "name": k.name,
                        "scopes": [s.value for s in k.scopes],
                        "created_at": k.created_at,
                        "expires_at": k.expires_at,
                        "last_used_at": k.last_used_at,
                        "usage_count": k.usage_count,
                        "revoked": k.revoked,
                    }
                    for k in keys
                ],
                "stats": self._key_mgr.stats(),
            }

        @app.post("/api/apikeys")
        async def api_create_key(data: dict):
            name = data.get("name", "Unnamed")
            scope_names = data.get("scopes", ["read", "write"])
            expires_in_days = data.get("expires_in_days")
            scopes = []
            for s in scope_names:
                try:
                    scopes.append(KeyScope(s))
                except ValueError:
                    return {"error": f"Invalid scope: {s}"}
            req = KeyCreateRequest(name=name, scopes=scopes, expires_in_days=expires_in_days)
            result = self._key_mgr.create_key(req)
            return {
                "key_id": result.key_id,
                "plaintext_key": result.plaintext_key,
                "key_prefix": result.key_prefix,
                "scopes": [s.value for s in result.scopes],
                "expires_at": result.expires_at,
            }

        @app.delete("/api/apikeys/{key_id}")
        async def api_revoke_key(key_id: str):
            ok = self._key_mgr.revoke_key(key_id)
            return {"success": ok, "key_id": key_id}

        @app.post("/api/apikeys/{key_id}/rotate")
        async def api_rotate_key(key_id: str):
            result = self._key_mgr.rotate_key(key_id)
            if not result:
                return {"error": f"Key not found or already revoked: {key_id}"}
            return {
                "key_id": result.key_id,
                "plaintext_key": result.plaintext_key,
                "key_prefix": result.key_prefix,
                "scopes": [s.value for s in result.scopes],
                "expires_at": result.expires_at,
            }

        # ── 配置面板 API ──
        @app.get("/api/config")
        async def api_get_config():
            import yaml
            config = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    config = yaml.safe_load(f) or {}
            env_vars = {}
            if ENV_FILE.exists():
                for line in ENV_FILE.read_text().strip().split("\n"):
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
            return {"config": config, "env_vars": env_vars, "config_path": str(CONFIG_FILE)}

        @app.post("/api/config")
        async def api_set_config(data: dict):
            import yaml
            config = data.get("config", {})
            env_vars = data.get("env_vars", {})
            section = data.get("section")
            if section:
                if not CONFIG_FILE.exists():
                    full = {}
                else:
                    with open(CONFIG_FILE) as f:
                        full = yaml.safe_load(f) or {}
                full[section] = config
                config = full
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            if env_vars:
                lines = ENV_FILE.read_text().strip().split("\n") if ENV_FILE.exists() else []
                existing = set()
                for line in lines:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        existing.add(line.split("=", 1)[0].strip())
                for k, v in env_vars.items():
                    if k in existing:
                        continue
                    lines.append(f"{k}={v}")
                ENV_FILE.write_text("\n".join(lines) + "\n")
            return {"success": True, "config_path": str(CONFIG_FILE)}

        # ── 静态文件 ──
        if os.path.isdir(self._static_dir):
            app.mount("/static", StaticFiles(directory=self._static_dir), name="static")

        @app.get("/")
        async def index():
            idx = os.path.join(self._static_dir, "index.html")
            if os.path.isfile(idx):
                return FileResponse(idx)
            return HTMLResponse("<h1>AgentOS Desktop</h1><p>Static files not found.</p>")

        return app

    async def _handle_ws_message(self, data: dict) -> dict:
        msg_type = data.get("type", "")
        payload = data.get("payload", {})

        if msg_type == "list_dir":
            r = self.file_op.list_dir(payload.get("path", "/"), payload.get("show_hidden", False))
            return {"type": "list_dir_result", "data": self._file_result_to_dict(r)}

        if msg_type == "read_file":
            r = self.file_op.read(payload.get("path", ""))
            return {"type": "read_file_result", "data": self._file_result_to_dict(r)}

        if msg_type == "write_file":
            r = self.file_op.write(payload.get("path", ""), payload.get("content", ""))
            return {"type": "write_file_result", "data": self._file_result_to_dict(r)}

        if msg_type == "shell":
            r = self.shell_exec.execute(payload.get("command", ""))
            return {
                "type": "shell_result",
                "data": {
                    "success": r.success, "stdout": r.stdout, "stderr": r.stderr,
                    "exit_code": r.exit_code, "duration_ms": r.duration_ms, "error": r.error,
                },
            }

        if msg_type == "get_pending_tickets":
            return {"type": "pending_tickets", "data": {"tickets": self._approval.get_pending_tickets()}}

        if msg_type == "resolve_ticket":
            ticket_id = payload.get("ticket_id", "")
            approved = payload.get("approved", False)
            remember = payload.get("remember", False)
            ok = self._approval.resolve(ticket_id, approved, remember)
            status = "approved" if approved else ("denied_remember" if remember else "denied")
            if ok:
                await self._broadcast({
                    "type": "approval_resolved",
                    "data": {"ticket_id": ticket_id, "status": status},
                })
            return {"type": "resolve_ticket_result", "data": {"success": ok, "ticket_id": ticket_id, "status": status}}

        if msg_type == "ping":
            return {"type": "pong"}

        return {"type": "error", "data": {"message": f"未知消息类型: {msg_type}"}}

    async def _broadcast(self, message: dict) -> None:
        for ws in self._ws_clients:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    @staticmethod
    def _file_result_to_dict(result: FileOpResult) -> dict:
        return {
            "success": result.success, "action": result.action,
            "path": result.path, "content": result.content, "error": result.error,
            "listing": [
                {"name": e.name, "path": e.path, "is_dir": e.is_dir,
                 "size_bytes": e.size_bytes, "modified_at": e.modified_at, "mime_type": e.mime_type}
                for e in (result.listing or [])
            ],
        }

    def serve(self) -> None:
        import uvicorn
        app = self.build_app()
        print(f"\n  AgentOS Desktop v{APP_VERSION}")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  地址:     http://{self._config.host}:{self._config.port}")
        print(f"  模式:     {self._config.permission_mode}")
        print(f"  工作区:   {os.getcwd()}")
        print(f"  会话:     {self._sid}")
        print(f"  授权引擎: 可视化审批（Agent主动申请 → 用户点击允许/拒绝）")
        print(f"  桌面壳:   agentos desktop-shell（原生窗口包裹）")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        uvicorn.run(app, host=self._config.host, port=self._config.port, log_level="warning")


def launch_desktop(host: str = "0.0.0.0", port: int = 19999,
                   mode: str = "dev", auto_open: bool = True) -> None:
    DesktopServer(DesktopConfig(host=host, port=port, permission_mode=mode, auto_open=auto_open)).serve()
