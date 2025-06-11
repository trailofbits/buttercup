"""Quality Engineer LLM agent, handling the testing of patches."""

import logging
import tempfile
import langgraph.errors
import re
import importlib.resources
import subprocess
from unidiff import PatchSet
from io import StringIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from pydantic import ValidationError, Field, field_validator
from langchain_core.runnables import Runnable
from langgraph.types import Command
from langgraph.constants import END
from buttercup.common.corpus import CrashDir
from buttercup.common.challenge_task import ChallengeTaskError, CommandResult
from langchain_core.messages import BaseMessage
import buttercup.common.node_local as node_local
from langchain_core.runnables import RunnableConfig
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.challenge_task import ChallengeTask
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    PatchAttempt,
    PatchStatus,
    BaseCtxState,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.patcher.agents.tools import (
    ls,
    grep,
    cat,
    get_lines,
    get_function,
    get_type,
    get_callees,
    get_callers,
)
from buttercup.common.llm import create_default_llm_with_temperature, ButtercupLLM
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent
from langchain_core.prompts import MessagesPlaceholder
import time

logger = logging.getLogger(__name__)

CHECK_HARNESS_CHANGES_SYSTEM_MSG = """
You are an agent - please keep going until the user’s query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.
If you are not sure about file content or codebase structure pertaining to the user’s request, use your tools to read files and gather the relevant information: do NOT guess or make up an answer.
You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.
You are a quality engineer agent tasked with checking the validity of a patch.
"""

CHECK_HARNESS_CHANGES_USER_MSG = """You are given a patch that has been applied to a challenge task.
You need to check if the patch is valid.

A patch is considered valid if it does NOT modify harness code.

Harness code is code that is used to test/fuzz the challenge task, usually found in `fuzz`, `fuzzers`, `tests`, `test` directories, etc.
Fuzzers are usually written in libfuzzer and they contain functions such as `LLVMFuzzerTestOneInput`, `Fuzzer::Execute`, `fuzzerTestOneInput` or similar.

Project name:
<project_name>
{PROJECT_NAME}
</project_name>

Patch:
<patch>
{PATCH}
</patch>

Current directory (pwd):
<cwd>
{CWD}
</cwd>

Files in current directory (ls -la):
<ls_cwd>
{LS_CWD}
</ls_cwd>


Think step by step and use your tools to check the validity of the patch. Wrap your thoughts and reasoning in <think> tags.
When you are done, return a true/false value in <is_valid> tags.
"""

CHECK_HARNESS_CHANGES_CHAIN = ChatPromptTemplate.from_messages(
    [
        ("system", CHECK_HARNESS_CHANGES_SYSTEM_MSG),
        ("user", CHECK_HARNESS_CHANGES_USER_MSG),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("ai", "<think>"),
    ]
)


class PatchValidationState(BaseCtxState):
    """State for the patch validation agent"""

    patch: PatchAttempt = Field(..., description="The patch to validate")

    @field_validator("patch")
    def validate_patch(cls, v: PatchAttempt) -> PatchAttempt:
        if v.patch is None:
            raise ValueError("patch.patch cannot be None")
        if v.patch.patch is None or not v.patch.patch.strip():
            raise ValueError("patch.patch.patch cannot be None or empty")
        return v


