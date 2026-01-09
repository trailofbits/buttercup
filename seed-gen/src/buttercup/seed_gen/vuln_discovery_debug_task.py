"""Vuln Discovery task with integrated debug capabilities.

This task integrates DebugSubagentUnified into the vulnerability discovery workflow.
When PoVs fail to crash (after testing), it uses GDB-based debugging to understand why
and incorporates those insights into the next iteration.
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import override

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
import tempfile
from pydantic import Field

from buttercup.seed_gen.debug_subagent_unified import DebugSubagentUnified
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
            skip_validation=True  # Skip validation since we already tested the PoV
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

    def _debug_failed_povs(self, state: VulnDiscoveryDebugState) -> Command:
        """Debug failed PoVs after testing to understand why they didn't crash"""
        # Note: _test_povs increments pov_iteration, so we need to use previous_iteration
        # to find files that were just moved
        previous_iteration = state.pov_iteration - 1
        logger.info("Debugging failed PoVs from iteration %d (current iteration is %d)", 
                   previous_iteration, state.pov_iteration)
        logger.info("Current state: valid_pov_count=%d, pov_iteration=%d", state.valid_pov_count, state.pov_iteration)
        
        # Only debug if all PoVs failed (valid_pov_count == 0)
        if state.valid_pov_count > 0:
            logger.info("Some PoVs succeeded, skipping debug")
            return Command(update={})

        # Log output directory details
        logger.info("Searching for failed PoVs in output_dir: %s", state.output_dir)
        logger.info("Output dir exists: %s", state.output_dir.exists())
        logger.info("Output dir is directory: %s", state.output_dir.is_dir() if state.output_dir.exists() else "N/A")
        
        if state.output_dir.exists():
            all_files = list(state.output_dir.iterdir())
            logger.info("All files in output_dir (%d total): %s", len(all_files), [f.name for f in all_files])
            
            # Log all .seed files regardless of pattern
            all_seed_files = list(state.output_dir.glob("*.seed"))
            logger.info("All .seed files in output_dir (%d total): %s", len(all_seed_files), [f.name for f in all_seed_files])
        else:
            logger.warning("Output directory does not exist: %s", state.output_dir)
            return Command(update={})

        # Find failed PoVs in output_dir (they were moved there by _test_povs)
        # IMPORTANT: _test_povs increments pov_iteration before returning, so we need to use
        # the previous iteration number (pov_iteration - 1) to find files that were just moved
        # Files are moved with pattern: iter{old_pov_iteration}_{original_name}
        search_pattern = f"iter{previous_iteration}_*.seed"
        logger.info("Searching for PoVs with pattern: %s (using previous iteration %d, current is %d)", 
                   search_pattern, previous_iteration, state.pov_iteration)
        
        # Sort by modification time (newest first) to get the most recently generated PoVs
        # This prevents picking up stale files from previous runs
        failed_povs = sorted(
            state.output_dir.glob(search_pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        for pov_file in failed_povs:
            # Check if this PoV actually failed (not valid)
            # We can't easily check this here, so we'll debug the first one
            logger.info("Found potential failed PoV: %s (size: %d bytes, mtime: %.2f)", 
                       pov_file.name, 
                       pov_file.stat().st_size if pov_file.exists() else 0,
                       pov_file.stat().st_mtime if pov_file.exists() else 0)
        
        logger.info("Total failed PoVs found: %d", len(failed_povs))
        
        if not failed_povs:
            logger.warning("No failed PoVs found to debug in output_dir")
            logger.warning("Expected pattern: iter%d_*.seed (previous iteration, current is %d)", 
                         previous_iteration, state.pov_iteration)
            logger.warning("This might indicate:")
            logger.warning("  1. PoVs were not moved to output_dir by _test_povs")
            logger.warning("  2. PoVs were moved with a different naming pattern")
            logger.warning("  3. PoVs were moved to a different location")
            logger.warning("  4. No PoVs were generated in this iteration")
            return Command(update={})

        # Debug the first failed PoV (could be extended to debug multiple)
        pov_path = failed_povs[0]
        logger.info(f"Debugging failed PoV: {pov_path}")

        # Create debug context from the analysis
        harness_info = f"Fuzzer: {state.harness.harness_name} in {state.harness.file_path}"
        logger.info(f"Harness info: {harness_info}")
        
        # Add more specific context if analysis is available
        analysis_section = f"\n{state.analysis}\n" if state.analysis.strip() else "\nNo detailed analysis available.\n"
        
        debug_context = f"""This PoV was generated to exploit a potential vulnerability but FAILED to crash the program when tested.

**Target Information:**
{harness_info}

**POV input:**
{pov_path.name}

**Vulnerability Analysis:**{analysis_section}
**Debugging Goals:**
This PoV was tested and did NOT cause a crash. Analyze its execution to understand why:

1. **Execution Path**: Is the vulnerable code path being executed at all?
2. **Input Processing**: How is the PoV input being parsed and processed? Is it being rejected or modified?
3. **Exploitation Conditions**: Are the necessary conditions for exploitation being met? What's missing?
4. **Program State**: What is the actual state of the program at critical points (buffer sizes, pointers, validation checks)?
5. **Vulnerability Trigger**: Is the vulnerability actually being triggered? If not, what's preventing it?
6. **Expected vs Actual**: Why doesn't the program behavior match our expectations from the analysis?

This debugging will help us:
- Understand why the PoV failed to crash
- Identify what conditions are needed for successful exploitation
- Gather insights to improve the next iteration's PoV generation
"""

        # Run debug subagent
        try:
            # Use a separate directory for debug output
            debug_uuid = uuid.uuid4().hex[:8]
            debug_output_dir = state.current_dir.parent / "agentic_debug" / f"{debug_uuid}_iter{previous_iteration}_failed"
            with tempfile.TemporaryDirectory(dir=state.current_dir ) as current_dir:
                logger.info("Calling debug subagent with pov_path=%s, output_dir=%s, current_dir=%s", pov_path, debug_output_dir, state.current_dir)
                debug_result = self.debug_subagent_unified.debug(
                    harness=state.harness,
                    pov_input_path=pov_path,
                    debug_context=debug_context,
                    output_dir=debug_output_dir,
                    current_dir=Path(current_dir),
                )
            logger.info("Debug subagent returned: analysis_len=%d, debug_commands_len=%d, output_len=%d, reflection_len=%d, attempts=%d", 
                       len(debug_result.analysis), 
                       len(debug_result.debug_commands),
                       len(debug_result.debug_output),
                       len(debug_result.reflection),
                       len(debug_result.attempts))

            # Format debug insights - focus on why the PoV failed
            # Use previous_iteration since that's when the PoV was actually tested
            debug_insights = f"""## Debug Session for Failed PoV (iteration {previous_iteration})

**PoV Status:** This PoV was tested and did NOT cause a crash.

**Debug Summary:**
{debug_result.reflection}

**Key Findings:**
- Why didn't this PoV crash the program?
- What conditions need to be met for successful exploitation?
- What should we change in the next iteration?
"""

            logger.info("Debug session completed for failed PoV")

            return Command(
                update={
                    "debug_insights": state.debug_insights + "\n\n" + debug_insights,
                }
            )

        except Exception as e:
            logger.error(f"Error during debugging of failed PoV: {e}")
            # Don't fail the whole workflow if debugging fails
            return Command(
                update={
                    "debug_insights": state.debug_insights
                    + f"\n\n## Debug Error\n\nFailed to debug PoV: {str(e)}",
                }
            )

    @override
    def _build_workflow(self) -> StateGraph:  # type: ignore[override]
        """Build workflow with debugging only when PoVs fail"""
        workflow = StateGraph(self.TaskStateClass)

        workflow.add_node("gather_context", self._gather_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_bug", self._analyze_bug)
        workflow.add_node("write_pov", self._write_pov)
        workflow.add_node("execute_python_funcs", self._exec_python_funcs_current)
        workflow.add_node("test_povs", self._test_povs)
        workflow.add_node("debug_failed_povs", self._debug_failed_povs)  # Run AFTER testing, only if failed

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
        
        # After debugging, retry with insights
        workflow.add_edge("debug_failed_povs", "analyze_bug")

        return workflow

    def recursion_limit(self) -> int:
        context_steps = 2
        pov_steps = 4
        debug_steps = 1  # Debug step only runs when PoVs fail
        # Debug only runs when valid_pov_count == 0, so it's conditional
        # We'll include it in the limit to be safe
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

