"""
LLM provider factory for the AI assistant.

Environment variables or Django settings in conf/env.py:
- AI_LLM_PROVIDER: deepseek | openai | openai-compatible | api
- AI_LLM_MODEL: model name
- AI_LLM_BASE_URL: provider base URL
- AI_LLM_API_KEY: API key for OpenAI-compatible providers
- AI_LLM_TEMPERATURE: default 0.1
- AI_LLM_TIMEOUT: request timeout seconds
- AI_CONTEXT_WINDOW_TOKENS / AI_CONTEXT_OUTPUT_TOKENS: operational budget
- AI_CONTEXT_SAFETY_MARGIN_TOKENS / AI_CONTEXT_COMPACTION_MIN_TOKENS
- AI_CONTEXT_TOOL_PROTOCOL_TOKENS: reserve for provider tool templates
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
    if provider == "deepseek":
        default_model = "deepseek-chat"
    else:
        default_model = "gpt-4o-mini"
    model = model_name or _config_value("AI_LLM_MODEL", default_model)

    if provider == "deepseek":
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


def get_context_policy():
    from .context_budget import ContextBudgetPolicy

    try:
        policy = ContextBudgetPolicy(
            context_tokens=int(_config_value("AI_CONTEXT_WINDOW_TOKENS", "256000")),
            output_tokens=int(_config_value("AI_CONTEXT_OUTPUT_TOKENS", "8192")),
            safety_margin_tokens=int(_config_value("AI_CONTEXT_SAFETY_MARGIN_TOKENS", "4096")),
            compaction_min_tokens=int(_config_value("AI_CONTEXT_COMPACTION_MIN_TOKENS", "1000")),
            tool_protocol_tokens=int(_config_value("AI_CONTEXT_TOOL_PROTOCOL_TOKENS", "1024")),
            trigger_ratio=float(_config_value("AI_CONTEXT_TRIGGER_RATIO", "0.8")),
            retain_ratio=float(_config_value("AI_CONTEXT_RETAIN_RATIO", "0.16")),
        )
        return policy
    except (ValueError, TypeError) as exc:
        raise LLMProviderError(f"Invalid AI context budget configuration: {exc}") from exc


def create_chat_model(model_name: str | None = None):
    from .chat_model import ChatCompletionsModel
    from .context_budget import GuardedChatModel

    config = get_llm_config(model_name)
    policy = get_context_policy()

    if config.provider in {"openai", "openai-compatible", "api", "deepseek"}:
        if not config.api_key:
            raise LLMProviderError("AI_LLM_API_KEY is required for OpenAI-compatible providers.")

        model = ChatCompletionsModel(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=config.temperature,
            timeout=config.timeout,
            max_tokens=policy.output_tokens,
            output_parameter="max_completion_tokens" if config.provider == "openai" else "max_tokens",
        )
        return GuardedChatModel(model, policy, provider=config.provider, model_name=config.model)

    raise LLMProviderError(f"Unsupported AI_LLM_PROVIDER: {config.provider}")
