import logging
import uuid
import subprocess
from dataclasses import dataclass
from buttercup.common.challenge_task import ChallengeTask
import os
from argparse import ArgumentParser
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class IndexConf:
    scriptdir: Path
    python: str
    allow_pull: bool
    base_image_url: str
    wdir: Path


class Indexer:
    def __init__(self, conf: IndexConf):
        self.conf = conf

    def build_image(self, task: ChallengeTask) -> str | None:
        logger.debug(f"Building image for {task.task_meta.task_id}")
        res = task.build_image(pull_latest_base_image=self.conf.allow_pull)
        if not res.success:
            return None
        base_image_name = f"{self.conf.base_image_url}/{task.project_name}"

        buildid = task.task_meta.task_id
        emitted_image = f"kyther_indexer_image_{task.project_name}_{buildid}"
        wdir = f"{self.conf.scriptdir}"
        command = [
            "docker",
            "build",
            "-t",
            emitted_image,
            "--build-arg",
            f"BASE_IMAGE={base_image_name}",
            ".",
        ]
        result = subprocess.run(command, check=True, cwd=wdir, capture_output=True)
        if result.returncode != 0:
            logger.error(
                f"Failed to build image for {task.task_meta.task_id}. Return code: {result.returncode}"
            )
            return None
        logger.debug(f"Finished building image for {task.task_meta.task_id}")
        return emitted_image

    def index_target(self, task: ChallengeTask) -> str | None:
        logger.debug(f"Started indexing target {task.task_meta.task_id}")
        emitted_image = self.build_image(task)
        if emitted_image is None:
            return None

        indexuid = str(uuid.uuid4())
        output_dir = f"{self.conf.wdir}/output_{indexuid}"
        os.makedirs(output_dir, exist_ok=True)
        workdir = task.workdir_from_dockerfile().absolute().as_posix()

        # Log directory information
        logger.debug(f"Task source path: {task.get_source_path().absolute()}")
        logger.debug(f"Work directory: {workdir}")
        logger.debug(f"Output directory: {output_dir}")

        # Verify directories exist
        if not task.get_source_path().exists():
            logger.error(
                f"Source path does not exist: {task.get_source_path().absolute()}"
            )
            return None

        command = [
            "docker",
            "run",
            "-v",
            f"{task.get_source_path().absolute()}:{workdir}",
            "-v",
            f"{output_dir}:/kythe_out",
            "-e",
            "KYTHE_OUTPUT_DIRECTORY=/kythe_out",
            "-e",
            f"KYTHE_CORPUS={task.task_meta.task_id}",
            emitted_image,
            "compile_and_extract",
        ]
        result = subprocess.run(command, check=True, capture_output=True)
        if result.returncode != 0:
            logger.error(
                f"Failed to index target {task.task_meta.task_id}. Return code: {result.returncode}"
            )
            return None
        logger.debug(f"Finished indexing target {task.task_meta.task_id}")
        return output_dir


def main() -> None:
    prsr = ArgumentParser()
    prsr.add_argument("--scriptdir", type=str, required=True)
    prsr.add_argument("--python", default="python3")
    prsr.add_argument("--allow_pull", type=bool, default=True)
    prsr.add_argument("--base_image_url", type=str, default="gcr.io/oss-fuzz")
    prsr.add_argument("--wdir", type=str, default="/tmp")
    prsr.add_argument("--task_dir", type=str, required=True)
    args = prsr.parse_args()

    conf = IndexConf(
        scriptdir=args.scriptdir,
        python=args.python,
        allow_pull=args.allow_pull,
        base_image_url=args.base_image_url,
        wdir=args.wdir,
    )

    task = ChallengeTask(
        args.task_dir,
    )
    with task.get_rw_copy(work_dir=args.wdir, delete=False) as local_task:
        indexer = Indexer(conf)
        print(indexer.index_target(local_task))


if __name__ == "__main__":
    main()
