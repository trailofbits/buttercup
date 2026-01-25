"""Quality Engineer LLM agent, handling the testing of patches."""

import concurrent.futures
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import get_executor_for_config
from langgraph.constants import END
from langgraph.types import Command

from buttercup.common import node_local
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError, CommandResult
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.corpus import CrashDir
from buttercup.common.project_yaml import ProjectYaml
from buttercup.patcher.agents.common import (
    PatchAttempt,
    PatcherAgentBase,
    PatcherAgentName,
    PatcherAgentState,
    PatchStatus,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.patcher.utils import PatchInputPoV

# ruff: noqa: E501

logger = logging.getLogger(__name__)


@dataclass
class _PoVResult:
    """Result of running a PoV test."""

    did_run: bool
    did_crash: bool
    stdout: bytes | None
    stderr: bytes | None


@dataclass
class QEAgent(PatcherAgentBase):
    """Quality Engineer LLM agent, handling the testing of patches."""

    def _patch_challenge(self, challenge: ChallengeTask, patch_attempt: PatchAttempt) -> bool:
        assert patch_attempt.patch
        with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
            patch_file.write(patch_attempt.patch.patch)
            patch_file.flush()
            logger.debug("Patch written to %s", patch_file.name)

            logger.info(
                "Applying patch to task %s / internal patch id %s",
                self.input.task_id,
                self.input.internal_patch_id,
            )
            try:
                return challenge.apply_patch_diff(Path(patch_file.name))
            except ChallengeTaskError:
                if logger.getEffectiveLevel() == logging.DEBUG:
                    logger.exception("Failed to apply patch to Challenge Task %s", self.challenge.name)

                return False

    def _rebuild_challenge(self, challenge: ChallengeTask, sanitizer: str) -> CommandResult:
        # NOTE: for the sake of simplicity, we're using the engine of the first PoV for now.
        #       In AIxCC only libfuzzer is supported, so we can use the engine of the first PoV.
        engine = self.input.povs[0].engine
        try:
            cp_output = challenge.build_fuzzers(
                engine=engine,
                sanitizer=sanitizer,
            )
        except ChallengeTaskError:
            msg = f"Failed to run build_fuzzers on Challenge Task {challenge.name} with patch and sanitizer {sanitizer}"
            logger.warning(msg)
            return CommandResult(success=False, output=msg.encode(), error=b"")

        if not cp_output.success:
            logger.warning("Failed to build Challenge Task %s with patch and sanitizer %s", challenge.name, sanitizer)
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

    def _get_sanitizers(self) -> list[str]:
        """Get the sanitizers for the challenge task"""
        project_yaml = ProjectYaml(self.challenge, self.challenge.project_name)
        return project_yaml.sanitizers

    def _build_with_sanitizer(
        self,
        clean_challenge: ChallengeTask,
        configuration: PatcherConfig,
        last_patch_attempt: PatchAttempt,
        sanitizer: str,
    ) -> tuple[bool, bool, CommandResult, Path | None]:
        """Build the challenge with a specific sanitizer. Returns (patch_success, build_success, result, sanitizer, built_task_dir)"""
        logger.info("Building Challenge Task %s with sanitizer %s", clean_challenge.name, sanitizer)
        with clean_challenge.get_rw_copy(configuration.work_dir, delete=False) as built_challenge:
            logger.info(
                "Patching Challenge Task %s with sanitizer %s (%s)",
                built_challenge.name,
                sanitizer,
                built_challenge.task_dir,
            )
            built_challenge.apply_patch_diff()
            patch_success = self._patch_challenge(built_challenge, last_patch_attempt)
            if not patch_success:
                logger.warning(
                    "Failed to apply patch to Challenge Task %s with sanitizer %s (%s)",
                    self.challenge.name,
                    sanitizer,
                    built_challenge.task_dir,
                )
                return (
                    False,
                    False,
                    CommandResult(success=False, output=b"", error=b"Patch application failed"),
                    None,
                )

            logger.info(
                "Rebuilding Challenge Task %s with sanitizer %s (%s)",
                built_challenge.name,
                sanitizer,
                built_challenge.task_dir,
            )
            cp_output = self._rebuild_challenge(built_challenge, sanitizer)
            if cp_output.success:
                logger.info(
                    "Rebuilt Challenge Task %s with sanitizer %s (%s)",
                    built_challenge.name,
                    sanitizer,
                    built_challenge.task_dir,
                )
                # Return the task directory path for later reuse
                return True, True, cp_output, built_challenge.task_dir
            logger.warning(
                "Failed to rebuild Challenge Task %s with sanitizer %s (%s)",
                built_challenge.name,
                sanitizer,
                built_challenge.task_dir,
            )
            return True, False, cp_output, None

    def build_patch_node(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal["run_pov", "reflection"]]:
        """Node in the LangGraph that builds a patch"""
        logger.info("Rebuilding Challenge Task %s with patch", self.challenge.name)
        configuration = PatcherConfig.from_configurable(config)

        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt or not last_patch_attempt.patch:
            logger.fatal("No patch to build, this should never happen")
            raise RuntimeError("No patch to build, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.BUILD_PATCH

        sanitizers = self._get_sanitizers()
        clean_challenge = self.challenge.get_clean_task(configuration.tasks_storage)
        last_patch_attempt.built_challenges = {}

        # Run builds in parallel
        with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
            # Submit all build tasks
            future_to_sanitizer = {
                executor.submit(
                    self._build_with_sanitizer,
                    clean_challenge,
                    configuration,
                    last_patch_attempt,
                    sanitizer,
                ): sanitizer
                for sanitizer in sanitizers
            }

            # Process completed builds and return immediately on first failure
            # (unless it is AArch64 architecture, where some sanitizers may fail
            # to build)
            for future in concurrent.futures.as_completed(future_to_sanitizer):
                sanitizer = future_to_sanitizer[future]
                try:
                    patch_success, build_success, cp_output, built_task_dir = future.result()
                    last_patch_attempt.build_stdout = cp_output.output
                    last_patch_attempt.build_stderr = cp_output.error

                    if patch_success and build_success and built_task_dir:
                        # Store the successfully built challenge directory
                        last_patch_attempt.built_challenges[sanitizer] = built_task_dir
                        continue

                    if not patch_success:
                        logger.warning(
                            "Failed to apply patch to Challenge Task %s with sanitizer %s",
                            self.challenge.name,
                            sanitizer,
                        )
                        last_patch_attempt.status = PatchStatus.APPLY_FAILED
                    elif not build_success:
                        if ARCHITECTURE == "aarch64":
                            logger.warning(
                                "Failed to rebuild Challenge Task %s with patch and sanitizer %s, but this may happen on AArch64, just move on.",
                                self.challenge.name,
                                sanitizer,
                            )
                            continue

                        logger.warning(
                            "Failed to rebuild Challenge Task %s with patch and sanitizer %s",
                            self.challenge.name,
                            sanitizer,
                        )
                        last_patch_attempt.status = PatchStatus.BUILD_FAILED

                    # Cancel remaining futures and clean up any built challenges
                    for remaining_future in future_to_sanitizer:
                        remaining_future.cancel()

                    # Clean up any successfully built challenge directories since we're failing
                    for built_dir in last_patch_attempt.built_challenges.values():
                        try:
                            ChallengeTask(read_only_task_dir=built_dir, local_task_dir=built_dir).cleanup()
                        except Exception:
                            pass  # Ignore cleanup errors

                    last_patch_attempt.built_challenges = {}

                    return Command(
                        update={
                            "patch_attempts": last_patch_attempt,
                            "execution_info": execution_info,
                        },
                        goto=PatcherAgentName.REFLECTION.value,
                    )
                except Exception as exc:
                    logger.error("Build with sanitizer %s generated an exception: %s", sanitizer, exc)
                    last_patch_attempt.status = PatchStatus.BUILD_FAILED
                    last_patch_attempt.build_stderr = str(exc).encode()

                    # Cancel remaining futures and clean up any built challenges
                    for remaining_future in future_to_sanitizer:
                        remaining_future.cancel()

                    # Clean up any successfully built challenge directories since we're failing
                    for built_dir in last_patch_attempt.built_challenges.values():
                        try:
                            ChallengeTask(read_only_task_dir=built_dir, local_task_dir=built_dir).cleanup()
                        except Exception:
                            pass  # Ignore cleanup errors

                    last_patch_attempt.built_challenges = {}

                    return Command(
                        update={
                            "patch_attempts": last_patch_attempt,
                            "execution_info": execution_info,
                        },
                        goto=PatcherAgentName.REFLECTION.value,
                    )

        if not last_patch_attempt.built_challenges:
            logger.error("Failed to build Challenge Task %s with any sanitizer", self.challenge.name)
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

    def _get_pov_variants(self, configuration: PatcherConfig, povs: list[PatchInputPoV]) -> list[PatchInputPoV]:
        """Get the variants of the PoV"""
        res = {pov.pov.absolute(): pov for pov in povs}

        sanitizers = self._get_sanitizers()
        for pov in povs:
            try:
                crash_dir = CrashDir(str(configuration.work_dir), self.input.task_id, pov.harness_name)
                for sanitizer in sanitizers:
                    crashes_for_token = crash_dir.list_crashes_for_token(pov.pov_token, sanitizer, get_remote=True)
                    if not crashes_for_token:
                        logger.info("No crashes found for PoV token %s and sanitizer %s", pov.pov_token, sanitizer)
                        crashes_for_token = []

                    res.update(
                        {
                            Path(crash).absolute(): PatchInputPoV(
                                challenge_task_dir=pov.challenge_task_dir,
                                sanitizer=sanitizer,
                                pov=Path(crash),
                                engine=pov.engine,
                                pov_token=pov.pov_token,
                                harness_name=pov.harness_name,
                            )
                            for crash in crashes_for_token[: configuration.max_pov_variants_per_token_sanitizer]
                        },
                    )
            except Exception:
                logger.exception("Failed to list PoV variants for token %s", pov.pov_token)

        # Remove original POVs from the result and move them to the beginning so they get tested first
        for pov in povs:
            try:
                res.pop(pov.pov.absolute())
            except KeyError:
                logger.warning(
                    "PoV %s not found in res, this should never happen. Skipping it, but continuing.",
                    pov.pov,
                )

        return povs + list(res.values())

    def run_pov_node(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal["run_tests", "reflection"]]:
        """Node in the LangGraph that runs a PoV against a currently built patch"""
        configuration = PatcherConfig.from_configurable(config)
        logger.info("Testing PoVs on Challenge Task %s rebuilt with patch", self.challenge.name)
        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal("No patch to run PoV on, this should never happen")
            raise RuntimeError("No patch to run PoV on, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.RUN_POV
        pov_variants = self._get_pov_variants(configuration, state.context.povs)
        logger.info("Running %d PoV variants", len(pov_variants))

        start_time = time.time()
        run_once = False

        def run_pov(pov_variant: PatchInputPoV) -> _PoVResult:
            """Run a single PoV and return the result."""
            try:
                pov_variant_crash = node_local.make_locally_available(pov_variant.pov)
                challenge_to_use = last_patch_attempt.get_built_challenge(pov_variant.sanitizer)
                if not challenge_to_use:
                    logger.error(
                        "[%s / %s] No pre-built challenge for sanitizer %s, skipping PoV",
                        self.challenge.task_meta.task_id,
                        self.input.internal_patch_id,
                        pov_variant.sanitizer,
                    )
                    return _PoVResult(did_run=False, did_crash=False, stdout=None, stderr=None)

                pov_output = challenge_to_use.reproduce_pov(pov_variant.harness_name, pov_variant_crash)
                logger.info(
                    "[%s / %s] Ran PoV %s/%s for harness %s",
                    self.challenge.task_meta.task_id,
                    self.input.internal_patch_id,
                    challenge_to_use.name,
                    pov_variant_crash,
                    pov_variant.harness_name,
                )
                logger.debug("PoV stdout: %s", pov_output.command_result.output)
                logger.debug("PoV stderr: %s", pov_output.command_result.error)

                if not pov_output.did_run():
                    logger.warning(
                        "[%s / %s] PoV %s did not run, skipping",
                        self.challenge.task_meta.task_id,
                        self.input.internal_patch_id,
                        pov_variant_crash,
                    )
                    return _PoVResult(did_run=False, did_crash=False, stdout=None, stderr=None)

                return _PoVResult(
                    did_run=True,
                    did_crash=pov_output.did_crash(),
                    stdout=pov_output.command_result.output,
                    stderr=pov_output.command_result.error,
                )

            except ChallengeTaskError:
                msg = f"Failed to run pov for Challenge Task {self.challenge.name}"
                logger.error(msg)
                return _PoVResult(did_run=False, did_crash=True, stdout=msg.encode(), stderr=b"")

        # Run PoVs in parallel
        with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
            # Submit all PoV tasks
            future_to_pov = {executor.submit(run_pov, pov_variant): pov_variant for pov_variant in pov_variants}

            def _handle_failure(
                pov_stdout: bytes | None,
                pov_stderr: bytes | None,
                goto_node: PatcherAgentName = PatcherAgentName.REFLECTION,
            ) -> Command:
                last_patch_attempt.pov_fixed = False
                last_patch_attempt.pov_stdout = pov_stdout
                last_patch_attempt.pov_stderr = pov_stderr
                last_patch_attempt.status = PatchStatus.POV_FAILED

                # Cancel remaining futures
                for remaining_future in future_to_pov:
                    remaining_future.cancel()

                return Command(
                    update={
                        "patch_attempts": last_patch_attempt,
                        "execution_info": execution_info,
                    },
                    goto=goto_node.value,
                )

            # Process completed PoVs and return immediately on first crash
            for future in concurrent.futures.as_completed(future_to_pov):
                # Check if we've exceeded the max_minutes_run_povs timeout
                if time.time() - start_time > configuration.max_minutes_run_povs * 60:
                    logger.warning("PoV processing lasted more than %d minutes", configuration.max_minutes_run_povs)
                    if run_once:
                        logger.info(
                            "[%s / %s] PoV processing lasted more than %d minutes, but we already ran (at least) one PoV successfully, so we'll stop here",
                            self.challenge.task_meta.task_id,
                            self.input.internal_patch_id,
                            configuration.max_minutes_run_povs,
                        )
                        break

                    return _handle_failure(
                        f"Operation timed out after {configuration.max_minutes_run_povs} minutes".encode(),
                        None,
                    )

                try:
                    result = future.result()
                    if result.did_run:
                        run_once = True
                        if result.did_crash:
                            return _handle_failure(result.stdout, result.stderr)

                except Exception as exc:
                    logger.error("PoV execution generated an exception: %s", exc)
                    return _handle_failure(str(exc).encode(), None)

        if not run_once:
            logger.error("No PoVs could be run, this should never happen")
            return _handle_failure(None, None, PatcherAgentName.ROOT_CAUSE_ANALYSIS)

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
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal["reflection", "__end__"]]:
        """Node in the LangGraph that runs tests against a currently built patch"""
        logger.info(
            "[%s / %s] Running tests on Challenge Task %s rebuilt with patch",
            self.input.task_id,
            self.input.internal_patch_id,
            self.challenge.name,
        )
        configuration = PatcherConfig.from_configurable(config)

        last_patch_attempt = state.get_last_patch_attempt()
        if not last_patch_attempt:
            logger.fatal(
                "[%s / %s] No patch to run tests on, this should never happen",
                self.input.task_id,
                self.input.internal_patch_id,
            )
            raise RuntimeError("No patch to run tests on, this should never happen")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.RUN_TESTS

        if not last_patch_attempt.build_succeeded or not last_patch_attempt.pov_fixed:
            logger.error(
                "[%s / %s] The patch needs to be built and PoV needs to be fixed before running tests",
                self.input.task_id,
                self.input.internal_patch_id,
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
            sh_cmd_res = None
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

            if sh_cmd_res is not None:
                tests_passed = sh_cmd_res.success
                last_patch_attempt.tests_stdout = sh_cmd_res.output
                last_patch_attempt.tests_stderr = sh_cmd_res.error
            else:
                logger.warning("Failed to run tests for Challenge Task %s", clean_challenge.name)
                last_patch_attempt.status = PatchStatus.TESTS_FAILED
                last_patch_attempt.tests_passed = False
                last_patch_attempt.tests_stdout = None
                last_patch_attempt.tests_stderr = None
        else:
            logger.warning(
                "[%s / %s] No tests instructions found, just accept the patch",
                self.input.task_id,
                self.input.internal_patch_id,
            )
            tests_passed = True

        last_patch_attempt.tests_passed = tests_passed
        if tests_passed:
            logger.info(
                "[%s / %s] Tests for Challenge Task %s ran successfully",
                self.input.task_id,
                self.input.internal_patch_id,
                self.challenge.name,
            )
            next_node = END
        else:
            logger.warning(
                "[%s / %s] Tests failed for Challenge Task %s",
                self.input.task_id,
                self.input.internal_patch_id,
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
