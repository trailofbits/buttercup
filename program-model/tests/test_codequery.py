"""CodeQuery primitives testing"""

import pytest
import subprocess
from pathlib import Path

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery, CodeQueryPersistent
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.utils.common import TypeDefinitionType


def setup_dirs(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create a mock project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_project" / "project.yaml"
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
    return strlen(s);
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
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return setup_dirs(tmp_path / "task_rw")


@pytest.fixture
def task_dir_ro(tmp_path: Path) -> Path:
    return setup_dirs(tmp_path / "task_ro")


@pytest.fixture
def mock_challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_dir, local_task_dir=task_dir)


@pytest.fixture
def mock_challenge_task_ro(task_dir_ro: Path) -> ChallengeTask:
    """Create a mock challenge task"""
    return ChallengeTask(task_dir_ro, local_task_dir=task_dir_ro)


def test_get_functions_simple(mock_challenge_task: ChallengeTask):
    """Test that we can get the main function"""
    codequery = CodeQuery(mock_challenge_task)
    main_functions = codequery.get_functions("main")
    assert len(main_functions) == 1
    assert main_functions[0].name == "main"
    assert len(main_functions[0].bodies) == 1
    assert main_functions[0].bodies[0].body == "int main() { return 0; }"


def test_get_functions_file(mock_challenge_task: ChallengeTask):
    """Test that we can get the main function from a specific file"""
    codequery = CodeQuery(mock_challenge_task)
    main_functions = codequery.get_functions("main", Path("test.c"))
    assert len(main_functions) == 1
    assert main_functions[0].name == "main"
    assert len(main_functions[0].bodies) == 1
    assert main_functions[0].bodies[0].body == "int main() { return 0; }"


def test_get_functions_multiple(mock_challenge_task: ChallengeTask):
    """Test that we can get multiple functions from a file"""
    codequery = CodeQuery(mock_challenge_task)
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
        == "int function4(char *s) {\n    return strlen(s);\n}"
    )


def test_get_functions_fuzzy(mock_challenge_task: ChallengeTask):
    """Test that we can get functions (fuzzy search) in codebase"""
    codequery = CodeQuery(mock_challenge_task)
    functions = codequery.get_functions("function", fuzzy=True)
    assert len(functions) == 4
    functions = codequery.get_functions("function", Path("test3.c"), fuzzy=True)
    assert len(functions) == 2
    functions = codequery.get_functions("function3", Path("test3.c"), fuzzy=True)
    assert len(functions) == 1


def test_keep_status(
    mock_challenge_task: ChallengeTask,
    mock_challenge_task_ro: ChallengeTask,
    tmp_path: Path,
):
    """Test that we can access the same db from different instances"""
    wdir = tmp_path
    wdir.mkdir(parents=True, exist_ok=True)

    codequery = CodeQueryPersistent(mock_challenge_task, work_dir=wdir)
    assert codequery.get_functions("main")
    assert mock_challenge_task.task_dir.exists()

    codequery2 = CodeQueryPersistent(mock_challenge_task_ro, work_dir=wdir)
    assert codequery2.get_functions("main")
    assert codequery2.challenge.task_dir == codequery.challenge.task_dir
    assert mock_challenge_task.task_dir.exists()
    assert mock_challenge_task_ro.task_dir.exists()

    with mock_challenge_task_ro.get_rw_copy(
        mock_challenge_task_ro.task_dir.parent
    ) as nd_challenge:
        codequery3 = CodeQueryPersistent(nd_challenge, work_dir=wdir)
        assert codequery3.get_functions("main")
        assert codequery3.challenge.task_dir == codequery.challenge.task_dir
        assert mock_challenge_task.task_dir.exists()
        assert mock_challenge_task_ro.task_dir.exists()

    with mock_challenge_task.get_rw_copy(
        mock_challenge_task.task_dir.parent
    ) as nd_challenge:
        codequery4 = CodeQueryPersistent(nd_challenge, work_dir=wdir)
        assert codequery4.get_functions("main")
        assert codequery4.challenge.task_dir == codequery.challenge.task_dir
        assert mock_challenge_task.task_dir.exists()
        assert mock_challenge_task_ro.task_dir.exists()


