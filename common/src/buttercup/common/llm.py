import os
from enum import Enum
from typing import Any
import requests
import functools
from langchain_core.language_models import BaseChatModel
from langchain_openai.chat_models import ChatOpenAI
from langfuse.callback import CallbackHandler
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.runnables import ConfigurableField

import logging

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


@functools.cache
def is_langfuse_available() -> bool:
    """Check if LangFuse is available."""
    langfuse_host = os.getenv("LANGFUSE_HOST")
    if not langfuse_host:
        logger.info("LangFuse not configured")
        return False
    try:
        response = requests.post(f"{langfuse_host}/api/public/ingestion", timeout=2)
        return response.status_code == 401  # expect that we aren't authenticated
    except requests.RequestException:
        return False


@functools.cache
def langfuse_auth_check() -> bool:
    """Check if LangFuse is available.

    Uses the ingestion endpoint to check if the API key is valid.
    """
    langfuse_host = os.getenv("LANGFUSE_HOST")
    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    try:
        response = requests.post(
            f"{langfuse_host}/api/public/ingestion", timeout=2, auth=(langfuse_public_key, langfuse_secret_key)
        )
        return response.status_code == 400  # expect that we authenticate, but the request is invalid
    except requests.RequestException:
        return False


@functools.cache
def get_langfuse_callbacks() -> list[BaseCallbackHandler]:
    """Get Langchain callbacks for monitoring LLM calls with LangFuse, if available."""
    if is_langfuse_available():
        try:
            langfuse_handler = CallbackHandler(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST"),
            )
            if langfuse_auth_check():
                logger.info("Tracing with LangFuse enabled")
                return [langfuse_handler]

            logger.warning("LangFuse authentication failed")
        except Exception:
            logger.error("Cannot connect to LangFuse")
    else:
        logger.info("LangFuse not available")

    return []


def create_default_llm(**kwargs: Any) -> BaseChatModel:
    """Create an LLM object with the default configuration."""
    return create_llm(
        model_name=kwargs.pop("model_name", ButtercupLLM.OPENAI_GPT_4_1.value),
        temperature=kwargs.pop("temperature", 0.1),
        timeout=420.0,
        max_retries=3,
        **kwargs,
    )


def create_default_llm_with_temperature(**kwargs: Any) -> BaseChatModel:
    """Create an LLM object with the default configuration and temperature."""
    return create_llm(
        model_name=kwargs.pop("model_name", ButtercupLLM.OPENAI_GPT_4_1.value),
        temperature=kwargs.pop("temperature", 0.1),
        timeout=420.0,
        max_retries=3,
        **kwargs,
    ).configurable_fields(
        temperature=ConfigurableField(
            id="llm_temperature",
            name="LLM temperature",
            description="The temperature for the LLM model",
        ),
    )


def create_llm(**kwargs: Any) -> BaseChatModel:
    """Create an LLM object with the given configuration."""
    return ChatOpenAI(
        openai_api_base=os.environ["BUTTERCUP_LITELLM_HOSTNAME"],
        openai_api_key=os.environ["BUTTERCUP_LITELLM_KEY"],
        **kwargs,
    )
