from clusterfuzz.fuzz import get_engine
from clusterfuzz.fuzz.engine import Engine, FuzzResult, FuzzOptions
from buttercup.common.queues import FuzzConfiguration
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
        job_name = f"{conf.engine}_{conf.sanitizer}"

        engine = typing.cast(Engine, get_engine(conf.engine))
        target = conf.target_path
        build_dir = os.path.dirname(target)
        distinguisher = uuid.uuid4()
        repro_dir = os.path.join(build_dir, f"repro{str(distinguisher)}")
        os.makedirs(repro_dir, exist_ok=True)
        os.environ["JOB_NAME"] = job_name
        logger.debug(f"Calling engine.prepare with {conf.corpus_dir} | {target} | {build_dir}")
        opts: FuzzOptions = engine.prepare(conf.corpus_dir, target, build_dir)
        logger.debug(f"Calling engine.fuzz with {target} | {repro_dir} | {self.conf.timeout}")
        results: FuzzResult = engine.fuzz(target, opts, repro_dir, self.conf.timeout)
        os.environ["JOB_NAME"] = ""
        print(results.logs)
        return results


def main():
    prsr = argparse.ArgumentParser("Fuzzer runner")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--corpusdir", required=True)
    prsr.add_argument("--engine", required=True)
    prsr.add_argument("--sanitizer", required=True)
    prsr.add_argument("target")
    args = prsr.parse_args()

    conf = Conf(args.timeout)
    fuzzconf = FuzzConfiguration(args.corpusdir, args.target, args.engine, args.sanitizer)
    runner = Runner(conf)
    print(runner.run_fuzzer(fuzzconf))


if __name__ == "__main__":
    main()
