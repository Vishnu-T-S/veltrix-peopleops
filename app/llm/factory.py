"""Pick the LLM provider named by LLM_PROVIDER."""
from __future__ import annotations

import logging

from app.config import Settings
from app.llm.client import LLM, AnthropicClient, GeminiClient, OpenAIClient

logger = logging.getLogger("veltrix.llm")


def make_llm(settings: Settings) -> LLM:
    provider = (settings.llm_provider or "openai").strip().lower()
    if provider == "openai":
        return OpenAIClient(settings.openai_api_key, settings.openai_model)
    if provider in ("anthropic", "claude"):
        return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
    if provider in ("gemini", "google"):
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    # The service still starts (so /health works); every model call will report that it is unavailable.
    logger.error("unknown LLM_PROVIDER %r: use openai, anthropic or gemini", provider)
    return OpenAIClient(None, None)
