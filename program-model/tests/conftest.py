import logging
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta

from buttercup.program_model.codequery import CodeQuery

logger = logging.getLogger(__name__)

_task_ids = set()
_task_dirs = set()


def register_task_id(task_id):
    """Register a task ID for cleanup."""
    global _task_ids
    logger.info(f"Registering task ID: {task_id}")
    _task_ids.add(task_id)


def register_temp_dir(temp_dir):
    """Register a temp directory for cleanup."""
    global _task_dirs
    logger.info(f"Registering temp directory: {temp_dir}")
    _task_dirs.add(temp_dir)


def is_cleanup_enabled(request) -> bool:
    """Check if the --no-cleanup flag was passed to pytest."""
    return not request.config.getoption("--no-cleanup")


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
    oss_fuzz_branch: str,
    project: str,
    project_url: str,
    project_commit: str,
) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    if not oss_fuzz_dir.exists():
        oss_fuzz_dir.mkdir(parents=True)

        # Clone oss-fuzz repo into temp dir and checkout specific commit
        subprocess.run(
            [
                "git",
                "-C",
                str(oss_fuzz_dir),
                "clone",
                "-b",
                str(oss_fuzz_branch),
                "https://github.com/tob-challenges/oss-fuzz-aixcc.git",
            ],
            check=True,
            capture_output=True,
        )

    source_dir = tmp_path / "src"
    if not source_dir.exists():
        source_dir.mkdir(parents=True)

        # Clone project source code into temp dir
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
    task_id = f"task-id-{oss_fuzz_project}"
    TaskMeta(
        project_name=oss_fuzz_project,
        focus=project,
        task_id=task_id,
        metadata={
            "task_id": task_id,
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(tmp_path)

    # Register task ID and temp directory for cleanup
    register_task_id(task_id)
    register_temp_dir(tmp_path)

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
        "aixcc-afc",
        "antlr4",
        "https://github.com/antlr/antlr4.git",
        "7b53e13ba005b978e2603f3ff81a0cb7cc98f689",
    )


@pytest.fixture(scope="module")
def antlr4_oss_fuzz_cq(antlr4_oss_fuzz_task: ChallengeTask):
    return CodeQuery(antlr4_oss_fuzz_task)


@pytest.fixture(scope="module")
def bc_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "bc-java",
        "aixcc-afc",
        "bc-java",
        "https://github.com/bcgit/bc-java.git",
        "1.72",
    )


@pytest.fixture(scope="module")
def bc_oss_fuzz_cq(bc_oss_fuzz_task: ChallengeTask):
    return CodeQuery(bc_oss_fuzz_task)


@pytest.fixture(scope="module")
def checkstyle_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "checkstyle",
        "aixcc-afc",
        "checkstyle",
        "https://github.com/checkstyle/checkstyle.git",
        "94cd165da31942661301a09561e4b4ad85366c77",
    )


@pytest.fixture(scope="module")
def checkstyle_oss_fuzz_cq(checkstyle_oss_fuzz_task: ChallengeTask):
    return CodeQuery(checkstyle_oss_fuzz_task)


@pytest.fixture(scope="module")
def commons_codec_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "apache-commons-codec",
        "aixcc-afc",
        "commons-codec",
        "https://gitbox.apache.org/repos/asf/commons-codec.git",
        "44e4c4d778c3ab87db09c00e9d1c3260fd42dad5",
    )


@pytest.fixture(scope="module")
def commons_codec_oss_fuzz_cq(commons_codec_oss_fuzz_task: ChallengeTask):
    return CodeQuery(commons_codec_oss_fuzz_task)


@pytest.fixture(scope="module")
def commons_compress_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "apache-commons-compress",
        "challenge-state/cc-full-01",
        "afc-commons-compress",
        "https://github.com/tob-challenges/afc-commons-compress.git",
        "challenges/cc-full-01",
    )


@pytest.fixture(scope="module")
def commons_compress_oss_fuzz_cq(commons_compress_oss_fuzz_task: ChallengeTask):
    return CodeQuery(commons_compress_oss_fuzz_task)


@pytest.fixture(scope="module")
def dropbear_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "dropbear",
        "challenge-state/db-full-01",
        "afc-dropbear",
        "https://github.com/tob-challenges/afc-dropbear.git",
        "challenges/db-full-01",
    )


@pytest.fixture(scope="module")
def dropbear_oss_fuzz_cq(dropbear_oss_fuzz_task: ChallengeTask):
    return CodeQuery(dropbear_oss_fuzz_task)


@pytest.fixture(scope="module")
def freerdp_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "freerdp",
        "challenge-state/fp-full-01",
        "afc-freerdp",
        "https://github.com/tob-challenges/afc-freerdp.git",
        "challenges/fp-full-01",
    )


@pytest.fixture(scope="module")
def freerdp_oss_fuzz_cq(freerdp_oss_fuzz_task: ChallengeTask):
    return CodeQuery(freerdp_oss_fuzz_task)


@pytest.fixture(scope="module")
def graphql_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "graphql-java",
        "aixcc-afc",
        "graphql-java",
        "https://github.com/graphql-java/graphql-java.git",
        "f52305325593dcec70aba9c4a5717b18b6543fa0",
    )


