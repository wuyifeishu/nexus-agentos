from dataclasses import dataclass


@dataclass
class CacheEntry:
    key: str = ""


class BaseEmbedder:
    pass


class OpenAIEmbedder(BaseEmbedder):
    pass


class LocalEmbedder(BaseEmbedder):
    pass


class CohereEmbedder(BaseEmbedder):
    pass


class ResponseCache:
    pass


class CacheKeyStrategy:
    pass


class LLMCache:
    pass
