"""CodeQuery primitives testing"""

import pytest
from unittest.mock import patch
from pathlib import Path
import shutil
import subprocess

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery, CodeQueryPersistent
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.utils.common import TypeDefinitionType


def setup_c_dirs(tmp_path: Path) -> Path:
    """Create a mock c challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create a mock project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_c_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("language: c\n")

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.c").write_text("int main() { return 0; }")
    (source / "test2.c").write_text("""int function2(int a, int b) {
    int c = a + b;
    return c;
}
""")
    (source / "test3.c").write_text("""int function3(int a, int b) {
    int c = a + b;
    return c;
}

int function4(char *s) {
onftest import libjpeg_oss_fuzz_task
from .c    return strlen(s);
}
""")
    (source / "test4.c").write_text("""typedef int myInt;
myInt function5(myInt a, myInt b) {
    typedef int myOtherInt;
    myOtherInt c = a + b;
    return a + b + c;
}
""")

    # Create task metadata
    TaskMeta(
        project_name="example_c_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={
            "task_id": "task-id-challenge-task",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def task_c_dir(tmp_path: Path) -> Path:
    return setup_c_dirs(tmp_path / "task_rw")


@pytest.fixture
def task_c_dir_ro(tmp_path: Path) -> Path:
    return setup_c_dirs(tmp_path / "task_ro")


@pytest.fixture
def mock_c_challenge_task(task_c_dir: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_c_dir, local_task_dir=task_c_dir)


@pytest.fixture
def mock_c_challenge_task_ro(task_c_dir_ro: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_c_dir_ro, local_task_dir=task_c_dir_ro)


original_subprocess_run = subprocess.run


def mock_docker_run(challenge_task: ChallengeTask):
    def wrapped(args, *rest, **kwargs):
        if args[0] == "docker":
            # Mock docker cp command by copying source path to container src dir
            if args[1] == "cp":
                container_dst_dir = Path(args[3]) / "src" / "my-source"
                container_dst_dir.mkdir(parents=True, exist_ok=True)
                # Copy source files to container src dir
                src_path = challenge_task.get_source_path()
                shutil.copytree(src_path, container_dst_dir, dirs_exist_ok=True)
            elif args[1] == "create":
                pass
            elif args[1] == "rm":
                pass

            return subprocess.CompletedProcess(args, returncode=0)
        return original_subprocess_run(args, *rest, **kwargs)

    return wrapped


def test_get_functions_simple(mock_c_challenge_task: ChallengeTask):
    """Test that we can get the main function"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)

    main_functions = codequery.get_functions("main")
    assert len(main_functions) == 1
    assert main_functions[0].name == "main"
    assert len(main_functions[0].bodies) == 1
    assert main_functions[0].bodies[0].body == "int main() { return 0; }"
    assert main_functions[0].file_path == Path("/src/my-source/test.c")


@pytest.mark.parametrize(
    "file_path,name,full_file_path,n_bodies,body",
    [
        (
            Path("test.c"),
            "main",
            Path("/src/my-source/test.c"),
            1,
            "int main() { return 0; }",
        ),
        (
            Path("test2.c"),
            "function2",
            Path("/src/my-source/test2.c"),
            1,
            "int function2(int a, int b) {\n    int c = a + b;\n    return c;\n}",
        ),
    ],
)
def test_get_functions_file(
    mock_c_challenge_task: ChallengeTask,
    file_path: Path,
    name: str,
    full_file_path: Path,
    n_bodies: int,
    body: str,
):
    """Test that we can get the main function from a specific file"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)

    functions = codequery.get_functions(name, file_path)
    assert len(functions) == 1
    assert functions[0].name == name
    assert functions[0].file_path == full_file_path
    assert len(functions[0].bodies) == n_bodies
    assert functions[0].bodies[0].body == body


def test_get_functions_multiple(mock_c_challenge_task: ChallengeTask):
    """Test that we can get multiple functions from a file"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)
    function3 = codequery.get_functions("function3", Path("test3.c"))
    assert len(function3) == 1
    assert function3[0].name == "function3"
    assert (
        function3[0].bodies[0].body
        == "int function3(int a, int b) {\n    int c = a + b;\n    return c;\n}"
    )

    function4 = codequery.get_functions("function4", Path("test3.c"))
    assert len(function4) == 1
    assert function4[0].name == "function4"
    assert (
        function4[0].bodies[0].body
        == "int function4(char *s) {\nonftest import libjpeg_oss_fuzz_task\nfrom .c    return strlen(s);\n}"
    )


