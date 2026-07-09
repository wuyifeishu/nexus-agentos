"""DeepSeek V3 API Provider."""

from agentos.llm.providers.base_http import BaseHttpProvider


class DeepSeekProvider(BaseHttpProvider):
    """DeepSeek API provider (deepseek-chat / deepseek-reasoner).

    Requires: DEEPSEEK_API_KEY env var.
    """

    provider_name = "deepseek"
    API_URL = "https://api.deepseek.com/chat/completions"
    _api_key_env = "DEEPSEEK_API_KEY"
    _default_model = "deepseek-chat"
