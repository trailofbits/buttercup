"""Tests for the program-model REST client."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import httpx

from buttercup.program_model.client import ProgramModelClient, ProgramModelClientError
from buttercup.program_model.rest_client import CodeQueryRest, CodeQueryPersistentRest
from buttercup.program_model.utils.common import (
    Function,
    FunctionBody,
    TypeDefinitionType,
)


@pytest.fixture
def mock_challenge_task():
    """Mock challenge task."""
    mock_task = Mock()
    mock_task.task_meta.task_id = "test-task-123"
    mock_task.task_dir = Path("/test/task/dir")
    return mock_task


class TestProgramModelClient:
    """Test the ProgramModelClient."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return ProgramModelClient(base_url="http://test:8000", timeout=10.0)

    def test_client_initialization(self, client):
        """Test client initialization."""
        assert client.base_url == "http://test:8000"
        assert client.timeout == 10.0

    @patch("httpx.Client.post")
    def test_initialize_task_success(self, mock_post, client):
        """Test successful task initialization."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "test-task-123",
            "status": "initialized",
            "message": "Success",
        }
        mock_post.return_value = mock_response

        result = client.initialize_task("test-task-123", Path("/work/dir"))

        assert result.task_id == "test-task-123"
        assert result.status == "initialized"
        assert result.message == "Success"

    @patch("httpx.Client.post")
    def test_initialize_task_error(self, mock_post, client):
        """Test task initialization error."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "Bad request",
            "detail": "Invalid task",
        }
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request", request=Mock(), response=mock_response
        )
        mock_post.return_value = mock_response

        with pytest.raises(ProgramModelClientError) as exc_info:
            client.initialize_task("test-task-123", Path("/work/dir"))

        assert "Bad request" in str(exc_info.value)

    @patch("httpx.Client.get")
    def test_get_functions_success(self, mock_get, client):
        """Test successful function retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "functions": [
                {
                    "name": "test_function",
                    "file_path": "/src/test.c",
                    "bodies": [
                        {
                            "body": "int test_function() { return 0; }",
                            "start_line": 1,
                            "end_line": 3,
                        }
                    ],
                }
            ],
            "total_count": 1,
        }
        mock_get.return_value = mock_response

        result = client.get_functions("test-task-123", "test_function")

        assert len(result) == 1
        assert result[0].name == "test_function"
        assert result[0].file_path == Path("/src/test.c")
        assert len(result[0].bodies) == 1

    @patch("httpx.Client.get")
    def test_get_callers_success(self, mock_get, client):
        """Test successful caller retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"functions": [], "total_count": 0}
        mock_get.return_value = mock_response

        result = client.get_callers("test-task-123", "test_function")

        assert len(result) == 0

    @patch("httpx.Client.get")
    def test_get_callees_success(self, mock_get, client):
        """Test successful callee retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"functions": [], "total_count": 0}
        mock_get.return_value = mock_response

        result = client.get_callees("test-task-123", "test_function")

        assert len(result) == 0

    @patch("httpx.Client.get")
    def test_get_types_success(self, mock_get, client):
        """Test successful type retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "types": [
                {
                    "name": "test_struct",
                    "type": "struct",
                    "definition": "struct test_struct { int x; };",
                    "definition_line": 5,
                    "file_path": "/src/test.h",
                }
            ],
            "total_count": 1,
        }
        mock_get.return_value = mock_response

        result = client.get_types("test-task-123", "test_struct")

        assert len(result) == 1
        assert result[0].name == "test_struct"
        assert result[0].type == TypeDefinitionType.STRUCT

    def test_context_manager(self):
        """Test client as context manager."""
        with ProgramModelClient() as client:
            assert client is not None


class TestCodeQueryRest:
    """Test the CodeQueryRest class."""

    @pytest.fixture
    def mock_client(self):
        """Mock ProgramModelClient."""
        client = Mock()
        client.get_functions.return_value = [
            Function(
                name="test_function",
                file_path=Path("/src/test.c"),
                bodies=[
                    FunctionBody(
                        body="int test_function() { return 0; }",
                        start_line=1,
                        end_line=3,
                    )
                ],
            )
        ]
        client.get_callers.return_value = []
        client.get_callees.return_value = []
        client.get_types.return_value = []
        client.get_type_calls.return_value = []
        return client

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_codequery_rest_initialization(
        self, mock_client_class, mock_challenge_task, mock_client
    ):
        """Test CodeQueryRest initialization."""
        mock_client_class.return_value = mock_client

        cq = CodeQueryRest(mock_challenge_task)

        assert cq.challenge == mock_challenge_task
        assert cq.task_id == "test-task-123"
        assert cq.client == mock_client

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_get_functions(self, mock_client_class, mock_challenge_task, mock_client):
        """Test get_functions method."""
        mock_client_class.return_value = mock_client

        cq = CodeQueryRest(mock_challenge_task)
        result = cq.get_functions("test_function")

        assert len(result) == 1
        assert result[0].name == "test_function"
        mock_client.get_functions.assert_called_once_with(
            task_id="test-task-123",
            function_name="test_function",
            file_path=None,
            line_number=None,
            fuzzy=False,
            fuzzy_threshold=80,
        )

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_get_callers_with_function_object(
        self, mock_client_class, mock_challenge_task, mock_client
    ):
        """Test get_callers method with Function object."""
        mock_client_class.return_value = mock_client

        cq = CodeQueryRest(mock_challenge_task)
        func = Function(
            name="test_function",
            file_path=Path("/src/test.c"),
            bodies=[],
        )
        result = cq.get_callers(func)

        assert len(result) == 0
        mock_client.get_callers.assert_called_once_with(
            task_id="test-task-123",
            function_name="test_function",
            file_path=Path("/src/test.c"),
        )

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_error_handling(self, mock_client_class, mock_challenge_task, mock_client):
        """Test error handling in CodeQueryRest."""
        mock_client_class.return_value = mock_client
        mock_client.get_functions.side_effect = ProgramModelClientError("Test error")

        cq = CodeQueryRest(mock_challenge_task)
        result = cq.get_functions("test_function")

        # Should return empty list on error
        assert result == []


class TestCodeQueryPersistentRest:
    """Test the CodeQueryPersistentRest class."""

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_initialization_success(self, mock_client_class, mock_challenge_task):
        """Test CodeQueryPersistentRest initialization."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.message = "Initialized successfully"
        mock_client.initialize_task.return_value = mock_response
        mock_client_class.return_value = mock_client

        CodeQueryPersistentRest(mock_challenge_task, Path("/work/dir"))

        mock_client.initialize_task.assert_called_once_with(
            "test-task-123", Path("/work/dir")
        )

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_initialization_error_continues(
        self, mock_client_class, mock_challenge_task
    ):
        """Test CodeQueryPersistentRest continues on initialization error."""
        mock_client = Mock()
        mock_client.initialize_task.side_effect = ProgramModelClientError("Test error")
        mock_client_class.return_value = mock_client

        # Should not raise exception, just log error
        cq = CodeQueryPersistentRest(mock_challenge_task, Path("/work/dir"))

        assert cq.client == mock_client

    @patch("buttercup.program_model.rest_client.ProgramModelClient")
    def test_destructor_cleanup(self, mock_client_class, mock_challenge_task):
        """Test destructor cleanup."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        cq = CodeQueryPersistentRest(mock_challenge_task, Path("/work/dir"))
        del cq

        # Should attempt cleanup, but we can't easily test __del__ calls
