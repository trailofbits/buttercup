"""Tests for the program-model REST API."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from buttercup.program_model.api.server import app
from buttercup.program_model.utils.common import (
    Function,
    FunctionBody,
    TypeDefinition,
    TypeDefinitionType,
)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_challenge_task():
    """Mock challenge task."""
    mock_task = Mock()
    mock_task.task_meta.task_id = "test-task-123"
    mock_task.task_dir = Path("/test/task/dir")
    return mock_task


@pytest.fixture
def mock_codequery(mock_challenge_task):
    """Mock CodeQueryPersistent instance."""
    mock_cq = Mock()
    mock_cq.challenge = mock_challenge_task
    mock_cq.get_functions.return_value = [
        Function(
            name="test_function",
            file_path=Path("/src/test.c"),
            bodies=[
                FunctionBody(
                    body="int test_function() { return 0; }", start_line=1, end_line=3
                )
            ],
        )
    ]
    mock_cq.get_callers.return_value = []
    mock_cq.get_callees.return_value = []
    mock_cq.get_types.return_value = [
        TypeDefinition(
            name="test_struct",
            type=TypeDefinitionType.STRUCT,
            definition="struct test_struct { int x; };",
            definition_line=5,
            file_path=Path("/src/test.h"),
        )
    ]
    mock_cq.get_type_calls.return_value = []
    return mock_cq


class TestProgramModelAPI:
    """Test the program-model REST API."""

    def test_health_check(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @patch("buttercup.program_model.api.server.ChallengeTask")
    @patch("buttercup.program_model.api.server.CodeQueryPersistent")
    def test_initialize_task_success(
        self,
        mock_codequery_class,
        mock_challenge_class,
        client,
        mock_challenge_task,
        mock_codequery,
    ):
        """Test successful task initialization."""
        mock_challenge_class.return_value = mock_challenge_task
        mock_codequery_class.return_value = mock_codequery

        # Mock Path.exists to return True
        with patch("pathlib.Path.exists", return_value=True):
            request_data = {"task_id": "test-task-123", "work_dir": "/test/work/dir"}

            response = client.post("/tasks/test-task-123/init", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["task_id"] == "test-task-123"
            assert response_data["status"] == "initialized"

    def test_initialize_task_missing_directory(self, client):
        """Test task initialization with missing directory."""
        with patch("pathlib.Path.exists", return_value=False):
            request_data = {"task_id": "test-task-123", "work_dir": "/test/work/dir"}

            response = client.post("/tasks/test-task-123/init", json=request_data)

            assert response.status_code == 400
            assert "does not exist" in response.json()["detail"]

    @patch("buttercup.program_model.api.server.get_codequery")
    def test_search_functions(self, mock_get_codequery, client, mock_codequery):
        """Test function search endpoint."""
        mock_get_codequery.return_value = mock_codequery

        response = client.get(
            "/tasks/test-task-123/functions?function_name=test_function"
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 1
        assert len(response_data["functions"]) == 1
        assert response_data["functions"][0]["name"] == "test_function"

    @patch("buttercup.program_model.api.server.get_codequery")
    def test_get_function_callers(self, mock_get_codequery, client, mock_codequery):
        """Test get function callers endpoint."""
        mock_get_codequery.return_value = mock_codequery

        response = client.get("/tasks/test-task-123/functions/test_function/callers")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 0
        assert len(response_data["functions"]) == 0

    @patch("buttercup.program_model.api.server.get_codequery")
    def test_get_function_callees(self, mock_get_codequery, client, mock_codequery):
        """Test get function callees endpoint."""
        mock_get_codequery.return_value = mock_codequery

        response = client.get("/tasks/test-task-123/functions/test_function/callees")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 0
        assert len(response_data["functions"]) == 0

    @patch("buttercup.program_model.api.server.get_codequery")
    def test_search_types(self, mock_get_codequery, client, mock_codequery):
        """Test type search endpoint."""
        mock_get_codequery.return_value = mock_codequery

        response = client.get("/tasks/test-task-123/types?type_name=test_struct")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 1
        assert len(response_data["types"]) == 1
        assert response_data["types"][0]["name"] == "test_struct"

    @patch("buttercup.program_model.api.server.get_codequery")
    def test_get_type_calls(self, mock_get_codequery, client, mock_codequery):
        """Test get type calls endpoint."""
        mock_get_codequery.return_value = mock_codequery

        response = client.get("/tasks/test-task-123/types/test_struct/calls")

        assert response.status_code == 200
        response_data = response.json()
        assert isinstance(response_data, list)
        assert len(response_data) == 0

    @patch("buttercup.program_model.api.server.get_codequery")
    @patch("buttercup.program_model.api.server.find_libfuzzer_harnesses")
    def test_find_libfuzzer_harnesses(
        self, mock_find_harnesses, mock_get_codequery, client, mock_codequery
    ):
        """Test find libfuzzer harnesses endpoint."""
        mock_get_codequery.return_value = mock_codequery
        mock_find_harnesses.return_value = [
            Path("/src/harness1.c"),
            Path("/src/harness2.c"),
        ]

        response = client.get("/tasks/test-task-123/harnesses/libfuzzer")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 2
        assert len(response_data["harnesses"]) == 2
        assert "/src/harness1.c" in response_data["harnesses"]

    @patch("buttercup.program_model.api.server.get_codequery")
    @patch("buttercup.program_model.api.server.find_jazzer_harnesses")
    def test_find_jazzer_harnesses(
        self, mock_find_harnesses, mock_get_codequery, client, mock_codequery
    ):
        """Test find jazzer harnesses endpoint."""
        mock_get_codequery.return_value = mock_codequery
        mock_find_harnesses.return_value = [Path("/src/HarnessTest.java")]

        response = client.get("/tasks/test-task-123/harnesses/jazzer")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["total_count"] == 1
        assert len(response_data["harnesses"]) == 1
        assert "/src/HarnessTest.java" in response_data["harnesses"]

    @patch("buttercup.program_model.api.server.get_codequery")
    @patch("buttercup.program_model.api.server.get_harness_source")
    def test_get_harness_source(
        self, mock_get_harness_source, mock_get_codequery, client, mock_codequery
    ):
        """Test get harness source endpoint."""
        mock_get_codequery.return_value = mock_codequery

        mock_harness_info = Mock()
        mock_harness_info.file_path = Path("/src/harness.c")
        mock_harness_info.code = "int main() { return 0; }"
        mock_harness_info.harness_name = "test_harness"
        mock_get_harness_source.return_value = mock_harness_info

        response = client.get("/tasks/test-task-123/harnesses/test_harness/source")

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["harness_name"] == "test_harness"
        assert response_data["code"] == "int main() { return 0; }"

    @patch("buttercup.program_model.api.server.get_codequery")
    @patch("buttercup.program_model.api.server.get_harness_source")
    def test_get_harness_source_not_found(
        self, mock_get_harness_source, mock_get_codequery, client, mock_codequery
    ):
        """Test get harness source endpoint when harness not found."""
        mock_get_codequery.return_value = mock_codequery
        mock_get_harness_source.return_value = None

        response = client.get(
            "/tasks/test-task-123/harnesses/nonexistent_harness/source"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_cleanup_task(self, client):
        """Test task cleanup endpoint."""
        # First add a task to cleanup
        with patch(
            "buttercup.program_model.api.server._codequery_instances",
            {"test-task-123": Mock()},
        ):
            response = client.delete("/tasks/test-task-123")

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["status"] == "cleaned_up"
            assert response_data["task_id"] == "test-task-123"

    def test_function_search_with_parameters(self, client):
        """Test function search with various parameters."""
        with patch(
            "buttercup.program_model.api.server.get_codequery"
        ) as mock_get_codequery:
            mock_cq = Mock()
            mock_cq.get_functions.return_value = []
            mock_get_codequery.return_value = mock_cq

            # Test with all parameters
            response = client.get(
                "/tasks/test-task-123/functions?"
                "function_name=test_func&"
                "file_path=/src/test.c&"
                "line_number=10&"
                "fuzzy=true&"
                "fuzzy_threshold=70"
            )

            assert response.status_code == 200
            mock_cq.get_functions.assert_called_once_with(
                function_name="test_func",
                file_path=Path("/src/test.c"),
                line_number=10,
                fuzzy=True,
                fuzzy_threshold=70,
            )

    def test_task_not_initialized_error(self, client):
        """Test error when task is not initialized."""
        response = client.get("/tasks/uninitialized-task/functions?function_name=test")

        assert response.status_code == 404
        assert "not initialized" in response.json()["detail"]
