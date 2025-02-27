import logging
from pathlib import Path

from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from buttercup.seed_gen.mock_context.mock import get_additional_context, get_harness
from buttercup.seed_gen.prompts import PYTHON_SEED_SYSTEM_PROMPT, PYTHON_SEED_USER_PROMPT
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import Task
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


class SeedInitTask(Task):
    SEED_INIT_SEED_COUNT = 10

    def generate_seed_funcs(self, harness: str, additional_context: str) -> str:
        """Generate a python file of seed-generation functions"""
        logger.debug('Additional context (snippet): "%s"', additional_context[:250])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PYTHON_SEED_SYSTEM_PROMPT),
                ("human", PYTHON_SEED_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | extract_md
        chain_config = chain.with_config(RunnableConfig(tags=["generate_seed_funcs"]))
        funcs = chain_config.invoke(
            {
                "count": self.SEED_INIT_SEED_COUNT,
                "harness": harness,
                "additional_context": additional_context,
            }
        )
        return funcs

    def do_task(self, challenge: str, output_dir: Path) -> None:
        """Do seed-init task"""
        logger.info("Doing seed-init for challenge %s", challenge)
        harness = get_harness(challenge)
        additional_context = get_additional_context(challenge)
        try:
            logger.info("Generating seed functions for challenge %s", challenge)
            funcs = self.generate_seed_funcs(harness, additional_context)
            logger.info("Executing seed functions for challenge %s", challenge)
            sandbox_exec_funcs(funcs, output_dir)
        except Exception as err:
            logger.error("Failed seed-init for challenge %s: %s", challenge, str(err))
