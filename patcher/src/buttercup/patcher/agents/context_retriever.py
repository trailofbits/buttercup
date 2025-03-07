"""Agent that retrieves code snippets from the project."""

import logging
import re
from dataclasses import dataclass, field

from langchain_core.runnables import Runnable
from langchain_core.prompts import ChatPromptTemplate
from buttercup.patcher.agents.common import PatcherAgentBase, ContextRetrieverState, ContextCodeSnippet, CodeSnippetKey
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from langgraph.types import Command

import subprocess
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from buttercup.program_model.api.tree_sitter import CodeTS

logger = logging.getLogger(__name__)

SYSTEM_TMPL = """You are a software engineer. Your job is to retrieve the code snippets requested by the user.
You must use the tools provided to you to retrieve the code snippets.

Do not stop until you have retrieved the code definition of the function.
Use `get_function_definition` as the last tool in your chain of calls to actually retrieve the code definition.
"""

RECURSION_LIMIT = 20

MESSAGES = ChatPromptTemplate.from_messages(
    [("human", "Please retrieve the code snippet for {file_path} | {function_name}")]
)


@dataclass
class ContextRetrieverAgent(PatcherAgentBase):
    """Agent that retrieves code snippets from the project."""

    llm: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm()
        fallback_llms = [
            create_llm(model_name=ButtercupLLM.OPENAI_GPT_4O_MINI.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

    def _parse_code_snippet_msg(self, msg: str) -> tuple[str, str, str]:
        """Parse the code snippet message."""
        # Extract code part from the message using regex
        code_pattern = re.compile(r"File path:.*?\nIdentifier:.*?\nCode:\n(.*?)$", re.DOTALL)
        code_match = code_pattern.search(msg)
        if code_match:
            code_block_pattern = re.compile(r"```(?:[a-z]+)?\s*(.*?)\s*```", re.DOTALL)
            code_block_match = code_block_pattern.search(code_match.group(1))
            if code_block_match:
                # Remove the code block markers
                msg = code_block_match.group(1).strip()
            else:
                # If we can't find the code block, just return the whole part after "Code:"
                msg = code_match.group(1).strip()

        return msg

    def retrieve_context(self, state: ContextRetrieverState) -> Command:
        """Retrieve the context for the diff analysis."""
        logger.info("Retrieving the context for the diff analysis in Challenge Task %s", self.challenge.name)
        logger.debug("Code snippet requests: %s", state.code_snippet_requests)

        code_ts = CodeTS(self.challenge)

        @tool
        def ls(path: str) -> str:
            """List the files in the given path in the project's source directory."""
            path = self.rebase_src_path(path)

            logger.info("Listing files in %s", path)
            return subprocess.check_output(["ls", "-l", path], cwd=self.challenge.get_source_path()).decode("utf-8")

        @tool
        def grep(path: str, pattern: str) -> str:
            """Grep for a string in a file. Prefer using this tool over cat."""
            path = self.rebase_src_path(path)

            logger.info("Searching for %s in %s", pattern, path)
            return subprocess.check_output(["grep", "-nr", pattern, path], cwd=self.challenge.get_source_path()).decode(
                "utf-8"
            )

        @tool
        def cat(path: str) -> str:
            """Read the contents of a file. Use this tool only if grep and get_lines do not work as it might return a large amount of text."""
            path = self.rebase_src_path(path)

            logger.info("Reading contents of %s", path)
            return self.challenge.get_source_path().joinpath(path).read_text()

        @tool
        def get_lines(path: str, start: int, end: int) -> str:
            """Get a range of lines from a file. Prefer using this tool over cat."""
            path = self.rebase_src_path(path)

            logger.info("Getting lines %d-%d of %s", start, end, path)
            return "\n".join(self.challenge.get_source_path().joinpath(path).read_text().splitlines()[start:end])

        @tool(return_direct=True)
        def get_function_definition(path: str, function_name: str) -> str:
            """Get the definition of a function in a file. You MUST use this tool as the last call in your chain of calls."""
            path = self.rebase_src_path(path)

            logger.info("Getting definition of %s in %s", function_name, path)
            bodies = code_ts.get_function_code(path, function_name)
            if not bodies:
                return "No definition found for function"

            # TODO: allow for multiple bodies
            return bodies[0]

        tools = [ls, grep, get_lines, cat, get_function_definition]
        agent = create_react_agent(
            self.llm,
            tools,
            prompt=SYSTEM_TMPL,
        )

        res = []
        for request in state.code_snippet_requests:
            logger.info("Retrieving code snippet for %s | %s", request.file_path, request.identifier)
            messages = MESSAGES.invoke({"file_path": request.file_path, "function_name": request.identifier})
            snippet = agent.invoke({"messages": messages.to_messages()}, {"recursion_limit": RECURSION_LIMIT})
            logger.info("Code snippet retrieved for %s | %s", request.file_path, request.identifier)
            if not snippet["messages"]:
                raise RuntimeError("No messages returned from the agent")

            msg = snippet["messages"][-1].content
            code = self._parse_code_snippet_msg(msg)

            res.append(
                ContextCodeSnippet(
                    key=CodeSnippetKey(
                        file_path=self.rebase_src_path(request.file_path),
                        identifier=request.identifier,
                    ),
                    code=code,
                    code_context="",
                )
            )

        return Command(
            update={
                "relevant_code_snippets": res,
            },
            goto=state.prev_node,
        )
