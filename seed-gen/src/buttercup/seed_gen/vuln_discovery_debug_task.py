"""Vuln Discovery task with integrated debug capabilities.

This task integrates DebugSubagent_interactive into the vulnerability discovery workflow.
When PoVs fail to crash, it uses GDB-based debugging to understand why and
incorporates those insights into the next iteration.
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import override

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import Field

from buttercup.seed_gen.debug_subagent_interactive import DebugSubagentInteractive
from buttercup.seed_gen.prompt.vuln_discovery import (
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
from buttercup.seed_gen.utils import get_diff_content
from buttercup.seed_gen.vuln_base_task import VulnBaseState, VulnBaseTask

logger = logging.getLogger(__name__)


class VulnDiscoveryDebugState(VulnBaseState):
    """Extended state with debug information"""

    diff_content: str = Field(description="The content of the diff being analyzed", default="")
    debug_insights: str = Field(
        description="Insights from GDB debugging about why PoVs are failing", default=""
    )
    should_debug: bool = Field(
        description="Whether we should debug failed PoVs in this iteration", default=False
    )


@dataclass
class VulnDiscoveryDebugTask(VulnBaseTask):
    """Vuln discovery task with integrated debugging.

    This task extends the base vulnerability discovery workflow by:
    1. Running GDB-based debugging when PoVs fail to crash
    2. Incorporating debug insights into the next analysis iteration
    3. Using the DebugSubagent_interactive to understand execution flow and state
    """

    TaskStateClass = VulnDiscoveryDebugState
    VULN_DISCOVERY_MAX_POV_COUNT = 5
    MAX_CONTEXT_ITERATIONS = 6
    DEBUG_AFTER_ITERATION = 1  # Start debugging after first failed iteration

    def __post_init__(self) -> None:
        super().__post_init__()
        # Initialize debug subagent with validation skipped (proactive debugging)
        self.debug_subagent_interactive = DebugSubagentInteractive(
            task=self, 
            reproduce_multiple=self.reproduce_multiple,
            skip_validation=True  # Skip validation for proactive debugging
        )

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

        # Append debug insights if available
        if state.debug_insights:
            system_prompt += f"""

## DEBUG INSIGHTS FROM PREVIOUS ITERATION

When analyzing the vulnerability, consider these insights from GDB debugging of failed PoVs:

