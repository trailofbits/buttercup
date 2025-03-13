"""TreeSitter based code querying module"""

import logging
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from enum import Enum

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.utils.common import Function, FunctionBody
from tree_sitter_language_pack import get_language, get_parser
from buttercup.common.project_yaml import ProjectYaml

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

QUERY_STR_TYPES_C = """
(
[
  (struct_specifier
    name: _ @type.name
    body: (field_declaration_list)) @type.definition

  (union_specifier
    name: _ @type.name
    body: (field_declaration_list)) @type.definition

  (enum_specifier
    name: _ @type.name
    body: (enumerator_list)) @type.definition

  (type_definition
    type: (type_specifier) @type.original_type
    declarator: (_) @type.name) @type.definition

  (preproc_def
    name: (identifier) @type.name
    value: (preproc_arg) @type.value) @type.definition
]
)
"""

QUERY_STR_TYPES_JAVA = """
(
[
  (class_declaration
    name: (identifier) @type.name) @type.definition

  (interface_declaration
    name: (identifier) @type.name) @type.definition

  (enum_declaration
    name: (identifier) @type.name) @type.definition

  (record_declaration
    name: (identifier) @type.name) @type.definition

  (annotation_type_declaration
    name: (identifier) @type.name) @type.definition
]
)
"""


@dataclass
class TypeDefinitionType(str, Enum):
    """Enum to store type definition type."""

    STRUCT = "struct"
    UNION = "union"
    ENUM = "enum"
    TYPEDEF = "typedef"
    PREPROC_TYPE = "preproc_type"


@dataclass
class TypeDefinition:
    """Class to store type definition information."""

    name: str
    type: TypeDefinitionType
    definition: str


@dataclass
class CodeTS:
    """Class to extract information about functions in a challenge project using TreeSitter."""

    challenge_task: ChallengeTask

    def __post_init__(self) -> None:
        """Initialize the CodeTS object."""
        project_yaml = ProjectYaml(
            self.challenge_task, self.challenge_task.task_meta.project_name
        )
        if project_yaml.language == "c" or project_yaml.language == "c++":
            self.parser = get_parser("c")
            self.language = get_language("c")
            query_str = QUERY_STR_C
            types_query_str = QUERY_STR_TYPES_C
        elif project_yaml.language == "java":
            self.parser = get_parser("java")
            self.language = get_language("java")
            query_str = QUERY_STR_JAVA
            types_query_str = QUERY_STR_TYPES_JAVA
        else:
            raise ValueError(f"Unsupported language: {project_yaml.language}")

        self.get_functions_in_code = lru_cache(maxsize=1000)(self.get_functions_in_code)
        self.get_function = lru_cache(maxsize=1000)(self.get_function)

        try:
            self.query = self.language.query(query_str)
            self.query_types = self.language.query(types_query_str)
        except Exception:
            raise ValueError("Query string is invalid")

    def get_functions(self, file_path: Path) -> dict[str, Function]:
        """Parse the functions in a file and return a dictionary of function names/body"""
        code = self.challenge_task.task_dir.joinpath(file_path).read_bytes()
        return self.get_functions_in_code(code, file_path)

    def get_functions_in_code(
        self, code: bytes, file_path: Path
    ) -> dict[str, Function]:
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
                function_code.decode(),
                start_body.start_point[0],
                function_definition.end_point[0],
            )
            function = functions.setdefault(
                function_name.decode(), Function(function_name.decode(), file_path)
            )
            function.bodies.append(function_body)

        return functions

    def get_function(self, function_name: str, file_path: Path) -> Function | None:
        """Get the code of a function in a file."""
        functions = self.get_functions(file_path)
        return functions.get(function_name)

    def parse_types_in_code(self, file_path: Path) -> dict[str, TypeDefinition]:
        """Parse the definition of a type in a piece of code."""
        logger.debug("Parsing types in code")
        code = self.challenge_task.task_dir.joinpath(file_path).read_bytes()
        tree = self.parser.parse(code)
        root_node = tree.root_node

        captures = self.query_types.matches(root_node)
        if not captures:
            return {}

        res: dict[str, TypeDefinition] = {}
        for match in captures:
            try:
                name_node = match[1]["type.name"][0]
                definition_node = match[1]["type.definition"][0]
            except Exception:
                continue

            if not name_node or not definition_node:
                continue

            # Walk back to include any comments right before the definition
            start_byte = definition_node.start_byte
            prev_node = definition_node.prev_named_sibling
            if prev_node and prev_node.type == "comment":
                start_byte = prev_node.start_byte

            # Make sure we start at the beginning of the line
            while start_byte > 0 and code[start_byte - 1] != 10:  # newline char
                start_byte -= 1

            type_definition = code[start_byte : definition_node.end_byte].decode()
            name = name_node.text.decode()
            logger.debug("Type name: %s", name)
            logger.debug("Type definition: %s", type_definition)

            # Determine the type based on the node type
            type_def_type = TypeDefinitionType.STRUCT  # default
            if definition_node.type == "struct_specifier":
                type_def_type = TypeDefinitionType.STRUCT
            elif definition_node.type == "union_specifier":
                type_def_type = TypeDefinitionType.UNION
            elif definition_node.type == "enum_specifier":
                type_def_type = TypeDefinitionType.ENUM
            elif definition_node.type == "type_definition":
                type_def_type = TypeDefinitionType.TYPEDEF
            elif definition_node.type == "preproc_def":
                type_def_type = TypeDefinitionType.PREPROC_TYPE
            else:
                continue  # Skip this define as it doesn't look like a type

            res[name] = TypeDefinition(
                name=name,
                type=type_def_type,
                definition=type_definition,
            )

        return res
