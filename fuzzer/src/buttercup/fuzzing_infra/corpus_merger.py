from buttercup.common import node_local
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
from dataclasses import dataclass
import os
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.corpus import Corpus
from buttercup.common.maps import HarnessWeights, BuildMap
from buttercup.common.utils import serve_loop, setup_periodic_zombie_reaper
from buttercup.common.logger import setup_package_logger
from redis import Redis
from typing import List
import random
from buttercup.common.datastructures.msg_pb2 import BuildOutput
import logging
from buttercup.common.challenge_task import ChallengeTask
from buttercup.fuzzing_infra.settings import FuzzerBotSettings
from buttercup.common.sets import MergedCorpusSetLock
from buttercup.common.constants import ADDRESS_SANITIZER
from buttercup.common.sets import FailedToAcquireLock
from buttercup.common.sets import MERGING_LOCK_TIMEOUT_SECONDS
from buttercup.common.telemetry import init_telemetry
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory
import datetime
import shutil
from tempfile import TemporaryDirectory

logger = logging.getLogger(__name__)

# NOTE: The idea of using three distinct classes to represent the local, remote, and merged corpuses
#       is to make the code more readable and easier to understand.
#       The BaseCorpus class is used to represent the initial corpus state, before any merge operations have been performed.
#       The PartitionedCorpus class is used to partition the corpus into local and remote parts.
#       The FinalCorpus class is used to represent the corpus after the merge operation has been performed.


@dataclass
class FinalCorpus:
    """
    Represents the corpus after the merge operation has been performed.
    """

    def __init__(self, corpus: Corpus, push_remotely: set[str], delete_locally: set[str]):
        self._corpus = corpus
        self._push_remotely = push_remotely
        self._delete_locally = delete_locally

    def push_remotely(self) -> int:
        """
        Push the files to remote storage.
        """
        n = 0
        if self._push_remotely:
            n = len(self._push_remotely)
            self._corpus.sync_specific_files_to_remote(self._push_remotely)
            self._push_remotely.clear()
        return n

    def delete_locally(self):
        """
        Delete the files from local storage.
        """
        n = 0
        for file in self._delete_locally:
            try:
                self._corpus.remove_local_file(file)
                n += 1
            except Exception as e:
                # Ignore this as we will ge a new chance next time the merger runs
                logger.error(f"Error removing file {file} from local corpus {self._corpus.path}: {e}")
        self._delete_locally.clear()
        return n


@dataclass
class PartitionedCorpus:
    """
    Represents the corpus split into local and remote parts.
    """

    corpus: Corpus
    local_dir: TemporaryDirectory
    remote_dir: TemporaryDirectory
    local_only_files: set[str]
    remote_files: set[str]
    max_local_files: int = 500

    def __post_init__(self):
        # Shuffle and limit the local_only_files to max_local_files
        local_files_list = list(self.local_only_files)
        random.shuffle(local_files_list)

        # Keep track of successfully copied files
        new_local_only_files = set()

        for file in local_files_list:
            try:
                shutil.copy(os.path.join(self.corpus.path, file), os.path.join(self.local_dir, file))
                new_local_only_files.add(file)
                if len(new_local_only_files) >= self.max_local_files:
                    break
            except Exception as e:
                logger.error(f"Error copying file {file} to local directory: {e}. Will be ignored in merge.")

        # These are the files that will be processed in the merge operation,
        # as we have limited the number of files to process to max_local_files.
        # Also, if files failed to copy, they will be removed from the local_only_files set.
        self.local_only_files = new_local_only_files

        for file in self.remote_files:
            try:
                shutil.copy(os.path.join(self.corpus.path, file), os.path.join(self.remote_dir, file))
            except Exception as e:
                # Copy this from the remote storage instead (slow, but shouldn't dissappear from there)
                shutil.copy(os.path.join(self.corpus.remote_path, file), os.path.join(self.remote_dir, file))
                logger.debug(f"Error copying file {file} to remote directory: {e}. Copied from remote storage instead.")

    def to_final(self) -> FinalCorpus:
        """
        Returns a FinalCorpus object that represents the corpus after the merge operation has been performed.
        NOTE: This should be called after the merge operation has been performed.

        Will rehash any files in the remote_directory as the merge operation may have changed the file names.
        Then it will partition the files into push_remotely and delete_locally sets and return a FinalCorpus object.
        """
        self.corpus.hash_corpus(self.remote_dir)

        # Partition the files into push_remotely and delete_locally sets
        files_in_new_remote_dir = set(os.listdir(self.remote_dir))

        # All remote files must still be in merged files
        assert self.remote_files.issubset(files_in_new_remote_dir), "Some remote files were lost during merge"
        # Only files from remote_files and local_only_files should be in merged_files
        assert files_in_new_remote_dir.issubset(self.remote_files.union(self.local_only_files)), (
            "Unexpected files appeared in merge output"
        )

        # These are the local files that add coverage (they are now both in the remote and local corpus)
        push_remotely = self.local_only_files & files_in_new_remote_dir

        # These are the local files that don't add coverage (they are only in the local corpus)
        delete_locally = self.local_only_files - files_in_new_remote_dir

        return FinalCorpus(self.corpus, push_remotely, delete_locally)


