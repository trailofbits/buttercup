"""The `seed-gen` entrypoint."""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from pydantic_settings import get_subcommand
from redis import Redis

import buttercup.seed_gen.cli_load_dotenv  # noqa: F401
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.logger import setup_package_logger
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.common.telemetry import init_telemetry
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.config import ProcessCommand, Settings
from buttercup.seed_gen.seed_explore import SeedExploreTask
from buttercup.seed_gen.seed_gen_bot import SeedGenBot
from buttercup.seed_gen.seed_init import SeedInitTask
from buttercup.seed_gen.task import TaskName
from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask
from buttercup.seed_gen.vuln_discovery_full import VulnDiscoveryFullTask

logger = logging.getLogger(__name__)


def command_server(settings: Settings) -> None:
    """Seed-gen worker server"""
    os.makedirs(settings.wdir, exist_ok=True)
    if settings.server.corpus_root:
        os.makedirs(settings.server.corpus_root, exist_ok=True)
    init_telemetry("seed-gen")
    redis = Redis.from_url(settings.server.redis_url)
    seed_gen_bot = SeedGenBot(
        redis,
        settings.server.sleep_time,
        settings.wdir,
        max_corpus_seed_size=settings.server.max_corpus_seed_size,
        max_pov_size=settings.server.max_pov_size,
        corpus_root=settings.server.corpus_root,
        crash_dir_count_limit=settings.server.crash_dir_count_limit,
    )
    seed_gen_bot.run()


def command_process(settings: Settings) -> None:
    """Process a single seed generation task"""
    command = get_subcommand(settings)
    if not isinstance(command, ProcessCommand):
        return

    command_outdir = command.output_dir

    init_telemetry("seed-gen")
    ro_challenge_task = ChallengeTask(read_only_task_dir=command.challenge_task_dir)
    with (
        tempfile.TemporaryDirectory(dir=settings.wdir, prefix="seedgen-") as temp_dir_str,
        ro_challenge_task.get_rw_copy(work_dir=temp_dir_str) as challenge_task,
    ):
        temp_dir = Path(temp_dir_str)
        out_dir = temp_dir / "out"
        out_dir.mkdir()
        current_dir = temp_dir / "seedgen-current"
        current_dir.mkdir()
        codequery = CodeQueryPersistent(challenge_task, work_dir=Path(settings.wdir))
        project_yaml = ProjectYaml(challenge_task, command.package_name)

        if command.task_type == TaskName.SEED_INIT.value:
            task = SeedInitTask(
                command.package_name,
                command.harness_name,
                challenge_task,
                codequery,
                project_yaml,
                None,
            )
            task.do_task(out_dir)
        elif command.task_type == TaskName.SEED_EXPLORE.value:
            if not command.target_function or not command.target_function_paths:
                raise ValueError(
                    "target_function and target_function_paths required for seed-explore"
                )
            task = SeedExploreTask(
                command.package_name,
                command.harness_name,
                challenge_task,
                codequery,
                project_yaml,
                None,
            )
            task.do_task(command.target_function, command.target_function_paths, out_dir)
        elif command.task_type == TaskName.VULN_DISCOVERY.value:
            if not command.build_output:
                raise ValueError("build_outputs required for vuln-discovery task")

            fbuilds = []
            # can only specify one build output currently
            build = command.build_output
            build_output = BuildOutput()
            build_output.task_dir = build["task_dir"]
            build_output.build_type = build["build_type"]
            build_output.engine = build["engine"]
            build_output.sanitizer = build["sanitizer"]
            build_output.apply_diff = build["apply_diff"]
            fbuilds.append(build_output)

            reproduce_multiple = ReproduceMultiple(temp_dir, fbuilds)
            with reproduce_multiple.open() as mult:
                if challenge_task.is_delta_mode():
                    task = VulnDiscoveryDeltaTask(
                        command.package_name,
                        command.harness_name,
                        challenge_task,
                        codequery,
                        project_yaml,
                        None,
                        mult,
                        [],  # skipping sarifs for now
                    )
                else:
                    task = VulnDiscoveryFullTask(
                        command.package_name,
                        command.harness_name,
                        challenge_task,
                        codequery,
                        project_yaml,
                        None,
                        mult,
                        [],  # skipping sarifs for now
                    )
                task.do_task(out_dir, current_dir)
        else:
            raise ValueError(f"Unknown task type: {command.task_type}")

        shutil.copytree(out_dir, command_outdir)


def main() -> None:
    settings = Settings()
    setup_package_logger(
        "seed-gen", __name__, settings.log_level.upper(), settings.log_max_line_length
    )
    command = get_subcommand(settings)
    if isinstance(command, ProcessCommand):
        command_process(settings)
    else:
        command_server(settings)
