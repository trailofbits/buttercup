import json
import logging
import operator
import random
import shutil
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, ClassVar

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from opentelemetry import trace
from pydantic import Field

from buttercup.common import stack_parsing
from buttercup.common.challenge_task import ChallengeTaskError
from buttercup.common.corpus import CrashDir
from buttercup.common.datastructures.msg_pb2 import BuildOutput, Crash
from buttercup.common.llm import get_langfuse_callbacks
from buttercup.common.project_yaml import Language
from buttercup.common.queues import ReliableQueue
from buttercup.common.reproduce_multiple import ReproduceMultiple, ReproduceResult
from buttercup.common.sarif_store import SARIFBroadcastDetail
from buttercup.common.stack_parsing import CrashSet
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.seed_gen.prompt.vuln_discovery import (
    C_CWE_LIST,
    COMMON_CWE_LIST,
    JAVA_CWE_LIST,
    VULN_C_POV_EXAMPLES,
    VULN_JAVA_POV_EXAMPLES,
)
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.task import BaseTaskState, Task
from buttercup.seed_gen.utils import extract_code

logger = logging.getLogger(__name__)


@dataclass
class PoVAttempt:
    analysis: str
    pov_functions: str

    def __str__(self) -> str:
        return f"""<test_case_attempt>
<analysis>
{self.analysis}
</analysis>
<test_cases>
{self.pov_functions}
</test_cases>
</test_case_attempt>
"""


class VulnBaseState(BaseTaskState):
    analysis: str = Field(description="The analysis of the vulnerability", default="")
    sarifs: list[SARIFBroadcastDetail] = Field(
        description="SARIF broadcasts for the task", default_factory=list
    )
    valid_pov_count: int = Field(description="The number of valid PoVs found", default=0)
    current_dir: Path = Field(
        description="Directory to store most recent seeds before they are tested"
    )
    pov_iteration: int = Field(description="Count of pov write iterations", default=0)
    pov_attempts: Annotated[list[PoVAttempt], operator.add] = Field(default_factory=list)

    def format_sarif_hints(self) -> str:
        """Format SARIF hints for prompts"""
        if not self.sarifs:
            return ""

        hints = []
        for sarif in self.sarifs:
            hints.append(json.dumps(sarif.sarif, indent=2))

        return "\n\n".join(hints)

    def format_pov_attempts(self) -> str:
        """Format PoV attempts for prompts"""
        return "\n\n".join(str(pov_attempt) for pov_attempt in self.pov_attempts)


@dataclass
class CrashSubmit:
    crash_queue: ReliableQueue[Crash]
    crash_set: CrashSet
    crash_dir: CrashDir
    max_pov_size: int