@pytest.fixture(scope="module")
def graphql_oss_fuzz_cq(graphql_oss_fuzz_task: ChallengeTask):
    return CodeQuery(graphql_oss_fuzz_task)


@pytest.fixture(scope="module")
def hdf5_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "hdf5",
        "aixcc-afc",
        "hdf5",
        "https://github.com/HDFGroup/hdf5.git",
        "7bf340440909d468dbb3cf41f0ea0d87f5050cea",
    )


@pytest.fixture(scope="module")
def hdf5_oss_fuzz_cq(hdf5_oss_fuzz_task: ChallengeTask):
    return CodeQuery(hdf5_oss_fuzz_task)


@pytest.fixture(scope="module")
def libjpeg_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libjpeg-turbo",
        "aixcc-afc",
        "libjpeg-turbo",
        "https://github.com/libjpeg-turbo/libjpeg-turbo.git",
        "6d91e950c871103a11bac2f10c63bf998796c719",
    )


@pytest.fixture(scope="module")
def libjpeg_oss_fuzz_cq(libjpeg_oss_fuzz_task: ChallengeTask):
    return CodeQuery(libjpeg_oss_fuzz_task)


@pytest.fixture(scope="module")
def libjpeg_main_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libjpeg-turbo",
        "aixcc-afc",
        "libjpeg-turbo",
        "https://github.com/libjpeg-turbo/libjpeg-turbo.git",
        "main",
    )


@pytest.fixture(scope="module")
def libjpeg_main_oss_fuzz_cq(libjpeg_main_oss_fuzz_task: ChallengeTask):
    return CodeQuery(libjpeg_main_oss_fuzz_task)


@pytest.fixture(scope="module")
def libpng_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libpng",
        "challenge-state/lp-delta-01",
        "example-libpng",
        "https://github.com/tob-challenges/example-libpng.git",
        "challenges/lp-delta-01",
    )


@pytest.fixture(scope="module")
def libpng_oss_fuzz_cq(libpng_oss_fuzz_task: ChallengeTask):
    return CodeQuery(libpng_oss_fuzz_task)


@pytest.fixture(scope="module")
def libxml2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libxml2",
        "challenge-state/lx-full-01",
        "afc-libxml2",
        "https://github.com/tob-challenges/afc-libxml2.git",
        "challenges/lx-full-01",
    )


@pytest.fixture(scope="module")
def libxml2_oss_fuzz_cq(libxml2_oss_fuzz_task: ChallengeTask):
    return CodeQuery(libxml2_oss_fuzz_task)


@pytest.fixture(scope="module")
def log4j2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "log4j2",
        "aixcc-afc",
        "logging-log4j2",
        "https://github.com/apache/logging-log4j2.git",
        "422c385dc9450d4f620a23d84abe2d6a0aa5b9fb",
    )


@pytest.fixture(scope="module")
def log4j2_oss_fuzz_cq(log4j2_oss_fuzz_task: ChallengeTask):
    return CodeQuery(log4j2_oss_fuzz_task)


@pytest.fixture(scope="module")
def selinux_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "selinux",
        "aixcc-afc",
        "selinux",
        "https://github.com/SELinuxProject/selinux.git",
        "054d7f0b4daef9194363a007c84f9bcbec598825",
    )


@pytest.fixture(scope="module")
def selinux_oss_fuzz_cq(selinux_oss_fuzz_task: ChallengeTask):
    return CodeQuery(selinux_oss_fuzz_task)


@pytest.fixture(scope="module")
def sqlite_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "sqlite3",
        "challenge-state/sq-full-01",
        "afc-sqlite3",
        "https://github.com/tob-challenges/afc-sqlite3.git",
        "challenges/sq-full-01",
    )


@pytest.fixture(scope="module")
def sqlite_oss_fuzz_cq(sqlite_oss_fuzz_task: ChallengeTask):
    return CodeQuery(sqlite_oss_fuzz_task)


@pytest.fixture(scope="module")
def zookeeper_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "zookeeper",
        "challenge-state/zk-full-01",
        "afc-zookeeper",
        "https://github.com/tob-challenges/afc-zookeeper.git",
        "challenges/zk-full-01",
    )


@pytest.fixture(scope="module")
def zookeeper_oss_fuzz_cq(zookeeper_oss_fuzz_task: ChallengeTask):
    return CodeQuery(zookeeper_oss_fuzz_task)


@pytest.fixture(scope="module", autouse=True)
def cleanup_module_task_dirs(request):
    """Clean up task directories after each test module."""

    # Yield to allow the test to run
    yield

    # Clean up database if needed
    if is_cleanup_enabled(request):
        global _task_ids
        global _task_dirs

        logger.info(f"Cleaning up task IDs: {_task_ids}")
        logger.info(f"Cleaning up task dirs: {_task_dirs}")

        # Clean up task IDs registered by this module
        _task_ids.clear()

        # Clean up temp directories created by this module
        remove = []
        for dir_path in _task_dirs:
            if dir_path.exists():
                try:
                    shutil.rmtree(dir_path, ignore_errors=True)
                    remove.append(dir_path)
                except Exception as e:
                    logger.error(f"Error cleaning up {dir_path}: {e}")
                    # NOTE(Evan): If it fails, it will try again next time
        _task_dirs.difference_update(remove)
