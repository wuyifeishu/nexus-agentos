"""
Huawei Pangu Provider — 华为盘古大模型，纯 httpx 实现。
支持 Pangu 系列模型：pangu-4, pangu-3.1, pangu-code 等。

环境变量: PANGU_API_KEY, PANGU_BASE_URL
"""

from __future__ import annotations

from typing import Any

from agentos.llm.openai_provider import OpenAIProvider

__all__ = ["PanguProvider"]

PANGU_DEFAULT_BASE = "https://pangu-api.huaweicloud.com/v1"
PANGU_DEFAULT_MODEL = "pangu-4"


class PanguProvider(OpenAIProvider):
    """华为盘古大模型 Provider — 基于 OpenAI 兼容协议。

    支持模型: pangu-4, pangu-3.1, pangu-code, pangu-vision 等。

    环境变量:
        PANGU_API_KEY: 华为云 API Key
        PANGU_BASE_URL: API 端点，默认 https://pangu-api.huaweicloud.com/v1
    """

    def __init__(
        self,
        model: str = PANGU_DEFAULT_MODEL,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
    ):
        import os

        resolved_base = base_url or os.getenv("PANGU_BASE_URL", PANGU_DEFAULT_BASE)
        resolved_key = api_key or os.getenv("PANGU_API_KEY", "")

        super().__init__(
            model=model,
            api_key=resolved_key,
            base_url=resolved_base,
        )
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "pangu"

    def chat(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("timeout", self._timeout)
        return super().chat(*args, **kwargs)

    async def achat(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("timeout", self._timeout)
        return await super().achat(*args, **kwargs)
