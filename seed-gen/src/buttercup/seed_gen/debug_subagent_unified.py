"""Unified debug subagent that supports batch, interactive, and hybrid debugging modes.

This allows experimentation with different debugging strategies:
- "batch": Uses pre-written GDB scripts (faster, less flexible)
- "interactive": Uses LLM-driven interactive GDB commands (slower, more flexible)
- "hybrid": Runs batch first, then interactive follow-up if needed
"""

import logging
import operator
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from opentelemetry import trace
from pydantic import Field

from buttercup.common.challenge_task import ChallengeTaskError
from buttercup.common.llm import get_langfuse_callbacks
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.interactive_debug_docker import InteractiveGDBDocker
from buttercup.seed_gen.prompt.debug import (
    DEBUG_ANALYZE_SYSTEM_PROMPT,
    DEBUG_ANALYZE_USER_PROMPT,
    DEBUG_GET_CONTEXT_SYSTEM_PROMPT,
    DEBUG_GET_CONTEXT_USER_PROMPT,
    DEBUG_INTERACTIVE_COMMAND_SYSTEM_PROMPT,
    DEBUG_INTERACTIVE_COMMAND_USER_PROMPT,
    DEBUG_INTERACTIVE_FOLLOW_UP_SYSTEM_PROMPT,
    DEBUG_INTERACTIVE_FOLLOW_UP_USER_PROMPT,
    DEBUG_REFLECT_SYSTEM_PROMPT,
    DEBUG_REFLECT_USER_PROMPT,
    DEBUG_WRITE_SCRIPT_SYSTEM_PROMPT,
    DEBUG_WRITE_SCRIPT_USER_PROMPT,
)
from buttercup.seed_gen.task import BaseTaskState, Task
from buttercup.seed_gen.utils import extract_code

logger = logging.getLogger(__name__)


class DebugMode(str, Enum):
    """Debug execution mode"""
    BATCH = "batch"
    INTERACTIVE = "interactive"
    HYBRID = "hybrid"


@dataclass
class DebugAttempt:
    """Represents a debug attempt with analysis and script"""

    analysis: str
    debug_script: str
    debug_output: str = ""
    pov_valid: bool = False

    def __str__(self) -> str:
        return f"""<debug_attempt>
<analysis>
{self.analysis}
</analysis>
<debug_script>
{self.debug_script}
</debug_script>
<debug_output>
{self.debug_output}
</debug_output>
<pov_valid>
{self.pov_valid}
</pov_valid>
</debug_attempt>
"""


@dataclass
class DebugResult:
    """Unified result of a debug session"""
    debug_commands: list[str]
    pov_valid: bool
    debug_output: str
    analysis: str
    reflection: str
    debug_script: str = ""  # Only populated for batch/hybrid modes
    attempts: list[DebugAttempt] = None  # For compatibility with batch mode

    def __post_init__(self):
        if self.attempts is None:
            self.attempts = []


class DebugTaskState(BaseTaskState):
    """State for the debug task - supports both batch and interactive modes"""

    debug_context: str = Field(
        description="Articulated context about what to test and verify",
        default="",
    )
    pov_input_path: Path = Field(
        description="Path to the PoV input file",
    )
    analysis: str = Field(description="The analysis of the debugging task", default="")
    debug_script: str = Field(description="The GDB debug script to execute (batch mode)", default="")
    debug_script_output: str = Field(description="Output from running the debug session", default="")
    debug_commands: list[str] = Field(description="List of GDB commands executed (interactive mode)", default_factory=list)
    debug_interactive_output: str = Field(description="Output from running the interactive debug session", default="")
    reflection: str = Field(description="Reflection on what happened during execution and how it relates to the vulnerability", default="")
    pov_valid: bool = Field(description="Whether the PoV is valid (causes a crash)", default=False)
    debug_iteration: int = Field(description="Count of debug iterations", default=0)
    debug_attempts: Annotated[list[DebugAttempt], operator.add] = Field(default_factory=list)
    needs_interactive_follow_up: bool = Field(description="Whether interactive debugging follow-up is needed (hybrid mode)", default=False)
    current_dir: Path = Field(description="Directory to scratchpad files")

    def format_debug_attempts(self) -> str:
        """Format debug attempts for prompts"""
        return "\n\n".join(str(attempt) for attempt in self.debug_attempts)


