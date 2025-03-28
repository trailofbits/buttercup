import logging
import re
from enum import Enum
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm, get_langfuse_callbacks
from buttercup.program_model.api import Graph
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function
from buttercup.seed_gen.find_harness import get_harness_source_candidates
from buttercup.seed_gen.utils import rebase_src_path

logger = logging.getLogger(__name__)


class FunctionRequest(BaseModel):
    """Requested function to look up."""

    name: str = Field(description="The name of the function to look up")
    reason: str = Field(
        description="A brief explanation of why understanding this function would be helpful"
    )


class FunctionRequestList(BaseModel):
    """List of requested functions to look up."""

    functions: list[FunctionRequest] = Field(description="List of functions to look up")


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
            model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value,
            callbacks=llm_callbacks,
        )
        fallback_llm = create_default_llm(
            model_name=ButtercupLLM.OPENAI_GPT_4O.value, callbacks=llm_callbacks
        )
        return llm.with_fallbacks([fallback_llm])

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

    @staticmethod
    def clean_func_name(func_name: str) -> str:
        """Heuristic function to clean up function names for codequery

        Handles the following function name formats:
        - OSS_FUZZ_ prefixed names (e.g., OSS_FUZZ_png_sig_cmp)
        - File path prefixed names (e.g., png.c:png_colorspace_check_gamma)

        Args:
            func_name: The function name to clean

        Returns:
            The cleaned function name
        """
        cleaned_func_name = func_name
        if func_name.startswith("OSS_FUZZ_"):
            cleaned_func_name = func_name[len("OSS_FUZZ_") :]

        file_path_pattern = re.compile(r"^([^:]*\.[^:]*:)(.*)")
        match = file_path_pattern.match(func_name)
        if match:
            cleaned_func_name = match.group(2)
        if cleaned_func_name != func_name:
            logger.info("Cleaned function name %s -> %s", func_name, cleaned_func_name)
        return cleaned_func_name

    def _do_get_function_def(
        self, function_name: str, function_paths: list[Path]
    ) -> Function | None:
        for function_path in function_paths:
            function_path_mod = (
                function_path
                if function_path is None
                else rebase_src_path(function_path, self.challenge_task.project_name)
            )
            function_defs = self.codequery.get_functions(function_name, function_path_mod)
            if len(function_defs) == 0:
                continue
            if len(function_defs) > 1:
                logger.warning(
                    "Multiple function definitions found for %s in %s. using first one.",
                    function_name,
                    function_path,
                )
            else:
                logger.info(
                    "Found function definition for %s in %s",
                    function_name,
                    function_path,
                )
            return function_defs[0]

        logger.debug(
            "No function definition found for %s in paths: %s", function_name, function_paths
        )
        return None

    def get_function_def(self, function_name: str, function_paths: list[Path]) -> Function | None:
        """Get function definition from codequery, with progressively less precise searches"""
        logger.info("Getting function definition for %s (paths: %s)", function_name, function_paths)

        # Exact match in paths
        function_def = self._do_get_function_def(function_name, function_paths)
        if function_def is not None:
            return function_def

        # Cleaned exact match in paths
        cleaned_function_name = self.clean_func_name(function_name)
        function_def = self._do_get_function_def(cleaned_function_name, function_paths)
        if function_def is not None:
            return function_def

        # Exact match general
        function_def = self._do_get_function_def(function_name, [None])
        if function_def is not None:
            return function_def

        # Cleaned match general
        function_def = self._do_get_function_def(cleaned_function_name, [None])
        if function_def is not None:
            return function_def

        logger.warning(
            "No function definition found for %s (paths: %s)", function_name, function_paths
        )
        return None
