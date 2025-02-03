import pytest
import hashlib
import responses
import tarfile
import io
from pathlib import Path
from buttercup.orchestrator.downloader.downloader import Downloader
from buttercup.common.datastructures.msg_pb2 import Task, SourceDetail


@pytest.fixture
def temp_download_dir(tmp_path):
    return tmp_path / "downloads"


@pytest.fixture
def downloader(temp_download_dir):
    return Downloader(download_dir=temp_download_dir)


@pytest.fixture
def sample_task():
    task = Task()
    task.task_id = "test_task_123"
    source = task.sources.add()
    source.url = "https://example.com/test.txt"
    source.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO
    # Create a simple content and its hash
    content = b"test content"
    source.sha256 = hashlib.sha256(content).hexdigest()
    return task, content


@pytest.fixture
def sample_tar_task():
    task = Task()
    task.task_id = "test_task_456"
    source = task.sources.add()
    source.url = "https://example.com/test.tar.gz"
    source.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO

    # Create a tar file in memory
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        # Add a file to the tar
        file_content = b"test file content"
        file_info = tarfile.TarInfo(name="test_dir/test.txt")
        file_info.size = len(file_content)
        file_data = io.BytesIO(file_content)
        tar.addfile(file_info, file_data)

    tar_content = tar_buffer.getvalue()
    source.sha256 = hashlib.sha256(tar_content).hexdigest()
    return task, tar_content


@responses.activate
def test_download_source_success(downloader, sample_task, tmp_path):
    task, content = sample_task
    source = task.sources[0]

    # Mock the HTTP request
    responses.add(responses.GET, source.url, body=content, status=200)

    # Test the download
    result = downloader.download_source(task.task_id, Path(tmp_path), source)

    assert result is not None
    assert result.exists()
    assert result.read_bytes() == content


@responses.activate
def test_download_source_wrong_hash(downloader, sample_task, tmp_path):
    task, content = sample_task
    source = task.sources[0]
    # Modify the expected hash to cause a mismatch
    source.sha256 = "wrong_hash"

    responses.add(responses.GET, source.url, body=content, status=200)

    result = downloader.download_source(task.task_id, Path(tmp_path), source)
    assert result is None


@responses.activate
def test_download_and_extract_tar(downloader, sample_tar_task):
    task, tar_content = sample_tar_task
    source = task.sources[0]

    responses.add(responses.GET, source.url, body=tar_content, status=200)

    # Test the download and extraction
    success = downloader.process_task(task)
    task_dir = downloader.get_task_dir(task.task_id)

    assert success
    # Check if the extracted file exists in the correct location
    extracted_file = task_dir / "src/test_dir/test.txt"
    assert extracted_file.exists()
    assert extracted_file.read_bytes() == b"test file content"


@responses.activate
def test_process_task_with_multiple_sources(downloader):
    task = Task()
    task.task_id = "multi_source_task"

    # Add two sources
    for i in range(2):
        source = task.sources.add()
        source.url = f"https://example.com/file{i}.tar.gz"
        source.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO

        # Create a tar.gz file in memory
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            content = f"content{i}".encode()
            info = tarfile.TarInfo(name=f"dir{i}/file{i}.txt")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        content = tar_buffer.getvalue()
        source.sha256 = hashlib.sha256(content).hexdigest()

        responses.add(responses.GET, source.url, body=content, status=200)

    success = downloader.process_task(task)
    assert success

    task_dir = downloader.get_task_dir(task.task_id)

    # Verify both files were downloaded
    for i in range(2):
        file_path = task_dir / f"src/dir{i}/file{i}.txt"
        assert file_path.exists()
        assert file_path.read_bytes() == f"content{i}".encode()
