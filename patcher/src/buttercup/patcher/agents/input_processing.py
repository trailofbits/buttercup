from buttercup.patcher.agents.common import PatcherAgentBase
from dataclasses import dataclass
from langgraph.types import Command
from langchain_core.runnables import RunnableConfig
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
)
from buttercup.patcher.utils import get_codequery


@dataclass
class InputProcessingAgent(PatcherAgentBase):
    """Input Processing LLM agent, handling the creation of patches."""

    def process_input(self, state: PatcherAgentState, config: RunnableConfig) -> Command:
        """Process the input and return the processed input."""
        configuration = PatcherConfig.from_configurable(config)
        # Run this to make sure the codequery is initialized with the correct challenge task
        get_codequery(self.challenge.task_dir, configuration.work_dir)

        return Command(
            goto=[
                PatcherAgentName.INITIAL_CODE_SNIPPET_REQUESTS.value,
                PatcherAgentName.FIND_TESTS.value,
            ],
        )
