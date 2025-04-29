"""LLM-based Patcher Agent module"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import openai
from opentelemetry import trace
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from buttercup.patcher.utils import CHAIN_CALL_TYPE
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory
from buttercup.patcher.agents.common import PatcherAgentState, PatcherAgentName
from buttercup.patcher.agents.qe import QEAgent
from buttercup.patcher.agents.rootcause import RootCauseAgent
from buttercup.patcher.agents.swe import SWEAgent
from buttercup.patcher.agents.context_retriever import ContextRetrieverAgent
from buttercup.patcher.utils import PatchInput, PatchOutput
from buttercup.common.llm import get_langfuse_callbacks

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 200


@dataclass
class PatcherLeaderAgent:
    """LLM-based Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    chain_call: CHAIN_CALL_TYPE
    work_dir: Path

    # Default to a low number as the patcher will be run multiple times and it
    # will eventually retry this many times.
    max_patch_retries: int = int(os.getenv("TOB_PATCHER_MAX_PATCH_RETRIES", 10))
    max_review_retries: int = int(os.getenv("TOB_PATCHER_MAX_REVIEW_RETRIES", 5))
    max_context_retriever_retries: int = int(os.getenv("TOB_PATCHER_MAX_CONTEXT_RETRIEVER_RETRIES", 30))
    max_context_retriever_recursion_limit: int = int(os.getenv("TOB_PATCHER_CTX_RETRIEVER_RECURSION_LIMIT", 80))

    def _init_patch_team(self) -> StateGraph:
        rootcause_agent = RootCauseAgent(self.challenge, self.input, chain_call=self.chain_call)
        swe_agent = SWEAgent(
            self.challenge,
            self.input,
            chain_call=self.chain_call,
            max_patch_retries=self.max_patch_retries,
        )
        qe_agent = QEAgent(
            self.challenge,
            self.input,
            chain_call=self.chain_call,
            max_review_retries=self.max_review_retries,
            work_dir=self.work_dir,
        )
        context_retriever_agent = ContextRetrieverAgent(
            self.challenge,
            self.input,
            chain_call=self.chain_call,
            work_dir=self.work_dir,
            max_retries=self.max_context_retriever_retries,
            recursion_limit=self.max_context_retriever_recursion_limit,
        )

        workflow = StateGraph(PatcherAgentState)
        workflow.add_node(PatcherAgentName.CONTEXT_RETRIEVER.value, context_retriever_agent.retrieve_context)
        workflow.add_node(PatcherAgentName.ROOT_CAUSE_ANALYSIS.value, rootcause_agent.analyze_vulnerability)
        workflow.add_node(PatcherAgentName.CREATE_PATCH.value, swe_agent.create_patch_node)
        workflow.add_node(PatcherAgentName.REVIEW_PATCH.value, qe_agent.review_patch_node)
        workflow.add_node(PatcherAgentName.BUILD_PATCH.value, qe_agent.build_patch_node)
        workflow.add_node(PatcherAgentName.BUILD_FAILURE_ANALYSIS.value, rootcause_agent.analyze_build_failure)
        workflow.add_node(PatcherAgentName.RUN_POV.value, qe_agent.run_pov_node)
        workflow.add_node(PatcherAgentName.RUN_TESTS.value, qe_agent.run_tests_node)

        workflow.set_entry_point(PatcherAgentName.ROOT_CAUSE_ANALYSIS.value)
        return workflow

    def run_patch_task(self) -> PatchOutput | None:
        """Run the patching task."""
        patch_team = self._init_patch_team()
        llm_callbacks = get_langfuse_callbacks()
        chain = patch_team.compile().with_config(
            RunnableConfig(
                callbacks=llm_callbacks,
                tags=["patch_team", self.challenge.name, self.input.task_id, self.input.submission_index],
                metadata={
                    "task_id": self.input.task_id,
                    "submission_index": self.input.submission_index,
                    "challenge_project_name": self.challenge.name,
                    "challenge_task_dir": self.challenge.task_dir,
                },
                recursion_limit=RECURSION_LIMIT,
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
                )

                output_state_dict: dict = chain.invoke(state)
                output_state = PatcherAgentState(**output_state_dict)
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
