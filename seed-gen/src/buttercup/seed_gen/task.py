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
    start_line: int
    end_line: int

    def __str__(self) -> str:
        return f"""<code_snippet>
<file_path>{self.file_path}</file_path>
<start_line>{self.start_line}</start_line>
<end_line>{self.end_line}</end_line>
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
    arguments: dict[str, str | list[str] | None]


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

    # Tool output limits
    MAX_TYPE_DEFS = 5
    MAX_CALLERS = 20
    MAX_GREP_OUTPUT_CHARS = 10000
    MAX_BATCH_CALLS = 10

    _harness_source_cache: ClassVar[dict[str, str]] = {}

    def __post_init__(self) -> None:
        fallbacks = [
            ButtercupLLM.CLAUDE_3_7_SONNET,
            ButtercupLLM.CLAUDE_3_5_SONNET,
            ButtercupLLM.OPENAI_GPT_4_1,
            ButtercupLLM.GEMINI_PRO,
        ]
        self.llm = Task.get_llm(ButtercupLLM.CLAUDE_4_SONNET, fallbacks)
        self.tools = [
            get_function_definition,
            get_type_definition,
            batch_tool,
            cat,
            get_callers,
        ]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    def get_debug_tools(self) -> list[BaseTool]:
        """Get tools for debug subagents, including grep and symbol lookup."""
        return [
            get_function_definition,
            get_type_definition,
            batch_tool,
            cat,
            get_callers,
            grep,
            lookup_symbols,
        ]

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
        return llm.with_fallbacks(fallbacks)  # type: ignore[no-any-return]

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
        function_paths: Sequence[Path | None],
        fuzzy: bool = False,
        fuzzy_threshold: int = 80,
    ) -> Function | None:
        """Gets function definition

        If there are multiple matches, returns the one with highest similarity.
        """
        for function_path in function_paths:
            # functions returned in descending order of similarity
            function_defs = self.codequery.get_functions(
                function_name,
                function_path,
                fuzzy=fuzzy,
                fuzzy_threshold=fuzzy_threshold,
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
            function_name,
            [None],
            fuzzy=fuzzy,
            fuzzy_threshold=fuzzy_threshold,
        )
        if function_def is not None:
            return function_def

        logger.warning(
            "No function definition found for %s (paths: %s)",
            function_name,
            function_paths,
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
            ],
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
        cmd: Command = Command(
            update={
                "messages": [res],
                "context_iteration": state.context_iteration + 1,
            },
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
        return type_defs  # type: ignore[no-any-return]

    @staticmethod
    def _get_function_definition(
        function_name: str,
        state: "BaseTaskState",
        tool_call_id: str,
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
                        ),
                    ],
                },
            )
        function_def = state.task.get_function_def(function_name, fuzzy=False)
        if function_def:
            results = [
                CodeSnippet(
                    file_path=function_def.file_path,
                    code=function_def.bodies[0].body,
                    start_line=function_def.bodies[0].start_line,
                    end_line=function_def.bodies[0].end_line,
                ),
            ]
            call_result = ToolCallResult(call=call, results=results)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Found definition for function {function_name}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                    "retrieved_context": {
                        call: call_result,
                    },
                },
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Could not find definition for function {function_name}",
                        tool_call_id=tool_call_id,
                    ),
                ],
            },
        )

    @staticmethod
    def _get_type_definition(
        type_name: str,
        state: "BaseTaskState",
        tool_call_id: str,
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
                        ),
                    ],
                },
            )
        type_defs = state.task._do_get_type_defs(type_name)
        if len(type_defs) > 0:
            results = [
                CodeSnippet(
                    file_path=type_def.file_path,
                    code=type_def.definition,
                    start_line=type_def.definition_line,
                    end_line=type_def.definition_line + len(type_def.definition.splitlines()),
                )
                for type_def in type_defs
            ]
            call_result = ToolCallResult(call=call, results=results)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Found {len(type_defs)} definitions for type {type_name}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                    "retrieved_context": {
                        call: call_result,
                    },
                },
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Could not find definition for type {type_name}",
                        tool_call_id=tool_call_id,
                    ),
                ],
            },
        )

    @staticmethod
    def _cat(
        file_path: str,
        state: "BaseTaskState",
        tool_call_id: str,
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
                        ),
                    ],
                },
            )
        cat_cmd_res = state.task.challenge_task.exec_docker_cmd(["cat", str(path)])
        if not cat_cmd_res.success:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Could not read contents of {path}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )
        cat_output = cat_cmd_res.output.decode("utf-8")
        results = [CodeSnippet(file_path=path, code=cat_output, start_line=1, end_line=len(cat_output.splitlines()))]
        call_result = ToolCallResult(call=call, results=results)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Retrieved contents of {path}",
                        tool_call_id=tool_call_id,
                    ),
                ],
                "retrieved_context": {
                    call: call_result,
                },
            },
        )

    @staticmethod
    def _grep(
        pattern: str,
        file_path: str | None,
        state: "BaseTaskState",
        tool_call_id: str,
    ) -> Command:
        """Implementation of grep tool"""
        logger.info("Tool call: grep for pattern %s in %s", pattern, file_path)
        path = Path(file_path) if file_path else None
        call = f'grep("{pattern}", "{file_path}")' if file_path else f'grep("{pattern}")'
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Grep results for pattern {pattern} already retrieved",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )
        args = ["grep", "-C", "5", "-nHrE", pattern]
        if path:
            args.append(str(path))
        grep_cmd_res = state.task.challenge_task.exec_docker_cmd(args)
        if not grep_cmd_res.success:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Could not search for pattern {pattern} in {path if path else 'project'}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )
        grep_output = grep_cmd_res.output.decode("utf-8")

        # Enforce a character limit to prevent overwhelming the LLM context
        truncated = False
        truncation_msg = ""

        if len(grep_output) > state.task.MAX_GREP_OUTPUT_CHARS:
            # Count total lines before truncation
            total_lines = len(grep_output.splitlines())

            # Truncate to first MAX_GREP_OUTPUT_CHARS characters
            grep_output = grep_output[: state.task.MAX_GREP_OUTPUT_CHARS]

            # Find the last complete line to avoid cutting mid-line
            last_newline = grep_output.rfind("\n")
            if last_newline > 0:
                grep_output = grep_output[:last_newline]

            shown_lines = len(grep_output.splitlines())
            truncated = True
            truncation_msg = f"""\n\n... OUTPUT TRUNCATED ...\n
