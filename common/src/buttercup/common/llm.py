import os
from enum import Enum
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_openai.chat_models import ChatOpenAI


class ButtercupLLM(Enum):
    """Enum for LLM models available in LiteLLM."""

    AZURE_GPT_4O = "azure-gpt-4o"
    AZURE_GPT_4O_MINI = "azure-gpt-4o-mini"


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
        openai_api_base=os.getenv("BUTTERCUP_LITELLM_HOSTNAME"),  # type: ignore[call-arg]
        openai_api_key=os.getenv("BUTTERCUP_LITELLM_KEY"),
        **kwargs,
    )
