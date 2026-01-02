"""Debug subagent utility for debugging PoVs with GDB scripts.

This is a utility that can be called by other tasks (like vuln_discovery) to debug
PoV inputs and investigate why they might not be working.
"""

import logging
import operator
import stat
import tempfile
from dataclasses import dataclass
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
    DEBUG_REFLECT_SYSTEM_PROMPT,
    DEBUG_REFLECT_USER_PROMPT,
)
from buttercup.seed_gen.utils import extract_code
from buttercup.seed_gen.task import BaseTaskState, Task

logger = logging.getLogger(__name__)


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
    """Result of a debug session"""

    pov_valid: bool
    debug_script: str
    debug_output: str
    analysis: str
    reflection: str
    attempts: list[DebugAttempt]


class DebugTaskState(BaseTaskState):
    """State for the debug task"""

    debug_context: str = Field(
        description="Articulated context about what to test and verify",
        default="",
    )
    pov_input_path: Path = Field(
        description="Path to the PoV input file",
    )
    analysis: str = Field(description="The analysis of the debugging task", default="")
    debug_output: str = Field(description="Output from running the interactive debug session", default="")
    debug_commands: list[str] = Field(description="List of GDB commands executed", default_factory=list)
    reflection: str = Field(description="Reflection on what happened during execution and how it relates to the vulnerability", default="")
    pov_valid: bool = Field(description="Whether the PoV is valid (causes a crash)", default=False)
    debug_iteration: int = Field(description="Count of debug iterations", default=0)
    debug_attempts: Annotated[list[DebugAttempt], operator.add] = Field(default_factory=list)

    def format_debug_attempts(self) -> str:
        """Format debug attempts for prompts"""
        return "\n\n".join(str(attempt) for attempt in self.debug_attempts)