def test_get_functions_fuzzy(mock_c_challenge_task: ChallengeTask):
    """Test that we can get functions (fuzzy search) in codebase"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)
    functions = codequery.get_functions("function", fuzzy=True)
    assert len(functions) == 4
    functions = codequery.get_functions("function", Path("test3.c"), fuzzy=True)
    assert len(functions) == 0
    functions = codequery.get_functions("function3", Path("test3.c"), fuzzy=True)
    assert len(functions) == 1


def test_keep_status(
    mock_c_challenge_task: ChallengeTask,
    mock_c_challenge_task_ro: ChallengeTask,
    tmp_path: Path,
):
    """Test that we can access the same db from different instances"""
    wdir = tmp_path
    wdir.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQueryPersistent(mock_c_challenge_task, work_dir=wdir)
    assert codequery.get_functions("main")
    assert mock_c_challenge_task.task_dir.exists()

    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task_ro)):
        codequery2 = CodeQueryPersistent(mock_c_challenge_task_ro, work_dir=wdir)
    assert codequery2.get_functions("main")
    assert codequery2.challenge.task_dir == codequery.challenge.task_dir
    assert mock_c_challenge_task.task_dir.exists()
    assert mock_c_challenge_task_ro.task_dir.exists()

    with mock_c_challenge_task_ro.get_rw_copy(
        mock_c_challenge_task_ro.task_dir.parent
    ) as nd_challenge:
        with patch("subprocess.run", side_effect=mock_docker_run(nd_challenge)):
            codequery3 = CodeQueryPersistent(nd_challenge, work_dir=wdir)
        assert codequery3.get_functions("main")
        assert codequery3.challenge.task_dir == codequery.challenge.task_dir
        assert mock_c_challenge_task.task_dir.exists()
        assert mock_c_challenge_task_ro.task_dir.exists()

    with mock_c_challenge_task.get_rw_copy(
        mock_c_challenge_task.task_dir.parent
    ) as nd_challenge:
        with patch("subprocess.run", side_effect=mock_docker_run(nd_challenge)):
            codequery4 = CodeQueryPersistent(nd_challenge, work_dir=wdir)
        assert codequery4.get_functions("main")
        assert codequery4.challenge.task_dir == codequery.challenge.task_dir
        assert mock_c_challenge_task.task_dir.exists()
        assert mock_c_challenge_task_ro.task_dir.exists()


def test_get_types(mock_c_challenge_task: ChallengeTask):
    """Test that we can get types in codebase"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)
    types = codequery.get_types("myInt", Path("test3.c"))
    assert len(types) == 0
    types = codequery.get_types("myInt")
    assert len(types) == 1
    types = codequery.get_types("myInt", Path("test4.c"))
    assert len(types) == 1
    assert types[0].name == "myInt"
    assert types[0].type == TypeDefinitionType.TYPEDEF
    assert types[0].definition == "typedef int myInt;"
    assert types[0].definition_line == 1
    types = codequery.get_types("myInt", Path("test4.c"), function_name="function5")
    assert len(types) == 0
    types = codequery.get_types(
        "myOtherInt", Path("test4.c"), function_name="function5"
    )
    assert len(types) == 1
    assert types[0].name == "myOtherInt"
    assert types[0].type == TypeDefinitionType.TYPEDEF
    assert types[0].definition == "    typedef int myOtherInt;"
    assert types[0].definition_line == 3


