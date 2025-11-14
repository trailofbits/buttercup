import functools
import logging
import os
from enum import Enum
from sys import exception
from typing import Any

import requests
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import ConfigurableField, Runnable
from langchain_openai.chat_models import ChatOpenAI
from langfuse import get_client
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)


class ButtercupLLM(Enum):
    """Enum for LLM models available in LiteLLM."""

    AZURE_GPT_4O = "azure-gpt-4o"
    AZURE_GPT_4O_MINI = "azure-gpt-4o-mini"
    AZURE_O3_MINI = "azure-o3-mini"
    AZURE_O1 = "azure-o1"
    OPENAI_GPT_4O = "openai-gpt-4o"
    OPENAI_GPT_4O_MINI = "openai-gpt-4o-mini"
    OPENAI_O3_MINI = "openai-o3-mini"
    OPENAI_O3 = "openai-o3"
    OPENAI_O1 = "openai-o1"
    OPENAI_GPT_4_1_NANO = "openai-gpt-4.1-nano"
    OPENAI_GPT_4_1_MINI = "openai-gpt-4.1-mini"
    OPENAI_GPT_4_1 = "openai-gpt-4.1"
    CLAUDE_3_5_SONNET = "claude-3.5-sonnet"
    CLAUDE_3_7_SONNET = "claude-3.7-sonnet"
    CLAUDE_4_SONNET = "claude-4-sonnet"
    GEMINI_PRO = "gemini-pro"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_EXP = "gemini-2.5-flash-exp"


@functools.cache
def is_langfuse_available() -> bool:
    """Check if LangFuse is available."""
    client = get_client()
    try:
        return client.auth_check()
    except Exception:
        return False


@functools.cache
def get_langfuse_callbacks() -> list[BaseCallbackHandler]:
    """Get Langchain callbacks for monitoring LLM calls with LangFuse, if available."""
    if not is_langfuse_available():
        logger.warning("LangFuse not available")
        return []

    langfuse_handler = CallbackHandler()
    logger.info("Tracing with LangFuse enabled")
    return [langfuse_handler]


def create_default_llm(**kwargs: Any) -> Runnable:
    """Create an LLM object with the default configuration."""
    fallback_models = kwargs.pop("fallback_models", [])
    fallback_models = [create_default_llm(**{**kwargs, "model_name": m.value}) for m in fallback_models]
    return create_llm(
        model_name=kwargs.pop("model_name", ButtercupLLM.OPENAI_GPT_4_1.value),
        temperature=kwargs.pop("temperature", 0.1),
        timeout=420.0,
        max_retries=3,
        **kwargs,
    ).with_fallbacks(fallback_models)


def create_default_llm_with_temperature(**kwargs: Any) -> Runnable:
    """Create an LLM object with the default configuration and temperature."""
    fallback_models = kwargs.pop("fallback_models", [])
    fallback_models = [
        create_default_llm_with_temperature(**{**kwargs, "model_name": m.value}) for m in fallback_models
    ]
    return (
        create_llm(
            model_name=kwargs.pop("model_name", ButtercupLLM.OPENAI_GPT_4_1.value),
            temperature=kwargs.pop("temperature", 0.1),
            timeout=420.0,
            max_retries=3,
            **kwargs,
        )
        .configurable_fields(
            temperature=ConfigurableField(
                id="llm_temperature",
                name="LLM temperature",
                description="The temperature for the LLM model",
            ),
        )
        .with_fallbacks(fallback_models)
    )


def create_llm(**kwargs: Any) -> BaseChatModel:
    """Create an LLM object with the given configuration."""
    return ChatOpenAI(
        openai_api_base=os.environ["BUTTERCUP_LITELLM_HOSTNAME"],
        openai_api_key=os.environ["BUTTERCUP_LITELLM_KEY"],
        **kwargs,
    )
