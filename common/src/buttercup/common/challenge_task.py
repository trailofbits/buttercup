from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
import subprocess
from dataclasses import dataclass

@dataclass
class CommandResult:
    success: bool
    error: Optional[str] = None
    output: Optional[str] = None

@dataclass
class ChallengeTask:
    """Class to manage Challenge Tasks."""

    task_dir: Path
    project_name: str
    oss_fuzz_subpath: Path
    source_subpath: Path
    diffs_subpath: Path | None = None

    def __post_init__(self) -> None:
        if not self.task_dir.exists():
            raise ValueError(f"Task directory does not exist: {self.task_dir}")

        # Verify required directories exist
        for directory in [self.oss_fuzz_subpath, self.source_subpath]:
            if not directory.is_dir():
                raise ValueError(f"Missing required directory: {directory}")

    def build_image(self) -> CommandResult:
        cmd = [
            self.python_path,
            "infra/helper.py",
            "build_image",
            self.project_name
        ]
        
        result = subprocess.run(
            cmd,
            cwd=self.oss_fuzz_dir,
            check=False,
            capture_output=True,
            text=True
        )

        return CommandResult(
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
            output=result.stdout
        )

    def build_fuzzers(
        self,
        engine: str,
        sanitizer: str,
        env: Optional[Dict[str, str]] = None
    ) -> CommandResult:
        cmd = [
            self.python_path,
            "infra/helper.py",
            "build_fuzzers",
            "--engine", engine,
            "--sanitizer", sanitizer,
            self.project_name
        ]

        # Set default environment if none provided
        if env is None:
            env = {"PYTHON_VERSION": "3.11"}

        result = subprocess.run(
            cmd,
            cwd=self.oss_fuzz_dir,
            env=env,
            check=False,
            capture_output=True,
            text=True
        )

        return CommandResult(
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
            output=result.stdout
        )

    def check_build(self, engine: str, sanitizer: str) -> CommandResult:
        cmd = [
            self.python_path,
            "infra/helper.py",
            "check_build",
            "--engine", engine,
            "--sanitizer", sanitizer,
            self.project_name
        ]

        result = subprocess.run(
            cmd,
            cwd=self.oss_fuzz_dir,
            check=False,
            capture_output=True,
            text=True
        )

        return CommandResult(
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
            output=result.stdout
        )

    def reproduce_pov(
        self,
        pov_file: Path,
        target: str,
        engine: str,
        sanitizer: str
    ) -> CommandResult:
        cmd = [
            self.python_path,
            "infra/helper.py",
            "reproduce",
            "--engine", engine,
            "--sanitizer", sanitizer,
            self.project_name,
            target,
            str(pov_file)
        ]

        result = subprocess.run(
            cmd,
            cwd=self.oss_fuzz_dir,
            check=False,
            capture_output=True,
            text=True
        )

        return CommandResult(
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
            output=result.stdout
        )
