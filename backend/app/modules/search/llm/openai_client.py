"""OpenAI implementation of LLMClient.

Three primitives every adapter uses:
  - chat()           plain completion, returns text
  - web_search()     Responses API + web_search tool, returns text + citations
  - extract_json()   structured-output style: send messages, receive parsed dict

Why both `chat.completions` and `responses` API?
  - chat.completions: stable, supports JSON-mode response_format, used for
    prompt-based extraction once we already have the source text.
  - responses + web_search tool: only path to live web data; required for
    the "fetch the latest article" half of every adapter.

Notes for gpt-5.4-mini (verified 2026-05-12):
  - Uses `max_completion_tokens` (not the older `max_tokens`).
  - Tool name is `"web_search"`.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

from langsmith import traceable
from langsmith.wrappers import wrap_openai
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings
from .base import LLMClient

T = TypeVar("T", bound=BaseModel)


class OpenAIClient(LLMClient):
    def __init__(self) -> None:
        # wrap_openai instruments chat.completions / responses so token
        # usage + cost lands in LangSmith automatically. Without this our
        # @traceable spans show but their token columns stay blank.
        # Uses RAG's existing openai_api_key / llm_model — no separate
        # OPENAI key for the SEARCH module by design.
        self._client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
        self._model = settings.llm_model

    # ── 1. plain chat ─────────────────────────────────────────
    @traceable(run_type="llm", name="OpenAI.chat")
    async def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1500,
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    # ── 2. live web search ────────────────────────────────────
    @traceable(run_type="tool", name="OpenAI.web_search")
    async def web_search(
        self,
        query: str,
        max_results: int = 5,  # currently advisory; tool decides
    ) -> dict[str, Any]:
        """Run a query through the model's web_search tool.

        Returns a dict:
            {
                "text":      LLM's narrative answer (with embedded citations),
                "citations": list[{"url": str, "title": str}],
                "raw":       the full response object for debugging
            }

        We accept the `_ = max_results` pattern because the OpenAI tool
        currently auto-decides count, but we keep the param so callers can
        signal intent that we'll honour once the SDK exposes it.
        """
        _ = max_results
        try:
            resp = await self._client.responses.create(
                model=self._model,
                input=query,
                tools=[{"type": "web_search"}],
            )
        except APIError as e:
            raise RuntimeError(
                f"web_search failed for query={query!r}: {e.message}"
            ) from e

        text = getattr(resp, "output_text", "") or ""
        citations: list[dict[str, str]] = []
        # Walk resp.output for url_citation annotations
        for item in getattr(resp, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                for ann in getattr(content, "annotations", []) or []:
                    ann_type = getattr(ann, "type", None)
                    if ann_type in ("url_citation", "citation"):
                        url = getattr(ann, "url", "") or ""
                        title = getattr(ann, "title", "") or ""
                        if url:
                            citations.append({"url": url, "title": title})

        return {"text": text, "citations": citations, "raw": resp}

    # ── 3. structured extraction (JSON mode) ──────────────────
    @traceable(run_type="llm", name="OpenAI.extract_json")
    async def extract_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 1500,
    ) -> T:
        """Parse the LLM's reply into a Pydantic model via JSON mode.

        Cheaper and more reliable than the parse() helper for simple cases,
        and works on every model that supports `response_format`.
        """
        full_system = (
            system
            + "\n\nRespond ONLY with a single valid JSON object matching this schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            + "\nDo not wrap the JSON in markdown fences."
        )
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(text)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise RuntimeError(
                f"extract_json: model returned non-conforming output: {text[:300]!r} "
                f"(error: {e})"
            ) from e
