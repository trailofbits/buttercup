"""Module for finding libfuzzer and jazzer harnesses in source code."""

import logging
from pathlib import Path

from redis import Redis

from buttercup.program_model.harness_finder import (
    find_jazzer_harnesses as _find_jazzer_harnesses,
)
from buttercup.program_model.harness_finder import (
    find_libfuzzer_harnesses as _find_libfuzzer_harnesses,
)
from buttercup.program_model.harness_finder import (
    get_harness_source as _get_harness_source,
)
from buttercup.program_model.harness_finder import (
    get_harness_source_candidates as _get_harness_source_candidates,
)
from buttercup.program_model.harness_models import HarnessInfo
from buttercup.program_model.rest_client import CodeQueryPersistentRest as CodeQuery

logger = logging.getLogger(__name__)


def find_libfuzzer_harnesses(codequery: CodeQuery) -> list[Path]:
    """Find libfuzzer harnesses in the source directory."""
    return _find_libfuzzer_harnesses(codequery.challenge.task_dir)


def find_jazzer_harnesses(codequery: CodeQuery) -> list[Path]:
    """Find Jazzer harnesses in the source directory."""
    return _find_jazzer_harnesses(codequery.challenge.task_dir)


def get_harness_source_candidates(codequery: CodeQuery, harness_name: str) -> list[Path]:
    """Get the list of candidate source files for a harness."""
    return _get_harness_source_candidates(codequery.challenge, harness_name)


def get_harness_source(
    redis: Redis | None, codequery: CodeQuery, harness_name: str
) -> HarnessInfo | None:
    """Get harness source for a specific harness."""
    return _get_harness_source(
        redis,
        codequery.challenge,
        harness_name,
    )
