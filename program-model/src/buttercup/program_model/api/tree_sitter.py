"""TreeSitter based code querying module"""

import logging
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.utils.common import (
    Function,
    FunctionBody,
    TypeDefinition,
    TypeDefinitionType,
)
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
# This query matches C function definitions:
# 1. Matches a function_definition node
# 2. Looks for a declarator that can be either:
#    - A nested _declarator with function_declarator and identifier (for complex declarations)
#    - A direct function_declarator with identifier (for simple declarations)
# 3. Captures the function name with @function.name
# 4. Captures the function body (compound_statement) with @function.body
# 5. Captures the entire function definition with @function.definition

QUERY_STR_JAVA = """
(method_declaration
  (modifiers)*
  (type_parameters)?
  [
    (type_identifier)
    (void_type)
  ]?
  name: (identifier) @function.name
  (formal_parameters)
  (throws)?
  body: (block) @function.body) @function.definition
"""
# This query matches Java method declarations:
# 1. Matches a method_declaration node
# 2. (modifiers)* - Matches zero or more modifiers (public, private, static, etc.)
# 3. (type_parameters)? - Optional generic type parameters (e.g., <T>)
# 4. [ ... ]? - Optional return type which can be either:
#    - type_identifier (e.g., String, int)
#    - void_type (for void methods)
# 5. name: (identifier) @function.name - Captures the method name
# 6. (formal_parameters) - Matches the method parameters
# 7. (throws)? - Optional throws clause
# 8. body: (block) @function.body - Captures the method body
# 9. @function.definition - Captures the entire method declaration

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
# This query matches C type definitions:
# 1. struct_specifier - Matches struct definitions with:
#    - name captured with @type.name
#    - body containing field declarations
# 2. union_specifier - Matches union definitions with:
#    - name captured with @type.name
#    - body containing field declarations
# 3. enum_specifier - Matches enum definitions with:
#    - name captured with @type.name
#    - body containing enumerator list
# 4. type_definition - Matches typedef statements with:
#    - original type captured with @type.original_type
#    - new type name captured with @type.name
# 5. preproc_def - Matches preprocessor type definitions with:
#    - name captured with @type.name
#    - value captured with @type.value

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
# This query matches Java type definitions:
# 1. class_declaration - Matches class definitions with:
#    - name captured with @type.name
# 2. interface_declaration - Matches interface definitions with:
#    - name captured with @type.name
# 3. enum_declaration - Matches enum definitions with:
#    - name captured with @type.name
# 4. record_declaration - Matches record definitions (Java 14+) with:
#    - name captured with @type.name
# 5. annotation_type_declaration - Matches annotation type definitions with:
#    - name captured with @type.name
# 6. type_parameter - Matches generic type parameters with:
#    - name captured with @type.name


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
        elif project_yaml.language == "jvm":
            self.parser = get_parser("java")
            self.language = get_language("java")
            query_str = QUERY_STR_JAVA
            types_query_str = QUERY_STR_TYPES_JAVA
        else:
            raise ValueError(f"Unsupported language: {project_yaml.language}")

        self.get_functions_in_code = lru_cache(maxsize=1000)(self.get_functions_in_code)  # type: ignore [method-assign]
        self.get_function = lru_cache(maxsize=1000)(self.get_function)  # type: ignore [method-assign]

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
            node, capture_name = match
            if "function.name" in capture_name.keys():
                name_node = capture_name["function.name"][0]
            if "function.body" in capture_name.keys():
                body_node = capture_name["function.body"][0]  # noqa:F841
            if "function.definition" in capture_name.keys():
                definition_node = capture_name["function.definition"][0]

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

            # Convert start and end points to 1-based line numbers.
            # We do this because the stacktrace will be 1-based, so it's best to keep everything consistent.
            start_line = start_body.start_point[0] + 1
            end_line = function_definition.end_point[0] + 1

            function_code = code[function_body_start:function_body_end]
            function_body = FunctionBody(
                function_code.decode(),
                start_line,
                end_line,
            )
            function = functions.setdefault(
                function_name.decode(),
                Function(function_name.decode(), file_path),
            )
            function.bodies.append(function_body)

        logger.debug("Found %d functions in %s", len(functions), file_path)

        return functions

    def get_function(self, function_name: str, file_path: Path) -> Function | None:
        """Get the code of a function in a file."""
        functions = self.get_functions(file_path)
        return functions.get(function_name)

    def parse_types_in_code(
        self, file_path: Path, typename: str | None = None, fuzzy: bool | None = False
    ) -> dict[str, TypeDefinition]:
        """Parse the definition of a type in a piece of code."""
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

            # Walk back to include any comments right before the definition
            start_byte = definition_node.start_byte
            prev_node = definition_node.prev_named_sibling
            if prev_node and prev_node.type == "comment":
                start_byte = prev_node.start_byte

            # Make sure we start at the beginning of the line
            while start_byte > 0 and code[start_byte - 1] != 10:  # newline char
                start_byte -= 1

            type_definition = code[start_byte : definition_node.end_byte].decode()
            if name_node.text is None:
                logger.warning("Type %s is None for %s", name_node, file_path)
                continue
            name = name_node.text.decode()
            # NOTE(boyan): here we strip any unexpected indirection that TS might leave.
            # It is the case for example with the following from libjpeg-turbo:
            # typedef struct jpeg_decompress_struct * j_decompress_ptr;
            # Where the name is "*j_decompress_ptr" but the actual type name
            # doesn't contain the star.
            name = name.lstrip("*")
            if typename and not fuzzy and name != typename:
                continue
            if typename and fuzzy and typename not in name:
                continue

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
            elif definition_node.type == "class_declaration":
                type_def_type = TypeDefinitionType.CLASS
            else:
                continue  # Skip this define as it doesn't look like a type

            res[name] = TypeDefinition(
                name=name,
                type=type_def_type,
                definition=type_definition,
                definition_line=definition_node.start_point[0]
                + 1,  # Convert to 1-based line number, since the stacktrace is 1-based
                file_path=file_path,
            )

        logger.debug("Found %d types in %s", len(res), file_path)

        return res