class DebugSubagentUnified:
    """Unified debug subagent that supports multiple debugging modes.
    
    This allows easy experimentation with different debugging strategies:
    - batch: Pre-written GDB scripts
    - interactive: LLM-driven interactive commands
    - hybrid: Batch first, then interactive follow-up
    """

    MAX_DEBUG_ITERATIONS = 2
    MAX_CONTEXT_ITERATIONS = 3
    MAX_CONTEXT_ITERATIONS_AGAIN = 2
    MAX_INTERACTIVE_COMMANDS = 20  # Depth of interactive debug loop
    # Each context iteration can have multiple tool calls (get_context -> tools)
    # Estimate ~5 tool calls per context iteration to be safe
    ESTIMATED_TOOLS_PER_CONTEXT = 5

    def __init__(
        self,
        task: Task,
        reproduce_multiple: ReproduceMultiple,
        mode: DebugMode | str | None = None,
        skip_validation: bool = False,
    ):
        """Initialize the unified debug subagent.

        Args:
            task: The parent task (provides LLM, tools, codequery, etc.)
            reproduce_multiple: Used to validate PoVs and run debug containers
            mode: Debug mode - "batch", "interactive", or "hybrid". 
                  If None, reads from BUTTERCUP_DEBUG_MODE env var (defaults to "interactive")
            skip_validation: If True, skip PoV validation and only run debug once
        """
        self.task = task
        self.reproduce_multiple = reproduce_multiple
        self.skip_validation = skip_validation
        
        # Determine mode
        if mode is None:
            mode_str = os.getenv("BUTTERCUP_DEBUG_MODE", "interactive")
        elif isinstance(mode, DebugMode):
            mode_str = mode.value
        else:
            mode_str = mode.lower()
        
        try:
            self.mode = DebugMode(mode_str)
        except ValueError:
            logger.warning(f"Invalid debug mode '{mode_str}', defaulting to 'interactive'")
            self.mode = DebugMode.INTERACTIVE
        
        logger.info(f"Initializing DebugSubagentUnified with mode: {self.mode.value}")
        
        # Create debug tools list with grep included
        self.debug_tools = task.get_debug_tools()
        self.llm_with_debug_tools = task.llm.bind_tools(self.debug_tools)

    def debug(
        self,
        harness: HarnessInfo,
        pov_input_path: Path,
        debug_context: str,
        output_dir: Path,
        current_dir: Path,
    ) -> DebugResult:
        """Debug a PoV input using the configured mode.

        Args:
            harness: The harness to target
            pov_input_path: Path to the PoV input file (actual input bytes, not script)
            debug_context: Articulated context about what to test/verify
            output_dir: Optional directory to write debug results to

        Returns:
            DebugResult with debug information and validation status
        """
        return self._debug_workflow(harness, pov_input_path, debug_context, output_dir, current_dir)

    def _debug_workflow(
        self,
        harness: HarnessInfo,
        pov_input_path: Path,
        debug_context: str,
        output_dir: Path,
        current_dir: Path,
    ) -> DebugResult:
        """Run the debug workflow based on the configured mode"""
        return self._run_debug_workflow(harness, pov_input_path, debug_context, output_dir, current_dir)


    def _run_debug_workflow(
        self,
        harness: HarnessInfo,
        pov_input_path: Path,
        debug_context: str,
        output_dir: Path,
        current_dir: Path,
    ) -> DebugResult:
        """Run the debug workflow (either batch or interactive)"""
        logger.info(
            "Starting debug session for harness: %s | pov_input: %s | mode: %s",
            harness,
            pov_input_path,
            self.mode.value,
        )

        try:
            logger.info("Creating debug state")
            logger.info(f"debug_subagent_unified: current_dir provided: {current_dir}")
            if not current_dir or not Path(current_dir).exists():
                logger.error(f"Provided current_dir does not exist: {current_dir}")
                raise FileNotFoundError(f"Provided current_dir does not exist: {current_dir}")
            state = DebugTaskState(
                harness=harness,
                task=self.task,
                output_dir=output_dir,
                pov_input_path=pov_input_path,
                debug_context=debug_context,
                current_dir=current_dir,
            )
            logger.info("Debug state created successfully")

            logger.info("Building debug workflow")
            workflow = self._build_workflow(self.mode)
            logger.info("Getting Langfuse callbacks")
            llm_callbacks = get_langfuse_callbacks()
            recursion_limit = self._recursion_limit(self.mode)
            logger.info("Compiling workflow with recursion_limit=%d", recursion_limit)
            chain = workflow.compile().with_config(
                RunnableConfig(
                    tags=["debug-subagent-unified"],
                    callbacks=llm_callbacks,
                    recursion_limit=recursion_limit,
                ),
            )
            logger.info("Workflow compiled successfully")

            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("seed_gen_debug") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                    crs_action_name="seed_gen_debug",
                    task_metadata=dict(self.task.challenge_task.task_meta.metadata),
                    extra_attributes={
                        "gen_ai.request.model": self.task.llm.model_name,  # type: ignore[attr-defined]
                        "debug_mode": self.mode.value,
                    },
                )

                # Run the workflow
                logger.info("Invoking debug workflow chain")
                final_state = chain.invoke(state)  # type: ignore[arg-type]
                logger.info("Debug workflow chain completed")

                # Get values from state (final_state is a dict)
                debug_script = final_state.get("debug_script", "") or ""
                debug_script_output = final_state.get("debug_script_output", "") or ""
                debug_interactive_output = final_state.get("debug_interactive_output", "") or ""
                debug_commands = final_state.get("debug_commands", [])
                analysis = final_state.get("analysis", "") or ""
                reflection = final_state.get("reflection", "") or ""
                pov_valid = final_state.get("pov_valid", False)
                debug_attempts = final_state.get("debug_attempts", [])

                # Use interactive output if available (for interactive/hybrid modes), otherwise use script output (for batch mode)
                debug_output = debug_interactive_output if debug_interactive_output else debug_script_output

                logger.info(
                    "Debug state extracted: analysis_len=%d, script_len=%d, commands=%d, output_len=%d, reflection_len=%d, attempts=%d",
                    len(analysis),
                    len(debug_script),
                    len(debug_commands),
                    len(debug_output),
                    len(reflection),
                    len(debug_attempts),
                )

                # Write results to output directory if provided
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    if debug_script:
                        (output_dir / "debug_script.gdb").write_text(debug_script)
                    if debug_commands:
                        (output_dir / "debug_commands.txt").write_text("\n".join(debug_commands))
                    if debug_script_output:
                        (output_dir / "debug_script_output.txt").write_text(debug_script_output)
                    if debug_interactive_output:
                        (output_dir / "debug_interactive_output.txt").write_text(debug_interactive_output)
                    # Write unified debug_output.txt (contains either script or interactive output)
                    if debug_output:
                        (output_dir / "debug_output.txt").write_text(debug_output)
                    if analysis:
                        (output_dir / "analysis.txt").write_text(analysis)
                    if reflection:
                        (output_dir / "reflection.txt").write_text(reflection)
                    (output_dir / "pov_valid.txt").write_text(str(pov_valid))
                    if debug_attempts:
                        attempts_text = "\n\n".join(str(attempt) for attempt in debug_attempts)
                        (output_dir / "debug_attempts.txt").write_text(attempts_text)

                logger.info(
                    "Debug session completed: pov_valid=%s, iterations=%d, attempts=%d",
                    pov_valid,
                    final_state.get("debug_iteration", 0),
                    len(debug_attempts),
                )

                return DebugResult(
                    debug_commands=debug_commands,
                    pov_valid=pov_valid,
                    debug_output=debug_output,
                    analysis=analysis,
                    reflection=reflection,
                    debug_script=debug_script,
                    attempts=debug_attempts,
                )

        except Exception as err:
            logger.exception("Failed debug session: %s", str(err))
            return DebugResult(
                debug_commands=[],
                pov_valid=False,
                debug_output=f"Error: {str(err)}",  # Use debug_output field name
                analysis="",
                reflection="",
                debug_script="",
                attempts=[],
            )

    def _get_context(self, state: DebugTaskState) -> Command:
        """Get context about the codebase for debugging"""
        logger.info("Getting context for debugging")
        prev_debug_attempt = """ We attempted a batch debug session before, and determined that more context and a new interactive debug session are needed to answer the query.
Here is the previous debug attempt:
<previous_debug_attempt>
{state.debug_script}
</previous_debug_attempt>
Here is the previous debug output:
<previous_debug_output>
{state.debug_script_output}
</previous_debug_output>
Please gather more context about the codebase that will help with debugging.
"""
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "retrieved_context": state.format_retrieved_context(),
            "prev_debug_attempt": prev_debug_attempt,
        }
        # Use custom llm_with_debug_tools that includes grep
        prompt = [
            ("system", DEBUG_GET_CONTEXT_SYSTEM_PROMPT),
            ("human", DEBUG_GET_CONTEXT_USER_PROMPT.format(**prompt_vars)),
        ]
        res = self.llm_with_debug_tools.invoke([*prompt, *state.messages])
        cmd: Command = Command(
            update={
                "messages": [res],
                "context_iteration": state.context_iteration + 1,
            },
        )
        return cmd

    def _analyze_debug(self, state: DebugTaskState) -> Command:
        """Analyze the debugging task and plan the debug script"""
        logger.info("Analyzing debug task")
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "retrieved_context": state.format_retrieved_context(),
            "previous_attempts": state.format_debug_attempts(),
        }
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DEBUG_ANALYZE_SYSTEM_PROMPT),
                ("human", DEBUG_ANALYZE_USER_PROMPT),
            ],
        )
        chain = prompt | self.task.llm | StrOutputParser()
        analysis = chain.invoke(prompt_vars)
        return Command(update={"analysis": analysis})

    def _write_debug_script(self, state: DebugTaskState) -> Command:
        """Write a GDB debug script (batch mode only)"""
        logger.info("Writing debug script")
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "analysis": state.analysis,
            "retrieved_context": state.format_retrieved_context(),
            "previous_attempts": state.format_debug_attempts(),
        }
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DEBUG_WRITE_SCRIPT_SYSTEM_PROMPT),
                ("human", DEBUG_WRITE_SCRIPT_USER_PROMPT),
            ],
        )
        logger.debug(f"Prompt variables for debug script generation: {prompt_vars}")
        
        try:
            # Get LLM response first to log it if extraction fails
            chain_no_extract = prompt | self.task.llm
            llm_response = chain_no_extract.invoke(prompt_vars)
            
            # Extract code from response
            debug_script = extract_code(llm_response)
            logger.info(f"Successfully extracted debug script ({len(debug_script)} chars)")
            return Command(update={"debug_script": debug_script})
        except Exception as e:
            logger.error(f"Failed to extract debug script from LLM response: {e}")
            if "llm_response" in locals():
                content = getattr(llm_response, "content", str(llm_response))
                logger.error(f"LLM response content (first 500 chars): {content[:500] if content else 'None'}")
            # Continue the loop with empty script - this iteration will be treated as failed
            return Command(update={"debug_script": ""})

    def _run_debug_script(self, state: DebugTaskState) -> Command:
        """Run the debug script in a debug container (batch mode only)"""
        logger.info("Running debug script")
        if not state.debug_script:
            logger.warning("No debug script to run")
            return Command(update={"debug_script_output": "No debug script provided"})

        # Write debug script to a temporary file
        # NOTE: We do NOT delete this file. Docker needs it to remain accessible
        # during the mount. The OS will clean it up later, or we could clean it
        # up after Docker has fully completed, but that's complex with the current
        # architecture where exec_docker_cmd might cache containers.
        logger.info("Creating temporary GDB script file...")
        logger.info(f"  Script content length: {len(state.debug_script)} characters")
        
        debug_script_path = state.current_dir / "debug_script.gdb"
        debug_script_path.write_text(state.debug_script)
        
        # Verify the file was created successfully
        logger.info(f"Verifying file after creation:")
        logger.info(f"  Path: {debug_script_path}")
        logger.info(f"  Exists: {debug_script_path.exists()}")
        if debug_script_path.exists():
            stat_info = debug_script_path.stat()
            logger.info(f"  Is file: {debug_script_path.is_file()}")
            logger.info(f"  Is directory: {debug_script_path.is_dir()}")
            logger.info(f"  Size: {stat_info.st_size} bytes")
            logger.info(f"  Permissions: {oct(stat_info.st_mode)}")
            logger.info(f"  Absolute path: {debug_script_path.resolve()}")
        
        if not debug_script_path.exists():
            logger.error(f"Failed to create debug script file at {debug_script_path}")
            return Command(update={"debug_script_output": f"Error: Failed to create debug script file"})
        
        logger.info(f"Created debug script file: {debug_script_path} (size: {debug_script_path.stat().st_size} bytes)")

        try:
            # Run the debug script using exec_docker_cmd with debug container
            # Verify the file exists and is readable before passing to Docker
            if not debug_script_path.exists():
                return Command(update={"debug_script_output": f"Error: Debug script file not found at {debug_script_path}"})
            if not debug_script_path.is_file():
                return Command(update={"debug_script_output": f"Error: Debug script path is not a file: {debug_script_path}"})
            
            logger.info(f"Debug script file verified: {debug_script_path} (size: {debug_script_path.stat().st_size} bytes)")
            
            debug_script_output = self._execute_debug_script(debug_script_path, state.pov_input_path, state.harness.harness_name)
            try:
                debug_script_path.unlink()
                logger.info(f"Removed debug script file: {debug_script_path}")
            except Exception as e:
                logger.warning(f"Failed to remove debug script file {debug_script_path}: {e}")
            return Command(update={"debug_script_output": debug_script_output})
        except Exception as e:
            logger.error(f"Error running debug script: {e}")
            try:
                debug_script_path.unlink()
                logger.info(f"Removed debug script file: {debug_script_path}")
            except Exception as e:
                logger.warning(f"Failed to remove debug script file {debug_script_path}: {e}")
            return Command(update={"debug_script_output": f"Error: {str(e)}"})

    def _run_interactive_debug(self, state: DebugTaskState) -> Command:
        """Run interactive GDB debugging session with LLM-driven commands (interactive mode only)"""
        logger.info("Starting interactive debug session")
        
        try:
            debug_interactive_output, debug_commands, debug_reasoning = self._execute_interactive_debug(state.pov_input_path, state)
            return Command(update={
                "debug_interactive_output": debug_interactive_output,
                "debug_commands": debug_commands,
            })
        except Exception as e:
            logger.error(f"Error running interactive debug: {e}")
            return Command(update={
                "debug_interactive_output": f"Error: {str(e)}",
                "debug_commands": [],
            })

    def _reflect_debug(self, state: DebugTaskState) -> Command:
        """Reflect on the debug output and summarize what happened"""
        logger.info("Reflecting on debug output")
        # For interactive mode, there's no debug_script, so provide a placeholder
        debug_script = state.debug_script
        if not debug_script:
            debug_script = ""
        debug_commands = state.debug_commands
        if not debug_commands:
            debug_commands = ""
        debug_interactive_output = state.debug_interactive_output
        if not debug_interactive_output:
            debug_interactive_output = ""
        debug_script_output = state.debug_script_output
        if not debug_script_output:
            debug_script_output = ""
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "analysis": state.analysis,
            "debug_script_output": debug_script_output,
            "debug_interactive_output": debug_interactive_output,
            "debug_script": debug_script,
            "debug_commands": debug_commands,
        }
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DEBUG_REFLECT_SYSTEM_PROMPT),
                ("human", DEBUG_REFLECT_USER_PROMPT),
            ],
        )
        chain = prompt | self.task.llm | StrOutputParser()
        reflection = chain.invoke(prompt_vars)
        return Command(update={"reflection": reflection})

    def _execute_debug_script(
        self,
        debug_script_path: Path,
        pov_input_path: Path,
        harness_name: str,
    ) -> str:
        """Execute a GDB debug script in a debug container (batch mode)
        
        IMPORTANT: Debug Symbol Support
        --------------------------------
        This method attempts to use debug binaries (built with build_fuzzers_with_debug_symbols())
        which have FULL debug symbols (`-ggdb -fno-inline`). If debug binaries are not available,
        it falls back to regular production binaries which are compiled with `-gline-tables-only`
        (minimal debug information).
        
        With FULL debug symbols (debug binaries):
        - ✅ Function names work
        - ✅ Line numbers work
        - ✅ Variable names available
        - ✅ Type information available
        - ✅ Detailed debugging info available
        
        
        GDB scripts should work with both, but will have better variable/type access with debug binaries.
        """
        # Get a writable copy of the task
        with self.reproduce_multiple.open() as mult:
            if mult.builds_cache is None or not mult.builds_cache:
                raise ValueError("Build cache not available")
            
            # Use the harness name from the PoV's harness (not self.task.harness_name)
            # This ensures we debug with the same harness the PoV was generated for
            
            # Select a build that contains the harness binary
            # Prefer address sanitizer builds, but verify the harness exists in the selected build
            # All builds for the same project share the same build directory,
            # but we prefer asan since it's most common and provides better crash detection
            task = None
            selected_build = None
            
            # First, try to find an address sanitizer build with the harness
            for build, cached_task in zip(mult.build_outputs, mult.builds_cache, strict=False):
                if build.sanitizer == "address":
                    build_dir = cached_task.get_build_dir()
                    if build_dir and build_dir.exists():
                        # Check if harness exists (debug or regular binary)
                        debug_binary_path = cached_task.get_debug_binary_path(harness_name)
                        regular_binary_path = build_dir / harness_name
                        if (debug_binary_path and debug_binary_path.exists()) or regular_binary_path.exists():
                            task = cached_task
                            selected_build = build
                            logger.info(f"Using address sanitizer build with harness '{harness_name}' (task_id: {build.task_id})")
                            break
            
            # If no asan build with harness found, try any build with the harness
            if task is None:
                for build, cached_task in zip(mult.build_outputs, mult.builds_cache, strict=False):
                    build_dir = cached_task.get_build_dir()
                    if build_dir and build_dir.exists():
                        # Check if harness exists (debug or regular binary)
                        debug_binary_path = cached_task.get_debug_binary_path(harness_name)
                        regular_binary_path = build_dir / harness_name
                        if (debug_binary_path and debug_binary_path.exists()) or regular_binary_path.exists():
                            task = cached_task
                            selected_build = build
                            logger.info(f"Using build with harness '{harness_name}' (task_id: {build.task_id}, sanitizer: {build.sanitizer})")
                            break
            
            # If still no build found, fallback to first build (will fail later if harness doesn't exist)
            if task is None:
                task = mult.builds_cache[0]
                selected_build = mult.build_outputs[0]
                logger.warning(f"No build found with harness '{harness_name}', using first build (task_id: {selected_build.task_id}). This may fail if harness doesn't exist.")
            
            # Determine the debug container image
            debug_container_image = "gcr.io/oss-fuzz-base/base-runner-debug"

            # Resolve paths to ensure they're absolute
            logger.info(f"Pre-resolve paths:")
            logger.info(f"  debug_script_path: {debug_script_path} (is_absolute: {debug_script_path.is_absolute()})")
            logger.info(f"  pov_input_path: {pov_input_path} (is_absolute: {pov_input_path.is_absolute()})")
            logger.info(f"  Current working directory: {Path.cwd()}")
            
            debug_script_path = debug_script_path.resolve()
            pov_input_path = pov_input_path.resolve()
            
            logger.info(f"Post-resolve paths:")
            logger.info(f"  debug_script_path: {debug_script_path}")
            logger.info(f"  pov_input_path: {pov_input_path}")

            # Get the build output directory so GDB can find the binary
            build_dir = task.get_build_dir()
            logger.info(f"Build directory from task.get_build_dir(): {build_dir}")
            
            if not build_dir or not build_dir.exists():
                raise ValueError(f"Build directory not found or doesn't exist: {build_dir}")
            
            logger.info(f"Build directory exists: {build_dir}")
            # List files in build_dir to debug
            if build_dir.is_dir():
                files_in_build = list(build_dir.iterdir())[:10]  # First 10 files
                logger.info(f"Files in build_dir: {[f.name for f in files_in_build]}")
            
            # Try to use debug binary first (with full debug symbols), fallback to regular binary
            debug_binary_path = task.get_debug_binary_path(harness_name)
            using_debug_binary = False
            if debug_binary_path and debug_binary_path.exists():
                harness_binary_path = debug_binary_path
                using_debug_binary = True
                logger.info(f"Using debug binary with full symbols: {harness_binary_path}")
            else:
                # Fallback to regular production binary
                harness_binary_path = build_dir / harness_name
                if not harness_binary_path.exists():
                    available_files = [f.name for f in build_dir.iterdir()] if build_dir.is_dir() else []
                    raise ValueError(
                        f"Harness binary '{harness_name}' not found in {build_dir}. "
                        f"Available files: {available_files}"
                    )
                logger.info(f"Using regular production binary (debug binary not available): {harness_binary_path}")
            
            # Ensure the binary has execute permissions
            current_perms = harness_binary_path.stat().st_mode
            harness_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            
            # Read first 4 bytes to check if it's an ELF binary (magic: 7f 45 4c 46)
            try:
                with open(harness_binary_path, 'rb') as f:
                    magic = f.read(4)
                    is_elf = magic == b'\x7fELF'
            except Exception:
                is_elf = False
            
            binary_size = harness_binary_path.stat().st_size
            logger.info(f"Found harness binary: {harness_binary_path}")
            logger.info(f"  Permissions: {oct(harness_binary_path.stat().st_mode)}")
            logger.info(f"  Size: {binary_size} bytes")
            logger.info(f"  Is ELF binary: {is_elf}")
            
            
            # If the file is not an ELF binary or is suspiciously small, it might be a wrapper script
            # Try to find the actual binary. Wrapper scripts often have suffixes like _nalloc, _asan, etc.
            # The actual binary is usually the base harness name without the suffix
            actual_binary_path = harness_binary_path
            actual_binary_name = harness_name
            if not is_elf or binary_size < 1024:
                logger.warning(
                    f"File '{harness_name}' appears to be a wrapper script (size={binary_size}, is_elf={is_elf}). "
                    f"Searching for actual ELF binary..."
                )
                
                # Try to find the actual binary by looking for ELF files in the build directory
                # Priority: 1) Base name without suffix, 2) Any ELF file with base name as prefix
                base_name = harness_name
                # Remove common sanitizer suffixes
                for suffix in ['_nalloc', '_asan', '_msan', '_ubsan', '_tsan', '_hwasan']:
                    if base_name.endswith(suffix):
                        base_name = base_name[:-len(suffix)]
                        break
                
                # First, try the base name directly
                candidate_path = build_dir / base_name
                if candidate_path.exists() and candidate_path.is_file():
                    try:
                        with open(candidate_path, 'rb') as f:
                            candidate_magic = f.read(4)
                            candidate_is_elf = candidate_magic == b'\x7fELF'
                        candidate_size = candidate_path.stat().st_size
                        if candidate_is_elf and candidate_size > 1024:
                            logger.info(
                                f"Found actual binary: {base_name} (size={candidate_size}, is_elf={candidate_is_elf}). "
                                f"Using this instead of wrapper '{harness_name}'."
                            )
                            actual_binary_path = candidate_path
                            actual_binary_name = base_name
                            # Set execute permissions
                            current_perms = actual_binary_path.stat().st_mode
                            actual_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    except Exception as e:
                        logger.debug(f"Error checking candidate {base_name}: {e}")
                
                # If base name didn't work, search for any ELF file with base name as prefix
                if actual_binary_path == harness_binary_path and build_dir.is_dir():
                    for candidate in build_dir.iterdir():
                        if candidate.is_file() and candidate != harness_binary_path:
                            if candidate.name.startswith(base_name):
                                try:
                                    with open(candidate, 'rb') as f:
                                        candidate_magic = f.read(4)
                                        candidate_is_elf = candidate_magic == b'\x7fELF'
                                    candidate_size = candidate.stat().st_size
                                    if candidate_is_elf and candidate_size > 1024:
                                        logger.info(
                                            f"Found actual binary: {candidate.name} (size={candidate_size}, is_elf={candidate_is_elf}). "
                                            f"Using this instead of wrapper '{harness_name}'."
                                        )
                                        actual_binary_path = candidate
                                        actual_binary_name = candidate.name
                                        # Set execute permissions
                                        current_perms = actual_binary_path.stat().st_mode
                                        actual_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                                        break
                                except Exception:
                                    pass
            
            # Use the actual binary (or original if it was already valid)
            harness_binary_path = actual_binary_path
            harness_name_for_path = actual_binary_name
            
            # Mount files for Docker
            # Use unique paths to avoid conflicts with existing directories in the container
            # Generate a unique filename based on the temp file name to ensure uniqueness
            logger.info("=" * 80)
            logger.info("Setting up Docker mounts...")
            logger.info("=" * 80)
            
            # Get parent directories for both files
            # NOTE: These are often DIFFERENT directories:
            # - debug_script_path is in state.current_dir (a temp directory)
            # - pov_input_path is in the output directory from testing
            debug_script_parent = debug_script_path.parent
            pov_input_parent = pov_input_path.parent
            
            # Check if they're in the same directory
            if debug_script_parent == pov_input_parent:
                # Both files are in the same directory - mount once to /work
                debug_script_container_path = Path(f"/work/{debug_script_path.name}")
                pov_input_container_path = Path(f"/work/{pov_input_path.name}")
                logger.info("Debug script and PoV input are in the same directory")
            else:
                # Files are in different directories - mount separately
                debug_script_container_path = Path(f"/work/debug/{debug_script_path.name}")
                pov_input_container_path = Path(f"/work/input/{pov_input_path.name}")
                logger.info("Debug script and PoV input are in DIFFERENT directories")
            
            logger.info(f"Host paths (source files on host):")
            logger.info(f"  Debug script: {debug_script_path}")
            logger.info(f"  Debug script parent: {debug_script_parent}")
            logger.info(f"  PoV input: {pov_input_path}")
            logger.info(f"  PoV input parent: {pov_input_parent}")
            logger.info(f"Container paths (targets in container):")
            logger.info(f"  Debug script: {debug_script_container_path}")
            logger.info(f"  PoV input: {pov_input_container_path}")
            
            # Get project_name for container binary path
            # build_dir is .../build/out/<project_name>, so project_name is the last component
            project_name = build_dir.name
            # Binary path in container: /out/<project_name>/<actual_binary_name>
            # If using debug binary, it's in /out/<project_name>/debug/<actual_binary_name>
            # Use the actual binary name (which may differ from harness_name if it was a wrapper)
            if using_debug_binary:
                binary_path = f"/out/{project_name}/debug/{harness_name_for_path}"
            else:
                binary_path = f"/out/{project_name}/{harness_name_for_path}"
            
            # Mount the parent of build_dir (which is .../build/out) to /out in container
            # This matches the pattern used in debug_subagent_task.py
            # build_dir is typically .../build/out/<project_name>
            # We want to mount .../build/out to /out
            out_dir = build_dir.parent  # This should be .../build/out
            
            # Verify all source files exist before mounting
            logger.debug(f"Verifying source files before Docker mount:")
            logger.debug(f"  Debug script:")
            logger.debug(f"    Path: {debug_script_path}")
            logger.debug(f"    Exists: {debug_script_path.exists()}")
            logger.debug(f"    Is file: {debug_script_path.is_file()}")
            logger.debug(f"    Is directory: {debug_script_path.is_dir()}")
            if debug_script_path.exists():
                logger.debug(f"    Size: {debug_script_path.stat().st_size} bytes")
                logger.debug(f"    Absolute: {debug_script_path.resolve()}")
            
            logger.info(f"  PoV input:")
            logger.debug(f"    Path: {pov_input_path}")
            logger.debug(f"    Exists: {pov_input_path.exists()}")
            logger.debug(f"    Is file: {pov_input_path.is_file()}")
            logger.debug(f"    Is directory: {pov_input_path.is_dir()}")
            if pov_input_path.exists():
                logger.debug(f"    Size: {pov_input_path.stat().st_size} bytes")
                logger.debug(f"    Absolute: {pov_input_path.resolve()}")
            
            logger.debug(f"  Build dir:")
            logger.debug(f"    Path: {build_dir}")
            logger.debug(f"    Exists: {build_dir.exists()}")
            logger.debug(f"    Is directory: {build_dir.is_dir()}")
            logger.debug(f"    Absolute: {build_dir.resolve()}")
            
            logger.info(f"  Out dir (parent of build_dir):")
            logger.debug(f"    Path: {out_dir}")
            logger.debug(f"    Exists: {out_dir.exists()}")
            logger.debug(f"    Is directory: {out_dir.is_dir()}")
            logger.debug(f"    Absolute: {out_dir.resolve()}")
            
            # Mount parent directories based on whether files are in the same directory
            if debug_script_parent == pov_input_parent:
                # Same directory - mount once to /work
                mount_dirs = {
                    pov_input_parent: Path("/work"),
                }
            else:
                # Different directories - mount both separately
                mount_dirs = {
                    debug_script_parent: Path("/work/debug"),
                    pov_input_parent: Path("/work/input"),
                }
            
            # Mount the parent directory (build/out) to /out, not the project_name subdirectory
            if out_dir.exists():
                mount_dirs[out_dir] = Path("/out")
                logger.info(f"  Using out_dir for /out mount: {out_dir}")
            else:
                # Fallback: mount build_dir directly if parent doesn't exist
                logger.warning(f"Out directory {out_dir} does not exist, falling back to mounting build_dir directly")
                mount_dirs[build_dir] = Path("/out")
                # If we mount build_dir directly, binary path should be /out/<actual_binary_name>
                binary_path = f"/out/{harness_name_for_path}"
                logger.info(f"  Using build_dir for /out mount (fallback): {build_dir}")
            
            source_path = task.get_source_path()
            if source_path and source_path.exists():
                mount_dirs[source_path] = Path("/src")
                logger.info(f"  Mounting source code: {source_path} -> /src")
            else:
                logger.warning(f"Source code path not found or doesn't exist: {source_path}")
            logger.debug(f"Final mount configuration:")
            for src, dst in mount_dirs.items():
                src_resolved = src.resolve() if hasattr(src, 'resolve') else Path(str(src)).resolve()
                dst_path = dst.resolve() if hasattr(dst, 'resolve') else Path(str(dst))
                logger.debug(f"  {src_resolved.as_posix()} -> {dst_path.as_posix()}")
                logger.debug(f"    Source exists: {src_resolved.exists()}")
                logger.debug(f"    Source is_file: {src_resolved.is_file() if src_resolved.exists() else 'N/A'}")
                logger.debug(f"    Source is_dir: {src_resolved.is_dir() if src_resolved.exists() else 'N/A'}")
                logger.debug(f"    Destination path type: {type(dst_path)}")
                logger.debug(f"    Destination as_posix(): {dst_path.as_posix()}")
                # Check if destination path looks suspicious
                if str(dst_path).endswith('/'):
                    logger.warning(f"    WARNING: Destination path ends with '/' - this might cause issues!")
                if '//' in str(dst_path):
                    logger.warning(f"    WARNING: Destination path contains '//' - this might cause issues!")
            
            logger.info(f"Container paths:")
            logger.info(f"  Debug script: {debug_script_container_path}")
            logger.info(f"  PoV input: {pov_input_container_path}")
            logger.info(f"  Binary: {binary_path}")
            logger.info("=" * 80)

            # Create the GDB command
            # Ensure all items are strings (Path objects cause join() to fail)
            gdb_cmd = [
                "gdb",
                "-batch",
                "-x",
                str(debug_script_container_path),
                "--args",
                str(binary_path),  # Ensure binary_path is also a string
                str(pov_input_container_path),
            ]
            
            logger.info("GDB command to execute in container:")
            logger.info(f"  {' '.join(gdb_cmd)}")
            logger.info(f"  Script path in container: {debug_script_container_path}")
            logger.info(f"  Binary path in container: {binary_path}")
            logger.info(f"  PoV input path in container: {pov_input_container_path}")

            # Run in debug container
            logger.info(f"Executing Docker command with:")
            logger.info(f"  Container image: {debug_container_image}")
            logger.info(f"  Number of mounts: {len(mount_dirs)}")
            logger.info(f"  Mount details logged above")
            
            # Log what the actual Docker mount command will look like
            for src, dst in mount_dirs.items():
                src_resolved = src.resolve() if hasattr(src, 'resolve') else Path(str(src)).resolve()
                dst_path = dst.resolve() if hasattr(dst, 'resolve') else Path(str(dst))
                mount_spec = f"{src_resolved.as_posix()}:{dst_path.as_posix()}"
                logger.info(f"  -v {mount_spec}")
                # Check for potential issues
                if str(dst_path).endswith('/'):
                    logger.error(f"    ERROR: Destination ends with '/' - Docker will treat this as a directory mount!")
                if ' ' in str(dst_path):
                    logger.warning(f"    WARNING: Destination contains spaces - may cause issues")
            
            # Combine GDB command with verification in the SAME container
            # This way we can see what actually happened in the container where GDB ran
            combined_cmd = [
                "bash", "-c",
                f"""
                # Run GDB
                echo "=== Running GDB ==="
                {' '.join(gdb_cmd)}
                gdb_exit_code=$?
                echo ""
                """
            ]
            
            result = task.exec_docker_cmd(
                combined_cmd,
                mount_dirs=mount_dirs,
                container_image=debug_container_image,
            )
            logger.info(f"Docker command completed:")
            logger.info(f"  Success: {result.success}")
            logger.info(f"  Return code: {result.returncode}")
            logger.info(f"  Output length: {len(result.output)} bytes")
            logger.info(f"  Error length: {len(result.error)} bytes")
            if result.error:
                logger.info(f"  Error preview: {result.error[:500].decode('utf-8', errors='ignore')}")

            if not result.success:
                return f"GDB execution failed:\nSTDOUT: {result.output.decode('utf-8', errors='ignore')}\nSTDERR: {result.error.decode('utf-8', errors='ignore')}"

            output = result.output.decode("utf-8", errors="ignore")
            error = result.error.decode("utf-8", errors="ignore")
            return f"GDB Output:\n{output}\n\nGDB Errors:\n{error}"

    def _execute_interactive_debug(
        self,
        pov_input_path: Path,
        state: DebugTaskState,
    ) -> tuple[str, list[str], list[str]]:
        """Execute interactive GDB debugging session with LLM-driven commands (interactive mode)
        
        Returns:
            Tuple of (debug_output, debug_commands, debug_reasoning) where:
            - debug_output: Combined output from all GDB commands
            - debug_commands: List of commands executed
            - debug_reasoning: List of LLM reasoning for each command
        """
        # Get a writable copy of the task
        with self.reproduce_multiple.open() as mult:
            if mult.builds_cache is None or not mult.builds_cache:
                raise ValueError("Build cache not available")
            
            # Use the harness name from the PoV's harness (not self.task.harness_name)
            # Note: self.task.harness_name should be the same as state.harness.harness_name
            # since the harness was retrieved using self.task.harness_name in _init_state().
            # However, using state.harness.harness_name is more explicit and defensive.
            harness_name = state.harness.harness_name
            
            # Select a build that contains the harness binary
            # Prefer address sanitizer builds, but verify the harness exists in the selected build
            # All builds for the same project share the same build directory,
            # but we prefer asan since it's most common and provides better crash detection
            task = None
            selected_build = None
            
            # First, try to find an address sanitizer build with the harness
            for build, cached_task in zip(mult.build_outputs, mult.builds_cache, strict=False):
                if build.sanitizer == "address":
                    build_dir = cached_task.get_build_dir()
                    if build_dir and build_dir.exists():
                        # Check if harness exists (debug or regular binary)
                        debug_binary_path = cached_task.get_debug_binary_path(harness_name)
                        regular_binary_path = build_dir / harness_name
                        if (debug_binary_path and debug_binary_path.exists()) or regular_binary_path.exists():
                            task = cached_task
                            selected_build = build
                            logger.info(f"Using address sanitizer build with harness '{harness_name}' (task_id: {build.task_id})")
                            break
            
            # If no asan build with harness found, try any build with the harness
            if task is None:
                for build, cached_task in zip(mult.build_outputs, mult.builds_cache, strict=False):
                    build_dir = cached_task.get_build_dir()
                    if build_dir and build_dir.exists():
                        # Check if harness exists (debug or regular binary)
                        debug_binary_path = cached_task.get_debug_binary_path(harness_name)
                        regular_binary_path = build_dir / harness_name
                        if (debug_binary_path and debug_binary_path.exists()) or regular_binary_path.exists():
                            task = cached_task
                            selected_build = build
                            logger.info(f"Using build with harness '{harness_name}' (task_id: {build.task_id}, sanitizer: {build.sanitizer})")
                            break
            
            # If still no build found, fallback to first build (will fail later if harness doesn't exist)
            if task is None:
                task = mult.builds_cache[0]
                selected_build = mult.build_outputs[0]
                logger.warning(f"No build found with harness '{harness_name}', using first build (task_id: {selected_build.task_id}). This may fail if harness doesn't exist.")
            
            debug_container_image = "gcr.io/oss-fuzz-base/base-runner-debug"

            # Resolve paths
            logger.info(f"Pre-resolve PoV input path: {pov_input_path} (is_absolute: {pov_input_path.is_absolute()})")
            pov_input_path = pov_input_path.resolve()
            logger.info(f"Post-resolve PoV input path: {pov_input_path}")
            
            # Verify PoV input file exists and is accessible
            logger.info(f"Verifying PoV input file before Docker mount:")
            logger.info(f"  Path: {pov_input_path}")
            logger.info(f"  Exists: {pov_input_path.exists()}")
            logger.info(f"  Is file: {pov_input_path.is_file()}")
            logger.info(f"  Is directory: {pov_input_path.is_dir()}")
            if not pov_input_path.exists():
                raise ValueError(f"PoV input file does not exist: {pov_input_path}")
            if not pov_input_path.is_file():
                raise ValueError(f"PoV input path is not a file: {pov_input_path}")
            if pov_input_path.exists():
                logger.info(f"  Size: {pov_input_path.stat().st_size} bytes")
                logger.info(f"  Absolute: {pov_input_path.resolve()}")
            
            # Get build directory and binary path
            build_dir = task.get_build_dir()
            if not build_dir or not build_dir.exists():
                raise ValueError(f"Build directory not found or doesn't exist: {build_dir}")
            
            # Try to use debug binary first, fallback to regular binary
            debug_binary_path = task.get_debug_binary_path(harness_name)
            using_debug_binary = False
            if debug_binary_path and debug_binary_path.exists():
                harness_binary_path = debug_binary_path
                using_debug_binary = True
                logger.info(f"Using debug binary with full symbols: {harness_binary_path}")
            else:
                harness_binary_path = build_dir / harness_name
                if not harness_binary_path.exists():
                    available_files = [f.name for f in build_dir.iterdir()] if build_dir.is_dir() else []
                    raise ValueError(
                        f"Harness binary '{harness_name}' not found in {build_dir}. "
                        f"Available files: {available_files}"
                    )
                logger.info(f"Using regular production binary (debug binary not available): {harness_binary_path}")
            
            # Ensure binary has execute permissions
            current_perms = harness_binary_path.stat().st_mode
            harness_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            
            # Determine binary path in container
            project_name = build_dir.name
            if using_debug_binary:
                binary_path = f"/out/{project_name}/debug/{harness_name}"
            else:
                binary_path = f"/out/{project_name}/{harness_name}"
            
            # Set up mount directories
            pov_input_parent = pov_input_path.parent
            pov_input_container_path = f"/work/{pov_input_path.name}"
            out_dir = build_dir.parent
            
            logger.info(f"Container paths (targets in container):")
            logger.info(f"  PoV input: {pov_input_container_path}")
            logger.info(f"  Binary: {binary_path}")
            logger.info(f"  PoV input parent (host): {pov_input_parent}")
            logger.info(f"  PoV input parent (container): /work")
            logger.info(f"  PoV input file name: {pov_input_path.name}")
            
            mount_dirs = {
                pov_input_parent: Path("/work"),
            }
            if out_dir.exists():
                mount_dirs[out_dir] = Path("/out")
            else:
                mount_dirs[build_dir] = Path("/out")
                binary_path = f"/out/{harness_name}"
            
            source_path = task.get_source_path()
            if source_path and source_path.exists():
                mount_dirs[source_path] = Path("/src")
                logger.info(f"  Mounting source code: {source_path} -> /src")
            else:
                logger.warning(f"Source code path not found or doesn't exist: {source_path}")
            
            logger.info(f"Mount directories:")
            for host_path, container_path in mount_dirs.items():
                logger.info(f"  {host_path} -> {container_path}")

            # Read first 4 bytes to check if it's an ELF binary (magic: 7f 45 4c 46)
            try:
                with open(harness_binary_path, 'rb') as f:
                    magic = f.read(4)
                    is_elf = magic == b'\x7fELF'
            except Exception:
                is_elf = False
            
            binary_size = harness_binary_path.stat().st_size
            logger.info(f"Found harness binary: {harness_binary_path}")
            logger.info(f"  Permissions: {oct(harness_binary_path.stat().st_mode)}")
            logger.info(f"  Size: {binary_size} bytes")
            logger.info(f"  Is ELF binary: {is_elf}")
            
            
            # If the file is not an ELF binary or is suspiciously small, it might be a wrapper script
            # Try to find the actual binary. Wrapper scripts often have suffixes like _nalloc, _asan, etc.
            # The actual binary is usually the base harness name without the suffix
            actual_binary_path = harness_binary_path
            actual_binary_name = harness_name
            if not is_elf or binary_size < 1024:
                logger.warning(
                    f"File '{harness_name}' appears to be a wrapper script (size={binary_size}, is_elf={is_elf}). "
                    f"Searching for actual ELF binary..."
                )
                
                # Try to find the actual binary by looking for ELF files in the build directory
                # Priority: 1) Base name without suffix, 2) Any ELF file with base name as prefix
                base_name = harness_name
                # Remove common sanitizer suffixes
                for suffix in ['_nalloc', '_asan', '_msan', '_ubsan', '_tsan', '_hwasan']:
                    if base_name.endswith(suffix):
                        base_name = base_name[:-len(suffix)]
                        break
                
                # First, try the base name directly
                candidate_path = build_dir / base_name
                if candidate_path.exists() and candidate_path.is_file():
                    try:
                        with open(candidate_path, 'rb') as f:
                            candidate_magic = f.read(4)
                            candidate_is_elf = candidate_magic == b'\x7fELF'
                        candidate_size = candidate_path.stat().st_size
                        if candidate_is_elf and candidate_size > 1024:
                            logger.info(
                                f"Found actual binary: {base_name} (size={candidate_size}, is_elf={candidate_is_elf}). "
                                f"Using this instead of wrapper '{harness_name}'."
                            )
                            actual_binary_path = candidate_path
                            actual_binary_name = base_name
                            # Set execute permissions
                            current_perms = actual_binary_path.stat().st_mode
                            actual_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    except Exception as e:
                        logger.debug(f"Error checking candidate {base_name}: {e}")
                
                # If base name didn't work, search for any ELF file with base name as prefix
                if actual_binary_path == harness_binary_path and build_dir.is_dir():
                    for candidate in build_dir.iterdir():
                        if candidate.is_file() and candidate != harness_binary_path:
                            if candidate.name.startswith(base_name):
                                try:
                                    with open(candidate, 'rb') as f:
                                        candidate_magic = f.read(4)
                                        candidate_is_elf = candidate_magic == b'\x7fELF'
                                    candidate_size = candidate.stat().st_size
                                    if candidate_is_elf and candidate_size > 1024:
                                        logger.info(
                                            f"Found actual binary: {candidate.name} (size={candidate_size}, is_elf={candidate_is_elf}). "
                                            f"Using this instead of wrapper '{harness_name}'."
                                        )
                                        actual_binary_path = candidate
                                        actual_binary_name = candidate.name
                                        # Set execute permissions
                                        current_perms = actual_binary_path.stat().st_mode
                                        actual_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                                        break
                                except Exception:
                                    pass
            
            # Use the actual binary (or original if it was already valid)
            harness_binary_path = actual_binary_path
            harness_name_for_path = actual_binary_name

            project_name = build_dir.name
            binary_path = actual_binary_name
            # Binary path in container: /out/<project_name>/<actual_binary_name>
            # If using debug binary, it's in /out/<project_name>/debug/<actual_binary_name>
            # Use the actual binary name (which may differ from harness_name if it was a wrapper)
            if using_debug_binary:
                binary_path = f"/out/{project_name}/debug/{harness_name_for_path}"
            else:
                binary_path = f"/out/{project_name}/{harness_name_for_path}"
            # Create InteractiveGDBDocker session
            logger.info("Creating interactive GDB session")
            logger.info(f"GDB command will be: gdb -q --interpreter=mi2 --args {binary_path} {pov_input_container_path}")
            logger.info(f"  Binary path in container: {binary_path}")
            logger.info(f"  Seed file path in container: {pov_input_container_path}")
            logger.info(f"  Seed file should be accessible at: {pov_input_container_path}")

            with tempfile.TemporaryDirectory(dir=state.current_dir) as scratchpad_dir_str:
                # Note: InteractiveGDBDocker will automatically mount scratchpad_dir to /scratchpad
                # if it's not already mounted, so we don't need to add it to mount_dirs here
                gdb_session = InteractiveGDBDocker(
                    container_image=debug_container_image,
                    mount_dirs=mount_dirs,
                    binary_path=binary_path,
                    input_path=pov_input_container_path,
                    scratchpad_dir=Path(scratchpad_dir_str),
                )
                
                try:
                    # Start the GDB session
                    gdb_session.run()
                    logger.info("GDB session started")
                    
                    # Initial setup commands
                    setup_commands = [
                        "set breakpoint pending on",
                        "set print elements 0",
                        "set print pretty on",
                        "set pagination off",
                        "set verbose off",
                    ]
                    
                    all_output_lines: list[str] = []
                    executed_commands: list[str] = []
                    debug_reasoning: list[str] = []
                    # Run setup commands
                    for cmd in setup_commands:
                        logger.info(f"Setup: {cmd}")
                        result = gdb_session.console(cmd, timeout=5.0)
                        all_output_lines.extend(result.lines)
                        executed_commands.append(cmd)
                    
                    # Interactive loop with LLM (depth 10)
                    command_count = 0
                    session_history: list[str] = []
                    
                    while command_count < self.MAX_INTERACTIVE_COMMANDS:
                        # Build prompt for next command
                        history_text = "\n\n".join(session_history[-30:]) if session_history else "No commands executed yet"
                        
                        # Get harness from state if available, otherwise use task
                        harness_str = str(state.harness) if hasattr(state, 'harness') and state.harness else str(self.task.harness_name)
                        prev_cmd_output = "\n".join(all_output_lines[-30:]) if all_output_lines else "No commands executed yet"
                        if state.debug_script:
                            prev_debug_attempt = f""" We attempted a batch debug session before, and determined that more context and a new interactive debug session are needed to answer the query.
                            Here is the previous debug attempt:
                            <previous_debug_attempt>
                            {state.debug_script}
                            </previous_debug_attempt>
                            Here is the previous debug output:
                            <previous_debug_output>
                            {state.debug_script_output}
                            </previous_debug_output>
                            """
                        else:
                            prev_debug_attempt = ""
                        prompt_vars = {
                            "harness": harness_str,
                            "debug_context": state.debug_context if hasattr(state, 'debug_context') else "Interactive debugging session",
                            "analysis": state.analysis if hasattr(state, 'analysis') and state.analysis else "Use GDB to investigate program execution",
                            "session_history": history_text,
                            "commands_remaining": self.MAX_INTERACTIVE_COMMANDS - command_count,
                            "prev_debug_attempt": prev_debug_attempt,
                            "prev_cmd_output": prev_cmd_output,
                        }
                        logger.debug("history_text: %s", history_text)
                        
                        # Prompt LLM for next command
                        next_command_prompt = ChatPromptTemplate.from_messages([
                            ("system", DEBUG_INTERACTIVE_COMMAND_SYSTEM_PROMPT),
                            ("human", DEBUG_INTERACTIVE_COMMAND_USER_PROMPT),
                        ])
                        
                        chain = next_command_prompt | self.task.llm | StrOutputParser()
                        llm_response = chain.invoke(prompt_vars)
                        logger.debug("llm_response: %s", llm_response)
                        debug_reasoning.append(llm_response)
                        # Extract command from string response (StrOutputParser returns a string)
                        # Try to extract code block, otherwise use the response as-is
                        try:
                            # extract_code expects AIMessage, but we have a string
                            # Create a temporary AIMessage for extraction
                            temp_msg = AIMessage(content=llm_response)
                            next_command = extract_code(temp_msg)
                        except Exception:
                            # If extraction fails, try simple regex for code blocks
                            code_match = re.search(r"```(?:gdb)?\n(.*?)```", llm_response, re.DOTALL)
                            if code_match:
                                next_command = code_match.group(1).strip()
                            else:
                                # No code block, use the response directly (might be "quit" or a command)
                                next_command = llm_response.strip()
                        
                        if not next_command or next_command.lower() in ["quit", "done", "exit", "q"]:
                            logger.info("LLM indicated debugging complete")
                            break
                        
                        # Split multi-line commands and execute each line individually
                        # Filter out comment lines (they cause errors in GDB MI)
                        command_lines = [
                            line.strip() 
                            for line in next_command.split("\n") 
                            if line.strip() and not line.strip().startswith('#')
                        ]
                        logger.info(f"Executing GDB command(s) [{command_count + 1}/{self.MAX_INTERACTIVE_COMMANDS}]: {len(command_lines)} line(s)")
                        logger.debug(f"Command lines: {command_lines}")
                        
                        found_quit = False
                        #checking for quit in the command lines
                        for command in command_lines:
                            if command.lower() in ["quit", "done", "exit", "q"]:
                                found_quit = True
                                break
                        
                        result = gdb_session.process_commands(command_lines)
                        all_output_lines.extend(result)
                        executed_commands.extend(command_lines)
                        command_count += 1
                        # Log the block of commands being sent and output received
                        logger.info(f"Sent GDB command block:\n{command_lines}")
                        logger.info(f"Received GDB output:\n{result}")
                        
                        
                        if result:
                            session_history.append("\n".join(result))

                        logger.info(f"Session history: {session_history}")
                        
                        # If we hit quit in a command line, break out of the main loop
                        if found_quit:
                            break
                    
                    # Finalize output
                    debug_output = "\n".join(all_output_lines)
                    logger.info(f"Interactive debug session completed: {command_count} commands executed")
                    
                    return debug_output, executed_commands, debug_reasoning
                    
                finally:
                    # Clean up
                    try:
                        gdb_session.close()
                    except Exception as e:
                        logger.warning(f"Error closing GDB session: {e}")

    def _validate_pov(self, state: DebugTaskState) -> Command:
        """Validate if the PoV causes a crash"""
        logger.info("Validating PoV")
        try:
            # Use reproduce_multiple to test the PoV
            with self.reproduce_multiple.open() as mult:
                pov_valid = False
                for build, result in mult.get_crashes(state.pov_input_path, state.harness.harness_name):
                    # If we get here, the PoV caused a crash
                    pov_valid = result.did_crash()
                    break

                # Store the debug attempt
                debug_script = state.debug_script if state.debug_script else ""
                if not debug_script and state.debug_commands:
                    debug_script = "\n".join(state.debug_commands)
                
                debug_attempt = DebugAttempt(
                    analysis=state.analysis,
                    debug_script=debug_script,
                    debug_output=state.debug_script_output,
                    pov_valid=pov_valid,
                )

                return Command(
                    update={
                        "pov_valid": pov_valid,
                        "debug_attempts": [debug_attempt],
                        "debug_iteration": state.debug_iteration + 1,
                    },
                )

        except ChallengeTaskError as exc:
            logger.error(f"Error validating PoV: {exc}")
            debug_script = state.debug_script if state.debug_script else ""
            if not debug_script and state.debug_commands:
                debug_script = "\n".join(state.debug_commands)
            debug_attempt = DebugAttempt(
                analysis=state.analysis,
                debug_script=debug_script,
                debug_output=state.debug_script_output,
                pov_valid=False,
            )
            return Command(
                update={
                    "pov_valid": False,
                    "debug_attempts": [debug_attempt],
                    "debug_iteration": state.debug_iteration + 1,
                },
            )

    def _continue_debug(self, state: DebugTaskState) -> bool:
        """Determine whether to continue debugging"""
        # Continue if PoV is not valid and we haven't exceeded max iterations
        return not state.pov_valid and state.debug_iteration < self.MAX_DEBUG_ITERATIONS

    def _continue_context_retrieval(self, state: DebugTaskState) -> bool:
        """Determine if we should continue the context retrieval iteration"""
        return state.context_iteration < self.MAX_CONTEXT_ITERATIONS

    def _continue_context_retrieval_again(self, state: DebugTaskState) -> bool:
        """Determine if we should continue the context retrieval iteration"""
        return state.context_iteration_again < self.MAX_CONTEXT_ITERATIONS_AGAIN

    def _build_workflow(self, mode: DebugMode) -> StateGraph:
        """Build the workflow for the debug task"""
        workflow = StateGraph(DebugTaskState)

        workflow.add_node("get_context", self._get_context)
        tool_node = ToolNode(self.debug_tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_debug", self._analyze_debug)
        
        if mode == DebugMode.BATCH or mode == DebugMode.HYBRID:
            # Batch mode workflow
            workflow.add_node("write_debug_script", self._write_debug_script)
            workflow.add_node("run_debug_script", self._run_debug_script)
        if mode == DebugMode.HYBRID:
            # Hybrid mode workflow
            workflow.add_node("needs_interactive_follow_up", self._needs_interactive_follow_up)
            workflow.add_node("gather_context_again", self._get_context)
            workflow.add_node("tools_again", tool_node)
        if mode == DebugMode.INTERACTIVE or mode == DebugMode.HYBRID:
            # Interactive mode workflow
            workflow.add_node("run_interactive_debug", self._run_interactive_debug)
        
        workflow.add_node("reflect_debug", self._reflect_debug)
        
        workflow.set_entry_point("get_context")
        workflow.add_edge("get_context", "tools")
        workflow.add_conditional_edges(
            "tools",
            self._continue_context_retrieval,
            {
                True: "get_context",
                False: "analyze_debug",
            },
        )

        if mode == DebugMode.BATCH:
            workflow.add_edge("analyze_debug", "write_debug_script")
            workflow.add_edge("write_debug_script", "run_debug_script")
            workflow.add_edge("run_debug_script", "reflect_debug")
        elif mode == DebugMode.INTERACTIVE:
            workflow.add_edge("analyze_debug", "run_interactive_debug")
            workflow.add_edge("run_interactive_debug", "reflect_debug")
        elif mode == DebugMode.HYBRID:
            workflow.add_edge("analyze_debug", "write_debug_script")
            workflow.add_edge("write_debug_script", "run_debug_script")
            workflow.add_edge("run_debug_script", "needs_interactive_follow_up")
            workflow.add_conditional_edges(
                "needs_interactive_follow_up",
                self._continue_interactive_follow_up,
                {
                    True: "gather_context_again",
                    False: "reflect_debug",
                },
            )

            workflow.add_edge("gather_context_again", "tools_again")
            workflow.add_conditional_edges(
                "tools_again",
                self._continue_context_retrieval,
                {
                    True: "gather_context_again",
                    False: "run_interactive_debug",
                },
            )
            workflow.add_edge("run_interactive_debug", "reflect_debug")

        workflow.add_edge("reflect_debug", END)


        return workflow

    def _recursion_limit(self, mode: DebugMode) -> int:
        """Calculate recursion limit for the workflow
        
        The workflow structure:
        1. Context gathering phase: get_context -> tools (can loop multiple times)
           - Each tool call from the LLM counts as a step
           - Can have multiple tool calls per iteration
        2. Debug phase: 
           - Batch: analyze_debug -> write_debug_script -> run_debug_script -> reflect_debug
           - Interactive: analyze_debug -> run_interactive_debug -> reflect_debug
           - Hybrid: analyze_debug -> write_debug_script -> run_debug_script -> needs_interactive_follow_up 
                    -> (if yes) gather_context_again -> tools_again -> run_interactive_debug -> reflect_debug
                    -> (if no) reflect_debug
        3. Validation phase (if not skipped): validate_pov -> (maybe loop back)
        
        We need to be generous with the limit because tool calls add up quickly.
        """
        # Each context iteration: get_context (1) + tools (N tool calls) 
        # Estimate max tool calls per context iteration
        context_steps_per_iteration = 1 + self.ESTIMATED_TOOLS_PER_CONTEXT
        context_total = context_steps_per_iteration * self.MAX_CONTEXT_ITERATIONS
        
        if self.skip_validation:
            if mode == DebugMode.BATCH:
                # Single debug pass: analyze + write + run + reflect
                debug_steps = 4
            elif mode == DebugMode.INTERACTIVE:
                # Single debug pass: analyze + run_interactive + reflect
                # Interactive loop adds MAX_INTERACTIVE_COMMANDS LLM calls
                debug_steps = 3 + self.MAX_INTERACTIVE_COMMANDS
            else:  # HYBRID
                # Hybrid: batch phase + potentially interactive phase
                # Batch: analyze + write + run + needs_interactive_follow_up (4)
                # If interactive needed: gather_context_again + tools_again (can loop) + run_interactive + reflect
                # Worst case: batch (4) + context_again (1 + tools) + interactive (MAX_INTERACTIVE_COMMANDS) + reflect (1)
                batch_steps = 4  # analyze + write + run + needs_interactive_follow_up
                interactive_context_steps = context_steps_per_iteration  # gather_context_again + tools_again (worst case one iteration)
                interactive_steps = 1 + self.MAX_INTERACTIVE_COMMANDS  # run_interactive_debug
                reflect_step = 1  # reflect_debug
                debug_steps = batch_steps + interactive_context_steps + interactive_steps + reflect_step
            return 1 + context_total + debug_steps
        else:
            # Full validation loop with retries
            if mode == DebugMode.BATCH:
                debug_steps = 5  # analyze + write + run + reflect + validate
            elif mode == DebugMode.INTERACTIVE:
                # Interactive loop adds MAX_INTERACTIVE_COMMANDS LLM calls per iteration
                debug_steps = 4 + self.MAX_INTERACTIVE_COMMANDS  # analyze + interactive_loop + reflect + validate
            else:  # HYBRID
                # Hybrid: batch phase + potentially interactive phase + validation
                # Batch: analyze + write + run + needs_interactive_follow_up (4)
                # If interactive needed: gather_context_again + tools_again + run_interactive + reflect (worst case)
                # Validation: validate_pov (1)
                batch_steps = 4  # analyze + write + run + needs_interactive_follow_up
                interactive_context_steps = context_steps_per_iteration  # gather_context_again + tools_again (worst case one iteration)
                interactive_steps = 1 + self.MAX_INTERACTIVE_COMMANDS  # run_interactive_debug
                reflect_step = 1  # reflect_debug
                validate_step = 1  # validate_pov
                debug_steps = batch_steps + interactive_context_steps + interactive_steps + reflect_step + validate_step
            return 1 + context_total + debug_steps * self.MAX_DEBUG_ITERATIONS

    def _needs_interactive_follow_up(self, state: DebugTaskState) -> Command:
        """Use LLM to determine if an interactive debugging follow-up is needed after batch mode"""
        logger.info("Checking if interactive debugging follow-up is needed")
        
        # Don't run interactive if PoV is already valid or we've exceeded max iterations
        if state.pov_valid:
            logger.info("PoV is valid, skipping interactive follow-up")
            return Command(update={"needs_interactive_follow_up": False})
        
        if state.debug_iteration >= self.MAX_DEBUG_ITERATIONS:
            logger.info("Max debug iterations reached, skipping interactive follow-up")
            return Command(update={"needs_interactive_follow_up": False})
        
        # Use LLM to analyze batch results and determine if interactive follow-up is needed
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "analysis": state.analysis,
            "debug_script": state.debug_script,
            "debug_output": state.debug_script_output,
            "pov_valid": state.pov_valid,
            "previous_attempts": state.format_debug_attempts(),
        }
        
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", DEBUG_INTERACTIVE_FOLLOW_UP_SYSTEM_PROMPT),
                ("human", DEBUG_INTERACTIVE_FOLLOW_UP_USER_PROMPT),
            ],
        )
        chain = prompt | self.task.llm | StrOutputParser()
        
        try:
            response = chain.invoke(prompt_vars).strip().lower()
            logger.info(f"LLM response for interactive follow-up decision: {response}")
            
            # Parse response - should be "yes" or "no"
            needs_follow_up = response == "yes"
            
            logger.info(f"Determined interactive follow-up needed: {needs_follow_up}")
            return Command(update={"needs_interactive_follow_up": needs_follow_up})
        except Exception as e:
            logger.error(f"Error determining interactive follow-up: {e}")
            # Default to False on error
            return Command(update={"needs_interactive_follow_up": False})
    
    def _continue_interactive_follow_up(self, state: DebugTaskState) -> bool:
        """Determine whether to continue with interactive follow-up based on LLM decision"""
        return state.needs_interactive_follow_up