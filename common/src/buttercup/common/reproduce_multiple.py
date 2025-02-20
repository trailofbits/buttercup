from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.challenge_task import ReproduceResult, ChallengeTask
from pathlib import Path
from typing import Generator


class ReproduceMultiple:
    def __init__(self, wdir: Path, build_outputs: list[BuildOutput]) -> None:
        self.build_outputs = build_outputs
        self.wdir = wdir

    def attempt_reproduce(
        self, pov: Path, harness_name: str
    ) -> Generator[tuple[BuildOutput, ReproduceResult], None, None]:
        for build in self.build_outputs:
            task = ChallengeTask(read_only_task_dir=build.task_dir)
            with task.get_rw_copy(self.wdir) as local_task:
                yield (build, local_task.reproduce_pov(harness_name, pov))

    def get_first_crash(self) -> tuple[BuildOutput, ReproduceResult] | None:
        for build, result in self.attempt_reproduce():
            if result.command_result.returncode is not None and result.stacktrace() is not None and result.did_crash():
                return build, result
        return None
