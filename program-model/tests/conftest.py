import pytest
import subprocess
import os
from unittest.mock import patch
from buttercup.program_model.api import Graph
from buttercup.program_model.graph import encode_value
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from pathlib import Path


def is_cleanup_enabled(request) -> bool:
    """Check if the --no-cleanup flag was passed to pytest."""
    return not request.config.getoption("--no-cleanup")


def cleanup_graphdb(request, task_id: str):
    """Clean up the JanusGraph database by dropping vertices and edges associated with a specific task ID."""
    if not is_cleanup_enabled(request):
        return

    with Graph(url="ws://localhost:8182/gremlin") as graph:
        # Drop vertices and edges associated with the task ID
        graph.g.V().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()
        graph.g.E().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()


def pytest_addoption(parser):
    parser.addoption(
        "--runintegration",
        action="store_true",
        default=False,
        help="run integration tests",
    )
    parser.addoption(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="do not clean up database before and after tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runintegration"):
        # --runintegration given in cli: do not skip integration tests
        return
    skip_integration = pytest.mark.skip(reason="need --runintegration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def oss_fuzz_task(
    tmp_path: Path,
    oss_fuzz_project: str,
    project: str,
    project_url: str,
    project_commit: str,
) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    if not oss_fuzz_dir.exists():
        oss_fuzz_dir.mkdir(parents=True)

        # Clone real oss-fuzz repo into temp dir
        subprocess.run(
            [
                "git",
                "-C",
                str(oss_fuzz_dir),
                "clone",
                "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
            ],
            check=True,
            capture_output=True,
        )
        # Restore oss-fuzz project directory to specific commit
        subprocess.run(
            [
                "git",
                "-C",
                str(oss_fuzz_dir / "oss-fuzz-aixcc"),
                "checkout",
                "aixcc-afc",
                "--",
                f"projects/{oss_fuzz_project}",
            ],
            check=True,
            capture_output=True,
        )

    source_dir = tmp_path / "src"
    if not source_dir.exists():
        source_dir.mkdir(parents=True)

        # Download project source code
        subprocess.run(
            ["git", "-C", str(source_dir), "clone", project_url],
            check=True,
            capture_output=True,
        )
        # Checkout specific project commit for reproducibility
        subprocess.run(
            [
                "git",
                "-C",
                str(source_dir / project),
                "checkout",
                project_commit,
            ],
            check=True,
            capture_output=True,
        )

    # Create task metadata
    TaskMeta(
        project_name=oss_fuzz_project,
        focus=project,
        task_id=f"task-id-{oss_fuzz_project}",
        metadata={
            "task_id": f"task-id-{oss_fuzz_project}",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(tmp_path)

    with patch.dict(os.environ, {"OSS_FUZZ_CONTAINER_ORG": "aixcc-afc"}):
        return ChallengeTask(
            read_only_task_dir=tmp_path,
            local_task_dir=tmp_path,
        )


@pytest.fixture(scope="module")
def antlr4_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "antlr4-java",
        "antlr4",
        "https://github.com/antlr/antlr4",
        "7b53e13ba005b978e2603f3ff81a0cb7cc98f689",
    )


@pytest.fixture(scope="module")
def bc_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "bc-java",
        "bc-java",
        "https://github.com/bcgit/bc-java",
        "8b4326f24738ad6f6ab360089436a8a93c6a5424",
    )


@pytest.fixture(scope="module")
def checkstyle_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "checkstyle",
        "checkstyle",
        "https://github.com/checkstyle/checkstyle",
        "94cd165da31942661301a09561e4b4ad85366c77",
    )


@pytest.fixture(scope="module")
def commons_codec_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "apache-commons-codec",
        "commons-codec",
        "https://gitbox.apache.org/repos/asf/commons-codec",
        "44e4c4d778c3ab87db09c00e9d1c3260fd42dad5",
    )


@pytest.fixture(scope="module")
def freerdp_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "freerdp",
        "FreeRDP",
        "https://github.com/FreeRDP/FreeRDP",
        "81e95e51cabfc2db201991b43c0b861b201e17f2",
    )


@pytest.fixture(scope="module")
def dropbear_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "dropbear",
        "dropbear",
        "https://github.com/mkj/dropbear",
        "16106997d11615e5e2dfe477def062aed7ed0bca",
    )


@pytest.fixture(scope="module")
def graphql_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "graphql-java",
        "graphql-java",
        "https://github.com/graphql-java/graphql-java",
        "f52305325593dcec70aba9c4a5717b18b6543fa0",
    )


@pytest.fixture(scope="module")
def hdf5_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "hdf5",
        "hdf5",
        "https://github.com/HDFGroup/hdf5",
        "966454aac1231da7209ef81c11055d3312181f99",
    )


@pytest.fixture(scope="module")
def libjpeg_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libjpeg-turbo",
        "libjpeg-turbo",
        "https://github.com/libjpeg-turbo/libjpeg-turbo",
        "6d91e950c871103a11bac2f10c63bf998796c719",
    )


@pytest.fixture(scope="module")
def libjpeg_main_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libjpeg-turbo",
        "libjpeg-turbo",
        "https://github.com/libjpeg-turbo/libjpeg-turbo",
        "main",
    )


@pytest.fixture(scope="module")
def libpng_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libpng",
        "libpng",
        "https://github.com/pnggroup/libpng",
        "44f97f08d729fcc77ea5d08e02cd538523dd7157",
    )


@pytest.fixture(scope="module")
def libxml2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libxml2",
        "libxml2",
        "https://gitlab.gnome.org/GNOME/libxml2",
        "1c82bca6bd23d0f0858d7fc228ec3a91fda3e0e2",
    )


@pytest.fixture(scope="module")
def log4j2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "log4j2",
        "logging-log4j2",
        "https://github.com/apache/logging-log4j2",
        "1b544d38c9238a0039a99e296fe93da43b8f7ace",
    )


@pytest.fixture(scope="module")
def selinux_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "selinux",
        "selinux",
        "https://github.com/SELinuxProject/selinux",
        "c35919a703302bd571476f245d856174a1fe1926",
    )


@pytest.fixture(scope="module")
def sqlite_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "sqlite3",
        "sqlite",
        "https://github.com/sqlite/sqlite",
        "5804da02182927dafae24a83bfe4176bb1746118",
    )


@pytest.fixture(scope="module")
def zookeeper_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "zookeeper",
        "zookeeper",
        "https://github.com/apache/zookeeper",
        "b86ccf19cf6c32f7e58e36754b6f3534be567727",
    )
