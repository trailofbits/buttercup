import logging
import random

import numpy as np
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import FunctionCoverage, WeightedHarness
from buttercup.common.maps import CoverageMap

logger = logging.getLogger(__name__)


class FunctionSelector:
    """
    Class for selecting functions based on coverage data.
    """

    def __init__(self, redis: Redis):
        """
        Initialize the FunctionSelector with a Redis connection.

        Args:
            redis: Redis connection
        """
        self.redis = redis

    def get_function_coverage(self, harness: WeightedHarness) -> list[FunctionCoverage]:
        """
        Get function coverage data for a given harness.

        Args:
            harness: The WeightedHarness to get coverage for

        Returns:
            List of FunctionCoverage objects
        """
        coverage_map = CoverageMap(
            self.redis, harness.harness_name, harness.package_name, harness.task_id
        )

        return coverage_map.list_function_coverage()

    @staticmethod
    def calculate_function_probabilities(
        function_coverage: list[FunctionCoverage], temperature: float = 1.0
    ) -> tuple[list[FunctionCoverage], list[float]]:
        """
        Calculate function probabilities, where lower coverage = higher probability.
        Uses softmax with temperature to convert inverse coverage ratios to probabilities.

        Will filter out functions with no lines.

        Will filter out functions with 100% coverage, if there are functions with partial coverage.

        Args:
            function_coverage: List of FunctionCoverage objects
            temperature: Temperature parameter for softmax

        Returns:
            Tuple of (list of FunctionCoverage, list of probabilities)
        """
        # Filter out functions with no lines
        valid_functions = [fc for fc in function_coverage if fc.total_lines > 0]

        if not valid_functions:
            logger.warning("No valid functions found for probability calculation")
            return ([], [])

        partial_functions = [fc for fc in function_coverage if fc.covered_lines < fc.total_lines]
        if not partial_functions:
            logger.info("All functions have 100% coverage, selecting one")
        else:
            valid_functions = partial_functions

        coverage_fractions = np.array([fc.covered_lines / fc.total_lines for fc in valid_functions])

        inverse_coverage = 1.0 - coverage_fractions

        # Apply softmax with temperature
        exp_values = np.exp(inverse_coverage / temperature)
        probabilities = exp_values / np.sum(exp_values)

        # Return functions with their probabilities
        return (valid_functions, probabilities.tolist())

    def sample_function(self, harness: WeightedHarness) -> FunctionCoverage | None:
        """
        Sample a function based on coverage probabilities.

        Args:
            harness: The WeightedHarness to sample a function for

        Returns:
            FunctionCoverage or None if no functions available
        """
        function_coverage = self.get_function_coverage(harness)

        if not function_coverage:
            logger.warning(
                "No function coverage data found for %s:%s",
                harness.package_name,
                harness.harness_name,
            )
            return None

        sample_functions, sample_probs = FunctionSelector.calculate_function_probabilities(
            function_coverage
        )

        if not sample_functions:
            logger.warning(
                "No valid functions with probabilities for %s:%s",
                harness.package_name,
                harness.harness_name,
            )
            return None

        # Sample a function
        selected_function = random.choices(sample_functions, weights=sample_probs, k=1)[0]

        function_name = selected_function.function_name
        function_paths = len(selected_function.function_paths)
        coverage_fraction = round(
            selected_function.covered_lines / selected_function.total_lines
            if selected_function.total_lines > 0
            else 0,
        )
        function_prob = round(sample_probs[sample_functions.index(selected_function)], 5)

        logger.info(
            "Selected function %s (cov: %s, prob: %s, paths: %s)",
            function_name,
            coverage_fraction,
            function_prob,
            function_paths,
        )

        return selected_function
