"""Codequery based code querying module"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from itertools import groupby
from typing import ClassVar, Union


from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.program_model.api.tree_sitter import CodeTS
from buttercup.program_model.utils.common import (
    Function,
    TypeDefinition,
)
from buttercup.common.project_yaml import ProjectYaml

logger = logging.getLogger(__name__)


@dataclass
class CQSearchResult:
    """Result of the cqsearch command."""

    value: str
    file: Path
    line: int
    body: str

    @classmethod
    def from_line(cls, line: str, base_path: Path) -> CQSearchResult | None:
        """Parse a line of the cqsearch output into a CQSearchResult."""
        try:
            value, file_line, body = line.split("\t", 2)
            file, line = file_line.split(":", 1)
        except ValueError:
            logger.warning("Invalid cqsearch line: %s", line)
            return None

        file = Path(file)
        if file.is_relative_to(base_path):
            file = file.relative_to(base_path)

        try:
            line_number = int(line)
        except ValueError:
            logger.warning("Invalid line number: %s", line)
            line_number = 0

        return cls(value, file, line_number, body)


@dataclass
class CodeQuery:
    """Class to extract context about a challenge project with CodeQuery."""

    challenge: ChallengeTask
    ts: CodeTS = field(init=False)
    _base_path: Path = field(init=False)

    BASE_PATH: ClassVar[str] = "cqdb_base_path"
    CSCOPE_FILES: ClassVar[str] = "cscope.files"
    CSCOPE_OUT: ClassVar[str] = "cscope.out"
    TAGS: ClassVar[str] = "tags"
    CODEQUERY_DB: ClassVar[str] = "codequery.db"

    def __post_init__(self) -> None:
        """Initialize the CodeQuery object."""
        self._verify_requirements()

        self.ts = CodeTS(self.challenge)
        if self._is_already_indexed():
            self._base_path = Path(
                self.challenge.task_dir.joinpath("cqdb_base_path").read_text()
            )
            logger.info("CodeQuery DB already exists in %s.", self.challenge.task_dir)
            return

        if self.challenge.local_task_dir is None:
            raise ValueError(
                "Challenge Task is read-only, cannot perform this operation"
            )

        self._create_codequery_db()
        logger.info("CodeQuery DB created successfully.")

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

    def _is_already_indexed(self) -> bool:
        """Check if the codequery database already exists."""
        return (
            self.challenge.task_dir.joinpath(self.CSCOPE_FILES).exists()
            and self.challenge.task_dir.joinpath(self.CSCOPE_OUT).exists()
            and self.challenge.task_dir.joinpath(self.CODEQUERY_DB).exists()
            and self.challenge.task_dir.joinpath(self.TAGS).exists()
            and self.challenge.task_dir.joinpath(self.BASE_PATH).exists()
        )

    def _create_codequery_db(self) -> None:
        """Create the codequery database."""
        with self.challenge.task_dir.joinpath(self.CSCOPE_FILES).open("w") as f:
            project_yaml = ProjectYaml(
                self.challenge, self.challenge.task_meta.project_name
            )
            if project_yaml.language == "c" or project_yaml.language == "c++":
                extensions = [
                    "*.c",
                    "*.cpp",
                    "*.cxx",
                    "*.cc",
                    "*.h",
                    "*.hpp",
                    "*.hxx",
                    "*.hh",
                ]
            elif project_yaml.language == "jvm":
                extensions = ["*.java"]
            else:
                raise ValueError(f"Unsupported language: {project_yaml.language}")

            # Find all files with the given extensions
            # When looking at files in oss-fuzz, we filter out files that are not in the challenge
            oss_fuzz_projects_dir = self.challenge.get_oss_fuzz_path() / "projects"
            challenge_task_projects_dir = (
                oss_fuzz_projects_dir / self.challenge.task_meta.project_name
            )
            for ext in extensions:
                for file in self.challenge.task_dir.rglob(ext):
                    if file.is_relative_to(self.challenge.get_oss_fuzz_path()):
                        if not file.is_relative_to(challenge_task_projects_dir):
                            continue

                    f.write(str(file) + "\n")

        try:
            subprocess.run(["cscope", "-cb"], cwd=self.challenge.task_dir, timeout=200)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cscope index.")

        if not self.challenge.task_dir.joinpath(self.CSCOPE_OUT).exists():
            raise RuntimeError("Failed to create cscope out.")

        try:
            subprocess.run(
                ["ctags", "--fields=+i", "-n", "-L", self.CSCOPE_FILES],
                cwd=self.challenge.task_dir,
                timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create ctags index.")

        if not self.challenge.task_dir.joinpath(self.TAGS).exists():
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
                cwd=self.challenge.task_dir,
                timeout=2700,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cquery database.")

        # Save the base path to a file in the challenge task
        self.challenge.task_dir.joinpath("cqdb_base_path").write_text(
            self.challenge.task_dir.as_posix()
        )
        self._base_path = self.challenge.task_dir

    def __repr__(self) -> str:
        return f"CodeQuery(challenge={self.challenge})"

    def _run_cqsearch(self, *args: str) -> list[CQSearchResult]:
        """Run the cqsearch command and parse the results."""
        try:
            logger.debug("Running cqsearch with args: %s", " ".join(args))
            result = subprocess.run(
                ["cqsearch", *args],
                cwd=self.challenge.task_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to run cqsearch: {e}")

        results = [
            CQSearchResult.from_line(line, self._base_path)
            for line in output.splitlines()
        ]
        return [result for result in results if result is not None]

    def get_functions(
        self,
        function_name: str,
        file_path: Path | None = None,
        line_number: int | None = None,
        fuzzy: bool | None = False,
    ) -> list[Function]:
        """Get the definition(s) of a function in the codebase or in a specific file."""
        # Get symbols and functions. Some functions are not found by cqsearching functions so we have to use symbols instead.
        results_all = []
        for search_type in ["1", "2"]:  # 1 for symbols, 2 for functions
            cqsearch_args = [
                "-s",
                self.CODEQUERY_DB,
                "-p",
                search_type,
                "-t",
                function_name,
                "-f" if fuzzy else "-e",
                "-u",
            ]
            if file_path:
                cqsearch_args += ["-b", file_path.as_posix()]

            results = self._run_cqsearch(*cqsearch_args)
            logger.debug("cqsearch output: %s", results)

            results_all.extend(results)

        res: set[Function] = set()
        results_by_file = groupby(results_all, key=lambda x: x.file)
        for file, results in results_by_file:
            functions_found = list(set(result.value for result in results))

            if not fuzzy and not all(function_name == f for f in functions_found):
                logger.warning(
                    "Function name mismatch, this should not happen: %s",
                    function_name,
                )
                continue
            if fuzzy and not all(function_name in f for f in functions_found):
                logger.warning(
                    "Function name mismatch, this should not happen: %s",
                    function_name,
                )
                continue

            for function in functions_found:
                f = self.ts.get_function(function, file)
                if f is None:
                    logger.warning("Function not found in tree-sitter: %s", function)
                    continue
                if line_number:
                    lines = [
                        (
                            body.start_line,
                            body.end_line,
                        )
                        for body in f.bodies
                    ]
                    logger.debug(
                        "Looking for function %s in file %s on lines %s",
                        function,
                        file,
                        ",".join(map(str, lines)),
                    )
                    # NOTE(boyan): We check whether the supplied line to look up for the function
                    # is contained within at least one of the function bodies found by
                    # tree-sitter
                    if any(
                        True
                        for start_line, end_line in lines
                        if start_line <= line_number <= end_line
                    ):
                        res.add(f)
                    else:
                        logger.warning(
                            "Function (%s) not found using tree-sitter in file %s for line %d",
                            function,
                            file,
                            line_number,
                        )
                else:
                    res.add(f)

        return list(res)

    def get_callers(self, function: Function) -> list[Function]:
        """Get the callers of a function."""
        cqsearch_args = [
            "-s",
            self.CODEQUERY_DB,  # Specify the database file path
            "-p",
            "6",
            "-t",
            function.name,
            "-e",
            "-u",  # use full paths
        ]

        results = self._run_cqsearch(*cqsearch_args)
        logger.debug("cqsearch output: %s", results)

        callers: set[Function] = set()
        for result in results:
            functions = self.get_functions(result.value, Path(result.file), result.line)
            callers.update(functions)

        return list(callers)

    def get_callees(self, function: Function) -> list[Function]:
        """Get the callees of a function."""
        cqsearch_args = [
            "-s",
            self.CODEQUERY_DB,  # Specify the database file path
            "-p",
            "7",
            "-t",
            function.name,
            "-e",
            "-u",  # use full paths
        ]

        results = self._run_cqsearch(*cqsearch_args)
        logger.debug("cqsearch output: %s", results)

        callees: set[Function] = set()
        for result in results:
            functions = self.get_functions(result.value)
            unique_functions = []
            for f in functions:
                if not any(x for x in unique_functions if x.has_same_source(f)):
                    unique_functions.append(f)
            callees.update(functions)
        return list(callees)

    def get_types(
        self,
        type_name: Union[bytes, str],
        file_path: Path | None = None,
        function_name: str | None = None,
        fuzzy: bool | None = False,
    ) -> list[TypeDefinition]:
        """Finds and return the definition of type named `typename`."""
        cqsearch_args = [
            "-s",
            self.CODEQUERY_DB,  # Specify the database file path
            "-p",
            "1",  # '1' for symbol
            "-t",
            type_name,  # The name of the type
            "-f" if fuzzy else "-e",
            "-u",  # use full paths
        ]
        if file_path:
            cqsearch_args += ["-b", file_path.as_posix()]

        results = self._run_cqsearch(*cqsearch_args)
        logger.debug("cqsearch output: %s", results)

        res: list[TypeDefinition] = []
        results_by_file = groupby(results, key=lambda x: x.file)
        for file, results in results_by_file:
            types_found = list(set(result.value for result in results))

            if not fuzzy and not all(type_name == t for t in types_found):
                logger.warning(
                    "Type name mismatch, this should not happen: %s",
                    type_name,
                )
                continue
            if fuzzy and not all(type_name in t for t in types_found):
                logger.warning(
                    "Type name mismatch, this should not happen: %s",
                    type_name,
                )
                continue

            typedefs: dict[str, TypeDefinition] = {}

            for typename in types_found:
                t = self.ts.parse_types_in_code(file, typename, fuzzy)
                if not t:
                    logger.warning(
                        "Type definition not found in tree-sitter: %s", typename
                    )
                    continue
                typedefs.update(t)

            if function_name:
                # Get the function definition to find its scope
                function = self.ts.get_function(function_name, file)
                if function:
                    # Filter type definitions to only include those within the function's scope
                    filtered_typedefs = {}
                    for name, typedef in typedefs.items():
                        # Check if the type definition is within the function's scope
                        for body in function.bodies:
                            if (
                                body.start_line
                                <= typedef.definition_line
                                <= body.end_line
                            ):
                                filtered_typedefs[name] = typedef
                                break
                    typedefs = filtered_typedefs
                else:
                    typedefs = {}

            res.extend(typedefs.values())

        return res

    def get_type_calls(self, type_definition: TypeDefinition) -> list[tuple[Path, int]]:
        """Get the calls to a type definition."""
        cqsearch_args = [
            "-s",
            self.CODEQUERY_DB,  # Specify the database file path
            "-p",
            "8",
            "-t",
            type_definition.name,
            "-e",
            "-u",  # use full paths
        ]

        results = self._run_cqsearch(*cqsearch_args)
        logger.debug("cqsearch output: %s", results)

        calls: list[tuple[Path, int]] = []
        for result in results:
            calls.append((Path(result.file), result.line))

        return calls


@dataclass
class CodeQueryPersistent(CodeQuery):
    """CodeQuery that we persist the status of the db

    It saves the db in the same workdir used by the challenge task, and it uses
    a copy of the challenge task named with the task-id + suffix. In this way it
    can always retrieve the db given a challenge task (even if it's a rw copy
    used by another instance).
    """

    work_dir: Path

    def __post_init__(self) -> None:
        """Post init the persistent codequery db"""
        task_id = self.challenge.task_meta.task_id
        cqdb_path = self.work_dir.joinpath(task_id + ".cqdb")
        try:
            self.challenge = ChallengeTask(cqdb_path, local_task_dir=cqdb_path)
            super().__post_init__()
        except ChallengeTaskError:
            # This is the case where the cqdb is not yet created
            logger.debug("Creating new CodeQueryPersistent DB in %s", cqdb_path)
            with self.challenge.get_rw_copy(self.work_dir) as persistent_challenge:
                self.challenge = persistent_challenge
                super().__post_init__()

                try:
                    persistent_challenge.commit(".cqdb")
                    logger.debug(
                        f"Uploading cqdb {persistent_challenge.local_task_dir} to remote storage"
                    )
                except Exception as e:
                    logger.exception("Failed to commit the cqdb: %s", e)
                    raise e
