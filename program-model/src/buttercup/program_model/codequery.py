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


CONTAINER_SRC_DIR: str = "container_src_dir"


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
            file, line = file_line.split(":", 1)
        except ValueError:
            logger.warning("Invalid cqsearch line: %s", line)
            return None

        # Rebase the file path from the challenge task base dir.
        # This is needed because the task-dir part might be different from what
        # was originall used to create the db.
        file = Path(file)
        if CONTAINER_SRC_DIR not in file.parts:
            logger.warning("File %s is not in the container source dir", file)
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

    CSCOPE_FILES: ClassVar[str] = "cscope.files"
    CSCOPE_OUT: ClassVar[str] = "cscope.out"
    TAGS: ClassVar[str] = "tags"
    CODEQUERY_DB: ClassVar[str] = "codequery.db"

    def __post_init__(self) -> None:
        """Initialize the CodeQuery object."""
        self._verify_requirements()

        self.ts = CodeTS(self.challenge)
        if self._is_already_indexed():
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
            self.challenge.task_dir.joinpath(CONTAINER_SRC_DIR).exists()
            and self._get_container_src_dir().joinpath(self.CSCOPE_FILES).exists()
            and self._get_container_src_dir().joinpath(self.CSCOPE_OUT).exists()
            and self._get_container_src_dir().joinpath(self.CODEQUERY_DB).exists()
            and self._get_container_src_dir().joinpath(self.TAGS).exists()
        )

    def _get_container_src_dir(self) -> Path:
        """Get the container source directory."""
        return self.challenge.task_dir.joinpath(CONTAINER_SRC_DIR)

    def _copy_src_from_container(self) -> None:
        """Copy the /src directory from the container to the challenge task directory."""
        res = self.challenge.build_image(pull_latest_base_image=True)
        if not res.success:
            raise RuntimeError("Failed to build image.")

        challenge_container_name = self.challenge.container_image()
        src_dst = self._get_container_src_dir()
        src_dst.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Copying src from container %s to %s", challenge_container_name, src_dst
        )
        try:
            command = [
                "docker",
                "create",
                "--name",
                f"codequery-container-{self.challenge.task_meta.task_id}",
                "-v",
                f"{self.challenge.get_source_path().as_posix()}:{self.challenge.workdir_from_dockerfile()}",
                challenge_container_name,
            ]
            subprocess.run(command, check=True)
            command = [
                "docker",
                "cp",
                f"codequery-container-{self.challenge.task_meta.task_id}:/src",
                src_dst.resolve().as_posix(),
            ]
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as e:
            logger.error("Failed to copy src from container: %s", e)
            raise RuntimeError(f"Failed to copy src from container: {e}")
        finally:
            command = [
                "docker",
                "rm",
                f"codequery-container-{self.challenge.task_meta.task_id}",
            ]
            subprocess.run(command, check=True)

    def _create_codequery_db(self) -> None:
        """Create the codequery database."""
        self._copy_src_from_container()

        with self._get_container_src_dir().joinpath(self.CSCOPE_FILES).open("w") as f:
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
            for ext in extensions:
                for file in self._get_container_src_dir().rglob(ext):
                    f.write(str(file) + "\n")

        try:
            subprocess.run(
                ["cscope", "-cb"], cwd=self._get_container_src_dir(), timeout=200
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cscope index.")

        if not self._get_container_src_dir().joinpath(self.CSCOPE_OUT).exists():
            raise RuntimeError("Failed to create cscope out.")

        try:
            subprocess.run(
                ["ctags", "--fields=+i", "-n", "-L", self.CSCOPE_FILES],
                cwd=self._get_container_src_dir(),
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
                cwd=self._get_container_src_dir(),
                timeout=2700,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Failed to create cquery database.")

    def __repr__(self) -> str:
        return f"CodeQuery(challenge={self.challenge})"

    def _run_cqsearch(self, *args: str) -> list[CQSearchResult]:
        """Run the cqsearch command and parse the results."""
        try:
            logger.debug("Running cqsearch with args: %s", " ".join(args))
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

    def get_functions(
        self,
        function_name: str,
        file_path: Path | None = None,
        line_number: int | None = None,
        fuzzy: bool | None = False,
    ) -> list[Function]:
        """Get the definition(s) of a function in the codebase or in a specific
        file. File paths are based on the challenge task container structure
        (e.g. /src)."""
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
                    logger.warning(
                        "Function not found in tree-sitter: %s/%s", file, function
                    )
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

        return self._rebase_functions_file_paths(list(res))

    def get_callers(self, function: Function) -> list[Function]:
        """Get the callers of a function. File paths are based on the challenge
        task container structure (e.g. /src)."""
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

        return self._rebase_functions_file_paths(list(callers))

    def get_callees(self, function: Function) -> list[Function]:
        """Get the callees of a function. File paths are based on the challenge
        task container structure (e.g. /src)."""
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
        return self._rebase_functions_file_paths(list(callees))

    def get_types(
        self,
        type_name: Union[bytes, str],
        file_path: Path | None = None,
        function_name: str | None = None,
        fuzzy: bool | None = False,
    ) -> list[TypeDefinition]:
        """Finds and return the definition of type named `typename`. File paths
        are based on the challenge task container structure (e.g. /src)."""
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

        # TODO: Rebase the file paths
        return res

    def get_type_calls(self, type_definition: TypeDefinition) -> list[tuple[Path, int]]:
        """Get the calls to a type definition. File paths are based on the challenge
        task container structure (e.g. /src)."""
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
            calls.append((self._rebase_path(result.file), result.line))

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
