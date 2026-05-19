"""Abstract LLMClient.

Why an interface? So later we can swap providers (Azure OpenAI, Anthropic, etc.)
without touching orchestrator / validator / narrator code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, system: str, user: str, max_tokens: int = 1500) -> str:
        """One-shot chat completion."""
        ...

    @abstractmethod
    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Live web search.

        Returns: {"text": str, "citations": list[{url, title}], "raw": ...}
        """
        ...

    @abstractmethod
    async def extract_json(
        self, system: str, user: str, schema: type[T], max_tokens: int = 1500
    ) -> T:
        """Structured extraction. Returns parsed pydantic model."""
        ...