@dataclass
class QEAgent(PatcherAgentBase):
    """Quality Engineer LLM agent, handling the testing of patches."""

    check_harness_changes_chain: Runnable = field(init=False)

    def __post_init__(self) -> None:
        tools = [
            ls,
            grep,
            cat,
            get_lines,
            get_function,
            get_type,
            get_callees,
            get_callers,
        ]
        default_agent = create_react_agent(
            model=create_default_llm_with_temperature(model_name=ButtercupLLM.OPENAI_GPT_4_1.value),
            state_schema=PatchValidationState,
            tools=tools,
            prompt=self._check_harness_changes_prompt,
        )
        fallback_agents = [
            create_react_agent(
                model=create_default_llm_with_temperature(model_name=llm.value),
                state_schema=PatchValidationState,
                tools=tools,
                prompt=self._check_harness_changes_prompt,
            )
            for llm in [ButtercupLLM.CLAUDE_3_7_SONNET]
        ]
        self.check_harness_changes_chain = default_agent.with_fallbacks(fallback_agents)

    def _check_harness_changes_prompt(self, state: PatchValidationState) -> list[BaseMessage]:
        ls_cwd = self.challenge.exec_docker_cmd(["ls", "-la"])
        if ls_cwd.success:
            ls_cwd = ls_cwd.output.decode("utf-8")
        else:
            ls_cwd = "ls cwd failed"

        return CHECK_HARNESS_CHANGES_CHAIN.format_messages(
            PROJECT_NAME=self.challenge.name,
            PATCH=state.patch.patch.patch,  # type: ignore[union-attr]
            CWD=self.challenge.workdir_from_dockerfile(),
            LS_CWD=ls_cwd,
            messages=state.messages,
        )

    def _patch_challenge(self, challenge: ChallengeTask, patch_attempt: PatchAttempt) -> bool:
        assert patch_attempt.patch
        with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
            patch_file.write(patch_attempt.patch.patch)
            patch_file.flush()
            logger.debug("Patch written to %s", patch_file.name)

            logger.info(
                "Applying patch to task %s / submission index %s", self.input.task_id, self.input.submission_index
            )
            try:
                return challenge.apply_patch_diff(Path(patch_file.name))  # type: ignore[no-any-return]
            except ChallengeTaskError:
                if logger.getEffectiveLevel() == logging.DEBUG:
                    logger.exception("Failed to apply patch to Challenge Task %s", self.challenge.name)

                return False

    def _rebuild_challenge(self) -> CommandResult:
        try:
            cp_output = self.challenge.build_fuzzers(
                engine=self.input.engine,
                sanitizer=self.input.sanitizer,
            )
        except ChallengeTaskError as exc:
            logger.error("Failed to run build_fuzzers on Challenge Task %s with patch", self.challenge.name)
            return CommandResult(
                success=False,
                output=exc.stdout,
                error=exc.stderr,
            )

        if not cp_output.success:
            logger.error("Failed to build Challenge Task %s with patch", self.challenge.name)
            return CommandResult(
                success=False,
                output=cp_output.output,
                error=cp_output.error,
            )

        return CommandResult(
            success=True,
            output=cp_output.output,
            error=cp_output.error,
        )

    def build_patch_node(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.RUN_POV.value, PatcherAgentName.REFLECTION.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that builds a patch"""
        logger.info("Rebuilding Challenge Task %s with patch", self.challenge.name)
        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt or not last_patch_attempt.patch:
            logger.fatal("No patch to build, this should never happen")
            raise RuntimeError("No patch to build, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.BUILD_PATCH
        if not self._patch_challenge(self.challenge, last_patch_attempt):
            logger.error("Failed to apply patch to Challenge Task %s", self.challenge.name)
            last_patch_attempt.status = PatchStatus.APPLY_FAILED
            return Command(
                update={
                    "patch_attempts": last_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        cp_output = self._rebuild_challenge()
        last_patch_attempt.build_stdout = cp_output.output
        last_patch_attempt.build_stderr = cp_output.error
        if not cp_output.success:
            logger.error("Failed to rebuild Challenge Task %s with patch", self.challenge.name)
            last_patch_attempt.status = PatchStatus.BUILD_FAILED
            return Command(
                update={
                    "patch_attempts": last_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        logger.info("Challenge Task %s rebuilt with patch", self.challenge.name)
        last_patch_attempt.build_succeeded = True
        return Command(
            update={
                "patch_attempts": last_patch_attempt,
            },
            goto=PatcherAgentName.RUN_POV.value,
        )

    def run_pov_node(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[Literal[PatcherAgentName.RUN_TESTS.value, PatcherAgentName.REFLECTION.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that runs a PoV against a currently built patch"""
        configuration = PatcherConfig.from_configurable(config)
        logger.info("Testing PoVs on Challenge Task %s rebuilt with patch", self.challenge.name)
        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal("No patch to run PoV on, this should never happen")
            raise RuntimeError("No patch to run PoV on, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.RUN_POV
        pov_variants = [self.input.pov]

        try:
            crash_dir = CrashDir(configuration.work_dir, self.input.task_id, self.input.harness_name)
            # TODO: test all sanitizers under this same crash-token
            crashes_for_token = crash_dir.list_crashes_for_token(
                self.input.pov_token, state.context.sanitizer, get_remote=True
            )
            if not crashes_for_token:
                logger.warning("No crashes found for PoV token %s", self.input.pov_token)
                crashes_for_token = []

            pov_variants.extend([Path(crash) for crash in crashes_for_token])
        except Exception as e:
            logger.error("Failed to list PoV variants for token %s", self.input.pov_token)
            logger.exception(e)

        start_time = time.time()
        run_once = False

        for pov_variant in pov_variants:
            # Check if we've exceeded the max_minutes_run_povs timeout
            if time.time() - start_time > configuration.max_minutes_run_povs * 60:
                logger.error("PoV processing lasted more than %d minutes", configuration.max_minutes_run_povs)
                if run_once:
                    logger.info(
                        "PoV processing lasted more than %d minutes, but we already ran one PoV successfully, so we'll stop here",
                        configuration.max_minutes_run_povs,
                    )
                    break

                last_patch_attempt.pov_fixed = False
                last_patch_attempt.pov_stdout = (
                    f"Operation timed out after {configuration.max_minutes_run_povs} minutes".encode()
                )
                last_patch_attempt.pov_stderr = None
                last_patch_attempt.status = PatchStatus.POV_FAILED
                return Command(
                    update={
                        "patch_attempts": last_patch_attempt,
                        "execution_info": execution_info,
                    },
                    goto=PatcherAgentName.REFLECTION.value,
                )

            pov_variant = node_local.make_locally_available(pov_variant)
            try:
                pov_output = self.challenge.reproduce_pov(self.input.harness_name, pov_variant)
                logger.info(
                    "Ran PoV %s/%s for harness %s",
                    self.challenge.name,
                    pov_variant,
                    self.input.harness_name,
                )
                logger.debug("PoV stdout: %s", pov_output.command_result.output)
                logger.debug("PoV stderr: %s", pov_output.command_result.error)

                if not pov_output.did_run():
                    logger.warning("PoV %s did not run, skipping", pov_variant)
                    continue

                if pov_output.did_crash():
                    logger.error("PoV %s still crashes", pov_variant)
                    last_patch_attempt.pov_fixed = False
                    last_patch_attempt.pov_stdout = pov_output.command_result.output
                    last_patch_attempt.pov_stderr = pov_output.command_result.error
                    last_patch_attempt.status = PatchStatus.POV_FAILED
                    return Command(
                        update={
                            "patch_attempts": last_patch_attempt,
                            "execution_info": execution_info,
                        },
                        goto=PatcherAgentName.REFLECTION.value,
                    )

                run_once = True
            except ChallengeTaskError as exc:
                logger.error("Failed to run pov for Challenge Task %s", self.challenge.name)
                last_patch_attempt.pov_fixed = False
                last_patch_attempt.pov_stdout = exc.stdout
                last_patch_attempt.pov_stderr = exc.stderr
                last_patch_attempt.status = PatchStatus.POV_FAILED
                return Command(
                    update={
                        "patch_attempts": last_patch_attempt,
                        "execution_info": execution_info,
                    },
                    goto=PatcherAgentName.REFLECTION.value,
                )

        if not run_once:
            logger.error("No PoVs could be run, this should never happen")
            return Command(
                update={
                    "pov_fixed": False,
                    "pov_stdout": None,
                    "pov_stderr": None,
                },
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        logger.info("All PoVs were fixed")
        last_patch_attempt.pov_fixed = True
        last_patch_attempt.pov_stdout = None
        last_patch_attempt.pov_stderr = None
        return Command(
            update={
                "patch_attempts": last_patch_attempt,
            },
            goto=PatcherAgentName.RUN_TESTS.value,
        )

    def run_tests_node(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[Literal[PatcherAgentName.REFLECTION.value, PatcherAgentName.PATCH_VALIDATION.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that runs tests against a currently built patch"""
        logger.info(
            "[%s / %s] Running tests on Challenge Task %s rebuilt with patch",
            self.input.task_id,
            self.input.submission_index,
            self.challenge.name,
        )
        configuration = PatcherConfig.from_configurable(config)

        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal(
                "[%s / %s] No patch to run tests on, this should never happen",
                self.input.task_id,
                self.input.submission_index,
            )
            raise RuntimeError("No patch to run tests on, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.RUN_TESTS

        if not last_patch_attempt.build_succeeded or not last_patch_attempt.pov_fixed:
            logger.error(
                "[%s / %s] The patch needs to be built and PoV needs to be fixed before running tests",
                self.input.task_id,
                self.input.submission_index,
            )
            last_patch_attempt.status = PatchStatus.TESTS_FAILED
            return Command(
                update={
                    "patch_attempts": last_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        tests_passed = False
        if state.tests_instructions:
            clean_challenge = self.challenge.get_clean_task(configuration.tasks_storage)
            with clean_challenge.get_rw_copy(configuration.work_dir) as clean_rw_challenge:
                clean_rw_challenge.apply_patch_diff()
                self._patch_challenge(clean_rw_challenge, last_patch_attempt)

                with tempfile.NamedTemporaryFile(dir=clean_rw_challenge.task_dir, delete=False) as f:
                    f.write(state.tests_instructions.encode("utf-8"))
                    f.flush()

                    test_file_path = Path(f.name)
                    test_file_path.chmod(0o755)

                sh_cmd_res = clean_rw_challenge.exec_docker_cmd(
                    clean_rw_challenge.get_test_sh_script("/tmp/test.sh"),
                    mount_dirs={
                        test_file_path: Path("/tmp/test.sh"),
                    },
                )

            tests_passed = sh_cmd_res.success
            last_patch_attempt.tests_passed = tests_passed
            last_patch_attempt.tests_stdout = sh_cmd_res.output
            last_patch_attempt.tests_stderr = sh_cmd_res.error
        else:
            logger.warning(
                "[%s / %s] No tests instructions found, just accept the patch",
                self.input.task_id,
                self.input.submission_index,
            )
            tests_passed = True

        if tests_passed:
            logger.info(
                "[%s / %s] Tests for Challenge Task %s ran successfully",
                self.input.task_id,
                self.input.submission_index,
                self.challenge.name,
            )
            next_node = PatcherAgentName.PATCH_VALIDATION.value
        else:
            logger.error(
                "[%s / %s] Tests failed for Challenge Task %s",
                self.input.task_id,
                self.input.submission_index,
                self.challenge.name,
            )
            last_patch_attempt.status = PatchStatus.TESTS_FAILED
            next_node = PatcherAgentName.REFLECTION.value

        return Command(
            update={
                "patch_attempts": last_patch_attempt,
                "execution_info": execution_info,
            },
            goto=next_node,
        )

    def _is_valid_patched_code(self, last_patch_attempt: PatchAttempt, configuration: PatcherConfig) -> bool:
        """Check if the patch does not patch harness code"""
        input_state = {
            "challenge_task_dir": self.challenge.task_dir,
            "work_dir": configuration.work_dir,
            "patch": last_patch_attempt,
        }
        try:
            state_dict = self.check_harness_changes_chain.invoke(
                input_state,
                config=RunnableConfig(
                    recursion_limit=configuration.patch_validation_recursion_limit,
                ),
            )
        except langgraph.errors.GraphRecursionError:
            logger.error("Reached recursion limit for patch validation")
            return False

        try:
            state = PatchValidationState.model_validate(state_dict)
        except ValidationError as e:
            logger.error("Invalid state dict for patch strategy: %s", e)
            return False

        last_msg = str(state.messages[-1].content)
        match = re.search(r"<is_valid>(.*?)</is_valid>", last_msg, re.DOTALL | re.IGNORECASE)
        if match is None:
            logger.error("No is_valid tag found in the output")
            return False

        is_valid = match.group(1).strip().lower() == "true"
        return is_valid

    def _is_valid_patched_language(self, last_patch_attempt: PatchAttempt) -> bool:
        """Check if the patch patches only files in valid languages"""
        assert last_patch_attempt.patch

        # Use unidiff library to parse patch
        patch = PatchSet(StringIO(last_patch_attempt.patch.patch))
        modified_files = [patched_file.path for patched_file in patch]
        # Get language from challenge task project yaml
        language = ProjectYaml(self.challenge, self.challenge.project_name).unified_language

        # Find language identifier binary using importlib resources
        identifier_bin = importlib.resources.files("buttercup.patcher.bins").joinpath("language-identifier")
        identifier_bin = Path(str(identifier_bin)).resolve()
        if not identifier_bin.exists():
            logger.error("Could not find language identifier binary at %s", identifier_bin)
            return False

        # Check each modified file against expected language
        for file_path in modified_files:
            abs_path = Path(self.challenge.get_source_path()) / file_path
            if not abs_path.exists():
                logger.error("Modified file %s does not exist", abs_path)
                return False

            try:
                result = subprocess.run(
                    [str(identifier_bin), "--language", language.value.lower(), "--path", str(abs_path)],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    logger.error("File %s is not valid %s code: %s", abs_path, language, result.stderr)
                    return False
            except subprocess.CalledProcessError as e:
                logger.error("Failed to check language for %s: %s", abs_path, e.stderr)
                return False

        return True

    def validate_patch_node(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[Literal[PatcherAgentName.REFLECTION.value, END]]:  # type: ignore[name-defined]
        """Node in the LangGraph that validates a patch"""
        logger.info(
            "[%s / %s] Validating patch for Challenge Task %s",
            self.input.task_id,
            self.input.submission_index,
            self.challenge.name,
        )
        configuration = PatcherConfig.from_configurable(config)
        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal(
                "[%s / %s] No patch to validate, this should never happen",
                self.input.task_id,
                self.input.submission_index,
            )
            raise RuntimeError("No patch to validate, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.PATCH_VALIDATION

        valid_patched_code = self._is_valid_patched_code(last_patch_attempt, configuration)
        if not valid_patched_code:
            logger.error(
                "[%s / %s] The patched code is not valid, this should never happen",
                self.input.task_id,
                self.input.submission_index,
            )
            last_patch_attempt.status = PatchStatus.VALIDATION_FAILED
            return Command(
                update={
                    "patch_attempts": last_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        valid_patched_language = self._is_valid_patched_language(last_patch_attempt)
        if not valid_patched_language:
            logger.error(
                "[%s / %s] The patch alters code in a language different from the challenge",
                self.input.task_id,
                self.input.submission_index,
            )
            last_patch_attempt.status = PatchStatus.VALIDATION_FAILED
            return Command(
                update={
                    "patch_attempts": last_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        last_patch_attempt.status = PatchStatus.SUCCESS
        logger.info(
            "[%s / %s] Patch for Challenge Task %s is valid",
            self.input.task_id,
            self.input.submission_index,
            self.challenge.name,
        )
        return Command(
            update={
                "patch_attempts": last_patch_attempt,
                "execution_info": execution_info,
            },
            goto=END,
        )