def test_get_types_fuzzy(mock_c_challenge_task: ChallengeTask):
    """Test that we can get types (fuzzy search) in codebase"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_c_challenge_task)):
        codequery = CodeQuery(mock_c_challenge_task)
    types = codequery.get_types("my", Path("test4.c"), fuzzy=True)
    assert len(types) == 0
    types = codequery.get_types("myInt", Path("test4.c"), fuzzy=True)
    assert len(types) == 1
    types = codequery.get_types("myOtherInt", Path("test4.c"), fuzzy=True)
    assert len(types) == 1
    types = codequery.get_types("my", fuzzy=True)
    assert len(types) == 0
    types = codequery.get_types("my", fuzzy=True, fuzzy_threshold=10)
    assert len(types) == 2
    types = codequery.get_types("myOtherInt", Path("test4.c"), "function5", fuzzy=True)
    assert len(types) == 1


@pytest.mark.integration
def test_libjpeg_indexing(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test that we can index libjpeg"""
    codequery = CodeQuery(libjpeg_oss_fuzz_task)
    functions = codequery.get_functions("jpeg_read_header")
    assert len(functions) == 3
    assert functions[0].name == "jpeg_read_header"

    parse_switches = codequery.get_functions("parse_switches")
    assert len(parse_switches) == 9

    parse_switches.sort(key=lambda x: x.file_path)

    assert parse_switches[0].file_path == Path("/src/libjpeg-turbo/cjpeg.c")
    assert parse_switches[0].file_path.name == "cjpeg.c"
    assert len(parse_switches[0].bodies) == 1
    assert (
        "parse_switches(j_compress_ptr cinfo, int argc, char **argv,"
        in parse_switches[0].bodies[0].body
    )

    assert parse_switches[1].file_path.name == "djpeg.c"
    assert parse_switches[1].name == "parse_switches"
    assert len(parse_switches[1].bodies) == 1
    assert "/* Parse optional switches." in parse_switches[1].bodies[0].body
    assert (
        """LOCAL(int)
parse_switches(j_decompress_ptr cinfo, int argc, char **argv,
               int last_file_arg_seen, boolean for_real)
"""
        in parse_switches[1].bodies[0].body
    )
    assert (
        '    } else if (keymatch(arg, "crop", 2)) {' in parse_switches[1].bodies[0].body
    )
    assert (
        "return argn;                  /* return index of next arg (file name) */"
        in parse_switches[1].bodies[0].body
    )

    assert parse_switches[2].file_path.name == "jpegtran.c"
    assert len(parse_switches[2].bodies) == 1
    assert (
        "parse_switches(j_compress_ptr cinfo, int argc, char **argv,"
        in parse_switches[2].bodies[0].body
    )


@pytest.mark.integration
def test_selinux_indexing(selinux_oss_fuzz_task: ChallengeTask):
    """Test that we can index selinux and files inside oss-fuzz repo"""
    codequery = CodeQuery(selinux_oss_fuzz_task)
    functions = codequery.get_functions("mls_semantic_level_expand")
    assert len(functions) == 1
    assert functions[0].name == "mls_semantic_level_expand"
    assert functions[0].file_path == Path("/src/selinux/libsepol/src/expand.c")
    assert len(functions[0].bodies) == 1
    assert (
        """cat->low > 0 ? p->p_cat_val_to_name[cat->low - 1] : "Invalid","""
        in functions[0].bodies[0].body
    )


