from buttercup.patcher.agents.common import PatcherAgentBase
from dataclasses import dataclass
from langgraph.types import Command
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
)


@dataclass
class InputProcessingAgent(PatcherAgentBase):
    """Input Processing LLM agent, handling the creation of patches."""

    def process_input(self, state: PatcherAgentState) -> Command:
        """Process the input and return the processed input."""
        stacktrace = ""
        if state.context.sanitizer_output:
            lines_stacktrace = state.context.sanitizer_output.splitlines()[-200:]
            stacktrace = "\n".join(lines_stacktrace)

        return Command(
            update={
                "cleaned_stacktrace": stacktrace,
            },
            goto=[
                PatcherAgentName.INITIAL_CODE_SNIPPET_REQUESTS.value,
                PatcherAgentName.FIND_TESTS.value,
            ],
        )
