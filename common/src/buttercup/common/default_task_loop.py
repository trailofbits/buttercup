from abc import ABC, abstractmethod
from redis import Redis
from buttercup.common.utils import serve_loop
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput
from buttercup.common.datastructures.aliases import BuildType
from buttercup.common.maps import HarnessWeights, BuildMap
from typing import List

import random
import logging

logger = logging.getLogger(__name__)


class TaskLoop(ABC):
    def __init__(self, redis: Redis, timeout: int):
        self.redis = redis
        self.timeout = timeout
        self.harness_weights = HarnessWeights(redis)
        self.builds = BuildMap(redis)

    # Declare a set of builds that must be available before running the task
    def required_builds(self) -> List[BuildType]:
        return []

    @abstractmethod
    def run_task(self, task: WeightedHarness, builds: dict[BuildType, list[BuildOutput]]):
        pass

    def serve_item(self) -> bool:
        weighted_items: list[WeightedHarness] = [wh for wh in self.harness_weights.list_harnesses() if wh.weight > 0]
        if len(weighted_items) <= 0:
            return False

        logger.info(f"Received {len(weighted_items)} weighted targets")
        chc = random.choices(
            weighted_items,
            weights=[it.weight for it in weighted_items],
            k=1,
        )[0]
        logger.info(f"Running task for {chc.harness_name} | {chc.package_name} | {chc.task_id}")

        builds = {reqbuild: self.builds.get_builds(chc.task_id, reqbuild) for reqbuild in self.required_builds()}

        has_all_builds = True
        for k, build in builds.items():
            if len(build) <= 0:
                logger.warning(f"Build {k} for {chc.task_id} not found")
                has_all_builds = False

        if has_all_builds:
            self.run_task(chc, builds)
            return True

        return False

    def run(self):
        serve_loop(self.serve_item, self.timeout)
