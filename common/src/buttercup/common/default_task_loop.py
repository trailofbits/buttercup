from abc import ABC, abstractmethod
from redis import Redis
import time
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput
from buttercup.common.maps import HarnessWeights, BuildMap
from typing import List
from buttercup.common.maps import BUILD_TYPES
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
    def required_builds(self) -> List[BUILD_TYPES]:
        return []

    @abstractmethod
    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        pass

    def run(self):
        while True:
            weighted_items: list[WeightedHarness] = self.harness_weights.list_harnesses()
            logger.info(f"Received {len(weighted_items)} weighted targets")

            if len(weighted_items) > 0:
                chc = random.choices(
                    weighted_items,
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
                logger.info(f"Running task for {chc.harness_name} | {chc.package_name} | {chc.task_id}")

                builds = {
                    reqbuild: self.builds.get_builds(chc.task_id, reqbuild) for reqbuild in self.required_builds()
                }

                has_all_builds = True
                for k, build in builds.items():
                    if len(build) <= 0:
                        logger.error(f"Build {k} for {chc.task_id} not found")
                        has_all_builds = False

                if has_all_builds:
                    self.run_task(chc, builds)

            time.sleep(self.timeout)
