"""
Evaluate vulnerability discovery with different configurations
"""

import argparse
from pathlib import Path

from vuln_discovery_base import TestConfig, VulnDiscoveryEvaluatorBase

from buttercup.common.llm import create_llm, get_langfuse_callbacks
from buttercup.seed_gen.mock_context.mock import get_diff, get_harness
from buttercup.seed_gen.vuln_discovery import VulnDiscoveryTask


class VulnDiscoveryEvaluator(VulnDiscoveryEvaluatorBase):
    def generate_pov_funcs(self, config: TestConfig) -> tuple[str, str]:
        """Generate PoV functions"""
        llm_callbacks = get_langfuse_callbacks()
        llm = create_llm(**config.llm_kwargs, callbacks=llm_callbacks)
        vuln_discovery = VulnDiscoveryTask(llm=llm)

        harness = get_harness(self.eval_config.package_name)
        diff = get_diff(self.eval_config.package_name)
        analysis = vuln_discovery.analyze_diff(diff, harness)

        pov_funcs = vuln_discovery.write_pov_funcs(analysis, harness, diff)
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
