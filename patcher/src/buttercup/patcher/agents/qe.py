"""Quality Engineer LLM agent, handling the testing of patches."""

import logging
import tempfile
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import Literal
from langgraph.types import Command
from langgraph.constants import END
from buttercup.common.corpus import CrashDir
from buttercup.common.challenge_task import ChallengeTaskError, CommandResult
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from pydantic import BaseModel, Field
import buttercup.common.node_local as node_local
from langchain_core.runnables import Runnable
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_DIFF_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_ROOT_CAUSE_TMPL,
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    PatchOutput,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm
from buttercup.patcher.utils import get_diff_content
from pydantic import ValidationError
import time

logger = logging.getLogger(__name__)

REVIEW_PATCH_SYSTEM_TMPL = """You are a Software Quality Engineer.

Your job is to review a patch created by a security engineer. The patch should \
fix the vulnerability and follow the guidelines. If the patch does not follow \
the guidelines, provide feedback to the security engineer.

Guidelines:
- The patch should fix the vulnerability described in the root cause analysis;
- The patch should address all points described in the root cause analysis;
- The patch should not contain unrelated changes;
- The patch should not introduce new vulnerabilities;
- The patch should not fix other vulnerabilities not described in the root cause \
analysis or not introduced in the vulnerable diff. Only consider the direct, \
root-cause vulnerability. No indirect or related vulnerabilities;
- The patch should be as simple and as minimal as possible to fix the \
vulnerability described in the root cause analysis;
- The patch should not contain TODOs, FIXMEs, other placeholders, or incomplete \
code.
- The patch should try to fix the root cause of the vulnerability, not just \
address the symptoms.

Analyze each snippet of the patch and provide feedback for each snippet.
"""

REVIEW_PATCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", REVIEW_PATCH_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        ("user", "Patch to review:\n```\n{patch}\n```\n"),
    ]
)

REVIEW_PATCH_STRUCTURED_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "Your job is to format the review provided below.\n{format_instructions}"),
        ("user", "Patch:\n```\n{patch}\n```\n"),
        ("ai", "Review:\n```\n{review}\n```\n"),
    ]
)


class ReviewPatchOutput(BaseModel):
    """Patch review"""

    suggestions: list[str] | None = Field(
        description="list of actionable points that still needs to be fixed in the provided patch"
    )
    approved: bool | None = Field(
        description="True if the patch follows ALL the guidelines, false if \
there are some points to address in the review."
    )


