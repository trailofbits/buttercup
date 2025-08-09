import pytest
from typing import Generator
from uuid import uuid4
import time
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from fastapi.encoders import jsonable_encoder
from buttercup.orchestrator.task_server.models.types import (
    Task,
    TaskDetail,
    SourceDetail,
    SourceType,
    TaskType,
)
from buttercup.orchestrator.competition_api_client.models.types_ping_response import TypesPingResponse


# Patch at module level before any other imports
monkeypatch = pytest.MonkeyPatch()
monkeypatch.setattr("buttercup.orchestrator.task_server.config.TaskServerSettings", MagicMock)


class TestSettings:
    """Test settings for authentication"""

    api_key_id: str = "515cc8a0-3019-4c9f-8c1c-72d0b54ae561"
    api_token: str = "VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB"
    api_token_hash: str = (
        "$argon2id$v=19$m=65536,t=3,p=4$Dg1v6NPGTyXPoOPF4ozD5A$wa/85ttk17bBsIASSwdR/uGz5UKN/bZuu4wu+JIy1iA"
    )
    log_level: str = "debug"
    log_max_line_length: int | None = None
    redis_url: str = "redis://localhost:6379"

    # Competition API configuration
    competition_api_url: str = "http://localhost:31323"
    competition_api_username: str = "11111111-1111-1111-1111-111111111111"
    competition_api_password: str = "secret"


settings = TestSettings()
monkeypatch.setattr("buttercup.orchestrator.task_server.dependencies.get_settings", lambda: settings)

from buttercup.orchestrator.task_server.server import app  # noqa: E402
from buttercup.orchestrator.task_server.dependencies import get_task_queue, get_delete_task_queue  # noqa: E402

# Create mock queue and override FastAPI dependency
mock_tasks_queue = MagicMock()
mock_delete_task_queue = MagicMock()
app.dependency_overrides[get_task_queue] = lambda: mock_tasks_queue
app.dependency_overrides[get_delete_task_queue] = lambda: mock_delete_task_queue


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Fixture providing a test client"""
    with TestClient(app) as test_client:
        yield test_client


def test_get_status_unauthorized(client: TestClient) -> None:
    """Test that status endpoint requires authentication"""
    response = client.get("/status/")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


@patch("buttercup.orchestrator.task_server.server.create_api_client")
@patch("time.time")
def test_get_status_authorized(mock_time, mock_create_api_client, client: TestClient) -> None:
    """Test that status endpoint works with valid credentials"""
    # Mock time to return a fixed timestamp
    mock_time.return_value = 1234567890

    # Mock the API client and its response
    mock_api = MagicMock()
    mock_api.v1_ping_get.return_value = TypesPingResponse(status="false")
    mock_create_api_client.return_value = mock_api

    response = client.get("/status/", auth=(settings.api_key_id, settings.api_token))
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
    assert not response.json()["ready"]
    assert response.json()["since"] == 0
    assert response.json()["state"]["tasks"]["canceled"] == 0
    assert response.json()["state"]["tasks"]["errored"] == 0
    assert response.json()["state"]["tasks"]["failed"] == 0
    assert response.json()["state"]["tasks"]["pending"] == 0


def test_post_task_unauthorized(client: TestClient) -> None:
    """Test that task submission requires authentication"""
    task = Task(
        message_id=str(uuid4()),
        message_time=int(time.time()),
        tasks=[
            TaskDetail(
                deadline=int(time.time() + 1000),
                focus="test_focus",
                harnesses_included=True,
                metadata={},
                project_name="test_project",
                source=[SourceDetail(sha256="test_sha256", type=SourceType.SourceTypeRepo, url="test_url")],
                task_id=str(uuid4()),
                type=TaskType.TaskTypeFull,
            )
        ],
    )
    response = client.post("/v1/task/", json=jsonable_encoder(task))
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_post_task_authorized(client: TestClient) -> None:
    """Test that task submission works with valid credentials"""
    task = Task(
        message_id=str(uuid4()),
        message_time=int(time.time()),
        tasks=[
            TaskDetail(
                deadline=int(time.time() + 1000),
                focus="test_focus",
                harnesses_included=True,
                metadata={"key1": "value1", "key2": "123", "key3": "true", "key4": "1.23"},
                project_name="test_project",
                source=[
                    SourceDetail(
                        sha256="ea8fac7c65fb589b0d53560f5251f74f9e9b243478dcb6b3ea79b5e36449c8d9",
                        type=SourceType.SourceTypeRepo,
                        url="https://example.com",
                    ),
                    SourceDetail(
                        sha256="ea8fac7c65fb589b0d53560f5251f74f9e9b243478dcb6b3ea79b5e36449c8d9",
                        type=SourceType.SourceTypeFuzzTooling,
                        url="https://example.com",
                    ),
                ],
                task_id=str(uuid4()),
                type=TaskType.TaskTypeFull,
            )
        ],
    )
    response = client.post("/v1/task/", json=jsonable_encoder(task), auth=(settings.api_key_id, settings.api_token))
    assert response.status_code == 200
    assert response.text == '"DONE"'

    # Verify the task was pushed to the queue
    mock_tasks_queue.push.assert_called_once()

    # Get the task that was pushed to the queue
    task_download = mock_tasks_queue.push.call_args[0][0]
    task_proto = task_download.task

    # Verify metadata was properly converted
    assert len(task_proto.metadata) == 4
    assert task_proto.metadata["key1"] == "value1"
    assert task_proto.metadata["key2"] == "123"
    assert task_proto.metadata["key3"] == "true"
    assert task_proto.metadata["key4"] == "1.23"


def test_delete_task_unauthorized(client: TestClient) -> None:
    """Test that task deletion requires authentication"""
    task_id = uuid4()
    response = client.delete(f"/v1/task/{task_id}/")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_delete_task_authorized(client: TestClient) -> None:
    """Test that task deletion works with valid credentials"""
    task_id = uuid4()
    response = client.delete(f"/v1/task/{task_id}/", auth=(settings.api_key_id, settings.api_token))
    assert response.status_code == 200
    assert response.text == '""'
