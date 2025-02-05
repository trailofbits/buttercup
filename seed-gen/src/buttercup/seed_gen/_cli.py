"""The `seed-gen` entrypoint."""

import argparse
import os
import tempfile
from pathlib import Path

from redis import Redis

from buttercup.common import utils
from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.msg_pb2 import BuildOutput, WeightedHarness
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.logger import setup_logging
from buttercup.common.maps import BUILD_TYPES
from buttercup.seed_gen.tasks import Task, do_seed_explore, do_seed_init, do_vuln_discovery

logger = setup_logging(__name__, os.getenv("LOG_LEVEL", "INFO").upper())


class SeedGenBot(TaskLoop):
    def __init__(self, redis: Redis, timer_seconds: int, wdir: str):
        self.wdir = wdir
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> list[BUILD_TYPES]:
        return [BUILD_TYPES.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        with tempfile.TemporaryDirectory(dir=self.wdir, prefix="seedgen-") as temp_dir_str:
            logger.info(
                f"Running seed-gen for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
            temp_dir = Path(temp_dir_str)
            logger.debug(f"Temp dir: {temp_dir}")
            out_dir = temp_dir / "seedgen-out"
            out_dir.mkdir()

            corp = Corpus(self.wdir, task.task_id, task.harness_name)

            build = builds[BUILD_TYPES.FUZZER]
            logger.info(f"Build dir: {build.output_ossfuzz_path}")
            output_ossfuzz_path = Path(build.output_ossfuzz_path)
            build_dir = output_ossfuzz_path / "build/out" / build.package_name
            copied_build_dir = temp_dir / build_dir.name
            utils.copyanything(build_dir, copied_build_dir)

            do_seed_init(build.package_name, out_dir)
            num_files = sum(1 for _ in out_dir.iterdir())
            logger.info("Copying %d files to corpus %s", num_files, corp.corpus_dir)
            corp.copy_corpus(out_dir)
            logger.info(
                f"Seed-gen finished for {task.harness_name} | {task.package_name} | {task.task_id}"
            )


def command_server(args: argparse.Namespace) -> None:
    """Seed-gen worker server"""
    os.makedirs(args.wdir, exist_ok=True)
    redis = Redis.from_url(args.redis_url)
    seed_gen_bot = SeedGenBot(redis, args.sleep, args.wdir)
    seed_gen_bot.run()


def command_task(args: argparse.Namespace) -> None:
    """Run single task"""
    task_name = args.task_name
    out_dir = args.out_dir
    out_dir.mkdir(parents=True)
    if task_name == Task.SEED_INIT:
        challenge = "libpng"
        do_seed_init(challenge, out_dir)
    elif task_name == Task.SEED_EXPLORE:
        do_seed_explore()
    elif task_name == Task.VULN_DISCOVERY:
        do_vuln_discovery()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    parser_server = subparsers.add_parser("server", help="Run seed-gen server")
    parser_server.add_argument(
        "--redis_url", required=False, help="Redis URL", default="redis://127.0.0.1:6379"
    )
    parser_server.add_argument("--wdir", required=True, help="Working directory")
    parser_server.add_argument(
        "--sleep", required=False, default=1, type=int, help="Sleep between runs (seconds)"
    )
    parser_task = subparsers.add_parser("task", help="Do a task")
    parser_task.add_argument(
        "task_name", choices=Task, help="Task name", metavar=", ".join(task.value for task in Task)
    )
    parser_task.add_argument("--out-dir", required=True, type=Path, help="Output directory")
    args = parser.parse_args()
    if args.command == "server":
        command_server(args)
    elif args.command == "task":
        command_task(args)
