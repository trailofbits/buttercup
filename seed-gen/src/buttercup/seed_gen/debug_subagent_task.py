import logging
import operator
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, ClassVar

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from opentelemetry import trace
from pydantic import Field

from buttercup.common.challenge_task import ChallengeTaskError, ReproduceResult
from buttercup.common.datastructures.msg_pb2 import BuildOutput
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


class DebugTaskState(BaseTaskState):
    """State for the debug task"""

    debug_context: str = Field(
        description="Articulated context about what to test and verify",
        default="",
    )
    pov_input_path: Path = Field(
        description="Path to the PoV input file (not the script, but the actual input)",
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


@dataclass
class DebugSubagentTask(Task):
    """Task for debugging PoVs with GDB scripts"""

    reproduce_multiple: ReproduceMultiple
    harness: HarnessInfo
    pov_input_path: Path
    debug_context: str

    MAX_DEBUG_ITERATIONS: ClassVar[int] = 5
    MAX_CONTEXT_ITERATIONS: ClassVar[int] = 6

    def _get_context(self, state: DebugTaskState) -> Command:
        """Get context about the codebase for debugging"""
        logger.info("Getting context for debugging")
        prompt_vars = {
            "harness": str(state.harness),
            "debug_context": state.debug_context,
            "retrieved_context": state.format_retrieved_context(),
        }
        res = self._get_context_base(
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
        chain = prompt | self.llm | StrOutputParser()
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
        chain = prompt | self.llm | extract_code
        debug_script = chain.invoke(prompt_vars)
        return Command(update={"debug_script": debug_script})

    def _run_debug_script(self, state: DebugTaskState) -> Command:
        """Run the debug script in a debug container"""
        logger.info("Running debug script")
        if not state.debug_script:
            logger.warning("No debug script to run")
            return Command(update={"debug_output": "No debug script provided"})

        # Write debug script to a temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
            f.write(state.debug_script)
            debug_script_path = Path(f.name)

        try:
            # Run the debug script using exec_docker_cmd with debug container
            # We need to use the debug container image (base-runner-debug)
            # and run GDB with the script
            debug_output = self._execute_debug_script(debug_script_path, state.pov_input_path)

            return Command(update={"debug_output": debug_output})
        except Exception as e:
            logger.error(f"Error running debug script: {e}")
            return Command(update={"debug_output": f"Error: {str(e)}"})
        finally:
            # Clean up temporary script file
            if debug_script_path.exists():
                debug_script_path.unlink()

    def _execute_debug_script(
        self,
        debug_script_path: Path,
        pov_input_path: Path,
    ) -> str:
        """Execute a GDB debug script in a debug container"""
        # Get the first build from reproduce_multiple to use for debugging
        if not self.reproduce_multiple.build_outputs:
            raise ValueError("No build outputs available for debugging")

        # Get a writable copy of the task
        with self.reproduce_multiple.open() as mult:
            if mult.builds_cache is None or not mult.builds_cache:
                raise ValueError("Build cache not available")
            task = mult.builds_cache[0]

            # Get the fuzzer binary path (typically in /out)
            harness_name = self.harness_name
            binary_path = f"/out/{harness_name}"

            # Determine the debug container image
            # OSS-Fuzz uses base-runner-debug images
            # Default to gcr.io/oss-fuzz-base/base-runner-debug
            # The actual registry might be different (e.g., ghcr.io for competition infra)
            # but for now we'll use the standard OSS-Fuzz debug image
            debug_container_image = "gcr.io/oss-fuzz-base/base-runner-debug"

            # Mount the debug script and PoV input
            mount_dirs = {
                debug_script_path: Path("/tmp/debug_script.gdb"),
                pov_input_path: Path(f"/tmp/{pov_input_path.name}"),
            }

            # Also need to mount the build output directory so GDB can find the binary
            # The build directory contains the compiled fuzzers in /out/<project_name>/
            build_dir = task.get_build_dir()
            if build_dir and build_dir.exists():
                # Mount the parent of build_dir (which contains /out) to /out in container
                # build_dir is typically .../build/out/<project_name>
                # We want to mount .../build/out to /out
                out_dir = build_dir.parent  # This should be .../build/out
                if out_dir.exists():
                    mount_dirs[out_dir] = Path("/out")
                else:
                    # Fallback: mount build_dir directly
                    mount_dirs[build_dir] = Path("/out")

            # Create the GDB command
            # We need to run: gdb -batch -x <script_path> --args <binary> <input_path>
            gdb_cmd = [
                "gdb",
                "-batch",
                "-x",
                "/tmp/debug_script.gdb",
                "--args",
                binary_path,
                f"/tmp/{pov_input_path.name}",
            ]

            # Run in debug container
            # Use exec_docker_cmd with the debug container image
            result = task.exec_docker_cmd(
                gdb_cmd,
                mount_dirs=mount_dirs,
                container_image=debug_container_image,
            )

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
                for build, result in mult.get_crashes(state.pov_input_path, self.harness_name):
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
                        "analysis": "",
                        "debug_script": "",
                        "debug_output": "",
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
                    "analysis": "",
                    "debug_script": "",
                    "debug_output": "",
                },
            )

    def _continue_debug(self, state: DebugTaskState) -> bool:
        """Determine whether to continue debugging"""
        # Continue if PoV is not valid and we haven't exceeded max iterations
        return not state.pov_valid and state.debug_iteration < self.MAX_DEBUG_ITERATIONS

    def _build_workflow(self) -> StateGraph:
        """Build the workflow for the debug task"""
        workflow = StateGraph(DebugTaskState)

        workflow.add_node("get_context", self._get_context)
        tool_node = ToolNode(self.tools, name="tools")
        workflow.add_node("tools", tool_node)
        workflow.add_node("analyze_debug", self._analyze_debug)
        workflow.add_node("write_debug_script", self._write_debug_script)
        workflow.add_node("run_debug_script", self._run_debug_script)
        workflow.add_node("validate_pov", self._validate_pov)

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

        workflow.add_edge("analyze_debug", "write_debug_script")
        workflow.add_edge("write_debug_script", "run_debug_script")
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

    def recursion_limit(self) -> int:
        """Calculate recursion limit for the workflow"""
        context_steps = 2
        debug_steps = 4
        return 1 + context_steps * self.MAX_CONTEXT_ITERATIONS + debug_steps * self.MAX_DEBUG_ITERATIONS

    def do_task(self, output_dir: Path) -> None:
        """Execute the debug task"""
        logger.info(
            "Doing debug task for challenge %s | harness: %s | pov_input: %s",
            self.package_name,
            self.harness_name,
            self.pov_input_path,
        )

        try:
            state = DebugTaskState(
                harness=self.harness,
                task=self,
                output_dir=output_dir,
                pov_input_path=self.pov_input_path,
                debug_context=self.debug_context,
            )

            workflow = self._build_workflow()
            llm_callbacks = get_langfuse_callbacks()
            chain = workflow.compile().with_config(
                RunnableConfig(
                    tags=["debug-subagent"],
                    callbacks=llm_callbacks,
                    recursion_limit=self.recursion_limit(),
                ),
            )

            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("seed_gen_debug") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                    crs_action_name="seed_gen_debug",
                    task_metadata=dict(self.challenge_task.task_meta.metadata),
                    extra_attributes={
                        "gen_ai.request.model": self.llm.model_name,  # type: ignore[attr-defined]
                    },
                )

                # Run the workflow
                final_state = chain.invoke(state)  # type: ignore[arg-type]

                # Write final results to output directory
                if final_state.debug_script:
                    (output_dir / "debug_script.gdb").write_text(final_state.debug_script)
                if final_state.debug_output:
                    (output_dir / "debug_output.txt").write_text(final_state.debug_output)
                if final_state.analysis:
                    (output_dir / "analysis.txt").write_text(final_state.analysis)
                (output_dir / "pov_valid.txt").write_text(str(final_state.pov_valid))

                # Write all debug attempts
                if final_state.debug_attempts:
                    attempts_text = "\n\n".join(str(attempt) for attempt in final_state.debug_attempts)
                    (output_dir / "debug_attempts.txt").write_text(attempts_text)

                logger.info(
                    "Debug task completed: pov_valid=%s, iterations=%d, attempts=%d",
                    final_state.pov_valid,
                    final_state.debug_iteration,
                    len(final_state.debug_attempts),
                )

        except Exception as err:
            logger.exception(
                "Failed debug task for challenge %s: %s",
                self.package_name,
                str(err),
            )
