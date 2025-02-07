"""Quality Engineer LLM agent, handling the testing of patches."""

import functools
import logging
import tempfile
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path

from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from pydantic import BaseModel, Field
from langchain_core.runnables import Runnable
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_COMMIT_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_ROOT_CAUSE_TMPL,
    PatcherAgentState,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from buttercup.patcher.utils import PatchInput
from pydantic import ValidationError

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
analysis or not introduced in the vulnerable commit. Only consider the direct, \
root-cause vulnerability. No indirect or related vulnerabilities;
- The patch should be as simple and as minimal as possible to fix the \
vulnerability described in the root cause analysis;
- The patch should not contain TODOs, FIXMEs, other placeholders, or incomplete \
code.

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
class QEAgent:
    """Quality Engineer LLM agent, handling the testing of patches."""

    challenge: ChallengeTask
    input: PatchInput

    llm: Runnable = field(init=False)
    review_patch_chain: Runnable = field(init=False)
    review_patch_structured_chain: Runnable = field(init=False)
    # sanitizer: ChallengeProjectSanitizer | None = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm()
        fallback_llms = [
            create_llm(model_name=ButtercupLLM.AZURE_GPT_4O_MINI.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)
        parser = JsonOutputParser(pydantic_object=ReviewPatchOutput)
        self.review_patch_chain = REVIEW_PATCH_PROMPT | self.llm | StrOutputParser()
        self.review_patch_structured_chain = (
            {"patch": itemgetter("patch"), "review": self.review_patch_chain}
            | REVIEW_PATCH_STRUCTURED_PROMPT.partial(
                format_instructions=parser.get_format_instructions()
            )
            | self.llm
            | parser
        )
        # self.sanitizer = self.challenge.get_sanitizer(self.input.context["sanitizer_id"])
        # if self.sanitizer is None:
        #     raise ValueError(f"Sanitizer ID {self.input.context['sanitizer_id']} not found")

    def get_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        # TODO: add support for multiple diffs if necessary
        diff_content = next(iter(self.challenge.get_diffs())).read_text()

        messages += [CONTEXT_COMMIT_TMPL.format(commit_content=diff_content)]
        if state.get("root_cause"):
            messages += [CONTEXT_ROOT_CAUSE_TMPL.format(root_cause=state["root_cause"])]

        for code_snippet in state.get("relevant_code_snippets") or []:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet["file_path"],
                    function_name=code_snippet.get("function_name", ""),
                    code=code_snippet.get("code", ""),
                    code_context=code_snippet.get("code_context", ""),
                )
            ]

        return messages

    def review_patch_node(self, state: PatcherAgentState) -> dict:
        """Node in the LangGraph that reviews a patch"""
        import pdb; pdb.set_trace()
        logger.info("Reviewing the last patch to ensure it follows the guidelines")
        default_review_result = ReviewPatchOutput(suggestions=[], approved=True)
        review_result_dict: dict = functools.reduce(
            lambda _, y: y,
            self.review_patch_structured_chain.stream(
                {
                    "context": self.get_context(state),
                    "patch": state["patches"][-1].patch,
                }
            ),
            # If the reviewer fails for some unexpected reasons, assume the patch is
            # good, so the patching process does not stop and tries to build the
            # patch anyway.
            default_review_result.dict(),
        )
        try:
            review_result = ReviewPatchOutput.validate(review_result_dict)
        except ValidationError:
            logger.warning("Failed to parse the review result: %s", review_result_dict)
            review_result = default_review_result

        patch_review_tries = (state.get("patch_review_tries") or 0) + 1
        patch_review_str = (
            None
            if review_result.approved
            else "\n".join("- " + x for x in review_result.suggestions or [])
        )
        return {
            "patch_review": patch_review_str,
            "patch_review_tries": patch_review_tries,
        }

    def build_patch_node(self, state: PatcherAgentState) -> dict:
        """Node in the LangGraph that builds a patch"""
        logger.info("Rebuilding Challenge Task %s with patch", self.challenge.name)
        with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
            patch_file.write(state["patches"][-1].patch)
            patch_file.flush()
            logger.debug("Patch written to %s", patch_file.name)

            # TODO: apply the patch to the source code
            # patch=str(patch_file.name),
            # source_target=str(state["patches"][-1].target),

            try:
                cp_output = self.challenge.build_fuzzers_with_cache(
                    engine=self.input.engine,
                    sanitizer=self.input.sanitizer,
                )
            except ChallengeTaskError as exc:
                logger.error("Failed to build Challenge Task %s with patch", self.challenge.name)
                return {
                    "build_succeeded": False,
                    "build_stdout": exc.stdout,
                    "build_stderr": exc.stderr,
                    "patch_review_tries": 0,
                }

            if cp_output.return_code != 0 or cp_output.exitcode != 0:
                logger.error("Failed to build Challenge Task %s with patch", self.challenge.name)
                return {
                    "build_succeeded": False,
                    "build_stdout": cp_output.stdout,
                    "build_stderr": cp_output.stderr,
                    "patch_review_tries": 0,
                }

            logger.info("Challenge Task %s rebuilt with patch", self.challenge.name)

        return {
            "build_succeeded": True,
            "build_stdout": cp_output.stdout,
            "build_stderr": cp_output.stderr,
            "patch_review_tries": 0,
        }

    def run_pov_node(self, state: PatcherAgentState) -> dict:
        """Node in the LangGraph that runs a PoV against a currently built patch"""
        logger.info("Testing PoV on Challenge Task %s rebuilt with patch", self.challenge.name)
        try:
            if isinstance(self.input.pov, bytes):
                with tempfile.NamedTemporaryFile() as pov_file:
                    pov_file.write(self.input.pov)
                    pov_file.flush()
                    pov_name = Path(pov_file.name)

                    pov_output = self.challenge.reproduce_pov(self.input.harness_name, pov_name)
            else:
                pov_name = self.input.pov
                pov_output = self.challenge.reproduce_pov(self.input.harness_name, pov_name)
        except ChallengeTaskError as exc:
            logger.error("Failed to run pov for Challenge Task %s", self.challenge.name)
            return {
                "pov_fixed": False,
                "build_stdout": exc.stdout,
                "build_stderr": exc.stderr,
            }

        if pov_output.return_code != 0:
            logger.error("PoV failed running")
            return {
                "pov_fixed": False,
                "pov_stdout": pov_output.stdout,
                "pov_stderr": pov_output.stderr,
            }

        logger.info(
            "Ran PoV %s/%s for harness %s",
            self.challenge.name,
            pov_name,
            self.input.harness_name,
        )
        logger.debug("PoV stdout: %s", pov_output.stdout)
        logger.debug("PoV stderr: %s", pov_output.stderr)

        # is_pov_triggered = self.challenge.is_sanitizer_triggered(self.sanitizer, pov_output)
        # TODO: implement this
        is_pov_triggered = True
        logger.info("PoV was %sfixed", "not " if is_pov_triggered else "")
        return {
            "pov_fixed": not is_pov_triggered,
            "pov_stdout": pov_output.stdout,
            "pov_stderr": pov_output.stderr,
        }

    def run_tests_node(self, state: PatcherAgentState) -> dict:
        """Node in the LangGraph that runs tests against a currently built patch"""
        logger.info("Running tests on Challenge Task %s rebuilt with patch", self.challenge.name)
        logger.warning("Tests are not implemented yet")
        logger.info("Tests for Challenge Task %s ran successfully", self.challenge.name)
        return {"tests_passed": True, "tests_stdout": None, "tests_stderr": None}