@dataclass
class VulnBaseTask(Task):
    reproduce_multiple: ReproduceMultiple
    sarifs: list[SARIFBroadcastDetail]
    TaskStateClass: ClassVar[type[BaseTaskState]]
    SARIF_PROBABILITY: ClassVar[float] = 0.5
    crash_submit: CrashSubmit | None = None

    MAX_POV_ITERATIONS: ClassVar[int] = 3
    MAX_CONTEXT_ITERATIONS: ClassVar[int]

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
        chain = prompt | self.llm | extract_code
        pov_funcs = chain.invoke(prompt_vars)
        return Command(update={"generated_functions": pov_funcs})

    def _exec_python_funcs_current(self, state: VulnBaseState) -> None:
        """Execute python functions"""
        logger.info("Executing python functions")
        sandbox_exec_funcs(state.generated_functions, state.current_dir)

    def _continue_pov_write(self, state: VulnBaseState) -> bool:
        """Determine whether to retry PoV writing"""
        return state.valid_pov_count == 0 and state.pov_iteration < self.MAX_POV_ITERATIONS

    def _test_povs(self, state: VulnBaseState) -> Command:
        """Test the PoVs"""
        # Note: due to reproduce_multiple, this node cannot be parallelized
        logger.info("Testing PoVs")
        new_valid_povs = 0
        for pov in state.current_dir.iterdir():
            final_name = f"iter{state.pov_iteration}_{pov.name}"  # avoid name conflicts
            final_path = state.output_dir / final_name
            shutil.move(pov, final_path)
            try:
                for build, result in self.reproduce_multiple.get_crashes(
                    final_path, self.harness_name
                ):
                    logger.info(
                        "Valid PoV found: (task_id: %s | package_name: %s | harness_name: %s | sanitizer: %s | delta_mode: %s | iter: %s)",  # noqa: E501
                        self.challenge_task.task_meta.task_id,
                        self.package_name,
                        self.harness_name,
                        build.sanitizer,
                        self.challenge_task.is_delta_mode(),
                        state.pov_iteration,
                    )
                    if self.crash_submit is not None:
                        self.submit_valid_pov(final_path, build, result)
                    new_valid_povs += 1
            except ChallengeTaskError as exc:
                logger.error(f"Error reproducing PoV {final_path}: {exc}")
        pov_attempt = PoVAttempt(analysis=state.analysis, pov_functions=state.generated_functions)
        return Command(
            update={
                "valid_pov_count": state.valid_pov_count + new_valid_povs,
                "pov_attempts": [pov_attempt],
                "analysis": "",
                "generated_functions": "",
                "pov_iteration": state.pov_iteration + 1,
            }
        )

    def submit_valid_pov(
        self,
        pov: Path,
        build: BuildOutput,
        result: ReproduceResult,
    ) -> None:
        if self.crash_submit is None:
            logger.error("Crash submission not configured")
            return
        if not result.did_crash():
            logger.error("Not submitting invalid PoV that did not crash: %s", pov)
            return

        file_size = pov.stat().st_size
        task_id = self.challenge_task.task_meta.task_id
        if file_size > self.crash_submit.max_pov_size:
            logger.warning(
                "Not submitting PoV (%s bytes) that exceeds max PoV size (%s bytes) for %s",
                file_size,
                self.crash_submit.max_pov_size,
                task_id,
            )
            return

        stacktrace = result.stacktrace()
        ctoken = stack_parsing.get_crash_token(stacktrace)
        dst = self.crash_submit.crash_dir.copy_file(pov, ctoken, build.sanitizer)
        if self.crash_submit.crash_set.add(
            self.package_name,
            self.harness_name,
            task_id,
            build.sanitizer,
            stacktrace,
        ):
            logger.info(
                "PoV already in crash set (task_id: %s | package_name: %s | harness_name: %s | sanitizer: %s | delta_mode: %s | crash_token: %s)",  # noqa: E501
                task_id,
                self.package_name,
                self.harness_name,
                build.sanitizer,
                self.challenge_task.is_delta_mode(),
                ctoken,
            )
            return
        logger.info(
            "Submitting PoV to crash queue (task_id: %s | package_name: %s | harness_name: %s | sanitizer: %s | delta_mode: %s | crash_token: %s)",  # noqa: E501
            task_id,
            self.package_name,
            self.harness_name,
            build.sanitizer,
            self.challenge_task.is_delta_mode(),
            ctoken,
        )

        crash = Crash(
            target=build,
            harness_name=self.harness_name,
            crash_input_path=dst,
            stacktrace=stacktrace,
            crash_token=ctoken,
        )
        self.crash_submit.crash_queue.push(crash)

        logger.debug("PoV stdout: %s", result.command_result.output)
        logger.debug("PoV stderr: %s", result.command_result.error)

    def _build_workflow(self) -> StateGraph:
        """Build the workflow for the VulnDiscovery task"""
        workflow = StateGraph(self.TaskStateClass)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)
        workflow.add_node("execute_python_funcs", self._exec_python_funcs_current)
        workflow.add_node("test_povs", self._test_povs)

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
        workflow.add_edge("write_pov", "execute_python_funcs")
        workflow.add_edge("execute_python_funcs", "test_povs")
        workflow.add_conditional_edges(
            "test_povs",
            self._continue_pov_write,
            {
                True: "analyze_bug",
                False: END,
            },
        )
        return workflow

    def recursion_limit(self) -> int:
        context_steps = 2
        pov_steps = 4
        return 1 + context_steps * self.MAX_CONTEXT_ITERATIONS + pov_steps * self.MAX_POV_ITERATIONS

    @abstractmethod
    def _init_state(self, out_dir: Path, current_dir: Path) -> BaseTaskState:
        """Set up State"""
        pass

    def do_task(self, out_dir: Path, current_dir: Path) -> None:
        """Do vuln-discovery task"""
        mode = "delta" if self.challenge_task.is_delta_mode() else "full"
        logger.info("Doing vuln-discovery for challenge %s (mode: %s)", self.package_name, mode)
        try:
            state = self._init_state(out_dir, current_dir)
            workflow = self._build_workflow()
            llm_callbacks = get_langfuse_callbacks()
            chain = workflow.compile().with_config(
                RunnableConfig(
                    tags=["vuln-discovery"],
                    callbacks=llm_callbacks,
                    recursion_limit=self.recursion_limit(),
                )
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
                chain.invoke(state)

        except Exception as err:
            logger.exception(
                "Failed vuln-discovery for challenge %s: %s", self.package_name, str(err)
            )

    def sample_sarifs(self) -> bool:
        """Sample SARIFs for the task"""
        if random.random() <= VulnBaseTask.SARIF_PROBABILITY:
            logger.info("Using %d SARIFs for challenge %s", len(self.sarifs), self.package_name)
            return self.sarifs
        return []

    def get_pov_examples(self) -> str:
        """Get PoV examples for the task"""
        if self.project_yaml.unified_language == Language.JAVA:
            return VULN_JAVA_POV_EXAMPLES
        else:
            return VULN_C_POV_EXAMPLES

    def get_vuln_files(self) -> str:
        if self.project_yaml.unified_language == Language.JAVA:
            return ".java"
        else:
            return ".c, .h, .cpp, or .hpp"

    def get_fuzzer_name(self) -> str:
        if self.project_yaml.unified_language == Language.JAVA:
            return "jazzer"
        else:
            return "libfuzzer"

    def get_cwe_list(self) -> str:
        if self.project_yaml.unified_language == Language.JAVA:
            return JAVA_CWE_LIST + "\n" + COMMON_CWE_LIST
        else:
            return C_CWE_LIST + "\n" + COMMON_CWE_LIST
