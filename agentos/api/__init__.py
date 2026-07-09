"""
AgentOS API Server — FastAPI-based REST + WebSocket server for agent endpoints.
"""

from agentos.api.server import AgentManager, app, serve

__all__ = ["app", "serve", "AgentManager"]