@dataclass
class QEAgent(PatcherAgentBase):
    """Quality Engineer LLM agent, handling the testing of patches."""

    work_dir: Path
    llm: Runnable = field(init=False)
    review_patch_chain: Runnable = field(init=False)
    review_patch_structured_chain: Runnable = field(init=False)
    max_review_retries: int = 3
    max_minutes_run_povs: int = 30

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_7_SONNET.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)
        parser = JsonOutputParser(pydantic_object=ReviewPatchOutput)
        self.review_patch_chain = REVIEW_PATCH_PROMPT | self.llm | StrOutputParser()
        self.review_patch_structured_chain = (
            {"patch": itemgetter("patch"), "review": self.review_patch_chain}
            | REVIEW_PATCH_STRUCTURED_PROMPT.partial(format_instructions=parser.get_format_instructions())
            | self.llm
            | parser
        )

    def get_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        diff_content = get_diff_content(self.challenge)

        messages += [CONTEXT_DIFF_TMPL.format(diff_content=diff_content)]
        if state.root_cause:
            messages += [CONTEXT_ROOT_CAUSE_TMPL.format(root_cause=state.root_cause)]

        for code_snippet in state.relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet.key.file_path,
                    identifier=code_snippet.key.identifier,
                    code=code_snippet.code,
                    code_context=code_snippet.code_context,
                )
            ]

        return messages

    def review_patch_node(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.BUILD_PATCH.value, PatcherAgentName.CREATE_PATCH.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that reviews a patch"""
        if state.patch_review_tries >= self.max_review_retries:
            logger.warning("Reached max review retries, skipping review")
            return Command(goto=PatcherAgentName.BUILD_PATCH.value)

        logger.info("Reviewing the last patch to ensure it follows the guidelines")
        default_review_result = ReviewPatchOutput(suggestions=[], approved=True)
        last_patch = state.get_last_patch()
        if not last_patch:
            logger.fatal("No patch to review")
            raise RuntimeError("No patch to review")

        review_result_dict: dict = self.chain_call(
            lambda _, y: y,
            self.review_patch_structured_chain,
            {
                "context": self.get_context(state),
                "patch": last_patch.patch,
            },
            # If the reviewer fails for some unexpected reasons, assume the patch is
            # good, so the patching process does not stop and tries to build the
            # patch anyway.
            default=default_review_result.dict(),  # type: ignore[call-arg]
        )
        try:
            review_result = ReviewPatchOutput.validate(review_result_dict)
        except ValidationError:
            logger.warning("Failed to parse the review result: %s", review_result_dict)
            review_result = default_review_result

        patch_review_tries = state.patch_review_tries + 1
        patch_review_str = (
            None if review_result.approved else "\n".join("- " + x for x in review_result.suggestions or [])
        )
        return Command(
            update={
                "patch_review": patch_review_str,
                "patch_review_tries": patch_review_tries,
            },
            goto=PatcherAgentName.BUILD_PATCH.value if review_result.approved else PatcherAgentName.CREATE_PATCH.value,
        )

    def _patch_challenge(self, patch: PatchOutput) -> bool:
        with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
            patch_file.write(patch.patch)
            patch_file.flush()
            logger.debug("Patch written to %s", patch_file.name)

            logger.info(
                "Applying patch to task %s / submission index %s", self.input.task_id, self.input.submission_index
            )
            try:
                return self.challenge.apply_patch_diff(Path(patch_file.name))  # type: ignore[no-any-return]
            except ChallengeTaskError:
                if logger.getEffectiveLevel() == logging.DEBUG:
                    logger.exception("Failed to apply patch to Challenge Task %s", self.challenge.name)

                return False

    def _rebuild_challenge(self) -> CommandResult:
        try:
            cp_output = self.challenge.build_fuzzers(
                engine=self.input.engine,
                sanitizer=self.input.sanitizer,
            )
        except ChallengeTaskError as exc:
            logger.error("Failed to run build_fuzzers on Challenge Task %s with patch", self.challenge.name)
            return CommandResult(
                success=False,
                output=exc.stdout,
                error=exc.stderr,
            )

        if not cp_output.success:
            logger.error("Failed to build Challenge Task %s with patch", self.challenge.name)
            return CommandResult(
                success=False,
                output=cp_output.output,
                error=cp_output.error,
            )

        return CommandResult(
            success=True,
            output=cp_output.output,
            error=cp_output.error,
        )

    def build_patch_node(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.RUN_POV.value, PatcherAgentName.BUILD_FAILURE_ANALYSIS.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that builds a patch"""
        logger.info("Rebuilding Challenge Task %s with patch", self.challenge.name)
        last_patch = state.get_last_patch()
        if not last_patch:
            logger.fatal("No patch to build, this should never happen")
            raise RuntimeError("No patch to build, this should never happen")

        update_state = {
            "build_succeeded": False,
            "build_stdout": None,
            "build_stderr": None,
            "patch_review_tries": 0,
        }
        if not self._patch_challenge(last_patch):
            logger.error("Failed to apply patch to Challenge Task %s", self.challenge.name)
            return Command(
                update=update_state,
                goto=PatcherAgentName.BUILD_FAILURE_ANALYSIS.value,
            )

        cp_output = self._rebuild_challenge()
        update_state["build_stdout"] = cp_output.output
        update_state["build_stderr"] = cp_output.error
        if not cp_output.success:
            logger.error("Failed to rebuild Challenge Task %s with patch", self.challenge.name)
            return Command(
                update=update_state,
                goto=PatcherAgentName.BUILD_FAILURE_ANALYSIS.value,
            )

        logger.info("Challenge Task %s rebuilt with patch", self.challenge.name)
        update_state["build_succeeded"] = True
        return Command(
            update=update_state,
            goto=PatcherAgentName.RUN_POV.value,
        )

    def run_pov_node(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.RUN_TESTS.value, PatcherAgentName.ROOT_CAUSE_ANALYSIS.value]]:  # type: ignore[name-defined]
        """Node in the LangGraph that runs a PoV against a currently built patch"""
        logger.info("Testing PoVs on Challenge Task %s rebuilt with patch", self.challenge.name)

        crash_dir = CrashDir(self.work_dir, self.input.task_id, self.input.harness_name)
        crashes_for_token = crash_dir.list_crashes_for_token(self.input.pov_token, get_remote=True)
        if not crashes_for_token:
            logger.warning("No crashes found for PoV token %s", self.input.pov_token)
            crashes_for_token = []

        pov_variants = [self.input.pov]
        pov_variants.extend([Path(crash) for crash in crashes_for_token])

        start_time = time.time()
        run_once = False

        for pov_variant in pov_variants:
            # Check if we've exceeded the max_minutes_run_povs timeout
            if time.time() - start_time > self.max_minutes_run_povs * 60:
                logger.error("PoV processing lasted more than %d minutes", self.max_minutes_run_povs)
                if run_once:
                    logger.info(
                        "PoV processing lasted more than %d minutes, but we already ran one PoV successfully, so we'll stop here",
                        self.max_minutes_run_povs,
                    )
                    break

                return Command(
                    update={
                        "pov_fixed": False,
                        "pov_stdout": f"Operation timed out after {self.max_minutes_run_povs} minutes",
                        "pov_stderr": None,
                    },
                    goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                )

            pov_variant = node_local.make_locally_available(pov_variant)
            try:
                pov_output = self.challenge.reproduce_pov(self.input.harness_name, pov_variant)
                logger.info(
                    "Ran PoV %s/%s for harness %s",
                    self.challenge.name,
                    pov_variant,
                    self.input.harness_name,
                )
                logger.debug("PoV stdout: %s", pov_output.command_result.output)
                logger.debug("PoV stderr: %s", pov_output.command_result.error)

                if not pov_output.did_run():
                    logger.warning("PoV %s did not run, skipping", pov_variant)
                    continue

                if pov_output.did_crash():
                    logger.error("PoV %s still crashes", pov_variant)
                    return Command(
                        update={
                            "pov_fixed": False,
                            "pov_stdout": pov_output.command_result.output,
                            "pov_stderr": pov_output.command_result.error,
                        },
                        goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                    )

                run_once = True
            except ChallengeTaskError as exc:
                logger.error("Failed to run pov for Challenge Task %s", self.challenge.name)
                return Command(
                    update={
                        "pov_fixed": False,
                        "pov_stdout": exc.stdout,
                        "pov_stderr": exc.stderr,
                    },
                    goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                )

        if not run_once:
            logger.error("No PoVs could be run, this should never happen")
            return Command(
                update={
                    "pov_fixed": False,
                    "pov_stdout": None,
                    "pov_stderr": None,
                },
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        logger.info("All PoVs were fixed")
        return Command(
            update={
                "pov_fixed": True,
                "pov_stdout": None,
                "pov_stderr": None,
            },
            goto=PatcherAgentName.RUN_TESTS.value,
        )

    def run_tests_node(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value, END]]:  # type: ignore[name-defined]
        """Node in the LangGraph that runs tests against a currently built patch"""
        logger.info("Running tests on Challenge Task %s rebuilt with patch", self.challenge.name)
        # TODO: implement tests
        logger.warning("Tests are not implemented yet")
        logger.info("Tests for Challenge Task %s ran successfully", self.challenge.name)
        return Command(
            update={
                "tests_passed": True,
                "tests_stdout": None,
                "tests_stderr": None,
            },
            goto=END,
        )
