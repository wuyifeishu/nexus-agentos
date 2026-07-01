"""
AgentOS Channels — 消息网关。

提供统一的 FastAPI 应用，一站式接入所有渠道 webhook：
  - POST /webhook/wechat       微信公众号
  - POST /webhook/wecom        企业微信
  - POST /webhook/feishu       飞书
  - POST /webhook/dingtalk     钉钉
  - POST /webhook/qq           QQ

同时提供管理接口：
  - GET /channels               列出所有已注册渠道
  - GET /health                 健康检查

依赖:
  pip install fastapi uvicorn
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from agentos.channels.base import BaseChannelAdapter, ChannelConfig, ReplyResult
from agentos.channels.message import ChannelMessage, ChannelType, MessageType, ConversationContext
from agentos.channels.router import ChannelRouter

logger = logging.getLogger("agentos.channels.gateway")

_router = ChannelRouter()

# ── 用户自定义消息处理器 ──

_on_message: Optional[Callable[[ChannelMessage, ConversationContext], Any]] = None


def on_message(handler: Callable[[ChannelMessage, ConversationContext], Any]):
    """装饰器：注册消息处理器。

    当任意渠道收到用户消息时，自动调用此 handler。
    handler 签名: async def handler(msg: ChannelMessage, ctx: ConversationContext) -> str | dict
    返回字符串直接作为回复；返回 dict 可包含 {"reply": "...", "image": "..."} 等。
    """
    global _on_message
    _on_message = handler
    return handler


def _check_signature(adapter: BaseChannelAdapter, raw_data: bytes, headers: dict) -> bool:
    """检查请求签名（安全校验）。"""
    return adapter.verify_signature(raw_data, headers)


def _process_message_async(adapter: BaseChannelAdapter, raw_data: bytes,
                           headers: dict) -> Any:
    """异步处理消息：签名校验 → 解析 → 路由 → 调用 handler → 回复。

    此函数作为同步入口，内部使用 asyncio.run 驱动异步流程。
    符合 FastAPI 的同步/异步兼容要求。
    """
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # 已在事件循环中，创建 task
        return _process_message_coro(adapter, raw_data, headers)
    return asyncio.run(_process_message_coro(adapter, raw_data, headers))


async def _process_message_coro(adapter: BaseChannelAdapter, raw_data: bytes,
                                headers: dict) -> Any:
    """消息处理协程。"""
    # 1. 签名校验
    if not _check_signature(adapter, raw_data, headers):
        logger.warning(f"[{adapter.channel_type.value}] 签名校验失败")
        return adapter.build_reply(
            ChannelMessage(channel=adapter.channel_type, content="signature_error"),
            "签名校验失败", success=False,
        )

    try:
        # 2. 解析消息
        msg: ChannelMessage = adapter.parse_webhook(raw_data, headers)
    except Exception as e:
        logger.exception(f"[{adapter.channel_type.value}] 消息解析失败: {e}")
        return adapter.build_reply(
            ChannelMessage(channel=adapter.channel_type, content="parse_error"),
            "消息解析失败", success=False,
        )

    if not msg.content and not msg.media_url:
        # 空消息/心跳 — 直接返回 200
        return adapter.build_reply(msg, "", success=True)

    # 3. 获取会话上下文
    ctx = _router.get_context(msg)

    # 4. 调用用户注册的消息处理器
    reply_text = ""
    try:
        if _on_message:
            result = _on_message(msg, ctx)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str):
                reply_text = result
            elif isinstance(result, dict):
                reply_text = result.get("reply", "")
        else:
            reply_text = f"[AgentOS Gateway] 收到来自 {msg.channel.value} 的消息，但未注册消息处理器。"
    except Exception as e:
        logger.exception(f"[{adapter.channel_type.value}] handler 异常: {e}")
        reply_text = f"处理失败: {e}"

    # 5. 记录到上下文
    if reply_text:
        _router.update_context(msg.session_id or msg.sender_id, reply_text)

    # 6. 构建回复
    return adapter.build_reply(msg, reply_text, success=True)


# ── FASTAPI 应用工厂 ──

def create_app(title: str = "AgentOS Channel Gateway",
               version: str = "1.0.0",
               adapter_webhook_paths: Optional[dict[ChannelType, str]] = None,
               ) -> Any:
    """创建 FastAPI 应用实例。

    Args:
        title: 应用标题
        version: 版本号
        adapter_webhook_paths: 渠道 → webhook 路径映射，如 {ChannelType.WECHAT: "/webhook/wechat"}

    Returns:
        FastAPI app 实例

    用法:
        from agentos.channels.gateway import create_app, on_message
        from agentos.channels.adapters import WeChatAdapter, WeComAdapter, FeishuAdapter
        from agentos.channels.message import ChannelType

        app = create_app(adapter_webhook_paths={
            ChannelType.WECHAT: "/webhook/wechat",
            ChannelType.WECOM: "/webhook/wecom",
        })

        @on_message
        async def handle_message(msg, ctx):
            return f"Echo: {msg.content}"

        if __name__ == "__main__":
            import uvicorn
            uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    try:
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.responses import JSONResponse, PlainTextResponse, Response
    except ImportError:
        raise ImportError(
            "agentos.channels.gateway requires fastapi and uvicorn. "
            "Install with: pip install fastapi uvicorn"
        )

    app = FastAPI(title=title, version=version)

    # 默认 webhook 路径映射
    default_paths: dict[ChannelType, str] = {
        ChannelType.WECHAT_MP: "/webhook/wechat",
        ChannelType.WECOM: "/webhook/wecom",
        ChannelType.FEISHU: "/webhook/feishu",
        ChannelType.DINGTALK: "/webhook/dingtalk",
        ChannelType.QQ: "/webhook/qq",
    }

    if adapter_webhook_paths:
        default_paths.update(adapter_webhook_paths)

    # ── 注册渠道 webhook 路由 ──

    def _make_webhook_handler(adapter: BaseChannelAdapter):
        """为每个渠道适配器创建 webhook handler。"""
        async def handler(request: Request):
            # 读取原始 body
            try:
                raw_data = await request.body()
            except Exception:
                raw_data = b""

            # 处理 GET 请求（飞书 URL 验证、微信 Token 验证）
            if request.method == "GET":
                query = dict(request.query_params)
                if adapter.channel_type == ChannelType.FEISHU:
                    return adapter.build_reply(
                        ChannelMessage(channel=ChannelType.FEISHU, content=""),
                        query.get("challenge", ""), success=True,
                    )
                if adapter.channel_type == ChannelType.WECHAT_MP:
                    # 微信公众号 URL 验证
                    token = adapter.config.token
                    sig = query.get("signature", "")
                    ts = query.get("timestamp", "")
                    nonce = query.get("nonce", "")
                    echostr = query.get("echostr", "")
                    if token:
                        params = sorted([token, ts, nonce])
                        expected = hashlib.sha1("".join(params).encode()).hexdigest()
                        if sig == expected:
                            return PlainTextResponse(echostr)
                        else:
                            raise HTTPException(status_code=403, detail="Signature verification failed")
                    return PlainTextResponse(echostr)
                return JSONResponse({"status": "ok"})

            # POST 请求 — 消息处理
            headers = dict(request.headers)
            try:
                result = await _process_message_coro(adapter, raw_data, headers)
                if result is None:
                    return JSONResponse({"status": "ok"})
                if isinstance(result, (str, bytes)):
                    return Response(content=result if isinstance(result, bytes) else result.encode(),
                                    media_type="application/xml" if adapter.channel_type in
                                    (ChannelType.WECHAT_MP, ChannelType.WECOM) else "application/json")
                if isinstance(result, dict):
                    return JSONResponse(result)
                return result
            except Exception as e:
                logger.exception(f"Gateway handler error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        return handler

    # 从已注册适配器动态创建路由
    # 注意：路由在 app startup 事件中注册，因为适配器可能在 create_app 之后才注册
    @app.on_event("startup")
    async def _register_routes():
        """应用启动时注册所有渠道路由。"""
        channel_adapters: dict[ChannelType, BaseChannelAdapter] = {}
        for webhook_path, adapter in _router._adapters.items():
            channel_adapters[adapter.channel_type] = adapter
        for channel, adapter in _router._by_channel.items():
            if channel not in channel_adapters:
                channel_adapters[channel] = adapter
                if channel in default_paths:
                    _router._adapters[default_paths[channel]] = adapter

        for channel, adapter in channel_adapters.items():
            webhook_path = adapter.config.webhook_path or default_paths.get(channel, "")
            if webhook_path:
                _router._adapters[webhook_path] = adapter
                app.add_api_route(webhook_path, _make_webhook_handler(adapter),
                                  methods=["GET", "POST"], name=f"webhook_{channel.value}")

    # ── 管理接口 ──

    @app.get("/channels")
    async def list_channels():
        return {
            "channels": _router.active_channels,
            "active_count": _router.active_count,
            "timestamp": time.time(),
        }

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "channels": _router.active_count, "timestamp": time.time()}

    return app


# ── 便利函数 ──

def get_router() -> ChannelRouter:
    """获取全局路由器实例。"""
    return _router


def register_adapter(adapter: BaseChannelAdapter, webhook_path: str = "") -> ChannelRouter:
    """手动注册渠道适配器到全局路由器。"""
    _router.register(adapter, webhook_path)
    return _router
