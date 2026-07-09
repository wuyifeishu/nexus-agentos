"""
RAG Pipeline — 检索增强生成管道。

将文档加载 → 向量化 → 检索 → LLM 生成 串联为一条端到端管道。
"""

from __future__ import annotations

from agentos.agent.tool_agent import ToolAgent
from agentos.rag.loader import DocumentLoader
from agentos.rag.store import ChromaStore, VectorStore


class RAGPipeline:
    """检索增强生成管道。

    使用流程::

        rag = RAGPipeline(agent)
        rag.ingest_file("docs/report.pdf")        # 加载文档到向量库
        rag.ingest_directory("docs/project/")      # 批量加载
        answer = rag.query("Q3 收入是多少？")       # 检索 + 生成

    Args:
        agent: 用于生成答案的 ToolAgent
        vector_store: 向量存储（默认 ChromaDB 内存模式）
        top_k: 检索返回片段数
    """

    def __init__(
        self,
        agent: ToolAgent,
        vector_store: VectorStore | None = None,
        top_k: int = 5,
    ):
        self._agent = agent
        self._store = vector_store or ChromaStore()
        self._top_k = top_k
        self._loader = DocumentLoader()

    @property
    def store(self) -> VectorStore:
        return self._store

    @property
    def doc_count(self) -> int:
        return self._store.count()

    def ingest_file(self, path: str) -> int:
        """加载单个文件到向量库。返回添加的块数。"""
        docs = self._loader.load_file(path)
        if not docs:
            return 0
        texts = [d.content for d in docs]
        metadatas = [{"source": d.source, "page": d.page} for d in docs]
        self._store.add(texts, metadatas)
        return len(texts)

    def ingest_directory(self, dir_path: str, recursive: bool = True) -> int:
        """加载目录到向量库。返回添加的块数。"""
        docs = self._loader.load_directory(dir_path, recursive=recursive)
        if not docs:
            return 0
        texts = [d.content for d in docs]
        metadatas = [{"source": d.source} for d in docs]
        self._store.add(texts, metadatas)
        return len(texts)

    def ingest_texts(self, texts: list[str], metadatas: list[dict] | None = None) -> int:
        """直接添加文本列表到向量库。"""
        self._store.add(texts, metadatas)
        return len(texts)

    def query(self, question: str, top_k: int | None = None) -> str:
        """检索 + 生成答案。

        Args:
            question: 用户问题
            top_k: 检索片段数（覆盖默认值）

        Returns:
            LLM 生成的答案
        """
        k = top_k or self._top_k

        if self._store.count() == 0:
            return self._agent.run(question).final_answer

        # 检索
        results = self._store.search(question, top_k=k)
        if not results:
            return self._agent.run(question).final_answer

        # 构建上下文
        context_parts = []
        sources = set()
        for i, r in enumerate(results, 1):
            context_parts.append(f"[{i}] {r.content}")
            if r.metadata.get("source"):
                sources.add(r.metadata["source"])

        context = "\n\n".join(context_parts)
        source_list = "\n".join(f"- {s}" for s in sorted(sources))

        # 构建 RAG prompt
        rag_task = f"""请基于以下参考资料回答用户的问题。
如果参考资料不足以回答问题，请明确说明，不要编造信息。

## 参考资料
{context}

## 来源文件
{source_list}

## 用户问题
{question}

请用中文回答。回答时引用具体的资料编号（如 [1]）。"""

        return self._agent.run(rag_task).final_answer

    def retrieve(self, question: str, top_k: int | None = None) -> list[str]:
        """仅检索，不生成。返回匹配的文本片段。"""
        k = top_k or self._top_k
        results = self._store.search(question, top_k=k)
        return [r.content for r in results]
