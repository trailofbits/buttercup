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
from buttercup.common.project_yaml import ProjectYaml, Language
import re
from typing import Any

logger = logging.getLogger(__name__)

QUERY_STR_C = """
(
[
  (function_definition
     declarator: [
         (_declarator (function_declarator declarator: (identifier) @function.name))
         (function_declarator declarator: (identifier) @function.name)
     ]
     body: (compound_statement) @function.body
  ) @function.definition

  (
    (expression_statement
      (call_expression
        function: (identifier) @macro.name
        arguments: (argument_list
          (identifier) @type
          (identifier) @function.name
          (parenthesized_expression (_) @function.arguments)
          (identifier) @attributes
        )
      ) @macro.call
    )
    (compound_statement) @function.body
  ) @function.definition
]
)
"""
# This query matches C two types of function definitions that use PNG_FUNCTION macro:
# 1. Matches a function_definition node
# 2. Looks for a declarator that can be either:
#    - A nested _declarator with function_declarator and identifier (for complex declarations)
#    - A direct function_declarator with identifier (for simple declarations)
# 3. Captures the function name with @function.name
# 4. Captures the function body (compound_statement) with @function.body
# 5. Captures the entire function definition with @function.definition

# 1. Matches an expression_statement containing a call_expression
# 2. The call_expression must be to PNG_FUNCTION with four arguments:
#    - First argument: type identifier
#    - Second argument: function name identifier
#    - Third argument: parenthesized expression containing function parameters
#    - Fourth argument: attributes identifier
# 3. Captures the macro call with @macro.call
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
    (identifier) @type.name
    (preproc_arg)? @type.value) @type.definition

  (preproc_function_def
    (identifier) @type.name
    (preproc_arg)? @type.value) @type.definition
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
# 6. preproc_function_def - Matches preprocessor function definitions with:
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


QUERY_STR_CLASS_MEMBERS_JAVA = """;; Match field declarations without explicit modifiers
(
  (class_declaration
    body: (class_body 
      (field_declaration
        type: (_) @type
        declarator: (variable_declarator
          name: (_) @name
          value: (_)? @value)
      ) @field_declaration
    )
  )
)

;; Match method declarations without explicit modifiers
(
  (class_declaration
    body: (class_body 
      (method_declaration
        type_parameters: (_)? @method_type_params
        type: (_) @method_return_type
        name: (_) @method_name
        parameters: (formal_parameters) @method_params
        body: (_)? @method_body
      ) @method_declaration
    )
  )
)

;; Match interface method declarations (without body)
(
  (interface_declaration
    body: (interface_body
      (method_declaration
        type_parameters: (_)? @method_type_params
        type: (_) @method_return_type
        name: (_) @method_name
        parameters: (formal_parameters) @method_params
        body: (_)? @method_body
      ) @method_declaration
    )
  )
)"""


