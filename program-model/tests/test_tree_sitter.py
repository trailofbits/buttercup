from pathlib import Path
import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.api.tree_sitter import CodeTS, TypeDefinitionType


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    base_path = tmp_path / "task_rw"
    oss_fuzz = base_path / "fuzz-tooling" / "fuzz-tooling"
    source = base_path / "src" / "example_project"
    diffs = base_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create mock project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text(
        "language: c\n"
        "sanitizers:\n"
        "  - address\n"
        "  - memory\n"
        "  - undefined\n"
        "architectures:\n"
        "  - x86_64\n"
        "fuzzing_engines:\n"
        "  - afl\n"
        "  - honggfuzz\n"
        "  - libfuzzer\n"
    )

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra" / "helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")

    # Create a test C file with two functions
    test_c_content = """#include <stdio.h>

// Forward declarations - these should not be matched
struct forward_struct;
union forward_union;
enum forward_enum;

// Preprocessor type definitions
#define MY_TYPE my_struct_t
#define ANOTHER_TYPE struct my_struct

struct struct_name {
    int a;
    int b;
};

int add(int a, int b) {
    return a + b;
}

void print_hello(void) {
    printf("Hello, World!\\n");
}
"""
    (source / "test.c").write_text(test_c_content)
    test2_c_content = """#include <stdio.h>

#ifdef TEST
int add(int a, int b) {
    return a + b;
}
#else
double add(double a, double b) {
    return a + b;
}
#endif
"""
    (source / "test2.c").write_text(test2_c_content)

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="example_project",
        task_id="task-id-tree-sitter",
    ).save(base_path)

    return base_path


@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
    )


def test_get_functions_code_c(challenge_task_readonly: ChallengeTask):
    """Test getting function code from a C file."""
    code_ts = CodeTS(challenge_task_readonly)
    functions = code_ts.get_functions(Path("src/example_project/test.c"))

    assert "add" in functions
    assert "print_hello" in functions

    add_function = functions["add"]
    assert len(add_function.bodies) == 1
    assert "int add(int a, int b)" in add_function.bodies[0].body
    assert "return a + b;" in add_function.bodies[0].body

    print_hello_function = functions["print_hello"]
    assert len(print_hello_function.bodies) == 1
    assert "void print_hello(void)" in print_hello_function.bodies[0].body
    assert 'printf("Hello, World!\\n");' in print_hello_function.bodies[0].body


def test_get_function_c(challenge_task_readonly: ChallengeTask):
    """Test getting a function from a C file."""
    code_ts = CodeTS(challenge_task_readonly)
    function = code_ts.get_function("add", Path("src/example_project/test.c"))
    assert function is not None
    assert function.name == "add"
    assert function.file_path == Path("src/example_project/test.c")
    assert len(function.bodies) == 1
    assert "int add(int a, int b)" in function.bodies[0].body
    assert "return a + b;" in function.bodies[0].body
    assert function.bodies[0].start_line == 16
    assert function.bodies[0].end_line == 18


def test_get_function_multiple_definitions_c(challenge_task_readonly: ChallengeTask):
    """Test getting a function from a C file with multiple definitions."""
    code_ts = CodeTS(challenge_task_readonly)
    function = code_ts.get_function("add", Path("src/example_project/test2.c"))
    assert function is not None
    assert function.name == "add"
    assert function.file_path == Path("src/example_project/test2.c")
    assert len(function.bodies) == 2
    assert "int add(int a, int b)" in function.bodies[0].body
    assert "double add(double a, double b)" in function.bodies[1].body
    assert function.bodies[0].start_line == 3
    assert function.bodies[0].end_line == 5
    assert function.bodies[1].start_line == 7
    assert function.bodies[1].end_line == 9


def test_get_type_definition_types(challenge_task_readonly: ChallengeTask):
    """Test getting different types of definitions."""
    code_ts = CodeTS(challenge_task_readonly)
    types = code_ts.parse_types_in_code(Path("src/example_project/test.c"))

    # Test preprocessor type definitions
    type_def = types["MY_TYPE"]
    assert type_def is not None
    assert type_def.type == TypeDefinitionType.PREPROC_TYPE
    assert "#define MY_TYPE my_struct_t" in type_def.definition

    type_def = types["ANOTHER_TYPE"]
    assert type_def is not None
    assert type_def.type == TypeDefinitionType.PREPROC_TYPE
    assert "#define ANOTHER_TYPE struct my_struct" in type_def.definition
