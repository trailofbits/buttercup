import logging
import re
from enum import Enum
from pathlib import Path

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.common.llm import create_default_llm
from buttercup.seed_gen.mock_context.mock import get_additional_context, get_harness
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.prompts import PYTHON_SEED_SYSTEM_PROMPT, PYTHON_SEED_USER_PROMPT

logger = logging.getLogger(__name__)


class Task(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


def extract_md(msg: AIMessage) -> str:
    """Extract the markdown from the AI message."""
    if not isinstance(msg, AIMessage):
        raise OutputParserException(
            "extract_md: did not receive an AIMessage. Received: %s", type(msg)
        )
    content = msg.content

    if not isinstance(content, str):
        raise OutputParserException(
            "extract_md: content is not a string. Content is %s", type(content)
        )

    match = re.search(r"```([A-Za-z]*)\n(.*?)```", content, re.DOTALL)
    if match is not None:
        content = match.group(2)
    else:
        logger.warning(
            "extract_md: did not find a markdown block in the AI message. Content is %s...",
            content[:250],
        )

    return content.strip("`")


def generate_seed_funcs(harness: str, additional_context: str, count: int) -> list[bytes]:
    """Generate a python file of seed-generation functions"""
    logger.debug('Additional context (snippet): "%s"', additional_context[:250])
    prompt = ChatPromptTemplate.from_messages(
        [
        ("system", PYTHON_SEED_SYSTEM_PROMPT),
        ("human", PYTHON_SEED_USER_PROMPT),
    ]
    )
    llm = create_default_llm()
    chain = prompt | llm | extract_md
    chain_config = chain.with_config(RunnableConfig(tags=["generate_seed_funcs"]))
    funcs = chain_config.invoke(
        {
            "count": count,
            "harness": harness,
            "additional_context": additional_context,
        }
    )
    return funcs


def do_seed_init(challenge: str, output_dir: Path) -> None:
    """Do seed-init task"""
    logger.info("Doing seed-init for challenge %s", challenge)
    count = 10
    harness = get_harness(challenge)
    additional_context = get_additional_context(challenge)
    try:
        logger.info("Generating %s seed functions for challenge %s", count, challenge)
        funcs = generate_seed_funcs(harness, additional_context, count)
        logger.info("Executing seed functions for challenge %s", challenge)
        sandbox_exec_funcs(funcs, output_dir)
    except Exception as err:
        logger.error("Failed seed-init for challenge %s: %s", challenge, str(err))


def do_seed_explore() -> None:
    """Do seed-explore task"""
    raise NotImplementedError(f"{Task.SEED_EXPLORE} not implemented")


def do_vuln_discovery() -> None:
    """Do vuln-discovery task"""
    raise NotImplementedError(f"{Task.VULN_DISCOVERY} not implemented")
