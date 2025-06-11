from clusterfuzz.fuzz import get_engine
from clusterfuzz.fuzz.engine import Engine, FuzzResult, FuzzOptions
from buttercup.common.queues import FuzzConfiguration
from buttercup.common.logger import setup_package_logger
from buttercup.common.node_local import scratch_dir
from buttercup.fuzzing_infra.temp_dir import patched_temp_dir, scratch_cwd
import typing
import os
from dataclasses import dataclass
import argparse
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class Conf:
    # in seconds
    timeout: int


class Runner:
    def __init__(self, conf: Conf):
        self.conf = conf

    def run_fuzzer(self, conf: FuzzConfiguration) -> FuzzResult:
        logger.info(f"Running fuzzer with {conf.engine} | {conf.sanitizer} | {conf.target_path}")
        job_name = f"{conf.engine}_{conf.sanitizer}"

        with patched_temp_dir() as _td, scratch_cwd() as _cwd_temp:
            engine = typing.cast(Engine, get_engine(conf.engine))
            target = conf.target_path
            build_dir = os.path.dirname(target)
            distinguisher = uuid.uuid4()
            repro_dir = os.path.join(build_dir, f"repro{str(distinguisher)}")
            os.makedirs(repro_dir, exist_ok=True)
            os.environ["JOB_NAME"] = job_name
            logger.debug(f"Calling engine.prepare with {conf.corpus_dir} | {target} | {build_dir}")
            opts: FuzzOptions = engine.prepare(conf.corpus_dir, target, build_dir)
            logger.debug(f"Fuzz option corpus_dir: {opts.corpus_dir}")
            logger.debug(f"Fuzz option arguments: {opts.arguments}")
            logger.debug(f"Fuzz option strategies: {opts.strategies}")
            logger.debug(f"Calling engine.fuzz with {target} | {repro_dir} | {self.conf.timeout}")
            results: FuzzResult = engine.fuzz(target, opts, repro_dir, self.conf.timeout)
            os.environ["JOB_NAME"] = ""
            logger.debug(f"Fuzzer logs: {results.logs}")
            return results

    def merge_corpus(self, conf: FuzzConfiguration, output_dir: str):
        logger.info(f"Merging corpus with {conf.engine} | {conf.sanitizer} | {conf.target_path}")
        job_name = f"{conf.engine}_{conf.sanitizer}"
        os.environ["JOB_NAME"] = job_name
        with patched_temp_dir() as _td, scratch_cwd() as _cwd_temp:
            engine = typing.cast(Engine, get_engine(conf.engine))
            # Temporary directory ignores crashes
            with scratch_dir() as td:
                engine.minimize_corpus(
                    conf.target_path, [], [conf.corpus_dir], output_dir, str(td.path), self.conf.timeout
                )


def main():
    prsr = argparse.ArgumentParser("Fuzzer runner")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--corpusdir", required=True)
    prsr.add_argument("--engine", required=True)
    prsr.add_argument("--sanitizer", required=True)
    prsr.add_argument("target")
    args = prsr.parse_args()

    setup_package_logger("fuzzer-runner", __name__, "DEBUG", None)

    conf = Conf(args.timeout)
    fuzzconf = FuzzConfiguration(args.corpusdir, args.target, args.engine, args.sanitizer)
    runner = Runner(conf)
    print(runner.run_fuzzer(fuzzconf))


if __name__ == "__main__":
    main()
