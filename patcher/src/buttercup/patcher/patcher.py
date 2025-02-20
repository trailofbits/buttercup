from dataclasses import dataclass, field
from pathlib import Path
from functools import reduce
from buttercup.patcher.context import ContextCodeSnippet
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Patch
from buttercup.patcher.utils import PatchInput, PatchOutput
from langchain_core.runnables import Runnable, RunnableConfig
from redis import Redis
from typing import Callable, Any
from buttercup.common.queues import ReliableQueue, QueueFactory, QueueNames, GroupNames
from buttercup.common.challenge_task import ChallengeTask
from buttercup.patcher.agents.leader import PatcherLeaderAgent
from buttercup.patcher.mock import MOCK_LIBPNG_FUNCTION_CODE
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
from buttercup.common.utils import serve_loop
import logging

logger = logging.getLogger(__name__)


@dataclass
class Patcher:
    task_storage_dir: Path
    scratch_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1
    mock_mode: bool = False
    dev_mode: bool = False

    vulnerability_queue: ReliableQueue | None = field(init=False, default=None)
    patches_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.vulnerability_queue = queue_factory.create(QueueNames.CONFIRMED_VULNERABILITIES, GroupNames.PATCHER)
            self.patches_queue = queue_factory.create(QueueNames.PATCHES)

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
        challenge_task = ChallengeTask(input.challenge_task_dir)
        with challenge_task.get_rw_copy(work_dir=self.scratch_dir) as rw_task:
            patcher_agent = PatcherLeaderAgent(
                rw_task,
                input,
                chain_call=self._chain_call,
            )
            patch = patcher_agent.run_patch_task()
            if patch is None:
                logger.error(
                    "Could not generate a patch for vulnerability %s/%s", challenge_task.name, input.vulnerability_id
                )
                return None

            logger.info("Generated patch for vulnerabiity %s/%s", challenge_task.name, input.vulnerability_id)
            logger.debug(f"Patch: {patch}")
            return patch

    def process_vulnerability(self, input: PatchInput) -> PatchOutput | None:
        logger.info(f"Processing vulnerability {input.task_id}/{input.vulnerability_id}")
        logger.debug(f"Patch Input: {input}")

        if self.dev_mode:
            set_llm_cache(SQLiteCache(database_path=f".{input.task_id}.langchain.db"))

        res = None
        if self.mock_mode:
            input.vulnerable_functions = [
                ContextCodeSnippet(
                    file_path="pngrutil.c",
                    function_name="png_handle_iCCP",
                    code_context="",
                    code=MOCK_LIBPNG_FUNCTION_CODE,
                )
            ]
            res = self._process_vulnerability(input)
        else:
            res = self._process_vulnerability(input)

        if res is not None:
            logger.info(f"Processed vulnerability {input.task_id}/{input.vulnerability_id}")
        else:
            logger.error(f"Failed to process vulnerability {input.task_id}/{input.vulnerability_id}")

        return res

    def _create_patch_input(self, vuln: ConfirmedVulnerability) -> PatchInput:
        return PatchInput(
            challenge_task_dir=Path(vuln.crash.crash.target.task_dir),
            task_id=vuln.crash.crash.target.task_id,
            vulnerability_id=vuln.vuln_id,
            harness_name=vuln.crash.crash.harness_name,
            pov=Path(vuln.crash.crash.crash_input_path),
            sanitizer_output=vuln.crash.tracer_stacktrace,
            engine=vuln.crash.crash.target.engine,
            sanitizer=vuln.crash.crash.target.sanitizer,
        )

    def serve_item(self) -> None:
        rq_item = self.vulnerability_queue.pop()
        if rq_item is None:
            return False

        vuln = rq_item.deserialized
        patch_input = self._create_patch_input(vuln)
        try:
            patch = self.process_vulnerability(patch_input)
            if patch is not None:
                patch_msg = Patch(
                    task_id=patch.task_id,
                    vulnerability_id=patch.vulnerability_id,
                    patch=patch.patch,
                )
                self.patches_queue.push(patch_msg)
                self.vulnerability_queue.ack_item(rq_item.item_id)
                logger.info(
                    f"Successfully generated patch for vulnerability {patch_input.task_id}/{patch_input.vulnerability_id}"
                )
            else:
                logger.error(
                    f"Failed to generate patch for vulnerability {patch_input.task_id}/{patch_input.vulnerability_id}"
                )
        except Exception as e:
            logger.error(
                f"Failed to generate patch for vulnerability {patch_input.task_id}/{patch_input.vulnerability_id}: {e}"
            )

        return True

    def serve(self) -> None:
        """Main loop to process vulnerabilities from queue"""
        if self.redis is None:
            raise ValueError("Redis is not initialized, setup redis connection")

        logger.info("Starting patcher service")
        serve_loop(self.serve_item, self.sleep_time)