Showing first {shown_lines} of {total_lines} lines (first {len(grep_output)}
of {len(grep_cmd_res.output)} characters)."""
            grep_output += truncation_msg

        # For grep results, we create a single CodeSnippet with the grep output
        # Since grep can match multiple files, we use a generic path or the provided path
        result_path = path if path else Path(".")
        results = [
            CodeSnippet(
                file_path=result_path,
                code=grep_output,
                start_line=1,
                end_line=len(grep_output.splitlines()) if grep_output else 1,
            )
        ]
        call_result = ToolCallResult(call=call, results=results)

        message = f"Found matches for pattern {pattern}"
        if truncated:
            message += f" (truncated - showing first ~{state.task.MAX_GREP_OUTPUT_CHARS} characters)"

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        message,
                        tool_call_id=tool_call_id,
                    ),
                ],
                "retrieved_context": {
                    call: call_result,
                },
            },
        )

    @staticmethod
    def _lookup_symbols(
        function_patterns: list[str],
        state: "BaseTaskState",
        tool_call_id: str,
    ) -> Command:
        """Look up function symbols in the binary using GDB"""
        # Limit to 20 patterns
        if len(function_patterns) > 20:
            function_patterns = function_patterns[:20]
            logger.warning("Limiting symbol lookup to first 20 patterns")

        logger.info("Tool call: lookup_symbols for patterns %s", function_patterns)
        call = f"lookup_symbols({function_patterns})"

        # Check cache to avoid redundant lookups
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Symbol lookup for {function_patterns} already retrieved",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

        # Get task and harness info
        task = state.task
        harness_name = state.harness.harness_name if hasattr(state, "harness") else task.harness_name

        # Get binary path - need to access reproduce_multiple
        # This is available in debug task states
        if not hasattr(state, "reproduce_multiple"):
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            "Symbol lookup tool not available in this task context (no reproduce_multiple in state)",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

        reproduce_multiple = state.reproduce_multiple

        try:
            with reproduce_multiple.open() as mult:
                # Select best build for the harness
                selected = mult.select_build_for_harness(harness_name)
                if selected is None:
                    return Command(
                        update={
                            "messages": [
                                ToolMessage(
                                    "Build cache not available for symbol lookup",
                                    tool_call_id=tool_call_id,
                                ),
                            ],
                        },
                    )

                cached_task = selected.task
                build_dir = cached_task.get_build_dir()
                if not build_dir or not build_dir.exists():
                    return Command(
                        update={
                            "messages": [
                                ToolMessage(
                                    "Build directory not found for symbol lookup",
                                    tool_call_id=tool_call_id,
                                ),
                            ],
                        },
                    )

                # Use the selected build's binary determination
                using_debug = selected.using_debug
                if using_debug:
                    binary_path = cached_task.get_debug_binary_path(harness_name)
                else:
                    binary_path = build_dir / harness_name
                    if not binary_path.exists():
                        return Command(
                            update={
                                "messages": [
                                    ToolMessage(
                                        f"Binary not found at {binary_path}",
                                        tool_call_id=tool_call_id,
                                    ),
                                ],
                            },
                        )

                # Mount directories for GDB
                project_name = build_dir.name
                out_dir = build_dir.parent
                mount_dirs = {out_dir: Path("/builds")}
                
                container_binary = f"/builds/{project_name}/{harness_name}"
                
                # Run GDB with commands passed directly via -ex flags
                # This avoids needing to mount a script file and dealing with docker-in-docker complexity
                gdb_cmd = ["gdb", "-batch"]

                # Add an info functions command for each pattern
                for pattern in function_patterns:
                    gdb_cmd.extend(["-ex", f"info functions {pattern}"])

                gdb_cmd.extend(["-ex", "quit", container_binary])

                result = cached_task.exec_docker_cmd(
                    gdb_cmd,
                    mount_dirs=mount_dirs,
                    container_image="gcr.io/oss-fuzz-base/base-runner-debug",
                )

                if not result.success:
                    error_msg = result.error.decode("utf-8", errors="ignore")[:500] if result.error else "Unknown error"
                    return Command(
                        update={
                            "messages": [
                                ToolMessage(
                                    f"GDB symbol lookup failed: {error_msg}",
                                    tool_call_id=tool_call_id,
                                ),
                            ],
                        },
                    )

                output = result.output.decode("utf-8", errors="ignore")
                logger.info(f"GDB output: {output}")

                # Parse the output to extract function symbols
                # Strip out GDB headers and just return the function definitions
                all_functions = []

                for line in output.splitlines():
                    # Skip GDB headers and metadata
                    if (
                        line.startswith("All functions matching")
                        or line.startswith("File ")
                        or line.startswith("Non-debugging symbols:")
                        or not line.strip()
                    ):
                        continue

                    # Extract lines that look like function definitions
                    # Format is typically: line_num:   return_type function_name(args);
                    if "(" in line:
                        func_line = line.strip()
                        all_functions.append(func_line)

                # Limit output to prevent overwhelming context
                MAX_SYMBOLS = 100
                total_found = len(all_functions)

                if all_functions:
                    # Show first N matches
                    funcs_to_show = all_functions[:MAX_SYMBOLS]
                    symbol_output = "\n".join(funcs_to_show)

                    if total_found > MAX_SYMBOLS:
                        symbol_output += f"""\n\n... {total_found - MAX_SYMBOLS} more matches not shown.
