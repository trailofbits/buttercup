from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import os
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.corpus import Corpus
import tempfile
from buttercup.common.logger import setup_package_logger
from redis import Redis
from buttercup.common.default_task_loop import TaskLoop
from typing import List
import random
from buttercup.common.datastructures.msg_pb2 import BuildOutput
import logging
from buttercup.common.challenge_task import ChallengeTask
from buttercup.fuzzing_infra.settings import FuzzerBotSettings
from buttercup.common.sets import MergedCorpusSet, MergedCorpusSetLock
from buttercup.common.constants import ADDRESS_SANITIZER
from buttercup.common.sets import FailedToAcquireLock
from buttercup.common.sets import MERGING_LOCK_TIMEOUT_SECONDS
from buttercup.common.telemetry import init_telemetry
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory
import datetime

# It doesnt make much sense to run a merge on a really small corpus
MERGE_LIMIT_COUNT = 100

logger = logging.getLogger(__name__)


class MergerBot(TaskLoop):
    def __init__(
        self, redis: Redis, timer_seconds: int, timeout_seconds: int, wdir: str, python: str, crs_scratch_dir: str
    ):
        self.wdir = wdir
        self.runner = Runner(Conf(timeout_seconds))
        self.python = python
        self.crs_scratch_dir = crs_scratch_dir
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BuildTypeHint]:
        return [BuildType.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, list[BuildOutput]]):
        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            logger.info(f"Running merge pass for {task.harness_name} | {task.package_name} | {task.task_id}")

            build = next(iter([b for b in builds[BuildType.FUZZER] if b.sanitizer == ADDRESS_SANITIZER]), None)
            if build is None:
                build = random.choice(builds[BuildType.FUZZER])

            tsk = ChallengeTask(read_only_task_dir=build.task_dir, python_path=self.python)
            corp = Corpus(self.crs_scratch_dir, task.task_id, task.harness_name)
            if corp.local_corpus_count() < MERGE_LIMIT_COUNT:
                logger.info(
                    f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} because corpus is too small"
                )
                return
            # We need to acquire a lock to ensure that we dont double remove a conflict
            try:
                with MergedCorpusSetLock(
                    self.redis, task.task_id, task.harness_name, MERGING_LOCK_TIMEOUT_SECONDS
                ).acquire():
                    with tsk.get_rw_copy(work_dir=td) as local_tsk:
                        logger.info(f"Build dir: {local_tsk.get_build_dir()}")

                        # It must be the case that we view all removes after we acquire the lock so
                        # we guarentee we dont double remove a conflict
                        corp.remove_any_merged(self.redis)
                        merged_corpus_set = MergedCorpusSet(self.redis, task.task_id, task.harness_name)
                        build_dir = local_tsk.get_build_dir()
                        fuzz_conf = FuzzConfiguration(
                            corp.path,
                            str(build_dir / task.harness_name),
                            build.engine,
                            build.sanitizer,
                        )
                        logger.info(f"Starting fuzzer {build.engine} | {build.sanitizer} | {task.harness_name}")

                        try:
                            with tempfile.TemporaryDirectory() as td:
                                will_definitely_be_merged = set([os.path.basename(x) for x in corp.list_local_corpus()])

                                # log telemetry
                                tracer = trace.get_tracer(__name__)
                                with tracer.start_as_current_span("merge_corpus") as span:
                                    set_crs_attributes(
                                        span,
                                        crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                                        crs_action_name="merge_corpus",
                                        task_metadata=dict(tsk.task_meta.metadata),
                                        extra_attributes={
                                            "crs.action.target.harness": task.harness_name,
                                            "crs.action.target.sanitizer": build.sanitizer,
                                            "crs.action.target.engine": build.engine,
                                            "fuzz.corpus.size": corp.local_corpus_size(),
                                            "fuzz.corpus.update.method": "merge",
                                            "fuzz.corpus.update.time": datetime.datetime.now().isoformat(),
                                        },
                                    )
                                    self.runner.merge_corpus(fuzz_conf, td)
                                    span.set_status(Status(StatusCode.OK))

                                dest_names = [os.path.basename(x) for x in corp.copy_corpus(td)]
                                to_remove = will_definitely_be_merged.difference(dest_names)
                                corp.sync_to_remote()
                                removed_number = 0
                                for file in to_remove:
                                    merged_corpus_set.add(file)
                                    try:
                                        removed_number += 1
                                        corp.remove_file(file)
                                    except Exception as e:
                                        # This can happen if the file is removed by another coverage worker in the remote
                                        logger.error(f"Error removing file {file} from local corpus {corp.path}: {e}")
                                logger.info(f"Removed {removed_number} files from local corpus {corp.path}")
                        except Exception as e:
                            logger.error(f"Error merging corpus: {e}")
                            raise e
            except FailedToAcquireLock:
                logger.info(
                    f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} because another worker is already merging"
                )


def main():
    args = FuzzerBotSettings()

    setup_package_logger("corpus-merger", __name__, args.log_level)
    init_telemetry("merger-bot")

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir} crs_scratch_dir: {args.crs_scratch_dir})")

    seconds_sleep = args.timer // 1000
    merger = MergerBot(
        Redis.from_url(args.redis_url), seconds_sleep, args.timeout, args.wdir, args.python, args.crs_scratch_dir
    )
    merger.run()


if __name__ == "__main__":
    main()
