"""Gemini implementation of LLMClient (google-genai SDK).

Same three primitives as OpenAIClient, so every source adapter works
unchanged when the SEARCH module is switched to Gemini via get_search_llm():
  - chat()           plain completion, returns text
  - web_search()     GoogleSearch grounding tool, returns text + citations
  - extract_json()   structured output via response_schema, returns parsed model

Why google-genai directly (not LangChain like the main RAG's get_llm)?
  - web_search() needs the Google Search *grounding* tool and its
    grounding_metadata (search queries + source URLs). LangChain's chat
    interface doesn't surface that metadata; the raw SDK does.

Notes for gemini-3.5-flash (verified against google-genai 1.75.0):
  - Async path is `client.aio.models.generate_content(...)`.
  - System prompt goes in `config.system_instruction` (not a message role).
  - Structured output: pass a Pydantic class as `response_schema` +
    response_mime_type="application/json"; read `resp.parsed` (already a
    validated instance). GoogleSearch grounding and response_schema can't
    be combined in one call — that's fine, extract_json uses no tools.
  - API key comes from settings.google_api_key (GOOGLE_API_KEY), NOT
    GEMINI_API_KEY — the latter isn't set in this project's .env.
"""
from __future__ import annotations

from typing import Any, TypeVar

from google import genai
from google.genai import types
from langsmith import traceable
from pydantic import BaseModel, ValidationError

from app.config import settings
from .base import LLMClient

T = TypeVar("T", bound=BaseModel)


def _strip_provider(spec: str) -> str:
    """'google_genai:gemini-3.5-flash' -> 'gemini-3.5-flash'.

    settings.llm_model carries the LangChain 'provider:model' prefix; the
    google-genai SDK wants the bare model id.
    """
    return spec.split(":", 1)[1] if ":" in spec else spec


class GeminiClient(LLMClient):
    def __init__(self) -> None:
        if not settings.google_api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY must be set in .env to use GeminiClient."
            )
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = _strip_provider(settings.llm_model)

    # ── 1. plain chat ─────────────────────────────────────────
    @traceable(run_type="llm", name="Gemini.chat")
    async def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1500,
    ) -> str:
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""

    # ── 2. live web search (Google Search grounding) ──────────
    @traceable(run_type="tool", name="Gemini.web_search")
    async def web_search(
        self,
        query: str,
        max_results: int = 5,  # advisory; the grounding tool decides
    ) -> dict[str, Any]:
        """Run a query through Gemini's GoogleSearch grounding tool.

        Returns the same shape as OpenAIClient.web_search:
            {"text": str, "citations": list[{"url","title"}], "raw": resp}
        """
        _ = max_results
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
        except Exception as e:  # google-genai raises its own error types
            raise RuntimeError(
                f"web_search failed for query={query!r}: {type(e).__name__}: {e}"
            ) from e

        text = resp.text or ""
        citations: list[dict[str, str]] = []
        # grounding_metadata.grounding_chunks[i].web.{uri,title}
        try:
            meta = resp.candidates[0].grounding_metadata
        except (AttributeError, IndexError, TypeError):
            meta = None
        if meta is not None:
            for chunk in getattr(meta, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", "") if web else ""
                if uri:
                    citations.append(
                        {"url": uri, "title": getattr(web, "title", "") or ""}
                    )

        return {"text": text, "citations": citations, "raw": resp}

    # ── 3. structured extraction (response_schema) ────────────
    @traceable(run_type="llm", name="Gemini.extract_json")
    async def extract_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 1500,
    ) -> T:
        """Parse the model's reply into a Pydantic model via response_schema.

        google-genai validates against the Pydantic schema server-side and
        returns the parsed instance on `resp.parsed`. We fall back to parsing
        `resp.text` defensively in case `parsed` is unexpectedly empty.
        """
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=max_tokens,
                temperature=0,
            ),
        )
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        text = resp.text or "{}"
        try:
            return schema.model_validate_json(text)
        except (ValueError, ValidationError) as e:
            raise RuntimeError(
                f"extract_json: model returned non-conforming output: "
                f"{text[:300]!r} (error: {e})"
            ) from e
