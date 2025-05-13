"""
Evaluate a prompt with different configurations for vulnerability discovery

Example usage:
python seed-gen/eval/vuln_discovery_base.py
    --prompt seed-gen/eval-prompt.txt \
    --eval-config seed-gen/eval/configs/libpng_model_eval_config.json \
    --task-dir sample-task-libpng/162fc720-b291-48cc-9554-efd8207cfb16-e408da6a-5c31-4d/ \
    --out-dir model-eval-out
"""

import argparse
import json
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from tqdm import tqdm

from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.common.llm import create_llm, get_langfuse_callbacks
from buttercup.common.logger import setup_package_logger
from buttercup.seed_gen.sandbox.sandbox import sandbox_exec_funcs
from buttercup.seed_gen.utils import extract_md

logger = setup_package_logger("vuln-discovery-base", __name__, "DEBUG")


@dataclass
class TestConfig:
    name: str
    llm_kwargs: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestConfig":
        return cls(**data)


@dataclass
class EvalConfig:
    configs: list[TestConfig]
    attempts_per_config: int
    package_name: str
    harness_name: str

    @classmethod
    def from_json(cls, json_path: str) -> "EvalConfig":
        with open(json_path) as f:
            data = json.load(f)

        # Convert the configs list from dicts to TestConfig objects
        data["configs"] = [TestConfig.from_dict(c) for c in data["configs"]]
        return cls(**data)


class VulnDiscoveryEvaluatorBase(ABC):
    def __init__(self, task_dir: Path, out_dir: Path, eval_config: EvalConfig):
        """Initialize the evaluator.

        Args:
            task_dir: Path to the challenge task directory
            out_dir: Path to the output directory
            eval_config: Evaluation configuration
        """
        self.task_dir = task_dir
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = out_dir / f"run-{timestamp}"
        self.out_dir = out_dir
        self.eval_config = EvalConfig.from_json(eval_config)
        ## set up out dir
        self.out_dir.mkdir(parents=True)
        self.metadata = {
            "package_name": self.eval_config.package_name,
            "harness_name": self.eval_config.harness_name,
            "eval_type": "vuln-discovery",
        }
        shutil.copy(eval_config, self.out_dir / "config.json")

    def test_povs(self, rw_task: ChallengeTask, pov_dir: Path) -> tuple[list[Path], list[Path]]:
        valid_povs = []
        invalid_povs = []
        for pov in pov_dir.iterdir():
            try:
                pov_output = rw_task.reproduce_pov(self.eval_config.harness_name, pov)
                if pov_output.did_crash():
                    valid_povs.append(pov)
                else:
                    invalid_povs.append(pov)
            except ChallengeTaskError as exc:
                logger.error(f"Error reproducing PoV {pov}: {exc}")
        return valid_povs, invalid_povs

    def evaluate_pov_generation(self) -> dict[str, Any]:
        """
        Evaluate test configurations for vulnerability discovery.
        """

        # Create challenge task for verification
        chall_task = ChallengeTask(read_only_task_dir=self.task_dir)
        with chall_task.get_rw_copy(work_dir=None) as rw_task:
            for config in tqdm(self.eval_config.configs, desc="Evaluating configs"):
                config_dir = self.out_dir / config.name
                config_dir.mkdir()
                for i in tqdm(
                    range(self.eval_config.attempts_per_config), desc=f"Evaluating {config.name}"
                ):
                    pov_dir = config_dir / f"attempt_{i}"
                    pov_dir.mkdir()
                    with tempfile.TemporaryDirectory() as workdir_str:
                        workdir = Path(workdir_str)
                        try:
                            # Generate PoV using the prompt
                            pov_funcs, trace_id = self.generate_pov_funcs(config)
                            trace_id_file = pov_dir / "langfuse_trace_id"
                            trace_id_file.write_text(trace_id)
                            sandbox_exec_funcs(pov_funcs, workdir)
                            valid_povs, invalid_povs = self.test_povs(rw_task, workdir)
                            valid_pov_count = len(valid_povs)
                            total_pov_count = valid_pov_count + len(invalid_povs)
                            logger.info(
                                f"Attempt {i}: generated {valid_pov_count} valid PoVs of {total_pov_count} total"  # noqa: E501
                            )
                            valid_dir = pov_dir / "valid"
                            invalid_dir = pov_dir / "invalid"
                            valid_dir.mkdir()
                            invalid_dir.mkdir()
                            for pov in valid_povs:
                                shutil.copy(pov, valid_dir / pov.name)
                            for pov in invalid_povs:
                                shutil.copy(pov, invalid_dir / pov.name)
                        except Exception as e:
                            logger.error(f"Error during PoV generation: {str(e)}")

    @abstractmethod
    def generate_pov_funcs(self, config: TestConfig) -> tuple[str, str]:
        """Generate a string with PoV functions from a config"""
        pass


class VulnDiscoveryEvaluator(VulnDiscoveryEvaluatorBase):
    def __init__(self, task_dir: Path, out_dir: Path, eval_config: EvalConfig, prompt: Path):
        """Initialize the evaluator.

        Args:
            task_dir: Path to the challenge task directory
            out_dir: Path to the output directory
            eval_config: Evaluation configuration
            prompt: Path to the prompt file
        """
        super().__init__(task_dir, out_dir, eval_config)
        self.prompt = prompt.read_text()

    def generate_pov_funcs(self, config: TestConfig) -> tuple[str, str]:
        llm_callbacks = get_langfuse_callbacks()
        llm = create_llm(**config.llm_kwargs, callbacks=llm_callbacks)
        chain = llm | extract_md
        chain_config = chain.with_config(RunnableConfig(metadata=self.metadata))
        res = chain_config.invoke(self.prompt)
        trace_id = llm_callbacks[0].trace.trace_id
        return res, trace_id


def main():
    """Main function to run the evaluation."""
    parser = argparse.ArgumentParser(description="Eval vuln discovery effectiveness")
    parser.add_argument("--prompt", required=True, help="Path to prompt file", type=Path)
    parser.add_argument(
        "--eval-config", required=True, help="Path to evaluation json config", type=Path
    )
    parser.add_argument(
        "--task-dir", required=True, help="Path to (built) challenge task directory", type=Path
    )
    parser.add_argument("--out-dir", required=True, help="Eval output directory", type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    evaluator = VulnDiscoveryEvaluator(args.task_dir, args.out_dir, args.eval_config, args.prompt)
    evaluator.evaluate_pov_generation()


if __name__ == "__main__":
    main()
