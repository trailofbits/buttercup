"""
Evaluate vulnerability discovery with different configurations
"""

import argparse
from pathlib import Path

from vuln_discovery_base import TestConfig, VulnDiscoveryEvaluatorBase

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import create_llm, get_langfuse_callbacks
from buttercup.seed_gen.utils import get_diff_content
from buttercup.seed_gen.vuln_discovery import VulnDiscoveryTask


class VulnDiscoveryEvaluator(VulnDiscoveryEvaluatorBase):
    def generate_pov_funcs(self, config: TestConfig) -> tuple[str, str]:
        """Generate PoV functions"""
        llm_callbacks = get_langfuse_callbacks()
        llm = create_llm(**config.llm_kwargs, callbacks=llm_callbacks)
        chall_task = ChallengeTask(read_only_task_dir=self.task_dir)
        vuln_discovery = VulnDiscoveryTask(
            self.eval_config.package_name, self.eval_config.harness_name, chall_task, llm=llm
        )

        harness = vuln_discovery.get_harness_source()
        if harness is None:
            return
        diffs = chall_task.get_diffs()
        diff_content = get_diff_content(diffs)
        analysis = vuln_discovery.analyze_diff(diff_content, harness)

        pov_funcs = vuln_discovery.write_pov_funcs(analysis, harness, diff_content)
        trace_id = llm_callbacks[0].trace.trace_id
        return pov_funcs, trace_id


def main():
    """Main function to run the evaluation."""
    parser = argparse.ArgumentParser(description="Eval multi-step vuln discovery effectiveness")
    parser.add_argument(
        "--eval-config", required=True, help="Path to evaluation json config", type=Path
    )
    parser.add_argument(
        "--task-dir", required=True, help="Path to (built) challenge task directory", type=Path
    )
    parser.add_argument("--out-dir", required=True, help="Eval output directory", type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    evaluator = VulnDiscoveryEvaluator(args.task_dir, args.out_dir, args.eval_config)
    evaluator.evaluate_pov_generation()


if __name__ == "__main__":
    main()
