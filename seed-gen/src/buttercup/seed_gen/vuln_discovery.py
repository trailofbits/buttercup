import logging
from pathlib import Path

from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.seed_gen.prompts import (
    DIFF_ANALYSIS_SYSTEM_PROMPT,
    DIFF_ANALYSIS_USER_PROMPT,
    VULN_DISCOVERY_FUNCTION_LOOKUP_SYSTEM_PROMPT,
    VULN_DISCOVERY_FUNCTION_LOOKUP_USER_PROMPT,
    WRITE_POV_SYSTEM_PROMPT,
    WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import FunctionRequestList, Task
from buttercup.seed_gen.utils import extract_md, get_diff_content

logger = logging.getLogger(__name__)


class VulnDiscoveryTask(Task):
    VULN_DISCOVERY_MAX_POV_COUNT = 8
    MAX_LOOKUP_FUNCTIONS = 5
    MAX_ITERATIONS = 2

    def _lookup_functions(self, diff: str, harness: str, collected_functions: dict[str, str]):
        """Ask the LLM which functions it would like to understand better

        Adds new functions to collected_functions
        """
        logger.info("Looking up functions")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", VULN_DISCOVERY_FUNCTION_LOOKUP_SYSTEM_PROMPT),
                ("human", VULN_DISCOVERY_FUNCTION_LOOKUP_USER_PROMPT),
            ]
        )
        parser = JsonOutputParser(pydantic_object=FunctionRequestList)
        chain = prompt | self.llm | parser

        additional_functions = "\n\n...\n\n".join(
            f"{body}" for body in collected_functions.values()
        )

        try:
            response = chain.invoke(
                {
                    "diff": diff,
                    "harness": harness,
                    "additional_functions": additional_functions,
                    "max_lookup_functions": self.MAX_LOOKUP_FUNCTIONS,
                }
            )

            for func in response[: self.MAX_LOOKUP_FUNCTIONS]:
                func_name = func["name"]
                if func_name in collected_functions:
                    continue

                # Get function definition
                func_def = self._do_get_function_def(func_name, [None])
                if func_def:
                    collected_functions[func_name] = func_def.bodies[0].body
                    logger.info(f"Collected function definition for {func_name}")
                else:
                    logger.warning(f"Could not find definition for function {func_name}")

        except Exception as e:
            logger.error("Error during function lookup: %s", str(e))

        return collected_functions

    def analyze_diff(self, diff: str, harness: str, additional_functions: str) -> str:
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
                "additional_functions": additional_functions,
            }
        )
        return analysis

    def write_pov_funcs(
        self, analysis: str, harness: str, diff: str, additional_functions: str
    ) -> str:
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
                "additional_functions": additional_functions,
            }
        )
        return pov_funcs

    def do_task(self, output_dir: Path) -> None:
        """Do vuln-discovery task"""
        logger.info("Doing vuln-discovery for challenge %s", self.package_name)
        harness = self.get_harness_source()
        if harness is None:
            return
        diffs = self.challenge_task.get_diffs()
        diff_content = get_diff_content(diffs)
        if diff_content is None:
            # currently assumes diff mode
            logger.error("No diff found for challenge %s", self.package_name)
            return
        collected_functions = {}
        try:
            for _ in range(self.MAX_ITERATIONS):
                # Look up functions once and reuse the results
                self._lookup_functions(diff_content, harness, collected_functions)

            additional_functions = "\n\n...\n\n".join(
                f"{body}" for body in collected_functions.values()
            )

            logger.info("Analyzing the diff in challenge %s", self.package_name)
            analysis = self.analyze_diff(diff_content, harness, additional_functions)
            logger.info("Making PoVs for the challenge %s", self.package_name)
            pov_funcs = self.write_pov_funcs(analysis, harness, diff_content, additional_functions)
            sandbox_exec_funcs(pov_funcs, output_dir)
        except Exception as err:
            logger.error("Failed vuln-discovery for challenge %s: %s", self.package_name, str(err))
