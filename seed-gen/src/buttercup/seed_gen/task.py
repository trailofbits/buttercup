import logging
from enum import Enum
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm, get_langfuse_callbacks
from buttercup.program_model.api import Graph
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function
from buttercup.seed_gen.find_harness import get_harness_source_candidates

logger = logging.getLogger(__name__)


class TaskName(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


class Task:
    def __init__(
        self,
        package_name: str,
        harness_name: str,
        challenge_task: ChallengeTask,
        codequery: CodeQueryPersistent,
        llm: BaseChatModel | None = None,
    ):
        self.package_name = package_name
        self.harness_name = harness_name
        self.challenge_task = challenge_task
        self.codequery = codequery
        if llm is None:
            self.llm = self.get_default_llm()
        else:
            self.llm = llm
        self.program_model = Graph()

    @staticmethod
    def get_default_llm() -> BaseChatModel:
        llm_callbacks = get_langfuse_callbacks()
        llm = create_default_llm(
            model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value, callbacks=llm_callbacks
        )
        return llm

    def get_harness_source(self) -> str | None:
        logger.info("Getting harness source for %s | %s", self.package_name, self.harness_name)
        harnesses = get_harness_source_candidates(
            self.challenge_task, self.package_name, self.harness_name
        )
        logger.info("Found %d harness candidates", len(harnesses))
        logger.debug("Harness candidates: %s", [h for h in harnesses])
        # TODO: use the LLM to select the best harness out of multiple candidates
        if len(harnesses) == 0:
            logger.error("No harness found for %s | %s", self.package_name, self.harness_name)
            return None
        if len(harnesses) > 1:
            logger.warning(
                "Multiple harnesses found for %s | %s. Returning first one.",
                self.package_name,
                self.harness_name,
            )

        return harnesses[0].read_text()

    def get_function_def(self, function_name: str, function_paths: list[Path]) -> Function | None:
        logger.info("Getting function definition for %s (paths: %s)", function_name, function_paths)
        for function_path in function_paths:
            function_defs = self.codequery.get_functions(function_name, function_path)
            if len(function_defs) == 0:
                logger.debug(
                    "No function definition found for %s in %s", function_name, function_path
                )
                continue
            if len(function_defs) > 1:
                logger.warning(
                    "Multiple function definitions found for %s in %s. using first one.",
                    function_name,
                    function_path,
                )
            else:
                logger.info("Found function definition for %s in %s", function_name, function_path)
            return function_defs[0]
        logger.warning(
            "No function definition found for %s (paths: %s)", function_name, function_paths
        )
        return None
