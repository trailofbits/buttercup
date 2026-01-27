import argparse
import json
import logging
import os
import typing
import uuid
from dataclasses import dataclass

from buttercup.common.logger import setup_package_logger
from buttercup.common.node_local import scratch_dir
from buttercup.common.types import FuzzConfiguration
from clusterfuzz.fuzz import get_engine
from clusterfuzz.fuzz.engine import Engine, FuzzOptions, FuzzResult

from buttercup.fuzzer_runner.temp_dir import patched_temp_dir, scratch_cwd

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
            engine = typing.cast("Engine", get_engine(conf.engine))
            target = conf.target_path
            build_dir = os.path.dirname(target)
            distinguisher = uuid.uuid4()
            repro_dir = os.path.join(build_dir, f"repro{distinguisher!s}")
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

    def merge_corpus(self, conf: FuzzConfiguration, output_dir: str) -> None:
        logger.info(f"Merging corpus with {conf.engine} | {conf.sanitizer} | {conf.target_path}")
        job_name = f"{conf.engine}_{conf.sanitizer}"
        os.environ["JOB_NAME"] = job_name
        with patched_temp_dir() as _td, scratch_cwd() as _cwd_temp:
            engine = typing.cast("Engine", get_engine(conf.engine))
            # Temporary directory ignores crashes
            with scratch_dir() as td:
                engine.minimize_corpus(
                    conf.target_path,
                    [],
                    [conf.corpus_dir],
                    output_dir,
                    str(td.path),
                    self.conf.timeout,
                )


def run_fuzzer_command(args: argparse.Namespace, runner: Runner, fuzzconf: FuzzConfiguration) -> dict[str, typing.Any]:
    """Run fuzzer command"""
    result = runner.run_fuzzer(fuzzconf)

    # Log detailed fuzzer result information
    stats = result.stats or {}
    logger.info(
        f"Fuzzer completed: crashes={len(result.crashes)}, "
        f"timed_out={result.timed_out}, time_executed={result.time_executed:.2f}s"
    )
    logger.info(
        f"Fuzzer stats: crash_count={stats.get('crash_count', 0)}, "
        f"oom_count={stats.get('oom_count', 0)}, "
        f"timeout_count={stats.get('timeout_count', 0)}, "
        f"startup_crash_count={stats.get('startup_crash_count', 0)}, "
        f"leak_count={stats.get('leak_count', 0)}"
    )
    logger.info(
        f"Fuzzer coverage: edge_coverage={stats.get('edge_coverage', 0)}/{stats.get('edges_total', 0)}, "
        f"feature_coverage={stats.get('feature_coverage', 0)}, "
        f"new_edges={stats.get('new_edges', 0)}, new_features={stats.get('new_features', 0)}"
    )

    if result.crashes:
        for i, crash in enumerate(result.crashes):
            logger.info(f"Crash {i + 1}: input_path={crash.input_path}, crash_time={crash.crash_time}")

    result_dict = {
        "logs": result.logs,
        "command": result.command,
        "crashes": [
            {
                "input_path": crash.input_path,
                "stacktrace": crash.stacktrace,
                "reproduce_args": crash.reproduce_args,
                "crash_time": crash.crash_time,
            }
            for crash in result.crashes
        ],
        "stats": result.stats,
        "time_executed": result.time_executed,
        "timed_out": result.timed_out,
    }
    return result_dict


def merge_corpus_command(
    args: argparse.Namespace, runner: Runner, fuzzconf: FuzzConfiguration
) -> dict[str, typing.Any]:
    """Run merge corpus command"""
    runner.merge_corpus(fuzzconf, args.output_dir)

    result_dict = {
        "status": "completed",
        "output_dir": args.output_dir,
        "message": "Corpus merge completed successfully",
    }
    return result_dict


def main() -> None:
    prsr = argparse.ArgumentParser("Fuzzer runner")

    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--corpusdir", required=True)
    prsr.add_argument("--engine", required=True)
    prsr.add_argument("--sanitizer", required=True)
    prsr.add_argument("target")

    subparsers = prsr.add_subparsers(dest="command", help="Available commands")

    # Fuzzer command
    fuzzer_parser = subparsers.add_parser("fuzz", help="Run fuzzer")
    fuzzer_parser.set_defaults(func=run_fuzzer_command)

    # Merge corpus command
    merge_parser = subparsers.add_parser("merge", help="Merge corpus")
    merge_parser.add_argument("--output-dir", required=True)
    merge_parser.set_defaults(func=merge_corpus_command)

    setup_package_logger("fuzzer-runner", __name__, "DEBUG", None)

    args = prsr.parse_args()

    if not hasattr(args, "func"):
        prsr.print_help()
        return

    conf = Conf(args.timeout)
    fuzzconf = FuzzConfiguration(args.corpusdir, args.target, args.engine, args.sanitizer)
    runner = Runner(conf)

    result_dict = args.func(args, runner, fuzzconf)
    print(json.dumps(result_dict))


if __name__ == "__main__":
    main()
