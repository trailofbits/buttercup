import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.graph import add_messages
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm, get_langfuse_callbacks
from buttercup.program_model.api import Graph
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function
from buttercup.seed_gen.find_harness import get_harness_source_candidates
from buttercup.seed_gen.utils import extract_md

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


@dataclass
class Task:
    package_name: str
    harness_name: str
    challenge_task: ChallengeTask
    codequery: CodeQueryPersistent
    llm: BaseChatModel | None = None
    program_model: Graph = field(init=False)
    tools: list[BaseTool] = field(init=False)

    def __post_init__(self) -> None:
        if self.llm is None:
            self.llm = self.get_default_llm()
        self.program_model = Graph()
        self.tools = [Task.get_function_definition]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

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
            function_defs = self.codequery.get_functions(function_name, function_path)
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

    def _generate_python_funcs_base(
        self,
        system_prompt: str,
        user_prompt: str,
        prompt_vars: dict[str, Any],
    ) -> str:
        """Base method for generating python seed functions that can be used by different tasks"""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        chain = prompt | self.llm | extract_md
        generated_functions = ""
        try:
            generated_functions = chain.invoke(prompt_vars)
        except Exception as e:
            logger.error("Error generating python functions: %s", str(e))
        return generated_functions

    def _get_context_base(
        self,
        system_prompt: str,
        user_prompt: str,
        state: "BaseTaskState",
        prompt_vars: dict[str, Any],
    ) -> Command:
        """Base method for getting context that can be used by different tasks"""

        prompt = [
            ("system", system_prompt),
            ("human", user_prompt.format(**prompt_vars)),
        ]
        res = self.llm_with_tools.invoke([*prompt, *state.messages])
        cmd = Command(
            update={
                "messages": [res],
                "context_iteration": state.context_iteration + 1,
            }
        )
        return cmd

    @tool
    def get_function_definition(
        function_name: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Retrieves the source code definition of a function from the codebase."""
        context_key = f"get_function_definition: {function_name}"
        if context_key in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Definition for {function_name} already retrieved",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )
        function_def = state.task._do_get_function_def(function_name, [None])
        if function_def:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Found definition for function {function_name}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "retrieved_context": {
                        **state.retrieved_context,
                        context_key: function_def.bodies[0].body,
                    },
                }
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Could not find definition for function {function_name}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )


class BaseTaskState(BaseModel):
    """Base state for all tasks."""

    harness: str = Field(description="Harness code")
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)
    retrieved_context: dict[str, str] = Field(
        description="Context retrieved by tools, keyed by tool call", default_factory=dict
    )
    generated_functions: str = Field(description="The generated seed functions", default="")
    context_iteration: int = Field(description="Count of context retrieval iterations", default=0)
    task: Task = Field(description="The task instance")

    def format_retrieved_context(self) -> str:
        """Format retrieved context for prompt"""
        context = ""
        if self.retrieved_context:
            for key, content in self.retrieved_context.items():
                context += f"\n--- Retrieved with {key} ---\n{content}\n"
        return context
