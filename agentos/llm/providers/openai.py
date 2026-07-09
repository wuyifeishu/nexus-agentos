"""OpenAI API Provider (GPT-4o, GPT-4o-mini, etc.)."""

from agentos.llm.providers.base_http import BaseHttpProvider


class OpenAIProvider(BaseHttpProvider):
    """OpenAI API provider.

    Requires: OPENAI_API_KEY env var.
    """

    provider_name = "openai"
    API_URL = "https://api.openai.com/v1/chat/completions"
    _api_key_env = "OPENAI_API_KEY"
    _default_model = "gpt-4o-mini"