Refine your patterns for more specific results."""

                    message = f"Found {total_found} matching symbols for pattern(s): {', '.join(function_patterns)}"
                    if total_found > MAX_SYMBOLS:
                        message += f" (showing first {MAX_SYMBOLS})"
                else:
                    symbol_output = "No matching symbols found. The functions may not exist, or try different patterns."
                    message = "No matching symbols found"

                # Create a code snippet with the results
                results = [
                    CodeSnippet(
                        file_path=Path(f"symbols_{harness_name}"),
                        code=symbol_output,
                        start_line=1,
                        end_line=len(symbol_output.splitlines()),
                    )
                ]
                call_result = ToolCallResult(call=call, results=results)

                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                message,
                                tool_call_id=tool_call_id,
                            ),
                        ],
                        "retrieved_context": {call: call_result},
                    },
                )
        except Exception as e:
            logger.error(f"Error during symbol lookup: {e}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Symbol lookup failed with error: {str(e)}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

    def _do_get_callers(
        self,
        function_name: str,
    ) -> list[Function]:
        """Get the callers of a function"""
        callers = self.codequery.get_callers(function_name)
        if len(callers) > self.MAX_CALLERS:
            logger.info(
                "Found %d callers for %s, truncating to %d",
                len(callers),
                function_name,
                self.MAX_CALLERS,
            )
            callers = callers[: self.MAX_CALLERS]
        return callers  # type: ignore[no-any-return]

    @staticmethod
    def _get_callers(
        function_name: str,
        file_path: str,
        state: "BaseTaskState",
        tool_call_id: str,
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
                        ),
                    ],
                },
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
                        ),
                    ],
                },
            )
        callers = state.task._do_get_callers(function_name)

        code_snippets = [
            CodeSnippet(
                file_path=caller.file_path,
                code=caller.bodies[0].body,
                start_line=caller.bodies[0].start_line,
                end_line=caller.bodies[0].end_line,
            )
            for caller in callers
        ]
        call_result = ToolCallResult(call=call, results=code_snippets)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Found {len(code_snippets)} callers of function {function_name}", tool_call_id=tool_call_id
                    ),
                ],
                "retrieved_context": {call: call_result},
            },
        )


class BaseTaskState(BaseModel):
    """Base state for all tasks."""

    harness: HarnessInfo = Field(description="Harness info")
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)
    retrieved_context: Annotated[dict[str, ToolCallResult], operator.or_] = Field(
        description="Context retrieved by tools, keyed by tool call",
        default_factory=dict,
    )
    generated_functions: str = Field(description="The generated seed functions", default="")
    context_iteration: int = Field(description="Count of context retrieval iterations", default=0)
    context_iteration_again: int = Field(
        description="Count of context retrieval iterations for the second time", default=0
    )
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


@tool
def get_function_definition(
    function_name: str,
    *,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Retrieves the source code definition of a function from the codebase.

    Args:
        function_name: The name of the function to retrieve

    Notes:
    - If looking up a method in a Java program, only specify the method name.
      For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.
    - If looking up a method in a C++ program, only specify the method name.
      For example, if the method is `example::MyClass::myMethod`, only specify `myMethod`.

    """
    assert isinstance(state, BaseTaskState)
    return Task._get_function_definition(function_name, state, tool_call_id)


