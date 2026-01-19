import contextlib
import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from buttercup.common.build_selection import SelectedBuild, select_build_for_harness
from buttercup.common.challenge_task import ChallengeTask, ReproduceResult
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType

logger = logging.getLogger(__name__)


class ReproduceMultiple:
    def __init__(
        self,
        wdir: Path,
        build_outputs: list[BuildOutput],
        build_cache: list[ChallengeTask] | None = None,
    ) -> None:
        self.build_outputs = build_outputs
        self.wdir = wdir
        self.builds_cache = build_cache

    @contextmanager
    def open(self) -> Generator["ReproduceMultiple", None, None]:
        with contextlib.ExitStack() as stack:
            cache = []
            for build in self.build_outputs:
                task = ChallengeTask(read_only_task_dir=Path(build.task_dir))
                cpy = stack.enter_context(task.get_rw_copy(self.wdir))
                cache.append(cpy)
            copied_mult = ReproduceMultiple(self.wdir, self.build_outputs, cache)
            try:
                yield copied_mult
            finally:
                pass

    def attempt_reproduce(
        self,
        pov: Path,
        harness_name: str,
    ) -> Generator[tuple[BuildOutput, ReproduceResult], None, None]:
        if self.builds_cache is None:
            raise RuntimeError("Build cache is not populated")
        
        # Log all available builds before testing
        logger.info(f"Testing PoV '{pov.name}' against {len(self.build_outputs)} builds for harness '{harness_name}'")
        for i, build in enumerate(self.build_outputs):
            logger.info(f"  Build {i}: sanitizer={build.sanitizer}, engine={build.engine}, type={BuildType.Name(build.build_type)}, task_id={build.task_id}")
        
        for build, task in zip(self.build_outputs, self.builds_cache, strict=False):
            # Skip FUZZER_DEBUG builds when testing PoVs - they don't have sanitizers
            # and won't detect bugs. FUZZER_DEBUG is only for interactive debugging.
            if build.build_type == BuildType.FUZZER_DEBUG:
                logger.debug(
                    f"Skipping FUZZER_DEBUG build for PoV testing (task_id: {build.task_id}). "
                    f"Debug builds don't have sanitizers and won't detect bugs."
                )
                continue
            
            logger.info(f"Testing PoV '{pov.name}' with sanitizer={build.sanitizer}, engine={build.engine}")
            result = task.reproduce_pov(harness_name, pov)
            logger.info(f"  Result: did_run={result.did_run()}, did_crash={result.did_crash()}, returncode={result.command_result.returncode if result.command_result else 'N/A'}")
            yield (build, result)

    def get_first_crash(self, pov: Path, harness_name: str) -> tuple[BuildOutput, ReproduceResult] | None:
        for build, result in self.attempt_reproduce(pov, harness_name):
            if not result.did_run():
                logger.warning("Failed to reproduce pov for task %s", build.task_id)
                logger.debug(
                    "Task %s, stdout: %s, stderr: %s",
                    build.task_id,
                    result.command_result.output,
                    result.command_result.error,
                )
                continue
            if result.did_crash():
                return build, result
        return None

    def get_crashes(self, pov: Path, harness_name: str) -> Generator[tuple[BuildOutput, ReproduceResult], None, None]:
        for build, result in self.attempt_reproduce(pov, harness_name):
            if not result.did_run():
                logger.warning("Failed to reproduce pov for task %s", build.task_id)
                logger.debug(
                    "Task %s, stdout: %s, stderr: %s",
                    build.task_id,
                    result.command_result.output,
                    result.command_result.error,
                )
                continue
            if result.did_crash():
                yield build, result

    def select_build_for_harness(
        self,
        harness_name: str,
        prefer_sanitizer: str = "address",
    ) -> SelectedBuild | None:
        """Select the best build that contains the specified harness.

        This is a convenience wrapper around build_selection.select_build_for_harness.

        Args:
            harness_name: Name of the harness binary to find
            prefer_sanitizer: Preferred sanitizer type (default: "address")

        Returns:
            SelectedBuild with build_output and task, or None if no builds available
        """
        if self.builds_cache is None or not self.builds_cache:
            return None

        return select_build_for_harness(
            self.build_outputs,
            self.builds_cache,
            harness_name,
            prefer_sanitizer,
        )
