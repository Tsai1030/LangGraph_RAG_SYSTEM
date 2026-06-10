"""
llm.py — 統一 LLM factory

呼叫端從：
    llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0)
改成：
    llm = get_llm("default", temperature=0)

切換 provider 只動 .env（model string 加前綴）：
    LLM_MODEL=openai:gpt-5.4
    LLM_MODEL=google_genai:gemini-3.1-pro
    LLM_MODEL=anthropic:claude-sonnet-4-6

LangChain 的 init_chat_model 會根據前綴自動回對應的 ChatXxx 物件，所以
graph node 用 .with_structured_output() / .astream() / .ainvoke() 都不用改。
"""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.config import settings


# 「沒有 provider 前綴」時的預設 fallback
_DEFAULT_PROVIDER = "openai"

# 把 .env 沒有 _api_key 後綴的 provider key 餵給 init_chat_model 時要用的對照。
# init_chat_model 預設會去 env var 找對應 provider 的 key（如 OPENAI_API_KEY），
# 我們的 settings 已經把所有 key 拉成 attribute，這裡只是在 get_llm 時動態
# 把對應的 key 從 settings 映射成 init_chat_model 看得懂的 kwarg 名。
_API_KEY_KWARG = {
    "openai": "api_key",
    "google_genai": "api_key",
    "anthropic": "api_key",
}

_SETTINGS_KEY_ATTR = {
    "openai": "openai_api_key",
    "google_genai": "google_api_key",
    "anthropic": "anthropic_api_key",
}


def _resolve_model_spec(role: str) -> str:
    spec_map = {
        "default": settings.llm_model,
        "grader":  settings.grader_model,
        "form":    settings.form_model,
        "vision":  settings.vision_model,
    }
    if role not in spec_map:
        raise ValueError(f"Unknown LLM role: {role!r} (expected one of {list(spec_map)})")

    spec = spec_map[role]
    if ":" not in spec:
        # 向後相容：沒前綴 = 視為 OpenAI
        spec = f"{_DEFAULT_PROVIDER}:{spec}"
    return spec


def get_llm(role: str = "default", **kwargs) -> BaseChatModel:
    """回傳一個 LangChain BaseChatModel。

    Args:
        role: "default" / "grader" / "form" / "vision" — 對應 settings 的角色 model。
        **kwargs: 直接透傳給 init_chat_model（如 temperature, streaming, stream_usage 等）。
                  provider 不支援的 kwarg 會被忽略（如 stream_usage 對 Gemini 無作用）。

    Returns:
        BaseChatModel — 支援 .ainvoke / .astream / .with_structured_output 等統一介面。
    """
    spec = _resolve_model_spec(role)
    provider, _ = spec.split(":", 1)

    # 把對應 provider 的 API key 注入（init_chat_model 預設會從 env 抓，但我們有 settings
    # 集中管理；顯式傳進去就不依賴 process env 的狀態，testing 時也好控制）
    key_attr = _SETTINGS_KEY_ATTR.get(provider)
    kwarg_name = _API_KEY_KWARG.get(provider)
    if key_attr and kwarg_name:
        key_value = getattr(settings, key_attr, "") or ""
        if key_value and kwarg_name not in kwargs:
            kwargs[kwarg_name] = key_value

    return init_chat_model(spec, **kwargs)
