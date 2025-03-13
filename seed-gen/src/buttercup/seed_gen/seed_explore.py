import logging
from pathlib import Path

from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.seed_gen.prompts import (
    PYTHON_SEED_EXPLORE_SYSTEM_PROMPT,
    PYTHON_SEED_EXPLORE_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import Task
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


class SeedExploreTask(Task):
    SEED_EXPLORE_SEED_COUNT = 10

    def generate_seed_funcs(self, harness: str, target_function: str) -> str:
        """Generate a python file of seed-generation functions"""

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PYTHON_SEED_EXPLORE_SYSTEM_PROMPT),
                ("human", PYTHON_SEED_EXPLORE_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | extract_md
        chain_config = chain.with_config(RunnableConfig(tags=["seed-explore"]))
        funcs = chain_config.invoke(
            {
                "count": self.SEED_EXPLORE_SEED_COUNT,
                "harness": harness,
                "target_function": target_function,
            }
        )
        return funcs

    def do_task(
        self, target_function_name: str, target_function_paths: list[Path], output_dir: Path
    ) -> None:
        """Do seed-explore task"""
        logger.info(
            "Doing seed-explore for challenge %s and function %s (paths: %s)",
            self.package_name,
            target_function_name,
            target_function_paths,
        )
        function_def = self.get_function_def(target_function_name, target_function_paths)
        if not function_def:
            logger.error("No function definition found for %s", target_function_name)
            return
        function_def_body = function_def.bodies[0].body

        harness = self.get_harness_source()
        if harness is None:
            return
        try:
            logger.info(
                "Generating seed functions for challenge %s and target function %s",
                self.package_name,
                target_function_name,
            )
            funcs = self.generate_seed_funcs(harness, function_def_body)
            logger.info("Executing seed functions for challenge %s", self.package_name)
            sandbox_exec_funcs(funcs, output_dir)
        except Exception as err:
            logger.error("Failed seed-explore for challenge %s: %s", self.package_name, str(err))
