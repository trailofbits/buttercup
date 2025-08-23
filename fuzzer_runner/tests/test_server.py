from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from buttercup.fuzzer_runner.server import active_tasks, app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_active_tasks():
    """Clear the global active_tasks state before each test"""
    active_tasks.clear()
    yield
    active_tasks.clear()


def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


def test_run_fuzzer_invalid_paths(client, tmp_path):
    """Test fuzzer endpoint with invalid paths"""
    # Test with non-existent corpus directory
    response = client.post(
        "/fuzz",
        json={
            "corpus_dir": "/non/existent/path",
            "target_path": str(tmp_path / "target"),
            "engine": "libfuzzer",
            "sanitizer": "address",
        },
    )
    assert response.status_code == 400
    assert "Corpus directory does not exist" in response.json()["detail"]

    # Test with non-existent target path
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    response = client.post(
        "/fuzz",
        json={
            "corpus_dir": str(corpus_dir),
            "target_path": "/non/existent/target",
            "engine": "libfuzzer",
            "sanitizer": "address",
        },
    )
    assert response.status_code == 400
    assert "Target path does not exist" in response.json()["detail"]


@patch("buttercup.fuzzer_runner.server.Runner")
def test_run_fuzzer_success(mock_runner_class, client, tmp_path):
    """Test successful fuzzer execution"""
    # Setup mock
    mock_runner = Mock()
    mock_result = Mock()
    mock_result.logs = "test logs"
    mock_result.crashes = []
    mock_result.stats = {}
    mock_result.corpus = []
    mock_result.time_taken = 10.0
    mock_result.command = "test command"
    mock_result.return_code = 0
    mock_runner.run_fuzzer.return_value = mock_result
    mock_runner_class.return_value = mock_runner

    # Create test directories
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    target_path = tmp_path / "target"
    target_path.write_text("fake binary")

    response = client.post(
        "/fuzz",
        json={
            "corpus_dir": str(corpus_dir),
            "target_path": str(target_path),
            "engine": "libfuzzer",
            "sanitizer": "address",
            "timeout": 30,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "task_id" in data

    # Check that the task was created
    task_response = client.get(f"/tasks/{data['task_id']}")
    assert task_response.status_code == 200
    task_data = task_response.json()
    assert task_data["type"] == "fuzz"
    assert task_data["status"] == "completed"


@patch("buttercup.fuzzer_runner.server.Runner")
def test_merge_corpus_success(mock_runner_class, client, tmp_path):
    """Test successful corpus merge"""
    # Setup mock
    mock_runner = Mock()
    mock_runner_class.return_value = mock_runner

    # Create test directories
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    target_path = tmp_path / "target"
    target_path.write_text("fake binary")
    output_dir = tmp_path / "output"

    response = client.post(
        "/merge-corpus",
        json={
            "corpus_dir": str(corpus_dir),
            "target_path": str(target_path),
            "engine": "libfuzzer",
            "sanitizer": "address",
            "output_dir": str(output_dir),
            "timeout": 30,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "task_id" in data

    # Check that the task was created
    task_response = client.get(f"/tasks/{data['task_id']}")
    assert task_response.status_code == 200
    task_data = task_response.json()
    assert task_data["type"] == "merge_corpus"
    assert task_data["status"] == "completed"


def test_get_task_not_found(client):
    """Test getting non-existent task"""
    response = client.get("/tasks/non-existent-task-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_list_tasks_empty(client):
    """Test listing tasks when none exist"""
    response = client.get("/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == {}


def test_list_tasks_with_tasks(client, tmp_path):
    """Test listing tasks when tasks exist"""
    # Create a task first
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    target_path = tmp_path / "target"
    target_path.write_text("fake binary")

    with patch("buttercup.fuzzer_runner.server.Runner"):
        response = client.post(
            "/fuzz",
            json={
                "corpus_dir": str(corpus_dir),
                "target_path": str(target_path),
                "engine": "libfuzzer",
                "sanitizer": "address",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]

        # List tasks
        list_response = client.get("/tasks")
        assert list_response.status_code == 200
        data = list_response.json()
        assert task_id in data["tasks"]
        assert data["tasks"][task_id]["type"] == "fuzz"
        assert data["tasks"][task_id]["status"] == "completed"
