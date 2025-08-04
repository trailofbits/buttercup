import logging
from dataclasses import dataclass
from pathlib import Path
from typing import override

from langgraph.types import Command
from pydantic import Field

from buttercup.seed_gen.prompt.vuln_discovery import (
    VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT,
    VULN_DELTA_ANALYZE_BUG_USER_PROMPT,
    VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT,
    VULN_DELTA_GET_CONTEXT_USER_PROMPT,
    VULN_DELTA_WRITE_POV_SYSTEM_PROMPT,
    VULN_DELTA_WRITE_POV_USER_PROMPT,
)
from buttercup.seed_gen.utils import get_diff_content
from buttercup.seed_gen.vuln_base_task import VulnBaseState, VulnBaseTask

logger = logging.getLogger(__name__)


class VulnDiscoveryDeltaState(VulnBaseState):
    diff_content: str = Field(description="The content of the diff being analyzed")


@dataclass
class VulnDiscoveryDeltaTask(VulnBaseTask):
    TaskStateClass = VulnDiscoveryDeltaState
    VULN_DISCOVERY_MAX_POV_COUNT = 5
    MAX_CONTEXT_ITERATIONS = 6

    @override
    def _gather_context(self, state: VulnDiscoveryDeltaState) -> Command:
        """Gather context about the diff and harness"""
        logger.info("Gathering context")
        prompt_vars = {
            "diff": state.diff_content,
            "harness": str(state.harness),
            "retrieved_context": state.format_retrieved_context(),
            "sarif_hints": state.format_sarif_hints(),
            "vuln_files": self.get_vuln_files(),
            "fuzzer_name": self.get_fuzzer_name(),
            "cwe_list": self.get_cwe_list(),
        }
        res = self._get_context_base(
            VULN_DELTA_GET_CONTEXT_SYSTEM_PROMPT,
            VULN_DELTA_GET_CONTEXT_USER_PROMPT,
            state,
            prompt_vars,
        )
        return res

    @override
    def _analyze_bug(self, state: VulnDiscoveryDeltaState) -> Command:
        """Analyze the diff for vulnerabilities"""
        prompt_vars = {
            "diff": state.diff_content,
            "harness": str(state.harness),
            "retrieved_context": state.format_retrieved_context(),
            "sarif_hints": state.format_sarif_hints(),
            "vuln_files": self.get_vuln_files(),
            "fuzzer_name": self.get_fuzzer_name(),
            "cwe_list": self.get_cwe_list(),
            "previous_attempts": state.format_pov_attempts(),
        }
        res = self._analyze_bug_base(
            VULN_DELTA_ANALYZE_BUG_SYSTEM_PROMPT, VULN_DELTA_ANALYZE_BUG_USER_PROMPT, prompt_vars
        )
        return res

    @override
    def _write_pov(self, state: VulnDiscoveryDeltaState) -> Command:
        """Write PoV functions for the vulnerability"""
        prompt_vars = {
            "analysis": state.analysis,
            "harness": str(state.harness),
            "diff": state.diff_content,
            "max_povs": self.VULN_DISCOVERY_MAX_POV_COUNT,
            "retrieved_context": state.format_retrieved_context(),
            "pov_examples": self.get_pov_examples(),
            "fuzzer_name": self.get_fuzzer_name(),
            "previous_attempts": state.format_pov_attempts(),
        }
        res = self._write_pov_base(
            VULN_DELTA_WRITE_POV_SYSTEM_PROMPT,
            VULN_DELTA_WRITE_POV_USER_PROMPT,
            prompt_vars,
        )
        return res

    @override
    def _init_state(self, out_dir: Path, current_dir: Path) -> VulnDiscoveryDeltaState:
        harness = self.get_harness_source()
        if harness is None:
            raise ValueError("No harness found for challenge %s", self.package_name)

        diffs = self.challenge_task.get_diffs()
        diff_content = get_diff_content(diffs)
        if diff_content is None:
            raise ValueError("No diff found for challenge %s", self.package_name)

        state = VulnDiscoveryDeltaState(
            harness=harness,
            diff_content=diff_content,
            task=self,
            sarifs=self.sample_sarifs(),
            output_dir=out_dir,
            current_dir=current_dir,
        )
        return state
