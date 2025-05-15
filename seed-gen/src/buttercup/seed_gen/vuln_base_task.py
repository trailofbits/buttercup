import json
import logging
import random
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from opentelemetry import trace
from pydantic import Field

from buttercup.common.llm import get_langfuse_callbacks
from buttercup.common.sarif_store import SARIFBroadcastDetail
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import BaseTaskState, Task
from buttercup.seed_gen.utils import extract_md

logger = logging.getLogger(__name__)


class VulnBaseState(BaseTaskState):
    analysis: str = Field(description="The analysis of the vulnerability", default="")
    sarifs: list[SARIFBroadcastDetail] = Field(
        description="SARIF broadcasts for the task", default_factory=list
    )

    def format_sarif_hints(self) -> str:
        """Format SARIF hints for prompts"""
        if not self.sarifs:
            return ""

        hints = []
        for sarif in self.sarifs:
            hints.append(json.dumps(sarif.sarif, indent=2))

        return "\n\n".join(hints)


@dataclass
class VulnBaseTask(Task):
    sarifs: list[SARIFBroadcastDetail]
    TaskStateClass: ClassVar[type[BaseTaskState]]
    SARIF_PROBABILITY: ClassVar[float] = 0.5

    @abstractmethod
    def _gather_context(self, state: BaseTaskState) -> Command:
        """Get context"""
        pass

    @abstractmethod
    def _analyze_bug(self, state: BaseTaskState) -> Command:
        """Get context"""
        pass

    def _analyze_bug_base(
        self,
        system_prompt: str,
        user_prompt: str,
        prompt_vars: dict[str, Any],
    ) -> Command:
        """Base method for analyzing a bug"""
        logger.info("Analyzing bug")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        analysis = chain.invoke(prompt_vars)
        return Command(update={"analysis": analysis})

    @abstractmethod
    def _write_pov(self, state: BaseTaskState) -> Command:
        """Write PoV functions for the vulnerability"""
        pass

    def _write_pov_base(
        self,
        system_prompt: str,
        user_prompt: str,
        prompt_vars: dict[str, Any],
    ) -> Command:
        logger.info("Writing PoV")
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        chain = prompt | self.llm | extract_md
        pov_funcs = chain.invoke(prompt_vars)
        return Command(update={"generated_functions": pov_funcs})

    def _build_workflow(self) -> StateGraph:
        """Build the workflow for the VulnDiscovery task"""
        workflow = StateGraph(self.TaskStateClass)

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

    @abstractmethod
    def _init_state(self) -> BaseTaskState:
        """Set up State"""
        pass

    def do_task(self, output_dir: Path) -> None:
        """Do vuln-discovery task"""
        mode = "delta" if self.challenge_task.is_delta_mode() else "full"
        logger.info("Doing vuln-discovery for challenge %s (mode: %s)", self.package_name, mode)
        try:
            state = self._init_state()
            workflow = self._build_workflow()
            llm_callbacks = get_langfuse_callbacks()
            chain = workflow.compile().with_config(
                RunnableConfig(tags=["vuln-discovery"], callbacks=llm_callbacks)
            )
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("seed_gen_vuln_discovery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.INPUT_GENERATION,
                    crs_action_name="seed_gen_vuln_discovery",
                    task_metadata=dict(self.challenge_task.task_meta.metadata),
                    extra_attributes={
                        "gen_ai.request.model": self.llm.model_name,
                    },
                )
                result = chain.invoke(state)

            logger.info("Executing PoV functions for challenge %s", self.package_name)
            sandbox_exec_funcs(result["generated_functions"], output_dir)

        except Exception as err:
            logger.error("Failed vuln-discovery for challenge %s: %s", self.package_name, str(err))

    def sample_sarifs(self) -> bool:
        """Sample SARIFs for the task"""
        if random.random() <= VulnBaseTask.SARIF_PROBABILITY:
            logger.info("Using %d SARIFs for challenge %s", len(self.sarifs), self.package_name)
            return self.sarifs
        return []
