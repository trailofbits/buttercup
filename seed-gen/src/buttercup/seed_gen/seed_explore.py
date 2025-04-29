import logging
from pathlib import Path
from typing import override

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from opentelemetry import trace
from pydantic import Field

from buttercup.common.llm import get_langfuse_callbacks
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.seed_gen.prompts import (
    PYTHON_SEED_EXPLORE_SYSTEM_PROMPT,
    PYTHON_SEED_EXPLORE_USER_PROMPT,
    SEED_EXPLORE_GET_CONTEXT_SYSTEM_PROMPT,
    SEED_EXPLORE_GET_CONTEXT_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.seed_task import SeedBaseTask
from buttercup.seed_gen.task import BaseTaskState

logger = logging.getLogger(__name__)


class SeedExploreState(BaseTaskState):
    """State for the SeedExplore task."""

    target_function: str = Field(description="The target function to generate seeds for")


class SeedExploreTask(SeedBaseTask):
    SEED_EXPLORE_SEED_COUNT = 8
    MAX_CONTEXT_ITERATIONS = 2
    MAX_TOOL_CALLS = 4

    TARGET_FUNCTION_FUZZY_THRESHOLD = 50

    @override
    def _generate_seeds(self, state: SeedExploreState) -> Command:
        """Generate seed functions using collected function definitions"""
        logger.info("Generating seeds")
        prompt_vars = {
            "count": self.SEED_EXPLORE_SEED_COUNT,
            "harness": state.harness,
            "target_function": state.target_function,
            "retrieved_context": state.format_retrieved_context(),
        }
        generated_functions = self._generate_python_funcs_base(
            PYTHON_SEED_EXPLORE_SYSTEM_PROMPT, PYTHON_SEED_EXPLORE_USER_PROMPT, prompt_vars
        )
        return Command(update={"generated_functions": generated_functions})

    @override
    def _get_context(self, state: SeedExploreState) -> Command:
        """Generate tool calls to retrieve context"""

        logger.info("Getting context")
        prompt_vars = {
            "target_function": state.target_function,
            "harness": state.harness,
            "retrieved_code": state.format_retrieved_context(),
            "max_calls": self.MAX_TOOL_CALLS,
        }
        res = self._get_context_base(
            SEED_EXPLORE_GET_CONTEXT_SYSTEM_PROMPT,
            SEED_EXPLORE_GET_CONTEXT_USER_PROMPT,
            state,
            prompt_vars,
        )
        return res

    def generate_seed_funcs(self, harness: str, target_function: str) -> str:
        """Generate a python file of seed-generation functions"""

        state = SeedExploreState(
            target_function=target_function,
            harness=harness,
            task=self,
        )
        workflow = self._build_workflow(SeedExploreState)
        llm_callbacks = get_langfuse_callbacks()
        chain = workflow.compile().with_config(
            RunnableConfig(tags=["seed-explore"], callbacks=llm_callbacks)
        )
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("seed_gen_explore") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.INPUT_GENERATION,
                crs_action_name="seed_gen_explore",
                task_metadata=dict(self.challenge_task.task_meta.metadata),
            )
            result = chain.invoke(state)

        return result["generated_functions"]

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
        cleaned_name = self.clean_func_name(target_function_name)
        function_def = self.get_function_def(
            cleaned_name,
            target_function_paths,
            fuzzy_threshold=self.TARGET_FUNCTION_FUZZY_THRESHOLD,
        )
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
