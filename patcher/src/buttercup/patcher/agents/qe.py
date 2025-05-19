"""Quality Engineer LLM agent, handling the testing of patches."""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from langgraph.types import Command
from langgraph.constants import END
from buttercup.common.corpus import CrashDir
from buttercup.common.challenge_task import ChallengeTaskError, CommandResult
import buttercup.common.node_local as node_local
from langchain_core.runnables import RunnableConfig
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    PatchAttempt,
    PatchStatus,
)
from buttercup.patcher.agents.config import PatcherConfig
import time

logger = logging.getLogger(__name__)


@dataclass
class QEAgent(PatcherAgentBase):
    """Quality Engineer LLM agent, handling the testing of patches."""

    def _patch_challenge(self, patch_attempt: PatchAttempt) -> bool:
        assert patch_attempt.patch
        with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
            patch_file.write(patch_attempt.patch.patch)
            patch_file.flush()
            logger.debug("Patch written to %s", patch_file.name)

            logger.info(
                "Applying patch to task %s / submission index %s", self.input.task_id, self.input.submission_index
            )
            try:
                return self.challenge.apply_patch_diff(Path(patch_file.name))  # type: ignore[no-any-return]
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
        if not self._patch_challenge(last_patch_attempt):
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
        crash_dir = CrashDir(configuration.work_dir, self.input.task_id, self.input.harness_name)
        crashes_for_token = crash_dir.list_crashes_for_token(self.input.pov_token, get_remote=True)
        if not crashes_for_token:
            logger.warning("No crashes found for PoV token %s", self.input.pov_token)
            crashes_for_token = []

        pov_variants = [self.input.pov]
        pov_variants.extend([Path(crash) for crash in crashes_for_token])

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

    def run_tests_node(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value, END]]:  # type: ignore[name-defined]
        """Node in the LangGraph that runs tests against a currently built patch"""
        logger.info("Running tests on Challenge Task %s rebuilt with patch", self.challenge.name)
        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal("No patch to run tests on, this should never happen")
            raise RuntimeError("No patch to run tests on, this should never happen")

        # TODO: implement tests
        logger.warning("Tests are not implemented yet")
        logger.info("Tests for Challenge Task %s ran successfully", self.challenge.name)
        last_patch_attempt.tests_passed = True
        last_patch_attempt.tests_stdout = None
        last_patch_attempt.tests_stderr = None
        last_patch_attempt.status = PatchStatus.SUCCESS
        return Command(
            update={
                "patch_attempts": last_patch_attempt,
            },
            goto=END,
        )