@tool
def get_type_definition(
    type_name: str,
    *,
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
    assert isinstance(state, BaseTaskState)
    return Task._get_type_definition(type_name, state, tool_call_id)


@tool
def lookup_symbols(
    function_patterns: list[str],
    *,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Look up function symbols in the binary using GDB's info functions command.

    This helps find the actual symbol names when functions might be mangled (C++)
    or modified by compiler instrumentation (coverage, sanitizers).

    Use this tool when you need to set breakpoints on functions but aren't sure of
    the exact symbol name in the binary. This is especially useful for:
    - C++ functions that may be name-mangled
    - Functions modified by sanitizer instrumentation
    - Functions with compiler-added prefixes/suffixes

    Args:
        function_patterns: List of function names or regex patterns to search for (max 20).
                          Examples: ["png_inflate", "decode_*", ".*process.*"]

    Returns:
        List of matching function symbols as they appear in the binary

    Examples:
        lookup_symbols(["png_inflate"])  # Find functions with "png_inflate" in name
        lookup_symbols(["^png_", "^decode_"])  # Multiple patterns
    """
    assert isinstance(state, BaseTaskState)
    return Task._lookup_symbols(function_patterns, state, tool_call_id)


@tool
def batch_tool(
    tool_calls: BatchToolCalls,
    *,
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

    """
    assert isinstance(state, BaseTaskState)
    logger.info("Tool call: batch_tool for %d calls", len(tool_calls.calls))
    results = []
    for call in tool_calls.calls[: state.task.MAX_BATCH_CALLS]:
        if call.tool_name == "get_function_definition" and "function_name" in call.arguments:
            function_name = call.arguments["function_name"]
            if isinstance(function_name, str):
                result = Task._get_function_definition(function_name, state, tool_call_id)
                results.append(result)
        elif call.tool_name == "get_type_definition" and "type_name" in call.arguments:
            type_name = call.arguments["type_name"]
            if isinstance(type_name, str):
                result = Task._get_type_definition(type_name, state, tool_call_id)
                results.append(result)
        elif call.tool_name == "cat" and "file_path" in call.arguments:
            file_path = call.arguments["file_path"]
            if isinstance(file_path, str):
                result = Task._cat(file_path, state, tool_call_id)
                results.append(result)
        elif call.tool_name == "get_callers" and "function_name" in call.arguments and "file_path" in call.arguments:
            function_name = call.arguments["function_name"]
            file_path = call.arguments["file_path"]
            if isinstance(function_name, str) and isinstance(file_path, str):
                result = Task._get_callers(function_name, file_path, state, tool_call_id)
                results.append(result)
        elif call.tool_name == "grep" and "pattern" in call.arguments:
            pattern = call.arguments["pattern"]
            if not isinstance(pattern, str):
                continue
            file_path = call.arguments.get("file_path")  # Optional, can be None
            if isinstance(file_path, str) or file_path is None:
                result = Task._grep(pattern, file_path, state, tool_call_id)
                results.append(result)
        elif call.tool_name == "lookup_symbols" and "function_patterns" in call.arguments:
            function_patterns = call.arguments["function_patterns"]
            # Ensure it's a list (might be a single string or already a list)
            if isinstance(function_patterns, str):
                function_patterns = [function_patterns]
            if isinstance(function_patterns, list):
                result = Task._lookup_symbols(function_patterns, state, tool_call_id)
                results.append(result)
        else:
            logger.warning("Invalid tool call: %s args: %s", call.tool_name, call.arguments)

    # Combine all results into a single Command
    combined_message = ""
    combined_context = {}
    for i, result in enumerate(results):
        if isinstance(result, Command):
            # TODO: We should check for dict type here
            if "messages" in result.update:  # type: ignore[operator]
                result_combined = "\n".join(
                    message.content
                    for message in result.update["messages"]  # type: ignore[index]
                )
                combined_message += f"Batched call {i}:\n{result_combined}\n"
            if "retrieved_context" in result.update:  # type: ignore[operator]
                combined_context.update(result.update["retrieved_context"])  # type: ignore[index]

    # Anthropic API expects 1 tool message per tool call ID
    return Command(
        update={
            "messages": [
                ToolMessage(
                    combined_message,
                    tool_call_id=tool_call_id,
                ),
            ],
            "retrieved_context": combined_context,
        },
    )


@tool
def cat(
    file_path: str,
    *,
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
    assert isinstance(state, BaseTaskState)
    return Task._cat(file_path, state, tool_call_id)


@tool
def get_callers(
    function_name: str,
    file_path: str,
    *,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the callers of a function.

    Args:
        function_name: The name of the function to get callers for
        file_path: The path to the file containing the function

    Notes:
        - If looking up a method in a Java program, only specify the method name.
          For example, if the method is `example.MyClass.myMethod`, only specify `myMethod`.
        - If looking up a method in a C++ program, only specify the method name.
          For example, if the method is `example::MyClass::myMethod`, only specify `myMethod`.
    """
    assert isinstance(state, BaseTaskState)
    return Task._get_callers(function_name, file_path, state, tool_call_id)


@tool
def grep(
    pattern: str,
    file_path: str | None = None,
    *,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Grep for a string and return a 5-line context around the match, together with line numbers.

    If no file_path is provided, search the entire project. Prefer using this tool over cat when
    you need to search for specific patterns.

    Args:
        pattern: The pattern to search for (regular expression)
        file_path: Optional path to a specific file or directory to search in

    Notes:
        - If no file_path is provided, the entire project will be searched
        - The search returns 5 lines of context around each match
        - Line numbers are included in the output
    """
    assert isinstance(state, BaseTaskState)
    return Task._grep(pattern, file_path, state, tool_call_id)
