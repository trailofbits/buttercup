from dataclasses import dataclass, asdict
import json
from pathlib import Path
from os import PathLike


@dataclass
class TaskMeta:
    """Metadata about a task, including project name and focus area."""

    METADATA_FILENAME = "task_meta.json"  # Constant for the filename
    project_name: str
    focus: str
    task_id: str
    metadata: dict

    @classmethod
    def load(cls, directory: PathLike) -> "TaskMeta":
        """Load TaskMeta from a JSON file in the specified directory.

        Args:
            directory: Directory containing the metadata file

        Returns:
            TaskMeta instance loaded from the file

        Raises:
            FileNotFoundError: If the file doesn't exist
            JSONDecodeError: If the file contains invalid JSON
        """
        path = Path(directory) / cls.METADATA_FILENAME
        with path.open() as f:
            data = json.load(f)
        return cls(**data)

    def save(self, directory: PathLike) -> None:
        """Save TaskMeta to a JSON file in the specified directory.

        Args:
            directory: Directory where to save the metadata file
        """
        path = Path(directory) / self.METADATA_FILENAME
        with path.open("w") as f:
            json.dump(asdict(self), f, indent=2)
