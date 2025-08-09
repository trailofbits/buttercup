import unittest
from unittest.mock import MagicMock, Mock, patch
from buttercup.orchestrator.task_server.backend import get_status_tasks_state
from buttercup.orchestrator.task_server.models.types import StatusTasksState


class TestBackend(unittest.TestCase):
    @patch("buttercup.orchestrator.task_server.backend.Redis")
    @patch("buttercup.orchestrator.task_server.backend.TaskRegistry")
    def test_get_status_tasks_state(self, mock_task_registry, mock_redis):
        # Create mock tasks
        mock_tasks = [Mock() for _ in range(5)]

        # Setup mock registry
        mock_registry = MagicMock()
        mock_registry.__iter__.return_value = mock_tasks

        # Setup status check methods to return different states for each task:
        # First task cancelled, second task processing, third task successful, fourth task errored, fifth task failed
        mock_registry.is_cancelled.side_effect = [True, False, False, False, False]
        mock_registry.is_expired.side_effect = [False, True, True, True]
        mock_registry.is_successful.side_effect = [True, False, False]
        mock_registry.is_errored.side_effect = [True, False]

        mock_task_registry.return_value = mock_registry

        # Call the function
        result = get_status_tasks_state("redis://localhost:6379")

        # Verify the result
        self.assertIsInstance(result, StatusTasksState)
        self.assertEqual(result.canceled, 1)
        self.assertEqual(result.errored, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.pending, 0)
        self.assertEqual(result.processing, 1)
        self.assertEqual(result.succeeded, 1)
        self.assertEqual(result.waiting, 0)

        # Verify Redis and TaskRegistry were initialized correctly
        mock_redis.from_url.assert_called_once_with("redis://localhost:6379")
        mock_task_registry.assert_called_once()
