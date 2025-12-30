"""Vuln Discovery task with integrated debug capabilities.

This task integrates DebugSubagent into the vulnerability discovery workflow.
When PoVs fail to crash, it uses GDB-based debugging to understand why and
incorporates those insights into the next iteration.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import override

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import Field

from buttercup.seed_gen.debug_subagent import DebugSubagent
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
    3. Using the DebugSubagent to understand execution flow and state
    """

    TaskStateClass = VulnDiscoveryDebugState
    VULN_DISCOVERY_MAX_POV_COUNT = 5
    MAX_CONTEXT_ITERATIONS = 6
    DEBUG_AFTER_ITERATION = 1  # Start debugging after first failed iteration

    def __post_init__(self) -> None:
        super().__post_init__()
        # Initialize debug subagent
        self.debug_subagent = DebugSubagent(task=self, reproduce_multiple=self.reproduce_multiple)

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

    def _debug_failed_povs(self, state: VulnDiscoveryDebugState) -> Command:
        """Debug failed PoVs using DebugSubagent to understand why they didn't crash"""
        logger.info("Debugging failed PoVs from iteration %d", state.pov_iteration - 1)

        # Find the most recent failed PoV
        recent_povs = list(state.output_dir.glob(f"iter{state.pov_iteration - 1}_*.seed"))
        if not recent_povs:
            logger.warning("No PoVs found to debug")
            return Command(update={"should_debug": False})

        # Debug the first PoV (could be extended to debug multiple)
        pov_path = recent_povs[0]
        logger.info(f"Debugging PoV: {pov_path}")

        # Create debug context from the analysis
        harness_info = f"Fuzzer: {state.harness.harness_name} in {state.harness.file_path}"
        
        # Add more specific context if analysis is available
        analysis_section = f"\n{state.analysis}\n" if state.analysis.strip() else "\nNo detailed analysis available.\n"
        
        debug_context = f"""This PoV was generated to test a potential vulnerability in the target program.

**Target Information:**
{harness_info}

**Analysis Context:**{analysis_section}
**Problem:**
The PoV is expected to exploit the vulnerability, but it did not cause a crash.

**Investigation Goals:**
1. Is the vulnerable code path being executed?
2. Are the necessary conditions for exploitation being met?
3. What is the actual state of the program when processing this input?
4. Why didn't the expected crash occur?
5. Are there any validation checks or sanitization preventing exploitation?
6. Are memory allocations failing or being bounded in unexpected ways?
"""

        # Run debug subagent
        try:
            debug_result = self.debug_subagent.debug(
                harness=state.harness,
                pov_input_path=pov_path,
                debug_context=debug_context,
                output_dir=state.output_dir / f"debug_iter{state.pov_iteration - 1}",
            )

            # Format debug insights
            debug_insights = f"""## Debug Session for iteration {state.pov_iteration - 1}

**PoV Validity:** {"Valid (causes crash)" if debug_result.pov_valid else "Invalid (no crash)"}

**Analysis:**
{debug_result.analysis}

**GDB Script Used:**
```gdb
{debug_result.debug_script}
```

**GDB Output:**
```
{debug_result.debug_output[:1000]}  # Limit to first 1000 chars
```

**Key Findings:**
- The PoV {"DOES" if debug_result.pov_valid else "DOES NOT"} cause a crash
- Review the GDB output above to understand execution flow
- Consider adjusting the exploit strategy based on these findings
"""

            logger.info("Debug session completed: pov_valid=%s", debug_result.pov_valid)

            return Command(
                update={
                    "debug_insights": state.debug_insights + "\n\n" + debug_insights,
                    "should_debug": False,
                }
            )

        except Exception as e:
            logger.error(f"Error during debugging: {e}")
            return Command(
                update={
                    "debug_insights": state.debug_insights
                    + f"\n\n## Debug Error\n\nFailed to debug PoV: {str(e)}",
                    "should_debug": False,
                }
            )

    @override
    def _build_workflow(self) -> StateGraph:  # type: ignore[override]
        """Build workflow with integrated debugging"""
        workflow = StateGraph(self.TaskStateClass)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)
        workflow.add_node("execute_python_funcs", self._exec_python_funcs_current)
        workflow.add_node("test_povs", self._test_povs)
        workflow.add_node("debug_povs", self._debug_failed_povs)

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

        # After testing PoVs, decide whether to debug
        def should_debug_or_continue(state: VulnDiscoveryDebugState) -> str:
            # If we found valid PoVs, we're done
            if state.valid_pov_count > 0:
                return "end"
            # If we've reached max iterations, we're done
            if state.pov_iteration >= self.MAX_POV_ITERATIONS:
                return "end"
            # If this is the first iteration, don't debug yet
            if state.pov_iteration <= self.DEBUG_AFTER_ITERATION:
                return "retry"
            # Otherwise, debug before retrying
            return "debug"

        workflow.add_conditional_edges(
            "test_povs",
            should_debug_or_continue,
            {
                "debug": "debug_povs",
                "retry": "analyze_bug",
                "end": END,
            },
        )

        # After debugging, always retry
        workflow.add_edge("debug_povs", "analyze_bug")

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

