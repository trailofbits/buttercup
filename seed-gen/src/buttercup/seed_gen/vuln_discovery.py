import logging
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.seed_gen.mock_context.mock import get_diff, get_harness
from buttercup.seed_gen.prompts import (
    DIFF_ANALYSIS_SYSTEM_PROMPT,
    DIFF_ANALYSIS_USER_PROMPT,
    WRITE_POV_SYSTEM_PROMPT,
    WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import Task
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


class VulnDiscoveryTask(Task):
    VULN_DISCOVERY_MAX_POV_COUNT = 10

    def analyze_diff(self, diff: str, harness: str) -> str:
        """
        Analyze a diff for a project and a test harness to determine if the diff introduces a vuln.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DIFF_ANALYSIS_SYSTEM_PROMPT),
                ("human", DIFF_ANALYSIS_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        chain_config = chain.with_config(RunnableConfig(tags=["analyze_diff"]))
        analysis = chain_config.invoke(
            {
                "diff": diff,
                "harness": harness,
            }
        )
        return analysis

    def write_pov_funcs(self, analysis: str, harness: str, diff: str) -> str:
        """
        Write PoVs for a vulnerability.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", WRITE_POV_SYSTEM_PROMPT),
                ("human", WRITE_POV_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | extract_md
        chain_config = chain.with_config(RunnableConfig(tags=["write_pov_funcs"]))
        pov_funcs = chain_config.invoke(
            {
                "analysis": analysis,
                "harness": harness,
                "diff": diff,
                "max_povs": self.VULN_DISCOVERY_MAX_POV_COUNT,
            }
        )
        return pov_funcs

    def do_task(self, challenge: str, output_dir: Path) -> None:
        """Do vuln-discovery task"""
        logger.info("Doing vuln-discovery for challenge %s", challenge)
        harness = get_harness(challenge)
        diff = get_diff(challenge)
        try:
            logger.info("Analyzing the diff in challenge %s", challenge)
            analysis = self.analyze_diff(diff, harness)
            logger.info("Making PoVs for the challenge %s", challenge)
            pov_funcs = self.write_pov_funcs(analysis, harness, diff)
            sandbox_exec_funcs(pov_funcs, output_dir)
        except Exception as err:
            logger.error("Failed vuln-discovery for challenge %s: %s", challenge, str(err))
