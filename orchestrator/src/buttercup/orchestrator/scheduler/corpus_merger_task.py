"""Corpus merger background task for the scheduler.

This module integrates the corpus merger functionality as a background task
within the scheduler, eliminating the need for a separate service container.
"""

from __future__ import annotations

import datetime
import logging
import os
import random
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis import Redis

from buttercup.common import node_local
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.constants import ADDRESS_SANITIZER
from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, WeightedHarness
from buttercup.common.maps import BuildMap, HarnessWeights
from buttercup.common.sets import FailedToAcquireLock, MERGING_LOCK_TIMEOUT_SECONDS, MergedCorpusSetLock
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.orchestrator.scheduler.background_tasks import BackgroundTask

logger = logging.getLogger(__name__)


class CorpusMergerTask(BackgroundTask):
    """Background task for merging local and remote fuzzing corpuses."""

    def __init__(
        self,
        redis: Redis,
        crs_scratch_dir: str,
        python: str = "python",
        interval: float = 10.0,
        timeout_seconds: int = 300,
        max_local_files: int = 500,
    ):
        super().__init__(name="corpus-merger", interval=interval)
        self.redis = redis
        self.crs_scratch_dir = crs_scratch_dir
        self.python = python
        self.timeout_seconds = timeout_seconds
        self.max_local_files = max_local_files
        self.harness_weights = HarnessWeights(redis)
        self.builds = BuildMap(redis)
        self._runner = None

    @property
    def runner(self):
        """Lazy load the runner to avoid import issues during testing."""
        if self._runner is None:
            try:
                from buttercup.fuzzing_infra.runner import Conf, Runner
                self._runner = Runner(Conf(self.timeout_seconds))
            except ImportError:
                logger.warning("Failed to import fuzzing_infra.runner, corpus merger will not work")
                return None
        return self._runner

    def execute(self) -> bool:
        """Execute one round of corpus merging for weighted harnesses.

        Returns:
            bool: True if any work was done, False otherwise
        """
        weighted_items: list[WeightedHarness] = [
            wh for wh in self.harness_weights.list_harnesses() if wh.weight > 0
        ]
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
                if self._run_merge_for_harness(item, builds):
                    did_work = True
            except Exception as e:
                n_exceptions += 1
                logger.error(f"Error running corpus merge task: {e}", exc_info=True)
                if n_exceptions > 1:
                    # Multiple exceptions indicate a serious issue
                    logger.warning("Multiple exceptions occurred while merging corpuses")
                    raise e

        return did_work

    def _run_merge_for_harness(self, task: WeightedHarness, builds: list[BuildOutput]) -> bool:
        """Run corpus merge for a single harness.

        Strategy:
        1. Acquire a lock on the merged corpus set
        2. Sync remote corpus files locally
        3. Partition corpus into remote (R) and local-only (L) sets
        4. Run fuzzer merge to find which L files add coverage
        5. Push coverage-adding files to remote, delete non-adding files locally
        6. Release the lock

        Returns:
            bool: True if work was done, False otherwise
        """
        logger.debug(f"Running merge pass for {task.harness_name} | {task.package_name} | {task.task_id}")

        # Select build to use for merging
        build = next(iter([b for b in builds if b.sanitizer == ADDRESS_SANITIZER]), None)
        if build is None:
            build = random.choice(builds)

        # Initialize corpus
        corp = Corpus(self.crs_scratch_dir, task.task_id, task.harness_name)
        corp.hash_new_corpus()

        # Try to acquire merge lock
        try:
            with MergedCorpusSetLock(
                self.redis, task.task_id, task.harness_name, MERGING_LOCK_TIMEOUT_SECONDS
            ).acquire():
                # Sync and partition corpus
                corp.sync_from_remote()
                
                local_files = set([
                    os.path.basename(x) for x in corp.list_local_corpus() 
                    if Corpus.has_hashed_name(x)
                ])
                remote_files = set([
                    os.path.basename(x) for x in corp.list_remote_corpus() 
                    if Corpus.has_hashed_name(x)
                ])
                local_only_files = local_files - remote_files

                # Skip if no local-only files
                if not local_only_files:
                    logger.debug(
                        f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} "
                        "because local corpus is up to date"
                    )
                    return False

                logger.info(
                    f"Found {len(local_only_files)} files only in local corpus for {task.harness_name}. "
                    "Will run merge operation."
                )

                # Run merge operation
                with TemporaryDirectory() as remote_dir, TemporaryDirectory() as local_dir:
                    # Copy files to temporary directories
                    local_files_to_process = self._prepare_merge_directories(
                        corp, local_dir, remote_dir, local_only_files, remote_files
                    )

                    # Run the merge
                    self._run_merge_operation(
                        task, build, remote_dir, local_dir, corp
                    )

                    # Process merge results
                    push_count, remove_count = self._process_merge_results(
                        corp, remote_dir, local_dir, remote_files, local_files_to_process
                    )

                    if push_count > 0:
                        logger.info(f"Synced {push_count} files that add coverage to remote corpus")
                    if remove_count > 0:
                        logger.info(
                            f"Removed {remove_count} files from local corpus {corp.path} that don't add coverage"
                        )

                    return True

        except FailedToAcquireLock:
            logger.debug(
                f"Skipping merge for {task.harness_name} | {task.package_name} | {task.task_id} "
                "because another worker is already merging"
            )
            return False

    def _prepare_merge_directories(
        self,
        corp: Corpus,
        local_dir: str,
        remote_dir: str,
        local_only_files: set[str],
        remote_files: set[str],
    ) -> set[str]:
        """Prepare temporary directories for merge operation.

        Returns:
            set[str]: Set of local files that were successfully copied
        """
        # Shuffle and limit local files
        local_files_list = list(local_only_files)
        random.shuffle(local_files_list)
        
        # Copy local-only files
        copied_local_files = set()
        for file in local_files_list:
            try:
                shutil.copy(os.path.join(corp.path, file), os.path.join(local_dir, file))
                copied_local_files.add(file)
                if len(copied_local_files) >= self.max_local_files:
                    break
            except Exception as e:
                logger.error(f"Error copying file {file} to local directory: {e}. Will be ignored in merge.")

        # Copy remote files
        for file in remote_files:
            try:
                shutil.copy(os.path.join(corp.path, file), os.path.join(remote_dir, file))
            except Exception as e:
                # Try copying from remote storage as fallback
                try:
                    shutil.copy(os.path.join(corp.remote_path, file), os.path.join(remote_dir, file))
                    logger.debug(f"Copied {file} from remote storage after local copy failed: {e}")
                except Exception as e2:
                    logger.error(f"Failed to copy {file} from both local and remote: {e2}")

        return copied_local_files

    def _run_merge_operation(
        self,
        task: WeightedHarness,
        build: BuildOutput,
        remote_dir: str,
        local_dir: str,
        corp: Corpus,
    ) -> None:
        """Run the fuzzer merge operation to find which local files add coverage."""
        if self.runner is None:
            raise RuntimeError("Fuzzing runner not available, cannot perform merge")
            
        # Import FuzzConfiguration here to avoid import issues
        try:
            from buttercup.fuzzing_infra.runner import FuzzConfiguration
        except ImportError:
            logger.error("Failed to import FuzzConfiguration")
            raise
            
        with node_local.scratch_dir() as td:
            tsk = ChallengeTask(read_only_task_dir=build.task_dir, python_path=self.python)
            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                build_dir = local_tsk.get_build_dir()

                # Configure fuzzing for merge
                fuzz_conf = FuzzConfiguration(
                    local_dir,
                    str(build_dir / task.harness_name),
                    build.engine,
                    build.sanitizer,
                )

                logger.info(f"Starting fuzzer merge for {build.engine} | {build.sanitizer} | {task.harness_name}")

                # Log telemetry
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

                    # Merge will move coverage-adding files from local_dir to remote_dir
                    self.runner.merge_corpus(fuzz_conf, remote_dir)
                    span.set_status(Status(StatusCode.OK))

    def _process_merge_results(
        self,
        corp: Corpus,
        remote_dir: str,
        local_dir: str,
        original_remote_files: set[str],
        processed_local_files: set[str],
    ) -> tuple[int, int]:
        """Process the results of the merge operation.

        Returns:
            tuple[int, int]: (files pushed to remote, files deleted locally)
        """
        # Rehash files in remote directory after merge
        corp.hash_corpus(remote_dir)
        
        # Get files in merged remote directory
        files_in_merged_remote = set(os.listdir(remote_dir))
        
        # Validate merge results
        assert original_remote_files.issubset(files_in_merged_remote), "Some remote files were lost during merge"
        assert files_in_merged_remote.issubset(
            original_remote_files.union(processed_local_files)
        ), "Unexpected files appeared in merge output"
        
        # Files that add coverage (now in remote dir)
        push_remotely = processed_local_files & files_in_merged_remote
        
        # Files that don't add coverage (only in local)
        delete_locally = processed_local_files - files_in_merged_remote
        
        # Push coverage-adding files to remote
        push_count = 0
        if push_remotely:
            push_count = len(push_remotely)
            corp.sync_specific_files_to_remote(push_remotely)
        
        # Delete non-coverage-adding files
        remove_count = 0
        for file in delete_locally:
            try:
                corp.remove_local_file(file)
                remove_count += 1
            except Exception as e:
                logger.error(f"Error removing file {file} from local corpus {corp.path}: {e}")
        
        return push_count, remove_count