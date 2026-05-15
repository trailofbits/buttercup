from dataclasses import dataclass
from pathlib import Path

import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta

from buttercup.program_model.api.tree_sitter import CodeTS, TypeDefinitionType


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
        "  - libfuzzer\n",
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
def task_dir_cpp(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    base_path = tmp_path / "task_rw"
    oss_fuzz = base_path / "fuzz-tooling" / "fuzz-tooling"
    source = base_path / "src" / "example_project"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)

    # Create mock project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text(
        "language: cpp\n"
        "sanitizers:\n"
        "  - address\n"
        "  - memory\n"
        "  - undefined\n"
        "architectures:\n"
        "  - x86_64\n"
        "fuzzing_engines:\n"
        "  - afl\n"
        "  - honggfuzz\n"
        "  - libfuzzer\n",
    )

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra" / "helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a test C file (as C++ project) with two functions
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
    (source / "test.cpp").write_text(test_c_content)
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
    (source / "test2.cpp").write_text(test2_c_content)

    test3_cpp_content = """#include <cstdio>

class Calculator {
private:
    int value;

public:
    Calculator(int initial_value = 0) : value(initial_value) {}

    int add(int a, int b) {
        return a + b;
    }

    void setValue(int new_value) {
        value = new_value;
    }

    int getValue() const {
        return value;
    }
};

int main() {
    Calculator calc;
    int result = calc.add(5, 3);
    calc.setValue(result);
    printf("Result: %d\n", calc.getValue());
    return 0;
}
"""
    (source / "test3.cpp").write_text(test3_cpp_content)

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="example_project",
        task_id="task-id-tree-sitter-cpp",
        metadata={
            "task_id": "task-id-tree-sitter-cpp",
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
def cpp_challenge_task_readonly(task_dir_cpp: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir_cpp,
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


def test_get_functions_code_cpp_c_content(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting function C code from a C++ file."""
    code_ts = CodeTS(cpp_challenge_task_readonly)
    functions = code_ts.get_functions(Path("src/example_project/test.cpp"))

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


def test_get_function_multiple_definitions_cpp(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting a function from a C file with multiple definitions."""
    code_ts = CodeTS(cpp_challenge_task_readonly)
    function = code_ts.get_function("add", Path("src/example_project/test2.cpp"))
    assert function is not None
    assert function.name == "add"
    assert function.file_path == Path("src/example_project/test2.cpp")
    assert len(function.bodies) == 2
    assert "#ifdef TEST" in function.bodies[0].body
    assert "int add(int a, int b)" in function.bodies[0].body
    assert "double add(double a, double b)" in function.bodies[1].body
    assert "#else" in function.bodies[1].body
    assert function.bodies[0].start_line == 3
    assert function.bodies[0].end_line == 6
    assert function.bodies[1].start_line == 7
    assert function.bodies[1].end_line == 10


def test_get_functions_code_cpp_cpp_content(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting C++ functions and methods from a C++ file."""
    code_ts = CodeTS(cpp_challenge_task_readonly)
    functions = code_ts.get_functions(Path("src/example_project/test3.cpp"))

    # Test that we found the expected functions
    assert "add" in functions
    assert "setValue" in functions
    assert "getValue" in functions
    assert "main" in functions

    # Test the add method
    add_function = functions["add"]
    assert len(add_function.bodies) == 1
    assert "int add(int a, int b)" in add_function.bodies[0].body
    assert "return a + b;" in add_function.bodies[0].body

    # Test the setValue method
    set_value_function = functions["setValue"]
    assert len(set_value_function.bodies) == 1
    assert "void setValue(int new_value)" in set_value_function.bodies[0].body
    assert "value = new_value;" in set_value_function.bodies[0].body

    # Test the getValue method
    get_value_function = functions["getValue"]
    assert len(get_value_function.bodies) == 1
    assert "int getValue() const" in get_value_function.bodies[0].body
    assert "return value;" in get_value_function.bodies[0].body

    # Test the main function
    main_function = functions["main"]
    assert len(main_function.bodies) == 1
    assert "int main()" in main_function.bodies[0].body
    assert "Calculator calc;" in main_function.bodies[0].body


def test_get_types_cpp(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting C++ type definitions from a C++ file."""
    code_ts = CodeTS(cpp_challenge_task_readonly)
    types = code_ts.parse_types_in_code(Path("src/example_project/test3.cpp"))

    # Test that we found the Calculator class
    assert "Calculator" in types
    calculator_type = types["Calculator"]
    assert calculator_type.type == TypeDefinitionType.CLASS
    assert "class Calculator" in calculator_type.definition
    assert "int value;" in calculator_type.definition


def test_get_function_cpp(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting a specific C++ function from a file."""
    code_ts = CodeTS(cpp_challenge_task_readonly)
    function = code_ts.get_function("add", Path("src/example_project/test3.cpp"))
    assert function is not None
    assert function.name == "add"
    assert function.file_path == Path("src/example_project/test3.cpp")
    assert len(function.bodies) == 1
    assert "int add(int a, int b)" in function.bodies[0].body
    assert "return a + b;" in function.bodies[0].body


def test_get_functions_cpp_with_struct(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting functions from a C++ file with struct definitions."""
    # Create a test file with struct
    test_struct_content = """#include <iostream>

struct Point {
    int x;
    int y;

    Point(int x, int y) : x(x), y(y) {}

    int getX() const {
        return x;
    }

    void setX(int new_x) {
        x = new_x;
    }
};

int distance(Point p1, Point p2) {
    return (p1.getX() - p2.getX()) * (p1.getX() - p2.getX());
}
"""

    # Write the test file
    test_file_path = cpp_challenge_task_readonly.task_dir / "src" / "example_project" / "test_struct.cpp"
    test_file_path.write_text(test_struct_content)

    code_ts = CodeTS(cpp_challenge_task_readonly)
    functions = code_ts.get_functions(Path("src/example_project/test_struct.cpp"))

    # Test that we found the expected functions
    assert "getX" in functions
    assert "setX" in functions
    assert "distance" in functions

    # Test the getX method
    get_x_function = functions["getX"]
    assert len(get_x_function.bodies) == 1
    assert "int getX() const" in get_x_function.bodies[0].body
    assert "return x;" in get_x_function.bodies[0].body

    # Test the setX method
    set_x_function = functions["setX"]
    assert len(set_x_function.bodies) == 1
    assert "void setX(int new_x)" in set_x_function.bodies[0].body
    assert "x = new_x;" in set_x_function.bodies[0].body

    # Test the distance function
    distance_function = functions["distance"]
    assert len(distance_function.bodies) == 1
    assert "int distance(Point p1, Point p2)" in distance_function.bodies[0].body
    assert "return (p1.getX() - p2.getX())" in distance_function.bodies[0].body


def test_get_types_cpp_with_struct(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting type definitions from a C++ file with struct."""
    # Create a test file with struct
    test_struct_content = """#include <iostream>

struct Point {
    int x;
    int y;
};

class Rectangle {
    Point topLeft;
    Point bottomRight;
};
"""

    # Write the test file
    test_file_path = cpp_challenge_task_readonly.task_dir / "src" / "example_project" / "test_types.cpp"
    test_file_path.write_text(test_struct_content)

    code_ts = CodeTS(cpp_challenge_task_readonly)
    types = code_ts.parse_types_in_code(Path("src/example_project/test_types.cpp"))

    # Test that we found the expected types
    assert "Point" in types
    assert "Rectangle" in types

    # Test the Point struct
    point_type = types["Point"]
    assert point_type.type == TypeDefinitionType.STRUCT
    assert "struct Point" in point_type.definition
    assert "int x;" in point_type.definition
    assert "int y;" in point_type.definition

    # Test the Rectangle class
    rectangle_type = types["Rectangle"]
    assert rectangle_type.type == TypeDefinitionType.CLASS
    assert "class Rectangle" in rectangle_type.definition
    assert "Point topLeft;" in rectangle_type.definition
    assert "Point bottomRight;" in rectangle_type.definition


def test_get_functions_cpp_qualified_name(cpp_challenge_task_readonly: ChallengeTask):
    """Test getting C++ functions with qualified names (class::method syntax)."""
    # Create a test file with qualified function names
    test_qualified_content = """#include <iostream>

class LibRaw {
public:
    void parse_exif(INT64 base);
};

void LibRaw::parse_exif(INT64 base)
{
    unsigned entries, tag, type, len, c;
    double expo, ape;
    INT64 save;

    // Function implementation
    entries = get2();
    for (c = 0; c < entries; c++) {
        tag = get2();
        type = get2();
        len = get4();
        save = ftell(ifp);

        if (type == 5 && len == 1) {
            expo = getreal(type);
            ape = pow(2, expo);
        }
    }
}

int main() {
    LibRaw raw;
    raw.parse_exif(0);
    return 0;
}
"""

    # Write the test file
    test_file_path = cpp_challenge_task_readonly.task_dir / "src" / "example_project" / "test_qualified.cpp"
    test_file_path.write_text(test_qualified_content)

    code_ts = CodeTS(cpp_challenge_task_readonly)
    functions = code_ts.get_functions(Path("src/example_project/test_qualified.cpp"))

    # Test that we found the expected functions
    assert "parse_exif" in functions
    assert "main" in functions

    # Test the parse_exif function (should capture the implementation, not the declaration)
    parse_exif_function = functions["parse_exif"]
    assert len(parse_exif_function.bodies) == 1
    assert "void LibRaw::parse_exif(INT64 base)" in parse_exif_function.bodies[0].body
    assert "unsigned entries, tag, type, len, c;" in parse_exif_function.bodies[0].body
    assert "entries = get2();" in parse_exif_function.bodies[0].body

    # Test the main function
    main_function = functions["main"]
    assert len(main_function.bodies) == 1
    assert "int main()" in main_function.bodies[0].body
    assert "LibRaw raw;" in main_function.bodies[0].body
