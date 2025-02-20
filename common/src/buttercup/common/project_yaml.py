from dataclasses import dataclass, field
import yaml
from buttercup.common.challenge_task import ChallengeTask


@dataclass
class ProjectYaml:
    challenge_task: ChallengeTask
    project_name: str
    _sanitizers: list[str] | None = field(init=False, default=None)
    _fuzzing_engines: list[str] | None = field(init=False, default=None)

    def __post_init__(self):
        project_yaml_path = self.challenge_task.get_oss_fuzz_path() / "projects" / self.project_name / "project.yaml"

        if not project_yaml_path.exists():
            raise FileNotFoundError(f"Could not find project.yaml at {project_yaml_path}")

        with open(project_yaml_path) as f:
            yaml_content = yaml.safe_load(f)
        self._sanitizers = yaml_content.get("sanitizers", ["address"])
        self._fuzzing_engines = yaml_content.get("fuzzing_engines", ["libfuzzer"])

    @property
    def sanitizers(self) -> list[str]:
        return self._sanitizers

    @property
    def fuzzing_engines(self) -> list[str]:
        return self._fuzzing_engines
