"""Integration tests for the scheduler with background tasks."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from redis import Redis

from buttercup.orchestrator.scheduler.scheduler import Scheduler
from buttercup.orchestrator.scheduler.background_tasks import BackgroundTaskManager
from buttercup.orchestrator.scheduler.scratch_cleaner_task import ScratchCleanerTask
from buttercup.orchestrator.scheduler.pov_reproducer_task import POVReproducerTask
from buttercup.orchestrator.scheduler.corpus_merger_task import CorpusMergerTask


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    with tempfile.TemporaryDirectory() as tasks_dir, \
         tempfile.TemporaryDirectory() as scratch_dir:
        yield Path(tasks_dir), Path(scratch_dir)


@pytest.fixture
def mock_redis():
    """Create a mock Redis instance."""
    return Mock(spec=Redis)


class TestSchedulerWithBackgroundTasks:
    """Test the scheduler with integrated background tasks."""
    
    @patch('buttercup.orchestrator.scheduler.scheduler.QueueFactory')
    @patch('buttercup.orchestrator.scheduler.scheduler.create_api_client')
    @patch('buttercup.orchestrator.scheduler.scheduler.Cancellation')
    @patch('buttercup.orchestrator.scheduler.scheduler.HarnessWeights')
    @patch('buttercup.orchestrator.scheduler.scheduler.BuildMap')
    @patch('buttercup.orchestrator.scheduler.scheduler.TaskRegistry')
    @patch('buttercup.orchestrator.scheduler.scheduler.StatusChecker')
    @patch('buttercup.orchestrator.scheduler.scheduler.Submissions')
    def test_scheduler_initialization_with_background_tasks(
        self,
        mock_submissions,
        mock_status_checker,
        mock_task_registry,
        mock_build_map,
        mock_harness_weights,
        mock_cancellation,
        mock_create_api_client,
        mock_queue_factory,
        mock_redis,
        temp_dirs
    ):
        """Test that scheduler properly initializes background tasks."""
        tasks_dir, scratch_dir = temp_dirs
        
        # Setup mocks
        mock_queue_factory.return_value.create.return_value = Mock()
        mock_create_api_client.return_value = Mock()
        
        # Create scheduler
        scheduler = Scheduler(
            tasks_storage_dir=tasks_dir,
            scratch_dir=scratch_dir,
            redis=mock_redis,
            scratch_cleaner_interval=60.0,
            scratch_cleaner_delta_seconds=1800,
            pov_reproducer_interval=0.1,
            corpus_merger_interval=10.0,
            corpus_merger_timeout=300,
            corpus_merger_max_files=500,
            python_path="python",
        )
        
        # Verify background task manager was created
        assert hasattr(scheduler, 'background_tasks')
        assert isinstance(scheduler.background_tasks, BackgroundTaskManager)
        
        # Verify all three background tasks were added
        assert len(scheduler.background_tasks.tasks) == 3
        
        # Check task names
        task_names = [task.name for task in scheduler.background_tasks.tasks]
        assert "scratch-cleaner" in task_names
        assert "pov-reproducer" in task_names
        assert "corpus-merger" in task_names
    
    def test_health_check(self, mock_redis, temp_dirs):
        """Test the scheduler health check functionality."""
        tasks_dir, scratch_dir = temp_dirs
        
        # Create scheduler without Redis to test unhealthy state
        scheduler = Scheduler(
            tasks_storage_dir=tasks_dir,
            scratch_dir=scratch_dir,
            redis=None,
        )
        
        health = scheduler.health_check()
        assert health["status"] == "unhealthy"
        assert health["components"]["redis"]["status"] == "unhealthy"
    
    @patch('buttercup.orchestrator.scheduler.scheduler.QueueFactory')
    @patch('buttercup.orchestrator.scheduler.scheduler.create_api_client')
    @patch('buttercup.orchestrator.scheduler.scheduler.Cancellation')
    @patch('buttercup.orchestrator.scheduler.scheduler.HarnessWeights')
    @patch('buttercup.orchestrator.scheduler.scheduler.BuildMap')
    @patch('buttercup.orchestrator.scheduler.scheduler.TaskRegistry')
    @patch('buttercup.orchestrator.scheduler.scheduler.StatusChecker')
    @patch('buttercup.orchestrator.scheduler.scheduler.Submissions')
    def test_background_task_status_logging(
        self,
        mock_submissions,
        mock_status_checker,
        mock_task_registry,
        mock_build_map,
        mock_harness_weights,
        mock_cancellation,
        mock_create_api_client,
        mock_queue_factory,
        mock_redis,
        temp_dirs
    ):
        """Test that background task status is logged periodically."""
        tasks_dir, scratch_dir = temp_dirs
        
        # Setup mocks
        mock_queue_factory.return_value.create.return_value = Mock()
        mock_create_api_client.return_value = Mock()
        mock_redis.ping.return_value = True
        
        # Create scheduler
        scheduler = Scheduler(
            tasks_storage_dir=tasks_dir,
            scratch_dir=scratch_dir,
            redis=mock_redis,
        )
        
        # Mock the background tasks
        scheduler.background_tasks = Mock(spec=BackgroundTaskManager)
        scheduler.background_tasks.get_status.return_value = {
            "active_threads": 3,
            "tasks": [
                {
                    "name": "scratch-cleaner",
                    "last_run": "2024-01-01T00:00:00",
                    "success_count": 10,
                    "error_count": 0,
                },
                {
                    "name": "pov-reproducer",
                    "last_run": "2024-01-01T00:00:01",
                    "success_count": 100,
                    "error_count": 1,
                },
                {
                    "name": "corpus-merger",
                    "last_run": "2024-01-01T00:00:02",
                    "success_count": 20,
                    "error_count": 0,
                },
            ]
        }
        
        # Call the logging method
        with patch('buttercup.orchestrator.scheduler.scheduler.logger') as mock_logger:
            scheduler._log_background_task_status()
            
            # Verify logging calls
            assert mock_logger.info.call_count >= 1
            mock_logger.info.assert_any_call("Background tasks status: 3 active threads")


class TestScratchCleanerIntegration:
    """Test the scratch cleaner background task."""
    
    def test_scratch_cleaner_task_creation(self, mock_redis, temp_dirs):
        """Test creating a scratch cleaner task."""
        _, scratch_dir = temp_dirs
        
        task = ScratchCleanerTask(
            redis=mock_redis,
            scratch_dir=scratch_dir,
            interval=60.0,
            delete_old_tasks_delta_seconds=1800,
        )
        
        assert task.name == "scratch-cleaner"
        assert task.interval == 60.0
        assert task.scratch_dir == scratch_dir


class TestPOVReproducerIntegration:
    """Test the POV reproducer background task."""
    
    def test_pov_reproducer_task_creation(self, mock_redis):
        """Test creating a POV reproducer task."""
        task = POVReproducerTask(
            redis=mock_redis,
            interval=0.1,
            max_retries=10,
        )
        
        assert task.name == "pov-reproducer"
        assert task.interval == 0.1
        assert task.max_retries == 10


class TestCorpusMergerIntegration:
    """Test the corpus merger background task."""
    
    def test_corpus_merger_task_creation(
        self,
        mock_redis,
        temp_dirs
    ):
        """Test creating a corpus merger task."""
        _, scratch_dir = temp_dirs
        
        task = CorpusMergerTask(
            redis=mock_redis,
            crs_scratch_dir=str(scratch_dir),
            python="python3",
            interval=10.0,
            timeout_seconds=300,
            max_local_files=500,
        )
        
        assert task.name == "corpus-merger"
        assert task.interval == 10.0
        assert task.crs_scratch_dir == str(scratch_dir)
        assert task.python == "python3"
        assert task.timeout_seconds == 300
        assert task.max_local_files == 500