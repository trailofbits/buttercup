import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.api.tree_sitter import CodeTS, TypeDefinitionType
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionInfo:
    num_bodies: int
    body_excerpts: list[str]


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
        metadata={
            "task_id": "task-id-tree-sitter",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(base_path)

    return base_path


@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
    )


@pytest.fixture
def java_task_dir(tmp_path: Path) -> Path:
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
    project_yaml_path.write_text("language: java\n")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra" / "helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="example_project",
        task_id="task-id-tree-sitter",
        metadata={
            "task_id": "task-id-tree-sitter",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(base_path)

    return base_path


@pytest.fixture
def java_challenge_task_readonly(java_task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=java_task_dir,
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
    assert function.bodies[0].start_line == 17
    assert function.bodies[0].end_line == 19


def test_get_function_multiple_definitions_c(challenge_task_readonly: ChallengeTask):
    """Test getting a function from a C file with multiple definitions."""
    code_ts = CodeTS(challenge_task_readonly)
    function = code_ts.get_function("add", Path("src/example_project/test2.c"))
    assert function is not None
    assert function.name == "add"
    assert function.file_path == Path("src/example_project/test2.c")
    assert len(function.bodies) == 2
    assert "#ifdef TEST" in function.bodies[0].body
    assert "int add(int a, int b)" in function.bodies[0].body
    assert "double add(double a, double b)" in function.bodies[1].body
    assert "#else" in function.bodies[1].body
    assert function.bodies[0].start_line == 3
    assert function.bodies[0].end_line == 6
    assert function.bodies[1].start_line == 7
    assert function.bodies[1].end_line == 10


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


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "png_icc_check_length",
            "src/example-libpng/png.c",
            FunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """if (!icc_check_length(png_ptr, colorspace, name, profile_length))
      return 0;

   /* This needs to be here because the 'normal' check is in
    * png_decompress_chunk, yet this happens after the attempt to
    * png_malloc_base the required data.  We only need this on read; on write
    * the caller supplies the profile buffer so libpng doesn't allocate it.  See
    * the call to icc_check_length below (the write case).
    */
#  ifdef PNG_SET_USER_LIMITS_SUPPORTED
      else if (png_ptr->user_chunk_malloc_max > 0 &&
               png_ptr->user_chunk_malloc_max < profile_length)
         return png_icc_profile_error(png_ptr, colorspace, name, profile_length,
             "exceeds application limits");""",
                ],
            ),
        ),
        (
            "png_pow10",
            "src/example-libpng/png.c",
            FunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """/* Utility used below - a simple accurate power of ten from an integral
 * exponent.
 */
static double
png_pow10(int power)
{
   int recip = 0;
   double d = 1;

   /* Handle negative exponent with a reciprocal at the end because
    * 10 is exact whereas .1 is inexact in base 2
    */
   if (power < 0)
   {
      if (power < DBL_MIN_10_EXP) return 0;
      recip = 1; power = -power;
   }""",
                ],
            ),
        ),
        (
            "png_check_IHDR",
            "src/example-libpng/png.c",
            FunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """int error = 0;

   /* Check for width and height valid values */
   if (width == 0)
   {
      png_warning(png_ptr, "Image width is zero in IHDR");
      error = 1;
   }

   if (width > PNG_UINT_31_MAX)
   {
      png_warning(png_ptr, "Invalid image width in IHDR");
      error = 1;
   }""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libpng_indexing(
    libpng_oss_fuzz_task: ChallengeTask,
    function_name: str,
    file_path: str,
    function_info: FunctionInfo,
):
    """Test that we can parse libpng code using tree-sitter."""
    code_ts = CodeTS(libpng_oss_fuzz_task)
    function = code_ts.get_function(function_name, Path(file_path))
    assert function is not None
    assert len(function.bodies) == function_info.num_bodies
    for body in function_info.body_excerpts:
        assert any([body in x.body for x in function.bodies])


def test_get_field_type(java_challenge_task_readonly: ChallengeTask):
    """Test getting the type of a field of a type definition."""
    code_ts = CodeTS(java_challenge_task_readonly)
    typedef = b"""class Person {
  age = 30;
  String something;
  public String child() {
      return this.child.toString();
  }
  Person2 child;
}
"""
    type_name = code_ts.get_field_type_name(typedef, "child")
    assert type_name == "Person2"


def test_get_method_return_type(java_challenge_task_readonly: ChallengeTask):
    """Test getting the return type of a method of a type definition."""
    code_ts = CodeTS(java_challenge_task_readonly)
    typedef = b"""class Person {
        int getName = 40;
        public SuperClass getname() {
            int getName = 1;
            return new SuperClass(getName);
        }
        public String getName() {
            return "John";
        }
    }
    """
    type_name = code_ts.get_method_return_type_name(typedef, "getName")
    assert type_name == "String"

    typedef = b"""public interface LoggerRepository {

    /**
     * Add a {@link HierarchyEventListener} event to the repository.
     *
     * @param listener The listener
     */
    void addHierarchyEventListener(HierarchyEventListener listener);

    /**
     * Returns whether this repository is disabled for a given
     * level. The answer depends on the repository threshold and the
     * <code>level</code> parameter. See also {@link #setThreshold}
     * method.
     *
     * @param level The level
     * @return whether this repository is disabled.
     */
    boolean isDisabled(int level);

    /**
     * Set the repository-wide threshold. All logging requests below the
     * threshold are immediately dropped. By default, the threshold is
     * set to <code>Level.ALL</code> which has the lowest possible rank.
     *
     * @param level The level
     */
    void setThreshold(Level level);

    /**
     * Another form of {@link #setThreshold(Level)} accepting a string
     * parameter instead of a <code>Level</code>.
     *
     * @param val The threshold value
     */
    void setThreshold(String val);

    void emitNoAppenderWarning(Category cat);

    /**
     * Get the repository-wide threshold. See {@link #setThreshold(Level)} for an explanation.
     *
     * @return the level.
     */
    Level getThreshold();

    Logger getLogger(String name);

    Logger getLogger(String name, LoggerFactory factory);

    Logger getRootLogger();

    Logger exists(String name);

    void shutdown();

    @SuppressWarnings("rawtypes")
    Enumeration getCurrentLoggers();

    /**
     * Deprecated. Please use {@link #getCurrentLoggers} instead.
     *
     * @return an enumeration of loggers.
     */
    @SuppressWarnings("rawtypes")
    Enumeration getCurrentCategories();

    void fireAddAppenderEvent(Category logger, Appender appender);

    void resetConfiguration();
}"""
    type_name = code_ts.get_method_return_type_name(typedef, "getLogger")
    assert type_name == "Logger"
