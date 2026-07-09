"""
Embedding实现层 — 多种embedding provider的真实调用。
v0.50: 新增模块。为语义缓存/向量数据库提供embedding实现。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class EmbeddingResult:
    """Result of an embedding generation request."""

    vector: list[float]
    tokens: int = 0
    model: str = ""

    def __len__(self) -> int:
        return len(self.vector)

    def __iter__(self):
        return iter(self.vector)

    def __getitem__(self, idx):
        return self.vector[idx]


class BaseEmbedder(ABC):
    """Embedding提供者抽象基类。"""

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult: ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]: ...

    @abstractmethod
    def dimension(self) -> int: ...


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI text-embedding-3-small / text-embedding-3-large."""

    MODELS = {
        "small": ("text-embedding-3-small", 1536),
        "large": ("text-embedding-3-large", 3072),
        "ada": ("text-embedding-ada-002", 1536),
    }

    def __init__(
        self, model: str = "small", api_key: str = "", base_url: str = "https://api.openai.com/v1"
    ):
        info = self.MODELS.get(model)
        if not info:
            raise ValueError(f"Unknown model key: {model}. Use: {list(self.MODELS.keys())}")
        self.model_id, self._dim = info
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url
        self._http = httpx.AsyncClient(
            timeout=60,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def dimension(self) -> int:
        return self._dim

    async def embed(self, text: str) -> EmbeddingResult:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        body = {"model": self.model_id, "input": texts}
        resp = await self._http.post(f"{self.base_url}/embeddings", json=body)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data["data"]:
            results.append(
                EmbeddingResult(
                    vector=item["embedding"],
                    model=self.model_id,
                )
            )
        return results

    async def close(self):
        await self._http.aclose()


class LocalEmbedder(BaseEmbedder):
    """本地sentence-transformers模型。无API调用，零成本。"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._dim = 384

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self._dim = self._model.get_sentence_embedding_dimension()

    def dimension(self) -> int:
        if self._model is None:
            if self.model_name == "all-MiniLM-L6-v2":
                self._dim = 384
            elif "large" in self.model_name:
                self._dim = 1024
            else:
                self._dim = 768
        return self._dim

    async def embed(self, text: str) -> EmbeddingResult:
        self._ensure_model()
        vec = self._model.encode(text, normalize_embeddings=True)
        return EmbeddingResult(vector=vec.tolist(), model=self.model_name)

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        self._ensure_model()
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [EmbeddingResult(vector=v.tolist(), model=self.model_name) for v in vecs]


class CohereEmbedder(BaseEmbedder):
    """Cohere Embed API."""

    def __init__(self, model: str = "embed-english-v3.0", api_key: str = ""):
        self.model_id = model
        self.api_key = api_key or os.environ.get("COHERE_API_KEY", "")
        self._http = httpx.AsyncClient(
            timeout=60,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        self._dim = {"embed-english-v3.0": 1024, "embed-multilingual-v3.0": 1024}.get(model, 1024)

    def dimension(self) -> int:
        return self._dim

    async def embed(self, text: str) -> EmbeddingResult:
        body = {"model": self.model_id, "texts": [text], "input_type": "search_document"}
        resp = await self._http.post("https://api.cohere.ai/v1/embed", json=body)
        resp.raise_for_status()
        data = resp.json()
        return EmbeddingResult(vector=data["embeddings"][0], model=self.model_id)

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        body = {"model": self.model_id, "texts": texts, "input_type": "search_document"}
        resp = await self._http.post("https://api.cohere.ai/v1/embed", json=body)
        resp.raise_for_status()
        data = resp.json()
        return [EmbeddingResult(vector=vec, model=self.model_id) for vec in data["embeddings"]]

    async def close(self):
        await self._http.aclose()


async def get_embedder(provider: str = "openai", **kwargs) -> BaseEmbedder:
    """工厂函数：获取embedder实例。"""
    match provider:
        case "openai":
            return OpenAIEmbedder(**kwargs)
        case "local":
            return LocalEmbedder(**kwargs)
        case "cohere":
            return CohereEmbedder(**kwargs)
        case _:
            raise ValueError(f"Unknown embedder provider: {provider}. Use: openai/local/cohere")


async def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