def test_get_types(mock_challenge_task: ChallengeTask):
    """Test that we can get types in codebase"""
    codequery = CodeQuery(mock_challenge_task)
    types = codequery.get_types("myInt", Path("test3.c"))
    assert len(types) == 0
    types = codequery.get_types("myInt")
    assert len(types) == 1
    types = codequery.get_types("myInt", Path("test4.c"))
    assert len(types) == 1
    assert types[0].name == "myInt"
    assert types[0].type == TypeDefinitionType.TYPEDEF
    assert types[0].definition == "typedef int myInt;"
    assert types[0].definition_line == 0
    types = codequery.get_types("myInt", Path("test4.c"), function_name="function5")
    assert len(types) == 0
    types = codequery.get_types(
        "myOtherInt", Path("test4.c"), function_name="function5"
    )
    assert len(types) == 1
    assert types[0].name == "myOtherInt"
    assert types[0].type == TypeDefinitionType.TYPEDEF
    assert types[0].definition == "    typedef int myOtherInt;"
    assert types[0].definition_line == 2


def test_get_types_fuzzy(mock_challenge_task: ChallengeTask):
    """Test that we can get types (fuzzy search) in codebase"""
    codequery = CodeQuery(mock_challenge_task)
    types = codequery.get_types("my", Path("test4.c"), fuzzy=True)
    assert len(types) == 2
    types = codequery.get_types("myInt", Path("test4.c"), fuzzy=True)
    assert len(types) == 1
    types = codequery.get_types("myOtherInt", Path("test4.c"), fuzzy=True)
    assert len(types) == 1
    types = codequery.get_types("my", fuzzy=True)
    assert len(types) == 2
    types = codequery.get_types("myOtherInt", Path("test4.c"), "function5", fuzzy=True)
    assert len(types) == 1


@pytest.fixture
def libjpeg_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    # Clone real oss-fuzz repo into temp dir
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir),
            "clone",
            "https://github.com/google/oss-fuzz.git",
        ],
        check=True,
    )
    # Restore libjpeg-turbo project directory to specific commit
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz"),
            "checkout",
            "7e664533834b558a859b0f8eb1f2c2caf676c12a",
            "--",
            "projects/libjpeg-turbo",
        ],
        check=True,
    )

    # Download libpng source code
    libjpeg_url = "https://github.com/libjpeg-turbo/libjpeg-turbo"
    # Checkout specific libjpeg commit for reproducibility
    subprocess.run(["git", "-C", str(source_dir), "clone", libjpeg_url], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir / "libjpeg-turbo"),
            "checkout",
            "6d91e950c871103a11bac2f10c63bf998796c719",
        ],
        check=True,
    )

    # Create task metadata
    TaskMeta(
        project_name="libjpeg-turbo",
        focus="libjpeg-turbo",
        task_id="task-id-libjpeg-turbo",
    ).save(tmp_path)

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
    )


@pytest.mark.integration
def test_libjpeg_indexing(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test that we can index libjpeg"""
    codequery = CodeQuery(libjpeg_oss_fuzz_task)
    functions = codequery.get_functions("jpeg_read_header")
    assert len(functions) == 1
    assert functions[0].name == "jpeg_read_header"

    parse_switches = codequery.get_functions("parse_switches")
    assert len(parse_switches) == 3

    parse_switches.sort(key=lambda x: x.file_path)

    assert parse_switches[0].file_path == Path("src/libjpeg-turbo/cjpeg.c")
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


@pytest.fixture
def selinux_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir),
            "clone",
            "https://github.com/google/oss-fuzz.git",
        ],
        check=True,
    )
    # Restore libjpeg-turbo project directory to specific commit
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz"),
            "checkout",
            "ef2f42b3b10af381d3d55cc901fde0729e54573b",
            "--",
            "projects/selinux",
        ],
        check=True,
    )

    # Download selinux source code
    url = "https://github.com/SELinuxProject/selinux"
    subprocess.run(["git", "-C", str(source_dir), "clone", url], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir / "selinux"),
            "checkout",
            "c35919a703302bd571476f245d856174a1fe1926",
        ],
        check=True,
    )

    # Create task metadata
    TaskMeta(project_name="selinux", focus="selinux", task_id="task-id-selinux").save(
        tmp_path
    )

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
    )


@pytest.mark.integration
def test_selinux_indexing(selinux_oss_fuzz_task: ChallengeTask):
    """Test that we can index selinux and files inside oss-fuzz repo"""
    codequery = CodeQuery(selinux_oss_fuzz_task)
    functions = codequery.get_functions("LLVMFuzzerTestOneInput")
    assert len(functions) == 1
    assert functions[0].name == "LLVMFuzzerTestOneInput"
    assert functions[0].file_path == Path(
        "fuzz-tooling/oss-fuzz/projects/selinux/secilc-fuzzer.c"
    )
    assert len(functions[0].bodies) == 1
    assert (
        "if (sepol_policydb_optimize(pdb) != SEPOL_OK)" in functions[0].bodies[0].body
    )
