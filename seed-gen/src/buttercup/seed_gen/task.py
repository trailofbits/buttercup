from enum import Enum

from langchain_core.language_models import BaseChatModel

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm, get_langfuse_callbacks


class TaskName(str, Enum):
    SEED_INIT = "seed-init"
    SEED_EXPLORE = "seed-explore"
    VULN_DISCOVERY = "vuln-discovery"


class Task:
    def __init__(
        self,
        package_name: str,
        harness_name: str,
        challenge_task: ChallengeTask,
        llm: BaseChatModel | None = None,
    ):
        self.package_name = package_name
        self.harness_name = harness_name
        self.challenge_task = challenge_task
        if llm is None:
            self.llm = self.get_default_llm()
        else:
            self.llm = llm

    @staticmethod
    def get_default_llm() -> BaseChatModel:
        llm_callbacks = get_langfuse_callbacks()
        llm = create_default_llm(
            model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value, callbacks=llm_callbacks
        )
        return llm
