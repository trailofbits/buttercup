"""Codequery based code querying module"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from typing import ClassVar

import rapidfuzz
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from buttercup.program_model.api.fuzzy_imports_resolver import (
    FuzzyCImportsResolver,
    FuzzyJavaImportsResolver,
)
from buttercup.program_model.api.tree_sitter import CodeTS
from buttercup.program_model.utils.common import (
    Function,
    TypeDefinition,
    TypeUsageInfo,
)

logger = logging.getLogger(__name__)


CONTAINER_SRC_DIR: str = "container_src_dir"

# C/C++ Projects
C_CPP_EXTENSIONS = [
    "*.c",
    "*.cpp",
    "*.cxx",
    "*.cc",
    "*.C",
    "*.c++",
    "*.h",
    "*.hpp",
    "*.hxx",
    "*.hh",
    "*.H",
    "*.h++",
    "*.inc",
    "*.inl",
    "*.ipp",
    "*.tpp",
    "*.y",
    "*.yy",
    "*.l",
    "*.ll",
    "*.lex",
    "*.yacc",
    "*.in",
    "*.m",
    "*.mm",
    "*.cu",
    "*.cuh",
]

# Java Projects
JAVA_EXTENSIONS = [
    "*.java",
    "*.jsp",
    "*.jspx",
    "*.tag",
    "*.jspf",
    "*.properties",
    "*.gradle",
    "*.kt",
    "*.scala",
    "*.groovy",
    "*.aj",
]


@dataclass
class CQSearchResult:
    """Result of the cqsearch command."""

    value: str
    file: Path
    line: int
    body: str

    @classmethod
    def from_line(cls, line: str) -> CQSearchResult | None:
        """Parse a line of the cqsearch output into a CQSearchResult."""
        try:
            value, file_line, body = line.split("\t", 2)
            file_str, line = file_line.split(":", 1)
        except ValueError:
            logger.warning("Invalid cqsearch line: %s", line)
            return None

        # Rebase the file path from the challenge task base dir.
        # This is needed because the task-dir part might be different from what
        # was originally used to create the db.
        file: Path = Path(file_str)
        if CONTAINER_SRC_DIR not in file.parts:
            logger.warning("File %s is not in the container source dir", file_str)
            return None

        container_src_dir_idx = file.parts.index(CONTAINER_SRC_DIR)
        assert container_src_dir_idx > 0
        file = Path(*file.parts[container_src_dir_idx:])

        try:
            line_number = int(line)
        except ValueError:
            logger.warning("Invalid line number: %s", line)
            line_number = 0

        return cls(value, file, line_number, body)


@dataclass
class CodeQuery:
    """Class to extract context about a challenge project with CodeQuery.

    This class indexes the codebase as it appears from within the oss-fuzz
    container used for fuzzing. All returned paths are absolute paths in the
    container (e.g. /src/my-source/my-file.c).
    """

    challenge: ChallengeTask
    ts: CodeTS = field(init=False)
    imports_resolver: FuzzyCImportsResolver | FuzzyJavaImportsResolver | None = field(init=False)

    CSCOPE_FILES: ClassVar[str] = "cscope.files"
    CSCOPE_OUT: ClassVar[str] = "cscope.out"
    TAGS: ClassVar[str] = "tags"
    CODEQUERY_DB: ClassVar[str] = "codequery.db"

    def __post_init__(self) -> None:
        """Initialize the CodeQuery object."""
        self._verify_requirements()
        self.ts = CodeTS(self.challenge)
        language = self._get_project_language()
        if language in [Language.C, Language.CPP]:
            self.imports_resolver = FuzzyCImportsResolver(self._get_container_src_dir())
        elif language == Language.JAVA:
            self.imports_resolver = FuzzyJavaImportsResolver(self.challenge, self)
        else:
            self.imports_resolver = None

        if self._is_already_indexed():
            logger.debug("CodeQuery DB already exists in %s.", self.challenge.task_dir)
            return

        if self.challenge.local_task_dir is None:
            raise ValueError("Challenge Task is read-only, cannot perform this operation")

        self._create_codequery_db()
        logger.debug("CodeQuery DB created successfully.")

    def _verify_requirements(self) -> None:
        """Verify that the required commands are installed."""
        required_commands = ["cscope", "ctags", "cqmakedb", "cqsearch"]
        missing_commands = []

        for command in required_commands:
            if shutil.which(command) is None:
                missing_commands.append(command)

        if missing_commands:
            logger.fatal(
                "Missing commands: %s. Please install the 'codequery' package.",
                ", ".join(missing_commands),
            )
            raise RuntimeError("No code query package")

    def _get_project_language(self) -> Language:
        project_yaml = ProjectYaml(self.challenge, self.challenge.task_meta.project_name)
        return project_yaml.unified_language

    def _is_already_indexed(self) -> bool:
        """Check if the codequery database already exists."""
        return (
            self.challenge.task_dir.joinpath(CONTAINER_SRC_DIR).exists()
            and self._get_container_src_dir().joinpath(self.CSCOPE_FILES).exists()
            and self._get_container_src_dir().joinpath(self.CSCOPE_OUT).exists()
            and self._get_container_src_dir().joinpath(self.CODEQUERY_DB).exists()
            and self._get_container_src_dir().joinpath(self.TAGS).exists()
        )

    def _get_container_src_dir(self) -> Path:
        """Get the container source directory."""
        return Path(self.challenge.task_dir.joinpath(CONTAINER_SRC_DIR))

    def _copy_src_from_container(self) -> None:
        """Build and copy the /src directory from the container to the challenge task directory."""
        container_name = self.challenge.task_meta.task_id + "_" + str(uuid.uuid4())[:16]
        res = self.challenge.build_fuzzers_save_containers(container_name)
        if not res.success:
            raise RuntimeError("Failed to build fuzzers.")

        src_dst = self._get_container_src_dir()
        src_dst.mkdir(parents=True, exist_ok=True)
        try:
            command = [
                "docker",
                "cp",
                f"{container_name}:/src",
                src_dst.resolve().as_posix(),
            ]
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error("Failed to copy src from container: %s", e)
            raise RuntimeError(f"Failed to copy src from container: {e}")
        finally:
            command = [
                "docker",
                "rm",
                container_name,
            ]
            subprocess.run(command, check=True, capture_output=True)

    def _create_codequery_db(self) -> None:
        """Create the codequery database."""
        self._copy_src_from_container()

        with self._get_container_src_dir().joinpath(self.CSCOPE_FILES).open("w") as f:
            project_yaml = ProjectYaml(self.challenge, self.challenge.task_meta.project_name)
            if project_yaml.unified_language in [Language.C, Language.CPP]:
                extensions = C_CPP_EXTENSIONS
            elif project_yaml.unified_language == Language.JAVA:
                extensions = JAVA_EXTENSIONS
            else:
                raise ValueError(f"Unsupported language: {project_yaml.language}")

            # Find all files with the given extensions
            for ext in extensions:
                for file in self._get_container_src_dir().rglob(ext):
                    f.write(str(file) + "\n")

        try:
            subprocess.run(
                ["cscope", "-bkq"],
                check=False,
                cwd=self._get_container_src_dir(),
                capture_output=True,
                timeout=200,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cscope index.")

        if not self._get_container_src_dir().joinpath(self.CSCOPE_OUT).exists():
            raise RuntimeError("Failed to create cscope out.")

        try:
            subprocess.run(
                ["ctags", "--fields=+i", "-n", "-L", self.CSCOPE_FILES],
                check=False,
                cwd=self._get_container_src_dir(),
                capture_output=True,
                timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create ctags index.")

        if not self._get_container_src_dir().joinpath(self.TAGS).exists():
            raise RuntimeError("Failed to create ctags index.")

        try:
            subprocess.run(
                [
                    "cqmakedb",
                    "-s",
                    self.CODEQUERY_DB,
                    "-c",
                    self.CSCOPE_OUT,
                    "-t",
                    self.TAGS,
                    "-p",
                ],
                check=False,
                cwd=self._get_container_src_dir(),
                capture_output=True,
                timeout=2700,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cquery database.")

        if not self._get_container_src_dir().joinpath(self.CODEQUERY_DB).exists():
            raise RuntimeError("Failed to create cquery database.")

    def __repr__(self) -> str:
        return f"CodeQuery(challenge={self.challenge})"

    def _run_cqsearch(self, *args: str) -> list[CQSearchResult]:
        """Run the cqsearch command and parse the results."""
        try:
            result = subprocess.run(
                ["cqsearch", *args],
                cwd=self._get_container_src_dir(),
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to run cqsearch: {e}")

        results = [CQSearchResult.from_line(line) for line in output.splitlines()]
        return [result for result in results if result is not None]

    def _rebase_path(self, path: Path) -> Path:
        if CONTAINER_SRC_DIR not in path.parts:
            return path
        container_src_dir_idx = path.parts.index(CONTAINER_SRC_DIR)
        return Path("/", *path.parts[container_src_dir_idx + 1 :])

    def _rebase_functions_file_paths(self, functions: list[Function]) -> list[Function]:
        """Rebase the file paths of the functions to the challenge task container structure."""
        return [
            Function(
                name=function.name,
                file_path=self._rebase_path(function.file_path),
                bodies=function.bodies,
            )
            for function in functions
        ]

    def _rebase_types_file_paths(self, types: list[TypeDefinition]) -> list[TypeDefinition]:
        """Rebase the file paths of the types to the challenge task container structure."""
        return [
            TypeDefinition(
                name=td.name,
                file_path=self._rebase_path(td.file_path),
                definition=td.definition,
                definition_line=td.definition_line,
                type=td.type,
            )
            for td in types
        ]

    def _rebase_type_usages_file_paths(self, type_usages: list[TypeUsageInfo]) -> list[TypeUsageInfo]:
        """Rebase the file paths of the types to the challenge task container structure."""
        return [
            TypeUsageInfo(
                name=tu.name,
                file_path=self._rebase_path(tu.file_path),
                line_number=tu.line_number,
            )
            for tu in type_usages
        ]

    def _get_all_functions(self) -> list[CQSearchResult]:
        """Get all functions in the codebase."""
        return [f for f in self._run_cqsearch("-s", self.CODEQUERY_DB, "-p", "2", "-t", "*", "-u")]

    def _get_all_types(self) -> list[CQSearchResult]:
        """Get all symbols in the codebase."""
        return [t for t in self._run_cqsearch("-s", self.CODEQUERY_DB, "-p", "1", "-t", "*", "-u")]

    def get_functions(
        self,
        function_name: str,
        file_path: Path | None = None,
        line_number: int | None = None,
        fuzzy: bool | None = False,
        fuzzy_threshold: int = 80,
        print_output: bool = True,
    ) -> list[Function]:
        """Get the definition(s) of a function in the codebase or in a specific
        file. File paths are based on the challenge task container structure
        (e.g. /src).

        The order of the results is (1) exact matches and (2) fuzzy matches sorted in descending order of similarity.

        NOTE: Fuzzy search will be disabled if a file path is provided.
        """
        if fuzzy and file_path:
            logger.warning(
                "Fuzzy search will be disabled because file path %s was provided.",
                file_path,
            )

        # FIXME(Evan): Sometimes cscope doesn't identify a function (option 2).
        # They can be found by looking for symbols (option 1).
        results: list[CQSearchResult] = []
        flags = ["1", "2"]
        for flag in flags:
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                flag,
                "-t",
                function_name,
                "-e",
                "-u",
            ]
            if file_path:
                cqsearch_args += ["-b", file_path.as_posix()]

            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("get_functions_with_codequery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.STATIC_ANALYSIS,
                    crs_action_name="get_functions_with_codequery",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                    extra_attributes={
                        "crs.action.code.file": str(file_path) if file_path else "",
                        "crs.action.code.lines": line_number if line_number else "",
                        "crs.action.code.fuzzy": fuzzy if fuzzy else False,
                        "crs.action.code.function_name": function_name,
                    },
                )
                results.extend(self._run_cqsearch(*cqsearch_args))
                span.set_status(Status(StatusCode.OK))

        # Extended fuzzy matching
        if fuzzy and file_path is None:
            # Fuzzy match the function name against all functions in the codebase
            fuzzy_matches: list[tuple[CQSearchResult, float]] = sorted(
                [
                    (f, rapidfuzz.fuzz.ratio(function_name, f.value))
                    for f in self._get_all_functions()
                    if f.value and rapidfuzz.fuzz.ratio(function_name, f.value) > fuzzy_threshold
                ],
                key=lambda x: x[1],
                reverse=True,
            )
            fuzzy_matches_extracted: list[CQSearchResult] = [f for f, _ in fuzzy_matches]
            results.extend(fuzzy_matches_extracted)

        res: set[Function] = set()
        results_by_file = groupby(results, key=lambda x: x.file)
        for file, file_results in results_by_file:
            file_results_list = list(file_results)
            functions_found = list(set(result.value for result in file_results_list))
            if not fuzzy and not all(function_name == f for f in functions_found):
                logger.warning(
                    "Function name mismatch, this should not happen: %s",
                    function_name,
                )
                continue

            for function in functions_found:
                f = self.ts.get_function(function, Path(file) if isinstance(file, str) else file)  # type: ignore[call-arg]
                if not f:
                    continue
                if line_number:
                    lines = [
                        (
                            body.start_line,
                            body.end_line,
                        )
                        for body in f.bodies
                    ]
                    # NOTE(boyan): We check whether the supplied line to look up for the function
                    # is contained within at least one of the function bodies found by
                    # tree-sitter
                    if any(True for start_line, end_line in lines if start_line <= line_number <= end_line):
                        res.add(f)
                else:
                    res.add(f)

        output_str = f"Found {len(res)} functions for {function_name}"
        if file_path:
            output_str += f" in {file_path}"
        if line_number:
            output_str += f" at line {line_number}"
        if print_output:
            logger.debug(output_str)

        # Sort in same order as results
        results_value = [r.value for r in results]
        res_sorted: list[Function] = sorted(res, key=lambda x: results_value.index(x.name))

        return self._rebase_functions_file_paths(res_sorted)

    def _filter_callees(self, caller_function: Function, callees: list[Function]) -> list[Function]:
        # If no resolver available, don't filter anything
        if not self.imports_resolver:
            return callees
        return self.imports_resolver.filter_callees(caller_function, callees)

    def get_callers(
        self,
        function: Function | str,
        file_path: Path | None = None,
    ) -> list[Function]:
        """Get the callers of a function. File paths are based on the challenge
        task container structure (e.g. /src).
        """
        if isinstance(function, str):
            function_name = function
        elif isinstance(function, Function):
            function_name = function.name
            if file_path:
                logger.warning(
                    "File path %s will be ignored because function %s is provided.",
                    file_path,
                    function_name,
                )
            file_path = function.file_path

        results: list[CQSearchResult] = []
        flags = ["6"]
        for flag in flags:
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                flag,
                "-t",
                function_name,
                "-e",
                "-u",
            ]
            # NOTE: Querying for callers returns the function definitions of the callers.
            # We don't add a file path to the cqsearch args because we don't want
            # to assume all callers of the function will be in the same file as the function.
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("get_callers_with_codequery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.STATIC_ANALYSIS,
                    crs_action_name="get_callers_with_codequery",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                    extra_attributes={
                        "crs.action.code.file": str(file_path) if file_path else "",
                        "crs.action.code.function_name": function_name,
                    },
                )
                results.extend(self._run_cqsearch(*cqsearch_args))
                span.set_status(Status(StatusCode.OK))

        callers: set[Function] = set()
        for result in results:
            caller = self.get_functions(result.value, result.file, result.line)
            callers.update(caller)

        # NOTE: Callers returned are a superset of the actual callers. We cannot
        # filter out incorrect callers because we cannot ask cqsearch to return
        # callers of a function which is contained at a specific file line number.

        output_str = f"Found {len(callers)} callers for {function_name}"
        if file_path:
            output_str += f" in {file_path}"
        logger.debug(output_str)

        return self._rebase_functions_file_paths(list(callers))

    def get_callees(
        self,
        function: Function | str,
        file_path: Path | None = None,
        line_number: int | None = None,
    ) -> list[Function]:
        """Get the callees of a function. File paths are based on the challenge
        task container structure (e.g. /src).
        """
        functions: list[Function] = []
        if isinstance(function, str):
            function_name = function
            if file_path is None and line_number is not None:
                logger.warning("File path is required when line number is provided")
                line_number = None
            # NOTE: We call get_functions to identify function definitions (and line numbers)
            # to filter out callees that are not in the same file path and line range as the function.
            functions.extend(self.get_functions(function_name, file_path, line_number))
        elif isinstance(function, Function):
            function_name = function.name
            if file_path:
                logger.warning(
                    "File path %s will be ignored because function %s is provided.",
                    file_path,
                    function_name,
                )
            file_path = function.file_path
            if line_number:
                logger.warning(
                    "Line number %s will be ignored because function %s is provided.",
                    line_number,
                    function_name,
                )
            functions.append(function)

        results: list[CQSearchResult] = []
        flags = ["7"]
        for flag in flags:
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                flag,
                "-t",
                function_name,
                "-e",
                "-u",
            ]
            # NOTE: Querying for callees returns the file path and line number of where
            # the callees are called, not the callee function definition. We add a file
            # path to cqsearch args because (by definition) the callees are called in
            # the same file as the function.
            if file_path:
                cqsearch_args += ["-b", file_path.as_posix()]

            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("get_callees_with_codequery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.STATIC_ANALYSIS,
                    crs_action_name="get_callees_with_codequery",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                    extra_attributes={
                        "crs.action.code.file": str(file_path) if file_path else "",
                        "crs.action.code.lines": line_number if line_number else "",
                        "crs.action.code.function_name": function_name,
                    },
                )
                results.extend(self._run_cqsearch(*cqsearch_args))
                span.set_status(Status(StatusCode.OK))

        # Create a dictionary of file path(s) and line ranges to filter callees by.
        callee_filter: dict[Path, list[tuple[int, int]]] = {}
        for function in functions:
            callee_filter[function.file_path] = [(b.start_line, b.end_line) for b in function.bodies]

        callees: set[Function] = set()
        for result in results:
            # NOTE: Each result is the callee function name, and the file path and line number
            # of where the callee function is called.

            rebased_path = self._rebase_path(result.file)

            # If the callee is contained in a file we're looking for.
            if not any(rebased_path == file_path for file_path in callee_filter):
                continue

            # If the callee is called at a line number we're looking for.
            if not any(line_range[0] <= result.line <= line_range[1] for line_range in callee_filter[rebased_path]):
                continue

            # Now find the function definition of the callee

            # NOTE: We don't add a file path or line number here because we don't
            # have that information.
            callee = self.get_functions(result.value)
            callees.update(callee)

        # NOTE: Callees returned are a superset of the actual callees. We cannot
        # filter out incorrect callees because we cannot ask cqsearch to return
        # the function definitions of callees called from a function which is
        # contained at a specific file line number.

        # TODO(Evan): If we do this, then tests become non-deterministic. Which file path do we keep?
        #       # Make sure we don't add the same function twice
        #       unique_functions: dict[str, list[Function]] = {}
        #       for f in callees:
        #           root = "/".join(f.file_path.parts[:3])
        #           if root not in unique_functions:
        #               unique_functions[root] = []
        #           if not any(x for x in unique_functions[root] if x.has_same_source(f)):
        #               unique_functions[root].append(f)
        #       callees = [f for fs in unique_functions.values() for f in fs]

        # TODO(boyan): if function is a str we should try to find the actual function
        # at the beginning of this function so we can use to do the filtering. If not
        # then we need the function file
        if isinstance(function, Function):
            callees = set(self._filter_callees(function, list(callees)))

        output_str = f"Found {len(callees)} callees for {function_name}"
        if file_path:
            output_str += f" in {file_path}"
        logger.debug(output_str)

        return self._rebase_functions_file_paths(list(callees))

    def get_types(
        self,
        type_name: str,
        file_path: Path | None = None,
        function_name: str | None = None,
        fuzzy: bool | None = False,
        fuzzy_threshold: int = 80,
    ) -> list[TypeDefinition]:
        """Finds and return the definition of type named `typename`. File paths
        are based on the challenge task container structure (e.g. /src).

        The order of the results is (1) exact matches and (2) fuzzy matches sorted in descending order of similarity.

        NOTE: Fuzzy search will be disabled if a file path is provided.
        """
        if fuzzy and file_path:
            logger.warning(
                "Fuzzy search will be disabled because file path %s was provided.",
                file_path,
            )

        # Look for symbols (option 1) and class/struct (option 3)
        results: list[CQSearchResult] = []
        flags = ["1", "3"]
        for flag in flags:
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                flag,
                "-t",
                type_name,
                "-e",
                "-u",
            ]
            if file_path:
                cqsearch_args += ["-b", file_path.as_posix()]

            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("get_types_with_codequery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.STATIC_ANALYSIS,
                    crs_action_name="get_types_with_codequery",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                    extra_attributes={
                        "crs.action.code.file": str(file_path) if file_path else "",
                        "crs.action.code.fuzzy": fuzzy if fuzzy else False,
                        "crs.action.code.type_name": type_name,
                        "crs.action.code.function_name": function_name if function_name else "",
                    },
                )
                results.extend(self._run_cqsearch(*cqsearch_args))
                span.set_status(Status(StatusCode.OK))

        # Extended fuzzy matching
        if fuzzy and file_path is None:
            # Fuzzy match the function name against all functions in the codebase
            fuzzy_matches: list[tuple[CQSearchResult, float]] = sorted(
                [
                    (t, rapidfuzz.fuzz.ratio(type_name, t.value))
                    for t in self._get_all_types()
                    if t.value and rapidfuzz.fuzz.ratio(type_name, t.value) > fuzzy_threshold
                ],
                key=lambda x: x[1],
                reverse=True,
            )
            fuzzy_matches_extracted: list[CQSearchResult] = [t for t, _ in fuzzy_matches]
            results.extend(fuzzy_matches_extracted)

        res: set[TypeDefinition] = set()
        results_by_file = groupby(results, key=lambda x: x.file)
        for file, file_results in results_by_file:
            file_results_list = list(file_results)
            types_found = list(set(result.value for result in file_results_list))

            if not fuzzy and not all(str(type_name) == str(t) for t in types_found):
                logger.warning(
                    "Type name mismatch, this should not happen: %s",
                    type_name,
                )
                continue

            typedefs: dict[str, TypeDefinition] = {}

            for typename in types_found:
                t = self.ts.parse_types_in_code(file, typename, fuzzy)
                if not t:
                    continue
                typedefs.update(t)

            if function_name:
                # Get the function definition to find its scope
                function = self.ts.get_function(function_name, Path(file) if isinstance(file, str) else file)  # type: ignore[call-arg]
                if function:
                    # Filter type definitions to only include those within the function's scope
                    filtered_typedefs = {}
                    for name, typedef in typedefs.items():
                        # Check if the type definition is within the function's scope
                        for body in function.bodies:
                            if body.start_line <= typedef.definition_line <= body.end_line:
                                filtered_typedefs[name] = typedef
                                break
                    typedefs = filtered_typedefs
                else:
                    typedefs = {}

            res.update(typedefs.values())

        output_str = f"Found {len(res)} types for {type_name}"
        if file_path:
            output_str += f" in {file_path}"
        if function_name:
            output_str += f" in {function_name}"
        logger.debug(output_str)

        # Sort in same order as results
        results_value = [r.value for r in results]
        res_sorted: list[TypeDefinition] = sorted(res, key=lambda x: results_value.index(x.name))

        # Rebase the file paths
        return self._rebase_types_file_paths(res_sorted)

    def get_type_calls(self, type_definition: TypeDefinition) -> list[TypeUsageInfo]:
        """Get the calls to a type definition. File paths are based on the challenge
        task container structure (e.g. /src).
        """
        results: list[CQSearchResult] = []
        flags = ["1", "8"]
        for flag in flags:
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                flag,
                "-t",
                type_definition.name,
                "-e",
                "-u",
            ]

            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("get_type_calls_with_codequery") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.STATIC_ANALYSIS,
                    crs_action_name="get_type_calls_with_codequery",
                    task_metadata=dict(self.challenge.task_meta.metadata),
                )
                results.extend(self._run_cqsearch(*cqsearch_args))
                span.set_status(Status(StatusCode.OK))

        logger.debug("Found %d calls to type %s", len(results), type_definition.name)

        calls: set[TypeUsageInfo] = set()
        for result in results:
            calls.add(
                TypeUsageInfo(
                    name=type_definition.name,
                    file_path=result.file,
                    line_number=result.line,
                ),
            )

        return self._rebase_type_usages_file_paths(list(calls))


@dataclass
class CodeQueryPersistent(CodeQuery):
    """CodeQuery that we persist the status of the db

    It saves the db in the same workdir used by the challenge task, and it uses
    a copy of the challenge task named with the task-id + suffix. In this way it
    can always retrieve the db given a challenge task (even if it's a rw copy
    used by another instance).
    """

    work_dir: Path
    tasks_storage: Path | None = None

    def __post_init__(self) -> None:
        """Post init the persistent codequery db"""
        task_id = self.challenge.task_meta.task_id
        cqdb_path = self.work_dir / task_id / (task_id + ".cqdb")
        try:
            self.challenge = ChallengeTask(cqdb_path, local_task_dir=cqdb_path)
        except ChallengeTaskError:
            # This is the case where the cqdb is not yet created
            logger.debug("Creating new CodeQueryPersistent DB in %s", cqdb_path)
            if self.tasks_storage is not None:
                clean_task = self.challenge.get_clean_task(self.tasks_storage)
            else:
                clean_task = self.challenge
            with clean_task.get_rw_copy(self.work_dir) as persistent_challenge:
                persistent_challenge.apply_patch_diff()
                self.challenge = persistent_challenge
                super().__post_init__()

                try:
                    persistent_challenge.commit(".cqdb")
                    logger.debug(f"Uploading cqdb {persistent_challenge.local_task_dir} to remote storage")
                except Exception as e:
                    logger.exception("Failed to commit the cqdb: %s", e)
                    raise e

            return

        super().__post_init__()
