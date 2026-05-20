from docifer_backend.config.settings import get_settings
from docifer_backend.providers.base import AIProvider
from docifer_backend.providers.openai_provider import OpenAIProvider


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAIProvider()
    raise RuntimeError(f"Unsupported LLM provider: {settings.llm_provider}")
