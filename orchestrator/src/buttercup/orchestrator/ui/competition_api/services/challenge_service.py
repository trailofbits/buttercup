from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from buttercup.orchestrator.ui.competition_api.models.crs_types import (
    SARIFBroadcast,
    SARIFBroadcastDetail,
    SourceDetail,
    SourceType,
    Task,
    TaskDetail,
    TaskType,
)

logger = logging.getLogger(__name__)


class ChallengeService:
    def __init__(self, storage_dir: Path, base_url: str) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url

    def create_challenge_tarball(
        self,
        repo_url: str,
        ref: str,
        tarball_name: str,
        exclude_dirs: list[str] | None = None,
        base_ref: str | None = None,
    ) -> tuple[str, str, str | None]:
        """
        Clone a git repository, checkout the specified ref, and create a tarball.

        Args:
            repo_url: Git repository URL
            ref: Git reference (branch, tag, or commit)
            tarball_name: Name for the tarball file
            exclude_dirs: Directories to exclude from the tarball

        Returns:
            Tuple of (focus_dir, sha256_hash, diff_sha256_hash)
        """
        if exclude_dirs is None:
            exclude_dirs = [".git", ".aixcc"]

        focus_dir = self._extract_focus_dir(repo_url)
        cur_ref = ref if not base_ref else base_ref

        with tempfile.TemporaryDirectory(dir=self.storage_dir) as temp_dir:
            temp_path = Path(temp_dir)
            sub_path = temp_path / focus_dir
            sub_path.mkdir(parents=True, exist_ok=True)

            # Clone the repository
            logger.info(f"Cloning {repo_url} to {sub_path}")

            # Check if we have GitHub credentials for private repos
            github_pat = os.environ.get("GITHUB_PAT")
            github_username = os.environ.get("GITHUB_USERNAME")

            if github_pat and github_username and "github.com" in repo_url:
                # For GitHub repositories, use the PAT for authentication
                if repo_url.startswith("https://github.com/"):
                    # Convert https://github.com/owner/repo.git to https://username:pat@github.com/owner/repo.git
                    auth_url = repo_url.replace(
                        "https://github.com/", f"https://{github_username}:{github_pat}@github.com/"
                    )
                    logger.info("Using authenticated URL for private repository")
                    clone_url = auth_url
                else:
                    clone_url = repo_url
            else:
                clone_url = repo_url

            result = subprocess.run(
                ["git", "clone", clone_url, sub_path],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Git clone output: {result.stdout}")

            # Checkout the specified ref
            logger.info(f"Checking out ref: {cur_ref}")
            result = subprocess.run(
                ["git", "checkout", cur_ref],
                cwd=sub_path,
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Git checkout output: {result.stdout}")

            # Create tarball
            tarball_path = self.storage_dir / f"{tarball_name}.tar.gz"

            with tarfile.open(tarball_path, "w:gz") as tar:
                # Add all files except excluded directories
                for item in temp_path.iterdir():
                    if item.name not in exclude_dirs:
                        tar.add(item, arcname=item.name)

            # Calculate SHA256 hash
            sha256_hash = self._calculate_sha256(tarball_path)
            # Rename the tarball to use the sha256 hash
            new_tarball_path = self.storage_dir / f"{sha256_hash}.tar.gz"
            os.rename(tarball_path, new_tarball_path)

            logger.info(f"Created tarball: {new_tarball_path}")
            diff_sha256_hash = None
            if base_ref:
                # Copy the checkout to a temporary directory
                with tempfile.TemporaryDirectory(dir=self.storage_dir) as base_temp_dir:
                    base_temp_path = Path(base_temp_dir)
                    base_sub_path = base_temp_path / "A"
                    ref_sub_path = base_temp_path / "B"

                    # Copy the cur_ref version to a temporary directory
                    shutil.copytree(sub_path, base_sub_path, ignore=shutil.ignore_patterns(".git", ".aixcc"))

                    # Checkout the base ref
                    logger.info(f"Checking out base ref: {ref}")
                    result = subprocess.run(
                        ["git", "checkout", ref],
                        cwd=sub_path,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    logger.info(f"Git checkout output: {result.stdout}")
                    shutil.copytree(sub_path, ref_sub_path, ignore=shutil.ignore_patterns(".git", ".aixcc"))

                    # Create a git-diff file between the two directories (base_sub_path and ref_sub_path)
                    diff_result = subprocess.run(
                        ["git", "diff", "--binary", "--no-index", base_sub_path.as_posix(), ref_sub_path.as_posix()],
                        cwd=base_temp_path,
                        capture_output=True,
                    )
                    diff_path = base_temp_path / "diff"
                    diff_path.mkdir(parents=True, exist_ok=True)
                    diff_file = diff_path / "ref.diff"
                    diff_content = diff_result.stdout
                    diff_content = diff_content.replace(base_sub_path.as_posix().encode(), b"")
                    diff_content = diff_content.replace(ref_sub_path.as_posix().encode(), b"")
                    diff_file.write_bytes(diff_content)
                    diff_tarball_path = diff_path / "diff.tar.gz"

                    with tarfile.open(diff_tarball_path, "w:gz") as tar:
                        tar.add(diff_path, arcname=diff_path.relative_to(base_temp_path).as_posix())

                    # Calculate SHA256 hash
                    diff_sha256_hash = self._calculate_sha256(diff_tarball_path)
                    # Rename the tarball to use the sha256 hash
                    new_diff_tarball_path = self.storage_dir / f"{diff_sha256_hash}.tar.gz"
                    os.rename(diff_tarball_path, new_diff_tarball_path)
                    logger.info(f"Created diff tarball: {new_diff_tarball_path}")

            return focus_dir, sha256_hash, diff_sha256_hash

    def _calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def serve_tarball(self, tarball_name: str) -> FileResponse:
        """Serve a tarball file."""
        tarball_path = self.storage_dir / f"{tarball_name}.tar.gz"
        tarball_path = tarball_path.resolve()

        if not tarball_path.exists() or not tarball_path.is_relative_to(self.storage_dir):
            raise HTTPException(status_code=404, detail=f"Tarball {tarball_name} not found")

        return FileResponse(
            path=tarball_path,
            filename=f"{tarball_name}.tar.gz",
            media_type="application/gzip",
        )

    def _extract_focus_dir(self, repo_url: str) -> str:
        """Extract the focus directory from the repository URL."""
        focus_dir = repo_url.rstrip("/").split("/")[-1]
        if focus_dir.endswith(".git"):
            focus_dir = focus_dir[:-4]  # Remove .git suffix
        return focus_dir

    def create_task_for_challenge(
        self,
        challenge_repo_url: str,
        challenge_repo_ref: str,
        challenge_repo_base_ref: str | None,
        fuzz_tooling_url: str,
        fuzz_tooling_ref: str,
        fuzz_tooling_project_name: str,
        duration_secs: int,
    ) -> Task:
        """
        Create a task for a challenge by processing repositories and creating tarballs.

        Args:
            challenge_repo_url: URL of the challenge repository
            challenge_repo_ref: Git reference for the challenge repository
            challenge_repo_base_ref: Git base reference for the challenge repository
            fuzz_tooling_url: URL of the fuzz tooling repository
            fuzz_tooling_ref: Git reference for the fuzz tooling repository
            fuzz_tooling_project_name: Name of the fuzz tooling project
            duration_secs: Duration of the task in seconds

        Returns:
            Task object ready to be sent to CRS
        """
        task_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        current_time = int(time.time() * 1000)  # Current time in milliseconds
        deadline = current_time + (duration_secs * 1000)  # Deadline in milliseconds

        # Create tarballs
        challenge_tarball_name = f"{fuzz_tooling_project_name}-repo-{task_id}"
        fuzz_tooling_tarball_name = f"{fuzz_tooling_project_name}-fuzz-tooling-{task_id}"

        # Create challenge repository tarball
        logger.info(f"Creating challenge repository tarball for {challenge_repo_url} with ref {challenge_repo_ref}")
        focus_dir, challenge_sha256, diff_sha256 = self.create_challenge_tarball(
            repo_url=challenge_repo_url,
            ref=challenge_repo_ref,
            tarball_name=challenge_tarball_name,
            base_ref=challenge_repo_base_ref,
        )

        # Create fuzz tooling tarball
        logger.info(f"Creating fuzz tooling repository tarball for {fuzz_tooling_url} with ref {fuzz_tooling_ref}")
        _, fuzz_tooling_sha256, _ = self.create_challenge_tarball(
            repo_url=fuzz_tooling_url,
            ref=fuzz_tooling_ref,
            tarball_name=fuzz_tooling_tarball_name,
        )

        # Create source details
        sources = [
            SourceDetail(
                sha256=challenge_sha256,
                type=SourceType.repo,
                url=f"{self.base_url}/files/{challenge_sha256}.tar.gz",
            ),
            SourceDetail(
                sha256=fuzz_tooling_sha256,
                type=SourceType.fuzz_tooling,
                url=f"{self.base_url}/files/{fuzz_tooling_sha256}.tar.gz",
            ),
        ]

        if diff_sha256:
            sources.append(
                SourceDetail(
                    sha256=diff_sha256,
                    type=SourceType.diff,
                    url=f"{self.base_url}/files/{diff_sha256}.tar.gz",
                )
            )

        # Create task detail
        task_detail = TaskDetail(
            deadline=deadline,
            focus=focus_dir,
            harnesses_included=True,  # Assuming harnesses are included
            metadata={
                "challenge_repo_url": challenge_repo_url,
                "challenge_repo_ref": challenge_repo_ref,
                "challenge_repo_base_ref": challenge_repo_base_ref or "",
                "fuzz_tooling_url": fuzz_tooling_url,
                "fuzz_tooling_ref": fuzz_tooling_ref,
            },
            project_name=fuzz_tooling_project_name,
            source=sources,
            task_id=task_id,
            type=TaskType.delta if diff_sha256 else TaskType.full,
        )

        # Create task
        task = Task(
            message_id=message_id,
            message_time=current_time,
            tasks=[task_detail],
        )

        logger.info(f"Created task {task_id} for challenge {fuzz_tooling_project_name}")
        return task

    def create_sarif_broadcast(self, task_id: str, sarif: dict[str, Any]) -> SARIFBroadcast:
        """
        Create a SARIF Broadcast for a task
        """
        sarif_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        message_time = int(time.time() * 1000)
        return SARIFBroadcast(
            broadcasts=[
                SARIFBroadcastDetail(
                    metadata={},
                    sarif=sarif,
                    sarif_id=sarif_id,
                    task_id=task_id,
                )
            ],
            message_id=message_id,
            message_time=message_time,
        )
