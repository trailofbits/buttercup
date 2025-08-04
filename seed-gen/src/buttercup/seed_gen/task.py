import logging
import operator
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, ClassVar

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.graph import add_messages
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm, get_langfuse_callbacks
from buttercup.common.project_yaml import ProjectYaml
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function, TypeDefinition
from buttercup.seed_gen.find_harness import HarnessInfo, get_harness_source
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.utils import extract_code

logger = logging.getLogger(__name__)


class TaskName(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


class CodeSnippet(BaseModel):
    """Code snippet"""

    file_path: Path
    code: str

    def __str__(self) -> str:
        return f"""<code_snippet>
<file_path>{self.file_path}</file_path>
<code>
{self.code}
</code>
</code_snippet>
"""


class ToolCallResult(BaseModel):
    """Result of calling a tool"""

    call: str
    results: list[CodeSnippet]

    def __str__(self) -> str:
        string = f"""<tool_result>
<tool_call>Retrieved with tool call: {self.call}</tool_call>"""
        for snippet in self.results:
            string += f"\n{snippet}"
        string += "\n</tool_result>"
        return string


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, str]


class BatchToolCalls(BaseModel):
    calls: list[ToolCall]


@dataclass
class Task:
    package_name: str
    harness_name: str
    challenge_task: ChallengeTask
    codequery: CodeQueryPersistent
    project_yaml: ProjectYaml
    redis: Redis | None = field(repr=False, compare=False)
    llm: BaseChatModel = field(init=False)
    tools: list[BaseTool] = field(init=False)

    MAX_CONTEXT_ITERATIONS: ClassVar[int]

    MAX_TYPE_DEFS = 5
    _harness_source_cache: ClassVar[dict[str, str]] = {}

    def __post_init__(self) -> None:
        fallbacks = [
            ButtercupLLM.CLAUDE_3_7_SONNET,
            ButtercupLLM.CLAUDE_3_5_SONNET,
        ]
        self.llm = Task.get_llm(ButtercupLLM.CLAUDE_4_SONNET, fallbacks)
        self.tools = [
            Task.get_function_definition,
            Task.get_type_definition,
            Task.batch_tool,
            Task.cat,
            Task.get_callers,
        ]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    @staticmethod
    def get_llm(llm: ButtercupLLM, fallback_llms: list[ButtercupLLM]) -> BaseChatModel:
        llm_callbacks = get_langfuse_callbacks()
        llm = create_default_llm(
            model_name=llm.value,
            callbacks=llm_callbacks,
        )
        fallbacks = []
        for fallback_llm in fallback_llms:
            fallback = create_default_llm(model_name=fallback_llm.value, callbacks=llm_callbacks)
            fallbacks.append(fallback)
        return llm.with_fallbacks(fallbacks)

    def get_harness_source(self) -> HarnessInfo | None:
        return get_harness_source(self.redis, self.codequery, self.harness_name)

    @staticmethod
    def clean_func_name(func_name: str) -> str:
        """Cleans function names from coverage info for codequery

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
        self,
        function_name: str,
        function_paths: list[Path],
        fuzzy: bool = False,
        fuzzy_threshold: int = 80,
    ) -> Function | None:
        """Gets function definition

        If there are multiple matches, returns the one with highest similarity.
        """
        for function_path in function_paths:
            # functions returned in descending order of similarity
            function_defs = self.codequery.get_functions(
                function_name, function_path, fuzzy=fuzzy, fuzzy_threshold=fuzzy_threshold
            )
            if len(function_defs) > 0:
                logger.info(
                    "Found function definition for %s in %s: %s (fuzzy=%s) (matches=%s)",
                    function_name,
                    function_path,
                    function_defs[0].name,
                    fuzzy,
                    len(function_defs),
                )
                return function_defs[0]

        logger.debug(
            "No function definition found for %s in paths: %s. (fuzzy=%s)",
            function_name,
            function_paths,
            fuzzy,
        )
        return None

    def get_function_def(
        self,
        function_name: str,
        function_paths: list[Path] | None = None,
        fuzzy: bool = True,
        fuzzy_threshold: int = 80,
    ) -> Function | None:
        """Get function definition from codequery

        Executes the following searches:
            - Exact match with paths
            - Match without paths (fuzzy if enabled)
        """
        logger.info("Getting function definition for %s (paths: %s)", function_name, function_paths)

        if function_paths:
            function_def = self._do_get_function_def(function_name, function_paths)
            if function_def is not None:
                return function_def

        function_def = self._do_get_function_def(
            function_name, [None], fuzzy=fuzzy, fuzzy_threshold=fuzzy_threshold
        )
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
        chain = prompt | self.llm | extract_code
        generated_functions = chain.invoke(prompt_vars)
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

    def _continue_context_retrieval(self, state: "BaseTaskState") -> bool:
        """Determine if we should continue the context retrieval iteration"""
        return state.context_iteration < self.MAX_CONTEXT_ITERATIONS

    def _execute_python_funcs(self, state: "BaseTaskState") -> None:
        """Execute python functions"""
        logger.info("Executing python functions")
        sandbox_exec_funcs(state.generated_functions, state.output_dir)

    def _do_get_type_defs(self, type_name: str) -> list[TypeDefinition]:
        """Get type definitions"""
        type_defs = self.codequery.get_types(type_name)

        if len(type_defs) > self.MAX_TYPE_DEFS:
            logger.info(
                "Got %d type defs for %s, truncating to %d",
                len(type_defs),
                type_name,
                self.MAX_TYPE_DEFS,
            )
            type_defs = type_defs[: self.MAX_TYPE_DEFS]
        else:
            logger.info("Got %d type defs for %s", len(type_defs), type_name)
        return type_defs

    @tool
    def get_function_definition(
        function_name: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Retrieves the source code definition of a function from the codebase.

        Args:
            function_name: The name of the function to retrieve

        Notes:
        - If looking up a method in a Java program, only specify the method name.
          For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.
        """
        return Task._get_function_definition(function_name, state, tool_call_id)

    def _get_function_definition(
        function_name: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Implementation of get_function_definition tool"""
        logger.info("Tool call: get_function_definition for %s", function_name)
        call = f'get_function_definition("{function_name}")'
        if call in state.retrieved_context:
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
        function_def = state.task.get_function_def(function_name, fuzzy=False)
        if function_def:
            results = [
                CodeSnippet(file_path=function_def.file_path, code=function_def.bodies[0].body)
            ]
            call_result = ToolCallResult(call=call, results=results)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Found definition for function {function_name}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "retrieved_context": {
                        call: call_result,
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

    @tool
    def get_type_definition(
        type_name: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Retrieves the source code definition of a type from the codebase.

        Args:
            type_name: The name of the type to retrieve

        Notes:
            - It will return multiple type definitions if there are multiple matches.
            - This tool cannot look up functions.
        """
        return Task._get_type_definition(type_name, state, tool_call_id)

    def _get_type_definition(
        type_name: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Implementation of get_type_definition tool"""
        logger.info("Tool call: get_type_definition for %s", type_name)
        call = f'get_type_definition("{type_name}")'
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Definition for {type_name} already retrieved",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )
        type_defs = state.task._do_get_type_defs(type_name)
        if len(type_defs) > 0:
            results = [
                CodeSnippet(file_path=type_def.file_path, code=type_def.definition)
                for type_def in type_defs
            ]
            call_result = ToolCallResult(call=call, results=results)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Found {len(type_defs)} definitions for type {type_name}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "retrieved_context": {
                        call: call_result,
                    },
                }
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Could not find definition for type {type_name}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    @tool
    def cat(
        file_path: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Read the contents of a file. Use this tool selectively as it could return a large amount of text.

        Args:
            file_path: The path to the file to read

        Notes:
            - Specify the absolute path to the file.
            - Prefer other tools when possible since this tool could return a large amount of text.
        """  # noqa: E501
        return Task._cat(file_path, state, tool_call_id)

    def _cat(
        file_path: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Implementation of cat tool"""
        logger.info("Tool call: cat for %s", file_path)
        path = Path(file_path)
        logger.info("Reading contents of %s", path)
        call = f'cat "{file_path}")'
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Contents of {file_path} already retrieved",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
        cat_cmd_res = state.task.challenge_task.exec_docker_cmd(["cat", str(path)])
        if not cat_cmd_res.success:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Could not read contents of {path}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
        cat_output = cat_cmd_res.output.decode("utf-8")
        results = [CodeSnippet(file_path=path, code=cat_output)]
        call_result = ToolCallResult(call=call, results=results)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Retrieved contents of {path}",
                        tool_call_id=tool_call_id,
                    )
                ],
                "retrieved_context": {
                    call: call_result,
                },
            }
        )

    def _do_get_callers(
        self,
        function_name: str,
    ) -> list[Function]:
        """Get the callers of a function"""
        max_callers = 20
        callers = self.codequery.get_callers(function_name)
        if len(callers) > max_callers:
            logger.info(
                "Found %d callers for %s, truncating to %d",
                len(callers),
                function_name,
                max_callers,
            )
            callers = callers[:max_callers]
        return callers

    @tool
    def get_callers(
        function_name: str,
        file_path: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Get the callers of a function.

        Args:
            function_name: The name of the function to get callers for
            file_path: The path to the file containing the function
        """
        return Task._get_callers(function_name, file_path, state, tool_call_id)

    def _get_callers(
        function_name: str,
        file_path: str,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        logger.info("Tool call: get_callers for %s in %s", function_name, file_path)
        call = f'get_callers("{function_name}", "{file_path}")'
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Callers for {function_name} in {file_path} already retrieved",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
        path = Path(file_path)
        function = state.task.get_function_def(function_name, function_paths=[path], fuzzy=False)
        if not function:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Could not look up function {function_name} in {path}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )
        callers = state.task._do_get_callers(function_name)

        code_snippets = [
            CodeSnippet(file_path=caller.file_path, code=caller.bodies[0].body)
            for caller in callers
        ]
        call_result = ToolCallResult(call=call, results=code_snippets)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Found {len(code_snippets)} callers of function {function_name}",
                        tool_call_id=tool_call_id,
                    )
                ],
                "retrieved_context": {
                    call: call_result,
                },
            }
        )

    @tool
    def batch_tool(
        tool_calls: BatchToolCalls,
        state: Annotated[BaseModel, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Execute multiple tool calls in a single invocation.

        Specify a list of tool calls to execute at once. This allows you to collect more context.

        Args:
            tool_calls: A list of tool calls to execute

        Notes:
            - The tool_calls argument must be a dictionary that exactly follows the tool_calls schema
            - Do not include '</invoke>' in your tool_calls argument.
        """  # noqa: E501
        logger.info("Tool call: batch_tool for %d calls", len(tool_calls.calls))
        max_calls_in_batch = 10
        results = []
        for call in tool_calls.calls[:max_calls_in_batch]:
            if call.tool_name == "get_function_definition" and "function_name" in call.arguments:
                function_name = call.arguments["function_name"]
                result = Task._get_function_definition(function_name, state, tool_call_id)
                results.append(result)
            elif call.tool_name == "get_type_definition" and "type_name" in call.arguments:
                type_name = call.arguments["type_name"]
                result = Task._get_type_definition(type_name, state, tool_call_id)
                results.append(result)
            elif call.tool_name == "cat" and "file_path" in call.arguments:
                file_path = call.arguments["file_path"]
                result = Task._cat(file_path, state, tool_call_id)
                results.append(result)
            elif (
                call.tool_name == "get_callers"
                and "function_name" in call.arguments
                and "file_path" in call.arguments
            ):
                function_name = call.arguments["function_name"]
                file_path = call.arguments["file_path"]
                result = Task._get_callers(function_name, file_path, state, tool_call_id)
                results.append(result)
            else:
                logger.warning("Invalid tool call: %s args: %s", call.tool_name, call.arguments)

        # Combine all results into a single Command
        combined_message = ""
        combined_context = {}
        for i, result in enumerate(results):
            if isinstance(result, Command):
                if "messages" in result.update:
                    result_combined = "\n".join(
                        message.content for message in result.update["messages"]
                    )
                    combined_message += f"Batched call {i}:\n{result_combined}\n"
                if "retrieved_context" in result.update:
                    combined_context.update(result.update["retrieved_context"])

        # Anthropic API expects 1 tool message per tool call ID
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        combined_message,
                        tool_call_id=tool_call_id,
                    )
                ],
                "retrieved_context": combined_context,
            }
        )


class BaseTaskState(BaseModel):
    """Base state for all tasks."""

    harness: HarnessInfo = Field(description="Harness info")
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)
    retrieved_context: Annotated[dict[str, ToolCallResult], operator.or_] = Field(
        description="Context retrieved by tools, keyed by tool call", default_factory=dict
    )
    generated_functions: str = Field(description="The generated seed functions", default="")
    context_iteration: int = Field(description="Count of context retrieval iterations", default=0)
    task: Task = Field(description="The task instance")
    output_dir: Path = Field(description="Directory to save generated seeds")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def format_retrieved_context(self) -> str:
        """Format retrieved context for prompt"""
        context = ""
        if self.retrieved_context:
            for call_result in self.retrieved_context.values():
                context += f"{call_result}\n"
        return context