def setup_java_dirs(tmp_path: Path) -> Path:
    """Create a mock java challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create a mock project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_java_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("language: jvm\n")

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.java").write_text("""public class Test {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
""")
    (source / "test2.java").write_text("""public class Test2 {
    public static int add(int a, int b) {
        return a + b;
    }

    public static void main(String[] args) {
        int sum = add(5, 3);
        System.out.println("The sum is: " + sum);
    }
}
""")
    (source / "test3.java").write_text("""class MyStruct {
    public int id;
    public String name;
    public double value;

    public MyStruct(int id, String name, double value) {
        this.id = id;
        this.name = name;
        this.value = value;
    }
}

public class Test3 {
    public static void main(String[] args) {
        MyStruct data = new MyStruct(1, "Example", 3.14);
        System.out.println("MyStruct: " + data.id + ", " + data.name + ", " + data.value);
    }
}
""")

    # Create task metadata
    TaskMeta(
        project_name="example_java_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={
            "task_id": "task-id-challenge-task",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def task_java_dir(tmp_path: Path) -> Path:
    return setup_java_dirs(tmp_path / "task_rw")


@pytest.fixture
def task_java_dir_ro(tmp_path: Path) -> Path:
    return setup_java_dirs(tmp_path / "task_ro")


@pytest.fixture
def mock_java_challenge_task(task_java_dir: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_java_dir, local_task_dir=task_java_dir)


@pytest.fixture
def mock_java_challenge_task_ro(task_java_dir_ro: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_java_dir_ro, local_task_dir=task_java_dir_ro)


def test_get_functions_java(mock_java_challenge_task: ChallengeTask):
    """Test that we can get the main function"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_java_challenge_task)):
        codequery = CodeQuery(mock_java_challenge_task)
    main_functions = codequery.get_functions("main")
    assert len(main_functions) == 3
    main_functions.sort(key=lambda x: x.file_path)
    assert main_functions[0].file_path == Path("/src/my-source/test.java")
    assert main_functions[0].name == "main"
    assert len(main_functions[0].bodies) == 1
    assert (
        main_functions[0].bodies[0].body
        == '    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }'
    )
    assert main_functions[1].name == "main"
    assert len(main_functions[1].bodies) == 1
    assert (
        main_functions[1].bodies[0].body
        == '    public static void main(String[] args) {\n        int sum = add(5, 3);\n        System.out.println("The sum is: " + sum);\n    }'
    )
    assert main_functions[2].name == "main"
    assert len(main_functions[2].bodies) == 1
    assert (
        main_functions[2].bodies[0].body
        == '    public static void main(String[] args) {\n        MyStruct data = new MyStruct(1, "Example", 3.14);\n        System.out.println("MyStruct: " + data.id + ", " + data.name + ", " + data.value);\n    }'
    )


def test_get_types_java(mock_java_challenge_task: ChallengeTask):
    """Test that we can get types in codebase"""
    with patch("subprocess.run", side_effect=mock_docker_run(mock_java_challenge_task)):
        codequery = CodeQuery(mock_java_challenge_task)
    types = codequery.get_types("MyStruct", Path("test2.java"))
    assert len(types) == 0
    types = codequery.get_types("MyStruct", Path("test3.java"))
    assert len(types) == 1
    assert types[0].name == "MyStruct"
    assert types[0].type == TypeDefinitionType.CLASS
    assert (
        types[0].definition
        == "class MyStruct {\n    public int id;\n    public String name;\n    public double value;\n\n    public MyStruct(int id, String name, double value) {\n        this.id = id;\n        this.name = name;\n        this.value = value;\n    }\n}"
    )
    assert types[0].definition_line == 1


@pytest.mark.integration
def test_antlr4_indexing(antlr4_oss_fuzz_cq: CodeQuery):
    """Test that we can index antlr4 and files inside oss-fuzz repo"""
    functions = antlr4_oss_fuzz_cq.get_functions("fuzzerTestOneInput")
    assert len(functions) == 1
    assert functions[0].name == "fuzzerTestOneInput"
    assert functions[0].file_path == Path("/src/GrammarFuzzer.java")
    assert len(functions[0].bodies) == 1
    assert (
        "LexerInterpreter lexEngine = lg.createLexerInterpreter(CharStreams.fromString(data.consumeRemainingAsString()));"
        in functions[0].bodies[0].body
    )