class DebugSubagentInteractive:
    """Utility for debugging PoVs with GDB scripts.

    This can be called by other tasks to debug PoV inputs and investigate
    why they might not be working as expected.
    """

    MAX_DEBUG_ITERATIONS = 2
    MAX_CONTEXT_ITERATIONS = 3
    MAX_INTERACTIVE_COMMANDS = 10  # Depth of interactive debug loop
    # Each context iteration can have multiple tool calls (get_context -> tools)
    # Estimate ~5 tool calls per context iteration to be safe
    ESTIMATED_TOOLS_PER_CONTEXT = 5

    def __init__(
        self,
        task: Task,
        reproduce_multiple: ReproduceMultiple,
        skip_validation: bool = False,
    ):
        """Initialize the debug subagent.

        Args:
            task: The parent task (provides LLM, tools, codequery, etc.)
            reproduce_multiple: Used to validate PoVs and run debug containers
            skip_validation: If True, skip PoV validation and only run debug once
        """
        self.task = task
        self.reproduce_multiple = reproduce_multiple
        self.skip_validation = skip_validation

    def debug(
        self,
        harness: HarnessInfo,
        pov_input_path: Path,
        debug_context: str,
        output_dir: Path | None = None,
    ) -> DebugResult:
        """Debug a PoV input.

        Args:
            harness: The harness to target
            pov_input_path: Path to the PoV input file (actual input bytes, not script)
            debug_context: Articulated context about what to test/verify
            output_dir: Optional directory to write debug results to

        Returns:
            DebugResult with debug information and validation status
        """
        logger.info(
            "Starting debug session for harness: %s | pov_input: %s",
            harness,
            pov_input_path,
        )

        # Create temporary output directory if not provided
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp(prefix="debug-"))

        try:
            logger.info("Creating debug state")
            state = DebugTaskState(
                harness=harness,
                task=self.task,
                output_dir=output_dir,
                pov_input_path=pov_input_path,
                debug_context=debug_context,
            )
            logger.info("Debug state created successfully")

            logger.info("Building debug workflow")
            workflow = self._build_workflow()
            logger.info("Getting Langfuse callbacks")
            llm_callbacks = get_langfuse_callbacks()
            logger.info("Compiling workflow with recursion_limit=%d", self._recursion_limit())
            chain = workflow.compile().with_config(
                RunnableConfig(
                    tags=["debug-subagent"],
                    callbacks=llm_callbacks,
                    recursion_limit=self._recursion_limit(),
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
                    },
                )

                # Run the workflow
                logger.info("Invoking debug workflow chain")
                final_state = chain.invoke(state)  # type: ignore[arg-type]
                logger.info("Debug workflow chain completed")

                # Get values from state (final_state is a dict)
                debug_output = final_state.get("debug_output", "") or ""
                debug_commands = final_state.get("debug_commands", [])
                analysis = final_state.get("analysis", "") or ""
                reflection = final_state.get("reflection", "") or ""
                pov_valid = final_state.get("pov_valid", False)
                debug_attempts = final_state.get("debug_attempts", [])

                logger.info(
                    "Debug state extracted: analysis_len=%d, commands=%d, output_len=%d, reflection_len=%d, attempts=%d",
                    len(analysis),
                    len(debug_commands),
                    len(debug_output),
                    len(reflection),
                    len(debug_attempts),
                )

                # Write results to output directory if provided
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    if debug_commands:
                        (output_dir / "debug_commands.txt").write_text("\n".join(debug_commands))
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
                    pov_valid=pov_valid,
                    debug_script="",  # No script in interactive mode
                    debug_output=debug_output,
                    analysis=analysis,
                    reflection=reflection,
                    attempts=debug_attempts,
                )

        except Exception as err:
            logger.exception("Failed debug session: %s", str(err))
            return DebugResult(
                pov_valid=False,
                debug_script="",
                debug_output=f"Error: {str(err)}",
                analysis="",
                reflection="",
                attempts=[],
            )

    def _get_context(self, state: DebugTaskState) -> Command:
        """Get context about the codebase for debugging"""
        logger.info("Getting context for debugging")
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "retrieved_context": state.format_retrieved_context(),
        }
        res = self.task._get_context_base(
            DEBUG_GET_CONTEXT_SYSTEM_PROMPT,
            DEBUG_GET_CONTEXT_USER_PROMPT,
            state,
            prompt_vars,
        )
        return res

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

    def _run_interactive_debug(self, state: DebugTaskState) -> Command:
        """Run interactive GDB debugging session with LLM-driven commands"""
        logger.info("Starting interactive debug session")
        
        try:
            debug_output, debug_commands = self._execute_interactive_debug(state.pov_input_path, state)
            return Command(update={
                "debug_output": debug_output,
                "debug_commands": debug_commands,
            })
        except Exception as e:
            logger.error(f"Error running interactive debug: {e}")
            return Command(update={
                "debug_output": f"Error: {str(e)}",
                "debug_commands": [],
            })

        

    def _reflect_debug(self, state: DebugTaskState) -> Command:
        """Reflect on the debug output and summarize what happened"""
        logger.info("Reflecting on debug output")
        # For interactive mode, there's no debug_script, so provide a placeholder
        debug_script = "Interactive GDB session - commands executed interactively"
        if state.debug_commands:
            debug_script = "\n".join(state.debug_commands)
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "analysis": state.analysis,
            "debug_output": state.debug_output,
            "debug_script": debug_script,
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

    def _execute_interactive_debug(
        self,
        pov_input_path: Path,
        state: DebugTaskState,
    ) -> tuple[str, list[str]]:
        """Execute interactive GDB debugging session with LLM-driven commands.
        
        Returns:
            Tuple of (debug_output, debug_commands) where:
            - debug_output: Combined output from all GDB commands
            - debug_commands: List of commands executed
        """
        # Get a writable copy of the task
        with self.reproduce_multiple.open() as mult:
            if mult.builds_cache is None or not mult.builds_cache:
                raise ValueError("Build cache not available")
            task = mult.builds_cache[0]

            # Get the fuzzer binary path (typically in /out)
            harness_name = self.task.harness_name
            debug_container_image = "gcr.io/oss-fuzz-base/base-runner-debug"

            # Resolve paths
            pov_input_path = pov_input_path.resolve()
            
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
                logger.info(f"Using regular production binary (debug binary not available): {harness_binary_path}")
                binary_path = f"/out/{project_name}/{harness_name}"
            
            # Set up mount directories
            pov_input_parent = pov_input_path.parent
            pov_input_container_path = f"/work/{pov_input_path.name}"
            out_dir = build_dir.parent
            
            mount_dirs = {
                pov_input_parent: Path("/work"),
            }
            if out_dir.exists():
                mount_dirs[out_dir] = Path("/out")
            else:
                mount_dirs[build_dir] = Path("/out")
                binary_path = f"/out/{harness_name}"

            # Read first 4 bytes to check if it's an ELF binary (magic: 7f 45 4c 46)
            # TODO: This is brittle, and should be moved to a helper function.
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
            gdb_session = InteractiveGDBDocker(
                container_image=debug_container_image,
                mount_dirs=mount_dirs,
                binary_path=binary_path,
                input_path=pov_input_container_path,
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
                ]
                
                all_output_lines: list[str] = []
                executed_commands: list[str] = []
                
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
                    history_text = "\n\n".join(session_history[-5:]) if session_history else "No commands executed yet"
                    
                    # Get harness from state if available, otherwise use task
                    harness_str = str(state.harness) if hasattr(state, 'harness') and state.harness else str(self.task.harness_name)
                    
                    prompt_vars = {
                        "harness": harness_str,
                        "debug_context": state.debug_context if hasattr(state, 'debug_context') else "Interactive debugging session",
                        "analysis": state.analysis if hasattr(state, 'analysis') and state.analysis else "Use GDB to investigate program execution",
                        "session_history": history_text,
                        "commands_remaining": self.MAX_INTERACTIVE_COMMANDS - command_count,
                    }
                    
                    # Prompt LLM for next command
                    next_command_prompt = ChatPromptTemplate.from_messages([
                        ("system", """You are debugging a program with GDB to understand why a PoV input doesn't crash as expected.

Debug goal: {debug_context}

Analysis: {analysis}

Based on the session history, suggest the NEXT GDB command or set of commands to run. 
- Respond optionally with a short explanation of why you're running this command, and the GDB command itself. 
- The gdb command or set of commands should be wrapped in ```gdb and ``` to be parsed as a single command.
- Common commands: break <function>, run, continue, bt, print <var>, x/<format> <addr>, info registers
- If you've gathered enough information, respond with 'quit'
- Be aware that symbol names may not be avaliable, or may be modified by the compiler.
)"""),
                        ("human", "Harness:\n{harness}\n\nSession history:\n{session_history}\n\nCommands remaining: {commands_remaining}\n\nNext GDB command:"),
                    ])
                    
                    chain = next_command_prompt | self.task.llm | StrOutputParser()
                    llm_response = chain.invoke(prompt_vars)
                    
                    # Extract command from string response (StrOutputParser returns a string)
                    # Try to extract code block, otherwise use the response as-is
                    try:
                        # extract_code expects AIMessage, but we have a string
                        # Create a temporary AIMessage for extraction
                        temp_msg = AIMessage(content=llm_response)
                        next_command = extract_code(temp_msg)
                    except Exception:
                        # If extraction fails, try simple regex for code blocks
                        import re
                        code_match = re.search(r"```(?:gdb)?\n(.*?)```", llm_response, re.DOTALL)
                        if code_match:
                            next_command = code_match.group(1).strip()
                        else:
                            # No code block, use the response directly (might be "quit" or a command)
                            next_command = llm_response.strip()
                    
                    if not next_command or next_command.lower() in ["quit", "done", "exit", "q"]:
                        logger.info("LLM indicated debugging complete")
                        break
                    
                    # Execute command
                    logger.info(f"Executing GDB command [{command_count + 1}/{self.MAX_INTERACTIVE_COMMANDS}]: {next_command}")
                    try:
                        result = gdb_session.console(next_command, timeout=10.0)
                        output_text = "\n".join(result.lines)
                        logger.info(f"GDB command output: {output_text}")
                        session_history.append(f"Command: {next_command}\nOutput:\n{output_text}")
                        all_output_lines.extend([f"Command: {next_command}"] + result.lines)
                        executed_commands.append(next_command)
                        command_count += 1
                    except Exception as e:
                        error_msg = f"Error executing command: {str(e)}"
                        logger.error(error_msg)
                        session_history.append(f"Command: {next_command}\nError: {error_msg}")
                        all_output_lines.extend([f"Command: {next_command}", error_msg])
                        executed_commands.append(next_command)
                        command_count += 1
                
                # Finalize output
                debug_output = "\n".join(all_output_lines)
                logger.info(f"Interactive debug session completed: {command_count} commands executed")
                
                return debug_output, executed_commands
                
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
                for build, result in mult.get_crashes(state.pov_input_path, self.task.harness_name):
                    # If we get here, the PoV caused a crash
                    pov_valid = result.did_crash()
                    break

                # Store the debug attempt
                debug_attempt = DebugAttempt(
                    analysis=state.analysis,
                    debug_script="",  # No script in interactive mode
                    debug_output=state.debug_output,
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
            debug_attempt = DebugAttempt(
                analysis=state.analysis,
                debug_script="",  # No script in interactive mode
                debug_output=state.debug_output,
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
        """Determine if we should continue the context retrieval iteration
        
        Override the parent task's method to use DebugSubagent's own MAX_CONTEXT_ITERATIONS
        instead of the parent task's limit.
        """
        return state.context_iteration < self.MAX_CONTEXT_ITERATIONS

    def _build_workflow(self) -> StateGraph:
        """Build the workflow for the debug task"""
        workflow = StateGraph(DebugTaskState)

        workflow.add_node("get_context", self._get_context)
        tool_node = ToolNode(self.task.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_debug", self._analyze_debug)
        workflow.add_node("run_interactive_debug", self._run_interactive_debug)
        workflow.add_node("reflect_debug", self._reflect_debug)
        
        workflow.set_entry_point("get_context")
        workflow.add_edge("get_context", "tools")
        workflow.add_conditional_edges(
            "tools",
            self._continue_context_retrieval,  # Use our own method, not self.task's
            {
                True: "get_context",
                False: "analyze_debug",
            },
        )

        workflow.add_edge("analyze_debug", "run_interactive_debug")
        workflow.add_edge("run_interactive_debug", "reflect_debug")
        
        if self.skip_validation:
            # Skip validation - just run debug once and exit
            workflow.add_edge("reflect_debug", END)
        else:
            # Include validation and allow retries
            workflow.add_node("validate_pov", self._validate_pov)
            workflow.add_edge("reflect_debug", "validate_pov")
            workflow.add_conditional_edges(
                "validate_pov",
                self._continue_debug,
                {
                    True: "analyze_debug",  # Retry if PoV not valid
                    False: END,  # Done if PoV valid or max iterations reached
                },
            )

        return workflow

    def _recursion_limit(self) -> int:
        """Calculate recursion limit for the workflow
        
        The workflow structure:
        1. Context gathering phase: get_context -> tools (can loop multiple times)
           - Each tool call from the LLM counts as a step
           - Can have multiple tool calls per iteration
        2. Debug phase: analyze_debug -> write_debug_script -> run_debug_script -> reflect_debug
        3. Validation phase (if not skipped): validate_pov -> (maybe loop back)
        
        We need to be generous with the limit because tool calls add up quickly.
        """
        # Each context iteration: get_context (1) + tools (N tool calls) 
        # Estimate max tool calls per context iteration
        context_steps_per_iteration = 1 + self.ESTIMATED_TOOLS_PER_CONTEXT
        context_total = context_steps_per_iteration * self.MAX_CONTEXT_ITERATIONS
        
        if self.skip_validation:
            # Single debug pass: analyze + run_interactive + reflect
            # Interactive loop adds MAX_INTERACTIVE_COMMANDS LLM calls
            debug_steps = 3 + self.MAX_INTERACTIVE_COMMANDS  # analyze + interactive_loop + reflect
            return 1 + context_total + debug_steps
        else:
            # Full validation loop with retries
            # Interactive loop adds MAX_INTERACTIVE_COMMANDS LLM calls per iteration
            debug_steps = 4 + self.MAX_INTERACTIVE_COMMANDS  # analyze + interactive_loop + reflect + validate
            return 1 + context_total + debug_steps * self.MAX_DEBUG_ITERATIONS
