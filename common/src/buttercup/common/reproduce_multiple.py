from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.challenge_task import ReproduceResult, ChallengeTask
from pathlib import Path
from typing import Generator
from contextlib import contextmanager
import contextlib
import logging

logger = logging.getLogger(__name__)


class ReproduceMultiple:
    def __init__(self, wdir: Path, build_outputs: list[BuildOutput], build_cache: list[ChallengeTask] = None) -> None:
        self.build_outputs = build_outputs
        self.wdir = wdir
        self.builds_cache: list[ChallengeTask] = build_cache

    @contextmanager
    def open(self) -> Generator["ReproduceMultiple", None, None]:
        with contextlib.ExitStack() as stack:
            cache = []
            for build in self.build_outputs:
                task = ChallengeTask(read_only_task_dir=build.task_dir)
                cpy = stack.enter_context(task.get_rw_copy(self.wdir))
                cache.append(cpy)
            copied_mult = ReproduceMultiple(self.wdir, self.build_outputs, cache)
            try:
                yield copied_mult
            finally:
                pass

    def attempt_reproduce(
        self, pov: Path, harness_name: str
    ) -> Generator[tuple[BuildOutput, ReproduceResult], None, None]:
        if self.builds_cache is None:
            raise RuntimeError("Build cache is not populated")
        for build, task in zip(self.build_outputs, self.builds_cache):
            yield (build, task.reproduce_pov(harness_name, pov))

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
