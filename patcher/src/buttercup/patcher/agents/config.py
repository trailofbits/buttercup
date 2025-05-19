from pydantic import BaseModel, Field
from typing import Self
from langchain_core.runnables import RunnableConfig
from pathlib import Path
import os
import uuid


class PatcherConfig(BaseModel):
    work_dir: Path
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    max_patch_retries: int = Field(default=30)
    max_last_failure_retries: int = Field(default=3)
    max_minutes_run_povs: int = Field(default=30)
    max_root_cause_analysis_retries: int = Field(default=3)
    context_retriever_recursion_limit: int = Field(default=80)
    n_initial_stackframes: int = Field(default=4)

    @classmethod
    def from_configurable(cls, config: RunnableConfig) -> Self:
        config_dict = config.get("configurable", {})
        values = {
            k: config_dict.get(k, os.getenv(f"TOB_PATCHER_{k.upper()}", v.default)) for k, v in cls.model_fields.items()
        }
        for k, v in cls.model_fields.items():
            if "int" in str(v.annotation) and values[k] is not None:
                values[k] = int(values[k])

        return cls(**values)

    def clone(self) -> Self:
        return self.model_copy(update={"thread_id": str(uuid.uuid4())})
