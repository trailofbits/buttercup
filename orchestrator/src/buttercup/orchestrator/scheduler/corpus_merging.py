"""Corpus merging background task for the scheduler.

This module provides corpus merging functionality as a background task,
replacing the standalone merger-bot service. It merges local corpus files
into remote storage if they add coverage.
"""

import logging
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional, Set, Tuple

from redis import Redis

from buttercup.common import node_local
from buttercup.common.constants import ADDRESS_SANITIZER
from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, WeightedHarness
from buttercup.common.maps import BuildMap, HarnessWeights
from buttercup.common.sets import FailedToAcquireLock, MERGING_LOCK_TIMEOUT_SECONDS, MergedCorpusSetLock
from buttercup.fuzzing_infra.runner import Conf, FuzzConfiguration, Runner
from buttercup.common.challenge_task import ChallengeTask
from .background_tasks import BackgroundTask

logger = logging.getLogger(__name__)


class CorpusMergingTask(BackgroundTask):
    """Background task for merging local corpus files into remote storage."""
    
    def __init__(
        self,
        redis: Redis,
        crs_scratch_dir: str,
        python_path: str = "python",
        interval_seconds: float = 10.0,
        timeout_seconds: int = 300,
        max_local_files: int = 500,
    ):
        super().__init__("corpus-merging", interval_seconds)
        self.redis = redis
        self.crs_scratch_dir = crs_scratch_dir
        self.python_path = python_path
        self.timeout_seconds = timeout_seconds
        self.max_local_files = max_local_files
        self.harness_weights = HarnessWeights(redis)
        self.builds = BuildMap(redis)
        self.runner = Runner(Conf(timeout_seconds))
        
    def _partition_corpus(
        self, corpus: Corpus, task: WeightedHarness
    ) -> Tuple[Set[str], Set[str], TemporaryDirectory, TemporaryDirectory]:
        """Partition corpus into local-only and remote files.
        
        Returns:
            Tuple of (local_only_files, remote_files, local_dir, remote_dir)
        """
        # Sync from remote
        corpus.sync_from_remote()
        
        # Get file lists
        local_files = set([
            os.path.basename(x) for x in corpus.list_local_corpus() 
            if Corpus.has_hashed_name(x)
        ])
        remote_files = set([
            os.path.basename(x) for x in corpus.list_remote_corpus() 
            if Corpus.has_hashed_name(x)
        ])
        
        local_only_files = local_files - remote_files
        
        # Create temporary directories
        local_dir = TemporaryDirectory()
        remote_dir = TemporaryDirectory()
        
        # Copy files to temporary directories
        # Limit local files to max_local_files
        local_files_list = list(local_only_files)
        random.shuffle(local_files_list)
        
        new_local_only_files = set()
        for file in local_files_list[:self.max_local_files]:
            try:
                shutil.copy(
                    os.path.join(corpus.path, file),
                    os.path.join(local_dir.name, file)
                )
                new_local_only_files.add(file)
            except Exception as e:
                logger.error(f"Error copying file {file} to local directory: {e}")
        
        # Copy remote files
        for file in remote_files:
            try:
                shutil.copy(
                    os.path.join(corpus.path, file),
                    os.path.join(remote_dir.name, file)
                )
            except Exception as e:
                # Try copying from remote storage
                try:
                    shutil.copy(
                        os.path.join(corpus.remote_path, file),
                        os.path.join(remote_dir.name, file)
                    )
                    logger.debug(
                        f"Error copying file {file} from local: {e}. "
                        "Copied from remote storage instead."
                    )
                except Exception as e2:
                    logger.error(f"Failed to copy file {file}: {e2}")
        
        return new_local_only_files, remote_files, local_dir, remote_dir
    
    def _run_merge_operation(
        self,
        task: WeightedHarness,
        build: BuildOutput,
        local_dir: str,
        remote_dir: str,
    ) -> None:
        """Run the merge operation to find which local files add coverage.
        
        Files that add coverage will be moved from local_dir to remote_dir.
        """
        with node_local.scratch_dir() as td:
            tsk = ChallengeTask(
                read_only_task_dir=build.task_dir,
                python_path=self.python_path
            )
            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                build_dir = local_tsk.get_build_dir()
                
                # Configure fuzzing
                fuzz_conf = FuzzConfiguration(
                    local_dir,
                    str(build_dir / task.harness_name),
                    build.engine,
                    build.sanitizer,
                )
                
                logger.info(
                    f"Starting fuzzer merge for {build.engine} | "
                    f"{build.sanitizer} | {task.harness_name}"
                )
                
                # Run merge - this moves files from local_dir to remote_dir
                # if they add coverage
                self.runner.merge_corpus(fuzz_conf, remote_dir)
    
    def _process_merge_results(
        self,
        corpus: Corpus,
        local_only_files: Set[str],
        remote_files: Set[str],
        remote_dir: TemporaryDirectory,
    ) -> Tuple[int, int]:
        """Process the results of the merge operation.
        
        Returns:
            Tuple of (files_pushed, files_deleted)
        """
        # Re-hash the corpus in the remote directory
        corpus.hash_corpus(remote_dir.name)
        
        # Get files in the merged remote directory
        files_in_new_remote_dir = set(os.listdir(remote_dir.name))
        
        # Verify consistency
        assert remote_files.issubset(files_in_new_remote_dir), \
            "Some remote files were lost during merge"
        assert files_in_new_remote_dir.issubset(remote_files.union(local_only_files)), \
            "Unexpected files appeared in merge output"
        
        # Files to push (local files that add coverage)
        push_remotely = local_only_files & files_in_new_remote_dir
        
        # Files to delete (local files that don't add coverage)
        delete_locally = local_only_files - files_in_new_remote_dir
        
        # Push files to remote
        files_pushed = 0
        if push_remotely:
            files_pushed = len(push_remotely)
            corpus.sync_specific_files_to_remote(push_remotely)
            logger.info(f"Synced {files_pushed} files that add coverage to remote corpus")
        
        # Delete files locally
        files_deleted = 0
        for file in delete_locally:
            try:
                corpus.remove_local_file(file)
                files_deleted += 1
            except Exception as e:
                logger.error(f"Error removing file {file} from local corpus: {e}")
        
        if files_deleted > 0:
            logger.info(
                f"Removed {files_deleted} files from local corpus that don't add coverage"
            )
        
        return files_pushed, files_deleted
    
    def _merge_corpus_for_task(self, task: WeightedHarness, builds: List[BuildOutput]) -> bool:
        """Merge corpus for a single task.
        
        Returns:
            bool: True if work was done, False otherwise
        """
        logger.debug(
            f"Running merge pass for {task.harness_name} | "
            f"{task.package_name} | {task.task_id}"
        )
        
        # Select build (prefer ADDRESS_SANITIZER)
        build = next(
            iter([b for b in builds if b.sanitizer == ADDRESS_SANITIZER]),
            None
        )
        if build is None:
            build = random.choice(builds)
        
        # Initialize corpus
        corp = Corpus(self.crs_scratch_dir, task.task_id, task.harness_name)
        
        # Hash local corpus files
        corp.hash_new_corpus()
        
        # Acquire lock for merging
        try:
            with MergedCorpusSetLock(
                self.redis, task.task_id, task.harness_name, MERGING_LOCK_TIMEOUT_SECONDS
            ).acquire():
                # Partition corpus
                local_only_files, remote_files, local_dir, remote_dir = \
                    self._partition_corpus(corp, task)
                
                try:
                    # Skip if no local-only files
                    if not local_only_files:
                        logger.debug(
                            f"Skipping merge for {task.harness_name} - "
                            "local corpus is up to date"
                        )
                        return False
                    
                    logger.info(
                        f"Found {len(local_only_files)} files only in local corpus "
                        f"for {task.harness_name}. Will run merge operation."
                    )
                    
                    # Run merge
                    self._run_merge_operation(task, build, local_dir.name, remote_dir.name)
                    
                    # Process results
                    files_pushed, files_deleted = self._process_merge_results(
                        corp, local_only_files, remote_files, remote_dir
                    )
                    
                    return True
                    
                finally:
                    # Cleanup temporary directories
                    local_dir.cleanup()
                    remote_dir.cleanup()
                    
        except FailedToAcquireLock:
            logger.debug(
                f"Skipping merge for {task.harness_name} - "
                "another worker is already merging"
            )
            return False
        except Exception as e:
            logger.error(f"Error merging corpus: {e}")
            raise
    
    def execute(self) -> bool:
        """Execute one iteration of corpus merging.
        
        Returns:
            bool: True if any merging was done, False otherwise
        """
        # Get weighted harnesses
        weighted_items: List[WeightedHarness] = [
            wh for wh in self.harness_weights.list_harnesses() 
            if wh.weight > 0
        ]
        
        if not weighted_items:
            return False
        
        did_work = False
        n_exceptions = 0
        
        # Process in random order
        random.shuffle(weighted_items)
        
        for item in weighted_items:
            # Get builds
            builds = self.builds.get_builds(item.task_id, BuildType.FUZZER)
            if not builds:
                continue
            
            try:
                if self._merge_corpus_for_task(item, builds):
                    did_work = True
            except Exception as e:
                n_exceptions += 1
                logger.error(f"Error running merge task: {e}")
                if n_exceptions > 1:
                    # Multiple exceptions indicate a serious issue
                    logger.warning("Multiple exceptions occurred, re-raising")
                    raise
        
        return did_work