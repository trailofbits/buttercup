import logging
from dataclasses import dataclass
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import Field

from buttercup.common.llm import get_langfuse_callbacks
from buttercup.seed_gen.prompts import (
    DIFF_ANALYSIS_SYSTEM_PROMPT,
    DIFF_ANALYSIS_USER_PROMPT,
    VULN_DISCOVERY_GET_CONTEXT_SYSTEM_PROMPT,
    VULN_DISCOVERY_GET_CONTEXT_USER_PROMPT,
    WRITE_POV_SYSTEM_PROMPT,
    WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import BaseTaskState, Task
from buttercup.seed_gen.utils import extract_md, get_diff_content

logger = logging.getLogger(__name__)


class VulnDiscoveryState(BaseTaskState):
    diff_content: str = Field(description="The content of the diff being analyzed")
    analysis: str = Field(description="The analysis of the vulnerability", default="")


@dataclass
class VulnDiscoveryTask(Task):
    VULN_DISCOVERY_MAX_POV_COUNT = 8
    MAX_TOOL_CALLS = 4
    MAX_CONTEXT_ITERATIONS = 2

    def _gather_context(self, state: VulnDiscoveryState) -> Command:
        """Gather context about the diff and harness"""
        logger.info("Gathering context")
        prompt_vars = {
            "diff": state.diff_content,
            "harness": state.harness,
            "retrieved_code": state.format_retrieved_context(),
            "max_calls": self.MAX_TOOL_CALLS,
        }
        res = self._get_context_base(
            VULN_DISCOVERY_GET_CONTEXT_SYSTEM_PROMPT,
            VULN_DISCOVERY_GET_CONTEXT_USER_PROMPT,
            state,
            prompt_vars,
        )
        return res

    def _analyze_bug(self, state: VulnDiscoveryState) -> Command:
        """Analyze the diff for vulnerabilities"""
        logger.info("Analyzing bug")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DIFF_ANALYSIS_SYSTEM_PROMPT),
                ("human", DIFF_ANALYSIS_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        analysis = chain.invoke(
            {
                "diff": state.diff_content,
                "harness": state.harness,
                "retrieved_code": state.format_retrieved_context(),
            }
        )
        return Command(update={"analysis": analysis})

    def _write_pov(self, state: VulnDiscoveryState) -> Command:
        """Write PoV functions for the vulnerability"""
        logger.info("Writing PoV")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", WRITE_POV_SYSTEM_PROMPT),
                ("human", WRITE_POV_USER_PROMPT),
            ]
        )
        chain = prompt | self.llm | extract_md
        pov_funcs = chain.invoke(
            {
                "analysis": state.analysis,
                "harness": state.harness,
                "diff": state.diff_content,
                "max_povs": self.VULN_DISCOVERY_MAX_POV_COUNT,
                "retrieved_code": state.format_retrieved_context(),
            }
        )
        return Command(update={"generated_functions": pov_funcs})

    def _build_workflow(self) -> StateGraph:
        """Build the workflow for the VulnDiscovery task"""
        workflow = StateGraph(VulnDiscoveryState)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)

        workflow.set_entry_point("gather_context")
        workflow.add_edge("gather_context", "tools")
        workflow.add_conditional_edges(
            "tools",
            self._continue_context_retrieval,
            {
                True: "gather_context",
                False: "analyze_bug",
            },
        )

        workflow.add_edge("analyze_bug", "write_pov")
        workflow.add_edge("write_pov", END)

        return workflow

    def do_task(self, output_dir: Path) -> None:
        """Do vuln-discovery task"""
        logger.info("Doing vuln-discovery for challenge %s", self.package_name)
        try:
            harness = self.get_harness_source()
            if harness is None:
                return

            diffs = self.challenge_task.get_diffs()
            diff_content = get_diff_content(diffs)
            if diff_content is None:
                logger.error("No diff found for challenge %s", self.package_name)
                return

            state = VulnDiscoveryState(
                harness=harness,
                diff_content=diff_content,
                task=self,
            )

            workflow = self._build_workflow()
            llm_callbacks = get_langfuse_callbacks()
            chain = workflow.compile().with_config(
                RunnableConfig(tags=["vuln-discovery"], callbacks=llm_callbacks)
            )
            result = chain.invoke(state)

            logger.info("Executing PoV functions for challenge %s", self.package_name)
            sandbox_exec_funcs(result["generated_functions"], output_dir)

        except Exception as err:
            logger.error("Failed vuln-discovery for challenge %s: %s", self.package_name, str(err))