@dataclass
class BaseCorpus:
    """
    Represents the initial corpus state, before any merge operations have been performed.
    - local_dir: TemporaryDirectory for the local corpus
    - remote_dir: TemporaryDirectory for the remote corpus

    NOTE: Before `partition_corpus` is called, it is required that the `MergedCorpusSetLock` is held.
    Otherwise, we risk adding more corpus to remote storage than is needed from a coverage perspective.
    """

    corpus: Corpus
    local_dir: TemporaryDirectory
    remote_dir: TemporaryDirectory
    max_local_files: int = 500

    def partition_corpus(self) -> PartitionedCorpus:
        """
        1. Collect the remote corpus files
        2. Collect the list of files only available remotely
        3. Partition the corpus into two sets,
            - files that are in the remote corpus,
            - files that are only in the local corpus.
        4. Return a PartitionedCorpus object (which takes care of copying the files to the correct directories)

        NOTE: This should be called before running the merge operation.
        """
        self.corpus.sync_from_remote()

        local_files = set([os.path.basename(x) for x in self.corpus.list_local_corpus() if Corpus.has_hashed_name(x)])
        remote_files = set([os.path.basename(x) for x in self.corpus.list_remote_corpus() if Corpus.has_hashed_name(x)])

        local_only_files = local_files - remote_files

        return PartitionedCorpus(
            corpus=self.corpus,
            local_dir=self.local_dir,
            remote_dir=self.remote_dir,
            local_only_files=local_only_files,
            remote_files=remote_files,
            max_local_files=self.max_local_files,
        )


