from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from functools import reduce
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Patch
from buttercup.patcher.utils import PatchInput, PatchOutput, PatchInputPoV
import buttercup.common.node_local as node_local
from langchain_core.runnables import Runnable, RunnableConfig
from redis import Redis
from typing import Callable, Any
from buttercup.common.queues import ReliableQueue, QueueFactory, QueueNames, GroupNames, RQItem
from buttercup.common.challenge_task import ChallengeTask
from buttercup.patcher.agents.leader import PatcherLeaderAgent
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
from buttercup.common.utils import serve_loop
from buttercup.common.task_registry import TaskRegistry
import logging

logger = logging.getLogger(__name__)


@dataclass
class Patcher:
    task_storage_dir: Path
    scratch_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1
    dev_mode: bool = False

    vulnerability_queue: ReliableQueue[ConfirmedVulnerability] | None = field(init=False, default=None)
    patches_queue: ReliableQueue[Patch] | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.vulnerability_queue = queue_factory.create(QueueNames.CONFIRMED_VULNERABILITIES, GroupNames.PATCHER)
            self.patches_queue = queue_factory.create(QueueNames.PATCHES)
            self.registry = TaskRegistry(self.redis)

    @staticmethod
    def _check_redis(func: Callable) -> Callable:
        """Decorator to check if the task is read-only."""

        def wrapper(self: Patcher, *args: Any, **kwargs: Any) -> Any:
            if self.redis is None:
                raise ValueError("Redis is not initialized, setup redis connection")
            return func(self, *args, **kwargs)

        return wrapper

    def _chain_call(
        self,
        reduce_function: Callable,
        runnable: Runnable,
        args: dict[str, Any],
        config: RunnableConfig | None = None,
        default: Any = None,
    ) -> Any:
        if self.dev_mode:
            res = runnable.invoke(args, config=config)
        else:
            res = reduce(reduce_function, runnable.stream(args, config=config), default)

        return res

    def _process_vulnerability(self, input: PatchInput) -> PatchOutput | None:
        ro_task = ChallengeTask(input.povs[0].challenge_task_dir)
        patcher_agent = PatcherLeaderAgent(
            ro_task,
            input,
            redis=self.redis,
            chain_call=self._chain_call,
            work_dir=self.scratch_dir,
            tasks_storage=self.task_storage_dir,
        )
        patch = patcher_agent.run_patch_task()
        if patch is None:
            logger.error("Could not generate a patch for vulnerability %s/%s", input.task_id, input.internal_patch_id)
            return None

        logger.info("Generated patch for vulnerabiity %s/%s", input.task_id, input.internal_patch_id)
        logger.debug(f"Patch: {patch}")
        return patch

    def process_patch_input(self, input: PatchInput) -> PatchOutput | None:
        logger.info(f"Processing vulnerability {input.task_id}/{input.internal_patch_id}")
        logger.debug(f"Patch Input: {input}")

        if self.dev_mode:
            set_llm_cache(SQLiteCache(database_path=f".{input.task_id}.langchain.db"))

        res = self._process_vulnerability(input)
        if res is not None:
            logger.info(f"Processed vulnerability {input.task_id}/{input.internal_patch_id}")
        else:
            logger.error(f"Failed to process vulnerability {input.task_id}/{input.internal_patch_id}")

        return res

    def _create_patch_input(self, vuln: ConfirmedVulnerability) -> PatchInput:
        povs = [
            PatchInputPoV(
                challenge_task_dir=Path(crash.crash.target.task_dir),
                pov=node_local.make_locally_available(crash.crash.crash_input_path),
                pov_token=crash.crash.crash_token,
                sanitizer=crash.crash.target.sanitizer,
                engine=crash.crash.target.engine,
                harness_name=crash.crash.harness_name,
                sanitizer_output=crash.tracer_stacktrace if crash.tracer_stacktrace else crash.crash.stacktrace,
            )
            for crash in vuln.crashes
        ]
        return PatchInput(
            task_id=vuln.crashes[0].crash.target.task_id,
            internal_patch_id=vuln.internal_patch_id,
            povs=povs,
        )

    @_check_redis
    def process_item(self, rq_item: RQItem[ConfirmedVulnerability]) -> None:
        assert self.patches_queue is not None
        assert self.vulnerability_queue is not None
        assert self.registry is not None

        vuln = rq_item.deserialized
        if len(vuln.crashes) == 0:
            logger.error(f"No crashes found for vulnerability {vuln.internal_patch_id}")
            self.vulnerability_queue.ack_item(rq_item.item_id)
            return

        assert vuln.crashes, "No crashes found for vulnerability"
        task_id = vuln.crashes[0].crash.target.task_id
        if not all(x.crash.target.task_id == task_id for x in vuln.crashes):
            logger.error(f"Mismatching task ids for vulnerability {vuln.internal_patch_id}")
            self.vulnerability_queue.ack_item(rq_item.item_id)
            return

        # Check if task should not be processed (expired or cancelled)
        if self.registry.should_stop_processing(task_id):
            logger.info(f"Skipping expired or cancelled task {task_id}")
            self.vulnerability_queue.ack_item(rq_item.item_id)
            return

        patch_input = self._create_patch_input(vuln)
        try:
            patch = self.process_patch_input(patch_input)
            if patch is not None:
                patch_msg = Patch(
                    task_id=patch.task_id,
                    internal_patch_id=patch.internal_patch_id,
                    patch=patch.patch,
                )
                self.patches_queue.push(patch_msg)
                self.vulnerability_queue.ack_item(rq_item.item_id)
                logger.info(
                    f"Successfully generated patch for vulnerability {patch_input.task_id}/{patch_input.internal_patch_id}"
                )
            else:
                logger.error(
                    f"Failed to generate patch for vulnerability {patch_input.task_id}/{patch_input.internal_patch_id}"
                )
        except Exception as e:
            logger.exception(
                f"Failed to generate patch for vulnerability {patch_input.task_id}/{patch_input.internal_patch_id}: {e}"
            )

    @_check_redis
    def serve_item(self) -> bool:
        assert self.vulnerability_queue is not None

        rq_item = self.vulnerability_queue.pop()

        if rq_item is None:
            return False

        self.process_item(rq_item)
        return True

    @_check_redis
    def serve(self) -> None:
        """Main loop to process vulnerabilities from queue"""
        logger.info("Starting patcher service")
        serve_loop(self.serve_item, self.sleep_time)
