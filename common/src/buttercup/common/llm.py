import os
from enum import Enum
from typing import Any
import requests
import functools
from langchain_core.language_models import BaseChatModel
from langchain_openai.chat_models import ChatOpenAI
from langfuse.callback import CallbackHandler
from langchain.callbacks.base import BaseCallbackHandler

import logging

logger = logging.getLogger(__name__)


class ButtercupLLM(Enum):
    """Enum for LLM models available in LiteLLM."""

    AZURE_GPT_4O = "azure-gpt-4o"
    AZURE_GPT_4O_MINI = "azure-gpt-4o-mini"


@functools.cache
def is_langfuse_available() -> bool:
    """Check if LangFuse is available."""
    langfuse_host = os.getenv("LANGFUSE_HOST")
    if not langfuse_host:
        logger.info("LangFuse not configured")
        return False
    try:
        response = requests.get(f"{langfuse_host}/api/public/health", timeout=2)
        return response.status_code == 200
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
            if langfuse_handler.auth_check():
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
        model_name=ButtercupLLM.AZURE_GPT_4O.value,
        temperature=kwargs.pop("temperature", 0.1),
        timeout=420.0,
        max_retries=3,
        **kwargs,
    )


def create_llm(**kwargs: Any) -> BaseChatModel:
    """Create an LLM object with the given configuration."""
    return ChatOpenAI(
        openai_api_base=os.environ["BUTTERCUP_LITELLM_HOSTNAME"],
        openai_api_key=os.environ["BUTTERCUP_LITELLM_KEY"],
        **kwargs,
    )
