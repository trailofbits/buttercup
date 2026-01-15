"""Vuln Discovery task with integrated debug capabilities.

This task integrates DebugSubagentUnified into the vulnerability discovery workflow.
When PoVs fail to crash (after testing), it uses GDB-based debugging to understand why
and incorporates those insights into the next iteration.
"""

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, override

from langchain_core.messages import ToolMessage
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.types import Command
from pydantic import BaseModel, Field

from buttercup.seed_gen.debug_subagent_unified import DebugSubagentUnified
from buttercup.seed_gen.prompt.vuln_discovery import (
    VULN_DEBUG_FAILED_POVS_SYSTEM_PROMPT,
    VULN_DEBUG_FAILED_POVS_USER_PROMPT,
    VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT,
    VULN_DELTA_ANALYZE_BUG_USER_PROMPT,
    VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT,
    VULN_DELTA_GET_CONTEXT_USER_PROMPT,
    VULN_DELTA_WRITE_POV_SYSTEM_PROMPT,
    VULN_DELTA_WRITE_POV_USER_PROMPT,
    VULN_FULL_ANALYZE_BUG_SYSTEM_PROMPT,
    VULN_FULL_ANALYZE_BUG_USER_PROMPT,
    VULN_FULL_GET_CONTEXT_SYSTEM_PROMPT,
    VULN_FULL_GET_CONTEXT_USER_PROMPT,
    VULN_FULL_WRITE_POV_SYSTEM_PROMPT,
    VULN_FULL_WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.task import BaseTaskState, CodeSnippet, ToolCallResult
from buttercup.seed_gen.utils import get_diff_content
from buttercup.seed_gen.vuln_base_task import VulnBaseState, VulnBaseTask

logger = logging.getLogger(__name__)


class VulnDiscoveryDebugState(VulnBaseState):
    """Extended state with debug information"""

    diff_content: str = Field(description="The content of the diff being analyzed", default="")
    debug_insights: str = Field(description="Insights from GDB debugging about why PoVs are failing", default="")
    should_debug: bool = Field(description="Whether we should debug failed PoVs in this iteration", default=False)


@dataclass
class VulnDiscoveryDebugTask(VulnBaseTask):
    """Vuln discovery task with integrated debugging.

    This task extends the base vulnerability discovery workflow by:
    1. Testing PoVs first (as normal)
    2. Running GDB-based debugging only when PoVs fail to crash
    3. Incorporating debug insights into the next analysis iteration
    4. Using DebugSubagentUnified to understand why PoVs failed
    """

    TaskStateClass = VulnDiscoveryDebugState
    VULN_DISCOVERY_MAX_POV_COUNT = 5
    MAX_CONTEXT_ITERATIONS = 6
    DEBUG_AFTER_ITERATION = 1  # Start debugging after first failed iteration

    def __post_init__(self) -> None:
        super().__post_init__()
        # Initialize debug subagent - validation will be skipped since we test PoVs first
        self.debug_subagent_unified = DebugSubagentUnified(
            task=self,
            reproduce_multiple=self.reproduce_multiple,
            mode="hybrid",
        )
        # Create the debug_pov tool for this task
        self.debug_pov_tool = self._create_debug_pov_tool()
        self.debug_pov_tools = [self.debug_pov_tool]

    @override
    def _gather_context(self, state: VulnDiscoveryDebugState) -> Command:  # type: ignore[override]
        """Gather context about the diff and harness"""
        logger.info("Gathering context")
        # Determine if we're in delta mode by checking if diff_content exists
        is_delta = bool(state.diff_content)

        if is_delta:
            prompt_vars = {
                "diff": state.diff_content,
                "harness": str(state.harness),
                "retrieved_context": state.format_retrieved_context(),
                "sarif_hints": state.format_sarif_hints(),
                "vuln_files": self.get_vuln_files(),
                "fuzzer_name": self.get_fuzzer_name(),
                "cwe_list": self.get_cwe_list(),
            }
            res = self._get_context_base(
                VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT,
                VULN_DELTA_GET_CONTEXT_USER_PROMPT,
                state,
                prompt_vars,
            )
        else:
            prompt_vars = {
                "harness": str(state.harness),
                "retrieved_context": state.format_retrieved_context(),
                "sarif_hints": state.format_sarif_hints(),
                "vuln_files": self.get_vuln_files(),
                "fuzzer_name": self.get_fuzzer_name(),
                "cwe_list": self.get_cwe_list(),
            }
            res = self._get_context_base(
                VULN_FULL_GET_CONTEXT_SYSTEM_PROMPT,
                VULN_FULL_GET_CONTEXT_USER_PROMPT,
                state,
                prompt_vars,
            )
        return res

    @override
    def _analyze_bug(self, state: VulnDiscoveryDebugState) -> Command:  # type: ignore[override]
        """Analyze the diff for vulnerabilities, incorporating debug insights"""
        logger.info("Analyzing bug (with debug insights: %s)", bool(state.debug_insights))

        is_delta = bool(state.diff_content)

        base_vars = {
            "harness": str(state.harness),
            "retrieved_context": state.format_retrieved_context(),
            "sarif_hints": state.format_sarif_hints(),
            "vuln_files": self.get_vuln_files(),
            "fuzzer_name": self.get_fuzzer_name(),
            "cwe_list": self.get_cwe_list(),
            "previous_attempts": state.format_pov_attempts(),
        }

        if is_delta:
            base_vars["diff"] = state.diff_content
            system_prompt = VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT
            user_prompt = VULN_DELTA_ANALYZE_BUG_USER_PROMPT
        else:
            system_prompt = VULN_FULL_ANALYZE_BUG_SYSTEM_PROMPT
            user_prompt = VULN_FULL_ANALYZE_BUG_USER_PROMPT

        # Append debug insights if available (from retrieved_context, like other tools)
        debug_insights = self._format_debug_insights(state)
        if debug_insights:
            system_prompt += f"""

## DEBUG INSIGHTS FROM PREVIOUS ITERATION

When analyzing the vulnerability, consider these insights from GDB debugging of failed PoVs:

{debug_insights}

Use these insights to:
1. Understand why previous PoVs didn't crash
2. Identify what conditions are needed for exploitation
3. Adjust your analysis to account for actual runtime behavior
"""

        res = self._analyze_bug_base(system_prompt, user_prompt, base_vars)
        return res

    @override
    def _write_pov(self, state: VulnDiscoveryDebugState) -> Command:  # type: ignore[override]
        """Write PoV functions for the vulnerability"""
        logger.info("Writing PoV")

        is_delta = bool(state.diff_content)

        base_vars = {
            "analysis": state.analysis,
            "harness": str(state.harness),
            "max_povs": self.VULN_DISCOVERY_MAX_POV_COUNT,
            "retrieved_context": state.format_retrieved_context(),
            "pov_examples": self.get_pov_examples(),
            "fuzzer_name": self.get_fuzzer_name(),
            "previous_attempts": state.format_pov_attempts(),
        }

        if is_delta:
            base_vars["diff"] = state.diff_content
            system_prompt = VULN_DELTA_WRITE_POV_SYSTEM_PROMPT
            user_prompt = VULN_DELTA_WRITE_POV_USER_PROMPT
        else:
            system_prompt = VULN_FULL_WRITE_POV_SYSTEM_PROMPT
            user_prompt = VULN_FULL_WRITE_POV_USER_PROMPT

        # Add debug insights to PoV writing if available (from retrieved_context)
        debug_insights = self._format_debug_insights(state)
        if debug_insights:
            system_prompt += f"""

## DEBUG INSIGHTS

Previous PoVs were debugged with GDB. Here's what we learned:

{debug_insights}

When writing new PoVs:
1. Address the issues identified in debugging
2. Ensure the conditions needed for exploitation are met
3. Adjust input generation based on actual runtime behavior
"""

        res = self._write_pov_base(system_prompt, user_prompt, base_vars)
        return res

    def _debug_failed_povs(self, state: VulnDiscoveryDebugState) -> Command:
        """Debug failed PoVs after testing to understand why they didn't crash. Should make a tool call"""
        logger.info("Debugging failed PoVs")

        # Get the most recent PoV functions code (what was just tested)
        latest_pov_functions = ""
        if state.pov_attempts:
            latest_pov_functions = state.pov_attempts[-1].pov_functions

        # Prepare prompt variables
        prompt_vars = {
            "harness": str(state.harness),
            "previous_attempts": state.format_pov_attempts(),
            "analysis": state.analysis,
            "latest_pov_functions": latest_pov_functions,
        }

        # Create prompt and call LLM with debug_pov tool
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", VULN_DEBUG_FAILED_POVS_SYSTEM_PROMPT),
                ("human", VULN_DEBUG_FAILED_POVS_USER_PROMPT),
            ],
        )

        # Bind the debug_pov tool to the LLM
        llm_with_debug_tool = self.llm.bind_tools(self.debug_pov_tools)
        chain = prompt | llm_with_debug_tool

        # Invoke with prompt variables and existing messages for context
        response = chain.invoke(prompt_vars)

        # Return command that will trigger the tool call
        return Command(
            update={
                "messages": [response],
            },
        )

    def _format_debug_insights(self, state: VulnDiscoveryDebugState) -> str:
        """Format debug insights from retrieved_context, similar to format_retrieved_context"""
        debug_insights = ""
        for call, call_result in state.retrieved_context.items():
            if "debug_pov" in call.lower():
                # Format the debug result
                debug_insights += f"{call_result}\n"
        return debug_insights

    def _create_debug_pov_tool(self) -> BaseTool:
        """Create the debug_pov tool for this task instance"""
        task_instance = self

        @tool
        def debug_pov(
            testcase_name: str,
            debug_context: str,
            output_dir: str | None = None,
            current_dir: str | None = None,
            *,
            state: Annotated[BaseModel, InjectedState],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ) -> Command:
            """Debug a PoV (Proof of Vulnerability) input using GDB-based debugging.

            This tool runs the unified debug agent to analyze why a PoV input may have failed
            to crash the program. It provides detailed insights about execution paths, program
            state, and exploitation conditions.

            Args:
                testcase_name: Name of the testcase to debug (e.g., "pov_1"). The tool will search
                               through output_dir to find the most recent .seed file containing this name.
                debug_context: Contextual information about what to test and verify during debugging
                output_dir: Optional directory to write debug results to (defaults to agentic_debug subdirectory)
                current_dir: Optional directory for temporary files (defaults to a temporary directory)

            Notes:
                - This tool is only available for tasks that have reproduce_multiple (VulnBaseTask)
                - The tool searches state.output_dir for .seed files containing the testcase_name
                - If multiple matches are found, the most recently modified file is selected
                - The debug agent will analyze the PoV execution and provide insights about why it may have failed
                - Results include analysis, debug commands executed, debug output, and reflection
            """
            assert isinstance(state, BaseTaskState)
            return task_instance._debug_pov_impl(
                testcase_name, debug_context, output_dir, current_dir, state, tool_call_id
            )

        return debug_pov

    def _debug_pov_impl(
        self,
        testcase_name: str,
        debug_context: str,
        output_dir: str | None,
        current_dir: str | None,
        state: BaseTaskState,
        tool_call_id: str,
    ) -> Command:
        """Implementation of debug_pov tool - calls unified debug agent"""
        logger.info("Tool call: debug_pov for testcase %s", testcase_name)

        call = f'debug_pov("{testcase_name}", "{debug_context}")'

        # Check cache to avoid redundant debug calls
        if call in state.retrieved_context:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Debug results for {testcase_name} already retrieved",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

        # Get harness from state
        harness = state.harness

        # Search for the most recent PoV file matching the testcase name in output_dir
        if not state.output_dir.exists():
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Output directory does not exist: {state.output_dir}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

        # Find all .seed files in output_dir that contain the testcase name
        matching_files = [f for f in state.output_dir.glob("*.seed") if testcase_name in f.name]

        if not matching_files:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"No PoV files found matching testcase name '{testcase_name}' in {state.output_dir}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

        # Sort by modification time (newest first) and pick the most recent
        pov_path = sorted(matching_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]

        logger.info("Found matching PoV file: %s (mtime: %.2f)", pov_path.name, pov_path.stat().st_mtime)

        # Set up output and current directories
        if output_dir:
            debug_output_dir = Path(output_dir)
        else:
            # Use a default location relative to state.output_dir
            debug_uuid = uuid.uuid4().hex[:8]
            debug_output_dir = state.output_dir.parent / "agentic_debug" / f"{debug_uuid}_tool_debug"

        if current_dir:
            debug_current_dir = Path(current_dir)
        elif hasattr(state, "current_dir") and state.current_dir:
            # Use state's current_dir if available
            debug_current_dir = state.current_dir
        else:
            # Use a temporary directory
            debug_current_dir = Path(tempfile.mkdtemp())

        try:
            # Call the debug agent (we already have it initialized in __post_init__)
            debug_result = self.debug_subagent_unified.debug(
                harness=harness,
                pov_input_path=pov_path,
                debug_context=debug_context,
                output_dir=debug_output_dir,
                current_dir=debug_current_dir,
            )

            # Format the debug results
            debug_output = f"""## Debug Session Results
**Reflection:**
{debug_result.reflection}
"""

            # Create a code snippet with the results
            results = [
                CodeSnippet(
                    file_path=Path(f"debug_{pov_path.name}"),
                    code=debug_output,
                    start_line=1,
                    end_line=len(debug_output.splitlines()),
                )
            ]
            call_result = ToolCallResult(call=call, results=results)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Debug session completed for {pov_path.name}. PoV valid: {debug_result.pov_valid}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                    "retrieved_context": {call: call_result},
                },
            )
        except Exception as e:
            logger.error(f"Error during debug: {e}", exc_info=True)
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Debug failed with error: {str(e)}",
                            tool_call_id=tool_call_id,
                        ),
                    ],
                },
            )

    @override
    def _build_workflow(self) -> StateGraph:
        """Build workflow with debugging only when PoVs fail"""
        workflow = StateGraph(self.TaskStateClass)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)
        workflow.add_node("execute_python_funcs", self._exec_python_funcs_current)
        workflow.add_node("test_povs", self._test_povs)
        workflow.add_node("debug_failed_povs", self._debug_failed_povs)
        workflow.add_node("debug_povs", ToolNode(self.debug_pov_tools, name="debug_povs"))

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

        # After testing PoVs, decide whether to debug (if failed) or end/retry
        def after_test_povs(state: VulnDiscoveryDebugState) -> str:
            # If we found valid PoVs, we're done
            if state.valid_pov_count > 0:
                return "end"
            # If we've reached max iterations, we're done
            if state.pov_iteration >= self.MAX_POV_ITERATIONS:
                return "end"
            # Otherwise, debug the failed PoVs before retrying
            return "debug"

        workflow.add_conditional_edges(
            "test_povs",
            after_test_povs,
            {
                "debug": "debug_failed_povs",
                "end": END,
            },
        )
        workflow.add_edge("debug_failed_povs", "debug_povs")
        workflow.add_edge("debug_povs", "analyze_bug")

        return workflow

    def recursion_limit(self) -> int:
        context_steps = 2
        pov_steps = 4
        debug_steps = 1  # Debug step only runs when PoVs fail
        # Debug only runs when valid_pov_count == 0, so it's conditional
        # We'll include it in the limit to be safe
        return 1 + context_steps * self.MAX_CONTEXT_ITERATIONS + (pov_steps + debug_steps) * self.MAX_POV_ITERATIONS

    @override
    def _init_state(self, out_dir: Path, current_dir: Path) -> VulnDiscoveryDebugState:
        """Initialize state - works for both delta and full mode"""
        harness = self.get_harness_source()
        if harness is None:
            raise ValueError("No harness found for challenge %s", self.package_name)

        # Check if we're in delta mode
        is_delta = self.challenge_task.is_delta_mode()
        diff_content = ""

        if is_delta:
            diffs = self.challenge_task.get_diffs()
            diff_content = get_diff_content(diffs) or ""
            if not diff_content:
                logger.warning("No diff found for challenge %s in delta mode", self.package_name)

        state = VulnDiscoveryDebugState(
            harness=harness,
            diff_content=diff_content,
            task=self,
            sarifs=self.sample_sarifs(),
            output_dir=out_dir,
            current_dir=current_dir,
        )
        return state
