"""The `seed-gen` entrypoint."""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from pydantic_settings import get_subcommand
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.logger import setup_package_logger
from buttercup.common.project_yaml import ProjectYaml
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
    os.makedirs(settings.server.wdir, exist_ok=True)
    if settings.server.corpus_root:
        os.makedirs(settings.server.corpus_root, exist_ok=True)
    init_telemetry("seed-gen")
    redis = Redis.from_url(settings.server.redis_url)
    seed_gen_bot = SeedGenBot(
        redis,
        settings.server.sleep_time,
        settings.server.wdir,
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
        out_dir.mkdir(parents=True, exist_ok=True)
        codequery = CodeQueryPersistent(challenge_task, work_dir=Path(settings.wdir))
        project_yaml = ProjectYaml(challenge_task, command.package_name)

        if command.task_type == TaskName.SEED_INIT.value:
            task = SeedInitTask(
                command.package_name,
                command.harness_name,
                challenge_task,
                codequery,
                project_yaml,
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
            )
            task.do_task(command.target_function, command.target_function_paths, out_dir)
        elif command.task_type == TaskName.VULN_DISCOVERY.value:
            if challenge_task.is_delta_mode():
                task = VulnDiscoveryDeltaTask(
                    command.package_name,
                    command.harness_name,
                    challenge_task,
                    codequery,
                    project_yaml,
                    [],
                )
            else:
                task = VulnDiscoveryFullTask(
                    command.package_name,
                    command.harness_name,
                    challenge_task,
                    codequery,
                    project_yaml,
                    [],  # skipping sarifs for now
                )
            task.do_task(out_dir)

            # Only reproduces against current challenge project, instead of all builds
            for pov in out_dir.iterdir():
                result = challenge_task.reproduce_pov(command.harness_name, pov)
                if result.did_crash():
                    logger.info(f"Valid PoV found: {pov}")
        else:
            raise ValueError(f"Unknown task type: {command.task_type}")

        shutil.copytree(out_dir, command_outdir)


def main() -> None:
    settings = Settings()
    setup_package_logger("seed-gen", __name__, settings.log_level.upper())
    command = get_subcommand(settings)
    if isinstance(command, ProcessCommand):
        command_process(settings)
    else:
        command_server(settings)
