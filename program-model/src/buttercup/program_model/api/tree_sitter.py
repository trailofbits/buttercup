"""TreeSitter based code querying module"""

import logging
from dataclasses import dataclass
from pathlib import Path

from buttercup.common.challenge_task import ChallengeTask
from tree_sitter_language_pack import get_language, get_parser

logger = logging.getLogger(__name__)

QUERY_STR_C = """
(
(function_definition
    declarator: [
        (_declarator (function_declarator declarator: (identifier) @function.name))
        (function_declarator declarator: (identifier) @function.name)
    ]
    body: (compound_statement) @function.body
) @function.definition
)
"""

QUERY_STR_JAVA = """
(
(method_declaration
    name: (identifier) @function.name
    body: (block) @function.body) @function.definition
)
"""


@dataclass
class FunctionBody:
    """Class to store function body information."""

    name: str
    body: str
    start_line: int
    "Start line of the function in the file (0-based)"
    end_line: int
    "End line of the function in the file (0-based)"


@dataclass
class Function:
    """Class to store function information."""

    name: str
    bodies: list[FunctionBody]


@dataclass
class CodeTS:
    """Class to extract information about functions in a challenge project using TreeSitter."""

    challenge_task: ChallengeTask

    def __post_init__(self) -> None:
        """Initialize the CodeTS object."""
        # TODO: use the language from the challenge task
        self.parser = get_parser("c")
        self.language = get_language("c")
        query_str = QUERY_STR_C  # TODO: use the correct query based on language

        try:
            self.query = self.language.query(query_str)
        except Exception:
            raise ValueError("Query string is invalid")

    def parse_functions(self, file_path: Path) -> dict[str, Function]:
        """Parse the functions in a file and return a dictionary of function names/body"""
        code = self.challenge_task.get_source_path().joinpath(file_path).read_bytes()
        return self.parse_functions_in_code(code)

    def parse_functions_in_code(self, code: bytes) -> dict[str, Function]:
        """Parse the functions in a piece of code and return a dictionary of function names/body"""
        tree = self.parser.parse(code)
        root_node = tree.root_node

        captures = self.query.matches(root_node)
        functions: dict[str, Function] = {}

        if not captures:
            return functions

        for match in captures:
            try:
                name_node = match[1]["function.name"][0]
                body_node = match[1]["function.body"][0]
                definition_node = match[1]["function.definition"][0]
            except Exception:
                continue

            if not name_node or not body_node or not definition_node:
                continue

            function_name = code[name_node.start_byte : name_node.end_byte]
            function_definition = definition_node
            start_body = function_definition
            if (
                start_body.prev_named_sibling
                and start_body.prev_named_sibling.type == "comment"
            ):
                start_body = start_body.prev_named_sibling

            function_body_start = start_body.start_byte
            while function_body_start > 0 and code[function_body_start - 1] != 10:
                function_body_start -= 1

            function_body_end = function_definition.end_byte
            # find the end of the line for the function body
            while function_body_end < len(code) and code[function_body_end] != 10:
                function_body_end += 1

            function_code = code[function_body_start:function_body_end]
            function_body = FunctionBody(
                function_name.decode(),
                function_code.decode(),
                start_body.start_point[0],
                function_definition.end_point[0],
            )
            function = functions.setdefault(
                function_name.decode(), Function(function_name.decode(), [])
            )
            function.bodies.append(function_body)

        return functions

    def get_function_code(
        self, file_path: Path, function_name: str
    ) -> list[str] | None:
        """Get the code of a function in a file."""
        functions = self.parse_functions(file_path)
        if function_name in functions:
            return [body.body for body in functions[function_name].bodies]

        return None
