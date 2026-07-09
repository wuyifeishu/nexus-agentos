"""
AgentOS v0.30 向量数据库集成 — Chroma + FAISS。
语义记忆检索、知识库索引。
"""

import os
import pickle
import uuid
from dataclasses import dataclass, field


@dataclass
class VectorEntry:
    """向量条目。"""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


class BaseVectorStore:
    """向量存储基类。"""

    def add(
        self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None
    ) -> list[str]: ...
    def search(self, query: str, top_k: int = 5) -> list[VectorEntry]: ...
    def delete(self, ids: list[str]): ...
    def count(self) -> int: ...


class FAISSVectorStore(BaseVectorStore):
    """基于 FAISS 的轻量向量存储。"""

    def __init__(self, dim: int = 768, index_path: str = ""):
        self.dim = dim
        self.index_path = index_path
        self._index = None
        self._store: dict[str, tuple[list[float], str, dict]] = {}
        self._next_id = 0
        if index_path and os.path.exists(index_path):
            self._load()

    def _init_index(self):
        try:
            import faiss

            self._index = faiss.IndexFlatIP(self.dim)
        except ImportError:
            self._index = None

    def add(
        self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None
    ) -> list[str]:
        embeddings = self._embed(texts)
        if not self._index:
            self._init_index()
        if self._index:
            import numpy as np

            vecs = np.array(embeddings, dtype=np.float32)
            self._index.add(vecs)

        res_ids = []
        for i, text in enumerate(texts):
            rid = ids[i] if ids else f"v{self._next_id}"
            self._next_id += 1
            self._store[rid] = (embeddings[i], text, metadatas[i] if metadatas else {})
            res_ids.append(rid)
        return res_ids

    def _fallback_search(self, q_vec, top_k):
        """Fallback余弦相似度搜索（无faiss时使用）。"""
        import math

        scores = []
        for rid, (vec, text, meta) in self._store.items():
            dot = sum(a * b for a, b in zip(q_vec, vec))
            na = math.sqrt(sum(a * a for a in q_vec))
            nb = math.sqrt(sum(b * b for b in vec))
            sim = dot / (na * nb) if na * nb > 0 else 0.0
            scores.append((sim, rid, text, meta))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [
            VectorEntry(id=rid, text=text, metadata=meta, score=float(s))
            for s, rid, text, meta in scores[:top_k]
        ]

    def search(self, query: str, top_k: int = 5) -> list[VectorEntry]:
        if not self._store:
            return []
        q_vec = self._embed([query])[0]
        if not self._index:
            return self._fallback_search(q_vec, top_k)
        q_vec = self._embed([query])[0]
        import numpy as np

        distances, indices = self._index.search(np.array([q_vec], dtype=np.float32), min(top_k, self.count()))
        results = []
        for score, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            rid = f"v{idx}"
            if rid in self._store:
                _, text, meta = self._store[rid]
                results.append(VectorEntry(id=rid, text=text, metadata=meta, score=float(score)))
        return results

    def delete(self, ids: list[str]):
        for rid in ids:
            self._store.pop(rid, None)

    def count(self) -> int:
        return len(self._store)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """轻量嵌入：使用 all-MiniLM-L6-v2 或回退到 TF-IDF。"""
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("all-MiniLM-L6-v2")
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()
        except ImportError:
            return self._tfidf_embed(texts)

    def _tfidf_embed(self, texts: list[str]) -> list[list[float]]:
        """TF-IDF 回退，仅作占位。"""
        import hashlib

        dim = self.dim
        result = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            vec = [(h[i] / 255.0) for i in range(min(len(h), dim))]
            vec += [0.0] * (dim - len(vec))
            result.append(vec)
        return result

    def _save(self):
        if self.index_path:
            os.makedirs(os.path.dirname(self.index_path) or ".", exist_ok=True)
            with open(self.index_path, "wb") as f:
                pickle.dump({"store": self._store, "next_id": self._next_id}, f)

    def _load(self):
        with open(self.index_path, "rb") as f:
            data = pickle.load(f)
        self._store = data["store"]
        self._next_id = data["next_id"]

    def __del__(self):
        if self.index_path:
            self._save()


class ChromaVectorStore(BaseVectorStore):
    """Chroma 向量存储。"""

    def __init__(self, collection_name: str = "agentos", persist_dir: str = "./chroma_data"):
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._client = None
        self._collection = None
        self._init()

    def _init(self):
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(self.collection_name)
        except ImportError:
            self._collection = None

    def add(
        self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None
    ) -> list[str]:
        if not self._collection:
            ids = ids or [f"v{len(self._fallback_store)}-{i}" for i in range(len(texts))]
            for i, t in enumerate(texts):
                self._fallback_store[ids[i]] = {
                    "text": t,
                    "metadata": metadatas[i] if metadatas else {},
                }
            return ids

        ids = ids or [str(uuid.uuid4())[:8] for _ in texts]
        self._collection.add(documents=texts, metadatas=metadatas or [{}] * len(texts), ids=ids)
        return ids

    def search(self, query: str, top_k: int = 5) -> list[VectorEntry]:
        if not self._collection:
            if self._fallback_store:
                return [
                    VectorEntry(id=k, text=v["text"], metadata=v["metadata"], score=0.5)
                    for k, v in list(self._fallback_store.items())[:top_k]
                ]
            return []
        results = self._collection.query(query_texts=[query], n_results=top_k)
        entries = []
        for i, rid in enumerate(results.get("ids", [[]])[0]):
            entries.append(
                VectorEntry(
                    id=rid,
                    text=results["documents"][0][i] if results.get("documents") else "",
                    metadata=results["metadatas"][0][i] if results.get("metadatas") else {},
                    score=1.0 - results["distances"][0][i] if results.get("distances") else 0.0,
                )
            )
        return entries

    def delete(self, ids: list[str]):
        if self._collection:
            self._collection.delete(ids=ids)
        else:
            for rid in ids:
                self._fallback_store.pop(rid, None)

    def count(self) -> int:
        if self._collection:
            return self._collection.count()
        return len(self._fallback_store)

    @property
    def _fallback_store(self) -> dict:
        if not hasattr(self, "_fb"):
            self._fb = {}
        return self._fb
