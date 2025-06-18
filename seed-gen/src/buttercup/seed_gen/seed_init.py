import logging
from dataclasses import dataclass
from pathlib import Path
from typing import override

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from opentelemetry import trace

from buttercup.common.llm import get_langfuse_callbacks
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.seed_gen.prompt.seed_init import (
    PYTHON_SEED_INIT_SYSTEM_PROMPT,
    PYTHON_SEED_INIT_USER_PROMPT,
    SEED_INIT_GET_CONTEXT_SYSTEM_PROMPT,
    SEED_INIT_GET_CONTEXT_USER_PROMPT,
)
from buttercup.seed_gen.seed_task import SeedBaseTask
from buttercup.seed_gen.task import BaseTaskState, HarnessInfo

logger = logging.getLogger(__name__)


@dataclass
class SeedInitTask(SeedBaseTask):
    SEED_INIT_SEED_COUNT = 8
    MAX_CONTEXT_ITERATIONS = 4

    @override
    def _generate_seeds(self, state: BaseTaskState) -> Command:
        """Generate seed functions using collected function definitions"""
        logger.info("Generating seeds")
        prompt_vars = {
            "count": self.SEED_INIT_SEED_COUNT,
            "harness": str(state.harness),
            "retrieved_context": state.format_retrieved_context(),
        }
        generated_functions = self._generate_python_funcs_base(
            PYTHON_SEED_INIT_SYSTEM_PROMPT, PYTHON_SEED_INIT_USER_PROMPT, prompt_vars
        )
        return Command(update={"generated_functions": generated_functions})

    @override
    def _get_context(self, state: BaseTaskState) -> Command:
        """Generate tool calls to retrieve context"""

        logger.info("Getting context")
        prompt_vars = {
            "harness": str(state.harness),
            "retrieved_context": state.format_retrieved_context(),
        }
        res = self._get_context_base(
            SEED_INIT_GET_CONTEXT_SYSTEM_PROMPT,
            SEED_INIT_GET_CONTEXT_USER_PROMPT,
            state,
            prompt_vars,
        )
        return res

    def generate_seeds(self, harness: HarnessInfo, output_dir: Path) -> None:
        """Generate a python file of seed-generation functions"""
        state = BaseTaskState(
            harness=harness,
            task=self,
            output_dir=output_dir,
        )
        workflow = self._build_workflow(BaseTaskState)
        llm_callbacks = get_langfuse_callbacks()
        chain = workflow.compile().with_config(
            RunnableConfig(tags=["seed-init"], callbacks=llm_callbacks)
        )
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("seed_gen_init") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.INPUT_GENERATION,
                crs_action_name="seed_gen_init",
                task_metadata=dict(self.challenge_task.task_meta.metadata),
                extra_attributes={
                    "gen_ai.request.model": self.llm.model_name,
                },
            )
            chain.invoke(state)

    def do_task(self, output_dir: Path) -> None:
        """Do seed-init task"""
        logger.info("Doing seed-init for challenge %s", self.package_name)
        harness = self.get_harness_source()
        if harness is None:
            return
        try:
            logger.info("Generating seeds for challenge %s", self.package_name)
            self.generate_seeds(harness, output_dir)
        except Exception as err:
            logger.exception("Failed seed-init for challenge %s: %s", self.package_name, str(err))
