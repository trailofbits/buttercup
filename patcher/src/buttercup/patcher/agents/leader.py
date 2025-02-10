"""LLM-based Patcher Agent module"""

import logging
import os
from dataclasses import dataclass

import openai

# from challenge_project_api.snapshot import SnapshotChallenge
from langchain_core.runnables import RunnableConfig
from langgraph.constants import Send
from langgraph.graph import END, StateGraph
from buttercup.common.challenge_task import ChallengeTask
from buttercup.patcher.agents.common import PatcherAgentState, PatchOutput
from buttercup.patcher.agents.qe import QEAgent
from buttercup.patcher.agents.rootcause import RootCauseAgent
from buttercup.patcher.agents.swe import SWEAgent
from buttercup.patcher.utils import PatchInput
from buttercup.patcher.llm import get_langfuse_callbacks

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 200


@dataclass
class PatcherLeaderAgent:
    """LLM-based Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    # snapshot_challenge: SnapshotChallenge

    max_retries: int = int(os.getenv("TOB_PATCHER_MAX_PATCHES_PER_RUN", 15))
    max_review_retries: int = int(os.getenv("TOB_PATCHER_MAX_REVIEW_RETRIES", 3))

    def is_review_successful(self, state: PatcherAgentState) -> str:
        """Determines the next step in the LangGraph after reviewing a patch."""
        if (state.get("patch_review_tries") or 0) > self.max_review_retries:
            return "yes"

        return "yes" if state.get("patch_review") is None else "no"

    def after_build(self, state: PatcherAgentState) -> str:
        """Determine the next step after building a patch."""
        if (state.get("patch_tries") or 0) > self.max_retries:
            return END

        if state.get("build_succeeded", False):
            return "run_pov"

        return "build_failure_analysis"

    def is_pov_fixed(self, state: PatcherAgentState) -> str:
        """Determines the next step in the LangGraph after running a PoV."""
        if (state.get("patch_tries") or 0) > self.max_retries:
            return "end"

        return "yes" if state.get("pov_fixed", False) else "no"

    def is_tests_passed(self, state: PatcherAgentState) -> str:
        """Determines the next step in the LangGraph after running tests."""
        if (state.get("patch_tries") or 0) > self.max_retries:
            return "end"

        return "yes" if state.get("tests_passed", False) else "no"

    def filter_snippets(self, state: PatcherAgentState) -> list:
        """Filter the snippets."""

        return [
            Send(
                "filter_code_snippet",
                {
                    "code_snippet": vc,
                    "commit_analysis": state["commit_analysis"],
                    "context": state["context"],
                },
            )
            for vc in state["context"].get("vulnerable_functions", [])
        ]

    def _init_patch_team(self) -> StateGraph:
        rootcause_agent = RootCauseAgent(self.challenge)
        # swe_agent = SWEAgent(self.challenge, self.snapshot_challenge, self.input)
        swe_agent = SWEAgent(self.challenge, self.input)
        qe_agent = QEAgent(self.challenge, self.input)

        workflow = StateGraph(PatcherAgentState)
        workflow.add_node("commit_analysis_node", rootcause_agent.commit_analysis)
        workflow.add_node("second_commit_analysis_node", rootcause_agent.commit_analysis)
        workflow.add_node("filter_code_snippet", rootcause_agent.filter_code_snippet_node)
        workflow.add_node("root_cause_analysis", rootcause_agent.analyze_vulnerability)
        workflow.add_node("create_patch", swe_agent.create_patch_node)
        workflow.add_node("review_patch", qe_agent.review_patch_node)
        workflow.add_node("build_patch", qe_agent.build_patch_node)
        workflow.add_node("build_failure_analysis", rootcause_agent.analyze_build_failure)
        workflow.add_node("run_pov", qe_agent.run_pov_node)
        workflow.add_node("run_tests", qe_agent.run_tests_node)

        workflow.set_entry_point("commit_analysis_node")

        workflow.add_conditional_edges("commit_analysis_node", self.filter_snippets)
        workflow.add_edge("second_commit_analysis_node", "root_cause_analysis")
        workflow.add_edge("filter_code_snippet", "root_cause_analysis")
        workflow.add_edge("root_cause_analysis", "create_patch")
        workflow.add_edge("build_failure_analysis", "create_patch")
        workflow.add_edge("create_patch", "review_patch")
        workflow.add_conditional_edges(
            "review_patch",
            self.is_review_successful,
            {"yes": "build_patch", "no": "create_patch", "end": END},
        )
        workflow.add_conditional_edges("build_patch", self.after_build)
        workflow.add_conditional_edges(
            "run_pov",
            self.is_pov_fixed,
            {"yes": "run_tests", "no": "second_commit_analysis_node", "end": END},
        )
        workflow.add_conditional_edges(
            "run_tests",
            self.is_tests_passed,
            {"yes": END, "no": "create_patch", "end": END},
        )

        return workflow

    def run_patch_task(self) -> PatchOutput | None:
        """Run the patching task."""
        patch_team = self._init_patch_team()
        llm_callbacks = get_langfuse_callbacks()
        chain = patch_team.compile().with_config(
            RunnableConfig(
                callbacks=llm_callbacks,
                tags=["patch_team", self.challenge.name],
                recursion_limit=RECURSION_LIMIT,
            )
        )

        try:
            # TODO: langgraph should raise exceptions if something fails in the agents
            state: PatcherAgentState = chain.invoke({"context": self.input})
            if state.get("build_succeeded") and state.get("pov_fixed") and state.get("tests_passed"):
                return state["patches"][-1]
        except openai.OpenAIError as e:
            logger.error("OpenAI error: %s", e)
            return None
        except ValueError as e:
            logger.error("Could not generate a patch: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error during patch generation: %s", e)
            return None

        return None