@dataclass
class CodeTS:
    """Class to extract information about functions in a challenge project using TreeSitter."""

    challenge_task: ChallengeTask

    def __post_init__(self) -> None:
        """Initialize the CodeTS object."""
        self.project_yaml = ProjectYaml(
            self.challenge_task, self.challenge_task.task_meta.project_name
        )
        if self.project_yaml.unified_language == Language.C:
            self.parser = get_parser("c")
            self.language = get_language("c")
            query_str = QUERY_STR_C
            types_query_str = QUERY_STR_TYPES_C
            query_class_members = None
        elif self.project_yaml.unified_language == Language.JAVA:
            self.parser = get_parser("java")
            self.language = get_language("java")
            query_str = QUERY_STR_JAVA
            types_query_str = QUERY_STR_TYPES_JAVA
            query_class_members = QUERY_STR_CLASS_MEMBERS_JAVA
        else:
            raise ValueError(f"Unsupported language: {self.project_yaml.language}")

        self.get_functions_in_code = lru_cache(maxsize=1000)(self.get_functions_in_code)  # type: ignore [method-assign]
        self.get_function = lru_cache(maxsize=1000)(self.get_function)  # type: ignore [method-assign]

        try:
            self.query = self.language.query(query_str)
            self.query_types = self.language.query(types_query_str)
            self.query_class_members = (
                self.language.query(query_class_members)
                if query_class_members
                else None
            )
        except Exception:
            raise ValueError("Query string is invalid")

        self.preprocess_keywords = ["ifdef", "ifndef", "if", "else", "elif", "endif"]
        self.preprocess_regex = [
            r"^#\s*{kw}\s*".format(kw=kw) for kw in self.preprocess_keywords
        ]

    def get_functions(self, file_path: Path) -> dict[str, Function]:
        """Parse the functions in a file and return a dictionary of function names/body"""
        code = self.challenge_task.task_dir.joinpath(file_path).read_bytes()
        return self.get_functions_in_code(code, file_path)

    def _get_code_no_preproc(self, code: bytes) -> bytes:
        """Remove preprocessor directives from the code"""
        return (b"\n").join(
            [
                x
                if not any(
                    re.match(pattern, x.decode()) for pattern in self.preprocess_regex
                )
                else b"/" * len(x)
                for x in code.splitlines()
            ]
        )

    def get_functions_in_code(
        self, code: bytes, file_path: Path
    ) -> dict[str, Function]:
        """Parse the functions in a piece of code and return a dictionary of function names/body"""
        if self.project_yaml.unified_language == Language.C:
            code_no_preproc = self._get_code_no_preproc(code)
            tree = self.parser.parse(code_no_preproc)
        else:
            tree = self.parser.parse(code)

        root_node = tree.root_node

        captures = self.query.matches(root_node)
        functions: dict[str, Function] = {}

        if not captures:
            return functions

        for match in captures:
            node, capture_name = match
            try:
                definition_node = capture_name["function.definition"][0]
                name_node = capture_name["function.name"][0]
                body_node = capture_name["function.body"][0]
                is_macro = True if "macro.call" in capture_name else False
            except Exception:
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
            while function_body_start > 0 and code[function_body_start - 1] != ord(
                "\n"
            ):
                function_body_start -= 1

            function_body_end = function_definition.end_byte
            if is_macro:
                function_body_end = body_node.end_byte

            # find the end of the line for the function body
            while function_body_end < len(code) and code[function_body_end] != ord(
                "\n"
            ):
                function_body_end += 1

            # Convert start and end points to 1-based line numbers.
            # We do this because the stacktrace will be 1-based, so it's best to keep everything consistent.
            start_line = start_body.start_point[0] + 1
            end_line = function_definition.end_point[0] + 1
            if is_macro:
                end_line = body_node.end_point[0] + 1

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
            # If the function is a macro, we shouldn't continue. The tree-sitter
            # query picks up more than just the function body.
            if is_macro and len(function.bodies) > 0:
                continue
            if function_body not in function.bodies:
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

        if self.project_yaml.unified_language == Language.C:
            code_no_preproc = self._get_code_no_preproc(code)
            tree = self.parser.parse(code_no_preproc)
        else:
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
            while start_byte > 0 and code[start_byte - 1] != ord("\n"):
                start_byte -= 1

            # Make sure we end at the end of the line, but take into account '\' for escaped newlines
            end_byte = definition_node.end_byte

            type_definition = code[start_byte:end_byte].decode()
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
            elif definition_node.type == "preproc_function_def":
                type_def_type = TypeDefinitionType.PREPROC_FUNCTION
            elif definition_node.type == "class_declaration":
                type_def_type = TypeDefinitionType.CLASS
            elif definition_node.type == "interface_declaration":
                type_def_type = TypeDefinitionType.CLASS
            else:
                logger.debug(
                    f"Unknown type definition node type: {definition_node.type}"
                )
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

    def find_node_and_ancestors(self, code: bytes, target_name: str) -> None:
        """
        Used for debugging.

        Recursively walk the tree to find a node and print its ancestors.

        Args:
            code: The code to parse
            target_name: The name of the node to find
        """
        tree = self.parser.parse(code)
        root_node = tree.root_node

        def walk(node: Any) -> bool:
            # Check current node
            if node.type == "identifier" and node.text.decode() == target_name:
                logger.debug("Found target node: %s", node.text.decode())

                # Print parent
                parent = node.parent
                if parent:
                    logger.debug("Parent: %s - %s", parent.type, parent.text.decode())

                    # Print grandparent
                    grandparent = parent.parent
                    if grandparent:
                        logger.debug(
                            "Grandparent: %s - %s",
                            grandparent.type,
                            grandparent.text.decode(),
                        )

                    # Print grandparent's siblings
                    siblings = grandparent.parent.children
                    for sibling in siblings:
                        logger.debug(
                            "Sibling    : %s - %s", sibling.type, sibling.text.decode()
                        )
                        # Print sibling's children
                        for child in sibling.children:
                            logger.debug(
                                "\tChild      : %s - %s",
                                child.type,
                                child.text.decode(),
                            )

                            if child.type == "expression_statement":
                                child_children = child.children
                                for child_child in child_children:
                                    logger.debug(
                                        "\t\tChild      : %s - %s",
                                        child_child.type,
                                        child_child.text.decode(),
                                    )

                    # Print great-grandparents
                    great_grandparent = grandparent.parent
                    if great_grandparent:
                        logger.debug(
                            "Great-grandparent: %s - %s",
                            great_grandparent.type,
                            great_grandparent.text.decode(),
                        )

                    # Print great-grandparent's siblings
                    siblings = great_grandparent.parent.children
                    for sibling in siblings:
                        logger.debug("Sibling    : %s", sibling.type)
                return True

            # Recursively check children
            for child in node.children:
                if walk(child):
                    return True
            return False

        walk(root_node)

    def get_field_type_name(
        self, type_definition: bytes, field_name: str
    ) -> str | None:
        """
        Get the type of a field of a type definition
        """
        if self.query_class_members is None:
            return None
        self.parser.parse(type_definition)
        root_node = self.parser.parse(type_definition).root_node
        captures = self.query_class_members.matches(root_node)
        for match in captures:
            if match[0] != 0:  # Skip if not a field declaration
                continue
            try:
                name = match[1]["name"][0].text.decode()  # type: ignore[union-attr]
                if name == field_name:
                    return match[1]["type"][0].text.decode()  # type: ignore[union-attr]
            except AttributeError:
                continue
        return None

    def get_method_return_type_name(
        self, type_definition: bytes, method_name: str
    ) -> str | None:
        """
        Get the return type of a method of a type definition
        """
        if self.query_class_members is None:
            return None
        self.parser.parse(type_definition)
        root_node = self.parser.parse(type_definition).root_node
        captures = self.query_class_members.matches(root_node)
        for match in captures:
            # Skip if not a method declaration from a class (1) or interface (2)
            if match[0] not in [1, 2]:
                continue
            try:
                name = match[1]["method_name"][0].text.decode()  # type: ignore[union-attr]
                if name == method_name:
                    return match[1]["method_return_type"][0].text.decode()  # type: ignore[union-attr]
            except AttributeError:
                continue
        return None