class MergerBot:
    def __init__(
        self, redis: Redis, timeout_seconds: int, python: str, crs_scratch_dir: str, max_local_files: int = 500
    ):
        self.redis = redis
        self.runner = Runner(Conf(timeout_seconds))
        self.python = python
        self.crs_scratch_dir = crs_scratch_dir
        self.harness_weights = HarnessWeights(redis)
        self.builds = BuildMap(redis)
        self.max_local_files = max_local_files

    def required_builds(self) -> List[BuildTypeHint]:
        return [BuildType.FUZZER]

    def _run_merge_operation(self, task, build, remote_dir, local_dir, local_only_files, remote_files, corp: Corpus):
        """
        Run the merge operation to find which local files add coverage.

        Args:
            task: The WeightedHarness object
            build: The BuildOutput object
            remote_dir: Path to the remote directory (R)
            local_dir: Path to the local directory (L)
            local_only_files: Set of files only in the local corpus
            remote_files: Set of files in the remote corpus
            corp: The Corpus object

        Returns:
            No return value - files that add coverage will be moved to remote_dir
        """
        with node_local.scratch_dir() as td:
            tsk = ChallengeTask(read_only_task_dir=build.task_dir, python_path=self.python)
            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                build_dir = local_tsk.get_build_dir()

                # Run merge from local_dir to remote_dir to find which files add coverage
                fuzz_conf = FuzzConfiguration(
                    local_dir,
                    str(build_dir / task.harness_name),
                    build.engine,
                    build.sanitizer,
                )

                logger.info(f"Starting fuzzer merge for {build.engine} | {build.sanitizer} | {task.harness_name}")

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

                    # We specify the remote_dir as the target dir as that will cause any `local_dir` files that adds coverage to be moved to remote_dir.
                    self.runner.merge_corpus(fuzz_conf, remote_dir)
                    span.set_status(Status(StatusCode.OK))

    def run_task(self, task: WeightedHarness, builds: list[BuildOutput]):
        """
        Strategy:
        Given a task/WeightedHarness, we want to merge the local corpus into the remote corpus if it adds coverage
           - acquire a lock on the merged corpus set, if not possible, return and move on to next task
           - ensure all of the remotely stored corpus files are available locally
           - partition the the local corpus into R and L, where R is the remote corpus and L is the local corpus excluding remote files (L = local_files - remote_files)
           - if L is empty the node is up to date, release the lock and move on to next task.
           - copy the local corpus into R and L directories respectively
           - run merger on R and L, moving files from L to R if they add coverage
           - (unfortunately re-hash the files in R to get the original names)
           - push any file in R that was previously not available remotely
           - remove any files only in L from the local corpus (as we know those don't add any coverage)
           - release the lock on the merged corpus set
        """

        logger.debug(f"Running merge pass for {task.harness_name} | {task.package_name} | {task.task_id}")

        build = next(iter([b for b in builds if b.sanitizer == ADDRESS_SANITIZER]), None)
        if build is None:
            build = random.choice(builds)

        # Initialize corpus outside of the temporary directory
        corp = Corpus(self.crs_scratch_dir, task.task_id, task.harness_name)

        # Hash local corpus files to ensure they are named appropriately
        corp.hash_new_corpus()

        # We need to acquire a lock to ensure that we dont double remove a conflict
        try:
            with MergedCorpusSetLock(
                self.redis, task.task_id, task.harness_name, MERGING_LOCK_TIMEOUT_SECONDS
            ).acquire():
                # Create scratch directories for remote (R) and local-only (L) corpus parts, and copy files
                with node_local.scratch_dir() as remote_dir, node_local.scratch_dir() as local_dir:
                    # Create BaseCorpus and partition it
                    base_corpus = BaseCorpus(corp, local_dir, remote_dir, self.max_local_files)
                    partitioned_corpus = base_corpus.partition_corpus()

                    # If L is empty, the node is up to date
                    if not partitioned_corpus.local_only_files:
                        logger.debug(
                            f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} because local corpus is up to date"
                        )
                        return False  # We did not do any work

                    logger.info(
                        f"Found {len(partitioned_corpus.local_only_files)} files only in local corpus for {task.harness_name}. Will run merge operation."
                    )

                    try:
                        # Run the merge operation
                        self._run_merge_operation(
                            task,
                            build,
                            remote_dir,
                            local_dir,
                            partitioned_corpus.local_only_files,
                            partitioned_corpus.remote_files,
                            corp,
                        )
                    except Exception as e:
                        logger.error(f"Error during merge operation: {e}")
                        raise e

                    # Create FinalCorpus which represents the state after the merge
                    final_corpus = partitioned_corpus.to_final()

                    # Push any files that add coverage to remote
                    push_count = final_corpus.push_remotely()
                    if push_count > 0:
                        logger.info(f"Synced {push_count} files that add coverage to remote corpus")

                    # Remove any files that don't add coverage
                    remove_count = final_corpus.delete_locally()
                    if remove_count > 0:
                        logger.info(
                            f"Removed {remove_count} files from local corpus {corp.path} that don't add coverage"
                        )

                    return True  # We did work

        except FailedToAcquireLock:
            logger.debug(
                f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} because another worker is already merging"
            )
        except Exception as e:
            logger.error(f"Error merging corpus: {e}")
            raise e

        return False  # We did not do any work

    def serve_item(self) -> bool:
        weighted_items: list[WeightedHarness] = [wh for wh in self.harness_weights.list_harnesses() if wh.weight > 0]
        if len(weighted_items) <= 0:
            return False

        did_work = False
        n_exceptions = 0
        random.shuffle(weighted_items)
        for item in weighted_items:
            builds = self.builds.get_builds(item.task_id, BuildType.FUZZER)
            if len(builds) <= 0:
                continue

            # We have the builds so we can run the task
            try:
                if self.run_task(item, builds):
                    did_work = True
            except Exception as e:
                n_exceptions += 1
                logger.error(f"Error running task: {e}")
                if n_exceptions > 1:
                    # The assumption is that a single exception is due to a temporary issue, where as multiple
                    # exceptions are due to a more serious issue and we should restart the bot.
                    logger.warning("Multiple exceptions occurred while running tasks, restarting")
                    raise e

        return did_work

    def run(self):
        serve_loop(self.serve_item, 10.0)


def main():
    args = FuzzerBotSettings()

    setup_package_logger("corpus-merger", __name__, args.log_level, args.log_max_line_length)
    init_telemetry("merger-bot")

    setup_periodic_zombie_reaper()

    logger.info(f"Starting merger (crs_scratch_dir: {args.crs_scratch_dir})")

    merger = MergerBot(
        Redis.from_url(args.redis_url), args.timeout, args.python, args.crs_scratch_dir, args.max_local_files
    )
    merger.run()


if __name__ == "__main__":
    main()
