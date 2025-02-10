import argparse
import logging
import os
from buttercup.common.logger import setup_package_logger
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.datastructures.msg_pb2 import WeightedHarness
from buttercup.common.maps import BUILD_TYPES
from typing import List
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.corpus import Corpus
from buttercup.fuzzing_infra.coverage_runner import CoverageRunner
from buttercup.common.oss_fuzz_tool import OSSFuzzTool, Conf
from buttercup.common import utils
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class CoverageBot(TaskLoop):
    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        wdir: str,
        python: str,
        allow_pull: bool,
        base_image_url: str,
        llvm_cov_tool: str,
    ):
        self.wdir = wdir
        self.python = python
        self.allow_pull = allow_pull
        self.base_image_url = base_image_url
        self.llvm_cov_tool = llvm_cov_tool
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BUILD_TYPES]:
        return [BUILD_TYPES.COVERAGE]

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        coverage_build = builds[BUILD_TYPES.COVERAGE]
        logger.info(f"Coverage build: {coverage_build}")
        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            corpus = Corpus(self.wdir, task.task_id, task.harness_name)
            output_oss_fuzz_path = Path(td) / "coverage-oss-fuzz"
            utils.copyanything(coverage_build.output_ossfuzz_path, output_oss_fuzz_path)

            runner = CoverageRunner(
                OSSFuzzTool(
                    Conf(coverage_build.output_ossfuzz_path, self.python, self.allow_pull, self.base_image_url)
                ),
                self.llvm_cov_tool,
            )
            runner.run(task.harness_name, corpus.path, coverage_build.package_name)
            logger.info(
                f"Coverage for {task.harness_name} | {coverage_build.package_name} | {task.task_id} | {corpus.path} | {coverage_build.output_ossfuzz_path}"
            )


def main():
    prsr = argparse.ArgumentParser("coverage bot")
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--wdir", required=True)
    prsr.add_argument("--python", default="python")
    prsr.add_argument("--allow-pull", action="store_true", default=False)
    prsr.add_argument("--base-image-url", default="gcr.io/oss-fuzz")
    prsr.add_argument("--llvm-cov-tool", default="llvm-cov")
    args = prsr.parse_args()
    setup_package_logger(__name__, "DEBUG")

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting coverage bot (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    fuzzer = CoverageBot(
        Redis.from_url(args.redis_url),
        seconds_sleep,
        args.wdir,
        args.python,
        args.allow_pull,
        args.base_image_url,
        args.llvm_cov_tool,
    )
    fuzzer.run()


if __name__ == "__main__":
    main()
