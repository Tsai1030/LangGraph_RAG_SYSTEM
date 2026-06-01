"""LLM client abstractions."""
from __future__ import annotations

from app.config import settings

from .base import LLMClient

__all__ = ["LLMClient", "get_search_llm"]


def get_search_llm() -> LLMClient:
    """Return the SEARCH module's LLM client, chosen by settings.llm_model.

        "google_genai:..."          -> GeminiClient (Google Search grounding)
        "openai:..." / no prefix    -> OpenAIClient (legacy default)

    Mirrors app/core/llm.get_llm()'s provider-prefix convention. Kept
    separate because SEARCH needs Google Search grounding metadata that the
    LangChain interface doesn't surface. Concrete clients are imported lazily
    so importing this package never forces both SDKs to load.
    """
    spec = settings.llm_model or ""
    provider = spec.split(":", 1)[0] if ":" in spec else "openai"
    if provider == "google_genai":
        from .gemini_client import GeminiClient
        return GeminiClient()
    from .openai_client import OpenAIClient
    return OpenAIClient()
