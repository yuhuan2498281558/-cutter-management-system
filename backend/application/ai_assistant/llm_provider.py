"""
LLM provider factory for the AI assistant.

Environment variables or Django settings in conf/env.py:
- AI_LLM_PROVIDER: ollama | openai | deepseek
- AI_LLM_MODEL: model name
- AI_LLM_BASE_URL: provider base URL
- AI_LLM_API_KEY: API key for OpenAI-compatible providers
- AI_LLM_TEMPERATURE: default 0.1
- AI_LLM_TIMEOUT: request timeout seconds
- OLLAMA_NUM_CTX / OLLAMA_NUM_PREDICT: Ollama generation options
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    temperature: float
    timeout: int


class LLMProviderError(RuntimeError):
    pass


def _config_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    try:
        from django.conf import settings
        value = getattr(settings, name, default)
    except Exception:
        value = default
    return str(value) if value is not None else default


def get_llm_config(model_name: str | None = None) -> LLMConfig:
    provider = _config_value("AI_LLM_PROVIDER", "deepseek").strip().lower()
    if provider == "ollama":
        default_model = "qwen2.5:7b"
    elif provider == "deepseek":
        default_model = "deepseek-chat"
    else:
        default_model = "gpt-4o-mini"
    model = model_name or _config_value("AI_LLM_MODEL", default_model)

    if provider == "ollama":
        default_base_url = "http://localhost:11434"
    elif provider == "deepseek":
        default_base_url = "https://api.deepseek.com/v1"
    else:
        default_base_url = "https://api.openai.com/v1"

    return LLMConfig(
        provider=provider,
        model=model,
        base_url=_config_value("AI_LLM_BASE_URL", default_base_url).rstrip("/"),
        api_key=_config_value("AI_LLM_API_KEY", ""),
        temperature=float(_config_value("AI_LLM_TEMPERATURE", "0.1")),
        timeout=int(_config_value("AI_LLM_TIMEOUT", "60")),
    )


def create_chat_model(model_name: str | None = None):
    config = get_llm_config(model_name)

    if config.provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise LLMProviderError(
                "AI_LLM_PROVIDER is set to ollama, but langchain-ollama is not installed. "
                "Switch AI_LLM_PROVIDER to deepseek/openai for API mode."
            ) from exc

        return ChatOllama(
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            num_ctx=int(_config_value("OLLAMA_NUM_CTX", "4096")),
            num_predict=int(_config_value("OLLAMA_NUM_PREDICT", "1024")),
        )

    if config.provider in {"openai", "openai-compatible", "api", "deepseek"}:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise LLMProviderError(
                "AI_LLM_PROVIDER is set to an OpenAI-compatible provider, "
                "but langchain-openai is not installed. Install langchain-openai "
                "or switch AI_LLM_PROVIDER back to ollama."
            ) from exc

        if not config.api_key:
            raise LLMProviderError("AI_LLM_API_KEY is required for OpenAI-compatible providers.")

        return ChatOpenAI(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=config.temperature,
            timeout=config.timeout,
        )

    raise LLMProviderError(f"Unsupported AI_LLM_PROVIDER: {config.provider}")
