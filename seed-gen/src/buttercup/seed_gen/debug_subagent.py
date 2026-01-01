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
from buttercup.seed_gen.prompt.debug import (
    DEBUG_ANALYZE_SYSTEM_PROMPT,
    DEBUG_ANALYZE_USER_PROMPT,
    DEBUG_GET_CONTEXT_SYSTEM_PROMPT,
    DEBUG_GET_CONTEXT_USER_PROMPT,
    DEBUG_WRITE_SCRIPT_SYSTEM_PROMPT,
    DEBUG_WRITE_SCRIPT_USER_PROMPT,
)
from buttercup.seed_gen.task import BaseTaskState, Task
from buttercup.seed_gen.utils import extract_code

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
    debug_script: str = Field(description="The GDB debug script to execute", default="")
    debug_output: str = Field(description="Output from running the debug script", default="")
    pov_valid: bool = Field(description="Whether the PoV is valid (causes a crash)", default=False)
    debug_iteration: int = Field(description="Count of debug iterations", default=0)
    debug_attempts: Annotated[list[DebugAttempt], operator.add] = Field(default_factory=list)

    def format_debug_attempts(self) -> str:
        """Format debug attempts for prompts"""
        return "\n\n".join(str(attempt) for attempt in self.debug_attempts)


class DebugSubagent:
    """Utility for debugging PoVs with GDB scripts.

    This can be called by other tasks to debug PoV inputs and investigate
    why they might not be working as expected.
    """

    MAX_DEBUG_ITERATIONS = 2
    MAX_CONTEXT_ITERATIONS = 3
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
                debug_script = final_state.get("debug_script", "") or ""
                debug_output = final_state.get("debug_output", "") or ""
                analysis = final_state.get("analysis", "") or ""
                pov_valid = final_state.get("pov_valid", False)
                debug_attempts = final_state.get("debug_attempts", [])

                logger.info(
                    "Debug state extracted: analysis_len=%d, script_len=%d, output_len=%d, attempts=%d",
                    len(analysis),
                    len(debug_script),
                    len(debug_output),
                    len(debug_attempts),
                )

                # Write results to output directory if provided
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    if debug_script:
                        (output_dir / "debug_script.gdb").write_text(debug_script)
                    if debug_output:
                        (output_dir / "debug_output.txt").write_text(debug_output)
                    if analysis:
                        (output_dir / "analysis.txt").write_text(analysis)
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
                    debug_script=debug_script,
                    debug_output=debug_output,
                    analysis=analysis,
                    attempts=debug_attempts,
                )

        except Exception as err:
            logger.exception("Failed debug session: %s", str(err))
            return DebugResult(
                pov_valid=False,
                debug_script="",
                debug_output=f"Error: {str(err)}",
                analysis="",
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

    def _write_debug_script(self, state: DebugTaskState) -> Command:
        """Write a GDB debug script"""
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
        """Run the debug script in a debug container"""
        logger.info("Running debug script")
        if not state.debug_script:
            logger.warning("No debug script to run")
            return Command(update={"debug_output": "No debug script provided"})

        # Write debug script to a temporary file
        # NOTE: We do NOT delete this file. Docker needs it to remain accessible
        # during the mount. The OS will clean it up later, or we could clean it
        # up after Docker has fully completed, but that's complex with the current
        # architecture where exec_docker_cmd might cache containers.
        import os
        logger.info("Creating temporary GDB script file...")
        logger.info(f"  Script content length: {len(state.debug_script)} characters")
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
            logger.info(f"  Temporary file created: {f.name}")
            f.write(state.debug_script)
            logger.info(f"  Content written to buffer")
            f.flush()  # Ensure content is written to OS buffer
            logger.info(f"  Buffer flushed to OS")
            os.fsync(f.fileno())  # Force write to disk before mounting
            logger.info(f"  File synced to disk (fsync)")
            debug_script_path = Path(f.name)
        
        # Also sync the parent directory to ensure metadata is written
        # This helps prevent race conditions where Docker tries to mount before
        # the file system has fully committed the file metadata
        logger.info(f"Syncing parent directory metadata: {debug_script_path.parent}")
        dir_fd = os.open(str(debug_script_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)  # Sync directory metadata to disk
            logger.info(f"  Directory metadata synced to disk")
        finally:
            os.close(dir_fd)
        
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
            return Command(update={"debug_output": f"Error: Failed to create debug script file"})
        
        logger.info(f"Created debug script file: {debug_script_path} (size: {debug_script_path.stat().st_size} bytes)")

        try:
            # Run the debug script using exec_docker_cmd with debug container
            # Verify the file exists and is readable before passing to Docker
            if not debug_script_path.exists():
                return Command(update={"debug_output": f"Error: Debug script file not found at {debug_script_path}"})
            if not debug_script_path.is_file():
                return Command(update={"debug_output": f"Error: Debug script path is not a file: {debug_script_path}"})
            
            logger.info(f"Debug script file verified: {debug_script_path} (size: {debug_script_path.stat().st_size} bytes)")
            
            debug_output = self._execute_debug_script(debug_script_path, state.pov_input_path)
            return Command(update={"debug_output": debug_output})
        except Exception as e:
            logger.error(f"Error running debug script: {e}")
            return Command(update={"debug_output": f"Error: {str(e)}"})
        # Note: We intentionally do NOT delete the debug_script_path here
        # because Docker might still be accessing it via the mount

    def _execute_debug_script(
        self,
        debug_script_path: Path,
        pov_input_path: Path,
    ) -> str:
        """Execute a GDB debug script in a debug container"""
        # Get a writable copy of the task
        with self.reproduce_multiple.open() as mult:
            if mult.builds_cache is None or not mult.builds_cache:
                raise ValueError("Build cache not available")
            task = mult.builds_cache[0]

            # Get the fuzzer binary path (typically in /out)
            harness_name = self.task.harness_name
            
            # Determine the debug container image
            # Default to gcr.io/oss-fuzz-base/base-runner-debug
            debug_container_image = "gcr.io/oss-fuzz-base/base-runner-debug"

            # Resolve paths to ensure they're absolute
            # Log the paths before and after resolution to debug any path issues
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
            # get_build_dir() returns .../build/out/<project_name>
            # Binaries are located at .../build/out/<project_name>/<harness_name>
            # This matches the pattern used in fuzzer_bot.py
            build_dir = task.get_build_dir()
            logger.info(f"Build directory from task.get_build_dir(): {build_dir}")
            
            if not build_dir or not build_dir.exists():
                raise ValueError(f"Build directory not found or doesn't exist: {build_dir}")
            
            logger.info(f"Build directory exists: {build_dir}")
            # List files in build_dir to debug
            if build_dir.is_dir():
                files_in_build = list(build_dir.iterdir())[:10]  # First 10 files
                logger.info(f"Files in build_dir: {[f.name for f in files_in_build]}")
            
            # Check if the harness binary exists in the build directory
            # Binary location matches fuzzer_bot.py: build_dir / harness_name
            harness_binary_path = build_dir / harness_name
            if not harness_binary_path.exists():
                available_files = [f.name for f in build_dir.iterdir()] if build_dir.is_dir() else []
                raise ValueError(
                    f"Harness binary '{harness_name}' not found in {build_dir}. "
                    f"Available files: {available_files}"
                )
            
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
            
            # Mount debug script to scratchpad (same directory as PoV input)
            # This avoids /tmp issues in Docker-in-Docker scenarios
            # Strategy: Mount the PoV input's parent directory to /work in container
            # Then both files are accessible at /work/<filename>
            pov_input_parent = pov_input_path.parent
            script_unique_name = f"debug_script_{debug_script_path.stem}.gdb"
            # Container paths relative to /work mount
            debug_script_container_path = Path(f"/work/{script_unique_name}")
            pov_input_container_path = Path(f"/work/{pov_input_path.name}")
            
            logger.info(f"Container paths (targets in container):")
            logger.info(f"  Debug script: {debug_script_container_path}")
            logger.info(f"  PoV input: {pov_input_container_path}")
            
            # Get project_name for container binary path
            # build_dir is .../build/out/<project_name>, so project_name is the last component
            project_name = build_dir.name
            # Binary path in container: /out/<project_name>/<actual_binary_name>
            # Use the actual binary name (which may differ from harness_name if it was a wrapper)
            binary_path = f"/out/{project_name}/{harness_name_for_path}"
            
            # Mount the parent of build_dir (which is .../build/out) to /out in container
            # This matches the pattern used in debug_subagent_task.py
            # build_dir is typically .../build/out/<project_name>
            # We want to mount .../build/out to /out
            out_dir = build_dir.parent  # This should be .../build/out
            
            # Verify all source files exist before mounting
            logger.info(f"Verifying source files before Docker mount:")
            logger.info(f"  Debug script:")
            logger.info(f"    Path: {debug_script_path}")
            logger.info(f"    Exists: {debug_script_path.exists()}")
            logger.info(f"    Is file: {debug_script_path.is_file()}")
            logger.info(f"    Is directory: {debug_script_path.is_dir()}")
            if debug_script_path.exists():
                logger.info(f"    Size: {debug_script_path.stat().st_size} bytes")
                logger.info(f"    Absolute: {debug_script_path.resolve()}")
            
            logger.info(f"  PoV input:")
            logger.info(f"    Path: {pov_input_path}")
            logger.info(f"    Exists: {pov_input_path.exists()}")
            logger.info(f"    Is file: {pov_input_path.is_file()}")
            logger.info(f"    Is directory: {pov_input_path.is_dir()}")
            if pov_input_path.exists():
                logger.info(f"    Size: {pov_input_path.stat().st_size} bytes")
                logger.info(f"    Absolute: {pov_input_path.resolve()}")
            
            logger.info(f"  Build dir:")
            logger.info(f"    Path: {build_dir}")
            logger.info(f"    Exists: {build_dir.exists()}")
            logger.info(f"    Is directory: {build_dir.is_dir()}")
            logger.info(f"    Absolute: {build_dir.resolve()}")
            
            logger.info(f"  Out dir (parent of build_dir):")
            logger.info(f"    Path: {out_dir}")
            logger.info(f"    Exists: {out_dir.exists()}")
            logger.info(f"    Is directory: {out_dir.is_dir()}")
            logger.info(f"    Absolute: {out_dir.resolve()}")
            
            # Mount the PoV input's parent directory to /work so both files are accessible
            # This puts both the debug script and PoV input in the scratchpad
            mount_dirs = {
                pov_input_parent: Path("/work"),  # Mount parent dir to /work
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
            
            # Copy debug script to the scratchpad directory before mounting
            # This ensures it's in the same directory as the PoV input
            import shutil
            debug_script_in_scratchpad = pov_input_parent / script_unique_name
            logger.info(f"Copying debug script to scratchpad: {debug_script_in_scratchpad}")
            shutil.copy2(debug_script_path, debug_script_in_scratchpad)
            logger.info(f"  Copied: {debug_script_path} -> {debug_script_in_scratchpad}")
            
            logger.info(f"Final mount configuration:")
            for src, dst in mount_dirs.items():
                src_resolved = src.resolve() if hasattr(src, 'resolve') else Path(str(src)).resolve()
                dst_path = dst.resolve() if hasattr(dst, 'resolve') else Path(str(dst))
                logger.info(f"  {src_resolved.as_posix()} -> {dst_path.as_posix()}")
                logger.info(f"    Source exists: {src_resolved.exists()}")
                logger.info(f"    Source is_file: {src_resolved.is_file() if src_resolved.exists() else 'N/A'}")
                logger.info(f"    Source is_dir: {src_resolved.is_dir() if src_resolved.exists() else 'N/A'}")
                logger.info(f"    Destination path type: {type(dst_path)}")
                logger.info(f"    Destination as_posix(): {dst_path.as_posix()}")
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

            # CRITICAL: Clean up any existing directory at mount target before mounting
            # If the target path exists as a directory, Docker will mount the file INTO it
            # instead of replacing it, causing "Is a directory" errors

            # Run in debug container
            # First, verify the mount will work by checking what exec_docker_cmd will actually do
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
                    debug_script=state.debug_script,
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
                debug_script=state.debug_script,
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
        workflow.add_node("write_debug_script", self._write_debug_script)
        workflow.add_node("run_debug_script", self._run_debug_script)
        
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

        workflow.add_edge("analyze_debug", "write_debug_script")
        workflow.add_edge("write_debug_script", "run_debug_script")
        
        if self.skip_validation:
            # Skip validation - just run debug once and exit
            workflow.add_edge("run_debug_script", END)
        else:
            # Include validation and allow retries
            workflow.add_node("validate_pov", self._validate_pov)
            workflow.add_edge("run_debug_script", "validate_pov")
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
        2. Debug phase: analyze_debug -> write_debug_script -> run_debug_script
        3. Validation phase (if not skipped): validate_pov -> (maybe loop back)
        
        We need to be generous with the limit because tool calls add up quickly.
        """
        # Each context iteration: get_context (1) + tools (N tool calls) 
        # Estimate max tool calls per context iteration
        context_steps_per_iteration = 1 + self.ESTIMATED_TOOLS_PER_CONTEXT
        context_total = context_steps_per_iteration * self.MAX_CONTEXT_ITERATIONS
        
        if self.skip_validation:
            # Single debug pass: analyze + write + run
            debug_steps = 3
            return 1 + context_total + debug_steps
        else:
            # Full validation loop with retries
            debug_steps = 4  # analyze + write + run + validate
            return 1 + context_total + debug_steps * self.MAX_DEBUG_ITERATIONS
