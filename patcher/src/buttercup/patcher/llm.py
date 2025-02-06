"""LLM-related functions/classes"""

import functools
import logging
import os
from enum import Enum
from typing import Any

import requests
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_openai.chat_models import ChatOpenAI
from langfuse.callback import CallbackHandler

logger = logging.getLogger(__name__)

@functools.cache
def is_langfuse_available() -> bool:
    """Check if LangFuse is available."""
    langfuse_host = os.getenv("LANGFUSE_HOST")
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
