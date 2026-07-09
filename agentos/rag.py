from dataclasses import dataclass


@dataclass
class ChunkConfig:
    chunk_size: int = 512


@dataclass
class EmbeddingConfig:
    model: str = "text-embedding-3-small"


class TextChunker:
    pass


class RAGPipeline:
    pass
