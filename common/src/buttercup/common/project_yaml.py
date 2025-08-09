from dataclasses import dataclass, field
from enum import Enum

import yaml

from buttercup.common.challenge_task import ChallengeTask


class Language(str, Enum):
    C = "c"
    JAVA = "java"


@dataclass
class ProjectYaml:
    challenge_task: ChallengeTask
    project_name: str
    _language: str | None = field(init=False, default=None)
    _sanitizers: list[str] = field(init=False, default_factory=list)
    _fuzzing_engines: list[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        oss_fuzz_path = self.challenge_task.get_oss_fuzz_path()
        if oss_fuzz_path is None:
            raise ValueError("OSS-Fuzz path not found")

        project_yaml_path = oss_fuzz_path / "projects" / self.project_name / "project.yaml"

        if not project_yaml_path.exists():
            raise FileNotFoundError(f"Could not find project.yaml at {project_yaml_path}")

        with open(project_yaml_path) as f:
            yaml_content = yaml.safe_load(f)
        self._language = yaml_content.get("language")
        self._sanitizers = yaml_content.get("sanitizers", ["address"])
        self._fuzzing_engines = yaml_content.get("fuzzing_engines", ["libfuzzer"])

    @property
    def language(self) -> str:
        # language is a required field in the project.yaml file
        if self._language is None:
            raise ValueError("Language not set")
        return self._language

    @property
    def unified_language(self) -> Language:
        """Language field but with a more consistent naming convention."""
        if self.language.lower() in ["c", "c++", "cpp"]:
            return Language.C
        elif self.language.lower() in ["java", "jvm"]:
            return Language.JAVA

        raise ValueError(f"Unsupported language: {self.language}")

    @property
    def sanitizers(self) -> list[str]:
        return self._sanitizers

    @property
    def fuzzing_engines(self) -> list[str]:
        return self._fuzzing_engines
