from unittest.mock import MagicMock, patch

import pytest
import requests

from buttercup.orchestrator.ui.competition_api.models.crs_types import (
    SourceDetail,
    SourceType,
    Task,
    TaskDetail,
    TaskType,
)
from buttercup.orchestrator.ui.competition_api.services import CRSClient


class TestCRSClient:
    """Test cases for the CRSClient class."""

    @pytest.fixture
    def crs_client(self):
        """Create a CRSClient instance for testing."""
        return CRSClient(crs_base_url="http://test-crs:8080", username="test_user", password="test_pass")

    @pytest.fixture
    def crs_client_no_auth(self):
        """Create a CRSClient instance without authentication."""
        return CRSClient(crs_base_url="http://test-crs:8080")

    @pytest.fixture
    def sample_task(self):
        """Create a sample task for testing."""
        return Task(
            message_id="test-message-id",
            message_time=1234567890000,
            tasks=[
                TaskDetail(
                    task_id="test-task-id",
                    deadline=1234567890000 + 3600000,  # 1 hour later
                    focus=".",
                    harnesses_included=True,
                    metadata={"test": "data"},
                    project_name="test-project",
                    source=[SourceDetail(sha256="a" * 64, type=SourceType.repo, url="/files/test-repo.tar.gz")],
                    type=TaskType.full,
                ),
            ],
        )

    @patch("requests.post")
    def test_submit_task_success(self, mock_post, crs_client, sample_task):
        """Test successful task submission."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_post.return_value = mock_response

        result = crs_client.submit_task(sample_task)

        assert result is True

        # Verify request was made correctly
        mock_post.assert_called_once_with(
            "http://test-crs:8080/v1/task/",
            json=sample_task.dict(),
            auth=("test_user", "test_pass"),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("requests.post")
    def test_submit_task_no_auth(self, mock_post, crs_client_no_auth, sample_task):
        """Test task submission without authentication."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_post.return_value = mock_response

        result = crs_client_no_auth.submit_task(sample_task)

        assert result is True

        # Verify request was made without auth
        mock_post.assert_called_once_with(
            "http://test-crs:8080/v1/task/",
            json=sample_task.dict(),
            auth=None,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    @patch("requests.post")
    def test_submit_task_failure_status(self, mock_post, crs_client, sample_task):
        """Test task submission with failure status code."""
        # Mock failed response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        result = crs_client.submit_task(sample_task)

        assert result is False

    @patch("requests.post")
    def test_submit_task_exception(self, mock_post, crs_client, sample_task):
        """Test task submission with exception."""
        # Mock exception
        mock_post.side_effect = requests.RequestException("Network error")

        result = crs_client.submit_task(sample_task)

        assert result is False

    @patch("requests.get")
    def test_ping_success_ready(self, mock_get, crs_client):
        """Test successful ping with CRS ready."""
        # Mock successful response with ready=True
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ready": True}
        mock_get.return_value = mock_response

        result = crs_client.ping()

        assert result is True

        # Verify request was made correctly
        mock_get.assert_called_once_with("http://test-crs:8080/status/", auth=("test_user", "test_pass"), timeout=10)

    @patch("requests.get")
    def test_ping_success_not_ready(self, mock_get, crs_client):
        """Test successful ping with CRS not ready."""
        # Mock successful response with ready=False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ready": False}
        mock_get.return_value = mock_response

        result = crs_client.ping()

        assert result is False

    @patch("requests.get")
    def test_ping_no_auth(self, mock_get, crs_client_no_auth):
        """Test ping without authentication."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ready": True}
        mock_get.return_value = mock_response

        result = crs_client_no_auth.ping()

        assert result is True

        # Verify request was made without auth
        mock_get.assert_called_once_with("http://test-crs:8080/status/", auth=None, timeout=10)

    @patch("requests.get")
    def test_ping_failure_status(self, mock_get, crs_client):
        """Test ping with failure status code."""
        # Mock failed response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response

        result = crs_client.ping()

        assert result is False

    @patch("requests.get")
    def test_ping_exception(self, mock_get, crs_client):
        """Test ping with exception."""
        # Mock exception
        mock_get.side_effect = requests.RequestException("Network error")

        result = crs_client.ping()

        assert result is False

    def test_crs_base_url_stripping(self):
        """Test that CRS base URL is properly stripped of trailing slashes."""
        client = CRSClient("http://test-crs:8080/")
        assert client.crs_base_url == "http://test-crs:8080"

        client = CRSClient("http://test-crs:8080")
        assert client.crs_base_url == "http://test-crs:8080"

    def test_authentication_handling(self):
        """Test authentication parameter handling."""
        # With both username and password
        client = CRSClient("http://test-crs:8080", "user", "pass")
        assert client.username == "user"
        assert client.password == "pass"

        # With only username
        client = CRSClient("http://test-crs:8080", "user")
        assert client.username == "user"
        assert client.password is None

        # With only password
        client = CRSClient("http://test-crs:8080", password="pass")
        assert client.username is None
        assert client.password == "pass"

        # Without authentication
        client = CRSClient("http://test-crs:8080")
        assert client.username is None
        assert client.password is None