{state.debug_insights}

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

        # Add debug insights to PoV writing if available
        if state.debug_insights:
            system_prompt += f"""

## DEBUG INSIGHTS

Previous PoVs were debugged with GDB. Here's what we learned:

{state.debug_insights}

When writing new PoVs:
1. Address the issues identified in debugging
2. Ensure the conditions needed for exploitation are met
3. Adjust input generation based on actual runtime behavior
"""

        res = self._write_pov_base(system_prompt, user_prompt, base_vars)
        return res

    def _debug_generated_pov(self, state: VulnDiscoveryDebugState) -> Command:
        """Debug generated PoV to understand execution flow before testing"""
        logger.info("Debugging generated PoV from iteration %d", state.pov_iteration)
        
        # Debug: log directory contents
        logger.debug("current_dir path: %s", state.current_dir)
        logger.debug("current_dir exists: %s", state.current_dir.exists())
        if state.current_dir.exists():
            all_files = list(state.current_dir.iterdir())
            logger.debug("current_dir contents (%d files): %s", len(all_files), [f.name for f in all_files])
        
        logger.debug("output_dir path: %s", state.output_dir)
        logger.debug("output_dir exists: %s", state.output_dir.exists())
        if state.output_dir.exists():
            all_output_files = list(state.output_dir.iterdir())
            logger.debug("output_dir contents (%d files): %s", len(all_output_files), [f.name for f in all_output_files])

        # Find the most recent PoV in current_dir (where they're written before being moved to output_dir)
        recent_povs = list(state.current_dir.glob("*.seed"))
        if not recent_povs:
            logger.warning("No PoVs found to debug in current_dir")
            return Command(update={"should_debug": False})

        # Debug the first PoV (could be extended to debug multiple)
        pov_path = recent_povs[0]
        logger.info(f"Proactively debugging PoV before testing: {pov_path}")

        # Create debug context from the analysis
        harness_info = f"Fuzzer: {state.harness.harness_name} in {state.harness.file_path}"
        logger.info(f"Harness info: {harness_info}")
        
        # Add more specific context if analysis is available
        analysis_section = f"\n{state.analysis}\n" if state.analysis.strip() else "\nNo detailed analysis available.\n"
        
        debug_context = f"""This PoV was just generated to exploit a potential vulnerability in the target program.

**Target Information:**
{harness_info}

**Vulnerability Analysis:**{analysis_section}
**Debugging Goals:**
Before testing whether this PoV crashes the program, analyze its execution to understand:

1. **Execution Path**: Is the vulnerable code path being executed?
2. **Input Processing**: How is the PoV input being parsed and processed?
3. **Exploitation Conditions**: Are the necessary conditions for exploitation being met?
4. **Program State**: What is the actual state of the program at critical points (buffer sizes, pointers, validation checks)?
5. **Vulnerability Trigger**: Is the vulnerability actually being triggered? If not, what's preventing it?
6. **Expected vs Actual**: Does the program behavior match our expectations from the analysis?

This proactive debugging will help us:
- Confirm the PoV is targeting the right code
- Identify why it might fail before running tests
- Gather insights to improve subsequent iterations
"""

        # Run debug subagent_interactive
        try:
            # Use a separate directory for debug output (not in output_dir which is for seed files)
            # Use UUID to create a unique identifier to avoid collisions
            debug_uuid = uuid.uuid4().hex[:8]
            debug_output_dir = state.current_dir.parent / "agentic_debug" / f"{debug_uuid}_iter{state.pov_iteration}"
            logger.info("Calling debug subagent with pov_path=%s, output_dir=%s", pov_path, debug_output_dir)
            debug_result = self.debug_subagent_interactive.debug(
                harness=state.harness,
                pov_input_path=pov_path,
                debug_context=debug_context,
                output_dir=debug_output_dir,
            )
            logger.info("Debug subagent_interactive returned: analysis_len=%d, debug_commands_len=%d, output_len=%d, reflection_len=%d, attempts=%d", 
                       len(debug_result.analysis), 
                       len(debug_result.debug_commands),
                       len(debug_result.debug_output),
                       len(debug_result.reflection),
                       len(debug_result.attempts))

            # Format debug insights - only include the summary/reflection
            # The calling agent doesn't need the script or raw output details
            debug_insights = f"""## Proactive Debug Session for iteration {state.pov_iteration}

**Debug Summary:**
{debug_result.reflection}

The PoV validation will now test if this actually crashes.
"""

            logger.info("Proactive debug session completed")

            return Command(
                update={
                    "debug_insights": state.debug_insights + "\n\n" + debug_insights,
                }
            )

        except Exception as e:
            logger.error(f"Error during proactive debugging: {e}")
            # Don't fail the whole workflow if debugging fails
            return Command(
                update={
                    "debug_insights": state.debug_insights
                    + f"\n\n## Debug Error\n\nFailed to debug PoV: {str(e)}",
                }
            )

    @override
    def _build_workflow(self) -> StateGraph:  # type: ignore[override]
        """Build workflow with proactive debugging before testing"""
        workflow = StateGraph(self.TaskStateClass)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)
        workflow.add_node("execute_python_funcs", self._exec_python_funcs_current)
        workflow.add_node("debug_pov", self._debug_generated_pov)  # Run BEFORE testing
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
        # After executing POV functions, debug them before testing
        workflow.add_edge("execute_python_funcs", "debug_pov")
        # After debugging, test the POVs
        workflow.add_edge("debug_pov", "test_povs")

        # After testing PoVs, decide whether to continue
        def should_continue_or_end(state: VulnDiscoveryDebugState) -> str:
            # If we found valid PoVs, we're done
            if state.valid_pov_count > 0:
                return "end"
            # If we've reached max iterations, we're done
            if state.pov_iteration >= self.MAX_POV_ITERATIONS:
                return "end"
            # Otherwise, retry with insights from debugging
            return "retry"

        workflow.add_conditional_edges(
            "test_povs",
            should_continue_or_end,
            {
                "retry": "analyze_bug",
                "end": END,
            },
        )

        return workflow

    def recursion_limit(self) -> int:
        context_steps = 2
        pov_steps = 4
        debug_steps = 1  # Add debug step
        return (
            1
            + context_steps * self.MAX_CONTEXT_ITERATIONS
            + (pov_steps + debug_steps) * self.MAX_POV_ITERATIONS
        )

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

