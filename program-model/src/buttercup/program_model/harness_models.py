"""Models for harness-related functionality."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class HarnessInfo:
    """Information about a harness."""

    file_path: Path
    code: str
    harness_name: str

    def __str__(self) -> str:
        return f"""<harness>
<harness_binary_name>{self.harness_name}</harness_binary_name>
<source_file_path>{self.file_path}</source_file_path>
<code>
{self.code}
</code>
</harness>
"""
