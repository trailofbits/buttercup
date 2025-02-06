import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.common.llm import create_default_llm
from buttercup.seed_gen.prompts import (
    DIFF_ANALYSIS_SYSTEM_PROMPT,
    DIFF_ANALYSIS_USER_PROMPT,
    WRITE_POV_SYSTEM_PROMPT,
    WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


def analyze_diff(diff: str, harness: str) -> str:
    """
    Analyze a diff for a project and a test harness to determine if the diff introduces a vuln.
    """
    llm = create_default_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", DIFF_ANALYSIS_SYSTEM_PROMPT),
            ("human", DIFF_ANALYSIS_USER_PROMPT),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    chain_config = chain.with_config(RunnableConfig(tags=["analyze_diff"]))
    analysis = chain_config.invoke(
        {
            "diff": diff,
            "harness": harness,
        }
    )
    return analysis


def write_pov_funcs(analysis: str, harness: str, diff: str, max_povs: int) -> str:
    """
    Write PoVs for a vulnerability.
    """
    llm = create_default_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", WRITE_POV_SYSTEM_PROMPT),
            ("human", WRITE_POV_USER_PROMPT),
        ]
    )
    chain = prompt | llm | extract_md
    chain_config = chain.with_config(RunnableConfig(tags=["write_pov_funcs"]))
    pov_funcs = chain_config.invoke(
        {
            "analysis": analysis,
            "harness": harness,
            "diff": diff,
            "max_povs": max_povs,
        }
    )
    return pov_funcs
