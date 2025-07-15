"""Harness management for the unified fuzzer."""

import logging
import os
from typing import List

from buttercup.common.clusterfuzz_utils import get_fuzz_targets
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, WeightedHarness
from buttercup.common.maps import BuildMap, HarnessWeights
from redis import Redis

logger = logging.getLogger(__name__)

DEFAULT_WEIGHT = 1.0


class HarnessManager:
    """Manages harness weights based on build outputs."""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        self.harness_weights = HarnessWeights(redis)
        self.build_map = BuildMap(redis)
    
    def process_build_output(self, build_output: BuildOutput) -> List[str]:
        """Process a build output and update harness weights.
        
        Args:
            build_output: The build output to process
            
        Returns:
            List of harness names that were added
        """
        # Update build map
        self.build_map.add_build(build_output)
        
        added_harnesses = []
        
        # If it's a fuzzer build, extract targets and update weights
        if build_output.build_type == BuildType.FUZZER:
            # Try to get the build directory to extract fuzz targets
            if hasattr(build_output, 'output_ossfuzz_path'):
                build_dir = os.path.join(
                    build_output.output_ossfuzz_path,
                    "build",
                    "out",
                    build_output.package_name,
                )
            else:
                # Fallback: assume task_dir structure
                build_dir = os.path.join(
                    build_output.task_dir,
                    "build",
                    "out",
                )
            
            logger.info(f"Processing fuzzer build for package: {build_dir}")
            
            try:
                targets = get_fuzz_targets(build_dir)
                
                for tgt in targets:
                    harness_name = os.path.basename(tgt)
                    logger.info(f"Adding harness: {harness_name}")
                    
                    self.harness_weights.push_harness(
                        WeightedHarness(
                            weight=DEFAULT_WEIGHT,
                            harness_name=harness_name,
                            package_name=build_output.package_name if hasattr(build_output, 'package_name') else "",
                            task_id=build_output.task_id,
                        )
                    )
                    added_harnesses.append(harness_name)
                    
            except Exception as e:
                logger.error(f"Failed to extract fuzz targets from {build_dir}: {e}")
        
        return added_harnesses