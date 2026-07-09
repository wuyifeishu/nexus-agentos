"""v0.80 — `agentos serve` API 服务器启动器。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ServeConfig:
    """API 服务配置。"""

    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    workers: int = 1
    log_level: str = "info"
    env_file: str = ".env"


def start_api_server(config: ServeConfig | None = None) -> None:
    """启动 AgentOS API 服务器（FastAPI + Uvicorn）。

    Args:
        config: ServeConfig 配置对象。
    """
    cfg = config or ServeConfig()

    if cfg.env_file and os.path.exists(cfg.env_file):
        from dotenv import load_dotenv

        load_dotenv(cfg.env_file)

    import uvicorn

    uvicorn.run(
        "agentos.api.server:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        workers=cfg.workers,
        log_level=cfg.log_level,
    )


async def start_api_server_async(config: ServeConfig | None = None) -> None:
    """异步启动 API 服务器。"""
    cfg = config or ServeConfig()
    import uvicorn

    server_config = uvicorn.Config(
        "agentos.api.server:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.reload,
        workers=cfg.workers,
        log_level=cfg.log_level,
    )
    server = uvicorn.Server(server_config)
    await server.serve()
