import logging
from enum import Enum
from pathlib import Path

from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.common.llm import create_default_llm, get_langfuse_callbacks
from buttercup.seed_gen.mock_context.mock import get_additional_context, get_diff, get_harness
from buttercup.seed_gen.prompts import PYTHON_SEED_SYSTEM_PROMPT, PYTHON_SEED_USER_PROMPT
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.utils import extract_md
from buttercup.seed_gen.vuln_discovery import analyze_diff, write_pov_funcs

logger = logging.getLogger(__name__)

SEED_INIT_SEED_COUNT = 10
VULN_DISCOVERY_MAX_POV_COUNT = 10


class Task(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


def generate_seed_funcs(harness: str, additional_context: str, count: int) -> list[bytes]:
    """Generate a python file of seed-generation functions"""
    logger.debug('Additional context (snippet): "%s"', additional_context[:250])
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", PYTHON_SEED_SYSTEM_PROMPT),
            ("human", PYTHON_SEED_USER_PROMPT),
        ]
    )
    llm_callbacks = get_langfuse_callbacks()
    llm = create_default_llm(callbacks=llm_callbacks)
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
    count = SEED_INIT_SEED_COUNT
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


def do_vuln_discovery(challenge: str, output_dir: Path) -> None:
    """Do vuln-discovery task"""
    logger.info("Doing vuln-discovery for challenge %s", challenge)
    max_povs = VULN_DISCOVERY_MAX_POV_COUNT
    harness = get_harness(challenge)
    diff = get_diff(challenge)
    try:
        logger.info("Analyzing the diff in challenge %s", challenge)
        analysis = analyze_diff(diff, harness)
        logger.info("Making PoVs for the challenge %s", challenge)
        pov_funcs = write_pov_funcs(analysis, harness, diff, max_povs)
        sandbox_exec_funcs(pov_funcs, output_dir)
    except Exception as err:
        logger.error("Failed vuln-discovery for challenge %s: %s", challenge, str(err))
