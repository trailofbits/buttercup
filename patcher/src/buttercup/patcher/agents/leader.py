"""LLM-based Patcher Agent module"""

import logging
from dataclasses import dataclass
from pathlib import Path

import openai
from opentelemetry import trace
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from buttercup.patcher.agents.config import PatcherConfig
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory
from buttercup.patcher.agents.common import PatcherAgentState, PatcherAgentName, PatcherAgentBase
from buttercup.patcher.agents.qe import QEAgent
from buttercup.patcher.agents.rootcause import RootCauseAgent
from buttercup.patcher.agents.swe import SWEAgent
from buttercup.patcher.agents.context_retriever import ContextRetrieverAgent
from buttercup.patcher.agents.reflection import ReflectionAgent
from buttercup.patcher.agents.input_processing import InputProcessingAgent
from buttercup.patcher.utils import PatchOutput
from buttercup.common.llm import get_langfuse_callbacks
from redis import Redis

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 200


@dataclass
class PatcherLeaderAgent(PatcherAgentBase):
    """LLM-based Patcher Agent."""

    redis: Redis | None
    work_dir: Path
    tasks_storage: Path
    model_name: str | None = None

    def _init_patch_team(self) -> StateGraph:
        rootcause_agent = RootCauseAgent(self.challenge, self.input, chain_call=self.chain_call)
        swe_agent = SWEAgent(self.challenge, self.input, chain_call=self.chain_call)
        qe_agent = QEAgent(self.challenge, self.input, chain_call=self.chain_call)
        context_retriever_agent = ContextRetrieverAgent(
            self.challenge, self.input, chain_call=self.chain_call, redis=self.redis
        )
        reflection_agent = ReflectionAgent(self.challenge, self.input, chain_call=self.chain_call)
        input_processing_agent = InputProcessingAgent(self.challenge, self.input, chain_call=self.chain_call)
        self.model_name = swe_agent.default_llm.model_name

        workflow = StateGraph(PatcherAgentState, PatcherConfig)
        workflow.add_node(PatcherAgentName.FIND_TESTS.value, context_retriever_agent.find_tests_node)
        workflow.add_node(PatcherAgentName.INPUT_PROCESSING.value, input_processing_agent.process_input)
        workflow.add_node(
            PatcherAgentName.INITIAL_CODE_SNIPPET_REQUESTS.value, context_retriever_agent.get_initial_context
        )
        workflow.add_node(PatcherAgentName.ROOT_CAUSE_ANALYSIS.value, rootcause_agent.analyze_vulnerability)
        workflow.add_node(PatcherAgentName.PATCH_STRATEGY.value, swe_agent.select_patch_strategy)
        workflow.add_node(PatcherAgentName.CREATE_PATCH.value, swe_agent.create_patch_node)
        workflow.add_node(PatcherAgentName.BUILD_PATCH.value, qe_agent.build_patch_node)
        workflow.add_node(PatcherAgentName.RUN_POV.value, qe_agent.run_pov_node)
        workflow.add_node(PatcherAgentName.RUN_TESTS.value, qe_agent.run_tests_node)
        workflow.add_node(PatcherAgentName.REFLECTION.value, reflection_agent.reflect_on_patch)
        workflow.add_node(PatcherAgentName.CONTEXT_RETRIEVER.value, context_retriever_agent.retrieve_context)
        workflow.add_node(PatcherAgentName.PATCH_VALIDATION.value, qe_agent.validate_patch_node)

        workflow.set_entry_point(PatcherAgentName.INPUT_PROCESSING.value)
        return workflow

    def run_patch_task(self) -> PatchOutput | None:
        """Run the patching task."""
        patch_team = self._init_patch_team()
        llm_callbacks = get_langfuse_callbacks()
        chain = patch_team.compile().with_config(
            RunnableConfig(
                callbacks=llm_callbacks,
                tags=["patch_team", self.challenge.name, self.input.task_id, self.input.internal_patch_id],
                metadata={
                    "task_id": self.input.task_id,
                    "internal_patch_id": self.input.internal_patch_id,
                    "challenge_project_name": self.challenge.name,
                },
                recursion_limit=RECURSION_LIMIT,
                configurable={
                    "work_dir": self.work_dir,
                    "tasks_storage": self.tasks_storage,
                },
            )
        )

        state = PatcherAgentState(messages=[], context=self.input)
        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("generate_pov_patch") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.PATCH_GENERATION,
                    crs_action_name="generate_pov_patch",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                    extra_attributes={
                        "gen_ai.request.model": self.model_name,
                    },
                )

                output_state_dict: dict = chain.invoke(state)
                output_state = PatcherAgentState(**output_state_dict)
                output_state.clean_built_challenges()
                return output_state.get_successful_patch()
        except openai.OpenAIError:
            logger.exception("OpenAI error")
            return None
        except ValueError:
            logger.exception("Could not generate a patch")
            return None
        except Exception:
            logger.exception("Unexpected error during patch generation")
            return None
